"""Pick sessions and pay periods (PRD §3.4, §3.5)."""

from flask import Blueprint

import config
import db
import response
import util
import validation as V
from errors import fail
from routes.helpers import CS, HM, PC, PICKER, filter_args
from services import calc

bp = Blueprint("sessions", __name__)

SESSION_READERS = (HM, CS, PC, PICKER)

SESSION_FIELDS = [
    V.Field("harvest_window_id", "string"),
    V.Field("picker_id", "string"),
    V.Field("work_date", "date"),
]

TALLY_FIELDS = [
    V.Field("hours_worked", "number", exclusive_min=0, maximum=16),
    V.Field("clamshells_filled", "int", minimum=0),
    V.Field("culled_clamshells", "int", minimum=0),
]

DISPUTE_FIELDS = [V.Field("dispute_reason_code", "string")]

RUN_FIELDS = [
    V.Field("crew_id", "string"),
    V.Field("period_start_date", "date"),
    V.Field("period_end_date", "date"),
]


@bp.route("/pick-sessions", methods=["POST"])
def create_session():
    user_id, _ = V.authenticate((CS,))
    body = V.read_body()
    V.validate_body(SESSION_FIELDS, body)
    parsed = V.parse_temporal(SESSION_FIELDS, body)
    picker = V.get_picker(body["picker_id"])
    window = V.get_window(body["harvest_window_id"])

    crew = db.crews.get(window["crew_id"])
    supervisor = crew["supervisor_user_id"] if crew else None
    if user_id != supervisor or picker["crew_id"] != window["crew_id"]:
        fail("ERR_NOT_SESSION_SUPERVISOR")
    if window["status"] != "OPEN":
        fail("ERR_WINDOW_NOT_OPEN")

    work_date = parsed["work_date"]
    expires = picker.get("_hygiene_training_expires_on")
    if expires is None or expires <= work_date:
        fail(
            "ERR_HYGIENE_TRAINING_INVALID",
            "The picker's hygiene training is missing or expired on the work date.",
        )
    for other in db.sessions_of_window(window["id"]):
        if other["picker_id"] == picker["id"] and other["_work_date"] == work_date:
            fail("ERR_DUPLICATE_RECORD", "That picker already has a session that day.")
    if not (
        window["_start_at"].date() <= work_date <= window["_end_at"].date()
    ):
        fail("ERR_WORK_DATE_OUTSIDE_WINDOW")

    rec = db.new_record()
    rec["harvest_window_id"] = window["id"]
    rec["picker_id"] = picker["id"]
    rec["payroll_run_id"] = None
    rec["work_date"] = body["work_date"]
    rec["hours_worked"] = util.q2(0)
    rec["clamshells_filled"] = 0
    rec["culled_clamshells"] = 0
    rec["cull_rate"] = None
    rec["quality_flag"] = "PENDING"
    rec["effective_piece_rate_cents"] = 0
    rec["piece_cents"] = 0
    rec["guarantee_floor_cents"] = 0
    rec["makeup_cents"] = 0
    rec["gross_cents"] = 0
    rec["housing_deduction_cents"] = 0
    rec["net_cents"] = 0
    rec["tally_revision_count"] = 0
    rec["tallied_by_user_id"] = None
    rec["approved_by_user_id"] = None
    rec["dispute_reason_code"] = None
    rec["void_reason_code"] = None
    rec["status"] = "OPEN"
    rec["_work_date"] = work_date
    db.pick_sessions[rec["id"]] = rec
    return response.object_response(rec, 201)


@bp.route("/pick-sessions/<pick_session_id>", methods=["GET"])
def read_session(pick_session_id):
    user_id, role = V.authenticate(SESSION_READERS, resolve_picker=True)
    session = V.get_session(pick_session_id)
    if role == PICKER and session["picker_id"] != user_id:
        fail("ERR_NOT_SESSION_OWNER")
    return response.object_response(session)


@bp.route("/pick-sessions", methods=["GET"])
def list_sessions():
    user_id, role = V.authenticate(SESSION_READERS, resolve_picker=True)
    rows = db.all_of(db.pick_sessions)
    if role == PICKER:
        rows = [r for r in rows if r["picker_id"] == user_id]
    rows = filter_args(
        rows,
        {
            "harvest_window_id": "harvest_window_id",
            "picker_id": "picker_id",
            "payroll_run_id": "payroll_run_id",
            "status": "status",
        },
    )
    return response.paginate(rows)


@bp.route("/pick-sessions/<pick_session_id>/tally", methods=["POST"])
def tally_session(pick_session_id):
    user_id, _ = V.authenticate((CS,))
    session = V.get_session(pick_session_id)
    body = V.read_body()
    V.validate_body(TALLY_FIELDS, body)
    if int(body["culled_clamshells"]) > int(body["clamshells_filled"]):
        fail("ERR_CULL_EXCEEDS_TALLY")

    window = db.harvest_windows[session["harvest_window_id"]]
    crew = db.crews[window["crew_id"]]
    if user_id != crew["supervisor_user_id"]:
        fail("ERR_NOT_SESSION_SUPERVISOR")
    if window["status"] != "OPEN":
        fail("ERR_WINDOW_NOT_OPEN")
    prior = session["status"]
    if prior not in ("OPEN", "DISPUTED"):
        fail("ERR_INVALID_SESSION_STATE", "A tally is admitted from OPEN or DISPUTED.")
    if prior == "DISPUTED":
        if int(session["tally_revision_count"]) >= config.MAX_TALLY_REVISIONS:
            fail("ERR_TALLY_REVISION_LIMIT")

    session["hours_worked"] = util.q2(body["hours_worked"])
    session["clamshells_filled"] = int(body["clamshells_filled"])
    session["culled_clamshells"] = int(body["culled_clamshells"])
    if prior == "DISPUTED":
        session["tally_revision_count"] = int(session["tally_revision_count"]) + 1
        session["dispute_reason_code"] = None
    calc.price_session(session, window, crew)
    session["tallied_by_user_id"] = user_id
    session["status"] = "TALLIED"
    db.touch(session)
    return response.object_response(session)


@bp.route("/pick-sessions/<pick_session_id>/approve", methods=["POST"])
def approve_session(pick_session_id):
    user_id, _ = V.authenticate((PC,))
    session = V.get_session(pick_session_id)
    if session["quality_flag"] == "PENDING":
        fail("ERR_SESSION_NOT_TALLIED")
    if session["status"] != "TALLIED":
        fail("ERR_INVALID_SESSION_STATE", "Only a TALLIED session may be approved.")
    if user_id == session["tallied_by_user_id"]:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The operator who tallied a session may not approve it.",
        )

    window = db.harvest_windows[session["harvest_window_id"]]
    crew = db.crews[window["crew_id"]]
    picker = db.pickers[session["picker_id"]]
    session["approved_by_user_id"] = user_id
    session["status"] = "APPROVED"
    calc.accrue(crew, session["net_cents"])
    calc.recompute_picker_productivity(picker)
    calc.recompute_window_harvested(window)
    db.touch(session)
    db.touch(crew)
    db.touch(picker)
    db.touch(window)
    return response.object_response(session)


@bp.route("/pick-sessions/<pick_session_id>/dispute", methods=["POST"])
def dispute_session(pick_session_id):
    user_id, role = V.authenticate((PICKER, CS), resolve_picker=True)
    session = V.get_session(pick_session_id)
    body = V.read_body()
    V.check_shape(DISPUTE_FIELDS, body)

    window = db.harvest_windows[session["harvest_window_id"]]
    crew = db.crews[window["crew_id"]]
    if role == PICKER:
        if session["picker_id"] != user_id:
            fail("ERR_NOT_SESSION_OWNER")
    else:
        if user_id != crew["supervisor_user_id"]:
            fail("ERR_NOT_SESSION_SUPERVISOR")
    if window["status"] != "OPEN":
        fail("ERR_WINDOW_NOT_OPEN")
    prior = session["status"]
    if prior not in ("TALLIED", "APPROVED"):
        fail("ERR_INVALID_SESSION_STATE", "A dispute is admitted from TALLIED or APPROVED.")
    if session["payroll_run_id"] is not None:
        fail("ERR_SESSION_PAYROLL_LOCKED")

    session["dispute_reason_code"] = body["dispute_reason_code"]
    session["status"] = "DISPUTED"
    db.touch(session)
    if prior == "APPROVED":
        picker = db.pickers[session["picker_id"]]
        calc.reverse_accrual(crew, session["net_cents"])
        session["approved_by_user_id"] = None
        calc.recompute_picker_productivity(picker)
        calc.recompute_window_harvested(window)
        db.touch(crew)
        db.touch(picker)
        db.touch(window)
    return response.object_response(session)


# ---------------------------------------------------------------------------
# payroll runs
# ---------------------------------------------------------------------------
@bp.route("/payroll-runs", methods=["POST"])
def create_run():
    V.authenticate((PC,))
    body = V.read_body()
    V.validate_body(RUN_FIELDS, body)
    start = V.tolerant("date", body.get("period_start_date"))
    end = V.tolerant("date", body.get("period_end_date"))
    if start is not None and end is not None and end < start:
        fail(
            "ERR_INVALID_DATE_RANGE",
            "period_end_date must be on or after period_start_date.",
        )
    parsed = V.parse_temporal(RUN_FIELDS, body)
    crew = V.get_crew(body["crew_id"])
    for other in db.runs_of_crew(crew["id"]):
        if (
            other["period_start_date"] == body["period_start_date"]
            and other["period_end_date"] == body["period_end_date"]
        ):
            fail("ERR_DUPLICATE_RECORD", "That crew already has a run for that period.")

    rec = db.new_record()
    rec["crew_id"] = crew["id"]
    rec["period_start_date"] = body["period_start_date"]
    rec["period_end_date"] = body["period_end_date"]
    rec["bound_session_count"] = 0
    for key in (
        "period_hours",
        "period_piece_cents",
        "period_floor_cents",
        "period_makeup_cents",
        "period_deduction_cents",
        "settled_gross_cents",
        "settled_net_cents",
        "accrued_gross_cents",
        "reconciliation_delta_cents",
        "locked_by_user_id",
        "settled_by_user_id",
    ):
        rec[key] = None
    rec["status"] = "DRAFT"
    rec["_period_start_date"] = parsed["period_start_date"]
    rec["_period_end_date"] = parsed["period_end_date"]
    db.payroll_runs[rec["id"]] = rec
    return response.object_response(rec, 201)


@bp.route("/payroll-runs/<payroll_run_id>", methods=["GET"])
def read_run(payroll_run_id):
    V.authenticate((PC, HM, CS))
    return response.object_response(V.get_run(payroll_run_id))


@bp.route("/payroll-runs", methods=["GET"])
def list_runs():
    V.authenticate((PC, HM, CS))
    rows = filter_args(
        db.all_of(db.payroll_runs), {"crew_id": "crew_id", "status": "status"}
    )
    return response.paginate(rows)


def _in_period(session, run):
    return (
        run["_period_start_date"] <= session["_work_date"] <= run["_period_end_date"]
    )


@bp.route("/payroll-runs/<payroll_run_id>/lock", methods=["POST"])
def lock_run(payroll_run_id):
    user_id, _ = V.authenticate((PC,))
    run = V.get_run(payroll_run_id)
    if run["status"] != "DRAFT":
        fail("ERR_INVALID_PAYROLL_STATE", "Only a DRAFT run may be locked.")
    crew_sessions = db.sessions_of_crew(run["crew_id"])
    in_period = [s for s in crew_sessions if _in_period(s, run)]
    for session in in_period:
        if session["status"] in ("OPEN", "TALLIED", "DISPUTED"):
            fail("ERR_PERIOD_HAS_UNRESOLVED_SESSIONS")
    for other in db.runs_of_crew(run["crew_id"]):
        if other["id"] != run["id"] and other["status"] == "LOCKED":
            fail("ERR_CREW_RUN_ALREADY_LOCKED")

    bound = []
    for session in in_period:
        if session["status"] != "APPROVED" or session["payroll_run_id"] is not None:
            continue
        window = db.harvest_windows.get(session["harvest_window_id"])
        crew_id = window["crew_id"] if window else None
        if crew_id is not None and crew_id != run["crew_id"]:
            fail("ERR_CREW_MISMATCH")
        bound.append(session)

    hours = util.ZERO
    piece = 0
    gross = 0
    for session in bound:
        session["payroll_run_id"] = run["id"]
        hours += util.dec(session["hours_worked"])
        piece += int(session["piece_cents"])
        gross += int(session["gross_cents"])
        db.touch(session)

    run["bound_session_count"] = len(bound)
    run["period_hours"] = util.q2(hours)
    run["period_piece_cents"] = piece
    run["accrued_gross_cents"] = gross
    run["locked_by_user_id"] = user_id
    run["status"] = "LOCKED"
    db.touch(run)
    return response.object_response(run)


@bp.route("/payroll-runs/<payroll_run_id>/settle", methods=["POST"])
def settle_run(payroll_run_id):
    user_id, _ = V.authenticate((PC,))
    run = V.get_run(payroll_run_id)
    if run["status"] != "LOCKED":
        fail("ERR_INVALID_PAYROLL_STATE", "Only a LOCKED run may be settled.")
    if user_id == run["locked_by_user_id"]:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The clerk who locked a period may not settle it.",
        )

    crew = db.crews[run["crew_id"]]
    bound = db.sessions_of_run(run["id"])
    net_sum = calc.settle_period(run, bound, crew)
    for session in bound:
        if session["status"] == "APPROVED":
            session["status"] = "SETTLED"
        db.touch(session)

    crew["accrued_wage_cents"] = int(crew["accrued_wage_cents"]) - net_sum
    crew["settled_wage_cents"] = int(crew["settled_wage_cents"]) + int(
        run["settled_net_cents"]
    )
    crew["reconciliation_delta_cents"] = int(crew["reconciliation_delta_cents"]) + int(
        run["reconciliation_delta_cents"]
    )
    db.touch(crew)
    run["settled_by_user_id"] = user_id
    run["status"] = "SETTLED"
    db.touch(run)
    return response.object_response(run)
