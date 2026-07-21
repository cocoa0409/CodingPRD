"""Resource serializers. Field names come from SCAFFOLD §1.1."""
import db
from services import budget


def _common(rec, versioned=True):
    out = {"id": rec["id"], "created_at": db.iso(rec["created_at"])}
    if versioned:
        out["updated_at"] = db.iso(rec["updated_at"])
        out["version"] = rec["version"]
    return out


def program(rec, subject_claim_id=None):
    pos = budget.position(rec, subject_claim_id)
    out = _common(rec)
    out.update({
        "name": rec["name"],
        "fiscal_year": rec["fiscal_year"],
        "escheat_jurisdiction": rec["escheat_jurisdiction"],
        "budget_total_cents": rec["budget_total_cents"],
        "committed_cents": pos["committed_cents"],
        "paid_cents": budget.paid_cents(rec),
        "escheat_recovered_cents": budget.escheat_recovered_cents(rec),
        "pending_provisional_cents": pos["pending_provisional_cents"],
        "reserve_cents": pos["reserve_cents"],
        "available_cents": pos["available_cents"],
        "utilization_pct": float(pos["utilization_pct"]),
        "status": rec["status"],
    })
    return out


def offer(rec):
    out = _common(rec)
    out.update({
        "program_id": rec["program_id"],
        "name": rec["name"],
        "channel": rec["channel"],
        "sku_scope": rec["sku_scope"],
        "effective_start_date": db.iso(rec["effective_start_date"]),
        "effective_end_date": db.iso(rec["effective_end_date"]),
        "max_rebate_cents_per_claim": rec["max_rebate_cents_per_claim"],
        "dealer_tier_enabled": rec["dealer_tier_enabled"],
        "status": rec["status"],
        "closed_at": db.iso(rec["closed_at"]),
        "active_claim_count": rec["active_claim_count"],
    })
    return out


def claimant(rec):
    out = _common(rec)
    out.update({
        "type": rec["type"],
        "legal_name": rec["legal_name"],
        "email": rec["email"],
        "mailing_state": rec["mailing_state"],
        "status": rec["status"],
        "fraud_score": rec["fraud_score"],
        "duplicate_attempt_count": rec["duplicate_attempt_count"],
        "denied_claim_count": rec["denied_claim_count"],
        "open_claim_count": rec["open_claim_count"],
    })
    return out


def claim(rec):
    out = _common(rec)
    out.update({
        "offer_id": rec["offer_id"],
        "claimant_id": rec["claimant_id"],
        "adjudication_status": rec["adjudication_status"],
        "payment_status": rec["payment_status"],
        "total_units": rec["total_units"],
        "provisional_rebate_cents": rec["provisional_rebate_cents"],
        "final_rebate_cents": rec["final_rebate_cents"],
        "fraud_score_at_submit": rec["fraud_score_at_submit"],
        "submitted_at": db.iso(rec["submitted_at"]),
        "approved_at": db.iso(rec["approved_at"]),
        "denied_at": db.iso(rec["denied_at"]),
        "approved_by_user_id": rec["approved_by_user_id"],
        "denial_reason_code": rec["denial_reason_code"],
        "appeal_count": rec["appeal_count"],
    })
    return out


def receipt(rec):
    out = _common(rec)
    out.update({
        "claim_id": rec["claim_id"],
        "serial_number": rec["serial_number"],
        "purchase_date": db.iso(rec["purchase_date"]),
        "retailer_name": rec["retailer_name"],
        "lines": rec["lines"],
        "line_count": rec["line_count"],
        "units": rec["units"],
        "gross_amount_cents": rec["gross_amount_cents"],
        "validated": rec["validated"],
        "validated_at": db.iso(rec["validated_at"]),
    })
    return out


def payout(rec):
    out = _common(rec)
    out.update({
        "claim_id": rec["claim_id"],
        "method": rec["method"],
        "gross_cents": rec["gross_cents"],
        "fee_cents": rec["fee_cents"],
        "net_cents": rec["net_cents"],
        "status": rec["status"],
        "check_number": rec["check_number"],
        "released_at": db.iso(rec["released_at"]),
        "released_by_user_id": rec["released_by_user_id"],
        "void_reason": rec["void_reason"],
        "reissue_count": rec["reissue_count"],
    })
    return out


def virtual_card(rec):
    out = _common(rec)
    out.update({
        "payout_id": rec["payout_id"],
        "initial_balance_cents": rec["initial_balance_cents"],
        "remaining_balance_cents": rec["remaining_balance_cents"],
        "status": rec["status"],
        "issued_at": db.iso(rec["issued_at"]),
        "last_activity_at": db.iso(rec["last_activity_at"]),
        "expires_at": db.iso(rec["expires_at"]),
    })
    return out


def escheat_record(rec):
    out = _common(rec, versioned=False)
    out.update({
        "payout_id": rec["payout_id"],
        "program_id": rec["program_id"],
        "amount_cents": rec["amount_cents"],
        "jurisdiction": rec["jurisdiction"],
        "dormancy_days": rec["dormancy_days"],
        "swept_at": db.iso(rec["swept_at"]),
    })
    return out


def budget_entry(rec):
    out = _common(rec, versioned=False)
    out.update({
        "program_id": rec["program_id"],
        "claim_id": rec["claim_id"],
        "entry_type": rec["entry_type"],
        "amount_cents": rec["amount_cents"],
        "committed_after_cents": rec["committed_after_cents"],
        "memo": rec["memo"],
    })
    return out


def fraud_case(rec):
    out = _common(rec)
    out.update({
        "claimant_id": rec["claimant_id"],
        "claim_id": rec["claim_id"],
        "status": rec["status"],
        "opened_reason": rec["opened_reason"],
        "opened_by": rec["opened_by"],
        "heuristic_score_at_open": rec["heuristic_score_at_open"],
        "final_score": rec["final_score"],
        "info_request_count": rec["info_request_count"],
    })
    return out
