"""Entity serializers — public view of each resource (internal 'seq' stripped)."""
import db


def _base(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def program_to_dict(p):
    d = _base(p)
    d.update({
        "name": p["name"],
        "fee_amount_cents": p["fee_amount_cents"],
        "daily_fee_cap_cents": p["daily_fee_cap_cents"],
        "max_daily_fees_count": p["max_daily_fees_count"],
        "de_minimis_threshold_cents": p["de_minimis_threshold_cents"],
        "sustained_overdraft_days_threshold": p["sustained_overdraft_days_threshold"],
        "sustained_overdraft_fee_cents": p["sustained_overdraft_fee_cents"],
        "charge_off_grace_business_days": p["charge_off_grace_business_days"],
        "notice_window_days": p["notice_window_days"],
        "steering_fee_count_threshold": p["steering_fee_count_threshold"],
        "steering_window_days": p["steering_window_days"],
        "offer_expiry_days": p["offer_expiry_days"],
        "posting_order_policy": p["posting_order_policy"],
        "current_disclosure_version": p["current_disclosure_version"],
        "status": p["status"],
    })
    return d


def account_to_dict(a):
    d = _base(a)
    d.update({
        "program_id": a["program_id"],
        "holder_name": a["holder_name"],
        "status": a["status"],
        "ledger_balance_cents": a["ledger_balance_cents"],
        "consecutive_negative_business_days": a["consecutive_negative_business_days"],
        "restricted_business_days": a["restricted_business_days"],
        "lifetime_fees_assessed_cents": a["lifetime_fees_assessed_cents"],
        "lifetime_fees_waived_cents": a["lifetime_fees_waived_cents"],
        "charged_off_cents": a["charged_off_cents"],
        "recovered_cents": a["recovered_cents"],
        "charge_off_original_cents": a["charge_off_original_cents"],
    })
    return d


def election_to_dict(e):
    d = _base(e)
    d.update({
        "account_id": e["account_id"],
        "status": e["status"],
        "channel": e["channel"],
        "disclosure_version": e["disclosure_version"],
        "elected_at": e["elected_at"],
        "last_changed_at": e["last_changed_at"],
    })
    return d


def transaction_to_dict(t):
    d = _base(t)
    d.update({
        "account_id": t["account_id"],
        "type": t["type"],
        "amount_cents": t["amount_cents"],
        "status": t["status"],
        "authorized_date": t["authorized_date"],
        "batch_id": t["batch_id"],
        "posting_sequence": t["posting_sequence"],
        "posted_date": t["posted_date"],
    })
    return d


def batch_to_dict(b):
    d = _base(b)
    d.update({
        "program_id": b["program_id"],
        "business_date": b["business_date"],
        "status": b["status"],
        "items_posted_count": b["items_posted_count"],
        "items_returned_count": b["items_returned_count"],
        "fees_assessed_count": b["fees_assessed_count"],
        "fees_assessed_cents": b["fees_assessed_cents"],
    })
    return d


def fee_to_dict(f):
    d = _base(f)
    d.update({
        "account_id": f["account_id"],
        "batch_id": f["batch_id"],
        "transaction_id": f["transaction_id"],
        "fee_type": f["fee_type"],
        "amount_cents": f["amount_cents"],
        "waived_cents": f["waived_cents"],
        "outstanding_cents": f["amount_cents"] - f["waived_cents"],
        "status": f["status"],
        "posted_date": f["posted_date"],
    })
    return d


def waiver_request_to_dict(w):
    d = _base(w)
    d.update({
        "account_id": w["account_id"],
        "fee_ids": list(w["fee_ids"]),
        "kind": w["kind"],
        "amount_cents": w["amount_cents"],
        "percent_bps": w["percent_bps"],
        "reason_code": w["reason_code"],
        "computed_total_cents": w["computed_total_cents"],
        "routing_band": w["routing_band"],
        "status": w["status"],
        "created_by_user_id": w["created_by_user_id"],
        "created_by_role": w["created_by_role"],
        "decided_by_user_id": w["decided_by_user_id"],
        "denied_band": w["denied_band"],
    })
    return d


def waiver_item_to_dict(i):
    # WaiverRequestItem carries only id and created_at (PRD §2.5).
    return {
        "id": i["id"],
        "created_at": i["created_at"],
        "waiver_request_id": i["waiver_request_id"],
        "fee_id": i["fee_id"],
        "waived_cents": i["waived_cents"],
    }


def notice_to_dict(n):
    d = _base(n)
    d.update({
        "program_id": n["program_id"],
        "parameter": n["parameter"],
        "new_value": n["new_value"],
        "old_value": n["old_value"],
        "status": n["status"],
        "sent_at": n["sent_at"],
        "effective_at": n["effective_at"],
    })
    return d


def offer_effective_status(o):
    """Lazy expiry (PRD §3.8): OFFERED past expires_at surfaces as EXPIRED."""
    if o["status"] == "OFFERED" and db.clock_dt() > db.parse_ts(o["expires_at"]):
        return "EXPIRED"
    return o["status"]


def offer_to_dict(o):
    d = _base(o)
    d.update({
        "account_id": o["account_id"],
        "offer_type": o["offer_type"],
        "trigger_reason": o["trigger_reason"],
        "status": offer_effective_status(o),
        "expires_at": o["expires_at"],
    })
    return d


def report_to_dict(r):
    d = _base(r)
    d.update({
        "program_id": r["program_id"],
        "period_start": r["period_start"],
        "period_end": r["period_end"],
        "status": r["status"],
        "revenue_provisional_cents": r["revenue_provisional_cents"],
        "revenue_final_cents": r["revenue_final_cents"],
        "waiver_ratio_bps": r["waiver_ratio_bps"],
        "avg_fees_per_overdrafter_centi": r["avg_fees_per_overdrafter_centi"],
        "scrutiny_flag": r["scrutiny_flag"],
        "finalized_by_user_id": r["finalized_by_user_id"],
    })
    return d
