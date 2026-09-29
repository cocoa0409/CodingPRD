"""Production blocks, the append-only agricultural-water register and the
logical harvest clock (PRD §3.1, §2.5)."""

from flask import Blueprint

import config
import db
import response
import util
import validation as V
from errors import fail
from routes.helpers import ALL_READERS, FSO, HM, PO, SM, filter_args
from services import calc, cascade

bp = Blueprint("blocks", __name__)

BLOCK_FIELDS = [
    V.Field("name", "string", maxlen=80),
    V.Field("variety", "string", enum=config.VARIETIES),
    V.Field("acres", "number", exclusive_min=0),
    V.Field("planting_year", "int", minimum=2000, maximum=2026),
    V.Field("irrigation_source_code", "string", maxlen=32),
]


def _new_block(body, name):
    rec = db.new_record()
    rec["name"] = name
    rec["variety"] = body["variety"]
    rec["acres"] = util.q2(body["acres"])
    rec["planting_year"] = int(body["planting_year"])
    rec["irrigation_source_code"] = body["irrigation_source_code"]
    rec["water_sample_count"] = 0
    rec["water_geomean_mpn"] = None
    rec["water_status"] = "NO_SAMPLES"
    rec["last_sample_date"] = None
    rec["manual_quarantine_active"] = False
    rec["quarantined_by_user_id"] = None
    rec["quarantine_reason_code"] = None
    rec["food_safety_posture"] = "RESTRICTED"
    rec["_last_sample_date"] = None
    return rec


@bp.route("/blocks", methods=["POST"])
def create_block():
    V.authenticate((HM,))
    body = V.read_body()
    V.validate_body(BLOCK_FIELDS, body)
    name = body["name"]
    for other in db.blocks.values():
        if other["name"] == name:
            fail("ERR_DUPLICATE_RECORD", "A block with that name already exists.")
    rec = _new_block(body, name)
    db.blocks[rec["id"]] = rec
    return response.object_response(rec, 201)


@bp.route("/blocks/<block_id>", methods=["GET"])
def read_block(block_id):
    V.authenticate(ALL_READERS)
    return response.object_response(V.get_block(block_id))


@bp.route("/blocks", methods=["GET"])
def list_blocks():
    V.authenticate(ALL_READERS)
    rows = filter_args(
        db.all_of(db.blocks),
        {
            "variety": "variety",
            "food_safety_posture": "food_safety_posture",
            "water_status": "water_status",
        },
    )
    return response.paginate(rows)


@bp.route("/blocks/<block_id>/quarantine", methods=["POST"])
def quarantine_block(block_id):
    user_id, _ = V.authenticate((FSO,))
    block = V.get_block(block_id)
    body = V.read_body()
    V.check_shape([V.Field("quarantine_reason_code", "string")], body)
    if block["manual_quarantine_active"]:
        fail("ERR_INVALID_BLOCK_STATE", "The block is already under a manual hold.")
    cascade.quarantine_block(block, user_id, body["quarantine_reason_code"])
    return response.object_response(block)


@bp.route("/blocks/<block_id>/clear", methods=["POST"])
def clear_block(block_id):
    user_id, _ = V.authenticate((FSO,))
    block = V.get_block(block_id)
    if not block["manual_quarantine_active"]:
        fail("ERR_INVALID_BLOCK_STATE", "The block is not under a manual hold.")
    if block["water_status"] not in ("PROVISIONAL", "COMPLIANT"):
        fail(
            "ERR_INVALID_BLOCK_STATE",
            "A passing water sample must be on file before the hold is lifted.",
        )
    if user_id == block["quarantined_by_user_id"]:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The officer who imposed the hold may not lift it.",
        )
    cascade.clear_block(block)
    return response.object_response(block)


@bp.route("/blocks/<block_id>/traceability-summary", methods=["GET"])
def traceability_summary(block_id):
    V.authenticate((HM, FSO, PO, SM))
    block = V.get_block(block_id)
    return response.raw_object_response(calc.traceability_summary(block))


# ---------------------------------------------------------------------------
# the append-only water register
# ---------------------------------------------------------------------------
WATER_FIELDS = [
    V.Field("block_id", "string"),
    V.Field("sample_date", "date"),
    V.Field("generic_ecoli_mpn", "int", minimum=1, maximum=100000),
]


@bp.route("/water-tests", methods=["POST"])
def create_water_test():
    user_id, _ = V.authenticate((FSO,))
    body = V.read_body()
    V.validate_body(WATER_FIELDS, body)
    parsed = V.parse_temporal(WATER_FIELDS, body)
    block = V.get_block(body["block_id"])

    mpn = int(body["generic_ecoli_mpn"])
    rec = db.new_record(with_audit=False)
    rec["block_id"] = block["id"]
    rec["sample_date"] = body["sample_date"]
    rec["generic_ecoli_mpn"] = mpn
    rec["single_sample_exceedance"] = mpn > config.SINGLE_SAMPLE_MAX_MPN
    rec["resulting_water_status"] = None
    rec["recorded_by_user_id"] = user_id
    rec["_sample_date"] = parsed["sample_date"]
    db.water_tests[rec["id"]] = rec

    status = calc.recompute_water_status(block)
    if status == "FAILED" and not block["manual_quarantine_active"]:
        cascade.quarantine_block(
            block, user_id, config.REASON_SINGLE_SAMPLE_EXCEEDANCE
        )
    else:
        calc.recompute_posture(block)
        db.touch(block)
    rec["resulting_water_status"] = block["water_status"]
    return response.object_response(rec, 201)


@bp.route("/water-tests/<water_test_id>", methods=["GET"])
def read_water_test(water_test_id):
    V.authenticate((HM, FSO, SM))
    return response.object_response(V.get_water_test(water_test_id))


@bp.route("/water-tests", methods=["GET"])
def list_water_tests():
    V.authenticate((HM, FSO, SM))
    rows = sorted(
        db.water_tests.values(),
        key=lambda r: (r["_sample_date"], r["created_at"], r["_seq"]),
    )
    rows = filter_args(rows, {"block_id": "block_id"})
    return response.paginate(rows)


# ---------------------------------------------------------------------------
# the logical clock
# ---------------------------------------------------------------------------
CLOCK_FIELDS = [V.Field("current_utc", "instant")]


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    V.authenticate((HM,))
    body = V.read_body()
    V.check_shape(CLOCK_FIELDS, body)
    parsed = V.parse_temporal(CLOCK_FIELDS, body)
    db.set_clock(body["current_utc"], parsed["current_utc"])
    return response.raw_object_response({"current_utc": db.clock_raw()})
