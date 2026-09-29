"""Logical clock + Disaster endpoints."""
from flask import Blueprint

from db import db, format_instant, new_row, parse_instant, setf, touch
from errors import fail
from middleware import ALL_ROLES, authenticate
from response import ok
from routes.common import PREFIX, render_list, require, respond
from services.calc import dec
from services.constants import (
    ALLOWED_FEDERAL_COST_SHARE_PCT,
    DEFAULT_FEDERAL_COST_SHARE_PCT,
    DEFAULT_SMALL_PROJECT_THRESHOLD_CENTS,
    INCIDENT_TYPES,
)
from services.ledger import projects_of_applicant
from validate import STATE_CODE_RE, body, present, v_enum, v_instant, v_int, v_num, v_str

bp = Blueprint("disasters", __name__)


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------

@bp.route(PREFIX + "/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate(("PlatformAdmin",))
    payload = body()
    raw = v_instant(payload, "to_iso8601")
    db.clock = parse_instant(raw)
    return ok({"current_utc": format_instant(db.clock)})


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _overlaps(state_code, incident_type, start, end, exclude_id=None):
    for other in db.disasters.values():
        if other["id"] == exclude_id:
            continue
        if other["state_code"] != state_code or other["incident_type"] != incident_type:
            continue
        other_start = parse_instant(other["incident_start_at"])
        other_end = parse_instant(other["incident_end_at"])
        if other_start is None or other_end is None:
            continue
        # half-open [start, end) collision
        if start < other_end and other_start < end:
            return True
    return False


def applicants_of_disaster(disaster_id):
    return [a for a in db.applicants.values() if a["disaster_id"] == disaster_id]


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------

@bp.route(PREFIX + "/disasters", methods=["POST"])
def create_disaster():
    authenticate(("PlatformAdmin",))
    payload = body()

    declaration_number = v_str(payload, "declaration_number")
    state_code = v_str(payload, "state_code")
    if not STATE_CODE_RE.match(state_code):
        fail("ERR_INVALID_REQUEST", "state_code must be exactly 2 uppercase letters")
    incident_type = v_enum(payload, "incident_type", INCIDENT_TYPES)
    incident_start_at = v_instant(payload, "incident_start_at")
    incident_end_at = v_instant(payload, "incident_end_at")
    population = v_int(payload, "population", minimum=1)
    if present(payload, "federal_cost_share_pct"):
        pct = v_num(payload, "federal_cost_share_pct")
        if str(dec(pct).quantize(dec("0.01"))) not in ALLOWED_FEDERAL_COST_SHARE_PCT:
            fail("ERR_INVALID_REQUEST",
                 "federal_cost_share_pct must be one of 0.75, 0.90, 1.00")
    else:
        pct = DEFAULT_FEDERAL_COST_SHARE_PCT
    threshold = v_int(payload, "small_project_threshold_cents", required=False,
                      default=DEFAULT_SMALL_PROJECT_THRESHOLD_CENTS, minimum=1)

    start = parse_instant(incident_start_at)
    end = parse_instant(incident_end_at)
    if end <= start:
        fail("ERR_INCIDENT_PERIOD_INVALID",
             "incident_end_at must be strictly after incident_start_at")

    for other in db.disasters.values():
        if other["declaration_number"] == declaration_number:
            fail("ERR_DECLARATION_NUMBER_DUPLICATE",
                 "declaration_number already exists")

    if _overlaps(state_code, incident_type, start, end):
        fail("ERR_INCIDENT_PERIOD_OVERLAP",
             "incident period collides with another declaration")

    row = new_row("disasters", {
        "declaration_number": declaration_number,
        "state_code": state_code,
        "incident_type": incident_type,
        "incident_start_at": incident_start_at,
        "incident_end_at": incident_end_at,
        "population": population,
        "federal_cost_share_pct": pct,
        "small_project_threshold_cents": threshold,
        "status": "DECLARED",
        "total_validated_loss_cents": 0,
        "per_capita_impact_cents": 0,
        "indicator_met": False,
        "total_obligated_cents": 0,
        "total_drawn_cents": 0,
        "enhanced_monitoring_applicant_count": 0,
        "suspended_applicant_count": 0,
    })
    return respond(row, 201)


@bp.route(PREFIX + "/disasters", methods=["GET"])
def list_disasters():
    authenticate(ALL_ROLES)
    return render_list("disasters", {
        "state_code": "state_code",
        "incident_type": "incident_type",
        "status": "status",
    })


@bp.route(PREFIX + "/disasters/<disaster_id>", methods=["GET"])
def get_disaster(disaster_id):
    authenticate(ALL_ROLES)
    row = require("disasters", disaster_id)
    return respond(row)


@bp.route(PREFIX + "/disasters/<disaster_id>/incident-period", methods=["PATCH"])
def amend_incident_period(disaster_id):
    authenticate(("PlatformAdmin",))
    disaster = require("disasters", disaster_id)
    payload = body()
    incident_end_at = v_instant(payload, "incident_end_at")

    if disaster["status"] != "DECLARED":
        fail("ERR_DISASTER_INVALID_STATE",
             "incident period may only be amended while DECLARED")

    new_end = parse_instant(incident_end_at)
    current_end = parse_instant(disaster["incident_end_at"])
    if new_end <= current_end:
        fail("ERR_INCIDENT_PERIOD_INVALID",
             "incident_end_at must move strictly forward")

    start = parse_instant(disaster["incident_start_at"])
    if _overlaps(disaster["state_code"], disaster["incident_type"], start, new_end,
                 exclude_id=disaster["id"]):
        fail("ERR_INCIDENT_PERIOD_OVERLAP",
             "extended incident period collides with another declaration")

    setf(disaster, "incident_end_at", incident_end_at)
    touch(disaster)
    return respond(disaster)


@bp.route(PREFIX + "/disasters/<disaster_id>/close-obligations", methods=["POST"])
def close_obligations(disaster_id):
    authenticate(("PlatformAdmin",))
    disaster = require("disasters", disaster_id)

    if disaster["status"] != "DECLARED":
        fail("ERR_DISASTER_INVALID_STATE", "declaration is already OBLIGATION_CLOSED")

    for applicant in applicants_of_disaster(disaster["id"]):
        for project in projects_of_applicant(applicant["id"]):
            if project["status"] in ("UNDER_REVIEW", "RFI_ISSUED"):
                fail("ERR_PROJECT_REVIEWS_OPEN",
                     "a project under this declaration is still in review")

    setf(disaster, "status", "OBLIGATION_CLOSED")
    touch(disaster)
    return respond(disaster)
