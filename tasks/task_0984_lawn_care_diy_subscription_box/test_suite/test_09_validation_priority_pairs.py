"""Validation precedence: state vs temporal, weather safety vs temporal
(PRD 2.8)."""
import test_helpers as th

ADMIN = th.TEST_USERS["platform_admin_headers"]


def _setup_task(api, email, applied=False):
    """Delivered box (FERT-01 x1) with one task on 2026-06-10; optionally
    marked APPLIED."""
    ctx = th.setup_active_subscription(email=email)
    box, _ = th.setup_delivered_box(ctx, lines=[th.shipment_line("FERT-01", 1)])
    task = th.validate_success(
        api.create_application(
            th.application_payload(ctx["subscription"]["id"], box["id"],
                                   product_sku="FERT-01",
                                   scheduled_date="2026-06-10"),
            ctx["customer_headers"],
        ),
        201,
    )
    if applied:
        th.validate_success(api.mark_applied(task["id"], ctx["customer_headers"]))
    return ctx, box, task


def test_reschedule_state_error_beats_window_violation(api):
    """PRD 2.8: "So a missing header surfaces before any role check, a role failure before ownership, ownership before existence, existence before state, state before the weather gate, the weather gate before temporal windows, temporal windows before constraint checks, and constraint checks before cross-entity referential checks."
    PRD 3.7: "Rescheduling is a self-loop on `SCHEDULED`: the task must be `SCHEDULED` (`ERR_APPLICATION_NOT_SCHEDULED`, HTTP 409), the acting customer must own the task's subscription, and the `new_date` must pass all three guards above."

    Design: Difficulty/priority_pair_validation_conflict/reschedule_state_beats_window_temporal
    """
    ctx, _, task = _setup_task(api, email="pp1@x.com", applied=True)
    # 2026-12-25 is outside the FERT-01 window AND the task is APPLIED; the
    # state precondition (priority 5) must surface before temporal (priority 7).
    th.validate_error(
        api.reschedule_application(task["id"], {"new_date": "2026-12-25"},
                                   ctx["customer_headers"]),
        th.ApiErrorId.ERR_APPLICATION_NOT_SCHEDULED,
    )


def test_window_violation_surfaces_when_state_is_ok(api):
    """PRD 2.8: "So a missing header surfaces before any role check, a role failure before ownership, ownership before existence, existence before state, state before the weather gate, the weather gate before temporal windows, temporal windows before constraint checks, and constraint checks before cross-entity referential checks."
    PRD 3.7: "the scheduled date must fall on or after `window_start_date` and strictly before `window_end_date`, otherwise `ERR_APPLICATION_WINDOW_VIOLATION` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/reschedule_state_beats_window_temporal
    """
    ctx, _, task = _setup_task(api, email="pp1b@x.com", applied=False)
    # Only the temporal rule fails here (state is SCHEDULED, no advisory on
    # 2026-12-25), isolating ERR_APPLICATION_WINDOW_VIOLATION.
    th.validate_error(
        api.reschedule_application(task["id"], {"new_date": "2026-12-25"},
                                   ctx["customer_headers"]),
        th.ApiErrorId.ERR_APPLICATION_WINDOW_VIOLATION,
    )


def test_weather_gate_beats_window_violation(api):
    """PRD 2.8: "So a missing header surfaces before any role check, a role failure before ownership, ownership before existence, existence before state, state before the weather gate, the weather gate before temporal windows, temporal windows before constraint checks, and constraint checks before cross-entity referential checks."
    PRD 3.7: "A blocked date is rejected with `ERR_WEATHER_GATE_BLOCKED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/weather_safety_beats_window_temporal
    """
    ctx, box, _ = _setup_task(api, email="pp2@x.com")
    th.get_success_data(
        api.create_weather_advisory(
            th.weather_advisory_payload(region="NE-OH", date="2026-12-25",
                                        rain_probability=0.90),
            ADMIN,
        )
    )
    # 2026-12-25 is both weather-blocked (rain 0.90) and outside the product
    # window; the weather gate (priority 6) precedes temporal (priority 7).
    th.validate_error(
        api.create_application(
            th.application_payload(ctx["subscription"]["id"], box["id"],
                                   product_sku="FERT-01",
                                   scheduled_date="2026-12-25"),
            ctx["customer_headers"],
        ),
        th.ApiErrorId.ERR_WEATHER_GATE_BLOCKED,
    )


def test_window_violation_surfaces_when_weather_is_benign(api):
    """PRD 2.8: "So a missing header surfaces before any role check, a role failure before ownership, ownership before existence, existence before state, state before the weather gate, the weather gate before temporal windows, temporal windows before constraint checks, and constraint checks before cross-entity referential checks."
    PRD 3.7: "the scheduled date must fall on or after `window_start_date` and strictly before `window_end_date`, otherwise `ERR_APPLICATION_WINDOW_VIOLATION` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/weather_safety_beats_window_temporal
    """
    ctx, box, _ = _setup_task(api, email="pp2b@x.com")
    # Benign advisory: gate passes, so the temporal violation surfaces alone.
    th.get_success_data(
        api.create_weather_advisory(
            th.weather_advisory_payload(region="NE-OH", date="2026-12-25",
                                        rain_probability=0.10, wind_kph=5,
                                        temp_high_c=20),
            ADMIN,
        )
    )
    th.validate_error(
        api.create_application(
            th.application_payload(ctx["subscription"]["id"], box["id"],
                                   product_sku="FERT-01",
                                   scheduled_date="2026-12-25"),
            ctx["customer_headers"],
        ),
        th.ApiErrorId.ERR_APPLICATION_WINDOW_VIOLATION,
    )
