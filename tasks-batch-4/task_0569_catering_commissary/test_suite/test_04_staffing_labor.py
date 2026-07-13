"""Staff assignments, labor rate calculation, overtime boundary, dispatch gate.

Translates queue-A instances (dual_variant_calc/staff_labor_scheduled_vs_actual_window,
transitive_cascade/staff_checkout_labor_bubbles_to_order,
priority_pair_validation_conflict/assign_staff_rolematch_beats_overlap,
boundary_precision_check/overtime_at_exactly_eight_hours) and queue-B corner instances
(calculations, validations).
"""
from test_helpers import validate_success, validate_error, ApiErrorId
from test_helpers import fixtures as fx
from test_helpers.constants import dt
from test_helpers.factories import create_staff_assignment_payload


# --------------------------------------------------------------------------
# Difficulty: dual_variant_calc / staff_labor_scheduled_vs_actual_window
# --------------------------------------------------------------------------
def test_scheduled_labor_from_shift_window(api, event_captain_headers):
    """PRD §3.6: "At creation, the assignment's `scheduled_labor_cents` is computed from
    the scheduled window."
    PRD §3.6: "the labor is the regular hours times the rate plus the overtime hours times
    the rate times 1.5, with the whole result rounded half up, once, to whole cents."

    Design: Difficulty/dual_variant_calc/staff_labor_scheduled_vs_actual_window
    """
    ctx = fx.offered_assignment(api, hourly_rate_cents=2000, shift_start=dt(10), shift_end=dt(16))  # 6h
    assert ctx["assignment"]["scheduled_labor_cents"] == 12000, (
        f"6h * 2000 = 12000, got {ctx['assignment']['scheduled_labor_cents']}"
    )


def test_actual_labor_from_clocked_window_with_overtime(api, event_captain_headers):
    """PRD §3.6: "computes `actual_labor_cents` using the identical labor formula but over
    the realized `actual_start`–`actual_end` window — a window that may cross the overtime
    threshold even when the scheduled one did not."
    PRD §3.6: "any hours strictly beyond 8.0 are overtime, paid at 1.5 times that rate."

    Design: Difficulty/dual_variant_calc/staff_labor_scheduled_vs_actual_window
    """
    ctx = fx.checked_in_assignment(api, hourly_rate_cents=2000, shift_start=dt(10),
                                   shift_end=dt(16), actual_start=dt(10))
    data = validate_success(api.checkout_assignment(ctx["assignment_id"], {"actual_end": dt(19)}, event_captain_headers))
    assert data["actual_labor_cents"] == 19000, (
        f"9h clocked: 8*2000 + 1*2000*1.5 = 19000, got {data['actual_labor_cents']}"
    )


# --------------------------------------------------------------------------
# Difficulty: transitive_cascade / staff_checkout_labor_bubbles_to_order
# --------------------------------------------------------------------------
def test_checkout_computes_actual_labor(api, event_captain_headers):
    """PRD §3.6: "check-out ... computes `actual_labor_cents` using the identical labor
    formula but over the realized `actual_start`–`actual_end` window"

    Design: Difficulty/transitive_cascade/staff_checkout_labor_bubbles_to_order
    """
    ctx = fx.checked_in_assignment(api, hourly_rate_cents=2000, shift_start=dt(10),
                                   shift_end=dt(16), actual_start=dt(10))
    data = validate_success(api.checkout_assignment(ctx["assignment_id"], {"actual_end": dt(19)}, event_captain_headers))
    assert data["actual_labor_cents"] == 19000, f"got {data['actual_labor_cents']}"


def test_checkout_bubbles_labor_to_order_total(api, event_captain_headers, sales_manager_headers):
    """PRD §3.6: "On check-out, the realized labor also bubbles up to the parent order:
    the order's `actual_labor_total_cents`, a running sum that starts at 0, is increased
    by this assignment's `actual_labor_cents`."

    Design: Difficulty/transitive_cascade/staff_checkout_labor_bubbles_to_order
    """
    ctx = fx.checked_in_assignment(api, hourly_rate_cents=2000, shift_start=dt(10),
                                   shift_end=dt(16), actual_start=dt(10))
    validate_success(api.checkout_assignment(ctx["assignment_id"], {"actual_end": dt(19)}, event_captain_headers))
    order = validate_success(api.get_event_order(ctx["order_id"], sales_manager_headers))
    assert order["actual_labor_total_cents"] == 19000, (
        f"order labor total must rise by 19000, got {order['actual_labor_total_cents']}"
    )


# --------------------------------------------------------------------------
# Difficulty: boundary_precision_check / overtime_at_exactly_eight_hours
# --------------------------------------------------------------------------
def test_exactly_eight_actual_hours_no_overtime(api, event_captain_headers):
    """PRD §3.6: "Overtime applies only to time strictly greater than the 8.0-hour
    threshold."

    Design: Difficulty/boundary_precision_check/overtime_at_exactly_eight_hours
    """
    ctx = fx.checked_in_assignment(api, hourly_rate_cents=2000, shift_start=dt(10),
                                   shift_end=dt(18), actual_start=dt(10))
    data = validate_success(api.checkout_assignment(ctx["assignment_id"], {"actual_end": dt(18)}, event_captain_headers))
    assert data["actual_labor_cents"] == 16000, (
        f"exactly 8h * 2000, no overtime = 16000, got {data['actual_labor_cents']}"
    )


def test_exactly_eight_scheduled_hours_no_overtime(api, event_captain_headers):
    """PRD §3.6: "regular hours are the lesser of the window length and 8.0, overtime
    hours are the window length minus 8.0 when positive and zero otherwise"

    Design: Difficulty/boundary_precision_check/overtime_at_exactly_eight_hours
    """
    ctx = fx.offered_assignment(api, hourly_rate_cents=2000, shift_start=dt(10), shift_end=dt(18))  # 8h
    assert ctx["assignment"]["scheduled_labor_cents"] == 16000, (
        f"exactly 8h * 2000, no overtime = 16000, got {ctx['assignment']['scheduled_labor_cents']}"
    )


# --------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / assign_staff_rolematch_beats_overlap
# --------------------------------------------------------------------------
def test_role_mismatch_reported_before_double_booking(api, event_captain_headers):
    """PRD §3.6: "The requested `staff_role` on the assignment must equal the staff
    member's own `staff_role`, or the offer is rejected with `ERR_STAFF_ROLE_MISMATCH`."
    PRD §2.6: "(6) business constraints such as requiring at least one order line for a
    quote (`ERR_NO_ORDER_LINES`) or matching staff roles (`ERR_STAFF_ROLE_MISMATCH`);
    ... (8) temporal conflict checks (`ERR_STAFF_DOUBLE_BOOKED`, `ERR_STATION_OVERBOOKED`)"

    Design: Difficulty/priority_pair_validation_conflict/assign_staff_rolematch_beats_overlap
    """
    ctx = fx.confirmed_order_with_staff(api, staff_role="BARTENDER", hourly_rate_cents=2500)
    validate_success(
        api.create_staff_assignment(
            create_staff_assignment_payload(ctx["order_id"], ctx["staff_member_id"],
                                            staff_role="BARTENDER", shift_start=dt(10), shift_end=dt(14)),
            event_captain_headers),
        201,
    )
    # New request both mismatches role (SERVER != BARTENDER) and overlaps the 10-14 shift.
    resp = api.create_staff_assignment(
        create_staff_assignment_payload(ctx["order_id"], ctx["staff_member_id"],
                                        staff_role="SERVER", shift_start=dt(13), shift_end=dt(15)),
        event_captain_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STAFF_ROLE_MISMATCH)


def test_role_mismatch_alone_rejected(api, event_captain_headers):
    """PRD §3.6: "The requested `staff_role` on the assignment must equal the staff
    member's own `staff_role`, or the offer is rejected with `ERR_STAFF_ROLE_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/assign_staff_rolematch_beats_overlap
    """
    ctx = fx.confirmed_order_with_staff(api, staff_role="BARTENDER", hourly_rate_cents=2500)
    resp = api.create_staff_assignment(
        create_staff_assignment_payload(ctx["order_id"], ctx["staff_member_id"],
                                        staff_role="SERVER", shift_start=dt(10), shift_end=dt(16)),
        event_captain_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STAFF_ROLE_MISMATCH)


# --------------------------------------------------------------------------
# Corner: calculations / validations
# --------------------------------------------------------------------------
def test_scheduled_labor_no_overtime_under_threshold(api, event_captain_headers):
    """PRD §3.6: "Hours up to a regular-time ceiling of 8.0 hours are paid at the staff
    member's `hourly_rate_cents`; any hours strictly beyond 8.0 are overtime, paid at 1.5
    times that rate."

    Design: Corner/calculations/scheduled_labor_no_overtime_under_threshold
    """
    ctx = fx.offered_assignment(api, hourly_rate_cents=2000, shift_start=dt(10), shift_end=dt(16))  # 6h
    assert ctx["assignment"]["scheduled_labor_cents"] == 12000


def test_staff_role_match_satisfaction_succeeds(api, event_captain_headers):
    """PRD §3.6: "The requested `staff_role` on the assignment must equal the staff
    member's own `staff_role`, or the offer is rejected with `ERR_STAFF_ROLE_MISMATCH`."
    PRD §3.6: "New assignments begin in `OFFERED` status."

    Design: Corner/validations/staff_role_match_satisfaction_succeeds
    """
    ctx = fx.confirmed_order_with_staff(api, staff_role="SERVER", hourly_rate_cents=2000)
    data = validate_success(
        api.create_staff_assignment(
            create_staff_assignment_payload(ctx["order_id"], ctx["staff_member_id"],
                                            staff_role="SERVER", shift_start=dt(10), shift_end=dt(16)),
            event_captain_headers),
        201,
    )
    assert data["status"] == "OFFERED", f"accepted assignment must be OFFERED, got {data['status']}"


def test_dispatch_without_confirmed_staff_returns_no_staff_confirmed(api, event_captain_headers):
    """PRD §3.7: "Dispatch is gated on staffing: the order must have at least one staff
    assignment in `CONFIRMED`, `CHECKED_IN`, or `CHECKED_OUT` status, or the request is
    rejected with `ERR_NO_STAFF_CONFIRMED`."

    Design: Corner/validations/dispatch_without_confirmed_staff_returns_no_staff_confirmed
    """
    ctx = fx.order_at_packed(api, run_portions=40)  # PACKED, no staff assignments
    validate_error(api.dispatch_order(ctx["order_id"], event_captain_headers), ApiErrorId.ERR_NO_STAFF_CONFIRMED)
