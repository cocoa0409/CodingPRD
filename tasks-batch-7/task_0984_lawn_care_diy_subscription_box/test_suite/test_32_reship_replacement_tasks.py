"""Replacement-box tasks activate on delivery (PRD 3.6, 3.9)."""
import test_helpers as th

ADMIN = th.TEST_USERS["platform_admin_headers"]
AGRONOMIST = th.TEST_USERS["agronomist_headers"]


def test_reship_replacement_task_activates_on_delivery(api):
    """PRD 3.6: "Reaching `DELIVERED` stamps `delivered_at` from the logical clock and computes `final_charge_cents` — the same charge formula run again, except that the early-season test uses the actual `delivered_at` instead of the planned `ship_date`, and the lawn's size tier is re-read at delivery."
    PRD 3.6: "Delivery also cascades: each attached `CONFIRMED` add-on order flips to `FULFILLED`, and each of the box's application tasks in `AWAITING_DELIVERY` flips to `SCHEDULED` with its `scheduled_date` set to the delivery date and its window fields recomputed for that year."

    Design: Corner/state_machines/reship_replacement_task_activates_on_delivery
    """
    ctx = th.setup_active_subscription(email="s15@x.com")
    box, _ = th.setup_delivered_box(
        ctx, lines=[th.shipment_line("FERT-01", 1)],
        deliver_clock="2026-06-05T00:00:00Z",
    )
    claim = th.file_claim(ctx, box, claim_reason="DAMAGED")
    th.validate_success(
        api.resolve_claim(claim["id"], {"resolution_type": "RESHIP"}, AGRONOMIST)
    )

    replacements, _ = th.validate_paginated(
        api.list_shipments(ADMIN, params={"source_claim_id": claim["id"]})
    )
    assert len(replacements) == 1
    replacement = replacements[0]

    tasks = th.list_tasks(shipment_id=replacement["id"])
    assert len(tasks) == 1
    assert tasks[0]["status"] == "AWAITING_DELIVERY", (
        "the replacement task waits for its box to arrive"
    )

    # The logical clock still reads 2026-06-05 — the delivery date.
    th.deliver_box(replacement["id"])
    task_after = th.validate_success(api.get_application(tasks[0]["id"], ADMIN))
    assert task_after["status"] == "SCHEDULED"
    assert task_after["scheduled_date"] == "2026-06-05", (
        "scheduled_date is set to the box's delivered_at date"
    )
