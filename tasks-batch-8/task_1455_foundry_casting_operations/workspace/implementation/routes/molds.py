"""Mold assembly and shakeout (PRD 3.5 / 3.6)."""

from flask import request

from db import all_of, get, new_record, touch
from errors import fail
from middleware import auth, paged, require_role
from response import ok_list, ok_object
from services import (pipeline_cap, recompute_pipeline,
                      recompute_posture_by_id)
from util import as_nonneg_num, as_nonneg_int, as_str, body_dict, q2, req

MOLD_GET_ROLES = {"FoundryAdmin", "LineOperator", "QualityInspector"}


def register(app):
    @app.route("/api/molds", methods=["POST"])
    def create_mold():
        auth_user, role = auth()
        require_role(role, {"LineOperator"})
        body = body_dict(request.get_json(silent=True))
        pattern_id = as_str(req(body, "pattern_id"), "pattern_id")
        sand_batch_id = as_str(req(body, "sand_batch_id"), "sand_batch_id")
        order_id = as_str(req(body, "order_id"), "order_id")
        sand_weight = as_nonneg_num(req(body, "sand_weight_kg"), "sand_weight_kg")
        metal_weight = as_nonneg_num(req(body, "metal_weight_kg"), "metal_weight_kg")
        cooling_hours = as_nonneg_int(req(body, "cooling_hours"), "cooling_hours")

        # existence + same-foundry references (priority 3, PRD 2.11)
        order = get("orders", order_id)
        if order is None:
            fail("ERR_NOT_FOUND", "order not found")
        foundry_id = order["foundry_id"]
        pattern = get("patterns", pattern_id)
        if pattern is None or pattern["foundry_id"] != foundry_id:
            fail("ERR_NOT_FOUND", "pattern not found")
        batch = get("sand_batches", sand_batch_id)
        if batch is None or batch["foundry_id"] != foundry_id:
            fail("ERR_NOT_FOUND", "sand batch not found")

        # referential lifecycle (priority 6) then per-batch checks
        if pattern["status"] != "ACTIVE":
            fail("ERR_PATTERN_NOT_ACTIVE", "pattern is not ACTIVE")
        if batch["status"] != "IN_SERVICE":
            fail("ERR_SAND_BATCH_INACTIVE", "sand batch is not IN_SERVICE")

        # fiscal (priority 9): sand sufficiency, then pipeline cap
        if batch["current_weight_kg"] < sand_weight:
            fail("ERR_SAND_INSUFFICIENT", "sand batch current weight is insufficient")
        if order["pipeline_count"] + pattern["impressions"] > pipeline_cap(order):
            fail("ERR_ORDER_QUANTITY_EXCEEDED", "order pipeline cap would be exceeded")

        rec = new_record("molds", {
            "pattern_id": pattern_id,
            "sand_batch_id": sand_batch_id,
            "order_id": order_id,
            "pour_slot_id": None,
            "sand_weight_kg": sand_weight,
            "metal_weight_kg": metal_weight,
            "cooling_hours": cooling_hours,
            "poured_at": None,
            "status": "ASSEMBLED",
        })
        # sand ledger: current -> committed
        batch["current_weight_kg"] = q2(batch["current_weight_kg"] - sand_weight)
        batch["committed_weight_kg"] = q2(batch["committed_weight_kg"] + sand_weight)
        touch(batch)
        # first mold flips the order into production
        if order["status"] == "RECEIVED":
            order["status"] = "IN_PRODUCTION"
            touch(order)
        recompute_pipeline(order)
        recompute_posture_by_id(foundry_id)
        return ok_object(rec, 201)

    @app.route("/api/molds/<mid>", methods=["GET"])
    def get_mold(mid):
        auth_user, role = auth()
        require_role(role, MOLD_GET_ROLES)
        rec = get("molds", mid)
        if rec is None:
            fail("ERR_NOT_FOUND", "mold not found")
        return ok_object(rec, 200)

    @app.route("/api/molds", methods=["GET"])
    def list_molds():
        auth_user, role = auth()
        require_role(role, MOLD_GET_ROLES)
        pattern_id = request.args.get("pattern_id")
        sand_batch_id = request.args.get("sand_batch_id")
        order_id = request.args.get("order_id")
        pour_slot_id = request.args.get("pour_slot_id")
        status = request.args.get("status")
        recs = list(all_of("molds"))
        if pattern_id is not None:
            recs = [m for m in recs if m["pattern_id"] == pattern_id]
        if sand_batch_id is not None:
            recs = [m for m in recs if m["sand_batch_id"] == sand_batch_id]
        if order_id is not None:
            recs = [m for m in recs if m["order_id"] == order_id]
        if pour_slot_id is not None:
            recs = [m for m in recs if m["pour_slot_id"] == pour_slot_id]
        if status is not None:
            recs = [m for m in recs if m["status"] == status]
        page, limit, offset, total = paged(recs)
        return ok_list(page, limit, offset, total)

    @app.route("/api/molds/<mid>/shakeout", methods=["POST"])
    def shakeout_mold(mid):
        auth_user, role = auth()
        require_role(role, {"LineOperator"})
        rec = get("molds", mid)
        if rec is None:
            fail("ERR_NOT_FOUND", "mold not found")
        if rec["status"] in ("CLOSED", "SCRAPPED"):
            fail("ERR_ALREADY_TERMINAL", "mold is in a terminal state")
        if rec["status"] != "COOLED":
            fail("ERR_INVALID_STATE", "only a COOLED mold can be shaken out")
        batch = get("sand_batches", rec["sand_batch_id"])
        if batch is not None:
            # sand ledger: committed -> spent
            batch["committed_weight_kg"] = q2(batch["committed_weight_kg"] - rec["sand_weight_kg"])
            batch["spent_weight_kg"] = q2(batch["spent_weight_kg"] + rec["sand_weight_kg"])
            touch(batch)
        rec["status"] = "SHAKEOUT"
        touch(rec)
        order = get("orders", rec["order_id"])
        if order is not None:
            recompute_posture_by_id(order["foundry_id"])
        return ok_object(rec, 200)
