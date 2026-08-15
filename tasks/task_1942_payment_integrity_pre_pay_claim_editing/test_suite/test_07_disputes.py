"""Provider disputes: creation guards (state, referential integrity,
one-open-per-hit, OCC, 45-day window), adjudication guards (SoD, 60-day
deadline, PARTIAL bounds, precedence), and the RFI round trip."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assign_and_decide,
    create_claim_with_lines,
    create_dispute_payload,
    create_upheld_claim,
    decide_dispute_payload,
    drive_hit_resolution,
    get_claim,
    get_hit,
    get_success_data,
    list_claim_hits,
    list_claim_tasks,
    make_adjudicator_headers,
    make_provider_headers,
    open_dispute,
    open_dispute_under_review,
    run_claim_edits,
    set_clock,
    setup_provider_with_active_edit,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["plan_admin_headers"]
ADJUDICATOR = TEST_USERS["adjudicator_headers"]


def test_dispute_create_on_pended_claim_rejected(api):
    """PRD §3.6: "the claim must be in `DETERMINED`, `READY_TO_PAY`, `DENIED`,
    or `PAID` and the hit must be `CONFIRMED`, else `ERR_DISPUTE_NOT_OPEN`
    (HTTP 409)"

    Design: Corner/state_machines/dispute_create_on_pended_claim_rejected
    """
    provider, _rule, _version = setup_provider_with_active_edit(
        npi="NPI-SM5", edit_code="PEND-01")
    ctx = drive_hit_resolution(provider["id"], 30000, "PD1", "M-PD1", "fired")
    claim = ctx["claim"]
    assert claim["status"] == "PENDED"
    assert ctx["hit"]["status"] == "FIRED"

    resp = api.create_dispute(
        claim["id"],
        create_dispute_payload(ctx["hit"]["id"], claim["version"],
                               reason="too early"),
        make_provider_headers(provider["id"]))
    validate_error(resp, ApiErrorId.ERR_DISPUTE_NOT_OPEN, expected_status=409)


def test_dispute_with_hit_from_other_claim_rejected(api):
    """PRD §3.6: "the `edit_hit_id` must actually belong to the claim in the
    path, else `ERR_HIT_NOT_ON_CLAIM` (HTTP 422)."

    Design: Corner/validations/dispute_with_hit_from_other_claim_rejected
    """
    provider, _rule, _version = setup_provider_with_active_edit(
        npi="NPI-XR", edit_code="XR-DENY")
    ctx_a = drive_hit_resolution(provider["id"], 30000, "XRA", "M-XRA",
                                 "uphold")
    ctx_b = drive_hit_resolution(provider["id"], 30000, "XRB", "M-XRB",
                                 "uphold")

    claim_b = get_claim(ctx_b["claim"]["id"])
    resp = api.create_dispute(
        claim_b["id"],
        create_dispute_payload(ctx_a["hit"]["id"], claim_b["version"],
                               reason="wrong claim"),
        make_provider_headers(provider["id"]))
    validate_error(resp, ApiErrorId.ERR_HIT_NOT_ON_CLAIM, expected_status=422)


def test_duplicate_open_dispute_on_same_hit(api):
    """PRD §3.6: "at most one dispute per hit may be open — a second dispute
    on a hit with a non-`DECIDED` dispute is rejected with
    `ERR_DISPUTE_ALREADY_OPEN` (HTTP 409)"

    Design: Corner/validations/duplicate_open_dispute_on_same_hit
    """
    ctx = create_upheld_claim(npi="NPI-DU", edit_code="DUP-DENY", billed=30000)
    first = open_dispute(ctx["provider"]["id"], ctx["claim"]["id"],
                         ctx["hit"]["id"], reason="first")
    assert first["status"] == "SUBMITTED"

    claim_now = get_claim(ctx["claim"]["id"])
    resp = api.create_dispute(
        ctx["claim"]["id"],
        create_dispute_payload(ctx["hit"]["id"], claim_now["version"],
                               reason="second"),
        make_provider_headers(ctx["provider"]["id"]))
    validate_error(resp, ApiErrorId.ERR_DISPUTE_ALREADY_OPEN,
                   expected_status=409)


def test_partial_dispute_release_out_of_range(api):
    """PRD §3.6: "for a `PARTIAL` outcome the supplied `released_cents` must
    be greater than zero and no more than the hit's
    `attributed_savings_cents`, else `ERR_INVALID_RELEASE_AMOUNT`
    (HTTP 422)."

    Design: Corner/validations/partial_dispute_release_out_of_range
    """
    ctx = create_upheld_claim(npi="NPI-RA", edit_code="RA-DENY", billed=60000)
    dispute = open_dispute_under_review(ctx["provider"]["id"],
                                        ctx["claim"]["id"], ctx["hit"]["id"])

    resp_hi = api.decide_dispute(
        dispute["id"],
        decide_dispute_payload("PARTIAL", released_cents=60001), ADJUDICATOR)
    validate_error(resp_hi, ApiErrorId.ERR_INVALID_RELEASE_AMOUNT,
                   expected_status=422)
    resp_zero = api.decide_dispute(
        dispute["id"], decide_dispute_payload("PARTIAL", released_cents=0),
        ADJUDICATOR)
    validate_error(resp_zero, ApiErrorId.ERR_INVALID_RELEASE_AMOUNT,
                   expected_status=422)

    still = get_success_data(api.get_dispute(dispute["id"], ADMIN))
    assert still["status"] == "UNDER_REVIEW"


def test_dispute_window_day45_allowed_day46_expired(api):
    """PRD §3.6: "the dispute must be opened no later than 45 days after the
    claim's `determined_at`, an inclusive boundary where exactly 45 days after
    determination is still admissible, else `ERR_DISPUTE_WINDOW_EXPIRED`
    (HTTP 422)"
    PRD §2.6: "At server startup the logical clock reads exactly
    2026-08-01T00:00:00Z"

    Design: Corner/validations/dispute_window_day45_allowed_day46_expired
    """
    provider, _rule, _version = setup_provider_with_active_edit(
        npi="NPI-WI", edit_code="WIN-DENY")
    ctx_w1 = drive_hit_resolution(provider["id"], 30000, "W1", "M-W1",
                                  "uphold")
    ctx_w2 = drive_hit_resolution(provider["id"], 30000, "W2", "M-W2",
                                  "uphold")
    # Both claims were determined at the default clock 2026-08-01T00:00:00Z.
    assert ctx_w1["claim"]["status"] == "DENIED"
    assert ctx_w2["claim"]["status"] == "DENIED"

    set_clock("2026-09-15T00:00:00Z")  # determined_at + 45 days exactly
    dispute = validate_success(api.create_dispute(
        ctx_w1["claim"]["id"],
        create_dispute_payload(ctx_w1["hit"]["id"],
                               get_claim(ctx_w1["claim"]["id"])["version"],
                               reason="day 45"),
        make_provider_headers(provider["id"])), expected_status=201)
    assert dispute["status"] == "SUBMITTED"

    set_clock("2026-09-16T00:00:00Z")  # determined_at + 46 days
    resp = api.create_dispute(
        ctx_w2["claim"]["id"],
        create_dispute_payload(ctx_w2["hit"]["id"],
                               get_claim(ctx_w2["claim"]["id"])["version"],
                               reason="day 46"),
        make_provider_headers(provider["id"]))
    validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_EXPIRED,
                   expected_status=422)


def test_decision_deadline_passed_pure_temporal(api):
    """PRD §3.6: "the decision must come no later than 60 days after
    `submitted_at`, an inclusive boundary where a decision exactly 60 days
    after submission is on time, else `ERR_DECISION_DEADLINE_PASSED`
    (HTTP 422)"

    Design: Corner/validations/decision_deadline_passed_pure_temporal
    """
    ctx = create_upheld_claim(npi="NPI-DL", edit_code="DL-DENY", billed=30000)
    dispute = open_dispute_under_review(ctx["provider"]["id"],
                                        ctx["claim"]["id"], ctx["hit"]["id"],
                                        reason="slow appeal")
    # Submitted at the default clock 2026-08-01; +61 days is past the deadline.
    set_clock("2026-10-01T00:00:00Z")
    resp = api.decide_dispute(dispute["id"], decide_dispute_payload("UPHELD"),
                              ADJUDICATOR)
    validate_error(resp, ApiErrorId.ERR_DECISION_DEADLINE_PASSED,
                   expected_status=422)
    still = get_success_data(api.get_dispute(dispute["id"], ADMIN))
    assert still["status"] == "UNDER_REVIEW"


def test_sod_reviewer_cannot_adjudicate_own_uphold(api):
    """PRD §2.9: "Dispute adjudication separates confirmation from
    adjudication: the operator who decides a dispute must not be the operator
    recorded as the disputed hit's `confirmed_by_user_id`, and a violation is
    rejected with `ERR_SOD_REVIEWER_ADJUDICATION` (HTTP 403)."

    Design: Corner/validations/sod_reviewer_cannot_adjudicate_own_uphold
    """
    ctx = create_upheld_claim(npi="NPI-SD", edit_code="SOD-DENY", billed=30000,
                              reviewer_id="rev-1")
    assert ctx["hit"]["confirmed_by_user_id"] == "rev-1"
    dispute = open_dispute_under_review(ctx["provider"]["id"],
                                        ctx["claim"]["id"], ctx["hit"]["id"])

    resp = api.decide_dispute(dispute["id"], decide_dispute_payload("OVERTURNED"),
                              make_adjudicator_headers("rev-1"))
    validate_error(resp, ApiErrorId.ERR_SOD_REVIEWER_ADJUDICATION,
                   expected_status=403)
    assert get_hit(ctx["hit"]["id"])["status"] == "CONFIRMED"
    still = get_success_data(api.get_dispute(dispute["id"], ADMIN))
    assert still["status"] == "UNDER_REVIEW"


def test_occ_stale_claim_version_on_dispute_create(api):
    """PRD §2.7: "If `expected_claim_version` does not equal the claim's
    current `version`, the create is rejected with `ERR_STALE_VERSION`
    (HTTP 412) rather than adjudicating against dollar amounts the client
    never saw."
    PRD §3.6: "Creation stamps `submitted_at` — the anchor for the decision
    deadline — and increments the claim's `version` by one."

    Design: Corner/cross_cutting_layers/occ_stale_claim_version_on_dispute_create
    """
    provider, _rule, _version = setup_provider_with_active_edit(
        npi="NPI-OC2", edit_code="OCC-DENY")
    claim = create_claim_with_lines(
        provider["id"], lines=((1, "99213", 30000), (2, "99214", 30000)),
        claim_number="OC2", member_id="M-OC2")
    run_claim_edits(claim["id"])
    tasks = list_claim_tasks(claim["id"])
    assert len(tasks) == 2
    for task in tasks:
        assign_and_decide(task["id"], reviewer_id="rev-1", outcome="UPHOLD")
    assert get_claim(claim["id"])["status"] == "DENIED"

    hits = list_claim_hits(claim["id"])
    assert len(hits) == 2
    observed_v = get_claim(claim["id"])["version"]

    first = validate_success(api.create_dispute(
        claim["id"],
        create_dispute_payload(hits[0]["id"], observed_v, reason="first"),
        make_provider_headers(provider["id"])), expected_status=201)
    assert first["status"] == "SUBMITTED"

    # The first create bumped the claim's version, so the same observed
    # version is now stale for the second hit.
    resp = api.create_dispute(
        claim["id"],
        create_dispute_payload(hits[1]["id"], observed_v, reason="second"),
        make_provider_headers(provider["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def test_dispute_rfi_round_trip_cycle(api):
    """PRD §3.6: "Requesting information — with an optional `info_request_note`
    — moves it from `UNDER_REVIEW` to `AWAITING_PROVIDER_INFO`, and the
    dispute's own provider returns it to `UNDER_REVIEW` by submitting
    information with an optional `info_response`; that submission is
    ownership-checked against the dispute's provider."

    Design: Difficulty/non_linear_state_machine/dispute_rfi_round_trip_cycle
    """
    ctx = create_upheld_claim(npi="NPI-D6", edit_code="RFI-DENY", billed=25000,
                              claim_number="D6", member_id="M-D6")
    dispute = open_dispute_under_review(ctx["provider"]["id"],
                                        ctx["claim"]["id"], ctx["hit"]["id"])

    awaiting = validate_success(api.request_dispute_info(
        dispute["id"], {"info_request_note": "send op report"}, ADJUDICATOR))
    assert awaiting["status"] == "AWAITING_PROVIDER_INFO"

    back = validate_success(api.submit_dispute_info(
        dispute["id"], {"info_response": "op report attached"},
        make_provider_headers(ctx["provider"]["id"])))
    assert back["status"] == "UNDER_REVIEW", (
        "UNDER_REVIEW -> AWAITING_PROVIDER_INFO -> UNDER_REVIEW cycle closed"
    )


def test_dispute_rfi_then_upheld_keeps_dollars(api):
    """PRD §3.6: "`UPHELD` changes nothing about the hit or the claim's
    amounts."
    PRD §3.6: "The request carries the `outcome`, the optional
    `released_cents` used only by `PARTIAL`, and an optional
    `decision_note`."

    Design: Difficulty/non_linear_state_machine/dispute_rfi_round_trip_cycle
    """
    ctx = create_upheld_claim(npi="NPI-D6B", edit_code="RFI-DENY-2",
                              billed=25000, claim_number="D6B",
                              member_id="M-D6B")
    dispute = open_dispute_under_review(ctx["provider"]["id"],
                                        ctx["claim"]["id"], ctx["hit"]["id"])
    validate_success(api.request_dispute_info(dispute["id"], {}, ADJUDICATOR))
    validate_success(api.submit_dispute_info(
        dispute["id"], {}, make_provider_headers(ctx["provider"]["id"])))

    decided = validate_success(api.decide_dispute(
        dispute["id"], decide_dispute_payload("UPHELD"), ADJUDICATOR))
    assert decided["status"] == "DECIDED"
    assert decided["outcome"] == "UPHELD"

    hit = get_hit(ctx["hit"]["id"])
    assert hit["status"] == "CONFIRMED"
    claim = get_claim(ctx["claim"]["id"])
    assert claim["allowed_amount_cents"] == 0
    assert claim["denied_amount_cents"] == 25000, (
        "the RFI loop and the UPHELD decision touched no dollars"
    )


def test_decided_dispute_past_deadline_state_beats_temporal(api):
    """PRD §2.8: "validation runs in a fixed order of precedence bands, and a
    failure in an earlier band masks every later check."
    PRD §2.8: "7. **State preconditions.** Each state machine's from-state
    requirement, surfacing the state-family errors"
    PRD §2.8: "10. **Temporal windows.** Dispute windows, decision deadlines,
    audit occupancy, and document-due expirability"
    PRD §3.6: "the dispute must be `UNDER_REVIEW`, else
    `ERR_DISPUTE_NOT_DECIDABLE`"

    Design: Difficulty/priority_pair_validation_conflict/decided_dispute_past_deadline_state_beats_temporal
    """
    ctx = create_upheld_claim(npi="NPI-D9", edit_code="PRIO-DENY", billed=25000,
                              claim_number="D9", member_id="M-D9")
    dispute = open_dispute_under_review(ctx["provider"]["id"],
                                        ctx["claim"]["id"], ctx["hit"]["id"],
                                        reason="contest")
    decided = validate_success(api.decide_dispute(
        dispute["id"], decide_dispute_payload("UPHELD"), ADJUDICATOR))
    assert decided["status"] == "DECIDED"

    # 2026-10-02 is 62 days after submission: both the state violation and the
    # temporal violation now hold; the earlier state band must mask the later.
    set_clock("2026-10-02T00:00:00Z")
    resp = api.decide_dispute(dispute["id"], decide_dispute_payload("UPHELD"),
                              ADJUDICATOR)
    validate_error(resp, ApiErrorId.ERR_DISPUTE_NOT_DECIDABLE,
                   expected_status=409)


def test_decided_dispute_past_deadline_no_side_effects(api):
    """PRD §3.6: "`UPHELD` changes nothing about the hit or the claim's
    amounts."
    PRD §3.6: "Any dispute action attempted from a status that does not permit
    it — deciding before review has started, requesting information outside
    `UNDER_REVIEW`, submitting information when none was requested — is
    rejected with `ERR_DISPUTE_NOT_DECIDABLE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/decided_dispute_past_deadline_state_beats_temporal
    """
    ctx = create_upheld_claim(npi="NPI-D9B", edit_code="PRIO-DENY-2",
                              billed=25000, claim_number="D9B",
                              member_id="M-D9B")
    dispute = open_dispute_under_review(ctx["provider"]["id"],
                                        ctx["claim"]["id"], ctx["hit"]["id"],
                                        reason="contest")
    validate_success(api.decide_dispute(dispute["id"],
                                        decide_dispute_payload("UPHELD"),
                                        ADJUDICATOR))

    set_clock("2026-10-02T00:00:00Z")
    resp = api.decide_dispute(dispute["id"], decide_dispute_payload("UPHELD"),
                              ADJUDICATOR)
    validate_error(resp, ApiErrorId.ERR_DISPUTE_NOT_DECIDABLE,
                   expected_status=409)

    still = get_success_data(api.get_dispute(dispute["id"], ADMIN))
    assert still["status"] == "DECIDED"
    assert still["outcome"] == "UPHELD"
    claim = get_claim(ctx["claim"]["id"])
    assert claim["status"] == "DENIED"
    assert claim["allowed_amount_cents"] == 0
    assert claim["denied_amount_cents"] == 25000
