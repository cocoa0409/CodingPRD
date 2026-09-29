from flask import Blueprint

import calc
from calc import D
from envelope import success
from errors import fail
from services import check_unique, design_risk_index, require
from store import base_record, db, ordered, touch
from validation import (
    COLORS,
    DESIGN_STATUSES,
    OWNERS,
    Enum,
    Id,
    Int,
    Num,
    Str,
    Text,
    authorize,
    paginate,
    pagination,
    query_enum,
    query_str,
    validate_body,
)

bp = Blueprint("designs", __name__)

READERS = (
    "PlantManager",
    "PlantScheduler",
    "MoldEngineer",
    "QualityEngineer",
    "CustomerRep",
)


def _recompute_promises(design):
    """PRD 3.4: submission recomputes both derived promises together."""
    design["breakage_risk_index"] = design_risk_index(design)
    design["lead_time_days"] = calc.design_lead_time_days(
        design["cavity_count"],
        design["revision_count"],
        design["breakage_risk_index"],
        design["supersedes_design_id"] is not None,
    )


@bp.post("/glass-plant/bottle-designs")
def create_design():
    authorize("MoldEngineer")
    data = validate_body(
        [
            Id("customer_id"),
            Id("supersedes_design_id", required=False),
            Str("code", min_len=1, max_len=32),
            Enum("color", COLORS),
            Num("capacity_ml", ge=50, le=3000, decimals=2),
            Num("nominal_weight_g", gt=0, le=1500, decimals=2),
            Num("min_wall_thickness_mm", ge="0.80", le=6, decimals=2),
            Int("cavity_count", ge=1, le=20),
            Num("target_line_speed_bpm", gt=0, le=900, decimals=2),
            Num("container_price_usd", gt=0, le=5, decimals=4),
            Enum("mold_owner", OWNERS),
        ]
    )
    # PRD 2.8: body foreign keys resolve in declared field order.
    customer = require(db.customers, data["customer_id"], "ERR_CUSTOMER_NOT_FOUND")
    predecessor = None
    if data["supersedes_design_id"] is not None:
        predecessor = require(
            db.bottle_designs, data["supersedes_design_id"], "ERR_BOTTLE_DESIGN_NOT_FOUND"
        )
    check_unique(db.bottle_designs, "code", data["code"])

    record = base_record()
    record.update(
        {
            "customer_id": customer["id"],
            "supersedes_design_id": predecessor["id"] if predecessor else None,
            "code": data["code"],
            "color": data["color"],
            "capacity_ml": data["capacity_ml"],
            "nominal_weight_g": data["nominal_weight_g"],
            "min_wall_thickness_mm": data["min_wall_thickness_mm"],
            "cavity_count": data["cavity_count"],
            "target_line_speed_bpm": data["target_line_speed_bpm"],
            "container_price_usd": data["container_price_usd"],
            "mold_owner": data["mold_owner"],
            "status": "DRAFT",
            "revision_count": 0,
            "breakage_risk_index": D("0.00"),
            "lead_time_days": 0,
            "risk_signed_by_user_id": None,
            "approved_by_user_id": None,
        }
    )
    db.bottle_designs[record["id"]] = record
    return success(record, 201)


@bp.get("/glass-plant/bottle-designs")
def list_designs():
    authorize(*READERS)
    status = query_enum("status", DESIGN_STATUSES)
    customer_id = query_str("customer_id")
    supersedes_design_id = query_str("supersedes_design_id")
    limit, offset = pagination()
    records = ordered(list(db.bottle_designs.values()))
    if customer_id is not None:
        records = [r for r in records if r["customer_id"] == customer_id]
    if supersedes_design_id is not None:
        records = [r for r in records if r["supersedes_design_id"] == supersedes_design_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, meta = paginate(records, limit, offset)
    return success(page, 200, meta)


@bp.get("/glass-plant/bottle-designs/<bottle_design_id>")
def read_design(bottle_design_id):
    authorize(*READERS)
    design = require(db.bottle_designs, bottle_design_id, "ERR_BOTTLE_DESIGN_NOT_FOUND")
    return success(design)


@bp.post("/glass-plant/bottle-designs/<bottle_design_id>/submit")
def submit_design(bottle_design_id):
    authorize("MoldEngineer")
    design = require(db.bottle_designs, bottle_design_id, "ERR_BOTTLE_DESIGN_NOT_FOUND")
    if design["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        fail("ERR_DESIGN_STATE_INVALID")
    if design["status"] == "CHANGES_REQUESTED":
        # A resubmission books the revision first, so the promise lengthens.
        design["revision_count"] = int(design["revision_count"]) + 1
    design["status"] = "SUBMITTED"
    _recompute_promises(design)
    touch(design)
    return success(design)


@bp.post("/glass-plant/bottle-designs/<bottle_design_id>/request-changes")
def request_changes(bottle_design_id):
    authorize("QualityEngineer")
    validate_body([Text("note", required=False)])
    design = require(db.bottle_designs, bottle_design_id, "ERR_BOTTLE_DESIGN_NOT_FOUND")
    if design["status"] != "SUBMITTED":
        fail("ERR_DESIGN_STATE_INVALID")
    design["status"] = "CHANGES_REQUESTED"
    touch(design)
    return success(design)


@bp.post("/glass-plant/bottle-designs/<bottle_design_id>/risk-signoff")
def risk_signoff(bottle_design_id):
    user_id, _role = authorize("QualityEngineer")
    design = require(db.bottle_designs, bottle_design_id, "ERR_BOTTLE_DESIGN_NOT_FOUND")
    if design["status"] != "SUBMITTED":
        fail("ERR_DESIGN_STATE_INVALID")
    if D(design["breakage_risk_index"]) > calc.RISK_SIGNOFF_CAP:
        fail("ERR_RISK_INDEX_ABOVE_CAP")
    design["status"] = "RISK_SIGNED"
    design["risk_signed_by_user_id"] = user_id
    touch(design)
    return success(design)


@bp.post("/glass-plant/bottle-designs/<bottle_design_id>/approve")
def approve_design(bottle_design_id):
    user_id, _role = authorize("QualityEngineer")
    design = require(db.bottle_designs, bottle_design_id, "ERR_BOTTLE_DESIGN_NOT_FOUND")
    if design["status"] != "RISK_SIGNED":
        fail("ERR_DESIGN_STATE_INVALID")
    if user_id == design["risk_signed_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")

    design["status"] = "APPROVED"
    design["approved_by_user_id"] = user_id
    touch(design)

    predecessor_id = design["supersedes_design_id"]
    if predecessor_id is not None:
        predecessor = db.bottle_designs.get(predecessor_id)
        if predecessor is not None and predecessor["status"] == "APPROVED":
            predecessor["status"] = "OBSOLETE"
            touch(predecessor)
    return success(design)
