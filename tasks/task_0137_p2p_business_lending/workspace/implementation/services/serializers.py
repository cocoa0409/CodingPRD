"""Entity → JSON serialization helpers.

Each serializer returns the exact public-facing shape of an entity as
described in SCAFFOLD §1.1 / PRD §3. Private/internal fields (prefix `_`)
are dropped.
"""
from __future__ import annotations


def _common(e: dict, include_version: bool = True) -> dict:
    out = {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e.get("updated_at"),
    }
    if include_version:
        out["version"] = e.get("version")
    return out


def serialize_platform(p: dict) -> dict:
    out = _common(p)
    out.update(
        {
            "name": p["name"],
            "currency": p["currency"],
            "clock_day_index": p["clock_day_index"],
            "origination_fee_bps": p["origination_fee_bps"],
            "servicing_fee_bps": p["servicing_fee_bps"],
            "late_fee_cents": p["late_fee_cents"],
            "max_borrower_concentration_bps": p["max_borrower_concentration_bps"],
        }
    )
    return out


def serialize_borrower(b: dict) -> dict:
    out = _common(b)
    out.update(
        {
            "platform_id": b["platform_id"],
            "legal_name": b["legal_name"],
            "ein": b["ein"],
            "annual_revenue_cents": b["annual_revenue_cents"],
            "requested_amount_cents": b["requested_amount_cents"],
            "plaid_snapshot_id": b.get("plaid_snapshot_id"),
            "provisional_grade": b.get("provisional_grade"),
            "final_grade": b.get("final_grade"),
            "status": b["status"],
        }
    )
    return out


def serialize_plaid_snapshot(s: dict) -> dict:
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "borrower_id": s["borrower_id"],
        "pulled_on_day_index": s["pulled_on_day_index"],
        "deposits_last_90d_cents": s["deposits_last_90d_cents"],
        "avg_daily_balance_cents": s["avg_daily_balance_cents"],
        "nsf_count_last_90d": s["nsf_count_last_90d"],
        "existing_debt_service_cents": s["existing_debt_service_cents"],
    }


def serialize_listing(l: dict) -> dict:
    out = _common(l)
    out.update(
        {
            "borrower_id": l["borrower_id"],
            "platform_id": l["platform_id"],
            "principal_cents": l["principal_cents"],
            "term_months": l["term_months"],
            "grade_at_listing": l.get("grade_at_listing"),
            "interest_rate_bps": l["interest_rate_bps"],
            "pledged_cents": l["pledged_cents"],
            "funding_deadline_day_index": l["funding_deadline_day_index"],
            "status": l["status"],
        }
    )
    return out


def serialize_investor(i: dict) -> dict:
    out = _common(i)
    out.update(
        {
            "platform_id": i["platform_id"],
            "display_name": i["display_name"],
            "accreditation_status": i["accreditation_status"],
            "committed_capital_cents": i["committed_capital_cents"],
            "cash_balance_cents": i["cash_balance_cents"],
            "outstanding_principal_cents": i["outstanding_principal_cents"],
            "status": i["status"],
        }
    )
    return out


def serialize_investment(i: dict) -> dict:
    out = _common(i)
    out.update(
        {
            "listing_id": i["listing_id"],
            "investor_id": i["investor_id"],
            "amount_cents": i["amount_cents"],
            "status": i["status"],
            "share_bps": i.get("share_bps", 0),
        }
    )
    return out


def serialize_loan(l: dict) -> dict:
    out = _common(l)
    out.update(
        {
            "listing_id": l["listing_id"],
            "borrower_id": l["borrower_id"],
            "platform_id": l["platform_id"],
            "principal_cents": l["principal_cents"],
            "interest_rate_bps": l["interest_rate_bps"],
            "term_months": l["term_months"],
            "monthly_payment_cents": l["monthly_payment_cents"],
            "principal_outstanding_cents": l["principal_outstanding_cents"],
            "accrued_late_fees_cents": l["accrued_late_fees_cents"],
            "charged_off_loss_cents": l["charged_off_loss_cents"],
            "consecutive_missed_installments": l["consecutive_missed_installments"],
            "origination_day_index": l["origination_day_index"],
            "status": l["status"],
        }
    )
    return out


def serialize_installment(i: dict) -> dict:
    out = _common(i)
    out.update(
        {
            "loan_id": i["loan_id"],
            "sequence_number": i["sequence_number"],
            "due_day_index": i["due_day_index"],
            "scheduled_principal_cents": i["scheduled_principal_cents"],
            "scheduled_interest_cents": i["scheduled_interest_cents"],
            "paid_principal_cents": i["paid_principal_cents"],
            "paid_interest_cents": i["paid_interest_cents"],
            "paid_fees_cents": i["paid_fees_cents"],
            "status": i["status"],
        }
    )
    return out


def serialize_payment(p: dict) -> dict:
    out = _common(p)
    out.update(
        {
            "loan_id": p["loan_id"],
            "borrower_id": p["borrower_id"],
            "amount_cents": p["amount_cents"],
            "received_on_day_index": p["received_on_day_index"],
            "allocation": p["allocation"],
            "status": p["status"],
        }
    )
    return out


def serialize_disclosure(d: dict) -> dict:
    return {
        "id": d["id"],
        "created_at": d["created_at"],
        "platform_id": d["platform_id"],
        "subject_type": d["subject_type"],
        "subject_id": d["subject_id"],
        "kind": d["kind"],
        "payload": d["payload"],
        "published": d["published"],
        "published_on_day_index": d.get("published_on_day_index"),
    }


def serialize_compliance_officer(c: dict) -> dict:
    out = _common(c)
    out.update(
        {
            "platform_id": c["platform_id"],
            "display_name": c["display_name"],
            "status": c["status"],
        }
    )
    return out
