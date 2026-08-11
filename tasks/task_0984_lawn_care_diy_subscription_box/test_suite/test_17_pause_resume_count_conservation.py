"""Pause/resume task-count conservation invariant (PRD 3.5)."""
import test_helpers as th


def _setup_three_tasks(api, email="ic@x.com"):
    """Delivered box (FERT-01, WEED-01, SEED-A) with three SCHEDULED tasks:
    FERT-01 on 2026-06-10, WEED-01 on 2026-06-24 (14-day clearance), SEED-A
    on 2026-06-10 (SEED declares no conflicts)."""
    ctx = th.setup_active_subscription(
        email=email,
        plan_lines=[
            th.plan_line("FERT-01", qty_units=1, target_month=6),
            th.plan_line("WEED-01", qty_units=1, target_month=6),
            th.plan_line("SEED-A", qty_units=1, target_month=6),
        ],
        seed_skus=("FERT-01", "WEED-01", "SEED-A"),
    )
    box, _ = th.setup_delivered_box(
        ctx,
        lines=[th.shipment_line("FERT-01", 1), th.shipment_line("WEED-01", 1),
               th.shipment_line("SEED-A", 1)],
    )
    sub_id = ctx["subscription"]["id"]
    for sku, date in (("FERT-01", "2026-06-10"), ("WEED-01", "2026-06-24"),
                      ("SEED-A", "2026-06-10")):
        th.validate_success(
            api.create_application(
                th.application_payload(sub_id, box["id"], product_sku=sku,
                                       scheduled_date=date),
                ctx["customer_headers"],
            ),
            201,
        )
    return ctx, box


def test_pause_resume_application_count_conservation(api):
    """PRD 3.5: "Moving a subscription from `ACTIVE` to `PAUSED` requires it to be `ACTIVE` (`ERR_SUBSCRIPTION_NOT_ACTIVE`, HTTP 409) and requires ownership; the pause cascades so that each of its shipment boxes in `SCHEDULED` flips to `HELD` and each of its application tasks in `SCHEDULED` flips to `FROZEN`."
    PRD 3.5: "Resuming moves a subscription from `PAUSED` back to `ACTIVE`, requires it to be `PAUSED` (`ERR_SUBSCRIPTION_NOT_PAUSED`, HTTP 409), and reverses the cascades: `HELD` boxes return to `SCHEDULED` and `FROZEN` tasks return to `SCHEDULED`."

    Design: Difficulty/compensating_invariant/pause_resume_application_count_conservation
    """
    ctx, _ = _setup_three_tasks(api)
    sub_id = ctx["subscription"]["id"]
    headers = ctx["customer_headers"]

    assert len(th.list_tasks(subscription_id=sub_id, status="SCHEDULED")) == 3
    assert len(th.list_tasks(subscription_id=sub_id, status="FROZEN")) == 0

    th.validate_success(
        api.set_subscription_status(sub_id, {"to_status": "PAUSED"}, headers)
    )
    assert len(th.list_tasks(subscription_id=sub_id, status="SCHEDULED")) == 0
    assert len(th.list_tasks(subscription_id=sub_id, status="FROZEN")) == 3, (
        "count(SCHEDULED) + count(FROZEN) stays invariant at 3 across the pause"
    )

    th.validate_success(
        api.set_subscription_status(sub_id, {"to_status": "ACTIVE"}, headers)
    )
    assert len(th.list_tasks(subscription_id=sub_id, status="SCHEDULED")) == 3
    assert len(th.list_tasks(subscription_id=sub_id, status="FROZEN")) == 0, (
        "the compensating resume restores the pre-pause per-status counts"
    )


def test_pause_resume_preserves_task_identity_dates_and_snooze(api):
    """PRD 3.5: "the pause cascades so that each of its shipment boxes in `SCHEDULED` flips to `HELD` and each of its application tasks in `SCHEDULED` flips to `FROZEN`."
    PRD 3.5: "Resuming moves a subscription from `PAUSED` back to `ACTIVE`, requires it to be `PAUSED` (`ERR_SUBSCRIPTION_NOT_PAUSED`, HTTP 409), and reverses the cascades: `HELD` boxes return to `SCHEDULED` and `FROZEN` tasks return to `SCHEDULED`."

    Design: Difficulty/compensating_invariant/pause_resume_application_count_conservation
    """
    ctx, _ = _setup_three_tasks(api, email="ic2@x.com")
    sub_id = ctx["subscription"]["id"]
    headers = ctx["customer_headers"]

    before = {
        t["id"]: (t["scheduled_date"], t["snooze_count"])
        for t in th.list_tasks(subscription_id=sub_id)
    }
    assert len(before) == 3

    th.validate_success(
        api.set_subscription_status(sub_id, {"to_status": "PAUSED"}, headers)
    )
    th.validate_success(
        api.set_subscription_status(sub_id, {"to_status": "ACTIVE"}, headers)
    )

    after = {
        t["id"]: (t["scheduled_date"], t["snooze_count"])
        for t in th.list_tasks(subscription_id=sub_id)
    }
    assert after == before, (
        "no task changed identity, scheduled_date, or snooze_count across the round trip"
    )
