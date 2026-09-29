"""Compliance measurements and the retier cascade (PRD section 3.8)."""

from decimal import Decimal

from flask import Blueprint

from db import db, ordered
from enums import MEASUREMENT_STATUSES
from errors import ApiError
from middleware import ALL_ROLES, COMPLIANCE_ANALYST, authenticate
from response import list_response, object_response
from services.calc import aggregate_measurement, qualified_tier_code
from services.cascade import requalification_retier_cascade
from services.lookup import get_measurement, resolve_body_fks
from validation import (
    bad,
    body_json,
    field_date,
    field_int,
    field_string,
    paginate,
    pagination,
    query_enum,
    query_string,
)

measurements_bp = Blueprint("measurements", __name__)

MEASURABLE_ELECTION_STATUSES = ("ACTIVE", "REQUAL_REVIEW")
# A SUPERSEDED measurement releases its period for a fresh attempt.
PERIOD_BLOCKING_STATUSES = ("DRAFT", "PRELIMINARY", "FINAL")


def _apply_variant(measurement, commitment, variant):
    """Run the shared aggregation and derive the qualified tier from its output."""
    figures = aggregate_measurement(
        commitment, measurement["period_start"], measurement["period_end"], variant
    )
    measurement.update(figures)
    contract = db.contracts.get(commitment["contract_id"])
    if contract is None:
        measurement["qualified_tier_code"] = None
    else:
        measurement["qualified_tier_code"] = qualified_tier_code(
            contract, figures["compliance_pct"], figures["measured_volume_units"]
        )
    return figures


@measurements_bp.route("/gpo/compliance-measurements", methods=["POST"])
def create_measurement():
    authenticate((COMPLIANCE_ANALYST,))
    body = body_json()
    resolved = resolve_body_fks(body, ("commitment_id",))
    commitment = resolved["commitment_id"]
    if commitment is None:
        raise bad("Field 'commitment_id' is required.")

    period_start = field_date(body, "period_start")
    period_end = field_date(body, "period_end")
    expected_commitment_version = field_int(body, "expected_commitment_version", minimum=0)

    if commitment["election_status"] not in MEASURABLE_ELECTION_STATUSES:
        raise ApiError(
            "ERR_COMMITMENT_NOT_ACTIVE",
            "Only an ACTIVE or REQUAL_REVIEW commitment can be measured.",
        )
    if expected_commitment_version != commitment["version"]:
        raise ApiError(
            "ERR_STALE_COMMITMENT_VERSION",
            "expected_commitment_version does not match the commitment's current version.",
        )
    for existing in db.measurements.values():
        if existing["commitment_id"] != commitment["id"]:
            continue
        if existing["status"] not in PERIOD_BLOCKING_STATUSES:
            continue
        if (
            existing["period_start"] == period_start
            and existing["period_end"] == period_end
        ):
            raise ApiError(
                "ERR_DUPLICATE_MEASUREMENT_PERIOD",
                "A live measurement already covers this period for the commitment.",
            )
    if period_end <= period_start:
        raise ApiError(
            "ERR_EFFECTIVE_WINDOW_INVALID", "period_end must be strictly after period_start."
        )

    row = db.new_row()
    row.update(
        {
            "commitment_id": commitment["id"],
            "period_start": period_start,
            "period_end": period_end,
            "status": "DRAFT",
            "on_contract_spend_cents": 0,
            "leakage_spend_cents": 0,
            "unmatched_spend_cents": 0,
            "total_category_spend_cents": 0,
            "compliance_pct": Decimal("0.00"),
            "preliminary_compliance_pct": None,
            "measured_volume_units": 0,
            "qualified_tier_code": None,
            "basis_empty": False,
            "computed_variant": None,
        }
    )
    db.measurements[row["id"]] = row
    # Opening a measurement pins the commitment snapshot it was computed against.
    db.touch(commitment)
    return object_response(row, 201)


@measurements_bp.route("/gpo/compliance-measurements/<measurement_id>", methods=["GET"])
def read_measurement(measurement_id):
    authenticate(ALL_ROLES)
    return object_response(get_measurement(measurement_id))


@measurements_bp.route("/gpo/compliance-measurements", methods=["GET"])
def list_measurements():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    commitment_id = query_string("commitment_id")
    status = query_enum("status", MEASUREMENT_STATUSES)
    rows = [
        row
        for row in ordered(db.measurements.values())
        if (commitment_id is None or row["commitment_id"] == commitment_id)
        and (status is None or row["status"] == status)
    ]
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


@measurements_bp.route(
    "/gpo/compliance-measurements/<measurement_id>/measure", methods=["POST"]
)
def measure_measurement(measurement_id):
    authenticate((COMPLIANCE_ANALYST,))
    measurement = get_measurement(measurement_id)
    if measurement["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_MEASUREMENT_STATE", "Only a DRAFT measurement can be measured."
        )
    commitment = db.commitments.get(measurement["commitment_id"])
    if commitment is None:
        raise ApiError("ERR_COMMITMENT_NOT_FOUND", "The measured commitment no longer exists.")
    figures = _apply_variant(measurement, commitment, "PRELIMINARY")
    # The preliminary figure is retained on the row as the audit trail.
    measurement["preliminary_compliance_pct"] = figures["compliance_pct"]
    measurement["status"] = "PRELIMINARY"
    db.touch(measurement)
    return object_response(measurement)


@measurements_bp.route(
    "/gpo/compliance-measurements/<measurement_id>/finalize", methods=["POST"]
)
def finalize_measurement(measurement_id):
    authenticate((COMPLIANCE_ANALYST,))
    measurement = get_measurement(measurement_id)
    if measurement["status"] != "PRELIMINARY":
        raise ApiError(
            "ERR_INVALID_MEASUREMENT_STATE", "Only a PRELIMINARY measurement can be finalized."
        )
    commitment = db.commitments.get(measurement["commitment_id"])
    if commitment is None:
        raise ApiError("ERR_COMMITMENT_NOT_FOUND", "The measured commitment no longer exists.")
    if commitment["election_status"] != "REQUAL_REVIEW":
        raise ApiError(
            "ERR_COMMITMENT_NOT_IN_REQUAL_REVIEW",
            "Finalizing requires the commitment to be in REQUAL_REVIEW.",
        )

    # Hop 1 -- the final variant overwrites compliance_pct, preserving the
    # preliminary figure already stored on the row.
    preliminary = measurement["preliminary_compliance_pct"]
    _apply_variant(measurement, commitment, "FINAL")
    measurement["preliminary_compliance_pct"] = preliminary
    measurement["status"] = "FINAL"
    db.touch(measurement)

    # Hop 2 -- the retier itself, closing the requalification cycle.
    previous_tier_code = commitment["current_tier_code"]
    commitment["last_final_compliance_pct"] = measurement["compliance_pct"]
    commitment["current_tier_code"] = measurement["qualified_tier_code"]
    commitment["requalification_round"] = commitment["requalification_round"] + 1
    commitment["election_status"] = "ACTIVE"
    db.touch(commitment)

    # Hops 3, 4 and 5 -- only when the governing tier actually moved.
    requalification_retier_cascade(commitment, previous_tier_code)
    return object_response(measurement)


@measurements_bp.route(
    "/gpo/compliance-measurements/<measurement_id>/supersede", methods=["POST"]
)
def supersede_measurement(measurement_id):
    authenticate((COMPLIANCE_ANALYST,))
    measurement = get_measurement(measurement_id)
    body = body_json()
    field_string(body, "reason", 0, None, required=False, default=None)
    if measurement["status"] not in ("DRAFT", "PRELIMINARY"):
        raise ApiError(
            "ERR_INVALID_MEASUREMENT_STATE",
            "Only a DRAFT or PRELIMINARY measurement can be superseded.",
        )
    measurement["status"] = "SUPERSEDED"
    db.touch(measurement)
    return object_response(measurement)
