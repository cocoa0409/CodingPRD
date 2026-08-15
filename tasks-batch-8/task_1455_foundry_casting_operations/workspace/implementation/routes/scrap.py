"""Scrap records: two-phase provisional/final remelt accounting (PRD 3.7)."""

from flask import request

from db import all_of, get, touch
from errors import fail
from middleware import auth, paged, require_role
from response import ok_list, ok_object
from services import q2, recompute_alloy_by_id
from util import as_nonneg_num, body_dict, req

SCRAP_GET_ROLES = {"FoundryAdmin", "QualityInspector", "MeltSupervisor"}


def register(app):
    @app.route("/api/scrap-records/<sid>", methods=["GET"])
    def get_scrap(sid):
        auth_user, role = auth()
        require_role(role, SCRAP_GET_ROLES)
        rec = get("scrap_records", sid)
        if rec is None:
            fail("ERR_NOT_FOUND", "scrap record not found")
        return ok_object(rec, 200)

    @app.route("/api/scrap-records", methods=["GET"])
    def list_scrap():
        auth_user, role = auth()
        require_role(role, SCRAP_GET_ROLES)
        casting_id = request.args.get("casting_id")
        return_lot_id = request.args.get("return_lot_id")
        status = request.args.get("status")
        recs = list(all_of("scrap_records"))
        if casting_id is not None:
            recs = [r for r in recs if r["casting_id"] == casting_id]
        if return_lot_id is not None:
            recs = [r for r in recs if r["return_lot_id"] == return_lot_id]
        if status is not None:
            recs = [r for r in recs if r["status"] == status]
        page, limit, offset, total = paged(recs)
        return ok_list(page, limit, offset, total)

    @app.route("/api/scrap-records/<sid>/weigh", methods=["POST"])
    def weigh_scrap(sid):
        auth_user, role = auth()
        require_role(role, {"QualityInspector"})
        rec = get("scrap_records", sid)
        if rec is None:
            fail("ERR_NOT_FOUND", "scrap record not found")
        if rec["status"] == "WEIGHED":
            fail("ERR_ALREADY_TERMINAL", "scrap record is already WEIGHED")
        body = body_dict(request.get_json(silent=True))
        actual = as_nonneg_num(req(body, "actual_weight_kg"), "actual_weight_kg")
        lot = get("return_lots", rec["return_lot_id"])
        delta = actual - rec["provisional_weight_kg"]
        # the reconciliation may not drive the lot's remaining weight negative
        if lot is not None and lot["remaining_weight_kg"] + delta < 0:
            fail("ERR_RETURN_LOT_INSUFFICIENT",
                 "weigh reconciliation would drive the lot negative")
        rec["actual_weight_kg"] = actual
        rec["status"] = "WEIGHED"
        touch(rec)
        if lot is not None:
            lot["scrap_credited_kg"] = q2(lot["scrap_credited_kg"] + delta)
            lot["remaining_weight_kg"] = q2(lot["remaining_weight_kg"] + delta)
            touch(lot)
            recompute_alloy_by_id(lot["foundry_id"])
        return ok_object(rec, 200)
