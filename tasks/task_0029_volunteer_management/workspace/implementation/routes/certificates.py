"""Certificate template + certificate endpoints (issue, batch, reissue, revoke, verify)."""
from __future__ import annotations

import secrets
import string

from flask import Blueprint, g, request

import db
from errors import (
    ERR_CERTIFICATE_ALREADY_ISSUED,
    ERR_INVALID_INPUT,
    ERR_INVALID_STATE,
    ERR_NOT_ELIGIBLE,
    ERR_NOT_FOUND,
    err,
)
from middleware import auth_required
from response import success
from services.audit import append_audit, emit_sync
from services.occ import check_occ
from validators import as_int, as_number, as_str, require_field
from views import view_certificate, view_certificate_template


bp = Blueprint("certificates", __name__)


def _mint_serial() -> str:
    alphabet = string.ascii_uppercase + string.digits
    while True:
        s = "".join(secrets.choice(alphabet) for _ in range(12))
        if not any(c.get("serial_number") == s for c in db.certificates.values()):
            return s


@bp.post("/certificate-templates")
@auth_required(["SkillAdmin"])
def create_template():
    body = request.get_json(silent=True) or {}
    code = as_str(require_field(body, "code"), "code", 2, 40)
    title = as_str(require_field(body, "title"), "title", 1)
    min_hours_in = require_field(body, "min_hours")
    min_hours = as_number(min_hours_in, "min_hours", mn=0.01)
    if min_hours <= 0:
        raise err(ERR_INVALID_INPUT, "min_hours must be > 0")
    min_hours = db.round2(min_hours)
    min_completed_activities = as_int(require_field(body, "min_completed_activities"),
                                      "min_completed_activities", mn=1)

    with db.lock():
        for t in db.certificate_templates.values():
            if t["code"] == code:
                raise err(ERR_INVALID_INPUT, "code already exists")
        row = {
            "code": code,
            "title": title,
            "min_hours": min_hours,
            "min_completed_activities": min_completed_activities,
            "status": "ACTIVE",
        }
        db.init_common(row)
        db.certificate_templates[row["id"]] = row
    return success(view_certificate_template(row), status_code=201)


def _check_eligible(volunteer: dict, template: dict) -> tuple[bool, str | None]:
    if float(volunteer.get("total_service_hours", 0)) < float(template["min_hours"]):
        return False, "insufficient_hours"
    if int(volunteer.get("total_completed_activities", 0)) < int(template["min_completed_activities"]):
        return False, "insufficient_activities"
    return True, None


def _has_existing_active(volunteer_id: str, template_id: str) -> bool:
    for c in db.certificates.values():
        if c["volunteer_id"] == volunteer_id and c["template_id"] == template_id \
                and c["status"] not in {"REISSUED", "REVOKED"}:
            return True
    return False


@bp.post("/certificates")
@auth_required(["SkillAdmin"])
def issue_certificate():
    body = request.get_json(silent=True) or {}
    template_id = as_str(require_field(body, "template_id"), "template_id", 1)
    volunteer_id = as_str(require_field(body, "volunteer_id"), "volunteer_id", 1)
    template = db.certificate_templates.get(template_id)
    if not template:
        raise err(ERR_NOT_FOUND, "template not found")
    vol = db.volunteers.get(volunteer_id)
    if not vol:
        raise err(ERR_NOT_FOUND, "volunteer not found")

    with db.lock():
        if _has_existing_active(volunteer_id, template_id):
            raise err(ERR_CERTIFICATE_ALREADY_ISSUED,
                      "certificate already issued for (volunteer, template)")
        ok, _reason = _check_eligible(vol, template)
        if not ok:
            raise err(ERR_NOT_ELIGIBLE, "volunteer not eligible")

        cert = {
            "template_id": template_id,
            "volunteer_id": volunteer_id,
            "serial_number": _mint_serial(),
            "hours_at_issuance": float(vol.get("total_service_hours", 0)),
            "activities_at_issuance": int(vol.get("total_completed_activities", 0)),
            "status": "ISSUED",
            "replacement_serial_number": None,
        }
        db.init_common(cert)
        db.certificates[cert["id"]] = cert

        append_audit("SkillAdmin", g.user_id, "CERTIFICATE_ISSUE",
                     "Certificate", cert["id"],
                     {"template_id": template_id, "volunteer_id": volunteer_id,
                      "serial_number": cert["serial_number"]})
        emit_sync("PARTNER_ORG", "CERTIFICATE_ISSUED",
                  {"certificate_id": cert["id"], "serial_number": cert["serial_number"],
                   "volunteer_id": volunteer_id, "template_id": template_id})
    return success(view_certificate(cert), status_code=201)


@bp.post("/certificates/batch")
@auth_required(["SkillAdmin"])
def batch_issue():
    body = request.get_json(silent=True) or {}
    template_id = as_str(require_field(body, "template_id"), "template_id", 1)
    volunteer_ids = require_field(body, "volunteer_ids")
    if not isinstance(volunteer_ids, list):
        raise err(ERR_INVALID_INPUT, "volunteer_ids must be a list")
    template = db.certificate_templates.get(template_id)
    if not template:
        raise err(ERR_NOT_FOUND, "template not found")

    issued = []
    skipped = []
    with db.lock():
        for vid in volunteer_ids:
            if not isinstance(vid, str):
                skipped.append({"volunteer_id": vid, "reason": "invalid_volunteer_id"})
                continue
            vol = db.volunteers.get(vid)
            if not vol:
                skipped.append({"volunteer_id": vid, "reason": "not_found"})
                continue
            if _has_existing_active(vid, template_id):
                skipped.append({"volunteer_id": vid, "reason": "already_issued"})
                continue
            ok, reason = _check_eligible(vol, template)
            if not ok:
                skipped.append({"volunteer_id": vid, "reason": reason})
                continue

            cert = {
                "template_id": template_id,
                "volunteer_id": vid,
                "serial_number": _mint_serial(),
                "hours_at_issuance": float(vol.get("total_service_hours", 0)),
                "activities_at_issuance": int(vol.get("total_completed_activities", 0)),
                "status": "ISSUED",
                "replacement_serial_number": None,
            }
            db.init_common(cert)
            db.certificates[cert["id"]] = cert
            issued.append(view_certificate(cert))

            append_audit("SkillAdmin", g.user_id, "CERTIFICATE_ISSUE",
                         "Certificate", cert["id"],
                         {"template_id": template_id, "volunteer_id": vid,
                          "serial_number": cert["serial_number"]})
            emit_sync("PARTNER_ORG", "CERTIFICATE_ISSUED",
                      {"certificate_id": cert["id"], "serial_number": cert["serial_number"],
                       "volunteer_id": vid, "template_id": template_id})

    return success({"issued": issued, "skipped": skipped})


@bp.post("/certificates/<cid>/reissue")
@auth_required(["SkillAdmin"])
def reissue_certificate(cid):
    old = db.certificates.get(cid)
    if not old:
        raise err(ERR_NOT_FOUND, "certificate not found")
    body = request.get_json(silent=True) or {}
    check_occ(old, body)
    with db.lock():
        if old["status"] != "ISSUED":
            raise err(ERR_INVALID_STATE, "must be ISSUED to reissue")
        vol = db.volunteers.get(old["volunteer_id"])
        if not vol:
            raise err(ERR_NOT_FOUND, "volunteer not found")
        new_cert = {
            "template_id": old["template_id"],
            "volunteer_id": old["volunteer_id"],
            "serial_number": _mint_serial(),
            "hours_at_issuance": float(vol.get("total_service_hours", 0)),
            "activities_at_issuance": int(vol.get("total_completed_activities", 0)),
            "status": "ISSUED",
            "replacement_serial_number": None,
        }
        db.init_common(new_cert)
        db.certificates[new_cert["id"]] = new_cert

        old["status"] = "REISSUED"
        old["replacement_serial_number"] = new_cert["serial_number"]
        db.touch(old)

        append_audit("SkillAdmin", g.user_id, "CERTIFICATE_REISSUE",
                     "Certificate", old["id"],
                     {"old_certificate_id": old["id"],
                      "new_certificate_id": new_cert["id"],
                      "serial_number": new_cert["serial_number"]})
    return success(view_certificate(new_cert), status_code=201)


@bp.post("/certificates/<cid>/revoke")
@auth_required(["SkillAdmin"])
def revoke_certificate(cid):
    cert = db.certificates.get(cid)
    if not cert:
        raise err(ERR_NOT_FOUND, "certificate not found")
    body = request.get_json(silent=True) or {}
    check_occ(cert, body)
    with db.lock():
        if cert["status"] != "ISSUED":
            raise err(ERR_INVALID_STATE, "must be ISSUED to revoke")
        cert["status"] = "REVOKED"
        db.touch(cert)
        append_audit("SkillAdmin", g.user_id, "CERTIFICATE_REVOKE",
                     "Certificate", cert["id"],
                     {"certificate_id": cert["id"]})
    return success(view_certificate(cert))


@bp.get("/certificates/verify/<serial_number>")
@auth_required(["Volunteer", "Organizer", "SkillAdmin"])
def verify_certificate(serial_number):
    for c in db.certificates.values():
        if c.get("serial_number") == serial_number:
            return success(view_certificate(c))
    raise err(ERR_NOT_FOUND, "certificate not found")
