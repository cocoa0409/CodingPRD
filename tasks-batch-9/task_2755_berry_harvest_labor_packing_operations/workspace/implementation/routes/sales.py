"""Buyer programs, allocation lines, shipping and settlement (PRD §3.7)."""

from flask import Blueprint

import config
import db
import response
import util
import validation as V
from errors import fail
from routes.helpers import HM, PO, SM, filter_args
from services import calc

bp = Blueprint("sales", __name__)

SALES_READERS = (SM, HM, PO)

COMMITMENT_FIELDS = [
    V.Field("buyer_name", "string", maxlen=80),
    V.Field("buyer_user_id", "string", maxlen=64),
    V.Field("variety", "string", enum=config.VARIETIES),
    V.Field("volume_commitment_lbs", "number", exclusive_min=0),
    V.Field("price_cents_per_lb", "int", minimum=1, maximum=10000),
    V.Field("shelf_life_guarantee_days", "int", minimum=1, maximum=30),
    V.Field("window_start_date", "date"),
    V.Field("window_end_date", "date"),
]

ALLOCATION_FIELDS = [
    V.Field("fruit_lot_id", "string"),
    V.Field("buyer_commitment_id", "string"),
    V.Field("allocated_lbs", "number", exclusive_min=0),
    V.Field("expected_buyer_commitment_version", "int"),
]

SHIP_FIELDS = [V.Field("shipped_at", "instant")]
RELEASE_FIELDS = [V.Field("release_reason_code", "string")]


# ---------------------------------------------------------------------------
# buyer commitments
# ---------------------------------------------------------------------------
@bp.route("/buyer-commitments", methods=["POST"])
def create_commitment():
    V.authenticate((SM,))
    body = V.read_body()
    V.validate_body(COMMITMENT_FIELDS, body)
    start = V.tolerant("date", body.get("window_start_date"))
    end = V.tolerant("date", body.get("window_end_date"))
    if start is not None and end is not None and end < start:
        fail(
            "ERR_INVALID_DATE_RANGE",
            "window_end_date must be on or after window_start_date.",
        )
    parsed = V.parse_temporal(COMMITMENT_FIELDS, body)

    volume = util.q2(body["volume_commitment_lbs"])
    rec = db.new_record()
    rec["buyer_name"] = body["buyer_name"]
    rec["buyer_user_id"] = body["buyer_user_id"]
    rec["variety"] = body["variety"]
    rec["volume_commitment_lbs"] = volume
    rec["price_cents_per_lb"] = int(body["price_cents_per_lb"])
    rec["shelf_life_guarantee_days"] = int(body["shelf_life_guarantee_days"])
    rec["window_start_date"] = body["window_start_date"]
    rec["window_end_date"] = body["window_end_date"]
    rec["committed_lbs"] = util.q2(0)
    rec["shipped_lbs"] = util.q2(0)
    # PRD §3.7: open_lbs is "not yet determined" on a brand-new program; it is
    # first derived by the exposure recompute the initial allocation triggers.
    rec["open_lbs"] = None
    rec["fill_pct"] = util.q4(0)
    rec["fill_status"] = "PENDING"
    rec["settled_revenue_cents"] = None
    rec["shortfall_penalty_cents"] = None
    rec["settled_net_cents"] = None
    rec["status"] = "OPEN"
    rec["_window_start_date"] = parsed["window_start_date"]
    rec["_window_end_date"] = parsed["window_end_date"]
    rec["_coverage_pct"] = util.q4(0)
    rec["risk_flag"] = calc.risk_flag(rec, util.q4(0))
    db.buyer_commitments[rec["id"]] = rec
    return response.object_response(rec, 201)


@bp.route("/buyer-commitments/<buyer_commitment_id>", methods=["GET"])
def read_commitment(buyer_commitment_id):
    V.authenticate(SALES_READERS)
    return response.object_response(V.get_commitment(buyer_commitment_id))


@bp.route("/buyer-commitments", methods=["GET"])
def list_commitments():
    V.authenticate(SALES_READERS)
    rows = filter_args(
        db.all_of(db.buyer_commitments), {"variety": "variety", "status": "status"}
    )
    return response.paginate(rows)


@bp.route("/buyer-commitments/<buyer_commitment_id>/settle", methods=["POST"])
def settle_commitment(buyer_commitment_id):
    V.authenticate((SM,))
    commitment = V.get_commitment(buyer_commitment_id)
    if commitment["status"] != "OPEN":
        fail("ERR_INVALID_COMMITMENT_STATE", "Only an OPEN commitment may be settled.")
    if db.clock_date() <= commitment["_window_end_date"]:
        fail(
            "ERR_TEMPORAL_ORDER_VIOLATION",
            "A commitment settles only after its delivery window has passed.",
        )
    lines = db.allocations_of_commitment(commitment["id"])
    for line in lines:
        if line["status"] == "RESERVED":
            fail(
                "ERR_INVALID_ALLOCATION_STATE",
                "Every reserved line must be shipped or released before settlement.",
            )

    shipped_lines = sorted(
        [l for l in lines if l["status"] == "SHIPPED"],
        key=lambda l: (l["_shipped_at"], l["created_at"], l["_seq"]),
    )
    volume = util.dec(commitment["volume_commitment_lbs"])
    shipped_lbs = util.dec(commitment["shipped_lbs"])

    if shipped_lbs > 0:
        revenue = calc.price_shipped_lines(commitment, shipped_lines)
        for line in shipped_lines:
            db.touch(line)
        fill_pct = util.q4(shipped_lbs / volume) if volume > 0 else util.q4(0)
        commitment["fill_pct"] = fill_pct
        if fill_pct >= config.FILL_TARGET_PCT:
            commitment["fill_status"] = "FILLED"
            penalty = 0
        else:
            commitment["fill_status"] = "SHORTFALL"
            penalty = calc.shortfall_penalty(commitment, shipped_lbs)
        commitment["settled_revenue_cents"] = revenue
        commitment["shortfall_penalty_cents"] = penalty
        commitment["settled_net_cents"] = revenue - penalty
        commitment["status"] = "SETTLED"
    else:
        penalty = util.q0(
            volume * util.dec(commitment["price_cents_per_lb"])
            * config.SHORTFALL_PENALTY_RATE
        )
        commitment["settled_revenue_cents"] = 0
        commitment["fill_pct"] = util.q4(0)
        commitment["fill_status"] = "SHORTFALL"
        commitment["shortfall_penalty_cents"] = penalty
        commitment["settled_net_cents"] = -penalty
        commitment["status"] = "DEFAULTED"

    db.touch(commitment)
    return response.object_response(commitment)


# ---------------------------------------------------------------------------
# allocation lines
# ---------------------------------------------------------------------------
@bp.route("/lot-allocations", methods=["POST"])
def create_allocation():
    V.authenticate((SM,))
    body = V.read_body()
    V.validate_body(ALLOCATION_FIELDS, body)
    lot = V.get_lot(body["fruit_lot_id"])
    commitment = V.get_commitment(body["buyer_commitment_id"])

    if int(body["expected_buyer_commitment_version"]) != int(commitment["version"]):
        fail("ERR_STALE_COMMITMENT_VERSION")
    if lot["disposition_status"] not in ("UNCOMMITTED", "RESERVED"):
        fail("ERR_INVALID_DISPOSITION_STATE")
    if commitment["status"] != "OPEN":
        fail("ERR_INVALID_COMMITMENT_STATE", "Only an OPEN commitment may be allocated against.")
    if lot["food_safety_hold"]:
        fail("ERR_LOT_ON_FOOD_SAFETY_HOLD")
    if lot["variety"] != commitment["variety"]:
        fail("ERR_VARIETY_MISMATCH", "The lot's variety must match the commitment's variety.")
    pledge = util.q2(body["allocated_lbs"])
    if pledge > util.dec(lot["available_lbs"]):
        fail("ERR_LOT_VOLUME_EXCEEDED")
    if commitment["open_lbs"] is None:
        open_now = util.q2(
            util.dec(commitment["volume_commitment_lbs"])
            - util.dec(commitment["committed_lbs"])
        )
    else:
        open_now = util.dec(commitment["open_lbs"])
    if pledge > open_now:
        fail("ERR_COMMITMENT_OVERBOOKED")

    rec = db.new_record()
    rec["fruit_lot_id"] = lot["id"]
    rec["buyer_commitment_id"] = commitment["id"]
    rec["allocated_lbs"] = pledge
    rec["shipped_at"] = None
    rec["release_reason_code"] = None
    rec["shelf_life_shortfall_days"] = None
    rec["line_gross_cents"] = None
    rec["line_discount_cents"] = None
    rec["line_net_cents"] = None
    rec["status"] = "RESERVED"
    rec["_shipped_at"] = None
    db.lot_allocations[rec["id"]] = rec

    if lot["disposition_status"] == "UNCOMMITTED":
        lot["disposition_status"] = "RESERVED"
    calc.recompute_lot_balance(lot)
    db.touch(lot)
    calc.recompute_commitment_exposure(commitment)
    db.touch(commitment)
    return response.object_response(rec, 201)


@bp.route("/lot-allocations/<lot_allocation_id>", methods=["GET"])
def read_allocation(lot_allocation_id):
    V.authenticate(SALES_READERS)
    return response.object_response(V.get_allocation(lot_allocation_id))


@bp.route("/lot-allocations", methods=["GET"])
def list_allocations():
    V.authenticate(SALES_READERS)
    rows = filter_args(
        db.all_of(db.lot_allocations),
        {
            "fruit_lot_id": "fruit_lot_id",
            "buyer_commitment_id": "buyer_commitment_id",
            "status": "status",
        },
    )
    return response.paginate(rows)


@bp.route("/lot-allocations/<lot_allocation_id>/ship", methods=["POST"])
def ship_allocation(lot_allocation_id):
    V.authenticate((SM,))
    line = V.get_allocation(lot_allocation_id)
    body = V.read_body()
    V.check_shape(SHIP_FIELDS, body)
    parsed = V.parse_temporal(SHIP_FIELDS, body)
    shipped_at = parsed["shipped_at"]

    lot = db.fruit_lots[line["fruit_lot_id"]]
    commitment = db.buyer_commitments[line["buyer_commitment_id"]]
    if lot["cold_chain_status"] != "COOLED":
        fail("ERR_INVALID_COLD_CHAIN_STATE", "Only a COOLED lot may ship.")
    if line["status"] != "RESERVED":
        fail("ERR_INVALID_ALLOCATION_STATE", "Only a RESERVED line may be shipped.")
    if commitment["status"] != "OPEN":
        fail("ERR_INVALID_COMMITMENT_STATE", "Only an OPEN commitment may be shipped from.")
    if lot["food_safety_hold"]:
        fail("ERR_LOT_ON_FOOD_SAFETY_HOLD")
    block = db.blocks.get(lot["block_id"])
    if block is None or block["water_status"] != "COMPLIANT":
        fail("ERR_BLOCK_WATER_NOT_COMPLIANT")
    ship_date = shipped_at.date()
    if not (
        commitment["_window_start_date"] <= ship_date <= commitment["_window_end_date"]
    ):
        fail(
            "ERR_SHIP_OUTSIDE_PROGRAM_WINDOW",
            "shipped_at falls outside the buyer's delivery window.",
        )
    expires = util.parse_date(lot["shelf_life_expires_on"])
    if expires is None or db.clock_date() > expires:
        fail(
            "ERR_SHIP_OUTSIDE_PROGRAM_WINDOW",
            "The lot is past its verified shelf life.",
        )

    line["shipped_at"] = body["shipped_at"]
    line["_shipped_at"] = shipped_at
    line["status"] = "SHIPPED"
    db.touch(line)
    lot["cold_chain_status"] = "SHIPPED"
    lot["disposition_status"] = "DELIVERED"
    db.touch(lot)
    calc.recompute_commitment_exposure(commitment)
    db.touch(commitment)
    return response.object_response(line)


@bp.route("/lot-allocations/<lot_allocation_id>/release", methods=["POST"])
def release_allocation(lot_allocation_id):
    V.authenticate((SM,))
    line = V.get_allocation(lot_allocation_id)
    body = V.read_body()
    V.check_shape(RELEASE_FIELDS, body)

    lot = db.fruit_lots[line["fruit_lot_id"]]
    commitment = db.buyer_commitments[line["buyer_commitment_id"]]
    if line["status"] != "RESERVED":
        fail("ERR_INVALID_ALLOCATION_STATE", "Only a RESERVED line may be released.")
    if commitment["status"] != "OPEN":
        fail("ERR_INVALID_COMMITMENT_STATE", "Only an OPEN commitment may be released from.")

    line["status"] = "RELEASED"
    line["release_reason_code"] = body["release_reason_code"]
    db.touch(line)

    calc.recompute_lot_balance(lot)
    still_held = any(
        a["status"] in ("RESERVED", "SHIPPED") for a in db.allocations_of_lot(lot["id"])
    )
    if not still_held and lot["disposition_status"] == "RESERVED":
        lot["disposition_status"] = "UNCOMMITTED"
    db.touch(lot)
    calc.recompute_commitment_exposure(commitment)
    db.touch(commitment)
    return response.object_response(line)
