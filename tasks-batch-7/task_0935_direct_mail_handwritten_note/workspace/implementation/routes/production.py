"""The plant floor: robot-pen production runs."""
from flask import Blueprint, request

import calc
import derive
import enums
import envelope
import ladder
import serial
import services
import store
from errors import ApiError
from ladder import Ctx
from model import new_row, touch
from store import db

bp = Blueprint("production", __name__)

RUN_READ_ROLES = ["PlatformAdmin", "ProductionOperator", "CampaignManager"]


def _run_state(run, allowed):
    if run["status"] not in allowed:
        raise ApiError("ERR_RUN_INVALID_STATE")


@bp.route("/mail/mail-jobs/<mail_job_id>/production-runs", methods=["POST"])
def create_run(mail_job_id):
    ctx = Ctx(["PlatformAdmin", "ProductionOperator"])
    ctx.path("mail_job", mail_job_id)
    ctx.fk("machine", "machine_id")
    ctx.fk("ink_lot", "ink_lot_id")
    ctx.fields(required=[("machine_id", "str"), ("ink_lot_id", "str"),
                         ("run_date", "date"), ("piece_count", "int"),
                         ("expected_mail_job_version", "int")],
               optional=[("capacity_variant", "str")])
    ctx.enums([("capacity_variant", enums.CAPACITY_VARIANTS)])
    ctx.ranges([("piece_count", store.MIN_JOB_PIECE_COUNT, None, False)])
    ctx.gate(lambda: ladder.campaign_of_job(ctx.get("mail_job")))
    ctx.occ("expected_mail_job_version", lambda: ctx.get("mail_job"))
    ctx.at(13, lambda: _reject_eddm(ctx.get("mail_job")))
    ctx.at(17, lambda: _job_committed(ctx.get("mail_job")))
    ctx.at(21, lambda: _lot_reservable(ctx.get("ink_lot")))
    ctx.at(22, lambda: _machine_online(ctx.get("machine")))
    ctx.at(32, lambda: _ink_type_match(ctx))
    ctx.at(36, lambda: _pieces_fit(ctx))
    ctx.at(39, lambda: _capacity(ctx))
    ctx.at(40, lambda: _ink_available(ctx))
    ctx.run()
    job = ctx.get("mail_job")
    lot = ctx.get("ink_lot")
    plan = ctx.derived["plan"]
    row = new_row({
        "mail_job_id": job["id"],
        "machine_id": ctx.body["machine_id"],
        "ink_lot_id": ctx.body["ink_lot_id"],
        "run_date": store.parse_date(ctx.body["run_date"]),
        "piece_count": ctx.body["piece_count"],
        "capacity_variant": ctx.body.get("capacity_variant") or "SINGLE_PASS",
        "planned_write_minutes": plan[0],
        "planned_slot_minutes": plan[1],
        "planned_ink_ul": plan[2],
        "status": "RESERVED",
        "spoiled_piece_count": 0,
    })
    db.production_runs[row["id"]] = row
    lot["remaining_ul"] = lot["remaining_ul"] - plan[2]
    if lot["status"] == "SEALED":
        lot["status"] = "OPEN"
    # Adjudication of friction 6: a draw that lands exactly on the safety
    # reserve carries the lot through to DEPLETED even when the same
    # reservation is the one that opened it (SEALED -> OPEN -> DEPLETED).
    # Leaving a freshly opened lot at OPEN on exactly 500 uL would strand it
    # there forever — no further draw can succeed — making both the
    # OPEN -> DEPLETED edge and the compensating DEPLETED -> OPEN edge
    # unreachable for that lot.
    if lot["remaining_ul"] == store.INK_SAFETY_RESERVE_UL:
        lot["status"] = "DEPLETED"
    touch(lot)
    touch(job)
    return envelope.object_response(serial.production_run(row), 201)


def _reject_eddm(job):
    if job["job_kind"] == "EDDM":
        raise ApiError("ERR_EDDM_NOT_APPLICABLE")


def _job_committed(job):
    if job["status"] != "COMMITTED":
        raise ApiError("ERR_MAIL_JOB_INVALID_STATE")


def _lot_reservable(lot):
    if lot["status"] not in ("SEALED", "OPEN"):
        raise ApiError("ERR_INK_LOT_UNAVAILABLE")


def _machine_online(machine):
    if machine["status"] != "ONLINE":
        raise ApiError("ERR_MACHINE_OFFLINE")


def _style_of_job(job):
    template = db.templates.get(job["template_id"])
    if template is None:
        return None, None
    return template, db.handwriting_styles.get(template["handwriting_style_id"])


def _ink_type_match(ctx):
    job = ctx.get("mail_job")
    template, style = _style_of_job(job)
    if style is None:
        return
    if ctx.get("ink_lot")["ink_type"] != style["ink_type"]:
        raise ApiError("ERR_INK_TYPE_MISMATCH")


def _pieces_fit(ctx):
    job = ctx.get("mail_job")
    reserved = sum(r["piece_count"] for r in derive.job_runs(job["id"])
                   if r["status"] != "VOIDED")
    if ctx.body["piece_count"] > job["billable_piece_count"] - reserved:
        raise ApiError("ERR_RUN_PIECES_EXCEED_JOB")


def _plan(ctx):
    if "plan" in ctx.derived:
        return ctx.derived["plan"]
    job = ctx.get("mail_job")
    template, style = _style_of_job(job)
    plan = calc.production_capacity_plan(
        ctx.body["piece_count"], template["character_count"],
        style["chars_per_minute"], style["ink_ul_per_1000_chars"],
        ctx.body.get("capacity_variant") or "SINGLE_PASS")
    ctx.derived["plan"] = plan
    return plan


def _capacity(ctx):
    plan = _plan(ctx)
    machine = ctx.get("machine")
    run_date = store.parse_date(ctx.body["run_date"])
    committed = derive.machine_day_committed_minutes(machine["id"], run_date)
    if committed + plan[1] > machine["daily_capacity_minutes"]:
        raise ApiError("ERR_MACHINE_CAPACITY_EXCEEDED")


def _ink_available(ctx):
    plan = _plan(ctx)
    lot = ctx.get("ink_lot")
    if lot["remaining_ul"] - plan[2] < store.INK_SAFETY_RESERVE_UL:
        raise ApiError("ERR_INK_INSUFFICIENT")


@bp.route("/mail/production-runs/<production_run_id>", methods=["GET"])
def get_run(production_run_id):
    ctx = Ctx(RUN_READ_ROLES)
    ctx.path("production_run", production_run_id)
    ctx.run()
    return envelope.object_response(serial.production_run(ctx.get("production_run")), 200)


@bp.route("/mail/production-runs", methods=["GET"])
def list_runs():
    ctx = Ctx(RUN_READ_ROLES)
    ctx.run()
    rows = list(db.production_runs.values())
    for field in ("mail_job_id", "machine_id", "ink_lot_id", "status"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    run_date = request.args.get("run_date")
    if run_date is not None:
        target = store.parse_date(run_date)
        rows = [r for r in rows if r["run_date"] == target]
    rows = envelope.sort_rows(rows)
    page, limit, offset, total = envelope.paginate(rows, request.args)
    return envelope.list_response([serial.production_run(r) for r in page], limit, offset, total)


@bp.route("/mail/production-runs/<production_run_id>/start", methods=["POST"])
def start_run(production_run_id):
    ctx = Ctx(["PlatformAdmin", "ProductionOperator"])
    ctx.path("production_run", production_run_id)
    ctx.gate(lambda: ladder.campaign_of_run(ctx.get("production_run")))
    ctx.at(19, lambda: _run_state(ctx.get("production_run"), ("RESERVED", "FAILED")))
    ctx.at(21, lambda: _lot_open(db.ink_lots.get(ctx.get("production_run")["ink_lot_id"])))
    ctx.at(22, lambda: _machine_online(db.machines[ctx.get("production_run")["machine_id"]]))
    ctx.run()
    run = ctx.get("production_run")
    run["status"] = "RUNNING"
    touch(run)
    job = db.mail_jobs.get(run["mail_job_id"])
    if job is not None and job["status"] == "COMMITTED":
        job["status"] = "IN_PRODUCTION"
        touch(job)
    return envelope.object_response(serial.production_run(run), 200)


def _lot_open(lot):
    if lot is None or lot["status"] != "OPEN":
        raise ApiError("ERR_INK_LOT_UNAVAILABLE")


@bp.route("/mail/production-runs/<production_run_id>/complete", methods=["POST"])
def complete_run(production_run_id):
    ctx = Ctx(["PlatformAdmin", "ProductionOperator"])
    ctx.path("production_run", production_run_id)
    ctx.gate(lambda: ladder.campaign_of_run(ctx.get("production_run")))
    ctx.at(19, lambda: _run_state(ctx.get("production_run"), ("RUNNING",)))
    ctx.run()
    run = ctx.get("production_run")
    run["status"] = "COMPLETED"
    touch(run)
    return envelope.object_response(serial.production_run(run), 200)


@bp.route("/mail/production-runs/<production_run_id>/fail", methods=["POST"])
def fail_run(production_run_id):
    ctx = Ctx(["PlatformAdmin", "ProductionOperator"])
    ctx.path("production_run", production_run_id)
    ctx.fields(required=[("spoiled_piece_count", "int")])
    ctx.gate(lambda: ladder.campaign_of_run(ctx.get("production_run")))
    ctx.at(19, lambda: _run_state(ctx.get("production_run"), ("RUNNING",)))
    ctx.run()
    run = ctx.get("production_run")
    run["status"] = "FAILED"
    run["spoiled_piece_count"] = ctx.body["spoiled_piece_count"]
    touch(run)
    return envelope.object_response(serial.production_run(run), 200)


@bp.route("/mail/production-runs/<production_run_id>/void", methods=["POST"])
def void_run(production_run_id):
    ctx = Ctx(["PlatformAdmin", "ProductionOperator"])
    ctx.path("production_run", production_run_id)
    ctx.fields(optional=[("reason", "str")])
    ctx.gate(lambda: ladder.campaign_of_run(ctx.get("production_run")))
    ctx.at(19, lambda: _run_state(ctx.get("production_run"), ("RESERVED", "FAILED")))
    ctx.run()
    run = ctx.get("production_run")
    services.void_run(run)
    return envelope.object_response(serial.production_run(run), 200)
