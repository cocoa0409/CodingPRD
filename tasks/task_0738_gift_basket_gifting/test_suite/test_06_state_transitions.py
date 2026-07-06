"""State-machine invalid-transition rejections not already exercised by the
Difficulty-queue cycle tests: terminal assembly-task, terminal shipment,
already-decided budget approval, already-locked message proof, already-paused
recurring series, already-pending order submit, and shipped-order cancel.

All Corner/state_machines translations.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, factories, fixtures,
)
from test_helpers.test_users import (
    TEST_USERS, make_account_manager_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
FIN = TEST_USERS["finance_approver_headers"]
PROOF = TEST_USERS["proof_approver_headers"]
WH = TEST_USERS["warehouse_ops_headers"]
SHIP = TEST_USERS["shipping_ops_headers"]


def test_assembly_task_start_after_complete_rejected(api):
    """PRD §3.7: "Any target that is not a legal next state for the task's
    current status is rejected with ERR_INVALID_FULFILLMENT_STATE (409)."

    Design: Corner/state_machines/assembly_task_start_after_complete_rejected
    """
    base = fixtures.setup_catalog(
        api, monthly_budget_cents=1_000_000, approval_threshold_cents=1000,
        template_kwargs=dict(name="Lamp Basket", base_price_cents=4000))
    p = fixtures.setup_approved_order(
        api, base=base,
        rows=[factories.recipient_row(email="task@example.com", quantity=2)])
    task = fixtures.find_task_for_recipient(api, recipient_id=p["recipients"][0]["id"])
    fixtures.advance_assembly_task(api, task_id=task["id"], target_status="IN_PROGRESS")
    fixtures.advance_assembly_task(api, task_id=task["id"], target_status="COMPLETE")
    resp = api.advance_assembly_task(task["id"], {"target_status": "IN_PROGRESS"}, WH)
    validate_error(resp, ApiErrorId.ERR_INVALID_FULFILLMENT_STATE.value)


def test_shipment_advance_after_delivered_rejected(api):
    """PRD §3.8: "An illegal target for the shipment's current status is rejected
    with ERR_INVALID_FULFILLMENT_STATE (409), exactly as for assembly tasks."

    Design: Corner/state_machines/shipment_advance_after_delivered_rejected
    """
    base = fixtures.setup_catalog(
        api, monthly_budget_cents=1_000_000, approval_threshold_cents=1_000_000,
        template_kwargs=dict(name="Vase Basket", category="CLIENT_APPRECIATION",
                             base_price_cents=4000))
    zone = fixtures.create_shipping_zone(
        api, zone_code="US-SOUTH", country_codes=["US"], carrier="SwiftShip",
        base_rate_cents=500, per_kg_rate_cents=100,
        transit_days_min=2, transit_days_max=5, blackout_dates=[])
    _, rec = fixtures.setup_order_with_recipients(
        api, account=base["account"], template_id=base["template"]["id"],
        rows=[factories.recipient_row(email="ship-sm@example.com", quantity=1)],
        occasion="THANK_YOU")
    fixtures.lock_message_proof_for_recipient(
        api, account_id=base["account"]["id"], recipient_id=rec[0]["id"],
        submitted_by="emp-msg-5", decided_by="proof-appr-5")
    shipment = fixtures.create_shipment(
        api, recipient_id=rec[0]["id"], zone_id=zone["id"],
        ship_date="2026-03-05T00:00:00Z")
    fixtures.advance_shipment(api, shipment_id=shipment["id"],
                              target_status="LABEL_GENERATED")
    fixtures.advance_shipment(api, shipment_id=shipment["id"],
                              target_status="IN_TRANSIT")
    fixtures.advance_shipment(api, shipment_id=shipment["id"],
                              target_status="DELIVERED")
    resp = api.advance_shipment(shipment["id"], {"target_status": "IN_TRANSIT"}, SHIP)
    validate_error(resp, ApiErrorId.ERR_INVALID_FULFILLMENT_STATE.value)


def test_budget_decision_after_already_decided_rejected(api):
    """PRD §3.4: "Both decisions share two checks, evaluated in this order: the
    order must exist (ERR_ORDER_NOT_FOUND, 404), and the order's
    BudgetApproval.decision must still be PENDING (ERR_INVALID_DECISION_STATE,
    409)."

    Design: Corner/state_machines/budget_decision_after_already_decided_rejected
    """
    base = fixtures.setup_catalog(
        api, monthly_budget_cents=1_000_000, approval_threshold_cents=1000,
        template_kwargs=dict(name="Cup Basket", base_price_cents=4000))
    p = fixtures.setup_approved_order(
        api, base=base,
        rows=[factories.recipient_row(email="decided@example.com", quantity=2)],
        requested_by_user_id="emp-req-20", approver_user_id="fin-appr-20")
    # Second decision on the same order — already APPROVED, so PENDING check fails.
    resp = api.budget_decision(
        p["order"]["id"],
        factories.budget_decision_payload(
            decision="REJECT", approver_user_id="fin-appr-21",
            decision_reason="too late"),
        FIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_DECISION_STATE.value)


def test_message_proof_decision_after_locked_rejected(api):
    """PRD §3.5: "Two checks gate this call, in order: the target MessageProof
    must exist (ERR_SUBRESOURCE_NOT_FOUND, 404), and its proof_status must
    still be SUBMITTED (ERR_INVALID_DECISION_STATE, 409)"

    Design: Corner/state_machines/message_proof_decision_after_locked_rejected
    """
    base = fixtures.setup_catalog(
        api, monthly_budget_cents=1_000_000, approval_threshold_cents=1_000_000,
        template_kwargs=dict(name="Bowl Basket", category="CLIENT_APPRECIATION",
                             base_price_cents=3000))
    _, rec = fixtures.setup_order_with_recipients(
        api, account=base["account"], template_id=base["template"]["id"],
        rows=[factories.recipient_row(email="locked@example.com", quantity=1)],
        occasion="THANK_YOU")
    proof = fixtures.submit_message_proof(
        api, account_id=base["account"]["id"], recipient_id=rec[0]["id"],
        message_text="Cheers!", submitted_by_user_id="emp-msg-6")
    fixtures.decide_message_proof(
        api, proof_id=proof["id"], decision="APPROVE",
        decided_by_user_id="proof-appr-6")
    resp = api.decide_message_proof(
        proof["id"],
        factories.proof_decision_payload(
            decision="REQUEST_REVISION", decided_by_user_id="proof-appr-6b"),
        PROOF)
    validate_error(resp, ApiErrorId.ERR_INVALID_DECISION_STATE.value)


def test_recurring_series_pause_when_already_paused_rejected(api):
    """PRD §3.9: "An AccountManager may pause an active series (setting active
    to false) or resume a paused one (setting active back to true) through the
    same update call; pausing when already inactive, or resuming when already
    active, is rejected with ERR_INVALID_SERIES_STATE (409)."

    Design: Corner/state_machines/recurring_series_pause_when_already_paused_rejected
    """
    base = fixtures.setup_catalog(
        api, monthly_budget_cents=1_000_000, approval_threshold_cents=1_000_000,
        template_kwargs=dict(name="Planner Basket", base_price_cents=4000))
    source_order = fixtures.create_order(
        api, account=base["account"], template_id=base["template"]["id"],
        occasion="ONBOARDING")
    hdrs = make_account_manager_headers(base["account"]["id"])
    series = validate_success(api.create_recurring_series(
        base["account"]["id"],
        {"source_order_id": source_order["id"], "interval_days": 30}, hdrs), 201)
    # First pause succeeds.
    validate_success(api.update_recurring_series(
        series["id"], {"active": False}, hdrs))
    # Second pause is rejected.
    resp = api.update_recurring_series(series["id"], {"active": False}, hdrs)
    validate_error(resp, ApiErrorId.ERR_INVALID_SERIES_STATE.value)


def test_submit_for_approval_while_already_pending_rejected(api):
    """PRD §3.4: "This call is only legal while order.approval_status is DRAFT
    or REJECTED and order.production_status is not CANCELLED — otherwise
    ERR_INVALID_ORDER_STATE (409)."

    Design: Corner/state_machines/submit_for_approval_while_already_pending_rejected
    """
    base = fixtures.setup_catalog(
        api, monthly_budget_cents=1_000_000, approval_threshold_cents=1000,
        template_kwargs=dict(name="Mug Basket 2", base_price_cents=4000))
    p = fixtures.setup_pending_approval_order(
        api, base=base,
        rows=[factories.recipient_row(email="pending@example.com", quantity=3)],
        requested_by_user_id="emp-req-22")
    hdrs = make_account_manager_headers(base["account"]["id"])
    resp = api.submit_for_approval(
        p["order"]["id"],
        factories.submit_for_approval_payload(requested_by_user_id="emp-req-23"),
        hdrs)
    validate_error(resp, ApiErrorId.ERR_INVALID_ORDER_STATE.value)


def test_cancel_already_shipped_order_rejected(api):
    """PRD §3.9: "Either an AccountManager or a PlatformAdmin may cancel a
    CorporateOrder whose production_status is still DRAFT or ASSEMBLING; any
    later production_status is rejected with ERR_ORDER_ALREADY_TERMINAL (409)."

    Design: Corner/state_machines/cancel_already_shipped_order_rejected
    """
    base = fixtures.setup_catalog(
        api, monthly_budget_cents=1_000_000, approval_threshold_cents=1000,
        template_kwargs=dict(name="Socks Basket", category="CLIENT_APPRECIATION",
                             base_price_cents=4000))
    zone = fixtures.create_shipping_zone(
        api, zone_code="US-NORTH", country_codes=["US"], carrier="SwiftShip",
        base_rate_cents=500, per_kg_rate_cents=100,
        transit_days_min=2, transit_days_max=5, blackout_dates=[])
    p = fixtures.setup_approved_order(
        api, base=base,
        rows=[factories.recipient_row(email="shipped@example.com", quantity=1)],
        requested_by_user_id="emp-req-24", approver_user_id="fin-appr-24")
    recipient_id = p["recipients"][0]["id"]
    task = fixtures.find_task_for_recipient(api, recipient_id=recipient_id)
    fixtures.advance_assembly_task(api, task_id=task["id"], target_status="IN_PROGRESS")
    fixtures.advance_assembly_task(api, task_id=task["id"], target_status="COMPLETE")
    fixtures.lock_message_proof_for_recipient(
        api, account_id=base["account"]["id"], recipient_id=recipient_id,
        message_text="Enjoy!",
        submitted_by="emp-msg-7", decided_by="proof-appr-7")
    shipment = fixtures.create_shipment(
        api, recipient_id=recipient_id, zone_id=zone["id"],
        ship_date="2026-03-05T00:00:00Z")
    fixtures.advance_shipment(api, shipment_id=shipment["id"],
                              target_status="LABEL_GENERATED")
    fixtures.advance_shipment(api, shipment_id=shipment["id"],
                              target_status="IN_TRANSIT")
    # production_status is now SHIPPED; cancel is illegal.
    hdrs = make_account_manager_headers(base["account"]["id"])
    resp = api.cancel_order(p["order"]["id"], hdrs)
    validate_error(resp, ApiErrorId.ERR_ORDER_ALREADY_TERMINAL.value)
