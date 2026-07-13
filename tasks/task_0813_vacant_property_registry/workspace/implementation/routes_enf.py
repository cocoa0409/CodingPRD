"""Routes: inspections, violations, fines, liens, abatement, receivership, demolition."""
from flask import request

import calc
import serialize
import services
from store import db
from envelope import ApiError, success, list_response
from services import get_or_404, stamp_new, touch
from reqhelp import (
    authenticate, check_property_owner, get_body, need, need_enum, need_int,
    need_datetime, parse_pagination, ordered, page, READ_ROLES,
)
from util import parse_iso, format_iso, add_days

GROUNDS = {"CHRONIC_NUISANCE", "STRUCTURAL_HAZARD", "TAX_DELINQUENCY"}


def _find_standard(code):
    for s in db.maintenance_standards.values():
        if s["code"] == code:
            return s
    return None


def _cite_or_reopen(insp, code):
    prop_id = insp["property_id"]
    std = _find_standard(code)
    clock = db.clock
    deadline = format_iso(add_days(clock, std["cure_period_days"]))
    cured = [v for v in db.violations.values()
             if v["property_id"] == prop_id and v["standard_code"] == code
             and v["status"] == "CURED"]
    if cured:
        v = ordered(cured)[-1]
        v["status"] = "OPEN"
        v["cured_at"] = None
        v["cited_at"] = format_iso(clock)
        v["cure_deadline_at"] = deadline
        touch(v)
    else:
        v = {
            "property_id": prop_id,
            "inspection_id": insp["id"],
            "standard_code": code,
            "severity_weight": std["severity_weight"],
            "status": "OPEN",
            "cited_at": format_iso(clock),
            "cure_deadline_at": deadline,
            "cured_at": None,
        }
        stamp_new(v)
        db.violations[v["id"]] = v


def register(app):

    # --- inspections -----------------------------------------------------
    @app.post("/registry/inspections")
    def create_inspection():
        authenticate({"CodeOfficer"})
        body = get_body()
        prop = db.properties.get(body.get("property_id"))
        if prop is None:
            raise ApiError("ERR_PROPERTY_NOT_FOUND", "property_id does not resolve")
        need(body, "inspector_badge")
        start = need_datetime(body, "scheduled_start")
        end = need_datetime(body, "scheduled_end")
        if not end > start:
            raise ApiError("ERR_INVALID_WINDOW", "scheduled_end must be after scheduled_start")
        badge = body["inspector_badge"]
        for other in db.inspections.values():
            if other["status"] != "SCHEDULED" or other["inspector_badge"] != badge:
                continue
            o_start = parse_iso(other["scheduled_start"])
            o_end = parse_iso(other["scheduled_end"])
            if start < o_end and o_start < end:  # half-open overlap
                raise ApiError("ERR_INSPECTOR_DOUBLE_BOOKED", "inspector already booked")
        insp = {
            "property_id": prop["id"],
            "inspector_badge": badge,
            "scheduled_start": body["scheduled_start"],
            "scheduled_end": body["scheduled_end"],
            "status": "SCHEDULED",
            "result": None,
            "failed_standard_codes": [],
            "performed_at": None,
        }
        stamp_new(insp)
        db.inspections[insp["id"]] = insp
        return success(serialize.inspection(insp), 201)

    @app.get("/registry/inspections/<iid>")
    def get_inspection(iid):
        authenticate(READ_ROLES)
        insp = get_or_404(db.inspections, iid, "ERR_INSPECTION_NOT_FOUND")
        return success(serialize.inspection(insp), 200)

    @app.get("/registry/inspections")
    def list_inspections():
        authenticate(READ_ROLES)
        limit, offset = parse_pagination()
        items = list(db.inspections.values())
        args = request.args
        if "property_id" in args:
            items = [i for i in items if i["property_id"] == args.get("property_id")]
        if "inspector_badge" in args:
            items = [i for i in items if i["inspector_badge"] == args.get("inspector_badge")]
        if "status" in args:
            items = [i for i in items if i["status"] == args.get("status")]
        items = ordered(items)
        total = len(items)
        data = [serialize.inspection(i) for i in page(items, limit, offset)]
        return list_response(data, total, limit, offset)

    @app.post("/registry/inspections/<iid>/complete")
    def complete_inspection(iid):
        authenticate({"CodeOfficer"})
        insp = get_or_404(db.inspections, iid, "ERR_INSPECTION_NOT_FOUND")
        body = get_body()
        result = need_enum(body, "result", {"PASS", "FAIL"})
        failed = body.get("failed_standard_codes")
        if result == "PASS":
            if failed not in (None, []):
                raise ApiError("ERR_VALIDATION", "PASS must have empty failed_standard_codes")
            failed_codes = []
        else:
            if not isinstance(failed, list) or len(failed) == 0:
                raise ApiError("ERR_VALIDATION", "FAIL requires non-empty failed_standard_codes")
            declared = {s["code"] for s in db.maintenance_standards.values()}
            for code in failed:
                if code not in declared:
                    raise ApiError("ERR_VALIDATION", "unknown standard code: %s" % code)
            failed_codes = failed
        if insp["status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", "inspection is not SCHEDULED")
        insp["status"] = "COMPLETED"
        insp["result"] = result
        insp["failed_standard_codes"] = failed_codes
        insp["performed_at"] = format_iso(db.clock)
        touch(insp)
        if result == "FAIL":
            for code in failed_codes:
                _cite_or_reopen(insp, code)
        return success(serialize.inspection(insp), 200)

    # --- violations ------------------------------------------------------
    @app.get("/registry/violations/<vid>")
    def get_violation(vid):
        authenticate(READ_ROLES)
        v = get_or_404(db.violations, vid, "ERR_VIOLATION_NOT_FOUND")
        return success(serialize.violation(v), 200)

    @app.get("/registry/violations")
    def list_violations():
        authenticate(READ_ROLES)
        limit, offset = parse_pagination()
        items = list(db.violations.values())
        args = request.args
        if "property_id" in args:
            items = [v for v in items if v["property_id"] == args.get("property_id")]
        if "inspection_id" in args:
            items = [v for v in items if v["inspection_id"] == args.get("inspection_id")]
        if "status" in args:
            items = [v for v in items if v["status"] == args.get("status")]
        items = ordered(items)
        total = len(items)
        data = [serialize.violation(v) for v in page(items, limit, offset)]
        return list_response(data, total, limit, offset)

    @app.post("/registry/violations/<vid>/transition")
    def violation_transition(vid):
        authenticate({"CodeOfficer"})
        v = get_or_404(db.violations, vid, "ERR_VIOLATION_NOT_FOUND")
        body = get_body()
        action = need_enum(body, "action", {"CURE", "ESCALATE"})
        if action == "CURE":
            if v["status"] not in ("OPEN", "ESCALATED"):
                raise ApiError("ERR_INVALID_STATE", "violation cannot be cured")
            v["status"] = "CURED"
            v["cured_at"] = format_iso(db.clock)
            touch(v)
        else:  # ESCALATE
            if v["status"] != "OPEN":
                raise ApiError("ERR_INVALID_STATE", "only OPEN violations can escalate")
            if db.clock < parse_iso(v["cure_deadline_at"]):
                raise ApiError("ERR_CURE_PERIOD_ACTIVE", "cure period not yet elapsed")
            v["status"] = "ESCALATED"
            touch(v)
        return success(serialize.violation(v), 200)

    @app.post("/registry/violations/<vid>/fines")
    def assess_fine(vid):
        authenticate({"CodeOfficer"})
        v = get_or_404(db.violations, vid, "ERR_VIOLATION_NOT_FOUND")
        if v["status"] != "ESCALATED":
            raise ApiError("ERR_INVALID_STATE", "only ESCALATED violations can be fined")
        std = _find_standard(v["standard_code"])
        base = std["base_fine_cents"] if std else 0
        prop = db.properties.get(v["property_id"])
        fine = {
            "violation_id": v["id"],
            "property_id": v["property_id"],
            "base_amount_cents": base,
            "assessed_at": format_iso(db.clock),
            "daily_penalty_cents": calc.DAILY_PENALTY_CENTS,
            "finalized_amount_cents": None,
            "status": "ASSESSED",
            "dispute_reason": None,
            "disputed_at": None,
            "paid_at": None,
        }
        stamp_new(fine)
        db.fines[fine["id"]] = fine
        v["status"] = "FINED"
        touch(v)
        services.post_ledger(prop, "FINE_ASSESSED", base, "FINE", fine["id"], "Fine assessed")
        return success(serialize.fine(fine), 201)

    # --- fines -----------------------------------------------------------
    @app.get("/registry/fines/<fid>")
    def get_fine(fid):
        authenticate(READ_ROLES)
        f = get_or_404(db.fines, fid, "ERR_FINE_NOT_FOUND")
        return success(serialize.fine(f), 200)

    @app.get("/registry/fines")
    def list_fines():
        authenticate(READ_ROLES)
        limit, offset = parse_pagination()
        items = list(db.fines.values())
        args = request.args
        if "violation_id" in args:
            items = [f for f in items if f["violation_id"] == args.get("violation_id")]
        if "property_id" in args:
            items = [f for f in items if f["property_id"] == args.get("property_id")]
        if "status" in args:
            items = [f for f in items if f["status"] == args.get("status")]
        items = ordered(items)
        total = len(items)
        data = [serialize.fine(f) for f in page(items, limit, offset)]
        return list_response(data, total, limit, offset)

    @app.post("/registry/fines/<fid>/transition")
    def fine_transition(fid):
        uid, role = authenticate({"Registrant"})
        f = get_or_404(db.fines, fid, "ERR_FINE_NOT_FOUND")
        prop = db.properties.get(f["property_id"])
        check_property_owner(prop, uid, role)
        body = get_body()
        action = need_enum(body, "action", {"PAY", "DISPUTE"})
        if f["status"] != "ASSESSED":
            raise ApiError("ERR_INVALID_STATE", "fine is not ASSESSED")
        if action == "PAY":
            services.pay_fine(f, prop)
        else:
            services.dispute_fine(f, body.get("dispute_reason"))
        return success(serialize.fine(f), 200)

    @app.post("/registry/fines/<fid>/resolve-dispute")
    def resolve_dispute(fid):
        authenticate({"ProgramAdmin"})
        f = get_or_404(db.fines, fid, "ERR_FINE_NOT_FOUND")
        body = get_body()
        decision = need_enum(body, "decision", {"DENY", "WAIVE"})
        if f["status"] != "DISPUTED":
            raise ApiError("ERR_INVALID_STATE", "fine is not DISPUTED")
        prop = db.properties.get(f["property_id"])
        if decision == "DENY":
            services.deny_dispute(f)
        else:
            services.waive_fine(f, prop)
        return success(serialize.fine(f), 200)

    @app.post("/registry/fines/<fid>/record-lien")
    def record_lien(fid):
        authenticate({"ProgramAdmin"})
        f = get_or_404(db.fines, fid, "ERR_FINE_NOT_FOUND")
        if f["status"] != "ASSESSED":
            raise ApiError("ERR_INVALID_STATE", "fine is not ASSESSED")
        finalized = calc.fine_accrual(
            f["base_amount_cents"], f["daily_penalty_cents"],
            parse_iso(f["assessed_at"]), db.clock,
        )
        if finalized < calc.MIN_LIEN_CENTS:
            raise ApiError("ERR_LIEN_AMOUNT_TOO_LOW", "finalized accrual below lien floor")
        prop = db.properties.get(f["property_id"])
        services.record_lien(f, prop)
        return success(serialize.fine(f), 201)

    # --- liens -----------------------------------------------------------
    @app.get("/registry/liens/<lid>")
    def get_lien(lid):
        authenticate(READ_ROLES)
        l = get_or_404(db.liens, lid, "ERR_LIEN_NOT_FOUND")
        return success(serialize.lien(l), 200)

    @app.get("/registry/liens")
    def list_liens():
        authenticate(READ_ROLES)
        limit, offset = parse_pagination()
        items = list(db.liens.values())
        args = request.args
        if "property_id" in args:
            items = [l for l in items if l["property_id"] == args.get("property_id")]
        if "source_fine_id" in args:
            items = [l for l in items if l["source_fine_id"] == args.get("source_fine_id")]
        if "status" in args:
            items = [l for l in items if l["status"] == args.get("status")]
        items = ordered(items)
        total = len(items)
        data = [serialize.lien(l) for l in page(items, limit, offset)]
        return list_response(data, total, limit, offset)

    @app.post("/registry/liens/<lid>/pay")
    def lien_pay(lid):
        uid, role = authenticate({"Registrant"})
        l = get_or_404(db.liens, lid, "ERR_LIEN_NOT_FOUND")
        prop = db.properties.get(l["property_id"])
        check_property_owner(prop, uid, role)
        if l["status"] != "RECORDED":
            raise ApiError("ERR_INVALID_STATE", "lien is not RECORDED")
        l["status"] = "SATISFIED"
        l["satisfied_at"] = format_iso(db.clock)
        touch(l)
        return success(serialize.lien(l), 200)

    @app.post("/registry/liens/<lid>/foreclose")
    def lien_foreclose(lid):
        authenticate({"ProgramAdmin"})
        l = get_or_404(db.liens, lid, "ERR_LIEN_NOT_FOUND")
        if l["status"] != "RECORDED":
            raise ApiError("ERR_INVALID_STATE", "lien is not RECORDED")
        prop = db.properties.get(l["property_id"])
        if prop["foreclosure_status"] != "REO":
            raise ApiError("ERR_PROPERTY_NOT_REO", "property is not at REO")
        l["status"] = "FORECLOSED"
        l["satisfied_at"] = format_iso(db.clock)
        touch(l)
        return success(serialize.lien(l), 200)

    # --- abatement orders ------------------------------------------------
    @app.post("/registry/properties/<pid>/abatement-orders")
    def create_abatement(pid):
        authenticate({"ProgramAdmin"})
        prop = get_or_404(db.properties, pid, "ERR_PROPERTY_NOT_FOUND")
        body = get_body()
        need(body, "scheduled_start", "scheduled_end", "estimated_cost_cents")
        start = need_datetime(body, "scheduled_start")
        end = need_datetime(body, "scheduled_end")
        est = need_int(body, "estimated_cost_cents", 0)
        if not end > start:
            raise ApiError("ERR_INVALID_WINDOW", "scheduled_end must be after scheduled_start")
        buffer_s = calc.ABATEMENT_BUFFER_SECONDS
        for o in db.abatement_orders.values():
            if o["property_id"] != pid or o["status"] != "ORDERED":
                continue
            o_start = parse_iso(o["scheduled_start"])
            o_end = parse_iso(o["scheduled_end"])
            gap_after = (start - o_end).total_seconds()
            gap_before = (o_start - end).total_seconds()
            if gap_after <= buffer_s and gap_before <= buffer_s:
                raise ApiError("ERR_ABATEMENT_WINDOW_CONFLICT", "window within 24h of another order")
        if not any(v["property_id"] == pid and v["status"] in ("ESCALATED", "FINED")
                   for v in db.violations.values()):
            raise ApiError("ERR_NO_ABATABLE_VIOLATION", "no ESCALATED/FINED violation")
        order = {
            "property_id": pid,
            "ordered_at": format_iso(db.clock),
            "scheduled_start": body["scheduled_start"],
            "scheduled_end": body["scheduled_end"],
            "estimated_cost_cents": est,
            "actual_cost_cents": None,
            "admin_fee_cents": None,
            "recovered_amount_cents": None,
            "status": "ORDERED",
        }
        stamp_new(order)
        db.abatement_orders[order["id"]] = order
        return success(serialize.abatement_order(order), 201)

    @app.get("/registry/properties/<pid>/abatement-orders")
    def list_abatement(pid):
        authenticate(READ_ROLES)
        get_or_404(db.properties, pid, "ERR_PROPERTY_NOT_FOUND")
        limit, offset = parse_pagination()
        items = [a for a in db.abatement_orders.values() if a["property_id"] == pid]
        if "status" in request.args:
            items = [a for a in items if a["status"] == request.args.get("status")]
        items = ordered(items)
        total = len(items)
        data = [serialize.abatement_order(a) for a in page(items, limit, offset)]
        return list_response(data, total, limit, offset)

    @app.post("/registry/abatement-orders/<aid>/complete")
    def complete_abatement(aid):
        authenticate({"ProgramAdmin"})
        a = get_or_404(db.abatement_orders, aid, "ERR_ABATEMENT_ORDER_NOT_FOUND")
        body = get_body()
        actual = need_int(body, "actual_cost_cents", 0)
        if a["status"] != "ORDERED":
            raise ApiError("ERR_INVALID_STATE", "abatement order is not ORDERED")
        a["status"] = "COMPLETED"
        a["actual_cost_cents"] = actual
        admin_fee, recovered = calc.cost_recovery(actual)
        a["admin_fee_cents"] = admin_fee
        a["recovered_amount_cents"] = recovered
        touch(a)
        prop = db.properties.get(a["property_id"])
        services.post_ledger(prop, "ABATEMENT_RECOVERY", recovered, "ABATEMENT_ORDER",
                             a["id"], "Abatement cost recovery")
        return success(serialize.abatement_order(a), 200)

    # --- receivership referrals -----------------------------------------
    @app.post("/registry/properties/<pid>/receivership-referrals")
    def create_receivership(pid):
        authenticate({"ProgramAdmin"})
        prop = get_or_404(db.properties, pid, "ERR_PROPERTY_NOT_FOUND")
        body = get_body()
        need(body, "ground", "receiver_name")
        ground = need_enum(body, "ground", GROUNDS)
        if prop["foreclosure_status"] not in ("NOTICE_OF_DEFAULT", "LIS_PENDENS"):
            raise ApiError("ERR_FORECLOSURE_STAGE_INVALID", "foreclosure stage not eligible")
        ref = {
            "property_id": pid,
            "referred_at": format_iso(db.clock),
            "ground": ground,
            "receiver_name": body["receiver_name"],
            "status": "REFERRED",
            "decided_at": None,
        }
        stamp_new(ref)
        db.receivership_referrals[ref["id"]] = ref
        return success(serialize.receivership_referral(ref), 201)

    @app.get("/registry/properties/<pid>/receivership-referrals")
    def list_receivership(pid):
        authenticate(READ_ROLES)
        get_or_404(db.properties, pid, "ERR_PROPERTY_NOT_FOUND")
        limit, offset = parse_pagination()
        items = [r for r in db.receivership_referrals.values() if r["property_id"] == pid]
        if "status" in request.args:
            items = [r for r in items if r["status"] == request.args.get("status")]
        items = ordered(items)
        total = len(items)
        data = [serialize.receivership_referral(r) for r in page(items, limit, offset)]
        return list_response(data, total, limit, offset)

    @app.post("/registry/receivership-referrals/<rid>/decide")
    def decide_receivership(rid):
        authenticate({"ProgramAdmin"})
        ref = get_or_404(db.receivership_referrals, rid, "ERR_RECEIVERSHIP_NOT_FOUND")
        body = get_body()
        decision = need_enum(body, "decision", {"ACCEPT", "DENY"})
        if ref["status"] != "REFERRED":
            raise ApiError("ERR_INVALID_STATE", "referral is not REFERRED")
        ref["status"] = "ACCEPTED" if decision == "ACCEPT" else "DENIED"
        ref["decided_at"] = format_iso(db.clock)
        touch(ref)
        return success(serialize.receivership_referral(ref), 200)

    # --- demolition listings --------------------------------------------
    @app.post("/registry/demolition-listings")
    def create_demolition():
        authenticate({"ProgramAdmin"})
        body = get_body()
        prop = db.properties.get(body.get("property_id"))
        if prop is None:
            raise ApiError("ERR_PROPERTY_NOT_FOUND", "property_id does not resolve")
        if services.open_violation_count(prop["id"]) < calc.DEMOLITION_MIN_VIOLATIONS:
            raise ApiError("ERR_INSUFFICIENT_VIOLATIONS", "fewer than 3 open violations")
        outstanding = services.outstanding_balance(prop["id"])
        if outstanding < calc.DEMOLITION_MIN_BALANCE_CENTS:
            raise ApiError("ERR_BALANCE_BELOW_DEMOLITION_THRESHOLD", "balance below threshold")
        severity_sum = sum(
            v["severity_weight"] for v in db.violations.values()
            if v["property_id"] == prop["id"] and v["status"] in ("OPEN", "ESCALATED")
        )
        score = calc.demolition_priority(
            severity_sum, parse_iso(prop["registered_at"]), db.clock,
            outstanding, prop["foreclosure_status"],
        )
        d = {
            "property_id": prop["id"],
            "listed_at": format_iso(db.clock),
            "priority_score": score,
            "status": "LISTED",
            "demolition_date": None,
        }
        stamp_new(d)
        db.demolition_listings[d["id"]] = d
        return success(serialize.demolition_listing(d), 201)

    @app.get("/registry/properties/<pid>/demolition-listings")
    def list_demolition(pid):
        authenticate(READ_ROLES)
        get_or_404(db.properties, pid, "ERR_PROPERTY_NOT_FOUND")
        limit, offset = parse_pagination()
        items = [d for d in db.demolition_listings.values() if d["property_id"] == pid]
        if "status" in request.args:
            items = [d for d in items if d["status"] == request.args.get("status")]
        items = ordered(items)
        total = len(items)
        data = [serialize.demolition_listing(d) for d in page(items, limit, offset)]
        return list_response(data, total, limit, offset)

    @app.post("/registry/demolition-listings/<did>/schedule")
    def schedule_demolition(did):
        authenticate({"ProgramAdmin"})
        d = get_or_404(db.demolition_listings, did, "ERR_DEMOLITION_NOT_FOUND")
        body = get_body()
        need(body, "demolition_date")
        need_datetime(body, "demolition_date")
        if d["status"] != "LISTED":
            raise ApiError("ERR_INVALID_STATE", "listing is not LISTED")
        d["status"] = "SCHEDULED"
        d["demolition_date"] = body["demolition_date"]
        touch(d)
        return success(serialize.demolition_listing(d), 200)
