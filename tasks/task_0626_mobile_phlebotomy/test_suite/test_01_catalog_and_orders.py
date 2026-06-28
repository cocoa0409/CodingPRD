"""Catalog/order creation, defaults, computed fields, immutability, listing, and not-found.

Corner queue (B) instances under sections: entities, consistency_model, endpoints.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    setup_catalog, create_partner, create_panel,
    setup_scheduled_appointment, drive_to_arrived,
    create_test_panel_payload, create_lab_order_payload,
    make_phlebotomist_headers, collect_specimen_payload,
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
)

_LABOPS = TEST_USERS["lab_ops_headers"]
_PROVIDER = TEST_USERS["ordering_provider_headers"]
_DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_create_test_panel_returns_201_with_defaults(api):
    """PRD §3.1: "A new panel begins life in ACTIVE status."
    PRD §2.4: "an integer version that begins at its initial value and increments by one on
    every mutation."

    Design: Corner/entities/create_test_panel_returns_201_with_fields
    """
    payload = create_test_panel_payload(panel_code="LIPID", name="Lipid Panel",
                                        required_tube_count=1, base_lab_fee_cents=1800,
                                        fasting_required=True)
    panel = validate_success(api.create_test_panel(payload, _LABOPS), 201)
    assert panel["status"] == "ACTIVE", f"expected ACTIVE, got {panel['status']}"
    assert panel["required_tube_count"] == 1
    assert panel["version"] == 1, f"expected version 1, got {panel['version']}"


def test_get_lab_order_not_found(api):
    """PRD §2.6: "The system validates every identifier in the path from left to right and rejects
    the request at the first identifier that does not resolve to an existing resource, using the
    not-found error specific to that resource type."

    Design: Corner/entities/get_lab_order_not_found_returns_404
    """
    validate_error(api.get_lab_order(NON_EXISTENT_UUID, _PROVIDER),
                   ApiErrorId.ERR_ORDER_NOT_FOUND.value, 404)


def test_create_lab_order_missing_panel_code_rejected(api):
    """PRD §3.3: "The create payload supplies the patient_full_name, the patient_territory_code
    (the patient's service territory), the panel_code being ordered, the lab_partner_id of the
    partner that will process the specimens, and the billing_mode, which is either INSURANCE or
    SELF_PAY."
    PRD §2.7: "fifth, request-body well-formedness — required fields present, enums valid, integers
    non-negative, an appointment's window end strictly after its window start, and an insurance
    order carrying its member id (ERR_INVALID_REQUEST)"

    Design: Corner/entities/create_lab_order_missing_panel_code_returns_invalid_request
    """
    _, partner = setup_catalog(panel_code="CMP14", accepted_panel_codes=["CMP14"])
    resp = api.create_lab_order({
        "patient_full_name": "Sam", "patient_territory_code": "SF_BAY",
        "lab_partner_id": partner["id"], "billing_mode": "SELF_PAY",
    }, _PROVIDER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_create_insurance_order_missing_member_id_rejected(api):
    """PRD §3.3: "When billing_mode is INSURANCE, the payload must also include an
    insurance_member_id; an insurance order missing that field is malformed and rejected with
    ERR_INVALID_REQUEST."

    Design: Corner/entities/create_insurance_order_missing_member_id_returns_invalid_request
    """
    _, partner = setup_catalog(panel_code="CMP14", accepted_panel_codes=["CMP14"])
    resp = api.create_lab_order({
        "patient_full_name": "Sam", "patient_territory_code": "SF_BAY", "panel_code": "CMP14",
        "lab_partner_id": partner["id"], "billing_mode": "INSURANCE",
    }, _PROVIDER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_order_priority_defaults_to_routine(api):
    """PRD §3.3: "An optional priority of either ROUTINE or STAT may be supplied; it defaults to
    ROUTINE, and STAT is what causes the partner's stat surcharge to apply."

    Design: Corner/entities/order_priority_defaults_routine
    """
    _, partner = setup_catalog(panel_code="CMP14", accepted_panel_codes=["CMP14"])
    order = get_success_data(api.create_lab_order(create_lab_order_payload(
        panel_code="CMP14", lab_partner_id=partner["id"], billing_mode="SELF_PAY"), _PROVIDER))
    assert order["priority"] == "ROUTINE", f"expected ROUTINE, got {order['priority']}"
    assert order["status"] == "ORDERED"


def test_order_specimens_required_count_mirrors_panel(api):
    """PRD §3.3: "At this point the server mirrors the ordered panel's required_tube_count onto
    the order as specimens_required_count, initializes specimens_accessioned_count and
    redraw_count to zero, leaves appointment_id unset until an appointment is booked, and stamps
    a provisional total_due_cents (see §3.9)."

    Design: Corner/entities/order_specimens_required_count_mirrors_panel
    """
    _, partner = setup_catalog(panel_code="CMP14", required_tube_count=3, accepted_panel_codes=["CMP14"])
    order = get_success_data(api.create_lab_order(create_lab_order_payload(
        panel_code="CMP14", lab_partner_id=partner["id"], billing_mode="SELF_PAY"), _PROVIDER))
    assert order["specimens_required_count"] == 3, \
        f"expected 3, got {order['specimens_required_count']}"
    assert order["redraw_count"] == 0


def test_custody_event_is_immutable_first_event_is_collected(api):
    """PRD §2.4: "A ChainOfCustodyEvent is an append-only, immutable audit record: it carries only
    an id and a created_at. It has no updated_at and no version, because it is never modified after
    it is written."
    PRD §3.7: "When a specimen is first collected, the system appends its first event with type
    COLLECTED and sequence_index zero."

    Design: Corner/entities/custody_event_immutable_no_version_field
    """
    ctx = setup_scheduled_appointment(panel_code="ONE", required_tube_count=1, base_lab_fee_cents=1000)
    drive_to_arrived(ctx, kit_tube_count=1)
    phleb_headers = make_phlebotomist_headers(ctx["phleb_id"])
    sp1 = get_success_data(api.collect_specimen(ctx["appt_id"], collect_specimen_payload("T1"), phleb_headers))
    events, _ = validate_paginated(api.list_specimen_custody_events(sp1["id"], _LABOPS))
    assert len(events) == 1, f"expected one custody event, got {len(events)}"
    ev0 = events[0]
    assert ev0["event_type"] == "COLLECTED", f"expected COLLECTED, got {ev0['event_type']}"
    assert ev0["sequence_index"] == 0
    assert "version" not in ev0, "custody event must not carry a version field"
    assert "updated_at" not in ev0, "custody event must not carry an updated_at field"


def test_list_lab_orders_returns_paginated_envelope(api):
    """PRD §2.3: "Every list response includes the following four fields inside the envelope's meta
    object: limit, offset, total_count, and has_more."

    Design: Corner/entities/list_lab_orders_pagination_envelope
    """
    _, partner = setup_catalog(panel_code="CMP14", accepted_panel_codes=["CMP14"])
    get_success_data(api.create_lab_order(create_lab_order_payload(
        panel_code="CMP14", lab_partner_id=partner["id"], billing_mode="SELF_PAY"), _PROVIDER))
    data, meta = validate_paginated(api.list_lab_orders(_DISPATCHER, params={"limit": 5, "offset": 0}))
    assert meta["total_count"] >= 1, f"expected >=1 order, got {meta['total_count']}"
    assert meta["has_more"] is False
    assert "limit" in meta and "offset" in meta


# ---------------------------------------------------------------------------
# Corner — consistency_model
# ---------------------------------------------------------------------------

def test_order_create_returns_all_computed_fields_immediately(api):
    """PRD §3.3: "At this point the server mirrors the ordered panel's required_tube_count onto
    the order as specimens_required_count, initializes specimens_accessioned_count and
    redraw_count to zero, leaves appointment_id unset until an appointment is booked, and stamps
    a provisional total_due_cents (see §3.9)."
    PRD §3.10: "They can diverge: the estimate is first stamped at order creation when redraw_count
    is zero (so it carries no redraw waiver), whereas the final invoice reflects whatever redraws
    actually accrued between order creation and issue."

    Design: Corner/consistency_model/immediate_visibility_of_specimens_required_count_on_create
    """
    _, partner = setup_catalog(panel_code="CMP14", required_tube_count=3, base_lab_fee_cents=4000,
                               accepted_panel_codes=["CMP14"])
    order = get_success_data(api.create_lab_order(create_lab_order_payload(
        panel_code="CMP14", lab_partner_id=partner["id"], billing_mode="SELF_PAY"), _PROVIDER))
    assert order["specimens_required_count"] == 3
    # SELF_PAY base 4000, 3 tubes, redraw 0: 4000 + (3500 + 2*500) - 0 = 8500.
    assert order["total_due_cents"] == 8500, f"expected 8500, got {order['total_due_cents']}"
    assert order["status"] == "ORDERED"


# ---------------------------------------------------------------------------
# Corner — endpoints
# ---------------------------------------------------------------------------

def test_kit_assignment_returns_201_assigned(api):
    """PRD §3.5: "The kit payload carries a kit_lot_number (the manufacturer lot number) and a
    tube_count giving how many empty tubes are loaded (at least one). The kit records its
    appointment_id and begins in ASSIGNED status."

    Design: Corner/endpoints/kit_assignment_returns_201_assigned
    """
    ctx = setup_scheduled_appointment(panel_code="CMP14", required_tube_count=3, base_lab_fee_cents=4000)
    kit = validate_success(api.assign_kit(ctx["appt_id"], {"kit_lot_number": "L1", "tube_count": 3}, _DISPATCHER), 201)
    assert kit["status"] == "ASSIGNED", f"expected ASSIGNED, got {kit['status']}"
    assert kit["tube_count"] == 3


def test_get_custody_events_returns_ordered_chain(api):
    """PRD §3.7: "When the specimen is batched onto a manifest, an event of type MANIFESTED is
    appended, linked to the prior event."
    PRD §3.7: "a sequence_index giving the event's zero-based position in the specimen's chain."

    Design: Corner/endpoints/get_custody_events_by_specimen_filter
    """
    from test_helpers import drive_to_draw_completed, create_manifest_payload
    ctx = setup_scheduled_appointment(panel_code="ONE", required_tube_count=1, base_lab_fee_cents=1000)
    drive_to_draw_completed(ctx)
    manifest = get_success_data(api.create_manifest(create_manifest_payload(ctx["partner_id"]), _DISPATCHER))
    phleb_headers = make_phlebotomist_headers(ctx["phleb_id"])
    sp1 = ctx["specimens"][0]["id"]
    get_success_data(api.add_specimen_to_manifest(manifest["id"], {"specimen_id": sp1}, phleb_headers))
    events, _ = validate_paginated(api.list_specimen_custody_events(sp1, _LABOPS))
    assert len(events) == 2, f"expected 2 events (COLLECTED, MANIFESTED), got {len(events)}"
    assert events[1]["event_type"] == "MANIFESTED", f"expected MANIFESTED at index 1, got {events[1]['event_type']}"
