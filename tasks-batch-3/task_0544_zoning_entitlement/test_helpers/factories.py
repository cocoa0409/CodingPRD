"""Payload factories — one per entity, input fields only (PRD §1 / §3)."""
from .constants import FEE_SCHEDULE_DEFAULTS

_apn_counter = [0]


def _next_apn():
    _apn_counter[0] += 1
    return f"APN-T{_apn_counter[0]:05d}"


def parcel_payload(**overrides) -> dict:
    """Input fields for POST /parcels (sensitive_area optional, defaults false)."""
    defaults = {
        "apn": _next_apn(),
        "zoning_district": "RES",
        "area_acres": 2,
        "neighbor_parcel_count": 6,
        "expanded_neighbor_count": 12,
        "sensitive_area": False,
    }
    defaults.update(overrides)
    return defaults


def fee_schedule_payload(**overrides) -> dict:
    """Input fields for POST /fee-schedules."""
    defaults = {"name": "FY26", **FEE_SCHEDULE_DEFAULTS}
    defaults.update(overrides)
    return defaults


def applicant_payload(**overrides) -> dict:
    """Input fields for POST /applicants (organization optional)."""
    defaults = {"full_name": "Test Applicant", "email": "applicant@example.com"}
    defaults.update(overrides)
    return defaults


def application_payload(parcel_id, applicant_id, **overrides) -> dict:
    """Input fields for POST /applications (affordable_housing optional, default false)."""
    defaults = {
        "application_type": "VARIANCE",
        "parcel_id": parcel_id,
        "applicant_id": applicant_id,
        "requested_use": "requested relief",
    }
    defaults.update(overrides)
    return defaults


def completeness_payload(determination="COMPLETE", **overrides) -> dict:
    """Input fields for POST /applications/{id}/completeness."""
    defaults = {"determination": determination}
    defaults.update(overrides)
    return defaults


def notice_payload(notice_kind="MAILED", **overrides) -> dict:
    """Input fields for POST /applications/{id}/notices."""
    defaults = {"notice_kind": notice_kind}
    defaults.update(overrides)
    return defaults


def hearing_payload(**overrides) -> dict:
    """Input fields for POST /hearings."""
    defaults = {
        "body": "PLANNING_COMMISSION",
        "scheduled_date": "2026-06-11T00:00:00Z",
        "agenda_capacity": 5,
    }
    defaults.update(overrides)
    return defaults


def agenda_item_payload(application_id, expected_hearing_version, **overrides) -> dict:
    """Input fields for POST /hearings/{id}/agenda-items."""
    defaults = {
        "application_id": application_id,
        "expected_hearing_version": expected_hearing_version,
    }
    defaults.update(overrides)
    return defaults


def decide_payload(decision="APPROVE", findings=None, conditions=None, **overrides) -> dict:
    """Input fields for POST /agenda-items/{id}/decide."""
    if findings is None:
        findings = [{"finding_code": "F-A", "finding_text": "meets code", "supports_approval": True}]
    payload = {"decision": decision, "findings": findings}
    if conditions is not None:
        payload["conditions"] = conditions
    payload.update(overrides)
    return payload


def appeal_payload(application_id, **overrides) -> dict:
    """Input fields for POST /appeals."""
    defaults = {
        "application_id": application_id,
        "appellant_name": "Neighbor",
        "grounds": "stated grounds",
    }
    defaults.update(overrides)
    return defaults


def resolve_payload(resolution="UPHELD", **overrides) -> dict:
    """Input fields for POST /appeals/{id}/resolve."""
    defaults = {"resolution": resolution}
    defaults.update(overrides)
    return defaults


def plat_payload(application_id, fee_schedule_id, declared_lot_count=4,
                 declared_gross_acres=10, **overrides) -> dict:
    """Input fields for POST /plats (prior_paid_fee_cents optional, default 0)."""
    defaults = {
        "application_id": application_id,
        "fee_schedule_id": fee_schedule_id,
        "declared_lot_count": declared_lot_count,
        "declared_gross_acres": declared_gross_acres,
    }
    defaults.update(overrides)
    return defaults


def record_payload(recorded_lot_count=4, recorded_gross_acres=10, **overrides) -> dict:
    """Input fields for POST /plats/{id}/record."""
    defaults = {
        "recorded_lot_count": recorded_lot_count,
        "recorded_gross_acres": recorded_gross_acres,
    }
    defaults.update(overrides)
    return defaults


def pay_payload(amount_cents, **overrides) -> dict:
    """Input fields for POST /impact-fees/{id}/pay."""
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults
