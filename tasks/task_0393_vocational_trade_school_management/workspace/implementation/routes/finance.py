"""Routes for AidDisbursement and RefundCase (with OCC + clawback)."""
from flask import Blueprint, request

from db import store
from errors import err
from middleware import require_role, ALL_ROLES
from helpers import (
    get_json_body, serialize, stamp_new, bump, paginate, sorted_collection,
    find_or_404, as_int, as_enum,
)
from response import success
import services

bp = Blueprint("finance", __name__)


# ==========================================================================
# AidDisbursement
# ==========================================================================
@bp.post("/v1/aid-disbursements")
def create_disbursement():
    require_role(["FinancialAidOfficer"])
    body = get_json_body()
    agreement_id = body.get("agreement_id")
    if agreement_id is None or not isinstance(agreement_id, str) or agreement_id == "":
        raise err("ERR_INVALID_REQUEST", "Missing required field: agreement_id")
    agreement = find_or_404(store.enrollment_agreements, agreement_id, "EnrollmentAgreement")

    disbursement_index = as_int(body, "disbursement_index", required=True, minimum=1)
    planned_amount = as_int(body, "planned_amount_cents", required=True, minimum=1)
    gate = as_int(body, "required_clock_hours_gate", required=True, minimum=0)

    # Uniqueness: disbursement_index unique per agreement.
    for d in store.aid_disbursements.values():
        if d["agreement_id"] == agreement_id and d["disbursement_index"] == disbursement_index:
            raise err("ERR_DUPLICATE_KEY", "disbursement_index already exists for agreement.")

    draw = {
        "agreement_id": agreement_id,
        "disbursement_index": disbursement_index,
        "planned_amount_cents": planned_amount,
        "required_clock_hours_gate": gate,
        "amount_cents": 0,
        "status": "SCHEDULED",
    }
    stamp_new(draw)
    store.aid_disbursements[draw["id"]] = draw
    return success(serialize(draw), 201)


@bp.get("/v1/aid-disbursements")
def list_disbursements():
    require_role(ALL_ROLES)
    agreement_id = request.args.get("agreement_id")
    status = request.args.get("status")

    def pred(e):
        if agreement_id and e["agreement_id"] != agreement_id:
            return False
        if status and e["status"] != status:
            return False
        return True

    items = sorted_collection(store.aid_disbursements, predicate=pred)
    page, meta = paginate(items)
    return success([serialize(e) for e in page], 200, pagination=meta)


@bp.get("/v1/aid-disbursements/<did>")
def get_disbursement(did):
    require_role(ALL_ROLES)
    draw = find_or_404(store.aid_disbursements, did, "AidDisbursement")
    return success(serialize(draw), 200)


@bp.post("/v1/aid-disbursements/<did>/release")
def release_disbursement(did):
    require_role(["FinancialAidOfficer"])
    draw = find_or_404(store.aid_disbursements, did, "AidDisbursement")
    if draw["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Disbursement must be SCHEDULED to release.")
    agreement = store.enrollment_agreements[draw["agreement_id"]]
    if agreement["status"] not in ("ENROLLED", "LEAVE_OF_ABSENCE"):
        raise err("ERR_AGREEMENT_NOT_ACTIVE",
                  "Agreement must be ENROLLED or LEAVE_OF_ABSENCE.")

    from decimal import Decimal
    if Decimal(str(agreement["clock_hours_completed"])) < Decimal(str(draw["required_clock_hours_gate"])):
        raise err("ERR_DISBURSEMENT_GATE_UNMET",
                  "Clock hours below required_clock_hours_gate.")

    # Ordering: all lower-index draws RELEASED (unless this is index 1).
    if draw["disbursement_index"] > 1:
        for d in store.aid_disbursements.values():
            if (d["agreement_id"] == agreement["id"]
                    and d["disbursement_index"] < draw["disbursement_index"]
                    and d["status"] != "RELEASED"):
                raise err("ERR_DISBURSEMENT_OUT_OF_ORDER",
                          "A lower-index draw is not yet RELEASED.")

    # Over-award: sum(RELEASED amount) + planned <= scheduled_aid_cents
    released_sum = sum(d["amount_cents"] for d in store.aid_disbursements.values()
                       if d["agreement_id"] == agreement["id"] and d["status"] == "RELEASED")
    if released_sum + draw["planned_amount_cents"] > agreement["scheduled_aid_cents"]:
        raise err("ERR_AID_OVER_AWARD", "Release would exceed scheduled_aid_cents.")

    draw["status"] = "RELEASED"
    draw["amount_cents"] = draw["planned_amount_cents"]
    bump(draw)
    services.recompute_agreement(agreement)
    bump(agreement)
    return success(serialize(draw), 200)


@bp.post("/v1/aid-disbursements/<did>/cancel")
def cancel_disbursement(did):
    require_role(["FinancialAidOfficer"])
    draw = find_or_404(store.aid_disbursements, did, "AidDisbursement")
    if draw["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Disbursement must be SCHEDULED to cancel.")
    draw["status"] = "CANCELLED"
    bump(draw)
    return success(serialize(draw), 200)


# ==========================================================================
# RefundCase
# ==========================================================================
@bp.post("/v1/refund-cases")
def create_refund():
    require_role(["FinancialAidOfficer"])
    body = get_json_body()
    agreement_id = body.get("agreement_id")
    if agreement_id is None or not isinstance(agreement_id, str) or agreement_id == "":
        raise err("ERR_INVALID_REQUEST", "Missing required field: agreement_id")
    agreement = find_or_404(store.enrollment_agreements, agreement_id, "EnrollmentAgreement")

    method = as_enum(body, "method", {"PRO_RATA", "STATE_TABLE"}, required=True)
    withdrawal_term = as_int(body, "withdrawal_term_index", required=True)

    cohort = store.cohorts[agreement["cohort_id"]]
    program = store.programs[agreement["program_id"]]
    if withdrawal_term < cohort["start_term_index"]:
        raise err("ERR_INVALID_REQUEST",
                  "withdrawal_term_index must be >= cohort.start_term_index.")

    if agreement["status"] != "WITHDRAWN":
        raise err("ERR_AGREEMENT_NOT_WITHDRAWN",
                  "Refund computation requires a WITHDRAWN agreement.")

    figures = services.compute_refund(agreement, cohort, program, method, withdrawal_term)
    case = {
        "agreement_id": agreement_id,
        "method": method,
        "withdrawal_term_index": withdrawal_term,
        "tuition_earned_cents": figures["tuition_earned_cents"],
        "tuition_refund_cents": figures["tuition_refund_cents"],
        "aid_return_cents": figures["aid_return_cents"],
        "student_refund_cents": figures["student_refund_cents"],
        "status": "COMPUTED",
    }
    stamp_new(case)
    store.refund_cases[case["id"]] = case
    return success(serialize(case), 201)


@bp.get("/v1/refund-cases")
def list_refunds():
    require_role(ALL_ROLES)
    agreement_id = request.args.get("agreement_id")
    status = request.args.get("status")

    def pred(e):
        if agreement_id and e["agreement_id"] != agreement_id:
            return False
        if status and e["status"] != status:
            return False
        return True

    items = sorted_collection(store.refund_cases, predicate=pred)
    page, meta = paginate(items)
    return success([serialize(e) for e in page], 200, pagination=meta)


@bp.get("/v1/refund-cases/<rid>")
def get_refund(rid):
    require_role(ALL_ROLES)
    case = find_or_404(store.refund_cases, rid, "RefundCase")
    return success(serialize(case), 200)


@bp.post("/v1/refund-cases/<rid>/settle")
def settle_refund(rid):
    require_role(["FinancialAidOfficer"])
    case = find_or_404(store.refund_cases, rid, "RefundCase")
    body = get_json_body()
    # Body well-formedness (priority 4): expected_agreement_version present + int.
    expected = as_int(body, "expected_agreement_version", required=True)

    agreement = store.enrollment_agreements[case["agreement_id"]]

    # OCC (priority 5) runs before any state check / business reconciliation.
    if expected != agreement["version"]:
        raise err("ERR_STALE_VERSION", "Agreement version mismatch.")

    # State (priority 6): case must be COMPUTED.
    if case["status"] != "COMPUTED":
        raise err("ERR_INVALID_STATE", "RefundCase must be COMPUTED to settle.")

    # Business rules (priority 7+).
    if agreement["status"] != "WITHDRAWN":
        raise err("ERR_AGREEMENT_NOT_WITHDRAWN",
                  "Settle requires a WITHDRAWN agreement.")
    for other in store.refund_cases.values():
        if (other["agreement_id"] == agreement["id"]
                and other["id"] != case["id"]
                and other["status"] == "SETTLED"):
            raise err("ERR_REFUND_ALREADY_SETTLED",
                      "Another refund case is already SETTLED for this agreement.")

    case["status"] = "SETTLED"
    bump(case)
    # Clawback cascade: return aid from RELEASED draws, descending index.
    services.settle_clawback(agreement, case["aid_return_cents"])
    services.recompute_agreement(agreement)
    bump(agreement)
    return success(serialize(case), 200)


@bp.post("/v1/refund-cases/<rid>/reverse")
def reverse_refund(rid):
    require_role(["FinancialAidOfficer"])
    case = find_or_404(store.refund_cases, rid, "RefundCase")
    if case["status"] != "COMPUTED":
        raise err("ERR_INVALID_STATE", "RefundCase must be COMPUTED to reverse.")
    case["status"] = "REVERSED"
    bump(case)
    return success(serialize(case), 200)
