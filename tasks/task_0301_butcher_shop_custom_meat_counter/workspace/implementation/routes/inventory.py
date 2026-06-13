"""InventoryLot: receive, fetch, list, start/complete aging, discard, draws
(PRD §3.2, §3.3)."""
from flask import request

import db
import errors
import response
import serializers
import validation as v
from middleware import authenticate, require_role
from routes._helpers import list_response
from services import common

LOT_STATUSES = {"AVAILABLE", "AGING", "ON_HOLD", "DEPLETED", "DISCARDED"}


def _elapsed_days(started_at, now):
    """Whole days between aging_started_at and now (PRD §3.2)."""
    delta = now - started_at
    return delta.days  # whole days, floored toward zero for positive deltas


def register(app):
    @app.route("/inventory-lots", methods=["POST"])
    def create_inventory_lot():
        _uid, role = authenticate()
        require_role(role, {"Butcher", "ShiftManager"})
        body = v.get_body()
        cut_type_id = v.as_str(v.require(body, "cut_type_id"), "cut_type_id")
        received = v.as_int(
            v.require(body, "received_weight_g"), "received_weight_g", minimum=1)
        aging_target = v.opt(body, "aging_target_days", 0)
        aging_target = v.as_int(aging_target, "aging_target_days", minimum=0)
        source_share_id = v.opt(body, "source_share_id", None)

        # FK existence (PRD §2.5)
        common.fk_or_404(db.cut_types, cut_type_id)
        if source_share_id is not None:
            v.as_str(source_share_id, "source_share_id")
            common.fk_or_404(db.animal_shares, source_share_id)

        record = {
            "cut_type_id": cut_type_id,
            "source_share_id": source_share_id,
            "received_weight_g": received,
            "remaining_weight_g": received,
            "lot_status": "AVAILABLE",
            "locker_id": None,
            "aging_started_at": None,
            "aging_target_days": aging_target,
        }
        db.stamp_create(record)
        db.inventory_lots[record["id"]] = record
        return response.object_response(serializers.inventory_lot(record), 201)

    @app.route("/inventory-lots/<rid>", methods=["GET"])
    def get_inventory_lot(rid):
        _uid, role = authenticate()
        require_role(role, {"Butcher", "ShiftManager", "CounterClerk"})
        record = common.get_or_404(db.inventory_lots, rid)
        return response.object_response(serializers.inventory_lot(record))

    @app.route("/inventory-lots", methods=["GET"])
    def list_inventory_lots():
        _uid, role = authenticate()
        require_role(role, {"Butcher", "ShiftManager", "CounterClerk"})
        records = list(db.inventory_lots.values())
        cut_type_id = request.args.get("cut_type_id")
        locker_id = request.args.get("locker_id")
        source_share_id = request.args.get("source_share_id")
        lot_status = request.args.get("lot_status")
        if cut_type_id is not None:
            records = [r for r in records if r["cut_type_id"] == cut_type_id]
        if locker_id is not None:
            records = [r for r in records if r.get("locker_id") == locker_id]
        if source_share_id is not None:
            records = [r for r in records
                       if r.get("source_share_id") == source_share_id]
        if lot_status is not None:
            records = [r for r in records if r["lot_status"] == lot_status]
        return list_response(records, request.args, serializers.inventory_lot)

    @app.route("/inventory-lots/<rid>/start-aging", methods=["POST"])
    def start_aging(rid):
        _uid, role = authenticate()
        require_role(role, {"Butcher"})
        lot = common.get_or_404(db.inventory_lots, rid)
        body = v.get_body()
        locker_id = v.as_str(v.require(body, "locker_id"), "locker_id")
        locker = common.fk_or_404(db.dry_age_lockers, locker_id)

        # State gate: transition is only defined from AVAILABLE (PRD §2.10 #5).
        if lot["lot_status"] != "AVAILABLE":
            errors.fail(errors.ERR_INVALID_STATE,
                        "Lot is not AVAILABLE; cannot start aging.")

        cut = db.cut_types.get(lot["cut_type_id"])
        # requires_dry_age precondition (PRD §3.2).
        if not cut or not cut.get("requires_dry_age"):
            errors.fail(errors.ERR_INVALID_STATE,
                        "Cut type does not require dry-aging.")
        # Locker must be OPERATIONAL.
        if locker["locker_status"] != "OPERATIONAL":
            errors.fail(errors.ERR_INVALID_STATE, "Locker is not OPERATIONAL.")
        # Untouched lot (no draws): remaining == received.
        if lot["remaining_weight_g"] != lot["received_weight_g"]:
            errors.fail(errors.ERR_INVALID_STATE,
                        "Lot has draws; cannot start aging.")
        # Capacity check (inclusive at equality) — ERR_LOCKER_OVER_CAPACITY.
        if locker["occupied_g"] + lot["received_weight_g"] > locker["capacity_g"]:
            errors.fail(errors.ERR_LOCKER_OVER_CAPACITY,
                        "Locker would exceed capacity.")

        lot["lot_status"] = "AGING"
        lot["locker_id"] = locker_id
        lot["aging_started_at"] = _clock_iso()
        db.touch(lot)
        common.reconcile_locker_occupied(locker)
        db.touch(locker)
        return response.object_response(serializers.inventory_lot(lot))

    @app.route("/inventory-lots/<rid>/complete-aging", methods=["POST"])
    def complete_aging(rid):
        _uid, role = authenticate()
        require_role(role, {"Butcher"})
        lot = common.get_or_404(db.inventory_lots, rid)

        # PRD §3.2: "completing aging on a lot whose locker is quarantined is
        # rejected with ERR_LOCKER_QUARANTINED (HTTP 409)." The quarantine
        # cascade holds an AGING lot as ON_HOLD (still carrying its locker_id),
        # so this case must surface ERR_LOCKER_QUARANTINED — not the generic
        # ERR_INVALID_STATE — even though the lot is no longer AGING.
        if lot["lot_status"] == "ON_HOLD":
            locker = db.dry_age_lockers.get(lot.get("locker_id"))
            if locker is not None and locker["locker_status"] == "QUARANTINED":
                errors.fail(errors.ERR_LOCKER_QUARANTINED,
                            "Lot's locker is quarantined.")

        if lot["lot_status"] != "AGING":
            errors.fail(errors.ERR_INVALID_STATE,
                        "Lot is not AGING; cannot complete aging.")
        locker = db.dry_age_lockers.get(lot.get("locker_id"))
        # Locker must be OPERATIONAL (PRD §3.2) -> ERR_LOCKER_QUARANTINED.
        if locker is not None and locker["locker_status"] != "OPERATIONAL":
            errors.fail(errors.ERR_LOCKER_QUARANTINED,
                        "Lot's locker is quarantined.")
        # Aging elapsed days check.
        started = common.parse_iso(lot["aging_started_at"], "aging_started_at")
        now = db.current_utc()
        if _elapsed_days(started, now) < lot["aging_target_days"]:
            errors.fail(errors.ERR_AGING_NOT_COMPLETE,
                        "Aging target days not yet elapsed.")

        lot["lot_status"] = "AVAILABLE"
        lot["locker_id"] = None
        db.touch(lot)
        if locker is not None:
            common.reconcile_locker_occupied(locker)
            db.touch(locker)
        return response.object_response(serializers.inventory_lot(lot))

    @app.route("/inventory-lots/<rid>/discard", methods=["POST"])
    def discard_lot(rid):
        _uid, role = authenticate()
        require_role(role, {"ShiftManager"})
        lot = common.get_or_404(db.inventory_lots, rid)
        if lot["lot_status"] != "ON_HOLD":
            errors.fail(errors.ERR_INVALID_STATE,
                        "Lot is not ON_HOLD; cannot discard.")
        locker = db.dry_age_lockers.get(lot.get("locker_id"))
        lot["lot_status"] = "DISCARDED"
        lot["locker_id"] = None
        lot["remaining_weight_g"] = 0
        db.touch(lot)
        if locker is not None:
            common.reconcile_locker_occupied(locker)
            db.touch(locker)
        return response.object_response(serializers.inventory_lot(lot))

    @app.route("/inventory-lots/<rid>/draws", methods=["GET"])
    def list_lot_draws_for_lot(rid):
        _uid, role = authenticate()
        require_role(role, {"Butcher", "ShiftManager"})
        common.get_or_404(db.inventory_lots, rid)
        records = [d for d in db.lot_draws.values()
                   if d["inventory_lot_id"] == rid]
        draw_status = request.args.get("draw_status")
        if draw_status is not None:
            records = [r for r in records if r["draw_status"] == draw_status]
        return list_response(records, request.args, serializers.lot_draw)


def _clock_iso():
    """Current logical clock as an ISO 8601 UTC string with ms precision."""
    dt = db.current_utc()
    return (dt.strftime("%Y-%m-%dT%H:%M:%S.")
            + "{:03d}".format(dt.microsecond // 1000) + "Z")
