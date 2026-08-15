"""Public entity serialization (internal keys like _seq/_verified_by excluded)."""

from .util import fmt_dt


def _base(e):
    return {
        "id": e["id"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def ser_contributor(c):
    d = _base(c)
    d.update({
        "legal_name": c["legal_name"],
        "pen_name": c["pen_name"],
        "email": c["email"],
        "tax_residency": c["tax_residency"],
        "status": c["status"],
        "ytd_gross_cents": c["ytd_gross_cents"],
        "reportable_threshold_crossed": c["reportable_threshold_crossed"],
        "backup_withholding_flag": c["backup_withholding_flag"],
    })
    return d


def ser_rate_agreement(r):
    d = _base(r)
    d.update({
        "contributor_id": r["contributor_id"],
        "pricing_mode": r["pricing_mode"],
        "per_word_rate_cents": r["per_word_rate_cents"],
        "flat_fee_cents": r["flat_fee_cents"],
        "kill_fee_pct_num": r["kill_fee_pct_num"],
        "rights_default": r["rights_default"],
        "effective_from": fmt_dt(r["effective_from"]),
        "effective_to": fmt_dt(r["effective_to"]),
        "status": r["status"],
    })
    return d


def ser_assignment(a):
    d = _base(a)
    d.update({
        "contributor_id": a["contributor_id"],
        "rate_agreement_id": a["rate_agreement_id"],
        "title": a["title"],
        "brief": a["brief"],
        "commissioned_word_count": a["commissioned_word_count"],
        "final_word_count": a["final_word_count"],
        "deadline_utc": fmt_dt(a["deadline_utc"]),
        "editorial_status": a["editorial_status"],
        "payment_status": a["payment_status"],
        "kill_fee_tier": a["kill_fee_tier"],
        "agreed_fee_cents": a["agreed_fee_cents"],
        "final_fee_cents": a["final_fee_cents"],
        "verification_cleared": a["verification_cleared"],
        "late_flag": a["late_flag"],
    })
    return d


def ser_expense_claim(c):
    d = _base(c)
    d.update({
        "assignment_id": c["assignment_id"],
        "category": c["category"],
        "requested_cents": c["requested_cents"],
        "approved_cents": c["approved_cents"],
        "claimed_cents": c["claimed_cents"],
        "receipt_attached": c["receipt_attached"],
        "status": c["status"],
        "reimbursable_cents": c["reimbursable_cents"],
    })
    return d


def ser_verification_report(r):
    d = _base(r)
    d.update({
        "assignment_id": r["assignment_id"],
        "checker_kind": r["checker_kind"],
        "similarity_score_bps": r["similarity_score_bps"],
        "ai_probability_bps": r["ai_probability_bps"],
        "status": r["status"],
        "adjudication_note": r["adjudication_note"],
    })
    return d


def ser_rights_purchase(r):
    d = _base(r)
    d.update({
        "assignment_id": r["assignment_id"],
        "rights_kind": r["rights_kind"],
        "reuse_count": r["reuse_count"],
        "reuse_fee_cents_total": r["reuse_fee_cents_total"],
        "buyout_uplift_cents": r["buyout_uplift_cents"],
        "status": r["status"],
    })
    return d


def ser_tax_document(t):
    d = _base(t)
    d.update({
        "contributor_id": t["contributor_id"],
        "doc_kind": t["doc_kind"],
        "treaty_country": t["treaty_country"],
        "tin_last4": t["tin_last4"],
        "submitted_at": fmt_dt(t["submitted_at"]),
        "expires_at": fmt_dt(t["expires_at"]),
        "status": t["status"],
    })
    return d


def ser_invoice(i):
    d = _base(i)
    d.update({
        "assignment_id": i["assignment_id"],
        "submitted_by_contributor_id": i["submitted_by_contributor_id"],
        "fee_claim_cents": i["fee_claim_cents"],
        "expense_claim_cents": i["expense_claim_cents"],
        "gross_cents": i["gross_cents"],
        "withholding_cents": i["withholding_cents"],
        "net_payable_cents": i["net_payable_cents"],
        "payment_terms_days": i["payment_terms_days"],
        "due_date_utc": fmt_dt(i["due_date_utc"]),
        "status": i["status"],
        "late_fee_cents": i["late_fee_cents"],
        "payment_batch_id": i["payment_batch_id"],
    })
    return d


def ser_payment_batch(b):
    d = _base(b)
    d.update({
        "scheduled_pay_date": fmt_dt(b["scheduled_pay_date"]),
        "status": b["status"],
        "total_gross_cents": b["total_gross_cents"],
        "total_withholding_cents": b["total_withholding_cents"],
        "total_net_cents": b["total_net_cents"],
        "locked_by_user_id": b["locked_by_user_id"],
    })
    return d


def ser_ledger_entry(e):
    # LedgerEntry carries id and created_at only (immutable postings: no updated_at/version)
    return {
        "id": e["id"],
        "created_at": fmt_dt(e["created_at"]),
        "invoice_id": e["invoice_id"],
        "contributor_id": e["contributor_id"],
        "entry_kind": e["entry_kind"],
        "amount_cents": e["amount_cents"],
        "posted_at": fmt_dt(e["posted_at"]),
    }


def ser_config(c):
    d = _base(c)
    for k in (
        "kill_fee_post_delivery_pct_num",
        "receipt_required_cents",
        "category_caps_cents",
        "net_terms_days",
        "late_fee_daily_bps",
        "reporting_threshold_cents",
        "backup_withholding_rate_bps",
        "foreign_statutory_rate_bps",
        "treaty_rates_bps",
        "flag_threshold_bps",
        "ai_flag_threshold_bps",
        "reuse_royalty_pct_num",
        "all_rights_uplift_pct_num",
    ):
        d[k] = c[k]
    return d
