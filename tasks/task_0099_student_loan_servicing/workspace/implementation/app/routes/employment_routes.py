"""Employment certification routes."""
from __future__ import annotations

from flask import Flask

from ..auth import current_actor, require_auth
from ..clock import parse_iso
from ..errors import ApiError
from ..pagination import parse_limit_offset, parse_optional_str
from ..services import payments as payment_svc
from ..store import bump_version, common_fields_create, get_store
from ._helpers import (
    check_version_or_conflict,
    created,
    get_borrower_or_404,
    get_json_body,
    list_ok,
    ok,
)


VALID_EMPLOYER_TYPES = {
    "GOVERNMENT",
    "NONPROFIT_501C3",
    "OTHER_NONPROFIT_QUALIFYING",
    "PRIVATE_NON_QUALIFYING",
}
QUALIFYING_TYPES = {"GOVERNMENT", "NONPROFIT_501C3", "OTHER_NONPROFIT_QUALIFYING"}


def register(app: Flask) -> None:
    @app.route("/borrowers/<borrower_id>/employment-certifications", methods=["POST"])
    @require_auth("Borrower", "ServicerAdmin")
    def create_cert(borrower_id):
        get_borrower_or_404(borrower_id)
        body = get_json_body(allow_empty=False)
        emp_type = body.get("employer_type")
        if emp_type not in VALID_EMPLOYER_TYPES:
            raise ApiError("ERR_INVALID_INPUT", f"Invalid employer_type: {emp_type}")
        emp_name = body.get("employer_name")
        if not isinstance(emp_name, str) or not emp_name:
            raise ApiError("ERR_INVALID_INPUT", "employer_name required.")
        ps = body.get("period_start")
        pe = body.get("period_end")
        if not ps or not pe:
            raise ApiError("ERR_INVALID_INPUT", "period_start/period_end required.")
        try:
            ps_dt = parse_iso(ps)
            pe_dt = parse_iso(pe)
        except Exception:
            raise ApiError("ERR_BAD_DATE_WINDOW", "Invalid period dates.")
        if pe_dt <= ps_dt:
            raise ApiError("ERR_BAD_DATE_WINDOW", "period_end must be after period_start.")
        cert = {
            **common_fields_create(),
            "borrower_id": borrower_id,
            "employer_name": emp_name,
            "employer_type": emp_type,
            "period_start": ps,
            "period_end": pe,
            "status": "SUBMITTED",
            "reviewed_by": None,
            "rejection_reason": None,
        }
        get_store().employment_certifications[cert["id"]] = cert
        return created(cert)

    @app.route("/borrowers/<borrower_id>/employment-certifications", methods=["GET"])
    @require_auth("Borrower", "ServicerAdmin", "ServicerCertifier", "ServicerApprover")
    def list_cert(borrower_id):
        get_borrower_or_404(borrower_id)
        limit, offset = parse_limit_offset()
        status = parse_optional_str("status")
        items = [
            c for c in get_store().employment_certifications.values()
            if c.get("borrower_id") == borrower_id
        ]
        if status:
            items = [c for c in items if c["status"] == status]
        items.sort(key=lambda c: c["created_at"])
        page = {
            "limit": limit,
            "offset": offset,
            "total_count": len(items),
            "has_more": offset + limit < len(items),
        }
        return list_ok(items[offset : offset + limit], page)

    @app.route("/borrowers/<borrower_id>/employment-certifications/<certification_id>", methods=["PATCH"])
    @require_auth("ServicerCertifier")
    def patch_cert(borrower_id, certification_id):
        get_borrower_or_404(borrower_id)
        cert = get_store().employment_certifications.get(certification_id)
        if not cert or cert.get("borrower_id") != borrower_id:
            raise ApiError("ERR_RESOURCE_NOT_FOUND", f"Certification {certification_id} not found.")
        body = get_json_body(allow_empty=False)
        check_version_or_conflict(cert, body)
        if cert["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", "Certification is not in SUBMITTED.")
        target = body.get("status")
        if target not in ("APPROVED", "REJECTED"):
            raise ApiError("ERR_INVALID_INPUT", f"Invalid target status: {target}")
        user_id, _ = current_actor()
        if target == "REJECTED":
            cert["status"] = "REJECTED"
            cert["rejection_reason"] = body.get("rejection_reason") or ""
            cert["reviewed_by"] = user_id
            bump_version(cert)
            return ok(cert)
        # APPROVED
        if cert["employer_type"] not in QUALIFYING_TYPES:
            raise ApiError(
                "ERR_INVALID_STATE",
                "Cannot approve a non-qualifying employer_type.",
            )
        cert["status"] = "APPROVED"
        cert["reviewed_by"] = user_id
        bump_version(cert)
        # Trigger PSLF recount
        payment_svc.recount_pslf_for_borrower(borrower_id)
        return ok(cert)
