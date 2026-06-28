"""AllowanceSchedule, AllowanceRun, scheduler sweep, and logical clock
endpoints (PRD §3.4, §2.4)."""
from datetime import timedelta

from flask import Blueprint, request

import db
import domain
import serialize
import validate
from clock import parse_iso8601, iso
from errors import err
from middleware import authenticate, require_role, get_json_body
from response import object_response, list_response

bp = Blueprint("allowances", __name__)

MIN_SCHEDULE_GAP_DAYS = 7


@bp.route("/child-accounts/<cid>/allowance-schedules", methods=["POST"])
def create_schedule(cid):
    identity = authenticate()
    require_role(identity, {"Parent"})
    child = domain.get_child(cid)
    domain.check_child_owner(identity, child)
    body = get_json_body()

    amount = validate.require_int(body, "amount_cents")
    payout = validate.optional_enum(body, "payout_jar_type", {"SPEND", "SAVE", "GIVE"}, "SPEND")
    cadence = validate.require_int(body, "cadence_days")
    next_run_raw = validate.require_str(body, "next_run_at")
    next_run = parse_iso8601(next_run_raw)
    if next_run is None:
        raise err("ERR_INVALID_REQUEST", "next_run_at must be a valid ISO 8601 timestamp")
    validate.bound_positive(amount, "amount_cents")
    validate.bound_min(cadence, 1, "cadence_days")

    # Schedule spacing (PRD §3.4): closed buffer of 7 days against existing
    # ACTIVE schedules on the same child with the same payout_jar_type.
    for s in db.allowance_schedules.values():
        if (s["child_account_id"] == cid and s["status"] == "ACTIVE"
                and s["payout_jar_type"] == payout):
            existing = parse_iso8601(s["next_run_at"])
            gap = abs((next_run - existing).total_seconds())
            if gap < MIN_SCHEDULE_GAP_DAYS * 86400:
                raise err("ERR_SCHEDULE_WINDOW_CONFLICT", "Schedule too close to an existing one")

    rec = db.base_fields()
    rec.update({
        "child_account_id": cid,
        "amount_cents": amount,
        "payout_jar_type": payout,
        "cadence_days": cadence,
        "next_run_at": iso(next_run),
        "status": "ACTIVE",
    })
    db.allowance_schedules[rec["id"]] = rec
    return object_response(serialize.allowance_schedule(rec), status=201)


@bp.route("/child-accounts/<cid>/allowance-schedules", methods=["GET"])
def list_schedules(cid):
    identity = authenticate()
    require_role(identity, {"Parent", "Child", "PlatformAdmin"})
    child = domain.get_child(cid)
    domain.check_child_owner(identity, child)
    items = [s for s in db.allowance_schedules.values() if s["child_account_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return list_response([serialize.allowance_schedule(s) for s in items], request.args)


@bp.route("/allowance-schedules/<sid>", methods=["GET"])
def read_schedule(sid):
    identity = authenticate()
    require_role(identity, {"Parent", "Child", "PlatformAdmin"})
    sched = domain.get_schedule(sid)
    child = domain.get_child(sched["child_account_id"])
    domain.check_child_owner(identity, child)
    return object_response(serialize.allowance_schedule(sched))


@bp.route("/allowance-schedules/<sid>/pause", methods=["POST"])
def pause_schedule(sid):
    identity = authenticate()
    require_role(identity, {"Parent"})
    sched = domain.get_schedule(sid)
    child = domain.get_child(sched["child_account_id"])
    domain.check_child_owner(identity, child)
    if sched["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Schedule is not ACTIVE")
    sched["status"] = "PAUSED"
    db.touch(sched)
    return object_response(serialize.allowance_schedule(sched))


@bp.route("/allowance-schedules/<sid>/resume", methods=["POST"])
def resume_schedule(sid):
    identity = authenticate()
    require_role(identity, {"Parent"})
    sched = domain.get_schedule(sid)
    child = domain.get_child(sched["child_account_id"])
    domain.check_child_owner(identity, child)
    if sched["status"] != "PAUSED":
        raise err("ERR_INVALID_STATE", "Schedule is not PAUSED")
    sched["status"] = "ACTIVE"
    db.touch(sched)
    return object_response(serialize.allowance_schedule(sched))


@bp.route("/allowance-schedules/<sid>", methods=["DELETE"])
def cancel_schedule(sid):
    identity = authenticate()
    require_role(identity, {"Parent"})
    sched = domain.get_schedule(sid)
    child = domain.get_child(sched["child_account_id"])
    domain.check_child_owner(identity, child)
    if sched["status"] not in ("ACTIVE", "PAUSED"):
        raise err("ERR_INVALID_STATE", "Schedule cannot be cancelled")
    sched["status"] = "CANCELLED"
    db.touch(sched)
    return object_response(serialize.allowance_schedule(sched))


@bp.route("/allowance-schedules/<sid>/runs", methods=["GET"])
def list_runs(sid):
    identity = authenticate()
    require_role(identity, {"Parent", "PlatformAdmin"})
    sched = domain.get_schedule(sid)
    child = domain.get_child(sched["child_account_id"])
    domain.check_family_owner_for_child(identity, child)
    items = [r for r in db.allowance_runs.values() if r["allowance_schedule_id"] == sid]
    return list_response([serialize.allowance_run(r) for r in items], request.args)


@bp.route("/_scheduler/run-due-allowances", methods=["POST"])
def run_due():
    identity = authenticate()
    require_role(identity, {"PlatformAdmin"})
    now = db.clock.current()
    created = []
    # Deterministic order: by created_at then id.
    due = sorted(
        db.allowance_schedules.values(),
        key=lambda s: (s.get("created_at", ""), s.get("id", "")),
    )
    for sched in due:
        if sched["status"] != "ACTIVE":
            continue
        next_run = parse_iso8601(sched["next_run_at"])
        if next_run is None or now < next_run:
            continue
        child = db.child_accounts.get(sched["child_account_id"])
        if child is None:
            continue
        fam = db.families.get(child["family_id"])
        if fam is None or fam["status"] != "ACTIVE":
            continue

        amount = sched["amount_cents"]
        run = db.base_fields()
        run.update({
            "allowance_schedule_id": sched["id"],
            "amount_cents": amount,
            "ran_at": db.now_iso(),
        })
        if fam["funding_balance_cents"] >= amount:
            fam["funding_balance_cents"] -= amount
            db.touch(fam)
            jar = domain.jar_of_type(child["id"], sched["payout_jar_type"])
            domain.credit_jar(jar, amount)
            run["outcome"] = "EXECUTED"
        else:
            run["outcome"] = "SKIPPED_INSUFFICIENT_FUNDS"
        db.allowance_runs[run["id"]] = run

        # Advance next_run_at by cadence_days regardless of outcome.
        new_next = next_run + timedelta(days=sched["cadence_days"])
        sched["next_run_at"] = iso(new_next)
        db.touch(sched)
        created.append(run)

    return list_response([serialize.allowance_run(r) for r in created], request.args)


# ----------------------------- Logical clock -------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    identity = authenticate()
    require_role(identity, {"PlatformAdmin"})
    body = get_json_body()
    raw = validate.require_str(body, "to_iso8601")
    dt = parse_iso8601(raw)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO 8601 timestamp")
    db.clock.set(dt)
    return object_response({"current_utc": iso(dt)})
