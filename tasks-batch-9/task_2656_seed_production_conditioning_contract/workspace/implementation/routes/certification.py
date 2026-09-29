"""Agency sampling, laboratory verdicts, quality pricing and tag issuance
(PRD 3.7)."""

import datetime

from flask import Blueprint

import calc
from common import (get_lot, get_sample, get_tag, paginate, public, public_list,
                    rows_where)
from envelope import iso_ms, list_response, object_response
from errors import ApiError
from services import (failed_result_cascade, recompute_certified_units_total,
                      recompute_tagged_bag_count)
from store import db, new_record, touch
from validation import (SAMPLE_KINDS, SEED_CLASSES, Field, authenticate, json_body,
                        parse_fields, parse_pagination, query_enum, query_string)

bp = Blueprint("certification", __name__)

SAMPLE_RESULTS = ("PENDING", "PASS", "FAIL")
TAG_STATUSES = ("ISSUED", "VOIDED")
MAX_WEED_SEEDS_PER_KG = 30


SAMPLE_FIELDS = [
    Field("seed_lot_id", "string"),
    Field("sample_kind", "enum", members=SAMPLE_KINDS),
    Field("sampled_on", "date"),
]


@bp.post("/seed-ops/lot-samples")
def draw_sample():
    user_id, _role = authenticate(("CertificationAgency",))
    data = parse_fields(json_body(), SAMPLE_FIELDS)
    lot = get_lot(data["seed_lot_id"])

    if lot["conditioning_status"] != "BAGGED":
        raise ApiError("ERR_INVALID_LOT_STATE")
    if data["sample_kind"] == "INITIAL":
        if lot["certification_status"] != "UNSAMPLED":
            raise ApiError("ERR_INVALID_LOT_STATE")
    else:
        if lot["certification_status"] not in ("RETEST_DUE", "TAGGED"):
            raise ApiError("ERR_INVALID_LOT_STATE")
    if data["sampled_on"] > db.today():
        raise ApiError("ERR_DATE_IN_FUTURE")

    rec = new_record(True)
    rec["seed_lot_id"] = lot["id"]
    rec["sample_kind"] = data["sample_kind"]
    rec["sampled_on"] = data["sampled_on__raw"]
    rec["sampler_user_id"] = user_id
    rec["germination_pct"] = None
    rec["purity_pct"] = None
    rec["inert_pct"] = None
    rec["weed_seed_count_per_kg"] = None
    rec["tested_at"] = None
    rec["result"] = "PENDING"
    rec["germination_valid_until"] = None
    db.lot_samples[rec["id"]] = rec

    lot["certification_status"] = "SAMPLED"
    touch(lot)
    return object_response(public(rec), 201)


RESULT_FIELDS = [
    Field("germination_pct", "number", minimum=0, maximum=100),
    Field("purity_pct", "number", minimum=0, maximum=100),
    Field("inert_pct", "number", minimum=0, maximum=100),
    Field("weed_seed_count_per_kg", "integer", minimum=0),
    Field("tested_at", "datetime"),
]


@bp.post("/seed-ops/lot-samples/<lot_sample_id>/results")
def post_results(lot_sample_id):
    authenticate(("CertificationAgency",))
    data = parse_fields(json_body(), RESULT_FIELDS)
    sample = get_sample(lot_sample_id)

    if sample["result"] != "PENDING":
        raise ApiError("ERR_SAMPLE_ALREADY_RESULTED")
    if calc.dec(data["purity_pct"]) + calc.dec(data["inert_pct"]) > calc.dec(100):
        raise ApiError("ERR_COMPONENT_PCT_SUM_INVALID")
    if data["tested_at"] > db.now():
        raise ApiError("ERR_DATE_IN_FUTURE")

    lot = db.seed_lots[sample["seed_lot_id"]]
    variety = db.varieties[lot["variety_id"]]
    contract = db.production_contracts[lot["production_contract_id"]]

    passed = (calc.dec(data["germination_pct"]) >= calc.dec(variety["germination_min_pct"])
              and calc.dec(data["purity_pct"]) >= calc.dec(variety["purity_min_pct"])
              and data["weed_seed_count_per_kg"] <= MAX_WEED_SEEDS_PER_KG)

    sample["germination_pct"] = data["germination_pct"]
    sample["purity_pct"] = data["purity_pct"]
    sample["inert_pct"] = data["inert_pct"]
    sample["weed_seed_count_per_kg"] = data["weed_seed_count_per_kg"]
    sample["tested_at"] = data["tested_at__raw"]

    lot["germination_pct"] = data["germination_pct"]
    lot["purity_pct"] = data["purity_pct"]
    lot["weed_seed_count_per_kg"] = data["weed_seed_count_per_kg"]

    if passed:
        valid_until = data["tested_at"] + datetime.timedelta(
            days=variety["germ_validity_days"])
        sample["result"] = "PASS"
        sample["germination_valid_until"] = iso_ms(valid_until)
        lot["germination_valid_until"] = iso_ms(valid_until)
        lot["_germination_valid_until"] = valid_until
        lot["certification_status"] = "PASSED"
        lot["adjusted_price_per_unit_cents"] = calc.adjusted_price_per_unit(
            data["germination_pct"], data["purity_pct"],
            data["weed_seed_count_per_kg"], lot["intake_moisture_pct"], variety,
            contract["base_price_per_unit_cents"])
        touch(sample)
        touch(lot)
    else:
        sample["result"] = "FAIL"
        sample["germination_valid_until"] = None
        touch(sample)
        failed_result_cascade(sample, lot)
    return object_response(public(sample))


TAG_FIELDS = [
    Field("seed_lot_id", "string"),
    Field("lot_sample_id", "string"),
    Field("tag_class", "enum", members=SEED_CLASSES),
    Field("bag_count", "integer", exclusive_min=0),
]


@bp.post("/seed-ops/certification-tags")
def issue_tag():
    authenticate(("CertificationAgency",))
    data = parse_fields(json_body(), TAG_FIELDS)
    lot = get_lot(data["seed_lot_id"])
    sample = get_sample(data["lot_sample_id"])

    if sample["seed_lot_id"] != lot["id"] or sample["result"] != "PASS":
        raise ApiError("ERR_SAMPLE_LOT_MISMATCH")
    if lot["conditioning_status"] != "BAGGED" or lot["certification_status"] != "PASSED":
        raise ApiError("ERR_LOT_NOT_TAG_ELIGIBLE")
    if data["bag_count"] > lot["bag_count"] - lot["tagged_bag_count"]:
        raise ApiError("ERR_TAG_BAG_COUNT_EXCEEDS_LOT")

    variety = db.varieties[lot["variety_id"]]
    if calc.CLASS_RANK[data["tag_class"]] > calc.CLASS_RANK[variety["max_seed_class"]]:
        raise ApiError("ERR_TAG_CLASS_EXCEEDS_VARIETY")

    valid_until = lot.get("_germination_valid_until")
    if valid_until is None or db.now() > valid_until:
        raise ApiError("ERR_GERMINATION_VALIDITY_EXPIRED")

    rec = new_record(True)
    rec["seed_lot_id"] = lot["id"]
    rec["lot_sample_id"] = sample["id"]
    rec["tag_serial"] = "TAG-%d-%06d" % (lot["season_year"], db.next_tag_seq())
    rec["tag_class"] = data["tag_class"]
    rec["bag_count"] = data["bag_count"]
    rec["issued_at"] = iso_ms(db.now())
    rec["status"] = "ISSUED"
    rec["void_reason"] = None
    db.certification_tags[rec["id"]] = rec

    recompute_tagged_bag_count(lot)
    lot["certification_status"] = "TAGGED"
    touch(lot)

    contract = db.production_contracts[lot["production_contract_id"]]
    recompute_certified_units_total(contract)
    touch(contract)
    return object_response(public(rec), 201)


@bp.post("/seed-ops/certification-tags/<certification_tag_id>/void")
def void_tag(certification_tag_id):
    authenticate(("CertificationAgency",))
    data = parse_fields(json_body(), [Field("void_reason", "string")])
    tag = get_tag(certification_tag_id)
    if tag["status"] != "ISSUED":
        raise ApiError("ERR_TAG_ALREADY_VOIDED")

    tag["status"] = "VOIDED"
    tag["void_reason"] = data["void_reason"]
    touch(tag)

    lot = db.seed_lots[tag["seed_lot_id"]]
    recompute_tagged_bag_count(lot)
    if lot["tagged_bag_count"] == 0 and lot["certification_status"] == "TAGGED":
        lot["certification_status"] = "PASSED"
        contract = db.production_contracts.get(lot["production_contract_id"])
        touch(lot)
        if contract is not None:
            recompute_certified_units_total(contract)
    else:
        touch(lot)
    return object_response(public(tag))


@bp.get("/seed-ops/lot-samples/<lot_sample_id>")
def read_sample(lot_sample_id):
    authenticate(("ProgramAdmin", "ConditioningManager", "CertificationAgency", "Grower"))
    return object_response(public(get_sample(lot_sample_id)))


@bp.get("/seed-ops/lot-samples")
def list_samples():
    authenticate(("ProgramAdmin", "ConditioningManager", "CertificationAgency", "Grower"))
    limit, offset = parse_pagination()
    rows = rows_where(
        db.lot_samples,
        seed_lot_id=query_string("seed_lot_id"),
        sample_kind=query_enum("sample_kind", SAMPLE_KINDS),
        result=query_enum("result", SAMPLE_RESULTS),
    )
    page, total = paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)


@bp.get("/seed-ops/certification-tags/<certification_tag_id>")
def read_tag(certification_tag_id):
    authenticate(("ProgramAdmin", "ConditioningManager", "CertificationAgency", "Grower"))
    return object_response(public(get_tag(certification_tag_id)))


@bp.get("/seed-ops/certification-tags")
def list_tags():
    authenticate(("ProgramAdmin", "ConditioningManager", "CertificationAgency", "Grower"))
    limit, offset = parse_pagination()
    rows = rows_where(
        db.certification_tags,
        seed_lot_id=query_string("seed_lot_id"),
        lot_sample_id=query_string("lot_sample_id"),
        status=query_enum("status", TAG_STATUSES),
    )
    page, total = paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)
