"""Offer dispatch: OCC on request version, supersede, attempt cap, the ADA
eligibility sub-order, rate-card selection, fiscal gate, and the pinned snapshot."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    create_org,
    create_standard_rate_card,
    create_vri_rate_card,
    create_active_interpreter,
    create_vri_interpreter,
    add_availability,
    create_submitted_request,
    create_submitted_vri_request,
    offer_to,
    get_request,
    get_request_version,
    get_assignment,
    create_offer_payload,
    setup_offered_assignment,
    setup_confirmed_assignment,
    drive_to_checkout,
    verify_encounter,
    file_and_adjudicate,
    setup_completed_encounter,
    assert_instant_equal,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]


def test_occ_stale_request_version_on_offer_rejected():
    """PRD §2.7: "Creating an offer against a request requires the non-optional
    `expected_request_version` field carrying the request `version` the client last
    read; if the request's current `version` has advanced past it — for example
    because a prior offer creation superseded an outstanding offer and bumped the
    version — the create is rejected with `ERR_STALE_REQUEST_VERSION` (HTTP 412),
    so the client cannot dispatch against a matching state it has not observed."

    Design: Corner/cross_cutting_layers/occ_stale_request_version_on_offer_rejected
    """
    ctx = setup_offered_assignment()
    req_id = ctx["request"]["id"]
    interp_id = ctx["interpreter"]["id"]
    stale_version = ctx["request"]["version"] - 1  # version observed before offer #1
    assert stale_version >= 1
    resp = api_client.create_offer(
        req_id, create_offer_payload(interp_id, stale_version), ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_REQUEST_VERSION)
    rows = get_success_data(api_client.list_request_offers(req_id, ADMIN))
    assert len(rows) == 1, "the stale offer must not create or supersede anything"
    assert rows[0]["status"] == "OFFERED"


def test_occ_correct_version_succeeds_and_bumps_version():
    """PRD §3.4: "A successful dispatch creates the assignment in `OFFERED` with its
    `request_id`, `interpreter_id`, an `offered_at` stamp at the current logical
    time, and a `response_deadline` set to the earlier of the scheduled start and
    twenty-four hours after the offer; the request moves to `OFFERED` (or stays
    there on a supersede) with its `version` incremented."
    PRD §3.3: "A new request is a `DRAFT` at `version` 1" and §2.5: "The `version`
    field is an integer that increments by one on every mutation" — create (1),
    submit (2), offer (3).

    Design: Corner/cross_cutting_layers/occ_correct_version_succeeds_and_bumps_version
    """
    set_clock("2026-05-01T00:00:00Z")
    org = create_org()
    create_standard_rate_card()
    interp = create_active_interpreter()
    add_availability(interp["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")
    req = create_submitted_request(org["id"])
    assert req["version"] == 2, f"create + submit must leave version 2, got {req['version']}"
    resp = api_client.create_offer(
        req["id"], create_offer_payload(interp["id"], req["version"]), ADMIN)
    assignment = validate_success(resp, 201)
    assert assignment["status"] == "OFFERED"
    after = get_request(req["id"])
    assert after["version"] == 3, f"offer bumps request version to 3, got {after['version']}"
    assert after["offer_attempt_count"] == 1
    assert after["status"] == "OFFERED"


def test_supersede_cancels_outstanding_offer():
    """PRD §3.4: "When a still-outstanding `OFFERED` assignment exists, creating the
    new offer legitimately supersedes it: the old offer becomes `CANCELLED` by the
    system with no fee, and the request's `version` advances."
    PRD §3.6: "the actor is recorded in `cancelled_by` as one of `REQUESTER`,
    `PLATFORM`, `INTERPRETER`, or `SYSTEM` — requester- and platform-initiated
    cancels take the first two values, while system-driven cancellations (the
    supersede of §3.4 and the suspension cascade of §3.2) take the last."

    Design: Corner/endpoints/supersede_cancels_outstanding_offer
    """
    ctx = setup_offered_assignment()
    req_id = ctx["request"]["id"]
    interp_id = ctx["interpreter"]["id"]
    a1 = ctx["assignment"]
    a2 = offer_to(req_id, interp_id)
    assert a2["status"] == "OFFERED"
    a1_after = get_assignment(a1["id"])
    assert a1_after["status"] == "CANCELLED", "superseded offer is cancelled"
    assert a1_after["cancelled_by"] == "SYSTEM"
    req_after = get_request(req_id)
    assert req_after["offer_attempt_count"] == 2
    assert req_after["status"] == "OFFERED"


def test_third_supersede_offer_rejected_max_attempts():
    """PRD §3.4: "Each request tolerates at most three offer attempts; a successful
    offer increments `offer_attempt_count` by one, and an attempt made when the count
    has already reached three is rejected with `ERR_MAX_OFFER_ATTEMPTS_REACHED`."

    Design: Corner/errors/third_supersede_offer_rejected_max_attempts
    """
    ctx = setup_offered_assignment()
    req_id = ctx["request"]["id"]
    interp_id = ctx["interpreter"]["id"]
    offer_to(req_id, interp_id)        # attempt 2 (supersedes attempt 1)
    a3 = offer_to(req_id, interp_id)   # attempt 3 (supersedes attempt 2)
    assert a3["status"] == "OFFERED"
    resp = api_client.create_offer(
        req_id, create_offer_payload(interp_id, get_request_version(req_id)), ADMIN)
    validate_error(resp, ApiErrorId.ERR_MAX_OFFER_ATTEMPTS_REACHED)
    assert get_assignment(a3["id"])["status"] == "OFFERED", (
        "the counter-exhausted rejection happens before any supersede"
    )


def test_offer_modality_mismatch_returns_modality_not_offered():
    """PRD §3.4: "the request's modality must appear in the interpreter's
    `modalities_offered` (else `ERR_MODALITY_NOT_OFFERED`)".

    Design: Corner/errors/offer_modality_mismatch_returns_modality_not_offered
    """
    set_clock("2026-05-01T00:00:00Z")
    org = create_org()
    create_standard_rate_card(modality="CART_ONSITE", hourly_rate_cents=9500)
    interp = create_active_interpreter(modalities=("ASL_ONSITE",))
    add_availability(interp["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z",
                     modalities=("ASL_ONSITE", "CART_ONSITE"))
    req = create_submitted_request(org["id"], modality="CART_ONSITE")
    resp = api_client.create_offer(
        req["id"], create_offer_payload(interp["id"], get_request_version(req["id"])),
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_MODALITY_NOT_OFFERED)
    after = get_request(req["id"])
    assert after["status"] == "MATCHING" and after["offer_attempt_count"] == 0


def test_offer_vri_without_platform_cert_returns_vri_cert_required():
    """PRD §3.4: "a VRI request additionally requires `vri_platform_certified` to be
    true (else `ERR_VRI_CERTIFICATION_REQUIRED`)".

    Design: Corner/errors/offer_vri_without_platform_cert_returns_vri_cert_required
    """
    set_clock("2026-05-01T00:00:00Z")
    org = create_org(name="State Univ", org_type="EDUCATION")
    create_vri_rate_card()
    interp = create_vri_interpreter(full_name="Vee Uncert", vri_platform_certified=False)
    req = create_submitted_request(
        org["id"], consumer_name="Stu Dent", modality="VRI", ada_context="GENERAL",
        scheduled_start="2026-06-15T10:00:00Z", scheduled_end="2026-06-15T11:00:00Z",
        onsite_address=None, estimated_mileage=0)
    resp = api_client.create_offer(
        req["id"], create_offer_payload(interp["id"], get_request_version(req["id"])),
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_VRI_CERTIFICATION_REQUIRED)


def test_offer_without_matching_rate_card_returns_not_found():
    """PRD §3.4: "among `ACTIVE` cards matching the request's modality, `ada_context`,
    and required credential level whose `effective_from` is not later than the
    current logical time, the card with the latest `effective_from` wins... When no
    card matches, the offer fails with `ERR_RATE_CARD_NOT_FOUND` (HTTP 404)."

    Design: Corner/errors/offer_without_matching_rate_card_returns_not_found
    """
    set_clock("2026-05-01T00:00:00Z")
    org = create_org(name="State Univ", org_type="EDUCATION")
    create_standard_rate_card()  # MEDICAL card only; request is EDUCATION
    interp = create_active_interpreter()
    add_availability(interp["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")
    req = create_submitted_request(
        org["id"], consumer_name="Stu Dent", modality="ASL_ONSITE",
        ada_context="EDUCATION", scheduled_start="2026-06-10T14:00:00Z",
        scheduled_end="2026-06-10T15:00:00Z", onsite_address="1 College Ave",
        estimated_mileage=5)
    resp = api_client.create_offer(
        req["id"], create_offer_payload(interp["id"], get_request_version(req["id"])),
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_RATE_CARD_NOT_FOUND)
    rows = get_success_data(api_client.list_request_offers(req["id"], ADMIN))
    assert rows == [], "no assignment may persist when no rate card matches"


def test_quality_below_threshold_blocks_offer():
    """PRD §3.4: "the interpreter's final `quality_score` must be at least 40 (else
    `ERR_QUALITY_BELOW_THRESHOLD`)".
    PRD §3.9: "The final `quality_score` is 100 minus the summed `penalty_points` of
    the interpreter's `SUBSTANTIATED` complaints, floored at zero." with
    "`penalty_points` is set by severity — five for `MINOR`, fifteen for `MAJOR`,
    thirty for `CRITICAL`" — two CRITICALs and one MAJOR give 100 - 30 - 30 - 15 = 25.

    Design: Corner/validations/quality_below_threshold_blocks_offer
    """
    ctx = setup_completed_encounter()
    interp_id = ctx["interpreter"]["id"]
    file_and_adjudicate(ctx, "SUBSTANTIATED", category="QUALITY", severity="CRITICAL",
                        narrative="c1")
    file_and_adjudicate(ctx, "SUBSTANTIATED", category="PROFESSIONALISM",
                        severity="CRITICAL", narrative="c2")
    file_and_adjudicate(ctx, "SUBSTANTIATED", category="LATENESS", severity="MAJOR",
                        narrative="c3")
    score = get_success_data(api_client.get_interpreter(interp_id, ADMIN))
    assert score["quality_score"] == 25, (
        f"two CRITICAL + one MAJOR substantiated => 25, got {score['quality_score']}"
    )
    req2 = create_submitted_request(
        ctx["org"]["id"], consumer_name="Next Pat",
        scheduled_start="2026-06-20T14:00:00Z", scheduled_end="2026-06-20T15:00:00Z",
        estimated_mileage=5)
    resp = api_client.create_offer(
        req2["id"], create_offer_payload(interp_id, get_request_version(req2["id"])),
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_QUALITY_BELOW_THRESHOLD)
    assert get_success_data(api_client.list_request_offers(req2["id"], ADMIN)) == []


def test_credit_limit_equality_allowed_one_cent_over_rejected():
    """PRD §3.1: "when an offer is created, and again when an assignment is
    confirmed, the platform requires the org's outstanding balance plus the
    assignment's `estimated_cost_cents` to be no more than `credit_limit_cents`.
    Equality is allowed; a sum strictly greater than the limit is rejected with
    `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."
    (The booking's estimate is 26200 cents: 150 billable minutes x 9000/h = 22500
    labor + flat 60 travel minutes at 3000/h = 3000 + 10 miles x 70 = 700.)

    Design: Corner/validations/credit_limit_equality_allowed_one_cent_over_rejected
    """
    set_clock("2026-05-01T00:00:00Z")
    org_exact = create_org(name="Org Exact", credit_limit_cents=26200)
    org_short = create_org(name="Org Short", credit_limit_cents=26199)
    create_standard_rate_card()
    interp = create_active_interpreter()
    add_availability(interp["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")
    req_a = create_submitted_request(
        org_exact["id"], consumer_name="Pat A",
        scheduled_start="2026-06-18T14:00:00Z", scheduled_end="2026-06-18T16:30:00Z")
    req_b = create_submitted_request(
        org_short["id"], consumer_name="Pat B",
        scheduled_start="2026-06-18T14:00:00Z", scheduled_end="2026-06-18T16:30:00Z")
    resp_a = api_client.create_offer(
        req_a["id"], create_offer_payload(interp["id"], get_request_version(req_a["id"])),
        ADMIN)
    asg_a = validate_success(resp_a, 201)
    assert asg_a["estimated_cost_cents"] == 26200, (
        "0 outstanding + 26200 estimate <= 26200 limit: equality allowed"
    )
    resp_b = api_client.create_offer(
        req_b["id"], create_offer_payload(interp["id"], get_request_version(req_b["id"])),
        ADMIN)
    validate_error(resp_b, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)


def test_offer_pins_snapshot_surviving_rate_card_retirement():
    """PRD §3.4: "Cards are born `ACTIVE`; retiring one flips it to `RETIRED`
    (re-retiring is rejected with `ERR_RATE_CARD_ALREADY_RETIRED`), excludes it from
    all future selection, and leaves every snapshot already pinned on an assignment
    untouched." and "Later edits or retirement of the card cannot move a pinned
    assignment."
    PRD §3.7: "The `LABOR` line is always present: its quantity is the encounter's
    `billable_minutes` and its amount is that time at the pinned hourly rate, rounded
    half-up."

    Design: Corner/endpoints/offer_pins_snapshot_surviving_rate_card_retirement
    """
    ctx = setup_confirmed_assignment()
    # Retire the source card after confirm, before service delivery and billing.
    retired = get_success_data(api_client.retire_rate_card(ctx["rate_card"]["id"], ADMIN))
    assert retired["status"] == "RETIRED"
    drive_to_checkout(ctx, checkout_payload={
        "travel_minutes_claimed": 90, "mileage_claimed": 12})
    verify_encounter(ctx)
    invoice = get_success_data(api_client.generate_invoice(
        {"assignment_id": ctx["assignment"]["id"]}, CLERK))
    asg = get_assignment(ctx["assignment"]["id"])
    assert asg["pinned_hourly_rate_cents"] == 9000, "snapshot pinned at offer time"
    assert asg["rate_card_id"] == ctx["rate_card"]["id"]
    # 130 actual minutes at pinned 9000/h + 90 travel min at 3000/h + 12 mi at 70.
    assert invoice["subtotal_cents"] == 24840, (
        f"billing from the pinned snapshot must survive retirement, got {invoice['subtotal_cents']}"
    )
    card_after = get_success_data(api_client.get_rate_card(ctx["rate_card"]["id"], ADMIN))
    assert card_after["status"] == "RETIRED"


def test_vri_estimate_uses_scheduled_minutes_and_skips_travel():
    """PRD §3.4: "The travel estimate is zero for VRI and otherwise a flat sixty
    estimated travel minutes — exactly one hour at the pinned travel rate, rounded
    half-up. The mileage estimate is zero for VRI and otherwise multiplies the
    pinned per-mile rate by the lesser of the request's `estimated_mileage` and the
    200-mile cap, rounded half-up. The platform-fee estimate applies only to VRI and
    multiplies the scheduled minutes by the pinned per-minute platform fee."
    (60 scheduled minutes vs the 30-minute floor -> labor 60 x 4500/60 = 4500;
    platform fee 60 x 15 = 900; travel/mileage forced to zero -> 5400.)
    PRD §3.4: "a `response_deadline` set to the earlier of the scheduled start and
    twenty-four hours after the offer".

    Design: Corner/calculations/vri_estimate_uses_scheduled_minutes_and_skips_travel
    """
    set_clock("2026-05-01T00:00:00Z")
    org = create_org(name="State Univ", org_type="EDUCATION")
    card = create_vri_rate_card()
    interp = create_vri_interpreter()
    req = create_submitted_vri_request(org["id"])
    resp = api_client.create_offer(
        req["id"], create_offer_payload(interp["id"], get_request_version(req["id"])),
        ADMIN)
    asg = validate_success(resp, 201)
    assert asg["estimated_cost_cents"] == 5400, (
        f"VRI estimate 4500 labor + 900 platform, got {asg['estimated_cost_cents']}"
    )
    assert asg["rate_card_id"] == card["id"]
    assert asg["pinned_hourly_rate_cents"] == 4500
    assert asg["pinned_minimum_billable_minutes"] == 30
    assert asg["pinned_vri_platform_fee_cents_per_min"] == 15
    assert_instant_equal(asg["response_deadline"], "2026-05-02T00:00:00Z",
                         "response_deadline = min(scheduled_start, offered_at + 24h)")


def test_retire_twice_returns_already_retired():
    """PRD §3.4: "Cards are born `ACTIVE`; retiring one flips it to `RETIRED`
    (re-retiring is rejected with `ERR_RATE_CARD_ALREADY_RETIRED`), excludes it from
    all future selection, and leaves every snapshot already pinned on an assignment
    untouched."

    Design: Corner/errors/retire_twice_returns_already_retired
    """
    set_clock("2026-05-01T00:00:00Z")
    card = create_vri_rate_card()
    get_success_data(api_client.retire_rate_card(card["id"], ADMIN))
    resp = api_client.retire_rate_card(card["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_RATE_CARD_ALREADY_RETIRED)


# ─── Difficulty: priority_pair_validation_conflict (safety vs fiscal) ──

def _setup_safety_and_fiscal_both_failing():
    """LEGAL request (requires SPECIALIST) + interpreter with only a verified
    SCREENED cert + org credit limit far below the estimate."""
    set_clock("2026-05-01T00:00:00Z")
    org = create_org(name="County Court", org_type="LEGAL", credit_limit_cents=100)
    create_standard_rate_card(
        modality="ASL_ONSITE", ada_context="LEGAL", credential_level="SPECIALIST",
        hourly_rate_cents=12000)
    interp = create_active_interpreter(
        full_name="Sam Screened", credential="STATE_QA", level="SCREENED")
    add_availability(interp["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")
    req = create_submitted_request(
        org["id"], consumer_name="Lee Litigant", modality="ASL_ONSITE",
        ada_context="LEGAL", scheduled_start="2026-06-16T14:00:00Z",
        scheduled_end="2026-06-16T15:00:00Z", onsite_address="1 Court Pl",
        estimated_mileage=0)
    return org, interp, req


def test_offer_safety_error_wins_over_fiscal_error():
    """PRD §2.10: "When several validations could reject the same request, they are
    evaluated in a fixed twelve-tier order, and the earliest failing tier determines
    the error returned." and "Ninth, the ADA credential-and-match gate on dispatch...
    (`ERR_MODALITY_NOT_OFFERED`, `ERR_VRI_CERTIFICATION_REQUIRED`,
    `ERR_CREDENTIAL_INSUFFICIENT`, `ERR_QUALITY_BELOW_THRESHOLD`; HTTP 422). ...
    Twelfth and last, the fiscal gates (`ERR_CREDIT_LIMIT_EXCEEDED`,
    `ERR_PAYMENT_EXCEEDS_AMOUNT_DUE`) — money is checked only after every safety,
    temporal, and structural rule has passed."

    Design: Difficulty/priority_pair_validation_conflict/offer_credential_insufficient_and_over_credit_limit_returns_safety_error
    """
    _org, interp, req = _setup_safety_and_fiscal_both_failing()
    resp = api_client.create_offer(
        req["id"], create_offer_payload(interp["id"], get_request_version(req["id"])),
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_CREDENTIAL_INSUFFICIENT)


def test_offer_safety_failure_creates_no_assignment():
    """PRD §2.10: "Ninth, the ADA credential-and-match gate on dispatch...
    (`ERR_MODALITY_NOT_OFFERED`, `ERR_VRI_CERTIFICATION_REQUIRED`,
    `ERR_CREDENTIAL_INSUFFICIENT`, `ERR_QUALITY_BELOW_THRESHOLD`; HTTP 422)."
    PRD §3.4: "A successful dispatch creates the assignment in `OFFERED`" — a
    rejected dispatch creates nothing and does not consume an attempt ("a successful
    offer increments `offer_attempt_count` by one").

    Design: Difficulty/priority_pair_validation_conflict/offer_credential_insufficient_and_over_credit_limit_returns_safety_error
    """
    _org, interp, req = _setup_safety_and_fiscal_both_failing()
    resp = api_client.create_offer(
        req["id"], create_offer_payload(interp["id"], get_request_version(req["id"])),
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_CREDENTIAL_INSUFFICIENT)
    rows = get_success_data(api_client.list_request_offers(req["id"], ADMIN))
    assert rows == [], "no assignment may be created when eligibility fails"
    after = get_request(req["id"])
    assert after["status"] == "MATCHING"
    assert after["offer_attempt_count"] == 0
