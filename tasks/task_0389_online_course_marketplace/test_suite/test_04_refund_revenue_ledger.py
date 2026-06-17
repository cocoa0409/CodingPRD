"""The refund cascade across enrollment, ledger, and instructor balances; the
compensating invariants on lifetime earnings and coupon redemptions; and the
window-expiry availability flip (PRD §2.7, §3.9).

Queue A: transitive_cascade (refund -> clawback -> balances), compensating_invariant
(lifetime_earned conserved; redeemed_count conserved). Queue B: window-expiry available
balance, enrollment_count reconciliation, refund-window-closed error.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    set_clock,
    create_instructor,
    create_learner,
    create_published_course,
    create_coupon,
    enroll_in_course,
    make_instructor_headers,
    make_learner_headers,
)


# ===========================================================================
# Queue A — transitive_cascade / refund_cascade_clawback_to_ledger_to_balances_depth3
# ===========================================================================
def test_refund_flips_sale_to_clawed_back_and_writes_refund_entry(api):
    """PRD §3.9: "The enrollment's originating `SALE` `RevenueLedgerEntry` flips from
    `PENDING` to `CLAWED_BACK`, and then a new `REFUND` entry is written with an
    `amount_cents` equal to the negative of the enrollment's `instructor_share_cents`".

    After refunding a 4000c enrollment (share 2000), the SALE entry is CLAWED_BACK and a
    REFUND entry of -2000 exists.

    Design: Difficulty/transitive_cascade/refund_cascade_clawback_to_ledger_to_balances_depth3
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, _ = create_published_course(instructor["id"], list_price_cents=4000,
                                        refund_window_days=30)
    enrollment = enroll_in_course(learner["id"], course["id"])
    validate_success(
        api.refund_enrollment(enrollment["id"], make_learner_headers(learner["id"])), 200
    )
    entries, _meta = _list_ledger_for_enrollment(api, instructor["id"], enrollment["id"])
    sale = next(e for e in entries if e["entry_type"] == "SALE")
    refund = next(e for e in entries if e["entry_type"] == "REFUND")
    assert sale["status"] == "CLAWED_BACK", "SALE entry flips PENDING->CLAWED_BACK on refund"
    assert refund["amount_cents"] == -2000, (
        f"REFUND entry == -instructor_share -2000, got {refund['amount_cents']}"
    )


def test_refund_recomputes_instructor_pending_and_lifetime_to_zero(api):
    """PRD §2.7: "The pending balance (`pending_balance_cents`) is the sum of
    `amount_cents` over the instructor's `SALE` entries whose status is `PENDING`." and
    "The lifetime earned figure (`lifetime_earned_cents`) is the sum of `amount_cents`
    over the instructor's entries whose `entry_type` is `SALE` or `REFUND` and whose
    status is anything other than `CLAWED_BACK`."

    After the clawback the SALE (+2000) is CLAWED_BACK and therefore excluded from the
    lifetime sum, while the REFUND (-2000) is included; pending == 0 (no PENDING SALE
    remains) and lifetime == -2000 (only the included REFUND of -2000 contributes).

    Design: Difficulty/transitive_cascade/refund_cascade_clawback_to_ledger_to_balances_depth3
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, _ = create_published_course(instructor["id"], list_price_cents=4000,
                                        refund_window_days=30)
    enrollment = enroll_in_course(learner["id"], course["id"])
    validate_success(
        api.refund_enrollment(enrollment["id"], make_learner_headers(learner["id"])), 200
    )
    inst = validate_success(
        api.get_instructor(instructor["id"], make_instructor_headers(instructor["id"])), 200
    )
    assert inst["pending_balance_cents"] == 0, (
        f"no PENDING SALE remains -> pending 0, got {inst['pending_balance_cents']}"
    )
    assert inst["lifetime_earned_cents"] == -2000, (
        f"SALE(clawed-back, excluded) + REFUND -2000 -> -2000, got {inst['lifetime_earned_cents']}"
    )


# ===========================================================================
# Queue A — compensating_invariant / refund_conserves_instructor_lifetime_earned
# ===========================================================================
def test_refund_conserves_lifetime_earned_at_presale_value(api):
    """PRD §2.7: "The lifetime earned figure (`lifetime_earned_cents`) is the sum of
    `amount_cents` over the instructor's entries whose `entry_type` is `SALE` or `REFUND`
    and whose status is anything other than `CLAWED_BACK`."

    SALE +2000 is excluded from the lifetime sum once it becomes CLAWED_BACK, while the
    compensating REFUND -2000 is included (status anything other than CLAWED_BACK); the
    formula therefore yields lifetime_earned == -2000. Pending and payout balances are 0.

    Design: Difficulty/compensating_invariant/refund_conserves_instructor_lifetime_earned
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, _ = create_published_course(instructor["id"], list_price_cents=4000,
                                        refund_window_days=30)
    enrollment = enroll_in_course(learner["id"], course["id"])
    validate_success(
        api.refund_enrollment(enrollment["id"], make_learner_headers(learner["id"])), 200
    )
    inst = validate_success(
        api.get_instructor(instructor["id"], make_instructor_headers(instructor["id"])), 200
    )
    assert inst["lifetime_earned_cents"] == -2000, (
        f"SALE(clawed-back, excluded) + REFUND(-2000, included) -> -2000, "
        f"got {inst['lifetime_earned_cents']}"
    )
    assert inst["pending_balance_cents"] == 0
    assert inst["payout_balance_cents"] == 0


def test_refund_leaves_no_payable_balance(api):
    """PRD §2.7: "The payable balance (`payout_balance_cents`) is the available credits
    minus the payouts-taken figure, floored at zero so it can never be negative."

    The refunded sale never reached AVAILABLE (it was clawed back while PENDING), so
    payout_balance_cents remains 0.

    Design: Difficulty/compensating_invariant/refund_conserves_instructor_lifetime_earned
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, _ = create_published_course(instructor["id"], list_price_cents=4000,
                                        refund_window_days=30)
    enrollment = enroll_in_course(learner["id"], course["id"])
    validate_success(
        api.refund_enrollment(enrollment["id"], make_learner_headers(learner["id"])), 200
    )
    inst = validate_success(
        api.get_instructor(instructor["id"], make_instructor_headers(instructor["id"])), 200
    )
    assert inst["payout_balance_cents"] == 0, (
        f"clawed-back sale yields no payable balance, got {inst['payout_balance_cents']}"
    )


# ===========================================================================
# Queue A — compensating_invariant / coupon_redeem_refund_conserves_redeemed_count
# ===========================================================================
def test_coupon_redeemed_count_conserved_after_refund(api):
    """PRD §3.9: "If the enrollment had redeemed a coupon, that coupon's `redeemed_count`
    is decremented".

    A coupon with redeemed_count 0, redeemed (+1) then the enrollment refunded (-1),
    returns redeemed_count to its pre-redemption value 0.

    Design: Difficulty/compensating_invariant/coupon_redeem_refund_conserves_redeemed_count
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, _ = create_published_course(instructor["id"], list_price_cents=5000,
                                        refund_window_days=30)
    coupon = create_coupon(instructor["id"], course["id"], code="THREE",
                           discount_type="FLAT", discount_value=1000, max_redemptions=3,
                           valid_from="2026-01-01T00:00:00Z", valid_until="2027-01-01T00:00:00Z")
    enrollment = enroll_in_course(learner["id"], course["id"], coupon_code="THREE")
    validate_success(
        api.refund_enrollment(enrollment["id"], make_learner_headers(learner["id"])), 200
    )
    after = validate_success(
        api.get_coupon(coupon["id"], make_instructor_headers(instructor["id"])), 200
    )
    assert after["redeemed_count"] == 0, (
        f"redeem +1 then refund -1 conserves redeemed_count at 0, got {after['redeemed_count']}"
    )


def test_coupon_stays_active_when_never_exhausted_after_refund(api):
    """PRD §3.5: "The coupon's `redeemed_count` begins at zero and tracks the number of
    non-`REFUNDED` enrollments that have redeemed it; the coupon's `status` begins
    `ACTIVE`."

    A max_redemptions=3 coupon redeemed once (never reaching the cap) stays ACTIVE through
    the refund, since it was never EXHAUSTED.

    Design: Difficulty/compensating_invariant/coupon_redeem_refund_conserves_redeemed_count
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, _ = create_published_course(instructor["id"], list_price_cents=5000,
                                        refund_window_days=30)
    coupon = create_coupon(instructor["id"], course["id"], code="THREE",
                           discount_type="FLAT", discount_value=1000, max_redemptions=3,
                           valid_from="2026-01-01T00:00:00Z", valid_until="2027-01-01T00:00:00Z")
    enrollment = enroll_in_course(learner["id"], course["id"], coupon_code="THREE")
    validate_success(
        api.refund_enrollment(enrollment["id"], make_learner_headers(learner["id"])), 200
    )
    after = validate_success(
        api.get_coupon(coupon["id"], make_instructor_headers(instructor["id"])), 200
    )
    assert after["status"] == "ACTIVE", "never exhausted -> remains ACTIVE"


# ===========================================================================
# Queue B — calculations / instructor_balance_available_after_window_expiry
# ===========================================================================
def test_window_expiry_moves_sale_into_payable_balance(api):
    """PRD §3.9: "Its single side effect is fiscal — the enrollment's originating `SALE`
    ledger entry flips from `PENDING` to `AVAILABLE`, which recomputes the instructor's
    `pending_balance_cents` and `payout_balance_cents`, moving that sale's share out of
    the provisional bucket and into the payable balance."

    A 4000c sale (share 2000) whose 5-day window has passed becomes EXPIRED on read, and
    the instructor's payout_balance_cents becomes 2000 with pending 0.

    Design: Corner/calculations/instructor_balance_available_after_window_expiry
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, _ = create_published_course(instructor["id"], list_price_cents=4000,
                                        refund_window_days=5)
    enrollment = enroll_in_course(learner["id"], course["id"])
    set_clock("2026-06-10T00:00:00Z")
    expired = validate_success(
        api.get_enrollment(enrollment["id"], make_learner_headers(learner["id"])), 200
    )
    assert expired["status"] == "EXPIRED", "refund window passed -> lazily EXPIRED"
    inst = validate_success(
        api.get_instructor(instructor["id"], make_instructor_headers(instructor["id"])), 200
    )
    assert inst["payout_balance_cents"] == 2000, (
        f"AVAILABLE flip makes the 2000 share payable, got {inst['payout_balance_cents']}"
    )
    assert inst["pending_balance_cents"] == 0


# ===========================================================================
# Queue B — cross_cutting_complexity_layers / derived_field_enrollment_count_reconciled_on_refund
# ===========================================================================
def test_course_enrollment_count_reconciled_on_refund(api):
    """PRD §3.9: "Finally the course's `enrollment_count` is decremented."

    Course.enrollment_count returns to 0 after the sole enrollment is refunded (REFUNDED
    enrollments are excluded from the count).

    Design: Corner/cross_cutting_complexity_layers/derived_field_enrollment_count_reconciled_on_refund
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, _ = create_published_course(instructor["id"], list_price_cents=1000,
                                        refund_window_days=30)
    enrollment = enroll_in_course(learner["id"], course["id"])
    validate_success(
        api.refund_enrollment(enrollment["id"], make_learner_headers(learner["id"])), 200
    )
    refreshed = validate_success(
        api.get_course(course["id"], make_instructor_headers(instructor["id"])), 200
    )
    assert refreshed["enrollment_count"] == 0, (
        f"refunded enrollment excluded -> count 0, got {refreshed['enrollment_count']}"
    )


# ===========================================================================
# Queue B — state_machines / refund_window_closed_returns_error
# ===========================================================================
def test_refund_after_window_closed_returns_error(api):
    """PRD §3.9: "A learner may self-refund (the `ACTIVE → REFUNDED` transition) while the
    enrollment is `ACTIVE` and the current clock is strictly before `refund_deadline`; a
    refund attempted at or after that instant is rejected with `ERR_REFUND_WINDOW_CLOSED`
    (HTTP 422)."

    Refunding an enrollment after its 5-day window (clock at 2026-06-10, deadline
    2026-06-06) is rejected.

    Design: Corner/state_machines/refund_window_closed_returns_error
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, _ = create_published_course(instructor["id"], list_price_cents=1000,
                                        refund_window_days=5)
    enrollment = enroll_in_course(learner["id"], course["id"])
    set_clock("2026-06-10T00:00:00Z")
    res = api.refund_enrollment(enrollment["id"], make_learner_headers(learner["id"]))
    validate_error(res, ApiErrorId.ERR_REFUND_WINDOW_CLOSED.value)


# ─── helper local to this module ───────────────────────────────────
def _list_ledger_for_enrollment(api, instructor_id, enrollment_id):
    from test_helpers import validate_paginated
    res = api.list_ledger_entries(
        make_instructor_headers(instructor_id), params={"enrollment_id": enrollment_id}
    )
    return validate_paginated(res)
