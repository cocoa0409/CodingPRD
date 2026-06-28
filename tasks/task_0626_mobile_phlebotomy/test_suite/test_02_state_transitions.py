"""State-machine transition guards and bubble-up effects.

Corner queue (B) instances under section: state_machines.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_catalog, create_partner,
    setup_scheduled_appointment, drive_to_draw_completed,
    setup_draw_completed_with_in_transit_specimens,
    create_lab_order_payload, create_manifest_payload, collect_specimen_payload,
    make_phlebotomist_headers,
    ApiErrorId, TEST_USERS,
)

_PROVIDER = TEST_USERS["ordering_provider_headers"]
_DISPATCHER = TEST_USERS["dispatcher_headers"]
_LABOPS = TEST_USERS["lab_ops_headers"]
_BILLING = TEST_USERS["billing_agent_headers"]


def test_cancel_already_cancelled_order_rejected(api):
    """PRD §3.3: "An OrderingProvider may cancel an order while it is in ORDERED, SCHEDULED, or
    REDRAW_REQUIRED; a cancel attempt from any other status is rejected with
    ERR_ORDER_NOT_CANCELLABLE."

    Design: Corner/state_machines/cancel_already_cancelled_order_returns_not_cancellable
    """
    _, partner = setup_catalog(panel_code="CMP14", accepted_panel_codes=["CMP14"])
    order = get_success_data(api.create_lab_order(create_lab_order_payload(
        panel_code="CMP14", lab_partner_id=partner["id"], billing_mode="SELF_PAY"), _PROVIDER))
    validate_success(api.cancel_order(order["id"], _PROVIDER))
    validate_error(api.cancel_order(order["id"], _PROVIDER),
                   ApiErrorId.ERR_ORDER_NOT_CANCELLABLE.value, 409)
    final = validate_success(api.get_lab_order(order["id"], _PROVIDER))
    assert final["status"] == "CANCELLED"


def test_dispatch_without_kit_rejected(api):
    """PRD §3.5: "a draw kit must already be assigned to the appointment whose tube_count is at
    least the order's specimens_required_count; if no such kit is assigned, the dispatch is
    rejected with ERR_KIT_NOT_ASSIGNED."

    Design: Corner/state_machines/dispatch_without_kit_returns_kit_not_assigned
    """
    ctx = setup_scheduled_appointment(panel_code="CMP14", required_tube_count=3, base_lab_fee_cents=4000)
    validate_error(api.dispatch_appointment(ctx["appt_id"], _DISPATCHER),
                   ApiErrorId.ERR_KIT_NOT_ASSIGNED.value, 409)
    appt = validate_success(api.get_appointment(ctx["appt_id"], _DISPATCHER))
    assert appt["status"] == "SCHEDULED"


def test_arrive_by_non_assigned_phlebotomist_forbidden(api):
    """PRD §3.6: "Arrival is the action gated by phlebotomist identity: the acting X-User-ID must
    equal the appointment's denormalized phlebotomist_id, and a mismatch is rejected with
    ERR_NOT_ASSIGNED_PHLEBOTOMIST."

    Design: Corner/state_machines/arrive_by_non_assigned_phlebotomist_forbidden
    """
    from test_helpers import create_phleb
    ctx = setup_scheduled_appointment(panel_code="ONE", required_tube_count=1, base_lab_fee_cents=1000)
    other_phleb = create_phleb(full_name="Phleb B")
    get_success_data(api.assign_kit(ctx["appt_id"], {"kit_lot_number": "L1", "tube_count": 1}, _DISPATCHER))
    get_success_data(api.dispatch_appointment(ctx["appt_id"], _DISPATCHER))
    other_headers = make_phlebotomist_headers(other_phleb["id"])
    validate_error(api.arrive_appointment(ctx["appt_id"], other_headers),
                   ApiErrorId.ERR_NOT_ASSIGNED_PHLEBOTOMIST.value, 403)
    appt = validate_success(api.get_appointment(ctx["appt_id"], _DISPATCHER))
    assert appt["status"] == "DISPATCHED"


def test_recall_reverts_dispatched_to_scheduled_and_redispatch_succeeds(api):
    """PRD §3.5: "A Dispatcher may recall an appointment that is currently DISPATCHED, reverting it
    from DISPATCHED back to SCHEDULED so dispatch can be retried; a recall attempt against an
    appointment not in DISPATCHED is rejected with ERR_APPOINTMENT_NOT_RECALLABLE."

    Design: Corner/state_machines/dispatch_recall_returns_to_scheduled
    """
    ctx = setup_scheduled_appointment(panel_code="ONE", required_tube_count=1, base_lab_fee_cents=1000)
    get_success_data(api.assign_kit(ctx["appt_id"], {"kit_lot_number": "L1", "tube_count": 1}, _DISPATCHER))
    get_success_data(api.dispatch_appointment(ctx["appt_id"], _DISPATCHER))
    recalled = validate_success(api.recall_appointment(ctx["appt_id"], _DISPATCHER))
    assert recalled["status"] == "SCHEDULED", f"expected SCHEDULED after recall, got {recalled['status']}"
    redispatched = validate_success(api.dispatch_appointment(ctx["appt_id"], _DISPATCHER))
    assert redispatched["status"] == "DISPATCHED", f"expected DISPATCHED, got {redispatched['status']}"


def test_issue_invoice_before_order_resulted_rejected(api):
    """PRD §3.11: "A BillingAgent issues the invoice, which is permitted only while the invoice is
    in DRAFT (otherwise ERR_INVOICE_NOT_ISSUABLE) and only while the owning order is RESULTED
    (otherwise ERR_ORDER_NOT_RESULTED)."

    Design: Corner/state_machines/issue_invoice_before_order_resulted_returns_not_resulted
    """
    _, partner = setup_catalog(panel_code="CMP14", accepted_panel_codes=["CMP14"])
    order = get_success_data(api.create_lab_order(create_lab_order_payload(
        panel_code="CMP14", lab_partner_id=partner["id"], billing_mode="SELF_PAY"), _PROVIDER))
    invoices, _ = order_invoices(api, order["id"])
    inv_id = invoices[0]["id"]
    validate_error(api.issue_invoice(inv_id, _BILLING),
                   ApiErrorId.ERR_ORDER_NOT_RESULTED.value, 409)
    inv = validate_success(api.get_invoice(inv_id, _BILLING))
    assert inv["status"] == "DRAFT"


def test_result_before_all_specimens_accessioned_rejected(api):
    """PRD §3.11: "Results may be posted only when the order is in DRAW_COMPLETED, or the request
    fails with ERR_ORDER_NOT_RESULTABLE, and only when the order's specimens_accessioned_count
    equals its specimens_required_count, or the request fails with ERR_SPECIMENS_NOT_ACCESSIONED."

    Design: Corner/state_machines/result_before_specimens_accessioned_returns_specimens_not_accessioned
    """
    ctx = setup_draw_completed_with_in_transit_specimens(
        billing_mode="SELF_PAY", panel_code="CBC2", required_tube_count=2, base_lab_fee_cents=2000,
    )
    # Accession only 1 of the 2 specimens.
    validate_success(api.accession_specimen(ctx["specimens"][0]["id"], _LABOPS))
    validate_error(api.post_results(ctx["order_id"], {"result_value": "ok"}, _LABOPS),
                   ApiErrorId.ERR_SPECIMENS_NOT_ACCESSIONED.value, 409)
    order = validate_success(api.get_lab_order(ctx["order_id"], _PROVIDER))
    assert order["status"] == "DRAW_COMPLETED"


def test_pickup_empty_manifest_rejected(api):
    """PRD §3.8: "Pickup is allowed only when the manifest is BUILDING, or it fails with
    ERR_MANIFEST_NOT_BUILDING; the manifest must hold at least one specimen, or it fails with
    ERR_MANIFEST_EMPTY; and the routed partner must be ACTIVE, or it fails with
    ERR_LAB_PARTNER_SUSPENDED."

    Design: Corner/state_machines/pickup_empty_manifest_returns_manifest_empty
    """
    partner = create_partner(name="Quest", accepted_panel_codes=["ONE"])
    manifest = get_success_data(api.create_manifest(create_manifest_payload(partner["id"]), _DISPATCHER))
    validate_error(api.pickup_manifest(manifest["id"], _DISPATCHER),
                   ApiErrorId.ERR_MANIFEST_EMPTY.value, 409)
    final = validate_success(api.get_manifest(manifest["id"], _DISPATCHER))
    assert final["status"] == "BUILDING"


def test_manifest_auto_delivered_when_last_specimen_accessioned(api):
    """PRD §3.8: "After the move, if every specimen on the manifest is now in either ACCESSIONED or
    QNS_REJECTED, the manifest bubbles up from IN_TRANSIT to DELIVERED."

    Design: Corner/state_machines/manifest_auto_delivered_when_all_specimens_terminal
    """
    ctx = setup_draw_completed_with_in_transit_specimens(
        billing_mode="SELF_PAY", panel_code="ONE", required_tube_count=1, base_lab_fee_cents=1000,
    )
    sp1 = ctx["specimens"][0]["id"]
    accessioned = validate_success(api.accession_specimen(sp1, _LABOPS))
    assert accessioned["status"] == "ACCESSIONED"
    manifest = validate_success(api.get_manifest(ctx["manifest"]["id"], _LABOPS))
    assert manifest["status"] == "DELIVERED", f"expected DELIVERED, got {manifest['status']}"


def order_invoices(api, order_id):
    body = api.list_order_invoices(order_id, _BILLING).json()
    return body.get("data", []), body.get("meta", {})
