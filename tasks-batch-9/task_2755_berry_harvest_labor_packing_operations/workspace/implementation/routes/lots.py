"""Cooling tunnels, field-packed fruit lots, the cold chain and the repack
line (PRD §3.6)."""

from flask import Blueprint

import config
import db
import response
import util
import validation as V
from errors import fail
from routes.helpers import FSO, HM, PO, SM, filter_args
from services import calc, cascade

bp = Blueprint("lots", __name__)

LOT_READERS = (PO, HM, SM, FSO)

TUNNEL_FIELDS = [
    V.Field("name", "string", maxlen=40),
    V.Field("slot_capacity", "int", minimum=1, maximum=96),
    V.Field("target_pulp_temp_f", "number", minimum=30, maximum=40),
]

LOT_FIELDS = [
    V.Field("harvest_window_id", "string"),
    V.Field("block_id", "string"),
    V.Field("pick_date", "date"),
    V.Field("variety", "string", enum=config.VARIETIES),
    V.Field("grade", "string", enum=config.GRADES),
    V.Field("clamshell_count", "int", minimum=1),
    V.Field("clamshell_net_weight_lbs", "number", exclusive_min=0, maximum=5),
    V.Field("pack_completed_at", "instant"),
    V.Field("field_pulp_temp_f", "number", minimum=30, maximum=110),
]

START_FIELDS = [
    V.Field("cooling_tunnel_id", "string"),
    V.Field("cool_start_at", "instant"),
    V.Field("planned_cool_end_at", "instant"),
    V.Field("entry_pulp_temp_f", "number"),
    V.Field("pallet_slots", "int", minimum=1, maximum=96),
    V.Field("expected_cooling_tunnel_version", "int"),
]

COMPLETE_FIELDS = [
    V.Field("cool_complete_at", "instant"),
    V.Field("exit_pulp_temp_f", "number"),
]

REPACK_FIELDS = [
    V.Field("output_grade", "string", enum=config.GRADES),
    V.Field("output_clamshell_count", "int"),
    V.Field("cull_clamshell_count", "int"),
    V.Field("optical_reject_clamshell_count", "int"),
]

REJECT_FIELDS = [V.Field("reject_reason_code", "string")]


# ---------------------------------------------------------------------------
# cooling tunnels
# ---------------------------------------------------------------------------
@bp.route("/cooling-tunnels", methods=["POST"])
def create_tunnel():
    V.authenticate((PO,))
    body = V.read_body()
    V.validate_body(TUNNEL_FIELDS, body)
    for other in db.cooling_tunnels.values():
        if other["name"] == body["name"]:
            fail("ERR_DUPLICATE_RECORD", "A cooling tunnel with that name already exists.")
    rec = db.new_record()
    rec["name"] = body["name"]
    rec["slot_capacity"] = int(body["slot_capacity"])
    rec["target_pulp_temp_f"] = util.q1(body["target_pulp_temp_f"])
    rec["committed_slots"] = 0
    db.cooling_tunnels[rec["id"]] = rec
    return response.object_response(rec, 201)


@bp.route("/cooling-tunnels/<cooling_tunnel_id>", methods=["GET"])
def read_tunnel(cooling_tunnel_id):
    V.authenticate((PO, HM, SM))
    return response.object_response(V.get_tunnel(cooling_tunnel_id))


@bp.route("/cooling-tunnels", methods=["GET"])
def list_tunnels():
    V.authenticate((PO, HM, SM))
    return response.paginate(db.all_of(db.cooling_tunnels))


# ---------------------------------------------------------------------------
# fruit lots
# ---------------------------------------------------------------------------
def _blank_lot():
    rec = db.new_record()
    rec["source_lot_id"] = None
    rec["cooling_tunnel_id"] = None
    rec["cool_start_at"] = None
    rec["planned_cool_end_at"] = None
    rec["cool_complete_at"] = None
    rec["entry_pulp_temp_f"] = None
    rec["exit_pulp_temp_f"] = None
    rec["pallet_slots"] = None
    rec["field_delay_hours"] = None
    rec["cool_hours"] = None
    rec["forecast_shelf_life_days"] = None
    rec["verified_shelf_life_days"] = None
    rec["shelf_life_expires_on"] = None
    rec["cold_chain_status"] = "PACKED"
    rec["disposition_status"] = "UNCOMMITTED"
    rec["allocated_lbs"] = util.q2(0)
    rec["repack_out_lbs"] = util.q2(0)
    rec["cull_lbs"] = util.q2(0)
    rec["optical_reject_lbs"] = util.q2(0)
    rec["food_safety_hold"] = False
    rec["reject_reason_code"] = None
    rec["_cool_start_at"] = None
    rec["_planned_cool_end_at"] = None
    rec["_cool_complete_at"] = None
    return rec


@bp.route("/fruit-lots", methods=["POST"])
def create_lot():
    V.authenticate((PO,))
    body = V.read_body()
    V.validate_body(LOT_FIELDS, body)
    parsed = V.parse_temporal(LOT_FIELDS, body)
    block = V.get_block(body["block_id"])
    window = V.get_window(body["harvest_window_id"])

    if block["food_safety_posture"] == "QUARANTINED":
        fail("ERR_BLOCK_QUARANTINED")
    if window["block_id"] != block["id"]:
        fail("ERR_LOT_BLOCK_MISMATCH")
    if body["variety"] != block["variety"]:
        fail("ERR_VARIETY_MISMATCH", "The lot's variety must match the block's variety.")
    pick_date = parsed["pick_date"]
    if not (window["_start_at"].date() <= pick_date <= window["_end_at"].date()):
        fail("ERR_PICK_DATE_OUTSIDE_WINDOW")

    weight = util.q2(body["clamshell_net_weight_lbs"])
    count = int(body["clamshell_count"])
    rec = _blank_lot()
    rec["harvest_window_id"] = window["id"]
    rec["block_id"] = block["id"]
    rec["pick_date"] = body["pick_date"]
    rec["variety"] = body["variety"]
    rec["grade"] = body["grade"]
    rec["clamshell_count"] = count
    rec["clamshell_net_weight_lbs"] = weight
    rec["net_packed_lbs"] = util.q2(util.dec(count) * weight)
    rec["pack_completed_at"] = body["pack_completed_at"]
    rec["field_pulp_temp_f"] = util.q1(body["field_pulp_temp_f"])
    rec["available_lbs"] = rec["net_packed_lbs"]
    rec["traceability_code"] = calc.traceability_code(
        block, body["pick_date"], pick_date, body["grade"]
    )
    rec["_pick_date"] = pick_date
    rec["_pack_completed_at"] = parsed["pack_completed_at"]
    db.fruit_lots[rec["id"]] = rec

    calc.recompute_window_packed(window)
    db.touch(window)
    return response.object_response(rec, 201)


@bp.route("/fruit-lots/<fruit_lot_id>", methods=["GET"])
def read_lot(fruit_lot_id):
    V.authenticate(LOT_READERS)
    return response.object_response(V.get_lot(fruit_lot_id))


@bp.route("/fruit-lots", methods=["GET"])
def list_lots():
    V.authenticate(LOT_READERS)
    rows = filter_args(
        db.all_of(db.fruit_lots),
        {
            "harvest_window_id": "harvest_window_id",
            "block_id": "block_id",
            "source_lot_id": "source_lot_id",
            "cooling_tunnel_id": "cooling_tunnel_id",
            "cold_chain_status": "cold_chain_status",
            "disposition_status": "disposition_status",
        },
    )
    return response.paginate(rows)


@bp.route("/fruit-lots/<fruit_lot_id>/start-cooling", methods=["POST"])
def start_cooling(fruit_lot_id):
    V.authenticate((PO,))
    lot = V.get_lot(fruit_lot_id)
    body = V.read_body()
    V.validate_body(START_FIELDS, body)
    start = V.tolerant("instant", body.get("cool_start_at"))
    end = V.tolerant("instant", body.get("planned_cool_end_at"))
    if start is not None and end is not None and end <= start:
        fail(
            "ERR_INVALID_DATE_RANGE",
            "planned_cool_end_at must be strictly after cool_start_at.",
        )
    parsed = V.parse_temporal(START_FIELDS, body)
    start = parsed["cool_start_at"]
    end = parsed["planned_cool_end_at"]
    tunnel = V.get_tunnel(body["cooling_tunnel_id"])

    if int(body["expected_cooling_tunnel_version"]) != int(tunnel["version"]):
        fail("ERR_STALE_TUNNEL_VERSION")
    if lot["cold_chain_status"] != "PACKED":
        fail("ERR_INVALID_COLD_CHAIN_STATE", "Only a PACKED lot may start cooling.")
    if lot["disposition_status"] not in ("UNCOMMITTED", "RESERVED"):
        fail("ERR_INVALID_DISPOSITION_STATE")
    if lot["food_safety_hold"]:
        fail("ERR_LOT_ON_FOOD_SAFETY_HOLD")
    if start < lot["_pack_completed_at"]:
        fail(
            "ERR_TEMPORAL_ORDER_VIOLATION",
            "cool_start_at may not precede pack_completed_at.",
        )
    slots = int(body["pallet_slots"])
    if not calc.tunnel_has_room(tunnel, start, end, slots, lot["id"]):
        fail("ERR_TUNNEL_CAPACITY_EXCEEDED")

    lot["cooling_tunnel_id"] = tunnel["id"]
    lot["cool_start_at"] = body["cool_start_at"]
    lot["planned_cool_end_at"] = body["planned_cool_end_at"]
    lot["entry_pulp_temp_f"] = util.q1(body["entry_pulp_temp_f"])
    lot["pallet_slots"] = slots
    lot["_cool_start_at"] = start
    lot["_planned_cool_end_at"] = end
    lot["field_delay_hours"] = util.hours_between(lot["_pack_completed_at"], start)
    forecast, _ = calc.shelf_life_days(lot, end, None)
    lot["forecast_shelf_life_days"] = forecast
    lot["cold_chain_status"] = "COOLING"
    db.touch(lot)

    tunnel["committed_slots"] = int(tunnel["committed_slots"]) + slots
    db.touch(tunnel)
    return response.object_response(lot)


@bp.route("/fruit-lots/<fruit_lot_id>/complete-cooling", methods=["POST"])
def complete_cooling(fruit_lot_id):
    V.authenticate((PO,))
    lot = V.get_lot(fruit_lot_id)
    body = V.read_body()
    V.validate_body(COMPLETE_FIELDS, body)
    parsed = V.parse_temporal(COMPLETE_FIELDS, body)
    if lot["cold_chain_status"] != "COOLING":
        fail("ERR_INVALID_COLD_CHAIN_STATE", "Only a COOLING lot may complete cooling.")
    done = parsed["cool_complete_at"]
    if done <= lot["_cool_start_at"]:
        fail(
            "ERR_TEMPORAL_ORDER_VIOLATION",
            "cool_complete_at must be strictly after cool_start_at.",
        )

    exit_temp = util.q1(body["exit_pulp_temp_f"])
    verified, cool_hours = calc.shelf_life_days(lot, done, exit_temp)
    lot["cool_complete_at"] = body["cool_complete_at"]
    lot["_cool_complete_at"] = done
    lot["exit_pulp_temp_f"] = exit_temp
    lot["cool_hours"] = cool_hours
    lot["verified_shelf_life_days"] = verified
    lot["shelf_life_expires_on"] = util.date_str(util.add_days(done.date(), verified))
    lot["cold_chain_status"] = "COOLED"
    db.touch(lot)

    tunnel = db.cooling_tunnels.get(lot["cooling_tunnel_id"])
    if tunnel is not None:
        tunnel["committed_slots"] = max(
            0, int(tunnel["committed_slots"]) - int(lot["pallet_slots"] or 0)
        )
        db.touch(tunnel)
    return response.object_response(lot)


@bp.route("/fruit-lots/<fruit_lot_id>/repack", methods=["POST"])
def repack_lot(fruit_lot_id):
    V.authenticate((PO,))
    source = V.get_lot(fruit_lot_id)
    body = V.read_body()
    V.validate_body(REPACK_FIELDS, body)
    if source["cold_chain_status"] != "COOLED":
        fail("ERR_INVALID_COLD_CHAIN_STATE", "Only a COOLED lot may be repacked.")
    if source["disposition_status"] != "UNCOMMITTED":
        fail("ERR_INVALID_DISPOSITION_STATE", "Only an UNCOMMITTED lot may be repacked.")
    if source["food_safety_hold"]:
        fail("ERR_LOT_ON_FOOD_SAFETY_HOLD")

    out = int(body["output_clamshell_count"])
    culls = int(body["cull_clamshell_count"])
    rejects = int(body["optical_reject_clamshell_count"])
    if out + culls + rejects != int(source["clamshell_count"]) or out < 1:
        fail("ERR_REPACK_MASS_BALANCE")

    weight = util.dec(source["clamshell_net_weight_lbs"])
    block = db.blocks[source["block_id"]]
    verified_source = source["verified_shelf_life_days"]
    if verified_source is None:
        child_verified = config.SHELF_LIFE_FLOOR_DAYS
    else:
        child_verified = max(
            config.SHELF_LIFE_FLOOR_DAYS,
            int(verified_source) - config.REPACK_DERATE_DAYS,
        )

    child = _blank_lot()
    child["harvest_window_id"] = source["harvest_window_id"]
    child["block_id"] = source["block_id"]
    child["source_lot_id"] = source["id"]
    child["cooling_tunnel_id"] = source["cooling_tunnel_id"]
    child["pick_date"] = source["pick_date"]
    child["variety"] = source["variety"]
    child["grade"] = body["output_grade"]
    child["clamshell_count"] = out
    child["clamshell_net_weight_lbs"] = source["clamshell_net_weight_lbs"]
    child["net_packed_lbs"] = util.q2(util.dec(out) * weight)
    child["pack_completed_at"] = source["pack_completed_at"]
    child["field_pulp_temp_f"] = source["field_pulp_temp_f"]
    child["cool_start_at"] = source["cool_start_at"]
    child["planned_cool_end_at"] = source["planned_cool_end_at"]
    child["cool_complete_at"] = source["cool_complete_at"]
    child["entry_pulp_temp_f"] = source["entry_pulp_temp_f"]
    child["exit_pulp_temp_f"] = source["exit_pulp_temp_f"]
    child["pallet_slots"] = source["pallet_slots"]
    child["field_delay_hours"] = source["field_delay_hours"]
    child["cool_hours"] = source["cool_hours"]
    child["forecast_shelf_life_days"] = source["forecast_shelf_life_days"]
    child["verified_shelf_life_days"] = child_verified
    child["cold_chain_status"] = "COOLED"
    child["disposition_status"] = "UNCOMMITTED"
    child["available_lbs"] = child["net_packed_lbs"]
    child["traceability_code"] = calc.traceability_code(
        block, source["pick_date"], source["_pick_date"], body["output_grade"]
    )
    child["_pick_date"] = source["_pick_date"]
    child["_pack_completed_at"] = source["_pack_completed_at"]
    child["_cool_start_at"] = source["_cool_start_at"]
    child["_planned_cool_end_at"] = source["_planned_cool_end_at"]
    child["_cool_complete_at"] = source["_cool_complete_at"]
    if source["_cool_complete_at"] is not None:
        child["shelf_life_expires_on"] = util.date_str(
            util.add_days(source["_cool_complete_at"].date(), child_verified)
        )
    db.fruit_lots[child["id"]] = child

    source["repack_out_lbs"] = util.q2(util.dec(out) * weight)
    source["cull_lbs"] = util.q2(util.dec(culls) * weight)
    source["optical_reject_lbs"] = util.q2(util.dec(rejects) * weight)
    source["available_lbs"] = util.q2(0)
    source["disposition_status"] = "REPACKED"
    db.touch(source)
    return response.object_response(child, 201)


@bp.route("/fruit-lots/<fruit_lot_id>/reject", methods=["POST"])
def reject_lot(fruit_lot_id):
    V.authenticate((PO, FSO))
    lot = V.get_lot(fruit_lot_id)
    body = V.read_body()
    V.check_shape(REJECT_FIELDS, body)
    if lot["disposition_status"] in ("DELIVERED", "REJECTED", "REPACKED"):
        fail("ERR_INVALID_DISPOSITION_STATE")
    cascade.reject_lot(lot, body["reject_reason_code"])
    return response.object_response(lot)
