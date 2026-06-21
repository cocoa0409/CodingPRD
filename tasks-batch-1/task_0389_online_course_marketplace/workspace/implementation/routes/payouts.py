"""Payouts + revenue ledger reads (PRD §3.11, §2.7)."""
from flask import Blueprint, request

import response
from db import db, new_id
from errors import err
from middleware import authenticate, require_roles
from services.common import (stamp_create, touch, require_field, as_str, as_int,
                             paginate)
from services.ledger import write_entry, recompute_balances
from services.serialize import view, view_list

bp = Blueprint("payouts", __name__)


def _body():
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


@bp.route("/payouts", methods=["POST"])
def request_payout():
    principal = authenticate()
    require_roles(principal, "Instructor")
    body = _body()
    instructor_id = as_str(require_field(body, "instructor_id"), "instructor_id")
    requested = as_int(require_field(body, "requested_amount_cents"), "requested_amount_cents")
    if requested < 1:
        raise err("ERR_INVALID_REQUEST", "requested_amount_cents must be >= 1.")

    if principal.user_id != instructor_id:
        raise err("ERR_FORBIDDEN")
    inst = db.instructors.get(instructor_id)
    if inst is None:
        raise err("ERR_NOT_FOUND")

    # ensure balances are current, then require payout_balance >= 1
    recompute_balances(instructor_id)
    if inst["payout_balance_cents"] < 1:
        raise err("ERR_INSUFFICIENT_BALANCE")

    rec = {
        "id": new_id(),
        "instructor_id": instructor_id,
        "requested_amount_cents": requested,
        "paid_amount_cents": 0,
        "status": "REQUESTED",
    }
    stamp_create(rec)
    db.payouts[rec["id"]] = rec
    return response.success(view(rec), status=201)


@bp.route("/payouts/<payout_id>", methods=["GET"])
def get_payout(payout_id):
    principal = authenticate()
    require_roles(principal, "Instructor", "PlatformAdmin")
    rec = db.payouts.get(payout_id)
    if rec is None:
        raise err("ERR_NOT_FOUND")
    if principal.role == "Instructor" and principal.user_id != rec["instructor_id"]:
        raise err("ERR_FORBIDDEN")
    return response.success(view(rec), status=200)


@bp.route("/payouts", methods=["GET"])
def list_payouts():
    principal = authenticate()
    require_roles(principal, "Instructor", "PlatformAdmin")
    args = request.args
    items = list(db.payouts.values())
    instructor_id = args.get("instructor_id")
    status = args.get("status")
    if instructor_id is not None:
        items = [p for p in items if p["instructor_id"] == instructor_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    if principal.role == "Instructor":
        items = [p for p in items if p["instructor_id"] == principal.user_id]
    page, meta = paginate(items, args)
    return response.success(view_list(page), status=200, pagination=meta)


@bp.route("/payouts/<payout_id>/approve", methods=["POST"])
def approve_payout(payout_id):
    principal = authenticate()
    require_roles(principal, "PlatformAdmin")
    body = _body()
    expected_version = as_int(require_field(body, "expected_instructor_version"),
                              "expected_instructor_version")

    rec = db.payouts.get(payout_id)
    if rec is None:
        raise err("ERR_NOT_FOUND")
    # state: must be REQUESTED
    if rec["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE")

    inst = db.instructors.get(rec["instructor_id"])
    # business: balance >= 1 (recompute to be current)
    recompute_balances(rec["instructor_id"])
    if inst["payout_balance_cents"] < 1:
        raise err("ERR_INSUFFICIENT_BALANCE")

    # OCC: expected_instructor_version == instructor.version (evaluated late)
    if expected_version != inst["version"]:
        raise err("ERR_STALE_VERSION")

    paid = min(rec["requested_amount_cents"], inst["payout_balance_cents"])
    rec["paid_amount_cents"] = paid
    rec["status"] = "PAID"
    touch(rec)

    # write PAYOUT ledger entry of -paid with status PAID, then recompute
    # balances (which bumps the instructor's version by 1).
    write_entry(rec["instructor_id"], "PAYOUT", -paid, "PAID", payout_id=payout_id)
    recompute_balances(rec["instructor_id"])

    return response.success(view(rec), status=200)


@bp.route("/payouts/<payout_id>/reject", methods=["POST"])
def reject_payout(payout_id):
    principal = authenticate()
    require_roles(principal, "PlatformAdmin")
    rec = db.payouts.get(payout_id)
    if rec is None:
        raise err("ERR_NOT_FOUND")
    if rec["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE")
    rec["status"] = "REJECTED"
    touch(rec)
    return response.success(view(rec), status=200)


# --------------------------------------------------------------------------
# Revenue ledger reads
# --------------------------------------------------------------------------

@bp.route("/ledger-entries/<entry_id>", methods=["GET"])
def get_ledger_entry(entry_id):
    principal = authenticate()
    require_roles(principal, "Instructor", "PlatformAdmin")
    rec = db.ledger_entries.get(entry_id)
    if rec is None:
        raise err("ERR_NOT_FOUND")
    if principal.role == "Instructor" and principal.user_id != rec["instructor_id"]:
        raise err("ERR_FORBIDDEN")
    return response.success(view(rec), status=200)


@bp.route("/ledger-entries", methods=["GET"])
def list_ledger_entries():
    principal = authenticate()
    require_roles(principal, "Instructor", "PlatformAdmin")
    args = request.args
    items = list(db.ledger_entries.values())
    for key in ("instructor_id", "enrollment_id", "payout_id", "entry_type", "status"):
        val = args.get(key)
        if val is not None:
            items = [e for e in items if e.get(key) == val]
    if principal.role == "Instructor":
        items = [e for e in items if e["instructor_id"] == principal.user_id]
    page, meta = paginate(items, args)
    return response.success(view_list(page), status=200, pagination=meta)
