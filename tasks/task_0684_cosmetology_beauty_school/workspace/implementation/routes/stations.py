"""Station routes (PRD 3.1; §1.5)."""
from flask import Blueprint

import db
import helpers
import lookups
import response
from middleware import require

bp = Blueprint("stations", __name__)

STATION_TYPES = {"HAIR", "NAIL", "SKIN", "MAKEUP"}


@bp.post("/school/stations")
@require("Registrar")
def create_station():
    data = helpers.body()
    helpers.require_fields(data, "label", "station_type")
    label = helpers.require_str(data, "label")
    station_type = helpers.require_enum(data, "station_type", STATION_TYPES)

    row = {
        "label": label,
        "station_type": station_type,
        "status": "AVAILABLE",
    }
    db.stamp_new(row)
    db.stations[row["id"]] = row
    return response.created(row)


@bp.get("/school/stations/<sid>")
@require("Registrar", "FinancialAidOfficer", "Instructor", "Student")
def get_station(sid):
    row = lookups.path(db.stations, sid)
    return response.ok(row)


@bp.get("/school/stations")
@require("Registrar", "FinancialAidOfficer", "Instructor", "Student")
def list_stations():
    rows, limit, offset, total = helpers.paginate(list(db.stations.values()))
    return response.listing(rows, limit, offset, total)
