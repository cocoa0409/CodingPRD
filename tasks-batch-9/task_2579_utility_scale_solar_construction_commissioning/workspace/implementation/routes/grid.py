"""Substation construction, energization and utility outage coordination."""

from flask import Blueprint

import calc
import clock
import envelope
import store
import validate
from errors import fail
from routes.common import filter_eq, paginate, unique_check
from validate import ALL_ROLES, authorize, body, dt, e, n, s

bp = Blueprint("grid", __name__)

SUBSTATION_ORDER = (
    "SITE_CIVIL",
    "STEEL_ERECTED",
    "EQUIPMENT_SET",
    "BACKFEED_REQUESTED",
    "ENERGIZED",
)
PURPOSES = ("BACKFEED", "SWITCHING", "TIE_IN")


@bp.post("/solar/projects/<project_id>/substations")
def create_substation(project_id):
    authorize("UtilityCoordinator")
    data = body(
        s("substation_code"),
        n("interconnection_voltage_kv", gt=0),
        n("mv_collection_km", ge=0),
    )
    store.require_project(project_id)
    unique_check(
        store.substations, "project_id", project_id, "substation_code", data["substation_code"]
    )
    row = store.base()
    row.update(
        {
            "project_id": project_id,
            "substation_code": data["substation_code"],
            "interconnection_voltage_kv": data["interconnection_voltage_kv"],
            "mv_collection_km": data["mv_collection_km"],
            "status": "SITE_CIVIL",
            "utility_witness_ref": None,
            "energized_at": None,
            "energizing_outage_window_id": None,
        }
    )
    store.substations[row["id"]] = row
    return envelope.created(row)


@bp.get("/solar/substations/<substation_id>")
def get_substation(substation_id):
    authorize(*ALL_ROLES)
    return envelope.ok(store.require_substation(substation_id))


@bp.get("/solar/projects/<project_id>/substations")
def list_substations(project_id):
    authorize(*ALL_ROLES)
    store.require_project(project_id)
    rows = store.children(store.substations, "project_id", project_id)
    rows = filter_eq(rows, "status", validate.q("status"))
    return paginate(rows)


@bp.post("/solar/substations/<substation_id>/status-advances")
def advance_substation(substation_id):
    authorize("UtilityCoordinator")
    data = body(e("to_status", SUBSTATION_ORDER), s("utility_witness_ref"))
    substation = store.require_substation(substation_id)
    current = SUBSTATION_ORDER.index(substation["status"])
    target = SUBSTATION_ORDER.index(data["to_status"])
    if target != current + 1:
        fail("ERR_SUBSTATION_STEP_NOT_SEQUENTIAL")

    window = None
    if data["to_status"] == "ENERGIZED":
        now = clock.now()
        for candidate in store.ordered(
            [
                w
                for w in store.outage_windows.values()
                if w["substation_id"] == substation_id
                and w["status"] == "APPROVED"
                and w["purpose"] == "BACKFEED"
            ]
        ):
            if candidate["start_at"] <= now <= candidate["end_at"]:
                window = candidate
                break
        if window is None:
            fail("ERR_NO_APPROVED_OUTAGE_WINDOW")

    substation["utility_witness_ref"] = data["utility_witness_ref"]
    substation["status"] = data["to_status"]
    if window is not None:
        substation["energized_at"] = clock.now()
        substation["energizing_outage_window_id"] = window["id"]
        window["status"] = "EXECUTED"
        store.touch(window)
    store.touch(substation)
    return envelope.ok(substation)


@bp.post("/solar/substations/<substation_id>/outage-windows")
def request_outage_window(substation_id):
    authorize("UtilityCoordinator")
    data = body(dt("start_at"), dt("end_at"), e("purpose", PURPOSES))
    validate.window_bounds(data["start_at"], data["end_at"])
    store.require_substation(substation_id)
    if calc.outage_conflict(substation_id, data["start_at"], data["end_at"]):
        fail("ERR_OUTAGE_WINDOW_CONFLICT")
    row = store.base()
    row.update(
        {
            "substation_id": substation_id,
            "start_at": data["start_at"],
            "end_at": data["end_at"],
            "purpose": data["purpose"],
            "status": "REQUESTED",
            "utility_reference": None,
            "responded_at": None,
        }
    )
    store.outage_windows[row["id"]] = row
    return envelope.created(row)


@bp.get("/solar/substations/<substation_id>/outage-windows")
def list_outage_windows(substation_id):
    authorize(*ALL_ROLES)
    store.require_substation(substation_id)
    rows = store.children(store.outage_windows, "substation_id", substation_id)
    rows = filter_eq(rows, "status", validate.q("status"))
    rows = filter_eq(rows, "purpose", validate.q("purpose"))
    return paginate(rows)


@bp.get("/solar/outage-windows/<window_id>")
def get_outage_window(window_id):
    authorize(*ALL_ROLES)
    return envelope.ok(store.require_outage_window(window_id))


@bp.post("/solar/outage-windows/<window_id>/utility-response")
def respond_outage_window(window_id):
    authorize("UtilityCoordinator")
    data = body(e("decision", ("APPROVE", "DENY")), s("utility_reference"))
    window = store.require_outage_window(window_id)
    if window["status"] != "REQUESTED":
        fail("ERR_OUTAGE_WINDOW_ALREADY_ANSWERED")
    window["status"] = "APPROVED" if data["decision"] == "APPROVE" else "DENIED"
    window["utility_reference"] = data["utility_reference"]
    window["responded_at"] = clock.now()
    store.touch(window)
    return envelope.ok(window)
