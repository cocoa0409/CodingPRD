"""Terminal-state error guards, RBAC enforcement, header validation, and OCC happy path.

Corner queue (B) instances under sections: errors, rbac, cross_cutting_complexity_layers.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_catalog, create_partner, create_phleb, create_route_day, create_order,
    setup_scheduled_appointment, drive_to_draw_completed,
    setup_draw_completed_with_in_transit_specimens,
    create_lab_order_payload, create_test_panel_payload, create_manifest_payload,
    make_phlebotomist_headers, build_user_headers,
    ApiErrorId, TEST_USERS,
)

_PROVIDER = TEST_USERS["ordering_provider_headers"]
_DISPATCHER = TEST_USERS["dispatcher_headers"]
_LABOPS = TEST_USERS["lab_ops_headers"]
_BILLING = TEST_USERS["billing_agent_headers"]


def _first_invoice_id(api, order_id):
    body = api.list_order_invoices(order_id, _BILLING).json()
    return body["data"][0]["id"]


# ---------------------------------------------------------------------------
# Corner — errors
# ---------------------------------------------------------------------------

def test_void_already_void_invoice_rejected(api):
    """PRD §3.11: "A BillingAgent may instead void a draft invoice, which is permitted only while
    it is in DRAFT (otherwise ERR_INVOICE_NOT_VOIDABLE) and moves it from DRAFT to VOID."

    Design: Corner/errors/invoice_void_then_void_again_returns_not_voidable
    """
    _, partner = setup_catalog(panel_code="CMP14", accepted_panel_codes=["CMP14"])
    order = get_success_data(api.create_lab_order(create_lab_order_payload(
        panel_code="CMP14", lab_partner_id=partner["id"], billing_mode="SELF_PAY"), _PROVIDER))
    inv_id = _first_invoice_id(api, order["id"])
    validate_success(api.void_invoice(inv_id, _BILLING))
    validate_error(api.void_invoice(inv_id, _BILLING),
                   ApiErrorId.ERR_INVOICE_NOT_VOIDABLE.value, 409)
    inv = validate_success(api.get_invoice(inv_id, _BILLING))
    assert inv["status"] == "VOID"


def test_add_specimen_to_in_transit_manifest_rejected(api):
    """PRD §3.8: "The manifest must be in BUILDING, or the request fails with
    ERR_MANIFEST_NOT_BUILDING."

    Design: Corner/errors/add_specimen_to_non_building_manifest_returns_not_building
    """
    # A 2-tube order: first specimen is manifested and the manifest picked up (IN_TRANSIT);
    # adding the second specimen to that IN_TRANSIT manifest must fail.
    ctx = setup_draw_completed_with_in_transit_specimens(
        billing_mode="SELF_PAY", panel_code="CBC2", required_tube_count=2, base_lab_fee_cents=2000,
        manifest_specimen_count=1,
    )
    sp2 = ctx["specimens"][1]["id"]
    phleb_headers = make_phlebotomist_headers(ctx["phleb_id"])
    resp = api.add_specimen_to_manifest(ctx["manifest"]["id"], {"specimen_id": sp2}, phleb_headers)
    validate_error(resp, ApiErrorId.ERR_MANIFEST_NOT_BUILDING.value, 409)
    specimen = validate_success(api.get_specimen(sp2, _LABOPS))
    assert specimen["status"] == "COLLECTED"


# ---------------------------------------------------------------------------
# Corner — rbac
# ---------------------------------------------------------------------------

def test_ordering_provider_cannot_book_appointment(api):
    """PRD §2.1: "When the headers are present and well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_INSUFFICIENT_PERMISSIONS."

    Design: Corner/rbac/ordering_provider_cannot_book_appointment
    """
    _, partner = setup_catalog(panel_code="CMP14", accepted_panel_codes=["CMP14"])
    phleb = create_phleb()
    rd = create_route_day(phleb["id"])
    order = create_order(partner["id"], panel_code="CMP14")
    # Booking is a Dispatcher-exclusive op (PRD §4); OrderingProvider must be denied.
    resp = api.book_appointment(order["id"], {
        "route_day_id": rd["id"], "window_start_utc": "2026-02-01T09:00:00Z",
        "window_end_utc": "2026-02-01T09:30:00Z", "expected_route_day_version": rd["version"],
    }, _PROVIDER)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value, 403)
    final = validate_success(api.get_lab_order(order["id"], _PROVIDER))
    assert final["status"] == "ORDERED"


def test_dispatcher_cannot_accession_specimen(api):
    """PRD §2.1: "When the headers are present and well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_INSUFFICIENT_PERMISSIONS."

    Design: Corner/rbac/dispatcher_cannot_accession_specimen
    """
    # Accession is a LabOps-exclusive op (PRD §4); a Dispatcher must be denied.
    ctx = setup_draw_completed_with_in_transit_specimens(
        billing_mode="SELF_PAY", panel_code="ONE", required_tube_count=1, base_lab_fee_cents=1000,
    )
    sp1 = ctx["specimens"][0]["id"]
    validate_error(api.accession_specimen(sp1, _DISPATCHER),
                   ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value, 403)
    specimen = validate_success(api.get_specimen(sp1, _LABOPS))
    assert specimen["status"] == "MANIFESTED"


def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "Every request must carry two mandatory HTTP headers: X-User-ID, identifying the
    acting user, and X-User-Role, declaring the operational capacity under which the request is
    made. If either header is missing or malformed, the request is rejected with
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."

    Design: Corner/rbac/missing_user_context_header_returns_400
    """
    resp = api.create_test_panel(create_test_panel_payload(panel_code="CMP14"), {})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value, 400)


# ---------------------------------------------------------------------------
# Corner — cross_cutting_complexity_layers
# ---------------------------------------------------------------------------

def test_booking_with_correct_version_succeeds_and_bumps_version(api):
    """PRD §2.8: "A request to book (or re-book after a redraw) an appointment for an order onto a
    route day must carry an expected_route_day_version field whose value equals the target route
    day's current version at the moment of booking."
    PRD §3.4: "the route day's booked_stop_count rises by one, and the route day's version rises
    by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_booking_succeeds_and_bumps
    """
    _, partner = setup_catalog(panel_code="CMP14", accepted_panel_codes=["CMP14"])
    phleb = create_phleb()
    rd = create_route_day(phleb["id"], stop_capacity=10)
    assert rd["version"] == 1, f"new route day must start at version 1, got {rd['version']}"
    order = create_order(partner["id"], panel_code="CMP14")
    appt = validate_success(api.book_appointment(order["id"], {
        "route_day_id": rd["id"], "window_start_utc": "2026-02-01T09:00:00Z",
        "window_end_utc": "2026-02-01T09:30:00Z", "expected_route_day_version": rd["version"],
    }, _DISPATCHER), 201)
    assert appt["status"] == "SCHEDULED"
    rd_after = validate_success(api.get_route_day(rd["id"], _DISPATCHER))
    assert rd_after["version"] == 2, f"version must bump 1->2, got {rd_after['version']}"
    assert rd_after["booked_stop_count"] == 1, f"expected booked 1, got {rd_after['booked_stop_count']}"
    order_after = validate_success(api.get_lab_order(order["id"], _PROVIDER))
    assert order_after["status"] == "SCHEDULED"
