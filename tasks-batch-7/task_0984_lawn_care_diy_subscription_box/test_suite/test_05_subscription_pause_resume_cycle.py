"""Subscription pause/resume: cyclic machine with box cascades (PRD 3.5)."""
import test_helpers as th

ADMIN = th.TEST_USERS["platform_admin_headers"]


def test_pause_resume_cycle_is_unlimited_and_cascades(api):
    """PRD 3.5: "Moving a subscription from `ACTIVE` to `PAUSED` requires it to be `ACTIVE` (`ERR_SUBSCRIPTION_NOT_ACTIVE`, HTTP 409) and requires ownership; the pause cascades so that each of its shipment boxes in `SCHEDULED` flips to `HELD` and each of its application tasks in `SCHEDULED` flips to `FROZEN`."
    PRD 3.5: "The pause/resume cycle between `ACTIVE` and `PAUSED` is unlimited, and each transition increments the subscription's `version` by 1."

    Design: Difficulty/non_linear_state_machine/subscription_pause_resume_cycle
    """
    ctx = th.setup_active_subscription(
        email="pr@x.com",
        plan_lines=[th.plan_line("FERT-01", qty_units=2, target_month=4)],
    )
    box = th.create_box(
        ctx["subscription"]["id"],
        lines=[th.shipment_line("FERT-01", 2)],
        ship_date="2026-06-03T00:00:00Z",
    )
    sub_id = ctx["subscription"]["id"]
    headers = ctx["customer_headers"]
    v0 = ctx["subscription"]["version"]

    paused = th.validate_success(
        api.set_subscription_status(sub_id, {"to_status": "PAUSED"}, headers)
    )
    assert paused["status"] == "PAUSED"
    assert paused["version"] == v0 + 1
    box_after_pause = th.validate_success(api.get_shipment(box["id"], ADMIN))
    assert box_after_pause["fulfillment_status"] == "HELD", (
        "pause must cascade the SCHEDULED box to HELD"
    )

    resumed = th.validate_success(
        api.set_subscription_status(sub_id, {"to_status": "ACTIVE"}, headers)
    )
    assert resumed["status"] == "ACTIVE", "cycling back to a prior state is legal"
    assert resumed["version"] == v0 + 2

    paused_again = th.validate_success(
        api.set_subscription_status(sub_id, {"to_status": "PAUSED"}, headers)
    )
    assert paused_again["status"] == "PAUSED", (
        "a second loop iteration must succeed — the cycle is unlimited"
    )
    assert paused_again["version"] == v0 + 3


def test_resume_cascade_restores_held_boxes(api):
    """PRD 3.5: "Resuming moves a subscription from `PAUSED` back to `ACTIVE`, requires it to be `PAUSED` (`ERR_SUBSCRIPTION_NOT_PAUSED`, HTTP 409), and reverses the cascades: `HELD` boxes return to `SCHEDULED` and `FROZEN` tasks return to `SCHEDULED`."

    Design: Difficulty/non_linear_state_machine/subscription_pause_resume_cycle
    """
    ctx = th.setup_active_subscription(email="pr2@x.com")
    box = th.create_box(ctx["subscription"]["id"],
                        lines=[th.shipment_line("FERT-01", 1)])
    sub_id = ctx["subscription"]["id"]
    headers = ctx["customer_headers"]

    th.validate_success(
        api.set_subscription_status(sub_id, {"to_status": "PAUSED"}, headers)
    )
    held = th.validate_success(api.get_shipment(box["id"], ADMIN))
    assert held["fulfillment_status"] == "HELD"

    th.validate_success(
        api.set_subscription_status(sub_id, {"to_status": "ACTIVE"}, headers)
    )
    restored = th.validate_success(api.get_shipment(box["id"], ADMIN))
    assert restored["fulfillment_status"] == "SCHEDULED", (
        "resume must flip HELD boxes back to SCHEDULED"
    )
