"""The consumer remedy ledger and its four-link credit cascade (PRD 3.8)."""

from flask import Blueprint

import auth
import calc
import lookups
import responses
import shapes
import store
from errors import raise_error

bp = Blueprint("claims", __name__)

REMEDY_TYPES = ("REPAIR", "REPLACE", "REFUND", "RETROFIT_KIT")
CLAIM_STATUSES = ("SUBMITTED", "APPROVED", "FULFILLED", "VOID")
NEGOTIABLE_CASE_STATUSES = ("ASSESSMENT_OPEN", "OFFER_MADE", "COUNTERED")

ROLES = ("ProgramAdmin", "ComplianceOfficer", "SafetyDirector", "PenaltyCounsel")


def linked_penalty_case(recall):
    for case in store.ordered(store.penalty_cases):
        if (case["section_report_id"] == recall["section_report_id"]
                and case["status"] in NEGOTIABLE_CASE_STATUSES):
            return case
    return None


@bp.route("/remedy-claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    auth.authorize(*ROLES)
    return responses.object_response(lookups.find("remedy_claim", claim_id))


@bp.route("/remedy-claims", methods=["GET"])
def list_claims():
    auth.authorize(*ROLES)
    limit, offset = shapes.pagination()
    recall_id = shapes.q_str("recall_id")
    status = shapes.q_enum("status", CLAIM_STATUSES)
    remedy_type = shapes.q_enum("remedy_type", REMEDY_TYPES)

    def keep(row):
        if recall_id is not None and row["recall_id"] != recall_id:
            return False
        if status is not None and row["status"] != status:
            return False
        if remedy_type is not None and row["remedy_type"] != remedy_type:
            return False
        return True

    return responses.list_response(
        store.ordered(store.remedy_claims, keep), limit, offset)


@bp.route("/remedy-claims", methods=["POST"])
def create_claim():
    auth.authorize("ComplianceOfficer")
    data = shapes.body()
    recall_id = shapes._req(data, "recall_id")
    consumer_ref = shapes.req_str(data, "consumer_ref", 1, 64)
    remedy_type = shapes.req_enum(data, "remedy_type", REMEDY_TYPES)
    quantity = shapes.req_int(data, "quantity", minimum=1)
    unit_price_cents = shapes.req_money(data, "unit_price_cents")
    shipping_cents_per_unit = shapes.req_money(data, "shipping_cents_per_unit")

    recall = lookups.find("recall", recall_id)
    if recall["plan_status"] not in ("APPROVED", "MONITORING"):
        raise_error("ERR_RECALL_PLAN_STATE_INVALID")

    if remedy_type not in recall["remedy_options"]:
        raise_error("ERR_REMEDY_OPTION_NOT_OFFERED")

    if quantity > recall["units_outstanding"]:
        raise_error("ERR_UNITS_OUTSTANDING_EXCEEDED")

    row = store.new_row(
        recall_id=recall_id,
        consumer_ref=consumer_ref,
        remedy_type=remedy_type,
        quantity=quantity,
        unit_price_cents=unit_price_cents,
        shipping_cents_per_unit=shipping_cents_per_unit,
        reimbursement_total_cents=calc.reimbursement_total(
            remedy_type, unit_price_cents, shipping_cents_per_unit, quantity),
        status="SUBMITTED",
        fulfilled_at=None,
        voided_at=None,
    )
    store.remedy_claims[row["id"]] = row
    return responses.created(row)


@bp.route("/remedy-claims/<claim_id>/approve", methods=["POST"])
def approve_claim(claim_id):
    auth.authorize("ComplianceOfficer", "SafetyDirector")
    claim = lookups.find("remedy_claim", claim_id)
    shapes.body()

    if claim["status"] != "SUBMITTED":
        raise_error("ERR_CLAIM_STATE_INVALID")

    recall = lookups.maybe("recall", claim["recall_id"])
    if recall is not None and claim["quantity"] > recall["units_outstanding"]:
        raise_error("ERR_UNITS_OUTSTANDING_EXCEEDED")

    claim["status"] = "APPROVED"
    store.touch(claim)
    return responses.object_response(claim)


@bp.route("/remedy-claims/<claim_id>/fulfill", methods=["POST"])
def fulfill_claim(claim_id):
    auth.authorize("ComplianceOfficer")
    claim = lookups.find("remedy_claim", claim_id)
    shapes.body()

    if claim["status"] != "APPROVED":
        raise_error("ERR_CLAIM_STATE_INVALID")

    recall = lookups.maybe("recall", claim["recall_id"])
    if recall is None or recall["plan_status"] not in ("APPROVED", "MONITORING"):
        raise_error("ERR_RECALL_PLAN_STATE_INVALID")

    # Link 1: the claim itself.
    claim["status"] = "FULFILLED"
    claim["fulfilled_at"] = store.now_logical()
    store.touch(claim)

    # Link 2: the recall's conserved unit ledger.
    recall["units_corrected"] = recall["units_corrected"] + claim["quantity"]
    recall["units_outstanding"] = recall["units_outstanding"] - claim["quantity"]

    # Link 3: the effectiveness flag, always on the units basis.
    model = lookups.model_for_recall(recall)
    rate = calc.effectiveness_rate(recall, "UNITS_BASIS", model)
    became_met = False
    if (recall["effectiveness_flag"] == "PENDING"
            and rate >= recall["participation_goal_pct"]):
        recall["effectiveness_flag"] = "MET"
        became_met = True
    store.touch(recall)

    # Link 4: the linked civil penalty case earns the cooperation bonus.
    if became_met:
        case = linked_penalty_case(recall)
        if case is not None:
            case["cooperation_bonus_applied"] = True
            calc.recompute_preview(case)
            store.touch(case)

    return responses.object_response(claim)


@bp.route("/remedy-claims/<claim_id>/void", methods=["POST"])
def void_claim(claim_id):
    auth.authorize("ComplianceOfficer", "SafetyDirector")
    claim = lookups.find("remedy_claim", claim_id)
    data = shapes.body()
    shapes.opt_str(data, "reason", 0, 2000)

    was = claim["status"]
    if was not in ("APPROVED", "FULFILLED"):
        raise_error("ERR_CLAIM_STATE_INVALID")

    recall = lookups.maybe("recall", claim["recall_id"])
    if was == "FULFILLED":
        if recall is not None and recall["plan_status"] == "CLOSED":
            raise_error("ERR_RECALL_PLAN_STATE_INVALID")

    claim["status"] = "VOID"
    claim["voided_at"] = store.now_logical()
    store.touch(claim)

    if was == "FULFILLED" and recall is not None:
        # Exact compensation using the claim's own stored quantity.
        recall["units_corrected"] = recall["units_corrected"] - claim["quantity"]
        recall["units_outstanding"] = recall["units_outstanding"] + claim["quantity"]

        model = lookups.model_for_recall(recall)
        rate = calc.effectiveness_rate(recall, "UNITS_BASIS", model)
        reverted = False
        if (recall["effectiveness_flag"] == "MET"
                and rate < recall["participation_goal_pct"]):
            accepted = any(
                p["recall_id"] == recall["id"] and p["status"] == "ACCEPTED"
                for p in store.progress_reports.values())
            recall["effectiveness_flag"] = "SHORTFALL" if accepted else "PENDING"
            reverted = True
        store.touch(recall)

        if reverted:
            case = linked_penalty_case(recall)
            if case is not None:
                case["cooperation_bonus_applied"] = False
                calc.recompute_preview(case)
                store.touch(case)

    return responses.object_response(claim)
