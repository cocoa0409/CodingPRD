"""Cost entries and insurance claims."""
from flask import Blueprint, request

from core import (ALL_ROLES, ROLE_ADJ, ROLE_COORD, ROLE_FIRM, auth, body, created, db, err,
                  new_row, ok, opt_str, paginate, public, req_enum, req_int, req_str, upd)
from domain import (COST_CATEGORIES, apply_metrics, cost_line_values, insurance_settlement,
                    recall_children)
from resolve import (firm_scope, get_sub, get_recall, not_terminated, recall_state, sub_recall,
                     sync)

bp = Blueprint("cost", __name__)


# ------------------------------------------------------------------ cost entries
@bp.post("/recalls/<recall_id>/cost-entries")
def create_cost_entry(recall_id):
    user_id, role = auth([ROLE_FIRM])
    recall = get_recall(recall_id)
    firm_scope(role, user_id, recall)
    data = body()
    category = req_enum(data, "category", COST_CATEGORIES)
    amount_cents = req_int(data, "amount_cents", exclusive_min=0)
    description = req_str(data, "description")
    not_terminated(recall)                                                     # rung 11
    sync(recall)
    entry = new_row(db.cost_entries,
                    recall_id=recall["id"],
                    category=category,
                    amount_cents=amount_cents,
                    description=description,
                    status="PENDING",
                    adjudicated_by_user_id=None,
                    adjudication_note=None,
                    **cost_line_values(category, amount_cents))
    return created(public(entry))


@bp.get("/recalls/<recall_id>/cost-entries")
def list_cost_entries(recall_id):
    user_id, role = auth(ALL_ROLES)
    recall = get_recall(recall_id)
    firm_scope(role, user_id, recall)
    rows = recall_children(db.cost_entries, recall["id"])
    for field in ("category", "status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    return paginate(rows)


_COST_FROM = {"ACCEPT": ("PENDING", "REJECTED"), "REJECT": ("PENDING", "ACCEPTED")}


@bp.post("/cost-entries/<entry_id>/adjudicate")
def adjudicate_cost_entry(entry_id):
    user_id, role = auth([ROLE_COORD])
    entry = get_sub(db.cost_entries, entry_id)
    recall = sub_recall(entry)
    firm_scope(role, user_id, recall)
    data = body()
    decision = req_enum(data, "decision", {"ACCEPT", "REJECT"})
    adjudication_note = opt_str(data, "adjudication_note")
    not_terminated(recall)                                                     # rung 11
    if entry.get("status") not in _COST_FROM[decision]:                        # rung 19
        err("ERR_INVALID_COST_ENTRY_STATE",
            "Cost entry status %s does not permit %s" % (entry.get("status"), decision))
    if adjudication_note is not None:
        upd(entry, adjudication_note=adjudication_note)
    upd(entry, status=("ACCEPTED" if decision == "ACCEPT" else "REJECTED"),
        adjudicated_by_user_id=user_id)
    apply_metrics(recall)
    return ok(public(entry))


# ------------------------------------------------------------------ insurance claims
@bp.post("/recalls/<recall_id>/insurance-claims")
def create_claim(recall_id):
    user_id, role = auth([ROLE_FIRM])
    recall = get_recall(recall_id)
    firm_scope(role, user_id, recall)
    data = body()
    claim_reference = req_str(data, "claim_reference")
    not_terminated(recall)                                                     # rung 11
    sync(recall)
    claim = new_row(db.insurance_claims,
                    recall_id=recall["id"],
                    claim_reference=claim_reference,
                    claimed_cents=0,
                    capped_total_cents=0,
                    coinsurance_rate=0,
                    settlement_payable_cents=0,
                    handling_fee_cents=0,
                    total_claim_value_cents=0,
                    paid_cents=0,
                    status="DRAFT",
                    supplement_round=0,
                    denial_reason=None,
                    adjudicated_by_user_id=None)
    return created(public(claim))


@bp.get("/recalls/<recall_id>/insurance-claims")
def list_claims(recall_id):
    user_id, role = auth(ALL_ROLES)
    recall = get_recall(recall_id)
    firm_scope(role, user_id, recall)
    rows = recall_children(db.insurance_claims, recall["id"])
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    return paginate(rows)


@bp.post("/insurance-claims/<claim_id>/submit")
def submit_claim(claim_id):
    user_id, role = auth([ROLE_FIRM])
    claim = get_sub(db.insurance_claims, claim_id)
    recall = sub_recall(claim)
    firm_scope(role, user_id, recall)
    # rung 11 — submission is explicitly allowed on a TERMINATED recall
    recall_state(recall, ("EFFECTIVENESS_REVIEW", "TERMINATION_REQUESTED", "TERMINATED"))
    sync(recall)
    if claim.get("status") not in ("DRAFT", "PARTIALLY_PAID"):                 # rung 18
        err("ERR_INVALID_CLAIM_STATE",
            "Claim status %s does not permit submission" % claim.get("status"))
    if int(recall.get("insurable_loaded_cost_cents") or 0) <= 0:               # rung 18
        err("ERR_INVALID_CLAIM_STATE",
            "The recall has no accepted insurable cost to claim")
    firm = db.firms.get(recall.get("firm_id"))
    remaining = int(firm.get("policy_aggregate_cents") or 0) - \
        int(firm.get("policy_paid_to_date_cents") or 0)
    if remaining <= 0:                                                         # rung 33
        err("ERR_CLAIM_EXCEEDS_POLICY_AGGREGATE",
            "The firm's remaining policy aggregate is exhausted")
    supplement = claim.get("status") == "PARTIALLY_PAID"
    values = insurance_settlement(recall, firm)
    upd(claim, status="SUBMITTED", **values)
    if supplement:
        upd(claim, supplement_round=int(claim.get("supplement_round") or 0) + 1)
    return ok(public(claim))


@bp.post("/insurance-claims/<claim_id>/adjudicate")
def adjudicate_claim(claim_id):
    user_id, role = auth([ROLE_ADJ])
    claim = get_sub(db.insurance_claims, claim_id)
    recall = sub_recall(claim)
    data = body()
    decision = req_enum(data, "decision", {"PAY_FULL", "PAY_PARTIAL", "DENY"})
    paid_cents = None
    denial_reason = None
    if decision == "PAY_PARTIAL":
        paid_cents = req_int(data, "paid_cents", exclusive_min=0)
    if decision == "DENY":
        denial_reason = req_str(data, "denial_reason")
    if claim.get("status") != "SUBMITTED":                                     # rung 18
        err("ERR_INVALID_CLAIM_STATE",
            "Claim status %s does not permit adjudication" % claim.get("status"))
    payable = int(claim.get("settlement_payable_cents") or 0)
    if decision == "PAY_PARTIAL" and paid_cents >= payable:
        err("ERR_INVALID_REQUEST",
            "paid_cents must be strictly less than settlement_payable_cents")

    firm = db.firms.get(recall.get("firm_id")) if recall else None
    upd(claim, adjudicated_by_user_id=user_id)
    if decision == "PAY_FULL":
        upd(claim, status="PAID", paid_cents=payable)
        if firm is not None:
            upd(firm, policy_paid_to_date_cents=int(firm.get("policy_paid_to_date_cents") or 0) + payable)
    elif decision == "PAY_PARTIAL":
        upd(claim, status="PARTIALLY_PAID", paid_cents=paid_cents)
        if firm is not None:
            upd(firm, policy_paid_to_date_cents=int(firm.get("policy_paid_to_date_cents") or 0) + paid_cents)
    else:
        upd(claim, status="DENIED", denial_reason=denial_reason)
    return ok(public(claim))
