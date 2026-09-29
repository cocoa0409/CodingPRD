"""The shop floor: build advancement and component installation."""
import constants as C
import db
import validation as V
from db import store
from errors import ApiError
from flask import Blueprint
from middleware import authorize
from routes.common import insert, list_out, must_find, object_out
from services import calc, cascade, derive

bp = Blueprint("builds", __name__)


# ---------------------------------------------------------------------------
# unit builds
# ---------------------------------------------------------------------------
@bp.get("/unit-builds/<row_id>")
@authorize(
    "PlantAdmin",
    "ProductionScheduler",
    "LineSupervisor",
    "QualityInspector",
    "WarrantyAdministrator",
)
def get_unit_build(row_id):
    return object_out("unit_builds", must_find("unit_builds", row_id))


@bp.get("/unit-builds")
@authorize("PlantAdmin", "ProductionScheduler", "LineSupervisor", "QualityInspector")
def list_unit_builds():
    unit_order_id = V.query_string("unit_order_id")
    chassis_receipt_id = V.query_string("chassis_receipt_id")
    station = V.query_enum("current_station", C.BUILD_STATIONS)
    recall_hold = V.query_bool("recall_hold")
    rows = list(store.unit_builds.values())
    if unit_order_id is not None:
        rows = [r for r in rows if r["unit_order_id"] == unit_order_id]
    if chassis_receipt_id is not None:
        rows = [r for r in rows if r["chassis_receipt_id"] == chassis_receipt_id]
    if station is not None:
        rows = [r for r in rows if r["current_station"] == station]
    if recall_hold is not None:
        rows = [r for r in rows if bool(r["recall_hold"]) == recall_hold]
    return list_out("unit_builds", rows)


def _successor(station):
    if station not in C.FORWARD_PATH:
        return None
    index = C.FORWARD_PATH.index(station)
    if index + 1 >= len(C.FORWARD_PATH):
        return None
    return C.FORWARD_PATH[index + 1]


def _installed_categories(build_id):
    categories = set()
    for installation in derive.build_installations(build_id):
        if installation["status"] != "INSTALLED":
            continue
        lot = store.component_lots.get(installation["component_lot_id"])
        if lot is not None:
            categories.add(lot["category"])
    return categories


@bp.post("/unit-builds/<row_id>/advance")
@authorize("LineSupervisor")
def advance_build(row_id):
    body = V.body_dict()
    to_station = V.field_enum(body, "to_station", C.BUILD_STATIONS, required=True)
    hours = V.field_number(body, "station_hours_used", required=True, exclusive_minimum=0)
    build = must_find("unit_builds", row_id)

    # the only legal move is one step forward along the fixed path
    if _successor(build["current_station"]) != to_station:
        raise ApiError(
            "ERR_STATION_SEQUENCE_VIOLATION",
            "Station '{}' is not the immediate successor of '{}'.".format(
                to_station, build["current_station"]
            ),
        )

    line = derive.line_of_build(build)
    if line is not None and line["status"] != "RUNNING":
        raise ApiError("ERR_LINE_NOT_RUNNING", "The line occupied by this build is PAUSED.")

    if build["recall_hold"]:
        raise ApiError("ERR_RECALL_SHIP_STOP", "The build is held by an open recall campaign.")

    order = store.unit_orders.get(build["unit_order_id"])
    if to_station == "WATER_TEST" and order is not None:
        selected = {o["category"] for o in derive.selected_options(order)}
        installed = _installed_categories(build["id"])
        for category in ("APPLIANCE", "PLUMBING"):
            if category in selected and category not in installed:
                raise ApiError(
                    "ERR_INVALID_STATE",
                    "No INSTALLED {} component is recorded on this build.".format(category),
                )
    if to_station == "PDI" and not build["water_test_passed"]:
        raise ApiError("ERR_WATER_TEST_NOT_PASSED", "The build has not passed its water test.")
    if to_station == "READY_TO_SHIP" and not build["pdi_passed"]:
        raise ApiError("ERR_PDI_NOT_PASSED", "The build has not passed its PDI.")

    build["current_station"] = to_station
    build["actual_station_hours"] = calc.rhu2(
        calc.dec(build["actual_station_hours"]) + calc.dec(hours)
    )
    db.touch(build)

    if to_station == "READY_TO_SHIP" and order is not None and order["status"] == "IN_PRODUCTION":
        order["status"] = "BUILT"
        db.touch(order)
    return object_out("unit_builds", build)


# ---------------------------------------------------------------------------
# component installations
# ---------------------------------------------------------------------------
@bp.post("/component-installations")
@authorize("LineSupervisor")
def create_installation():
    body = V.body_dict()
    build_id = V.field_string(body, "unit_build_id", required=True, min_len=1)
    lot_id = V.field_string(body, "component_lot_id", required=True, min_len=1)
    station = V.field_enum(body, "station", C.INSTALL_STATIONS, required=True)
    quantity = V.field_int(body, "quantity", required=True, minimum=1)
    must_find("unit_builds", build_id)
    lot = must_find("component_lots", lot_id)

    if lot["status"] == "QUARANTINED":
        raise ApiError("ERR_LOT_QUARANTINED", "Lot '{}' is quarantined.".format(lot["lot_code"]))
    if quantity > int(lot["quantity_available"]):
        raise ApiError(
            "ERR_LOT_QUANTITY_INSUFFICIENT",
            "Lot '{}' has only {} pieces available.".format(
                lot["lot_code"], lot["quantity_available"]
            ),
        )

    row = db.new_row(
        {
            "unit_build_id": build_id,
            "component_lot_id": lot_id,
            "station": station,
            "quantity": quantity,
            "recall_campaign_id": None,
            "status": "INSTALLED",
        }
    )
    insert("component_installations", row)

    lot["quantity_available"] = int(lot["quantity_available"]) - quantity
    lot["quantity_installed"] = int(lot["quantity_installed"]) + quantity
    if lot["quantity_available"] == 0:
        lot["status"] = "DEPLETED"
    db.touch(lot)
    return object_out("component_installations", row, 201)


@bp.get("/component-installations/<row_id>")
@authorize("PlantAdmin", "LineSupervisor", "RecallCoordinator")
def get_installation(row_id):
    return object_out("component_installations", must_find("component_installations", row_id))


@bp.get("/component-installations")
@authorize("PlantAdmin", "LineSupervisor", "RecallCoordinator")
def list_installations():
    build_id = V.query_string("unit_build_id")
    lot_id = V.query_string("component_lot_id")
    campaign_id = V.query_string("recall_campaign_id")
    status = V.query_enum("status", ["INSTALLED", "REVERSED", "RECALL_AFFECTED", "REMEDIED"])
    rows = list(store.component_installations.values())
    if build_id is not None:
        rows = [r for r in rows if r["unit_build_id"] == build_id]
    if lot_id is not None:
        rows = [r for r in rows if r["component_lot_id"] == lot_id]
    if campaign_id is not None:
        rows = [r for r in rows if r.get("recall_campaign_id") == campaign_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_out("component_installations", rows)


@bp.post("/component-installations/<row_id>/reverse")
@authorize("LineSupervisor")
def reverse_installation(row_id):
    body = V.body_dict()
    V.field_string(body, "reversal_reason", max_len=500)
    row = must_find("component_installations", row_id)
    if row["status"] != "INSTALLED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Installation status is {}; only an INSTALLED installation can be reversed.".format(
                row["status"]
            ),
        )
    build = store.unit_builds.get(row["unit_build_id"])
    if build is not None and build["current_station"] in ("SHIPPED", "SCRAPPED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "The build is {}; its installations can no longer be reversed.".format(
                build["current_station"]
            ),
        )

    row["status"] = "REVERSED"
    db.touch(row)
    lot = store.component_lots.get(row["component_lot_id"])
    if lot is not None:
        lot["quantity_installed"] = int(lot["quantity_installed"]) - int(row["quantity"])
        lot["quantity_available"] = int(lot["quantity_available"]) + int(row["quantity"])
        if lot["status"] == "DEPLETED" and lot["quantity_available"] > 0:
            lot["status"] = "AVAILABLE"
        db.touch(lot)
    return object_out("component_installations", row)


@bp.post("/component-installations/<row_id>/remedy")
@authorize("RecallCoordinator")
def remedy_installation(row_id):
    body = V.body_dict()
    V.field_string(body, "remedy_note", max_len=500)
    row = must_find("component_installations", row_id)
    if row["status"] != "RECALL_AFFECTED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Installation status is {}; only a RECALL_AFFECTED installation can be remedied.".format(
                row["status"]
            ),
        )
    campaign = store.recall_campaigns.get(row.get("recall_campaign_id"))
    if campaign is None or campaign["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "The recall campaign is not OPEN.")

    row["status"] = "REMEDIED"
    db.touch(row)
    campaign["remedied_installation_count"] = int(campaign["remedied_installation_count"]) + 1
    db.touch(campaign)
    build = store.unit_builds.get(row["unit_build_id"])
    if build is not None:
        cascade.clear_recall_hold_if_done(build)
    return object_out("component_installations", row)
