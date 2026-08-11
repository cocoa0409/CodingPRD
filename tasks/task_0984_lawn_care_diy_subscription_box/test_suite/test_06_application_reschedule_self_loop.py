"""Application task reschedule: SCHEDULED self-loop with snooze counter (PRD 3.7)."""
import test_helpers as th

ADMIN = th.TEST_USERS["platform_admin_headers"]


def _setup_scheduled_task(api, email="rs@x.com", date="2026-06-10"):
    ctx = th.setup_active_subscription(email=email)
    box, _ = th.setup_delivered_box(ctx, lines=[th.shipment_line("FERT-01", 1)])
    resp = api.create_application(
        th.application_payload(ctx["subscription"]["id"], box["id"],
                               product_sku="FERT-01", scheduled_date=date),
        ctx["customer_headers"],
    )
    task = th.validate_success(resp, 201)
    return ctx, box, task


def test_reschedule_self_loop_bumps_snooze_count(api):
    """PRD 3.7: "Rescheduling is a self-loop on `SCHEDULED`: the task must be `SCHEDULED` (`ERR_APPLICATION_NOT_SCHEDULED`, HTTP 409), the acting customer must own the task's subscription, and the `new_date` must pass all three guards above."
    PRD 3.7: "A successful reschedule writes `scheduled_date` to the new date and increments `snooze_count` by 1 — each reschedule, weather-driven or customer-driven, bumps the snooze counter — and increments the task's `version` by 1."

    Design: Difficulty/non_linear_state_machine/application_reschedule_self_loop
    """
    ctx, _, task = _setup_scheduled_task(api)
    headers = ctx["customer_headers"]

    first = th.validate_success(
        api.reschedule_application(task["id"], {"new_date": "2026-06-15"}, headers)
    )
    assert first["status"] == "SCHEDULED", "self-loop: the status label never changes"
    assert first["scheduled_date"] == "2026-06-15"
    assert first["snooze_count"] == 1

    second = th.validate_success(
        api.reschedule_application(task["id"], {"new_date": "2026-06-20"}, headers)
    )
    assert second["status"] == "SCHEDULED"
    assert second["scheduled_date"] == "2026-06-20"
    assert second["snooze_count"] == 2, "each loop iteration bumps the snooze counter"


def test_reschedule_revalidates_the_window_guard(api):
    """PRD 3.7: "Three independent guards protect every scheduling decision, and each is re-validated on every reschedule."
    PRD 3.7: "the scheduled date must fall on or after `window_start_date` and strictly before `window_end_date`, otherwise `ERR_APPLICATION_WINDOW_VIOLATION` (HTTP 422)."

    Design: Difficulty/non_linear_state_machine/application_reschedule_self_loop
    """
    ctx, _, task = _setup_scheduled_task(api, email="rs-guard@x.com")
    headers = ctx["customer_headers"]

    # 2026-08-01 is outside FERT-01's half-open window [03-01, 07-01).
    th.validate_error(
        api.reschedule_application(task["id"], {"new_date": "2026-08-01"}, headers),
        th.ApiErrorId.ERR_APPLICATION_WINDOW_VIOLATION,
    )
    after = th.validate_success(api.get_application(task["id"], ADMIN))
    assert after["status"] == "SCHEDULED"
    assert after["scheduled_date"] == "2026-06-10", "a rejected reschedule changes nothing"
    assert after["snooze_count"] == 0
