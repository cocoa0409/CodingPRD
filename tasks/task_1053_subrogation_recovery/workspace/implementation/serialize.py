"""Entity serializers -> public JSON (§1.1 field lists, §2.4 common fields)."""
from timeutil import format_dt as fmt


def _common(o):
    return {
        "id": o["id"],
        "created_at": fmt(o["created_at"]),
        "updated_at": fmt(o["updated_at"]),
        "version": o["version"],
    }


def carrier(o):
    d = _common(o)
    d.update({
        "name": o["name"],
        "naic_code": o["naic_code"],
        "commission_rate_bps": o["commission_rate_bps"],
        "commission_basis": o["commission_basis"],
        "status": o["status"],
    })
    return d


def adverse_party(o):
    d = _common(o)
    d.update({
        "name": o["name"],
        "adverse_carrier_name": o["adverse_carrier_name"],
        "is_arbitration_eligible": o["is_arbitration_eligible"],
        "policy_limit_cents": o["policy_limit_cents"],
    })
    return d


def claim(o):
    d = _common(o)
    d.update({
        "carrier_id": o["carrier_id"],
        "adverse_party_id": o["adverse_party_id"],
        "claim_reference": o["claim_reference"],
        "loss_date": o["loss_date"],
        "referral_date": fmt(o["referral_date"]),
        "paid_loss_cents": o["paid_loss_cents"],
        "deductible_cents": o["deductible_cents"],
        "total_damages_cents": o["total_damages_cents"],
        "statute_deadline": o["statute_deadline"],
        "liability_pct": o["liability_pct"],
        "provisional_recoverable_cents": o["provisional_recoverable_cents"],
        "settled_amount_cents": o["settled_amount_cents"],
        "final_recovered_cents": o["final_recovered_cents"],
        "deductible_reimbursed_cents": o["deductible_reimbursed_cents"],
        "carrier_recovered_cents": o["carrier_recovered_cents"],
        "accrued_commission_cents": o["accrued_commission_cents"],
        "status": o["status"],
    })
    return d


def demand(o):
    d = _common(o)
    d.update({
        "claim_id": o["claim_id"],
        "amount_demanded_cents": o["amount_demanded_cents"],
        "issued_at": fmt(o["issued_at"]),
        "response_due_at": fmt(o["response_due_at"]),
        "disputed_at": fmt(o["disputed_at"]),
        "arbitration_window_due_at": fmt(o["arbitration_window_due_at"]),
        "outcome": o["outcome"],
        "status": o["status"],
    })
    return d


def _round(r):
    return {
        "round_no": r["round_no"],
        "filer": r["filer"],
        "filed_at": fmt(r["filed_at"]),
        "note": r["note"],
    }


def arbitration(o):
    d = _common(o)
    d.update({
        "claim_id": o["claim_id"],
        "forum": o["forum"],
        "filed_at": fmt(o["filed_at"]),
        "hearing_start": o["hearing_start"],
        "hearing_end": o["hearing_end"],
        "rounds": [_round(r) for r in o["rounds"]],
        "round_count": o["round_count"],
        "award_amount_cents": o["award_amount_cents"],
        "status": o["status"],
    })
    return d


def settlement(o):
    d = _common(o)
    d.update({
        "claim_id": o["claim_id"],
        "settled_amount_cents": o["settled_amount_cents"],
        "proposed_by_user_id": o["proposed_by_user_id"],
        "approved_by_user_id": o["approved_by_user_id"],
        "status": o["status"],
    })
    return d


def recovery_payment(o):
    d = _common(o)
    d.update({
        "claim_id": o["claim_id"],
        "amount_cents": o["amount_cents"],
        "received_at": fmt(o["received_at"]),
        "alloc_deductible_cents": o["alloc_deductible_cents"],
        "alloc_carrier_cents": o["alloc_carrier_cents"],
        "alloc_commission_cents": o["alloc_commission_cents"],
        "status": o["status"],
    })
    return d


def deductible_reimbursement(o):
    d = _common(o)
    d.update({
        "claim_id": o["claim_id"],
        "recovery_payment_id": o["recovery_payment_id"],
        "amount_cents": o["amount_cents"],
        "disbursed_at": fmt(o["disbursed_at"]),
        "status": o["status"],
    })
    return d


def commission_statement(o):
    d = _common(o)
    d.update({
        "carrier_id": o["carrier_id"],
        "period_label": o["period_label"],
        "lines": [dict(line) for line in o["lines"]],
        "total_commission_cents": o["total_commission_cents"],
        "status": o["status"],
    })
    return d


def claim_document(o):
    return {
        "id": o["id"],
        "created_at": fmt(o["created_at"]),
        "claim_id": o["claim_id"],
        "doc_type": o["doc_type"],
        "title": o["title"],
        "uri": o["uri"],
    }
