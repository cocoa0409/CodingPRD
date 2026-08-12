"""Benefit cycles, the benefit face formula, and the issuance waterfall
(PRD §3.4)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    assert_voucher,
    TEST_USERS,
    create_program, create_cycle, open_cycle, issue_cycle,
    setup_active_program, setup_enrollment, add_enrollment,
    setup_issued_voucher, setup_enrollment_with_tier,
    get_pool,
)
from test_helpers import api_client

ADMIN = TEST_USERS["program_admin_headers"]


def test_create_cycle_invalid_date_range_rejected(api):
    """PRD §3.4: "The window is half-open: the start date is included, the end
    date is excluded. The start must precede the end and the whole window must
    lie within the program's own window, otherwise `ERR_INVALID_DATE_RANGE`;
    and the new period must not overlap any existing cycle of the program —
    exact adjacency, where one cycle's `end_date` equals another's
    `start_date`, is allowed — otherwise `ERR_PERIOD_OVERLAP`."

    Design: Corner/validations/c_create_cycle_invalid_date_range
    """
    program = create_program()
    res = api.create_cycle(program["id"],
                           {"period_index": 1, "start_date": "2026-06-01",
                            "end_date": "2026-05-01"}, ADMIN)
    validate_error(res, "ERR_INVALID_DATE_RANGE")


def test_issue_second_run_issues_nothing_new(api):
    """PRD §3.4: "Because only enrollments without a voucher for the cycle are
    considered, re-running issuance on the same cycle issues nothing new to
    prior recipients."

    Design: Corner/state_machines/c_issue_second_run_idempotent
    """
    ctx = setup_issued_voucher()
    assert ctx["issue_result"]["issued_count"] == 1

    second = validate_success(api.issue_cycle(ctx["cycle"]["id"], ADMIN), 200)
    assert second["issued_count"] == 0
    assert second["total_face_value_cents"] == 0

    data, meta = validate_paginated(api.list_vouchers(
        ADMIN, params={"enrollment_id": ctx["enrollment_id"]}))
    assert meta["total_count"] == 1


def test_benefit_single_household_base_only(api):
    """PRD §3.4: "the base is `base_monthly_benefit_cents` plus one
    `household_increment_cents` for each household member beyond the first, up
    to that cap; the engagement tier then scales the base by 1.00 at T1, 1.10
    at T2, or 1.25 at T3; and an originating referral whose `priority` is
    URGENT adds a further 1.10 multiplier, while STANDARD adds none. The full
    product is rounded half up once to whole cents to give `face_value_cents`."

    Design: Corner/calculations/c_benefit_single_household_base_only
    """
    ctx = setup_enrollment(household_size=1)
    cycle = create_cycle(ctx["program"]["id"])
    open_cycle(cycle["id"])
    result = issue_cycle(cycle["id"])
    assert result["issued_count"] == 1
    assert result["total_face_value_cents"] == 10000


def test_issuance_waterfall_skips_unfunded_enrollment(api):
    """PRD §3.4: "If the pool's `available_cents` covers the face value, a
    voucher is created in ISSUED status with `redeemed_cents` at zero and
    `remaining_cents` equal to `face_value_cents`, stamped with the recipient
    `enrollment_id` and the issuing `benefit_cycle_id`, and the face value
    moves from the pool's `available_cents` into its `reserved_cents`. If the
    pool cannot cover it, the enrollment is skipped — its id is recorded in
    `skipped_enrollment_ids` — and the waterfall continues to the next
    candidate rather than aborting."

    Design: Corner/calculations/c_issuance_waterfall_skips_unfunded_enrollment
    """
    # Pool 20000: enrollment A (household 2 -> face 12500, created first) is
    # funded; enrollment B (household 4 -> face 17500, created second) exceeds
    # the remaining 7500 and is skipped.
    ctx = setup_enrollment(pool_committed_cents=20000, household_size=2,
                           patient_name="Pat A")
    _, _, enrollment_b = add_enrollment(ctx, household_size=4,
                                        patient_name="Pat B")
    cycle = create_cycle(ctx["program"]["id"])
    open_cycle(cycle["id"])
    result = issue_cycle(cycle["id"])

    assert result["issued_count"] == 1
    assert result["total_face_value_cents"] == 12500
    assert result["skipped_enrollment_ids"] == [enrollment_b]

    data, meta = validate_paginated(api.list_vouchers(
        ADMIN, params={"enrollment_id": enrollment_b}))
    assert meta["total_count"] == 0

    pool = get_pool(ctx["pool"]["id"])
    assert pool["available_cents"] == 7500
    assert pool["reserved_cents"] == 12500


def test_voucher_list_filter_by_enrollment(api):
    """PRD §3.4: "The vouchers listing accepts optional `enrollment_id` and
    `benefit_cycle_id` filters."

    Design: Corner/endpoints/c_voucher_list_filter_by_enrollment
    """
    ctx = setup_enrollment(household_size=2, patient_name="Pat A")
    _, _, enrollment_b = add_enrollment(ctx, household_size=3,
                                        patient_name="Pat B")
    cycle = create_cycle(ctx["program"]["id"])
    open_cycle(cycle["id"])
    result = issue_cycle(cycle["id"])
    assert result["issued_count"] == 2

    data, meta = validate_paginated(api.list_vouchers(
        ADMIN, params={"enrollment_id": ctx["enrollment_id"]}))
    assert meta["total_count"] == 1
    assert data[0]["enrollment_id"] == ctx["enrollment_id"]


# ---------------------------------------------------------------------------
# Depth instances: combinatorial benefit formula and cycle-period semantics
# ---------------------------------------------------------------------------

def _urgent_t2_capped_household_context():
    """Enrollment from an URGENT referral with household_size 9 (capped at the
    program's max 6), promoted to tier T2 by exactly 3 passed completions."""
    return setup_enrollment_with_tier(3, household_size=9, priority="URGENT",
                                      patient_name="Pat Nine")


def test_benefit_face_combines_household_cap_tier_and_priority(api):
    """PRD §3.4: "the household size used is the enrollment's `household_size`
    capped at the program's `max_household_size`; the base is
    `base_monthly_benefit_cents` plus one `household_increment_cents` for each
    household member beyond the first, up to that cap; the engagement tier then
    scales the base by 1.00 at T1, 1.10 at T2, or 1.25 at T3; and an
    originating referral whose `priority` is URGENT adds a further 1.10
    multiplier, while STANDARD adds none. The full product is rounded half up
    once to whole cents to give `face_value_cents`."

    Design: Difficulty/combinatorial_formula/benefit_face_tier_priority_household_cap
    """
    ctx = _urgent_t2_capped_household_context()
    cycle = create_cycle(ctx["program"]["id"])
    open_cycle(cycle["id"])
    result = issue_cycle(cycle["id"])
    assert result["issued_count"] == 1

    data, meta = validate_paginated(api.list_vouchers(
        ADMIN, params={"enrollment_id": ctx["enrollment_id"]}))
    assert meta["total_count"] == 1
    voucher = data[0]
    assert_voucher(voucher)
    # household 9 capped to 6 -> base 10000 + 5*2500 = 22500; T2 x1.10 and
    # URGENT x1.10 -> round_half_up(22500 * 1.10 * 1.10) == 27225.
    assert voucher["face_value_cents"] == 27225


def test_benefit_face_voucher_filter_returns_single_voucher(api):
    """PRD §3.4: "The full product is rounded half up once to whole cents to
    give `face_value_cents`." and "The vouchers listing accepts optional
    `enrollment_id` and `benefit_cycle_id` filters."
    PRD §3.6: "If the count is at least the program's `tier3_completions`, the
    tier is T3; otherwise, if it is at least `tier2_completions`, the tier is
    T2; otherwise it remains T1."

    Design: Difficulty/combinatorial_formula/benefit_face_tier_priority_household_cap
    """
    ctx = _urgent_t2_capped_household_context()
    enrollment = validate_success(
        api.get_enrollment(ctx["enrollment_id"], ADMIN), 200)
    assert enrollment["engagement_tier"] == "T2"
    assert enrollment["household_size"] == 9

    cycle = create_cycle(ctx["program"]["id"])
    open_cycle(cycle["id"])
    issue_cycle(cycle["id"])

    data, meta = validate_paginated(api.list_vouchers(
        ADMIN, params={"enrollment_id": ctx["enrollment_id"]}))
    assert meta["total_count"] == 1
    assert data[0]["face_value_cents"] == 27225
    assert data[0]["status"] == "ISSUED"


def _draft_program_with_cycle_1():
    program = create_program()
    cycle1 = create_cycle(program["id"], period_index=1,
                          start_date="2026-05-01", end_date="2026-06-01")
    return program, cycle1


def test_cycle_exact_adjacency_allowed(api):
    """PRD §3.4: "the new period must not overlap any existing cycle of the
    program — exact adjacency, where one cycle's `end_date` equals another's
    `start_date`, is allowed — otherwise `ERR_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/benefit_cycle_adjacent_periods_allowed_overlap_rejected
    """
    program, _cycle1 = _draft_program_with_cycle_1()
    cycle2 = validate_success(api.create_cycle(
        program["id"], {"period_index": 2, "start_date": "2026-06-01",
                        "end_date": "2026-07-01"}, ADMIN), 201)
    assert cycle2["status"] == "SCHEDULED"

    cycle4 = validate_success(api.create_cycle(
        program["id"], {"period_index": 4, "start_date": "2026-07-01",
                        "end_date": "2026-08-01"}, ADMIN), 201)
    assert cycle4["status"] == "SCHEDULED"


def test_cycle_interior_overlap_rejected(api):
    """PRD §3.4: "the new period must not overlap any existing cycle of the
    program — exact adjacency, where one cycle's `end_date` equals another's
    `start_date`, is allowed — otherwise `ERR_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/benefit_cycle_adjacent_periods_allowed_overlap_rejected
    """
    program, _cycle1 = _draft_program_with_cycle_1()
    validate_success(api.create_cycle(
        program["id"], {"period_index": 2, "start_date": "2026-06-01",
                        "end_date": "2026-07-01"}, ADMIN), 201)

    res = api.create_cycle(
        program["id"], {"period_index": 3, "start_date": "2026-05-15",
                        "end_date": "2026-06-15"}, ADMIN)
    validate_error(res, "ERR_PERIOD_OVERLAP")
