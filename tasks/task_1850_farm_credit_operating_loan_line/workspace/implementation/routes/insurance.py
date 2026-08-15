"""InsurancePolicy and InsuranceClaim endpoints."""
from flask import Blueprint

from db import STORE, get_clock
from errors import raise_err
from middleware import ALL_ROLES, auth, require_owner, require_role
from response import ok_list, ok_object
from routes.loans import get_loan_or_404
from serialize import list_response, ser_claim, ser_policy
from services.core import (claims_of_policy, coverage_remaining_cents,
                           policies_of_borrower, projected_accrued,
                           accrue_interest, standard_cascade, stamp_new,
                           touch)
from util import (as_dt, as_nonneg_int, as_pos_int, as_str, body, need,
                  new_id)

bp = Blueprint("insurance", __name__)

OPEN_CLAIM_STATES = ("REPORTED", "ADJUSTED", "APPROVED", "UNDER_APPEAL")


def get_policy_or_404(pid):
    p = STORE.policies.get(pid)
    if p is None:
        raise_err("ERR_NOT_FOUND", "Insurance policy not found")
    return p


def get_claim_or_404(cid):
    c = STORE.claims.get(cid)
    if c is None:
        raise_err("ERR_NOT_FOUND", "Insurance claim not found")
    return c


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------

@bp.route("/insurance-policies", methods=["POST"])
def create_policy():
    uid, role = auth()
    require_role(role, ["Borrower", "LoanOfficer"])
    b = body()
    borrower_id = as_str(need(b, "borrower_id"), "borrower_id")
    policy_number = as_str(need(b, "policy_number"), "policy_number")
    crop_type = as_str(need(b, "crop_type"), "crop_type")
    county = as_str(need(b, "county"), "county")
    coverage_start = as_dt(need(b, "coverage_start"), "coverage_start")
    coverage_end = as_dt(need(b, "coverage_end"), "coverage_end")
    coverage_amount = as_pos_int(need(b, "coverage_amount_cents"), "coverage_amount_cents")
    if coverage_end <= coverage_start:
        raise_err("ERR_INVALID_REQUEST", "coverage_end must be after coverage_start")
    borrower = STORE.borrowers.get(borrower_id)
    if borrower is None:
        raise_err("ERR_NOT_FOUND", "Borrower not found")
    if role == "Borrower":
        require_owner(borrower_id == uid)
    # Tier 10: half-open coverage windows for same (borrower, crop, county)
    # must not overlap; adjacency allowed. Only ACTIVE policies count.
    for p in policies_of_borrower(borrower_id):
        if p["status"] != "ACTIVE":
            continue
        if p["crop_type"] != crop_type or p["county"] != county:
            continue
        if coverage_start < p["coverage_end"] and p["coverage_start"] < coverage_end:
            raise_err("ERR_COVERAGE_OVERLAP",
                      "Coverage window overlaps an existing ACTIVE policy")
    # Tier 11: policy_number unique per borrower.
    for p in policies_of_borrower(borrower_id):
        if p["policy_number"] == policy_number:
            raise_err("ERR_POLICY_NUMBER_TAKEN",
                      "policy_number already in use for this borrower")
    policy = stamp_new({
        "id": new_id(),
        "borrower_id": borrower_id,
        "assigned_loan_id": None,
        "policy_number": policy_number,
        "crop_type": crop_type,
        "county": county,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "coverage_amount_cents": coverage_amount,
        "status": "ACTIVE",
        "assignment_status": "UNASSIGNED",
    })
    STORE.policies[policy["id"]] = policy
    return ok_object(ser_policy(policy), code=201)


@bp.route("/insurance-policies/<pid>", methods=["GET"])
def get_policy(pid):
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    return ok_object(ser_policy(get_policy_or_404(pid)))


@bp.route("/insurance-policies", methods=["GET"])
def list_policies():
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    page, total, limit, offset, ser = list_response(
        STORE.policies.values(), ser_policy,
        [("borrower_id", lambda e: e["borrower_id"]),
         ("assigned_loan_id", lambda e: e["assigned_loan_id"]),
         ("status", lambda e: e["status"])])
    return ok_list([ser(e) for e in page], limit, offset, total)


@bp.route("/insurance-policies/<pid>/assign", methods=["POST"])
def assign_policy(pid):
    auth_uid, role = auth()
    require_role(role, ["LoanOfficer"])
    b = body()
    loan_account_id = as_str(need(b, "loan_account_id"), "loan_account_id")
    policy = get_policy_or_404(pid)
    loan = STORE.loans.get(loan_account_id)
    if loan is None:
        raise_err("ERR_NOT_FOUND", "Loan account not found")
    # PRD 3.5 order: ACTIVE, not already ASSIGNED, same association, window.
    if policy["status"] != "ACTIVE":
        raise_err("ERR_POLICY_NOT_ACTIVE", "Policy is not ACTIVE")
    if policy["assignment_status"] != "UNASSIGNED":
        raise_err("ERR_POLICY_ALREADY_ASSIGNED", "Policy is not UNASSIGNED")
    borrower = STORE.borrowers.get(policy["borrower_id"])
    if borrower is None or borrower["association_id"] != loan["association_id"]:
        raise_err("ERR_CROSS_ASSOCIATION_REFERENCE",
                  "Loan and policy belong to different associations")
    if not (policy["coverage_start"] <= get_clock()
            and policy["coverage_end"] >= loan["maturity_date"]):
        raise_err("ERR_INVALID_REQUEST",
                  "Coverage window must contain the loan season")
    policy["assignment_status"] = "ASSIGNED"
    policy["assigned_loan_id"] = loan["id"]
    touch(policy)
    return ok_object(ser_policy(policy))


@bp.route("/insurance-policies/<pid>/cancel", methods=["POST"])
def cancel_policy(pid):
    uid, role = auth()
    require_role(role, ["Borrower", "LoanOfficer"])
    policy = get_policy_or_404(pid)
    if role == "Borrower":
        require_owner(policy["borrower_id"] == uid)
    if policy["status"] != "ACTIVE":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only an ACTIVE policy can be cancelled")
    for c in claims_of_policy(pid):
        if c["status"] in OPEN_CLAIM_STATES:
            raise_err("ERR_INVALID_STATE_TRANSITION",
                      "Policy has an open insurance claim")
    policy["status"] = "CANCELLED"
    if policy["assignment_status"] == "ASSIGNED":
        policy["assignment_status"] = "RELEASED"
        policy["assigned_loan_id"] = None
    touch(policy)
    return ok_object(ser_policy(policy))


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------

@bp.route("/insurance-claims", methods=["POST"])
def create_claim():
    uid, role = auth()
    require_role(role, ["Borrower", "LoanOfficer"])
    b = body()
    policy_id = as_str(need(b, "policy_id"), "policy_id")
    loan_account_id = as_str(need(b, "loan_account_id"), "loan_account_id")
    claimed_loss = as_pos_int(need(b, "claimed_loss_cents"), "claimed_loss_cents")
    policy = STORE.policies.get(policy_id)
    if policy is None:
        raise_err("ERR_NOT_FOUND", "Insurance policy not found")
    loan = STORE.loans.get(loan_account_id)
    if loan is None:
        raise_err("ERR_NOT_FOUND", "Loan account not found")
    if role == "Borrower":
        require_owner(loan["borrower_id"] == uid)
    # Tier 12: cross-aggregate integrity first.
    borrower = STORE.borrowers.get(policy["borrower_id"])
    if borrower is None or borrower["association_id"] != loan["association_id"]:
        raise_err("ERR_CROSS_ASSOCIATION_REFERENCE",
                  "Policy and loan belong to different associations")
    if policy["status"] != "ACTIVE":
        raise_err("ERR_POLICY_NOT_ACTIVE", "Policy is CANCELLED")
    if (policy["assignment_status"] != "ASSIGNED"
            or policy["assigned_loan_id"] != loan_account_id):
        raise_err("ERR_POLICY_NOT_ASSIGNED_TO_LOAN",
                  "Policy is not ASSIGNED to this loan")
    claim = stamp_new({
        "id": new_id(),
        "policy_id": policy_id,
        "loan_account_id": loan_account_id,
        "claimed_loss_cents": claimed_loss,
        "adjuster_approved_cents": None,
        "indemnity_to_lender_cents": None,
        "applied_interest_cents": None,
        "applied_principal_cents": None,
        "remitted_to_borrower_cents": None,
        "status": "REPORTED",
    })
    STORE.claims[claim["id"]] = claim
    return ok_object(ser_claim(claim), code=201)


@bp.route("/insurance-claims/<cid>", methods=["GET"])
def get_claim(cid):
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    return ok_object(ser_claim(get_claim_or_404(cid)))


@bp.route("/insurance-claims", methods=["GET"])
def list_claims():
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    page, total, limit, offset, ser = list_response(
        STORE.claims.values(), ser_claim,
        [("policy_id", lambda e: e["policy_id"]),
         ("loan_account_id", lambda e: e["loan_account_id"]),
         ("status", lambda e: e["status"])])
    return ok_list([ser(e) for e in page], limit, offset, total)


@bp.route("/insurance-claims/<cid>/adjuster_report", methods=["POST"])
def adjuster_report(cid):
    auth_uid, role = auth()
    require_role(role, ["InsuranceAdjuster"])
    b = body()
    approved = as_nonneg_int(need(b, "adjuster_approved_cents"), "adjuster_approved_cents")
    claim = get_claim_or_404(cid)
    if claim["status"] not in ("REPORTED", "UNDER_APPEAL"):
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Adjuster report requires REPORTED or UNDER_APPEAL status")
    policy = get_policy_or_404(claim["policy_id"])
    if approved > coverage_remaining_cents(policy):
        raise_err("ERR_CLAIM_EXCEEDS_COVERAGE",
                  "adjuster_approved_cents exceeds remaining coverage")
    claim["adjuster_approved_cents"] = approved
    claim["status"] = "ADJUSTED"
    touch(claim)
    return ok_object(ser_claim(claim))


@bp.route("/insurance-claims/<cid>/approve", methods=["POST"])
def approve_claim(cid):
    auth_uid, role = auth()
    require_role(role, ["InsuranceAdjuster"])
    claim = get_claim_or_404(cid)
    if claim["status"] != "ADJUSTED":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only an ADJUSTED claim can be approved")
    claim["status"] = "APPROVED"
    touch(claim)
    return ok_object(ser_claim(claim))


@bp.route("/insurance-claims/<cid>/deny", methods=["POST"])
def deny_claim(cid):
    auth_uid, role = auth()
    require_role(role, ["InsuranceAdjuster"])
    claim = get_claim_or_404(cid)
    if claim["status"] not in ("REPORTED", "ADJUSTED", "UNDER_APPEAL"):
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Claim cannot be denied from its current status")
    claim["status"] = "DENIED"
    touch(claim)
    return ok_object(ser_claim(claim))


@bp.route("/insurance-claims/<cid>/appeal", methods=["POST"])
def appeal_claim(cid):
    uid, role = auth()
    require_role(role, ["Borrower", "LoanOfficer"])
    claim = get_claim_or_404(cid)
    if role == "Borrower":
        loan = get_loan_or_404(claim["loan_account_id"])
        require_owner(loan["borrower_id"] == uid)
    if claim["status"] != "APPROVED":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only an APPROVED claim can be appealed")
    claim["status"] = "UNDER_APPEAL"
    touch(claim)
    return ok_object(ser_claim(claim))


@bp.route("/insurance-claims/<cid>/pay", methods=["POST"])
def pay_claim(cid):
    auth_uid, role = auth()
    require_role(role, ["LoanOfficer"])
    claim = get_claim_or_404(cid)
    if claim["status"] != "APPROVED":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only an APPROVED claim can be paid")
    loan = get_loan_or_404(claim["loan_account_id"])
    if loan["status"] not in ("ACTIVE", "RESTRUCTURING"):
        raise_err("ERR_LOAN_NOT_ACTIVE",
                  "Claim payment requires loan status ACTIVE or RESTRUCTURING")
    policy = get_policy_or_404(claim["policy_id"])
    indemnity = min(claim["adjuster_approved_cents"], coverage_remaining_cents(policy))
    accrue_interest(loan)
    applied_interest = min(indemnity, loan["accrued_interest_cents"])
    applied_principal = min(indemnity - applied_interest,
                            loan["outstanding_principal_cents"])
    remitted = indemnity - applied_interest - applied_principal
    loan["accrued_interest_cents"] -= applied_interest
    loan["outstanding_principal_cents"] -= applied_principal
    claim["indemnity_to_lender_cents"] = indemnity
    claim["applied_interest_cents"] = applied_interest
    claim["applied_principal_cents"] = applied_principal
    claim["remitted_to_borrower_cents"] = remitted
    claim["status"] = "PAID"
    touch(claim)
    if (loan["status"] == "ACTIVE" and loan["outstanding_principal_cents"] == 0
            and loan["accrued_interest_cents"] == 0):
        loan["status"] = "PAID_OFF"
    touch(loan)
    standard_cascade(loan)
    return ok_object(ser_claim(claim))
