"""Reference resolution (PRD section 2.5): one not-found code per entity."""

import db
from errors import ApiError

CODES = {
    "applicable_rules": "ERR_RULE_NOT_FOUND",
    "product_categories": "ERR_CATEGORY_NOT_FOUND",
    "category_rule_mappings": "ERR_MAPPING_NOT_FOUND",
    "suppliers": "ERR_SUPPLIER_NOT_FOUND",
    "laboratories": "ERR_LABORATORY_NOT_FOUND",
    "lab_accreditations": "ERR_ACCREDITATION_NOT_FOUND",
    "products": "ERR_PRODUCT_NOT_FOUND",
    "component_parts": "ERR_COMPONENT_PART_NOT_FOUND",
    "component_part_certificates": "ERR_PART_CERTIFICATE_NOT_FOUND",
    "sampling_plans": "ERR_SAMPLING_PLAN_NOT_FOUND",
    "test_orders": "ERR_TEST_ORDER_NOT_FOUND",
    "certificates": "ERR_CERTIFICATE_NOT_FOUND",
    "production_batches": "ERR_BATCH_NOT_FOUND",
    "noncompliance_cases": "ERR_CASE_NOT_FOUND",
    "material_change_events": "ERR_MATERIAL_CHANGE_EVENT_NOT_FOUND",
}


def require(table, row_id):
    row = db.get(table, row_id)
    if row is None:
        raise ApiError(CODES[table])
    return row


def require_child_of(table, row_id, product_id):
    """A child that exists but belongs to another product uses its own code."""
    row = require(table, row_id)
    if row.get("product_id") != product_id:
        raise ApiError(CODES[table])
    return row


def rule(rule_id):
    return require("applicable_rules", rule_id)


def category(category_id):
    return require("product_categories", category_id)


def mapping(mapping_id):
    return require("category_rule_mappings", mapping_id)


def supplier(supplier_id):
    return require("suppliers", supplier_id)


def laboratory(laboratory_id):
    return require("laboratories", laboratory_id)


def accreditation(accreditation_id):
    return require("lab_accreditations", accreditation_id)


def product(product_id):
    return require("products", product_id)


def part(part_id):
    return require("component_parts", part_id)


def part_certificate(part_certificate_id):
    return require("component_part_certificates", part_certificate_id)


def plan(plan_id):
    return require("sampling_plans", plan_id)


def order(order_id):
    return require("test_orders", order_id)


def certificate(certificate_id):
    return require("certificates", certificate_id)


def batch(batch_id):
    return require("production_batches", batch_id)


def case(case_id):
    return require("noncompliance_cases", case_id)


def event(event_id):
    return require("material_change_events", event_id)
