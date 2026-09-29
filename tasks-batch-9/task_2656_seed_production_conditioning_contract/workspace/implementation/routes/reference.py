"""Reference data: varieties, treatment products, growers, fields, history,
plus the read-through eligibility assessment (PRD 3.1, 3.2)."""

from flask import Blueprint

import calc
from common import (get_field, get_grower, get_history_record, get_variety,
                    paginate, public, public_list, rows_where)
from envelope import list_response, object_response
from errors import ApiError
from store import db, new_record, touch
from validation import (CONTRACT_CLASSES, CROP_KINDS, SEED_CLASSES, SIGNAL_WORDS,
                        Field, authenticate, bad_request, json_body, parse_fields,
                        parse_pagination, query_boolean, query_enum, query_integer,
                        query_string)

bp = Blueprint("reference", __name__)

ALL_ROLES = ("ProgramAdmin", "FieldOfficer", "Grower", "ConditioningManager",
             "CertificationAgency", "SettlementAccountant")


# ---- varieties -----------------------------------------------------------
VARIETY_FIELDS = [
    Field("crop_kind", "enum", members=CROP_KINDS),
    Field("variety_name", "string"),
    Field("max_seed_class", "enum", members=SEED_CLASSES),
    Field("isolation_min_m", "number"),
    Field("restricted_prior_crop_kinds", "enum_array", members=CROP_KINDS),
    Field("restricted_prior_crop_years", "integer", minimum=1),
    Field("germination_min_pct", "number"),
    Field("purity_min_pct", "number"),
    Field("max_off_type_per_10000", "number"),
    Field("max_restricted_weed_per_10000", "number"),
    Field("max_disease_incidence_pct", "number"),
    Field("max_rogueing_rounds", "integer", required=False, default=2),
    Field("estimated_conditioning_shrink_pct", "number"),
    Field("germ_validity_days", "integer"),
    Field("max_carryover_generations", "integer", required=False, default=2),
    Field("treatment_required", "boolean", required=False, default=False),
]


@bp.post("/seed-ops/varieties")
def create_variety():
    authenticate(("ProgramAdmin",))
    data = parse_fields(json_body(), VARIETY_FIELDS)
    rec = new_record(False)
    for f in VARIETY_FIELDS:
        rec[f.name] = data[f.name]
    db.varieties[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.get("/seed-ops/varieties/<variety_id>")
def read_variety(variety_id):
    authenticate(ALL_ROLES)
    return object_response(public(get_variety(variety_id)))


@bp.get("/seed-ops/varieties")
def list_varieties():
    authenticate(ALL_ROLES)
    limit, offset = parse_pagination()
    rows = rows_where(db.varieties, crop_kind=query_enum("crop_kind", CROP_KINDS))
    page, total = paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)


# ---- treatment products -------------------------------------------------
PRODUCT_FIELDS = [
    Field("product_code", "string"),
    Field("epa_registration_number", "string"),
    Field("allowed_crop_kinds", "enum_array", members=CROP_KINDS),
    Field("max_rate_g_per_100kg", "number"),
    Field("requires_dye", "boolean", required=False, default=False),
    Field("restricted_use", "boolean", required=False, default=False),
    Field("label_signal_word", "enum", members=SIGNAL_WORDS),
]


@bp.post("/seed-ops/treatment-products")
def create_treatment_product():
    authenticate(("ProgramAdmin",))
    data = parse_fields(json_body(), PRODUCT_FIELDS)
    for existing in db.treatment_products.values():
        if existing["product_code"] == data["product_code"]:
            bad_request("product_code must be unique across the registry.")
    rec = new_record(False)
    for f in PRODUCT_FIELDS:
        rec[f.name] = data[f.name]
    db.treatment_products[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.get("/seed-ops/treatment-products/<treatment_product_id>")
def read_treatment_product(treatment_product_id):
    from common import get_treatment_product
    authenticate(("ProgramAdmin", "ConditioningManager", "CertificationAgency"))
    return object_response(public(get_treatment_product(treatment_product_id)))


@bp.get("/seed-ops/treatment-products")
def list_treatment_products():
    authenticate(("ProgramAdmin", "ConditioningManager", "CertificationAgency"))
    limit, offset = parse_pagination()
    rows = rows_where(db.treatment_products, restricted_use=query_boolean("restricted_use"))
    page, total = paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)


# ---- growers -------------------------------------------------------------
GROWER_FIELDS = [
    Field("grower_name", "string"),
    Field("region_code", "string"),
    Field("contact_email", "string"),
]


@bp.post("/seed-ops/growers")
def create_grower():
    authenticate(("ProgramAdmin",))
    data = parse_fields(json_body(), GROWER_FIELDS)
    rec = new_record(True)
    rec["grower_name"] = data["grower_name"]
    rec["region_code"] = data["region_code"]
    rec["contact_email"] = data["contact_email"]
    rec["status"] = "GOOD_STANDING"
    rec["compliance_flag_count"] = 0
    db.growers[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.get("/seed-ops/growers/<grower_id>")
def read_grower(grower_id):
    authenticate(("ProgramAdmin", "FieldOfficer", "SettlementAccountant", "Grower"))
    return object_response(public(get_grower(grower_id)))


@bp.get("/seed-ops/growers")
def list_growers():
    authenticate(("ProgramAdmin", "FieldOfficer", "SettlementAccountant"))
    limit, offset = parse_pagination()
    rows = rows_where(
        db.growers,
        status=query_enum("status", ("GOOD_STANDING", "WATCH", "SUSPENDED")),
        region_code=query_string("region_code"),
    )
    page, total = paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)


# ---- production fields --------------------------------------------------
FIELD_FIELDS = [
    Field("grower_id", "string"),
    Field("field_code", "string"),
    Field("acres", "number"),
    Field("isolation_distance_m", "number"),
]


@bp.post("/seed-ops/production-fields")
def create_production_field():
    authenticate(("ProgramAdmin", "FieldOfficer"))
    data = parse_fields(json_body(), FIELD_FIELDS)
    get_grower(data["grower_id"])
    for existing in db.production_fields.values():
        if (existing["grower_id"] == data["grower_id"]
                and existing["field_code"] == data["field_code"]):
            bad_request("field_code must be unique per grower.")
    rec = new_record(True)
    rec["grower_id"] = data["grower_id"]
    rec["field_code"] = data["field_code"]
    rec["acres"] = data["acres"]
    rec["isolation_distance_m"] = data["isolation_distance_m"]
    rec["last_assessed_risk_score"] = None
    rec["history_record_count"] = 0
    db.production_fields[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.get("/seed-ops/production-fields/<production_field_id>")
def read_production_field(production_field_id):
    authenticate(("ProgramAdmin", "FieldOfficer", "Grower"))
    return object_response(public(get_field(production_field_id)))


@bp.get("/seed-ops/production-fields")
def list_production_fields():
    authenticate(("ProgramAdmin", "FieldOfficer", "Grower"))
    limit, offset = parse_pagination()
    rows = rows_where(db.production_fields, grower_id=query_string("grower_id"))
    page, total = paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)


# ---- field history records ---------------------------------------------
HISTORY_FIELDS = [
    Field("crop_kind", "enum", members=CROP_KINDS),
    Field("crop_year", "integer", minimum=1990, maximum=2100),
    Field("source_note", "string", required=False, default="GROWER_DECLARED"),
]


@bp.post("/seed-ops/production-fields/<production_field_id>/history")
def create_history_record(production_field_id):
    authenticate(("ProgramAdmin", "FieldOfficer"))
    data = parse_fields(json_body(), HISTORY_FIELDS)
    field = get_field(production_field_id)
    for existing in db.field_history_records.values():
        if (existing["production_field_id"] == field["id"]
                and existing["crop_year"] == data["crop_year"]):
            bad_request("A field may not carry two history records for the same crop year.")
    rec = new_record(False)
    rec["production_field_id"] = field["id"]
    rec["crop_kind"] = data["crop_kind"]
    rec["crop_year"] = data["crop_year"]
    rec["source_note"] = data["source_note"]
    db.field_history_records[rec["id"]] = rec
    field["history_record_count"] = field["history_record_count"] + 1
    touch(field)
    return object_response(public(rec), 201)


@bp.get("/seed-ops/field-history-records/<field_history_record_id>")
def read_history_record(field_history_record_id):
    authenticate(("ProgramAdmin", "FieldOfficer", "Grower"))
    return object_response(public(get_history_record(field_history_record_id)))


@bp.get("/seed-ops/field-history-records")
def list_history_records():
    authenticate(("ProgramAdmin", "FieldOfficer", "Grower"))
    limit, offset = parse_pagination()
    rows = rows_where(
        db.field_history_records,
        production_field_id=query_string("production_field_id"),
        crop_year=query_integer("crop_year"),
    )
    page, total = paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)


# ---- eligibility assessment (computed read-through) --------------------
ASSESSMENT_FIELDS = [
    Field("variety_id", "string"),
    Field("season_year", "integer"),
    Field("seed_class", "enum", members=CONTRACT_CLASSES),
]


def assess_field(field, variety, season_year, seed_class):
    history = rows_where(db.field_history_records, production_field_id=field["id"])
    return calc.field_eligibility_assessment(history, variety, field, season_year, seed_class)


@bp.post("/seed-ops/production-fields/<production_field_id>/eligibility-assessments")
def create_eligibility_assessment(production_field_id):
    authenticate(("ProgramAdmin", "FieldOfficer"))
    data = parse_fields(json_body(), ASSESSMENT_FIELDS)
    field = get_field(production_field_id)
    variety = get_variety(data["variety_id"])
    result = assess_field(field, variety, data["season_year"], data["seed_class"])
    field["last_assessed_risk_score"] = result["contamination_risk_score"]
    touch(field)
    return object_response(result, 200)
