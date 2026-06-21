"""ProductionLine, SanitationEvent, and Crew endpoints (PRD §3.3, §3.7)."""
from flask import Blueprint

import db
import errors
import response
import serializers
import util
from middleware import require_role, ALL_ROLES

bp = Blueprint("lines", __name__)


# ---------------------------------------------------------------------------
# Production lines
# ---------------------------------------------------------------------------
@bp.route("/copack/production-lines", methods=["POST"])
@require_role("Scheduler")
def create_line():
    body = util.get_json_body()
    util.require_fields(body, "name", "rated_units_per_hour")
    name = body["name"]
    rated = body["rated_units_per_hour"]
    changeover = body.get("changeover_minutes", 30)

    if not isinstance(name, str):
        raise errors.invalid_request("name must be a string")
    if not util.is_number(rated):
        raise errors.invalid_request("rated_units_per_hour must be a number")
    if changeover is None:
        changeover = 30
    if not util.is_int(changeover):
        raise errors.invalid_request("changeover_minutes must be an integer")

    # priority 8: rated > 0, changeover >= 0.
    if rated <= 0:
        raise errors.invalid_quantity("rated_units_per_hour must be > 0")
    if changeover < 0:
        raise errors.invalid_quantity("changeover_minutes must be >= 0")

    rec = db.new_full_record({
        "name": name,
        "rated_units_per_hour": rated,
        "changeover_minutes": changeover,
        "current_allergen_residue": [],
        # tracks whether a sanitation cleared the line since its last STARTED run
        "_sanitized_since_last_run": False,
    })
    db.production_lines[rec["id"]] = rec
    return response.success(serializers.production_line(rec), status=201)


@bp.route("/copack/production-lines/<lid>", methods=["GET"])
@require_role(*ALL_ROLES)
def get_line(lid):
    rec = db.production_lines.get(lid)
    if rec is None:
        raise errors.not_found("Production line not found")
    return response.success(serializers.production_line(rec), status=200)


@bp.route("/copack/production-lines", methods=["GET"])
@require_role(*ALL_ROLES)
def list_lines():
    limit, offset = util.parse_pagination()
    items = util.sort_by_creation(list(db.production_lines.values()))
    window, meta = util.paginate(items, limit, offset)
    return response.success([serializers.production_line(r) for r in window], status=200, pagination=meta)


@bp.route("/copack/production-lines/<lid>/sanitation-events", methods=["POST"])
@require_role("QAInspector")
def create_sanitation_event(lid):
    line = db.production_lines.get(lid)
    if line is None:
        raise errors.not_found("Production line not found")

    cleared = list(line.get("current_allergen_residue", []))
    rec = db.new_append_record({
        "line_id": lid,
        "cleared_allergens": cleared,
    })
    db.sanitation_events[rec["id"]] = rec

    # empty the line's residue; mark sanitized since last run; bump line version.
    line["current_allergen_residue"] = []
    line["_sanitized_since_last_run"] = True
    db.touch(line)

    return response.success(serializers.sanitation_event(rec), status=201)


@bp.route("/copack/production-lines/<lid>/sanitation-events", methods=["GET"])
@require_role(*ALL_ROLES)
def list_sanitation_events(lid):
    line = db.production_lines.get(lid)
    if line is None:
        raise errors.not_found("Production line not found")
    limit, offset = util.parse_pagination()
    items = [s for s in db.sanitation_events.values() if s["line_id"] == lid]
    items = util.sort_by_creation(items)
    window, meta = util.paginate(items, limit, offset)
    return response.success([serializers.sanitation_event(r) for r in window], status=200, pagination=meta)


# ---------------------------------------------------------------------------
# Crews
# ---------------------------------------------------------------------------
@bp.route("/copack/crews", methods=["POST"])
@require_role("Scheduler")
def create_crew():
    body = util.get_json_body()
    util.require_fields(body, "name")
    name = body["name"]
    rest = body.get("rest_buffer_minutes", 15)

    if not isinstance(name, str):
        raise errors.invalid_request("name must be a string")
    if rest is None:
        rest = 15
    if not util.is_int(rest):
        raise errors.invalid_request("rest_buffer_minutes must be an integer")

    # priority 8: rest_buffer_minutes >= 0.
    if rest < 0:
        raise errors.invalid_quantity("rest_buffer_minutes must be >= 0")

    rec = db.new_full_record({
        "name": name,
        "rest_buffer_minutes": rest,
    })
    db.crews[rec["id"]] = rec
    return response.success(serializers.crew(rec), status=201)


@bp.route("/copack/crews/<cid>", methods=["GET"])
@require_role(*ALL_ROLES)
def get_crew(cid):
    rec = db.crews.get(cid)
    if rec is None:
        raise errors.not_found("Crew not found")
    return response.success(serializers.crew(rec), status=200)


@bp.route("/copack/crews", methods=["GET"])
@require_role(*ALL_ROLES)
def list_crews():
    limit, offset = util.parse_pagination()
    items = util.sort_by_creation(list(db.crews.values()))
    window, meta = util.paginate(items, limit, offset)
    return response.success([serializers.crew(r) for r in window], status=200, pagination=meta)
