"""Master records: customers, presses, tools, qualification rows, logical clock."""
from flask import g

import calcs
import services
import validation as v
from common import (DB, endpoint, fail, iso, list_response, lookup, new_entity,
                    order_key, page_params, filter_int, filter_value, parse_instant,
                    public, respond, set_clock, sorted_values, touch)

PRESS_STATUSES = ("AVAILABLE", "OFFLINE")
MOLD_STATUSES = ("NEW", "SAMPLING", "PPAP_APPROVED", "INTERIM_APPROVED",
                 "QUARANTINED", "TRANSFERRED", "RETIRED")
SERVICE_STATES = ("SERVICEABLE", "PM_DUE", "IN_MAINTENANCE")
OWNERSHIPS = ("SHOP_OWNED", "CUSTOMER_OWNED")
QUAL_STATUSES = ("UNQUALIFIED", "RUN_AT_RATE_SCHEDULED", "QUALIFIED", "FAILED", "REVOKED")


def register(app):
    # ------------------------------------------------------------ customers ----
    @app.post("/customers")
    @endpoint("PlantAdmin")
    def create_customer():
        body = v.body()
        name = v.want_str(body, "name")
        code = v.want_str(body, "code", min_len=2, max_len=16)
        credit_hold = v.want_bool(body, "credit_hold", required=False)
        if credit_hold is None:
            credit_hold = False
        for existing in DB.customers.values():
            if existing["code"] == code:
                fail("ERR_DUPLICATE_CODE", "Customer code already exists.")
        row = new_entity({"name": name, "code": code, "credit_hold": credit_hold})
        DB.customers[row["id"]] = row
        return respond(public(row), 201)

    @app.get("/customers/<cid>")
    @endpoint("PlantAdmin", "SalesEngineer", "CustomerRep")
    def get_customer(cid):
        row = lookup("customers", cid)
        if g.role == "CustomerRep" and g.user_id != row["id"]:
            fail("ERR_CUSTOMER_SCOPE_VIOLATION", "A CustomerRep may only read its own record.")
        return respond(public(row))

    # -------------------------------------------------------------- presses ----
    @app.post("/presses")
    @endpoint("PlantAdmin")
    def create_press():
        body = v.body()
        press_code = v.want_str(body, "press_code")
        tonnage = v.want_int(body, "tonnage", minimum=1)
        shot_size = v.want_int(body, "shot_size_grams_max", minimum=1)
        rate = v.want_int(body, "hourly_rate_cents", minimum=1)
        for existing in DB.presses.values():
            if existing["press_code"] == press_code:
                fail("ERR_DUPLICATE_CODE", "Press code already exists.")
        row = new_entity({
            "press_code": press_code,
            "tonnage": tonnage,
            "shot_size_grams_max": shot_size,
            "hourly_rate_cents": rate,
            "status": "AVAILABLE",
            "committed_minutes_scheduled": 0,
        })
        DB.presses[row["id"]] = row
        return respond(public(row), 201)

    @app.get("/presses/<pid>")
    @endpoint("PlantAdmin", "SalesEngineer", "ProcessEngineer", "QualityEngineer", "ToolroomTech")
    def get_press(pid):
        return respond(public(lookup("presses", pid)))

    @app.get("/presses")
    @endpoint("PlantAdmin", "SalesEngineer", "ProcessEngineer", "QualityEngineer")
    def list_presses():
        limit, offset = page_params()
        status = filter_value("status", PRESS_STATUSES)
        min_tonnage = filter_int("min_tonnage")
        rows = sorted_values(DB.presses)
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        if min_tonnage is not None:
            rows = [r for r in rows if r["tonnage"] >= min_tonnage]
        return list_response(rows, limit, offset)

    @app.post("/presses/<pid>/status")
    @endpoint("PlantAdmin")
    def set_press_status(pid):
        press = lookup("presses", pid)
        body = v.body()
        status = v.want_enum(body, "status", PRESS_STATUSES)
        v.want_str(body, "note", required=False)
        press["status"] = status
        touch(press)
        return respond(public(press))

    # ---------------------------------------------------------------- molds ----
    @app.post("/molds")
    @endpoint("PlantAdmin")
    def create_mold():
        body = v.body()
        mold_code = v.want_str(body, "mold_code")
        customer_id = v.want_str(body, "customer_id")
        cavity_count = v.want_int(body, "cavity_count", minimum=1)
        shot_weight = v.want_int(body, "shot_weight_grams", minimum=1)
        min_tonnage = v.want_int(body, "required_min_tonnage", minimum=1)
        max_tonnage = v.want_int(body, "required_max_tonnage", minimum=1)
        pm_interval = v.want_int(body, "pm_interval_shots", minimum=1)
        tooling_cost = v.want_int(body, "tooling_cost_cents", minimum=0)
        ownership = v.want_enum(body, "ownership", OWNERSHIPS, required=False) or "SHOP_OWNED"
        if max_tonnage < min_tonnage:
            fail("ERR_INVALID_REQUEST",
                 "required_max_tonnage must be at least required_min_tonnage.")
        lookup("customers", customer_id)
        for existing in DB.molds.values():
            if existing["mold_code"] == mold_code:
                fail("ERR_DUPLICATE_CODE", "Mold code already exists.")
        row = new_entity({
            "mold_code": mold_code,
            "customer_id": customer_id,
            "cavity_count": cavity_count,
            "shot_weight_grams": shot_weight,
            "required_min_tonnage": min_tonnage,
            "required_max_tonnage": max_tonnage,
            "pm_interval_shots": pm_interval,
            "tooling_cost_cents": tooling_cost,
            "ownership": ownership,
            "status": "NEW",
            "service_state": "SERVICEABLE",
            "total_shot_count": 0,
            "shots_since_pm": 0,
            "approved_max_regrind_bp": None,
            "interim_expiry_shots": None,
            "active_transfer_id": None,
        })
        DB.molds[row["id"]] = row
        return respond(public(row), 201)

    @app.get("/molds/<mid>")
    @endpoint("PlantAdmin", "SalesEngineer", "ProcessEngineer", "QualityEngineer",
              "ToolroomTech", "CustomerRep")
    def get_mold(mid):
        return respond(public(lookup("molds", mid)))

    @app.get("/molds")
    @endpoint("PlantAdmin", "SalesEngineer", "ProcessEngineer", "QualityEngineer",
              "ToolroomTech", "CustomerRep")
    def list_molds():
        limit, offset = page_params()
        customer_id = filter_value("customer_id")
        status = filter_value("status", MOLD_STATUSES)
        service_state = filter_value("service_state", SERVICE_STATES)
        ownership = filter_value("ownership", OWNERSHIPS)
        rows = sorted_values(DB.molds)
        if customer_id is not None:
            rows = [r for r in rows if r["customer_id"] == customer_id]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        if service_state is not None:
            rows = [r for r in rows if r["service_state"] == service_state]
        if ownership is not None:
            rows = [r for r in rows if r["ownership"] == ownership]
        return list_response(rows, limit, offset)

    @app.post("/molds/<mid>/quality-hold")
    @endpoint("QualityEngineer", "PlantAdmin")
    def quality_hold(mid):
        mold = lookup("molds", mid)
        body = v.body()
        action = v.want_enum(body, "action", ("QUARANTINE", "RELEASE"))
        v.want_str(body, "reason", required=False)
        status = mold["status"]
        if action == "QUARANTINE":
            if status == "QUARANTINED":
                fail("ERR_MOLD_QUARANTINED", "The tool is already quarantined.")
            if status == "RETIRED":
                fail("ERR_MOLD_RETIRED", "The tool is retired.")
            if status == "TRANSFERRED":
                fail("ERR_MOLD_TRANSFERRED", "The tool has been transferred.")
            if status not in ("SAMPLING", "PPAP_APPROVED", "INTERIM_APPROVED"):
                fail("ERR_INVALID_STATE", "A tool in %s may not be quarantined." % status)
            mold["status"] = "QUARANTINED"
            touch(mold)
            services.block_scheduled_jobs(mold, "MOLD_QUARANTINED")
        else:
            if status == "RETIRED":
                fail("ERR_MOLD_RETIRED", "The tool is retired.")
            if status == "TRANSFERRED":
                fail("ERR_MOLD_TRANSFERRED", "The tool has been transferred.")
            if status != "QUARANTINED":
                fail("ERR_INVALID_STATE", "Only a quarantined tool may be released.")
            if mold.get("approved_max_regrind_bp") is not None:
                mold["status"] = "PPAP_APPROVED"
                mold["interim_expiry_shots"] = None
            else:
                mold["status"] = "SAMPLING"
            touch(mold)
        return respond(public(mold))

    @app.post("/molds/<mid>/retire")
    @endpoint("PlantAdmin")
    def retire_mold(mid):
        mold = lookup("molds", mid)
        body = v.body()
        v.want_str(body, "reason", required=False)
        status = mold["status"]
        if status not in ("NEW", "PPAP_APPROVED"):
            if status == "QUARANTINED":
                fail("ERR_MOLD_QUARANTINED", "The tool is quarantined.")
            if status == "RETIRED":
                fail("ERR_MOLD_RETIRED", "The tool is already retired.")
            if status == "TRANSFERRED":
                fail("ERR_MOLD_TRANSFERRED", "The tool has been transferred.")
            fail("ERR_INVALID_STATE", "A tool in %s may not be retired." % status)
        for job in services.jobs_of_mold(mold["id"]):
            if job["run_status"] in ("SCHEDULED", "BLOCKED", "RUNNING"):
                fail("ERR_INVALID_STATE", "The tool still carries unfinished work.")
        mold["status"] = "RETIRED"
        touch(mold)
        services.revoke_qualifications(mold)
        return respond(public(mold))

    # -------------------------------------------------- press qualifications ----
    @app.post("/press-qualifications")
    @endpoint("ProcessEngineer", "PlantAdmin")
    def create_qualification():
        body = v.body()
        mold_id = v.want_str(body, "mold_id")
        press_id = v.want_str(body, "press_id")
        lookup("molds", mold_id)
        lookup("presses", press_id)
        if services.qualification_for(mold_id, press_id) is not None:
            fail("ERR_DUPLICATE_QUALIFICATION",
                 "A qualification row already exists for this tool and machine.")
        row = new_entity({
            "mold_id": mold_id,
            "press_id": press_id,
            "status": "UNQUALIFIED",
            "scheduled_start": None,
            "scheduled_end": None,
            "target_parts_per_hour": None,
            "actual_parts_per_hour": None,
            "attempt_count": 0,
        })
        DB.qualifications[row["id"]] = row
        return respond(public(row), 201)

    @app.get("/press-qualifications/<qid>")
    @endpoint("PlantAdmin", "ProcessEngineer", "QualityEngineer")
    def get_qualification(qid):
        return respond(public(lookup("qualifications", qid)))

    @app.get("/press-qualifications")
    @endpoint("PlantAdmin", "ProcessEngineer", "QualityEngineer")
    def list_qualifications():
        limit, offset = page_params()
        mold_id = filter_value("mold_id")
        press_id = filter_value("press_id")
        status = filter_value("status", QUAL_STATUSES)
        rows = sorted_values(DB.qualifications)
        if mold_id is not None:
            rows = [r for r in rows if r["mold_id"] == mold_id]
        if press_id is not None:
            rows = [r for r in rows if r["press_id"] == press_id]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        return list_response(rows, limit, offset)

    @app.post("/press-qualifications/<qid>/schedule-run-at-rate")
    @endpoint("ProcessEngineer")
    def schedule_run_at_rate(qid):
        qual = lookup("qualifications", qid)
        body = v.body()
        start_raw = v.want_window_raw(body, "scheduled_start")
        end_raw = v.want_window_raw(body, "scheduled_end")
        target = v.want_int(body, "target_parts_per_hour", minimum=1)
        start, end = v.screen_window(start_raw, end_raw)
        if qual["status"] not in ("UNQUALIFIED", "FAILED", "REVOKED"):
            fail("ERR_INVALID_STATE",
                 "A trial may not be booked from %s." % qual["status"])
        mold = DB.molds[qual["mold_id"]]
        if qual["status"] in ("UNQUALIFIED", "REVOKED"):
            if mold["status"] == "RETIRED":
                fail("ERR_MOLD_RETIRED", "The tool is retired.")
            if mold["status"] == "TRANSFERRED":
                fail("ERR_MOLD_TRANSFERRED", "The tool has been transferred.")
        press = DB.presses[qual["press_id"]]
        if press["status"] != "AVAILABLE":
            fail("ERR_PRESS_OFFLINE", "The press is offline.")
        qual["status"] = "RUN_AT_RATE_SCHEDULED"
        qual["scheduled_start"] = start_raw
        qual["scheduled_end"] = end_raw
        qual["target_parts_per_hour"] = target
        qual["actual_parts_per_hour"] = None
        qual["_start_dt"] = start
        qual["_end_dt"] = end
        touch(qual)
        return respond(public(qual))

    @app.post("/press-qualifications/<qid>/record-run-at-rate")
    @endpoint("QualityEngineer")
    def record_run_at_rate(qid):
        qual = lookup("qualifications", qid)
        body = v.body()
        actual = v.want_int(body, "actual_parts_per_hour", minimum=0)
        if qual["status"] != "RUN_AT_RATE_SCHEDULED":
            fail("ERR_RUN_AT_RATE_NOT_SCHEDULED",
                 "No run-at-rate trial is scheduled on this row.")
        achieved = calcs.achievement_bp(actual, qual["target_parts_per_hour"])
        qual["status"] = "QUALIFIED" if achieved >= calcs.RUN_AT_RATE_MIN_BP else "FAILED"
        qual["actual_parts_per_hour"] = actual
        qual["attempt_count"] += 1
        touch(qual)
        return respond(public(qual))

    # ---------------------------------------------------------- logical clock ----
    @app.post("/_clock/set_current_utc")
    @endpoint("PlantAdmin")
    def set_current_utc():
        body = v.body()
        raw = v.want_str(body, "to_iso8601")
        moment = parse_instant(raw)
        if moment is None:
            fail("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 UTC instant.")
        set_clock(moment)
        return respond({"current_utc": raw})
