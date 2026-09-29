"""Cell design authoring, editing, review and supersession."""
from decimal import Decimal

from flask import Blueprint, g

from authz import (
    DESIGN_ENGINEER,
    FLEET_ENGINEER,
    JOB_ENGINEER,
    PLANT_ADMIN,
    PRODUCTION_SUPERVISOR,
    QUALITY_INSPECTOR,
    WARRANTY_ADMINISTRATOR,
    endpoint,
    require_job_class,
)
from errors import ApiError
from helpers import apply_filters, lookup, paginated, unique_or_conflict
from response import object_response
from store import db
from util import q
from services.constants import (
    CHEMISTRIES,
    CHEM_LEAD,
    CHEM_LITHIUM,
    PLATE_FLAT,
    PLATE_PRISMATIC,
    PLATE_TUBULAR,
    PLATE_TYPES,
)

bp = Blueprint("designs", __name__)

DESIGN_READERS = [
    PLANT_ADMIN,
    DESIGN_ENGINEER,
    PRODUCTION_SUPERVISOR,
    QUALITY_INSPECTOR,
    FLEET_ENGINEER,
    WARRANTY_ADMINISTRATOR,
]

APPROVAL_STATES = ["DRAFT", "UNDER_REVIEW", "CHANGES_REQUESTED", "APPROVED", "RETIRED"]

CREATE_SPEC = {
    "code": {"type": "string", "required": True},
    "chemistry": {"type": "enum", "required": True, "values": CHEMISTRIES},
    "plate_type": {"type": "enum", "required": True, "values": PLATE_TYPES},
    "cells_per_battery": {"type": "int", "required": True, "gte": 1},
    "cell_nominal_voltage_v": {"type": "number", "required": True, "gt": 0},
    "nominal_capacity_ah": {"type": "number", "required": True, "gt": 0},
    "rated_cycles": {"type": "int", "required": True, "gte": 1},
    "warranty_months": {"type": "int", "required": True, "gte": 1},
    "pack_weight_kg": {"type": "number", "required": True, "gt": 0},
    "lead_content_kg": {"type": "number", "required": True, "gte": 0},
    "list_price_cents": {"type": "int", "required": True, "gt": 0},
    "formation_charge_factor": {
        "type": "number",
        "gte": 1,
        "lte": 2,
        "default": Decimal("1.15"),
    },
    "retest_tightening_enabled": {"type": "bool", "default": True},
    "supersedes_design_id": {"type": "id", "nullable": True, "default": None},
}

PATCH_SPEC = {
    "nominal_capacity_ah": {"type": "number", "gt": 0},
    "rated_cycles": {"type": "int", "gte": 1},
    "warranty_months": {"type": "int", "gte": 1},
    "pack_weight_kg": {"type": "number", "gt": 0},
    "lead_content_kg": {"type": "number", "gte": 0},
    "formation_charge_factor": {"type": "number", "gte": 1, "lte": 2},
    "list_price_cents": {"type": "int", "gt": 0},
    "retest_tightening_enabled": {"type": "bool"},
}

REVIEW_SPEC = {
    "action": {
        "type": "enum",
        "required": True,
        "values": ["SUBMIT", "REQUEST_CHANGES", "APPROVE"],
    },
    "review_comment": {"type": "string", "allow_blank": True},
}

DESIGN_FILTERS = {
    "chemistry": "chemistry",
    "approval_state": "approval_state",
    "submitted_by_worker_id": "submitted_by_worker_id",
    "approved_by_worker_id": "approved_by_worker_id",
    "supersedes_design_id": "supersedes_design_id",
}
DEFAULT_ORDER = [("created_at", "asc"), ("id", "asc")]


def check_plate_coherence(chemistry, plate_type, lead_content_kg):
    """PRD 3.3: chemistry and construction must agree."""
    if chemistry == CHEM_LEAD:
        if plate_type not in (PLATE_TUBULAR, PLATE_FLAT) or lead_content_kg <= 0:
            raise ApiError(
                "ERR_PLATE_TYPE_INCOMPATIBLE",
                "A LEAD_ACID design requires TUBULAR or FLAT_PASTED plates and positive lead content",
            )
    elif chemistry == CHEM_LITHIUM:
        if plate_type != PLATE_PRISMATIC or lead_content_kg != 0:
            raise ApiError(
                "ERR_PLATE_TYPE_INCOMPATIBLE",
                "A LITHIUM_LFP design requires PRISMATIC_CELL plates and zero lead content",
            )


def _create_plate_check(payload):
    check_plate_coherence(payload["chemistry"], payload["plate_type"], payload["lead_content_kg"])


@bp.post("/cell-designs")
@endpoint([DESIGN_ENGINEER], body=CREATE_SPEC, schema_check=_create_plate_check)
def create_design():
    payload = g.body
    if payload.get("supersedes_design_id") is not None:
        lookup("cell_designs", payload["supersedes_design_id"], "ERR_CELL_DESIGN_NOT_FOUND")
    unique_or_conflict("cell_designs", "code", payload["code"])
    record = {
        "code": payload["code"],
        "chemistry": payload["chemistry"],
        "plate_type": payload["plate_type"],
        "cells_per_battery": payload["cells_per_battery"],
        "cell_nominal_voltage_v": payload["cell_nominal_voltage_v"],
        "nominal_pack_voltage_v": q(
            Decimal(payload["cells_per_battery"]) * payload["cell_nominal_voltage_v"], 1
        ),
        "nominal_capacity_ah": payload["nominal_capacity_ah"],
        "rated_cycles": payload["rated_cycles"],
        "warranty_months": payload["warranty_months"],
        "pack_weight_kg": payload["pack_weight_kg"],
        "lead_content_kg": payload["lead_content_kg"],
        "formation_charge_factor": payload["formation_charge_factor"],
        "list_price_cents": payload["list_price_cents"],
        "retest_tightening_enabled": payload["retest_tightening_enabled"],
        "supersedes_design_id": payload["supersedes_design_id"],
        "approval_state": "DRAFT",
        "revision": 1,
        "approved_revision": None,
        "submitted_by_worker_id": None,
        "approved_by_worker_id": None,
    }
    db.insert("cell_designs", record)
    return object_response(record, 201)


@bp.get("/cell-designs")
@endpoint(DESIGN_READERS, paginated=True)
def list_designs():
    return paginated(apply_filters(db.rows("cell_designs"), DESIGN_FILTERS), DEFAULT_ORDER)


@bp.get("/cell-designs/<design_id>")
@endpoint(DESIGN_READERS)
def read_design(design_id):
    return object_response(lookup("cell_designs", design_id))


@bp.patch("/cell-designs/<design_id>")
@endpoint([DESIGN_ENGINEER], body=PATCH_SPEC, at_least_one=True)
def edit_design(design_id):
    design = lookup("cell_designs", design_id)
    merged_lead = g.body.get("lead_content_kg", design["lead_content_kg"])
    check_plate_coherence(design["chemistry"], design["plate_type"], merged_lead)
    if design["approval_state"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise ApiError(
            "ERR_DESIGN_STATE_INVALID",
            "Only a DRAFT or CHANGES_REQUESTED design may be edited",
        )
    for field in PATCH_SPEC:
        if field in g.body:
            design[field] = g.body[field]
    design["revision"] = design.get("revision", 1) + 1
    if design["approval_state"] == "CHANGES_REQUESTED":
        design["approval_state"] = "DRAFT"
    db.touch(design)
    return object_response(design)


@bp.post("/cell-designs/<design_id>/review-actions")
@endpoint([DESIGN_ENGINEER], body=REVIEW_SPEC)
def review_design(design_id):
    action = g.body["action"]
    if action == "APPROVE":
        require_job_class(JOB_ENGINEER)
    design = lookup("cell_designs", design_id)
    actor_id = g.actor["id"]
    if action == "SUBMIT":
        if design["approval_state"] != "DRAFT":
            raise ApiError("ERR_DESIGN_STATE_INVALID", "Only a DRAFT design may be submitted")
        design["approval_state"] = "UNDER_REVIEW"
        design["submitted_by_worker_id"] = actor_id
    elif action == "REQUEST_CHANGES":
        if design["approval_state"] != "UNDER_REVIEW":
            raise ApiError(
                "ERR_DESIGN_STATE_INVALID",
                "Only an UNDER_REVIEW design may have changes requested",
            )
        if design.get("submitted_by_worker_id") == actor_id:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                "The submitter may not request changes on their own design",
            )
        design["approval_state"] = "CHANGES_REQUESTED"
    else:
        if design["approval_state"] != "UNDER_REVIEW":
            raise ApiError(
                "ERR_DESIGN_STATE_INVALID", "Only an UNDER_REVIEW design may be approved"
            )
        if design.get("submitted_by_worker_id") == actor_id:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                "The submitter may not approve their own design",
            )
        design["approval_state"] = "APPROVED"
        design["approved_revision"] = design["revision"]
        design["approved_by_worker_id"] = actor_id
        predecessor_id = design.get("supersedes_design_id")
        if predecessor_id:
            predecessor = db.cell_designs.get(predecessor_id)
            if predecessor is not None and predecessor.get("approval_state") == "APPROVED":
                predecessor["approval_state"] = "RETIRED"
                db.touch(predecessor)
    db.touch(design)
    return object_response(design)
