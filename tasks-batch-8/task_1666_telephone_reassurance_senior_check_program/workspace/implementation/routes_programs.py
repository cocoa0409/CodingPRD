"""Clock + Program + promotion-run + daily-closeout + outcome-report routes."""
from flask import Blueprint, request

from auth import endpoint, get_body
from db import store, now, new_entity, touch
from envelope import ok, ok_list
from errors import (raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_STALE_VERSION, ERR_REPORT_PERIOD_OPEN)
from validate import Field, validate_payload, parse_pagination, sort_items
import cascade
import calc
import serialize
import timeutil

bp = Blueprint("programs", __name__)

ALL = ["ProgramCoordinator", "IntakeWorker", "QualityReviewer",
       "VolunteerCaller", "ExternalResponder"]
PC = ["ProgramCoordinator"]
IW = ["IntakeWorker"]
QR = ["QualityReviewer"]


@bp.route("/api/_clock/set_current_utc", methods=["POST"])
@endpoint(["ProgramCoordinator", "IntakeWorker", "QualityReviewer"])
def set_clock(uid, role):
    data = validate_payload(get_body(),
                            [Field("to_iso8601", "dt", required=True)])
    store.clock = data["to_iso8601"]
    return ok({"current_utc": timeutil.fmt_dt(store.clock)})


@bp.route("/api/programs", methods=["POST"])
@endpoint(PC)
def create_program(uid, role):
    spec = [
        Field("name", "str", required=True, allow_empty_str=False),
        Field("total_capacity", "int", required=True, minv=1, maxv=10000),
        Field("current_policy_version", "str", required=True, allow_empty_str=False),
        Field("max_reserve_slots", "int", minv=0),
        Field("no_answer_threshold", "int", minv=1),
        Field("escalation_retry_hours", "int", minv=0),
        Field("contact_phase_hours", "int", minv=0),
        Field("offer_ttl_hours", "int", minv=0),
        Field("reapply_cooling_days", "int", minv=0),
        Field("survey_valid_days", "int", minv=0),
        Field("doc_buffer_minutes", "int", minv=0),
    ]
    data = validate_payload(get_body(), spec)
    reserve = data.get("max_reserve_slots")
    if reserve is None:
        reserve = min(5, data["total_capacity"])
    if reserve > data["total_capacity"]:
        raise_err(ERR_INVALID_REQUEST, "max_reserve_slots must be <= total_capacity")
    g = new_entity()
    g.update({
        "name": data["name"],
        "total_capacity": data["total_capacity"],
        "max_reserve_slots": reserve,
        "no_answer_threshold": data.get("no_answer_threshold", 3),
        "escalation_retry_hours": data.get("escalation_retry_hours", 4),
        "contact_phase_hours": data.get("contact_phase_hours", 24),
        "offer_ttl_hours": data.get("offer_ttl_hours", 72),
        "reapply_cooling_days": data.get("reapply_cooling_days", 30),
        "survey_valid_days": data.get("survey_valid_days", 30),
        "doc_buffer_minutes": data.get("doc_buffer_minutes", 15),
        "current_policy_version": data["current_policy_version"],
        "intake_posture": "OPEN",
        "promotion_epoch": 0,
    })
    store.programs[g["id"]] = g
    return ok(serialize.program(g), 201)


def get_program_or_404(pid):
    g = store.programs.get(pid)
    if not g:
        raise_err(ERR_NOT_FOUND, "Program not found")
    return g


@bp.route("/api/programs/<pid>", methods=["GET"])
@endpoint(ALL)
def get_program(pid, uid, role):
    return ok(serialize.program(get_program_or_404(pid)))


PATCH_SPEC = [
    Field("expected_program_version", "int", required=True),
    Field("name", "str", allow_empty_str=False),
    Field("total_capacity", "int", minv=1, maxv=10000),
    Field("max_reserve_slots", "int", minv=0),
    Field("no_answer_threshold", "int", minv=1),
    Field("escalation_retry_hours", "int", minv=0),
    Field("contact_phase_hours", "int", minv=0),
    Field("offer_ttl_hours", "int", minv=0),
    Field("reapply_cooling_days", "int", minv=0),
    Field("survey_valid_days", "int", minv=0),
    Field("doc_buffer_minutes", "int", minv=0),
    Field("current_policy_version", "str", allow_empty_str=False),
]


@bp.route("/api/programs/<pid>", methods=["PATCH"])
@endpoint(PC)
def patch_program(pid, uid, role):
    g = get_program_or_404(pid)
    data = validate_payload(get_body(), PATCH_SPEC, partial=False)
    if data["expected_program_version"] != g["version"]:
        raise_err(ERR_STALE_VERSION, "Stale program version")
    new_cap = data.get("total_capacity", g["total_capacity"])
    new_reserve = data.get("max_reserve_slots", g["max_reserve_slots"])
    if new_reserve > new_cap:
        raise_err(ERR_INVALID_REQUEST, "max_reserve_slots must be <= total_capacity")
    for key in PATCH_SPEC[1:]:
        if key.name in data:
            g[key.name] = data[key.name]
    touch(g)
    return ok(serialize.program(g))


@bp.route("/api/programs/<pid>/pause-intake", methods=["POST"])
@endpoint(PC)
def pause_intake(pid, uid, role):
    g = get_program_or_404(pid)
    if g["intake_posture"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "Intake is not OPEN")
    g["intake_posture"] = "PAUSED"
    touch(g)
    return ok(serialize.program(g))


@bp.route("/api/programs/<pid>/resume-intake", methods=["POST"])
@endpoint(PC)
def resume_intake(pid, uid, role):
    g = get_program_or_404(pid)
    if g["intake_posture"] != "PAUSED":
        raise_err(ERR_INVALID_STATE, "Intake is not PAUSED")
    g["intake_posture"] = "OPEN"
    touch(g)
    return ok(serialize.program(g))


@bp.route("/api/programs/<pid>/promotion-runs", methods=["POST"])
@endpoint(IW)
def promotion_runs(pid, uid, role):
    g = get_program_or_404(pid)
    data = validate_payload(
        get_body(), [Field("expected_program_version", "int", required=True)])
    if data["expected_program_version"] != g["version"]:
        raise_err(ERR_STALE_VERSION, "Stale program version")
    result = cascade.promotion_run(g)
    return ok(result, 201)


@bp.route("/api/programs/<pid>/daily-closeout", methods=["POST"])
@endpoint(PC)
def daily_closeout(pid, uid, role):
    g = get_program_or_404(pid)
    result = cascade.daily_closeout(g)
    return ok(result)


@bp.route("/api/programs/<pid>/outcome-reports", methods=["POST"])
@endpoint(QR)
def generate_report(pid, uid, role):
    g = get_program_or_404(pid)
    data = validate_payload(get_body(),
                            [Field("period_month", "month", required=True)])
    r = new_entity()
    r.update({
        "program_id": g["id"],
        "period_month": data["period_month"],
        "status": "PROVISIONAL",
    })
    r.update(calc.compute_report_metrics(g, data["period_month"], "provisional"))
    store.reports[r["id"]] = r
    return ok(serialize.outcome_report(r), 201)


@bp.route("/api/programs/<pid>/outcome-reports", methods=["GET"])
@endpoint(["ProgramCoordinator", "QualityReviewer"])
def list_reports(pid, uid, role):
    g = get_program_or_404(pid)
    limit, offset = parse_pagination(request.args)
    items = [r for r in store.reports.values() if r["program_id"] == g["id"]]
    pm = request.args.get("period_month")
    if pm is not None:
        items = [r for r in items if r["period_month"] == pm]
    items = sort_items(items)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize.outcome_report(r) for r in page], total, limit, offset)
