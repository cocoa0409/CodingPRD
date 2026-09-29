"""Shop floor: resin lots, production jobs, shift reports, toolroom orders."""
from flask import g

import calcs
import services
import validation as v
from common import (DB, endpoint, fail, list_response, lookup, new_entity,
                    page_params, filter_bool, filter_value, public, respond,
                    sorted_values, touch)

LOT_STATUSES = ("QUARANTINE", "RELEASED", "HOLD", "REJECTED", "DEPLETED")
RUN_STATUSES = ("DRAFT", "SCHEDULED", "BLOCKED", "RUNNING", "COMPLETED", "CANCELLED")
MATERIAL_STATUSES = ("UNSTAGED", "STAGED", "CONSUMED")
ORDER_STATUSES = ("OPEN", "CLOSED")
APPROVED = ("PPAP_APPROVED", "INTERIM_APPROVED")


def register(app):
    # ----------------------------------------------------------- resin lots ----
    @app.post("/resin-lots")
    @endpoint("PlantAdmin", "ProcessEngineer")
    def create_resin_lot():
        body = v.body()
        resin_grade = v.want_str(body, "resin_grade")
        supplier_lot_code = v.want_str(body, "supplier_lot_code")
        qty_kg = v.want_int(body, "qty_kg_received", minimum=1)
        moisture_bp = v.want_int(body, "moisture_bp", minimum=0, maximum=10000)
        for existing in DB.resin_lots.values():
            if existing["supplier_lot_code"] == supplier_lot_code:
                fail("ERR_DUPLICATE_CODE", "Supplier lot code already exists.")
        row = new_entity({
            "resin_grade": resin_grade,
            "supplier_lot_code": supplier_lot_code,
            "qty_kg_received": qty_kg,
            "moisture_bp": moisture_bp,
            "qty_grams_remaining": qty_kg * 1000,
            "status": "QUARANTINE",
        })
        DB.resin_lots[row["id"]] = row
        return respond(public(row), 201)

    @app.get("/resin-lots/<lid>")
    @endpoint("PlantAdmin", "ProcessEngineer", "QualityEngineer")
    def get_resin_lot(lid):
        return respond(public(lookup("resin_lots", lid)))

    @app.get("/resin-lots")
    @endpoint("PlantAdmin", "ProcessEngineer", "QualityEngineer")
    def list_resin_lots():
        limit, offset = page_params()
        resin_grade = filter_value("resin_grade")
        status = filter_value("status", LOT_STATUSES)
        rows = sorted_values(DB.resin_lots)
        if resin_grade is not None:
            rows = [r for r in rows if r["resin_grade"] == resin_grade]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        return list_response(rows, limit, offset)

    @app.post("/resin-lots/<lid>/disposition")
    @endpoint("QualityEngineer")
    def disposition_resin_lot(lid):
        lot = lookup("resin_lots", lid)
        body = v.body()
        decision = v.want_enum(body, "decision", ("RELEASE", "HOLD", "REJECT"))
        v.want_str(body, "reason", required=False)
        status = lot["status"]
        if decision == "RELEASE":
            if status not in ("QUARANTINE", "HOLD"):
                fail("ERR_INVALID_STATE", "A lot in %s may not be released." % status)
            if lot["moisture_bp"] > calcs.MAX_MOISTURE_BP:
                fail("ERR_RESIN_MOISTURE_TOO_HIGH", "The lot is too wet to release.")
            if lot.get("qty_grams_remaining") is None:
                lot["qty_grams_remaining"] = lot["qty_kg_received"] * 1000
            lot["status"] = "RELEASED"
        elif decision == "HOLD":
            if status != "RELEASED":
                fail("ERR_INVALID_STATE", "Only a released lot may be held.")
            lot["status"] = "HOLD"
        else:
            if status not in ("QUARANTINE", "HOLD"):
                fail("ERR_INVALID_STATE", "A lot in %s may not be rejected." % status)
            lot["status"] = "REJECTED"
        touch(lot)
        return respond(public(lot))

    # ------------------------------------------------------ production jobs ----
    @app.post("/production-jobs")
    @endpoint("ProcessEngineer")
    def create_job():
        body = v.body()
        quote_id = v.want_str(body, "quote_id")
        planned_qty = v.want_int(body, "planned_qty", minimum=1)
        start_raw = v.want_window_raw(body, "scheduled_start")
        end_raw = v.want_window_raw(body, "scheduled_end")
        press_id = v.want_str(body, "press_id", required=False)
        start, end = v.screen_window(start_raw, end_raw)
        quote = lookup("quotes", quote_id)
        press = lookup("presses", press_id) if press_id is not None else None
        if quote["status"] != "ACCEPTED":
            fail("ERR_INVALID_STATE", "A job may only be opened against an accepted quote.")
        mold = DB.molds[quote["mold_id"]]
        services.mold_lifecycle_gate(mold, APPROVED)
        services.service_gate(mold)
        services.transfer_gate(mold)
        if press is not None:
            services.press_physical_gate(mold, press)
            qual = services.qualification_for(mold["id"], press["id"])
            if qual is None or qual["status"] != "QUALIFIED":
                fail("ERR_PRESS_NOT_QUALIFIED",
                     "The tool is not qualified on that machine.")
        else:
            press = services.select_routing_press(mold, start, end)
        row = new_entity({
            "quote_id": quote_id,
            "mold_id": mold["id"],
            "press_id": press["id"],
            "staged_resin_lot_id": None,
            "planned_qty": planned_qty,
            "scheduled_start": start_raw,
            "scheduled_end": end_raw,
            "run_status": "DRAFT",
            "material_status": "UNSTAGED",
            "block_reason": None,
            "total_shots": 0,
            "parts_molded_total": 0,
            "good_parts_total": 0,
            "scrap_parts_total": 0,
            "short_shot_shots_total": 0,
            "total_run_minutes": 0,
            "cumulative_regrind_bp": 0,
            "first_pass_yield_bp": 10000,
            "actual_cycle_time_sec": None,
            "job_direct_cost_cents": 0,
            "job_overhead_cents": 0,
            "job_total_cost_cents": 0,
            "as_run_piece_price_cents": None,
            "price_variance_cents": None,
        })
        row["_start_dt"] = start
        row["_end_dt"] = end
        DB.jobs[row["id"]] = row
        return respond(public(row), 201)

    @app.get("/production-jobs/<jid>")
    @endpoint("PlantAdmin", "SalesEngineer", "ProcessEngineer", "QualityEngineer", "CustomerRep")
    def get_job(jid):
        return respond(public(lookup("jobs", jid)))

    @app.get("/production-jobs")
    @endpoint("PlantAdmin", "SalesEngineer", "ProcessEngineer", "QualityEngineer", "CustomerRep")
    def list_jobs():
        limit, offset = page_params()
        quote_id = filter_value("quote_id")
        mold_id = filter_value("mold_id")
        press_id = filter_value("press_id")
        staged_resin_lot_id = filter_value("staged_resin_lot_id")
        run_status = filter_value("run_status", RUN_STATUSES)
        material_status = filter_value("material_status", MATERIAL_STATUSES)
        rows = sorted_values(DB.jobs)
        if quote_id is not None:
            rows = [r for r in rows if r["quote_id"] == quote_id]
        if mold_id is not None:
            rows = [r for r in rows if r["mold_id"] == mold_id]
        if press_id is not None:
            rows = [r for r in rows if r["press_id"] == press_id]
        if staged_resin_lot_id is not None:
            rows = [r for r in rows if r["staged_resin_lot_id"] == staged_resin_lot_id]
        if run_status is not None:
            rows = [r for r in rows if r["run_status"] == run_status]
        if material_status is not None:
            rows = [r for r in rows if r["material_status"] == material_status]
        return list_response(rows, limit, offset)

    @app.post("/production-jobs/<jid>/schedule")
    @endpoint("ProcessEngineer")
    def schedule_job(jid):
        job = lookup("jobs", jid)
        body = v.body()
        expected_press_version = v.want_int(body, "expected_press_version")
        press = DB.presses[job["press_id"]]
        if expected_press_version != press["version"]:
            fail("ERR_STALE_PRESS_VERSION", "The press has changed since it was read.")
        if job["run_status"] != "DRAFT":
            fail("ERR_INVALID_STATE", "Only a draft job may be scheduled.")
        mold = DB.molds[job["mold_id"]]
        services.mold_lifecycle_gate(mold, APPROVED)
        services.service_gate(mold)
        services.transfer_gate(mold)
        if press["status"] != "AVAILABLE":
            fail("ERR_PRESS_OFFLINE", "The press is offline.")
        services.check_press_window(press["id"], job["_start_dt"], job["_end_dt"], job["id"])
        services.check_mold_window(mold["id"], job["_start_dt"], job["_end_dt"], job["id"])
        services.check_daily_capacity(press["id"], job)
        job["run_status"] = "SCHEDULED"
        touch(job)
        services.reserve_minutes(job)
        return respond(public(job))

    @app.post("/production-jobs/<jid>/stage-material")
    @endpoint("ProcessEngineer")
    def stage_material(jid):
        job = lookup("jobs", jid)
        body = v.body()
        resin_lot_id = v.want_str(body, "resin_lot_id")
        lot = lookup("resin_lots", resin_lot_id)
        if job["run_status"] != "SCHEDULED":
            fail("ERR_JOB_NOT_SCHEDULED", "Only a scheduled job may be staged.")
        if job["material_status"] != "UNSTAGED":
            fail("ERR_INVALID_STATE", "The job's material axis is already past UNSTAGED.")
        if lot["status"] != "RELEASED":
            fail("ERR_RESIN_LOT_NOT_RELEASED", "The lot is not released.")
        quote = DB.quotes[job["quote_id"]]
        if lot["resin_grade"] != quote["resin_grade"]:
            fail("ERR_RESIN_GRADE_MISMATCH", "The lot's grade does not match the quote.")
        if lot["qty_grams_remaining"] < 1:
            fail("ERR_RESIN_LOT_INSUFFICIENT", "The lot has no material left.")
        job["material_status"] = "STAGED"
        job["staged_resin_lot_id"] = lot["id"]
        touch(job)
        return respond(public(job))

    @app.post("/production-jobs/<jid>/start")
    @endpoint("ProcessEngineer")
    def start_job(jid):
        job = lookup("jobs", jid)
        if job["run_status"] != "SCHEDULED":
            fail("ERR_JOB_NOT_SCHEDULED", "Only a scheduled job may be started.")
        if job["material_status"] != "STAGED":
            fail("ERR_JOB_MATERIAL_NOT_STAGED", "The job has no material staged.")
        mold = DB.molds[job["mold_id"]]
        services.mold_lifecycle_gate(mold, APPROVED)
        lot = DB.resin_lots.get(job["staged_resin_lot_id"])
        if lot is None or lot["status"] != "RELEASED":
            fail("ERR_RESIN_LOT_NOT_RELEASED", "The staged lot is no longer released.")
        services.service_gate(mold)
        job["run_status"] = "RUNNING"
        touch(job)
        return respond(public(job))

    @app.post("/production-jobs/<jid>/complete")
    @endpoint("ProcessEngineer")
    def complete_job(jid):
        job = lookup("jobs", jid)
        if job["run_status"] != "RUNNING":
            fail("ERR_JOB_NOT_RUNNING", "Only a running job may be completed.")
        if job["total_shots"] < 1:
            fail("ERR_INVALID_STATE", "The job has not reported a single shot.")
        job["run_status"] = "COMPLETED"
        if job["material_status"] == "STAGED":
            job["material_status"] = "CONSUMED"
        services.recompute_job_rollups(job)
        services.as_run_price(job)
        touch(job)
        services.release_minutes(job)
        return respond(public(job))

    @app.post("/production-jobs/<jid>/cancel")
    @endpoint("ProcessEngineer", "PlantAdmin")
    def cancel_job_route(jid):
        job = lookup("jobs", jid)
        body = v.body()
        v.want_str(body, "reason")
        if job["run_status"] not in ("DRAFT", "SCHEDULED", "BLOCKED", "RUNNING"):
            fail("ERR_INVALID_STATE", "The job is already terminal.")
        services.cancel_job(job, None)
        return respond(public(job))

    @app.post("/production-jobs/<jid>/unblock")
    @endpoint("ProcessEngineer")
    def unblock_job(jid):
        job = lookup("jobs", jid)
        body = v.body()
        expected_press_version = v.want_int(body, "expected_press_version")
        press = DB.presses[job["press_id"]]
        if expected_press_version != press["version"]:
            fail("ERR_STALE_PRESS_VERSION", "The press has changed since it was read.")
        if job["run_status"] != "BLOCKED":
            fail("ERR_JOB_NOT_BLOCKED", "Only a blocked job may be returned to the schedule.")
        mold = DB.molds[job["mold_id"]]
        services.mold_lifecycle_gate(mold, APPROVED)
        services.service_gate(mold)
        services.check_press_window(press["id"], job["_start_dt"], job["_end_dt"], job["id"])
        services.check_mold_window(mold["id"], job["_start_dt"], job["_end_dt"], job["id"])
        services.check_daily_capacity(press["id"], job)
        job["run_status"] = "SCHEDULED"
        job["block_reason"] = None
        touch(job)
        services.reserve_minutes(job)
        return respond(public(job))

    # --------------------------------------------------- production reports ----
    @app.post("/production-reports")
    @endpoint("ProcessEngineer")
    def create_report():
        body = v.body()
        job_id = v.want_str(body, "job_id")
        shots = v.want_int(body, "shots", minimum=1)
        short_shot_shots = v.want_int(body, "short_shot_shots", minimum=0)
        good_parts = v.want_int(body, "good_parts", minimum=0)
        scrap_parts = v.want_int(body, "scrap_parts", minimum=0)
        virgin_grams = v.want_int(body, "virgin_grams", minimum=0)
        regrind_grams = v.want_int(body, "regrind_grams", minimum=0)
        run_minutes = v.want_int(body, "run_minutes", minimum=1)
        expected_job_version = v.want_int(body, "expected_job_version")
        if short_shot_shots > shots:
            fail("ERR_INVALID_REQUEST", "short_shot_shots may not exceed shots.")
        job = lookup("jobs", job_id)
        if expected_job_version != job["version"]:
            fail("ERR_STALE_JOB_VERSION", "The job has changed since it was read.")
        if job["run_status"] != "RUNNING":
            fail("ERR_JOB_NOT_RUNNING", "Reports may only be posted against a running job.")

        mold = DB.molds[job["mold_id"]]
        quote = DB.quotes[job["quote_id"]]
        press = DB.presses[job["press_id"]]
        cavity_count = mold["cavity_count"]

        # 18. parts conservation
        if (good_parts + scrap_parts != shots * cavity_count
                or scrap_parts < short_shot_shots * cavity_count):
            fail("ERR_PARTS_BALANCE_MISMATCH", "The report's parts do not conserve.")

        # 19. regrind ratio control — instantaneous gate first, then cumulative
        limit_bp = mold["approved_max_regrind_bp"]
        if limit_bp is None:
            limit_bp = calcs.DEFAULT_MAX_REGRIND_BP
        inst_total = virgin_grams + regrind_grams
        instantaneous_bp = (0 if inst_total == 0
                            else calcs.round_half_up(regrind_grams * 10000, inst_total))
        if instantaneous_bp > limit_bp:
            fail("ERR_REGRIND_RATIO_EXCEEDED", "The report exceeds the approved regrind ceiling.")
        existing = services.reports_of_job(job["id"])
        cum_regrind = regrind_grams + sum(r["regrind_grams"] for r in existing)
        cum_total = inst_total + sum(r["virgin_grams"] + r["regrind_grams"] for r in existing)
        cumulative_bp = (0 if cum_total == 0
                         else calcs.round_half_up(cum_regrind * 10000, cum_total))
        if cumulative_bp > limit_bp:
            fail("ERR_REGRIND_RATIO_EXCEEDED", "The job exceeds the approved regrind ceiling.")

        # 20. resin sufficiency
        lot = DB.resin_lots.get(job["staged_resin_lot_id"])
        if lot is None or virgin_grams > lot["qty_grams_remaining"]:
            fail("ERR_RESIN_LOT_INSUFFICIENT", "The staged lot has too little material.")

        row = new_entity({
            "job_id": job["id"],
            "resin_lot_id": job["staged_resin_lot_id"],
            "shots": shots,
            "short_shot_shots": short_shot_shots,
            "good_parts": good_parts,
            "scrap_parts": scrap_parts,
            "virgin_grams": virgin_grams,
            "regrind_grams": regrind_grams,
            "run_minutes": run_minutes,
            "instantaneous_regrind_bp": instantaneous_bp,
            "report_direct_cost_cents": calcs.report_line_cost(
                run_minutes, press["hourly_rate_cents"], virgin_grams, regrind_grams,
                quote["resin_price_cents_per_kg"]),
            "is_reversed": False,
            "reversal_reason": None,
        })
        DB.reports[row["id"]] = row

        services.recompute_job_rollups(job)
        touch(job)
        if lot is not None:
            services.recompute_lot(lot)
        services.recompute_mold_counters(mold)
        return respond(public(row), 201)

    @app.get("/production-reports/<rid>")
    @endpoint("PlantAdmin", "ProcessEngineer", "QualityEngineer")
    def get_report(rid):
        return respond(public(lookup("reports", rid)))

    @app.get("/production-reports")
    @endpoint("PlantAdmin", "ProcessEngineer", "QualityEngineer")
    def list_reports():
        limit, offset = page_params()
        job_id = filter_value("job_id")
        resin_lot_id = filter_value("resin_lot_id")
        is_reversed = filter_bool("is_reversed")
        rows = sorted_values(DB.reports)
        if job_id is not None:
            rows = [r for r in rows if r["job_id"] == job_id]
        if resin_lot_id is not None:
            rows = [r for r in rows if r["resin_lot_id"] == resin_lot_id]
        if is_reversed is not None:
            rows = [r for r in rows if r["is_reversed"] == is_reversed]
        return list_response(rows, limit, offset)

    @app.post("/production-reports/<rid>/reverse")
    @endpoint("QualityEngineer", "PlantAdmin")
    def reverse_report(rid):
        report = lookup("reports", rid)
        body = v.body()
        reason = v.want_str(body, "reason")
        if report["is_reversed"]:
            fail("ERR_REPORT_ALREADY_REVERSED", "The report has already been reversed.")
        report["is_reversed"] = True
        report["reversal_reason"] = reason
        touch(report)
        job = DB.jobs.get(report["job_id"])
        if job is not None:
            services.recompute_job_rollups(job)
            touch(job)
            mold = DB.molds.get(job["mold_id"])
        else:
            mold = None
        lot = DB.resin_lots.get(report.get("resin_lot_id"))
        if lot is not None:
            services.recompute_lot(lot)
        if mold is not None:
            services.recompute_mold_counters(mold)
        return respond(public(report))

    # --------------------------------------------------- maintenance orders ----
    @app.post("/maintenance-orders")
    @endpoint("ToolroomTech", "PlantAdmin")
    def create_maintenance_order():
        body = v.body()
        mold_id = v.want_str(body, "mold_id")
        kind = v.want_enum(body, "kind", ("PM", "REPAIR"))
        start_raw = v.want_window_raw(body, "window_start")
        end_raw = v.want_window_raw(body, "window_end")
        start, end = v.screen_window(start_raw, end_raw)
        mold = lookup("molds", mold_id)
        services.check_mold_window(mold_id, start, end, None)
        for order in DB.maintenance_orders.values():
            if order["mold_id"] == mold_id and order["status"] == "OPEN":
                fail("ERR_MAINTENANCE_ALREADY_OPEN",
                     "The tool already has an open toolroom order.")
        row = new_entity({
            "mold_id": mold_id,
            "kind": kind,
            "window_start": start_raw,
            "window_end": end_raw,
            "status": "OPEN",
            "shots_at_open": mold["shots_since_pm"],
            "shots_reset": False,
        })
        row["_start_dt"] = start
        row["_end_dt"] = end
        DB.maintenance_orders[row["id"]] = row
        mold["service_state"] = "IN_MAINTENANCE"
        touch(mold)
        return respond(public(row), 201)

    @app.get("/maintenance-orders/<oid>")
    @endpoint("PlantAdmin", "ToolroomTech", "ProcessEngineer", "QualityEngineer")
    def get_maintenance_order(oid):
        return respond(public(lookup("maintenance_orders", oid)))

    @app.get("/maintenance-orders")
    @endpoint("PlantAdmin", "ToolroomTech", "ProcessEngineer", "QualityEngineer")
    def list_maintenance_orders():
        limit, offset = page_params()
        mold_id = filter_value("mold_id")
        status = filter_value("status", ORDER_STATUSES)
        rows = sorted_values(DB.maintenance_orders)
        if mold_id is not None:
            rows = [r for r in rows if r["mold_id"] == mold_id]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        return list_response(rows, limit, offset)

    @app.post("/maintenance-orders/<oid>/close")
    @endpoint("ToolroomTech", "PlantAdmin")
    def close_maintenance_order(oid):
        order = lookup("maintenance_orders", oid)
        body = v.body()
        reset_shot_counter = v.want_bool(body, "reset_shot_counter")
        expected_mold_version = v.want_int(body, "expected_mold_version")
        mold = DB.molds[order["mold_id"]]
        if expected_mold_version != mold["version"]:
            fail("ERR_STALE_MOLD_VERSION", "The tool has changed since it was read.")
        if order["status"] != "OPEN":
            fail("ERR_INVALID_STATE", "Only an open toolroom order may be closed.")
        if not reset_shot_counter and mold["shots_since_pm"] < mold["pm_interval_shots"]:
            fail("ERR_INVALID_STATE",
                 "A close without a counter reset is only declared for a tool that is due.")
        order["status"] = "CLOSED"
        if reset_shot_counter:
            order["shots_reset"] = True
            mold["shots_since_pm"] = 0
            mold["service_state"] = "SERVICEABLE"
        else:
            mold["service_state"] = "PM_DUE"
        touch(order)
        touch(mold)
        return respond(public(order))
