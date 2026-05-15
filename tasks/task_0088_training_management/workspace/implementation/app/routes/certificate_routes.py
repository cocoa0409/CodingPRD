"""CertificateTemplate and Certificate endpoints."""
from __future__ import annotations

from typing import Any

from flask import Flask, g, request

from ..auth import optional_auth, require_auth
from ..clock import add_days, add_months, format_iso, now_dt, parse_iso
from ..errors import ApiError
from ..pagination import parse_limit_offset
from ..store import bump_version, common_fields_append_only, common_fields_create, get_store, new_id
from ..services.lookups import get_certificate, ref_course, ref_enrollment
from ..services.serializers import serialize_certificate, serialize_certificate_template
from ._helpers import created, get_json_body, ok, ok_list, sort_by_created, with_lock


def register(app: Flask) -> None:
    @app.post("/training/certificate-templates")
    @require_auth("TrainingAdmin")
    @with_lock
    def create_template():
        body = get_json_body()
        course_id = body.get("course_id")
        if not course_id:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "course_id required.", http_status=422)
        course = ref_course(course_id)
        store = get_store()
        if course_id in store.cert_template_by_course:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "Template already exists for this course.", http_status=422)
        try:
            vm = int(body.get("validity_months"))
        except (TypeError, ValueError):
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "validity_months required.", http_status=422)
        if not (1 <= vm <= 120):
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "validity_months out of range.", http_status=422)
        rwd = body.get("renewal_window_days", 30)
        try:
            rwd = int(rwd)
        except (TypeError, ValueError):
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "renewal_window_days invalid.", http_status=422)
        if not (1 <= rwd <= 180):
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "renewal_window_days out of range.", http_status=422)
        req_att = bool(body.get("requires_attendance", True))
        req_exam = bool(body.get("requires_exam_pass", True))

        base = common_fields_create()
        row: dict[str, Any] = {
            **base,
            "course_id": course_id,
            "validity_months": vm,
            "renewal_window_days": rwd,
            "requires_attendance": req_att,
            "requires_exam_pass": req_exam,
        }
        store.certificate_templates[base["id"]] = row
        store.cert_template_by_course[course_id] = base["id"]
        return created(serialize_certificate_template(row))

    @app.get("/training/certificates")
    @require_auth("TrainingAdmin", "DepartmentManager", "Trainee")
    @with_lock
    def list_certificates():
        limit, offset = parse_limit_offset()
        trainee_id = request.args.get("trainee_id")
        status = request.args.get("status")
        items = list(get_store().certificates.values())
        if g.user_role == "Trainee":
            items = [c for c in items if c["trainee_id"] == g.user_id]
        if trainee_id:
            items = [c for c in items if c["trainee_id"] == trainee_id]
        if status:
            items = [c for c in items if c["status"] == status]
        items = sort_by_created(items)
        return ok_list([serialize_certificate(c) for c in items], limit, offset)

    @app.get("/training/certificates/<cid>")
    @require_auth("TrainingAdmin", "DepartmentManager", "Trainee")
    @with_lock
    def fetch_certificate(cid):
        c = get_certificate(cid)
        if g.user_role == "Trainee" and c["trainee_id"] != g.user_id:
            raise ApiError("ERR_FORBIDDEN_ROLE", "Cannot view another trainee's certificate.")
        return ok(serialize_certificate(c))

    @app.post("/training/certificates/<cid>/renew")
    @require_auth("Trainee")
    @with_lock
    def renew_certificate(cid):
        c = get_certificate(cid)
        if c["trainee_id"] != g.user_id:
            raise ApiError("ERR_FORBIDDEN_ROLE", "Cannot renew another trainee's certificate.")
        if c["status"] != "EXPIRING_SOON":
            raise ApiError("ERR_INVALID_STATE", "Certificate not in EXPIRING_SOON.")
        body = get_json_body()
        source_enrollment_id = body.get("source_enrollment_id")
        if not source_enrollment_id:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "source_enrollment_id required.", http_status=422)
        store = get_store()
        e = store.enrollments.get(source_enrollment_id)
        if not e:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "Enrollment not found.")
        if e["trainee_id"] != g.user_id:
            raise ApiError("ERR_RENEWAL_WINDOW_INVALID", "Source enrollment not owned.")
        if e.get("status") != "COMPLETED":
            raise ApiError("ERR_RENEWAL_WINDOW_INVALID", "Source enrollment not COMPLETED.")
        sess = store.sessions.get(e["session_id"])
        if not sess:
            raise ApiError("ERR_RENEWAL_WINDOW_INVALID", "Source session not found.")
        # session.course_id must match original certificate's course
        tpl = store.certificate_templates.get(c["certificate_template_id"])
        if not tpl:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "Template missing.")
        if sess["course_id"] != tpl["course_id"]:
            raise ApiError("ERR_RENEWAL_WINDOW_INVALID", "Source enrollment course mismatch.")
        # Window: session.start_at in (expires_at - renewal_window_days, expires_at]
        expires_dt = parse_iso(c["expires_at"])
        window_start = add_days(expires_dt, -int(tpl["renewal_window_days"]))
        sess_start = parse_iso(sess["start_at"])
        if not (window_start < sess_start <= expires_dt):
            raise ApiError("ERR_RENEWAL_WINDOW_INVALID", "Source session outside renewal window.")

        # Create new certificate
        new_expires = add_months(expires_dt, int(tpl["validity_months"]))
        base = common_fields_append_only()
        code = new_id().replace("-", "")
        while code in store.verification_code_uniq:
            code = new_id().replace("-", "")
        new_cert = {
            "id": base["id"],
            "created_at": base["created_at"],
            "updated_at": base["created_at"],
            "version": 0,
            "trainee_id": c["trainee_id"],
            "certificate_template_id": tpl["id"],
            "source_enrollment_id": source_enrollment_id,
            "issued_at": base["created_at"],
            "expires_at": format_iso(new_expires),
            "status": "VALID",
            "verification_code": code,
        }
        store.certificates[base["id"]] = new_cert
        store.verification_code_uniq[code] = base["id"]

        # Old becomes RENEWED
        c["status"] = "RENEWED"
        bump_version(c)
        return created(serialize_certificate(new_cert))

    @app.post("/training/certificates/<cid>/revoke")
    @require_auth("TrainingAdmin")
    @with_lock
    def revoke_certificate(cid):
        c = get_certificate(cid)
        if c["status"] not in ("VALID", "EXPIRING_SOON"):
            raise ApiError("ERR_INVALID_STATE", "Certificate cannot be revoked in current state.")
        c["status"] = "REVOKED"
        bump_version(c)
        return ok(serialize_certificate(c))

    @app.post("/training/certificates/verify/<code>")
    @optional_auth
    @with_lock
    def verify_certificate(code):
        store = get_store()
        cid = store.verification_code_uniq.get(code)
        if not cid:
            raise ApiError("ERR_RESOURCE_NOT_FOUND", "Verification code unknown.")
        c = store.certificates.get(cid)
        if not c:
            raise ApiError("ERR_RESOURCE_NOT_FOUND", "Certificate not found.")
        # Minimal payload — no private trainee data
        payload = {
            "verification_code": code,
            "status": c["status"],
            "issued_at": c["issued_at"],
            "expires_at": c["expires_at"],
            "certificate_template_id": c["certificate_template_id"],
        }
        return ok(payload)
