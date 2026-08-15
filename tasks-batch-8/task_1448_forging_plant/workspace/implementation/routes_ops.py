"""Routes: DieSet, WorkCenter, WorkOrder, ForgeRun (+ forge heats)."""
from decimal import Decimal

from core import (
    ALL_ROLES, DB, auth, body, success, list_response, apply_filters, view,
    new_record, touch, get_or_404, f_str, f_num, f_int, f_enum, f_id_list,
    parse_dt, clock_now, err, q2, ceil_int, D, recompute_order,
    reeval_heat_depleted, reeval_coverage, turnaround_ok,
)


def register(app):

    # ---------------- DieSet ----------------
    @app.post("/die-sets")
    def create_die():
        auth(["DieShopTechnician"])
        d = body()
        code = f_str(d, "die_set_code")
        family = f_str(d, "part_family")
        wear = f_int(d, "wear_limit_hits", min_inclusive=1)
        resinks = f_int(d, "max_resinks", min_inclusive=0)
        for x in DB["die_sets"].values():
            if x["die_set_code"] == code:
                raise err("ERR_INVALID_REQUEST", 400, f"die_set_code '{code}' already registered")
        rec = new_record("die_sets")
        rec.update({
            "die_set_code": code,
            "part_family": family,
            "wear_limit_hits": wear,
            "max_resinks": resinks,
            "cumulative_hits": 0,
            "resink_count": 0,
            "installed_work_center_id": None,
            "status": "AVAILABLE",
        })
        return success(view(rec), 201)

    @app.get("/die-sets")
    def list_dies():
        auth(ALL_ROLES)
        return list_response(apply_filters(
            DB["die_sets"].values(), ["status", "installed_work_center_id"]))

    @app.get("/die-sets/<rid>")
    def get_die(rid):
        auth(ALL_ROLES)
        return success(view(get_or_404("die_sets", rid)), 200)

    @app.post("/die-sets/<rid>/install")
    def install_die(rid):
        auth(["DieShopTechnician"])
        d = body()
        wc_id = f_str(d, "work_center_id")
        die = get_or_404("die_sets", rid)
        wc = get_or_404("work_centers", wc_id)
        if die["status"] != "AVAILABLE":
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"die set in status {die['status']} cannot be installed")
        for x in DB["die_sets"].values():
            if x["id"] != die["id"] and x["status"] == "INSTALLED" \
                    and x["installed_work_center_id"] == wc["id"]:
                raise err("ERR_WORKCENTER_HAS_DIE", 409,
                          "another die set is already INSTALLED on the work center")
        if wc["status"] != "UP":
            raise err("ERR_WORKCENTER_DOWN", 409, "work center is DOWN")
        die["status"] = "INSTALLED"
        die["installed_work_center_id"] = wc["id"]
        touch("die_sets", die)
        return success(view(die), 200)

    @app.post("/die-sets/<rid>/uninstall")
    def uninstall_die(rid):
        auth(["DieShopTechnician"])
        body()
        die = get_or_404("die_sets", rid)
        if die["status"] != "INSTALLED":
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"die set in status {die['status']} cannot be uninstalled")
        for r in DB["forge_runs"].values():
            if r["die_set_id"] == die["id"] and r["status"] in ("IN_PROGRESS", "FORGED"):
                raise err("ERR_DIE_IN_USE", 409,
                          "an active forge run references this die set")
        die["status"] = "AVAILABLE"
        die["installed_work_center_id"] = None
        touch("die_sets", die)
        return success(view(die), 200)

    @app.post("/die-sets/<rid>/start-resink")
    def start_resink(rid):
        auth(["DieShopTechnician"])
        body()
        die = get_or_404("die_sets", rid)
        if die["status"] != "WORN":
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"die set in status {die['status']} cannot start resink")
        if die["resink_count"] >= die["max_resinks"]:
            raise err("ERR_DIE_RESINK_LIMIT", 409, "resink budget exhausted")
        die["status"] = "RESINKING"
        touch("die_sets", die)
        return success(view(die), 200)

    @app.post("/die-sets/<rid>/complete-resink")
    def complete_resink(rid):
        auth(["DieShopTechnician"])
        body()
        die = get_or_404("die_sets", rid)
        if die["status"] != "RESINKING":
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"die set in status {die['status']} cannot complete resink")
        die["status"] = "AVAILABLE"
        die["cumulative_hits"] = 0
        die["resink_count"] += 1
        touch("die_sets", die)
        return success(view(die), 200)

    @app.post("/die-sets/<rid>/retire")
    def retire_die(rid):
        auth(["DieShopTechnician"])
        body()
        die = get_or_404("die_sets", rid)
        if die["status"] not in ("AVAILABLE", "WORN"):
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"die set in status {die['status']} cannot be retired")
        die["status"] = "RETIRED"
        touch("die_sets", die)
        return success(view(die), 200)

    # ---------------- WorkCenter ----------------
    @app.post("/work-centers")
    def create_wc():
        auth(["PlantManager"])
        d = body()
        code = f_str(d, "code")
        wtype = f_enum(d, "type", {"PRESS", "HAMMER"})
        tonnage = f_int(d, "rated_tonnage", min_inclusive=0)
        for x in DB["work_centers"].values():
            if x["code"] == code:
                raise err("ERR_INVALID_REQUEST", 400, f"work center code '{code}' already registered")
        rec = new_record("work_centers")
        rec.update({"code": code, "type": wtype, "rated_tonnage": tonnage, "status": "UP"})
        return success(view(rec), 201)

    @app.get("/work-centers")
    def list_wcs():
        auth(ALL_ROLES)
        return list_response(apply_filters(DB["work_centers"].values(), ["status", "type"]))

    @app.get("/work-centers/<rid>")
    def get_wc(rid):
        auth(ALL_ROLES)
        return success(view(get_or_404("work_centers", rid)), 200)

    @app.post("/work-centers/<rid>/set-status")
    def set_wc_status(rid):
        auth(["PlantManager"])
        d = body()
        status = f_enum(d, "status", {"UP", "DOWN"})
        wc = get_or_404("work_centers", rid)
        if wc["status"] != status:
            wc["status"] = status
            touch("work_centers", wc)
        return success(view(wc), 200)

    # ---------------- WorkOrder ----------------
    @app.post("/work-orders")
    def create_wo():
        auth(["SalesPlanner"])
        d = body()
        order_number = f_str(d, "order_number")
        customer_name = f_str(d, "customer_name")
        alloy_id = f_str(d, "alloy_spec_id")
        part_number = f_str(d, "part_number")
        ordered_qty = f_int(d, "ordered_qty", min_inclusive=1)
        part_net = f_num(d, "part_net_weight_lbs", min_exclusive=0)
        billet_weight = f_num(d, "billet_weight_lbs", min_exclusive=0)
        area = f_num(d, "projected_area_in2", min_exclusive=0)
        process = f_enum(d, "required_process", {"PRESS", "HAMMER"})
        t1_limit = f_num(d, "price_tier1_limit_tons", min_inclusive=0)
        t1_rate = f_int(d, "price_tier1_cents_per_ton", min_inclusive=0)
        t2_limit = f_num(d, "price_tier2_limit_tons", min_inclusive=0)
        t2_rate = f_int(d, "price_tier2_cents_per_ton", min_inclusive=0)
        t3_rate = f_int(d, "price_tier3_cents_per_ton", min_inclusive=0)
        scrap_rate = f_int(d, "scrap_recovery_rate_cents_per_lb", min_inclusive=0)
        if t2_limit <= t1_limit:
            raise err("ERR_INVALID_REQUEST", 400, "price_tier2_limit_tons must be > price_tier1_limit_tons")
        alloy = get_or_404("alloy_specs", alloy_id)
        # billet must cover flash + trim loss
        min_billet = part_net * (Decimal("1") + D(alloy["flash_allowance_pct"]) / Decimal("100"))
        if billet_weight < min_billet:
            raise err("ERR_BILLET_UNDERWEIGHT", 422,
                      "billet_weight_lbs below part_net_weight_lbs * (1 + flash_allowance_pct/100)")
        required_tonnage = max(1, ceil_int(area * D(alloy["flow_stress_ksi"]) / Decimal("2")))
        for x in DB["work_orders"].values():
            if x["order_number"] == order_number:
                raise err("ERR_INVALID_REQUEST", 400, f"order_number '{order_number}' already registered")
        rec = new_record("work_orders")
        rec.update({
            "order_number": order_number,
            "customer_name": customer_name,
            "alloy_spec_id": alloy_id,
            "part_number": part_number,
            "ordered_qty": ordered_qty,
            "part_net_weight_lbs": part_net,
            "billet_weight_lbs": billet_weight,
            "projected_area_in2": area,
            "required_process": process,
            "price_tier1_limit_tons": t1_limit,
            "price_tier1_cents_per_ton": t1_rate,
            "price_tier2_limit_tons": t2_limit,
            "price_tier2_cents_per_ton": t2_rate,
            "price_tier3_cents_per_ton": t3_rate,
            "scrap_recovery_rate_cents_per_lb": scrap_rate,
            "required_tonnage": required_tonnage,
            "forged_qty": 0,
            "trimmed_qty": 0,
            "shipped_qty": 0,
            "scrapped_qty": 0,
            "planned_billet_weight_lbs": q2(Decimal(ordered_qty) * billet_weight),
            "consumed_billet_weight_lbs": q2(Decimal("0")),
            "trimmed_net_lbs": q2(Decimal("0")),
            "status": "RELEASED",
        })
        return success(view(rec), 201)

    @app.get("/work-orders")
    def list_wos():
        auth(ALL_ROLES)
        return list_response(apply_filters(DB["work_orders"].values(), ["status", "alloy_spec_id"]))

    @app.get("/work-orders/<rid>")
    def get_wo(rid):
        auth(ALL_ROLES)
        return success(view(get_or_404("work_orders", rid)), 200)

    @app.post("/work-orders/<rid>/cancel")
    def cancel_wo(rid):
        auth(["SalesPlanner"])
        body()
        wo = get_or_404("work_orders", rid)
        if wo["status"] not in ("RELEASED", "IN_PROGRESS"):
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"work order in status {wo['status']} cannot be cancelled")
        runs = [r for r in DB["forge_runs"].values() if r["work_order_id"] == wo["id"]]
        if wo["status"] == "IN_PROGRESS":
            run_ids = {r["id"] for r in runs}
            if any(h["forge_run_id"] in run_ids for h in DB["forge_heats"].values()):
                raise err("ERR_ORDER_HAS_PROGRESS", 409,
                          "work-order cancel blocked: heats already recorded")
        for r in runs:
            if r["status"] in ("SCHEDULED", "IN_PROGRESS"):
                r["status"] = "CANCELLED"
                touch("forge_runs", r)
        wo["status"] = "CANCELLED"
        touch("work_orders", wo)
        return success(view(wo), 200)

    @app.post("/work-orders/<rid>/ship")
    def ship_wo(rid):
        auth(["SalesPlanner"])
        d = body()
        part_ids = f_id_list(d, "part_serial_ids")
        wo = get_or_404("work_orders", rid)
        parts = [get_or_404("part_serials", pid) for pid in part_ids]
        for p in parts:
            if p["work_order_id"] != wo["id"]:
                raise err("ERR_NOT_FOUND", 404,
                          f"part {p['id']} does not belong to work order {wo['id']}")
        for p in parts:
            if p["status"] != "INSPECTED":
                raise err("ERR_PART_NOT_INSPECTED", 409,
                          f"part {p['id']} is in status {p['status']}, not INSPECTED")
        for p in parts:
            p["status"] = "SHIPPED"
            touch("part_serials", p)
        recompute_order(wo)
        return success(view(wo), 200)

    # ---- nested order lists ----
    @app.get("/work-orders/<rid>/forge-runs")
    def list_wo_runs(rid):
        auth(ALL_ROLES)
        get_or_404("work_orders", rid)
        return list_response([r for r in DB["forge_runs"].values() if r["work_order_id"] == rid])

    @app.get("/work-orders/<rid>/quality-certs")
    def list_wo_certs(rid):
        auth(ALL_ROLES)
        get_or_404("work_orders", rid)
        return list_response([c for c in DB["quality_certs"].values() if c["work_order_id"] == rid])

    @app.get("/work-orders/<rid>/invoices")
    def list_wo_invoices(rid):
        auth(ALL_ROLES)
        get_or_404("work_orders", rid)
        return list_response([i for i in DB["invoices"].values() if i["work_order_id"] == rid])

    @app.get("/work-orders/<rid>/part-serials")
    def list_wo_parts(rid):
        auth(ALL_ROLES)
        get_or_404("work_orders", rid)
        return list_response([p for p in DB["part_serials"].values() if p["work_order_id"] == rid])

    # ---------------- ForgeRun ----------------
    @app.post("/forge-runs")
    def create_run():
        auth(["ForgeOperator"])
        d = body()
        wo_id = f_str(d, "work_order_id")
        die_id = f_str(d, "die_set_id")
        start = parse_dt(f_str(d, "planned_start"), "planned_start")
        end = parse_dt(f_str(d, "planned_end"), "planned_end")
        if end < start:
            raise err("ERR_INVALID_REQUEST", 400, "planned_end must be >= planned_start")
        planned_qty = f_int(d, "planned_qty", min_inclusive=1)
        expected = f_int(d, "expected_work_order_version")
        wc_id = d.get("work_center_id")
        if wc_id is not None and (not isinstance(wc_id, str) or not wc_id):
            raise err("ERR_INVALID_REQUEST", 400, "work_center_id must be a string id")
        wo = get_or_404("work_orders", wo_id)
        get_or_404("die_sets", die_id)
        wc = get_or_404("work_centers", wc_id) if wc_id else None
        # OCC
        if expected != wo["version"]:
            raise err("ERR_STALE_VERSION", 412,
                      "expected_work_order_version does not match the order's current version")
        # order state
        if wo["status"] in ("CANCELLED", "CLOSED"):
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"cannot schedule a run against a {wo['status']} work order")
        if wc is not None:
            # temporal first (tier 9), then capacity/compatibility (tier 11)
            if not turnaround_ok(wc["id"], start, end):
                raise err("ERR_WORKCENTER_WINDOW_OVERLAP", 409,
                          "run window violates the 30-minute turnaround gap on the work center")
            if wc["status"] != "UP":
                raise err("ERR_WORKCENTER_DOWN", 409, "work center is DOWN")
            if wc["type"] != wo["required_process"]:
                raise err("ERR_PROCESS_TYPE_MISMATCH", 409,
                          "work center type != required_process")
            if wc["rated_tonnage"] < wo["required_tonnage"]:
                raise err("ERR_WORKCENTER_TONNAGE_INSUFFICIENT", 422,
                          "rated_tonnage < required_tonnage")
        else:
            pool = [c for c in DB["work_centers"].values()
                    if c["status"] == "UP"
                    and c["type"] == wo["required_process"]
                    and c["rated_tonnage"] >= wo["required_tonnage"]
                    and turnaround_ok(c["id"], start, end)]
            pool.sort(key=lambda c: (c["rated_tonnage"], c["_seq"]))
            if not pool:
                raise err("ERR_NO_WORKCENTER_AVAILABLE", 409,
                          "no eligible work center (empty candidate pool)")
            wc = pool[0]
        rec = new_record("forge_runs")
        rec.update({
            "work_order_id": wo["id"],
            "die_set_id": die_id,
            "work_center_id": wc["id"],
            "planned_start": start,
            "planned_end": end,
            "planned_qty": planned_qty,
            "operator_id": None,
            "actual_started_at": None,
            "parts_good_total": 0,
            "parts_scrapped_total": 0,
            "input_weight_lbs": q2(Decimal("0")),
            "status": "SCHEDULED",
        })
        touch("work_orders", wo)
        return success(view(rec), 201)

    @app.get("/forge-runs")
    def list_runs():
        auth(ALL_ROLES)
        return list_response(apply_filters(
            DB["forge_runs"].values(),
            ["work_order_id", "work_center_id", "die_set_id", "status"]))

    @app.get("/forge-runs/<rid>")
    def get_run(rid):
        auth(ALL_ROLES)
        return success(view(get_or_404("forge_runs", rid)), 200)

    @app.post("/forge-runs/<rid>/start")
    def start_run(rid):
        uid = auth(["ForgeOperator"])
        body()
        run = get_or_404("forge_runs", rid)
        if run["status"] != "SCHEDULED":
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"run in status {run['status']} cannot be started")
        wo = get_or_404("work_orders", run["work_order_id"])
        if wo["status"] not in ("RELEASED", "IN_PROGRESS", "PRODUCED", "CERTIFIED"):
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"work order in status {wo['status']} does not admit run start")
        die = get_or_404("die_sets", run["die_set_id"])
        if die["status"] != "INSTALLED" or die["installed_work_center_id"] != run["work_center_id"]:
            raise err("ERR_DIE_NOT_INSTALLED", 409,
                      "die set is not INSTALLED on the run's work center")
        wc = get_or_404("work_centers", run["work_center_id"])
        if wc["status"] != "UP":
            raise err("ERR_WORKCENTER_DOWN", 409, "work center is DOWN")
        run["operator_id"] = uid
        run["actual_started_at"] = clock_now()
        run["status"] = "IN_PROGRESS"
        touch("forge_runs", run)
        if wo["status"] == "RELEASED":
            wo["status"] = "IN_PROGRESS"
            touch("work_orders", wo)
        return success(view(run), 200)

    @app.post("/forge-runs/<rid>/heats")
    def record_heat(rid):
        auth(["ForgeOperator"])
        d = body()
        charge_id = f_str(d, "furnace_charge_id")
        billet_ids = f_id_list(d, "billet_ids")
        good = f_int(d, "parts_good", min_inclusive=0)
        scrapped = f_int(d, "parts_scrapped", min_inclusive=0)
        run = get_or_404("forge_runs", rid)
        charge = get_or_404("furnace_charges", charge_id)
        billets = [get_or_404("billets", bid) for bid in billet_ids]
        # state
        if run["status"] != "IN_PROGRESS":
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"run in status {run['status']} cannot record heats")
        if charge["status"] != "READY":
            raise err("ERR_CHARGE_NOT_READY", 409,
                      f"charge in status {charge['status']} is not READY")
        # die worn guard
        die = get_or_404("die_sets", run["die_set_id"])
        if die["status"] == "WORN":
            raise err("ERR_DIE_WORN", 409, "the run's die set is WORN")
        # part accounting
        if good + scrapped != len(billet_ids):
            raise err("ERR_PART_COUNT_MISMATCH", 422,
                      "parts_good + parts_scrapped must equal the number of billets")
        # billet-in-charge membership
        for b in billets:
            if b["status"] != "CHARGED" or b.get("current_charge_id") != charge["id"]:
                raise err("ERR_BILLET_NOT_IN_CHARGE", 409,
                          f"billet {b['id']} is not CHARGED in the referenced charge")
        # alloy match
        wo = get_or_404("work_orders", run["work_order_id"])
        if charge["alloy_spec_id"] != wo["alloy_spec_id"]:
            raise err("ERR_ALLOY_MISMATCH", 409, "charge alloy != work order alloy")
        alloy = get_or_404("alloy_specs", charge["alloy_spec_id"])
        # ---- effects ----
        heat = new_record("forge_heats", common=False)
        hits = (good + scrapped) * alloy["strokes_per_part"]
        heat.update({
            "forge_run_id": run["id"],
            "furnace_charge_id": charge["id"],
            "billet_ids": list(billet_ids),
            "parts_good": good,
            "parts_scrapped": scrapped,
            "hits_added": hits,
        })
        for b in billets:
            b["status"] = "CONSUMED"
            b["consumed_by_run_id"] = run["id"]
            b["current_charge_id"] = None
            touch("billets", b)
        # one PartSerial per consumed billet
        seq = sum(1 for p in DB["part_serials"].values() if p["work_order_id"] == wo["id"])
        for b in billets:
            seq += 1
            part = new_record("part_serials")
            part.update({
                "serial_seq": seq,
                "serial_code": f"{wo['order_number']}-{seq}",
                "work_order_id": wo["id"],
                "forge_run_id": run["id"],
                "forge_heat_id": heat["id"],
                "mill_heat_id": b["mill_heat_id"],
                "net_weight_lbs": None,
                "status": "FORGED",
            })
        # die wear accumulation
        die["cumulative_hits"] += hits
        touch("die_sets", die)
        if die["cumulative_hits"] >= die["wear_limit_hits"] and die["status"] != "WORN":
            die["status"] = "WORN"
            die["installed_work_center_id"] = None
            for r2 in DB["forge_runs"].values():
                if r2["die_set_id"] == die["id"] and r2["status"] == "SCHEDULED":
                    r2["status"] = "CANCELLED"
                    touch("forge_runs", r2)
        # run tallies
        run["parts_good_total"] += good
        run["parts_scrapped_total"] += scrapped
        run["input_weight_lbs"] = q2(sum(
            (b["cut_weight_lbs"] for b in DB["billets"].values()
             if b.get("consumed_by_run_id") == run["id"]), Decimal("0")))
        touch("forge_runs", run)
        # order + heat-lot bookkeeping
        recompute_order(wo)
        for mh_id in {b["mill_heat_id"] for b in billets}:
            reeval_heat_depleted(get_or_404("mill_heats", mh_id))
        reeval_coverage(wo)
        return success(view(heat), 201)

    @app.get("/forge-runs/<rid>/heats")
    def list_run_heats(rid):
        auth(ALL_ROLES)
        get_or_404("forge_runs", rid)
        return list_response([h for h in DB["forge_heats"].values() if h["forge_run_id"] == rid])

    @app.post("/forge-runs/<rid>/finish-forging")
    def finish_forging(rid):
        auth(["ForgeOperator"])
        body()
        run = get_or_404("forge_runs", rid)
        if run["status"] != "IN_PROGRESS":
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"run in status {run['status']} cannot finish forging")
        if not any(h["forge_run_id"] == run["id"] for h in DB["forge_heats"].values()):
            raise err("ERR_RUN_NO_HEATS", 409, "no forge heats recorded on this run")
        run["status"] = "FORGED"
        touch("forge_runs", run)
        return success(view(run), 200)

    @app.post("/forge-runs/<rid>/reopen")
    def reopen_run(rid):
        auth(["ForgeOperator"])
        body()
        run = get_or_404("forge_runs", rid)
        if run["status"] != "FORGED":
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"run in status {run['status']} cannot be reopened")
        for t in DB["trim_tickets"].values():
            if t["forge_run_id"] == run["id"] and t["status"] in ("DRAFT", "FLAGGED"):
                raise err("ERR_TRIM_TICKET_ACTIVE_EXISTS", 409,
                          "run has an active trim ticket")
        run["status"] = "IN_PROGRESS"
        touch("forge_runs", run)
        return success(view(run), 200)

    @app.post("/forge-runs/<rid>/complete")
    def complete_run(rid):
        auth(["ForgeOperator"])
        body()
        run = get_or_404("forge_runs", rid)
        if run["status"] != "FORGED":
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"run in status {run['status']} cannot be completed")
        if any(p["forge_run_id"] == run["id"] and p["status"] == "FORGED"
               for p in DB["part_serials"].values()):
            raise err("ERR_TRIM_PENDING", 409, "parts of this run remain in FORGED")
        if not any(t["forge_run_id"] == run["id"] and t["status"] == "ACCEPTED"
                   for t in DB["trim_tickets"].values()):
            raise err("ERR_TRIM_PENDING", 409, "no ACCEPTED trim ticket on this run")
        run["status"] = "COMPLETED"
        touch("forge_runs", run)
        return success(view(run), 200)

    @app.post("/forge-runs/<rid>/cancel")
    def cancel_run(rid):
        auth(["ForgeOperator"])
        body()
        run = get_or_404("forge_runs", rid)
        if run["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"run in status {run['status']} cannot be cancelled")
        if run["status"] == "IN_PROGRESS":
            if any(h["forge_run_id"] == run["id"] for h in DB["forge_heats"].values()):
                raise err("ERR_RUN_HAS_HEATS", 409, "run already has recorded heats")
        run["status"] = "CANCELLED"
        touch("forge_runs", run)
        return success(view(run), 200)
