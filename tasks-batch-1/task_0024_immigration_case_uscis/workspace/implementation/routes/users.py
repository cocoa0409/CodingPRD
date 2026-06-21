"""GET /uscis/applicants/{id} and GET /uscis/attorneys/{id}."""
from __future__ import annotations

from flask import Blueprint

import db
from middleware import require_auth
from response import ok_object
from services.validation import lookup_or_404


bp = Blueprint("users", __name__)


ALL_ROLES = ["Applicant", "Attorney", "Officer", "FieldOfficeAdmin"]


@bp.get("/uscis/applicants/<rid>")
def get_applicant(rid: str):
    require_auth(ALL_ROLES)()
    a = lookup_or_404(db.applicants, rid, "Applicant")
    return ok_object(a, 200)


@bp.get("/uscis/attorneys/<rid>")
def get_attorney(rid: str):
    require_auth(ALL_ROLES)()
    a = lookup_or_404(db.attorneys, rid, "Attorney")
    return ok_object(a, 200)
