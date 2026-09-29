"""PreservationProgram endpoints (PRD 3.1)."""

from decimal import Decimal

from flask import Blueprint

from db import base_row, db
from errors import ApiError
from middleware import authenticate
from response import ok, created
from services import lookup, serialize
from validation import Payload, raw_body

bp = Blueprint("programs", __name__)

AMENDMENT_POLICIES = ("STRICT", "CONDITIONAL")

PROGRAM_FIELDS = (
    "name",
    "soil_weight",
    "size_weight",
    "contiguity_weight",
    "pressure_weight",
    "min_composite_score",
    "max_negotiation_rounds",
    "local_match_min_pct",
    "federal_max_share_pct",
    "impervious_allowance_pct",
    "amendment_policy",
    "monitoring_interval_days",
    "monitoring_grace_days",
    "appraisal_engagement_buffer_days",
)


@bp.post("/preservation-programs")
def create_program():
    authenticate(("ProgramAdmin",))
    payload = Payload(raw_body(), PROGRAM_FIELDS)

    name = payload.string("name", min_len=1, max_len=200)
    soil = payload.decimal("soil_weight", minimum=0, maximum=1)
    size = payload.decimal("size_weight", minimum=0, maximum=1)
    contiguity = payload.decimal("contiguity_weight", minimum=0, maximum=1)
    pressure = payload.decimal("pressure_weight", minimum=0, maximum=1)
    min_score = payload.decimal("min_composite_score", minimum=0, maximum=100)
    max_rounds = payload.integer("max_negotiation_rounds", minimum=1, maximum=10)
    local_match = payload.decimal("local_match_min_pct", minimum=0, maximum=1)
    federal_max = payload.decimal("federal_max_share_pct", minimum=0, maximum=1)
    impervious = payload.decimal("impervious_allowance_pct", minimum=0, maximum="0.25")
    policy = payload.enum("amendment_policy", AMENDMENT_POLICIES)
    interval = payload.integer(
        "monitoring_interval_days", required=False, default=365, minimum=30, maximum=1095
    )
    grace = payload.integer(
        "monitoring_grace_days", required=False, default=30, minimum=0, maximum=365
    )
    buffer_days = payload.integer(
        "appraisal_engagement_buffer_days", required=False, default=3, minimum=0, maximum=30
    )

    if soil + size + contiguity + pressure != Decimal(1):
        raise ApiError(
            "ERR_WEIGHTS_NOT_NORMALIZED",
            "the four scoring weights must sum to exactly 1.00",
        )

    row = base_row()
    row.update(
        {
            "name": name,
            "soil_weight": soil,
            "size_weight": size,
            "contiguity_weight": contiguity,
            "pressure_weight": pressure,
            "min_composite_score": min_score,
            "max_negotiation_rounds": max_rounds,
            "local_match_min_pct": local_match,
            "federal_max_share_pct": federal_max,
            "impervious_allowance_pct": impervious,
            "amendment_policy": policy,
            "monitoring_interval_days": interval,
            "monitoring_grace_days": grace,
            "appraisal_engagement_buffer_days": buffer_days,
            "status": "ACTIVE",
        }
    )
    db.programs[row["id"]] = row
    return created(serialize.program(row))


@bp.get("/preservation-programs/<program_id>")
def read_program(program_id):
    authenticate(
        (
            "ProgramAdmin",
            "AcquisitionOfficer",
            "AppraisalReviewer",
            "StewardshipMonitor",
            "Landowner",
        )
    )
    return ok(serialize.program(lookup.get_program(program_id)))
