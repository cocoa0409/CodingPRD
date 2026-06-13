"""Bill issuance, weighted splitting, remainder ordering, payment, periods,
and the parallel payment/reminder dimensions.

Translates queue-A combinatorial_formula (bill_split remainder), dual_variant /
non_linear_state_machine (parallel dimensions), resource_temporal_overlap (RENT
period overlap), compensating_invariant (split recompute preserves total), plus
queue-B calculation/validation corner instances.
"""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
    validate_error,
    ApiErrorId,
    make_roommate_headers,
    make_operator_headers,
    create_bill_payload,
    build_household_with_members,
    issue_rent_bill,
    issue_utilities_bill,
    find_split_for_profile,
    set_clock,
)

api = api_client


def test_equal_split_remainder_assigned_by_created_at_ascending():
    """PRD §2.7: "The cents left over after flooring — always a non-negative number
    strictly smaller than the participant count — are then handed out one cent at a
    time, to participants taken in ascending order of their share row's `created_at`,
    until the remainder is exhausted."

    10001 cents EQUAL across M1, M2, M3 (created in that order) -> 3334, 3334, 3333.

    Design: Difficulty/combinatorial_formula/bill_split_rounding_remainder_order
    """
    env = build_household_with_members(
        api,
        [{"full_name": "M1"}, {"full_name": "M2"}, {"full_name": "M3"}],
        listing_overrides={"split_policy": "EQUAL", "capacity": 4},
    )
    m1, m2, m3 = env["members"]
    bill = issue_utilities_bill(api, env, total_amount_cents=10001)
    splits = validate_success(
        api.list_bill_splits(bill["id"], make_roommate_headers(env["lister"]["id"]))
    )
    assert find_split_for_profile(splits, m1["id"])["share_cents"] == 3334
    assert find_split_for_profile(splits, m2["id"])["share_cents"] == 3334
    assert find_split_for_profile(splits, m3["id"])["share_cents"] == 3333
    assert sum(s["share_cents"] for s in splits) == 10001


def test_equal_split_single_cent_remainder_to_earliest_member():
    """PRD §2.7: "The cents left over after flooring — always a non-negative number
    strictly smaller than the participant count — are then handed out one cent at a
    time, to participants taken in ascending order of their share row's `created_at`,
    until the remainder is exhausted."

    10000 cents EQUAL across M1, M2, M3 -> floor 3333 each (9999), remainder 1 to the
    earliest-created member M1 -> 3334, 3333, 3333.

    Design: Difficulty/combinatorial_formula/bill_split_rounding_remainder_order
    """
    env = build_household_with_members(
        api,
        [{"full_name": "E1"}, {"full_name": "E2"}, {"full_name": "E3"}],
        listing_overrides={"split_policy": "EQUAL", "capacity": 4},
    )
    m1, m2, m3 = env["members"]
    bill = issue_utilities_bill(api, env, total_amount_cents=10000)
    splits = validate_success(
        api.list_bill_splits(bill["id"], make_roommate_headers(env["lister"]["id"]))
    )
    assert find_split_for_profile(splits, m1["id"])["share_cents"] == 3334
    assert find_split_for_profile(splits, m2["id"])["share_cents"] == 3333
    assert find_split_for_profile(splits, m3["id"])["share_cents"] == 3333
    assert sum(s["share_cents"] for s in splits) == 10000


def test_by_income_weighting_splits_proportionally():
    """PRD §3.4: "under `BY_INCOME` a member's weight is the larger of 1 and their
    `monthly_income_cents`. With the total weight summed across members, each member's
    base share is the bill total multiplied by that member's weight, divided by the
    total weight, then floored to whole cents."

    10000 across incomes 600000:400000 -> 6000 and 4000.

    Design: Corner/calculations/bill_split_by_income_weighting
    """
    env = build_household_with_members(
        api,
        [
            {"full_name": "IncM1", "monthly_income_cents": 600_000},
            {"full_name": "IncM2", "monthly_income_cents": 400_000},
        ],
        listing_overrides={"split_policy": "BY_INCOME", "capacity": 3},
    )
    m1, m2 = env["members"]
    bill = issue_utilities_bill(api, env, total_amount_cents=10000)
    splits = validate_success(
        api.list_bill_splits(bill["id"], make_roommate_headers(env["lister"]["id"]))
    )
    assert find_split_for_profile(splits, m1["id"])["share_cents"] == 6000
    assert find_split_for_profile(splits, m2["id"])["share_cents"] == 4000


def test_rent_bill_period_overlap_rejected():
    """PRD §3.4: "Two rent bills for the same household may never cover overlapping
    periods: a new `RENT` bill whose closed `[period_start, period_end]` interval
    overlaps that of any existing `RENT` bill of the household is rejected with
    `ERR_BILL_PERIOD_OVERLAP`."

    June 1-30 then June 30-July 15 share the single day June 30.

    Design: Difficulty/resource_temporal_overlap/rent_bill_period_closed_interval_overlap
    """
    env = build_household_with_members(api, [{"full_name": "M1"}])
    issue_rent_bill(
        api, env, total_amount_cents=200_000,
        period_start="2026-06-01T00:00:00.000Z", period_end="2026-06-30T00:00:00.000Z",
    )
    resp = api.create_bill(
        create_bill_payload(
            env["household"]["id"], bill_type="RENT", total_amount_cents=200_000,
            period_start="2026-06-30T00:00:00.000Z", period_end="2026-07-15T00:00:00.000Z",
        ),
        make_roommate_headers(env["lister"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_BILL_PERIOD_OVERLAP.value)


def test_rent_bill_fully_contained_period_overlap_rejected():
    """PRD §3.4: "a new `RENT` bill whose closed `[period_start, period_end]` interval
    overlaps that of any existing `RENT` bill of the household is rejected with
    `ERR_BILL_PERIOD_OVERLAP`."

    A June 10-20 period sits fully inside an existing June 1-30 RENT period and overlaps
    it, so the second bill is rejected.

    Design: Difficulty/resource_temporal_overlap/rent_bill_period_closed_interval_overlap
    """
    env = build_household_with_members(api, [{"full_name": "Mc1"}])
    issue_rent_bill(
        api, env, total_amount_cents=200_000,
        period_start="2026-06-01T00:00:00.000Z", period_end="2026-06-30T00:00:00.000Z",
    )
    resp = api.create_bill(
        create_bill_payload(
            env["household"]["id"], bill_type="RENT", total_amount_cents=200_000,
            period_start="2026-06-10T00:00:00.000Z", period_end="2026-06-20T00:00:00.000Z",
        ),
        make_roommate_headers(env["lister"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_BILL_PERIOD_OVERLAP.value)


def test_bill_invalid_period_rejected():
    """PRD §3.4: "The billing period is a closed interval inclusive of both endpoints,
    and `period_end` must be strictly after `period_start`; a period that fails this is
    rejected with `ERR_INVALID_PERIOD`."

    Design: Corner/validations/bill_invalid_period_rejected
    """
    env = build_household_with_members(api, [{"full_name": "M1"}])
    resp = api.create_bill(
        create_bill_payload(
            env["household"]["id"], bill_type="RENT", total_amount_cents=200_000,
            period_start="2026-06-30T00:00:00.000Z", period_end="2026-06-01T00:00:00.000Z",
        ),
        make_roommate_headers(env["lister"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_PERIOD.value)


def test_reminder_and_payment_dimensions_advance_independently():
    """PRD §3.4: "The bill carries two independent status dimensions: a `payment_status`
    of `UNPAID`, `PARTIALLY_PAID`, or `PAID`, and a `reminder_status` of `NONE`,
    `SCHEDULED`, or `SENT`. The two advance independently of each other."
    PRD §3.8: "every `SCHEDULED` reminder whose `due_date` is at or before the current
    clock instant is moved to `SENT`, and where such a reminder targets a bill, that
    bill's `reminder_status` is advanced to `SENT` as well."

    Design: Difficulty/non_linear_state_machine/bill_parallel_payment_and_reminder_dimensions
    """
    env = build_household_with_members(
        api, [{"full_name": "M1"}], clock="2026-06-01T00:00:00.000Z",
        listing_overrides={"capacity": 3},
    )
    lh = make_roommate_headers(env["lister"]["id"])
    bill = issue_rent_bill(api, env, total_amount_cents=200_000)
    reminder = validate_success(
        api.create_payment_reminder(
            {"household_id": env["household"]["id"], "bill_id": bill["id"],
             "due_date": "2026-06-10T00:00:00.000Z"},
            lh,
        ),
        201,
    )
    set_clock(api, "2026-06-10T00:00:00.000Z")
    validate_success(api.dispatch_reminders(make_operator_headers()))

    bill_after = validate_success(api.get_bill(bill["id"], lh))
    assert bill_after["reminder_status"] == "SENT"
    assert bill_after["payment_status"] == "UNPAID"
    reminder_after = validate_success(api.get_payment_reminder(reminder["id"], lh))
    assert reminder_after["status"] == "SENT"


def test_scheduling_reminder_advances_only_reminder_dimension():
    """PRD §3.8: "When the reminder targets a bill and that bill's `reminder_status` is
    currently `NONE`, scheduling advances the bill's `reminder_status` to `SCHEDULED`;
    this reminder dimension moves independently of the bill's `payment_status`."

    After scheduling, reminder_status is SCHEDULED while payment_status is still UNPAID —
    the two parallel dimensions move without coupling.

    Design: Difficulty/non_linear_state_machine/bill_parallel_payment_and_reminder_dimensions
    """
    env = build_household_with_members(
        api, [{"full_name": "Par1"}], clock="2026-06-01T00:00:00.000Z",
        listing_overrides={"capacity": 3},
    )
    lh = make_roommate_headers(env["lister"]["id"])
    bill = issue_rent_bill(api, env, total_amount_cents=200_000)
    validate_success(
        api.create_payment_reminder(
            {"household_id": env["household"]["id"], "bill_id": bill["id"],
             "due_date": "2026-06-10T00:00:00.000Z"},
            lh,
        ),
        201,
    )
    bill_after = validate_success(api.get_bill(bill["id"], lh))
    assert bill_after["reminder_status"] == "SCHEDULED"
    assert bill_after["payment_status"] == "UNPAID"


def test_moveout_recompute_preserves_bill_total():
    """PRD §3.5: "Throughout, the bill's `total_amount_cents` continues to equal the sum
    of all `share_cents`."

    After a mid-period move-out the RENT bill's splits are recomputed; their sum still
    equals the unchanged total. (The exact per-member prorated split depends on
    move_in_date provenance, which the PRD does not pin, so only the conserved total is
    asserted here.)

    Design: Difficulty/compensating_invariant/bill_split_recompute_preserves_total
    """
    env = build_household_with_members(
        api,
        [{"full_name": "M1"}, {"full_name": "M2"}],
        listing_overrides={"split_policy": "EQUAL", "capacity": 3},
        clock="2026-06-01T00:00:00.000Z",
    )
    lh = make_roommate_headers(env["lister"]["id"])
    m2 = env["members"][1]
    mem2 = env["memberships"][1]
    bill = issue_rent_bill(api, env, total_amount_cents=200_000)

    set_clock(api, "2026-06-15T00:00:00.000Z")
    moved = validate_success(api.move_out_membership(mem2["id"], make_roommate_headers(m2["id"])))
    assert moved["status"] == "MOVED_OUT"

    bill_after = validate_success(api.get_bill(bill["id"], lh))
    assert bill_after["total_amount_cents"] == 200_000
    splits = validate_success(api.list_bill_splits(bill["id"], lh))
    assert sum(s["share_cents"] for s in splits) == 200_000


def test_moveout_recompute_preserves_bill_total_odd_amount():
    """PRD §3.5: "Throughout, the bill's `total_amount_cents` continues to equal the sum
    of all `share_cents`."

    A second arrangement with a non-round total (300001 cents) confirms the conserved
    quantity Bill.total_amount_cents == sum(BillSplit.share_cents) survives the
    post-move-out recompute.

    Design: Difficulty/compensating_invariant/bill_split_recompute_preserves_total
    """
    env = build_household_with_members(
        api,
        [{"full_name": "Od1"}, {"full_name": "Od2"}],
        listing_overrides={"split_policy": "EQUAL", "capacity": 3},
        clock="2026-06-01T00:00:00.000Z",
    )
    lh = make_roommate_headers(env["lister"]["id"])
    m2 = env["members"][1]
    mem2 = env["memberships"][1]
    bill = issue_rent_bill(api, env, total_amount_cents=300_001)

    set_clock(api, "2026-06-15T00:00:00.000Z")
    validate_success(api.move_out_membership(mem2["id"], make_roommate_headers(m2["id"])))

    bill_after = validate_success(api.get_bill(bill["id"], lh))
    assert bill_after["total_amount_cents"] == 300_001
    splits = validate_success(api.list_bill_splits(bill["id"], lh))
    assert sum(s["share_cents"] for s in splits) == 300_001
