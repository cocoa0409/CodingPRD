"""Impound, the statutory hold, the auction and the proceeds waterfall."""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_estray_case,
    assert_estray_distribution_conserved,
    assert_instant_equals,
    enter_finding,
    make_field_inspector_headers,
    make_livestock_owner_headers,
    present_lot,
    read_estray_case,
    read_lot,
    read_territory,
    record_sale_payload,
    schedule_auction_payload,
    set_clock,
    setup_estray_at_auction,
    setup_estray_capacity_scenario,
    setup_estray_sold_unclaimed,
    setup_impounded_estray,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

BOARD_ADMIN = TEST_USERS["board_admin_headers"]
FEE_ADMIN = TEST_USERS["fee_administrator_headers"]


# ─── The two variants of the proceeds waterfall ───────────────────────────────

def test_provisional_distribution_charges_the_statutory_care_floor(api):
    """PRD §3.8: "**First**, the care cost: the board charges 275 cents per head per day
    of care, so `care_cost_cents` is 275 multiplied by the case's `head_count`
    multiplied by the number of care days the variant supplies."
    PRD §3.8: "**Third**, an uncapped handling fee is computed as fifteen percent of the
    gross amount, rounded half up to whole cents. **Fourth**, a cap on that fee is
    computed as twenty percent of the net available amount — treating a negative net as
    zero — likewise rounded half up to whole cents. **Fifth**, `handling_fee_cents` is
    zero whenever the net available amount is zero or less, and is otherwise the smaller
    of the uncapped fee and the cap. **Sixth**, `claimant_residual_cents` is the net
    available amount less the handling fee, floored at zero so it is never negative."
    PRD §3.8: "The **PROVISIONAL** variant runs when the auction is scheduled: the gross
    amount is the case's `estimated_gross_cents`, and the care-day count is the
    statutory floor of 20 days regardless of where the logical clock actually stands."

    Design: Difficulty/dual_variant_calc/estray_provisional_vs_final_distribution_diverge
    """
    scenario = setup_estray_at_auction(
        head_count=12,
        impounded_at="2026-08-05T00:00:00Z",
        auction_at="2026-08-25T00:00:00Z",
        estimated_gross_cents=180000,
        territory_code="T-EST",
    )
    case = read_estray_case(scenario["case"]["id"])

    assert_estray_case(case)
    assert case["status"] == "AUCTION_SCHEDULED"
    assert case["distribution_variant"] == "PROVISIONAL"
    assert case["care_cost_cents"] == 66000, "275 cents per head per day over 12 head for 20 days"
    assert case["handling_fee_cents"] == 22800, "capped at 20 percent of the 114000 net"
    assert case["claimant_residual_cents"] == 91200
    assert_estray_distribution_conserved(case)


def test_final_distribution_overwrites_the_provisional_buckets(api):
    """PRD §3.8: "The **FINAL** variant runs when the sale is recorded: the gross amount
    is the case's `gross_proceeds_cents`, and the care-day count is the number of
    calendar dates from the date of `impounded_at` through the date of `sale_at`
    inclusive — that is, the difference between the two calendar dates plus one, counting
    both the intake day and the sale day."
    PRD §3.8: "It sets `distribution_variant` to `FINAL` and overwrites every bucket the
    provisional pass wrote."
    PRD §3.8: "After every write the conserved-quantity invariant holds: the gross amount
    equals the care cost plus the handling fee plus whichever of the claimant residual or
    the board forfeiture is in play."

    Design: Difficulty/dual_variant_calc/estray_provisional_vs_final_distribution_diverge
    """
    scenario = setup_estray_at_auction(
        head_count=12,
        impounded_at="2026-08-05T00:00:00Z",
        auction_at="2026-08-25T00:00:00Z",
        estimated_gross_cents=180000,
        territory_code="T-EST2",
    )
    provisional = read_estray_case(scenario["case"]["id"])
    assert provisional["claimant_residual_cents"] == 91200

    set_clock("2026-09-04T00:00:00Z")
    sold = validate_success(
        api.record_sale(
            scenario["case"]["id"], record_sale_payload(160000), BOARD_ADMIN
        ),
        200,
    )

    assert sold["status"] == "SOLD"
    assert sold["distribution_variant"] == "FINAL"
    assert sold["care_cost_cents"] == 102300, "31 inclusive care days at 275 cents over 12 head"
    assert sold["handling_fee_cents"] == 11540
    assert sold["claimant_residual_cents"] == 46160
    assert (
        sold["care_cost_cents"] + sold["handling_fee_cents"] + sold["claimant_residual_cents"]
        == 160000
    )
    assert_estray_distribution_conserved(sold)


def test_handling_fee_is_zero_when_the_care_bucket_swallows_the_gross(api):
    """PRD §3.8: "**Fifth**, `handling_fee_cents` is zero whenever the net available
    amount is zero or less, and is otherwise the smaller of the uncapped fee and the
    cap. **Sixth**, `claimant_residual_cents` is the net available amount less the
    handling fee, floored at zero so it is never negative."
    PRD §3.8: "**Second**, the net available amount is the gross amount less that care
    cost."

    Design: Corner/calculations/corner_estray_handling_fee_zero_when_care_exceeds_gross
    """
    scenario = setup_estray_at_auction(
        head_count=12,
        impounded_at="2026-08-05T00:00:00Z",
        auction_at="2026-08-25T00:00:00Z",
        estimated_gross_cents=180000,
        territory_code="T-DEFC",
    )
    set_clock("2026-09-04T00:00:00Z")

    sold = validate_success(
        api.record_sale(scenario["case"]["id"], record_sale_payload(90000), BOARD_ADMIN),
        200,
    )

    assert sold["distribution_variant"] == "FINAL"
    assert sold["care_cost_cents"] == 102300
    assert sold["handling_fee_cents"] == 0, "a non-positive net leaves no handling fee"
    assert sold["claimant_residual_cents"] == 0, "the residual is floored at zero"
    assert read_estray_case(scenario["case"]["id"])["status"] == "SOLD"


# ─── The facility capacity projection ─────────────────────────────────────────

def test_overlapping_intake_above_capacity_is_refused(api):
    """PRD §3.8: "The board projects the proposed occupancy as the half-open interval
    beginning at the logical clock and ending 20 days later."
    PRD §3.8: "The board then cuts the proposed interval at every interval endpoint
    among those projections and its own, and for each resulting half-open segment it
    sums the new lot's `head_count` together with the `head_count` of every live case
    whose interval covers that segment. If any segment's total exceeds the district's
    `impound_capacity_head`, the impound is refused with
    `ERR_FACILITY_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/facility_aggregate_capacity_rejects_overlapping_impound
    """
    scenario = setup_estray_capacity_scenario(
        capacity_head=30, first_head_count=20, pending_head_counts=(15, 10)
    )
    assert scenario["territory_after_first_intake"]["impound_current_head"] == 20
    assert scenario["territory_after_first_intake"]["intake_status"] == "OPEN"
    oversized = scenario["pending_lots"][0]

    response = api.record_finding(
        oversized["id"],
        {"finding": "NO_LEGIBLE_BRAND"},
        make_field_inspector_headers(scenario["inspector"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_FACILITY_CAPACITY_EXCEEDED.value, 409)

    unchanged = read_lot(oversized["id"])
    assert unchanged["match_status"] == "UNCHECKED"
    assert unchanged["lot_status"] == "PRESENTED"
    assert read_territory(scenario["territory"]["id"])["impound_current_head"] == 20


def test_intake_that_exactly_fills_the_facility_is_accepted(api):
    """PRD §3.8: "The board then cuts the proposed interval at every interval endpoint
    among those projections and its own, and for each resulting half-open segment it
    sums the new lot's `head_count` together with the `head_count` of every live case
    whose interval covers that segment. If any segment's total exceeds the district's
    `impound_capacity_head`, the impound is refused with
    `ERR_FACILITY_CAPACITY_EXCEEDED`."
    PRD §3.1: "Thereafter `impound_current_head` is the summed `head_count` of every
    estray case at that district whose status is `IMPOUNDED`, `CLAIM_FILED`,
    `AUCTION_SCHEDULED` or `SOLD`, and the district's intake posture follows directly
    from that occupancy: the district reads `RESTRICTED` once the live head count
    reaches ninety percent of `impound_capacity_head` — precisely, when the live head
    count multiplied by one hundred is greater than or equal to the capacity multiplied
    by ninety — and reads `OPEN` at any lower occupancy."

    Design: Difficulty/resource_temporal_overlap/facility_aggregate_capacity_rejects_overlapping_impound
    """
    scenario = setup_estray_capacity_scenario(
        capacity_head=30, first_head_count=20, pending_head_counts=(10,)
    )
    exact_fit = scenario["pending_lots"][0]

    impounded = enter_finding(
        exact_fit["id"], scenario["inspector"]["id"], "NO_LEGIBLE_BRAND"
    )

    assert impounded["match_status"] == "UNMATCHED"
    assert impounded["disposition"] == "ESTRAY_HOLD"

    territory = read_territory(scenario["territory"]["id"])
    assert territory["impound_current_head"] == 30
    assert territory["intake_status"] == "RESTRICTED"

    rows, meta = validate_paginated(
        api.list_estray_cases(
            BOARD_ADMIN, params={"territory_id": scenario["territory"]["id"]}
        )
    )
    assert meta["total_count"] == 2


def test_restricted_intake_is_reported_before_the_capacity_projection(api):
    """PRD §3.8: "The first gate is posture. The district's `intake_status` must read
    `OPEN` at the moment of the finding; a district that has already crossed the
    ninety-percent occupancy line described in §3.1 reads `RESTRICTED` and refuses
    further intake with `ERR_FACILITY_INTAKE_RESTRICTED`."
    PRD §3.1: "A district that is exactly at the ninety percent line is already
    `RESTRICTED`."
    PRD §2.8: "Brand exclusivity by recording priority (`ERR_BRAND_CONFLICT_EXISTS`) is
    evaluated first, then the theft-hold gate on fee operations (`ERR_ORDER_HOLD_ACTIVE`),
    then the district intake posture for an estray impound
    (`ERR_FACILITY_INTAKE_RESTRICTED`), then inspector availability
    (`ERR_INSPECTOR_UNAVAILABLE`), then the buffered window collision
    (`ERR_INSPECTOR_WINDOW_CONFLICT`), then the statutory-hold gate on scheduling an
    auction (`ERR_HOLD_PERIOD_NOT_ELAPSED`), then the claim-window gate on filing an
    estray claim (`ERR_CLAIM_WINDOW_CLOSED`), then the inspector's daily assignment
    ceiling (`ERR_INSPECTOR_DAILY_LIMIT`), then projected facility capacity
    (`ERR_FACILITY_CAPACITY_EXCEEDED`), then the uniqueness constraints
    (`ERR_DUPLICATE_DOCUMENT_NUMBER`, `ERR_DUPLICATE_BADGE_NUMBER`,
    `ERR_DUPLICATE_TERRITORY_CODE`), then the renewability of the prior record at
    recording time (`ERR_PRIOR_REGISTRATION_NOT_RENEWABLE`), then the tendered
    instrument's agreement with the lot (`ERR_BILL_OF_SALE_MISMATCH`), then the
    inspector's home-state match (`ERR_TERRITORY_MISMATCH`), then the owner's fiscal
    standing (`ERR_OWNER_STANDING_SUSPENDED`), then the late-renewal cutoff
    (`ERR_REGISTRATION_UNRENEWABLE`), and last of all the remittance overpayment test
    (`ERR_REMITTANCE_AMOUNT_INVALID`)."

    Design: Corner/validations/corner_restricted_intake_blocks_impound_before_capacity_check
    """
    scenario = setup_impounded_estray(
        head_count=9, impound_capacity_head=10, territory_code="T-TIGHT",
        owner_name="Tight Pen Ranch",
    )
    territory = read_territory(scenario["territory"]["id"])
    assert territory["impound_current_head"] == 9
    assert territory["intake_status"] == "RESTRICTED"

    next_lot = present_lot(scenario["order"]["id"], scenario["inspector"]["id"], 1)

    response = api.record_finding(
        next_lot["id"],
        {"finding": "NO_LEGIBLE_BRAND"},
        make_field_inspector_headers(scenario["inspector"]["id"]),
    )

    error = validate_error(
        response, ApiErrorId.ERR_FACILITY_INTAKE_RESTRICTED.value, 409
    )
    assert error["error_id"] != ApiErrorId.ERR_FACILITY_CAPACITY_EXCEEDED.value
    assert read_lot(next_lot["id"])["match_status"] == "UNCHECKED"
    assert read_territory(scenario["territory"]["id"])["impound_current_head"] == 9


def test_impound_cascade_is_visible_on_the_next_request(api):
    """PRD §3.8: "Clearing both gates produces a three-level cascade. The lot moves to
    `lot_status` `HELD` with `disposition` `ESTRAY_HOLD`."
    PRD §3.8: "An estray case is created at status `IMPOUNDED`, naming the lot as
    `animal_lot_id` and the district as `territory_id`, copying the lot's `head_count`,
    stamping `impounded_at` from the logical clock, and setting `statutory_release_on` to
    `impounded_at` advanced by 20 days."
    PRD §2.9: "These multi-hop effects are not best-effort conveniences; they are part
    of the operation's definition and complete within the same request."

    Design: Corner/consistency_model/corner_immediate_consistency_cascade_visible_without_replay
    """
    scenario = setup_impounded_estray(
        head_count=15, impounded_at="2026-08-05T00:00:00Z",
        territory_code="T-IMM", owner_name="Immediate Ranch",
    )

    assert scenario["lot"]["disposition"] == "ESTRAY_HOLD"
    assert scenario["lot"]["lot_status"] == "HELD"

    territory = read_territory(scenario["territory"]["id"])
    assert territory["impound_current_head"] == 15
    assert territory["intake_status"] == "OPEN"

    rows, meta = validate_paginated(
        api.list_estray_cases(
            BOARD_ADMIN, params={"territory_id": scenario["territory"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    case = rows[0]
    assert case["head_count"] == 15
    assert case["status"] == "IMPOUNDED"
    assert_instant_equals(
        case["statutory_release_on"], "2026-08-25T00:00:00Z", "statutory_release_on"
    )
    assert_instant_equals(case["impounded_at"], "2026-08-05T00:00:00Z", "impounded_at")


# ─── The statutory hold and the claim window ──────────────────────────────────

def test_denied_claim_returns_the_case_to_impound(api):
    """PRD §3.8: "Filing moves the case `IMPOUNDED → CLAIM_FILED` and records the
    claimant's `X-User-ID` as `claimant_owner_id`."
    PRD §3.8: "Denial sends the case back: it moves `CLAIM_FILED → IMPOUNDED`,
    `claim_denied_count` rises by one, and `claimant_owner_id` is cleared to null so
    that the same owner or a different one may file again while the window remains open."

    Design: Corner/state_machines/corner_estray_claim_denied_cycles_case_back_to_impounded
    """
    scenario = setup_impounded_estray(
        head_count=12, territory_code="T-DENY", owner_name="Deny Claim Ranch"
    )
    claimed = validate_success(
        api.claim_estray(
            scenario["case"]["id"],
            make_livestock_owner_headers(scenario["owner"]["id"]),
        ),
        200,
    )
    assert claimed["status"] == "CLAIM_FILED"
    assert claimed["claimant_owner_id"] == scenario["owner"]["id"]

    denied = validate_success(
        api.decide_estray_claim(
            scenario["case"]["id"], {"decision": "DENIED"}, BOARD_ADMIN
        ),
        200,
    )

    assert denied["status"] == "IMPOUNDED"
    assert denied["claim_denied_count"] == 1
    assert denied["claimant_owner_id"] is None
    assert read_territory(scenario["territory"]["id"])["impound_current_head"] == 12
    assert read_lot(scenario["lot"]["id"])["match_status"] == "UNMATCHED"


def test_claim_filed_at_the_release_instant_is_refused(api):
    """PRD §3.8: "A `LivestockOwner` files an ownership claim while the hold is still
    running — the logical clock must be strictly before `statutory_release_on`, and a
    claim filed at or after that instant is refused with `ERR_CLAIM_WINDOW_CLOSED`."

    Design: Corner/validations/corner_estray_claim_after_statutory_window_rejected
    """
    scenario = setup_impounded_estray(
        head_count=12, territory_code="T-LATE", owner_name="Late Claim Ranch"
    )
    assert_instant_equals(
        scenario["case"]["statutory_release_on"],
        "2026-08-25T00:00:00Z",
        "statutory_release_on",
    )
    set_clock("2026-08-25T00:00:00Z")

    response = api.claim_estray(
        scenario["case"]["id"], make_livestock_owner_headers(scenario["owner"]["id"])
    )

    validate_error(response, ApiErrorId.ERR_CLAIM_WINDOW_CLOSED.value, 409)
    case = read_estray_case(scenario["case"]["id"])
    assert case["status"] == "IMPOUNDED"
    assert case["claimant_owner_id"] is None


def test_auction_scheduled_one_day_early_is_refused(api):
    """PRD §3.8: "Scheduling the auction is available from `IMPOUNDED` and from
    `CLAIM_FILED` alike, and requires that the logical clock be at or after
    `statutory_release_on`; scheduling earlier is refused with
    `ERR_HOLD_PERIOD_NOT_ELAPSED`."

    Design: Corner/validations/corner_auction_before_hold_elapsed_rejected
    """
    scenario = setup_impounded_estray(
        head_count=12, territory_code="T-EARLY", owner_name="Early Auction Ranch"
    )
    set_clock("2026-08-24T00:00:00Z")

    response = api.schedule_auction(
        scenario["case"]["id"], schedule_auction_payload(180000), BOARD_ADMIN
    )

    validate_error(response, ApiErrorId.ERR_HOLD_PERIOD_NOT_ELAPSED.value, 409)
    case = read_estray_case(scenario["case"]["id"])
    assert case["status"] == "IMPOUNDED"
    assert case["distribution_variant"] == "NONE"
    assert case["care_cost_cents"] == 0


def test_claim_decision_without_a_filed_claim_is_refused(api):
    """PRD §3.8: "Attempting any of these estray transitions from a state that does not
    declare it — disbursing a case that was never sold, ruling on a claim that was never
    filed — is refused with `ERR_ESTRAY_INVALID_STATE`."

    Design: Corner/errors/corner_claim_decision_without_filed_claim_rejected
    """
    scenario = setup_impounded_estray(
        head_count=12, territory_code="T-NOCL", owner_name="No Claim Ranch"
    )
    assert scenario["case"]["status"] == "IMPOUNDED"

    response = api.decide_estray_claim(
        scenario["case"]["id"], {"decision": "APPROVED"}, BOARD_ADMIN
    )

    validate_error(response, ApiErrorId.ERR_ESTRAY_INVALID_STATE.value, 409)
    case = read_estray_case(scenario["case"]["id"])
    assert case["status"] == "IMPOUNDED"
    assert case["claim_denied_count"] == 0
    assert read_territory(scenario["territory"]["id"])["impound_current_head"] == 12


# ─── Closing out a sold case ──────────────────────────────────────────────────

def test_disbursement_forfeits_the_balance_when_nobody_claimed(api):
    """PRD §3.8: "When `claimant_owner_id` is null — nobody ever claimed, or the only
    claim was denied — the case moves `SOLD → FORFEITED_TO_BOARD`,
    `claimant_residual_cents` is set to 0, and `board_forfeiture_cents` takes the gross
    proceeds less the care cost less the handling fee."
    PRD §3.8: "After every write the conserved-quantity invariant holds: the gross amount
    equals the care cost plus the handling fee plus whichever of the claimant residual or
    the board forfeiture is in play."

    Design: Difficulty/compensating_invariant/estray_disbursement_restores_facility_head_count
    """
    scenario = setup_estray_sold_unclaimed()

    disbursed = validate_success(
        api.disburse_estray(scenario["case"]["id"], FEE_ADMIN), 200
    )

    assert disbursed["status"] == "FORFEITED_TO_BOARD"
    assert disbursed["care_cost_cents"] == 102300
    assert disbursed["handling_fee_cents"] == 11540
    assert disbursed["board_forfeiture_cents"] == 46160
    assert disbursed["claimant_residual_cents"] == 0
    assert (
        disbursed["care_cost_cents"]
        + disbursed["handling_fee_cents"]
        + disbursed["board_forfeiture_cents"]
        == 160000
    )
    assert_estray_distribution_conserved(disbursed)


def test_disbursement_vacates_only_the_disbursed_cases_head(api):
    """PRD §3.8: "Both exits vacate the facility identically: the district's
    `impound_current_head` falls by the case's `head_count`, its `intake_status` is
    recomputed, and the impounded lot moves to `lot_status` `VERIFIED` with `disposition`
    `CLEARED`."
    PRD §2.9: "Third, derived aggregates are recomputed from their source rows rather
    than adjusted incrementally, so that a compensating action returns an aggregate to
    exactly the value it held before the action it compensates."

    Design: Difficulty/compensating_invariant/estray_disbursement_restores_facility_head_count
    """
    scenario = setup_estray_sold_unclaimed()
    assert scenario["head_after_intake"] == 20
    assert_instant_equals(
        scenario["case"]["statutory_release_on"],
        "2026-08-25T00:00:00Z",
        "statutory_release_on",
    )

    validate_success(api.disburse_estray(scenario["case"]["id"], FEE_ADMIN), 200)

    territory = read_territory(scenario["territory"]["id"])
    assert territory["impound_current_head"] == 8, (
        "only the disbursed case vacates; the 8-head case is still on hand"
    )
    assert territory["intake_status"] == "OPEN"

    lot = read_lot(scenario["lot"]["id"])
    assert lot["lot_status"] == "VERIFIED"
    assert lot["disposition"] == "CLEARED"
    assert read_estray_case(scenario["second_case"]["id"])["status"] == "IMPOUNDED"
