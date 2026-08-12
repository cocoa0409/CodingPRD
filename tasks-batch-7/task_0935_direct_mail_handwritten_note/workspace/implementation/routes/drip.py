"""Drip schedules and their steps."""
from flask import Blueprint, request

import calc
import derive
import enums
import envelope
import ladder
import serial
import store
from errors import ApiError
from ladder import Ctx
from model import new_row, touch
from store import db

bp = Blueprint("drip", __name__)

DRIP_READ_ROLES = ["PlatformAdmin", "CampaignManager", "AccountOwner"]


def _schedule_account(schedule):
    campaign = db.campaigns.get(schedule["campaign_id"]) if schedule else None
    return campaign["account_id"] if campaign else None


@bp.route("/mail/drip-schedules", methods=["POST"])
def create_schedule():
    ctx = Ctx(["PlatformAdmin", "CampaignManager"])
    ctx.fk("campaign", "campaign_id")
    ctx.fields(required=[("campaign_id", "str"), ("name", "str"),
                         ("anchor_variant", "str")])
    ctx.enums([("anchor_variant", enums.ANCHOR_VARIANTS)])
    ctx.gate(lambda: ctx.get("campaign"))
    ctx.run()
    row = new_row({
        "campaign_id": ctx.body["campaign_id"],
        "name": ctx.body["name"],
        "anchor_variant": ctx.body["anchor_variant"],
        "status": "DRAFT",
    })
    db.drip_schedules[row["id"]] = row
    return envelope.object_response(serial.drip_schedule(row), 201)


@bp.route("/mail/drip-schedules/<drip_schedule_id>", methods=["GET"])
def get_schedule(drip_schedule_id):
    ctx = Ctx(DRIP_READ_ROLES)
    ctx.path("drip_schedule", drip_schedule_id)
    ctx.scope(lambda: _schedule_account(ctx.get("drip_schedule")))
    ctx.run()
    return envelope.object_response(serial.drip_schedule(ctx.get("drip_schedule")), 200)


@bp.route("/mail/drip-schedules", methods=["GET"])
def list_schedules():
    ctx = Ctx(DRIP_READ_ROLES)
    ctx.run()
    rows = list(db.drip_schedules.values())
    for field in ("campaign_id", "status"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    rows = envelope.sort_rows(rows)
    page, limit, offset, total = envelope.paginate(rows, request.args)
    return envelope.list_response([serial.drip_schedule(r) for r in page], limit, offset, total)


@bp.route("/mail/drip-schedules/<drip_schedule_id>/steps", methods=["POST"])
def create_step(drip_schedule_id):
    ctx = Ctx(["PlatformAdmin", "CampaignManager"])
    ctx.path("drip_schedule", drip_schedule_id)
    ctx.fk("mail_job", "mail_job_id")
    ctx.fields(required=[("mail_job_id", "str"), ("sequence_no", "int"),
                         ("anchor_date", "date"),
                         ("expected_drip_schedule_version", "int")])
    ctx.ranges([("sequence_no", 1, None, False)])
    ctx.gate(lambda: ladder.campaign_of_schedule(ctx.get("drip_schedule")))
    ctx.occ("expected_drip_schedule_version", lambda: ctx.get("drip_schedule"))
    ctx.at(20, lambda: _schedule_open(ctx.get("drip_schedule")))
    ctx.at(26, lambda: _unique_sequence(ctx))
    ctx.at(27, lambda: _derive_step(ctx))
    ctx.at(30, lambda: _gap(ctx))
    ctx.at(31, lambda: _step_limit(ctx))
    ctx.run()
    schedule = ctx.get("drip_schedule")
    job = ctx.get("mail_job")
    mail_date, in_home, shift = ctx.derived["derivation"]
    row = new_row({
        "drip_schedule_id": schedule["id"],
        "mail_job_id": job["id"],
        "sequence_no": ctx.body["sequence_no"],
        "anchor_date": store.parse_date(ctx.body["anchor_date"]),
        "computed_mail_date": mail_date,
        "computed_in_home_date": in_home,
        "shifted_days": shift,
        "status": "SCHEDULED" if job["status"] in ("PROOFED", "SCHEDULED") else "PENDING",
    })
    db.drip_steps[row["id"]] = row
    if schedule["status"] == "DRAFT":
        schedule["status"] = "ACTIVE"
    touch(schedule)
    return envelope.object_response(serial.drip_step(row), 201)


def _schedule_open(schedule):
    if schedule["status"] == "CANCELLED":
        raise ApiError("ERR_INVALID_STATE")


def _unique_sequence(ctx):
    for step in derive.schedule_steps(ctx.get("drip_schedule")["id"]):
        if step["sequence_no"] == ctx.body["sequence_no"]:
            raise ApiError("ERR_DUPLICATE_KEY")


def _derive_step(ctx):
    schedule = ctx.get("drip_schedule")
    job = ctx.get("mail_job")
    anchor = store.parse_date(ctx.body["anchor_date"])
    ctx.derived["derivation"] = calc.mail_date_derivation(
        anchor, job["mail_class"], schedule["anchor_variant"])


def _gap(ctx):
    mail_date = ctx.derived["derivation"][0]
    # Adjudication of friction 5: a sibling that holds no resolved drop date
    # (an unscheduled PENDING step) has nothing to conflict with and is
    # skipped.  Both readings offered by PRD 3.6 converge on this outcome.
    for step in derive.schedule_steps(ctx.get("drip_schedule")["id"]):
        if step["status"] == "CANCELLED" or step["computed_mail_date"] is None:
            continue
        delta = abs((mail_date - step["computed_mail_date"]).days)
        if delta < store.DRIP_MIN_GAP_DAYS:
            raise ApiError("ERR_DRIP_GAP_TOO_SMALL")


def _step_limit(ctx):
    if derive.schedule_step_count(ctx.get("drip_schedule")["id"]) >= store.DRIP_MAX_STEPS:
        raise ApiError("ERR_DRIP_STEP_LIMIT")


@bp.route("/mail/drip-steps/<drip_step_id>", methods=["GET"])
def get_step(drip_step_id):
    ctx = Ctx(DRIP_READ_ROLES)
    ctx.path("drip_step", drip_step_id)
    ctx.scope(lambda: _schedule_account(
        db.drip_schedules.get(ctx.get("drip_step")["drip_schedule_id"])))
    ctx.run()
    return envelope.object_response(serial.drip_step(ctx.get("drip_step")), 200)


@bp.route("/mail/drip-steps", methods=["GET"])
def list_steps():
    ctx = Ctx(DRIP_READ_ROLES)
    ctx.run()
    rows = list(db.drip_steps.values())
    for field in ("drip_schedule_id", "mail_job_id", "status"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    rows = envelope.sort_rows(rows)
    page, limit, offset, total = envelope.paginate(rows, request.args)
    return envelope.list_response([serial.drip_step(r) for r in page], limit, offset, total)


@bp.route("/mail/drip-steps/<drip_step_id>/release", methods=["POST"])
def release_step(drip_step_id):
    ctx = Ctx(["PlatformAdmin", "CampaignManager"])
    ctx.path("drip_step", drip_step_id)
    ctx.gate(lambda: ladder.campaign_of_step(ctx.get("drip_step")))
    ctx.at(20, lambda: _release_gates(ctx.get("drip_step")))
    ctx.run()
    step = ctx.get("drip_step")
    step["status"] = "RELEASED"
    touch(step)
    return envelope.object_response(serial.drip_step(step), 200)


def _release_gates(step):
    if step["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")
    job = db.mail_jobs.get(step["mail_job_id"])
    if job is None or job["status"] != "COMMITTED":
        raise ApiError("ERR_MAIL_JOB_INVALID_STATE")
