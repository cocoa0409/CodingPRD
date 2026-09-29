"""ForeignSupplier and Food."""
from flask import Blueprint

import cascades
import core
import serialize
from core import write_txn
from db import store
from errors import fail
from middleware import CO, FDA, QI, endpoint
from response import object_response
from routes._common import find, paged, require_qi_current
from shapes import (
    body,
    opt_bool,
    opt_enum,
    pagination,
    query_enum,
    req_bool,
    req_enum,
    req_str,
)

bp = Blueprint("suppliers", __name__)

EVALUATION_DECISIONS = ("APPROVE", "APPROVE_CONDITIONALLY")


# --------------------------------------------------------- ForeignSupplier
@bp.post("/fsvp/foreign-suppliers")
@endpoint([CO])
def create_supplier():
    b = body()
    importer_id = req_str(b, "importer_id")
    name = req_str(b, "name", minlen=1)
    country_code = req_str(b, "country_code")
    if len(country_code) != 2 or not country_code.isascii() or not country_code.isupper() or not country_code.isalpha():
        fail("ERR_INVALID_REQUEST", "country_code must be exactly 2 uppercase letters")
    frn = req_str(b, "facility_registration_number", minlen=1)
    compliance = opt_enum(
        b, "regulatory_compliance_status", core.COMPLIANCE_STATUSES, default="NO_ADVERSE_FINDINGS"
    )

    find("importer", importer_id, "ERR_IMPORTER_NOT_FOUND")

    for row in store.suppliers.values():
        if row["importer_id"] == importer_id and row["facility_registration_number"] == frn:
            fail("ERR_DUPLICATE_IDENTIFIER", "facility_registration_number already used")

    with write_txn():
        row = store.new_row("supplier")
        row.update(
            {
                "importer_id": importer_id,
                "name": name,
                "country_code": country_code,
                "facility_registration_number": frn,
                "regulatory_compliance_status": compliance,
                "compliance_status_source_reference": None,
                "status": "UNEVALUATED",
                "last_evaluated_at": None,
            }
        )
        store.insert(row)
    return object_response(serialize.supplier_out(row), 201)


@bp.get("/fsvp/foreign-suppliers/<supplier_id>")
@endpoint([CO, QI, FDA])
def read_supplier(supplier_id):
    row = find("supplier", supplier_id, "ERR_SUPPLIER_NOT_FOUND")
    return object_response(serialize.supplier_out(row))


@bp.get("/fsvp/importers/<importer_id>/foreign-suppliers")
@endpoint([CO, QI, FDA])
def list_importer_suppliers(importer_id):
    status = query_enum("status", core.SUPPLIER_STATUSES)
    compliance = query_enum("regulatory_compliance_status", core.COMPLIANCE_STATUSES)
    limit, offset = pagination()
    importer = find("importer", importer_id, "ERR_IMPORTER_NOT_FOUND")
    rows = core.suppliers_of_importer(importer["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if compliance is not None:
        rows = [r for r in rows if r["regulatory_compliance_status"] == compliance]
    return paged(rows, serialize.supplier_out, limit, offset)


@bp.patch("/fsvp/foreign-suppliers/<supplier_id>/compliance-status")
@endpoint([CO])
def patch_compliance_status(supplier_id):
    b = body()
    compliance = req_enum(b, "regulatory_compliance_status", core.COMPLIANCE_STATUSES)
    source_reference = req_str(b, "source_reference", minlen=1)

    supplier = find("supplier", supplier_id, "ERR_SUPPLIER_NOT_FOUND")

    with write_txn():
        supplier["regulatory_compliance_status"] = compliance
        supplier["compliance_status_source_reference"] = source_reference
        store.touch(supplier)
        cascades.compliance_status_cascade(supplier)
    return object_response(serialize.supplier_out(supplier))


@bp.post("/fsvp/foreign-suppliers/<supplier_id>/evaluation")
@endpoint([QI])
def evaluate_supplier(supplier_id):
    b = body()
    decision = req_enum(b, "decision", EVALUATION_DECISIONS)
    req_str(b, "performance_basis_note", minlen=1)

    supplier = find("supplier", supplier_id, "ERR_SUPPLIER_NOT_FOUND")

    transitions = {
        ("UNEVALUATED", "APPROVE"): "APPROVED",
        ("UNEVALUATED", "APPROVE_CONDITIONALLY"): "CONDITIONALLY_APPROVED",
        ("CONDITIONALLY_APPROVED", "APPROVE"): "APPROVED",
    }
    target = transitions.get((supplier["status"], decision))
    if target is None:
        fail(
            "ERR_INVALID_STATE_TRANSITION",
            "cannot %s a %s supplier" % (decision, supplier["status"]),
        )

    require_qi_current()

    allowed_postures = (
        ("NO_ADVERSE_FINDINGS",)
        if decision == "APPROVE"
        else ("NO_ADVERSE_FINDINGS", "WARNING_LETTER")
    )
    if supplier["regulatory_compliance_status"] not in allowed_postures:
        fail(
            "ERR_COMPLIANCE_STATUS_BLOCKS_APPROVAL",
            "regulatory_compliance_status %s blocks this decision"
            % supplier["regulatory_compliance_status"],
        )

    with write_txn():
        supplier["status"] = target
        supplier["last_evaluated_at"] = core.clock()
        store.touch(supplier)
    return object_response(serialize.supplier_out(supplier))


# --------------------------------------------------------------------- Food
@bp.post("/fsvp/foods")
@endpoint([CO])
def create_food():
    b = body()
    importer_id = req_str(b, "importer_id")
    food_name = req_str(b, "food_name", minlen=1)
    product_code = req_str(b, "fda_product_code", minlen=3, maxlen=16)
    is_rac = req_bool(b, "is_raw_agricultural_commodity")
    consumer_group = req_enum(b, "intended_consumer_group", core.CONSUMER_GROUPS)
    process_control = opt_enum(
        b, "process_control_category", core.PROCESS_CONTROL_CATEGORIES, default="NONE"
    )
    ready_to_eat = opt_bool(b, "ready_to_eat", default=False)

    find("importer", importer_id, "ERR_IMPORTER_NOT_FOUND")

    for row in store.foods.values():
        if row["importer_id"] == importer_id and row["fda_product_code"] == product_code:
            fail("ERR_DUPLICATE_IDENTIFIER", "fda_product_code already used for this importer")

    with write_txn():
        row = store.new_row("food", versioned=False)
        row.update(
            {
                "importer_id": importer_id,
                "food_name": food_name,
                "fda_product_code": product_code,
                "is_raw_agricultural_commodity": is_rac,
                "intended_consumer_group": consumer_group,
                "process_control_category": process_control,
                "ready_to_eat": ready_to_eat,
            }
        )
        store.insert(row)
    return object_response(serialize.food_out(row), 201)


@bp.get("/fsvp/importers/<importer_id>/foods")
@endpoint([CO, QI, FDA])
def list_importer_foods(importer_id):
    process_control = query_enum("process_control_category", core.PROCESS_CONTROL_CATEGORIES)
    limit, offset = pagination()
    importer = find("importer", importer_id, "ERR_IMPORTER_NOT_FOUND")
    rows = [f for f in store.foods.values() if f["importer_id"] == importer["id"]]
    if process_control is not None:
        rows = [r for r in rows if r["process_control_category"] == process_control]
    return paged(rows, serialize.food_out, limit, offset)
