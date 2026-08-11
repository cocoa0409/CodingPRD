"""Application task terminal state: mark-applied is not idempotent (PRD 3.7)."""
import test_helpers as th

ADMIN = th.TEST_USERS["platform_admin_headers"]


def test_application_mark_applied_not_idempotent(api):
    """PRD 3.7: "When the work is done, the customer marks the task applied: again the task must be `SCHEDULED` (`ERR_APPLICATION_NOT_SCHEDULED`) and owned by the caller; the task moves to the terminal `APPLIED` state with `applied_at` stamped from the logical clock."

    Design: Corner/state_machines/application_mark_applied_not_idempotent
    """
    ctx = th.setup_active_subscription(email="s9@x.com")
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
    applied = th.validate_success(
        api.mark_applied(task["id"], ctx["customer_headers"])
    )
    assert applied["status"] == "APPLIED"
    assert applied["applied_at"] is not None

    # APPLIED is terminal: the second call is a state error and changes nothing.
    th.validate_error(
        api.mark_applied(task["id"], ctx["customer_headers"]),
        th.ApiErrorId.ERR_APPLICATION_NOT_SCHEDULED,
    )
    after = th.validate_success(api.get_application(task["id"], ADMIN))
    assert after["status"] == "APPLIED"
    assert after["applied_at"] == applied["applied_at"]
