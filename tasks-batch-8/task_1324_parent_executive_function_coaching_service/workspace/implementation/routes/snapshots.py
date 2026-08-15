"""ProgressSnapshot endpoints: compute + store both index variants, list."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import db
import errors as E
import middleware as mw
from middleware import (get_auth, require_roles, require_family_scope,
                        require_coach_scope, get_entity, touch, snapshot_pub,
                        list_response)
from response import success_object

bp = Blueprint("snapshots", __name__)

ROLLING_WINDOW = timedelta(days=28)
REVISION_THRESHOLD = 40


def _components(client_id, plan_filter, window):
    """Compute (goals_considered, goals_achieved, checkins_considered, checkins_on_time)."""
    window_start, window_end = window  # None bounds => unbounded
    plan_ids = None
    if plan_filter is not None:
        plan_ids = {plan_filter}
    else:
        plan_ids = {p["id"] for p in db.plans.values() if p["client_id"] == client_id}

    def in_window(dt):
        if dt is None:
            return False
        if window_start is not None and dt < window_start:
            return False
        if window_end is not None and dt > window_end:
            return False
        return True

    goals_considered = 0
    goals_achieved = 0
    for g in db.goals.values():
        if g["plan_id"] not in plan_ids:
            continue
        if g["status"] in ("ACHIEVED", "DROPPED", "CARRIED_FORWARD") and in_window(g["resolved_at_dt"]):
            goals_considered += 1
            if g["status"] == "ACHIEVED":
                goals_achieved += 1

    checkins_considered = 0
    checkins_on_time = 0
    for c in db.checkins.values():
        if c["plan_id"] not in plan_ids:
            continue
        if c["status"] == "PENDING":
            continue
        resolution = c["submitted_at_dt"] if c["submitted_at_dt"] is not None else c["updated_dt"]
        if not in_window(resolution):
            continue
        checkins_considered += 1
        if (c["status"] in ("SUBMITTED_ON_TIME", "ACKNOWLEDGED")
                and c["submitted_at_dt"] is not None
                and c["submitted_at_dt"] <= c["due_at_dt"]):
            checkins_on_time += 1

    return goals_considered, goals_achieved, checkins_considered, checkins_on_time


def _index(goals_considered, goals_achieved, checkins_considered, checkins_on_time):
    goal_rate = (Decimal(goals_achieved) / Decimal(goals_considered)) if goals_considered else None
    checkin_rate = (Decimal(checkins_on_time) / Decimal(checkins_considered)) if checkins_considered else None
    if goal_rate is None and checkin_rate is None:
        return None
    if goal_rate is None:
        return mw.rhu(Decimal(100) * checkin_rate)
    if checkin_rate is None:
        return mw.rhu(Decimal(100) * goal_rate)
    blended = Decimal("0.6") * goal_rate + Decimal("0.4") * checkin_rate
    return mw.rhu(Decimal(100) * blended)


@bp.post("/clients/<cid>/progress-snapshots")
def create_snapshot(cid):
    auth = get_auth()
    require_roles(auth, ["Coach"])
    client = get_entity("client", cid)
    if client["active_plan_id"] is None or client["active_plan_id"] not in db.plans:
        E.raise_error(E.ERR_PLAN_NOT_ACTIVE, "Client has no ACTIVE plan")
    plan = db.plans[client["active_plan_id"]]
    require_coach_scope(auth, plan["coach_id"])

    now = db.clock
    window_start = now - ROLLING_WINDOW
    rg, rga, rc, rco = _components(cid, plan["id"], (window_start, now))
    rolling = _index(rg, rga, rc, rco)
    cg, cga, cc, cco = _components(cid, plan["id"], (None, None))
    cumulative = _index(cg, cga, cc, cco)

    snap = {
        "id": db.new_id(),
        "created_at": db.now_iso(),
        "seq": db.next_seq(),
        "client_id": cid,
        "window_start": db.iso(window_start),
        "window_end": db.iso(now),
        "goals_considered": rg,
        "goals_achieved": rga,
        "checkins_considered": rc,
        "checkins_on_time": rco,
        "rolling_index": rolling,
        "cumulative_index": cumulative,
    }
    db.snapshots[snap["id"]] = snap

    client["rolling_progress_index"] = rolling
    client["cumulative_progress_index"] = cumulative
    touch(client)

    # Revision trigger: last two snapshots both non-null and < 40.
    snaps = sorted(
        (s for s in db.snapshots.values() if s["client_id"] == cid),
        key=lambda s: (s["created_at"], s["seq"]),
    )
    if len(snaps) >= 2:
        a, b = snaps[-2], snaps[-1]
        if (a["rolling_index"] is not None and b["rolling_index"] is not None
                and a["rolling_index"] < REVISION_THRESHOLD
                and b["rolling_index"] < REVISION_THRESHOLD):
            if not plan["revision_recommended"]:
                plan["revision_recommended"] = True
                touch(plan)

    return success_object(snapshot_pub(snap), 201)


@bp.get("/clients/<cid>/progress-snapshots")
def list_snapshots(cid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin", "Coach", "FamilyMember"])
    client = get_entity("client", cid)
    require_family_scope(auth, client["family_id"])
    rows = [s for s in db.snapshots.values() if s["client_id"] == cid]
    return list_response(rows, snapshot_pub, paginate=False)
