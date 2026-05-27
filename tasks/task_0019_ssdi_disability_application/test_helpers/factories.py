"""Payload factories — one per entity, input fields only (PRD §3, §4)."""


# ---------- Claimant ----------

def create_claimant_payload(
    ssn_last4: str = "1234",
    full_name: str = "Test Claimant",
    date_of_birth: str = "1980-01-01T00:00:00Z",
    filing_state: str = "TX",
    monthly_income_cents: int = None,
    countable_resources_cents: int = None,
    **overrides,
) -> dict:
    payload = {
        "ssn_last4": ssn_last4,
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "filing_state": filing_state,
    }
    if monthly_income_cents is not None:
        payload["monthly_income_cents"] = monthly_income_cents
    if countable_resources_cents is not None:
        payload["countable_resources_cents"] = countable_resources_cents
    payload.update(overrides)
    return payload


# ---------- WorkCreditRecord ----------

def create_work_credit_payload(
    claimant_id: str,
    year: int,
    credits_earned: int = 4,
    earnings_cents: int = 4_800_000,
    **overrides,
) -> dict:
    payload = {
        "claimant_id": claimant_id,
        "year": year,
        "credits_earned": credits_earned,
        "earnings_cents": earnings_cents,
    }
    payload.update(overrides)
    return payload


# ---------- Application ----------

def create_application_payload(
    claimant_id: str,
    alleged_onset_date: str = "2024-01-01T00:00:00Z",
    protective_filing_date: str = "2026-01-15T00:00:00Z",
    claim_type: str = "SSDI_ONLY",
    **overrides,
) -> dict:
    payload = {
        "claimant_id": claimant_id,
        "alleged_onset_date": alleged_onset_date,
        "protective_filing_date": protective_filing_date,
        "claim_type": claim_type,
    }
    payload.update(overrides)
    return payload


# ---------- MedicalEvidence ----------

def create_evidence_payload(
    source_type: str = "TREATING_PHYSICIAN",
    report_date: str = "2024-02-01T00:00:00Z",
    diagnosis_code: str = "M54.5",
    severity_score: int = 80,
    **overrides,
) -> dict:
    payload = {
        "source_type": source_type,
        "report_date": report_date,
        "diagnosis_code": diagnosis_code,
        "severity_score": severity_score,
    }
    payload.update(overrides)
    return payload


# ---------- MedicalDeterminationDecision ----------

def medical_decision_payload(
    decision_type: str,
    established_onset_date: str,
    expected_application_version: int,
    listing_reference: str = None,
    rfc_score: int = None,
    **overrides,
) -> dict:
    payload = {
        "decision_type": decision_type,
        "established_onset_date": established_onset_date,
        "expected_application_version": expected_application_version,
    }
    if listing_reference is not None:
        payload["listing_reference"] = listing_reference
    if rfc_score is not None:
        payload["rfc_score"] = rfc_score
    payload.update(overrides)
    return payload


# ---------- HearingRequest schedule / decision ----------

def schedule_hearing_payload(scheduled_date: str, **overrides) -> dict:
    payload = {"scheduled_date": scheduled_date}
    payload.update(overrides)
    return payload


def hearing_decision_payload(outcome: str, **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


# ---------- ChildAuxiliaryBenefit ----------

def create_child_auxiliary_payload(
    child_full_name: str,
    child_date_of_birth: str,
    relationship: str,
    expected_benefit_award_version: int,
    **overrides,
) -> dict:
    payload = {
        "child_full_name": child_full_name,
        "child_date_of_birth": child_date_of_birth,
        "relationship": relationship,
        "expected_benefit_award_version": expected_benefit_award_version,
    }
    payload.update(overrides)
    return payload


# ---------- CDRReview complete ----------

def complete_cdr_payload(outcome: str, **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


# ---------- Test-driving clock ----------

def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
