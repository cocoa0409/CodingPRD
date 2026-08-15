"""Melt deck: heats, charges (incl. AUTO_CORRECT), samples, tap (PRD 3.4)."""

from decimal import Decimal

from flask import request

from db import all_of, get, logical_now, new_record, touch
from errors import fail
from middleware import auth, paged, require_role
from response import ok_list, ok_object
from services import (auto_correct_masses, certifies, recompute_alloy_by_id,
                      recompute_chemistry)
from util import (D, as_int, as_nonneg_num, as_str, body_dict, opt, q2, req)

HEAT_GET_ROLES = {"FoundryAdmin", "MeltSupervisor", "Spectrographer",
                  "LineOperator", "QualityInspector"}


def _get_heat_or_404(hid):
    heat = get("heats", hid)
    if heat is None:
        fail("ERR_NOT_FOUND", "heat not found")
    return heat


def _check_occ(heat, body):
    expected = as_int(req(body, "expected_heat_version"), "expected_heat_version")
    if expected != heat["version"]:
        fail("ERR_STALE_VERSION", "heat version mismatch; re-read the heat")


def register(app):
    @app.route("/api/heats", methods=["POST"])
    def create_heat():
        auth_user, role = auth()
        require_role(role, {"MeltSupervisor"})
        body = body_dict(request.get_json(silent=True))
        foundry_id = as_str(req(body, "foundry_id"), "foundry_id")
        furnace_id = as_str(req(body, "furnace_id"), "furnace_id")
        grade = as_str(req(body, "alloy_grade"), "alloy_grade")
        spec = req(body, "chemistry_spec")
        if not isinstance(spec, dict):
            fail("ERR_INVALID_REQUEST", "chemistry_spec must be an object")
        if get("foundries", foundry_id) is None:
            fail("ERR_NOT_FOUND", "foundry not found")
        furnace = get("equipment", furnace_id)
        if furnace is None or furnace["foundry_id"] != foundry_id:
            fail("ERR_NOT_FOUND", "furnace not found")
        # equipment-kind matching (priority 7)
        if furnace["kind"] != "FURNACE":
            fail("ERR_INVALID_REQUEST", "furnace_id must reference FURNACE equipment")
        rec = new_record("heats", {
            "foundry_id": foundry_id,
            "furnace_id": furnace_id,
            "alloy_grade": grade,
            "chemistry_spec": spec,
            "charge_total_kg": Decimal("0"),
            "charge_composition": {},
            "last_sample_reading": None,
            "last_sample_passed": False,
            "certified_by_user_id": None,
            "last_correction_masses": None,
            "tapped_weight_kg": None,
            "tapped_date": None,
            "remaining_metal_kg": None,
            "status": "CHARGING",
            "_additions": [],
        })
        return ok_object(rec, 201)

    @app.route("/api/heats/<hid>", methods=["GET"])
    def get_heat(hid):
        auth_user, role = auth()
        require_role(role, HEAT_GET_ROLES)
        return ok_object(_get_heat_or_404(hid), 200)

    @app.route("/api/heats", methods=["GET"])
    def list_heats():
        auth_user, role = auth()
        require_role(role, HEAT_GET_ROLES)
        foundry_id = request.args.get("foundry_id")
        furnace_id = request.args.get("furnace_id")
        status = request.args.get("status")
        recs = list(all_of("heats"))
        if foundry_id is not None:
            recs = [h for h in recs if h["foundry_id"] == foundry_id]
        if furnace_id is not None:
            recs = [h for h in recs if h["furnace_id"] == furnace_id]
        if status is not None:
            recs = [h for h in recs if h["status"] == status]
        page, limit, offset, total = paged(recs)
        return ok_list(page, limit, offset, total)

    @app.route("/api/heats/<hid>/charges", methods=["POST"])
    def add_charges(hid):
        auth_user, role = auth()
        require_role(role, {"MeltSupervisor"})
        heat = _get_heat_or_404(hid)
        body = body_dict(request.get_json(silent=True))
        mode = opt(body, "mode")
        if mode is not None and mode != "AUTO_CORRECT":
            fail("ERR_INVALID_REQUEST", "mode must be AUTO_CORRECT when provided")
        additions = opt(body, "additions", [])
        if not isinstance(additions, list):
            fail("ERR_INVALID_REQUEST", "additions must be an array")

        # state feasibility (priority 4)
        if heat["status"] == "POURED_OUT":
            fail("ERR_ALREADY_TERMINAL", "heat is in a terminal state")
        if heat["status"] not in ("CHARGING", "SAMPLED"):
            fail("ERR_INVALID_STATE", "charges accepted only while CHARGING or SAMPLED")
        if heat["status"] == "SAMPLED" and heat["last_sample_passed"]:
            fail("ERR_INVALID_STATE", "corrective loop-back requires a failing last sample")

        # validate and resolve additions (existence priority 3 before business)
        parsed = []
        if mode != "AUTO_CORRECT":
            for i, a in enumerate(additions):
                if not isinstance(a, dict):
                    fail("ERR_INVALID_REQUEST", "additions[%d] must be an object" % i)
                source = a.get("source")
                if source not in ("VIRGIN", "RETURN_LOT"):
                    fail("ERR_INVALID_REQUEST",
                         "additions[%d].source must be VIRGIN or RETURN_LOT" % i)
                weight = as_nonneg_num(req_wrapper(a, "weight_kg", i), "weight_kg")
                if source == "VIRGIN":
                    comp = a.get("composition") or {}
                    if not isinstance(comp, dict):
                        fail("ERR_INVALID_REQUEST",
                             "additions[%d].composition must be an object" % i)
                    comp = {str(e): D(v, "composition") for e, v in comp.items()}
                    parsed.append({"weight": weight, "composition": comp, "lot": None})
                else:
                    lot_id = a.get("return_lot_id")
                    if not isinstance(lot_id, str) or not lot_id:
                        fail("ERR_INVALID_REQUEST",
                             "additions[%d].return_lot_id is required" % i)
                    lot = get("return_lots", lot_id)
                    if lot is None or lot["foundry_id"] != heat["foundry_id"]:
                        fail("ERR_NOT_FOUND", "return lot not found")
                    parsed.append({"weight": weight, "composition": None, "lot": lot})

        # referential lifecycle + sufficiency for RETURN_LOT additions
        for p in parsed:
            if p["lot"] is not None:
                lot = p["lot"]
                if lot["status"] != "ASSAYED":
                    fail("ERR_RETURN_LOT_NOT_ASSAYED", "return lot is not ASSAYED")
                if p["weight"] > lot["remaining_weight_kg"]:
                    fail("ERR_RETURN_LOT_INSUFFICIENT",
                         "return lot remaining weight is insufficient")

        # OCC last among preconditions (scaffold transition listing)
        _check_occ(heat, body)

        # ---- apply ----
        if mode == "AUTO_CORRECT":
            masses = auto_correct_masses(heat)
            for e, mass in masses.items():
                heat["_additions"].append({
                    "weight": mass,
                    "composition": {e: Decimal("100")},
                })
            heat["last_correction_masses"] = masses
        else:
            for p in parsed:
                if p["lot"] is not None:
                    lot = p["lot"]
                    comp = {str(e): D(v) for e, v in (lot["assay_composition"] or {}).items()}
                    lot["remaining_weight_kg"] = q2(lot["remaining_weight_kg"] - p["weight"])
                    lot["consumed_weight_kg"] = q2(lot["consumed_weight_kg"] + p["weight"])
                    if lot["remaining_weight_kg"] == 0:
                        lot["status"] = "CONSUMED"
                    touch(lot)
                    recompute_alloy_by_id(lot["foundry_id"])
                else:
                    comp = p["composition"]
                heat["_additions"].append({"weight": p["weight"], "composition": comp})

        recompute_chemistry(heat)
        if heat["status"] == "SAMPLED":
            heat["status"] = "CHARGING"
        touch(heat)
        return ok_object(heat, 200)

    @app.route("/api/heats/<hid>/samples", methods=["POST"])
    def record_sample(hid):
        auth_user, role = auth()
        require_role(role, {"Spectrographer"})
        heat = _get_heat_or_404(hid)
        body = body_dict(request.get_json(silent=True))
        reading = req(body, "reading")
        if not isinstance(reading, dict):
            fail("ERR_INVALID_REQUEST", "reading must be an object")
        # state feasibility (priority 4)
        if heat["status"] == "POURED_OUT":
            fail("ERR_ALREADY_TERMINAL", "heat is in a terminal state")
        if heat["status"] not in ("CHARGING", "SAMPLED"):
            fail("ERR_INVALID_STATE", "sampling accepted only while CHARGING or SAMPLED")
        if heat["status"] == "CHARGING" and heat["charge_total_kg"] <= 0:
            fail("ERR_INVALID_STATE", "cannot sample an empty bath")
        # OCC (PRD 2.6)
        _check_occ(heat, body)

        heat["last_sample_reading"] = reading
        if certifies(heat["chemistry_spec"], reading):
            heat["status"] = "CERTIFIED"
            heat["last_sample_passed"] = True
            heat["certified_by_user_id"] = auth_user
        else:
            heat["status"] = "SAMPLED"
            heat["last_sample_passed"] = False
        touch(heat)
        return ok_object(heat, 200)

    @app.route("/api/heats/<hid>/tap", methods=["POST"])
    def tap_heat(hid):
        auth_user, role = auth()
        require_role(role, {"MeltSupervisor"})
        heat = _get_heat_or_404(hid)
        body = body_dict(request.get_json(silent=True))
        tap_weight = as_nonneg_num(req(body, "tap_weight_kg"), "tap_weight_kg")

        # tap gate: CERTIFIED required (domain-specific state error, PRD 3.4)
        if heat["status"] == "POURED_OUT":
            fail("ERR_ALREADY_TERMINAL", "heat is in a terminal state")
        if heat["status"] in ("CHARGING", "SAMPLED"):
            fail("ERR_HEAT_NOT_CERTIFIED", "heat must be CERTIFIED before tap")
        if heat["status"] != "CERTIFIED":
            fail("ERR_INVALID_STATE", "heat has already been tapped")

        furnace = get("equipment", heat["furnace_id"])
        now = logical_now()
        # logical now must not fall inside any maintenance window (closed interval)
        for w in (furnace["maintenance_windows"] if furnace else []):
            if w["_start_dt"] <= now <= w["_end_dt"]:
                fail("ERR_INVALID_STATE", "furnace is inside a maintenance window")
        # furnace daily tap capacity (equality allowed; priority 9)
        if furnace is not None and furnace["daily_tap_capacity_kg"] is not None:
            today = now.strftime("%Y-%m-%d")
            used = Decimal("0")
            for h in all_of("heats"):
                if (h["furnace_id"] == furnace["id"] and h["tapped_date"] == today
                        and h["tapped_weight_kg"] is not None):
                    used += h["tapped_weight_kg"]
            if used + tap_weight > furnace["daily_tap_capacity_kg"]:
                fail("ERR_FURNACE_CAPACITY_EXCEEDED",
                     "furnace daily tap capacity exceeded")

        heat["tapped_weight_kg"] = tap_weight
        heat["tapped_date"] = now.strftime("%Y-%m-%d")
        heat["remaining_metal_kg"] = tap_weight
        heat["status"] = "TAPPED"
        touch(heat)
        return ok_object(heat, 200)


def req_wrapper(addition, name, index):
    if name not in addition or addition[name] is None:
        fail("ERR_INVALID_REQUEST", "additions[%d].%s is required" % (index, name))
    return addition[name]
