"""CheckIn endpoints + revision/assessment state machine (PRD §3.6)."""

from flask import Blueprint, g

import errors
from db import db, new_id, now_ts
from clock import parse_iso8601, format_iso8601_ms
from helpers import (get_json_body, require_fields, parse_required_datetime,
                     pagination_params, paginate)
from middleware import require_roles
from response import success, list_success
from serializers import check_in_view
from services import domain
from services import calculations as calc

bp = Blueprint("check_ins", __name__)


def _published_program(engagement_id):
    """The engagement's PUBLISHED program supplying adherence denominators.

    Tests provision one PUBLISHED program per engagement; if several exist, use
    the most recently created one for determinism."""
    pubs = [
        p for p in db.program_assignments.values()
        if p["engagement_id"] == engagement_id and p["status"] == "PUBLISHED"
    ]
    if not pubs:
        return None
    pubs.sort(key=lambda p: (p["created_at"], p["_seq"]))
    return pubs[-1]


def _compute_adherence(check_in):
    """Compute the adherence score for a check-in over its window using the
    engagement's habit logs and PUBLISHED program denominators."""
    engagement_id = check_in["engagement_id"]
    program = _published_program(engagement_id)
    if program is None:
        planned_per_week = 0
        habit_target = 0
    else:
        planned_per_week = program["planned_workouts_per_week"]
        habit_target = program["habit_checks_target"]

    window_start = parse_iso8601(check_in["window_start_utc"])
    window_end = parse_iso8601(check_in["window_end_utc"])

    logs = [
        {"kind": h["kind"], "logged_at": parse_iso8601(h["logged_at"])}
        for h in db.habit_logs.values()
        if h["engagement_id"] == engagement_id
    ]
    return calc.adherence_score(window_start, window_end, planned_per_week, habit_target, logs)


@bp.route("/engagements/<engagement_id>/check-ins", methods=["POST"])
@require_roles("Client", "Trainer")
def create_check_in(engagement_id):
    engagement = domain.get_engagement(engagement_id)
    domain.assert_owns_engagement(engagement)

    body = get_json_body()
    require_fields(body, "measured_at", "weight_kg", "window_start_utc", "window_end_utc")
    measured_at = parse_required_datetime(body["measured_at"], "measured_at")
    weight_kg = body["weight_kg"]
    if isinstance(weight_kg, bool) or not isinstance(weight_kg, (int, float)) or weight_kg <= 0:
        raise errors.invalid_request("weight_kg must be a positive number")
    window_start = parse_required_datetime(body["window_start_utc"], "window_start_utc")
    window_end = parse_required_datetime(body["window_end_utc"], "window_end_utc")
    if not (window_end > window_start):
        raise errors.invalid_request("window_end_utc must be strictly after window_start_utc")

    photo_urls = body.get("photo_urls", [])
    if photo_urls is None:
        photo_urls = []
    if not isinstance(photo_urls, list) or not all(isinstance(u, str) for u in photo_urls):
        raise errors.invalid_request("photo_urls must be an array of strings")

    cid = new_id()
    ts = now_ts()
    check_in = {
        "id": cid,
        "engagement_id": engagement_id,
        "measured_at": format_iso8601_ms(measured_at),
        "weight_kg": weight_kg,
        "photo_urls": list(photo_urls),
        "window_start_utc": format_iso8601_ms(window_start),
        "window_end_utc": format_iso8601_ms(window_end),
        "adherence_score": 0,
        "status": "SUBMITTED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    check_in["adherence_score"] = _compute_adherence(check_in)
    db.check_ins[cid] = check_in
    return success(check_in_view(check_in), 201)


@bp.route("/check-ins/<check_in_id>", methods=["GET"])
@require_roles("Trainer", "Client")
def get_check_in(check_in_id):
    check_in = domain.get_check_in(check_in_id)
    engagement = domain.get_engagement(check_in["engagement_id"])
    domain.assert_owns_engagement(engagement)
    return success(check_in_view(check_in), 200)


@bp.route("/engagements/<engagement_id>/check-ins", methods=["GET"])
@require_roles("Trainer", "Client")
def list_check_ins(engagement_id):
    engagement = domain.get_engagement(engagement_id)
    domain.assert_owns_engagement(engagement)
    limit, offset = pagination_params()
    items = [c for c in db.check_ins.values() if c["engagement_id"] == engagement_id]
    items.sort(key=lambda c: (c["created_at"], c["_seq"]))
    page, total = paginate(items, limit, offset)
    return list_success([check_in_view(c) for c in page], limit, offset, total, 200)


@bp.route("/check-ins/<check_in_id>/request-revision", methods=["POST"])
@require_roles("Trainer")
def request_revision(check_in_id):
    check_in = domain.get_check_in(check_in_id)
    engagement = domain.get_engagement(check_in["engagement_id"])
    domain.assert_owns_engagement(engagement)
    if check_in["status"] != "SUBMITTED":
        raise errors.invalid_state(errors.ERR_INVALID_STATE, "Check-in is not SUBMITTED")
    check_in["status"] = "REVISION_REQUESTED"
    domain.touch(check_in)
    return success(check_in_view(check_in), 200)


@bp.route("/check-ins/<check_in_id>/resubmit", methods=["POST"])
@require_roles("Client")
def resubmit_check_in(check_in_id):
    check_in = domain.get_check_in(check_in_id)
    engagement = domain.get_engagement(check_in["engagement_id"])
    domain.assert_owns_engagement(engagement)
    if check_in["status"] != "REVISION_REQUESTED":
        raise errors.invalid_state(errors.ERR_INVALID_STATE, "Check-in is not REVISION_REQUESTED")

    body = get_json_body()
    if "weight_kg" in body and body["weight_kg"] is not None:
        weight_kg = body["weight_kg"]
        if isinstance(weight_kg, bool) or not isinstance(weight_kg, (int, float)) or weight_kg <= 0:
            raise errors.invalid_request("weight_kg must be a positive number")
        check_in["weight_kg"] = weight_kg
    if "photo_urls" in body and body["photo_urls"] is not None:
        photo_urls = body["photo_urls"]
        if not isinstance(photo_urls, list) or not all(isinstance(u, str) for u in photo_urls):
            raise errors.invalid_request("photo_urls must be an array of strings")
        check_in["photo_urls"] = list(photo_urls)

    check_in["status"] = "SUBMITTED"
    check_in["adherence_score"] = _compute_adherence(check_in)
    domain.touch(check_in)
    return success(check_in_view(check_in), 200)


@bp.route("/check-ins/<check_in_id>/assess", methods=["POST"])
@require_roles("Trainer")
def assess_check_in(check_in_id):
    check_in = domain.get_check_in(check_in_id)
    engagement = domain.get_engagement(check_in["engagement_id"])
    domain.assert_owns_engagement(engagement)
    if check_in["status"] != "SUBMITTED":
        raise errors.invalid_state(errors.ERR_INVALID_STATE, "Check-in is not SUBMITTED")

    check_in["status"] = "ASSESSED"
    domain.touch(check_in)

    # Side effects: recompute client latest weight + provisional macro plans.
    client = db.clients.get(engagement["client_id"])
    domain.recompute_latest_weight(client)
    domain.recompute_provisional_macro_plans(engagement["id"])
    return success(check_in_view(check_in), 200)
