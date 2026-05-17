"""Visit endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from ..auth import ROLE_BILLER, ROLE_CLINIC_ADMIN, ROLE_THERAPIST, require_roles
from ..helpers import (
    assert_integer,
    assert_string,
    occ_check,
    paginate,
    parse_iso8601,
    parse_pagination,
    require_json_object,
)
from ..responses import created, listing, ok
from ..services.lookups import get_episode_or_404, get_visit_or_404
from ..services.mutations import (
    cancel_visit,
    create_visit,
    sign_visit,
    start_visit,
    submit_claim,
)
from ..services.serialize import visit_to_dict
from ..store import store

bp = Blueprint("visits", __name__)


@bp.route("/episodes/<eid>/visits", methods=["POST"])
@require_roles(ROLE_THERAPIST)
def schedule_visit_route(eid: str, **_kwargs):
    body = require_json_object()
    poc_id = assert_string(body.get("plan_of_care_id"), "plan_of_care_id")
    auth_id = assert_string(body.get("authorization_id"), "authorization_id")
    clinician_id = assert_string(body.get("clinician_id"), "clinician_id")
    scheduled_start = parse_iso8601(body.get("scheduled_start"), "scheduled_start")
    scheduled_end = parse_iso8601(body.get("scheduled_end"), "scheduled_end")
    units_planned = assert_integer(body.get("units_planned"), "units_planned", minimum=1)
    s = store()
    with s.lock:
        episode = get_episode_or_404(eid)
        row = create_visit(
            episode,
            poc_id,
            auth_id,
            clinician_id,
            scheduled_start,
            scheduled_end,
            units_planned,
        )
    return created(visit_to_dict(row))


@bp.route("/visits/<vid>/start", methods=["POST"])
@require_roles(ROLE_THERAPIST)
def start_visit_route(vid: str, **_kwargs):
    body = require_json_object()
    s = store()
    with s.lock:
        visit = get_visit_or_404(vid)
        occ_check(body.get("version"), visit["version"])
        row = start_visit(visit)
    return ok(visit_to_dict(row))


@bp.route("/visits/<vid>/sign", methods=["POST"])
@require_roles(ROLE_THERAPIST)
def sign_visit_route(vid: str, *, _caller_id: str, _caller_role: str):
    body = require_json_object()
    timed_minutes = assert_integer(body.get("timed_minutes"), "timed_minutes", minimum=0)
    s = store()
    with s.lock:
        visit = get_visit_or_404(vid)
        occ_check(body.get("version"), visit["version"])
        row = sign_visit(visit, timed_minutes, _caller_id)
    return ok(visit_to_dict(row))


@bp.route("/visits/<vid>/submit-claim", methods=["POST"])
@require_roles(ROLE_BILLER)
def submit_claim_route(vid: str, **_kwargs):
    body = require_json_object()
    s = store()
    with s.lock:
        visit = get_visit_or_404(vid)
        occ_check(body.get("version"), visit["version"])
        row = submit_claim(visit)
    return ok(visit_to_dict(row))


@bp.route("/visits/<vid>/cancel", methods=["POST"])
@require_roles(ROLE_THERAPIST)
def cancel_visit_route(vid: str, **_kwargs):
    body = require_json_object()
    s = store()
    with s.lock:
        visit = get_visit_or_404(vid)
        occ_check(body.get("version"), visit["version"])
        row = cancel_visit(visit)
    return ok(visit_to_dict(row))


@bp.route("/visits/<vid>", methods=["GET"])
@require_roles(ROLE_CLINIC_ADMIN, ROLE_THERAPIST, ROLE_BILLER)
def get_visit_route(vid: str, **_kwargs):
    s = store()
    with s.lock:
        row = get_visit_or_404(vid)
    return ok(visit_to_dict(row))


@bp.route("/episodes/<eid>/visits", methods=["GET"])
@require_roles(ROLE_CLINIC_ADMIN, ROLE_THERAPIST, ROLE_BILLER)
def list_episode_visits(eid: str, **_kwargs):
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    s = store()
    with s.lock:
        get_episode_or_404(eid)
        items = [v for v in s.visits.values() if v["episode_id"] == eid]
        if status_filter is not None:
            items = [v for v in items if v.get("status") == status_filter]
        items.sort(key=lambda r: r["created_at"])
        total = len(items)
        page = paginate(items, limit, offset)
        out = [visit_to_dict(r) for r in page]
    return listing(out, total, limit, offset)
