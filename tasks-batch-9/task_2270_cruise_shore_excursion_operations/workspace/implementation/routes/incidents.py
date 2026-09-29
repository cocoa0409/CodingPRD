"""Guest incident reports and the opening of liability claims."""

from flask import Blueprint

from db import db
from errors import fail
from middleware import DESK, MANAGER, RISK, endpoint
from response import list_response, object_response
from routes import API_PREFIX
from serializers import claim_json, incident_json
from validation import (f, incident_or_404, paginate, pagination, query_values,
                        validate_body)

bp = Blueprint("incidents", __name__)

INCIDENT_STATUSES = ("FILED", "CLAIM_OPENED", "CLOSED_NO_CLAIM", "CLOSED_UPHELD", "CLOSED_DENIED")
INCIDENT_SEVERITIES = ("MINOR", "MODERATE", "SEVERE")
BASIS_CODES = ("NEGLIGENCE", "EQUIPMENT_FAILURE", "GUIDE_CONDUCT", "ROUTE_DEVIATION",
               "MEDICAL_RESPONSE")

READ_ROLES = (DESK, RISK, MANAGER)

CLAIM_OPEN = [
    f("claimed_amount_cents", "int", required=True, lo=1),
    f("basis_code", "enum", required=True, enum=BASIS_CODES),
]

INCIDENT_CLOSE = [
    f("resolution_note", "string"),
]


def claim_of_incident(incident_id):
    for claim in db.claims.values():
        if claim["incident_id"] == incident_id:
            return claim
    return None


@bp.get(API_PREFIX + "/incidents/<incident_id>")
@endpoint(*READ_ROLES)
def read_incident(caller, incident_id):
    return object_response(incident_json(incident_or_404(incident_id)))


@bp.get(API_PREFIX + "/incidents")
@endpoint(*READ_ROLES)
def list_incidents(caller):
    limit, offset = pagination()
    filters = query_values([
        f("booking_id", "string"),
        f("status", "enum", enum=INCIDENT_STATUSES),
        f("severity", "enum", enum=INCIDENT_SEVERITIES),
    ])
    rows = db.ordered("incidents")
    for key in ("booking_id", "status", "severity"):
        if key in filters:
            rows = [r for r in rows if r[key] == filters[key]]
    page, total = paginate(rows, limit, offset)
    return list_response([incident_json(r) for r in page], limit, offset, total)


@bp.post(API_PREFIX + "/incidents/<incident_id>/claims")
@endpoint(RISK)
def open_claim(caller, incident_id):
    body = validate_body(CLAIM_OPEN)
    incident = incident_or_404(incident_id)

    if incident["status"] != "FILED" or claim_of_incident(incident["id"]) is not None:
        fail("ERR_INVALID_CLAIM_ACTION", "a claim may only be opened on an unclaimed FILED incident")

    booking = db.bookings.get(incident["booking_id"])
    departure = db.departures.get(booking["departure_id"]) if booking else None
    excursion = db.excursions.get(departure["excursion_id"]) if departure else None

    row = db.insert("claims", {
        "incident_id": incident["id"],
        "operator_id": excursion["operator_id"] if excursion else None,
        "port_call_id": departure["port_call_id"] if departure else None,
        "claimed_amount_cents": body["claimed_amount_cents"],
        "basis_code": body["basis_code"],
        "status": "SUBMITTED",
        "dispute_round_count": 0,
        "liability_share_bps": 0,
        "settlement_amount_cents": 0,
        "operator_charge_cents": 0,
        "submitted_by_user_id": caller.user_id,
        "adjudicated_by_user_id": None,
    })

    incident["status"] = "CLAIM_OPENED"
    db.touch(incident)
    return object_response(claim_json(row), 201)


@bp.post(API_PREFIX + "/incidents/<incident_id>/close")
@endpoint(RISK)
def close_incident(caller, incident_id):
    validate_body(INCIDENT_CLOSE)
    incident = incident_or_404(incident_id)
    if incident["status"] != "FILED" or claim_of_incident(incident["id"]) is not None:
        fail("ERR_INVALID_CLAIM_ACTION",
             "only a FILED incident without a claim may be closed without one")
    incident["status"] = "CLOSED_NO_CLAIM"
    db.touch(incident)
    return object_response(incident_json(incident))
