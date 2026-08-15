"""Distribution runs and Disbursement routes (list/read/reverse).

A distribution run with nothing to do — it would create no disbursements and
would not close the case — is rejected with ERR_NO_DISTRIBUTABLE_SURPLUS; a
run attempted before the case has been sold is ERR_INVALID_CASE_STATE. The
final reconciliation pass (case DEED_RECORDED, surplus zeroed, no FILED or
APPROVED claims remaining) moves the case to CLOSED.

Reversal is the only correction mechanism (PRD §2.11): CLEARED -> REVERSED
with type-dependent compensating effects; books are final once the case is
CLOSED.
"""
from datetime import timedelta
from flask import Blueprint, request

import db
from db import touch
from errors import (err_invalid_case_state, err_no_distributable,
                    err_invalid_disbursement_state)
from middleware import require_roles
from response import success_object, success_list, parse_pagination
from services import calc
from services.domain import (get_case, get_disbursement, view,
                             case_disbursements, case_claims, closed_sale,
                             claim_derived_status)
from services.validate import get_body, check_unknown, req_string
from services.workflow import run_distribution

bp = Blueprint("disbursements", __name__)

DISTRIBUTABLE_STATES = ("SOLD", "DEED_RECORDED")


def _residue_work_pending(case):
    """Whether a borrower-residue disbursement is currently creatable: no
    payable approved claims, surplus still positive, and either the claims
    window has closed or no non-terminal claims exist on the case."""
    eligible = [c for c in case_claims(case["id"])
                if c["status"] == "APPROVED" and c["paid_cents"] < c["approved_amount_cents"]]
    if eligible or case["undistributed_surplus_cents"] <= 0:
        return False
    deadline_passed = False
    sale = closed_sale(case["id"])
    if sale is not None and sale.get("closed_at"):
        close_date = db._parse_iso(sale["closed_at"]).date()
        deadline_passed = (db.CLOCK.now_date()
                           > close_date + timedelta(days=calc.CLAIMS_WINDOW_DAYS))
    non_terminal = [c for c in case_claims(case["id"])
                    if c["status"] == "APPROVED"
                    or (c["status"] == "FILED" and claim_derived_status(c) != "EXPIRED")]
    return deadline_passed or not non_terminal


def _close_eligible(case):
    """Final reconciliation pass: DEED_RECORDED, surplus zeroed, no FILED or
    APPROVED claim remains (EXPIRED is derived-terminal and does not block)."""
    if case["lifecycle_status"] != "DEED_RECORDED":
        return False
    if case["undistributed_surplus_cents"] != 0:
        return False
    open_claims = [c for c in case_claims(case["id"])
                   if c["status"] == "APPROVED"
                   or (c["status"] == "FILED" and claim_derived_status(c) != "EXPIRED")]
    return not open_claims


@bp.route("/api/foreclosure-cases/<case_id>/distribute-surplus", methods=["POST"], strict_slashes=False)
@require_roles("CaseManager")
def distribute_surplus(user_id, role, case_id):
    case = get_case(case_id)
    body = get_body()
    check_unknown(body, set())
    # a run attempted before the case has been sold is a case-state error
    if case["lifecycle_status"] not in DISTRIBUTABLE_STATES:
        raise err_invalid_case_state("distribution requires the case in SOLD or DEED_RECORDED")
    # ERR_NO_DISTRIBUTABLE_SURPLUS per the error catalog: a run with zero
    # undistributed surplus and no payable claims or residue work — unless
    # this run is the final reconciliation pass that closes the case.
    payable = [c for c in case_claims(case["id"])
               if c["status"] == "APPROVED" and c["paid_cents"] < c["approved_amount_cents"]]
    nothing = (case["undistributed_surplus_cents"] == 0 and not payable
               and not _residue_work_pending(case))
    if nothing and not _close_eligible(case):
        raise err_no_distributable()
    created, closes = run_distribution(case)
    case["_dist_run_count"] = case.get("_dist_run_count", 0) + 1
    run_index = case["_dist_run_count"]
    for d in created:
        d["distribution_run_index"] = run_index
    distributed = sum(d["amount_cents"] for d in created)
    if created or closes:
        touch(case)
    return success_object({
        "run_index": run_index,
        "created_disbursement_count": len(created),
        "distributed_cents": distributed,
        "undistributed_surplus_cents": case["undistributed_surplus_cents"],
        "case_status": case["lifecycle_status"],
    })


@bp.route("/api/disbursements", methods=["GET"], strict_slashes=False)
@require_roles("TrusteeAdmin", "CaseManager", "Beneficiary")
def list_disbursements(user_id, role):
    items = list(db.disbursements.values())
    case_id = request.args.get("foreclosure_case_id")
    claim_id = request.args.get("surplus_claim_id")
    recipient_type = request.args.get("recipient_type")
    if case_id is not None:
        items = [d for d in items if d["foreclosure_case_id"] == case_id]
    if claim_id is not None:
        items = [d for d in items if d.get("surplus_claim_id") == claim_id]
    if recipient_type is not None:
        items = [d for d in items if d["recipient_type"] == recipient_type]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    limit, offset = parse_pagination(request.args)
    page = [view(d) for d in items[offset:offset + limit]]
    return success_list(page, limit, offset, len(items))


@bp.route("/api/disbursements/<disbursement_id>", methods=["GET"], strict_slashes=False)
@require_roles("TrusteeAdmin", "CaseManager")
def read_disbursement(user_id, role, disbursement_id):
    return success_object(view(get_disbursement(disbursement_id)))


@bp.route("/api/disbursements/<disbursement_id>/reverse", methods=["POST"], strict_slashes=False)
@require_roles("TrusteeAdmin")
def reverse_disbursement(user_id, role, disbursement_id):
    d = get_disbursement(disbursement_id)
    body = get_body()
    check_unknown(body, {"reversal_reason"})
    reason = req_string(body, "reversal_reason")
    case = get_case(d["foreclosure_case_id"])
    # books are final once the case is CLOSED (case-state family precedes the
    # disbursement-state family in the §2.8 state tier)
    if case["lifecycle_status"] == "CLOSED":
        raise err_invalid_case_state("case is CLOSED; disbursements are final")
    if d["status"] != "CLEARED":
        raise err_invalid_disbursement_state()
    d["status"] = "REVERSED"
    d["reversal_reason"] = reason
    touch(d)
    if d["recipient_type"] == "CLAIMANT" and d.get("surplus_claim_id"):
        claim = db.surplus_claims.get(d["surplus_claim_id"])
        if claim is not None:
            claim["paid_cents"] -= d["amount_cents"]
            # regress PAID -> APPROVED when paid falls below approved
            if (claim["status"] == "PAID" and claim["approved_amount_cents"] is not None
                    and claim["paid_cents"] < claim["approved_amount_cents"]):
                claim["status"] = "APPROVED"
            touch(claim)
    if d["recipient_type"] in ("CLAIMANT", "BORROWER_RESIDUE"):
        case["undistributed_surplus_cents"] += d["amount_cents"]
        touch(case)
    # BENEFICIARY_COST_REIMBURSEMENT reversal is accounting-only: the covered
    # advance remains REIMBURSED (PRD §3.9)
    return success_object(view(d))
