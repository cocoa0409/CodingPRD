"""JSON serializers: convert internal records (datetime objects) to API shape."""
from services import calc
from util import fmt_dt


def _common(e):
    return {
        "id": e["id"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def borrower_out(b):
    out = _common(b)
    out.update({
        "full_name": b["full_name"],
        "state_code": b["state_code"],
        "email": b["email"],
    })
    return out


def loan_out(l):
    out = _common(l)
    out.update({
        "borrower_id": l["borrower_id"],
        "vin": l["vin"],
        "governing_state_code": l["governing_state_code"],
        "principal_balance_cents": l["principal_balance_cents"],
        "apr_bps": l["apr_bps"],
        "monthly_payment_cents": l["monthly_payment_cents"],
        "missed_installments": l["missed_installments"],
        "accrued_interest_cents": l["accrued_interest_cents"],
        "late_fees_cents": l["late_fees_cents"],
        "paid_to_date_cents": l["paid_to_date_cents"],
        "total_outstanding_cents": calc.total_outstanding(l),
        "status": l["status"],
    })
    return out


def case_out(c):
    out = _common(c)
    out.update({
        "loan_account_id": c["loan_account_id"],
        "default_reason": c["default_reason"],
        "opened_by_user_id": c["opened_by_user_id"],
        "status": c["status"],
        "cure_deadline": fmt_dt(c["cure_deadline"]),
        "redemption_deadline": fmt_dt(c["redemption_deadline"]),
        "pre_complaint_state": c["pre_complaint_state"],
        "current_cure_notice_id": c["current_cure_notice_id"],
        "current_redemption_quote_id": c["current_redemption_quote_id"],
        "collateral_secured_at": fmt_dt(c["collateral_secured_at"]),
        "odometer": c["odometer"],
        "condition_grade": c["condition_grade"],
        "trade_in_value_cents": c["trade_in_value_cents"],
        "auction_guide_low_cents": c["auction_guide_low_cents"],
        "sold_at": fmt_dt(c["sold_at"]),
        "property_item_count": c["property_item_count"],
    })
    return out


def cure_notice_out(n):
    out = _common(n)
    out.update({
        "recovery_case_id": n["recovery_case_id"],
        "status": n["status"],
        "sent_at": fmt_dt(n["sent_at"]),
        "cure_amount_cents": n["cure_amount_cents"],
        "superseded_by_id": n["superseded_by_id"],
    })
    return out


def agent_out(a):
    out = _common(a)
    lifetime, rolling = calc.agent_scores(a["id"])
    out.update({
        "name": a["name"],
        "license_number": a["license_number"],
        "licensed_state_codes": list(a["licensed_state_codes"]),
        "max_active_assignments": a["max_active_assignments"],
        "status": a["status"],
        "performance_score_lifetime": lifetime,
        "performance_score_rolling": rolling,
    })
    return out


def assignment_out(a):
    out = _common(a)
    out.update({
        "recovery_case_id": a["recovery_case_id"],
        "agent_id": a["agent_id"],
        "status": a["status"],
        "field_window_start": fmt_dt(a["field_window_start"]),
        "field_window_end": fmt_dt(a["field_window_end"]),
        "auto_selected": a["auto_selected"],
        "secured_fast": a["secured_fast"],
    })
    return out


def item_out(i):
    out = _common(i)
    out.update({
        "recovery_case_id": i["recovery_case_id"],
        "description": i["description"],
        "estimated_value_cents": i["estimated_value_cents"],
        "status": i["status"],
        "claimed_by_borrower_id": i["claimed_by_borrower_id"],
    })
    return out


def quote_out(q):
    out = _common(q)
    out.update({
        "recovery_case_id": q["recovery_case_id"],
        "quote_type": q["quote_type"],
        "status": q["status"],
        "issued_at": fmt_dt(q["issued_at"]),
        "valid_until": fmt_dt(q["valid_until"]),
        "quoted_amount_cents": q["quoted_amount_cents"],
        "per_diem_cents": q["per_diem_cents"],
        "superseded_by_id": q["superseded_by_id"],
    })
    return out


def auction_house_out(h):
    out = _common(h)
    out.update({
        "name": h["name"],
        "fee_bps": h["fee_bps"],
        "transport_fee_cents": h["transport_fee_cents"],
    })
    return out


def consignment_out(c):
    out = _common(c)
    out.update({
        "recovery_case_id": c["recovery_case_id"],
        "auction_house_id": c["auction_house_id"],
        "status": c["status"],
        "reserve_price_cents": c["reserve_price_cents"],
        "listing_start": fmt_dt(c["listing_start"]),
        "listing_end": fmt_dt(c["listing_end"]),
        "relist_count": c["relist_count"],
        "consignment_seq": c["consignment_seq"],
    })
    return out


def sale_out(s):
    out = _common(s)
    out.update({
        "consignment_id": s["consignment_id"],
        "gross_sale_cents": s["gross_sale_cents"],
        "auction_fee_cents": s["auction_fee_cents"],
        "transport_fee_cents": s["transport_fee_cents"],
        "net_proceeds_cents": s["net_proceeds_cents"],
        "status": s["status"],
    })
    return out


def deficiency_out(n):
    out = _common(n)
    out.update({
        "recovery_case_id": n["recovery_case_id"],
        "status": n["status"],
        "deficiency_amount_cents": n["deficiency_amount_cents"],
        "surplus_cents": n["surplus_cents"],
        "paid_cents": n["paid_cents"],
        "sent_at": fmt_dt(n["sent_at"]),
    })
    return out


def complaint_out(c):
    out = _common(c)
    out.update({
        "recovery_case_id": c["recovery_case_id"],
        "borrower_id": c["borrower_id"],
        "category": c["category"],
        "description": c["description"],
        "status": c["status"],
        "resolved_by_user_id": c["resolved_by_user_id"],
    })
    return out


def ledger_out(e):
    """Append-only: id + created_at only from the standard set (PRD §2.4)."""
    return {
        "id": e["id"],
        "created_at": fmt_dt(e["created_at"]),
        "recovery_case_id": e["recovery_case_id"],
        "kind": e["kind"],
        "amount_cents": e["amount_cents"],
        "memo": e["memo"],
        "reverses_entry_id": e["reverses_entry_id"],
    }
