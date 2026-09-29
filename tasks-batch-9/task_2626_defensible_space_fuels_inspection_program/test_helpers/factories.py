"""Request payload builders.

Each builder returns a complete, PRD-valid payload for one endpoint and accepts
keyword overrides so a test can perturb exactly the field under examination.
Optional inputs are omitted unless supplied, which lets tests exercise the
declared server-side defaults.
"""

import itertools

from .constants import (
    DEFAULT_MAX_DAILY_ORDERS,
    PROGRAM_TYPE_GRANT,
)

_apn_counter = itertools.count(1001)
_name_counter = itertools.count(1)


def next_apn():
    """A fresh assessor parcel number; APNs are unique across parcels."""
    return "APN-%d" % next(_apn_counter)


def next_name(prefix):
    return "%s-%d" % (prefix, next(_name_counter))


def _compact(payload, overrides):
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not _OMIT}


class _Omit:
    def __repr__(self):
        return "<omit>"


_OMIT = _Omit()
OMIT = _OMIT


# ---------------------------------------------------------------------------
# Cycles, communities
# ---------------------------------------------------------------------------

def cycle_payload(season_year=2026, **overrides):
    """A cycle create payload; notice_lead_days and invoice_due_days default."""
    return _compact(
        {
            "season_year": season_year,
            "notice_lead_days": _OMIT,
            "invoice_due_days": _OMIT,
        },
        overrides,
    )


def community_payload(name=None, **overrides):
    return _compact(
        {
            "name": name or next_name("Ridgeline Community"),
            "organizer_name": "Dana Ortiz",
            "target_certification_year": 2026,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Parcels
# ---------------------------------------------------------------------------

def parcel_payload(apn=None, **overrides):
    """The canonical HIGH-risk profile.

    slope_pct 30, BRUSH vegetation, CLASS_B roof, GATED access and a HIGH
    hazard zone.
    """
    return _compact(
        {
            "apn": apn or next_apn(),
            "owner_name": "Rosa Almeida",
            "owner_email": "rosa@example.com",
            "situs_address": "18 Ridgeline Road",
            "community_id": _OMIT,
            "structure_present": _OMIT,
            "roof_class": "CLASS_B",
            "vegetation_type": "BRUSH",
            "slope_pct": 30,
            "lot_area_sqft": 21780,
            "hazard_zone": "HIGH",
            "access_constraint": "GATED",
            "owner_hardship_flag": _OMIT,
        },
        overrides,
    )


def moderate_parcel_payload(apn=None, **overrides):
    """slope_pct 20, GRASS, CLASS_B roof, no access constraint, MODERATE zone."""
    base = {
        "roof_class": "CLASS_B",
        "vegetation_type": "GRASS",
        "slope_pct": 20,
        "hazard_zone": "MODERATE",
        "access_constraint": "NONE",
    }
    base.update(overrides)
    return parcel_payload(apn, **base)


def very_high_parcel_payload(apn=None, **overrides):
    """The canonical HIGH-risk profile relocated into a VERY_HIGH hazard zone."""
    base = {"hazard_zone": "VERY_HIGH"}
    base.update(overrides)
    return parcel_payload(apn, **base)


def extreme_parcel_payload(apn=None, **overrides):
    """A profile whose raw weighted score overflows the 100.00 clamp."""
    base = {
        "roof_class": "NONE",
        "vegetation_type": "MIXED_CONIFER",
        "slope_pct": 50,
        "hazard_zone": "VERY_HIGH",
        "access_constraint": "LOCKED_GATE",
    }
    base.update(overrides)
    return parcel_payload(apn, **base)


def parcel_patch(expected_parcel_version, **overrides):
    payload = {"expected_parcel_version": expected_parcel_version}
    payload.update(overrides)
    return payload


def survival_payload(outcome="SURVIVED", **overrides):
    return _compact(
        {
            "incident_name": "Cedar Gulch Fire",
            "outcome": outcome,
            "incident_date_utc": "2026-08-15T00:00:00Z",
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Inspectors, contractors
# ---------------------------------------------------------------------------

def inspector_payload(full_name=None, certification_level="ADVANCED", **overrides):
    return _compact(
        {
            "full_name": full_name or next_name("Inspector"),
            "certification_level": certification_level,
            "status": _OMIT,
        },
        overrides,
    )


def contractor_payload(business_name=None, **overrides):
    """Hourly rate 8600 cents, mobilization fee 32000 cents."""
    return _compact(
        {
            "business_name": business_name or next_name("Ridge Fuels Crew"),
            "hourly_rate_cents": 8600,
            "mobilization_fee_cents": 32000,
            "license_status": _OMIT,
            "insurance_expiry_utc": "2027-06-30T00:00:00Z",
            "max_daily_orders": _OMIT,
        },
        overrides,
    )


def contractor_patch(**overrides):
    return dict(overrides)


# ---------------------------------------------------------------------------
# Inspections and their child records
# ---------------------------------------------------------------------------

def inspection_payload(
    parcel_id,
    cycle_id,
    inspector_id,
    scheduled_start_utc="2026-08-20T09:00:00Z",
    scheduled_end_utc="2026-08-20T11:00:00Z",
    **overrides
):
    return _compact(
        {
            "parcel_id": parcel_id,
            "cycle_id": cycle_id,
            "inspector_id": inspector_id,
            "inspection_type": "INITIAL",
            "scheduled_start_utc": scheduled_start_utc,
            "scheduled_end_utc": scheduled_end_utc,
            "access_arrangement": "EXTERIOR_ONLY",
        },
        overrides,
    )


def reschedule_payload(scheduled_start_utc, scheduled_end_utc, **overrides):
    return _compact(
        {
            "scheduled_start_utc": scheduled_start_utc,
            "scheduled_end_utc": scheduled_end_utc,
            "inspector_id": _OMIT,
        },
        overrides,
    )


def zone_payload(zone, measured_clearance_ft, **overrides):
    return _compact(
        {
            "zone": zone,
            "measured_clearance_ft": measured_clearance_ft,
            "ladder_fuel_present": _OMIT,
        },
        overrides,
    )


def finding_payload(item_code="EAVE_VENTS", status="COMPLIANT", **overrides):
    payload = {"item_code": item_code, "status": status}
    payload.update(overrides)
    return payload


def notice_service_payload(notice_method="CERTIFIED_MAIL", **overrides):
    payload = {"notice_method": notice_method}
    payload.update(overrides)
    return payload


def discretionary_notice_payload(
    inspection_id, expected_parcel_version, notice_method="CERTIFIED_MAIL", **overrides
):
    payload = {
        "inspection_id": inspection_id,
        "notice_method": notice_method,
        "expected_parcel_version": expected_parcel_version,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Abatement
# ---------------------------------------------------------------------------

def authorize_payload(estimated_cost_cents=500000, **overrides):
    payload = {"estimated_cost_cents": estimated_cost_cents}
    payload.update(overrides)
    return payload


def award_payload(
    contractor_id,
    crew_hours=12.5,
    work_start_utc="2026-10-06T08:00:00Z",
    work_end_utc="2026-10-06T16:00:00Z",
    **overrides
):
    payload = {
        "contractor_id": contractor_id,
        "crew_hours": crew_hours,
        "work_start_utc": work_start_utc,
        "work_end_utc": work_end_utc,
    }
    payload.update(overrides)
    return payload


def complete_work_payload(actual_crew_hours=12.5, green_waste_tons=3.25, **overrides):
    payload = {
        "actual_crew_hours": actual_crew_hours,
        "green_waste_tons": green_waste_tons,
    }
    payload.update(overrides)
    return payload


def payment_payload(amount_cents, method="CHECK", **overrides):
    payload = {"amount_cents": amount_cents, "method": method}
    payload.update(overrides)
    return payload


def reason_payload(reason="Owner completed the work themselves", **overrides):
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Support programs and enrollments
# ---------------------------------------------------------------------------

def support_program_payload(
    cycle_id,
    program_type=PROGRAM_TYPE_GRANT,
    budget_total_cents=500000,
    capacity_slots=1,
    service_window_start_utc="2026-08-01T00:00:00Z",
    service_window_end_utc="2026-09-30T00:00:00Z",
    **overrides
):
    payload = {
        "cycle_id": cycle_id,
        "program_type": program_type,
        "budget_total_cents": budget_total_cents,
        "capacity_slots": capacity_slots,
        "service_window_start_utc": service_window_start_utc,
        "service_window_end_utc": service_window_end_utc,
    }
    payload.update(overrides)
    return payload


def enrollment_payload(
    support_program_id, parcel_id, expected_program_version, vendor_invoice_cents=None,
    **overrides
):
    payload = {
        "support_program_id": support_program_id,
        "parcel_id": parcel_id,
        "expected_program_version": expected_program_version,
    }
    if vendor_invoice_cents is not None:
        payload["vendor_invoice_cents"] = vendor_invoice_cents
    payload.update(overrides)
    return payload


def complete_enrollment_payload(attended=True, **overrides):
    payload = {"attended": attended}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Certificates and community decisions
# ---------------------------------------------------------------------------

def certificate_payload(requester_kind="REAL_ESTATE", **overrides):
    payload = {
        "requester_kind": requester_kind,
        "transaction_reference": "ESCROW-88213",
    }
    payload.update(overrides)
    return payload


def decision_payload(decision, note=None, **overrides):
    payload = {"decision": decision}
    if note is not None:
        payload["note"] = note
    payload.update(overrides)
    return payload


DEFAULT_CONTRACTOR_MAX_DAILY_ORDERS = DEFAULT_MAX_DAILY_ORDERS


# ---------------------------------------------------------------------------
# Action payloads for the remaining lifecycle operations
# ---------------------------------------------------------------------------

def access_denial_payload(reason_code="GATE_LOCKED", **overrides):
    payload = {"reason_code": reason_code}
    payload.update(overrides)
    return payload


def complete_inspection_payload(result="FAIL", violation_notice_method=None, **overrides):
    """A completion request; the notice method is only meaningful on a FAIL."""
    payload = {"result": result}
    if violation_notice_method is not None:
        payload["violation_notice_method"] = violation_notice_method
    payload.update(overrides)
    return payload


def submit_certification_payload(parcels_outreached_count, **overrides):
    payload = {"parcels_outreached_count": parcels_outreached_count}
    payload.update(overrides)
    return payload


def verify_completion_payload(verified_note=None, **overrides):
    payload = {}
    if verified_note is not None:
        payload["verified_note"] = verified_note
    payload.update(overrides)
    return payload
