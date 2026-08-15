"""Serialize internal entity dicts to API representation (ISO timestamps, null fields)."""

from db import iso_ts


def serialize_employee(e):
    return {
        "id": e["id"],
        "full_name": e["full_name"],
        "job_level": e["job_level"],
        "home_ownership": e["home_ownership"],
        "employment_status": e["employment_status"],
        "termination_date": iso_ts(e.get("termination_date")),
        "created_at": iso_ts(e["created_at"]),
        "updated_at": iso_ts(e["updated_at"]),
        "version": e["version"],
    }


def serialize_policy(p):
    return {
        "id": p["id"],
        "job_level": p["job_level"],
        "move_scope": p["move_scope"],
        "home_ownership": p["home_ownership"],
        "hhg_cap_cents": p["hhg_cap_cents"],
        "temp_housing_cap_cents": p["temp_housing_cap_cents"],
        "temp_housing_max_nights": p["temp_housing_max_nights"],
        "travel_cap_cents": p["travel_cap_cents"],
        "loss_on_sale_cap_cents": p["loss_on_sale_cap_cents"],
        "misc_cap_cents": p["misc_cap_cents"],
        "home_sale_eligible": p["home_sale_eligible"],
        "repayment_window_months": p["repayment_window_months"],
        "gross_up_method": p["gross_up_method"],
        "flat_gross_up_rate": p["flat_gross_up_rate"],
        "marginal_bracket_threshold_cents": p["marginal_bracket_threshold_cents"],
        "marginal_rate_low": p["marginal_rate_low"],
        "marginal_rate_high": p["marginal_rate_high"],
        "loss_basis": p["loss_basis"],
        "created_at": iso_ts(p["created_at"]),
        "updated_at": iso_ts(p["updated_at"]),
        "version": p["version"],
    }


def serialize_vendor(v):
    return {
        "id": v["id"],
        "name": v["name"],
        "service_regions": list(v.get("service_regions") or []),
        "status": v["status"],
        "rating_count": v.get("rating_count", 0),
        "rating_sum": v.get("rating_sum", 0),
        "avg_rating_lifetime": v.get("avg_rating_lifetime"),
        "avg_rating_rolling_12m": v.get("avg_rating_rolling_12m"),
        "completed_moves": v.get("completed_moves", 0),
        "created_at": iso_ts(v["created_at"]),
        "updated_at": iso_ts(v["updated_at"]),
        "version": v["version"],
    }


def serialize_case(c):
    return {
        "id": c["id"],
        "employee_id": c["employee_id"],
        "policy_id": c["policy_id"],
        "move_scope": c["move_scope"],
        "origin_city": c["origin_city"],
        "destination_city": c["destination_city"],
        "expected_move_date": iso_ts(c.get("expected_move_date")),
        "status": c["status"],
        "authorized_at": iso_ts(c.get("authorized_at")),
        "total_committed_cents": c.get("total_committed_cents", 0),
        "total_paid_cents": c.get("total_paid_cents", 0),
        "total_released_cents": c.get("total_released_cents", 0),
        "cumulative_taxable_paid_cents": c.get("cumulative_taxable_paid_cents", 0),
        "created_at": iso_ts(c["created_at"]),
        "updated_at": iso_ts(c["updated_at"]),
        "version": c["version"],
    }


def serialize_assignment(a):
    return {
        "id": a["id"],
        "case_id": a["case_id"],
        "vendor_id": a["vendor_id"],
        "survey_at": iso_ts(a.get("survey_at")),
        "estimated_cents": a.get("estimated_cents"),
        "final_invoice_cents": a.get("final_invoice_cents"),
        "status": a["status"],
        "rating": a.get("rating"),
        "rated_at": iso_ts(a.get("rated_at")),
        "created_at": iso_ts(a["created_at"]),
        "updated_at": iso_ts(a["updated_at"]),
        "version": a["version"],
    }


def serialize_booking(b):
    return {
        "id": b["id"],
        "case_id": b["case_id"],
        "kind": b["kind"],
        "start_date": iso_ts(b.get("start_date")),
        "end_date": iso_ts(b.get("end_date")),
        "amount_cents": b["amount_cents"],
        "nights": b.get("nights", 0),
        "total_cents": b.get("total_cents", 0),
        "status": b["status"],
        "created_at": iso_ts(b["created_at"]),
        "updated_at": iso_ts(b["updated_at"]),
        "version": b["version"],
    }


def serialize_claim(c):
    return {
        "id": c["id"],
        "case_id": c["case_id"],
        "category": c["category"],
        "payment_method": c["payment_method"],
        "lines": c.get("lines") or [],
        "amount_cents": c.get("amount_cents", 0),
        "taxable": c.get("taxable", False),
        "gross_up_cents": c.get("gross_up_cents", 0),
        "total_payment_cents": c.get("total_payment_cents", 0),
        "status": c["status"],
        "reject_reason": c.get("reject_reason"),
        "paid_at": iso_ts(c.get("paid_at")),
        "created_at": iso_ts(c["created_at"]),
        "updated_at": iso_ts(c["updated_at"]),
        "version": c["version"],
    }


def serialize_home_sale(h):
    return {
        "id": h["id"],
        "case_id": h["case_id"],
        "appraised_value_cents": h["appraised_value_cents"],
        "original_purchase_price_cents": h["original_purchase_price_cents"],
        "list_price_cents": h["list_price_cents"],
        "sale_price_cents": h.get("sale_price_cents"),
        "loss_basis_used": h.get("loss_basis_used"),
        "gross_loss_cents": h.get("gross_loss_cents"),
        "capped_benefit_cents": h.get("capped_benefit_cents"),
        "status": h["status"],
        "created_at": iso_ts(h["created_at"]),
        "updated_at": iso_ts(h["updated_at"]),
        "version": h["version"],
    }


def serialize_repayment(r):
    return {
        "id": r["id"],
        "case_id": r["case_id"],
        "total_owed_cents": r["total_owed_cents"],
        "installments_count": r["installments_count"],
        "installment_cents": r["installment_cents"],
        "final_installment_cents": r["final_installment_cents"],
        "signed_at": iso_ts(r.get("signed_at")),
        "next_due_date": iso_ts(r.get("next_due_date")),
        "paid_to_date_cents": r.get("paid_to_date_cents", 0),
        "balance_cents": r.get("balance_cents", 0),
        "status": r["status"],
        "created_at": iso_ts(r["created_at"]),
        "updated_at": iso_ts(r["updated_at"]),
        "version": r["version"],
    }


def serialize_exception(x):
    return {
        "id": x["id"],
        "case_id": x["case_id"],
        "component": x["component"],
        "requested_cap_increase_cents": x["requested_cap_increase_cents"],
        "justification": x["justification"],
        "status": x["status"],
        "decision_note": x.get("decision_note"),
        "appeal_count": x.get("appeal_count", 0),
        "created_at": iso_ts(x["created_at"]),
        "updated_at": iso_ts(x["updated_at"]),
        "version": x["version"],
    }
