"""Crews, their support plan and certification, and the picker roster
(PRD §3.2)."""

from flask import Blueprint

import config
import db
import response
import util
import validation as V
from errors import fail
from routes.helpers import CS, FSO, HM, PC, filter_args

bp = Blueprint("crews", __name__)

CREW_FIELDS = [
    V.Field("name", "string", maxlen=80),
    V.Field("labor_program", "string", enum=config.LABOR_PROGRAMS),
    V.Field("supervisor_user_id", "string", maxlen=64),
    V.Field("planned_head_count", "int", minimum=1, maximum=60),
    V.Field("contract_start_date", "date"),
    V.Field("contract_end_date", "date"),
]

SUPPORT_FIELDS = [
    V.Field("housing_unit_code", "string", required=False, nullable=True),
    V.Field("beds_confirmed", "int", minimum=0),
    V.Field("transport_route_code", "string", required=False, nullable=True),
    V.Field("vehicle_seats", "int", minimum=0),
]

PICKER_FIELDS = [
    V.Field("crew_id", "string"),
    V.Field("full_name", "string", maxlen=80),
    V.Field("hygiene_training_on", "date", required=False, nullable=True),
]

HYGIENE_FIELDS = [V.Field("hygiene_training_on", "date")]


def recompute_support_plan(crew):
    """PRD §3.2: transport for everyone, housing as well for an H2A crew."""
    head = int(crew["planned_head_count"])
    complete = (
        crew["transport_route_code"] is not None
        and int(crew["vehicle_seats"]) >= head
    )
    if crew["labor_program"] == "H2A":
        complete = (
            complete
            and crew["housing_unit_code"] is not None
            and int(crew["beds_confirmed"]) >= head
        )
    crew["support_plan_complete"] = bool(complete)
    return crew["support_plan_complete"]


def recompute_picker_count(crew):
    crew["picker_count"] = len(db.pickers_of_crew(crew["id"]))
    return crew["picker_count"]


def expiry_of(training_date):
    if training_date is None:
        return None
    return util.add_days(training_date, config.HYGIENE_VALID_DAYS)


# ---------------------------------------------------------------------------
# crews
# ---------------------------------------------------------------------------
@bp.route("/crews", methods=["POST"])
def create_crew():
    V.authenticate((HM,))
    body = V.read_body()
    V.validate_body(CREW_FIELDS, body)
    start = V.tolerant("date", body.get("contract_start_date"))
    end = V.tolerant("date", body.get("contract_end_date"))
    if start is not None and end is not None and end < start:
        fail(
            "ERR_INVALID_DATE_RANGE",
            "contract_end_date must be on or after contract_start_date.",
        )
    parsed = V.parse_temporal(CREW_FIELDS, body)

    rec = db.new_record()
    rec["name"] = body["name"]
    rec["labor_program"] = body["labor_program"]
    rec["supervisor_user_id"] = body["supervisor_user_id"]
    rec["planned_head_count"] = int(body["planned_head_count"])
    rec["contract_start_date"] = body["contract_start_date"]
    rec["contract_end_date"] = body["contract_end_date"]
    rec["housing_unit_code"] = None
    rec["beds_confirmed"] = 0
    rec["transport_route_code"] = None
    rec["vehicle_seats"] = 0
    rec["support_plan_complete"] = False
    rec["picker_count"] = 0
    rec["status"] = "RECRUITING"
    rec["accrued_wage_cents"] = 0
    rec["settled_wage_cents"] = 0
    rec["reconciliation_delta_cents"] = 0
    rec["_contract_start_date"] = parsed["contract_start_date"]
    rec["_contract_end_date"] = parsed["contract_end_date"]
    db.crews[rec["id"]] = rec
    return response.object_response(rec, 201)


@bp.route("/crews/<crew_id>", methods=["GET"])
def read_crew(crew_id):
    V.authenticate((HM, CS, PC, FSO))
    return response.object_response(V.get_crew(crew_id))


@bp.route("/crews", methods=["GET"])
def list_crews():
    V.authenticate((HM, CS, PC, FSO))
    rows = filter_args(
        db.all_of(db.crews), {"labor_program": "labor_program", "status": "status"}
    )
    return response.paginate(rows)


@bp.route("/crews/<crew_id>/support-plan", methods=["POST"])
def support_plan(crew_id):
    V.authenticate((HM,))
    crew = V.get_crew(crew_id)
    body = V.read_body()
    V.validate_body(SUPPORT_FIELDS, body)
    if crew["status"] not in ("RECRUITING", "STAFFED"):
        fail(
            "ERR_INVALID_CREW_STATE",
            "Housing and transport cannot be re-cut after certification.",
        )
    crew["housing_unit_code"] = body.get("housing_unit_code")
    crew["beds_confirmed"] = int(body["beds_confirmed"])
    crew["transport_route_code"] = body.get("transport_route_code")
    crew["vehicle_seats"] = int(body["vehicle_seats"])
    recompute_support_plan(crew)
    db.touch(crew)
    return response.object_response(crew)


@bp.route("/crews/<crew_id>/certify", methods=["POST"])
def certify_crew(crew_id):
    V.authenticate((HM,))
    crew = V.get_crew(crew_id)
    if crew["status"] != "STAFFED":
        fail("ERR_INVALID_CREW_STATE", "Only a STAFFED crew may be certified.")
    today = db.clock_date()
    for picker in db.pickers_of_crew(crew["id"]):
        expires = picker.get("_hygiene_training_expires_on")
        if expires is None or expires <= today:
            fail(
                "ERR_HYGIENE_TRAINING_INVALID",
                "Every picker needs unexpired worker-hygiene training.",
            )
    if not crew["support_plan_complete"]:
        fail("ERR_SUPPORT_PLAN_INCOMPLETE")
    crew["status"] = "CERTIFIED"
    db.touch(crew)
    return response.object_response(crew)


@bp.route("/crews/<crew_id>/release", methods=["POST"])
def release_crew(crew_id):
    V.authenticate((HM,))
    crew = V.get_crew(crew_id)
    if crew["status"] not in ("CERTIFIED", "ACTIVE"):
        fail("ERR_INVALID_CREW_STATE", "Only a CERTIFIED or ACTIVE crew may be released.")
    for window in db.windows_of_crew(crew["id"]):
        if window["status"] in ("CONFIRMED", "OPEN", "SUSPENDED"):
            fail("ERR_CREW_LEDGER_NOT_CLEAR", "The crew still holds a live window.")
    for session in db.sessions_of_crew(crew["id"]):
        if session["status"] in ("OPEN", "TALLIED", "DISPUTED"):
            fail(
                "ERR_CREW_LEDGER_NOT_CLEAR", "The crew still holds an unresolved session."
            )
    if int(crew["accrued_wage_cents"]) != 0:
        fail("ERR_CREW_LEDGER_NOT_CLEAR", "The crew still holds accrued wages.")
    crew["status"] = "RELEASED"
    db.touch(crew)
    return response.object_response(crew)


# ---------------------------------------------------------------------------
# pickers
# ---------------------------------------------------------------------------
@bp.route("/pickers", methods=["POST"])
def create_picker():
    V.authenticate((HM, CS))
    body = V.read_body()
    V.validate_body(PICKER_FIELDS, body)
    parsed = V.parse_temporal(PICKER_FIELDS, body)
    crew = V.get_crew(body["crew_id"])

    training = parsed.get("hygiene_training_on")
    expires = expiry_of(training)
    rec = db.new_record()
    rec["crew_id"] = crew["id"]
    rec["full_name"] = body["full_name"]
    rec["hygiene_training_on"] = body.get("hygiene_training_on")
    rec["labor_program"] = crew["labor_program"]
    rec["hygiene_training_expires_on"] = util.date_str(expires)
    rec["total_clamshells_lifetime"] = 0
    rec["total_hours_lifetime"] = util.q2(0)
    rec["avg_lbs_per_hour"] = util.q2(0)
    rec["_hygiene_training_on"] = training
    rec["_hygiene_training_expires_on"] = expires
    db.pickers[rec["id"]] = rec

    before = int(crew["picker_count"])
    recompute_picker_count(crew)
    if before == 0 and crew["picker_count"] > 0 and crew["status"] == "RECRUITING":
        crew["status"] = "STAFFED"
    db.touch(crew)
    return response.object_response(rec, 201)


@bp.route("/pickers/<picker_id>", methods=["GET"])
def read_picker(picker_id):
    V.authenticate((HM, CS, PC, config.ROLE_PICKER))
    return response.object_response(V.get_picker(picker_id))


@bp.route("/pickers", methods=["GET"])
def list_pickers():
    V.authenticate((HM, CS, PC))
    rows = filter_args(db.all_of(db.pickers), {"crew_id": "crew_id"})
    return response.paginate(rows)


@bp.route("/pickers/<picker_id>/hygiene-training", methods=["POST"])
def record_hygiene(picker_id):
    V.authenticate((HM, CS))
    picker = V.get_picker(picker_id)
    body = V.read_body()
    V.check_shape(HYGIENE_FIELDS, body)
    parsed = V.parse_temporal(HYGIENE_FIELDS, body)
    training = parsed["hygiene_training_on"]
    expires = expiry_of(training)
    picker["hygiene_training_on"] = body["hygiene_training_on"]
    picker["hygiene_training_expires_on"] = util.date_str(expires)
    picker["_hygiene_training_on"] = training
    picker["_hygiene_training_expires_on"] = expires
    db.touch(picker)
    return response.object_response(picker)
