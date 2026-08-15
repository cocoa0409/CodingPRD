"""RegistrationCertificate endpoints (PRD 3.6): application, issuance, renewal
(on-time / late-within-grace / reinstatement after reinspection)."""

import uuid
from datetime import timedelta

from flask import Blueprint

import db
from errors import (
    ApiError, ERR_ACCEPTANCE_NOT_PASSED, ERR_ANNUAL_INSPECTION_REQUIRED,
    ERR_CERTIFICATE_NOT_FOUND, ERR_CERTIFICATE_STATE_FORBIDS,
    ERR_REINSPECTION_REQUIRED, ERR_RENEWAL_GRACE_EXPIRED, ERR_UNIT_NOT_FOUND,
    state_forbids,
)
from middleware import PROJECT_COORDINATOR, REGULATOR, ALL_ROLES, require_roles
from response import ok
from routes.common import get_or_404, list_endpoint
from services import calc, cascade
from util import add_years, get_json_body, serialize, validate_body

bp = Blueprint("certificates", __name__)

ACCEPTANCE_TYPES = ("ACCEPTANCE", "MODERNIZATION_ACCEPTANCE")


def _latest_of_type(unit_id, types):
    """Latest terminal inspection of the given type(s) on the unit."""
    terminal = [
        i for i in db.inspections.values()
        if i["unit_id"] == unit_id and i["inspection_type"] in types and i["status"] in ("PASSED", "FAILED")
    ]
    if not terminal:
        return None
    terminal.sort(key=lambda i: (i["recorded_at"], i["_seq"]))
    return terminal[-1]


@bp.post("/api/registration-certificates")
@require_roles(PROJECT_COORDINATOR)
def create_certificate():
    vals = validate_body(get_json_body(), {"unit_id": ("string", True, None)})
    unit = get_or_404(db.units, vals["unit_id"], ERR_UNIT_NOT_FOUND, "Unit")
    # referential gate: latest ACCEPTANCE / MODERNIZATION_ACCEPTANCE must be PASSED
    latest = _latest_of_type(unit["id"], ACCEPTANCE_TYPES)
    if latest is None or latest["status"] != "PASSED":
        raise ApiError(ERR_ACCEPTANCE_NOT_PASSED, 409, "Certificate application requires a PASSED acceptance inspection")
    rec = db.new_record({
        "unit_id": unit["id"],
        "certificate_number": None,
        "issued_date": None,
        "expiration_date": None,
        "renewal_count": 0,
        "last_renewal_fee": None,
        "status": "PENDING_ISSUANCE",
    })
    db.certificates[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.get("/api/registration-certificates")
@require_roles(*ALL_ROLES)
def list_certificates():
    return list_endpoint(db.certificates, {"unit_id": "unit_id", "status": "status"})


@bp.get("/api/registration-certificates/<certificateId>")
@require_roles(*ALL_ROLES)
def get_certificate(certificateId):
    rec = get_or_404(db.certificates, certificateId, ERR_CERTIFICATE_NOT_FOUND, "Certificate")
    return ok(serialize(rec))


@bp.post("/api/registration-certificates/<certificateId>/issue")
@require_roles(REGULATOR)
def issue_certificate(certificateId):
    cert = get_or_404(db.certificates, certificateId, ERR_CERTIFICATE_NOT_FOUND, "Certificate")
    if cert["status"] != "PENDING_ISSUANCE":
        raise state_forbids(ERR_CERTIFICATE_STATE_FORBIDS, "Certificate")
    cert["certificate_number"] = "CERT-" + uuid.uuid4().hex[:12].upper()
    cert["issued_date"] = db.now()
    cert["expiration_date"] = add_years(db.now(), 1)
    cert["status"] = "ACTIVE"
    db.touch(cert)
    # side effects: unit UNREGISTERED -> REGISTERED, INSTALLED -> IN_SERVICE
    unit = db.units.get(cert["unit_id"])
    if unit is not None:
        if unit["registration_status"] == "UNREGISTERED":
            unit["registration_status"] = "REGISTERED"
        if unit["equipment_status"] == "INSTALLED":
            unit["equipment_status"] = "IN_SERVICE"
        db.touch(unit)
        # side effect: installing project AWAITING_REGISTRATION -> REGISTERED
        project = db.projects.get(unit["project_id"])
        if project is not None and project["status"] == "AWAITING_REGISTRATION":
            project["status"] = "REGISTERED"
            db.touch(project)
    return ok(serialize(cert))


@bp.post("/api/registration-certificates/<certificateId>/renew")
@require_roles(PROJECT_COORDINATOR)
def renew_certificate(certificateId):
    cert = get_or_404(db.certificates, certificateId, ERR_CERTIFICATE_NOT_FOUND, "Certificate")
    clock = db.now()
    if cert["status"] == "RENEWAL_DUE":
        # requires the unit's latest ANNUAL inspection PASSED
        latest = _latest_of_type(cert["unit_id"], ("ANNUAL",))
        if latest is None or latest["status"] != "PASSED":
            raise ApiError(ERR_ANNUAL_INSPECTION_REQUIRED, 409, "Renewal requires the unit's latest ANNUAL inspection to be PASSED")
        cert["expiration_date"] = add_years(cert["expiration_date"], 1)
        cert["last_renewal_fee"] = calc.money(calc.BASE_RENEWAL_FEE)
    elif cert["status"] == "EXPIRED":
        # late renewal within the 90-day grace window; annual inspection first
        latest = _latest_of_type(cert["unit_id"], ("ANNUAL",))
        if latest is None or latest["status"] != "PASSED":
            raise ApiError(ERR_ANNUAL_INSPECTION_REQUIRED, 409, "Renewal requires the unit's latest ANNUAL inspection to be PASSED")
        late = calc.days_late(clock, cert["expiration_date"])
        if late > calc.GRACE_DAYS:
            raise ApiError(ERR_RENEWAL_GRACE_EXPIRED, 422, "Renewal attempted more than 90 days past expiration")
        cert["expiration_date"] = add_years(clock, 1)
        cert["last_renewal_fee"] = calc.renewal_fee(late)
        # restores the lapsed unit
        unit = db.units.get(cert["unit_id"])
        if unit is not None:
            if unit["registration_status"] == "LAPSED":
                unit["registration_status"] = "REGISTERED"
            if unit["equipment_status"] == "OUT_OF_SERVICE":
                unit["equipment_status"] = "IN_SERVICE"
            db.touch(unit)
    elif cert["status"] == "REVOKED":
        # reinstatement: latest REINSPECTION PASSED; always the base tier
        latest = _latest_of_type(cert["unit_id"], ("REINSPECTION",))
        if latest is None or latest["status"] != "PASSED":
            raise ApiError(ERR_REINSPECTION_REQUIRED, 409, "Reinstatement requires the unit's latest REINSPECTION to be PASSED")
        cert["expiration_date"] = add_years(clock, 1)
        cert["last_renewal_fee"] = calc.money(calc.BASE_RENEWAL_FEE)
        unit = db.units.get(cert["unit_id"])
        if unit is not None:
            if unit["registration_status"] == "SUSPENDED":
                unit["registration_status"] = "REGISTERED"
            if unit["equipment_status"] == "OUT_OF_SERVICE":
                unit["equipment_status"] = "IN_SERVICE"
            db.touch(unit)
    else:
        raise state_forbids(ERR_CERTIFICATE_STATE_FORBIDS, "Certificate")
    cert["status"] = "ACTIVE"
    cert["renewal_count"] += 1
    db.touch(cert)
    return ok(serialize(cert))
