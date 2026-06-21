"""SuretyProgram endpoints (PRD §3.1, §2.6). Senior creates/suspends; all read."""

from flask import Blueprint

import errors
from db import db, new_id, now_ts, next_seq
from middleware import require_roles
from response import success, list_success
from serializers import serialize_program
from services.domain import touch
from helpers import (
    get_body, require_str, require_int,
    parse_pagination, paginate, sort_by_created,
)

bp = Blueprint("programs", __name__)


@bp.route("/surety/programs", methods=["POST"])
@require_roles("SeniorUnderwriter")
def create_program():
    body = get_body()
    name = require_str(body, "name")
    single_limit_cents = require_int(body, "single_limit_cents")
    aggregate_limit_cents = require_int(body, "aggregate_limit_cents")
    referral_threshold_cents = require_int(body, "referral_threshold_cents")
    loss_alert_threshold_cents = require_int(body, "loss_alert_threshold_cents")

    ts = now_ts()
    pid = new_id()
    record = {
        "id": pid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
        "name": name,
        "single_limit_cents": single_limit_cents,
        "aggregate_limit_cents": aggregate_limit_cents,
        "referral_threshold_cents": referral_threshold_cents,
        "loss_alert_threshold_cents": loss_alert_threshold_cents,
        "aggregate_committed_cents": 0,
        "status": "OPEN",
    }
    db.programs[pid] = record
    return success(serialize_program(record), status=201)


@bp.route("/surety/programs/<pid>", methods=["GET"])
@require_roles("Underwriter", "SeniorUnderwriter", "ClaimsExaminer")
def get_program(pid):
    record = db.programs.get(pid)
    if record is None:
        raise errors.not_found("Program not found")
    return success(serialize_program(record), status=200)


@bp.route("/surety/programs", methods=["GET"])
@require_roles("Underwriter", "SeniorUnderwriter", "ClaimsExaminer")
def list_programs():
    limit, offset = parse_pagination()
    items = sort_by_created(list(db.programs.values()))
    page, total = paginate(items, limit, offset)
    return list_success([serialize_program(p) for p in page], limit, offset, total)


@bp.route("/surety/programs/<pid>/suspend", methods=["POST"])
@require_roles("SeniorUnderwriter")
def suspend_program(pid):
    record = db.programs.get(pid)
    if record is None:
        raise errors.not_found("Program not found")
    if record["status"] != "OPEN":
        raise errors.invalid_state("Program is not OPEN")
    record["status"] = "SUSPENDED"
    touch(record)
    return success(serialize_program(record), status=200)
