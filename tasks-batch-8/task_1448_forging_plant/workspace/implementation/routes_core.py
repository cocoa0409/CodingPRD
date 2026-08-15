"""Routes: logical clock, AlloySpec, MillHeat, Billet, Furnace, FurnaceCharge."""
from decimal import Decimal

from core import (
    ALL_ROLES, DB, LOGICAL, ApiError, auth, body, success, list_response,
    apply_filters, view, furnace_view, new_record, touch, get_or_404,
    f_str, f_num, f_int, f_bool, f_enum, f_id_list, parse_dt, fmt_dt,
    clock_now, err, q2, D, update_heat_remaining, reeval_heat_depleted,
)
from datetime import timedelta


def register(app):

    # ---------------- logical clock ----------------
    @app.post("/_clock/set_current_utc")
    def set_clock():
        auth(["PlantManager"])
        d = body()
        to = parse_dt(f_str(d, "to_iso8601"), "to_iso8601")
        LOGICAL["now"] = to
        return success({"current_utc": fmt_dt(to)}, 200)

    # ---------------- AlloySpec ----------------
    @app.post("/alloy-specs")
    def create_alloy():
        auth(["PlantManager"])
        d = body()
        grade = f_str(d, "grade_code")
        tmin = f_int(d, "forge_temp_min_f")
        tmax = f_int(d, "forge_temp_max_f")
        rec_data = {
            "grade_code": grade,
            "name": f_str(d, "name"),
            "forge_temp_min_f": tmin,
            "forge_temp_max_f": tmax,
            "reheat_limit": f_int(d, "reheat_limit", min_inclusive=0),
            "flash_allowance_pct": f_num(d, "flash_allowance_pct", min_inclusive=0),
            "strokes_per_part": f_int(d, "strokes_per_part", min_inclusive=1),
            "flow_stress_ksi": f_num(d, "flow_stress_ksi", min_exclusive=0),
            "carbon_max_pct": f_num(d, "carbon_max_pct", min_inclusive=0),
            "manganese_max_pct": f_num(d, "manganese_max_pct", min_inclusive=0),
            "grain_flow_min_rating": f_int(d, "grain_flow_min_rating", min_inclusive=1, max_inclusive=8),
            "macro_etch_required": f_bool(d, "macro_etch_required"),
        }
        if tmax <= tmin:
            raise err("ERR_INVALID_REQUEST", 400, "forge_temp_max_f must be > forge_temp_min_f")
        for s in DB["alloy_specs"].values():
            if s["grade_code"] == grade:
                raise err("ERR_DUPLICATE_ALLOY_GRADE", 409, f"grade_code '{grade}' already registered")
        rec = new_record("alloy_specs")
        rec.update(rec_data)
        return success(view(rec), 201)

    @app.get("/alloy-specs")
    def list_alloys():
        auth(ALL_ROLES)
        return list_response(apply_filters(DB["alloy_specs"].values(), ["grade_code"]))

    @app.get("/alloy-specs/<rid>")
    def get_alloy(rid):
        auth(ALL_ROLES)
        return success(view(get_or_404("alloy_specs", rid)), 200)

    # ---------------- MillHeat ----------------
    @app.post("/mill-heats")
    def create_heat():
        auth(["PlantManager"])
        d = body()
        heat_number = f_str(d, "heat_number")
        alloy_id = f_str(d, "alloy_spec_id")
        mill_name = f_str(d, "mill_name")
        received = f_num(d, "received_weight_lbs", min_exclusive=0)
        bar_lbs = f_num(d, "bar_lbs_per_in", min_exclusive=0)
        get_or_404("alloy_specs", alloy_id)
        for h in DB["mill_heats"].values():
            if h["heat_number"] == heat_number:
                raise err("ERR_DUPLICATE_HEAT_NUMBER", 409, f"heat_number '{heat_number}' already registered")
        rec = new_record("mill_heats")
        rec.update({
            "heat_number": heat_number,
            "alloy_spec_id": alloy_id,
            "mill_name": mill_name,
            "received_weight_lbs": received,
            "bar_lbs_per_in": bar_lbs,
            "carbon_pct": None,
            "manganese_pct": None,
            "remaining_weight_lbs": received,
            "status": "RECEIVED",
        })
        return success(view(rec), 201)

    @app.get("/mill-heats")
    def list_heats():
        auth(ALL_ROLES)
        return list_response(apply_filters(DB["mill_heats"].values(), ["status", "alloy_spec_id"]))

    @app.get("/mill-heats/<rid>")
    def get_heat(rid):
        auth(ALL_ROLES)
        return success(view(get_or_404("mill_heats", rid)), 200)

    @app.post("/mill-heats/<rid>/verify-cert")
    def verify_cert(rid):
        auth(["QualityEngineer"])
        d = body()
        carbon = f_num(d, "carbon_pct", min_inclusive=0)
        manganese = f_num(d, "manganese_pct", min_inclusive=0)
        heat = get_or_404("mill_heats", rid)
        if heat["status"] != "RECEIVED":
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"heat in status {heat['status']} cannot be cert-verified")
        alloy = get_or_404("alloy_specs", heat["alloy_spec_id"])
        if carbon > D(alloy["carbon_max_pct"]) or manganese > D(alloy["manganese_max_pct"]):
            raise err("ERR_CHEMISTRY_OUT_OF_SPEC", 422,
                      "measured chemistry exceeds alloy carbon/manganese maxima")
        heat["carbon_pct"] = carbon
        heat["manganese_pct"] = manganese
        heat["status"] = "CERT_VERIFIED"
        touch("mill_heats", heat)
        return success(view(heat), 200)

    @app.post("/mill-heats/<rid>/quarantine")
    def quarantine_heat(rid):
        auth(["QualityEngineer"])
        d = body()
        f_str(d, "reason")
        heat = get_or_404("mill_heats", rid)
        if heat["status"] not in ("RECEIVED", "CERT_VERIFIED"):
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"heat in status {heat['status']} cannot be quarantined")
        heat["status"] = "QUARANTINED"
        touch("mill_heats", heat)
        return success(view(heat), 200)

    @app.post("/mill-heats/<rid>/release-quarantine")
    def release_heat(rid):
        auth(["QualityEngineer"])
        body()
        heat = get_or_404("mill_heats", rid)
        if heat["status"] != "QUARANTINED":
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"heat in status {heat['status']} cannot be released from quarantine")
        heat["status"] = "CERT_VERIFIED"
        touch("mill_heats", heat)
        reeval_heat_depleted(heat)
        return success(view(heat), 200)

    @app.post("/mill-heats/<rid>/reject")
    def reject_heat(rid):
        auth(["QualityEngineer"])
        d = body()
        f_str(d, "reason")
        heat = get_or_404("mill_heats", rid)
        if heat["status"] != "QUARANTINED":
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"heat in status {heat['status']} cannot be rejected")
        heat["status"] = "REJECTED"
        touch("mill_heats", heat)
        return success(view(heat), 200)

    # ---------------- Billet ----------------
    @app.get("/mill-heats/<rid>/billets")
    def list_heat_billets(rid):
        auth(ALL_ROLES)
        get_or_404("mill_heats", rid)
        recs = [b for b in DB["billets"].values() if b["mill_heat_id"] == rid]
        return list_response(recs)

    @app.post("/mill-heats/<rid>/billets")
    def cut_billets(rid):
        auth(["SawOperator"])
        d = body()
        cuts = d.get("cuts")
        if not isinstance(cuts, list) or not cuts:
            raise err("ERR_INVALID_REQUEST", 400, "cuts must be a non-empty array")
        heat = get_or_404("mill_heats", rid)
        # parse cut lines
        lines = []
        for item in cuts:
            if isinstance(item, dict):
                length = f_num(item, "cut_length_in", min_exclusive=0)
                qty = item.get("quantity", item.get("pieces", item.get("count", 1)))
                if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
                    raise err("ERR_INVALID_REQUEST", 400, "cut line quantity must be an integer >= 1")
            elif isinstance(item, (int, float)) and not isinstance(item, bool):
                length = D(item)
                if length <= 0:
                    raise err("ERR_INVALID_REQUEST", 400, "cut_length_in must be > 0")
                qty = 1
            else:
                raise err("ERR_INVALID_REQUEST", 400, "each cut line must be an object with cut_length_in")
            lines.append((length, qty))
        # heat usability
        if heat["status"] == "QUARANTINED":
            raise err("ERR_HEAT_QUARANTINED", 409, "heat is quarantined")
        if heat["status"] != "CERT_VERIFIED":
            raise err("ERR_HEAT_NOT_CERTIFIED", 409, "heat is not CERT_VERIFIED")
        # weight check (atomic: whole batch must fit)
        bar = D(heat["bar_lbs_per_in"])
        weights = []
        for length, qty in lines:
            w = q2(length * bar)
            weights.extend([w] * qty)
        total = sum(weights, Decimal("0"))
        if total > D(heat["remaining_weight_lbs"]):
            raise err("ERR_INSUFFICIENT_HEAT_WEIGHT", 409,
                      "cut lines' total weight exceeds the heat's remaining_weight_lbs")
        created = []
        seq = sum(1 for b in DB["billets"].values() if b["mill_heat_id"] == heat["id"])
        i = 0
        for length, qty in lines:
            w = q2(length * bar)
            for _ in range(qty):
                i += 1
                rec = new_record("billets")
                rec.update({
                    "mill_heat_id": heat["id"],
                    "cut_seq": seq + i,
                    "cut_length_in": length,
                    "cut_weight_lbs": w,
                    "charge_count": 0,
                    "current_charge_id": None,
                    "consumed_by_run_id": None,
                    "status": "CUT",
                })
                created.append(rec)
        update_heat_remaining(heat)
        reeval_heat_depleted(heat)
        return success([view(b) for b in created], 201, "array")

    @app.get("/billets")
    def list_billets():
        auth(ALL_ROLES)
        return list_response(apply_filters(
            DB["billets"].values(),
            ["mill_heat_id", "status", "current_charge_id", "consumed_by_run_id"]))

    @app.get("/billets/<rid>")
    def get_billet(rid):
        auth(ALL_ROLES)
        return success(view(get_or_404("billets", rid)), 200)

    @app.post("/billets/<rid>/scrap")
    def scrap_billet(rid):
        auth(["SawOperator"])
        d = body()
        f_str(d, "reason")
        b = get_or_404("billets", rid)
        if b["status"] not in ("CUT", "DISCHARGED"):
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"billet in status {b['status']} cannot be scrapped")
        b["status"] = "SCRAPPED"
        touch("billets", b)
        heat = get_or_404("mill_heats", b["mill_heat_id"])
        reeval_heat_depleted(heat)
        return success(view(b), 200)

    # ---------------- Furnace ----------------
    @app.post("/furnaces")
    def create_furnace():
        auth(["PlantManager"])
        d = body()
        code = f_str(d, "furnace_code")
        capacity = f_num(d, "capacity_lbs", min_exclusive=0)
        for f in DB["furnaces"].values():
            if f["furnace_code"] == code:
                raise err("ERR_INVALID_REQUEST", 400, f"furnace_code '{code}' already registered")
        rec = new_record("furnaces")
        rec.update({"furnace_code": code, "capacity_lbs": capacity, "status": "UP"})
        return success(furnace_view(rec), 201)

    @app.get("/furnaces")
    def list_furnaces():
        auth(ALL_ROLES)
        recs = sorted(DB["furnaces"].values(), key=lambda r: r["_seq"])
        status = _q("status")
        active = _q("active_charge_id")
        if status is not None:
            recs = [f for f in recs if f["status"] == status]
        if active is not None:
            recs = [f for f in recs if furnace_view(f)["active_charge_id"] == active]
        from core import paginate
        page, meta = paginate(recs)
        return success([furnace_view(f) for f in page], 200, "array", meta)

    @app.get("/furnaces/<rid>")
    def get_furnace(rid):
        auth(ALL_ROLES)
        return success(furnace_view(get_or_404("furnaces", rid)), 200)

    @app.post("/furnaces/<rid>/set-status")
    def set_furnace_status(rid):
        auth(["PlantManager"])
        d = body()
        status = f_enum(d, "status", {"UP", "DOWN"})
        f = get_or_404("furnaces", rid)
        if f["status"] != status:
            f["status"] = status
            touch("furnaces", f)
        return success(furnace_view(f), 200)

    # ---------------- FurnaceCharge ----------------
    @app.post("/furnace-charges")
    def create_charge():
        auth(["FurnaceOperator"])
        d = body()
        furnace_id = f_str(d, "furnace_id")
        billet_ids = f_id_list(d, "billet_ids")
        target = f_int(d, "target_temp_f")
        soak = f_int(d, "soak_minutes", min_inclusive=0)
        start = parse_dt(f_str(d, "planned_load_start"), "planned_load_start")
        unload = parse_dt(f_str(d, "planned_unload"), "planned_unload")
        if unload <= start:
            raise err("ERR_INVALID_REQUEST", 400, "planned_unload must be after planned_load_start")
        furnace = get_or_404("furnaces", furnace_id)
        billets = [get_or_404("billets", bid) for bid in billet_ids]
        # state: every billet CUT or DISCHARGED
        for b in billets:
            if b["status"] not in ("CUT", "DISCHARGED"):
                raise err("ERR_INVALID_STATE_TRANSITION", 409,
                          f"billet {b['id']} in status {b['status']} cannot be charged")
        heats = [get_or_404("mill_heats", b["mill_heat_id"]) for b in billets]
        # single alloy
        alloy_ids = {h["alloy_spec_id"] for h in heats}
        if len(alloy_ids) > 1:
            raise err("ERR_MIXED_ALLOY_CHARGE", 409, "all billets in a charge must share one alloy")
        alloy = get_or_404("alloy_specs", next(iter(alloy_ids)))
        # forge window
        if target < alloy["forge_temp_min_f"] or target > alloy["forge_temp_max_f"]:
            raise err("ERR_TEMP_OUTSIDE_FORGE_WINDOW", 422,
                      "target_temp_f outside the alloy forge window")
        # reheat ceiling
        for b in billets:
            if b["charge_count"] >= alloy["reheat_limit"] + 1:
                raise err("ERR_REHEAT_LIMIT_EXCEEDED", 409,
                          f"billet {b['id']} has reached the re-heat limit")
        # heat usability
        for h in heats:
            if h["status"] == "QUARANTINED":
                raise err("ERR_HEAT_QUARANTINED", 409, "heat is quarantined")
            if h["status"] != "CERT_VERIFIED":
                raise err("ERR_HEAT_NOT_CERTIFIED", 409, "heat is not CERT_VERIFIED")
        # temporal: half-open window overlap on the furnace
        for c in DB["furnace_charges"].values():
            if c["furnace_id"] != furnace["id"]:
                continue
            if c["status"] not in ("LOADING", "SOAKING", "READY"):
                continue
            if start < c["planned_unload"] and c["planned_load_start"] < unload:
                raise err("ERR_FURNACE_WINDOW_OVERLAP", 409,
                          "charge window overlaps another active charge on the furnace")
        # capacity
        weight = q2(sum((b["cut_weight_lbs"] for b in billets), Decimal("0")))
        if weight > D(furnace["capacity_lbs"]):
            raise err("ERR_FURNACE_CAPACITY_EXCEEDED", 409,
                      "charge weight exceeds furnace capacity")
        if furnace["status"] != "UP":
            raise err("ERR_FURNACE_DOWN", 409, "furnace is DOWN")
        rec = new_record("furnace_charges")
        rec.update({
            "furnace_id": furnace["id"],
            "billet_ids": list(billet_ids),
            "alloy_spec_id": alloy["id"],
            "target_temp_f": target,
            "soak_minutes": soak,
            "planned_load_start": start,
            "planned_unload": unload,
            "charge_weight_lbs": weight,
            "load_started_at": clock_now(),
            "closed_at": None,
            "ready_at": None,
            "discharged_at": None,
            "status": "LOADING",
        })
        for b in billets:
            b["status"] = "CHARGED"
            b["charge_count"] += 1
            b["current_charge_id"] = rec["id"]
            touch("billets", b)
        touch("furnaces", furnace)
        return success(view(rec), 201)

    @app.get("/furnace-charges")
    def list_charges():
        auth(ALL_ROLES)
        return list_response(apply_filters(
            DB["furnace_charges"].values(), ["furnace_id", "status", "alloy_spec_id"]))

    @app.get("/furnace-charges/<rid>")
    def get_charge(rid):
        auth(ALL_ROLES)
        return success(view(get_or_404("furnace_charges", rid)), 200)

    def _release_billets(charge):
        furnace = get_or_404("furnaces", charge["furnace_id"])
        for b in DB["billets"].values():
            if b.get("current_charge_id") == charge["id"] and b["status"] == "CHARGED":
                b["status"] = "DISCHARGED"
                b["current_charge_id"] = None
                touch("billets", b)
        charge["discharged_at"] = clock_now()
        touch("furnace_charges", charge)
        touch("furnaces", furnace)

    @app.post("/furnace-charges/<rid>/close-loading")
    def close_loading(rid):
        auth(["FurnaceOperator"])
        body()
        c = get_or_404("furnace_charges", rid)
        if c["status"] != "LOADING":
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"charge in status {c['status']} cannot close loading")
        c["status"] = "SOAKING"
        c["closed_at"] = clock_now()
        touch("furnace_charges", c)
        return success(view(c), 200)

    @app.post("/furnace-charges/<rid>/mark-ready")
    def mark_ready(rid):
        auth(["FurnaceOperator"])
        body()
        c = get_or_404("furnace_charges", rid)
        if c["status"] != "SOAKING":
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"charge in status {c['status']} cannot be marked ready")
        if clock_now() < c["closed_at"] + timedelta(minutes=c["soak_minutes"]):
            raise err("ERR_SOAK_TIME_NOT_ELAPSED", 409,
                      "soak time has not elapsed")
        c["status"] = "READY"
        c["ready_at"] = clock_now()
        touch("furnace_charges", c)
        return success(view(c), 200)

    @app.post("/furnace-charges/<rid>/discharge")
    def discharge(rid):
        auth(["FurnaceOperator"])
        body()
        c = get_or_404("furnace_charges", rid)
        if c["status"] != "READY":
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"charge in status {c['status']} cannot be discharged")
        c["status"] = "DISCHARGED"
        _release_billets(c)
        return success(view(c), 200)

    @app.post("/furnace-charges/<rid>/abort")
    def abort_charge(rid):
        auth(["FurnaceOperator"])
        body()
        c = get_or_404("furnace_charges", rid)
        if c["status"] not in ("LOADING", "SOAKING", "READY"):
            raise err("ERR_INVALID_STATE_TRANSITION", 409,
                      f"charge in status {c['status']} cannot be aborted")
        c["status"] = "ABORTED"
        _release_billets(c)
        return success(view(c), 200)

    @app.get("/furnace-charges/<rid>/heats")
    def list_charge_heats(rid):
        auth(ALL_ROLES)
        get_or_404("furnace_charges", rid)
        recs = [h for h in DB["forge_heats"].values() if h["furnace_charge_id"] == rid]
        return list_response(recs)


def _q(name):
    from flask import request
    return request.args.get(name)
