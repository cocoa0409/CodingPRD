"""Donor cost claims, the adjudication waterfall and reversal (PRD 3.9)."""

from flask import Blueprint, g

import calc
import domain
import serialize
from db import db, new_entity, now, touch
from errors import ApiError
from middleware import authenticate
from response import object_response
from validation import forbid, get_body, opt_str, req_date, req_enum, req_int, req_str

bp = Blueprint("claims", __name__)


def find_claim(claim_id):
    row = db.claims.get(claim_id)
    if row is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND", "no DonorCostClaim with id %s" % claim_id)
    return row


def _prior_totals(donor, exclude_claim_id=None):
    """This donor's already-adjudicated lifetime and grant consumption."""
    adjudicated = 0
    grant = 0
    for claim in domain.claims_of_donor(donor):
        if claim["id"] == exclude_claim_id or claim["status"] != "ADJUDICATED":
            continue
        adjudicated += claim["adjudicated_reimbursement_cents"] or 0
        grant += claim["grant_part_cents"] or 0
    return adjudicated, grant


@bp.post("/donor-cost-claims")
def create_claim():
    authenticate(["TransplantCoordinator"])
    body = get_body()
    donor_candidate_id = req_str(body, "donor_candidate_id")
    claim_type = req_enum(body, "claim_type", calc.CLAIM_TYPES)
    coverage_source = req_enum(body, "coverage_source", calc.COVERAGE_SOURCES)
    submitted_amount_cents = req_int(body, "submitted_amount_cents", minimum=1)
    if claim_type == "LOST_WAGES":
        lost_wage_days = req_int(body, "lost_wage_days", minimum=1)
    else:
        forbid(body, "lost_wage_days", "is only accepted for a LOST_WAGES claim")
        lost_wage_days = None
    service_from_on = req_date(body, "service_from_on")
    service_to_on = req_date(body, "service_to_on")
    if service_to_on < service_from_on:
        raise ApiError("ERR_VALIDATION", "service_to_on may not precede service_from_on")

    # priority 5
    donor = db.donors.get(donor_candidate_id)
    if donor is None:
        raise ApiError(
            "ERR_DONOR_NOT_FOUND", "no DonorCandidate with id %s" % donor_candidate_id
        )

    # priority 14 -- only a donor who has actually donated may be reimbursed
    if donor["overall_status"] != "DONATED":
        raise ApiError("ERR_DONOR_NOT_DONATED", "the donor has not donated")

    program = domain.program_of_donor(donor)

    # priority 15 -- single-program containment
    domain.require_same_program(
        [program["id"], g.staff["program_id"] if g.staff is not None else None]
    )

    estimated = calc.estimated_reimbursement(
        claim_type, submitted_amount_cents, lost_wage_days, program
    )

    row = new_entity(
        "DonorCostClaim",
        {
            "donor_candidate_id": donor["id"],
            "claim_type": claim_type,
            "coverage_source": coverage_source,
            "submitted_amount_cents": submitted_amount_cents,
            "lost_wage_days": lost_wage_days,
            "service_from_on": service_from_on.isoformat(),
            "service_to_on": service_to_on.isoformat(),
            "estimated_reimbursement_cents": estimated,
            "adjudicated_reimbursement_cents": None,
            "insurance_part_cents": 0,
            "grant_part_cents": 0,
            "fund_part_cents": 0,
            "unfunded_cents": None,
            "status": "SUBMITTED",
            "adjudicated_at": None,
            "adjudicated_by_user_id": None,
            "reversal_reason_code": None,
        },
    )
    db.claims[row["id"]] = row
    return object_response(serialize.donor_cost_claim(row), 201)


@bp.post("/donor-cost-claims/<claim_id>/adjudication")
def adjudicate(claim_id):
    authenticate(["FinanceAdmin"])
    claim = find_claim(claim_id)

    body = get_body()
    decision = req_enum(body, "decision", calc.CLAIM_DECISIONS)
    decision_reason_code = opt_str(body, "decision_reason_code")
    if decision == "DENY" and decision_reason_code is None:
        raise ApiError("ERR_VALIDATION", "decision_reason_code is required for a denial")

    # priority 8 -- both branches are only reachable from SUBMITTED
    if claim["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "a claim in %s may not be adjudicated" % claim["status"],
        )

    donor = db.donors[claim["donor_candidate_id"]]

    # priority 14
    if donor["overall_status"] != "DONATED":
        raise ApiError("ERR_DONOR_NOT_DONATED", "the claim's donor has not donated")

    program = domain.program_of_donor(donor)
    clock = now()

    if decision == "DENY":
        claim["status"] = "DENIED"
        claim["insurance_part_cents"] = 0
        claim["grant_part_cents"] = 0
        claim["fund_part_cents"] = 0
        claim["adjudicated_reimbursement_cents"] = 0
        claim["unfunded_cents"] = claim["estimated_reimbursement_cents"]
        claim["adjudicated_at"] = clock
        claim["adjudicated_by_user_id"] = g.user_id
        touch(claim)
        return object_response(serialize.donor_cost_claim(claim))

    prior_adjudicated, prior_grant = _prior_totals(donor, exclude_claim_id=claim["id"])

    # priority 24 -- a claim arriving at zero lifetime headroom cannot be approved
    if calc.DONOR_LIFETIME_CAP_CENTS - prior_adjudicated <= 0:
        raise ApiError(
            "ERR_DONOR_LIFETIME_CAP_REACHED",
            "the donor's lifetime reimbursement cap is already exhausted",
        )

    insurance, grant, fund, adjudicated, unfunded = calc.adjudicate_claim(
        claim, prior_adjudicated, prior_grant, domain.fund_remaining_cents(program)
    )

    claim["status"] = "ADJUDICATED"
    claim["insurance_part_cents"] = insurance
    claim["grant_part_cents"] = grant
    claim["fund_part_cents"] = fund
    claim["adjudicated_reimbursement_cents"] = adjudicated
    claim["unfunded_cents"] = unfunded
    claim["adjudicated_at"] = clock
    claim["adjudicated_by_user_id"] = g.user_id
    touch(claim)
    return object_response(serialize.donor_cost_claim(claim))


@bp.post("/donor-cost-claims/<claim_id>/reversal")
def reverse(claim_id):
    authenticate(["FinanceAdmin"])
    claim = find_claim(claim_id)

    body = get_body()
    reversal_reason_code = req_str(body, "reversal_reason_code")

    # priority 9 -- the domain-specific code wins over the generic terminal rule
    if claim["status"] != "ADJUDICATED":
        raise ApiError(
            "ERR_CLAIM_NOT_ADJUDICATED",
            "a claim in %s may not be reversed" % claim["status"],
        )

    # the claim's amounts are retained for audit; leaving ADJUDICATED is what
    # removes it from the fund ledger, the lifetime total and the grant pool.
    claim["status"] = "REVERSED"
    claim["reversal_reason_code"] = reversal_reason_code
    touch(claim)
    return object_response(serialize.donor_cost_claim(claim))
