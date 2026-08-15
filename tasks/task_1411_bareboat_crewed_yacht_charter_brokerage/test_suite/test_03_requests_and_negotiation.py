"""Charter request creation rules, negotiation round, offer computation
variants, OCC guards, offer expiry, rebooking, and negotiation RBAC."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    THRESHOLDS,
    assert_charter_request,
    create_broker_payload,
    create_charter_request_payload,
    create_counter_payload,
    create_listed_yacht,
    create_manual_block,
    create_offer_payload,
    create_operator,
    create_qualified_client,
    create_rebook_payload,
    create_request,
    decline_request,
    make_central_agent_headers,
    make_client_headers,
    make_offer,
    make_retail_broker_headers,
    setup_accepted_agreement,
    setup_listed_marketplace,
    setup_marketplace,
    setup_offered_request,
    setup_submitted_request,
    set_clock,
    submit_request,
    TEST_USERS,
    api_client,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _parse_instant(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def test_request_creation_defaults(api):
    """PRD section 3.3: "The new request starts in `DRAFT` with `round_count`
    at zero and the commercial fields `quoted_charter_fee_cents`, `apa_pct`,
    `gratuity_pledged_cents`, and `retail_pct_bps` all null until the first
    offer; `offer_expires_at` is likewise null outside the `OFFERED` state."
    PRD section 3.3: "with the new request's `rebooked_from_request_id`
    pointing back at the terminal request it descends from (null on any
    request not born of a rebook)."

    Design: Corner/entities/request_creation_defaults
    """
    ctx = setup_listed_marketplace()
    request = validate_success(
        api.create_charter_request(
            create_charter_request_payload(ctx.client["id"], ctx.yacht["id"]),
            ctx.cl_headers),
        201)
    assert_charter_request(request)
    assert request["status"] == "DRAFT"
    assert request["round_count"] == 0
    assert isinstance(request["version"], int)
    for field in ("quoted_charter_fee_cents", "apa_pct", "gratuity_pledged_cents",
                  "retail_pct_bps", "offer_expires_at", "rebooked_from_request_id"):
        assert request[field] is None, f"request.{field} must be null before any offer"
    assert is_valid_uuid(request["id"])
    assert is_iso8601_timestamp(request["created_at"])
    assert is_iso8601_timestamp(request["updated_at"])


def test_guests_above_capacity_rejected(api):
    """PRD section 3.3: "The party size must be at least one and no more than
    the yacht's `capacity_berths` — a party exactly equal to capacity passes,
    and anything larger is rejected with `ERR_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/capacity_equals_limit_passes
    """
    ctx = setup_listed_marketplace()  # Yacht A preset: capacity_berths 8
    res = api.create_charter_request(
        create_charter_request_payload(ctx.client["id"], ctx.yacht["id"],
                                       guests_count=9),
        ctx.cl_headers)
    validate_error(res, ApiErrorId.ERR_CAPACITY_EXCEEDED, expected_status=422)

    data, meta = validate_paginated(
        api.list_charter_requests(ADMIN, params={"client_id": ctx.client["id"]}))
    assert meta["total_count"] == 0, "the oversized request must not persist"


def test_guests_equal_capacity_accepted(api):
    """PRD section 3.3: "The party size must be at least one and no more than
    the yacht's `capacity_berths` — a party exactly equal to capacity passes,
    and anything larger is rejected with `ERR_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/capacity_equals_limit_passes
    """
    ctx = setup_listed_marketplace()  # Yacht A preset: capacity_berths 8
    request = validate_success(
        api.create_charter_request(
            create_charter_request_payload(ctx.client["id"], ctx.yacht["id"],
                                           guests_count=8),
            ctx.cl_headers),
        201)
    assert request["status"] == "DRAFT"
    assert request["guests_count"] == 8, "guests_count == capacity passes"


def test_charter_duration_minimum_enforced(api):
    """PRD section 3.3: "The charter's length in whole days must reach the
    yacht's `min_charter_days`, or creation fails with
    `ERR_CHARTER_DURATION_INVALID`."

    Design: Corner/validations/charter_duration_minimum_enforced
    """
    ctx = setup_listed_marketplace()  # Yacht A preset: min_charter_days 3
    res = api.create_charter_request(
        create_charter_request_payload(ctx.client["id"], ctx.yacht["id"],
                                       start_date="2026-10-01",
                                       end_date="2026-10-03"),
        ctx.cl_headers)
    validate_error(res, ApiErrorId.ERR_CHARTER_DURATION_INVALID,
                   expected_status=422)  # 2 days < min 3

    request = validate_success(
        api.create_charter_request(
            create_charter_request_payload(ctx.client["id"], ctx.yacht["id"],
                                           start_date="2026-10-01",
                                           end_date="2026-10-04"),
            ctx.cl_headers),
        201)
    assert request["status"] == "DRAFT", "exactly min_charter_days (3) passes"


def test_duplicate_active_request_rejected(api):
    """PRD section 3.3: "A duplicate guard also applies at creation: the same
    client asking for the same yacht over half-open-overlapping dates is
    rejected with `ERR_DUPLICATE_ACTIVE_REQUEST` if an earlier request of
    theirs is still live — that is, in `DRAFT`, `SUBMITTED`, `OFFERED`, or
    `COUNTERED`."

    Design: Corner/validations/duplicate_active_request_rejected
    """
    ctx = setup_listed_marketplace()
    first = create_request(ctx.client["id"], ctx.yacht["id"])  # 10-01..10-11
    assert first["status"] == "DRAFT"

    res = api.create_charter_request(
        create_charter_request_payload(ctx.client["id"], ctx.yacht["id"],
                                       start_date="2026-10-05",
                                       end_date="2026-10-15"),
        ctx.cl_headers)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_ACTIVE_REQUEST,
                   expected_status=409)

    second = validate_success(
        api.create_charter_request(
            create_charter_request_payload(ctx.client["id"], ctx.yacht["id"],
                                           start_date="2026-12-01",
                                           end_date="2026-12-11"),
            ctx.cl_headers),
        201)
    assert second["status"] == "DRAFT", (
        "disjoint dates for the same client+yacht do not trip the guard")


def test_yacht_not_listed_submit_rejected(api):
    """PRD section 3.3: "The yacht must currently be `LISTED`, else
    `ERR_YACHT_NOT_LISTED`."

    Design: Corner/validations/yacht_not_listed_submit_rejected
    """
    ctx = setup_marketplace()  # yacht stays DRAFT
    request = create_request(ctx.client["id"], ctx.yacht["id"])
    res = api.submit_charter_request(request["id"], ctx.cl_headers)
    validate_error(res, ApiErrorId.ERR_YACHT_NOT_LISTED, expected_status=409)

    after = validate_success(api.get_charter_request(request["id"], ctx.cl_headers),
                             200)
    assert after["status"] == "DRAFT"


def test_unqualified_submit_rejected_despite_overlap(api):
    """PRD section 3.3: "Submitting the request — by the client or the retail
    broker on the deal, others drawing `ERR_FORBIDDEN` — moves it from `DRAFT`
    to `SUBMITTED` through an ordered battery of gates. The yacht must
    currently be `LISTED`, else `ERR_YACHT_NOT_LISTED`. The operator must be
    `ACTIVE`, else `ERR_OPERATOR_SUSPENDED`. For a `BAREBOAT` yacht, two
    qualification gates follow: the client's `qualification_status` must be
    `QUALIFIED`, else `ERR_CLIENT_NOT_QUALIFIED`, and the client's
    `resume_class` must rank at or above the yacht's `required_resume_class`
    on the `NONE`-to-`OCEAN` ladder, else `ERR_RESUME_CLASS_INSUFFICIENT`; a
    `CREWED` yacht skips both gates, since a professional crew carries the
    vessel. The calendar rules of section 2.7 then run against the requested
    window, rejecting overlaps with `ERR_AVAILABILITY_CONFLICT` and buffer
    adjacency with `ERR_TURNAROUND_BUFFER_VIOLATION`, and finally the
    duplicate guard runs again — submission is the second of its three
    enforcement points — surfacing `ERR_DUPLICATE_ACTIVE_REQUEST` for an
    overlapping live request by the same client on the same yacht."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_submit
    """
    ctx = setup_marketplace(qualify=False)  # client stays UNVERIFIED
    block = create_manual_block(ctx.yacht["id"], ctx.operator["id"],
                                ctx.yacht["version"],
                                start_date="2026-10-30", end_date="2026-11-09")
    listed = validate_success(api.list_yacht(ctx.yacht["id"], ctx.op_headers), 200)
    request = create_request(ctx.client["id"], ctx.yacht["id"],
                             start_date="2026-11-01", end_date="2026-11-08")

    # The window truly overlaps the ACTIVE block, yet the qualification gate
    # is ordered ahead of the calendar rules in the fixed battery.
    res = api.submit_charter_request(request["id"], ctx.cl_headers)
    validate_error(res, ApiErrorId.ERR_CLIENT_NOT_QUALIFIED, expected_status=422)


def test_rejected_submit_leaves_request_draft(api):
    """PRD section 3.3: "Submitting the request — by the client or the retail
    broker on the deal, others drawing `ERR_FORBIDDEN` — moves it from `DRAFT`
    to `SUBMITTED` through an ordered battery of gates. The yacht must
    currently be `LISTED`, else `ERR_YACHT_NOT_LISTED`. The operator must be
    `ACTIVE`, else `ERR_OPERATOR_SUSPENDED`. For a `BAREBOAT` yacht, two
    qualification gates follow: the client's `qualification_status` must be
    `QUALIFIED`, else `ERR_CLIENT_NOT_QUALIFIED`, and the client's
    `resume_class` must rank at or above the yacht's `required_resume_class`
    on the `NONE`-to-`OCEAN` ladder, else `ERR_RESUME_CLASS_INSUFFICIENT`; a
    `CREWED` yacht skips both gates, since a professional crew carries the
    vessel. The calendar rules of section 2.7 then run against the requested
    window, rejecting overlaps with `ERR_AVAILABILITY_CONFLICT` and buffer
    adjacency with `ERR_TURNAROUND_BUFFER_VIOLATION`, and finally the
    duplicate guard runs again — submission is the second of its three
    enforcement points — surfacing `ERR_DUPLICATE_ACTIVE_REQUEST` for an
    overlapping live request by the same client on the same yacht."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_submit
    """
    ctx = setup_marketplace(qualify=False)
    block = create_manual_block(ctx.yacht["id"], ctx.operator["id"],
                                ctx.yacht["version"],
                                start_date="2026-10-30", end_date="2026-11-09")
    validate_success(api.list_yacht(ctx.yacht["id"], ctx.op_headers), 200)
    request = create_request(ctx.client["id"], ctx.yacht["id"],
                             start_date="2026-11-01", end_date="2026-11-08")

    validate_error(api.submit_charter_request(request["id"], ctx.cl_headers),
                   ApiErrorId.ERR_CLIENT_NOT_QUALIFIED, expected_status=422)
    after = validate_success(api.get_charter_request(request["id"], ctx.cl_headers),
                             200)
    assert after["status"] == "DRAFT", (
        "a rejected submit applies no transition; the overlapping block "
        "remains the only calendar fact")


def test_pro_rata_quote_exact_daily_seventh(api):
    """PRD section 3.3: "Under the `PRO_RATA` variant, every day costs exactly
    one seventh of the week — the fee is the weekly base rate multiplied by
    the number of charter days, divided by seven, rounded half-up to whole
    cents."

    Design: Difficulty/dual_variant_calc/quote_pro_rata_vs_weekly_plus_daily
    """
    ctx = setup_submitted_request(start_date="2026-10-01", end_date="2026-10-11",
                                  yacht_preset={"pricing_mode": "PRO_RATA"})
    offered = make_offer(ctx.request["id"], ctx.central_agent["id"])
    assert offered["quoted_charter_fee_cents"] == 1000000, (
        "10 days x 700000 / 7 rounds to exactly 1000000 under PRO_RATA")
    assert offered["status"] == "OFFERED"


def test_weekly_plus_daily_quote_short_week_premium(api):
    """PRD section 3.3: "Under `WEEKLY_PLUS_DAILY`, each complete seven-day
    week is charged at the full weekly rate, and each remaining day beyond the
    last complete week is charged at the industry's short-week daily rate —
    the weekly base rate divided by six, rounded half-up to whole cents — so
    spare days are dearer than pro-rata days, and identical dates at an
    identical weekly rate quote strictly higher whenever at least one spare
    day exists."

    Design: Difficulty/dual_variant_calc/quote_pro_rata_vs_weekly_plus_daily
    """
    ctx = setup_submitted_request(start_date="2026-10-01", end_date="2026-10-11",
                                  yacht_preset={"pricing_mode": "WEEKLY_PLUS_DAILY",
                                                "security_deposit_cents": 400000})
    offered = make_offer(ctx.request["id"], ctx.central_agent["id"])
    # 1 week at 700000 + 3 spare days at round_half_up(700000/6) = 116667.
    assert offered["quoted_charter_fee_cents"] == 1050001, (
        "WEEKLY_PLUS_DAILY quotes strictly higher than the PRO_RATA 1000000 "
        "for identical dates and weekly rate")

    other = setup_submitted_request(start_date="2026-12-01",
                                    end_date="2026-12-11",
                                    yacht_preset={"pricing_mode": "PRO_RATA"})
    offered_other = make_offer(other.request["id"], other.central_agent["id"])
    assert offered["quoted_charter_fee_cents"] != offered_other["quoted_charter_fee_cents"], (
        "the two variants must diverge whenever at least one spare day exists")


def test_weekly_plus_daily_rounding_precision(api):
    """PRD section 3.3: "Under `WEEKLY_PLUS_DAILY`, each complete seven-day
    week is charged at the full weekly rate, and each remaining day beyond the
    last complete week is charged at the industry's short-week daily rate —
    the weekly base rate divided by six, rounded half-up to whole cents — so
    spare days are dearer than pro-rata days, and identical dates at an
    identical weekly rate quote strictly higher whenever at least one spare
    day exists."
    PRD section 2.6: "Wherever a calculation introduces a division or a
    fractional multiplication, the result is rounded half-up to whole cents,
    and the rounding is applied at each rounding step in the order the
    relevant rule pins down, never once at the end of a chain of operations."

    Design: Corner/calculations/weekly_plus_daily_rounding_precision
    """
    ctx = setup_submitted_request(
        start_date="2026-10-01", end_date="2026-10-09", guests_count=2,
        yacht_preset={"pricing_mode": "WEEKLY_PLUS_DAILY",
                      "weekly_base_rate_cents": 100000,
                      "capacity_berths": 4,
                      "security_deposit_cents": 100000})
    offered = make_offer(ctx.request["id"], ctx.central_agent["id"])
    # round_half_up(100000 / 6) = 16667; truncating division would give 116666.
    assert offered["quoted_charter_fee_cents"] == 116667, (
        "the extra-day rate step rounds half-up: 100000 + 16667")


def test_apa_pct_tier_boundary(api):
    """PRD section 3.3: "The APA fraction: an `apa_pct` override locks as
    given; otherwise the tiered default keys on the quoted fee — a quoted fee
    strictly below 2,000,000 cents (twenty thousand dollars) locks `apa_pct`
    at 0.30, while a fee at or above the threshold locks 0.25, so a quote of
    exactly 2,000,000 cents lands in the 0.25 tier."

    Design: Corner/calculations/apa_pct_tier_boundary
    """
    import pytest

    ctx = setup_submitted_request(start_date="2026-10-30", end_date="2026-11-19")
    offered = make_offer(ctx.request["id"], ctx.central_agent["id"])
    assert offered["quoted_charter_fee_cents"] == 2000000, (
        "20 days at 700000 pro-rata lands exactly on the threshold")
    assert offered["apa_pct"] == pytest.approx(0.25), (
        "a quote of exactly 2,000,000 cents lands in the 0.25 tier")

    ctx2 = setup_submitted_request(start_date="2026-12-01", end_date="2026-12-21")
    offered2 = make_offer(ctx2.request["id"], ctx2.central_agent["id"],
                          quoted_charter_fee_cents=1999999)
    assert offered2["apa_pct"] == pytest.approx(0.30), (
        "one cent below the threshold takes the 0.30 tier")


def test_gratuity_minimum_crewed_boundary(api):
    """PRD section 3.3: "The gratuity: `gratuity_pledged_cents` rides along
    with the offer, and for a `CREWED` yacht it must be at least ten percent
    of the quoted charter fee, rounded half-up to whole cents — a smaller
    pledge is rejected with `ERR_GRATUITY_BELOW_MINIMUM` — while a `BAREBOAT`
    offer accepts any non-negative pledge, zero included."

    Design: Corner/validations/gratuity_minimum_crewed_boundary
    """
    # CREWED yacht: qualification gates are skipped, so an UNVERIFIED client
    # still submits fine (setup_submitted_request qualifies the client anyway).
    ctx = setup_submitted_request(
        start_date="2026-10-01", end_date="2026-10-11", guests_count=6,
        yacht_preset={"charter_type": "CREWED",
                      "capacity_berths": 10,
                      "required_resume_class": "NONE",
                      "security_deposit_cents": 0,
                      "pricing_mode": "PRO_RATA"})
    ca_headers = make_central_agent_headers(ctx.central_agent["id"])

    res = api.offer_charter_request(
        ctx.request["id"], create_offer_payload(gratuity_pledged_cents=99999),
        ca_headers)
    validate_error(res, ApiErrorId.ERR_GRATUITY_BELOW_MINIMUM,
                   expected_status=422)  # 99999 < round_half_up(0.10 x 1000000)

    after = validate_success(api.get_charter_request(ctx.request["id"], ctx.cl_headers),
                             200)
    assert after["status"] == "SUBMITTED", "a rejected offer must not transition"

    offered = validate_success(
        api.offer_charter_request(
            ctx.request["id"], create_offer_payload(gratuity_pledged_cents=100000),
            ca_headers),
        200)
    assert offered["status"] == "OFFERED"
    assert offered["quoted_charter_fee_cents"] == 1000000
    assert offered["gratuity_pledged_cents"] == 100000, (
        "a pledge exactly at the ten-percent minimum passes")


def test_counter_cycle_round_count_and_expiry_cleared(api):
    """PRD section 3.3: "A successful counter increments `round_count` by one,
    clears `offer_expires_at` back to null, and increments `version` by one;
    the client side may optionally attach `counter_charter_fee_cents` to
    signal the price it is holding out for, leaving the formal terms to the
    central agent's next offer."
    PRD section 3.3: "The first offer requires the operator to be `ACTIVE`
    (`ERR_OPERATOR_SUSPENDED`); a re-offer after a counter moves from
    `COUNTERED` back to `OFFERED` under the same ownership rule but does not
    re-check the operator's standing."

    Design: Difficulty/non_linear_state_machine/request_negotiation_counter_cycle
    """
    ctx = setup_submitted_request(start_date="2026-10-01", end_date="2026-10-11")
    offered = make_offer(ctx.request["id"], ctx.central_agent["id"])
    assert offered["status"] == "OFFERED"
    assert offered["quoted_charter_fee_cents"] == 1000000
    assert offered["version"] == ctx.request["version"] + 1

    countered = validate_success(
        api.counter_charter_request(
            ctx.request["id"],
            create_counter_payload(offered["version"],
                                   counter_charter_fee_cents=900000),
            ctx.cl_headers),
        200)
    assert countered["status"] == "COUNTERED"
    assert countered["round_count"] == 1
    assert countered["offer_expires_at"] is None, (
        "a successful counter clears offer_expires_at back to null")
    assert countered["version"] == offered["version"] + 1

    reoffered = make_offer(ctx.request["id"], ctx.central_agent["id"],
                           quoted_charter_fee_cents=950000)
    assert reoffered["status"] == "OFFERED"
    assert reoffered["quoted_charter_fee_cents"] == 950000
    assert reoffered["version"] == countered["version"] + 1


def test_acceptance_uses_final_offer_terms(api):
    """PRD section 3.4: "Onto the agreement go the source
    `charter_request_id`; the `client_id` and `retail_broker_id` from the
    request (the latter may be null); the `yacht_id`; the `operator_id` read
    off the yacht; the `central_agent_id` read off the yacht's
    `listing_central_agent_id`; the `start_date` and `end_date` of the
    charter window; the agreed commercials — `charter_fee_cents` from the
    request's quoted fee, `apa_pct`, `gratuity_pledged_cents` (zero for a
    bareboat charter unless the offer pledged one), and `retail_pct_bps`; the
    yacht's `security_deposit_cents`; and the yacht's `pricing_mode`, kept for
    audit even though no further quoting occurs."

    Design: Difficulty/non_linear_state_machine/request_negotiation_counter_cycle
    """
    ctx = setup_submitted_request(start_date="2026-10-01", end_date="2026-10-11")
    offered = make_offer(ctx.request["id"], ctx.central_agent["id"])
    countered = validate_success(
        api.counter_charter_request(
            ctx.request["id"],
            create_counter_payload(offered["version"],
                                   counter_charter_fee_cents=900000),
            ctx.cl_headers),
        200)
    reoffered = make_offer(ctx.request["id"], ctx.central_agent["id"],
                           quoted_charter_fee_cents=950000)

    agreement = validate_success(
        api.accept_charter_request(
            ctx.request["id"],
            {"expected_charter_request_version": reoffered["version"]},
            ctx.cl_headers),
        201)
    assert agreement["charter_fee_cents"] == 950000, (
        "the agreement snapshots the terms of the final offer, not the first")
    assert agreement["charter_request_id"] == ctx.request["id"]
    assert agreement["status"] == "PENDING_SIGNATURES"
    assert agreement["funds_status"] == "UNFUNDED"


def test_negotiation_round_cap_at_four(api):
    """PRD section 3.3: "then the round cap — `round_count` must still be
    below the four-round negotiation limit, and a counter at the cap is
    rejected with `ERR_NEGOTIATION_ROUND_LIMIT`."

    Design: Corner/state_machines/negotiation_round_cap_at_four
    """
    ctx = setup_submitted_request(start_date="2026-10-01", end_date="2026-10-11")

    version = ctx.request["version"]
    rounds = 0
    for _ in range(THRESHOLDS["MAX_NEGOTIATION_ROUNDS"]):
        offered = make_offer(ctx.request["id"], ctx.central_agent["id"])
        version = offered["version"]
        countered = validate_success(
            api.counter_charter_request(
                ctx.request["id"], create_counter_payload(version),
                ctx.cl_headers),
            200)
        rounds = countered["round_count"]
        version = countered["version"]
    assert rounds == 4, "exactly four counter cycles are allowed"

    offered = make_offer(ctx.request["id"], ctx.central_agent["id"])
    res = api.counter_charter_request(
        ctx.request["id"], create_counter_payload(offered["version"]),
        ctx.cl_headers)
    validate_error(res, ApiErrorId.ERR_NEGOTIATION_ROUND_LIMIT,
                   expected_status=409)

    after = validate_success(api.get_charter_request(ctx.request["id"], ctx.cl_headers),
                             200)
    assert after["status"] == "OFFERED"
    assert after["round_count"] == 4, "the rejected counter must not increment"


def test_offer_expiry_lazy_transition(api):
    """PRD section 2.5: "Offer expiry is explicitly not part of this sweep: a
    charter request whose offer has lapsed is transitioned to `EXPIRED`
    lazily, only when the client side next attempts to counter or accept it."
    PRD section 3.3: "then the lazy expiry check — if the logical clock has
    passed `offer_expires_at`, the request transitions to `EXPIRED` and the
    counter is rejected with `ERR_OFFER_EXPIRED`; then the round cap —
    `round_count` must still be below the four-round negotiation limit, and a
    counter at the cap is rejected with `ERR_NEGOTIATION_ROUND_LIMIT`."
    PRD section 3.3: "Issuing the offer transitions the request to `OFFERED`,
    locks all four terms onto it, stamps `offer_expires_at` at exactly seven
    days after the offer moment, and increments the request's `version` by
    one."

    Design: Corner/state_machines/offer_expiry_lazy_transition
    """
    ctx = setup_offered_request(start_date="2026-10-01", end_date="2026-10-11")
    offered = ctx.request
    # The offer was issued under the startup clock 2026-08-01T00:00:00Z.
    assert _parse_instant(offered["offer_expires_at"]) == datetime(
        2026, 8, 8, 0, 0, 0, tzinfo=timezone.utc), (
        "offer_expires_at is exactly seven days after the offer moment")

    set_clock("2026-08-10T00:00:00Z")
    res = api.accept_charter_request(
        ctx.request["id"],
        {"expected_charter_request_version": offered["version"]},
        ctx.cl_headers)
    validate_error(res, ApiErrorId.ERR_OFFER_EXPIRED, expected_status=409)

    after = validate_success(api.get_charter_request(ctx.request["id"], ctx.cl_headers),
                             200)
    assert after["status"] == "EXPIRED", (
        "the lazy expiry check transitions the request to EXPIRED")

    rebooked = validate_success(
        api.rebook_charter_request(
            ctx.request["id"],
            create_rebook_payload(ctx.yacht["id"]),
            ctx.cl_headers),
        201)
    assert rebooked["status"] == "DRAFT"
    assert rebooked["rebooked_from_request_id"] == ctx.request["id"], (
        "EXPIRED is a terminal state from which the client side may rebook")


def test_terminal_request_lockdown(api):
    """PRD section 3.3: "Three states end a request: `DECLINED`, `EXPIRED`,
    and `CANCELLED`."
    PRD section 2.11: "State validity — the target is in a from-state with a
    declared transition for the trigger, covering wrong-from-state,
    already-terminal resources, a duplicate signature on an agreement, a
    manual release attempted on a `CHARTER` block, a second insurance
    certificate while one is still `PENDING` or `VERIFIED`, and a void
    attempted after a signature exists; failures surface as
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/terminal_request_lockdown
    """
    ctx = setup_offered_request(start_date="2026-10-01", end_date="2026-10-11")
    declined = decline_request(ctx.request["id"], ctx.client["id"])
    assert declined["status"] == "DECLINED"

    res = api.counter_charter_request(
        ctx.request["id"], create_counter_payload(declined["version"],
                                                  counter_charter_fee_cents=900000),
        ctx.cl_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    res = api.decline_charter_request(ctx.request["id"], ctx.cl_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    # A DRAFT request (different dates) cannot be offered either.
    draft = create_request(ctx.client["id"], ctx.yacht["id"],
                           start_date="2026-12-01", end_date="2026-12-11")
    res = api.offer_charter_request(draft["id"], create_offer_payload(),
                                    make_central_agent_headers(ctx.central_agent["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_rebook_from_non_terminal_rejected(api):
    """PRD section 3.3: "Three states end a request: `DECLINED`, `EXPIRED`,
    and `CANCELLED`. From any of them the client side may rebook — a fresh
    request in `DRAFT` for the same client, built from a payload of
    `yacht_id`, `start_date`, `end_date`, `guests_count`, and optionally
    `retail_broker_id`, with the new request's `rebooked_from_request_id`
    pointing back at the terminal request it descends from (null on any
    request not born of a rebook)."
    PRD section 2.11: "State validity — the target is in a from-state with a
    declared transition for the trigger, covering wrong-from-state,
    already-terminal resources, a duplicate signature on an agreement, a
    manual release attempted on a `CHARTER` block, a second insurance
    certificate while one is still `PENDING` or `VERIFIED`, and a void
    attempted after a signature exists; failures surface as
    `ERR_INVALID_STATE`."

    Design: Corner/validations/rebook_from_non_terminal_rejected
    """
    ctx = setup_offered_request(start_date="2026-10-01", end_date="2026-10-11")
    res = api.rebook_charter_request(
        ctx.request["id"], create_rebook_payload(ctx.yacht["id"]), ctx.cl_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_occ_counter_stale_version(api):
    """PRD section 2.10: "First, countering an offer on a charter request
    requires the request body to carry `expected_charter_request_version`,
    holding the request `version` the caller last observed. If the request's
    current `version` differs — because the central agent has since posted a
    fresh offer with different terms, or any other write has advanced it —
    the counter is rejected with `ERR_STALE_VERSION` (HTTP 412), and the
    client must re-read the request and counter against the current version."

    Design: Corner/cross_cutting_complexity_layers/occ_counter_stale_version
    """
    ctx = setup_offered_request(start_date="2026-10-01", end_date="2026-10-11")
    current_version = ctx.request["version"]

    res = api.counter_charter_request(
        ctx.request["id"],
        create_counter_payload(current_version - 1), ctx.cl_headers)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    countered = validate_success(
        api.counter_charter_request(
            ctx.request["id"], create_counter_payload(current_version),
            ctx.cl_headers),
        200)
    assert countered["status"] == "COUNTERED"
    assert countered["version"] == current_version + 1, (
        "the rejected stale counter caused no version drift")


def test_occ_accept_stale_version(api):
    """PRD section 2.10: "Second, accepting an offer requires the same
    `expected_charter_request_version` field with the same semantics and the
    same `ERR_STALE_VERSION` (HTTP 412) rejection on mismatch. Accepting terms
    the client has not observed is never legitimate: if the version has
    advanced since the client last read the offer, the acceptance is refused
    and the client must re-read before accepting."

    Design: Corner/cross_cutting_complexity_layers/occ_accept_stale_version
    """
    ctx = setup_offered_request(start_date="2026-10-01", end_date="2026-10-11")
    current_version = ctx.request["version"]

    res = api.accept_charter_request(
        ctx.request["id"],
        {"expected_charter_request_version": current_version - 1},
        ctx.cl_headers)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    agreements, meta = validate_paginated(
        api.list_charter_agreements(ADMIN,
                                    params={"charter_request_id": ctx.request["id"]}))
    assert meta["total_count"] == 0, (
        "a stale acceptance creates no agreement; 412 is rejection, not terminal")

    agreement = validate_success(
        api.accept_charter_request(
            ctx.request["id"],
            {"expected_charter_request_version": current_version},
            ctx.cl_headers),
        201)
    assert agreement["status"] == "PENDING_SIGNATURES"
    assert agreement["funds_status"] == "UNFUNDED"


def test_forbidden_retail_broker_cannot_offer(api, platform_admin_headers):
    """PRD section 3.3: "With the request `SUBMITTED`, the deal's central
    agent — the broker matching the yacht's `listing_central_agent_id`,
    anyone else drawing `ERR_FORBIDDEN` — issues an offer."
    PRD section 2.1: "A well-authenticated caller who attempts an operation
    not open to their role, or who violates an ownership rule — an operator
    touching another operator's yacht, a non-party acting on a request or
    agreement, an offer issued by a broker who is not the listing central
    agent — is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/forbidden_retail_broker_cannot_offer
    """
    ctx = setup_listed_marketplace()
    retail_broker = validate_success(
        api.create_broker(create_broker_payload(display_name="RB One",
                                                broker_type="RETAIL_BROKER",
                                                license_no="LIC-RB-1"), ADMIN),
        201)
    request = create_request(ctx.client["id"], ctx.yacht["id"],
                             as_role="RetailBroker", caller_id=retail_broker["id"])
    request = submit_request(request["id"], retail_broker["id"],
                             as_role="RetailBroker")

    res = api.offer_charter_request(
        request["id"], create_offer_payload(),
        make_retail_broker_headers(retail_broker["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    after = validate_success(api.get_charter_request(request["id"], ADMIN), 200)
    assert after["status"] == "SUBMITTED"


def test_forbidden_wrong_central_agent_cannot_offer(api, platform_admin_headers):
    """PRD section 3.3: "With the request `SUBMITTED`, the deal's central
    agent — the broker matching the yacht's `listing_central_agent_id`,
    anyone else drawing `ERR_FORBIDDEN` — issues an offer."

    Design: Corner/rbac/forbidden_wrong_central_agent_cannot_offer
    """
    ctx = setup_submitted_request(start_date="2026-10-01", end_date="2026-10-11")
    other_ca = validate_success(
        api.create_broker(create_broker_payload(display_name="CA Two",
                                                license_no="LIC-CA-2"), ADMIN),
        201)
    res = api.offer_charter_request(
        ctx.request["id"], create_offer_payload(),
        make_central_agent_headers(other_ca["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
