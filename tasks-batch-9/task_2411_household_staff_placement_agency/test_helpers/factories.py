"""Payload factories — one per entity and per action endpoint, input fields only."""
from .constants import BASE_SCENARIO


# --- Households --------------------------------------------------------------


def create_client_payload(**overrides) -> dict:
    payload = {
        "household_name": BASE_SCENARIO["HOUSEHOLD_NAME"],
        "primary_contact_email": BASE_SCENARIO["CONTACT_EMAIL"],
        "region_code": BASE_SCENARIO["REGION_CODE"],
    }
    payload.update(overrides)
    return payload


def sign_agreement_payload(**overrides) -> dict:
    payload = {
        "action": "SIGN",
        "signatory_name": BASE_SCENARIO["SIGNATORY_NAME"],
    }
    payload.update(overrides)
    return payload


def countersign_agreement_payload(**overrides) -> dict:
    payload = {"action": "COUNTERSIGN"}
    payload.update(overrides)
    return payload


def ledger_adjustment_payload(signed_amount_cents=100_000, **overrides) -> dict:
    payload = {
        "entry_type": "MANUAL_ADJUSTMENT",
        "signed_amount_cents": signed_amount_cents,
        "memo": "Manual movement recorded by the receivables desk.",
    }
    payload.update(overrides)
    return payload


# --- Fee schedules -----------------------------------------------------------


def create_fee_schedule_payload(**overrides) -> dict:
    payload = {
        "role_type": BASE_SCENARIO["ROLE_TYPE"],
        "comp_band_floor_cents": BASE_SCENARIO["BAND_FLOOR_CENTS"],
        "comp_band_ceiling_cents": BASE_SCENARIO["BAND_CEILING_CENTS"],
        "fee_percent_bps": BASE_SCENARIO["FEE_PERCENT_BPS"],
        "guarantee_window_days": BASE_SCENARIO["GUARANTEE_WINDOW_DAYS"],
        "effective_from": BASE_SCENARIO["EFFECTIVE_FROM"],
    }
    payload.update(overrides)
    return payload


# --- Role requisitions -------------------------------------------------------


def create_requisition_payload(client_id, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "role_type": BASE_SCENARIO["ROLE_TYPE"],
        "first_year_compensation_cents": BASE_SCENARIO["COMPENSATION_CENTS"],
        "schedule_pattern": BASE_SCENARIO["SCHEDULE_PATTERN"],
    }
    payload.update(overrides)
    return payload


def scope_requisition_payload(**overrides) -> dict:
    payload = {"scope_note": BASE_SCENARIO["SCOPE_NOTE"]}
    payload.update(overrides)
    return payload


def finalize_scope_payload(**overrides) -> dict:
    payload = {"note": "Fee band resolved."}
    payload.update(overrides)
    return payload


def withdraw_requisition_payload(**overrides) -> dict:
    payload = {"reason": "The household paused the search."}
    payload.update(overrides)
    return payload


# --- Candidates --------------------------------------------------------------


def create_candidate_payload(**overrides) -> dict:
    payload = {
        "full_name": BASE_SCENARIO["CANDIDATE_NAME"],
        "contact_email": BASE_SCENARIO["CANDIDATE_EMAIL"],
        "primary_role_type": BASE_SCENARIO["ROLE_TYPE"],
        "years_experience": BASE_SCENARIO["YEARS_EXPERIENCE"],
        "live_in_willing": True,
    }
    payload.update(overrides)
    return payload


def create_reference_check_payload(**overrides) -> dict:
    payload = {
        "principal_employer_name": "Whitfield Residence",
        "relationship_type": "PRINCIPAL_EMPLOYER",
        "employment_start_month": "2022-01",
        "employment_end_month": "2022-12",
        "contact_email": "whitfield@mail.example",
    }
    payload.update(overrides)
    return payload


def verify_reference_payload(outcome="VERIFIED", **overrides) -> dict:
    payload = {
        "outcome": outcome,
        "verification_note": "Confirmed by telephone.",
    }
    payload.update(overrides)
    return payload


def create_background_verification_payload(**overrides) -> dict:
    payload = {
        "provider_reference": "BV-2411-01",
        "scope_items": ["IDENTITY", "CRIMINAL", "DMV"],
    }
    payload.update(overrides)
    return payload


def record_background_result_payload(result="CLEARED", **overrides) -> dict:
    payload = {
        "result": result,
        "findings_note": "No adverse findings.",
    }
    payload.update(overrides)
    return payload


def adjudicate_background_payload(
    disposition, expected_candidate_version, **overrides
) -> dict:
    payload = {
        "disposition": disposition,
        "expected_candidate_version": expected_candidate_version,
        "waiver_note": "Reviewed by the agency principal.",
    }
    payload.update(overrides)
    return payload


def release_availability_payload(**overrides) -> dict:
    payload = {"note": "Returned to the available pool."}
    payload.update(overrides)
    return payload


# --- Trial engagements -------------------------------------------------------


def create_trial_engagement_payload(candidate_id, **overrides) -> dict:
    payload = {
        "candidate_id": candidate_id,
        "engagement_type": "TRIAL_DAY",
        "start_at": "2026-08-10T09:00:00Z",
        "end_at": "2026-08-10T17:00:00Z",
        "day_rate_cents": BASE_SCENARIO["TRIAL_DAY_RATE_CENTS"],
    }
    payload.update(overrides)
    return payload


def start_trial_payload(**overrides) -> dict:
    payload = {"note": "Household received the candidate."}
    payload.update(overrides)
    return payload


def record_trial_outcome_payload(outcome="PASSED", **overrides) -> dict:
    payload = {
        "outcome": outcome,
        "outcome_note": "Household verdict recorded.",
    }
    payload.update(overrides)
    return payload


def cancel_trial_payload(cancel_reason="CLIENT_REQUEST", **overrides) -> dict:
    payload = {
        "cancel_reason": cancel_reason,
        "note": "Cancellation recorded.",
    }
    payload.update(overrides)
    return payload


# --- Accommodation terms -----------------------------------------------------


def create_accommodation_term_payload(
    candidate_id, expected_requisition_version, **overrides
) -> dict:
    payload = {
        "candidate_id": candidate_id,
        "live_in": False,
        "weekly_hours": 40,
        "days_off_per_week": 2,
        "private_quarters": False,
        "imputed_accommodation_cents": 0,
        "expected_requisition_version": expected_requisition_version,
        "note": "Opening position on hours and accommodation.",
    }
    payload.update(overrides)
    return payload


def respond_accommodation_term_payload(response="ACCEPT", **overrides) -> dict:
    payload = {
        "response": response,
        "note": "Response recorded.",
    }
    payload.update(overrides)
    return payload


# --- Placements --------------------------------------------------------------


def create_placement_payload(
    requisition_id, candidate_id, expected_requisition_version, **overrides
) -> dict:
    payload = {
        "requisition_id": requisition_id,
        "candidate_id": candidate_id,
        "start_date": BASE_SCENARIO["START_DATE"],
        "base_salary_cents": BASE_SCENARIO["BASE_SALARY_CENTS"],
        "guaranteed_bonus_cents": BASE_SCENARIO["GUARANTEED_BONUS_CENTS"],
        "accommodation_imputed_cents": BASE_SCENARIO["ACCOMMODATION_IMPUTED_CENTS"],
        "overtime_allowance_cents": BASE_SCENARIO["OVERTIME_ALLOWANCE_CENTS"],
        "expected_requisition_version": expected_requisition_version,
    }
    payload.update(overrides)
    return payload


def confirm_start_payload(**overrides) -> dict:
    payload = {"note": "Package confirmed on the start date."}
    payload.update(overrides)
    return payload


def terminate_placement_payload(separation_date, **overrides) -> dict:
    payload = {
        "separation_date": separation_date,
        "note": "The household and the candidate separated.",
    }
    payload.update(overrides)
    return payload


# --- Fee milestones ----------------------------------------------------------


def invoice_milestone_payload(**overrides) -> dict:
    payload = {"note": "Milestone invoiced."}
    payload.update(overrides)
    return payload


def record_payment_payload(paid_amount_cents, **overrides) -> dict:
    payload = {
        "paid_amount_cents": paid_amount_cents,
        "payment_reference": BASE_SCENARIO["PAYMENT_REFERENCE"],
    }
    payload.update(overrides)
    return payload


def reverse_milestone_payload(**overrides) -> dict:
    payload = {"reason": "Billing correction."}
    payload.update(overrides)
    return payload


# --- Replacement claims ------------------------------------------------------


def create_replacement_claim_payload(
    requested_remedy, separation_date, expected_placement_version, **overrides
) -> dict:
    payload = {
        "requested_remedy": requested_remedy,
        "separation_date": separation_date,
        "narrative": "The placement did not hold and the household seeks a remedy.",
        "expected_placement_version": expected_placement_version,
    }
    payload.update(overrides)
    return payload


def review_claim_payload(action, **overrides) -> dict:
    payload = {
        "action": action,
        "decision_note": "Claim reviewed by the agency principal.",
    }
    payload.update(overrides)
    return payload


def provide_claim_info_payload(**overrides) -> dict:
    payload = {"info_note": "Household supplied the requested detail."}
    payload.update(overrides)
    return payload


# --- Payroll handoffs --------------------------------------------------------


def create_payroll_handoff_payload(**overrides) -> dict:
    payload = {
        "provider_name": "Domestic Payroll Partners",
        "guidance_packet_version": "NY-2026.1",
    }
    payload.update(overrides)
    return payload


def update_ein_payload(ein_status="ISSUED", **overrides) -> dict:
    payload = {"ein_status": ein_status}
    payload.update(overrides)
    return payload


def attest_handoff_payload(**overrides) -> dict:
    payload = {"attested_by_name": BASE_SCENARIO["SIGNATORY_NAME"]}
    payload.update(overrides)
    return payload


# --- Non-solicitation enforcement -------------------------------------------


def create_non_solicitation_case_payload(
    respondent_client_id, candidate_id, discovered_on, **overrides
) -> dict:
    payload = {
        "respondent_client_id": respondent_client_id,
        "candidate_id": candidate_id,
        "allegation_note": "The household approached the candidate directly.",
        "discovered_on": discovered_on,
    }
    payload.update(overrides)
    return payload


def investigate_case_payload(**overrides) -> dict:
    payload = {"note": "Investigation opened."}
    payload.update(overrides)
    return payload


def resolve_case_payload(disposition, **overrides) -> dict:
    payload = {
        "disposition": disposition,
        "findings_note": "Findings recorded by the compliance desk.",
    }
    payload.update(overrides)
    return payload


def settle_case_payload(settlement_amount_cents, **overrides) -> dict:
    payload = {"settlement_amount_cents": settlement_amount_cents}
    payload.update(overrides)
    return payload
