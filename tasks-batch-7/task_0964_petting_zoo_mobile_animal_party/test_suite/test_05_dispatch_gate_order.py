"""Validation ordering conflicts: pipeline state validity masks the dispatch
business gates, and within dispatch the enumerated gate order decides which
error the caller sees (PRD §2.9, §3.8).
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    fixtures as fx,
)


# =====================================================================
# Difficulty/priority_pair_validation_conflict/state_beats_safety_on_dispatch_from_quoted
# =====================================================================
def test_dispatch_from_quoted_fails_state_check_even_with_pending_waiver(api):
    """PRD §2.9: "Requests are validated in a fixed pipeline, and earlier
    failures mask later ones"
    PRD §2.9: "**State validity** — the target resource is in a valid
    from-state for the requested transition, including the rule that terminal
    states accept no further transitions; failures are `ERR_INVALID_STATE`."
    PRD §3.8: "Event day begins with dispatch, the coordinator action that
    moves a `CONFIRMED` booking to `EN_ROUTE`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_dispatch_from_quoted
    """
    # 5 children: waiver is PENDING — yet the state check fires first.
    ctx = fx.setup_quoted_goat_booking(child_guest_count=5)
    resp = api.dispatch_booking(ctx["booking"]["id"], fx.COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert fx.get_booking(ctx["booking"]["id"])["status"] == "QUOTED"


def test_dispatch_from_quoted_fails_state_check_even_with_complete_waiver(api):
    """PRD §2.9: "Requests are validated in a fixed pipeline, and earlier
    failures mask later ones"
    PRD §2.9: "**State validity** — the target resource is in a valid
    from-state for the requested transition, including the rule that terminal
    states accept no further transitions; failures are `ERR_INVALID_STATE`."
    PRD §3.8: "Event day begins with dispatch, the coordinator action that
    moves a `CONFIRMED` booking to `EN_ROUTE`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_dispatch_from_quoted
    """
    ctx = fx.setup_quoted_goat_booking(child_guest_count=5)
    booking_id = ctx["booking"]["id"]
    # Complete the waiver so only the state violation remains.
    fx.sign_waiver(booking_id, ctx["customer"]["id"], 5)
    resp = api.dispatch_booking(booking_id, fx.COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert fx.get_booking(booking_id)["status"] == "QUOTED"


# =====================================================================
# Difficulty/priority_pair_validation_conflict/staff_constraint_beats_balance_fiscal_on_dispatch
# =====================================================================
def test_dispatch_without_staff_fails_ratio_before_balance_check(api):
    """PRD §3.8: "Three gates guard it, in this order: the waiver must be
    `COMPLETE` (`ERR_WAIVER_INCOMPLETE`); the count of `ASSIGNED` staff
    assignments must meet or exceed `required_staff_count`
    (`ERR_STAFF_RATIO_NOT_MET`); and `total_paid_cents` must meet or exceed
    `quoted_total_cents` — the event never rolls with an open balance
    (`ERR_BALANCE_UNPAID`)."
    PRD §2.9: "Within an endpoint, when §3 enumerates several business checks,
    the enumeration order is the evaluation order, so the first failing check
    is the one the caller sees."

    Design: Difficulty/priority_pair_validation_conflict/staff_constraint_beats_balance_fiscal_on_dispatch
    """
    # Waiver auto-COMPLETE (0 children), zero staff, balance 4872 < 16240:
    # the staff gate is enumerated before the fiscal gate, so it wins.
    ctx = fx.setup_confirmed_goat_booking()
    resp = api.dispatch_booking(ctx["booking"]["id"], fx.COORD)
    validate_error(resp, ApiErrorId.ERR_STAFF_RATIO_NOT_MET)
    assert fx.get_booking(ctx["booking"]["id"])["status"] == "CONFIRMED"


def test_dispatch_with_staff_but_unpaid_balance_fails_fiscal_gate(api):
    """PRD §3.8: "Three gates guard it, in this order: the waiver must be
    `COMPLETE` (`ERR_WAIVER_INCOMPLETE`); the count of `ASSIGNED` staff
    assignments must meet or exceed `required_staff_count`
    (`ERR_STAFF_RATIO_NOT_MET`); and `total_paid_cents` must meet or exceed
    `quoted_total_cents` — the event never rolls with an open balance
    (`ERR_BALANCE_UNPAID`)."
    PRD §2.9: "Within an endpoint, when §3 enumerates several business checks,
    the enumeration order is the evaluation order, so the first failing check
    is the one the caller sees."

    Design: Difficulty/priority_pair_validation_conflict/staff_constraint_beats_balance_fiscal_on_dispatch
    """
    ctx = fx.setup_confirmed_goat_booking()
    booking_id = ctx["booking"]["id"]
    handler = fx.create_handler("Hank", ["FIRST_AID"])
    # required_staff_count is 1 for the standard goat fixture: staff gate met.
    fx.assign_handler(booking_id, handler["id"], "LEAD")
    resp = api.dispatch_booking(booking_id, fx.COORD)
    # Now the first failing gate is the fiscal one: 4872 < 16240.
    validate_error(resp, ApiErrorId.ERR_BALANCE_UNPAID)
    assert fx.get_booking(booking_id)["status"] == "CONFIRMED"
