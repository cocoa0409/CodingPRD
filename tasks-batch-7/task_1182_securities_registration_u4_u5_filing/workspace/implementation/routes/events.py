"""DisclosureEvent endpoints."""
from flask import Blueprint

from db import store
from middleware import auth
from common import (
    body, get_or_404, fk_or_404, required, require_enum, new_entity,
    serialize, list_page,
)
from response import success_obj, success_list
from errors import err_invalid_request, err_temporal
from timeutil import now, today, parse_date
from services import compute_deadline, event_firm_basis, AMENDMENT_WINDOW_DAYS

bp = Blueprint("events", __name__)

READ_ROLES = ("SystemOperator", "ComplianceOfficer", "RegistrationPrincipal", "Regulator")
EVENT_TYPES = {"CRIMINAL_CHARGE", "REGULATORY_ACTION", "BANKRUPTCY", "CIVIL_JUDGMENT", "CUSTOMER_COMPLAINT"}


@bp.post("/registration-desk/disclosure-events")
def create_event():
    auth("RegistrationPrincipal")
    data = body()
    applicant = fk_or_404(store.applicants, data.get("applicant_id"))
    # Priority 9: field shape.
    required(data, "applicant_id")
    etype = require_enum(required(data, "event_type"), EVENT_TYPES, "event_type")
    edate_raw = required(data, "event_date")
    edate = parse_date(edate_raw)
    if edate is None:
        raise err_invalid_request("event_date must be an ISO YYYY-MM-DD date")
    # Priority 10: event_date may not be in the future.
    if edate > today():
        raise err_temporal("event_date may not be in the future")
    reported = now()
    basis = event_firm_basis(applicant["id"])
    ev = new_entity()
    ev.update({
        "applicant_id": applicant["id"],
        "event_type": etype,
        "event_date": edate_raw,
        "reported_at": reported,
        "amendment_due_at": compute_deadline(basis, reported.date(), AMENDMENT_WINDOW_DAYS),
        "status": "OPEN",
        "_deadline_basis": basis,
    })
    store.disclosure_events[ev["id"]] = ev
    return success_obj(serialize(ev), 201)


@bp.get("/registration-desk/disclosure-events")
def list_events():
    auth(*READ_ROLES)
    page, limit, offset, total = list_page(
        store.disclosure_events,
        (
            ("applicant_id", "applicant_id", str),
            ("status", "status", str),
        ),
    )
    return success_list([serialize(e) for e in page], limit, offset, total)


@bp.get("/registration-desk/disclosure-events/<id>")
def get_event(id):
    auth(*READ_ROLES)
    ev = get_or_404(store.disclosure_events, id)
    return success_obj(serialize(ev), 200)
