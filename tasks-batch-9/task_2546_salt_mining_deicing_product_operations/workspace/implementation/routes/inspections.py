"""Append-only ground-control inspections and the four-hop defect cascade."""

from flask import Blueprint, g

import db
import response
from db import store, touch
from middleware import auth
from services import calc, cascade, derive, serialize
from util import body, enum, filter_bool, filter_str, number, require

bp = Blueprint("inspections", __name__)

FINDINGS = ("PASS", "ADVISORY", "DEFECT")


@bp.post("/salt/ground-control-inspections")
@auth("GroundControlEngineer")
def create_inspection():
    payload = body()
    require(payload, ["panel_id", "roof_span_ft", "convergence_rate_in_per_day",
                      "finding"])
    finding = enum(payload, "finding", FINDINGS)
    roof_span = number(payload, "roof_span_ft", gt=0, maxv=120)
    convergence = number(payload, "convergence_rate_in_per_day", minv=0)

    panel = derive.get_panel(payload["panel_id"])
    mine = derive.get_mine(panel["mine_id"])

    inspection = db.stamp()
    inspection.pop("version", None)
    inspection.pop("updated_at", None)
    inspection.update({
        "panel_id": panel["id"],
        "roof_span_ft": roof_span,
        "convergence_rate_in_per_day": convergence,
        "finding": finding,
        "inspector_user_id": g.user_id,
        "caused_suspension": False,
    })
    store.inspections[inspection["id"]] = inspection

    if finding == "DEFECT":
        # ---- hop 1: the panel
        panel["open_defect"] = True
        left_production = panel["status"] == "PRODUCING"
        if left_production:
            panel["status"] = "SUSPENDED"
            panel["suspended_by_user_id"] = g.user_id
            inspection["caused_suspension"] = True
        touch(panel)

        # ---- hops 2 through 4
        if left_production:
            cascade.panel_left_production(mine, panel)

        # ---- the third defect ends the panel
        if derive.panel_defect_count(panel["id"]) >= 3 and panel["status"] == "SUSPENDED":
            cascade.terminate_panel(mine, panel, "ABANDONED", bump_mine=False)

    return response.created(serialize.inspection_json(inspection))


@bp.get("/salt/ground-control-inspections/<inspection_id>")
@auth()
def read_inspection(inspection_id):
    return response.ok(
        serialize.inspection_json(derive.get_inspection(inspection_id)))


@bp.get("/salt/ground-control-inspections")
@auth()
def list_inspections():
    rows = list(store.inspections.values())
    panel_id = filter_str("panel_id")
    finding = filter_str("finding")
    caused = filter_bool("caused_suspension")
    if panel_id is not None:
        rows = [r for r in rows if r["panel_id"] == panel_id]
    if finding is not None:
        rows = [r for r in rows if r["finding"] == finding]
    if caused is not None:
        rows = [r for r in rows if r["caused_suspension"] == caused]
    return response.page(db.by_seq_desc(rows), serialize.inspection_json)
