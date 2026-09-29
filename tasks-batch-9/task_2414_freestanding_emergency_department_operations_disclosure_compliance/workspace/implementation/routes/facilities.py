"""Facility routes: creation, read, configuration, signage, coverage summary,
compliance ledger."""

from flask import Blueprint

import constants as C
from db import base_row, db, sorted_rows, touch
from domain import (
    append_ledger,
    compute_posture,
    facility_ambulance_totals,
    facility_view,
    get_facility,
    get_forecast,
    ledger_view,
    observation_beds_occupied,
    recompute_posture,
    reconcile_coverage,
    select_active_forecast,
    signage_expiry,
)
from errors import ApiError
from response import ok, created, ok_list, paginate
from validate import (
    auth,
    body,
    num,
    pagination,
    query_enum,
    query_str,
    req_enum,
    req_enum_array,
    req_int,
    req_str,
)

bp = Blueprint("facilities", __name__)


@bp.post("/facilities")
def create_facility():
    auth("FacilityAdministrator")
    data = body()
    name = req_str(data, "name", 1, 200)
    state_code = req_str(data, "state_code", 2, 2)
    if len(state_code) != 2 or not state_code.isalpha() or not state_code.isupper():
        raise ApiError("ERR_INVALID_REQUEST", "state_code must be exactly two uppercase letters")
    license_category = req_enum(data, "license_category", C.LICENSE_CATEGORIES)
    license_status = req_enum(
        data, "license_status", C.LICENSE_STATUSES, required=False, default="ACTIVE"
    )
    observation_bed_count = req_int(data, "observation_bed_count", minimum=0)
    imaging_scope = req_enum_array(data, "imaging_scope", C.IMAGING_CODES)
    lab_scope = req_enum_array(data, "lab_scope", C.LAB_CODES)
    pharmacy_scope_tier = req_enum(data, "pharmacy_scope_tier", C.PHARMACY_SCOPE_TIERS)
    max_concurrent_physicians = req_int(data, "max_concurrent_physicians", minimum=1)

    facility = base_row()
    facility.update(
        {
            "name": name,
            "state_code": state_code,
            "license_category": license_category,
            "license_status": license_status,
            "signage_attestation_status": "PENDING",
            "signage_attested_at": None,
            "signage_expires_at": None,
            "signage_attested_by_user_id": None,
            "observation_bed_count": observation_bed_count,
            "imaging_scope": list(imaging_scope),
            "lab_scope": list(lab_scope),
            "pharmacy_scope_tier": pharmacy_scope_tier,
            "max_concurrent_physicians": max_concurrent_physicians,
            "open_compliance_defect_count": 0,
            "compliance_posture": None,
            "restricted_service_codes": [],
            "current_published_template_id": None,
            "coverage_deficit_flag": False,
        }
    )
    db.facilities[facility["id"]] = facility
    # Creation is the one facility-scoped mutation that produces no
    # POSTURE_CHANGE entry: the computed posture is where this facility starts
    # rather than a change from a previous value.
    posture = compute_posture(facility)
    facility["compliance_posture"] = posture
    facility["restricted_service_codes"] = list(C.RESTRICTED_CODES_BY_POSTURE[posture])
    return created(facility_view(facility))


@bp.get("/facilities/<fid>")
def read_facility(fid):
    auth(
        "FacilityAdministrator",
        "ComplianceOfficer",
        "RegistrationClerk",
        "EmergencyPhysician",
        "PayerRepresentative",
    )
    return ok(facility_view(get_facility(fid)))


@bp.patch("/facilities/<fid>")
def update_facility(fid):
    auth("FacilityAdministrator")
    data = body()
    expected = req_int(data, "expected_facility_version", minimum=0)
    license_status = req_enum(data, "license_status", C.LICENSE_STATUSES, required=False)
    observation_bed_count = req_int(data, "observation_bed_count", minimum=0, required=False)
    max_concurrent_physicians = req_int(
        data, "max_concurrent_physicians", minimum=1, required=False
    )
    imaging_scope = req_enum_array(data, "imaging_scope", C.IMAGING_CODES, required=False)
    lab_scope = req_enum_array(data, "lab_scope", C.LAB_CODES, required=False)
    pharmacy_scope_tier = req_enum(
        data, "pharmacy_scope_tier", C.PHARMACY_SCOPE_TIERS, required=False
    )

    facility = get_facility(fid)
    if expected != facility["version"]:
        raise ApiError("ERR_STALE_FACILITY_VERSION")

    if license_status is not None:
        facility["license_status"] = license_status
    if observation_bed_count is not None:
        facility["observation_bed_count"] = observation_bed_count
    if max_concurrent_physicians is not None:
        facility["max_concurrent_physicians"] = max_concurrent_physicians
    if imaging_scope is not None:
        facility["imaging_scope"] = list(imaging_scope)
    if lab_scope is not None:
        facility["lab_scope"] = list(lab_scope)
    if pharmacy_scope_tier is not None:
        facility["pharmacy_scope_tier"] = pharmacy_scope_tier

    touch(facility)
    recompute_posture(facility)
    return ok(facility_view(facility))


@bp.post("/facilities/<fid>/signage-attestations")
def file_signage_attestation(fid):
    user_id, _ = auth("ComplianceOfficer")
    data = body()
    attested_elements = req_enum_array(data, "attested_elements", C.SIGNAGE_ELEMENTS)
    req_str(data, "attestation_note", 1, 1000, required=False)

    facility = get_facility(fid)

    published_id = facility["current_published_template_id"]
    published = db.templates.get(published_id) if published_id else None
    if published is not None and published["published_by_user_id"] == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    required = set(C.REQUIRED_SIGNAGE_BY_CATEGORY[facility["license_category"]])
    if published is not None:
        required |= set(published["required_signage_elements"])
    if not required.issubset(set(attested_elements)):
        raise ApiError("ERR_SIGNAGE_ELEMENTS_INCOMPLETE")

    facility["signage_attestation_status"] = "ATTESTED"
    facility["signage_attested_at"] = db.clock
    facility["signage_expires_at"] = signage_expiry(db.clock)
    facility["signage_attested_by_user_id"] = user_id
    append_ledger(
        facility,
        "SIGNAGE_ATTESTED",
        "INFO",
        "FACILITY",
        facility["id"],
        "Signage attestation filed covering the required patient-facing elements.",
        defect_counted=False,
    )
    touch(facility)
    recompute_posture(facility)
    return ok(facility_view(facility))


@bp.get("/facilities/<fid>/coverage-summary")
def coverage_summary(fid):
    auth("FacilityAdministrator", "ComplianceOfficer")
    forecast_id = query_str("volume_forecast_id")
    facility = get_facility(fid)

    if forecast_id is not None:
        forecast = get_forecast(forecast_id)
        if forecast["facility_id"] != facility["id"]:
            raise ApiError("ERR_VOLUME_FORECAST_NOT_FOUND")
    else:
        forecast = select_active_forecast(facility)
        if forecast is None:
            raise ApiError("ERR_VOLUME_FORECAST_NOT_FOUND")

    scheduled, board_hours, deficit, compliant = reconcile_coverage(facility, forecast)
    committed, reserved = facility_ambulance_totals(facility)
    view = facility_view(facility)
    return ok(
        {
            "facility_id": facility["id"],
            "compliance_posture": view["compliance_posture"],
            "selected_volume_forecast_id": forecast["id"],
            "forecast_basis": forecast["forecast_basis"],
            "forecast_method": forecast["method"],
            "required_physician_hours_per_day": num(
                forecast["required_physician_hours_per_day"]
            ),
            "required_physician_hours_total": num(forecast["required_physician_hours_total"]),
            "required_board_certified_hours_total": num(
                forecast["required_board_certified_hours_total"]
            ),
            "scheduled_physician_hours": num(scheduled),
            "board_certified_hours": num(board_hours),
            "coverage_deficit_hours": num(deficit),
            "coverage_compliant": bool(compliant),
            "coverage_deficit_flag": facility["coverage_deficit_flag"],
            "observation_bed_count": facility["observation_bed_count"],
            "observation_beds_occupied": observation_beds_occupied(facility),
            "ambulance_units_available": committed - reserved,
        }
    )


@bp.get("/facilities/<fid>/compliance-ledger-entries")
def list_ledger(fid):
    auth("FacilityAdministrator", "ComplianceOfficer")
    event_type = query_enum("event_type", C.LEDGER_EVENT_TYPES)
    severity = query_enum("severity", C.LEDGER_SEVERITIES)
    limit, offset = pagination()

    facility = get_facility(fid)
    rows = [e for e in db.ledger.values() if e["facility_id"] == facility["id"]]
    if event_type is not None:
        rows = [e for e in rows if e["event_type"] == event_type]
    if severity is not None:
        rows = [e for e in rows if e["severity"] == severity]
    rows = sorted_rows(rows)
    page = paginate(rows, limit, offset)
    return ok_list([ledger_view(e) for e in page], limit, offset, len(rows))
