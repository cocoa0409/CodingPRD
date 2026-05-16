"""Serializer functions that produce the JSON shape for each entity."""


def serialize_application(app: dict) -> dict:
    return {
        "id": app["id"],
        "applicant_id": app["applicant_id"],
        "coverage_year": app["coverage_year"],
        "status": app["status"],
        "filing_state": app["filing_state"],
        "enrollment_window": app["enrollment_window"],
        "household_size": app.get("household_size", 0),
        "total_magi_cents": app.get("total_magi_cents"),
        "fpl_percentage": app.get("fpl_percentage"),
        "csr_eligibility": app.get("csr_eligibility"),
        "aptc_estimated_cents": app.get("aptc_estimated_cents"),
        "aptc_reconciled_cents": app.get("aptc_reconciled_cents"),
        "pinned_fpl_table_version": app.get("pinned_fpl_table_version"),
        "submitted_at": app.get("submitted_at"),
        "approved_at": app.get("approved_at"),
        "created_at": app["created_at"],
        "updated_at": app["updated_at"],
        "version": app["version"],
    }


def serialize_household_member(m: dict) -> dict:
    return {
        "id": m["id"],
        "application_id": m["application_id"],
        "filer_type": m["filer_type"],
        "date_of_birth": m["date_of_birth"],
        "include_in_household": m["include_in_household"],
        "include_in_magi": m["include_in_magi"],
        "is_tobacco_user": m["is_tobacco_user"],
        "medicaid_eligible": m.get("medicaid_eligible"),
        "member_magi_cents": m.get("member_magi_cents", 0),
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def serialize_income_record(r: dict) -> dict:
    return {
        "id": r["id"],
        "member_id": r["member_id"],
        "source_type": r["source_type"],
        "amount_cents": r["amount_cents"],
        "effective_date": r["effective_date"],
        "superseded_by_id": r.get("superseded_by_id"),
        "created_at": r["created_at"],
    }


def serialize_insurer(i: dict) -> dict:
    return {
        "id": i["id"],
        "name": i["name"],
        "filing_states": list(i["filing_states"]),
        "contact_phone": i["contact_phone"],
        "created_at": i["created_at"],
    }


def serialize_plan(p: dict) -> dict:
    return {
        "id": p["id"],
        "insurer_id": p["insurer_id"],
        "coverage_year": p["coverage_year"],
        "filing_state": p["filing_state"],
        "tier": p["tier"],
        "base_monthly_premium_cents": p["base_monthly_premium_cents"],
        "is_benchmark_silver": p["is_benchmark_silver"],
        "status": p["status"],
        "catalog_version": p["catalog_version"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_plan_variant(v: dict) -> dict:
    return {
        "id": v["id"],
        "plan_id": v["plan_id"],
        "csr_level": v["csr_level"],
        "actuarial_value": v["actuarial_value"],
        "out_of_pocket_max_cents": v["out_of_pocket_max_cents"],
        "created_at": v["created_at"],
    }


def serialize_sep_event(s: dict) -> dict:
    return {
        "id": s["id"],
        "application_id": s["application_id"],
        "event_type": s["event_type"],
        "event_date": s["event_date"],
        "reported_at": s["reported_at"],
        "status": s["status"],
        "window_opens_on": s.get("window_opens_on"),
        "window_closes_on": s.get("window_closes_on"),
        "effective_date": s.get("effective_date"),
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_enrollment(e: dict) -> dict:
    return {
        "id": e["id"],
        "application_id": e["application_id"],
        "plan_variant_id": e["plan_variant_id"],
        "pinned_plan_catalog_version": e.get("pinned_plan_catalog_version"),
        "coverage_status": e["coverage_status"],
        "payment_status": e["payment_status"],
        "coverage_start_date": e.get("coverage_start_date"),
        "coverage_end_date": e.get("coverage_end_date"),
        "monthly_premium_gross_cents": e.get("monthly_premium_gross_cents"),
        "monthly_aptc_applied_cents": e.get("monthly_aptc_applied_cents"),
        "monthly_net_premium_cents": e.get("monthly_net_premium_cents"),
        "terminated_reason": e.get("terminated_reason"),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_premium_invoice(inv: dict) -> dict:
    return {
        "id": inv["id"],
        "enrollment_id": inv["enrollment_id"],
        "billing_month": inv["billing_month"],
        "gross_amount_cents": inv["gross_amount_cents"],
        "aptc_amount_cents": inv["aptc_amount_cents"],
        "net_amount_cents": inv["net_amount_cents"],
        "due_date": inv["due_date"],
        "status": inv["status"],
        "paid_at": inv.get("paid_at"),
        "created_at": inv["created_at"],
    }
