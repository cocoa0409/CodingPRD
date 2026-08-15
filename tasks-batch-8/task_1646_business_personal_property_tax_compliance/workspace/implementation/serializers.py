"""Entity -> wire dict serializers. Dates stored internally as date objects
are rendered as YYYY-MM-DD strings; datetimes as ISO 8601 with Z."""


def _d(v):
    """date -> 'YYYY-MM-DD'."""
    if v is None:
        return None
    return v.isoformat()


def _copy_fields(obj, fields):
    return {f: obj.get(f) for f in fields}


def client_view(c):
    return {
        "id": c["id"],
        "legal_name": c["legal_name"],
        "contact_email": c["contact_email"],
        "forecast_sequence": c["forecast_sequence"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def operator_view(o):
    return {
        "id": o["id"],
        "display_name": o["display_name"],
        "operator_role": o["operator_role"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def jurisdiction_view(j):
    return {
        "id": j["id"],
        "county_name": j["county_name"],
        "state_code": j["state_code"],
        "base_deadline_mmdd": j["base_deadline_mmdd"],
        "max_extension_days": j["max_extension_days"],
        "late_penalty_pct_per_month": j["late_penalty_pct_per_month"],
        "max_late_penalty_pct": j["max_late_penalty_pct"],
        "penalty_base": j["penalty_base"],
        "tax_rate": j["tax_rate"],
        "offered_exemption_types": j["offered_exemption_types"],
        "max_exemption_pct": j["max_exemption_pct"],
        "created_at": j["created_at"],
        "updated_at": j["updated_at"],
        "version": j["version"],
    }


def class_rule_view(r):
    return {
        "id": r["id"],
        "jurisdiction_id": r["jurisdiction_id"],
        "category": r["category"],
        "is_taxable": r["is_taxable"],
        "depreciation_convention": r["depreciation_convention"],
        "percent_good_vector": r["percent_good_vector"],
        "percent_good_floor_pct": r["percent_good_floor_pct"],
        "de_minimis_line_cents": r["de_minimis_line_cents"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def asset_view(a):
    return {
        "id": a["id"],
        "client_id": a["client_id"],
        "jurisdiction_id": a["jurisdiction_id"],
        "asset_tag": a["asset_tag"],
        "category": a["category"],
        "acquisition_cost_cents": a["acquisition_cost_cents"],
        "acquisition_date": _d(a["acquisition_date"]),
        "in_service_date": _d(a["in_service_date"]),
        "lifecycle_status": a["lifecycle_status"],
        "classification_status": a["classification_status"],
        "taxable_classification": a["taxable_classification"],
        "disposed_date": _d(a["disposed_date"]),
        "disposal_proceeds_cents": a["disposal_proceeds_cents"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def disposal_view(d):
    return {
        "id": d["id"],
        "asset_id": d["asset_id"],
        "disposal_date": _d(d["disposal_date"]),
        "disposal_proceeds_cents": d["disposal_proceeds_cents"],
        "disposal_status": d["disposal_status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def line_view(l):
    return dict(l)


def rendition_view(r):
    return {
        "id": r["id"],
        "client_id": r["client_id"],
        "jurisdiction_id": r["jurisdiction_id"],
        "tax_year": r["tax_year"],
        "rendition_status": r["rendition_status"],
        "lines": [line_view(l) for l in r["lines"]],
        "total_assessed_value_cents": r["total_assessed_value_cents"],
        "deadline_date": _d(r["deadline_date"]),
        "is_late_filing": r["is_late_filing"],
        "late_days": r["late_days"],
        "late_penalty_months": r["late_penalty_months"],
        "late_penalty_cents": r["late_penalty_cents"],
        "filed_at": r["filed_at"],
        "filed_by_operator_id": r["filed_by_operator_id"],
        "amendment_opened_by_operator_id": r["amendment_opened_by_operator_id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def extension_view(e):
    return {
        "id": e["id"],
        "rendition_id": e["rendition_id"],
        "requested_extend_to_date": _d(e["requested_extend_to_date"]),
        "granted_days": e["granted_days"],
        "extension_status": e["extension_status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def notice_view(n):
    return {
        "id": n["id"],
        "rendition_id": n["rendition_id"],
        "notice_value_cents": n["notice_value_cents"],
        "received_date": _d(n["received_date"]),
        "protest_deadline_date": _d(n["protest_deadline_date"]),
        "notice_status": n["notice_status"],
        "final_value_cents": n["final_value_cents"],
        "created_at": n["created_at"],
        "updated_at": n["updated_at"],
        "version": n["version"],
    }


def appeal_view(a):
    return {
        "id": a["id"],
        "notice_id": a["notice_id"],
        "claimed_value_cents": a["claimed_value_cents"],
        "grounds": a["grounds"],
        "appeal_status": a["appeal_status"],
        "hearing_date": _d(a["hearing_date"]),
        "decision": a["decision"],
        "decided_value_cents": a["decided_value_cents"],
        "board_value_cents": a["board_value_cents"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def installment_view(i):
    return {
        "installment_no": i["installment_no"],
        "due_date": _d(i["due_date"]),
        "amount_cents": i["amount_cents"],
        "installment_status": i["installment_status"],
        "paid_date": _d(i["paid_date"]),
    }


def bill_view(b):
    return {
        "id": b["id"],
        "notice_id": b["notice_id"],
        "billed_amount_cents": b["billed_amount_cents"],
        "tax_rate": b["tax_rate"],
        "due_date": _d(b["due_date"]),
        "validated_amount_cents": b["validated_amount_cents"],
        "variance_cents": b["variance_cents"],
        "validation_status": b["validation_status"],
        "payment_status": b["payment_status"],
        "installments": [installment_view(i) for i in b["installments"]],
        "unscheduled_amount_cents": b["unscheduled_amount_cents"],
        "created_by_operator_id": b["created_by_operator_id"],
        "validated_by_operator_id": b["validated_by_operator_id"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def exemption_view(e):
    return {
        "id": e["id"],
        "asset_id": e["asset_id"],
        "exemption_type": e["exemption_type"],
        "exemption_pct": e["exemption_pct"],
        "effective_date": _d(e["effective_date"]),
        "expiration_date": _d(e["expiration_date"]),
        "application_status": e["application_status"],
        "suspended_date": _d(e["suspended_date"]),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def abatement_view(a):
    return {
        "id": a["id"],
        "asset_id": a["asset_id"],
        "first_tax_year": a["first_tax_year"],
        "last_tax_year": a["last_tax_year"],
        "abatement_pct": a["abatement_pct"],
        "agreement_status": a["agreement_status"],
        "last_recertified_year": a["last_recertified_year"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def forecast_view(f):
    return {
        "id": f["id"],
        "client_id": f["client_id"],
        "tax_year": f["tax_year"],
        "variant": f["variant"],
        "as_of_date": _d(f["as_of_date"]),
        "forecasted_liability_cents": f["forecasted_liability_cents"],
        "component_count": f["component_count"],
        "forecast_status": f["forecast_status"],
        "needs_regeneration": f["needs_regeneration"],
        "published_by_operator_id": f["published_by_operator_id"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def audit_event_view(e):
    return {
        "id": e["id"],
        "client_id": e["client_id"],
        "event_type": e["event_type"],
        "message": e["message"],
        "actor_id": e["actor_id"],
        "created_at": e["created_at"],
    }
