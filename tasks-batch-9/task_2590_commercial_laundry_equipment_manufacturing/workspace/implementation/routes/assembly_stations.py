"""Assembly stations: floor tooling."""

import lookup
import response
import validate
from db import base_row, by_key, db
from errors import ERR_DUPLICATE_RESOURCE_CODE, fail
from middleware import (PLANT_MANAGER, PRODUCT_ENGINEER, QUALITY_INSPECTOR,
                        TECHNICIAN, endpoint)
from validate import PRODUCT_LINES, STATION_TYPES

STATION_STATES = ["OPEN", "MAINTENANCE"]


def register(app):
    @app.post("/clm/assembly-stations")
    @endpoint([PLANT_MANAGER])
    def create_assembly_station():
        body = validate.parse_body()
        station_code = body.code("station_code")
        station_type = body.enum("station_type", STATION_TYPES)
        parallel_capacity = body.integer("parallel_capacity", minimum=1, maximum=4)
        changeover_buffer_minutes = body.integer("changeover_buffer_minutes",
                                                 minimum=0, maximum=120)
        supported_product_lines = body.enum_array("supported_product_lines",
                                                  PRODUCT_LINES)
        station_state = body.enum("station_state", STATION_STATES, required=False,
                                  default="OPEN")
        # rule 48: natural-key uniqueness
        if any(s["station_code"] == station_code for s in db.stations.values()):
            fail(ERR_DUPLICATE_RESOURCE_CODE,
                 "station_code '%s' already exists." % station_code)

        row = base_row()
        row.update({
            "station_code": station_code,
            "station_type": station_type,
            "parallel_capacity": parallel_capacity,
            "changeover_buffer_minutes": changeover_buffer_minutes,
            "supported_product_lines": supported_product_lines,
            "station_state": station_state,
        })
        db.stations[row["id"]] = row
        return response.created(row)

    @app.get("/clm/assembly-stations/<station_id>")
    @endpoint([PLANT_MANAGER, PRODUCT_ENGINEER, TECHNICIAN, QUALITY_INSPECTOR])
    def read_assembly_station(station_id):
        return response.ok(lookup.station(station_id))

    @app.get("/clm/assembly-stations")
    @endpoint([PLANT_MANAGER, PRODUCT_ENGINEER, TECHNICIAN, QUALITY_INSPECTOR])
    def list_assembly_stations():
        limit, offset = validate.q_pagination()
        station_type = validate.q_enum("station_type", STATION_TYPES)
        station_state = validate.q_enum("station_state", STATION_STATES)
        rows = list(db.stations.values())
        if station_type is not None:
            rows = [r for r in rows if r["station_type"] == station_type]
        if station_state is not None:
            rows = [r for r in rows if r["station_state"] == station_state]
        rows = by_key(rows, "station_code")
        page, total = validate.paginate(rows, limit, offset)
        return response.listing(page, limit, offset, total)
