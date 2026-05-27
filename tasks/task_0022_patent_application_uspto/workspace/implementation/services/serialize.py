"""Resource -> wire-format serialization helpers."""

from db import iso_from_datetime


def _opt_iso(dt):
    if dt is None:
        return None
    return iso_from_datetime(dt)


def applicant_to_wire(a: dict) -> dict:
    return {
        "id": a["id"],
        "legal_name": a["legal_name"],
        "entity_size": a["entity_size"],
        "micro_qualifying_year": a.get("micro_qualifying_year"),
        "gross_income_prior_year_cents": a.get("gross_income_prior_year_cents"),
        "prior_applications_filed": a.get("prior_applications_filed", 0),
        "created_at": iso_from_datetime(a["created_at"]),
        "updated_at": iso_from_datetime(a["updated_at"]),
        "version": a["version"],
    }


def application_to_wire(app: dict) -> dict:
    return {
        "id": app["id"],
        "applicant_id": app["applicant_id"],
        "application_type": app["application_type"],
        "title": app["title"],
        "claim_count": app["claim_count"],
        "independent_claim_count": app["independent_claim_count"],
        "filing_date": iso_from_datetime(app["filing_date"]),
        "status": app["status"],
        "parent_application_id": app.get("parent_application_id"),
        "continuation_type": app.get("continuation_type"),
        "priority_date": iso_from_datetime(app["priority_date"]),
        "total_fees_paid_cents": app.get("total_fees_paid_cents", 0),
        "issued_patent_number": app.get("issued_patent_number"),
        "issue_date": _opt_iso(app.get("issue_date")),
        "term_expiration_date": _opt_iso(app.get("term_expiration_date")),
        "created_at": iso_from_datetime(app["created_at"]),
        "updated_at": iso_from_datetime(app["updated_at"]),
        "version": app["version"],
    }


def office_action_to_wire(oa: dict) -> dict:
    return {
        "id": oa["id"],
        "application_id": oa["application_id"],
        "action_type": oa["action_type"],
        "issue_date": iso_from_datetime(oa["issue_date"]),
        "shortened_due_date": iso_from_datetime(oa["shortened_due_date"]),
        "maximum_due_date": iso_from_datetime(oa["maximum_due_date"]),
        "status": oa["status"],
        "created_at": iso_from_datetime(oa["created_at"]),
        "updated_at": iso_from_datetime(oa["updated_at"]),
        "version": oa["version"],
    }


def office_action_response_to_wire(r: dict) -> dict:
    return {
        "id": r["id"],
        "office_action_id": r["office_action_id"],
        "response_filed_at": iso_from_datetime(r["response_filed_at"]),
        "extension_months_requested": r["extension_months_requested"],
        "claim_amendment_count": r["claim_amendment_count"],
        "extension_fee_cents": r["extension_fee_cents"],
        "response_status": r["response_status"],
        "created_at": iso_from_datetime(r["created_at"]),
        "updated_at": iso_from_datetime(r["updated_at"]),
        "version": r["version"],
    }


def maintenance_fee_to_wire(mf: dict) -> dict:
    return {
        "id": mf["id"],
        "application_id": mf["application_id"],
        "window_number": mf["window_number"],
        "window_open_date": iso_from_datetime(mf["window_open_date"]),
        "window_due_date": iso_from_datetime(mf["window_due_date"]),
        "window_grace_date": iso_from_datetime(mf["window_grace_date"]),
        "base_fee_cents": mf["base_fee_cents"],
        "fee_status": mf["fee_status"],
        "paid_at": _opt_iso(mf.get("paid_at")),
        "created_at": iso_from_datetime(mf["created_at"]),
        "updated_at": iso_from_datetime(mf["updated_at"]),
        "version": mf["version"],
    }


def fee_payment_to_wire(fp: dict) -> dict:
    return {
        "id": fp["id"],
        "application_id": fp["application_id"],
        "payment_category": fp["payment_category"],
        "amount_cents": fp["amount_cents"],
        "maintenance_fee_id": fp.get("maintenance_fee_id"),
        "payment_status": fp["payment_status"],
        "created_at": iso_from_datetime(fp["created_at"]),
    }


def pct_phase_entry_to_wire(p: dict) -> dict:
    return {
        "id": p["id"],
        "application_id": p["application_id"],
        "pct_international_filing_date": iso_from_datetime(p["pct_international_filing_date"]),
        "national_phase_due_date": iso_from_datetime(p["national_phase_due_date"]),
        "phase_status": p["phase_status"],
        "created_at": iso_from_datetime(p["created_at"]),
        "updated_at": iso_from_datetime(p["updated_at"]),
        "version": p["version"],
    }
