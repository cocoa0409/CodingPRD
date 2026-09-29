"""Conditioning lines, the stage ladder, the mass ledger, reversal and
carryover minting (PRD 3.5, 3.6, 3.8)."""

import datetime

from flask import Blueprint

import calc
from common import (get_contract, get_line, get_lot, get_run, get_treatment_product,
                   paginate, public, public_list, rows_where)
from envelope import list_response, object_response
from errors import ApiError
from services import new_seed_lot, recompute_lot_dockage
from store import db, new_record, touch
from validation import (STAGES, Field, authenticate, bad_request, json_body,
                        parse_fields, parse_pagination, query_enum, query_integer,
                        query_string)

bp = Blueprint("conditioning", __name__)

LINE_STATUSES = ("AVAILABLE", "OUT_OF_SERVICE")
RUN_STATUSES = ("PLANNED", "COMPLETED", "ABORTED", "REVERSED")
CONDITIONING_STATUSES = ("RAW", "CLEANED", "SIZED", "TREATED", "BAGGED")
CERTIFICATION_STATUSES = ("UNSAMPLED", "SAMPLED", "PASSED", "FAILED", "TAGGED",
                          "RETEST_DUE")

STAGE_RESULT = {"CLEANING": "CLEANED", "SIZING": "SIZED", "TREATING": "TREATED",
                "BAGGING": "BAGGED"}


# ---- conditioning lines -------------------------------------------------
LINE_FIELDS = [
    Field("line_code", "string"),
    Field("cleanout_minutes_required", "integer", minimum=0),
    Field("capacity_kg_per_hour", "number", exclusive_min=0),
    Field("status", "enum", members=LINE_STATUSES, required=False, default="AVAILABLE"),
]


@bp.post("/seed-ops/conditioning-lines")
def create_line():
    authenticate(("ProgramAdmin", "ConditioningManager"))
    data = parse_fields(json_body(), LINE_FIELDS)
    for existing in db.conditioning_lines.values():
        if existing["line_code"] == data["line_code"]:
            bad_request("line_code must be unique across the plant.")
    rec = new_record(True)
    rec["line_code"] = data["line_code"]
    rec["cleanout_minutes_required"] = data["cleanout_minutes_required"]
    rec["capacity_kg_per_hour"] = data["capacity_kg_per_hour"]
    rec["status"] = data["status"]
    rec["last_cleanout_variety_id"] = None
    rec["last_run_end_utc"] = None
    rec["_last_run_end"] = None
    db.conditioning_lines[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.get("/seed-ops/conditioning-lines/<conditioning_line_id>")
def read_line(conditioning_line_id):
    authenticate(("ProgramAdmin", "ConditioningManager"))
    return object_response(public(get_line(conditioning_line_id)))


@bp.get("/seed-ops/conditioning-lines")
def list_lines():
    authenticate(("ProgramAdmin", "ConditioningManager"))
    limit, offset = parse_pagination()
    rows = rows_where(
        db.conditioning_lines,
        last_cleanout_variety_id=query_string("last_cleanout_variety_id"),
        status=query_enum("status", LINE_STATUSES),
    )
    page, total = paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)


# ---- run planning -------------------------------------------------------
RUN_FIELDS = [
    Field("seed_lot_id", "string"),
    Field("conditioning_line_id", "string"),
    Field("stage", "enum", members=STAGES),
    Field("window_start", "datetime"),
    Field("window_end", "datetime"),
    Field("input_kg", "number", exclusive_min=0),
    Field("treatment_product_id", "string", required=False),
    Field("treatment_rate_g_per_100kg", "number", required=False),
    Field("label_text", "string", required=False),
]


def _stage_allowed(lot, variety, stage):
    current = lot["conditioning_status"]
    if current == "RAW":
        return stage == "CLEANING"
    if current == "CLEANED":
        return stage == "SIZING"
    if current == "SIZED":
        if stage == "TREATING":
            return True
        return stage == "BAGGING" and not variety["treatment_required"]
    if current == "TREATED":
        return stage == "BAGGING"
    return False


def _check_treatment(data, lot, variety):
    stage = data["stage"]
    supplied = [data["treatment_product_id"], data["treatment_rate_g_per_100kg"],
                data["label_text"]]
    if stage == "TREATING":
        if any(v is None for v in supplied):
            raise ApiError("ERR_TREATMENT_FIELDS_NOT_ALLOWED")
    else:
        if any(v is not None for v in supplied):
            raise ApiError("ERR_TREATMENT_FIELDS_NOT_ALLOWED")
        return None

    product = db.treatment_products[data["treatment_product_id"]]
    if variety["crop_kind"] not in (product["allowed_crop_kinds"] or []):
        raise ApiError("ERR_TREATMENT_CROP_NOT_LABELED")
    if calc.dec(data["treatment_rate_g_per_100kg"]) > calc.dec(product["max_rate_g_per_100kg"]):
        raise ApiError("ERR_TREATMENT_RATE_EXCEEDS_LABEL")

    text = data["label_text"]
    if product["epa_registration_number"] not in text:
        raise ApiError("ERR_TREATMENT_LABEL_INCOMPLETE")
    if product["requires_dye"] and "DYED" not in text:
        raise ApiError("ERR_TREATMENT_LABEL_INCOMPLETE")
    if product["restricted_use"] and product["label_signal_word"] not in text:
        raise ApiError("ERR_TREATMENT_LABEL_INCOMPLETE")
    return product


@bp.post("/seed-ops/conditioning-runs")
def plan_run():
    authenticate(("ConditioningManager",))
    data = parse_fields(json_body(), RUN_FIELDS)
    lot = get_lot(data["seed_lot_id"])
    line = get_line(data["conditioning_line_id"])
    if data["treatment_product_id"] is not None:
        get_treatment_product(data["treatment_product_id"])

    if lot["conditioning_status"] == "BAGGED":
        raise ApiError("ERR_INVALID_LOT_STATE")

    variety = db.varieties[lot["variety_id"]]
    _check_treatment(data, lot, variety)

    if not _stage_allowed(lot, variety, data["stage"]):
        raise ApiError("ERR_STAGE_OUT_OF_ORDER")

    if calc.round_half_up(data["input_kg"], 2) != calc.round_half_up(lot["current_kg"], 2):
        raise ApiError("ERR_INPUT_MASS_MISMATCH")

    if lot["certification_status"] == "TAGGED":
        raise ApiError("ERR_LOT_TAGGED_IMMUTABLE")

    if not data["window_start"] < data["window_end"]:
        raise ApiError("ERR_INVALID_WINDOW")

    for other in db.conditioning_runs.values():
        if other["conditioning_line_id"] != line["id"]:
            continue
        if other["status"] not in ("PLANNED", "COMPLETED"):
            continue
        if (data["window_start"] < other["_window_end"]
                and other["_window_start"] < data["window_end"]):
            raise ApiError("ERR_LINE_WINDOW_CONFLICT")

    if line["last_cleanout_variety_id"] == lot["variety_id"]:
        buffer_minutes = 0
    else:
        buffer_minutes = line["cleanout_minutes_required"]
    if (line["last_cleanout_variety_id"] is not None
            and line["last_cleanout_variety_id"] != lot["variety_id"]
            and line["_last_run_end"] is not None):
        earliest = line["_last_run_end"] + datetime.timedelta(
            minutes=line["cleanout_minutes_required"])
        if data["window_start"] < earliest:
            raise ApiError("ERR_LINE_CLEANOUT_BUFFER_VIOLATION")

    rec = new_record(True)
    rec["seed_lot_id"] = lot["id"]
    rec["conditioning_line_id"] = line["id"]
    rec["stage"] = data["stage"]
    rec["window_start"] = data["window_start__raw"]
    rec["window_end"] = data["window_end__raw"]
    rec["input_kg"] = calc.round_half_up(data["input_kg"], 2)
    rec["output_kg"] = None
    rec["shrink_kg"] = None
    rec["bag_count"] = None
    rec["status"] = "PLANNED"
    rec["treatment_product_id"] = data["treatment_product_id"]
    rec["treatment_rate_g_per_100kg"] = data["treatment_rate_g_per_100kg"]
    rec["label_text"] = data["label_text"]
    rec["cleanout_buffer_applied_minutes"] = buffer_minutes
    rec["reversal_reason"] = None
    rec["_window_start"] = data["window_start"]
    rec["_window_end"] = data["window_end"]
    rec["_prev_conditioning_status"] = None
    db.conditioning_runs[rec["id"]] = rec
    return object_response(public(rec), 201)


# ---- completion ---------------------------------------------------------
@bp.post("/seed-ops/conditioning-runs/<conditioning_run_id>/complete")
def complete_run(conditioning_run_id):
    authenticate(("ConditioningManager",))
    data = parse_fields(json_body(), [Field("output_kg", "number")])
    run = get_run(conditioning_run_id)
    if run["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_RUN_STATE")

    output = calc.dec(data["output_kg"])
    if output < 0 or output > calc.dec(run["input_kg"]):
        raise ApiError("ERR_OUTPUT_EXCEEDS_INPUT")
    if run["_window_end"] > db.now():
        raise ApiError("ERR_RUN_WINDOW_NOT_ELAPSED")

    lot = db.seed_lots[run["seed_lot_id"]]
    line = db.conditioning_lines[run["conditioning_line_id"]]
    shrink = calc.dec(run["input_kg"]) - output

    run["status"] = "COMPLETED"
    run["output_kg"] = calc.round_half_up(output, 2)
    run["shrink_kg"] = calc.round_half_up(shrink, 2)
    run["_prev_conditioning_status"] = lot["conditioning_status"]

    lot["current_kg"] = calc.round_half_up(output, 2)
    lot["cumulative_shrink_kg"] = calc.round_half_up(
        calc.dec(lot["cumulative_shrink_kg"]) + shrink, 2)
    recompute_lot_dockage(lot)
    lot["conditioning_status"] = STAGE_RESULT[run["stage"]]

    if run["stage"] == "BAGGING":
        bags = calc.bag_count_for(output, lot["bag_size_kg"])
        lot["bag_count"] = bags
        run["bag_count"] = bags
        lot["final_clean_units"] = calc.final_bagged_basis(output)
    touch(run)
    touch(lot)

    line["last_cleanout_variety_id"] = lot["variety_id"]
    line["last_run_end_utc"] = run["window_end"]
    line["_last_run_end"] = run["_window_end"]
    touch(line)
    return object_response(public(run))


# ---- reversal -----------------------------------------------------------
@bp.post("/seed-ops/conditioning-runs/<conditioning_run_id>/reversal")
def reverse_run(conditioning_run_id):
    authenticate(("ConditioningManager",))
    data = parse_fields(json_body(), [Field("reversal_reason", "string")])
    run = get_run(conditioning_run_id)
    if run["status"] not in ("PLANNED", "COMPLETED"):
        raise ApiError("ERR_INVALID_RUN_STATE")

    lot = db.seed_lots[run["seed_lot_id"]]

    if run["status"] == "COMPLETED":
        completed = [r for r in db.conditioning_runs.values()
                     if r["seed_lot_id"] == lot["id"] and r["status"] == "COMPLETED"]
        completed.sort(key=lambda r: (r["_window_end"], r["created_at"], r["_seq"]),
                       reverse=True)
        if not completed or completed[0]["id"] != run["id"]:
            raise ApiError("ERR_RUN_NOT_LATEST")

    if lot["certification_status"] == "TAGGED":
        raise ApiError("ERR_LOT_TAGGED_IMMUTABLE")

    if run["status"] == "PLANNED":
        run["status"] = "ABORTED"
        run["reversal_reason"] = data["reversal_reason"]
        touch(run)
        return object_response(public(run))

    lot["current_kg"] = calc.round_half_up(run["input_kg"], 2)
    lot["cumulative_shrink_kg"] = calc.round_half_up(
        calc.dec(lot["cumulative_shrink_kg"]) - calc.dec(run["shrink_kg"]), 2)
    recompute_lot_dockage(lot)
    if run["_prev_conditioning_status"] is not None:
        lot["conditioning_status"] = run["_prev_conditioning_status"]
    if run["stage"] == "BAGGING":
        lot["bag_count"] = 0
        lot["final_clean_units"] = None

    run["status"] = "REVERSED"
    run["reversal_reason"] = data["reversal_reason"]
    touch(run)
    touch(lot)
    return object_response(public(run))


# ---- carryover ----------------------------------------------------------
CARRYOVER_FIELDS = [
    Field("expected_seed_lot_version", "integer"),
    Field("next_season_year", "integer", minimum=2000, maximum=2100),
]


@bp.post("/seed-ops/seed-lots/<seed_lot_id>/carryover")
def mint_carryover(seed_lot_id):
    authenticate(("ConditioningManager",))
    data = parse_fields(json_body(), CARRYOVER_FIELDS)
    parent = get_lot(seed_lot_id)

    if parent["certification_status"] != "TAGGED":
        raise ApiError("ERR_INVALID_LOT_STATE")
    if data["expected_seed_lot_version"] != parent["version"]:
        raise ApiError("ERR_STALE_LOT_VERSION")

    valid_until = parent.get("_germination_valid_until")
    if valid_until is None or db.now() <= valid_until:
        raise ApiError("ERR_RETEST_NOT_DUE")

    variety = db.varieties[parent["variety_id"]]
    if parent["carryover_generation"] + 1 > variety["max_carryover_generations"]:
        raise ApiError("ERR_CARRYOVER_LIMIT_EXCEEDED")

    contract = db.production_contracts[parent["production_contract_id"]]
    successor = new_seed_lot(
        contract,
        data["next_season_year"],
        parent["variety_id"],
        parent["current_kg"],
        parent["bag_size_kg"],
        parent["intake_moisture_pct"],
        parent["provisional_clean_units"],
        conditioning_status="BAGGED",
        certification_status="RETEST_DUE",
        parent_seed_lot_id=parent["id"],
        carryover_generation=parent["carryover_generation"] + 1,
        bag_count=parent["bag_count"],
        final_clean_units=parent["final_clean_units"],
    )
    touch(parent)
    return object_response(public(successor), 201)


# ---- reads --------------------------------------------------------------
@bp.get("/seed-ops/conditioning-runs/<conditioning_run_id>")
def read_run(conditioning_run_id):
    authenticate(("ProgramAdmin", "ConditioningManager", "CertificationAgency"))
    return object_response(public(get_run(conditioning_run_id)))


@bp.get("/seed-ops/conditioning-runs")
def list_runs():
    authenticate(("ProgramAdmin", "ConditioningManager", "CertificationAgency"))
    limit, offset = parse_pagination()
    rows = rows_where(
        db.conditioning_runs,
        seed_lot_id=query_string("seed_lot_id"),
        conditioning_line_id=query_string("conditioning_line_id"),
        treatment_product_id=query_string("treatment_product_id"),
        stage=query_enum("stage", STAGES),
        status=query_enum("status", RUN_STATUSES),
    )
    page, total = paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)


@bp.get("/seed-ops/seed-lots/<seed_lot_id>")
def read_lot(seed_lot_id):
    authenticate(("ProgramAdmin", "ConditioningManager", "CertificationAgency",
                  "SettlementAccountant", "Grower"))
    return object_response(public(get_lot(seed_lot_id)))


@bp.get("/seed-ops/seed-lots")
def list_lots():
    authenticate(("ProgramAdmin", "ConditioningManager", "CertificationAgency",
                  "SettlementAccountant", "Grower"))
    limit, offset = parse_pagination()
    rows = rows_where(
        db.seed_lots,
        variety_id=query_string("variety_id"),
        production_contract_id=query_string("production_contract_id"),
        parent_seed_lot_id=query_string("parent_seed_lot_id"),
        conditioning_status=query_enum("conditioning_status", CONDITIONING_STATUSES),
        certification_status=query_enum("certification_status", CERTIFICATION_STATUSES),
        season_year=query_integer("season_year"),
    )
    page, total = paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)
