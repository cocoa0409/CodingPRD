"""Composite setup helpers, arranged from the simplest configuration record up
to the fully negotiated discrepancy case.

Every helper drives only the documented endpoints, asserts the expected status
of each setup call so that a broken precondition fails loudly, and returns a
plain dict of the identifiers and records a test needs. The server restarts
before each test, so every helper starts from an empty database.

Tiers
  1. single records .............. jurisdiction, agency, coverage cell, road
  2. base geography .............. jurisdiction + cell (+ road in a given state)
  3. live data ................... address points, assignment requests, boundaries
  4. quality and provisioning .... QC reports, defects, packages
  5. negotiation ................. discrepancy cases through to concurrence
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_success

from . import factories as f
from .api_client import ApiClient
from .test_users import (
    ANALYST_HEADERS,
    PERMIT_HEADERS,
    PROV_HEADERS,
    QC_HEADERS,
    SYSADMIN_HEADERS,
    make_agency_liaison_headers,
)


# ===========================================================================
# Clock control
# ===========================================================================
def set_clock(api: ApiClient, to_iso8601: str) -> str:
    """Set the logical clock and return the new ``current_utc``."""
    resp = api.set_clock(to_iso8601, SYSADMIN_HEADERS)
    data = validate_success(resp, 200)
    return data["current_utc"]


def reset_clock_to_startup(api: ApiClient) -> str:
    return set_clock(api, "2026-08-01T00:00:00Z")


# ===========================================================================
# Tier 1 — single records
# ===========================================================================
def setup_jurisdiction(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    resp = api.create_jurisdiction(f.jurisdiction_payload(**overrides), SYSADMIN_HEADERS)
    return validate_success(resp, 201)


def setup_agency(
    api: ApiClient,
    jurisdiction_id: str,
    agency_type: str = "LAW",
    name: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    default_names = {
        "LAW": "Larimer County Sheriff",
        "FIRE": "Poudre Fire Authority",
        "EMS": "Thompson Valley EMS",
    }
    payload = f.agency_payload(
        jurisdiction_id,
        agency_type=agency_type,
        name=name or default_names.get(agency_type, "Responding Agency"),
        **overrides,
    )
    resp = api.create_agency(payload, SYSADMIN_HEADERS)
    return validate_success(resp, 201)


def suspend_agency(api: ApiClient, agency_id: str, **overrides: Any) -> Dict[str, Any]:
    resp = api.suspend_agency(
        agency_id, f.suspend_agency_payload(**overrides), SYSADMIN_HEADERS
    )
    return validate_success(resp, 200)


def setup_coverage_cell(
    api: ApiClient, jurisdiction_id: str, cell_code: str = "C001", **overrides: Any
) -> Dict[str, Any]:
    payload = f.coverage_cell_payload(jurisdiction_id, cell_code=cell_code, **overrides)
    resp = api.create_coverage_cell(payload, ANALYST_HEADERS)
    return validate_success(resp, 201)


def setup_road(api: ApiClient, jurisdiction_id: str, **overrides: Any) -> Dict[str, Any]:
    """Create a DRAFT centerline; left 100-198 EVEN, right 101-199 ODD by default."""
    resp = api.create_road_centerline(
        f.road_centerline_payload(jurisdiction_id, **overrides), ANALYST_HEADERS
    )
    return validate_success(resp, 201)


def validate_road(api: ApiClient, road_id: str) -> Dict[str, Any]:
    return validate_success(api.validate_road_centerline(road_id, {}, ANALYST_HEADERS), 200)


def publish_road(api: ApiClient, road_id: str) -> Dict[str, Any]:
    return validate_success(api.publish_road_centerline(road_id, {}, QC_HEADERS), 200)


# ===========================================================================
# Tier 2 — base geography
# ===========================================================================
def setup_base_geography(
    api: ApiClient, cell_codes: Optional[List[str]] = None, **jurisdiction_overrides: Any
) -> Dict[str, Any]:
    """A jurisdiction plus one or more coverage cells."""
    jurisdiction = setup_jurisdiction(api, **jurisdiction_overrides)
    codes = cell_codes if cell_codes is not None else ["C001"]
    cells = [setup_coverage_cell(api, jurisdiction["id"], code) for code in codes]
    return {
        "jurisdiction": jurisdiction,
        "j_id": jurisdiction["id"],
        "cells": cells,
        "cell": cells[0] if cells else None,
        "cell_id": cells[0]["id"] if cells else None,
    }


def setup_geography_without_cells(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    jurisdiction = setup_jurisdiction(api, **overrides)
    return {"jurisdiction": jurisdiction, "j_id": jurisdiction["id"]}


def setup_draft_road_world(api: ApiClient, **road_overrides: Any) -> Dict[str, Any]:
    """Jurisdiction + one cell + one DRAFT centerline."""
    world = setup_base_geography(api)
    road = setup_road(api, world["j_id"], **road_overrides)
    world["road"] = road
    world["road_id"] = road["id"]
    return world


def setup_validated_road_world(api: ApiClient, **road_overrides: Any) -> Dict[str, Any]:
    world = setup_draft_road_world(api, **road_overrides)
    world["road"] = validate_road(api, world["road_id"])
    return world


def setup_published_road_world(api: ApiClient, **road_overrides: Any) -> Dict[str, Any]:
    world = setup_validated_road_world(api, **road_overrides)
    world["road"] = publish_road(api, world["road_id"])
    return world


# ===========================================================================
# Tier 3 — address points
# ===========================================================================
def setup_address_point(
    api: ApiClient, road_centerline_id: str, cell_id: Optional[str], **overrides: Any
) -> Dict[str, Any]:
    resp = api.create_address_point(
        f.address_point_payload(road_centerline_id, cell_id, **overrides),
        ANALYST_HEADERS,
    )
    return validate_success(resp, 201)


def setup_unit_point(
    api: ApiClient,
    road_centerline_id: str,
    cell_id: Optional[str],
    parent_id: str,
    unit_id: str = "1",
    house_number: int = 100,
    **overrides: Any,
) -> Dict[str, Any]:
    resp = api.create_address_point(
        f.unit_address_point_payload(
            road_centerline_id,
            cell_id,
            parent_id,
            house_number=house_number,
            unit_id=unit_id,
            **overrides,
        ),
        ANALYST_HEADERS,
    )
    return validate_success(resp, 201)


def activate_point(api: ApiClient, point_id: str) -> Dict[str, Any]:
    return validate_success(api.activate_address_point(point_id, {}, ANALYST_HEADERS), 200)


def retire_point(api: ApiClient, point_id: str, **overrides: Any) -> Dict[str, Any]:
    return validate_success(
        api.retire_address_point(
            point_id, f.retire_address_point_payload(**overrides), ANALYST_HEADERS
        ),
        200,
    )


def setup_active_point_on_published_road(api: ApiClient, **point_overrides: Any):
    """Jurisdiction + cell + PUBLISHED road + one ACTIVE geometry-verified point.

    This is the smallest world in which a package can hold a non-empty record
    set: one ROAD_CENTERLINE record and one ADDRESS_POINT record.
    """
    world = setup_validated_road_world(api)
    defaults = {"geometry_verified": True}
    defaults.update(point_overrides)
    point = setup_address_point(api, world["road_id"], world["cell_id"], **defaults)
    world["road"] = publish_road(api, world["road_id"])
    world["point"] = activate_point(api, point["id"])
    world["point_id"] = point["id"]
    return world


def setup_pending_point_on_draft_road(api: ApiClient, **point_overrides: Any):
    world = setup_draft_road_world(api)
    defaults = {"geometry_verified": True}
    defaults.update(point_overrides)
    point = setup_address_point(api, world["road_id"], world["cell_id"], **defaults)
    world["point"] = point
    world["point_id"] = point["id"]
    return world


# ===========================================================================
# Tier 3 — address assignment requests
# ===========================================================================
def setup_assignment_request(
    api: ApiClient, road_centerline_id: str, **overrides: Any
) -> Dict[str, Any]:
    resp = api.create_assignment_request(
        f.assignment_request_payload(road_centerline_id, **overrides), PERMIT_HEADERS
    )
    return validate_success(resp, 201)


def gis_review(api: ApiClient, request_id: str, decision: str = "APPROVE", **overrides):
    return validate_success(
        api.gis_review_assignment_request(
            request_id, f.gis_review_payload(decision, **overrides), ANALYST_HEADERS
        ),
        200,
    )


def utility_clearance(
    api: ApiClient, request_id: str, decision: str = "CLEAR", **overrides: Any
):
    return validate_success(
        api.utility_clearance_assignment_request(
            request_id,
            f.utility_clearance_payload(decision, **overrides),
            PERMIT_HEADERS,
        ),
        200,
    )


def setup_ready_to_assign_request(
    api: ApiClient, road_centerline_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A request whose review is approved and whose utilities are cleared."""
    request = setup_assignment_request(api, road_centerline_id, **overrides)
    gis_review(api, request["id"], "APPROVE")
    return utility_clearance(api, request["id"], "CLEAR")


def setup_fulfilled_request(
    api: ApiClient, road_centerline_id: str, **overrides: Any
) -> Dict[str, Any]:
    request = setup_ready_to_assign_request(api, road_centerline_id, **overrides)
    return validate_success(
        api.assign_assignment_request(request["id"], {}, ANALYST_HEADERS), 200
    )


def void_request(api: ApiClient, request_id: str, **overrides: Any) -> Dict[str, Any]:
    return validate_success(
        api.void_assignment_request(
            request_id, f.void_request_payload(**overrides), PERMIT_HEADERS
        ),
        200,
    )


# ===========================================================================
# Tier 3 — emergency service boundaries
# ===========================================================================
def setup_boundary(
    api: ApiClient, agency_id: str, **overrides: Any
) -> Dict[str, Any]:
    resp = api.create_boundary(
        f.boundary_payload(agency_id, **overrides), make_agency_liaison_headers(agency_id)
    )
    return validate_success(resp, 201)


def claim_cell(
    api: ApiClient,
    boundary_id: str,
    agency_id: str,
    cell_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Claim a cell for a DRAFT boundary, reading the boundary's live version first."""
    headers = make_agency_liaison_headers(agency_id)
    boundary = validate_success(api.get_boundary(boundary_id, headers), 200)
    payload = f.cell_assignment_payload(cell_id, boundary["version"], **overrides)
    return validate_success(api.create_cell_assignment(boundary_id, payload, headers), 201)


def propose_boundary(api: ApiClient, boundary_id: str, agency_id: str) -> Dict[str, Any]:
    return validate_success(
        api.propose_boundary(boundary_id, {}, make_agency_liaison_headers(agency_id)), 200
    )


def activate_boundary(api: ApiClient, boundary_id: str, agency_id: str) -> Dict[str, Any]:
    return validate_success(
        api.activate_boundary(boundary_id, {}, make_agency_liaison_headers(agency_id)), 200
    )


def retire_boundary(
    api: ApiClient, boundary_id: str, agency_id: str, **overrides: Any
) -> Dict[str, Any]:
    return validate_success(
        api.retire_boundary(
            boundary_id,
            f.retire_boundary_payload(**overrides),
            make_agency_liaison_headers(agency_id),
        ),
        200,
    )


def setup_proposed_boundary_on_cell(
    api: ApiClient,
    agency_id: str,
    cell_id: str,
    boundary_overrides: Optional[Dict[str, Any]] = None,
    claim_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A boundary holding one cell claim and advanced to PROPOSED."""
    boundary = setup_boundary(api, agency_id, **(boundary_overrides or {}))
    assignment = claim_cell(
        api, boundary["id"], agency_id, cell_id, **(claim_overrides or {})
    )
    boundary = propose_boundary(api, boundary["id"], agency_id)
    return {
        "boundary": boundary,
        "boundary_id": boundary["id"],
        "assignment": assignment,
        "assignment_id": assignment["id"],
        "agency_id": agency_id,
    }


def setup_active_boundary_on_cell(
    api: ApiClient,
    agency_id: str,
    cell_id: str,
    boundary_overrides: Optional[Dict[str, Any]] = None,
    claim_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    result = setup_proposed_boundary_on_cell(
        api, agency_id, cell_id, boundary_overrides, claim_overrides
    )
    result["boundary"] = activate_boundary(api, result["boundary_id"], agency_id)
    return result


def setup_full_coverage(
    api: ApiClient, jurisdiction_id: str, cell_id: str
) -> Dict[str, Any]:
    """One ACTIVE open-ended boundary per service type over the given cell, so the
    cell has zero gap pairs and the jurisdiction's covered_cell_count is 1."""
    result: Dict[str, Any] = {"agencies": {}, "boundaries": {}, "assignments": {}}
    for service_type in ("LAW", "FIRE", "EMS"):
        agency = setup_agency(api, jurisdiction_id, service_type)
        built = setup_active_boundary_on_cell(api, agency["id"], cell_id)
        result["agencies"][service_type] = agency
        result["boundaries"][service_type] = built["boundary"]
        result["assignments"][service_type] = built["assignment"]
    return result


# ===========================================================================
# Tier 4 — QC reports, defects and packages
# ===========================================================================
def setup_road_scoped_report(api: ApiClient, road_centerline_id: str) -> Dict[str, Any]:
    return validate_success(
        api.create_qc_report(f.qc_report_payload_road(road_centerline_id), ANALYST_HEADERS),
        201,
    )


def setup_jurisdiction_scoped_report(
    api: ApiClient, jurisdiction_id: str
) -> Dict[str, Any]:
    return validate_success(
        api.create_qc_report(
            f.qc_report_payload_jurisdiction(jurisdiction_id), ANALYST_HEADERS
        ),
        201,
    )


def certify_report(api: ApiClient, report_id: str, headers=None) -> Dict[str, Any]:
    return validate_success(
        api.certify_qc_report(report_id, {}, headers or QC_HEADERS), 200
    )


def reject_report(api: ApiClient, report_id: str, **overrides: Any) -> Dict[str, Any]:
    return validate_success(
        api.reject_qc_report(report_id, f.reject_report_payload(**overrides), QC_HEADERS),
        200,
    )


def list_defects(
    api: ApiClient, report_id: str, params: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    resp = api.list_qc_report_defects(report_id, params or {"limit": 100}, ANALYST_HEADERS)
    body = resp.json()
    assert resp.status_code == 200, f"defect listing failed: {resp.status_code} {body}"
    return body["data"]


def waive_defect(api: ApiClient, defect_id: str, **overrides: Any) -> Dict[str, Any]:
    return validate_success(
        api.waive_qc_defect(defect_id, f.waive_defect_payload(**overrides), QC_HEADERS),
        200,
    )


def setup_certified_report_on_published_road(api: ApiClient) -> Dict[str, Any]:
    """A world whose ROAD-scoped report is CERTIFIED with zero defects.

    The point is geometry-verified and postal-matching and the road is PUBLISHED
    and normalized, so the scan finds nothing and the report certifies outright.
    """
    world = setup_active_point_on_published_road(api)
    report = setup_road_scoped_report(api, world["road_id"])
    world["report"] = certify_report(api, report["id"])
    world["report_id"] = report["id"]
    return world


def setup_package(
    api: ApiClient, jurisdiction_id: str, qc_report_id: str, channel: str = "MAPPING"
) -> Dict[str, Any]:
    return validate_success(
        api.create_package(
            f.package_payload(jurisdiction_id, qc_report_id, channel), PROV_HEADERS
        ),
        201,
    )


def seal_package(api: ApiClient, package_id: str) -> Dict[str, Any]:
    return validate_success(api.seal_package(package_id, {}, PROV_HEADERS), 200)


def publish_package(api: ApiClient, package_id: str, headers=None) -> Dict[str, Any]:
    return validate_success(
        api.publish_package(package_id, {}, headers or PROV_HEADERS), 200
    )


def rollback_package(api: ApiClient, package_id: str, **overrides: Any) -> Dict[str, Any]:
    return validate_success(
        api.rollback_package(
            package_id, f.rollback_package_payload(**overrides), PROV_HEADERS
        ),
        200,
    )


def setup_sealed_package(api: ApiClient, channel: str = "MAPPING") -> Dict[str, Any]:
    """A SEALED package over the smallest non-empty record set."""
    world = setup_certified_report_on_published_road(api)
    package = setup_package(api, world["j_id"], world["report_id"], channel)
    world["package"] = seal_package(api, package["id"])
    world["package_id"] = package["id"]
    return world


def setup_published_package(api: ApiClient, channel: str = "MAPPING") -> Dict[str, Any]:
    world = setup_sealed_package(api, channel)
    world["package"] = publish_package(api, world["package_id"])
    return world


# ===========================================================================
# Tier 5 — discrepancy negotiation
# ===========================================================================
def setup_two_agencies(api: ApiClient, jurisdiction_id: str) -> Dict[str, Any]:
    opener = setup_agency(api, jurisdiction_id, "LAW")
    counterparty = setup_agency(api, jurisdiction_id, "FIRE")
    return {
        "opener": opener,
        "opener_id": opener["id"],
        "counterparty": counterparty,
        "counterparty_id": counterparty["id"],
    }


def setup_discrepancy_case(
    api: ApiClient,
    subject_ref_id: str,
    opener_agency_id: str,
    counterparty_agency_id: str,
    subject_type: str = "ROAD_NAME",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.discrepancy_case_payload(
        subject_ref_id, counterparty_agency_id, subject_type, **overrides
    )
    resp = api.create_discrepancy_case(
        payload, make_agency_liaison_headers(opener_agency_id)
    )
    return validate_success(resp, 201)


def file_proposal(
    api: ApiClient,
    case_id: str,
    acting_agency_id: str,
    proposed_value: str,
    expected_case_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """File a proposal, reading the case's live version when none is supplied."""
    headers = make_agency_liaison_headers(acting_agency_id)
    if expected_case_version is None:
        case = validate_success(api.get_discrepancy_case(case_id, headers), 200)
        expected_case_version = case["version"]
    payload = f.proposal_payload(proposed_value, expected_case_version, **overrides)
    return validate_success(api.create_proposal(case_id, payload, headers), 201)


def concur(
    api: ApiClient, case_id: str, acting_agency_id: str, proposal_id: str
) -> Dict[str, Any]:
    return validate_success(
        api.concur_discrepancy_case(
            case_id,
            f.concur_payload(proposal_id),
            make_agency_liaison_headers(acting_agency_id),
        ),
        200,
    )


def adopt(api: ApiClient, case_id: str) -> Dict[str, Any]:
    return validate_success(
        api.adopt_discrepancy_case(case_id, {}, SYSADMIN_HEADERS), 200
    )


def arbitrate(api: ApiClient, case_id: str, arbitration_value: str, **overrides: Any):
    return validate_success(
        api.arbitrate_discrepancy_case(
            case_id, f.arbitrate_payload(arbitration_value, **overrides), SYSADMIN_HEADERS
        ),
        200,
    )


def setup_case_on_road(api: ApiClient, world: Dict[str, Any]) -> Dict[str, Any]:
    """Open a ROAD_NAME case against ``world['road_id']``, freezing that road."""
    parties = setup_two_agencies(api, world["j_id"])
    case = setup_discrepancy_case(
        api, world["road_id"], parties["opener_id"], parties["counterparty_id"]
    )
    result = dict(parties)
    result["case"] = case
    result["case_id"] = case["id"]
    return result


def setup_concurred_case_on_road(
    api: ApiClient, world: Dict[str, Any], proposed_value: str = "N MAPLE AVE"
) -> Dict[str, Any]:
    """A case carrying one proposal by the opener that the counterparty concurred
    with, so the case sits at CONCURRED ready for adoption."""
    result = setup_case_on_road(api, world)
    proposal = file_proposal(
        api, result["case_id"], result["opener_id"], proposed_value
    )
    result["proposal"] = proposal
    result["proposal_id"] = proposal["id"]
    result["case"] = concur(
        api, result["case_id"], result["counterparty_id"], proposal["id"]
    )
    return result


def setup_escalated_case_on_road(
    api: ApiClient, world: Dict[str, Any]
) -> Dict[str, Any]:
    """Four filings — opener, counterparty, opener, counterparty — drive the case
    to ESCALATED on the fourth."""
    result = setup_case_on_road(api, world)
    sides = [
        result["opener_id"],
        result["counterparty_id"],
        result["opener_id"],
        result["counterparty_id"],
    ]
    proposals = []
    for index, agency_id in enumerate(sides, start=1):
        proposals.append(
            file_proposal(api, result["case_id"], agency_id, f"N MAPLE ROUND {index}")
        )
    result["proposals"] = proposals
    result["case"] = validate_success(
        api.get_discrepancy_case(
            result["case_id"], make_agency_liaison_headers(result["opener_id"])
        ),
        200,
    )
    return result


# ===========================================================================
# Read-back helpers
# ===========================================================================
def read_jurisdiction(api: ApiClient, jurisdiction_id: str) -> Dict[str, Any]:
    return validate_success(api.get_jurisdiction(jurisdiction_id, ANALYST_HEADERS), 200)


def read_agency(api: ApiClient, agency_id: str) -> Dict[str, Any]:
    return validate_success(api.get_agency(agency_id, ANALYST_HEADERS), 200)


def read_cell(api: ApiClient, cell_id: str) -> Dict[str, Any]:
    return validate_success(api.get_coverage_cell(cell_id, ANALYST_HEADERS), 200)


def read_coverage_status(api: ApiClient, cell_id: str) -> Dict[str, Any]:
    return validate_success(api.get_coverage_status(cell_id, ANALYST_HEADERS), 200)


def read_road(api: ApiClient, road_id: str) -> Dict[str, Any]:
    return validate_success(api.get_road_centerline(road_id, ANALYST_HEADERS), 200)


def read_point(api: ApiClient, point_id: str) -> Dict[str, Any]:
    return validate_success(api.get_address_point(point_id, ANALYST_HEADERS), 200)


def read_request(api: ApiClient, request_id: str) -> Dict[str, Any]:
    return validate_success(api.get_assignment_request(request_id, ANALYST_HEADERS), 200)


def read_boundary(api: ApiClient, boundary_id: str) -> Dict[str, Any]:
    return validate_success(api.get_boundary(boundary_id, ANALYST_HEADERS), 200)


def read_cell_assignment(api: ApiClient, assignment_id: str) -> Dict[str, Any]:
    return validate_success(api.get_cell_assignment(assignment_id, ANALYST_HEADERS), 200)


def read_report(api: ApiClient, report_id: str) -> Dict[str, Any]:
    return validate_success(api.get_qc_report(report_id, ANALYST_HEADERS), 200)


def read_defect(api: ApiClient, defect_id: str) -> Dict[str, Any]:
    return validate_success(api.get_qc_defect(defect_id, ANALYST_HEADERS), 200)


def read_package(api: ApiClient, package_id: str) -> Dict[str, Any]:
    return validate_success(api.get_package(package_id, ANALYST_HEADERS), 200)


def read_package_records(
    api: ApiClient, package_id: str, params: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    resp = api.list_package_records(package_id, params or {"limit": 100}, ANALYST_HEADERS)
    body = resp.json()
    assert resp.status_code == 200, f"record listing failed: {resp.status_code} {body}"
    return body["data"]


def read_case(api: ApiClient, case_id: str) -> Dict[str, Any]:
    return validate_success(api.get_discrepancy_case(case_id, ANALYST_HEADERS), 200)


def read_proposals(
    api: ApiClient, case_id: str, params: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    resp = api.list_proposals(case_id, params or {"limit": 100}, ANALYST_HEADERS)
    body = resp.json()
    assert resp.status_code == 200, f"proposal listing failed: {resp.status_code} {body}"
    return body["data"]


def list_all(api_method, params: Optional[Dict[str, Any]] = None, headers=None):
    """Call a listing endpoint with a generous limit and return (rows, meta)."""
    merged = {"limit": 100}
    merged.update(params or {})
    resp = api_method(merged, headers or ANALYST_HEADERS)
    body = resp.json()
    assert resp.status_code == 200, f"listing failed: {resp.status_code} {body}"
    return body["data"], body["meta"]


def defect_by_code(defects: List[Dict[str, Any]], defect_code: str) -> Dict[str, Any]:
    matches = [d for d in defects if d["defect_code"] == defect_code]
    assert matches, f"no defect with code {defect_code} among {[d['defect_code'] for d in defects]}"
    return matches[0]


def defects_by_code(defects: List[Dict[str, Any]], defect_code: str) -> List[Dict[str, Any]]:
    return [d for d in defects if d["defect_code"] == defect_code]


__all__ = [name for name in dir() if not name.startswith("_")]
