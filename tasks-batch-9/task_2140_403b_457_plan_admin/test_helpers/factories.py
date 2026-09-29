"""Payload factories — one per entity, input fields only."""

from .constants import TEST_DEFAULTS

DEFAULTS = {
    "EMPLOYER_NAME": "Riverbend Unified School District",
    "EMPLOYER_EIN": "11-1111111",
    "VENDOR_NAME": "Northline Annuity",
    "VENDOR_CODE": "NLA",
    "VENDOR_EMAIL": "ops@northline.example",
    "PLAN_NAME": "Riverbend 403(b)",
    "PARTICIPANT_NAME": "Ada Reyes",
    "PARTICIPANT_DOB": "1975-05-05",
    "PARTICIPANT_HIRE_DATE": "2014-08-01",
    "CONTRACT_NUMBER": "NLA-0001",
}


def create_employer_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["EMPLOYER_NAME"],
        "ein": DEFAULTS["EMPLOYER_EIN"],
        "entity_type": "PUBLIC_SCHOOL",
        "organization_subtype": "SCHOOL",
        "total_employee_count": 400,
    }
    payload.update(overrides)
    return payload


def create_vendor_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["VENDOR_NAME"],
        "vendor_code": DEFAULTS["VENDOR_CODE"],
        "contact_email": DEFAULTS["VENDOR_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_plan_payload(employer_id: str, **overrides) -> dict:
    payload = {
        "employer_id": employer_id,
        "plan_name": DEFAULTS["PLAN_NAME"],
        "plan_type": "PLAN_403B",
        "plan_year": TEST_DEFAULTS["PLAN_YEAR"],
        "reported_participant_count": TEST_DEFAULTS["LARGE_PLAN_PARTICIPANT_COUNT"],
    }
    payload.update(overrides)
    return payload


def create_agreement_payload(plan_id: str, vendor_id: str, **overrides) -> dict:
    payload = {
        "plan_id": plan_id,
        "vendor_id": vendor_id,
        "effective_from": TEST_DEFAULTS["AGREEMENT_FROM"],
        "effective_through": TEST_DEFAULTS["AGREEMENT_THROUGH"],
    }
    payload.update(overrides)
    return payload


def create_participant_payload(employer_id: str, **overrides) -> dict:
    payload = {
        "employer_id": employer_id,
        "full_name": DEFAULTS["PARTICIPANT_NAME"],
        "date_of_birth": DEFAULTS["PARTICIPANT_DOB"],
        "hire_date": DEFAULTS["PARTICIPANT_HIRE_DATE"],
        "scheduled_hours_per_week": 40,
        "prior_year_hours_worked": 2000,
        "includible_compensation_cents": 9_000_000,
        "years_of_service": 12,
    }
    payload.update(overrides)
    return payload


def create_notice_payload(**overrides) -> dict:
    payload = {
        "plan_year": TEST_DEFAULTS["PLAN_YEAR"],
        "issued_date": TEST_DEFAULTS["NOTICE_ISSUED_DATE"],
        "delivery_method": "EMAIL",
        "recipient_count": TEST_DEFAULTS["LARGE_PLAN_PARTICIPANT_COUNT"],
        "describes_effective_opportunity": True,
    }
    payload.update(overrides)
    return payload


def create_eligibility_determination_payload(plan_id: str, participant_id: str, **overrides) -> dict:
    payload = {"plan_id": plan_id, "participant_id": participant_id}
    payload.update(overrides)
    return payload


def create_vendor_account_payload(
    participant_id: str, plan_id: str, vendor_id: str, **overrides
) -> dict:
    payload = {
        "participant_id": participant_id,
        "plan_id": plan_id,
        "vendor_id": vendor_id,
        "contract_number": DEFAULTS["CONTRACT_NUMBER"],
        "accumulated_benefit_cents": 5_000_000,
        "vested_percentage_bps": 10_000,
    }
    payload.update(overrides)
    return payload


def create_balance_report_payload(expected_vendor_account_version: int, **overrides) -> dict:
    payload = {
        "expected_vendor_account_version": expected_vendor_account_version,
        "as_of_date": TEST_DEFAULTS["FRESH_FEED_DATE"],
        "accumulated_benefit_cents": 5_000_000,
        "outstanding_loan_balance_cents": 0,
        "highest_outstanding_loan_12mo_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_election_payload(
    participant_id: str,
    plan_id: str,
    vendor_account_id: str,
    expected_participant_version: int,
    **overrides,
) -> dict:
    payload = {
        "participant_id": participant_id,
        "plan_id": plan_id,
        "vendor_account_id": vendor_account_id,
        "annual_deferral_amount_cents": 1_000_000,
        "effective_from": "2026-09-01",
        "effective_through": "2026-12-31",
        "expected_participant_version": expected_participant_version,
    }
    payload.update(overrides)
    return payload


def create_remittance_batch_payload(plan_id: str, line_items, **overrides) -> dict:
    total = sum(item["elective_deferral_cents"] for item in line_items)
    payload = {
        "plan_id": plan_id,
        "pay_period_start": "2026-07-01",
        "pay_period_end": "2026-07-16",
        "withholding_date": "2026-07-15",
        "total_elective_deferral_cents": total,
        "line_items": line_items,
    }
    payload.update(overrides)
    return payload


def make_line_item(vendor_account_id: str, elective_deferral_cents: int,
                   employer_contribution_cents: int = 0) -> dict:
    return {
        "vendor_account_id": vendor_account_id,
        "elective_deferral_cents": elective_deferral_cents,
        "employer_contribution_cents": employer_contribution_cents,
    }


def create_participant_request_payload(
    participant_id: str, plan_id: str, vendor_account_id: str, request_type: str, **overrides
) -> dict:
    payload = {
        "participant_id": participant_id,
        "plan_id": plan_id,
        "vendor_account_id": vendor_account_id,
        "request_type": request_type,
        "requested_amount_cents": 100_000,
    }
    payload.update(overrides)
    return payload


def create_movement_request_payload(
    participant_id: str,
    request_kind: str,
    source_plan_id: str,
    destination_plan_id: str,
    source_vendor_account_id: str,
    destination_vendor_account_id: str,
    amount_cents: int,
    **overrides,
) -> dict:
    payload = {
        "participant_id": participant_id,
        "request_kind": request_kind,
        "source_plan_id": source_plan_id,
        "destination_plan_id": destination_plan_id,
        "source_vendor_account_id": source_vendor_account_id,
        "destination_vendor_account_id": destination_vendor_account_id,
        "amount_cents": amount_cents,
    }
    payload.update(overrides)
    return payload
