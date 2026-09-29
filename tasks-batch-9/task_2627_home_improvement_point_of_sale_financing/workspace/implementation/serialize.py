"""Response shapes. Every entity emits exactly the fields SCAFFOLD 1.1 declares."""
import calc
from util import fmt_dt


def _common(rec, versioned=True):
    out = {"id": rec["id"], "created_at": fmt_dt(rec["created_at"])}
    if versioned:
        out["updated_at"] = fmt_dt(rec["updated_at"])
        out["version"] = rec["version"]
    return out


def _dt(value):
    return fmt_dt(value) if value else None


def trade_rule(rec):
    out = _common(rec)
    out.update({
        "trade_type": rec["trade_type"],
        "max_ticket_cents": rec["max_ticket_cents"],
        "holdback_pct_bps": rec["holdback_pct_bps"],
        "max_precompletion_release_bps": rec["max_precompletion_release_bps"],
        "velocity_cap_cents": rec["velocity_cap_cents"],
        "requires_completion_certificate": rec["requires_completion_certificate"],
        "min_license_months": rec["min_license_months"],
    })
    return out


def promotion_plan(rec):
    out = _common(rec)
    out.update({
        "code": rec["code"],
        "promotion_type": rec["promotion_type"],
        "promo_term_months": rec["promo_term_months"],
        "deferred_apr_bps": rec["deferred_apr_bps"],
        "post_promo_apr_bps": rec["post_promo_apr_bps"],
        "merchant_discount_bps": rec["merchant_discount_bps"],
        "min_ticket_cents": rec["min_ticket_cents"],
        "max_ticket_cents": rec["max_ticket_cents"],
        "disclosure_template_version": rec["disclosure_template_version"],
        "allowed_trade_types": list(rec["allowed_trade_types"]),
    })
    return out


def merchant(rec):
    out = _common(rec)
    out.update({
        "legal_name": rec["legal_name"],
        "trade_type": rec["trade_type"],
        "state_code": rec["state_code"],
        "contact_email": rec["contact_email"],
        "enrollment_status": rec["enrollment_status"],
        "attestation_ref": rec["attestation_ref"],
        "approved_by_user_id": rec["approved_by_user_id"],
        "approved_on": _dt(rec["approved_on"]),
        "suspension_reason_code": rec["suspension_reason_code"],
        "termination_reason_code": rec["termination_reason_code"],
        "risk_tier": calc.merchant_risk_tier(rec["id"]),
        "funded_volume_cents": calc.funded_volume_cents(rec["id"]),
        "holdback_reserve_cents": rec["holdback_reserve_cents"],
        "holdback_target_cents": rec["holdback_target_cents"],
        "reserve_coverage_bps": calc.reserve_coverage_bps(rec),
        "settlement_offset_receivable_cents": rec["settlement_offset_receivable_cents"],
        "program_write_off_cents": rec["program_write_off_cents"],
        "dispute_rate_bps": calc.dispute_rate_bps(rec["id"]),
        "delinquency_rate_bps": calc.delinquency_rate_bps(rec["id"]),
        "phantom_risk_score": calc.phantom_risk_score(rec["id"]),
        "portfolio_grade": calc.merchant_grade(rec["id"]),
        "termination_recommended": calc.termination_recommended(rec["id"]),
    })
    return out


def merchant_license(rec):
    out = _common(rec)
    out.update({
        "merchant_id": rec["merchant_id"],
        "trade_type": rec["trade_type"],
        "license_number": rec["license_number"],
        "state_code": rec["state_code"],
        "effective_from": rec["effective_from"],
        "expires_on": rec["expires_on"],
        "verification_status": rec["verification_status"],
        "verified_by_user_id": rec["verified_by_user_id"],
        "verification_note": rec["verification_note"],
        "verified_on": _dt(rec["verified_on"]),
    })
    return out


def enrollment(rec):
    out = _common(rec)
    out.update({
        "merchant_id": rec["merchant_id"],
        "promotion_plan_id": rec["promotion_plan_id"],
        "window_start_date": rec["window_start_date"],
        "window_end_date": rec["window_end_date"],
        "negotiated_discount_bps": rec["negotiated_discount_bps"],
        "status": rec["status"],
    })
    return out


def consumer(rec):
    out = _common(rec)
    out.update({
        "full_name": rec["full_name"],
        "ssn_last4": rec["ssn_last4"],
        "annual_income_cents": rec["annual_income_cents"],
        "fico_score": rec["fico_score"],
        "state_code": rec["state_code"],
        "existing_program_debt_cents": calc.existing_program_debt_cents(rec["id"]),
        "active_loan_count": calc.active_loan_count(rec["id"]),
    })
    return out


def application(rec):
    out = _common(rec)
    out.update({
        "merchant_id": rec["merchant_id"],
        "consumer_id": rec["consumer_id"],
        "promotion_plan_id": rec["promotion_plan_id"],
        "project_amount_cents": rec["project_amount_cents"],
        "decision": rec["decision"],
        "approved_limit_cents": rec["approved_limit_cents"],
        "decision_dti_bps": rec["decision_dti_bps"],
        "decision_reason_codes": list(rec["decision_reason_codes"]),
        "disclosure_status": rec["disclosure_status"],
        "disclosure_template_version": rec["disclosure_template_version"],
        "disclosure_delivered_at": _dt(rec["disclosure_delivered_at"]),
        "disclosure_acknowledged_at": _dt(rec["disclosure_acknowledged_at"]),
        "consumer_signature_ref": rec["consumer_signature_ref"],
        "offer_expires_at": _dt(rec["offer_expires_at"]),
        "promo_disclosure_summary": rec["promo_disclosure_summary"],
    })
    return out


def loan_account(rec):
    out = _common(rec)
    out.update({
        "application_id": rec["application_id"],
        "consumer_id": rec["consumer_id"],
        "merchant_id": rec["merchant_id"],
        "promotion_plan_id": rec["promotion_plan_id"],
        "credit_limit_cents": rec["credit_limit_cents"],
        "principal_balance_cents": calc.principal_balance_cents(rec),
        "capitalized_interest_cents": rec["capitalized_interest_cents"],
        "accrued_deferred_interest_cents": calc.accrued_deferred_interest_cents(rec),
        "waived_interest_cents": rec["waived_interest_cents"],
        "promo_status": rec["promo_status"],
        "balance_status": rec["balance_status"],
        "promo_expires_on": rec["promo_expires_on"],
        "apr_bps": rec["apr_bps"],
        "first_funding_on": rec["first_funding_on"],
        "last_payment_on": rec["last_payment_on"],
        "total_funded_cents": calc.total_funded_cents(rec),
        "promo_payoff_cents": calc.promo_payoff_cents(rec),
        "standard_payoff_cents": calc.standard_payoff_cents(rec),
        "deferred_interest_at_risk_cents": calc.deferred_interest_at_risk_cents(rec),
    })
    return out


def project(rec):
    out = _common(rec)
    out.update({
        "application_id": rec["application_id"],
        "merchant_id": rec["merchant_id"],
        "loan_account_id": rec["loan_account_id"],
        "scope_description": rec["scope_description"],
        "contract_amount_cents": rec["contract_amount_cents"],
        "completion_status": rec["completion_status"],
        "completion_certificate_ref": rec["completion_certificate_ref"],
        "certified_on": _dt(rec["certified_on"]),
        "verified_release_bps": calc.verified_release_bps(rec),
        "settled_funded_cents": calc.settled_funded_cents(rec),
        "funded_pct_bps": calc.funded_pct_bps(rec),
        "max_fundable_now_cents": calc.max_fundable_now_cents(rec),
        "disputed_amount_cents": calc.disputed_amount_cents(rec),
    })
    return out


def milestone(rec):
    out = _common(rec)
    out.update({
        "project_id": rec["project_id"],
        "sequence_no": rec["sequence_no"],
        "name": rec["name"],
        "release_pct_bps": rec["release_pct_bps"],
        "requires_consumer_signoff": rec["requires_consumer_signoff"],
        "status": rec["status"],
        "claimed_at": _dt(rec["claimed_at"]),
        "verified_at": _dt(rec["verified_at"]),
        "rejection_count": rec["rejection_count"],
        "evidence_ref": rec["evidence_ref"],
        "is_funded": calc.milestone_is_funded(rec),
    })
    return out


def draw(rec):
    out = _common(rec)
    out.update({
        "loan_account_id": rec["loan_account_id"],
        "project_milestone_id": rec["project_milestone_id"],
        "merchant_id": rec["merchant_id"],
        "requested_amount_cents": rec["requested_amount_cents"],
        "settlement_speed": rec["settlement_speed"],
        "status": rec["status"],
        "funded_amount_cents": rec["funded_amount_cents"],
        "provisional_discount_cents": rec["provisional_discount_cents"],
        "provisional_holdback_cents": rec["provisional_holdback_cents"],
        "provisional_net_settlement_cents": rec["provisional_net_settlement_cents"],
        "effective_discount_bps": rec["effective_discount_bps"],
        "volume_tier_credit_bps": rec["volume_tier_credit_bps"],
        "merchant_discount_cents": rec["merchant_discount_cents"],
        "holdback_withheld_cents": rec["holdback_withheld_cents"],
        "net_settlement_cents": rec["net_settlement_cents"],
        "settled_on": rec["settled_on"],
        "released_by_user_id": rec["released_by_user_id"],
        "denial_reason_code": rec["denial_reason_code"],
        "reversal_reason_code": rec["reversal_reason_code"],
    })
    return out


def dispute(rec):
    out = _common(rec)
    out.update({
        "loan_account_id": rec["loan_account_id"],
        "project_id": rec["project_id"],
        "merchant_id": rec["merchant_id"],
        "reopens_case_id": rec["reopens_case_id"],
        "claimed_incomplete_amount_cents": rec["claimed_incomplete_amount_cents"],
        "description": rec["description"],
        "status": rec["status"],
        "opened_on": rec["opened_on"],
        "response_due_at": _dt(rec["response_due_at"]),
        "merchant_responded_at": _dt(rec["merchant_responded_at"]),
        "response_type": rec["response_type"],
        "evidence_ref": rec["evidence_ref"],
        "chargeback_amount_cents": rec["chargeback_amount_cents"],
        "chargeback_absorbed_from_reserve_cents":
            rec["chargeback_absorbed_from_reserve_cents"],
        "chargeback_receivable_cents": rec["chargeback_receivable_cents"],
        "chargeback_write_off_cents": rec["chargeback_write_off_cents"],
        "resolved_by_user_id": rec["resolved_by_user_id"],
        "resolved_on": rec["resolved_on"],
    })
    return out


def fraud_alert(rec):
    out = _common(rec)
    out.update({
        "merchant_id": rec["merchant_id"],
        "alert_type": rec["alert_type"],
        "severity_weight": rec["severity_weight"],
        "source": rec["source"],
        "status": rec["status"],
        "evidence_ref": rec["evidence_ref"],
        "opened_on": rec["opened_on"],
        "investigated_by_user_id": rec["investigated_by_user_id"],
        "investigation_note": rec["investigation_note"],
    })
    return out


def payment(rec):
    out = _common(rec, versioned=False)
    out.update({
        "loan_account_id": rec["loan_account_id"],
        "amount_cents": rec["amount_cents"],
        "posted_on": rec["posted_on"],
        "applied_to_capitalized_interest_cents":
            rec["applied_to_capitalized_interest_cents"],
        "applied_to_principal_cents": rec["applied_to_principal_cents"],
        "resulting_principal_balance_cents": rec["resulting_principal_balance_cents"],
        "source_role": rec["source_role"],
    })
    return out
