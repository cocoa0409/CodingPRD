"""Insurance claim endpoints — filing, segregation of duties, payment (PRD §3.8)."""

from flask import Blueprint, request

from db import store
from middleware import (
    require_roles, ALL_ROLES, ROLE_FARM_MANAGER, ROLE_INSURANCE_ADJUSTER,
)
from response import success_object, success_list, parse_pagination
from util import get_body, check_unknown_fields, req_str, req_int, req_num, req_enum
from errors import (
    invalid_state, segregation_of_duties, ApiError,
    ERR_DUPLICATE_CLAIM, ERR_PLAN_NOT_COMPLETE,
)
from services.core import (
    base_record, touch, public, get_claim, get_plan,
    compute_guarantee_lbs, indemnity_cents, filtered_sorted, CLAIM_STATUSES,
)

bp = Blueprint("insurance_claims", __name__)

IA = [ROLE_INSURANCE_ADJUSTER]


def _check_sod(claim, user_id):
    """Priority 5: the caller's X-User-ID must differ from filed_by_user_id."""
    if user_id == claim["filed_by_user_id"]:
        raise segregation_of_duties()


@bp.route("/api/insurance-claims", methods=["POST"])
def create_claim():
    role, user_id = require_roles([ROLE_FARM_MANAGER])
    body = get_body()
    check_unknown_fields(body, {"planting_plan_id", "price_election_cents_per_lb",
                                "coverage_pct"})
    planting_plan_id = req_str(body, "planting_plan_id")
    price_election = req_int(body, "price_election_cents_per_lb", min_v=1)
    coverage = req_num(body, "coverage_pct", gt=0, lte=1) if "coverage_pct" in body else None
    if coverage is None:
        coverage = 0.75

    plan = get_plan(planting_plan_id)
    if plan["status"] not in ("GROWING", "HARVESTING", "COMPLETE"):
        raise invalid_state("Plan is not GROWING, HARVESTING, or COMPLETE")

    # at most one open claim per plan
    for c in store.insurance_claims.values():
        if (c["planting_plan_id"] == planting_plan_id
                and c["status"] in ("FILED", "UNDER_REVIEW", "APPROVED")):
            raise ApiError(ERR_DUPLICATE_CLAIM, 422,
                           "An open claim already exists for this plan")

    guarantee = compute_guarantee_lbs(plan, coverage)
    # preliminary variant: production := projected yield; pinned at filing
    estimate = indemnity_cents(guarantee, plan["projected_yield_lbs"], price_election)

    rec = base_record()
    rec.update({
        "planting_plan_id": planting_plan_id,
        "price_election_cents_per_lb": price_election,
        "coverage_pct": coverage,
        "guarantee_lbs": guarantee,
        "indemnity_estimate_cents": estimate,
        "filed_by_user_id": user_id,
        "indemnity_final_cents": None,
        "status": "FILED",
    })
    store.insurance_claims[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/api/insurance-claims/<claim_id>", methods=["GET"])
def get_claim_endpoint(claim_id):
    require_roles(ALL_ROLES)
    return success_object(public(get_claim(claim_id)))


@bp.route("/api/insurance-claims", methods=["GET"])
def list_claims():
    require_roles(ALL_ROLES)
    records = filtered_sorted(list(store.insurance_claims.values()), request.args, {
        "planting_plan_id": ("str", "planting_plan_id"),
        "status": ("enum", "status", CLAIM_STATUSES),
    })
    limit, offset = parse_pagination(request.args)
    total = len(records)
    page = records[offset:offset + limit]
    return success_list([public(r) for r in page], limit, offset, total)


@bp.route("/api/insurance-claims/<claim_id>/begin-review", methods=["POST"])
def begin_review(claim_id):
    role, user_id = require_roles(IA)
    check_unknown_fields(get_body(), set())
    claim = get_claim(claim_id)
    _check_sod(claim, user_id)
    if claim["status"] != "FILED":
        raise invalid_state("Claim is not FILED")
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return success_object(public(claim))


@bp.route("/api/insurance-claims/<claim_id>/decide", methods=["POST"])
def decide_claim(claim_id):
    role, user_id = require_roles(IA)
    body = get_body()
    check_unknown_fields(body, {"outcome"})
    outcome = req_enum(body, "outcome", {"APPROVED", "DENIED"})

    claim = get_claim(claim_id)
    _check_sod(claim, user_id)
    if claim["status"] != "UNDER_REVIEW":
        raise invalid_state("Claim is not UNDER_REVIEW")
    claim["status"] = outcome
    touch(claim)
    return success_object(public(claim))


@bp.route("/api/insurance-claims/<claim_id>/pay", methods=["POST"])
def pay_claim(claim_id):
    role, user_id = require_roles(IA)
    check_unknown_fields(get_body(), set())
    claim = get_claim(claim_id)
    _check_sod(claim, user_id)
    if claim["status"] != "APPROVED":
        raise invalid_state("Claim is not APPROVED")
    plan = get_plan(claim["planting_plan_id"])
    if plan["status"] != "COMPLETE":
        raise ApiError(ERR_PLAN_NOT_COMPLETE, 422,
                       "The linked plan is not COMPLETE")

    # final variant: production := actual kiln-dried yield
    claim["indemnity_final_cents"] = indemnity_cents(
        claim["guarantee_lbs"], plan["actual_yield_lbs"],
        claim["price_election_cents_per_lb"])
    claim["status"] = "PAID"
    touch(claim)
    return success_object(public(claim))
