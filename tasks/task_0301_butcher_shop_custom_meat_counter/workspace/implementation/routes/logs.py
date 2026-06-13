"""Reverse-reachability single reads + lists for log/junction children
(PRD §3.8, §3.9)."""
from flask import request

import db
import response
import serializers
from middleware import authenticate, require_role
from routes._helpers import list_response
from services import common


def register(app):
    # ---- LotDraw ----
    @app.route("/lot-draws/<rid>", methods=["GET"])
    def get_lot_draw(rid):
        _uid, role = authenticate()
        require_role(role, {"Butcher", "ShiftManager"})
        record = common.get_or_404(db.lot_draws, rid)
        return response.object_response(serializers.lot_draw(record))

    @app.route("/lot-draws", methods=["GET"])
    def list_lot_draws():
        _uid, role = authenticate()
        require_role(role, {"Butcher", "ShiftManager"})
        records = list(db.lot_draws.values())
        inventory_lot_id = request.args.get("inventory_lot_id")
        order_line_id = request.args.get("order_line_id")
        batch_input_id = request.args.get("batch_input_id")
        draw_status = request.args.get("draw_status")
        if inventory_lot_id is not None:
            records = [r for r in records
                       if r["inventory_lot_id"] == inventory_lot_id]
        if order_line_id is not None:
            records = [r for r in records
                       if r.get("order_line_id") == order_line_id]
        if batch_input_id is not None:
            records = [r for r in records
                       if r.get("batch_input_id") == batch_input_id]
        if draw_status is not None:
            records = [r for r in records if r["draw_status"] == draw_status]
        return list_response(records, request.args, serializers.lot_draw)

    # ---- BatchInput ----
    @app.route("/batch-inputs/<rid>", methods=["GET"])
    def get_batch_input(rid):
        _uid, role = authenticate()
        require_role(role, {"Butcher", "ShiftManager"})
        record = common.get_or_404(db.batch_inputs, rid)
        return response.object_response(serializers.batch_input(record))

    @app.route("/batch-inputs", methods=["GET"])
    def list_batch_inputs():
        _uid, role = authenticate()
        require_role(role, {"Butcher", "ShiftManager"})
        records = list(db.batch_inputs.values())
        inventory_lot_id = request.args.get("inventory_lot_id")
        sausage_batch_id = request.args.get("sausage_batch_id")
        if inventory_lot_id is not None:
            records = [r for r in records
                       if r["inventory_lot_id"] == inventory_lot_id]
        if sausage_batch_id is not None:
            records = [r for r in records
                       if r["sausage_batch_id"] == sausage_batch_id]
        return list_response(records, request.args, serializers.batch_input)

    # ---- TempReading single read ----
    @app.route("/temp-readings/<rid>", methods=["GET"])
    def get_temp_reading(rid):
        _uid, role = authenticate()
        require_role(role, {"SafetyOfficer", "ShiftManager", "Butcher"})
        record = common.get_or_404(db.temp_readings, rid)
        return response.object_response(serializers.temp_reading(record))
