"""Service lines, evidence items and classification overrides."""

from flask import Blueprint

import logic
import lookup
from core import (
    ANY_ROLE, body_json, by_created_at, db, endpoint, fail, field, filter_arg,
    filter_bool, iso_ms, new_row, paginate, read_pagination, respond_list,
    respond_object, touch, validate_body,
)

bp = Blueprint("inventory", __name__)

SIDES = ("UTILITY", "CUSTOMER")
MATERIALS = ("LEAD", "GRR", "COPPER", "PLASTIC", "UNKNOWN")
SOURCE_TYPES = ("HISTORIC_RECORD", "PREDICTIVE_MODEL", "WATER_SAMPLING",
                "VISUAL_INSPECTION", "POTHOLE")


# ---------------------------------------------------------------- ServiceLine
@bp.post("/lsl/service-lines")
@endpoint(["InventoryAnalyst"])
def create_service_line():
    data = validate_body(body_json(), [
        field("water_system_id", "string", required=True),
        field("address_label", "string", required=True, nonempty=True),
        field("census_tract_code", "string", required=True, nonempty=True),
        field("street_project_id", "string", default=None),
        field("serves_sensitive_population", "boolean", default=False),
        field("interior_diameter_mm", "number", default=19.0, gt=0),
        field("total_length_m", "number", default=15.0, gt=0),
    ])
    ws = lookup.water_system(data["water_system_id"])
    if data["street_project_id"] is not None:
        lookup.street_project(data["street_project_id"])

    for row in db.service_lines.values():
        if row["water_system_id"] == ws["id"] \
                and row["address_label"] == data["address_label"]:
            fail("ERR_DUPLICATE_ADDRESS_LABEL",
                 "address_label %s already exists for this water system."
                 % data["address_label"])

    line = new_row()
    line.update({
        "water_system_id": ws["id"],
        "street_project_id": data["street_project_id"],
        "address_label": data["address_label"],
        "census_tract_code": data["census_tract_code"],
        "serves_sensitive_population": data["serves_sensitive_population"],
        "interior_diameter_mm": data["interior_diameter_mm"],
        "total_length_m": data["total_length_m"],
        "disadvantaged_status": data["census_tract_code"]
        in ws["disadvantaged_tract_codes"],
        "utility_side_material": "UNKNOWN",
        "customer_side_material": "UNKNOWN",
        "classification": "UNKNOWN",
        "certainty_basis": "RECORDS_BASIS",
        "certainty_score": 0.0,
        "replacement_priority_score": 0.0,
        "consent_barrier_flag": False,
        "inventory_state": "UNCLASSIFIED",
        "replacement_state": "NOT_REQUIRED",
    })
    db.service_lines[line["id"]] = line
    return respond_object(logic.serialize_service_line(line), 201)


@bp.get("/lsl/service-lines")
@endpoint(ANY_ROLE)
def list_service_lines():
    limit, offset = read_pagination()
    rows = by_created_at(list(db.service_lines.values()))
    for name in ("water_system_id", "street_project_id", "classification",
                 "inventory_state", "replacement_state"):
        value = filter_arg(name)
        if value is not None:
            rows = [r for r in rows if r[name] == value]
    flag = filter_bool("disadvantaged_status")
    if flag is not None:
        rows = [r for r in rows if r["disadvantaged_status"] == flag]
    page, total = paginate(rows, limit, offset)
    return respond_list([logic.serialize_service_line(r) for r in page],
                        limit, offset, total)


@bp.get("/lsl/service-lines/<line_id>")
@endpoint(ANY_ROLE)
def read_service_line(line_id):
    line = lookup.service_line(line_id)
    return respond_object(logic.serialize_service_line(line))


@bp.post("/lsl/service-lines/<line_id>/classification-overrides")
@endpoint(["InventoryAnalyst"])
def override_classification(line_id):
    data = validate_body(body_json(), [
        field("expected_service_line_version", "integer", required=True),
        field("side", "string", required=True, enum=SIDES),
        field("asserted_material", "string", required=True, enum=MATERIALS),
        field("justification", "string", required=True, nonempty=True),
    ])
    line = lookup.service_line(line_id)
    if data["expected_service_line_version"] != line["version"]:
        fail("ERR_STALE_SERVICE_LINE_VERSION",
             "expected_service_line_version %s does not match the live version %s."
             % (data["expected_service_line_version"], line["version"]))

    logic.create_evidence_item(
        line["id"], "POTHOLE", data["side"], data["asserted_material"],
        iso_ms(db.clock), notes=data["justification"], origin="MANUAL",
    )
    logic.classification_recompute(line)
    return respond_object(logic.serialize_service_line(line))


# --------------------------------------------------------------- EvidenceItem
@bp.post("/lsl/evidence-items")
@endpoint(["InventoryAnalyst", "FieldTechnician"])
def create_evidence_item():
    data = validate_body(body_json(), [
        field("service_line_id", "string", required=True),
        field("source_type", "string", required=True, enum=SOURCE_TYPES),
        field("side", "string", required=True, enum=SIDES),
        field("observed_material", "string", required=True, enum=MATERIALS),
        field("observed_at", "datetime", required=True),
        field("notes", "string", default=None),
    ])
    line = lookup.service_line(data["service_line_id"])
    if data["source_type"] == "WATER_SAMPLING" and data["side"] == "CUSTOMER":
        fail("ERR_EVIDENCE_SIDE_MISMATCH",
             "A WATER_SAMPLING observation may only describe the UTILITY side.")

    item = logic.create_evidence_item(
        line["id"], data["source_type"], data["side"], data["observed_material"],
        data["observed_at"], notes=data["notes"], origin="MANUAL",
    )
    logic.classification_recompute(line)
    return respond_object(logic.serialize_evidence_item(item), 201)


@bp.get("/lsl/evidence-items")
@endpoint(["ProgramAdministrator", "InventoryAnalyst", "ComplianceOfficer",
           "FieldTechnician"])
def list_evidence_items():
    limit, offset = read_pagination()
    rows = by_created_at(list(db.evidence_items.values()))
    for name in ("service_line_id", "source_type", "side", "origin"):
        value = filter_arg(name)
        if value is not None:
            rows = [r for r in rows if r[name] == value]
    flag = filter_bool("retracted")
    if flag is not None:
        rows = [r for r in rows if r["retracted"] == flag]
    page, total = paginate(rows, limit, offset)
    return respond_list([logic.serialize_evidence_item(r) for r in page],
                        limit, offset, total)


@bp.get("/lsl/evidence-items/<item_id>")
@endpoint(["ProgramAdministrator", "InventoryAnalyst", "ComplianceOfficer",
           "FieldTechnician"])
def read_evidence_item(item_id):
    item = lookup.evidence_item(item_id)
    return respond_object(logic.serialize_evidence_item(item))


@bp.post("/lsl/evidence-items/<item_id>/retract")
@endpoint(["InventoryAnalyst"])
def retract_evidence_item(item_id):
    data = validate_body(body_json(), [
        field("reason", "string", required=True, nonempty=True),
    ])
    item = lookup.evidence_item(item_id)
    if item["retracted"]:
        fail("ERR_EVIDENCE_ALREADY_RETRACTED",
             "This evidence item has already been retracted.")

    item["retracted"] = True
    item["retraction_reason"] = data["reason"]
    touch(item)

    line = db.service_lines.get(item["service_line_id"])
    if line is not None:
        logic.classification_recompute(line)
    return respond_object(logic.serialize_evidence_item(item))
