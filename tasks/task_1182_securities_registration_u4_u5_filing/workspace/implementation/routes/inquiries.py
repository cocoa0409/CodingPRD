"""RegulatoryInquiry endpoints."""
from flask import Blueprint

from db import store
from middleware import auth
from common import (
    body, get_or_404, required, require_enum, require_min_len, new_entity, touch,
    serialize, list_page,
)
from response import success_obj, success_list
from errors import (
    err_not_found, err_invalid_state, err_invalid_request, err_temporal,
)
from timeutil import now
from services import compute_deadline, INQUIRY_RESPONSE_DAYS

bp = Blueprint("inquiries", __name__)

READ_ROLES = ("SystemOperator", "ComplianceOfficer", "RegistrationPrincipal", "Regulator")
SUBJECT_TYPES = {"REGISTRATION_REQUEST", "AMENDMENT_FILING", "TERMINATION_FILING"}


def _resolve_subject(subject_type, subject_id):
    """Resolve the polymorphic subject FK and return the owning firm's id."""
    if subject_type == "REGISTRATION_REQUEST":
        coll, key = store.registration_requests, None
    elif subject_type == "AMENDMENT_FILING":
        coll, key = store.amendment_filings, "amendment"
    else:
        coll, key = store.termination_filings, "termination"
    filing = coll.get(subject_id)
    if filing is None:
        raise err_not_found()
    if key is None:
        req = filing
    else:
        req = store.registration_requests.get(filing["registration_request_id"])
    if req is None:
        raise err_not_found()
    return req["firm_id"]


@bp.post("/registration-desk/regulatory-inquiries")
def create_inquiry():
    auth("Regulator")
    data = body()
    # Field shape needed to attempt resolution (type enum) and required ids.
    stype = require_enum(required(data, "subject_filing_type"), SUBJECT_TYPES, "subject_filing_type")
    sid = required(data, "subject_filing_id")
    # Priority 3: the subject filing must exist.
    firm_id = _resolve_subject(stype, sid)
    # Priority 9: inquiry_text min length 20.
    text = require_min_len(required(data, "inquiry_text"), 20, "inquiry_text")
    created = now()
    q = new_entity()
    q.update({
        "firm_id": firm_id,
        "subject_filing_type": stype,
        "subject_filing_id": sid,
        "inquiry_text": text,
        # Inquiries always use the REGULATORY basis, 15 business days.
        "response_due_at": compute_deadline("REGULATORY", created.date(), INQUIRY_RESPONSE_DAYS),
        "response_text": None,
        "status": "OPEN",
    })
    store.regulatory_inquiries[q["id"]] = q
    return success_obj(serialize(q), 201)


@bp.get("/registration-desk/regulatory-inquiries")
def list_inquiries():
    auth(*READ_ROLES)
    page, limit, offset, total = list_page(
        store.regulatory_inquiries,
        (
            ("firm_id", "firm_id", str),
            ("subject_filing_id", "subject_filing_id", str),
            ("status", "status", str),
        ),
    )
    return success_list([serialize(q) for q in page], limit, offset, total)


@bp.get("/registration-desk/regulatory-inquiries/<id>")
def get_inquiry(id):
    auth(*READ_ROLES)
    q = get_or_404(store.regulatory_inquiries, id)
    return success_obj(serialize(q), 200)


@bp.post("/registration-desk/regulatory-inquiries/<id>/route")
def route_inquiry(id):
    auth("SystemOperator")
    q = get_or_404(store.regulatory_inquiries, id)
    if q["status"] != "OPEN":
        raise err_invalid_state("only an OPEN inquiry may be routed")
    q["status"] = "PENDING_RESPONSE"
    touch(q)
    return success_obj(serialize(q), 200)


@bp.post("/registration-desk/regulatory-inquiries/<id>/respond")
def respond_inquiry(id):
    auth("ComplianceOfficer")
    q = get_or_404(store.regulatory_inquiries, id)
    if q["status"] != "PENDING_RESPONSE":
        raise err_invalid_state("only a PENDING_RESPONSE inquiry may be responded to")
    data = body()
    text = require_min_len(required(data, "response_text"), 20, "response_text")
    if now() > q["response_due_at"]:
        raise err_temporal("the inquiry response is past its due date")
    q["response_text"] = text
    q["status"] = "RESPONDED"
    touch(q)
    return success_obj(serialize(q), 200)


@bp.post("/registration-desk/regulatory-inquiries/<id>/close")
def close_inquiry(id):
    auth("SystemOperator")
    q = get_or_404(store.regulatory_inquiries, id)
    if q["status"] != "RESPONDED":
        raise err_invalid_state("only a RESPONDED inquiry may be closed")
    q["status"] = "CLOSED"
    touch(q)
    return success_obj(serialize(q), 200)
