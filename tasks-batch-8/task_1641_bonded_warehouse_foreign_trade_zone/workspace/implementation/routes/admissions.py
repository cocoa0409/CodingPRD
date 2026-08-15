"""Admission endpoints (SCAFFOLD 1.5, PRD 3.2)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_ZONE_NOT_FOUND, ERR_ADMISSION_INVALID_TRANSITION,
    ERR_NOT_RESOURCE_OWNER, ERR_ZONE_NOT_ACTIVE, ERR_ZONE_AUDIT_HOLD,
    ERR_UNKNOWN_HTS_CODE, ERR_BOND_CAPACITY_EXCEEDED, ERR_ADMISSION_NOT_FOUND,
)
from middleware import authorized
from response import success_object, success_list
from serializers import admission_view
from services import (
    new_common, touch, create_lot_from_admission, admit_deferred_estimate,
    recompute_zone_aggregates, HTS_RATE_TABLE, ZONE_STATUSES, CLOCK,
)
from validate import (
    get_body, reject_unknown_fields, req_str, req_int, req_enum, require_path,
    require_body_fk, parse_pagination,
)

bp = Blueprint("admissions", __name__)

ALL_ROLES = ["ZoneOperator", "Importer", "CustomsOfficer", "GateOfficer"]


def _get_zone_or_404(zone_id):
    return require_body_fk("zones", zone_id, ERR_ZONE_NOT_FOUND, "zone_id")


@bp.route("/zones/admissions", methods=["POST"])
def create_admission():
    caller = authorized(["Importer"])
    body = get_body()
    reject_unknown_fields(body, {"zone_id", "description", "hts_code", "quantity",
                                 "unit_value_cents", "zone_status"})
    # Priority 3: body FK existence before schema checks on other fields? FK value
    # itself is schema-checked as a string first, then resolved.
    zone_id = req_str(body, "zone_id")
    zone = _get_zone_or_404(zone_id)
    description = req_str(body, "description")
    hts_code = req_str(body, "hts_code")  # HTS presence deliberately NOT verified at creation (PRD 3.2)
    quantity = req_int(body, "quantity", positive=True)
    unit_value = req_int(body, "unit_value_cents", non_negative=True)
    zone_status = req_enum(body, "zone_status", ZONE_STATUSES)

    admission = new_common()
    admission.update({
        "zone_id": zone["id"],
        "importer_ref": caller.user_id,
        "description": description,
        "hts_code": hts_code,
        "quantity": quantity,
        "unit_value_cents": unit_value,
        "zone_status": zone_status,
        "admission_date": None,
        "status": "DRAFT",
    })
    db["admissions"][admission["id"]] = admission
    return success_object(admission_view(admission), status=201)


@bp.route("/zones/admissions", methods=["GET"])
def list_admissions():
    authorized(ALL_ROLES)
    limit, offset = parse_pagination()
    zone_id = request.args.get("zone_id")
    importer_ref = request.args.get("importer_ref")
    status = request.args.get("status")
    zone_status = request.args.get("zone_status")
    items = sorted(db["admissions"].values(), key=lambda a: (a["created_at"], a["id"]))
    if zone_id is not None:
        items = [a for a in items if a["zone_id"] == zone_id]
    if importer_ref is not None:
        items = [a for a in items if a["importer_ref"] == importer_ref]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    if zone_status is not None:
        items = [a for a in items if a["zone_status"] == zone_status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([admission_view(a) for a in page], total, limit, offset)


@bp.route("/zones/admissions/<admissionId>", methods=["GET"])
def get_admission(admissionId):
    authorized(ALL_ROLES)
    admission = require_path("admissions", admissionId, ERR_ADMISSION_NOT_FOUND)
    return success_object(admission_view(admission))


def _zone_gate_active_and_normal(zone):
    if zone["status"] != "ACTIVE":
        raise_error(ERR_ZONE_NOT_ACTIVE, "operation requires zone.status == ACTIVE")
    if zone["compliance_posture"] != "NORMAL":
        raise_error(ERR_ZONE_AUDIT_HOLD, "operation requires zone.compliance_posture == NORMAL")


@bp.route("/zones/admissions/<admissionId>/submit", methods=["POST"])
def submit_admission(admissionId):
    caller = authorized(["Importer"])
    admission = require_path("admissions", admissionId, ERR_ADMISSION_NOT_FOUND)
    get_body()  # tolerate empty/absent body
    # Ownership (priority 5) precedes state preconditions (priority 6).
    if caller.user_id != admission["importer_ref"]:
        raise_error(ERR_NOT_RESOURCE_OWNER, "caller does not own this admission")
    if admission["status"] != "DRAFT":
        raise_error(ERR_ADMISSION_INVALID_TRANSITION,
                    f"admission cannot be submitted from {admission['status']}")
    zone = db["zones"][admission["zone_id"]]
    _zone_gate_active_and_normal(zone)

    admission["status"] = "SUBMITTED"
    touch(admission)
    return success_object(admission_view(admission))


@bp.route("/zones/admissions/<admissionId>/admit", methods=["POST"])
def admit_admission(admissionId):
    caller = authorized(["CustomsOfficer"])
    admission = require_path("admissions", admissionId, ERR_ADMISSION_NOT_FOUND)
    get_body()
    if admission["status"] != "SUBMITTED":
        raise_error(ERR_ADMISSION_INVALID_TRANSITION,
                    f"admission cannot be admitted from {admission['status']}")
    zone = db["zones"][admission["zone_id"]]
    _zone_gate_active_and_normal(zone)
    # HTS code must exist at this moment (referential, priority 10).
    if admission["hts_code"] not in HTS_RATE_TABLE:
        raise_error(ERR_UNKNOWN_HTS_CODE, f"hts_code {admission['hts_code']} not in tariff schedule")
    # Bond capacity enforced last (fiscal, priority 11); equality allowed.
    estimate = admit_deferred_estimate(admission)
    if zone["deferred_duty_exposure_cents"] + estimate > zone["bond_coverage_cents"]:
        raise_error(ERR_BOND_CAPACITY_EXCEEDED,
                    "admitting would exceed the zone's bond coverage")

    admission["status"] = "ADMITTED"
    admission["admission_date"] = CLOCK.now()
    touch(admission)
    create_lot_from_admission(admission)
    recompute_zone_aggregates(zone)
    return success_object(admission_view(admission))


@bp.route("/zones/admissions/<admissionId>/return", methods=["POST"])
def return_admission(admissionId):
    caller = authorized(["CustomsOfficer"])
    admission = require_path("admissions", admissionId, ERR_ADMISSION_NOT_FOUND)
    get_body()
    if admission["status"] != "SUBMITTED":
        raise_error(ERR_ADMISSION_INVALID_TRANSITION,
                    f"admission cannot be returned from {admission['status']}")
    admission["status"] = "DRAFT"
    touch(admission)
    return success_object(admission_view(admission))


@bp.route("/zones/admissions/<admissionId>/cancel", methods=["POST"])
def cancel_admission(admissionId):
    caller = authorized(["Importer"])
    admission = require_path("admissions", admissionId, ERR_ADMISSION_NOT_FOUND)
    get_body()
    if caller.user_id != admission["importer_ref"]:
        raise_error(ERR_NOT_RESOURCE_OWNER, "caller does not own this admission")
    if admission["status"] not in ("DRAFT", "SUBMITTED"):
        raise_error(ERR_ADMISSION_INVALID_TRANSITION,
                    f"admission cannot be cancelled from {admission['status']}")
    zone = db["zones"][admission["zone_id"]]
    # Cancellation checks only the lifecycle gate; audit hold is not a blocker (PRD 3.2).
    if zone["status"] != "ACTIVE":
        raise_error(ERR_ZONE_NOT_ACTIVE, "operation requires zone.status == ACTIVE")

    admission["status"] = "CANCELLED"
    touch(admission)
    return success_object(admission_view(admission))
