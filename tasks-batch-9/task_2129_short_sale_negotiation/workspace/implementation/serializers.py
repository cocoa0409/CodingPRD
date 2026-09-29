"""Resource representations."""
from timeutil import to_iso


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": to_iso(rec["created_at"]),
        "updated_at": to_iso(rec["updated_at"]),
        "version": rec["version"],
    }


def case_out(rec):
    out = _common(rec)
    out.update(
        {
            "property_address": rec["property_address"],
            "investor_type": rec["investor_type"],
            "unpaid_principal_balance_cents": rec["unpaid_principal_balance_cents"],
            "servicer_name": rec["servicer_name"],
            "assigned_negotiator_user_id": rec["assigned_negotiator_user_id"],
            "negotiation_status": rec["negotiation_status"],
            "documentation_status": rec["documentation_status"],
            "final_value_cents": rec["final_value_cents"],
            "minimum_acceptable_net_cents": rec["minimum_acceptable_net_cents"],
            "junior_contribution_total_cents": rec["junior_contribution_total_cents"],
            "junior_lien_count": rec["junior_lien_count"],
            "failed_offer_count": rec["failed_offer_count"],
            "price_reduction_required": rec["price_reduction_required"],
            "deficiency_waiver_permitted": rec["deficiency_waiver_permitted"],
        }
    )
    return out


def vendor_out(rec):
    # Immutable configuration: id and created_at only, no updated_at, no version.
    return {
        "id": rec["id"],
        "created_at": to_iso(rec["created_at"]),
        "vendor_name": rec["vendor_name"],
        "license_state": rec["license_state"],
        "daily_inspection_capacity": rec["daily_inspection_capacity"],
    }


def package_out(rec):
    out = _common(rec)
    out.update(
        {
            "case_id": rec["case_id"],
            "hardship_reason": rec["hardship_reason"],
            "monthly_income_cents": rec["monthly_income_cents"],
            "monthly_expenses_cents": rec["monthly_expenses_cents"],
            "liquid_assets_cents": rec["liquid_assets_cents"],
            "assembled_by_user_id": rec["assembled_by_user_id"],
            "document_count": rec["document_count"],
            "pending_document_count": rec["pending_document_count"],
            "verified_document_count": rec["verified_document_count"],
            "rejected_document_count": rec["rejected_document_count"],
            "hardship_score_intake": _num(rec["hardship_score_intake"]),
            "hardship_score_audit": _num(rec["hardship_score_audit"]),
            "status": rec["status"],
        }
    )
    return out


def _num(value):
    return None if value is None else float(value)


def document_out(rec):
    out = _common(rec)
    out.update(
        {
            "package_id": rec["package_id"],
            "doc_type": rec["doc_type"],
            "issued_on": to_iso(rec["issued_on"]),
            "reference_label": rec["reference_label"],
            "age_days_at_review": rec["age_days_at_review"],
            "reviewed_by_user_id": rec["reviewed_by_user_id"],
            "status": rec["status"],
        }
    )
    return out


def listing_out(rec):
    from services import days_on_market

    out = _common(rec)
    out.update(
        {
            "case_id": rec["case_id"],
            "list_price_cents": rec["list_price_cents"],
            "commission_pct": float(rec["commission_pct"]),
            "listed_at": to_iso(rec["listed_at"]),
            "ended_at": to_iso(rec["ended_at"]),
            "listing_agent_user_id": rec["listing_agent_user_id"],
            "days_on_market": days_on_market(rec),
            "price_reduction_count": rec["price_reduction_count"],
            "marketing_status": rec["marketing_status"],
        }
    )
    return out


def offer_out(rec):
    out = _common(rec)
    out.update(
        {
            "case_id": rec["case_id"],
            "buyer_name": rec["buyer_name"],
            "buyer_financing": rec["buyer_financing"],
            "offer_price_cents": rec["offer_price_cents"],
            "earnest_money_cents": rec["earnest_money_cents"],
            "requested_closing_days": rec["requested_closing_days"],
            "round_index": rec["round_index"],
            "servicer_counter_price_cents": rec["servicer_counter_price_cents"],
            "submitted_at": to_iso(rec["submitted_at"]),
            "status": rec["status"],
        }
    )
    return out


def net_sheet_out(rec):
    out = _common(rec)
    out.update(
        {
            "offer_id": rec["offer_id"],
            "variant": rec["variant"],
            "title_escrow_cents": rec["title_escrow_cents"],
            "property_tax_arrears_cents": rec["property_tax_arrears_cents"],
            "hoa_arrears_cents": rec["hoa_arrears_cents"],
            "commission_pct_applied": rec["commission_pct_applied"],
            "line_items": [dict(line) for line in rec["line_items"]],
            "gross_deductions_cents": rec["gross_deductions_cents"],
            "mi_contribution_credit_cents": rec["mi_contribution_credit_cents"],
            "base_net_cents": rec["base_net_cents"],
            "relocation_incentive_cents": rec["relocation_incentive_cents"],
            "net_proceeds_cents": rec["net_proceeds_cents"],
            "prepared_by_user_id": rec["prepared_by_user_id"],
            "status": rec["status"],
        }
    )
    return out


def valuation_out(rec):
    out = _common(rec)
    out.update(
        {
            "case_id": rec["case_id"],
            "vendor_id": rec["vendor_id"],
            "valuation_type": rec["valuation_type"],
            "effective_date": to_iso(rec["effective_date"]),
            "inspection_start": to_iso(rec["inspection_start"]),
            "inspection_end": to_iso(rec["inspection_end"]),
            "ordered_by_user_id": rec["ordered_by_user_id"],
            "value_cents": rec["value_cents"],
            "recorded_at": to_iso(rec["recorded_at"]),
            "status": rec["status"],
        }
    )
    return out


def dispute_out(rec):
    out = _common(rec)
    out.update(
        {
            "valuation_id": rec["valuation_id"],
            "claimed_value_cents": rec["claimed_value_cents"],
            "comparable_count": rec["comparable_count"],
            "rationale": rec["rationale"],
            "filed_by_user_id": rec["filed_by_user_id"],
            "variance_pct": _num(rec["variance_pct"]),
            "resolved_value_cents": rec["resolved_value_cents"],
            "adjudicated_by_user_id": rec["adjudicated_by_user_id"],
            "status": rec["status"],
        }
    )
    return out


def lien_out(rec):
    out = _common(rec)
    out.update(
        {
            "case_id": rec["case_id"],
            "lien_position": rec["lien_position"],
            "holder_name": rec["holder_name"],
            "holder_user_id": rec["holder_user_id"],
            "balance_cents": rec["balance_cents"],
            "demand_cents": rec["demand_cents"],
            "approved_contribution_cents": rec["approved_contribution_cents"],
            "status": rec["status"],
        }
    )
    return out


def mi_claim_out(rec):
    out = _common(rec)
    out.update(
        {
            "case_id": rec["case_id"],
            "mi_provider": rec["mi_provider"],
            "coverage_pct": float(rec["coverage_pct"]),
            "claim_reference": rec["claim_reference"],
            "required_contribution_cents": rec["required_contribution_cents"],
            "contribution_form": rec["contribution_form"],
            "decided_by_user_id": rec["decided_by_user_id"],
            "status": rec["status"],
        }
    )
    return out


def approval_out(rec):
    out = _common(rec)
    out.update(
        {
            "case_id": rec["case_id"],
            "offer_id": rec["offer_id"],
            "supersedes_approval_id": rec["supersedes_approval_id"],
            "approved_net_proceeds_cents": rec["approved_net_proceeds_cents"],
            "commission_cap_pct": float(rec["commission_cap_pct"]),
            "seller_relocation_incentive_cents": rec["seller_relocation_incentive_cents"],
            "deficiency_waiver": rec["deficiency_waiver"],
            "conditions": list(rec["conditions"]),
            "issued_by_user_id": rec["issued_by_user_id"],
            "issued_at": to_iso(rec["issued_at"]),
            "closing_deadline": to_iso(rec["closing_deadline"]),
            "cumulative_extension_days_used": rec["cumulative_extension_days_used"],
            "status": rec["status"],
        }
    )
    return out


def extension_out(rec):
    out = _common(rec)
    out.update(
        {
            "approval_letter_id": rec["approval_letter_id"],
            "requested_days": rec["requested_days"],
            "reason": rec["reason"],
            "requested_by_user_id": rec["requested_by_user_id"],
            "granted_days": rec["granted_days"],
            "decided_by_user_id": rec["decided_by_user_id"],
            "new_closing_deadline": to_iso(rec["new_closing_deadline"]),
            "status": rec["status"],
        }
    )
    return out
