"""TerminationFiling (U5) endpoints."""
from flask import Blueprint

from db import store
from middleware import auth
from common import (
    body, get_or_404, fk_or_404, required, require_enum, new_entity, touch,
    serialize, list_page,
)
from response import success_obj, success_list
from errors import (
    err_invalid_state, err_sod, err_invalid_request, err_temporal,
)
from timeutil import now, today, parse_date
from services import compute_deadline, firm_basis, cascade_request_terminated, U5_WINDOW_DAYS

bp = Blueprint("terminations", __name__)

READ_ROLES = ("SystemOperator", "ComplianceOfficer", "RegistrationPrincipal", "Regulator")
REASONS = {"VOLUNTARY", "PERMITTED_TO_RESIGN", "DISCHARGED", "DECEASED"}


def _inquiries_on(filing_id):
    return [
        q for q in store.regulatory_inquiries.values()
        if q["subject_filing_type"] == "TERMINATION_FILING" and q["subject_filing_id"] == filing_id
    ]


def _comments_on(filing_id):
    return [c for c in store.u5_comments.values() if c["termination_filing_id"] == filing_id]


@bp.post("/registration-desk/termination-filings")
def create_termination():
    uid, _ = auth("RegistrationPrincipal")
    data = body()
    req = fk_or_404(store.registration_requests, data.get("registration_request_id"))
    # Priority 5: the registration must be ACTIVE.
    if req is not None and req["status"] != "ACTIVE":
        raise err_invalid_state("a U5 may be filed only against an ACTIVE registration")
    # Priority 9: field shape.
    required(data, "registration_request_id")
    reason = require_enum(required(data, "termination_reason"), REASONS, "termination_reason")
    tdate_raw = required(data, "termination_date")
    tdate = parse_date(tdate_raw)
    if tdate is None:
        raise err_invalid_request("termination_date must be an ISO YYYY-MM-DD date")
    # Priority 10: termination_date may not be in the future.
    if tdate > today():
        raise err_temporal("termination_date may not be in the future")
    filed = now()
    basis = firm_basis(req["firm_id"])
    deadline = compute_deadline(basis, tdate, U5_WINDOW_DAYS)
    f = new_entity()
    f.update({
        "registration_request_id": req["id"],
        "termination_reason": reason,
        "termination_date": tdate_raw,
        "filed_at": filed,
        "filing_deadline_at": deadline,
        "is_late": filed > deadline,
        "status": "FILED",
        "_filer_user_id": uid,
    })
    store.termination_filings[f["id"]] = f
    # RegistrationRequest ACTIVE -> TERMINATED with the full cascade.
    req["status"] = "TERMINATED"
    touch(req)
    cascade_request_terminated(req)
    return success_obj(serialize(f), 201)


@bp.get("/registration-desk/termination-filings")
def list_terminations():
    auth(*READ_ROLES)
    page, limit, offset, total = list_page(
        store.termination_filings,
        (
            ("registration_request_id", "registration_request_id", str),
            ("status", "status", str),
        ),
    )
    return success_list([serialize(f) for f in page], limit, offset, total)


@bp.get("/registration-desk/termination-filings/<id>")
def get_termination(id):
    auth(*READ_ROLES)
    f = get_or_404(store.termination_filings, id)
    return success_obj(serialize(f), 200)


@bp.post("/registration-desk/termination-filings/<id>/open-amendment")
def open_amendment(id):
    auth("RegistrationPrincipal")
    f = get_or_404(store.termination_filings, id)
    if f["status"] != "FILED":
        raise err_invalid_state("only a FILED U5 may be opened for amendment")
    if any(q["status"] in ("OPEN", "PENDING_RESPONSE") for q in _inquiries_on(f["id"])):
        raise err_invalid_state("an open regulatory inquiry blocks opening the U5 for amendment")
    f["status"] = "AMENDMENT_OPEN"
    touch(f)
    return success_obj(serialize(f), 200)


@bp.post("/registration-desk/termination-filings/<id>/close-amendment")
def close_amendment(id):
    auth("RegistrationPrincipal")
    f = get_or_404(store.termination_filings, id)
    if f["status"] != "AMENDMENT_OPEN":
        raise err_invalid_state("only an AMENDMENT_OPEN U5 may be closed back to FILED")
    if any(c["disposition"] != "CONSISTENT" for c in _comments_on(f["id"])):
        raise err_invalid_state("every U5 comment must be CONSISTENT to close the amendment")
    f["status"] = "FILED"
    touch(f)
    return success_obj(serialize(f), 200)


@bp.post("/registration-desk/termination-filings/<id>/close")
def close_termination(id):
    uid, _ = auth("ComplianceOfficer")
    f = get_or_404(store.termination_filings, id)
    if f["status"] != "FILED":
        raise err_invalid_state("only a FILED U5 may be closed")
    if any(c["disposition"] != "CONSISTENT" for c in _comments_on(f["id"])):
        raise err_invalid_state("every U5 comment must be CONSISTENT to close the filing")
    if any(q["status"] != "CLOSED" for q in _inquiries_on(f["id"])):
        raise err_invalid_state("every regulatory inquiry on the filing must be CLOSED")
    if uid == f["_filer_user_id"]:
        raise err_sod()
    f["status"] = "CLOSED"
    touch(f)
    return success_obj(serialize(f), 200)
