"""Regulatory reference library and the supplier register (PRD 3.1, 3.2)."""

from flask import Blueprint

import auth
import db
import paging
import refs
import response
import validation
from errors import ApiError
from services import calc, engine

bp = Blueprint("reference", __name__)

ALL_ROLES = auth.ROLES

HAZARD_CLASSES = {
    "LEAD_PAINT",
    "LEAD_CONTENT",
    "PHTHALATES",
    "MECHANICAL_HAZARD",
    "FLAMMABILITY",
}
LIMIT_UNITS = {"PPM", "PERCENT_BY_WEIGHT", "NEWTON", "MILLIMETRE"}
LIMIT_COMPARATORS = {"AT_OR_BELOW", "AT_OR_ABOVE"}
APPLICABILITY_CONDITIONS = {
    "ALWAYS",
    "IF_PAINTED_SURFACE",
    "IF_PLASTICIZED_PART",
    "IF_SMALL_PART_PRESENT",
    "IF_ACCESSIBLE_METAL",
}
MAPPING_STATES = {"ACTIVE", "RETIRED"}
RELIANCE_AGREEMENT_STATES = {"NOT_ON_FILE", "ON_FILE"}


# --------------------------------------------------------------------------
# Applicable rules
# --------------------------------------------------------------------------

@bp.post("/applicable-rules")
def create_rule():
    auth.require_roles("ComplianceAdministrator")
    body = validation.json_body()
    rule_code = validation.string_field(
        body, "rule_code", min_len=3, max_len=40, pattern=validation.RE_UPPER_SNAKE
    )
    hazard_class = validation.enum_field(body, "hazard_class", HAZARD_CLASSES)
    test_method_code = validation.string_field(
        body,
        "test_method_code",
        min_len=3,
        max_len=40,
        pattern=validation.RE_UPPER_ALNUM_DASH,
    )
    limit_value = validation.number_field(body, "limit_value", minimum=0)
    limit_unit = validation.enum_field(body, "limit_unit", LIMIT_UNITS)
    limit_comparator = validation.enum_field(
        body, "limit_comparator", LIMIT_COMPARATORS, required=False,
        default="AT_OR_BELOW",
    )
    periodic_interval_months = validation.int_field(
        body, "periodic_interval_months", minimum=1, maximum=60
    )
    base_method_fee_cents = validation.int_field(
        body, "base_method_fee_cents", minimum=0
    )
    component_reliance_allowed = validation.bool_field(
        body, "component_reliance_allowed", required=False, default=True
    )
    severity_weight = validation.int_field(
        body, "severity_weight", minimum=1, maximum=10
    )
    for existing in db.all_rows("applicable_rules"):
        if existing["rule_code"] == rule_code:
            raise ApiError("ERR_INVALID_REQUEST", "rule_code: must be unique")
    row = db.insert(
        "applicable_rules",
        {
            "rule_code": rule_code,
            "hazard_class": hazard_class,
            "test_method_code": test_method_code,
            "limit_value": limit_value,
            "limit_unit": limit_unit,
            "limit_comparator": limit_comparator,
            "periodic_interval_months": periodic_interval_months,
            "base_method_fee_cents": base_method_fee_cents,
            "component_reliance_allowed": component_reliance_allowed,
            "severity_weight": severity_weight,
        },
    )
    return response.object_response(db.serialize("applicable_rules", row), 201)


@bp.get("/applicable-rules/<rule_id>")
def get_rule(rule_id):
    auth.require_roles(*ALL_ROLES)
    row = refs.rule(rule_id)
    return response.object_response(db.serialize("applicable_rules", row))


@bp.get("/applicable-rules")
def list_rules():
    auth.require_roles(*ALL_ROLES)
    hazard_class = validation.query_enum("hazard_class", HAZARD_CLASSES)
    return paging.build(
        "applicable_rules", [paging.eq_filter("hazard_class", hazard_class)]
    )


# --------------------------------------------------------------------------
# Product categories
# --------------------------------------------------------------------------

@bp.post("/product-categories")
def create_category():
    auth.require_roles("ComplianceAdministrator")
    body = validation.json_body()
    category_code = validation.string_field(
        body, "category_code", min_len=3, max_len=40,
        pattern=validation.RE_UPPER_SNAKE,
    )
    display_name = validation.string_field(body, "display_name", min_len=1, max_len=120)
    durable_infant_product = validation.bool_field(
        body, "durable_infant_product", required=False, default=False
    )
    intended_age_max_months = validation.int_field(
        body, "intended_age_max_months", minimum=0, maximum=168
    )
    sampling_floor_units = validation.int_field(
        body, "sampling_floor_units", minimum=1
    )
    for existing in db.all_rows("product_categories"):
        if existing["category_code"] == category_code:
            raise ApiError("ERR_INVALID_REQUEST", "category_code: must be unique")
    row = db.insert(
        "product_categories",
        {
            "category_code": category_code,
            "display_name": display_name,
            "durable_infant_product": durable_infant_product,
            "intended_age_max_months": intended_age_max_months,
            "sampling_floor_units": sampling_floor_units,
        },
    )
    return response.object_response(db.serialize("product_categories", row), 201)


@bp.get("/product-categories/<category_id>")
def get_category(category_id):
    auth.require_roles(*ALL_ROLES)
    row = refs.category(category_id)
    return response.object_response(db.serialize("product_categories", row))


# --------------------------------------------------------------------------
# Category-rule mappings
# --------------------------------------------------------------------------

@bp.post("/category-rule-mappings")
def create_mapping():
    auth.require_roles("ComplianceAdministrator")
    body = validation.json_body()
    category_id = validation.id_field(body, "category_id")
    rule_id = validation.id_field(body, "rule_id")
    condition = validation.enum_field(
        body, "applicability_condition", APPLICABILITY_CONDITIONS
    )
    effective_from = validation.datetime_field(body, "effective_from")
    refs.category(category_id)
    refs.rule(rule_id)
    for existing in db.all_rows("category_rule_mappings"):
        if (
            existing["category_id"] == category_id
            and existing["rule_id"] == rule_id
            and existing["mapping_state"] == "ACTIVE"
        ):
            raise ApiError("ERR_MAPPING_DUPLICATE")
    row = db.insert(
        "category_rule_mappings",
        {
            "category_id": category_id,
            "rule_id": rule_id,
            "applicability_condition": condition,
            "effective_from": effective_from,
            "mapping_state": "ACTIVE",
        },
    )
    return response.object_response(db.serialize("category_rule_mappings", row), 201)


@bp.get("/category-rule-mappings/<mapping_id>")
def get_mapping(mapping_id):
    auth.require_roles(
        "ComplianceAdministrator", "TestCoordinator", "CertificationOfficer"
    )
    row = refs.mapping(mapping_id)
    return response.object_response(db.serialize("category_rule_mappings", row))


@bp.get("/category-rule-mappings")
def list_mappings():
    auth.require_roles(
        "ComplianceAdministrator", "TestCoordinator", "CertificationOfficer"
    )
    category_id = validation.query_string("category_id")
    rule_id = validation.query_string("rule_id")
    mapping_state = validation.query_enum("mapping_state", MAPPING_STATES)
    return paging.build(
        "category_rule_mappings",
        [
            paging.eq_filter("category_id", category_id),
            paging.eq_filter("rule_id", rule_id),
            paging.eq_filter("mapping_state", mapping_state),
        ],
    )


@bp.post("/category-rule-mappings/<mapping_id>/retire")
def retire_mapping(mapping_id):
    auth.require_roles("ComplianceAdministrator")
    row = refs.mapping(mapping_id)
    row["mapping_state"] = "RETIRED"
    engine.bump("category_rule_mappings", row)
    for product in db.find("products", category_id=row["category_id"]):
        if product["certification_state"] != "DRAFT":
            continue
        product["required_rule_ids"] = calc.derive_required_rule_ids(product)
        engine.bump("products", product)
    return response.object_response(db.serialize("category_rule_mappings", row))


# --------------------------------------------------------------------------
# Suppliers
# --------------------------------------------------------------------------

@bp.post("/suppliers")
def create_supplier():
    auth.require_roles("ComplianceAdministrator")
    body = validation.json_body()
    legal_name = validation.string_field(body, "legal_name", min_len=1, max_len=160)
    country_code = validation.string_field(
        body, "country_code", min_len=2, max_len=2, pattern=validation.RE_COUNTRY
    )
    reliance_agreement_state = validation.enum_field(
        body, "reliance_agreement_state", RELIANCE_AGREEMENT_STATES,
        required=False, default="NOT_ON_FILE",
    )
    row = db.insert(
        "suppliers",
        {
            "legal_name": legal_name,
            "country_code": country_code,
            "reliance_agreement_state": reliance_agreement_state,
            "certificates_issued_count": 0,
        },
    )
    return response.object_response(db.serialize("suppliers", row), 201)


@bp.get("/suppliers/<supplier_id>")
def get_supplier(supplier_id):
    auth.require_roles(
        "ComplianceAdministrator", "CertificationOfficer", "SupplierUser"
    )
    row = refs.supplier(supplier_id)
    return response.object_response(db.serialize("suppliers", row))
