"""Entity creation, defaults, required fields, type constraints, not-found, and
reverse-reachability listings.

Queue B corner sections: entities, endpoints.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    set_clock, create_unit, add_bed,
    register_and_admit, register_encounter,
    create_unit_payload, create_bed_payload, create_encounter_payload,
    create_bed_request_payload,
    NON_EXISTENT_PATH_UUID,
)
from test_helpers.fixtures import ADMIN, BCC, NURSE, TCA


# ============================================================================
# Corner: entities / create_unit_returns_201_with_computed_defaults
# ============================================================================

def test_create_unit_initial_computed_state(api, flow_admin_headers):
    """PRD §3.1: "A new unit begins with all four bed counts at 0, derived_posture
    and effective_posture both CLOSED, and declared_surge_level at GREEN."

    Design: Corner/entities/create_unit_returns_201_with_computed_defaults
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.create_unit(create_unit_payload(name="Ward A", unit_type="MEDSURG"),
                          flow_admin_headers)
    unit = validate_success(res, 201)
    assert unit["staffed_bed_count"] == 0
    assert unit["derived_posture"] == "CLOSED"
    assert unit["effective_posture"] == "CLOSED"
    assert unit["declared_surge_level"] == "GREEN"
    assert unit["version"] == 1


# ============================================================================
# Corner: entities / create_unit_gmlos_default_applied
# ============================================================================

def test_create_unit_gmlos_defaults_to_three(api, flow_admin_headers):
    """PRD §3.1: "optionally a gmlos_days benchmark (the geometric-mean
    length-of-stay target in days for that unit, defaulting to 3)".

    Design: Corner/entities/create_unit_gmlos_default_applied
    """
    res = api.create_unit(create_unit_payload(name="Ward B", unit_type="ICU"),
                          flow_admin_headers)
    unit = validate_success(res, 201)
    assert unit["gmlos_days"] == 3


# ============================================================================
# Corner: entities / create_encounter_missing_sex_returns_invalid_request
# ============================================================================

def test_create_encounter_missing_sex_invalid_request(api, bed_control_headers):
    """PRD §3.3: "registers an encounter, supplying the patient's mrn, sex (MALE or
    FEMALE)" — PRD §2.6: "required fields present and enum values legal
    (ERR_INVALID_REQUEST, HTTP 422)."

    Design: Corner/entities/create_encounter_missing_sex_returns_invalid_request
    """
    res = api.create_encounter({"mrn": "MX1", "origin": "ED"}, bed_control_headers)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


# ============================================================================
# Corner: entities / create_encounter_invalid_enum_origin_returns_invalid_request
# ============================================================================

def test_create_encounter_invalid_origin_enum(api, bed_control_headers):
    """PRD §3.3: "The origin is one of ED, DIRECT, or TRANSFER_IN" — PRD §2.6:
    "enum values legal (ERR_INVALID_REQUEST, HTTP 422)."

    Design: Corner/entities/create_encounter_invalid_enum_origin_returns_invalid_request
    """
    res = api.create_encounter({"mrn": "MX2", "sex": "MALE", "origin": "WALKIN"},
                               bed_control_headers)
    validate_error(res, "ERR_INVALID_REQUEST")


# ============================================================================
# Corner: entities / create_encounter_defaults_origin_ed_and_flags_false
# ============================================================================

def test_create_encounter_defaults(api, bed_control_headers):
    """PRD §3.3: "The origin is one of ED, DIRECT, or TRANSFER_IN and defaults to ED"
    — "A new encounter starts in REGISTERED".

    Design: Corner/entities/create_encounter_defaults_origin_ed_and_flags_false
    """
    res = api.create_encounter({"mrn": "MX3", "sex": "FEMALE"}, bed_control_headers)
    enc = validate_success(res, 201)
    assert enc["origin"] == "ED"
    assert enc["requires_isolation"] is False
    assert enc["requires_telemetry"] is False
    assert enc["status"] == "REGISTERED"


# ============================================================================
# Corner: entities / get_unit_nonexistent_returns_not_found
# ============================================================================

def test_get_nonexistent_unit_not_found(api, bed_control_headers):
    """PRD §2.5: "returns ERR_NOT_FOUND (HTTP 404) as soon as any referenced resource
    in the path does not exist."

    Design: Corner/entities/get_unit_nonexistent_returns_not_found
    """
    res = api.get_unit(NON_EXISTENT_PATH_UUID, bed_control_headers)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


# ============================================================================
# Corner: entities / create_bed_system_fields_ignored_and_starts_dirty
# ============================================================================

def test_create_bed_starts_dirty_cohort_none(api, flow_admin_headers, charge_nurse_headers):
    """PRD §3.1: "A freshly added bed enters life in DIRTY status with sex_cohort set
    to NONE".

    Design: Corner/entities/create_bed_system_fields_ignored_and_starts_dirty
    """
    unit = validate_success(
        api.create_unit(create_unit_payload(name="Ward C", unit_type="MEDSURG"),
                        flow_admin_headers), 201)
    # client-supplied status must be ignored.
    payload = create_bed_payload(unit["id"], label="C1")
    payload["status"] = "OCCUPIED"
    res = api.create_bed(unit["id"], payload, charge_nurse_headers)
    bed = validate_success(res, 201)
    assert bed["status"] == "DIRTY"
    assert bed["sex_cohort"] == "NONE"
    assert bed["version"] == 1


# ============================================================================
# Corner: entities / create_bedrequest_reference_not_found_encounter
# ============================================================================

def test_create_bedrequest_unknown_encounter_reference_not_found(api, transfer_agent_headers):
    """PRD §2.5: "FK references carried in a request body — such as encounter_id,
    bed_id, unit_id, or preferred_unit_id — are validated separately: if a
    body-referenced resource does not resolve, the request fails with
    ERR_REFERENCE_NOT_FOUND (HTTP 404)".

    Design: Corner/entities/create_bedrequest_reference_not_found_encounter
    """
    res = api.create_bed_request(
        {"encounter_id": "00000000-0000-4000-8000-000000000001"}, transfer_agent_headers)
    validate_error(res, "ERR_REFERENCE_NOT_FOUND")


# ============================================================================
# Corner: endpoints / get_beds_filtered_by_unit_reverse_reachability
# ============================================================================

def test_list_beds_in_unit(api, flow_admin_headers, charge_nurse_headers):
    """PRD §3.1: "Beds may be browsed within a unit, and a status filter narrows that
    listing".

    Design: Corner/endpoints/get_beds_filtered_by_unit_reverse_reachability
    """
    unit = validate_success(
        api.create_unit(create_unit_payload(name="FbWard", unit_type="MEDSURG"),
                        flow_admin_headers), 201)
    api.create_bed(unit["id"], create_bed_payload(unit["id"], label="FB1"), charge_nurse_headers)
    api.create_bed(unit["id"], create_bed_payload(unit["id"], label="FB2"), charge_nurse_headers)

    beds, meta = validate_paginated(api.list_beds(unit["id"], charge_nurse_headers))
    assert meta["total_count"] == 2


# ============================================================================
# Corner: endpoints / get_adt_events_for_encounter
# ============================================================================

def test_adt_events_contain_admit_after_admit_order(api, bed_control_headers):
    """PRD §3.3: "an admit ADT event is appended" — PRD §3.10: "the ADT event listing
    for an encounter exposes each event's encounter_id, event_type (ADMIT, PLACE,
    TRANSFER, DISCHARGE_ORDER, DISCHARGE, or CANCEL)".

    Design: Corner/endpoints/get_adt_events_for_encounter
    """
    set_clock("2026-06-05T08:00:00Z")
    enc = register_and_admit(mrn="MS14", sex="FEMALE", origin="DIRECT")
    events, meta = validate_paginated(api.list_adt_events(enc["id"], bed_control_headers))
    assert meta["total_count"] == 1
    assert events[0]["event_type"] == "ADMIT"
