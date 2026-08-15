"""Monthly billing: the PROVISIONAL vs FINAL credit variants, tier-straddling
marginal sums, calendar-day proration on mid-period activation, the charges
cap, bill lifecycle guards, and per-period uniqueness."""
from test_helpers import (
    ApiErrorId,
    activate_subscription,
    assert_bill,
    create_bill,
    create_subscription,
    get_bill,
    get_program,
    issue_bill,
    set_clock,
    setup_active_subscription,
    setup_open_program,
    validate_error,
    validate_success,
)

from test_helpers import TEST_USERS

PM = TEST_USERS["program_manager_headers"]

TIERS_5_7_9 = [
    {"up_to_kwh": 500, "rate_cents_per_kwh": 5},
    {"up_to_kwh": 2000, "rate_cents_per_kwh": 7},
    {"up_to_kwh": None, "rate_cents_per_kwh": 9},
]
TIERS_5_7 = [
    {"up_to_kwh": 500, "rate_cents_per_kwh": 5},
    {"up_to_kwh": 2000, "rate_cents_per_kwh": 7},
]


def _billable_setup(activate_at="2026-07-01T00:00:00Z", rate_tiers=None,
                    allocation_kw=10, estimated_usage_kwh=800):
    """OPEN program + ACTIVE subscription; clock lands on 2026-08-01 so July
    bills are creatable. deemed = allocation_kw * 100 (default)."""
    setup = setup_active_subscription(
        allocation_kw=allocation_kw,
        estimated_usage_kwh=estimated_usage_kwh,
        activate_at=activate_at,
        rate_tiers=rate_tiers or TIERS_5_7_9,
    )
    set_clock("2026-08-01T00:00:00Z")
    return setup


# ---------------------------------------------------------------------------
# PROVISIONAL vs FINAL credit variants on the same bill
# ---------------------------------------------------------------------------

def test_bill_provisional_credit_ignores_actual_usage_proration_and_cap(api):
    """PRD §3.6: "The PROVISIONAL variant runs at bill creation. Its usage
    figure is the subscription's declared `estimated_usage_kwh`; it applies
    no proration and no cap against charges, and its result is stored in
    `provisional_credit_cents`." and "A new bill lands in `DRAFT` status with
    `issued_credit_cents`, the proration fields, and `issued_at` unset — but
    its `provisional_credit_cents` is computed immediately, at creation, per
    the PROVISIONAL variant below."

    Design: Difficulty/dual_variant_calc/bill_credit_provisional_vs_final
    """
    setup = _billable_setup()
    bill = create_bill(
        setup["subscription"]["id"], period_month="2026-07",
        usage_kwh=1500, charges_cents=20000,
    )
    assert_bill(bill)
    assert bill["status"] == "DRAFT"
    # eligible = min(estimated 800, deemed 10*100) = 800
    # tiers: 500*5 + 300*7 = 2500 + 2100 = 4600
    assert bill["provisional_credit_cents"] == 4600
    assert bill["issued_credit_cents"] is None
    assert bill["proration_active_days"] is None
    assert bill["issued_at"] is None


def test_bill_final_credit_uses_actual_usage_tiers_and_cap(api):
    """PRD §3.6: "The FINAL variant runs at issue and reissue. Its usage
    figure is the bill's actual `usage_kwh`; ... and the final credit is the
    smaller of the prorated amount and the bill's `charges_cents`."

    Design: Difficulty/dual_variant_calc/bill_credit_provisional_vs_final
    """
    setup = _billable_setup()
    bill = create_bill(
        setup["subscription"]["id"], period_month="2026-07",
        usage_kwh=1500, charges_cents=20000,
    )
    issued = issue_bill(bill["id"])
    assert issued["status"] == "ISSUED"
    # eligible = min(actual 1500, deemed 1000) = 1000
    # base: 500*5 + 500*7 = 6000; active all 31 of 31 days -> 6000;
    # cap min(6000, 20000) -> 6000
    assert issued["issued_credit_cents"] == 6000
    assert issued["provisional_credit_cents"] == 4600, (
        "the provisional figure is not rewritten by issue"
    )
    assert issued["issued_credit_cents"] - issued["provisional_credit_cents"] == 1400, (
        "the two variants over identical subscription data diverge by 1400 cents"
    )
    assert issued["issued_at"] is not None


# ---------------------------------------------------------------------------
# Tier straddle combined with mid-period proration
# ---------------------------------------------------------------------------

def test_final_credit_prorated_for_mid_period_activation(api):
    """PRD §3.6: "after the tier sum, the base credit is prorated by calendar
    days — the number of days of the `period_month` during which the
    subscription held `ACTIVE` or `SUSPENDED` status for any part of the day,
    derived from its `activated_at` and `terminated_at` against the period
    bounds ... The proration divides the base credit by the calendar days in
    the period and multiplies by the active days, rounding half-up to a whole
    cent".

    Design: Difficulty/combinatorial_formula/bill_credit_tier_straddle_with_proration
    """
    setup = _billable_setup(activate_at="2026-07-16T00:00:00Z")
    bill = create_bill(
        setup["subscription"]["id"], period_month="2026-07",
        usage_kwh=1500, charges_cents=20000,
    )
    issued = issue_bill(bill["id"])
    # Active July 16..31 inclusive = 16 of 31 days.
    assert issued["proration_active_days"] == 16
    assert issued["proration_days_in_period"] == 31
    # base 6000 (tier straddle 500*5 + 500*7); round_half_up(6000*16/31)
    # = round_half_up(3096.774...) = 3097
    assert issued["issued_credit_cents"] == 3097


def test_provisional_credit_ignores_proration(api):
    """PRD §3.6: "it applies no proration and no cap against charges" — the
    PROVISIONAL figure for the same mid-period-activated subscription is the
    plain tier sum over the estimated usage.

    Design: Difficulty/combinatorial_formula/bill_credit_tier_straddle_with_proration
    """
    setup = _billable_setup(activate_at="2026-07-16T00:00:00Z")
    bill = create_bill(
        setup["subscription"]["id"], period_month="2026-07",
        usage_kwh=1500, charges_cents=20000,
    )
    # eligible = min(estimated 800, deemed 1000) = 800 -> 500*5 + 300*7 = 4600
    assert bill["provisional_credit_cents"] == 4600, (
        "PROVISIONAL uses estimated usage with no proration and no cap, even "
        "though the FINAL variant for the same bill prorates"
    )


# ---------------------------------------------------------------------------
# Marginal tier boundary at 500 kWh
# ---------------------------------------------------------------------------

def test_bill_tier_boundary_500_and_501(api):
    """PRD §3.6: "walk the program's `rate_tiers` in ascending order of
    `up_to_kwh`, and let each tier contribute the number of eligible
    kilowatt-hours falling inside its band — the smaller of the remaining
    eligible energy and the tier's width, where the first tier's band starts
    at zero and a null `up_to_kwh` is unbounded — multiplied by that tier's
    `rate_cents_per_kwh`, in exact integer cents."

    Design: Corner/calculations/bill_tier_boundary_500_and_501
    """
    setup = _billable_setup(activate_at="2026-05-01T00:00:00Z",
                            rate_tiers=TIERS_5_7)
    sub_id = setup["subscription"]["id"]
    b1 = create_bill(sub_id, period_month="2026-06", usage_kwh=500,
                     charges_cents=100000)
    b2 = create_bill(sub_id, period_month="2026-07", usage_kwh=501,
                     charges_cents=100000)

    issued1 = issue_bill(b1["id"])
    issued2 = issue_bill(b2["id"])
    # Both months fully active (subscription ACTIVE since 2026-05-01), so
    # proration is identity; eligible = usage (both under deemed 1000).
    assert issued1["issued_credit_cents"] == 2500, (
        "exactly 500 kWh prices entirely inside tier 1: 500 * 5"
    )
    assert issued2["issued_credit_cents"] == 2507, (
        "the 501st kWh is marginal at the tier-2 rate: 500*5 + 1*7"
    )


# ---------------------------------------------------------------------------
# Bill lifecycle guards and per-period uniqueness
# ---------------------------------------------------------------------------

def test_bill_issue_twice_and_dispute_draft_rejected(api):
    """PRD §3.6: "Any issue, dispute, reissue, or void attempted from a state
    the transition does not allow is rejected with `ERR_BILL_STATE_INVALID`."
    and "Issuing a `DRAFT` bill moves it to `ISSUED`" / "A customer dispute
    moves an `ISSUED` bill to `DISPUTED`".

    Design: Corner/state_machines/bill_issue_twice_and_dispute_draft_rejected
    """
    setup = _billable_setup()
    bill = create_bill(setup["subscription"]["id"], period_month="2026-07",
                       usage_kwh=1500, charges_cents=20000)

    resp_dispute = api.dispute_bill(bill["id"], {"reason": "too early"},
                                    PM)
    validate_error(resp_dispute, ApiErrorId.ERR_BILL_STATE_INVALID, expected_status=409)

    issued = issue_bill(bill["id"])
    assert issued["status"] == "ISSUED"

    resp_issue2 = api.issue_bill(bill["id"], PM)
    validate_error(resp_issue2, ApiErrorId.ERR_BILL_STATE_INVALID, expected_status=409)


def test_duplicate_bill_blocked_until_void(api):
    """PRD §3.6: "At most one non-`VOID` bill may exist for a given
    subscription and period month: a second one is rejected with
    `ERR_DUPLICATE_BILL`." and "A bill in `DRAFT` or `DISPUTED` may be voided
    into the terminal `VOID` state."

    Design: Corner/validations/duplicate_bill_blocked_until_void
    """
    setup = _billable_setup()
    sub_id = setup["subscription"]["id"]
    b1 = create_bill(sub_id, period_month="2026-07", usage_kwh=900,
                     charges_cents=20000)

    resp = api.create_bill(
        {"subscription_id": sub_id, "period_month": "2026-07",
         "usage_kwh": 950, "charges_cents": 21000},
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_BILL, expected_status=409)

    voided = validate_success(api.void_bill(b1["id"], PM))
    assert voided["status"] == "VOID"

    b2 = create_bill(sub_id, period_month="2026-07", usage_kwh=950,
                     charges_cents=21000)
    assert_bill(b2)
    assert b2["status"] == "DRAFT", "a VOID bill no longer blocks the period"


def test_bill_on_waitlisted_subscription_rejected(api):
    """PRD §3.6: "The subscription must be `ACTIVE` or `SUSPENDED` — billing
    a `PENDING`, `WAITLISTED`, or `TERMINATED` subscription is rejected with
    `ERR_SUBSCRIPTION_STATE_INVALID`".

    Design: Corner/validations/bill_on_waitlisted_subscription_rejected
    """
    setup = setup_open_program(capacity_cap_kw=10)
    program = setup["program"]
    s1 = create_subscription(program["id"], allocation_kw=10,
                             utility_account_no="U-A")
    activate_subscription(s1["id"])
    s2 = create_subscription(program["id"], allocation_kw=5,
                             utility_account_no="U-B")
    parked = activate_subscription(s2["id"])
    assert parked["status"] == "WAITLISTED"

    resp = api.create_bill(
        {"subscription_id": s2["id"], "period_month": "2026-07",
         "usage_kwh": 400, "charges_cents": 8000},
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_STATE_INVALID, expected_status=409)

    bills = validate_success(
        api.list_bills(PM, params={"subscription_id": s2["id"]})
    )
    assert bills == [], "no bill row is created for a WAITLISTED subscription"
