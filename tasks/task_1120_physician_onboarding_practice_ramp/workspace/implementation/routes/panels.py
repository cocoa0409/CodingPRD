"""Panel endpoints (PRD 3.6)."""

from flask import Blueprint, request

import domain as D
from db import store, bump, fmt_clock
from errors import (
    ApiError, ERR_PANEL_NOT_FOUND, ERR_PANEL_NOT_OPEN, ERR_PANEL_NOT_FROZEN,
    ERR_POSTURE_NOT_READY, ERR_START_DATE_NOT_REACHED,
    ERR_PANEL_CAPACITY_EXCEEDED, ERR_NEGATIVE_CENSUS,
)
from middleware import get_context, require_role
from response import success_object, paginate

bp = Blueprint("panels", __name__)


def _get_panel(pid):
    panel = store.panels.get(pid)
    if panel is None:
        raise ApiError(ERR_PANEL_NOT_FOUND, 404, "Panel not found")
    return panel


@bp.route("/onboarding/panels/<pid>", methods=["GET"])
def get_panel(pid):
    get_context()
    return success_object(D.serialize_panel(_get_panel(pid)))


@bp.route("/onboarding/panels", methods=["GET"])
def list_panels():
    get_context()
    case_id = request.args.get("onboarding_case_id")
    status = request.args.get("status")
    records = sorted(store.panels.values(), key=lambda r: r["_seq"])
    if case_id is not None:
        records = [r for r in records if r["onboarding_case_id"] == case_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return paginate([D.serialize_panel(r) for r in records], request.args)


@bp.route("/onboarding/panels/<pid>/open", methods=["POST"])
def open_panel(pid):
    _uid, role = get_context()
    require_role(role, ["PracticeManager"])
    panel = _get_panel(pid)
    if panel["status"] != "NOT_OPEN":
        raise ApiError(ERR_PANEL_NOT_OPEN, 409, "Panel must be NOT_OPEN to open")
    case = store.cases.get(panel["onboarding_case_id"])
    D.recompute_posture(case)
    if case["posture"] != "GO_LIVE_READY":
        raise ApiError(ERR_POSTURE_NOT_READY, 409,
                       "Case posture must be GO_LIVE_READY to open the panel")
    actual_start = D.parse_date(case["actual_start_date"], "actual_start_date")
    if D.clock_date() < actual_start:
        raise ApiError(ERR_START_DATE_NOT_REACHED, 422,
                       "The logical clock has not reached the actual start date")
    panel["status"] = "OPEN"
    panel["opened_at"] = fmt_clock(D.clock())
    bump(panel)
    case["case_status"] = "HIRED"
    case["posture"] = "LIVE"
    bump(case)
    physician = store.physicians.get(case["physician_id"])
    if physician is not None and physician["status"] == "ONBOARDING":
        physician["status"] = "ACTIVE"
        bump(physician)
    return success_object(D.serialize_panel(panel))


@bp.route("/onboarding/panels/<pid>/freeze", methods=["POST"])
def freeze_panel(pid):
    _uid, role = get_context()
    require_role(role, ["PracticeManager"])
    panel = _get_panel(pid)
    if panel["status"] != "OPEN":
        raise ApiError(ERR_PANEL_NOT_OPEN, 409, "Only an OPEN panel can be frozen")
    panel["status"] = "FROZEN"
    bump(panel)
    case = store.cases.get(panel["onboarding_case_id"])
    if case is not None:
        D.recompute_posture(case)
        bump(case)
    return success_object(D.serialize_panel(panel))


@bp.route("/onboarding/panels/<pid>/unfreeze", methods=["POST"])
def unfreeze_panel(pid):
    _uid, role = get_context()
    require_role(role, ["PracticeManager"])
    panel = _get_panel(pid)
    if panel["status"] != "FROZEN":
        raise ApiError(ERR_PANEL_NOT_FROZEN, 409, "Only a FROZEN panel can be unfrozen")
    case = store.cases.get(panel["onboarding_case_id"])
    ready = D.components_ready(case)
    if ready and case["actual_start_date"] is not None:
        ready = D.clock_date() >= D.parse_date(case["actual_start_date"], "actual_start_date")
    if not ready:
        raise ApiError(ERR_POSTURE_NOT_READY, 409,
                       "All readiness components must hold to unfreeze the panel")
    panel["status"] = "OPEN"
    bump(panel)
    if case is not None:
        case["posture"] = "LIVE"
        bump(case)
    return success_object(D.serialize_panel(panel))


@bp.route("/onboarding/panels/<pid>/census-adjustments", methods=["POST"])
def census_adjustment(pid):
    _uid, role = get_context()
    require_role(role, ["PracticeManager"])
    panel = _get_panel(pid)
    body = D.get_body()
    delta = D.req_int(body, "delta")
    if panel["status"] != "OPEN":
        raise ApiError(ERR_PANEL_NOT_OPEN, 409,
                       "Census adjustments apply only while the panel is OPEN")
    new_size = panel["current_size"] + delta
    if new_size > panel["capacity"]:
        raise ApiError(ERR_PANEL_CAPACITY_EXCEEDED, 422,
                       "Census may not exceed the panel capacity")
    if new_size < 0:
        raise ApiError(ERR_NEGATIVE_CENSUS, 422, "Census may not fall below zero")
    panel["current_size"] = new_size
    bump(panel)
    return success_object(D.serialize_panel(panel))
