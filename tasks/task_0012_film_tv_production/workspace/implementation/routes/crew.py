"""Crew assignment routes."""
from flask import Blueprint, g

import errors as E
from db import store, init_common, touch
from middleware import require_roles
from response import ok_object
from body import get_json_body, require_string, require_int
from services.occ import check_version
from services.serializers import serialize_crew_assignment


bp = Blueprint("crew", __name__)


def _get_production(pid):
    p = store.productions.get(pid)
    if not p:
        E.not_found(f"Production {pid} not found")
    return p


def _get_crew(pid, cid):
    ca = store.crew_assignments.get(cid)
    if not ca or ca["production_id"] != pid:
        E.not_found(f"CrewAssignment {cid} not found in production {pid}")
    return ca


@bp.route("/productions/<pid>/crew-assignments", methods=["POST"])
@require_roles("LineProducer")
def create_crew(pid):
    body = get_json_body()
    p = _get_production(pid)
    if p.get("posture") == "FROZEN":
        E.posture_blocked("Production posture is FROZEN")
    crew_user_id = require_string(body, "crew_user_id")
    role_label = require_string(body, "role_label")
    rate = require_int(body, "day_rate_cents", minv=0)
    days = require_int(body, "scheduled_days", minv=0)
    rec = {
        "production_id": pid,
        "crew_user_id": crew_user_id,
        "role_label": role_label,
        "day_rate_cents": rate,
        "scheduled_days": days,
        "actual_days": 0,
        "payroll_cents": 0,
        "status": "BOOKED",
    }
    init_common(rec)
    store.crew_assignments[rec["id"]] = rec
    return ok_object(serialize_crew_assignment(rec), http_status=201)


@bp.route("/productions/<pid>/crew-assignments/<cid>/actual-days", methods=["PATCH"])
@require_roles("LineProducer")
def patch_actual_days(pid, cid):
    body = get_json_body()
    with store.lock:
        p = _get_production(pid)
        ca = _get_crew(pid, cid)
        check_version(ca, body)
        if p.get("posture") == "FROZEN":
            E.posture_blocked("Production posture is FROZEN")
        actual = require_int(body, "actual_days", minv=0)
        ca["actual_days"] = actual
        touch(ca)
        return ok_object(serialize_crew_assignment(ca))
