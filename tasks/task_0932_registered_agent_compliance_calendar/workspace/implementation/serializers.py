"""Response projections.  Every field named by the PRD as a field of an entity
is part of that entity's response body; per-step working values inside a
calculation are the only things that stay internal (PRD 2.4)."""

from timeutil import render_date, render_instant

# The three lean types carry only id and created_at (PRD 2.4).
_LEAN = ("certificate", "allocation", "escalation_event")


def _audit(row, lean=False):
    out = {"id": row["id"], "created_at": render_instant(row["created_at"])}
    if not lean:
        out["updated_at"] = render_instant(row["updated_at"])
        out["version"] = row["version"]
    return out


def client(row):
    out = _audit(row)
    out.update(
        {
            "legal_name": row["legal_name"],
            "billing_email": row["billing_email"],
            "credit_balance_cents": row["credit_balance_cents"],
            "portfolio_entity_count": row["portfolio_entity_count"],
            "portfolio_open_obligation_count": row["portfolio_open_obligation_count"],
            "portfolio_outstanding_cents": row["portfolio_outstanding_cents"],
            "portfolio_delinquency_status": row["portfolio_delinquency_status"],
            "sop_open_escalation_count": row["sop_open_escalation_count"],
            "portfolio_risk_flag": row["portfolio_risk_flag"],
        }
    )
    return out


_STATE_RULE_SCALARS = (
    "annual_report_basis",
    "fixed_due_month",
    "fixed_due_day",
    "fiscal_offset_days",
    "franchise_tax_basis",
    "flat_franchise_tax_cents",
    "assumed_par_value_rate_bps",
    "min_franchise_tax_cents",
    "max_franchise_tax_cents",
    "grace_days",
    "grace_basis",
    "late_fee_style",
    "late_fee_flat_cents",
    "late_fee_per_month_cents",
    "late_fee_percent_bps",
    "late_fee_cap_cents",
    "delinquency_to_dissolution_days",
    "reinstatement_window_days",
    "annual_report_fee_cents",
    "franchise_tax_filing_fee_cents",
    "foreign_qualification_fee_cents",
    "withdrawal_fee_cents",
    "dissolution_fee_cents",
    "reinstatement_fee_cents",
    "expedite_surcharge_cents",
    "good_standing_freshness_days",
    "requires_tax_clearance",
)


def state_rule(row):
    out = _audit(row)
    out["state_code"] = row["state_code"]
    out["effective_from"] = render_date(row["effective_from"])
    out["effective_to"] = render_date(row["effective_to"])
    for key in _STATE_RULE_SCALARS:
        out[key] = row[key]
    out["authorized_shares_tiers"] = [dict(t) for t in row["authorized_shares_tiers"]]
    out["gross_receipts_brackets"] = [dict(b) for b in row["gross_receipts_brackets"]]
    return out


def legal_entity(row):
    out = _audit(row)
    out.update(
        {
            "client_id": row["client_id"],
            "legal_name": row["legal_name"],
            "entity_type": row["entity_type"],
            "home_state_code": row["home_state_code"],
            "formation_date": render_date(row["formation_date"]),
            "fiscal_year_end_month": row["fiscal_year_end_month"],
            "fiscal_year_end_day": row["fiscal_year_end_day"],
            "authorized_shares": row["authorized_shares"],
            "issued_shares": row["issued_shares"],
            "total_gross_assets_cents": row["total_gross_assets_cents"],
            "annual_gross_receipts_cents": row["annual_gross_receipts_cents"],
            "boi_exempt_class": row["boi_exempt_class"],
            "lifecycle_status": row["lifecycle_status"],
            "boi_status": row["boi_status"],
            "boi_initial_deadline": render_date(row["boi_initial_deadline"]),
            "boi_update_deadline": render_date(row["boi_update_deadline"]),
            "company_applicant_required": row["company_applicant_required"],
            "compliance_posture": row["compliance_posture"],
            "final_report_required": row["final_report_required"],
        }
    )
    return out


def beneficial_owner(row):
    out = _audit(row)
    out.update(
        {
            "legal_entity_id": row["legal_entity_id"],
            "full_name": row["full_name"],
            "date_of_birth": render_date(row["date_of_birth"]),
            "residential_address": row["residential_address"],
            "id_document_number": row["id_document_number"],
            "ownership_pct": row["ownership_pct"],
            "is_company_applicant": row["is_company_applicant"],
            "owner_status": row["owner_status"],
        }
    )
    return out


def name_clearance(row):
    out = _audit(row)
    out.update(
        {
            "legal_entity_id": row["legal_entity_id"],
            "state_code": row["state_code"],
            "requested_name": row["requested_name"],
            "fallback_assumed_name": row["fallback_assumed_name"],
            "result": row["result"],
            "conflicting_name": row["conflicting_name"],
            "resolved_name": row["resolved_name"],
        }
    )
    return out


def registration(row):
    out = _audit(row)
    out.update(
        {
            "legal_entity_id": row["legal_entity_id"],
            "name_clearance_id": row["name_clearance_id"],
            "state_code": row["state_code"],
            "registration_kind": row["registration_kind"],
            "qualified_on": render_date(row["qualified_on"]),
            "closed_on": render_date(row["closed_on"]),
            "status": row["status"],
            "agent_of_record_id": row["agent_of_record_id"],
            "admin_dissolved_on": render_date(row["admin_dissolved_on"]),
            "reinstatement_deadline": render_date(row["reinstatement_deadline"]),
            "delinquency_rank": row["delinquency_rank"],
            "sop_priority_hold": row["sop_priority_hold"],
            "assumed_name": row["assumed_name"],
        }
    )
    return out


def certificate(row):
    out = _audit(row, lean=True)
    out.update(
        {
            "registration_id": row["registration_id"],
            "state_code": row["state_code"],
            "issued_on": render_date(row["issued_on"]),
            "certificate_number": row["certificate_number"],
        }
    )
    return out


def agent_appointment(row):
    out = _audit(row)
    out.update(
        {
            "registration_id": row["registration_id"],
            "superseded_by_appointment_id": row["superseded_by_appointment_id"],
            "provider_name": row["provider_name"],
            "appointed_on": render_date(row["appointed_on"]),
            "status": row["status"],
            "resignation_noticed_on": render_date(row["resignation_noticed_on"]),
            "resignation_effective_on": render_date(row["resignation_effective_on"]),
            "of_record": row["of_record"],
        }
    )
    return out


def obligation(row):
    out = _audit(row)
    out.update(
        {
            "registration_id": row["registration_id"],
            "governing_rule_id": row["governing_rule_id"],
            "obligation_type": row["obligation_type"],
            "period_year": row["period_year"],
            "rule_determination_date": render_date(row["rule_determination_date"]),
            "due_date": render_date(row["due_date"]),
            "grace_end_date": render_date(row["grace_end_date"]),
            "delinquency_date": render_date(row["delinquency_date"]),
            "status": row["status"],
            "state_fee_cents": row["state_fee_cents"],
            "franchise_tax_cents": row["franchise_tax_cents"],
            "late_fee_cents": row["late_fee_cents"],
            "service_fee_cents": row["service_fee_cents"],
            "total_due_cents": row["total_due_cents"],
            "satisfied_on": render_date(row["satisfied_on"]),
        }
    )
    return out


def reminder(row):
    out = _audit(row)
    out.update(
        {
            "compliance_obligation_id": row["compliance_obligation_id"],
            "offset_label": row["offset_label"],
            "scheduled_for": render_date(row["scheduled_for"]),
            "due_date_snapshot": render_date(row["due_date_snapshot"]),
            "status": row["status"],
            "sent_on": render_date(row["sent_on"]),
        }
    )
    return out


def filing(row):
    out = _audit(row)
    out.update(
        {
            "registration_id": row["registration_id"],
            "compliance_obligation_id": row["compliance_obligation_id"],
            "good_standing_certificate_id": row["good_standing_certificate_id"],
            "filing_kind": row["filing_kind"],
            "expedite_tier": row["expedite_tier"],
            "status": row["status"],
            "attempt_number": row["attempt_number"],
            "prepared_by_user_id": row["prepared_by_user_id"],
            "submitted_by_user_id": row["submitted_by_user_id"],
            "submitted_on": render_date(row["submitted_on"]),
            "outcome_recorded_on": render_date(row["outcome_recorded_on"]),
            "rejection_reason": row["rejection_reason"],
            "refile_window_end": render_date(row["refile_window_end"]),
            "state_fee_cents": row["state_fee_cents"],
            "service_fee_cents": row["service_fee_cents"],
            "expedite_fee_cents": row["expedite_fee_cents"],
            "state_portion_cents": row["state_portion_cents"],
            "service_portion_cents": row["service_portion_cents"],
            "total_fee_cents": row["total_fee_cents"],
            "paid_amount_cents": row["paid_amount_cents"],
        }
    )
    return out


def payment(row):
    out = _audit(row)
    out.update(
        {
            "client_id": row["client_id"],
            "authorized_amount_cents": row["authorized_amount_cents"],
            "captured_amount_cents": row["captured_amount_cents"],
            "allocated_amount_cents": row["allocated_amount_cents"],
            "unallocated_amount_cents": row["unallocated_amount_cents"],
            "refunded_amount_cents": row["refunded_amount_cents"],
            "status": row["status"],
        }
    )
    return out


def allocation(row):
    out = _audit(row, lean=True)
    out.update(
        {
            "payment_id": row["payment_id"],
            "filing_id": row["filing_id"],
            "amount_cents": row["amount_cents"],
            "state_portion_cents": row["state_portion_cents"],
            "service_portion_cents": row["service_portion_cents"],
            "sequence_index": row["sequence_index"],
            "is_reversal": row["is_reversal"],
        }
    )
    return out


def sop_document(row):
    out = _audit(row)
    out.update(
        {
            "registration_id": row["registration_id"],
            "sop_class": row["sop_class"],
            "plaintiff_name": row["plaintiff_name"],
            "court_case_number": row["court_case_number"],
            "received_at": render_instant(row["received_at"]),
            "scanned_at": render_instant(row["scanned_at"]),
            "forwarded_at": render_instant(row["forwarded_at"]),
            "acknowledged_at": render_instant(row["acknowledged_at"]),
            "forward_deadline_at": render_instant(row["forward_deadline_at"]),
            "ack_deadline_at": render_instant(row["ack_deadline_at"]),
            "escalation_level": row["escalation_level"],
            "deferred": row["deferred"],
            "deferral_count": row["deferral_count"],
            "forwarded_late": row["forwarded_late"],
            "status": row["status"],
        }
    )
    return out


def escalation_event(row):
    out = _audit(row, lean=True)
    out.update(
        {
            "sop_document_id": row["sop_document_id"],
            "level": row["level"],
            "raised_at": render_instant(row["raised_at"]),
            "channel": row["channel"],
        }
    )
    return out


def boi_report(row):
    out = _audit(row)
    out.update(
        {
            "legal_entity_id": row["legal_entity_id"],
            "report_kind": row["report_kind"],
            "includes_company_applicant": row["includes_company_applicant"],
            "deadline_date": render_date(row["deadline_date"]),
            "triggering_change_date": render_date(row["triggering_change_date"]),
            "owner_snapshot_count": row["owner_snapshot_count"],
            "submitted_on": render_date(row["submitted_on"]),
            "accepted_on": render_date(row["accepted_on"]),
            "status": row["status"],
        }
    )
    return out


def reinstatement_case(row):
    out = _audit(row)
    out.update(
        {
            "registration_id": row["registration_id"],
            "status": row["status"],
            "window_close_date": render_date(row["window_close_date"]),
            "assessment_date": render_date(row["assessment_date"]),
            "missed_period_count": row["missed_period_count"],
            "back_fee_total_cents": row["back_fee_total_cents"],
            "obligations_cured_count": row["obligations_cured_count"],
            "denial_reason": row["denial_reason"],
        }
    )
    return out
