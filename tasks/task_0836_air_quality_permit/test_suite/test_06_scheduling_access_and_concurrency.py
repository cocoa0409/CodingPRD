"""Inspection scheduling, role-based access control, ownership, optimistic
concurrency, and FK listing.

Folds the smaller cross-cutting concerns (inspection windows, RBAC, OCC,
reverse-FK listing) into one file.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    register_facility, setup_facility_with_source, register_source, create_inspection,
    create_source_payload, current_facility_version,
    make_facility_operator_headers, TEST_USERS, build_user_headers,
)

REVIEWER = TEST_USERS["permit_reviewer_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]


# ─── resource_temporal_overlap / inspection_half_open_adjacency_allowed ───

def test_inspection_adjacent_at_end_boundary_allowed(api):
    """PRD §3.6: "The inspection window must not overlap any other inspection on the
    same facility, but back-to-back adjacency is allowed because the window is
    half-open".

    Design: Difficulty/resource_temporal_overlap/inspection_half_open_adjacency_allowed
    """
    facility = register_facility(name="Oscar Co")
    create_inspection(facility["id"], "2026-03-01T10:00:00Z", "2026-03-01T12:00:00Z")
    res = api.create_inspection({
        "facility_id": facility["id"],
        "scheduled_start": "2026-03-01T12:00:00Z",
        "scheduled_end": "2026-03-01T14:00:00Z",
    }, INSPECTOR)
    insp2 = validate_success(res, 201)
    assert insp2["status"] == "SCHEDULED"


def test_inspection_adjacent_at_start_boundary_allowed(api):
    """PRD §3.6: "The inspection window must not overlap any other inspection on the
    same facility, but back-to-back adjacency is allowed because the window is
    half-open".

    Design: Difficulty/resource_temporal_overlap/inspection_half_open_adjacency_allowed
    """
    facility = register_facility(name="Oscar Start Co")
    create_inspection(facility["id"], "2026-03-01T10:00:00Z", "2026-03-01T12:00:00Z")
    res = api.create_inspection({
        "facility_id": facility["id"],
        "scheduled_start": "2026-03-01T08:00:00Z",
        "scheduled_end": "2026-03-01T10:00:00Z",
    }, INSPECTOR)
    insp2 = validate_success(res, 201)
    assert insp2["status"] == "SCHEDULED"


def test_inspection_overlap_rejected(api):
    """PRD §3.6: "an overlap is rejected with ERR_INSPECTION_OVERLAP".

    Design: Corner/validations/inspection_overlap_returns_error
    """
    facility = register_facility(name="Golf2 Co")
    create_inspection(facility["id"], "2026-03-01T10:00:00Z", "2026-03-01T12:00:00Z")
    res = api.create_inspection({
        "facility_id": facility["id"],
        "scheduled_start": "2026-03-01T11:00:00Z",
        "scheduled_end": "2026-03-01T13:00:00Z",
    }, INSPECTOR)
    validate_error(res, "ERR_INSPECTION_OVERLAP")


# ─── rbac corner ───

def test_source_register_forbidden_for_inspector(api):
    """PRD §2.1: "When a recognized role attempts an operation it is not permitted
    to perform, the request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."

    Design: Corner/rbac/source_register_forbidden_for_inspector
    """
    facility = register_facility(name="Papa2 Co")
    payload = create_source_payload(
        facility["id"], facility["version"], source_type="BOILER", pollutant="NOX",
        max_hourly_rate_lbs=10, operating_hours_per_year=8760, permit_limit_ppm=50, control_efficiency=0)
    res = api.create_source(payload, INSPECTOR)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_missing_role_returns_unauthenticated(api):
    """PRD §2.1: "A request that omits X-User-Role or presents a value that is not
    one of the recognized roles is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_role_returns_unauthenticated
    """
    facility = register_facility(name="Quebec2 Co")
    headers = {"X-User-ID": "someone", "Content-Type": "application/json"}
    res = api.get_facility(facility["id"], headers)
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_operator_acting_on_other_facility_forbidden(api):
    """PRD §2.1: "When a FacilityOperator attempts an operator-owned write on a
    resource whose facility is not the one named by X-User-ID, the request is
    rejected with ERR_NOT_FACILITY_OWNER (HTTP 403); this ownership guard applies
    to source registration".

    Design: Corner/rbac/operator_wrong_owner_source_returns_forbidden
    """
    facility_a = register_facility(name="Romeo2 Co")
    facility_b = register_facility(name="Sierra2 Co")
    payload = create_source_payload(
        facility_a["id"], facility_a["version"], source_type="BOILER", pollutant="NOX",
        max_hourly_rate_lbs=10, operating_hours_per_year=8760, permit_limit_ppm=50, control_efficiency=0)
    res = api.create_source(payload, make_facility_operator_headers(facility_b["id"]))
    validate_error(res, "ERR_NOT_FACILITY_OWNER")


# ─── cross_cutting / optimistic concurrency ───

def test_stale_facility_version_on_source_register(api):
    """PRD §2.9: "If expected_facility_version does not equal the facility's current
    version — because another source registration already moved the potential-to-
    emit ... since the client last read the facility — the request is rejected with
    ERR_STALE_FACILITY_VERSION (HTTP 412)".

    Design: Corner/cross_cutting/stale_facility_version_on_source_register
    """
    facility = register_facility(name="Tango2 Co")
    stale_version = facility["version"]
    register_source(facility["id"], source_type="BOILER", pollutant="NOX",
                    max_hourly_rate_lbs=10, operating_hours_per_year=8760,
                    permit_limit_ppm=50, control_efficiency=0)
    payload = create_source_payload(
        facility["id"], stale_version, source_type="FLARE", pollutant="VOC",
        max_hourly_rate_lbs=5, operating_hours_per_year=8760, permit_limit_ppm=40, control_efficiency=0)
    res = api.create_source(payload, make_facility_operator_headers(facility["id"]))
    validate_error(res, "ERR_STALE_FACILITY_VERSION")


def test_stale_facility_version_on_certify(api):
    """PRD §2.9: "If expected_facility_version does not equal the facility's current
    version ... the request is rejected with ERR_STALE_FACILITY_VERSION (HTTP 412)".

    Design: Corner/cross_cutting/stale_facility_version_on_certify
    """
    from test_helpers import setup_submitted_inventory
    facility, source = setup_facility_with_source("Uniform2 Co", max_hourly_rate_lbs=50)
    inv = setup_submitted_inventory(facility["id"], source["id"], [10.000])
    current = current_facility_version(facility["id"])
    res = api.certify_inventory(inv["id"], {"expected_facility_version": current - 1}, REVIEWER)
    validate_error(res, "ERR_STALE_FACILITY_VERSION")


# ─── endpoints corner ───

def test_list_facility_sources_returns_both(api):
    """PRD §3.1: "The facility is the aggregate root: sources, permits, inventories,
    complaints, inspections, and enforcement actions all reference it by
    facility_id". PRD §2.3: "Every list response includes limit, offset,
    total_count, and has_more in the meta object of the envelope."

    Design: Corner/endpoints/list_facility_sources_paginated
    """
    facility, source_a = setup_facility_with_source(
        "November2 Co", source_type="BOILER", pollutant="NOX", max_hourly_rate_lbs=10,
        operating_hours_per_year=8760, permit_limit_ppm=50)
    register_source(facility["id"], source_type="FLARE", pollutant="VOC",
                    max_hourly_rate_lbs=5, operating_hours_per_year=8760,
                    permit_limit_ppm=40, control_efficiency=0)
    op = make_facility_operator_headers(facility["id"])
    data, meta = validate_paginated(api.list_facility_sources(facility["id"], op))
    assert meta["total_count"] == 2
