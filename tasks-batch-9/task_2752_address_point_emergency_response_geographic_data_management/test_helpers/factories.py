"""Payload factories: valid-by-default request bodies with keyword overrides.

Numeric fields are emitted as JSON numbers, never as strings. Passing an
override of ``None`` sets the field to null; use ``omit=[...]`` to drop keys
entirely so that required-field tests can distinguish missing from null.
"""

from typing import Any, Dict, Iterable, Optional

# ---------------------------------------------------------------------------
# Canonical literals reused across scenarios
# ---------------------------------------------------------------------------
DEFAULT_JURISDICTION_NAME = "Larimer County"
DEFAULT_JURISDICTION_CODE = "LARCO"
DEFAULT_POSTAL_CITY = "FORT COLLINS"
DEFAULT_ROAD_NAME = "N MAPLE STREET"
DEFAULT_CELL_CODE = "C001"


def _apply(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    omit: Iterable[str] = overrides.pop("omit", []) or []
    payload.update(overrides)
    for key in omit:
        payload.pop(key, None)
    return payload


# ---------------------------------------------------------------------------
# Jurisdiction
# ---------------------------------------------------------------------------
def jurisdiction_payload(**overrides: Any) -> Dict[str, Any]:
    return _apply(
        {
            "name": DEFAULT_JURISDICTION_NAME,
            "code": DEFAULT_JURISDICTION_CODE,
            "jurisdiction_type": "COUNTY",
            "postal_city": DEFAULT_POSTAL_CITY,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Agency
# ---------------------------------------------------------------------------
def agency_payload(jurisdiction_id: str, **overrides: Any) -> Dict[str, Any]:
    return _apply(
        {
            "name": "Larimer County Sheriff",
            "agency_type": "LAW",
            "jurisdiction_id": jurisdiction_id,
        },
        overrides,
    )


def suspend_agency_payload(**overrides: Any) -> Dict[str, Any]:
    return _apply(
        {"suspended_reason": "Consolidated into the regional dispatch authority"},
        overrides,
    )


# ---------------------------------------------------------------------------
# Coverage cell
# ---------------------------------------------------------------------------
def coverage_cell_payload(jurisdiction_id: str, **overrides: Any) -> Dict[str, Any]:
    return _apply(
        {"cell_code": DEFAULT_CELL_CODE, "jurisdiction_id": jurisdiction_id},
        overrides,
    )


# ---------------------------------------------------------------------------
# Road centerline
# ---------------------------------------------------------------------------
def road_centerline_payload(jurisdiction_id: str, **overrides: Any) -> Dict[str, Any]:
    """Left range 100-198 EVEN (capacity 50), right range 101-199 ODD."""
    return _apply(
        {
            "primary_name": DEFAULT_ROAD_NAME,
            "jurisdiction_id": jurisdiction_id,
            "from_addr_left": 100,
            "to_addr_left": 198,
            "parity_left": "EVEN",
            "from_addr_right": 101,
            "to_addr_right": 199,
            "parity_right": "ODD",
        },
        overrides,
    )


def road_patch_payload(expected_road_version: int, **overrides: Any) -> Dict[str, Any]:
    return _apply({"expected_road_version": expected_road_version}, overrides)


def retire_road_payload(**overrides: Any) -> Dict[str, Any]:
    return _apply(
        {"retire_reason": "Segment vacated by the board of county commissioners"},
        overrides,
    )


# ---------------------------------------------------------------------------
# Address point
# ---------------------------------------------------------------------------
def address_point_payload(
    road_centerline_id: str, cell_id: Optional[str], **overrides: Any
) -> Dict[str, Any]:
    return _apply(
        {
            "house_number": 100,
            "road_centerline_id": road_centerline_id,
            "side": "LEFT",
            "source": "PARCEL",
            "postal_city": DEFAULT_POSTAL_CITY,
            "cell_id": cell_id,
        },
        overrides,
    )


def unit_address_point_payload(
    road_centerline_id: str,
    cell_id: Optional[str],
    parent_address_point_id: str,
    house_number: int = 100,
    unit_id: str = "1",
    **overrides: Any,
) -> Dict[str, Any]:
    return _apply(
        {
            "house_number": house_number,
            "road_centerline_id": road_centerline_id,
            "side": "LEFT",
            "source": "PARCEL",
            "postal_city": DEFAULT_POSTAL_CITY,
            "cell_id": cell_id,
            "unit_type": "UNIT",
            "unit_id": unit_id,
            "parent_address_point_id": parent_address_point_id,
        },
        overrides,
    )


def retire_address_point_payload(**overrides: Any) -> Dict[str, Any]:
    return _apply({"retire_reason": "Structure demolished after fire loss"}, overrides)


# ---------------------------------------------------------------------------
# Address assignment request
# ---------------------------------------------------------------------------
def assignment_request_payload(
    road_centerline_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _apply(
        {
            "permit_number": "BP-2026-0001",
            "parcel_id": "8712300001",
            "road_centerline_id": road_centerline_id,
            "side": "LEFT",
        },
        overrides,
    )


def gis_review_payload(decision: str = "APPROVE", **overrides: Any) -> Dict[str, Any]:
    return _apply({"decision": decision}, overrides)


def utility_clearance_payload(
    decision: str = "CLEAR", **overrides: Any
) -> Dict[str, Any]:
    return _apply({"decision": decision}, overrides)


def void_request_payload(**overrides: Any) -> Dict[str, Any]:
    return _apply(
        {"void_reason": "Permit withdrawn by the applicant before foundation inspection"},
        overrides,
    )


# ---------------------------------------------------------------------------
# Emergency service boundary and cell claims
# ---------------------------------------------------------------------------
def boundary_payload(agency_id: str, **overrides: Any) -> Dict[str, Any]:
    return _apply(
        {"agency_id": agency_id, "effective_start": "2026-08-01T00:00:00Z"},
        overrides,
    )


def cell_assignment_payload(
    cell_id: str, expected_boundary_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _apply(
        {
            "cell_id": cell_id,
            "effective_start": "2026-08-01T00:00:00Z",
            "expected_boundary_version": expected_boundary_version,
        },
        overrides,
    )


def retire_boundary_payload(**overrides: Any) -> Dict[str, Any]:
    return _apply(
        {"retire_reason": "Fire district dissolved into the regional authority"},
        overrides,
    )


# ---------------------------------------------------------------------------
# QC reports and defects
# ---------------------------------------------------------------------------
def qc_report_payload_full(**overrides: Any) -> Dict[str, Any]:
    return _apply({"scope": "FULL"}, overrides)


def qc_report_payload_jurisdiction(
    jurisdiction_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _apply(
        {"scope": "JURISDICTION", "jurisdiction_id": jurisdiction_id}, overrides
    )


def qc_report_payload_road(road_centerline_id: str, **overrides: Any) -> Dict[str, Any]:
    return _apply({"scope": "ROAD", "road_centerline_id": road_centerline_id}, overrides)


def waive_defect_payload(**overrides: Any) -> Dict[str, Any]:
    return _apply(
        {"waiver_reason": "Geometry survey scheduled for the next field cycle"},
        overrides,
    )


def reject_report_payload(**overrides: Any) -> Dict[str, Any]:
    return _apply(
        {"rejection_reason": "Scan ran before the nightly parcel load completed"},
        overrides,
    )


# ---------------------------------------------------------------------------
# Provisioning packages
# ---------------------------------------------------------------------------
def package_payload(
    jurisdiction_id: str, qc_report_id: str, channel: str = "MAPPING", **overrides: Any
) -> Dict[str, Any]:
    return _apply(
        {
            "channel": channel,
            "jurisdiction_id": jurisdiction_id,
            "qc_report_id": qc_report_id,
        },
        overrides,
    )


def rollback_package_payload(**overrides: Any) -> Dict[str, Any]:
    return _apply(
        {
            "rollback_reason": "Dispatch reported bad geometry on the 100 block after cutover"
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Discrepancy cases and proposals
# ---------------------------------------------------------------------------
def discrepancy_case_payload(
    subject_ref_id: str,
    counterparty_agency_id: str,
    subject_type: str = "ROAD_NAME",
    **overrides: Any,
) -> Dict[str, Any]:
    return _apply(
        {
            "subject_type": subject_type,
            "subject_ref_id": subject_ref_id,
            "counterparty_agency_id": counterparty_agency_id,
            "description": "The two agencies spell the road differently on their run cards",
        },
        overrides,
    )


def proposal_payload(
    proposed_value: str, expected_case_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _apply(
        {
            "proposed_value": proposed_value,
            "expected_case_version": expected_case_version,
        },
        overrides,
    )


def concur_payload(proposal_id: str, **overrides: Any) -> Dict[str, Any]:
    return _apply({"proposal_id": proposal_id}, overrides)


def arbitrate_payload(arbitration_value: str, **overrides: Any) -> Dict[str, Any]:
    return _apply({"arbitration_value": arbitration_value}, overrides)
