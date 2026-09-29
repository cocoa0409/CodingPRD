"""Clock, service areas, fee schedules, applicants, inspectors and equipment."""

from flask import Blueprint, g

import calc
import services as svc
import validation
from auth import (
    ANY_ROLE,
    APPLICANT_USER,
    AUDITOR,
    LICENSED_INSPECTOR,
    SERVICE_ADMIN,
    SUPERVISING_INSPECTOR,
    assert_applicant_scope,
    endpoint,
)
from envelope import apply_filters, created, listing, ok
from errors import ApiError
from store import db, iso, new_row, serialize, touch

bp = Blueprint("config", __name__)

PREFIX = "/grain-inspection"

AUTHORITY_TYPES = ("DELEGATED", "DESIGNATED")
AREA_STATUSES = ("ACTIVE", "SUSPENDED")
SERVICE_CLASSES = ("GRADING", "WEIGHING", "PROTEIN", "EXPORT_SUPERVISION", "APPEAL")
ENDORSEMENTS = ("SAMPLING", "GRADING", "PROTEIN", "WEIGHING", "SUPERVISION")
EQUIPMENT_KINDS = ("SAMPLING_DEVICE", "SCALE", "PROTEIN_INSTRUMENT")


# ==========================================================================
# logical clock
# ==========================================================================

@bp.post("/_clock/set_current_utc")
@endpoint(ANY_ROLE)
def set_clock():
    body = validation.parse({"current_utc": {"type": "datetime", "required": True}})
    target = body["current_utc"]
    if target < db.now:
        raise ApiError("ERR_CLOCK_NOT_MONOTONIC")
    db.now = target
    counts = svc.expiry_sweep()
    payload = {"current_utc": iso(db.now)}
    payload.update(counts)
    return ok(payload)


# ==========================================================================
# service areas
# ==========================================================================

@bp.post(PREFIX + "/service-areas")
@endpoint((SERVICE_ADMIN,))
def create_service_area():
    body = validation.parse(
        {
            "name": {"required": True, "maxlen": 120},
            "state_code": {"required": True, "pattern": r"[A-Z]{2}"},
            "authority_type": {"type": "enum", "values": AUTHORITY_TYPES, "required": True},
            "status": {"type": "enum", "values": AREA_STATUSES, "default": "ACTIVE"},
            "fee_multiplier_bp": {"type": "int", "min": 10000, "max": 15000, "default": 10000},
            "supervision_required": {"type": "bool", "default": True},
            "concurrent_watch_capacity": {"type": "int", "min": 1, "default": 2},
        }
    )
    row = new_row(
        {
            "name": body["name"],
            "state_code": body["state_code"],
            "authority_type": body["authority_type"],
            "status": body["status"],
            "fee_multiplier_bp": body["fee_multiplier_bp"],
            "supervision_required": body["supervision_required"],
            "concurrent_watch_capacity": body["concurrent_watch_capacity"],
            "open_watch_count": 0,
        }
    )
    db.service_areas[row["id"]] = row
    return created(serialize(row))


@bp.get(PREFIX + "/service-areas")
@endpoint(ANY_ROLE)
def list_service_areas():
    rows = apply_filters(db.service_areas.values(), ("state_code", "authority_type", "status"))
    return listing(rows)


@bp.get(PREFIX + "/service-areas/<row_id>")
@endpoint(ANY_ROLE)
def get_service_area(row_id):
    return ok(serialize(svc.area(row_id)))


@bp.patch(PREFIX + "/service-areas/<row_id>")
@endpoint((SERVICE_ADMIN,))
def update_service_area(row_id):
    row = svc.area(row_id)
    body, provided = validation.parse_present(
        {
            "status": {"type": "enum", "values": AREA_STATUSES},
            "fee_multiplier_bp": {"type": "int", "min": 10000, "max": 15000},
            "supervision_required": {"type": "bool"},
            "concurrent_watch_capacity": {"type": "int", "min": 1},
        }
    )
    for field in ("status", "fee_multiplier_bp", "supervision_required", "concurrent_watch_capacity"):
        if field in provided and body[field] is not None:
            row[field] = body[field]
    touch(row)
    return ok(serialize(row))


# ==========================================================================
# fee schedules
# ==========================================================================

@bp.post(PREFIX + "/fee-schedules")
@endpoint((SERVICE_ADMIN,))
def create_fee_schedule():
    body = validation.parse(
        {
            "service_area_id": {"required": True},
            "service_class": {"type": "enum", "values": SERVICE_CLASSES, "required": True},
            "base_fee_cents": {"type": "int", "min": 0, "required": True},
            "per_thousand_bushel_rate_cents": {"type": "int", "min": 0, "default": 0},
            "overtime_multiplier_bp": {"type": "int", "min": 0, "max": 10000, "default": 2500},
            "minimum_fee_cents": {"type": "int", "min": 0, "default": 0},
            "effective_from": {"type": "datetime", "required": True},
            "effective_to": {"type": "datetime", "nullable": True, "default": None},
        }
    )
    svc.area(body["service_area_id"])
    if body["effective_to"] is not None and body["effective_to"] <= body["effective_from"]:
        raise ApiError("ERR_FEE_SCHEDULE_WINDOW_CONFLICT")
    row = new_row(
        {
            "service_area_id": body["service_area_id"],
            "service_class": body["service_class"],
            "base_fee_cents": body["base_fee_cents"],
            "per_thousand_bushel_rate_cents": body["per_thousand_bushel_rate_cents"],
            "overtime_multiplier_bp": body["overtime_multiplier_bp"],
            "minimum_fee_cents": body["minimum_fee_cents"],
            "effective_from": body["effective_from"],
            "effective_to": body["effective_to"],
            "status": "DRAFT",
        }
    )
    db.fee_schedules[row["id"]] = row
    return created(serialize(row))


@bp.post(PREFIX + "/fee-schedules/<row_id>/activate")
@endpoint((SERVICE_ADMIN,))
def activate_fee_schedule(row_id):
    row = svc.find("fee_schedules", row_id, "ERR_FEE_SCHEDULE_NOT_FOUND")
    if row["status"] != "DRAFT":
        raise ApiError("ERR_FEE_SCHEDULE_NOT_DRAFT")
    siblings = [
        other
        for other in db.fee_schedules.values()
        if other["id"] != row["id"]
        and other["status"] == "ACTIVE"
        and other["service_area_id"] == row["service_area_id"]
        and other["service_class"] == row["service_class"]
    ]
    for other in siblings:
        if svc.windows_overlap(
            row["effective_from"], row["effective_to"],
            other["effective_from"], other["effective_to"],
        ):
            raise ApiError("ERR_FEE_SCHEDULE_WINDOW_CONFLICT")
    for other in siblings:
        if other["effective_to"] is not None and other["effective_to"] <= db.now:
            other["status"] = "SUPERSEDED"
            touch(other)
    row["status"] = "ACTIVE"
    touch(row)
    return ok(serialize(row))


@bp.get(PREFIX + "/fee-schedules")
@endpoint(ANY_ROLE)
def list_fee_schedules():
    rows = apply_filters(
        db.fee_schedules.values(), ("service_area_id", "service_class", "status")
    )
    return listing(rows)


@bp.get(PREFIX + "/fee-schedules/<row_id>")
@endpoint(ANY_ROLE)
def get_fee_schedule(row_id):
    return ok(serialize(svc.find("fee_schedules", row_id, "ERR_FEE_SCHEDULE_NOT_FOUND")))


# ==========================================================================
# applicants
# ==========================================================================

@bp.post(PREFIX + "/applicants")
@endpoint((SERVICE_ADMIN,))
def create_applicant():
    body = validation.parse(
        {
            "name": {"required": True},
            "account_code": {"required": True, "pattern": r"[A-Z0-9-]{3,20}"},
            "contact_email": {"required": True},
            "credit_limit_cents": {"type": "int", "min": 0, "default": 500000},
        }
    )
    for existing in db.applicants.values():
        if existing["account_code"] == body["account_code"]:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER")
    row = new_row(
        {
            "name": body["name"],
            "account_code": body["account_code"],
            "contact_email": body["contact_email"],
            "credit_limit_cents": body["credit_limit_cents"],
            "charges_total_cents": 0,
            "credits_total_cents": 0,
            "open_balance_cents": 0,
        }
    )
    db.applicants[row["id"]] = row
    return created(serialize(row))


@bp.get(PREFIX + "/applicants")
@endpoint((SERVICE_ADMIN, SUPERVISING_INSPECTOR, AUDITOR))
def list_applicants():
    rows = apply_filters(db.applicants.values(), ("account_code",))
    return listing(rows)


@bp.get(PREFIX + "/applicants/<row_id>")
@endpoint((SERVICE_ADMIN, SUPERVISING_INSPECTOR, APPLICANT_USER, AUDITOR))
def get_applicant(row_id):
    row = svc.applicant(row_id)
    assert_applicant_scope(row["id"])
    return ok(serialize(row))


@bp.post(PREFIX + "/applicants/<row_id>/payments")
@endpoint((SERVICE_ADMIN, APPLICANT_USER))
def record_payment(row_id):
    applicant = svc.applicant(row_id)
    assert_applicant_scope(applicant["id"])
    body = validation.parse({"amount_cents": {"type": "int", "required": True}})
    amount = body["amount_cents"]

    open_certs = []
    for cert in db.certificates.values():
        req = db.inspection_requests.get(cert["inspection_request_id"])
        if req is None or req["applicant_id"] != applicant["id"]:
            continue
        if cert["fee_settlement_status"] != "UNPAID":
            continue
        if cert["status"] not in ("ISSUED", "UNDER_APPEAL"):
            continue
        open_certs.append(cert)
    open_certs.sort(key=lambda c: (c["issued_at"], c["sequence_no"]))
    allocatable = sum(c["fee_total_cents"] - c["fee_paid_cents"] for c in open_certs)

    if amount <= 0 or amount > allocatable:
        raise ApiError("ERR_PAYMENT_EXCEEDS_ALLOCATABLE")

    remaining = amount
    for cert in open_certs:
        if remaining == 0:
            break
        take = min(remaining, cert["fee_total_cents"] - cert["fee_paid_cents"])
        if take <= 0:
            continue
        cert["fee_paid_cents"] += take
        if cert["fee_paid_cents"] == cert["fee_total_cents"]:
            cert["fee_settlement_status"] = "PAID"
        touch(cert)
        remaining -= take
    svc.credit(applicant, amount)
    return ok(serialize(applicant))


# ==========================================================================
# inspectors
# ==========================================================================

@bp.post(PREFIX + "/inspectors")
@endpoint((SERVICE_ADMIN,))
def create_inspector():
    body = validation.parse(
        {
            "service_area_id": {"required": True},
            "license_number": {"required": True},
            "full_name": {"required": True},
            "endorsements": {
                "type": "enum_array",
                "values": ENDORSEMENTS,
                "min_items": 1,
                "max_items": 5,
                "required": True,
            },
            "license_expires_at": {"type": "datetime", "required": True},
        }
    )
    svc.area(body["service_area_id"])
    for existing in db.inspectors.values():
        if (
            existing["service_area_id"] == body["service_area_id"]
            and existing["license_number"] == body["license_number"]
        ):
            raise ApiError("ERR_DUPLICATE_IDENTIFIER")
    row = new_row(
        {
            "service_area_id": body["service_area_id"],
            "license_number": body["license_number"],
            "full_name": body["full_name"],
            "endorsements": list(dict.fromkeys(body["endorsements"])),
            "license_status": "PROBATIONARY",
            "license_expires_at": body["license_expires_at"],
            "training_hours_completed": 0,
            "appeal_reversal_count": 0,
            "check_sample_deviation_count": 0,
            "late_certificate_count": 0,
            "performance_score": 100,
            "suspension_reason": None,
        }
    )
    db.inspectors[row["id"]] = row
    return created(serialize(row))


@bp.get(PREFIX + "/inspectors")
@endpoint((SERVICE_ADMIN, SUPERVISING_INSPECTOR, LICENSED_INSPECTOR, AUDITOR))
def list_inspectors():
    rows = apply_filters(db.inspectors.values(), ("service_area_id", "license_status"))
    return listing(rows)


@bp.get(PREFIX + "/inspectors/<row_id>")
@endpoint((SERVICE_ADMIN, SUPERVISING_INSPECTOR, LICENSED_INSPECTOR, AUDITOR))
def get_inspector(row_id):
    return ok(serialize(svc.inspector(row_id)))


@bp.post(PREFIX + "/inspectors/<row_id>/activate")
@endpoint((SERVICE_ADMIN,))
def activate_inspector(row_id):
    row = svc.inspector(row_id)
    if row["license_status"] != "PROBATIONARY":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if row["training_hours_completed"] < 24 or row["performance_score"] < calc.ACTIVATION_MINIMUM_SCORE:
        raise ApiError("ERR_INSPECTOR_NOT_QUALIFIED")
    if row["license_expires_at"] <= db.now:
        raise ApiError("ERR_EXPIRY_IN_PAST")
    row["license_status"] = "ACTIVE"
    touch(row)
    return ok(serialize(row))


@bp.post(PREFIX + "/inspectors/<row_id>/suspend")
@endpoint((SERVICE_ADMIN,))
def suspend_inspector(row_id):
    row = svc.inspector(row_id)
    body = validation.parse({"suspension_reason": {"required": True}})
    if row["license_status"] not in ("PROBATIONARY", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    row["license_status"] = "SUSPENDED"
    row["suspension_reason"] = body["suspension_reason"]
    touch(row)
    svc.abort_watches(row, svc.NON_TERMINAL_WATCH)
    return ok(serialize(row))


@bp.post(PREFIX + "/inspectors/<row_id>/reinstate")
@endpoint((SERVICE_ADMIN,))
def reinstate_inspector(row_id):
    row = svc.inspector(row_id)
    if row["license_status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if row["performance_score"] < calc.ACTIVATION_MINIMUM_SCORE:
        raise ApiError("ERR_INSPECTOR_NOT_QUALIFIED")
    if row["license_expires_at"] <= db.now:
        raise ApiError("ERR_EXPIRY_IN_PAST")
    row["license_status"] = "ACTIVE"
    row["suspension_reason"] = None
    touch(row)
    return ok(serialize(row))


@bp.post(PREFIX + "/inspectors/<row_id>/revoke")
@endpoint((SERVICE_ADMIN,))
def revoke_inspector(row_id):
    row = svc.inspector(row_id)
    body = validation.parse({"suspension_reason": {"required": True}})
    if row["license_status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    row["license_status"] = "REVOKED"
    row["suspension_reason"] = body["suspension_reason"]
    touch(row)
    return ok(serialize(row))


@bp.post(PREFIX + "/inspectors/<row_id>/training-records")
@endpoint((SERVICE_ADMIN, SUPERVISING_INSPECTOR))
def file_training_record(row_id):
    row = svc.inspector(row_id)
    body = validation.parse(
        {
            "course_code": {"required": True},
            "hours": {"type": "number", "exclusive_min": 0, "max": 1000, "required": True},
        }
    )
    total = float(calc.round_half_up(
        calc.dec(row["training_hours_completed"]) + calc.dec(body["hours"]), 2
    ))
    row["training_hours_completed"] = int(total) if total.is_integer() else total
    svc.recompute_performance(row)
    touch(row)
    return ok(serialize(row))


# ==========================================================================
# equipment
# ==========================================================================

@bp.post(PREFIX + "/equipment")
@endpoint((SERVICE_ADMIN,))
def create_equipment():
    body, provided = validation.parse_present(
        {
            "service_area_id": {"required": True},
            "equipment_kind": {"type": "enum", "values": EQUIPMENT_KINDS, "required": True},
            "asset_code": {"required": True, "maxlen": 40},
            "model": {"required": True},
            "capacity_lbs": {"type": "int", "min": 1, "nullable": True, "default": None},
            "tolerance_lbs": {"type": "number", "min": 0, "nullable": True, "default": None},
        }
    )
    svc.area(body["service_area_id"])
    is_scale = body["equipment_kind"] == "SCALE"
    has_capacity = body["capacity_lbs"] is not None
    has_tolerance = body["tolerance_lbs"] is not None
    if is_scale:
        if not has_capacity or not has_tolerance:
            raise ApiError("ERR_EQUIPMENT_FIELD_APPLICABILITY")
    elif has_capacity or has_tolerance or "capacity_lbs" in provided or "tolerance_lbs" in provided:
        raise ApiError("ERR_EQUIPMENT_FIELD_APPLICABILITY")
    for existing in db.equipment.values():
        if (
            existing["service_area_id"] == body["service_area_id"]
            and existing["asset_code"] == body["asset_code"]
        ):
            raise ApiError("ERR_DUPLICATE_IDENTIFIER")
    row = new_row(
        {
            "service_area_id": body["service_area_id"],
            "equipment_kind": body["equipment_kind"],
            "asset_code": body["asset_code"],
            "model": body["model"],
            "approval_status": "PENDING_APPROVAL",
            "certified_until": None,
            "capacity_lbs": body["capacity_lbs"],
            "tolerance_lbs": body["tolerance_lbs"],
            "last_certification_error_lbs": None,
            "recent_deviations_pct": [],
            "rolling_bias_pct": None,
            "last_comparison_deviation_pct": None,
            "comparison_check_count": 0,
            "consecutive_out_of_tolerance_checks": 0,
            "_last_comparison_check_at": None,
        }
    )
    db.equipment[row["id"]] = row
    return created(serialize(row))


@bp.get(PREFIX + "/equipment")
@endpoint((SERVICE_ADMIN, SUPERVISING_INSPECTOR, LICENSED_INSPECTOR, AUDITOR))
def list_equipment():
    rows = apply_filters(
        db.equipment.values(), ("service_area_id", "equipment_kind", "approval_status")
    )
    return listing(rows)


@bp.get(PREFIX + "/equipment/<row_id>")
@endpoint((SERVICE_ADMIN, SUPERVISING_INSPECTOR, LICENSED_INSPECTOR, AUDITOR))
def get_equipment(row_id):
    return ok(serialize(svc.equipment(row_id)))


@bp.post(PREFIX + "/equipment/<row_id>/certify")
@endpoint((SERVICE_ADMIN,))
def certify_equipment(row_id):
    row = svc.equipment(row_id)
    body, provided = validation.parse_present(
        {
            "certified_until": {"type": "datetime", "required": True},
            "test_error_lbs": {"type": "number", "nullable": True, "default": None},
        }
    )
    is_scale = row["equipment_kind"] == "SCALE"
    supplied_error = body["test_error_lbs"] is not None
    if is_scale:
        if not supplied_error:
            raise ApiError("ERR_EQUIPMENT_FIELD_APPLICABILITY")
    elif supplied_error or "test_error_lbs" in provided:
        raise ApiError("ERR_EQUIPMENT_FIELD_APPLICABILITY")

    if row["approval_status"] == "WITHDRAWN":
        raise ApiError("ERR_EQUIPMENT_WITHDRAWN")
    if body["certified_until"] <= db.now:
        raise ApiError("ERR_EXPIRY_IN_PAST")

    if is_scale:
        row["last_certification_error_lbs"] = body["test_error_lbs"]
        tolerance = calc.dec(row["tolerance_lbs"] or 0)
        if abs(calc.dec(body["test_error_lbs"])) > tolerance:
            row["approval_status"] = "OUT_OF_TOLERANCE"
            touch(row)
            svc.scale_failure_cascade(row)
            return ok(serialize(row))

    row["approval_status"] = "APPROVED"
    row["certified_until"] = body["certified_until"]
    row["consecutive_out_of_tolerance_checks"] = 0
    row["recent_deviations_pct"] = []
    row["rolling_bias_pct"] = None
    touch(row)
    return ok(serialize(row))


# ==========================================================================
# comparison checks
# ==========================================================================

@bp.post(PREFIX + "/comparison-checks")
@endpoint((SERVICE_ADMIN, SUPERVISING_INSPECTOR))
def file_comparison_check():
    body = validation.parse(
        {
            "instrument_id": {"required": True},
            "inspector_id": {"required": True},
            "reference_value_pct": {"type": "number", "min": 0, "max": 60, "required": True},
            "instrument_reading_pct": {"type": "number", "min": 0, "max": 60, "required": True},
        }
    )
    instrument = svc.equipment(body["instrument_id"])
    inspector = svc.inspector(body["inspector_id"])

    if instrument["equipment_kind"] != "PROTEIN_INSTRUMENT":
        raise ApiError("ERR_EQUIPMENT_KIND_MISMATCH")
    if instrument["approval_status"] in ("WITHDRAWN", "PENDING_APPROVAL", "EXPIRED"):
        raise ApiError("ERR_EQUIPMENT_WITHDRAWN")
    svc.assert_licence(inspector, svc.LINE_LICENCE_STATES)
    if g.get("user_id") == inspector["id"]:
        raise ApiError("ERR_SELF_CHECK_FORBIDDEN")

    deviation = calc.comparison_deviation(
        body["instrument_reading_pct"], body["reference_value_pct"]
    )
    instrument["last_comparison_deviation_pct"] = float(deviation)
    instrument["comparison_check_count"] += 1
    recent = list(instrument["recent_deviations_pct"]) + [float(deviation)]
    recent = recent[-calc.ROLLING_WINDOW_SIZE:]
    instrument["recent_deviations_pct"] = recent
    bias = calc.rolling_bias(recent)
    instrument["rolling_bias_pct"] = float(bias) if bias is not None else None

    resolution = calc.comparison_resolution(deviation, bias)
    previous_check_at = instrument["_last_comparison_check_at"]

    if resolution == "OUT_OF_TOLERANCE":
        instrument["consecutive_out_of_tolerance_checks"] += 1
        if instrument["consecutive_out_of_tolerance_checks"] >= calc.WITHDRAWAL_CONSECUTIVE_FAILURES:
            instrument["approval_status"] = "WITHDRAWN"
        else:
            instrument["approval_status"] = "OUT_OF_TOLERANCE"
    else:
        instrument["consecutive_out_of_tolerance_checks"] = 0
        if resolution == "DRIFT_WATCH":
            if instrument["approval_status"] in ("APPROVED", "DRIFT_WATCH"):
                instrument["approval_status"] = "DRIFT_WATCH"
        elif instrument["approval_status"] == "DRIFT_WATCH":
            if instrument["certified_until"] is not None and instrument["certified_until"] > db.now:
                instrument["approval_status"] = "APPROVED"

    instrument["_last_comparison_check_at"] = db.now
    touch(instrument)

    if resolution == "OUT_OF_TOLERANCE":
        svc.instrument_tolerance_cascade(instrument, previous_check_at)

    if calc.counts_against_inspector(deviation):
        inspector["check_sample_deviation_count"] += 1
        svc.recompute_performance(inspector)
        touch(inspector)

    # Filing a check creates a new comparison-check row (§3.3 counts them and
    # orders analyses against "the instrument's previous comparison check"), so
    # PRD §4's "Operations that create a new resource return 201 Created" holds.
    return created(serialize(instrument))
