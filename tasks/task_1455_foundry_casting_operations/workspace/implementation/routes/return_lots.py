"""Alloy return lots: collection and assay (PRD 3.7)."""

from decimal import Decimal

from flask import request

from db import all_of, get, new_record, touch
from errors import fail
from middleware import auth, paged, require_role
from response import ok_list, ok_object
from services import recompute_alloy_by_id, spec_elements
from util import as_nonneg_num, as_str, body_dict, req

LOT_GET_ROLES = {"FoundryAdmin", "MeltSupervisor", "Spectrographer", "QualityInspector"}


def _assay_passes(spec, composition):
    """Every spec element must lie within its [min, max] range (inclusive)."""
    if not isinstance(composition, dict):
        return False
    for e, rng in spec_elements(spec).items():
        if e not in composition or composition[e] is None:
            return False
        try:
            v = Decimal(str(composition[e]))
            lo = Decimal(str(rng.get("min")))
            hi = Decimal(str(rng.get("max")))
        except Exception:
            return False
        if not (lo <= v <= hi):
            return False
    return True


def register(app):
    @app.route("/api/return-lots", methods=["POST"])
    def create_lot():
        auth_user, role = auth()
        require_role(role, {"MeltSupervisor"})
        body = body_dict(request.get_json(silent=True))
        foundry_id = as_str(req(body, "foundry_id"), "foundry_id")
        grade = as_str(req(body, "alloy_grade"), "alloy_grade")
        collected = as_nonneg_num(req(body, "collected_weight_kg"), "collected_weight_kg")
        if get("foundries", foundry_id) is None:
            fail("ERR_NOT_FOUND", "foundry not found")
        rec = new_record("return_lots", {
            "foundry_id": foundry_id,
            "alloy_grade": grade,
            "collected_weight_kg": collected,
            "scrap_credited_kg": Decimal("0"),
            "consumed_weight_kg": Decimal("0"),
            "downgraded_weight_kg": Decimal("0"),
            "remaining_weight_kg": collected,
            "assay_composition": None,
            "status": "COLLECTED",
        })
        return ok_object(rec, 201)

    @app.route("/api/return-lots/<lid>", methods=["GET"])
    def get_lot(lid):
        auth_user, role = auth()
        require_role(role, LOT_GET_ROLES)
        rec = get("return_lots", lid)
        if rec is None:
            fail("ERR_NOT_FOUND", "return lot not found")
        return ok_object(rec, 200)

    @app.route("/api/return-lots", methods=["GET"])
    def list_lots():
        auth_user, role = auth()
        require_role(role, LOT_GET_ROLES)
        foundry_id = request.args.get("foundry_id")
        status = request.args.get("status")
        recs = list(all_of("return_lots"))
        if foundry_id is not None:
            recs = [l for l in recs if l["foundry_id"] == foundry_id]
        if status is not None:
            recs = [l for l in recs if l["status"] == status]
        page, limit, offset, total = paged(recs)
        return ok_list(page, limit, offset, total)

    @app.route("/api/return-lots/<lid>/assay", methods=["POST"])
    def assay_lot(lid):
        auth_user, role = auth()
        require_role(role, {"Spectrographer"})
        rec = get("return_lots", lid)
        if rec is None:
            fail("ERR_NOT_FOUND", "return lot not found")
        if rec["status"] in ("CONSUMED", "DOWNGRADED"):
            fail("ERR_ALREADY_TERMINAL", "return lot is in a terminal state")
        if rec["status"] != "COLLECTED":
            fail("ERR_INVALID_STATE", "only a COLLECTED lot can be assayed")
        body = body_dict(request.get_json(silent=True))
        composition = req(body, "assay_composition")
        spec = req(body, "chemistry_spec")
        if not isinstance(composition, dict):
            fail("ERR_INVALID_REQUEST", "assay_composition must be an object")
        if not isinstance(spec, dict):
            fail("ERR_INVALID_REQUEST", "chemistry_spec must be an object")

        if _assay_passes(spec, composition):
            rec["status"] = "ASSAYED"
            rec["assay_composition"] = composition
        else:
            # contaminated: entire remainder leaves circulation
            rec["status"] = "DOWNGRADED"
            rec["downgraded_weight_kg"] = rec["remaining_weight_kg"]
            rec["remaining_weight_kg"] = Decimal("0")
        touch(rec)
        recompute_alloy_by_id(rec["foundry_id"])
        return ok_object(rec, 200)
