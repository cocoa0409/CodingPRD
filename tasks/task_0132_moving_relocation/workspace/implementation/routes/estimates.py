"""Estimate routes — the pricing engine (PRD §3.4, §3.5).

POST /estimates is an OCC write against the parent MoveJob.version
(expected_move_job_version required). Generation snapshots the author, locks
the linked survey, computes every charge component, and increments the job's
version by one. Revise re-runs the engine (cyclic DRAFT<->REVISED). Accept
books the job and supersedes siblings.
"""
from flask import Blueprint, request

import db
from errors import err
from middleware import authenticate, require_roles
from response import object_response, array_response
from serialize import public, public_list
from services import common
from services import calculations

bp = Blueprint("estimates", __name__)

BINDING_TYPES = {"BINDING", "NON_BINDING"}
COVERAGE_TYPES = {"RELEASED", "FULL_VALUE"}


def _linked_packing_total(move_job_id):
    """Most recently created PackingOrder for the job (PRD §3.4: 'the linked
    packing order's packing_total_cents at generation, or 0 if none')."""
    orders = [p for p in db.packing_orders.values() if p["move_job_id"] == move_job_id]
    if not orders:
        return 0
    orders.sort(key=lambda p: (p["created_at"], p["_seq"]))
    return orders[-1]["packing_total_cents"]


def _validate_coverage_inputs(valuation_coverage, declared_value_cents,
                              deductible_cents, survey):
    """Field validity (priority 9) then FULL_VALUE declared-value floor
    (priority 10 -> ERR_DECLARED_VALUE_TOO_LOW)."""
    if not common.is_int(declared_value_cents) or declared_value_cents < 0:
        raise err("ERR_INVALID_FIELD", "declared_value_cents must be a non-negative integer.")
    if not common.is_int(deductible_cents) or deductible_cents < 0:
        raise err("ERR_INVALID_FIELD", "deductible_cents must be a non-negative integer.")

    if valuation_coverage == "FULL_VALUE":
        # Deductible must be in the allowed set AND declared value >= floor.
        if deductible_cents not in calculations.ALLOWED_DEDUCTIBLES:
            raise err("ERR_DECLARED_VALUE_TOO_LOW", "deductible_cents is not an allowed amount.")
        floor = survey["estimated_weight_lbs"] * calculations.MIN_VALUATION_PER_LB_CENTS
        if declared_value_cents < floor:
            raise err("ERR_DECLARED_VALUE_TOO_LOW",
                      "declared_value_cents is below the $6.00/lb minimum.")


@bp.route("/estimates", methods=["POST"])
def create_estimate():
    user_id, role = authenticate()
    require_roles(role, {"Estimator"})
    body = common.get_json_body()
    common.require_fields(body, [
        "move_job_id", "survey_id", "binding_type",
        "valuation_coverage", "expected_move_job_version",
    ])

    # Existence: body FKs left-to-right (PRD §2.5).
    job = common.lookup_fk(db.move_jobs, body["move_job_id"])
    survey = common.lookup_fk(db.surveys, body["survey_id"])

    # Field validity (priority 9).
    common.require_enum(body, "binding_type", BINDING_TYPES)
    common.require_enum(body, "valuation_coverage", COVERAGE_TYPES)

    declared = body.get("declared_value_cents", 0)
    if declared is None:
        declared = 0
    deductible = body.get("deductible_cents", 0)
    if deductible is None:
        deductible = 0

    _validate_coverage_inputs(body["valuation_coverage"], declared, deductible, survey)

    # OCC (priority 17): expected_move_job_version must match job.version.
    expected = body["expected_move_job_version"]
    if not common.is_int(expected):
        raise err("ERR_INVALID_FIELD", "expected_move_job_version must be an integer.")
    if expected != job["version"]:
        raise err("ERR_STALE_VERSION", "MoveJob version has advanced; refresh and retry.")

    packing_total = _linked_packing_total(body["move_job_id"])

    estimate = db.new_common({
        "move_job_id": body["move_job_id"],
        "survey_id": body["survey_id"],
        "estimator_user_id": user_id,
        "binding_type": body["binding_type"],
        "valuation_coverage": body["valuation_coverage"],
        "declared_value_cents": declared,
        "deductible_cents": deductible,
        "linehaul_cents": 0,
        "labor_cents": 0,
        "fuel_surcharge_cents": 0,
        "packing_cents": 0,
        "valuation_premium_cents": 0,
        "accessorial_cents": 0,
        "estimate_total_cents": 0,
        "status": "DRAFT",
    })
    components = calculations.estimate_total(job, survey, estimate, packing_total)
    estimate.update(components)
    db.estimates[estimate["id"]] = estimate

    # Side effects: lock survey, bump job version by one (PRD §2.4 / §3.4).
    survey["locked"] = True
    db.touch(survey)
    db.touch(job)  # increments MoveJob.version by 1

    return object_response(public(estimate), 201)


@bp.route("/estimates/<eid>", methods=["GET"])
def get_estimate(eid):
    user_id, role = authenticate()
    require_roles(role, {"Estimator", "PlatformAdmin", "Customer"})
    record = common.lookup(db.estimates, eid)
    return object_response(public(record), 200)


@bp.route("/estimates", methods=["GET"])
def list_estimates():
    user_id, role = authenticate()
    require_roles(role, {"Estimator", "PlatformAdmin", "Customer"})
    limit, offset = common.parse_pagination()
    move_job_id = request.args.get("move_job_id")
    survey_id = request.args.get("survey_id")
    status = request.args.get("status")
    records = list(db.estimates.values())
    if move_job_id is not None:
        records = [r for r in records if r["move_job_id"] == move_job_id]
    if survey_id is not None:
        records = [r for r in records if r["survey_id"] == survey_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = common.paginate(records, limit, offset)
    return array_response(public_list(page), limit, offset, total, 200)


@bp.route("/estimates/<eid>/revise", methods=["POST"])
def revise_estimate(eid):
    user_id, role = authenticate()
    require_roles(role, {"Estimator"})
    estimate = common.lookup(db.estimates, eid)
    job = common.lookup(db.move_jobs, estimate["move_job_id"])
    survey = common.lookup(db.surveys, estimate["survey_id"])

    # State (priority 6): revise only from DRAFT/REVISED while job is QUOTING.
    if estimate["status"] not in {"DRAFT", "REVISED"}:
        raise err("ERR_INVALID_STATE", "Only DRAFT or REVISED estimates may be revised.")
    if job["job_status"] != "QUOTING":
        raise err("ERR_INVALID_STATE", "Cannot revise once the job has left QUOTING.")

    body = common.get_json_body()

    # Optional new inputs; field validity then declared-value floor (priority 9/10).
    if "binding_type" in body and body["binding_type"] is not None:
        common.require_enum(body, "binding_type", BINDING_TYPES)
        estimate["binding_type"] = body["binding_type"]
    if "valuation_coverage" in body and body["valuation_coverage"] is not None:
        common.require_enum(body, "valuation_coverage", COVERAGE_TYPES)
        estimate["valuation_coverage"] = body["valuation_coverage"]
    if "declared_value_cents" in body and body["declared_value_cents"] is not None:
        if not common.is_int(body["declared_value_cents"]) or body["declared_value_cents"] < 0:
            raise err("ERR_INVALID_FIELD", "declared_value_cents must be a non-negative integer.")
        estimate["declared_value_cents"] = body["declared_value_cents"]
    if "deductible_cents" in body and body["deductible_cents"] is not None:
        if not common.is_int(body["deductible_cents"]) or body["deductible_cents"] < 0:
            raise err("ERR_INVALID_FIELD", "deductible_cents must be a non-negative integer.")
        estimate["deductible_cents"] = body["deductible_cents"]

    _validate_coverage_inputs(
        estimate["valuation_coverage"],
        estimate["declared_value_cents"],
        estimate["deductible_cents"],
        survey,
    )

    packing_total = _linked_packing_total(estimate["move_job_id"])
    components = calculations.estimate_total(job, survey, estimate, packing_total)
    estimate.update(components)
    estimate["status"] = "REVISED"
    db.touch(estimate)  # increments Estimate.version by 1
    return object_response(public(estimate), 200)


@bp.route("/estimates/<eid>/accept", methods=["POST"])
def accept_estimate(eid):
    user_id, role = authenticate()
    require_roles(role, {"Customer"})
    estimate = common.lookup(db.estimates, eid)
    job = common.lookup(db.move_jobs, estimate["move_job_id"])

    # Resource ownership (priority 4): acting customer owns the job.
    if user_id != job["customer_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "You do not own this move job.")

    # State (priority 6): accept only from DRAFT/REVISED; job must be QUOTING.
    if estimate["status"] not in {"DRAFT", "REVISED"}:
        raise err("ERR_INVALID_STATE", "Only a DRAFT or REVISED estimate may be accepted.")
    if job["job_status"] != "QUOTING":
        raise err("ERR_INVALID_STATE", "The job is no longer QUOTING.")

    # Side effects (PRD §3.5).
    estimate["status"] = "ACCEPTED"
    db.touch(estimate)
    job["accepted_estimate_id"] = estimate["id"]
    job["job_status"] = "BOOKED"
    job["gross_charges_cents"] += estimate["estimate_total_cents"]
    common.recompute_balance(job)
    db.touch_updated_only(job)

    # Supersede sibling estimates in DRAFT/REVISED.
    for sib in db.estimates.values():
        if (sib["move_job_id"] == job["id"] and sib["id"] != estimate["id"]
                and sib["status"] in {"DRAFT", "REVISED"}):
            sib["status"] = "SUPERSEDED"
            db.touch(sib)

    return object_response(public(estimate), 200)
