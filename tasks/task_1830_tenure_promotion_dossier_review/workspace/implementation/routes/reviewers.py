"""ExternalReviewer endpoints (PRD §3.4)."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_REVIEWER_NOT_FOUND, ERR_DUPLICATE_REVIEWER_EMAIL
from middleware import authorized
from response import success_object
from routes.helpers import public, get_one
from services.core import new_record
from validate import get_body, req_str, raw_str

bp = Blueprint("reviewers", __name__)


@bp.post("/reviewers")
def create_reviewer():
    authorized(["ProvostOfficer"])
    body = get_body()
    # Priority 9 structural, listed order: duplicate email, then shape.
    email_raw = raw_str(body, "email")
    if email_raw is not None:
        for r in db["reviewers"].values():
            if r["email"] == email_raw:
                raise_error(ERR_DUPLICATE_REVIEWER_EMAIL, "reviewer email already registered")
    full_name = req_str(body, "full_name")
    institution = req_str(body, "institution")
    email = req_str(body, "email")
    expertise_area = req_str(body, "expertise_area")
    rec = new_record("reviewers", {
        "full_name": full_name,
        "institution": institution,
        "email": email,
        "expertise_area": expertise_area,
    })
    return success_object(public(rec), status=201)


@bp.get("/reviewers/<rid>")
def get_reviewer(rid):
    return get_one("reviewers", rid, ERR_REVIEWER_NOT_FOUND)
