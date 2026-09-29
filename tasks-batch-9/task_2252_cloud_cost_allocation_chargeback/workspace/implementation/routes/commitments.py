"""Commitment purchase, activation and re-evaluation (PRD 3.4)."""
from flask import Blueprint

from db import add_hours, base_fields, db, now, touch
from errors import fail
from middleware import authorize
from routes.common import lookup, serve, serve_list
from services import derived, flows
from services.calc import (
    COMMITMENT_BUFFER_HOURS,
    D,
    HOURS_PER_PERIOD,
    REGION_MAX_HOURLY_COMMIT_CENTS,
    pct2,
)
from validation import body, present, req_enum, req_int, req_interval, req_number, req_str

bp = Blueprint("commitments", __name__)

TYPES = ("RESERVED_INSTANCE", "SAVINGS_PLAN")
KINDS = ("COMPUTE", "DATABASE", "STORAGE")
LIVE_STATUSES = ("PENDING", "ACTIVE", "UNDER_UTILIZED")
READERS = ("FinOpsController", "FinOpsAnalyst", "PlatformAdmin")


@bp.route("/finops/commitments", methods=["POST"])
@authorize("FinOpsController")
def purchase_commitment():
    data = body()
    commitment_type = req_enum(data, "commitment_type", TYPES)
    region = req_str(data, "region")
    (start_raw, start), (end_raw, end) = req_interval(data, "term_start", "term_end")
    hourly = req_int(data, "hourly_commit_cents", exclusive_minimum=0)

    if commitment_type == "RESERVED_INSTANCE":
        covered_kind = req_enum(data, "covered_resource_kind", KINDS)
    else:
        if present(data, "covered_resource_kind"):
            fail(
                "ERR_INVALID_REQUEST",
                "covered_resource_kind must be absent for a SAVINGS_PLAN.",
            )
        covered_kind = None

    coverage_target = (
        pct2(req_number(data, "coverage_target_pct", minimum=0))
        if present(data, "coverage_target_pct")
        else 80.00
    )
    utilization_target = (
        pct2(req_number(data, "utilization_target_pct", minimum=0))
        if present(data, "utilization_target_pct")
        else 85.00
    )

    for other in db.commitments.values():
        if other["commitment_type"] != commitment_type or other["region"] != region:
            continue
        if other["status"] not in LIVE_STATUSES:
            continue
        padded_start = add_hours(other["_term_start_dt"], -COMMITMENT_BUFFER_HOURS)
        padded_end = add_hours(other["_term_end_dt"], COMMITMENT_BUFFER_HOURS)
        if start <= padded_end and padded_start <= end:
            fail(
                "ERR_COMMITMENT_WINDOW_CONFLICT",
                "The requested term falls inside the 24-hour buffer around commitment %s."
                % other["id"],
            )

    regional = hourly + sum(
        c["hourly_commit_cents"]
        for c in db.commitments.values()
        if c["region"] == region and c["status"] in LIVE_STATUSES
    )
    if regional > REGION_MAX_HOURLY_COMMIT_CENTS:
        fail(
            "ERR_COMMITMENT_CAPACITY_EXCEEDED",
            "Region %s would exceed the aggregate hourly commit cap." % region,
        )

    commitment = base_fields()
    commitment.update(
        {
            "commitment_type": commitment_type,
            "region": region,
            "covered_resource_kind": covered_kind,
            "term_start": start_raw,
            "term_end": end_raw,
            "hourly_commit_cents": hourly,
            "coverage_target_pct": coverage_target,
            "utilization_target_pct": utilization_target,
            "status": "PENDING",
            "committed_capacity_cents": hourly * HOURS_PER_PERIOD,
            "covered_spend_cents": 0,
            "total_discount_cents": 0,
            "waste_cents": 0,
            "coverage_pct": 0.00,
            "utilization_pct": 0.00,
            "_term_start_dt": start,
            "_term_end_dt": end,
            "_in_scope_list_total": 0,
        }
    )
    db.commitments[commitment["id"]] = commitment
    return serve(commitment, 201)


@bp.route("/finops/commitments", methods=["GET"])
@authorize(*READERS)
def list_commitments():
    return serve_list(
        db.commitments.values(),
        {"commitment_type": "commitment_type", "region": "region", "status": "status"},
    )


@bp.route("/finops/commitments/<commitment_id>", methods=["GET"])
@authorize(*READERS)
def get_commitment(commitment_id):
    return serve(lookup("commitments", commitment_id))


@bp.route("/finops/commitments/<commitment_id>/activate", methods=["POST"])
@authorize("FinOpsController")
def activate_commitment(commitment_id):
    commitment = lookup("commitments", commitment_id)
    if commitment["status"] != "PENDING":
        fail("ERR_COMMITMENT_STATE_INVALID", "Only a PENDING commitment may be activated.")
    if now() > commitment["_term_end_dt"]:
        fail(
            "ERR_COMMITMENT_STATE_INVALID",
            "The commitment term has already elapsed.",
        )
    flows.apply_commitment_waterfall(commitment)
    return serve(commitment)


@bp.route("/finops/commitments/<commitment_id>/evaluate", methods=["POST"])
@authorize("FinOpsController")
def evaluate_commitment(commitment_id):
    commitment = lookup("commitments", commitment_id)
    if commitment["status"] not in ("ACTIVE", "UNDER_UTILIZED"):
        fail(
            "ERR_COMMITMENT_STATE_INVALID",
            "Only an ACTIVE or UNDER_UTILIZED commitment may be evaluated.",
        )

    values = derived.commitment_values(commitment)
    if now() > commitment["_term_end_dt"]:
        values["status"] = "EXPIRED"
    elif D(values["utilization_pct"]) < D(commitment["utilization_target_pct"]):
        values["status"] = "UNDER_UTILIZED"
    else:
        values["status"] = "ACTIVE"
    commitment.update(values)
    touch(commitment)
    return serve(commitment)
