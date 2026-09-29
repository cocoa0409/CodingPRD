"""
Values sitting exactly on a stated threshold, and the values one step either side
of it.

Two thresholds are exercised. The per-issuance point cap is inclusive, so a
measured point count of exactly 5000 is accepted while 5001 is refused; the
interesting part is that the count being compared is the one produced by the
rounding discipline, not the raw base points. The lot expiry horizon is compared
inclusively against the logical clock, so a sweep one millisecond early does
nothing and a sweep at the exact instant expires the lot.
"""

from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_created,
    assert_error,
    assert_fields,
    assert_ok,
    assert_page,
)
from test_helpers.constants import (
    CLOCK_EPOCH,
    LOT_EXPIRED,
    LOT_OUTSTANDING,
    MEMBER_ACTIVE,
    MEMBER_DORMANT,
    STATE_TX,
    TIER_BASE,
    TIER_GOLD,
)
from test_helpers.test_users import ACCOUNTANT_HEADERS, CONTROLLER_HEADERS

# ─── The inclusive per-issuance point cap ────────────────────────────────────
# A GOLD member's tier multiplier is 12500 bp, so the measured count is the base
# points times 1.25 rounded half up: 4000 → 5000 exactly on the cap, 3999 → 4999
# just under it, 4001 → 5001 just over it.
POINT_CAP = 5000
ON_CAP_BASE_POINTS = 4000
ON_CAP_POINTS_ISSUED = 5000
ON_CAP_GROSS_SSP_CENTS = 6000
ON_CAP_RESERVE_CENTS = 1500
ON_CAP_DEFERRED_CENTS = 4500
ON_CAP_TIER_EXPENSE_CENTS = 1200

UNDER_CAP_BASE_POINTS = 3999
UNDER_CAP_TIER_POINTS = 4999
UNDER_CAP_POINTS_ISSUED = 4999
UNDER_CAP_GROSS_SSP_CENTS = 5999
UNDER_CAP_RESERVE_CENTS = 1500
UNDER_CAP_DEFERRED_CENTS = 4499
UNDER_CAP_TIER_EXPENSE_CENTS = 1200

OVER_CAP_BASE_POINTS = 4001

# Both accepted lots together, for the untouched-ledger assertions.
TWO_LOT_POINT_BALANCE = UNDER_CAP_POINTS_ISSUED + ON_CAP_POINTS_ISSUED
TWO_LOT_DEFERRED_CENTS = UNDER_CAP_DEFERRED_CENTS + ON_CAP_DEFERRED_CENTS

# ─── The inclusive lot expiry instant ───────────────────────────────────────
EXPIRY_DAYS = 730
ISSUE_INSTANT = "2026-08-05T00:00:00Z"
# 2026-08-05 advanced by 730 whole days, crossing the 2028 leap day.
EXPIRES_AT = "2028-08-04T00:00:00Z"
ONE_MILLISECOND_EARLY = "2028-08-03T23:59:59.999Z"

EXPIRING_BASE_POINTS = 1000
EXPIRING_POINTS = 1000
EXPIRING_GROSS_SSP_CENTS = 1200
EXPIRING_RESERVE_CENTS = 300
EXPIRING_DEFERRED_CENTS = 900

SWEEP_PERIOD_CODE = "2028-08"
SWEEP_PERIOD_START = "2028-08-01T00:00:00Z"
SWEEP_PERIOD_END = "2028-09-01T00:00:00Z"
DORMANCY_DAYS_AT_EXPIRY = 730


def _capped_issuance_ready(api):
    """An ACTIVE programme with a GOLD member and one OPEN period holding no lots."""
    fixtures.set_clock(api, CLOCK_EPOCH)
    program = fixtures.new_program(api, per_issuance_point_cap=POINT_CAP)
    fixtures.new_state_expiry_rule(api, program["id"])
    cohort = fixtures.new_cohort(api, program["id"])
    program = fixtures.activate(api, program["id"])
    member = fixtures.new_member(
        api, program["id"], cohort["id"], tier=TIER_GOLD, state_code=STATE_TX
    )
    period = fixtures.new_period(api, program["id"])
    return {
        "program": program,
        "cohort": cohort,
        "member": member,
        "period": period,
    }


def _issue(api, setup, base_points):
    """One issuance attempt, returned unchecked so a rejection can be inspected."""
    return api.create_point_lot(
        factories.point_lot_payload(
            setup["member"]["id"], setup["period"]["id"], base_points
        ),
        ACCOUNTANT_HEADERS,
    )


def _expiring_lot_ready(api):
    """
    One lot issued on 2026-08-05 under a 730-day horizon, plus the later period
    that will contain the sweep. Escheatment is switched off in the member's state
    so the expiry boundary is observed on its own.
    """
    fixtures.set_clock(api, CLOCK_EPOCH)
    program = fixtures.new_program(api, point_expiry_days=EXPIRY_DAYS)
    fixtures.new_state_expiry_rule(
        api,
        program["id"],
        state_code=STATE_TX,
        expiry_permitted=True,
        min_dormancy_days=0,
        escheatment_required=False,
        escheat_rate_bp=0,
    )
    cohort = fixtures.new_cohort(api, program["id"])
    program = fixtures.activate(api, program["id"])
    member = fixtures.new_member(
        api, program["id"], cohort["id"], tier=TIER_BASE, state_code=STATE_TX
    )
    issuing_period = fixtures.new_period(api, program["id"])

    fixtures.set_clock(api, ISSUE_INSTANT)
    lot = fixtures.issue_lot(
        api, member["id"], issuing_period["id"], EXPIRING_BASE_POINTS
    )

    sweep_period = fixtures.new_period(
        api,
        program["id"],
        period_code=SWEEP_PERIOD_CODE,
        start_at=SWEEP_PERIOD_START,
        end_at=SWEEP_PERIOD_END,
    )
    return {
        "program": program,
        "member": member,
        "issuing_period": issuing_period,
        "sweep_period": sweep_period,
        "lot": lot,
    }


# ─── The cap is inclusive at exactly five thousand points ───────────────────
def test_measured_points_exactly_on_the_cap_are_accepted(api):
    """
    The cap is compared against the measured point count, not the requested base
    points: 4000 base points at a 12500 bp tier multiplier measure to exactly 5000,
    which is the cap itself. An exclusive comparison would refuse this lot, so the
    acceptance — together with the full measurement chain it produces — is what
    pins the boundary as inclusive.

    "`per_issuance_point_cap`, at least 1, is the largest point count a single lot may carry once tier and promotional multipliers have been applied; the boundary is inclusive, so a lot whose measured point count lands exactly on the cap is accepted and only a strictly larger count is rejected with `ERR_ISSUANCE_CAP_EXCEEDED`."
    "Only once `points_issued` has been measured is the cap tested: a `points_issued` strictly greater than the programme's `per_issuance_point_cap` is rejected with `ERR_ISSUANCE_CAP_EXCEEDED`, and a value exactly equal to the cap passes."

    Design: Difficulty/boundary_precision_check/boundary_issuance_cap_inclusive_at_five_thousand
    """
    setup = _capped_issuance_ready(api)

    lot = assert_created(_issue(api, setup, ON_CAP_BASE_POINTS))
    assert_fields(
        lot,
        base_points=ON_CAP_BASE_POINTS,
        tier_points=ON_CAP_POINTS_ISSUED,
        points_issued=ON_CAP_POINTS_ISSUED,
        points_remaining=ON_CAP_POINTS_ISSUED,
        gross_ssp_cents=ON_CAP_GROSS_SSP_CENTS,
        breakage_reserve_cents=ON_CAP_RESERVE_CENTS,
        deferred_revenue_cents=ON_CAP_DEFERRED_CENTS,
        tier_benefit_expense_cents=ON_CAP_TIER_EXPENSE_CENTS,
        promo_expense_cents=0,
        lifecycle_state=LOT_OUTSTANDING,
    )


def test_the_rounded_count_one_point_under_the_cap_is_measured_in_full(api):
    """
    One base point fewer moves the measured count to 4999, one point under the cap,
    and every downstream figure follows from that rounded count rather than from the
    base points: the gross of 5998.8 millicent-cents rounds to 5999 and the reserve
    of 1499.75 rounds up to 1500, leaving 4499 deferred. This is the neighbour that
    makes the accepted 5000 case meaningful rather than a lucky pass.

    "`tier_points` is `base_points` multiplied by `tier_multiplier_bp_at_issue`, divided by 10000, and rounded half up to a whole number of points."
    "`gross_ssp_cents` is `points_issued` multiplied by `ssp_millicents_per_point_at_issue`, divided by 1000, rounded half up."
    "`breakage_reserve_cents` is `gross_ssp_cents` multiplied by `breakage_rate_bp_at_issue`, divided by 10000, rounded half up."
    "Rounding is uniform: every division named in this document is followed by rounding to a whole number using the round-half-up rule — a remainder of exactly one half rounds away from zero, upward in magnitude."

    Design: Difficulty/boundary_precision_check/boundary_issuance_cap_inclusive_at_five_thousand
    """
    setup = _capped_issuance_ready(api)

    lot = assert_created(_issue(api, setup, UNDER_CAP_BASE_POINTS))
    assert_fields(
        lot,
        base_points=UNDER_CAP_BASE_POINTS,
        tier_points=UNDER_CAP_TIER_POINTS,
        points_issued=UNDER_CAP_POINTS_ISSUED,
        gross_ssp_cents=UNDER_CAP_GROSS_SSP_CENTS,
        breakage_reserve_cents=UNDER_CAP_RESERVE_CENTS,
        deferred_revenue_cents=UNDER_CAP_DEFERRED_CENTS,
        tier_benefit_expense_cents=UNDER_CAP_TIER_EXPENSE_CENTS,
        promo_expense_cents=0,
        lifecycle_state=LOT_OUTSTANDING,
    )


def test_measured_points_one_point_above_the_cap_are_rejected(api):
    """
    All three neighbours are exercised against one period: 4999 and 5000 are booked,
    then 4001 base points measure to 5001 and are refused. Only a strictly larger
    count fails, and the refusal must be complete — the period holds exactly the two
    accepted lots, and its deferral is the sum of only those two.

    "`per_issuance_point_cap`, at least 1, is the largest point count a single lot may carry once tier and promotional multipliers have been applied; the boundary is inclusive, so a lot whose measured point count lands exactly on the cap is accepted and only a strictly larger count is rejected with `ERR_ISSUANCE_CAP_EXCEEDED`."
    "`deferred_revenue_cents` is `gross_ssp_cents` less `breakage_reserve_cents`, and it is this deferral — not the gross — that is added to the period's `issuance_deferred_cents`."

    Design: Difficulty/boundary_precision_check/boundary_issuance_cap_inclusive_at_five_thousand
    """
    setup = _capped_issuance_ready(api)
    under = assert_created(_issue(api, setup, UNDER_CAP_BASE_POINTS))
    on_cap = assert_created(_issue(api, setup, ON_CAP_BASE_POINTS))

    rejected = _issue(api, setup, OVER_CAP_BASE_POINTS)
    assert_error(rejected, ApiErrorId.ISSUANCE_CAP_EXCEEDED.value)

    assert_page(
        api.list_point_lots(ACCOUNTANT_HEADERS, period_id=setup["period"]["id"]),
        expected_ids=[under["id"], on_cap["id"]],
        total_count=2,
    )
    member = assert_ok(api.get_member(setup["member"]["id"], ACCOUNTANT_HEADERS))
    assert_fields(member, point_balance=TWO_LOT_POINT_BALANCE)
    period = assert_ok(api.get_period(setup["period"]["id"], CONTROLLER_HEADERS))
    assert_fields(period, issuance_deferred_cents=TWO_LOT_DEFERRED_CENTS)


# ─── Expiry fires at exactly the expires_at instant ─────────────────────────
def test_the_expiry_horizon_is_whole_days_added_across_a_leap_day(api):
    """
    The horizon is 730 whole 24-hour days added to the issuance instant, and the span
    from 2026-08-05 contains the 2028 leap day, so calendar-month arithmetic or a
    365-day year would land on a different date. The instant this lot pins is what
    the two sweeps either side of it are measured against.

    "`issued_at` takes the current logical clock reading, and `expires_at` is set to `issued_at` advanced by the programme's `point_expiry_days` whole days."
    "When a lot's expiry horizon is described as a number of days after issuance, or a statement's due date as a number of days after a period ends, the computation adds that many 24-hour days to the base instant."
    "Calendar arithmetic is always in whole days on that logical clock."

    Design: Difficulty/boundary_precision_check/boundary_lot_expiry_at_exact_expires_at_instant
    """
    setup = _expiring_lot_ready(api)

    assert_fields(
        setup["lot"],
        issued_at=ISSUE_INSTANT,
        expires_at=EXPIRES_AT,
        points_issued=EXPIRING_POINTS,
        points_remaining=EXPIRING_POINTS,
        gross_ssp_cents=EXPIRING_GROSS_SSP_CENTS,
        breakage_reserve_cents=EXPIRING_RESERVE_CENTS,
        deferred_revenue_cents=EXPIRING_DEFERRED_CENTS,
        lifecycle_state=LOT_OUTSTANDING,
    )


def test_a_sweep_one_millisecond_before_the_expiry_instant_does_nothing(api):
    """
    With the clock one millisecond short of the lot's expiry instant the lot is not
    yet a candidate, so the sweep must be a complete no-op: the lot keeps its full
    balance and its outstanding state, the swept period books no release, and the
    member is not swept into dormancy. Millisecond precision matters here because a
    comparison truncated to whole seconds would wrongly expire the lot.

    "A point lot whose `expires_at` is `2028-08-04T00:00:00Z` is not yet expirable when the clock reads `2028-08-03T23:59:59.999Z`, and becomes expirable at exactly `2028-08-04T00:00:00Z`."
    "Candidates are the programme's lots whose `lifecycle_state` is `OUTSTANDING` or `PARTIALLY_REDEEMED` and whose `expires_at` is at or before the clock reading; the comparison is inclusive, so a lot whose `expires_at` is exactly the current clock reading is eligible while one an instant later is not."

    Design: Difficulty/boundary_precision_check/boundary_lot_expiry_at_exact_expires_at_instant
    """
    setup = _expiring_lot_ready(api)
    fixtures.set_clock(api, ONE_MILLISECOND_EARLY)

    assert_ok(
        api.run_expiry_sweep(setup["sweep_period"]["id"], None, ACCOUNTANT_HEADERS)
    )

    lot = assert_ok(api.get_point_lot(setup["lot"]["id"], ACCOUNTANT_HEADERS))
    assert_fields(
        lot,
        lifecycle_state=LOT_OUTSTANDING,
        points_remaining=EXPIRING_POINTS,
        expired_gross_ssp_cents=0,
        escheated_cents=0,
        version=setup["lot"]["version"],
    )
    sweep_period = assert_ok(
        api.get_period(setup["sweep_period"]["id"], CONTROLLER_HEADERS)
    )
    assert_fields(sweep_period, expiry_released_cents=0, escheat_accrual_cents=0)
    member = assert_ok(api.get_member(setup["member"]["id"], ACCOUNTANT_HEADERS))
    assert_fields(
        member, status=MEMBER_ACTIVE, point_balance=EXPIRING_POINTS
    )


def test_a_sweep_at_exactly_the_expiry_instant_expires_the_lot(api):
    """
    Advancing the clock by that single millisecond, to exactly the lot's expiry
    instant, makes the lot a candidate and the whole expiry pass runs: the gross and
    the deferral are captured before the balance is zeroed, the release lands in the
    swept period rather than the issuing one, escheatment stays off so the lot rests
    at EXPIRED, and the emptied member — dormant for exactly 730 days — is swept
    into DORMANT.

    "A point lot whose `expires_at` is `2028-08-04T00:00:00Z` is not yet expirable when the clock reads `2028-08-03T23:59:59.999Z`, and becomes expirable at exactly `2028-08-04T00:00:00Z`."
    "The captured released deferral is added to the **swept** period's `expiry_released_cents`, and the lot's `version` increments by 1."
    "When `escheatment_required` is false, `escheated_cents` stays 0 and the lot rests at `EXPIRED`."
    "A member whose `status` is `ACTIVE`, whose `point_balance` is 0 after the pass, and whose `dormancy_days` is at least 730 — two years since `last_activity_at` — moves `ACTIVE → DORMANT` with `version` incremented by 1."

    Design: Difficulty/boundary_precision_check/boundary_lot_expiry_at_exact_expires_at_instant
    """
    setup = _expiring_lot_ready(api)
    fixtures.set_clock(api, EXPIRES_AT)

    assert_ok(
        api.run_expiry_sweep(setup["sweep_period"]["id"], None, ACCOUNTANT_HEADERS)
    )

    lot = assert_ok(api.get_point_lot(setup["lot"]["id"], ACCOUNTANT_HEADERS))
    assert_fields(
        lot,
        lifecycle_state=LOT_EXPIRED,
        points_remaining=0,
        expired_gross_ssp_cents=EXPIRING_GROSS_SSP_CENTS,
        escheated_cents=0,
    )
    sweep_period = assert_ok(
        api.get_period(setup["sweep_period"]["id"], CONTROLLER_HEADERS)
    )
    assert_fields(
        sweep_period,
        expiry_released_cents=EXPIRING_DEFERRED_CENTS,
        escheat_accrual_cents=0,
    )
    issuing_period = assert_ok(
        api.get_period(setup["issuing_period"]["id"], CONTROLLER_HEADERS)
    )
    assert_fields(issuing_period, expiry_released_cents=0)

    program = assert_ok(api.get_program(setup["program"]["id"], CONTROLLER_HEADERS))
    assert_fields(
        program, total_escheat_accrual_cents=0, escheat_disclosure_required=False
    )
    member = assert_ok(api.get_member(setup["member"]["id"], ACCOUNTANT_HEADERS))
    assert_fields(
        member,
        status=MEMBER_DORMANT,
        point_balance=0,
        dormancy_days=DORMANCY_DAYS_AT_EXPIRY,
    )
