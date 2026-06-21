"""OptionExercise routes: exercise (create+settle), fetch, list."""

from flask import Blueprint, request

import db
from errors import err
from middleware import get_auth, require_role
from response import object_response, array_response
from routes.helpers import lookup, paginate
from services import domain
from services import calc
import validation as V

bp = Blueprint("option_exercises", __name__)


# ---------------------------------------------------------------------------
# Exercise (Tenant): create PENDING then settle, Agreement ACTIVE -> EXERCISED
# ---------------------------------------------------------------------------
@bp.post("/agreements/<aid>/option-exercises")
def exercise_option(aid):
    user_id, role = get_auth()
    require_role(role, {"Tenant"})
    agreement = lookup(db.agreements, aid)
    if agreement["tenant_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Tenant does not own this agreement")

    body = V.get_body()
    exercised_at = V.parse_dt(V.require(body, "exercised_at"), "exercised_at")

    # State (priority 7): agreement must be ACTIVE.
    if agreement["status"] != "ACTIVE":
        raise err("ERR_AGREEMENT_NOT_ACTIVE", "Agreement is not ACTIVE")

    # Temporal (priority 9): exercised_at <= option_deadline.
    deadline = V.parse_dt(agreement["option_deadline"], "option_deadline")
    if exercised_at > deadline:
        raise err("ERR_OPTION_EXPIRED", "Exercise is after the option deadline")

    # Safety (priority 11): missed_payment_count must be 0.
    domain.recompute_accruals(agreement)
    if agreement["missed_payment_count"] > 0:
        raise err("ERR_OPTION_BLOCKED_BY_DEFAULT",
                  "Option blocked by outstanding default risk")

    # Settlement — pinned evaluation order (PRD §3.6).
    locked_snapshot = agreement["locked_price_cents"]
    cap = calc.max_credit_cap(locked_snapshot, agreement["max_credit_pct"])
    available = agreement["available_credit_cents"]
    credit_applied = min(available, cap)
    option_fee_credit = (agreement["option_fee_cents"]
                         if agreement["option_fee_creditable"] else 0)
    net_due = locked_snapshot - credit_applied - option_fee_credit

    rec = {
        "id": db.new_id(),
        "agreement_id": aid,
        "exercised_at": db.iso_millis(exercised_at),
        "locked_price_snapshot_cents": locked_snapshot,
        "max_credit_cap_cents": cap,
        "credit_applied_cents": credit_applied,
        "option_fee_credit_cents": option_fee_credit,
        "net_due_at_closing_cents": net_due,
        "status": "PENDING",
    }
    domain._stamp_new(rec)
    # PENDING -> SETTLED immediately (system step).
    rec["status"] = "SETTLED"
    domain.touch(rec)
    db.option_exercises[rec["id"]] = rec

    # Agreement ACTIVE -> EXERCISED.
    agreement["status"] = "EXERCISED"
    domain.touch(agreement)

    return object_response(domain.serialize_option_exercise(rec), 201)


# ---------------------------------------------------------------------------
# Fetch / list
# ---------------------------------------------------------------------------
@bp.get("/option-exercises/<rid>")
def get_exercise(rid):
    _, role = get_auth()
    require_role(role, {"Landlord", "Tenant", "EscrowAgent"})
    rec = lookup(db.option_exercises, rid)
    return object_response(domain.serialize_option_exercise(rec), 200)


@bp.get("/option-exercises")
def list_exercises():
    _, role = get_auth()
    require_role(role, {"Landlord", "Tenant", "EscrowAgent"})
    items = list(db.option_exercises.values())
    for field in ("agreement_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [e for e in items if e.get(field) == val]
    page, limit, offset, total = paginate(items)
    return array_response([domain.serialize_option_exercise(e) for e in page],
                          limit, offset, total)
