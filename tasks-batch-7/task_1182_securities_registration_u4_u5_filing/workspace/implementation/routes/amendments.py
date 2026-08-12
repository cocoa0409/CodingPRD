"""AmendmentFiling endpoints."""
from flask import Blueprint

from db import store
from middleware import auth
from common import (
    body, get_or_404, fk_or_404, required, require_min_len, new_entity, touch,
    serialize, list_page,
)
from response import success_obj, success_list
from errors import err_invalid_state, err_sod, err_referential
from timeutil import now
from services import (
    compute_deadline, applicant_active_registration, AMENDMENT_WINDOW_DAYS,
)

bp = Blueprint("amendments", __name__)

READ_ROLES = ("SystemOperator", "ComplianceOfficer", "RegistrationPrincipal", "Regulator")


@bp.post("/registration-desk/amendment-filings")
def create_amendment():
    uid, _ = auth("RegistrationPrincipal")
    data = body()
    ev = fk_or_404(store.disclosure_events, data.get("disclosure_event_id"))
    # Priority 5: event must be OPEN.
    if ev is not None and ev["status"] != "OPEN":
        raise err_invalid_state("amendments may be filed only against an OPEN disclosure event")
    # Priority 9: narrative_text min length 20.
    required(data, "disclosure_event_id")
    narrative = require_min_len(required(data, "narrative_text"), 20, "narrative_text")
    # Priority 11: the applicant must have an ACTIVE registration at filing time.
    active_req = applicant_active_registration(ev["applicant_id"])
    if active_req is None:
        raise err_referential("amendment filing requires an ACTIVE registration for the applicant")
    filed = now()
    is_late = filed > ev["amendment_due_at"]
    f = new_entity()
    f.update({
        "disclosure_event_id": ev["id"],
        "registration_request_id": active_req["id"],
        "filed_at": filed,
        "is_late": is_late,
        "narrative_text": narrative,
        "status": "FILED",
        "_filer_user_id": uid,
    })
    store.amendment_filings[f["id"]] = f
    ev["status"] = "LATE_AMENDED" if is_late else "AMENDED"
    touch(ev)
    return success_obj(serialize(f), 201)


@bp.get("/registration-desk/amendment-filings")
def list_amendments():
    auth(*READ_ROLES)
    page, limit, offset, total = list_page(
        store.amendment_filings,
        (
            ("disclosure_event_id", "disclosure_event_id", str),
            ("registration_request_id", "registration_request_id", str),
            ("status", "status", str),
        ),
    )
    return success_list([serialize(f) for f in page], limit, offset, total)


@bp.get("/registration-desk/amendment-filings/<id>")
def get_amendment(id):
    auth(*READ_ROLES)
    f = get_or_404(store.amendment_filings, id)
    return success_obj(serialize(f), 200)


@bp.post("/registration-desk/amendment-filings/<id>/accept")
def accept_amendment(id):
    uid, _ = auth("ComplianceOfficer")
    f = get_or_404(store.amendment_filings, id)
    if f["status"] != "FILED":
        raise err_invalid_state("only a FILED amendment may be accepted")
    if uid == f["_filer_user_id"]:
        raise err_sod()
    f["status"] = "ACCEPTED"
    touch(f)
    return success_obj(serialize(f), 200)


@bp.post("/registration-desk/amendment-filings/<id>/return")
def return_amendment(id):
    uid, _ = auth("ComplianceOfficer")
    f = get_or_404(store.amendment_filings, id)
    if f["status"] != "FILED":
        raise err_invalid_state("only a FILED amendment may be returned")
    if uid == f["_filer_user_id"]:
        raise err_sod()
    f["status"] = "RETURNED"
    touch(f)
    # The parent event reverts to OPEN; the deadline is recomputed from the
    # original reported_at under the same basis (the 30-day clock does not restart).
    ev = get_or_404(store.disclosure_events, f["disclosure_event_id"])
    ev["status"] = "OPEN"
    ev["amendment_due_at"] = compute_deadline(
        ev.get("_deadline_basis", "CALENDAR"), ev["reported_at"].date(), AMENDMENT_WINDOW_DAYS
    )
    touch(ev)
    return success_obj(serialize(f), 200)
