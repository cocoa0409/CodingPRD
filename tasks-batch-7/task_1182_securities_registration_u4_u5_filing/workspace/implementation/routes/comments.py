"""U5Comment endpoints."""
from flask import Blueprint

from db import store
from middleware import auth
from common import (
    body, get_or_404, fk_or_404, required, require_min_len, new_entity,
    serialize, list_page,
)
from response import success_obj, success_list
from services import comment_disposition

bp = Blueprint("comments", __name__)

READ_ROLES = ("SystemOperator", "ComplianceOfficer", "RegistrationPrincipal", "Regulator")
ROLE_MAP = {
    "ComplianceOfficer": "COMPLIANCE_OFFICER",
    "RegistrationPrincipal": "REGISTRATION_PRINCIPAL",
}


@bp.post("/registration-desk/u5-comments")
def create_comment():
    uid, role = auth("ComplianceOfficer", "RegistrationPrincipal")
    data = body()
    filing = fk_or_404(store.termination_filings, data.get("termination_filing_id"))
    required(data, "termination_filing_id")
    text = require_min_len(required(data, "comment_text"), 10, "comment_text")
    c = new_entity()
    c.update({
        "termination_filing_id": filing["id"],
        "author_role": ROLE_MAP[role],
        "comment_text": text,
        "disposition": comment_disposition(filing["termination_reason"], text),
    })
    store.u5_comments[c["id"]] = c
    return success_obj(serialize(c), 201)


@bp.get("/registration-desk/u5-comments")
def list_comments():
    auth(*READ_ROLES)
    page, limit, offset, total = list_page(
        store.u5_comments,
        (
            ("termination_filing_id", "termination_filing_id", str),
            ("disposition", "disposition", str),
        ),
    )
    return success_list([serialize(c) for c in page], limit, offset, total)


@bp.get("/registration-desk/u5-comments/<id>")
def get_comment(id):
    auth(*READ_ROLES)
    c = get_or_404(store.u5_comments, id)
    return success_obj(serialize(c), 200)
