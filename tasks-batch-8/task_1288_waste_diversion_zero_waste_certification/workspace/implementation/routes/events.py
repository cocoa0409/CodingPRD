"""ContaminationEvent endpoints and the corrective-training lifecycle."""

from flask import Blueprint

from db import base_record, store, touch
from errors import (
    ApiError,
    ERR_CROSS_SITE_REFERENCE,
    ERR_INVALID_STATE,
    not_found,
)
from middleware import (
    no_input,
    ALL_ROLES,
    authenticate,
    check_unknown,
    f_bool,
    f_date,
    f_enum,
    f_pct,
    f_str,
    get_body,
)
from response import success_list, success_object
from services.calc import severity_of
from services.lifecycle import (
    pub_event,
    rederive_standing,
    reject_ticket,
    void_ticket,
)
from util import (
    EVENT_STATUSES,
    MATERIAL_STREAMS,
    apply_filters,
    paginate,
    sort_items,
)

bp = Blueprint("events", __name__)


def _get_event(event_id):
    e = store.events.get(event_id)
    if e is None:
        raise not_found("Contamination event not found")
    return e


@bp.route("/contamination_events", methods=["POST"])
def create_event():
    authenticate(["WasteAuditor"])
    b = get_body()
    check_unknown(b, ["site_id", "event_date", "material_stream",
                      "contamination_pct", "ticket_id", "audit_id"])
    site_id = f_str(b, "site_id")
    event_date = f_date(b, "event_date")
    stream = f_enum(b, "material_stream", MATERIAL_STREAMS)
    pct = f_pct(b, "contamination_pct")
    ticket_id = f_str(b, "ticket_id", required=False, nullable=True)
    audit_id = f_str(b, "audit_id", required=False, nullable=True)

    if site_id not in store.sites:
        raise not_found("Site not found")
    ticket = None
    if ticket_id is not None:
        ticket = store.tickets.get(ticket_id)
        if ticket is None:
            raise not_found("Ticket not found")
    if audit_id is not None and audit_id not in store.audits:
        raise not_found("Audit not found")

    # FK scope: a linked ticket must belong to the event's site.
    if ticket is not None and ticket["site_id"] != site_id:
        raise ApiError(ERR_CROSS_SITE_REFERENCE, 422,
                       "ticket_id belongs to another site")

    severity = severity_of(pct)
    rec = base_record({
        "site_id": site_id,
        "ticket_id": ticket_id,
        "audit_id": audit_id,
        "event_date": event_date,
        "material_stream": stream,
        "contamination_pct": pct,
        "severity": severity,
        "status": "OPEN",
        "trainee_name": None,
        "training_due_date": None,
        "dismiss_reason": None,
    })
    store.events[rec["id"]] = rec

    # A CRITICAL event has teeth: void a linked VALIDATED ticket on the spot,
    # reject a linked PENDING one.
    if severity == "CRITICAL" and ticket is not None:
        if ticket["validation_status"] == "VALIDATED":
            void_ticket(ticket)
        elif ticket["validation_status"] == "PENDING":
            reject_ticket(ticket, None)

    rederive_standing(site_id)
    return success_object(pub_event(rec), 201)


@bp.route("/contamination_events/<event_id>", methods=["GET"])
def get_event(event_id):
    authenticate(ALL_ROLES)
    return success_object(pub_event(_get_event(event_id)))


@bp.route("/contamination_events", methods=["GET"])
def list_events():
    authenticate(ALL_ROLES)
    items = apply_filters(store.events.values(), [
        ("site_id", "site_id", None),
        ("ticket_id", "ticket_id", None),
        ("audit_id", "audit_id", None),
        ("status", "status", EVENT_STATUSES),
    ])
    page, meta = paginate(sort_items(items))
    return success_list([pub_event(e) for e in page], meta)


@bp.route("/contamination_events/<event_id>/assign_training", methods=["POST"])
def assign_training(event_id):
    authenticate(["WasteAuditor"])
    b = get_body()
    check_unknown(b, ["trainee_name", "training_due_date"])
    trainee = f_str(b, "trainee_name")
    due = f_date(b, "training_due_date")
    e = _get_event(event_id)
    if e["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Event is not OPEN")
    e["trainee_name"] = trainee
    e["training_due_date"] = due
    e["status"] = "TRAINING_ASSIGNED"
    touch(e)
    rederive_standing(e["site_id"])
    return success_object(pub_event(e))


@bp.route("/contamination_events/<event_id>/complete_training", methods=["POST"])
def complete_training(event_id):
    authenticate(["WasteAuditor"])
    no_input(get_body())
    e = _get_event(event_id)
    if e["status"] != "TRAINING_ASSIGNED":
        raise ApiError(ERR_INVALID_STATE, 409, "Event is not TRAINING_ASSIGNED")
    e["status"] = "TRAINING_COMPLETED"
    touch(e)
    rederive_standing(e["site_id"])
    return success_object(pub_event(e))


@bp.route("/contamination_events/<event_id>/verify", methods=["POST"])
def verify_event(event_id):
    authenticate(["WasteAuditor"])
    b = get_body()
    check_unknown(b, ["passed"])
    passed = f_bool(b, "passed")
    e = _get_event(event_id)
    if e["status"] != "TRAINING_COMPLETED":
        raise ApiError(ERR_INVALID_STATE, 409, "Event is not TRAINING_COMPLETED")
    if passed:
        e["status"] = "VERIFIED_CLOSED"
    else:
        # Loop restarts: back to OPEN with training fields cleared.
        e["status"] = "OPEN"
        e["trainee_name"] = None
        e["training_due_date"] = None
    touch(e)
    rederive_standing(e["site_id"])
    return success_object(pub_event(e))


@bp.route("/contamination_events/<event_id>/dismiss", methods=["POST"])
def dismiss_event(event_id):
    authenticate(["WasteAuditor"])
    b = get_body()
    check_unknown(b, ["reason"])
    reason = f_str(b, "reason")
    e = _get_event(event_id)
    if e["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Event is not OPEN")
    e["status"] = "DISMISSED"
    e["dismiss_reason"] = reason
    touch(e)
    rederive_standing(e["site_id"])
    return success_object(pub_event(e))
