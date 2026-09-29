from flask import Blueprint

import calc
from calc import D
from envelope import success
from errors import fail
from services import check_unique, design_risk_index, require
from store import base_record, db, ordered, touch
from validation import (
    PROGRAM_STATUSES,
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

bp = Blueprint("programs", __name__)

READERS = ("PlantManager", "MoldEngineer", "QualityEngineer", "CustomerRep")

NON_TERMINAL = ("DRAFT", "RISK_ASSESSED", "PILOT", "ADOPTED", "SUSPENDED")


@bp.post("/glass-plant/lightweighting-programs")
def create_program():
    authorize("QualityEngineer")
    data = validate_body(
        [
            Id("baseline_design_id"),
            Str("code", min_len=1, max_len=32),
            Num("target_weight_g", gt=0, le=1500, decimals=2),
            Int("annual_volume_units", ge=1000, le=500000000),
            Num("resin_free_glass_price_per_kg", gt=0, le=10, decimals=4),
            Int("expected_design_version", ge=1),
        ]
    )
    design = require(db.bottle_designs, data["baseline_design_id"], "ERR_BOTTLE_DESIGN_NOT_FOUND")
    # 23 concurrency -> 31 business rule -> 39 uniqueness.
    if int(data["expected_design_version"]) != int(design["version"]):
        fail("ERR_STALE_DESIGN_VERSION")
    if not D(data["target_weight_g"]) < D(design["nominal_weight_g"]):
        fail("ERR_TARGET_WEIGHT_NOT_LIGHTER")
    check_unique(db.programs, "code", data["code"])

    record = base_record()
    record.update(
        {
            "baseline_design_id": design["id"],
            "code": data["code"],
            "target_weight_g": data["target_weight_g"],
            "annual_volume_units": data["annual_volume_units"],
            "resin_free_glass_price_per_kg": data["resin_free_glass_price_per_kg"],
            "status": "DRAFT",
            "weight_saved_g": D("0.00"),
            "gross_savings_usd": D("0.00"),
            "savings_tier": "TIER_A",
            "breakage_risk_delta": D("0.00"),
            "risk_reserve_usd": D("0.00"),
            "net_savings_usd": D("0.00"),
            "customer_rebate_usd": D("0.00"),
            "pilot_decided_by_user_id": None,
        }
    )

    # PRD 3.8: opening a program supersedes every live program on the same baseline.
    for other in ordered(list(db.programs.values())):
        if other["baseline_design_id"] == design["id"] and other["status"] in NON_TERMINAL:
            other["status"] = "SUPERSEDED"
            touch(other)

    db.programs[record["id"]] = record
    touch(design)
    return success(record, 201)


@bp.get("/glass-plant/lightweighting-programs")
def list_programs():
    authorize(*READERS)
    status = query_enum("status", PROGRAM_STATUSES)
    baseline_design_id = query_str("baseline_design_id")
    limit, offset = pagination()
    records = ordered(list(db.programs.values()))
    if baseline_design_id is not None:
        records = [r for r in records if r["baseline_design_id"] == baseline_design_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, meta = paginate(records, limit, offset)
    return success(page, 200, meta)


@bp.get("/glass-plant/lightweighting-programs/<program_id>")
def read_program(program_id):
    authorize(*READERS)
    program = require(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    return success(program)


@bp.post("/glass-plant/lightweighting-programs/<program_id>/assess-risk")
def assess_risk(program_id):
    authorize("QualityEngineer")
    program = require(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    if program["status"] not in ("DRAFT", "SUSPENDED"):
        fail("ERR_PROGRAM_STATE_INVALID")
    design = db.bottle_designs[program["baseline_design_id"]]
    if design["status"] != "APPROVED":
        fail("ERR_DESIGN_STATE_INVALID")

    target_index = design_risk_index(design, weight_override=program["target_weight_g"])
    economics = calc.lightweighting_economics(
        design["nominal_weight_g"],
        program["target_weight_g"],
        program["annual_volume_units"],
        program["resin_free_glass_price_per_kg"],
        design["breakage_risk_index"],
        target_index,
    )
    program.update(economics)
    program["status"] = "RISK_ASSESSED"
    touch(program)
    return success(program)


@bp.post("/glass-plant/lightweighting-programs/<program_id>/customer-decision")
def customer_decision(program_id):
    user_id, _role = authorize("CustomerRep")
    data = validate_body([Enum("decision", ("PILOT", "REJECT"))])
    program = require(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    design = db.bottle_designs[program["baseline_design_id"]]
    if user_id != design["customer_id"]:
        fail("ERR_CUSTOMER_SCOPE_VIOLATION")
    if program["status"] != "RISK_ASSESSED":
        fail("ERR_PROGRAM_STATE_INVALID")

    if data["decision"] == "REJECT":
        # Declining a proposal is always permitted: no cap, no standing rule.
        program["status"] = "REJECTED"
        touch(program)
        return success(program)

    if D(program["breakage_risk_delta"]) > calc.RISK_DELTA_CAP:
        fail("ERR_RISK_DELTA_ABOVE_CAP")
    customer = db.customers[design["customer_id"]]
    if customer["quality_standing"] == "CRITICAL":
        fail(
            "ERR_PROGRAM_STATE_INVALID",
            "A customer in CRITICAL quality standing may not pilot a lightweighting program.",
        )
    program["status"] = "PILOT"
    program["pilot_decided_by_user_id"] = user_id
    touch(program)
    return success(program)


@bp.post("/glass-plant/lightweighting-programs/<program_id>/adopt")
def adopt_program(program_id):
    authorize("PlantManager")
    program = require(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    if program["status"] != "PILOT":
        fail("ERR_PROGRAM_STATE_INVALID")
    design = db.bottle_designs[program["baseline_design_id"]]
    customer = db.customers[design["customer_id"]]
    if customer["quality_standing"] != "GOOD":
        fail(
            "ERR_PROGRAM_STATE_INVALID",
            "Adoption requires the customer's quality standing to be GOOD.",
        )
    program["status"] = "ADOPTED"
    touch(program)
    return success(program)


@bp.post("/glass-plant/lightweighting-programs/<program_id>/suspend")
def suspend_program(program_id):
    authorize("QualityEngineer")
    validate_body([Text("reason", required=False)])
    program = require(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    if program["status"] not in ("PILOT", "ADOPTED"):
        fail("ERR_PROGRAM_STATE_INVALID")
    program["status"] = "SUSPENDED"
    touch(program)
    return success(program)
