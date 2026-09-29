"""Build orders: floor release, station logs, final inspection."""

from datetime import timedelta

import lookup
import response
import validate
from db import base_row, bump, db, order_created_asc, by_key
from errors import (ERR_BUILD_STATE_INVALID, ERR_DUPLICATE_RESOURCE_CODE,
                    ERR_INTERVAL_INVALID, ERR_INVALID_REQUEST,
                    ERR_MODEL_NOT_CERTIFIED, ERR_PRELOAD_OUT_OF_SPEC,
                    ERR_SEGREGATION_OF_DUTIES, ERR_STATION_CAPACITY_CONFLICT,
                    ERR_STATION_LINE_UNSUPPORTED, ERR_STATION_TYPE_MISMATCH,
                    ERR_STATION_UNAVAILABLE, ERR_TECHNICIAN_DOUBLE_BOOKED, fail)
from flask import g
from middleware import (COMPLIANCE_OFFICER, DISTRIBUTOR, PLANT_MANAGER,
                        PRODUCT_ENGINEER, QUALITY_INSPECTOR, TECHNICIAN,
                        WARRANTY_ANALYST, acting_technician, endpoint,
                        require_certified)
from services import calc
from services.cascades import (finish_terminal_transition, logs_of_build,
                               refresh_build_derived, scrap_if_over_limit)
from validate import STATION_TYPES

BUILD_STATES = ["PLANNED", "ON_FLOOR", "DRUM_DONE", "BEARINGS_DONE", "QA_HOLD",
                "REWORK", "QUALITY_HOLD", "ACCEPTED", "SCRAPPED"]
DEFECT_CODES = ["NONE", "DRUM_WELD", "BEARING_PRELOAD", "CONTROL_FIRMWARE",
                "PAYMENT_MODULE"]
OUTCOMES = ["PASS", "FAIL"]


def register(app):
    @app.post("/clm/build-orders")
    @endpoint([PLANT_MANAGER])
    def create_build_order():
        body = validate.parse_body()
        model_id = body.id_ref("model_id")
        serial_number = body.code("serial_number")
        planned_start_at = body.instant("planned_start_at")
        # rule 16: the body model_id must resolve
        lookup.model(model_id)
        # rule 48: natural-key uniqueness
        if any(b["serial_number"] == serial_number for b in db.builds.values()):
            fail(ERR_DUPLICATE_RESOURCE_CODE,
                 "serial_number '%s' already exists." % serial_number)

        row = base_row()
        row.update({
            "model_id": model_id,
            "serial_number": serial_number,
            "planned_start_at": planned_start_at,
            "build_state": "PLANNED",
            "rework_count": 0,
            "integrity_hold": False,
            "labor_minutes_total": 0,
            "station_pass_count": 0,
            "scrap_reason": "NONE",
            "qa_inspector_user_id": None,
            "accepted_at": None,
        })
        db.builds[row["id"]] = row
        return response.created(row)

    @app.get("/clm/build-orders/<build_id>")
    @endpoint([PLANT_MANAGER, PRODUCT_ENGINEER, COMPLIANCE_OFFICER, WARRANTY_ANALYST,
               TECHNICIAN, QUALITY_INSPECTOR, DISTRIBUTOR])
    def read_build_order(build_id):
        return response.ok(lookup.build(build_id))

    @app.get("/clm/build-orders")
    @endpoint([PLANT_MANAGER, PRODUCT_ENGINEER, COMPLIANCE_OFFICER, WARRANTY_ANALYST,
               TECHNICIAN, QUALITY_INSPECTOR])
    def list_build_orders():
        limit, offset = validate.q_pagination()
        model_id = validate.q_str("model_id")
        build_state = validate.q_enum("build_state", BUILD_STATES)
        integrity_hold = validate.q_bool("integrity_hold")
        rows = list(db.builds.values())
        if model_id is not None:
            rows = [r for r in rows if r["model_id"] == model_id]
        if build_state is not None:
            rows = [r for r in rows if r["build_state"] == build_state]
        if integrity_hold is not None:
            rows = [r for r in rows if r["integrity_hold"] == integrity_hold]
        rows = order_created_asc(rows)
        page, total = validate.paginate(rows, limit, offset)
        return response.listing(page, limit, offset, total)

    @app.post("/clm/build-orders/<build_id>/release-to-floor")
    @endpoint([PLANT_MANAGER])
    def release_build_order_to_floor(build_id):
        build = lookup.build(build_id)
        # rule 26: PLANNED or REWORK only; a held unit is not re-released
        if build["build_state"] not in ("PLANNED", "REWORK"):
            fail(ERR_BUILD_STATE_INVALID,
                 "A floor release requires build_state PLANNED or REWORK.")
        # rule 27: the model must be CERTIFIED or RELEASED
        model = db.models.get(build["model_id"])
        if model is None or model["certification_state"] not in ("CERTIFIED", "RELEASED"):
            fail(ERR_MODEL_NOT_CERTIFIED,
                 "The unit's model must be CERTIFIED or RELEASED.")
        build["build_state"] = "ON_FLOOR"
        bump(build)
        return response.ok(build)

    @app.post("/clm/build-orders/<build_id>/qa-signoff")
    @endpoint([QUALITY_INSPECTOR])
    def qa_signoff(build_id):
        body = validate.parse_body()
        decision = body.enum("decision", ["APPROVE", "REJECT"])
        defect_code = body.enum("defect_code", DEFECT_CODES, required=False)
        body.string("note", maxlen=1000, required=False)
        if decision == "REJECT" and (defect_code is None or defect_code == "NONE"):
            fail(ERR_INVALID_REQUEST,
                 "defect_code other than NONE is required for a REJECT decision.")

        build = lookup.build(build_id)          # rule 10
        inspector = acting_technician()          # rule 22
        # rule 26
        if build["build_state"] != "QA_HOLD":
            fail(ERR_BUILD_STATE_INVALID, "Final inspection requires build_state QA_HOLD.")
        # rule 35: nobody inspects their own welds
        if any(log["technician_id"] == g.user_id for log in logs_of_build(build["id"])):
            fail(ERR_SEGREGATION_OF_DUTIES,
                 "The inspector worked a station on this unit.")
        # rule 36
        require_certified(inspector, "QA_SIGNOFF")

        model = db.models.get(build["model_id"])
        if decision == "APPROVE":
            build["build_state"] = "ACCEPTED"
            build["accepted_at"] = db.now
            build["qa_inspector_user_id"] = g.user_id
            bump(build)
            if model is not None:
                finish_terminal_transition(model)
            return response.ok(build)

        build["rework_count"] = build["rework_count"] + 1
        build["qa_inspector_user_id"] = g.user_id
        build["build_state"] = "REWORK"
        bump(build)
        if model is not None and scrap_if_over_limit(build, model):
            finish_terminal_transition(model)
        return response.ok(build)

    @app.post("/clm/build-orders/<build_id>/station-logs")
    @endpoint([TECHNICIAN])
    def create_station_log(build_id):
        body = validate.parse_body()
        station_id = body.id_ref("station_id")
        station_type = body.enum("station_type", STATION_TYPES)
        started_at = body.instant("started_at")
        completed_at = body.instant("completed_at")
        outcome = body.enum("outcome", OUTCOMES)
        defect_code = body.enum("defect_code", DEFECT_CODES, required=False,
                                default="NONE")
        preload = body.decimal("bearing_preload_micron", required=False)
        if outcome == "PASS" and defect_code != "NONE":
            fail(ERR_INVALID_REQUEST, "defect_code must be NONE when outcome is PASS.")
        if outcome == "FAIL" and defect_code == "NONE":
            fail(ERR_INVALID_REQUEST,
                 "defect_code must not be NONE when outcome is FAIL.")

        build = lookup.build(build_id)            # rule 10
        station = lookup.station(station_id)      # rule 19
        technician = acting_technician()          # rule 22
        # rule 26: the chain is strictly sequential
        expected = calc.NEXT_STATION_FOR_STATE.get(build["build_state"])
        if expected is None or expected != station_type:
            fail(ERR_BUILD_STATE_INVALID,
                 "build_state %s does not accept a %s log."
                 % (build["build_state"], station_type))
        # rule 36: the acting technician holds the referenced station's scope
        require_certified(technician,
                          calc.SCOPE_FOR_STATION_TYPE[station["station_type"]])
        # rule 37: the bearing preload acceptance window
        model = db.models.get(build["model_id"])
        if station_type == "BEARING_INSTALL":
            if preload is None:
                fail(ERR_PRELOAD_OUT_OF_SPEC,
                     "bearing_preload_micron is required for a bearing-installation log.")
            low, high = calc.PRELOAD_WINDOWS[model["drum_alloy_grade"]]
            if preload < low or preload > high:
                fail(ERR_PRELOAD_OUT_OF_SPEC,
                     "bearing_preload_micron must sit between %s and %s for %s."
                     % (low, high, model["drum_alloy_grade"]))
        elif preload is not None:
            fail(ERR_PRELOAD_OUT_OF_SPEC,
                 "bearing_preload_micron must be null for a %s log." % station_type)
        # rule 39
        if station_type != station["station_type"]:
            fail(ERR_STATION_TYPE_MISMATCH,
                 "The submitted station_type does not match the station.")
        # rule 40
        if model["product_line"] not in station["supported_product_lines"]:
            fail(ERR_STATION_LINE_UNSUPPORTED,
                 "The station is not tooled for %s." % model["product_line"])
        # rule 43
        if station["station_state"] != "OPEN":
            fail(ERR_STATION_UNAVAILABLE, "The station is in MAINTENANCE.")
        # rule 44
        if not started_at < completed_at:
            fail(ERR_INTERVAL_INVALID, "started_at must be strictly before completed_at.")

        occupation_from = started_at
        occupation_to = completed_at + timedelta(
            minutes=station["changeover_buffer_minutes"])
        # rule 45: closed-interval station contention, buffer included
        overlapping = 0
        for log in db.logs.values():
            if log["station_id"] != station["id"]:
                continue
            if (log["occupation_from"] <= occupation_to
                    and occupation_from <= log["occupation_to"]):
                overlapping += 1
        if overlapping >= station["parallel_capacity"]:
            fail(ERR_STATION_CAPACITY_CONFLICT,
                 "The station has no free parallel capacity over that window.")
        # rule 46: half-open technician work intervals
        for log in db.logs.values():
            if log["technician_id"] != technician["id"]:
                continue
            if log["started_at"] < completed_at and started_at < log["completed_at"]:
                fail(ERR_TECHNICIAN_DOUBLE_BOOKED,
                     "The technician already has work over that interval.")

        row = base_row(versioned=False)
        row.update({
            "build_order_id": build["id"],
            "station_id": station["id"],
            "technician_id": technician["id"],
            "station_type": station_type,
            "started_at": started_at,
            "completed_at": completed_at,
            "outcome": outcome,
            "defect_code": defect_code,
            "bearing_preload_micron": preload,
            "labor_minutes": calc.labor_minutes(started_at, completed_at),
            "occupation_from": occupation_from,
            "occupation_to": occupation_to,
        })
        db.logs[row["id"]] = row

        if outcome == "PASS":
            build["build_state"] = calc.STATE_AFTER_PASS[build["build_state"]]
            refresh_build_derived(build)
            bump(build)
        else:
            build["build_state"] = "REWORK"
            build["rework_count"] = build["rework_count"] + 1
            refresh_build_derived(build)
            bump(build)
            if model is not None and scrap_if_over_limit(build, model):
                finish_terminal_transition(model)
        return response.created(row)

    @app.get("/clm/station-logs/<log_id>")
    @endpoint([PLANT_MANAGER, PRODUCT_ENGINEER, COMPLIANCE_OFFICER, WARRANTY_ANALYST,
               TECHNICIAN, QUALITY_INSPECTOR])
    def read_station_log(log_id):
        return response.ok(lookup.station_log(log_id))

    @app.get("/clm/station-logs")
    @endpoint([PLANT_MANAGER, PRODUCT_ENGINEER, COMPLIANCE_OFFICER, WARRANTY_ANALYST,
               TECHNICIAN, QUALITY_INSPECTOR])
    def list_station_logs():
        limit, offset = validate.q_pagination()
        build_order_id = validate.q_str("build_order_id")
        station_id = validate.q_str("station_id")
        technician_id = validate.q_str("technician_id")
        outcome = validate.q_enum("outcome", OUTCOMES)
        rows = list(db.logs.values())
        if build_order_id is not None:
            rows = [r for r in rows if r["build_order_id"] == build_order_id]
        if station_id is not None:
            rows = [r for r in rows if r["station_id"] == station_id]
        if technician_id is not None:
            rows = [r for r in rows if r["technician_id"] == technician_id]
        if outcome is not None:
            rows = [r for r in rows if r["outcome"] == outcome]
        rows = by_key(rows, "started_at", "created_at")
        page, total = validate.paginate(rows, limit, offset)
        return response.listing(page, limit, offset, total)
