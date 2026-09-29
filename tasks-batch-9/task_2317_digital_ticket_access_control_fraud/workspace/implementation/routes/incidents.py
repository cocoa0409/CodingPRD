"""DeniedEntryIncident endpoints (PRD 3.8)."""

from flask import Blueprint

from db import db, public, sort_created_asc, touch
from errors import ApiError
from middleware import auth, f_str, get_body, q
from response import ok
from services import calc
from services.domain import append_audit, get_or_404, recompute_fraud_score
from routes._common import filter_eq, paginated

bp = Blueprint("incidents", __name__)

INCIDENT_READERS = ("BoxOfficeAgent", "SecurityInvestigator", "VenueAdmin")


@bp.route("/denied-entry-incidents/<incident_id>", methods=["GET"])
def get_incident(incident_id):
    auth(INCIDENT_READERS)
    incident = get_or_404(db.incidents, incident_id, "ERR_INCIDENT_NOT_FOUND")
    return ok(public(incident))


@bp.route("/denied-entry-incidents", methods=["GET"])
def list_incidents():
    auth(INCIDENT_READERS)
    rows = sort_created_asc(list(db.incidents.values()))
    rows = filter_eq(rows, "scan_event_id", q("scan_event_id"))
    rows = filter_eq(rows, "ticket_id", q("ticket_id"))
    rows = filter_eq(rows, "patron_id", q("patron_id"))
    rows = filter_eq(rows, "category", q("category"))
    rows = filter_eq(rows, "status", q("status"))
    return paginated(rows)


@bp.route("/denied-entry-incidents/<incident_id>/start-review", methods=["POST"])
def start_review(incident_id):
    user_id, _role = auth(("SecurityInvestigator",))
    incident = get_or_404(db.incidents, incident_id, "ERR_INCIDENT_NOT_FOUND")
    if incident["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Only an OPEN incident may be taken for review.")
    incident["status"] = "UNDER_REVIEW"
    incident["reviewer_user_id"] = user_id
    touch(incident)
    return ok(public(incident))


@bp.route("/denied-entry-incidents/<incident_id>/remediate", methods=["POST"])
def remediate(incident_id):
    user_id, role = auth(("SecurityInvestigator",))
    body = get_body()
    resolution_note = f_str(body, "resolution_note", allow_empty=False)
    incident = get_or_404(db.incidents, incident_id, "ERR_INCIDENT_NOT_FOUND")
    if incident["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Only an UNDER_REVIEW incident may be remediated.")
    if not incident["ticket_id"]:
        raise ApiError(
            "ERR_INVALID_STATE",
            "The incident carries no ticket, so no goodwill credit can be granted.",
        )

    ticket = db.tickets[incident["ticket_id"]]
    event = db.events[ticket["event_id"]]
    patron = db.patrons.get(incident["patron_id"])
    credit = calc.denied_entry_remediation_credit(ticket, patron)
    if event["settlement_pool_cents"] < credit:
        raise ApiError("ERR_SETTLEMENT_POOL_INSUFFICIENT")

    incident["status"] = "REMEDIATED"
    incident["resolution_note"] = resolution_note
    incident["remediation_credit_cents"] = credit
    touch(incident)

    if patron is not None:
        patron["remediation_credit_cents"] += credit
        recompute_fraud_score(patron, "ADJUDICATED")
        touch(patron)

    event["settlement_pool_cents"] -= credit
    touch(event)

    append_audit(
        event["id"], "DENIED_ENTRY_INCIDENT", incident["id"], "DENIED_ENTRY_REMEDIATED",
        role, user_id,
        "Incident %s (%s) remediated for %d cents from the settlement pool: %s"
        % (incident["id"], incident["category"], credit, resolution_note),
    )
    return ok(public(incident))


@bp.route("/denied-entry-incidents/<incident_id>/dismiss", methods=["POST"])
def dismiss(incident_id):
    user_id, role = auth(("SecurityInvestigator",))
    body = get_body()
    resolution_note = f_str(body, "resolution_note", allow_empty=False)
    incident = get_or_404(db.incidents, incident_id, "ERR_INCIDENT_NOT_FOUND")
    if incident["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Only an UNDER_REVIEW incident may be dismissed.")

    incident["status"] = "DISMISSED"
    incident["resolution_note"] = resolution_note
    touch(incident)

    patron = db.patrons.get(incident["patron_id"])
    if patron is not None:
        patron["strike_count"] = max(patron["strike_count"] - 1, 0)
        recompute_fraud_score(patron, "ADJUDICATED")
        touch(patron)

    append_audit(
        incident["_event_id"], "DENIED_ENTRY_INCIDENT", incident["id"],
        "DENIED_ENTRY_DISMISSED", role, user_id,
        "Incident %s (%s) dismissed with no credit; the strike was withdrawn: %s"
        % (incident["id"], incident["category"], resolution_note),
    )
    return ok(public(incident))
