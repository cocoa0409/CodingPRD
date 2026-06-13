"""Panel endpoints: get, seat, dismiss, list-assignments; plus PanelAssignment
get and excuse-from-panel.

Seat validation order (PRD §4 / §1.4 priorities): existence (panel + body summons,
20) -> panel state FORMING (21) -> term OPEN (30) -> trial READY (32) ->
summons REPORTING (33) -> panel full (50) -> OCC expected_panel_version (70).
Pure body-shape validation (ERR_INVALID_REQUEST, 80) is last.
"""
from flask import Blueprint, request

import db
import errors
import helpers
import serializers
from middleware import get_identity, require_roles
from response import success
from services import core

bp = Blueprint("panels", __name__)


# ---------------------------------------------------------------------------
# GET /panels/{id}
# ---------------------------------------------------------------------------
@bp.route("/panels/<panel_id>", methods=["GET"])
def get_panel(panel_id):
    _, role = get_identity()
    require_roles(role, {"JuryAdministrator", "CourtClerk", "Judge"})

    p = core.get_panel(panel_id)
    if p is None:
        raise errors.err("ERR_NOT_FOUND", "Panel not found")
    return success(serializers.panel(p), status=200)


# ---------------------------------------------------------------------------
# POST /panels/{id}/seat  (Judge)
# ---------------------------------------------------------------------------
@bp.route("/panels/<panel_id>/seat", methods=["POST"])
def seat(panel_id):
    _, role = get_identity()
    require_roles(role, {"Judge"})

    panel = core.get_panel(panel_id)
    if panel is None:
        raise errors.err("ERR_NOT_FOUND", "Panel not found")

    body = helpers.get_body()

    # Body-referenced summons existence (priority 20). Pull the raw value; a
    # missing/blank summons_id is a 422 body issue (priority 80, last), but a
    # supplied id that does not resolve is a 404 (priority 20).
    summons_id = body.get("summons_id")
    if summons_id is not None and summons_id != "":
        summons = db.summonses.get(summons_id)
        if summons is None:
            raise errors.err("ERR_NOT_FOUND", "Summons not found")
    else:
        summons = None

    term = db.service_terms[panel["service_term_id"]]
    trial = db.trials.get(panel["trial_id"])

    # Panel state (priority 21): must be FORMING.
    if panel["status"] != "FORMING":
        raise errors.err("ERR_INVALID_STATE", "Panel is not FORMING")

    # Term open (priority 30).
    if term["status"] != "OPEN":
        raise errors.err("ERR_TERM_NOT_OPEN", "Term must be OPEN to seat")

    # Trial ready (priority 32).
    if trial is None or trial["status"] != "READY":
        raise errors.err("ERR_TRIAL_NOT_READY", "Panel's trial is not READY")

    # Summons reporting (priority 33). (summons existence already checked.)
    if summons is None or summons["status"] != "REPORTING":
        if summons is None:
            # summons_id was absent — body validation (priority 80) handles it.
            helpers.require_string(body, "summons_id")
        raise errors.err("ERR_SUMMONS_NOT_REPORTING", "Summons being seated is not REPORTING")

    # Panel full (priority 50).
    if core.panel_seated_count(panel_id) >= panel["target_size"]:
        raise errors.err("ERR_PANEL_FULL", "Panel is already full")

    # OCC (priority 70): expected_panel_version must equal panel.version.
    expected_version = body.get("expected_panel_version")
    if expected_version is None:
        # Missing OCC field — body validation (priority 80).
        helpers.require_int(body, "expected_panel_version")
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        helpers.require_int(body, "expected_panel_version")
    if expected_version != panel["version"]:
        raise errors.err("ERR_STALE_PANEL_VERSION", "Stale panel version")

    # Commit seat.
    seat_index = core.panel_seated_count(panel_id) + 1
    assignment = core.create_panel_assignment(panel_id, summons_id, seat_index)
    panel["seated_count"] = core.panel_seated_count(panel_id)
    core.touch(panel)  # version increments by one per seat (PRD §2.6/§3.7)

    summons["status"] = "SERVING"
    core.touch(summons)

    # Auto-fill: panel reaches target_size -> SEATED; trial READY -> IN_TRIAL;
    # ESTIMATED voucher for every SEATED summons on the panel.
    if core.panel_seated_count(panel_id) == panel["target_size"]:
        panel["status"] = "SEATED"
        core.touch(panel)
        if trial["status"] == "READY":
            trial["status"] = "IN_TRIAL"
            core.touch(trial)
        for a in db.panel_assignments.values():
            if a["panel_id"] == panel_id and a["status"] == "SEATED":
                seated_summons = db.summonses.get(a["summons_id"])
                if seated_summons is not None:
                    core.issue_estimated_voucher(seated_summons)

    return success(serializers.panel_assignment(assignment), status=201)


# ---------------------------------------------------------------------------
# POST /panels/{id}/dismiss  (Judge)
# ---------------------------------------------------------------------------
@bp.route("/panels/<panel_id>/dismiss", methods=["POST"])
def dismiss(panel_id):
    _, role = get_identity()
    require_roles(role, {"Judge"})

    panel = core.get_panel(panel_id)
    if panel is None:
        raise errors.err("ERR_NOT_FOUND", "Panel not found")

    trial = db.trials.get(panel["trial_id"])

    if panel["status"] == "SEATED":
        # SEATED -> DISMISSED; trial IN_TRIAL -> ADJOURNED; seated summonses stay
        # SERVING (no auto-release).
        panel["status"] = "DISMISSED"
        core.touch(panel)
        if trial is not None and trial["status"] == "IN_TRIAL":
            trial["status"] = "ADJOURNED"
            core.touch(trial)
    elif panel["status"] == "FORMING":
        # FORMING -> DISMISSED; cascade: every SEATED assignment ->
        # EXCUSED_FROM_PANEL; each occupying summons SERVING -> REPORTING;
        # seated_count reset; version bump.
        for a in db.panel_assignments.values():
            if a["panel_id"] == panel_id and a["status"] == "SEATED":
                a["status"] = "EXCUSED_FROM_PANEL"
                core.touch(a)
                s = db.summonses.get(a["summons_id"])
                if s is not None and s["status"] == "SERVING":
                    s["status"] = "REPORTING"
                    core.touch(s)
        panel["status"] = "DISMISSED"
        panel["seated_count"] = 0
        core.touch(panel)
    else:
        raise errors.err("ERR_INVALID_STATE", "Panel cannot be dismissed from its current state")

    return success(serializers.panel(panel), status=200)


# ---------------------------------------------------------------------------
# GET /panels/{id}/assignments
# ---------------------------------------------------------------------------
@bp.route("/panels/<panel_id>/assignments", methods=["GET"])
def list_panel_assignments(panel_id):
    _, role = get_identity()
    require_roles(role, {"JuryAdministrator", "CourtClerk", "Judge"})

    p = core.get_panel(panel_id)
    if p is None:
        raise errors.err("ERR_NOT_FOUND", "Panel not found")

    status = request.args.get("status")
    rows = [a for a in db.panel_assignments.values() if a["panel_id"] == panel_id]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]

    data, meta = helpers.paginate(rows, serializers.panel_assignment)
    return success(data, status=200, pagination=meta)


# ---------------------------------------------------------------------------
# GET /panel-assignments/{id}
# ---------------------------------------------------------------------------
@bp.route("/panel-assignments/<assignment_id>", methods=["GET"])
def get_assignment(assignment_id):
    _, role = get_identity()
    require_roles(role, {"JuryAdministrator", "CourtClerk", "Judge"})

    a = core.get_assignment(assignment_id)
    if a is None:
        raise errors.err("ERR_NOT_FOUND", "Panel assignment not found")
    return success(serializers.panel_assignment(a), status=200)


# ---------------------------------------------------------------------------
# POST /panel-assignments/{id}/excuse-from-panel  (Judge)
# ---------------------------------------------------------------------------
@bp.route("/panel-assignments/<assignment_id>/excuse-from-panel", methods=["POST"])
def excuse_from_panel(assignment_id):
    _, role = get_identity()
    require_roles(role, {"Judge"})

    a = core.get_assignment(assignment_id)
    if a is None:
        raise errors.err("ERR_NOT_FOUND", "Panel assignment not found")

    panel = db.panels.get(a["panel_id"])

    # State (priority 21): assignment SEATED and panel still FORMING.
    if a["status"] != "SEATED":
        raise errors.err("ERR_INVALID_STATE", "Assignment is not SEATED")
    if panel is None or panel["status"] != "FORMING":
        raise errors.err("ERR_INVALID_STATE", "Cannot pull a seat from a non-FORMING panel")

    a["status"] = "EXCUSED_FROM_PANEL"
    core.touch(a)

    panel["seated_count"] = core.panel_seated_count(panel["id"])
    core.touch(panel)  # version increments by one (PRD §3.9)

    summons = db.summonses.get(a["summons_id"])
    if summons is not None and summons["status"] == "SERVING":
        summons["status"] = "REPORTING"
        core.touch(summons)

    return success(serializers.panel_assignment(a), status=200)
