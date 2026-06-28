"""Business-rule validation guards on ordering, booking, collection, and manifesting.

Corner queue (B) instances under section: validations.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_catalog, create_partner, create_phleb, create_route_day, create_order,
    setup_scheduled_appointment, drive_to_arrived, drive_to_draw_completed,
    create_lab_order_payload, create_manifest_payload, collect_specimen_payload,
    make_phlebotomist_headers,
    ApiErrorId, TEST_USERS,
)

_PROVIDER = TEST_USERS["ordering_provider_headers"]
_DISPATCHER = TEST_USERS["dispatcher_headers"]
_LABOPS = TEST_USERS["lab_ops_headers"]


def test_order_panel_not_accepted_by_partner_rejected(api):
    """PRD §3.3: "At creation the order's panel_code must reference a panel that is ACTIVE and
    whose code appears in the chosen partner's accepted_panel_codes. If the ordered panel is
    RETIRED, or if it is not among the partner's accepted codes, the order is rejected with
    ERR_PANEL_NOT_ACCEPTED_BY_PARTNER."

    Design: Corner/validations/order_panel_not_accepted_by_partner_returns_conflict
    """
    from test_helpers import create_panel
    create_panel(panel_code="CMP14", required_tube_count=3, base_lab_fee_cents=4000)
    create_panel(panel_code="LIPID", required_tube_count=1, base_lab_fee_cents=1800)
    partner = create_partner(name="Quest", accepted_panel_codes=["CMP14"])
    resp = api.create_lab_order(create_lab_order_payload(
        panel_code="LIPID", lab_partner_id=partner["id"], billing_mode="SELF_PAY"), _PROVIDER)
    validate_error(resp, ApiErrorId.ERR_PANEL_NOT_ACCEPTED_BY_PARTNER.value, 409)


def test_booking_territory_mismatch_rejected(api):
    """PRD §3.4: "The route day's territory_code must equal the order's patient_territory_code, or
    the request fails with ERR_TERRITORY_MISMATCH."

    Design: Corner/validations/booking_territory_mismatch_returns_conflict
    """
    _, partner = setup_catalog(panel_code="CMP14", accepted_panel_codes=["CMP14"])
    phleb = create_phleb(territory_code="SF_BAY")
    rd = create_route_day(phleb["id"], territory_code="SF_BAY")
    order = create_order(partner["id"], panel_code="CMP14", patient_territory_code="LA")
    resp = api.book_appointment(order["id"], {
        "route_day_id": rd["id"],
        "window_start_utc": "2026-02-01T09:00:00Z",
        "window_end_utc": "2026-02-01T09:30:00Z",
        "expected_route_day_version": rd["version"],
    }, _DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_TERRITORY_MISMATCH.value, 409)
    final = validate_success(api.get_lab_order(order["id"], _PROVIDER))
    assert final["status"] == "ORDERED"


def test_booking_closed_route_day_rejected(api):
    """PRD §3.4: "The referenced route day must be OPEN, or the request fails with
    ERR_ROUTE_DAY_CLOSED."

    Design: Corner/validations/booking_closed_route_day_returns_conflict
    """
    _, partner = setup_catalog(panel_code="CMP14", accepted_panel_codes=["CMP14"])
    phleb = create_phleb()
    rd = create_route_day(phleb["id"])
    closed = validate_success(api.close_route_day(rd["id"], _DISPATCHER))
    order = create_order(partner["id"], panel_code="CMP14")
    resp = api.book_appointment(order["id"], {
        "route_day_id": rd["id"],
        "window_start_utc": "2026-02-01T09:00:00Z",
        "window_end_utc": "2026-02-01T09:30:00Z",
        "expected_route_day_version": closed["version"],
    }, _DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_ROUTE_DAY_CLOSED.value, 409)
    final = validate_success(api.get_lab_order(order["id"], _PROVIDER))
    assert final["status"] == "ORDERED"


def test_window_outside_shift_rejected(api):
    """PRD §3.4: "And the requested window must fit the day: the half-open interval
    [window_start_utc, window_end_utc) must lie within the route day's [shift_start_utc,
    shift_end_utc] and must not overlap any other booked appointment's window on the same route day."
    PRD §3.4: "A window that falls outside the shift or that overlaps an existing booked window is
    rejected with ERR_APPOINTMENT_WINDOW_CONFLICT."

    Design: Corner/validations/window_outside_shift_returns_window_conflict
    """
    _, partner = setup_catalog(panel_code="CMP14", accepted_panel_codes=["CMP14"])
    phleb = create_phleb()
    rd = create_route_day(phleb["id"], shift_start_utc="2026-02-01T08:00:00Z",
                          shift_end_utc="2026-02-01T18:00:00Z")
    order = create_order(partner["id"], panel_code="CMP14")
    resp = api.book_appointment(order["id"], {
        "route_day_id": rd["id"],
        "window_start_utc": "2026-02-01T19:00:00Z",
        "window_end_utc": "2026-02-01T19:30:00Z",
        "expected_route_day_version": rd["version"],
    }, _DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_APPOINTMENT_WINDOW_CONFLICT.value, 409)
    final = validate_success(api.get_lab_order(order["id"], _PROVIDER))
    assert final["status"] == "ORDERED"


def test_duplicate_tube_label_within_order_rejected(api):
    """PRD §3.6: "Each collection supplies a tube_label — a short label printed on the tube, such
    as T1 or T2 — that must be unique within its lab order; a repeated label on the same order is
    rejected with ERR_DUPLICATE_TUBE_LABEL."

    Design: Corner/validations/duplicate_tube_label_within_order_returns_conflict
    """
    ctx = setup_scheduled_appointment(panel_code="CMP14", required_tube_count=3, base_lab_fee_cents=4000)
    drive_to_arrived(ctx, kit_tube_count=3)
    phleb_headers = make_phlebotomist_headers(ctx["phleb_id"])
    get_success_data(api.collect_specimen(ctx["appt_id"], collect_specimen_payload("T1"), phleb_headers))
    resp = api.collect_specimen(ctx["appt_id"], collect_specimen_payload("T1"), phleb_headers)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_TUBE_LABEL.value, 409)


def test_add_specimen_lab_partner_mismatch_rejected(api):
    """PRD §3.8: "And the manifest's lab_partner_id must equal the lab_partner_id on the specimen's
    lab order, or the request fails with ERR_LAB_PARTNER_MISMATCH."

    Design: Corner/validations/add_specimen_lab_partner_mismatch_returns_conflict
    """
    from test_helpers import create_panel
    create_panel(panel_code="ONE", required_tube_count=1, base_lab_fee_cents=1000)
    quest = create_partner(name="Quest", accepted_panel_codes=["ONE"])
    labcorp = create_partner(name="Labcorp", accepted_panel_codes=["ONE"])
    phleb = create_phleb()
    rd = create_route_day(phleb["id"])
    order = create_order(quest["id"], panel_code="ONE")
    ctx = {"appt_id": None, "phleb_id": phleb["id"], "order": order,
           "partner_id": quest["id"], "route_day_id": rd["id"], "order_id": order["id"]}
    appt = validate_success(api.book_appointment(order["id"], {
        "route_day_id": rd["id"], "window_start_utc": "2026-02-01T09:00:00Z",
        "window_end_utc": "2026-02-01T09:30:00Z", "expected_route_day_version": rd["version"],
    }, _DISPATCHER), 201)
    ctx["appt_id"] = appt["id"]
    ctx["appointment"] = appt
    drive_to_draw_completed(ctx, tube_labels=["T1"])
    sp1 = ctx["specimens"][0]["id"]
    # Manifest routed to Labcorp, but the order is on Quest.
    manifest = get_success_data(api.create_manifest(create_manifest_payload(labcorp["id"]), _DISPATCHER))
    phleb_headers = make_phlebotomist_headers(phleb["id"])
    resp = api.add_specimen_to_manifest(manifest["id"], {"specimen_id": sp1}, phleb_headers)
    validate_error(resp, ApiErrorId.ERR_LAB_PARTNER_MISMATCH.value, 409)
    specimen = validate_success(api.get_specimen(sp1, _LABOPS))
    assert specimen["status"] == "COLLECTED"


def test_pickup_to_suspended_partner_rejected(api):
    """PRD §3.8: "and the routed partner must be ACTIVE, or it fails with
    ERR_LAB_PARTNER_SUSPENDED."

    Design: Corner/validations/pickup_to_suspended_partner_returns_conflict
    """
    from test_helpers import build_in_transit_manifest, create_manifest_payload as _cmp
    ctx = setup_scheduled_appointment(panel_code="ONE", required_tube_count=1, base_lab_fee_cents=1000)
    drive_to_draw_completed(ctx)
    manifest = get_success_data(api.create_manifest(_cmp(ctx["partner_id"]), _DISPATCHER))
    phleb_headers = make_phlebotomist_headers(ctx["phleb_id"])
    get_success_data(api.add_specimen_to_manifest(manifest["id"], {"specimen_id": ctx["specimens"][0]["id"]}, phleb_headers))
    validate_success(api.suspend_lab_partner(ctx["partner_id"], _LABOPS))
    validate_error(api.pickup_manifest(manifest["id"], _DISPATCHER),
                   ApiErrorId.ERR_LAB_PARTNER_SUSPENDED.value, 409)
    final = validate_success(api.get_manifest(manifest["id"], _DISPATCHER))
    assert final["status"] == "BUILDING"
