"""X-ray inspection reports and MRB disposition (PRD 3.6 / 3.7)."""

from decimal import Decimal

from flask import request

from db import all_of, get, new_record, touch
from errors import fail
from middleware import auth, paged, require_role
from response import ok_list, ok_object
from services import (SCRAP_PROVISIONAL_YIELD, order_casting_accepted,
                      order_casting_scrapped, q2, recompute_alloy_by_id)
from util import as_enum, as_int, as_str, body_dict, opt, req

INSPECTION_GET_ROLES = {"FoundryAdmin", "QualityInspector", "WarrantyManager"}
DEFECT_TYPES = {"NONE", "POROSITY", "SHRINKAGE", "INCLUSION", "MISRUN", "CRACK"}
SCRAP_CODES = {"POROSITY", "SHRINKAGE", "INCLUSION", "MISRUN", "CRACK", "PROCESS"}
REWORKABLE_DEFECTS = {"POROSITY", "SHRINKAGE", "INCLUSION"}


def register(app):
    @app.route("/api/inspections", methods=["POST"])
    def create_inspection():
        auth_user, role = auth()
        require_role(role, {"QualityInspector"})
        body = body_dict(request.get_json(silent=True))
        casting_id = as_str(req(body, "casting_id"), "casting_id")
        casting = get("castings", casting_id)
        if casting is None:
            fail("ERR_NOT_FOUND", "casting not found")
        # inspectable only at routing FINAL_INSPECTION and quality not SCRAPPED
        if casting["routing_status"] != "FINAL_INSPECTION" or casting["quality_status"] == "SCRAPPED":
            fail("ERR_CASTING_NOT_INSPECTABLE",
                 "casting is not at FINAL_INSPECTION or is SCRAPPED")
        grade = as_int(req(body, "porosity_grade"), "porosity_grade")
        if grade < 1 or grade > 8:
            fail("ERR_INVALID_REQUEST", "porosity_grade must be in 1..8")
        defect = as_enum(req(body, "defect_type"), "defect_type", DEFECT_TYPES)
        zone = as_enum(req(body, "zone"), "zone", {"A", "B", "C"})

        rec = new_record("inspections", {
            "casting_id": casting_id,
            "porosity_grade": grade,
            "defect_type": defect,
            "zone": zone,
            "disposited_by_user_id": None,
            "disposition": None,
            "status": "RECORDED",
        })
        # re-inspection after a rework loop resets quality to PENDING
        if casting["quality_status"] == "REWORK":
            casting["quality_status"] = "PENDING"
            touch(casting)
        return ok_object(rec, 201)

    @app.route("/api/inspections/<iid>", methods=["GET"])
    def get_inspection(iid):
        auth_user, role = auth()
        require_role(role, INSPECTION_GET_ROLES)
        rec = get("inspections", iid)
        if rec is None:
            fail("ERR_NOT_FOUND", "inspection report not found")
        return ok_object(rec, 200)

    @app.route("/api/inspections", methods=["GET"])
    def list_inspections():
        auth_user, role = auth()
        require_role(role, INSPECTION_GET_ROLES)
        casting_id = request.args.get("casting_id")
        status = request.args.get("status")
        recs = list(all_of("inspections"))
        if casting_id is not None:
            recs = [r for r in recs if r["casting_id"] == casting_id]
        if status is not None:
            recs = [r for r in recs if r["status"] == status]
        page, limit, offset, total = paged(recs)
        return ok_list(page, limit, offset, total)

    @app.route("/api/inspections/<iid>/disposition", methods=["POST"])
    def disposition_inspection(iid):
        auth_user, role = auth()
        require_role(role, {"QualityInspector"})
        rec = get("inspections", iid)
        if rec is None:
            fail("ERR_NOT_FOUND", "inspection report not found")
        body = body_dict(request.get_json(silent=True))
        disposition = as_enum(req(body, "disposition"), "disposition",
                              {"ACCEPT", "USE_AS_IS", "REWORK", "SCRAP"})

        casting = get("castings", rec["casting_id"])
        # SCRAP credits a named return lot (body FK existence, priority 3)
        lot = None
        if disposition == "SCRAP":
            lot_id = body.get("return_lot_id")
            if lot_id is not None:
                if not isinstance(lot_id, str):
                    fail("ERR_INVALID_REQUEST", "return_lot_id must be a string")
                lot = get("return_lots", lot_id)
                order = get("orders", casting["order_id"]) if casting else None
                if lot is None or (order is not None and lot["foundry_id"] != order["foundry_id"]):
                    fail("ERR_NOT_FOUND", "return lot not found")

        # state (priority 4): a second disposition gets the specific error
        if rec["status"] == "DISPOSITIONED":
            fail("ERR_DISPOSITION_EXISTS", "inspection report already dispositioned")

        # segregation of duties (priority 5): disposer != heat certifier
        heat = None
        if casting is not None:
            mold = get("molds", casting["mold_id"])
            if mold is not None and mold["pour_slot_id"] is not None:
                slot = get("pour_slots", mold["pour_slot_id"])
                if slot is not None:
                    heat = get("heats", slot["heat_id"])
        if heat is not None and heat["certified_by_user_id"] is not None \
                and heat["certified_by_user_id"] == auth_user:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "spectro certifier may not disposition castings from the own heat")

        # branch rules (scaffold transition preconditions, equal weight)
        if disposition == "USE_AS_IS" and rec["porosity_grade"] > 4:
            fail("ERR_DISPOSITION_RULE_VIOLATED",
                 "USE_AS_IS requires porosity_grade <= 4")
        if disposition == "REWORK" and rec["defect_type"] not in REWORKABLE_DEFECTS:
            fail("ERR_DISPOSITION_RULE_VIOLATED",
                 "REWORK requires a POROSITY, SHRINKAGE, or INCLUSION defect")
        if disposition == "SCRAP":
            scrap_code = body.get("scrap_code")
            if scrap_code is None:
                fail("ERR_INVALID_REQUEST", "scrap_code is required for SCRAP")
            as_enum(scrap_code, "scrap_code", SCRAP_CODES)
            if lot is None:
                fail("ERR_INVALID_REQUEST", "return_lot_id is required for SCRAP")

        # ---- apply branch side effects ----
        rec["disposition"] = disposition
        rec["disposited_by_user_id"] = auth_user
        rec["status"] = "DISPOSITIONED"
        touch(rec)

        order = get("orders", casting["order_id"]) if casting else None
        if disposition in ("ACCEPT", "USE_AS_IS"):
            casting["quality_status"] = "ACCEPTED" if disposition == "ACCEPT" else "USE_AS_IS"
            touch(casting)
            if order is not None:
                order_casting_accepted(order)
        elif disposition == "REWORK":
            casting["quality_status"] = "REWORK"
            if casting["routing_status"] == "FINAL_INSPECTION":
                casting["routing_status"] = "GRINDING"
            touch(casting)
        elif disposition == "SCRAP":
            casting["quality_status"] = "SCRAPPED"
            touch(casting)
            if order is not None:
                order_casting_scrapped(order)
            provisional = q2(casting["casting_weight_kg"] * SCRAP_PROVISIONAL_YIELD)
            new_record("scrap_records", {
                "casting_id": casting["id"],
                "return_lot_id": lot["id"],
                "scrap_code": body["scrap_code"],
                "provisional_weight_kg": provisional,
                "actual_weight_kg": None,
                "status": "PROVISIONAL",
            })
            lot["scrap_credited_kg"] = q2(lot["scrap_credited_kg"] + provisional)
            lot["remaining_weight_kg"] = q2(lot["remaining_weight_kg"] + provisional)
            touch(lot)
            recompute_alloy_by_id(lot["foundry_id"])
        return ok_object(rec, 200)
