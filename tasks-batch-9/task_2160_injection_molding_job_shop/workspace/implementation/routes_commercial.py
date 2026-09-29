"""Commercial surface: quotes, PPAP packages, tool transfers, capacity commits."""
from flask import g

import calcs
import services
import validation as v
from common import (DB, endpoint, fail, list_response, lookup, new_entity,
                    page_params, filter_value, public, respond, sorted_values, touch)

QUOTE_STATUSES = ("DRAFT", "PRICED", "SUBMITTED", "ACCEPTED", "DECLINED", "SUPERSEDED")
PPAP_STATUSES = ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "APPROVED", "INTERIM_APPROVED",
                 "REJECTED")
TRANSFER_STATUSES = ("REQUESTED", "APPROVED", "DECLINED", "COMPLETED")
COMMIT_STATUSES = ("OPEN", "SETTLED", "CANCELLED")
APPROVED_MOLD_STATUSES = ("PPAP_APPROVED", "INTERIM_APPROVED")


def register(app):
    # --------------------------------------------------------------- quotes ----
    @app.post("/quotes")
    @endpoint("SalesEngineer")
    def create_quote():
        body = v.body()
        customer_id = v.want_str(body, "customer_id")
        mold_id = v.want_str(body, "mold_id")
        part_weight = v.want_int(body, "part_weight_grams", minimum=1)
        cycle_time = v.want_int(body, "cycle_time_sec", minimum=1)
        cavitation = v.want_int(body, "cavitation", minimum=1)
        resin_grade = v.want_str(body, "resin_grade")
        resin_price = v.want_int(body, "resin_price_cents_per_kg", minimum=1)
        annual_volume = v.want_int(body, "annual_volume", minimum=1)
        lookup("customers", customer_id)
        mold = lookup("molds", mold_id)
        if cavitation > mold["cavity_count"]:
            fail("ERR_INVALID_REQUEST", "cavitation may not exceed the tool's cavity_count.")
        row = new_entity({
            "customer_id": customer_id,
            "mold_id": mold_id,
            "part_weight_grams": part_weight,
            "cycle_time_sec": cycle_time,
            "cavitation": cavitation,
            "resin_grade": resin_grade,
            "resin_price_cents_per_kg": resin_price,
            "annual_volume": annual_volume,
            "rate_press_id": None,
            "margin_bp": None,
            "quoted_lot_price_cents": None,
            "quoted_piece_price_cents": None,
            "status": "DRAFT",
            "decided_by_user_id": None,
        })
        DB.quotes[row["id"]] = row
        return respond(public(row), 201)

    @app.get("/quotes/<qid>")
    @endpoint("PlantAdmin", "SalesEngineer", "ProcessEngineer", "QualityEngineer", "CustomerRep")
    def get_quote(qid):
        return respond(public(lookup("quotes", qid)))

    @app.get("/quotes")
    @endpoint("PlantAdmin", "SalesEngineer", "ProcessEngineer", "CustomerRep")
    def list_quotes():
        limit, offset = page_params()
        customer_id = filter_value("customer_id")
        mold_id = filter_value("mold_id")
        rate_press_id = filter_value("rate_press_id")
        status = filter_value("status", QUOTE_STATUSES)
        rows = sorted_values(DB.quotes)
        if customer_id is not None:
            rows = [r for r in rows if r["customer_id"] == customer_id]
        if mold_id is not None:
            rows = [r for r in rows if r["mold_id"] == mold_id]
        if rate_press_id is not None:
            rows = [r for r in rows if r["rate_press_id"] == rate_press_id]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        return list_response(rows, limit, offset)

    @app.post("/quotes/<qid>/price")
    @endpoint("SalesEngineer")
    def price_quote(qid):
        quote = lookup("quotes", qid)
        body = v.body()
        press_id = v.want_str(body, "press_id", required=False)
        press = lookup("presses", press_id) if press_id is not None else None
        if quote["status"] != "DRAFT":
            fail("ERR_INVALID_STATE", "Only a DRAFT quote may be priced.")
        mold = DB.molds[quote["mold_id"]]
        if mold["status"] == "TRANSFERRED":
            fail("ERR_MOLD_TRANSFERRED", "The tool has been transferred.")
        if mold["status"] == "RETIRED":
            fail("ERR_MOLD_RETIRED", "The tool is retired.")
        if quote["cavitation"] > mold["cavity_count"]:
            fail("ERR_INVALID_REQUEST", "cavitation may not exceed the tool's cavity_count.")
        if press is not None:
            services.press_physical_gate(mold, press)
        else:
            press = services.select_rate_press(mold)
        margin_bp, lot_price, piece_price = calcs.piece_price(
            cavitation=quote["cavitation"],
            cycle_time_sec=quote["cycle_time_sec"],
            hourly_rate_cents=press["hourly_rate_cents"],
            part_weight_grams=quote["part_weight_grams"],
            resin_price_cents_per_kg=quote["resin_price_cents_per_kg"],
            ownership=mold["ownership"],
            tooling_cost_cents=mold["tooling_cost_cents"],
            annual_volume=quote["annual_volume"],
            yield_bp=calcs.STANDARD_YIELD_BP,
        )
        quote["rate_press_id"] = press["id"]
        quote["margin_bp"] = margin_bp
        quote["quoted_lot_price_cents"] = lot_price
        quote["quoted_piece_price_cents"] = piece_price
        quote["status"] = "PRICED"
        touch(quote)
        return respond(public(quote))

    @app.post("/quotes/<qid>/submit")
    @endpoint("SalesEngineer")
    def submit_quote(qid):
        quote = lookup("quotes", qid)
        if quote["status"] != "PRICED" or quote["quoted_piece_price_cents"] is None:
            fail("ERR_QUOTE_NOT_PRICED", "Only a priced quote may be sent to the customer.")
        quote["status"] = "SUBMITTED"
        touch(quote)
        return respond(public(quote))

    @app.post("/quotes/<qid>/customer-decision")
    @endpoint("CustomerRep")
    def decide_quote(qid):
        quote = lookup("quotes", qid)
        body = v.body()
        decision = v.want_enum(body, "decision", ("ACCEPT", "DECLINE"))
        expected_mold_version = v.want_int(body, "expected_mold_version")
        v.want_str(body, "reason", required=False)
        if g.user_id != quote["customer_id"]:
            fail("ERR_CUSTOMER_SCOPE_VIOLATION", "This quote belongs to another customer.")
        mold = DB.molds[quote["mold_id"]]
        if expected_mold_version != mold["version"]:
            fail("ERR_STALE_MOLD_VERSION", "The tool has changed since it was read.")
        if quote["status"] != "SUBMITTED":
            fail("ERR_INVALID_STATE", "Only a submitted quote may be decided.")
        if decision == "ACCEPT":
            services.mold_lifecycle_gate(mold, ("NEW", "SAMPLING"))
            customer = DB.customers[quote["customer_id"]]
            if customer["credit_hold"]:
                fail("ERR_CUSTOMER_CREDIT_HOLD", "The customer is on credit hold.")
            quote["status"] = "ACCEPTED"
            quote["decided_by_user_id"] = g.user_id
            touch(quote)
            if mold["status"] == "NEW":
                mold["status"] = "SAMPLING"
            touch(mold)
            for sibling in sorted_values(DB.quotes):
                if sibling["id"] == quote["id"] or sibling["mold_id"] != quote["mold_id"]:
                    continue
                if sibling["status"] in ("DRAFT", "PRICED", "SUBMITTED"):
                    sibling["status"] = "SUPERSEDED"
                    touch(sibling)
        else:
            quote["status"] = "DECLINED"
            quote["decided_by_user_id"] = g.user_id
            touch(quote)
        return respond(public(quote))

    # ------------------------------------------------------ PPAP submissions ----
    @app.post("/ppap-submissions")
    @endpoint("QualityEngineer")
    def create_ppap():
        body = v.body()
        mold_id = v.want_str(body, "mold_id")
        quote_id = v.want_str(body, "quote_id")
        level = v.want_int(body, "level", minimum=1, maximum=5)
        max_regrind_bp = v.want_int(body, "max_regrind_bp", minimum=0, maximum=10000)
        supersedes = v.want_str(body, "supersedes_submission_id", required=False)
        lookup("molds", mold_id)
        lookup("quotes", quote_id)
        if supersedes is not None:
            lookup("ppaps", supersedes)
        row = new_entity({
            "mold_id": mold_id,
            "quote_id": quote_id,
            "level": level,
            "max_regrind_bp": max_regrind_bp,
            "supersedes_submission_id": supersedes,
            "revision_no": 1,
            "fai_dimensional_pass": None,
            "fai_sample_shots": None,
            "submitted_by_user_id": None,
            "internal_reviewed_by_user_id": None,
            "customer_decided_by_user_id": None,
            "interim_expiry_shots": None,
            "status": "DRAFT",
        })
        DB.ppaps[row["id"]] = row
        return respond(public(row), 201)

    @app.get("/ppap-submissions/<sid>")
    @endpoint("PlantAdmin", "QualityEngineer", "ProcessEngineer", "CustomerRep")
    def get_ppap(sid):
        return respond(public(lookup("ppaps", sid)))

    @app.get("/ppap-submissions")
    @endpoint("PlantAdmin", "QualityEngineer", "ProcessEngineer", "CustomerRep")
    def list_ppaps():
        limit, offset = page_params()
        mold_id = filter_value("mold_id")
        quote_id = filter_value("quote_id")
        supersedes = filter_value("supersedes_submission_id")
        status = filter_value("status", PPAP_STATUSES)
        rows = sorted_values(DB.ppaps)
        if mold_id is not None:
            rows = [r for r in rows if r["mold_id"] == mold_id]
        if quote_id is not None:
            rows = [r for r in rows if r["quote_id"] == quote_id]
        if supersedes is not None:
            rows = [r for r in rows if r["supersedes_submission_id"] == supersedes]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        return list_response(rows, limit, offset)

    @app.post("/ppap-submissions/<sid>/submit")
    @endpoint("QualityEngineer")
    def submit_ppap(sid):
        package = lookup("ppaps", sid)
        body = v.body()
        fai_pass = v.want_bool(body, "fai_dimensional_pass")
        fai_shots = v.want_int(body, "fai_sample_shots", minimum=0)
        if package["status"] != "DRAFT":
            fail("ERR_INVALID_STATE", "Only a draft package may be filed.")
        mold = DB.molds[package["mold_id"]]
        services.mold_lifecycle_gate(mold, ("SAMPLING",))
        if not fai_pass or fai_shots < calcs.MIN_FAI_SAMPLE_SHOTS:
            fail("ERR_FAI_NOT_PASSED", "The first-article evidence is inadequate.")
        package["fai_dimensional_pass"] = fai_pass
        package["fai_sample_shots"] = fai_shots
        package["submitted_by_user_id"] = g.user_id
        package["status"] = "SUBMITTED"
        touch(package)
        return respond(public(package))

    @app.post("/ppap-submissions/<sid>/internal-review")
    @endpoint("QualityEngineer", "PlantAdmin")
    def review_ppap(sid):
        package = lookup("ppaps", sid)
        body = v.body()
        decision = v.want_enum(body, "decision", ("ENDORSE", "REJECT"))
        v.want_str(body, "note", required=False)
        if package["status"] != "SUBMITTED":
            fail("ERR_INVALID_STATE", "Only a submitted package may be reviewed.")
        if g.user_id == package["submitted_by_user_id"]:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "The submitter may not review their own package.")
        package["internal_reviewed_by_user_id"] = g.user_id
        package["status"] = "UNDER_REVIEW" if decision == "ENDORSE" else "REJECTED"
        touch(package)
        return respond(public(package))

    @app.post("/ppap-submissions/<sid>/customer-decision")
    @endpoint("CustomerRep")
    def decide_ppap(sid):
        package = lookup("ppaps", sid)
        body = v.body()
        decision = v.want_enum(body, "decision", ("APPROVE", "INTERIM_APPROVE", "REJECT"))
        expected_mold_version = v.want_int(body, "expected_mold_version")
        interim_shots = v.want_int(body, "interim_expiry_shots",
                                   required=(decision == "INTERIM_APPROVE"), minimum=1)
        v.want_str(body, "reason", required=False)
        mold = DB.molds[package["mold_id"]]
        if g.user_id != mold["customer_id"]:
            fail("ERR_CUSTOMER_SCOPE_VIOLATION", "This tool belongs to another customer.")
        if expected_mold_version != mold["version"]:
            fail("ERR_STALE_MOLD_VERSION", "The tool has changed since it was read.")
        if package["status"] != "UNDER_REVIEW":
            fail("ERR_INVALID_STATE", "Only a package under review may be decided.")
        if decision in ("APPROVE", "INTERIM_APPROVE"):
            services.mold_lifecycle_gate(mold, ("SAMPLING",))
        package["customer_decided_by_user_id"] = g.user_id
        if decision == "APPROVE":
            package["status"] = "APPROVED"
            touch(package)
            mold["status"] = "PPAP_APPROVED"
            mold["approved_max_regrind_bp"] = package["max_regrind_bp"]
            mold["interim_expiry_shots"] = None
            touch(mold)
        elif decision == "INTERIM_APPROVE":
            package["status"] = "INTERIM_APPROVED"
            package["interim_expiry_shots"] = interim_shots
            touch(package)
            mold["status"] = "INTERIM_APPROVED"
            mold["approved_max_regrind_bp"] = package["max_regrind_bp"]
            mold["interim_expiry_shots"] = mold["total_shot_count"] + interim_shots
            touch(mold)
        else:
            package["status"] = "REJECTED"
            touch(package)
        return respond(public(package))

    @app.post("/ppap-submissions/<sid>/revise")
    @endpoint("QualityEngineer")
    def revise_ppap(sid):
        package = lookup("ppaps", sid)
        body = v.body()
        max_regrind_bp = v.want_int(body, "max_regrind_bp", required=False,
                                    minimum=0, maximum=10000)
        if package["status"] != "REJECTED":
            fail("ERR_INVALID_STATE", "Only a rejected package may be revised.")
        mold = DB.molds[package["mold_id"]]
        services.mold_lifecycle_gate(mold, ("SAMPLING",))
        package["status"] = "DRAFT"
        package["revision_no"] += 1
        package["fai_dimensional_pass"] = None
        package["fai_sample_shots"] = None
        package["submitted_by_user_id"] = None
        package["internal_reviewed_by_user_id"] = None
        package["customer_decided_by_user_id"] = None
        if max_regrind_bp is not None:
            package["max_regrind_bp"] = max_regrind_bp
        touch(package)
        return respond(public(package))

    # -------------------------------------------------------- tool transfers ----
    @app.post("/tool-transfers")
    @endpoint("CustomerRep", "PlantAdmin")
    def create_transfer():
        body = v.body()
        mold_id = v.want_str(body, "mold_id")
        to_customer_id = v.want_str(body, "to_customer_id")
        settlement_cents = v.want_int(body, "settlement_cents", minimum=0)
        mold = lookup("molds", mold_id)
        lookup("customers", to_customer_id)
        if g.role == "CustomerRep" and g.user_id != to_customer_id:
            fail("ERR_CUSTOMER_SCOPE_VIOLATION",
                 "A CustomerRep may only request a transfer to its own customer.")
        for existing in DB.transfers.values():
            if existing["mold_id"] == mold_id and existing["status"] in ("REQUESTED", "APPROVED"):
                fail("ERR_MOLD_TRANSFER_IN_PROGRESS",
                     "A transfer is already in flight on this tool.")
        row = new_entity({
            "mold_id": mold_id,
            "to_customer_id": to_customer_id,
            "from_ownership": mold["ownership"],
            "settlement_cents": settlement_cents,
            "status": "REQUESTED",
            "decision_reason": None,
        })
        DB.transfers[row["id"]] = row
        mold["active_transfer_id"] = row["id"]
        touch(mold)
        return respond(public(row), 201)

    @app.get("/tool-transfers/<tid>")
    @endpoint("PlantAdmin", "CustomerRep", "ToolroomTech")
    def get_transfer(tid):
        return respond(public(lookup("transfers", tid)))

    @app.get("/tool-transfers")
    @endpoint("PlantAdmin", "CustomerRep", "ToolroomTech")
    def list_transfers():
        limit, offset = page_params()
        mold_id = filter_value("mold_id")
        to_customer_id = filter_value("to_customer_id")
        status = filter_value("status", TRANSFER_STATUSES)
        rows = sorted_values(DB.transfers)
        if mold_id is not None:
            rows = [r for r in rows if r["mold_id"] == mold_id]
        if to_customer_id is not None:
            rows = [r for r in rows if r["to_customer_id"] == to_customer_id]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        return list_response(rows, limit, offset)

    @app.post("/tool-transfers/<tid>/decision")
    @endpoint("PlantAdmin")
    def decide_transfer(tid):
        transfer = lookup("transfers", tid)
        body = v.body()
        decision = v.want_enum(body, "decision", ("APPROVE", "DECLINE"))
        reason = v.want_str(body, "reason", required=False)
        if transfer["status"] != "REQUESTED":
            fail("ERR_INVALID_STATE", "Only a requested transfer may be adjudicated.")
        mold = DB.molds[transfer["mold_id"]]
        if decision == "APPROVE":
            if mold["status"] == "RETIRED":
                fail("ERR_MOLD_RETIRED", "The tool is retired.")
            if mold["status"] == "TRANSFERRED":
                fail("ERR_MOLD_TRANSFERRED", "The tool has already been transferred.")
            transfer["status"] = "APPROVED"
            transfer["decision_reason"] = reason
            touch(transfer)
        else:
            transfer["status"] = "DECLINED"
            transfer["decision_reason"] = reason
            touch(transfer)
            mold["active_transfer_id"] = None
            touch(mold)
        return respond(public(transfer))

    @app.post("/tool-transfers/<tid>/complete")
    @endpoint("PlantAdmin")
    def complete_transfer(tid):
        transfer = lookup("transfers", tid)
        body = v.body()
        expected_mold_version = v.want_int(body, "expected_mold_version")
        mold = DB.molds[transfer["mold_id"]]
        if expected_mold_version != mold["version"]:
            fail("ERR_STALE_MOLD_VERSION", "The tool has changed since it was read.")
        if transfer["status"] != "APPROVED":
            fail("ERR_TRANSFER_NOT_APPROVED", "Only an approved transfer may be completed.")
        for job in services.jobs_of_mold(mold["id"]):
            if job["run_status"] == "RUNNING":
                fail("ERR_MOLD_TRANSFER_IN_PROGRESS",
                     "A job on this tool is still running.")
        transfer["status"] = "COMPLETED"
        touch(transfer)
        mold["ownership"] = "CUSTOMER_OWNED"
        mold["customer_id"] = transfer["to_customer_id"]
        mold["status"] = "TRANSFERRED"
        mold["active_transfer_id"] = None
        touch(mold)
        services.revoke_qualifications(mold)
        return respond(public(transfer))

    # ----------------------------------------------------- capacity commits ----
    @app.post("/capacity-commits")
    @endpoint("SalesEngineer", "PlantAdmin")
    def create_commit():
        body = v.body()
        customer_id = v.want_str(body, "customer_id")
        press_id = v.want_str(body, "press_id")
        start_raw = v.want_window_raw(body, "window_start")
        end_raw = v.want_window_raw(body, "window_end")
        committed_minutes = v.want_int(body, "committed_minutes", minimum=1)
        policy = v.want_enum(body, "shortfall_policy", ("STRICT", "GOODWILL"))
        start, end = v.screen_window(start_raw, end_raw)
        customer = lookup("customers", customer_id)
        lookup("presses", press_id)
        window_minutes = calcs.minutes_between(start, end)
        available = calcs.floor_div(window_minutes * calcs.PRESS_AVAILABILITY_BP, 10000)
        booked = 0
        for other in DB.commits.values():
            if other["press_id"] != press_id or other["status"] != "OPEN":
                continue
            if other["_start_dt"] < end and start < other["_end_dt"]:
                booked += other["committed_minutes"]
        if booked + committed_minutes > available:
            fail("ERR_CAPACITY_COMMIT_EXCEEDED",
                 "The press cannot deliver that many minutes in the window.")
        if customer["credit_hold"]:
            fail("ERR_CUSTOMER_CREDIT_HOLD", "The customer is on credit hold.")
        row = new_entity({
            "customer_id": customer_id,
            "press_id": press_id,
            "window_start": start_raw,
            "window_end": end_raw,
            "committed_minutes": committed_minutes,
            "shortfall_policy": policy,
            "status": "OPEN",
            "consumed_minutes": 0,
            "shortfall_minutes": 0,
            "shortfall_fee_cents": 0,
            "utilization_bp": 0,
        })
        row["_start_dt"] = start
        row["_end_dt"] = end
        DB.commits[row["id"]] = row
        return respond(public(row), 201)

    @app.get("/capacity-commits/<cid>")
    @endpoint("PlantAdmin", "SalesEngineer", "CustomerRep")
    def get_commit(cid):
        return respond(public(lookup("commits", cid)))

    @app.get("/capacity-commits")
    @endpoint("PlantAdmin", "SalesEngineer", "CustomerRep")
    def list_commits():
        limit, offset = page_params()
        customer_id = filter_value("customer_id")
        press_id = filter_value("press_id")
        status = filter_value("status", COMMIT_STATUSES)
        rows = sorted_values(DB.commits)
        if customer_id is not None:
            rows = [r for r in rows if r["customer_id"] == customer_id]
        if press_id is not None:
            rows = [r for r in rows if r["press_id"] == press_id]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        return list_response(rows, limit, offset)

    @app.post("/capacity-commits/<cid>/settle")
    @endpoint("PlantAdmin")
    def settle_commit(cid):
        commit = lookup("commits", cid)
        if commit["status"] != "OPEN":
            fail("ERR_CAPACITY_COMMIT_NOT_OPEN", "Only an open commitment may be settled.")
        press = DB.presses[commit["press_id"]]
        consumed = 0
        for job in services.jobs_of_press(commit["press_id"]):
            if job["run_status"] not in ("RUNNING", "COMPLETED"):
                continue
            mold = DB.molds.get(job["mold_id"])
            if mold is None or mold["customer_id"] != commit["customer_id"]:
                continue
            if job["_start_dt"] < commit["_start_dt"] or job["_end_dt"] > commit["_end_dt"]:
                continue
            consumed += services.duration_minutes(job)
        committed = commit["committed_minutes"]
        commit["consumed_minutes"] = consumed
        commit["utilization_bp"] = calcs.floor_div(consumed * 10000, committed)
        shortfall = max(0, committed - consumed)
        commit["shortfall_minutes"] = shortfall
        if commit["shortfall_policy"] == "STRICT":
            commit["shortfall_fee_cents"] = calcs.strict_shortfall_fee(
                shortfall, press["hourly_rate_cents"])
        else:
            commit["shortfall_fee_cents"] = calcs.goodwill_shortfall_fee(
                shortfall, committed, press["hourly_rate_cents"])
        commit["status"] = "SETTLED"
        touch(commit)
        return respond(public(commit))

    @app.post("/capacity-commits/<cid>/cancel")
    @endpoint("PlantAdmin")
    def cancel_commit(cid):
        commit = lookup("commits", cid)
        body = v.body()
        v.want_str(body, "reason")
        if commit["status"] != "OPEN":
            fail("ERR_CAPACITY_COMMIT_NOT_OPEN", "Only an open commitment may be cancelled.")
        commit["status"] = "CANCELLED"
        touch(commit)
        return respond(public(commit))
