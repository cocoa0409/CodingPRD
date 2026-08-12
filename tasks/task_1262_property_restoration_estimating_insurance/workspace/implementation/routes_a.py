"""Routes: clock, carriers, price lists, customers, policies, claims,
inspections, moisture readings, photos."""
from datetime import timedelta

from store import (DB, now, fmt_clock, new_id, stamp_new, touch, dec, rhu,
                   MOISTURE_WET_MARGIN)
from errors import (ApiError, ok_object, page, public, auth, require_roles,
                    body, req_field, opt_field, as_str, as_bool, as_int,
                    as_num, as_enum, as_dt, paginate_args, sorted_items,
                    ok_list)
from domain import (get, find, carrier_of_claim, policy_of_claim,
                    compute_drying_days, clock_sweep)

CA = "ContractorAdmin"
EST = "Estimator"
FT = "FieldTechnician"
ADJ = "Adjuster"
CUST = "Customer"

CLAIM_STATUSES = {
    "INTAKE", "ASSESSING", "ESTIMATING", "NEGOTIATING", "APPROVED",
    "AUTHORIZED", "IN_PROGRESS", "ON_HOLD", "COMPLETE", "INVOICED",
    "CLOSED", "DENIED", "WITHDRAWN",
}


def register(a):
    # ---------------------------------------------------------------- clock
    @a.post("/v1/_clock/set_current_utc")
    def set_current_utc():
        uid, role = auth()
        require_roles(role, {CA})
        data = body()
        target = as_dt(req_field(data, "to_iso8601"), "to_iso8601")
        from store import set_clock
        set_clock(target)
        expired = clock_sweep()
        return ok_object({"current_utc": fmt_clock(now()),
                          "expired_round_ids": expired})

    # ------------------------------------------------------------ carriers
    @a.post("/v1/carriers")
    def create_carrier():
        uid, role = auth()
        require_roles(role, {CA})
        data = body()
        rec = {
            "id": new_id(),
            "name": as_str(req_field(data, "name"), "name"),
            "tax_rate": as_num(req_field(data, "tax_rate"), "tax_rate"),
            "overhead_rate": as_num(opt_field(data, "overhead_rate", 0.10), "overhead_rate"),
            "profit_rate": as_num(opt_field(data, "profit_rate", 0.10), "profit_rate"),
            "o_and_p_min_trades": as_int(opt_field(data, "o_and_p_min_trades", 3), "o_and_p_min_trades"),
            "negotiation_response_days": as_int(opt_field(data, "negotiation_response_days", 7), "negotiation_response_days"),
        }
        stamp_new(rec)
        DB["carriers"][rec["id"]] = rec
        return ok_object(public(rec), 201)

    @a.get("/v1/carriers/<cid>")
    def get_carrier(cid):
        uid, role = auth()
        require_roles(role, {CA, EST, ADJ})
        return ok_object(public(get("carriers", cid)))

    @a.post("/v1/carriers/<cid>/price-list-entries")
    def create_price_entry(cid):
        uid, role = auth()
        require_roles(role, {CA})
        carrier = get("carriers", cid)
        data = body()
        rec = {
            "id": new_id(),
            "carrier_id": cid,
            "category_code": as_str(req_field(data, "category_code"), "category_code"),
            "trade": as_str(req_field(data, "trade"), "trade"),
            "kind": as_enum(req_field(data, "kind"), "kind", {"MATERIAL", "LABOR", "EQUIPMENT"}),
            "unit": as_str(req_field(data, "unit"), "unit"),
            "unit_price_cents": as_int(req_field(data, "unit_price_cents"), "unit_price_cents"),
            "tax_applicable": as_bool(opt_field(data, "tax_applicable", False), "tax_applicable"),
            "o_and_p_eligible": as_bool(opt_field(data, "o_and_p_eligible", False), "o_and_p_eligible"),
            "default_depreciation_pct": as_num(opt_field(data, "default_depreciation_pct", 0), "default_depreciation_pct"),
            "effective_from": None,
            "effective_to": None,
        }
        if rec["unit_price_cents"] < 0:
            raise ApiError("ERR_INVALID_REQUEST", "unit_price_cents must be >= 0")
        ef = as_dt(req_field(data, "effective_from"), "effective_from")
        et = as_dt(req_field(data, "effective_to"), "effective_to")
        if not et > ef:
            raise ApiError("ERR_INVALID_REQUEST", "effective_to must be strictly later than effective_from")
        rec["effective_from"] = fmt_clock(ef)
        rec["effective_to"] = fmt_clock(et)
        rec["_effective_from"] = ef
        rec["_effective_to"] = et
        # half-open window overlap per (carrier_id, category_code); adjacency ok
        for ex in DB["price_list_entries"].values():
            if ex["carrier_id"] == cid and ex["category_code"] == rec["category_code"]:
                if ef < ex["_effective_to"] and et > ex["_effective_from"]:
                    raise ApiError("ERR_PRICE_WINDOW_OVERLAP",
                                   "Window overlaps an existing entry for this carrier and category_code")
        stamp_new(rec)
        DB["price_list_entries"][rec["id"]] = rec
        return ok_object(public(rec), 201)

    @a.get("/v1/carriers/<cid>/price-list-entries")
    def list_price_entries(cid):
        uid, role = auth()
        require_roles(role, {CA, EST, ADJ})
        get("carriers", cid)
        items = [e for e in DB["price_list_entries"].values() if e["carrier_id"] == cid]
        from flask import request
        return page(items, {"category_code": request.args.get("category_code")})

    # ----------------------------------------------------------- customers
    @a.post("/v1/customers")
    def create_customer():
        uid, role = auth()
        require_roles(role, {CA})
        data = body()
        rec = {
            "id": new_id(),
            "full_name": as_str(req_field(data, "full_name"), "full_name"),
            "email": as_str(req_field(data, "email"), "email"),
        }
        stamp_new(rec)
        DB["customers"][rec["id"]] = rec
        return ok_object(public(rec), 201)

    # ------------------------------------------------------------ policies
    @a.post("/v1/policies")
    def create_policy():
        uid, role = auth()
        require_roles(role, {CA})
        data = body()
        customer_id = opt_field(data, "customer_id")
        carrier_id = opt_field(data, "carrier_id")
        if customer_id is not None and isinstance(customer_id, str):
            get("customers", customer_id)
        if carrier_id is not None and isinstance(carrier_id, str):
            get("carriers", carrier_id)
        customer_id = as_str(req_field(data, "customer_id"), "customer_id")
        carrier_id = as_str(req_field(data, "carrier_id"), "carrier_id")
        rec = {
            "id": new_id(),
            "customer_id": customer_id,
            "carrier_id": carrier_id,
            "policy_number": as_str(req_field(data, "policy_number"), "policy_number"),
            "coverage_a_limit_cents": as_int(req_field(data, "coverage_a_limit_cents"), "coverage_a_limit_cents"),
            "deductible_type": as_enum(req_field(data, "deductible_type"), "deductible_type",
                                       {"FLAT", "PERCENT_OF_COVERAGE_A"}),
            "recoverable_depreciation": as_bool(req_field(data, "recoverable_depreciation"), "recoverable_depreciation"),
            "ordinance_coverage_pct": as_num(opt_field(data, "ordinance_coverage_pct", 0), "ordinance_coverage_pct"),
            "ordinance_flat_cap_cents": as_int(opt_field(data, "ordinance_flat_cap_cents", 0), "ordinance_flat_cap_cents"),
        }
        if rec["coverage_a_limit_cents"] <= 0:
            raise ApiError("ERR_INVALID_REQUEST", "coverage_a_limit_cents must be > 0")
        if rec["deductible_type"] == "FLAT":
            if "deductible_pct" in data and data["deductible_pct"] is not None:
                raise ApiError("ERR_INVALID_REQUEST", "deductible_pct is not valid for FLAT deductible_type")
            rec["flat_deductible_cents"] = as_int(req_field(data, "flat_deductible_cents"), "flat_deductible_cents")
            rec["deductible_pct"] = None
        else:
            if "flat_deductible_cents" in data and data["flat_deductible_cents"] is not None:
                raise ApiError("ERR_INVALID_REQUEST", "flat_deductible_cents is not valid for PERCENT_OF_COVERAGE_A deductible_type")
            rec["deductible_pct"] = as_num(req_field(data, "deductible_pct"), "deductible_pct")
            rec["flat_deductible_cents"] = None
        ps = as_dt(req_field(data, "period_start"), "period_start")
        pe = as_dt(req_field(data, "period_end"), "period_end")
        rec["period_start"] = fmt_clock(ps)
        rec["period_end"] = fmt_clock(pe)
        rec["_period_start"] = ps
        rec["_period_end"] = pe
        rec["ordinance_limit_cents"] = min(
            rhu(dec(rec["ordinance_coverage_pct"]) * dec(rec["coverage_a_limit_cents"])),
            rec["ordinance_flat_cap_cents"])
        stamp_new(rec)
        DB["policies"][rec["id"]] = rec
        return ok_object(public(rec), 201)

    @a.get("/v1/policies/<pid>")
    def get_policy(pid):
        uid, role = auth()
        require_roles(role, {CA, EST, ADJ})
        return ok_object(public(get("policies", pid)))

    @a.get("/v1/policies")
    def list_policies():
        uid, role = auth()
        require_roles(role, {CA, EST, ADJ})
        from flask import request
        return page(list(DB["policies"].values()), {
            "customer_id": request.args.get("customer_id"),
            "carrier_id": request.args.get("carrier_id"),
        })

    # -------------------------------------------------------------- claims
    @a.post("/v1/claims")
    def create_claim():
        uid, role = auth()
        require_roles(role, {CA})
        data = body()
        policy_id = opt_field(data, "policy_id")
        if policy_id is not None and isinstance(policy_id, str):
            get("policies", policy_id)
        policy_id = as_str(req_field(data, "policy_id"), "policy_id")
        policy = DB["policies"].get(policy_id)
        if policy is None:
            raise ApiError("ERR_RESOURCE_NOT_FOUND", "policy_id does not resolve")
        cause = as_enum(req_field(data, "cause_of_loss"), "cause_of_loss",
                        {"WATER", "FIRE", "WIND", "MOLD", "HAIL"})
        dol = as_dt(req_field(data, "date_of_loss"), "date_of_loss")
        loss_address = as_str(opt_field(data, "loss_address", ""), "loss_address")
        if not (policy["_period_start"] <= dol <= policy["_period_end"]):
            raise ApiError("ERR_POLICY_WINDOW_VIOLATION",
                           "date_of_loss is outside the policy period")
        if policy["deductible_type"] == "FLAT":
            deductible = policy["flat_deductible_cents"]
        else:
            deductible = rhu(dec(policy["deductible_pct"]) * dec(policy["coverage_a_limit_cents"]))
        rec = {
            "id": new_id(),
            "policy_id": policy_id,
            "customer_id": policy["customer_id"],
            "cause_of_loss": cause,
            "date_of_loss": fmt_clock(dol),
            "loss_address": loss_address,
            "status": "INTAKE",
            "deductible_cents": deductible,
            "rcv_total_cents": 0,
            "acv_total_cents": 0,
            "recoverable_depreciation_cents": 0,
            "carrier_paid_cents": 0,
            "customer_paid_cents": 0,
            "deductible_collected_cents": 0,
            "outstanding_balance_cents": 0,
            "ordinance_consumed_cents": 0,
            "payment_posture": "UNPAID",
            "_date_of_loss": dol,
        }
        stamp_new(rec)
        DB["claims"][rec["id"]] = rec
        return ok_object(public(rec), 201)

    @a.get("/v1/claims")
    def list_claims():
        uid, role = auth()
        require_roles(role, {CA, EST, ADJ, CUST})
        from flask import request
        items = list(DB["claims"].values())
        if role == CUST:
            items = [c for c in items if c["customer_id"] == uid]
        return page(items, {
            "policy_id": request.args.get("policy_id"),
            "customer_id": request.args.get("customer_id"),
            "status": request.args.get("status"),
        })

    def claim_visible_to(claim, uid, role):
        if role == CUST and claim["customer_id"] != uid:
            raise ApiError("ERR_RESOURCE_NOT_FOUND", "Resource not found")

    @a.get("/v1/claims/<cid>")
    def get_claim(cid):
        uid, role = auth()
        require_roles(role, {CA, EST, ADJ, CUST})
        claim = get("claims", cid)
        claim_visible_to(claim, uid, role)
        return ok_object(public(claim))

    @a.post("/v1/claims/<cid>/transition")
    def claim_transition(cid):
        uid, role = auth()
        require_roles(role, {CA, ADJ})
        claim = get("claims", cid)
        data = body()
        to = as_enum(req_field(data, "to"), "to", CLAIM_STATUSES)
        cur = claim["status"]
        edges = set()
        if role == CA:
            edges = {
                ("INTAKE", "ASSESSING"), ("ASSESSING", "ESTIMATING"),
                ("INTAKE", "WITHDRAWN"), ("ASSESSING", "WITHDRAWN"),
                ("ESTIMATING", "WITHDRAWN"), ("NEGOTIATING", "WITHDRAWN"),
            }
        elif role == ADJ:
            edges = {
                ("INTAKE", "DENIED"), ("ASSESSING", "DENIED"),
                ("ESTIMATING", "DENIED"),
            }
        if (cur, to) not in edges:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "No declared edge from %s to %s" % (cur, to))
        claim["status"] = to
        touch(claim)
        return ok_object(public(claim))

    @a.post("/v1/claims/<cid>/start-work")
    def start_work(cid):
        uid, role = auth()
        require_roles(role, {CA})
        claim = get("claims", cid)
        if claim["status"] not in ("APPROVED", "AUTHORIZED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "start-work requires APPROVED or AUTHORIZED")
        was = [w for w in DB["work_authorizations"].values()
               if w["claim_id"] == cid and w["status"] == "SIGNED"
               and w["deductible_acknowledged"]]
        if not was:
            raise ApiError("ERR_AUTHORIZATION_MISSING",
                           "A signed work authorization with deductible acknowledgment is required")
        wa = sorted(was, key=lambda r: r["_seq"])[-1]
        if claim["cause_of_loss"] == "MOLD":
            ok = False
            for est in DB["estimates"].values():
                if est["claim_id"] == cid and est["status"] in ("APPROVED", "LOCKED"):
                    for line in DB["estimate_lines"].values():
                        if (line["estimate_id"] == est["id"]
                                and line["negotiation_status"] != "REMOVED"
                                and line["trade"] == "CONTAINMENT"):
                            ok = True
            if not ok:
                raise ApiError("ERR_CONTAINMENT_REQUIRED",
                               "MOLD claims require a CONTAINMENT-trade line in an approved estimate")
        if now() > wa["_expires_at_instant"]:
            raise ApiError("ERR_AUTHORIZATION_EXPIRED",
                           "The signed work authorization has expired")
        claim["status"] = "IN_PROGRESS"
        touch(claim)
        return ok_object(public(claim))

    @a.post("/v1/claims/<cid>/complete-work")
    def complete_work(cid):
        uid, role = auth()
        require_roles(role, {CA})
        claim = get("claims", cid)
        if claim["status"] != "IN_PROGRESS":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "complete-work requires IN_PROGRESS")
        if claim["cause_of_loss"] in ("WATER", "MOLD"):
            insp_ids = {i["id"] for i in DB["inspections"].values()
                        if i["claim_id"] == cid}
            groups = {}
            for r in DB["moisture_readings"].values():
                if r["inspection_id"] not in insp_ids:
                    continue
                groups.setdefault((r["area"], r["material"]), []).append(r)
            for key, readings in groups.items():
                if not any(r["is_wet"] for r in readings):
                    continue
                latest = max(readings,
                             key=lambda r: (r["_recorded_at"], r["_created_instant"], r["_seq"]))
                if dec(latest["reading_value"]) > dec(latest["dry_standard"]) + MOISTURE_WET_MARGIN:
                    raise ApiError("ERR_MOISTURE_GATE_FAILED",
                                   "Latest reading for a wet area/material still exceeds the dry standard")
        for cu in DB["code_upgrades"].values():
            if cu["claim_id"] == cid and cu["status"] == "IDENTIFIED":
                raise ApiError("ERR_CODE_UPGRADES_PENDING",
                               "Code upgrades are still IDENTIFIED on this claim")
        claim["status"] = "COMPLETE"
        touch(claim)
        return ok_object(public(claim))

    @a.get("/v1/claims/<cid>/financial-summary")
    def financial_summary(cid):
        uid, role = auth()
        require_roles(role, {CA, EST, ADJ, CUST})
        claim = get("claims", cid)
        claim_visible_to(claim, uid, role)
        approved = [e for e in DB["estimates"].values()
                    if e["claim_id"] == cid and e["status"] in ("APPROVED", "LOCKED")]
        policy = policy_of_claim(claim)
        data = {
            "rcv_total_cents": sum(e["grand_total_cents"] for e in approved),
            "acv_total_cents": sum(e["acv_total_cents"] for e in approved),
            "grand_total_cents": sum(e["grand_total_cents"] for e in approved),
            "depreciation_total_cents": sum(e["depreciation_total_cents"] for e in approved),
            "recoverable_depreciation_cents": sum(e["recoverable_depreciation_cents"] for e in approved),
            "deductible_cents": claim["deductible_cents"],
            "deductible_collected_cents": claim["deductible_collected_cents"],
            "carrier_paid_cents": claim["carrier_paid_cents"],
            "customer_paid_cents": claim["customer_paid_cents"],
            "outstanding_balance_cents": claim["outstanding_balance_cents"],
            "ordinance_limit_cents": policy["ordinance_limit_cents"],
            "ordinance_consumed_cents": claim["ordinance_consumed_cents"],
            "payment_posture": claim["payment_posture"],
        }
        return ok_object(data)

    # --------------------------------------------------------- inspections
    @a.post("/v1/claims/<cid>/inspections")
    def create_inspection(cid):
        uid, role = auth()
        require_roles(role, {FT})
        get("claims", cid)
        claim = DB["claims"][cid]
        data = body()
        rec = {
            "id": new_id(),
            "claim_id": cid,
            "type": as_enum(req_field(data, "type"), "type", {"INITIAL", "VERIFICATION"}),
            "assignee_id": as_str(req_field(data, "assignee_id"), "assignee_id"),
            "status": "SCHEDULED",
            "completed_at": None,
            "drying_days_worst_variant": None,
            "drying_days_mean_variant": None,
        }
        ss = as_dt(req_field(data, "scheduled_start"), "scheduled_start")
        se = as_dt(req_field(data, "scheduled_end"), "scheduled_end")
        if not se > ss:
            raise ApiError("ERR_INVALID_REQUEST", "scheduled_end must be strictly later than scheduled_start")
        rec["scheduled_start"] = fmt_clock(ss)
        rec["scheduled_end"] = fmt_clock(se)
        rec["_scheduled_start"] = ss
        rec["_scheduled_end"] = se
        if claim["status"] not in ("INTAKE", "ASSESSING"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Inspections may be created only while the claim is INTAKE or ASSESSING")
        buffer = timedelta(minutes=30)
        for ex in DB["inspections"].values():
            if ex["assignee_id"] != rec["assignee_id"] or ex["status"] != "SCHEDULED":
                continue
            if ss < ex["_scheduled_end"] + buffer and se > ex["_scheduled_start"] - buffer:
                raise ApiError("ERR_INSPECTION_SCHEDULE_CONFLICT",
                               "Window conflicts with an existing scheduled inspection for this assignee")
        stamp_new(rec)
        DB["inspections"][rec["id"]] = rec
        return ok_object(public(rec), 201)

    @a.get("/v1/claims/<cid>/inspections")
    def list_inspections(cid):
        uid, role = auth()
        require_roles(role, {CA, EST, FT, ADJ})
        get("claims", cid)
        from flask import request
        items = [i for i in DB["inspections"].values() if i["claim_id"] == cid]
        return page(items, {"status": request.args.get("status")})

    @a.get("/v1/inspections/<iid>")
    def get_inspection(iid):
        uid, role = auth()
        require_roles(role, {CA, EST, FT, ADJ})
        return ok_object(public(get("inspections", iid)))

    @a.post("/v1/inspections/<iid>/complete")
    def complete_inspection(iid):
        uid, role = auth()
        require_roles(role, {FT})
        insp = get("inspections", iid)
        if insp["status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Only a SCHEDULED inspection can be completed")
        claim = DB["claims"][insp["claim_id"]]
        photos = [p for p in DB["photos"].values()
                  if p.get("inspection_id") == iid
                  and p["tag"] in ("LOSS_OVERVIEW", "AREA", "MOISTURE_PROOF")]
        if len(photos) < 3:
            raise ApiError("ERR_INSPECTION_EVIDENCE_INSUFFICIENT",
                           "At least 3 evidence photos are required")
        readings = [r for r in DB["moisture_readings"].values()
                    if r["inspection_id"] == iid]
        if claim["cause_of_loss"] in ("WATER", "MOLD") and len(readings) < 1:
            raise ApiError("ERR_INSPECTION_EVIDENCE_INSUFFICIENT",
                           "At least one moisture reading is required for WATER/MOLD claims")
        worst, mean = compute_drying_days(readings)
        insp["status"] = "COMPLETED"
        insp["completed_at"] = fmt_clock(now())
        insp["drying_days_worst_variant"] = worst
        insp["drying_days_mean_variant"] = mean
        touch(insp)
        return ok_object(public(insp))

    @a.post("/v1/inspections/<iid>/cancel")
    def cancel_inspection(iid):
        uid, role = auth()
        require_roles(role, {FT})
        insp = get("inspections", iid)
        if insp["status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Only a SCHEDULED inspection can be canceled")
        insp["status"] = "CANCELED"
        touch(insp)
        return ok_object(public(insp))

    @a.post("/v1/inspections/<iid>/readings")
    def create_reading(iid):
        uid, role = auth()
        require_roles(role, {FT})
        insp = get("inspections", iid)
        data = body()
        rec = {
            "id": new_id(),
            "inspection_id": iid,
            "area": as_str(req_field(data, "area"), "area"),
            "material": as_str(req_field(data, "material"), "material"),
            "reading_value": as_num(req_field(data, "reading_value"), "reading_value"),
            "dry_standard": as_num(req_field(data, "dry_standard"), "dry_standard"),
        }
        ra = as_dt(req_field(data, "recorded_at"), "recorded_at")
        rec["recorded_at"] = fmt_clock(ra)
        rec["_recorded_at"] = ra
        if insp["status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Readings may be added only while the inspection is SCHEDULED")
        rec["is_wet"] = bool(dec(rec["reading_value"]) > dec(rec["dry_standard"]) + MOISTURE_WET_MARGIN)
        stamp_new(rec)
        DB["moisture_readings"][rec["id"]] = rec
        return ok_object(public(rec), 201)

    @a.get("/v1/inspections/<iid>/readings")
    def list_readings(iid):
        uid, role = auth()
        require_roles(role, {CA, EST, FT, ADJ})
        get("inspections", iid)
        from flask import request
        items = [r for r in DB["moisture_readings"].values() if r["inspection_id"] == iid]
        return page(items, {"area": request.args.get("area")})

    # -------------------------------------------------------------- photos
    @a.post("/v1/photos")
    def create_photo():
        uid, role = auth()
        require_roles(role, {FT, EST})
        data = body()
        claim_id = opt_field(data, "claim_id")
        inspection_id = opt_field(data, "inspection_id")
        supplement_id = opt_field(data, "supplement_id")
        if claim_id is not None and isinstance(claim_id, str):
            get("claims", claim_id)
        if inspection_id is not None and isinstance(inspection_id, str):
            get("inspections", inspection_id)
        if supplement_id is not None and isinstance(supplement_id, str):
            get("supplements", supplement_id)
        claim_id = as_str(req_field(data, "claim_id"), "claim_id")
        if claim_id not in DB["claims"]:
            raise ApiError("ERR_RESOURCE_NOT_FOUND", "claim_id does not resolve")
        if (inspection_id is None) == (supplement_id is None):
            raise ApiError("ERR_INVALID_REQUEST",
                           "Exactly one of inspection_id or supplement_id must be set")
        tag = as_enum(req_field(data, "tag"), "tag",
                      {"LOSS_OVERVIEW", "AREA", "MOISTURE_PROOF", "SUPPLEMENT_EVIDENCE", "COMPLETION"})
        if supplement_id is not None and tag != "SUPPLEMENT_EVIDENCE":
            raise ApiError("ERR_INVALID_REQUEST",
                           "A photo attached via supplement_id must carry SUPPLEMENT_EVIDENCE")
        if inspection_id is not None:
            as_str(inspection_id, "inspection_id")
            if inspection_id not in DB["inspections"]:
                raise ApiError("ERR_RESOURCE_NOT_FOUND", "inspection_id does not resolve")
        if supplement_id is not None:
            as_str(supplement_id, "supplement_id")
            if supplement_id not in DB["supplements"]:
                raise ApiError("ERR_RESOURCE_NOT_FOUND", "supplement_id does not resolve")
        cap = as_dt(req_field(data, "captured_at"), "captured_at")
        rec = {
            "id": new_id(),
            "claim_id": claim_id,
            "inspection_id": inspection_id,
            "supplement_id": supplement_id,
            "tag": tag,
            "file_ref": as_str(req_field(data, "file_ref"), "file_ref"),
            "captured_at": fmt_clock(cap),
        }
        stamp_new(rec)
        DB["photos"][rec["id"]] = rec
        return ok_object(public(rec), 201)

    @a.get("/v1/photos/<pid>")
    def get_photo(pid):
        uid, role = auth()
        require_roles(role, {CA, EST, FT, ADJ})
        return ok_object(public(get("photos", pid)))

    @a.get("/v1/photos")
    def list_photos():
        uid, role = auth()
        require_roles(role, {CA, EST, FT, ADJ})
        from flask import request
        return page(list(DB["photos"].values()), {
            "claim_id": request.args.get("claim_id"),
            "inspection_id": request.args.get("inspection_id"),
            "supplement_id": request.args.get("supplement_id"),
            "tag": request.args.get("tag"),
        })
