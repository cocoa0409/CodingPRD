"""Convert internal entity dicts into the JSON shapes PRD §2 specifies.

In particular, all datetimes serialize as ISO 8601 UTC with three fractional digits
and a trailing Z. Monetary fields are integer cents (no float).
"""

from datetime import datetime, timezone


def fmt_dt(dt):
    """ISO 8601 UTC with three fractional digits and trailing Z. None -> None."""
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt  # Already serialized somewhere upstream (paranoid pass-through).
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{int(dt.microsecond / 1000):03d}Z"


def owner_to_json(o: dict) -> dict:
    return {
        "id": o["id"],
        "full_name": o["full_name"],
        "date_of_birth": fmt_dt(o["date_of_birth"]),
        "tax_id_last4": o["tax_id_last4"],
        "filing_status": o["filing_status"],
        "modified_agi_cents": o["modified_agi_cents"],
        "deceased_at": fmt_dt(o["deceased_at"]),
        "rmd_posture": o["rmd_posture"],
        "created_at": fmt_dt(o["created_at"]),
        "updated_at": fmt_dt(o["updated_at"]),
        "version": o["version"],
    }


def account_to_json(a: dict) -> dict:
    return {
        "id": a["id"],
        "owner_id": a["owner_id"],
        "account_type": a["account_type"],
        "status": a["status"],
        "cash_balance_cents": a["cash_balance_cents"],
        "pretax_basis_cents": a["pretax_basis_cents"],
        "aftertax_basis_cents": a["aftertax_basis_cents"],
        "ytd_contribution_cents": a["ytd_contribution_cents"],
        "tax_year_marker": a["tax_year_marker"],
        "opened_at": fmt_dt(a["opened_at"]),
        "closed_at": fmt_dt(a["closed_at"]),
        "created_at": fmt_dt(a["created_at"]),
        "updated_at": fmt_dt(a["updated_at"]),
        "version": a["version"],
    }


def beneficiary_to_json(b: dict) -> dict:
    return {
        "id": b["id"],
        "account_id": b["account_id"],
        "beneficiary_full_name": b["beneficiary_full_name"],
        "relationship": b["relationship"],
        "percentage_bps": b["percentage_bps"],
        "status": b["status"],
        "secure_deadline_at": fmt_dt(b["secure_deadline_at"]),
        "created_at": fmt_dt(b["created_at"]),
        "updated_at": fmt_dt(b["updated_at"]),
        "version": b["version"],
    }


def contribution_to_json(c: dict) -> dict:
    return {
        "id": c["id"],
        "account_id": c["account_id"],
        "tax_year": c["tax_year"],
        "amount_cents": c["amount_cents"],
        "contribution_kind": c["contribution_kind"],
        "status": c["status"],
        "confirmed_at": fmt_dt(c["confirmed_at"]),
        "created_at": fmt_dt(c["created_at"]),
        "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
    }


def distribution_to_json(d: dict) -> dict:
    return {
        "id": d["id"],
        "account_id": d["account_id"],
        "amount_cents": d["amount_cents"],
        "distribution_reason": d["distribution_reason"],
        "tax_year": d["tax_year"],
        "federal_withholding_cents": d["federal_withholding_cents"],
        "status": d["status"],
        "confirmed_at": fmt_dt(d["confirmed_at"]),
        "created_at": fmt_dt(d["created_at"]),
        "updated_at": fmt_dt(d["updated_at"]),
        "version": d["version"],
    }


def conversion_to_json(c: dict) -> dict:
    return {
        "id": c["id"],
        "source_account_id": c["source_account_id"],
        "target_account_id": c["target_account_id"],
        "gross_amount_cents": c["gross_amount_cents"],
        "taxable_amount_cents": c["taxable_amount_cents"],
        "nontaxable_amount_cents": c["nontaxable_amount_cents"],
        "status": c["status"],
        "completed_at": fmt_dt(c["completed_at"]),
        "created_at": fmt_dt(c["created_at"]),
        "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
    }


def rmd_schedule_to_json(s: dict) -> dict:
    return {
        "id": s["id"],
        "owner_id": s["owner_id"],
        "tax_year": s["tax_year"],
        "required_amount_cents": s["required_amount_cents"],
        "satisfied_amount_cents": s["satisfied_amount_cents"],
        "deadline_at": fmt_dt(s["deadline_at"]),
        "status": s["status"],
        "is_first_rmd_year": s["is_first_rmd_year"],
        "created_at": fmt_dt(s["created_at"]),
        "updated_at": fmt_dt(s["updated_at"]),
        "version": s["version"],
    }


def form_1099r_to_json(f: dict) -> dict:
    return {
        "id": f["id"],
        "distribution_id": f["distribution_id"],
        "conversion_id": f["conversion_id"],
        "tax_year": f["tax_year"],
        "gross_distribution_cents": f["gross_distribution_cents"],
        "taxable_amount_cents": f["taxable_amount_cents"],
        "federal_withholding_cents": f["federal_withholding_cents"],
        "distribution_code": f["distribution_code"],
        "ira_sep_simple_flag": f["ira_sep_simple_flag"],
        "created_at": fmt_dt(f["created_at"]),
    }


def audit_event_to_json(e: dict) -> dict:
    return {
        "id": e["id"],
        "owner_id": e["owner_id"],
        "account_id": e["account_id"],
        "event_kind": e["event_kind"],
        "tax_year": e["tax_year"],
        "amount_cents": e["amount_cents"],
        "occurred_at": fmt_dt(e["occurred_at"]),
        "created_at": fmt_dt(e["created_at"]),
    }


def system_clock_to_json(c: dict) -> dict:
    return {
        "current_utc": fmt_dt(c["current_utc"]),
        "current_tax_year": c["current_tax_year"],
    }
