"""SausageBatch + BatchInput: create, inputs, reserve, produce, cancel
(PRD §3.8)."""
from flask import request

import db
import errors
import response
import serializers
import validation as v
from middleware import authenticate, require_role
from routes._helpers import list_response
from services import common
from services import pricing


def register(app):
    @app.route("/sausage-batches", methods=["POST"])
    def create_batch():
        _uid, role = authenticate()
        require_role(role, {"Butcher"})
        body = v.get_body()
        recipe_name = v.as_str(v.require(body, "recipe_name"), "recipe_name")
        output_cut_type_id = v.as_str(
            v.require(body, "output_cut_type_id"), "output_cut_type_id")
        planned_output = v.as_int(
            v.require(body, "planned_output_g"), "planned_output_g", minimum=1)

        cut = common.fk_or_404(db.cut_types, output_cut_type_id)
        # Output must be a grind cut (PRD §3.8) -> ERR_OUTPUT_NOT_GRIND.
        if not cut.get("is_grind"):
            errors.fail(errors.ERR_OUTPUT_NOT_GRIND,
                        "Output cut type is not a grind cut.")

        record = {
            "recipe_name": recipe_name,
            "output_cut_type_id": output_cut_type_id,
            "planned_output_g": planned_output,
            "actual_yield_g": None,
            "batch_status": "DRAFT",
        }
        db.stamp_create(record)
        db.sausage_batches[record["id"]] = record
        return response.object_response(serializers.sausage_batch(record), 201)

    @app.route("/sausage-batches/<rid>", methods=["GET"])
    def get_batch(rid):
        _uid, role = authenticate()
        require_role(role, {"Butcher", "ShiftManager"})
        record = common.get_or_404(db.sausage_batches, rid)
        return response.object_response(serializers.sausage_batch(record))

    @app.route("/sausage-batches", methods=["GET"])
    def list_batches():
        _uid, role = authenticate()
        require_role(role, {"Butcher", "ShiftManager"})
        records = list(db.sausage_batches.values())
        output_cut_type_id = request.args.get("output_cut_type_id")
        batch_status = request.args.get("batch_status")
        if output_cut_type_id is not None:
            records = [r for r in records
                       if r["output_cut_type_id"] == output_cut_type_id]
        if batch_status is not None:
            records = [r for r in records if r["batch_status"] == batch_status]
        return list_response(records, request.args, serializers.sausage_batch)

    @app.route("/sausage-batches/<rid>/inputs", methods=["POST"])
    def add_batch_input(rid):
        _uid, role = authenticate()
        require_role(role, {"Butcher"})
        batch = common.get_or_404(db.sausage_batches, rid)
        body = v.get_body()
        inventory_lot_id = v.as_str(
            v.require(body, "inventory_lot_id"), "inventory_lot_id")
        weight_g = v.as_int(v.require(body, "weight_g"), "weight_g", minimum=1)
        common.fk_or_404(db.inventory_lots, inventory_lot_id)
        # Inputs are added while the batch is in DRAFT (PRD §3.8).
        if batch["batch_status"] != "DRAFT":
            errors.fail(errors.ERR_INVALID_STATE,
                        "Batch is not DRAFT; cannot add inputs.")

        record = {
            "sausage_batch_id": batch["id"],
            "inventory_lot_id": inventory_lot_id,
            "weight_g": weight_g,
        }
        db.stamp_create(record)
        db.batch_inputs[record["id"]] = record
        return response.object_response(serializers.batch_input(record), 201)

    @app.route("/sausage-batches/<rid>/inputs", methods=["GET"])
    def list_batch_inputs_for_batch(rid):
        _uid, role = authenticate()
        require_role(role, {"Butcher", "ShiftManager"})
        common.get_or_404(db.sausage_batches, rid)
        records = [b for b in db.batch_inputs.values()
                   if b["sausage_batch_id"] == rid]
        return list_response(records, request.args, serializers.batch_input)

    @app.route("/sausage-batches/<rid>/reserve", methods=["POST"])
    def reserve_batch(rid):
        _uid, role = authenticate()
        require_role(role, {"Butcher"})
        batch = common.get_or_404(db.sausage_batches, rid)
        if batch["batch_status"] != "DRAFT":
            errors.fail(errors.ERR_INVALID_STATE,
                        "Batch is not DRAFT; cannot reserve.")
        inputs = [b for b in db.batch_inputs.values()
                  if b["sausage_batch_id"] == rid]
        if len(inputs) < 1:
            errors.fail(errors.ERR_INVALID_STATE, "Batch has no inputs.")

        # Atomicity (skill pitfall #5): validate ALL inputs before committing.
        for inp in inputs:
            lot = db.inventory_lots.get(inp["inventory_lot_id"])
            if lot is None:
                errors.fail(errors.ERR_NOT_FOUND, "Input lot not found.")
            if lot["lot_status"] != "AVAILABLE":
                if lot["lot_status"] == "ON_HOLD":
                    locker = db.dry_age_lockers.get(lot.get("locker_id"))
                    if locker is not None and \
                            locker["locker_status"] == "QUARANTINED":
                        errors.fail(errors.ERR_LOCKER_QUARANTINED,
                                    "Input lot is held under a quarantined locker.")
                errors.fail(errors.ERR_LOT_NOT_AVAILABLE,
                            "Input lot is not AVAILABLE.")
            if lot["remaining_weight_g"] < inp["weight_g"]:
                errors.fail(errors.ERR_INSUFFICIENT_LOT_WEIGHT,
                            "Input lot has insufficient remaining weight.")

        # Commit: one draw per input.
        for inp in inputs:
            lot = db.inventory_lots[inp["inventory_lot_id"]]
            draw = {
                "inventory_lot_id": lot["id"],
                "order_line_id": None,
                "batch_input_id": inp["id"],
                "weight_g": inp["weight_g"],
                "draw_status": "COMMITTED",
            }
            db.stamp_create(draw)
            db.lot_draws[draw["id"]] = draw
            common.reconcile_lot_remaining(lot)
            db.touch(lot)
            if lot["remaining_weight_g"] == 0 and lot["lot_status"] == "AVAILABLE":
                lot["lot_status"] = "DEPLETED"
                db.touch(lot)

        batch["batch_status"] = "RESERVED"
        db.touch(batch)
        return response.object_response(serializers.sausage_batch(batch))

    @app.route("/sausage-batches/<rid>/produce", methods=["POST"])
    def produce_batch(rid):
        _uid, role = authenticate()
        require_role(role, {"Butcher"})
        batch = common.get_or_404(db.sausage_batches, rid)
        if batch["batch_status"] != "RESERVED":
            errors.fail(errors.ERR_INVALID_STATE,
                        "Batch is not RESERVED; cannot produce.")
        inputs = [b for b in db.batch_inputs.values()
                  if b["sausage_batch_id"] == rid]
        total_input = sum(b["weight_g"] for b in inputs)
        policy = common.active_policy_or_400()
        yield_g = pricing.sausage_yield_g(total_input, policy)

        batch["actual_yield_g"] = yield_g
        batch["batch_status"] = "PRODUCED"
        db.touch(batch)

        # Create the output lot (AVAILABLE).
        out_lot = {
            "cut_type_id": batch["output_cut_type_id"],
            "source_share_id": None,
            "received_weight_g": yield_g,
            "remaining_weight_g": yield_g,
            "lot_status": "AVAILABLE",
            "locker_id": None,
            "aging_started_at": None,
            "aging_target_days": 0,
        }
        db.stamp_create(out_lot)
        db.inventory_lots[out_lot["id"]] = out_lot
        return response.object_response(serializers.sausage_batch(batch))

    @app.route("/sausage-batches/<rid>/cancel", methods=["POST"])
    def cancel_batch(rid):
        _uid, role = authenticate()
        require_role(role, {"Butcher"})
        batch = common.get_or_404(db.sausage_batches, rid)
        status = batch["batch_status"]
        if status not in ("DRAFT", "RESERVED"):
            errors.fail(errors.ERR_INVALID_STATE,
                        "Batch cannot be cancelled from %s." % status)

        if status == "RESERVED":
            # Compensation: revert committed draws of this batch.
            input_ids = {b["id"] for b in db.batch_inputs.values()
                         if b["sausage_batch_id"] == rid}
            for draw in db.lot_draws.values():
                if draw.get("batch_input_id") in input_ids and \
                        draw["draw_status"] == "COMMITTED":
                    draw["draw_status"] = "REVERTED"
                    db.touch(draw)
                    lot = db.inventory_lots.get(draw["inventory_lot_id"])
                    if lot is not None:
                        was_depleted = lot["lot_status"] == "DEPLETED"
                        common.reconcile_lot_remaining(lot)
                        if was_depleted and lot["remaining_weight_g"] > 0:
                            lot["lot_status"] = "AVAILABLE"
                        db.touch(lot)

        batch["batch_status"] = "CANCELLED"
        db.touch(batch)
        return response.object_response(serializers.sausage_batch(batch))
