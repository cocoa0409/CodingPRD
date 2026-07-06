"""Site and report creation, defaults, computed/system fields, and existence.

Queue B (Corner): sections `entities` and `state_machines`.
"""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId, NON_EXISTENT_UUID,
    validate_success, validate_error,
    create_site_payload, create_report_payload, create_material_payload,
    create_property_owner_payload,
)

COORD = TEST_USERS["coordinator_headers"]
CLERK = TEST_USERS["intake_clerk_headers"]
INV = TEST_USERS["inventory_manager_headers"]
ADMIN = TEST_USERS["program_admin_headers"]


def test_create_site_returns_201_normal_and_zero_counters(api):
    """PRD §3.1: "A new site starts with `status` of `NORMAL` and all of its computed
    counters at zero: `report_count_90d`, `open_report_count`, `hotspot_severity_index_rolling`,
    `hotspot_severity_index_confirmed`, `outstanding_recovery_cents`, and `lien_count`, along
    with a null `active_notice_id`."

    Design: Corner/entities/create_site_returns_201_with_fields
    """
    resp = api.create_site(create_site_payload(ownership_type="PUBLIC"), COORD)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "NORMAL"
    assert data["report_count_90d"] == 0
    assert data["open_report_count"] == 0
    assert data["hotspot_severity_index_rolling"] == 0
    assert data["hotspot_severity_index_confirmed"] == 0
    assert data["outstanding_recovery_cents"] == 0
    assert data["lien_count"] == 0
    assert data["active_notice_id"] is None


def test_get_nonexistent_site_returns_not_found(api):
    """PRD §2.8: "the system checks each referenced identifier in order ... and rejects the
    request at the first identifier that does not resolve, returning the matching not-found
    error: `ERR_SITE_NOT_FOUND` ... each carrying HTTP 404."

    Design: Corner/entities/get_site_nonexistent_returns_not_found
    """
    resp = api.get_site(NON_EXISTENT_UUID, COORD)
    validate_error(resp, ApiErrorId.ERR_SITE_NOT_FOUND)


def test_create_report_missing_severity_returns_invalid_request(api):
    """PRD §2.10: "Third is request well-formedness — required fields present, types and enums
    valid, and `scheduled_end` strictly after `scheduled_start` — a failure of which yields
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_report_missing_severity_returns_invalid_request
    """
    site = validate_success(api.create_site(create_site_payload(ownership_type="PUBLIC"), COORD), 201)
    payload = {
        "site_id": site["id"],
        "reported_via": "WEB",
        "surface_type": "WALL",
        "description": "no severity",
    }
    resp = api.create_report(payload, CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_report_is_offensive_defaults_false(api):
    """PRD §3.2: "`is_offensive` marks hateful or offensive content and defaults to false;
    `latitude` and `longitude` pin the precise incident and default to null; and
    `reporter_contact` records an optional call-back contact and defaults to null."

    Design: Corner/entities/report_is_offensive_defaults_false
    """
    site = validate_success(api.create_site(create_site_payload(ownership_type="PUBLIC"), COORD), 201)
    payload = create_report_payload(site["id"], severity="LOW", surface_type="WALL")
    data = validate_success(api.create_report(payload, CLERK), 201)
    assert data["is_offensive"] is False


def test_material_status_low_when_available_at_threshold(api):
    """PRD §3.7: "it is `DEPLETED` when `quantity_available` is at or below 0; otherwise it is
    `LOW` when `quantity_available` is at or below the `reorder_threshold`; otherwise it is
    `AVAILABLE`."

    Design: Corner/entities/material_status_computed_from_quantities
    """
    payload = create_material_payload(name="Low Paint", unit_cost_cents=1000,
                                      quantity_available=5.0, reorder_threshold=5.0)
    data = validate_success(api.create_material(payload, INV), 201)
    assert data["status"] == "LOW"


def test_report_system_fields_generated(api):
    """PRD §3.2: "A newly filed report enters `SUBMITTED` status with a null `priority_score`."

    Design: Corner/entities/report_system_fields_generated_input_ignored
    """
    site = validate_success(api.create_site(create_site_payload(ownership_type="PUBLIC"), COORD), 201)
    payload = create_report_payload(site["id"], severity="LOW", surface_type="WALL")
    data = validate_success(api.create_report(payload, CLERK), 201)
    assert data["status"] == "SUBMITTED"
    assert data["priority_score"] is None


def test_site_invalid_ownership_enum_returns_invalid_request(api):
    """PRD §2.10: "Third is request well-formedness — required fields present, types and enums
    valid, and `scheduled_end` strictly after `scheduled_start` — a failure of which yields
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/site_invalid_ownership_enum_returns_invalid_request
    """
    payload = {"ownership_type": "MUNICIPAL", "address": "5 Way", "latitude": 41.0, "longitude": -73.0}
    resp = api.create_site(payload, COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_report_references_missing_site_returns_not_found(api):
    """PRD §2.8: "existence is validated left to right: the system checks each referenced
    identifier in order — `site_id`, then `report_id` ... and rejects the request at the first
    identifier that does not resolve, returning the matching not-found error: `ERR_SITE_NOT_FOUND`".

    Design: Corner/entities/report_references_missing_site_returns_not_found
    """
    payload = create_report_payload("00000000-0000-4000-8000-000000000001",
                                    severity="LOW", surface_type="WALL")
    resp = api.create_report(payload, CLERK)
    validate_error(resp, ApiErrorId.ERR_SITE_NOT_FOUND)


def test_new_report_initial_state_submitted(api):
    """PRD §3.2: "A newly filed report enters `SUBMITTED` status with a null `priority_score`."

    Design: Corner/state_machines/new_report_initial_state_submitted
    """
    site = validate_success(api.create_site(create_site_payload(ownership_type="PUBLIC"), COORD), 201)
    payload = create_report_payload(site["id"], severity="LOW", surface_type="WALL")
    data = validate_success(api.create_report(payload, CLERK), 201)
    assert data["status"] == "SUBMITTED"
