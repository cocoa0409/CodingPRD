"""Submitter routes (PRD §2.6, §3.1, §4)."""
from flask import Blueprint

from auth import require_auth, CLERK, EXAMINER, RECORDER, ALL_READERS
from db import db, new_id, common_fields, touch
from helpers import (body, require_fields, as_str, as_enum, get_or_404, out,
                     out_list, paginate, sort_created)
from response import ok, created, listed

bp = Blueprint("submitters", __name__)

SUBMITTER_TYPES = {"TITLE_COMPANY", "ATTORNEY", "SELF", "GOVERNMENT"}


@bp.route("/submitters", methods=["POST"])
def create_submitter():
    require_auth([CLERK])
    data = body()
    require_fields(data, ["name", "submitter_type"])
    name = as_str(data, "name")
    submitter_type = as_enum(data, "submitter_type", SUBMITTER_TYPES)

    sid = new_id()
    submitter = {
        "id": sid,
        "name": name,
        "submitter_type": submitter_type,
        "status": "ACTIVE",
        "escrow_deposited_total_cents": 0,
        "escrow_balance_cents": 0,
        "escrow_held_cents": 0,
        "escrow_available_cents": 0,
    }
    submitter.update(common_fields())
    db.submitters[sid] = submitter
    return created(out(submitter))


@bp.route("/submitters/<sid>", methods=["GET"])
def get_submitter(sid):
    require_auth(ALL_READERS)
    submitter = get_or_404(db.submitters, sid)
    return ok(out(submitter))


@bp.route("/submitters/<sid>/suspend", methods=["POST"])
def suspend_submitter(sid):
    require_auth([CLERK])
    submitter = get_or_404(db.submitters, sid)
    submitter["status"] = "SUSPENDED"
    touch(submitter)
    return ok(out(submitter))


@bp.route("/submitters", methods=["GET"])
def list_submitters():
    require_auth([CLERK, EXAMINER, RECORDER])
    items = sort_created(list(db.submitters.values()))
    window, limit, offset, total = paginate(items)
    return listed(out_list(window), limit, offset, total)
