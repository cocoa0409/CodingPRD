"""Payload factories — one per entity, only `source: input` fields.

Defaults are PRD-driven: PRD §3.1 says entity_size defaults to LARGE and
prior_applications_filed defaults to 0. Factories surface those defaults
through **overrides** so individual tests control only what they need.
"""


def create_applicant_payload(legal_name: str = "Test Applicant",
                             entity_size: str = "LARGE",
                             prior_applications_filed: int = 0,
                             micro_qualifying_year: int = None,
                             gross_income_prior_year_cents: int = None,
                             **overrides) -> dict:
    payload = {
        "legal_name": legal_name,
        "entity_size": entity_size,
        "prior_applications_filed": prior_applications_filed,
    }
    if micro_qualifying_year is not None:
        payload["micro_qualifying_year"] = micro_qualifying_year
    if gross_income_prior_year_cents is not None:
        payload["gross_income_prior_year_cents"] = gross_income_prior_year_cents
    payload.update(overrides)
    return payload


def create_application_payload(applicant_id: str,
                               application_type: str = "UTILITY",
                               title: str = "Test invention",
                               claim_count: int = 10,
                               independent_claim_count: int = 2,
                               parent_application_id: str = None,
                               continuation_type: str = None,
                               **overrides) -> dict:
    payload = {
        "applicant_id": applicant_id,
        "application_type": application_type,
        "title": title,
        "claim_count": claim_count,
        "independent_claim_count": independent_claim_count,
    }
    if parent_application_id is not None:
        payload["parent_application_id"] = parent_application_id
    if continuation_type is not None:
        payload["continuation_type"] = continuation_type
    payload.update(overrides)
    return payload


def create_office_action_payload(application_id: str,
                                 action_type: str = "NON_FINAL",
                                 **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "action_type": action_type,
    }
    payload.update(overrides)
    return payload


def create_office_action_response_payload(office_action_id: str,
                                          extension_months_requested: int = 0,
                                          claim_amendment_count: int = 10,
                                          **overrides) -> dict:
    payload = {
        "office_action_id": office_action_id,
        "extension_months_requested": extension_months_requested,
        "claim_amendment_count": claim_amendment_count,
    }
    payload.update(overrides)
    return payload


def create_fee_payment_payload(application_id: str,
                               payment_category: str,
                               amount_cents: int,
                               maintenance_fee_id: str = None,
                               **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "payment_category": payment_category,
        "amount_cents": amount_cents,
    }
    if maintenance_fee_id is not None:
        payload["maintenance_fee_id"] = maintenance_fee_id
    payload.update(overrides)
    return payload


def create_pct_phase_entry_payload(application_id: str,
                                   pct_international_filing_date: str,
                                   **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "pct_international_filing_date": pct_international_filing_date,
    }
    payload.update(overrides)
    return payload


def create_pay_issue_fee_payload(amount_cents: int,
                                 expected_application_version: int,
                                 **overrides) -> dict:
    payload = {
        "amount_cents": amount_cents,
        "expected_application_version": expected_application_version,
    }
    payload.update(overrides)
    return payload


def create_convert_provisional_payload(title: str,
                                       claim_count: int,
                                       independent_claim_count: int,
                                       expected_application_version: int,
                                       **overrides) -> dict:
    payload = {
        "title": title,
        "claim_count": claim_count,
        "independent_claim_count": independent_claim_count,
        "expected_application_version": expected_application_version,
    }
    payload.update(overrides)
    return payload
