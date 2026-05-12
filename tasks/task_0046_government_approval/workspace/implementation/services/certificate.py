"""Certificate issuance, reissue, revoke, verification."""

from __future__ import annotations

import base64
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

import db
from config import DAY_SECONDS
from errors import (
    AppError,
    ERR_CERTIFICATE_ALREADY_REISSUED,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
)
from services import audit, calculations
from services import validators as V


_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


def _render_body(template: str, vars_: dict) -> str:
    def _sub(m):
        name = m.group(1)
        return str(vars_.get(name, ""))
    return _PLACEHOLDER_RE.sub(_sub, template)


def _generate_serial(matter_code: str, day_dt: datetime) -> str:
    day_str = day_dt.strftime("%y%m%d")
    seq = db.next_cert_seq(matter_code, day_str)
    return f"GOV-{matter_code}-{day_str}-{seq:06d}"


def _generate_verification_code(serial: str) -> str:
    raw = uuid.uuid4().bytes + serial.encode("utf-8")
    encoded = base64.b32encode(raw).decode("ascii").rstrip("=")
    # Strip non-alphanumeric (b32 is already alnum) and take first 16.
    return encoded[:16]


def _resolve_variable(name: str, application: dict, version: dict,
                      matter: dict) -> str:
    """Look up a variable from application + version + matter context."""
    # Prefer explicit application metadata, then matter, then version.
    sources = [
        application,
        version,
        matter,
        {
            "applicant_user_id": application.get("applicant_user_id"),
            "matter_code": matter.get("code"),
            "matter_theme": matter.get("theme"),
            "version_label": version.get("version_label"),
            "issued_at": db.now_iso(),
            "channel": application.get("channel"),
        },
    ]
    for src in sources:
        if src and name in src and src[name] is not None:
            return calculations.format_variable(src[name])
    return ""


def issue_certificate_for_application(app_id: str) -> dict | None:
    app = db.find_by_id("applications", app_id)
    if not app or app["review_status"] != "APPROVED":
        return None
    version = db.find_by_id("matter_versions", app["matter_version_id"])
    matter = db.find_by_id("matters", version["matter_id"])
    template = db.find_by_id("certificate_templates", version["certificate_template_id"])
    if not template:
        return None

    rendered_vars = {}
    for v in template["required_variables"]:
        rendered_vars[v] = _resolve_variable(v, app, version, matter)
    rendered_body = _render_body(template["body_template"], rendered_vars)

    issued_at_dt = db.now_dt()
    issued_at = db.format_ts(issued_at_dt)
    serial = _generate_serial(matter["code"], issued_at_dt)
    code = _generate_verification_code(serial)

    if template["validity_days"] > 0:
        expires_dt = issued_at_dt + timedelta(seconds=template["validity_days"] * DAY_SECONDS)
        expires_at = db.format_ts(expires_dt)
    else:
        expires_at = None

    cert = db.insert("certificates", {
        "application_id": app_id,
        "certificate_template_id": template["id"],
        "serial_number": serial,
        "verification_code": code,
        "rendered_body": rendered_body,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "status": "ACTIVE",
        "superseded_by_certificate_id": None,
    })
    audit.write("CERT_ISSUE", "Certificate", cert["id"],
                {"application_id": app_id, "serial_number": serial})
    return cert


def get_certificate_for_application(app_id: str) -> dict:
    app = db.find_by_id("applications", app_id)
    if not app:
        raise AppError(ERR_NOT_FOUND, f"Application not found: {app_id}", 404)
    if app["review_status"] != "APPROVED":
        raise AppError(ERR_INVALID_STATE,
                       f"Application status is {app['review_status']}; no certificate",
                       409)
    # Read access: Applicant (own), PlatformAdmin, CertificateOfficer.
    role = g.role
    if role == "Applicant" and app["applicant_user_id"] != g.user_id:
        raise AppError(ERR_FORBIDDEN,
                       "Applicant may only access own application's certificate",
                       403)
    certs = sorted(
        [c for c in db.find_many("certificates", application_id=app_id)],
        key=lambda c: c.get("created_at") or "",
    )
    if not certs:
        raise AppError(ERR_NOT_FOUND,
                       "No certificate issued for this application", 404)
    # Return the most recent non-REISSUED certificate; if all are REISSUED, the latest one.
    active = [c for c in certs if c["status"] != "REISSUED"]
    if active:
        active.sort(key=lambda c: c.get("created_at") or "", reverse=True)
        return active[0]
    return certs[-1]


def reissue_certificate(cert_id: str, body: dict) -> dict:
    cert = db.find_by_id("certificates", cert_id)
    if not cert:
        raise AppError(ERR_NOT_FOUND, f"Certificate not found: {cert_id}", 404)

    if g.role != "CertificateOfficer":
        raise AppError(ERR_FORBIDDEN,
                       "Only CertificateOfficer may reissue certificates", 403)

    # Priority 4: state — current must be ACTIVE or EXPIRED.
    if cert["status"] not in {"ACTIVE", "EXPIRED"}:
        # If REISSUED, surface the more specific error per priority 18.
        if cert["status"] == "REISSUED" or cert.get("superseded_by_certificate_id"):
            raise AppError(ERR_CERTIFICATE_ALREADY_REISSUED,
                           "Certificate already reissued", 409)
        raise AppError(ERR_INVALID_STATE,
                       f"Cannot reissue certificate in status {cert['status']}",
                       409)
    # Priority 18: already-reissued.
    if cert.get("superseded_by_certificate_id"):
        raise AppError(ERR_CERTIFICATE_ALREADY_REISSUED,
                       "Certificate already reissued", 409)

    app = db.find_by_id("applications", cert["application_id"])
    if not app or app["review_status"] != "APPROVED":
        raise AppError(ERR_INVALID_STATE,
                       "Source application must be APPROVED to reissue", 409)

    from services import occ
    occ.check(cert, body)

    version = db.find_by_id("matter_versions", app["matter_version_id"])
    matter = db.find_by_id("matters", version["matter_id"])
    template = db.find_by_id("certificate_templates", cert["certificate_template_id"])

    rendered_vars = {}
    for v in template["required_variables"]:
        rendered_vars[v] = _resolve_variable(v, app, version, matter)
    rendered_body = _render_body(template["body_template"], rendered_vars)

    issued_at_dt = db.now_dt()
    issued_at = db.format_ts(issued_at_dt)
    serial = _generate_serial(matter["code"], issued_at_dt)
    code = _generate_verification_code(serial)
    if template["validity_days"] > 0:
        expires_dt = issued_at_dt + timedelta(seconds=template["validity_days"] * DAY_SECONDS)
        expires_at = db.format_ts(expires_dt)
    else:
        expires_at = None

    new_cert = db.insert("certificates", {
        "application_id": app["id"],
        "certificate_template_id": template["id"],
        "serial_number": serial,
        "verification_code": code,
        "rendered_body": rendered_body,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "status": "ACTIVE",
        "superseded_by_certificate_id": None,
    })
    db.update("certificates", cert_id, {
        "status": "REISSUED",
        "superseded_by_certificate_id": new_cert["id"],
    })
    audit.write("CERT_REISSUE", "Certificate", new_cert["id"],
                {"superseded": cert_id})
    return new_cert


def revoke_certificate(cert_id: str, body: dict) -> dict:
    cert = db.find_by_id("certificates", cert_id)
    if not cert:
        raise AppError(ERR_NOT_FOUND, f"Certificate not found: {cert_id}", 404)

    if cert["status"] != "ACTIVE":
        raise AppError(ERR_INVALID_STATE,
                       f"Only ACTIVE certificates may be revoked (current: {cert['status']})",
                       409)
    body = V.must_be_dict(body)
    reason = V.opt_str(body, "reason", default=None)

    from services import occ
    occ.check(cert, body)

    db.update("certificates", cert_id, {"status": "REVOKED"})
    audit.write("CERT_REVOKE", "Certificate", cert_id, {"reason": reason})
    return db.find_by_id("certificates", cert_id)


def verify_certificate(verification_code: str) -> dict:
    cert = db.find_one("certificates", verification_code=verification_code)
    if not cert:
        raise AppError(ERR_NOT_FOUND, "verification_code not found", 404)
    return {
        "verification_code": cert["verification_code"],
        "serial_number": cert["serial_number"],
        "status": cert["status"],
        "issued_at": cert["issued_at"],
        "expires_at": cert["expires_at"],
    }
