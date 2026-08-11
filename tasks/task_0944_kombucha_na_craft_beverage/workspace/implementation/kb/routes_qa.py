"""The QA log, the corrective sign-off and ingredient consumption."""

from decimal import Decimal
from flask import Blueprint, g

from . import constants as C
from . import lookup
from .auth import authorize
from .envelope import list_response, object_response
from .errors import ApiError
from .routes_batches import readings_of
from .routes_recipes import require_id
from .store import base_record, collection_sorted, db, touch
from .util import add_days, dec, round2, whole_days_between
from .validate import (
    body_dict,
    field,
    pagination,
    paginate,
    parse_body,
    query_bool,
    query_enum,
)

bp = Blueprint("qa", __name__)

READ_ROLES = ("ProductionOperator", "QaManager", "ComplianceOfficer", "PlatformAdmin")
GAP_SECONDS = C.QA_READING_MAX_GAP_DAYS * 86400 + C.QA_MISSED_READING_GRACE_HOURS * 3600


def effective_ph_ceiling(recipe):
    return min(dec(recipe["target_ph_ceiling"]), C.F1_PH_CEILING)


@bp.post("/batches/<id>/qa-readings")
def append_qa_reading(id):
    authorize("ProductionOperator", "QaManager", "PlatformAdmin")
    batch = lookup.batch(id)
    payload = body_dict()
    data = parse_body(
        payload,
        [
            field("reading_type", "enum", required=True, members=C.READING_TYPES),
            field("reading_at", "datetime", required=True),
            field("ph", "number", required=True),
            field("temperature_c", "number", required=True),
            field("brix", "number", required=True),
            field("abv_pct", "number", required=True),
        ],
    )
    reading_at = data["reading_at"]
    if reading_at < batch["pitched_at"] or reading_at > db.clock:
        raise ApiError(
            "ERR_VALIDATION",
            "reading_at must lie between the batch's pitched_at and the logical clock.",
        )
    if batch["ferment_stage"] in ("PACKAGED", "DUMPED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "A PACKAGED or DUMPED batch may not receive a QA reading.",
        )

    recipe = db.recipes.get(batch["recipe_id"])
    ceiling = effective_ph_ceiling(recipe) if recipe else C.F1_PH_CEILING

    ph = round2(data["ph"])
    abv_pct = round2(data["abv_pct"])
    temperature_c = dec(data["temperature_c"])
    brix = dec(data["brix"])

    prior = [r for r in readings_of(batch["id"]) if r["reading_at"] <= reading_at]
    previous = prior[-1] if prior else None

    flag_reasons = []
    if previous is not None and ph > dec(previous["ph"]) + C.PH_REGRESSION_TOLERANCE:
        flag_reasons.append("PH_REGRESSION")
    if ph < C.PH_HARD_FLOOR:
        flag_reasons.append("PH_HARD_FLOOR")
    excursion = temperature_c < C.F1_TEMP_MIN_C or temperature_c > C.F1_TEMP_MAX_C
    if excursion:
        flag_reasons.append("TEMP_EXCURSION")
    if previous is not None:
        elapsed = (reading_at - previous["reading_at"]).total_seconds()
        if elapsed > GAP_SECONDS:
            flag_reasons.append("READING_GAP")

    day_index = whole_days_between(batch["pitched_at"], reading_at)

    reading = base_record(with_common=False)
    reading.update(
        {
            "batch_id": batch["id"],
            "reading_type": data["reading_type"],
            "reading_at": reading_at,
            "day_index": day_index,
            "ph": ph,
            "temperature_c": temperature_c,
            "brix": brix,
            "abv_pct": abv_pct,
            "flagged": len(flag_reasons) > 0,
            "flag_reasons": flag_reasons,
            "recorded_by_user_id": g.user_id,
        }
    )
    db.qa_readings[reading["id"]] = reading

    log = readings_of(batch["id"])
    batch["flagged_reading_count"] = sum(1 for r in log if r["flagged"])
    batch["temp_excursion_count"] = sum(
        1
        for r in log
        if dec(r["temperature_c"]) < C.F1_TEMP_MIN_C
        or dec(r["temperature_c"]) > C.F1_TEMP_MAX_C
    )

    # the pH-target stamp is independent of `flagged`
    if (
        batch["ph_target_hit_day_index"] is None
        and ph <= ceiling
        and C.F1_PH_WINDOW_MIN_DAYS <= day_index <= C.F1_PH_WINDOW_MAX_DAYS
    ):
        batch["ph_target_hit_day_index"] = day_index

    hard_fail = (
        ph < C.PH_HARD_FLOOR
        or (
            day_index > C.F1_PH_WINDOW_MAX_DAYS
            and batch["ph_target_hit_day_index"] is None
        )
        or (
            excursion
            and int(batch["temp_excursion_count"]) > C.TEMP_EXCURSION_FLAG_LIMIT
        )
    )

    if reading["flagged"]:
        batch["last_flagged_reading_by_user_id"] = g.user_id

    if hard_fail:
        if batch["qa_disposition"] in ("PENDING", "CONFORMING", "AT_RISK"):
            batch["qa_disposition"] = "NONCONFORMING"
    elif reading["flagged"]:
        if batch["qa_disposition"] in ("PENDING", "CONFORMING", "AT_RISK"):
            batch["qa_disposition"] = "AT_RISK"
    else:
        if (
            batch["qa_disposition"] == "PENDING"
            and int(batch["flagged_reading_count"]) == 0
            and ph <= ceiling
            and C.F1_PH_WINDOW_MIN_DAYS <= day_index <= C.F1_PH_WINDOW_MAX_DAYS
        ):
            batch["qa_disposition"] = "CONFORMING"

    packaging_log = [r for r in log if r["reading_type"] == "PACKAGING"]
    if packaging_log:
        batch["packaging_abv_pct"] = round2(packaging_log[-1]["abv_pct"])

    touch(batch)
    return object_response(reading, 201)


@bp.get("/batches/<id>/qa-readings")
def list_qa_readings(id):
    authorize(*READ_ROLES)
    batch = lookup.batch(id)
    reading_type = query_enum("reading_type", C.READING_TYPES)
    limit, offset = pagination()
    rows = readings_of(batch["id"], reading_type)
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/batches/<id>/qa-signoff")
def qa_signoff(id):
    authorize("QaManager", "PlatformAdmin")
    batch = lookup.batch(id)
    payload = body_dict()
    parse_body(payload, [field("note", "string")])

    if batch["qa_disposition"] != "AT_RISK":
        raise ApiError(
            "ERR_INVALID_STATE", "Only an AT_RISK batch may take a corrective sign-off."
        )
    log = readings_of(batch["id"])
    if log and log[-1]["flagged"]:
        raise ApiError(
            "ERR_INVALID_STATE",
            "The most recent QA reading is still flagged.",
        )
    if int(batch["qa_signoff_count"]) != 0:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The corrective sign-off has already been spent on this batch.",
        )
    if g.user_id == batch["last_flagged_reading_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The signer may not be the operator who recorded the last flagged reading.",
        )

    batch["qa_disposition"] = "CONFORMING"
    batch["qa_signoff_count"] = 1
    touch(batch)
    return object_response(batch)


@bp.post("/batches/<id>/ingredient-uses")
def record_ingredient_use(id):
    authorize("ProductionOperator", "PlatformAdmin")
    batch = lookup.batch(id)
    payload = body_dict()
    lot = lookup.ingredient_lot(require_id(payload, "ingredient_lot_id"))
    data = parse_body(
        payload,
        [
            field("ingredient_lot_id", "string", required=True),
            field("quantity_used", "number", required=True, positive=True),
        ],
    )

    if lot["status"] == "EXPIRED":
        raise ApiError(
            "ERR_INGREDIENT_EXPIRED", "The ingredient lot has already expired."
        )
    if lot["status"] not in ("AVAILABLE", "PARTIALLY_CONSUMED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only an AVAILABLE or PARTIALLY_CONSUMED lot may be consumed.",
        )
    if lot["expiry_date"] is None or lot["expiry_date"] <= add_days(
        db.clock, C.INGREDIENT_EXPIRY_BUFFER_DAYS
    ):
        raise ApiError(
            "ERR_INGREDIENT_EXPIRED",
            "The lot must expire strictly after the clock plus %d days."
            % C.INGREDIENT_EXPIRY_BUFFER_DAYS,
        )

    quantity = round2(data["quantity_used"])
    if quantity > dec(lot["quantity_available"]):
        raise ApiError(
            "ERR_VALIDATION", "quantity_used exceeds the lot's quantity_available."
        )

    record = base_record()
    record.update(
        {
            "batch_id": batch["id"],
            "ingredient_lot_id": lot["id"],
            "quantity_used": quantity,
            "voided": False,
            "voided_at": None,
        }
    )
    db.batch_ingredient_uses[record["id"]] = record

    lot["quantity_consumed"] = round2(dec(lot["quantity_consumed"]) + quantity)
    lot["quantity_available"] = round2(
        dec(lot["quantity_received"]) - dec(lot["quantity_consumed"])
    )
    lot["status"] = (
        "CONSUMED" if dec(lot["quantity_available"]) == Decimal("0.00") else "PARTIALLY_CONSUMED"
    )
    touch(lot)
    return object_response(record, 201)


@bp.get("/batches/<id>/ingredient-uses")
def list_batch_ingredient_uses(id):
    authorize(*READ_ROLES)
    batch = lookup.batch(id)
    voided = query_bool("voided")
    limit, offset = pagination()
    rows = collection_sorted(
        db.batch_ingredient_uses,
        lambda u: u["batch_id"] == batch["id"]
        and (voided is None or bool(u["voided"]) == voided),
    )
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)
