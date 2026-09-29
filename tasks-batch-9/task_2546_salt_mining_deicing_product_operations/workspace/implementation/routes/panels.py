"""Panel layout, the recoverable reserve and the panel lifecycle."""

from flask import Blueprint, g

import db
import response
from db import store, touch
from errors import (
    ERR_GROUND_CONTROL_DEFECT_OPEN,
    ERR_HOIST_UNAVAILABLE,
    ERR_MINE_WITHDRAWAL_ORDER_ACTIVE,
    ERR_PANEL_INVALID_STATE,
    fail,
    invalid,
)
from middleware import auth
from services import calc, cascade, derive, serialize
from util import body, boolean, filter_bool, filter_str, number, require, text

bp = Blueprint("panels", __name__)


def _require_status(panel, allowed):
    if panel["status"] not in allowed:
        fail(ERR_PANEL_INVALID_STATE,
             "panel status %s does not admit this operation" % panel["status"])


@bp.post("/salt/panels")
@auth("MinePlanner")
def create_panel():
    payload = body()
    require(payload, ["mine_id", "panel_code", "gross_tons_in_place",
                      "extraction_ratio_pct", "grade_pct_nacl", "insolubles_pct"])
    panel_code = text(payload, "panel_code", minlen=1, maxlen=40)
    gross = number(payload, "gross_tons_in_place", gt=0)
    ratio = number(payload, "extraction_ratio_pct", gt=0, maxv=75)
    grade = number(payload, "grade_pct_nacl", minv=80, maxv=100)
    insolubles = number(payload, "insolubles_pct", minv=0, maxv=30)
    pillar = boolean(payload, "pillar_recovery_allowed", default=False)

    mine = derive.get_mine(payload["mine_id"])
    for peer in derive.panels_of_mine(mine["id"]):
        if peer["panel_code"] == panel_code:
            invalid("panel_code %s already exists on this mine" % panel_code)

    panel = db.stamp()
    panel.update({
        "mine_id": mine["id"],
        "panel_code": panel_code,
        "gross_tons_in_place": gross,
        "extraction_ratio_pct": ratio,
        "grade_pct_nacl": grade,
        "insolubles_pct": insolubles,
        "pillar_recovery_allowed": bool(pillar),
        "status": "PLANNED",
        "open_defect": False,
        "suspended_by_user_id": None,
    })
    panel["recoverable_tons"] = calc.panel_recoverable_tons(panel, mine)
    store.panels[panel["id"]] = panel
    return response.created(serialize.panel_json(panel))


@bp.get("/salt/panels/<panel_id>")
@auth()
def read_panel(panel_id):
    return response.ok(serialize.panel_json(derive.get_panel(panel_id)))


@bp.get("/salt/panels")
@auth()
def list_panels():
    rows = list(store.panels.values())
    mine_id = filter_str("mine_id")
    status = filter_str("status")
    open_defect = filter_bool("open_defect")
    if mine_id is not None:
        rows = [r for r in rows if r["mine_id"] == mine_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if open_defect is not None:
        rows = [r for r in rows if r["open_defect"] == open_defect]
    return response.page(db.by_seq(rows), serialize.panel_json)


@bp.post("/salt/panels/<panel_id>/develop")
@auth("MinePlanner")
def develop_panel(panel_id):
    panel = derive.get_panel(panel_id)
    mine = derive.get_mine(panel["mine_id"])
    _require_status(panel, ("PLANNED",))
    if mine["compliance_state"] == "WITHDRAWAL_ORDER":
        fail(ERR_MINE_WITHDRAWAL_ORDER_ACTIVE,
             "the mine is under a withdrawal order")
    panel["status"] = "DEVELOPED"
    touch(panel)
    return response.ok(serialize.panel_json(panel))


@bp.post("/salt/panels/<panel_id>/start-production")
@auth("MinePlanner")
def start_production(panel_id):
    panel = derive.get_panel(panel_id)
    mine = derive.get_mine(panel["mine_id"])
    _require_status(panel, ("DEVELOPED", "SUSPENDED"))
    if mine["compliance_state"] != "COMPLIANT":
        fail(ERR_MINE_WITHDRAWAL_ORDER_ACTIVE,
             "the mine's compliance_state must be COMPLIANT to start production")
    if mine["hoist_state"] == "HOIST_DOWN":
        fail(ERR_HOIST_UNAVAILABLE, "the mine's shaft is down")
    if panel["open_defect"]:
        fail(ERR_GROUND_CONTROL_DEFECT_OPEN,
             "the panel carries an open ground-control defect")

    panel["status"] = "PRODUCING"
    panel["suspended_by_user_id"] = None
    touch(panel)
    touch(mine)
    return response.ok(serialize.panel_json(panel))


@bp.post("/salt/panels/<panel_id>/suspend")
@auth("GroundControlEngineer", "ComplianceOfficer")
def suspend_panel(panel_id):
    payload = body()
    require(payload, ["reason"])
    panel = derive.get_panel(panel_id)
    mine = derive.get_mine(panel["mine_id"])
    _require_status(panel, ("PRODUCING",))

    panel["status"] = "SUSPENDED"
    panel["suspended_by_user_id"] = g.user_id
    touch(panel)
    cascade.panel_left_production(mine, panel)
    return response.ok(serialize.panel_json(panel))


@bp.post("/salt/panels/<panel_id>/remediate-defect")
@auth("GroundControlEngineer")
def remediate_defect(panel_id):
    payload = body()
    require(payload, ["remediation_note"])
    panel = derive.get_panel(panel_id)
    panel["open_defect"] = False
    touch(panel)
    return response.ok(serialize.panel_json(panel))


@bp.post("/salt/panels/<panel_id>/deplete")
@auth("MinePlanner")
def deplete_panel(panel_id):
    panel = derive.get_panel(panel_id)
    mine = derive.get_mine(panel["mine_id"])
    _require_status(panel, ("PRODUCING", "SUSPENDED"))
    cascade.terminate_panel(mine, panel, "DEPLETED")
    return response.ok(serialize.panel_json(panel))


@bp.post("/salt/panels/<panel_id>/abandon")
@auth("MinePlanner", "ComplianceOfficer")
def abandon_panel(panel_id):
    payload = body()
    require(payload, ["reason"])
    panel = derive.get_panel(panel_id)
    mine = derive.get_mine(panel["mine_id"])
    _require_status(panel, ("PLANNED", "DEVELOPED", "PRODUCING", "SUSPENDED"))
    cascade.terminate_panel(mine, panel, "ABANDONED")
    return response.ok(serialize.panel_json(panel))
