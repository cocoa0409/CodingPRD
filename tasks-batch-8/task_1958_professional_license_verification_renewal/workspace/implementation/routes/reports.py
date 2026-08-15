"""Compliance summary report endpoint (PRD 3.9)."""
from flask import Blueprint

from db import DB
from middleware import SUMMARY_ROLES, auth
from response import ok
from serializers import employee_view, license_view

bp = Blueprint("reports", __name__, url_prefix="/licensing")


@bp.get("/reports/compliance-summary")
def compliance_summary():
    auth(SUMMARY_ROLES)
    # Views refresh derived fields before counting.
    emp_views = [employee_view(e) for e in DB["employees"].values()]
    lic_views = [license_view(l) for l in DB["licenses"].values()]
    summary = {
        "authorized_employee_count": sum(
            1 for v in emp_views if v["work_authorization"] == "AUTHORIZED"
        ),
        "restricted_employee_count": sum(
            1 for v in emp_views if v["work_authorization"] == "RESTRICTED"
        ),
        "flagged_employee_count": sum(
            1 for v in emp_views if v["screening_posture"] == "FLAGGED"
        ),
        "expired_license_count": sum(
            1 for v in lic_views if v["status"] == "EXPIRED"
        ),
        "overdue_verification_count": sum(
            1 for v in lic_views if v["verification_posture"] == "OVERDUE"
        ),
        "open_screening_count": sum(
            1
            for s in DB["exclusion_screenings"].values()
            if s["status"] == "UNDER_REVIEW"
        ),
        "committed_reimbursement_cents": sum(
            v["reimbursement_committed_cents"] for v in emp_views
        ),
        "paid_reimbursement_cents": sum(
            v["reimbursement_paid_cents"] for v in emp_views
        ),
    }
    return ok(summary)
