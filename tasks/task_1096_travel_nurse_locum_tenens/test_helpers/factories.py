"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "LOCALITY_CODE": "PHX-AZ",
    "LOCALITY_STATE": "AZ",
    "DAILY_LODGING_CENTS": 15000,
    "DAILY_MIE_CENTS": 7900,
    "EFFECTIVE_FROM": "2026-01-01",
    "FACILITY_NAME": "Desert Valley Medical Center",
    "FACILITY_STATE": "AZ",
    "BILLING_EMAIL": "ap@dvmc.example",
    "CLIN_NAME": "Ada Reyes",
    "DISCIPLINE": "RN",
    "SPECIALTY": "ICU",
    "EMPLOYMENT_TYPE": "W2_EMPLOYEE",
    "RESIDENCE_STATE": "TX",
    "LICENSE_STATE": "TX",
    "LICENSE_TYPE": "RN",
    "LICENSE_NUMBER": "TX-RN-88120",
    "LICENSE_EXPIRES": "2027-12-31",
    "START_DATE": "2026-06-07",
    "TERM_WEEKS": 13,
    "WEEKLY_GUARANTEED_HOURS": 36,
    "BASE_PAY": 5200,
    "BILL_RATE": 14000,
}


def create_per_diem_locality_payload(**overrides):
    p = {
        "locality_code": DEFAULTS["LOCALITY_CODE"],
        "state_code": DEFAULTS["LOCALITY_STATE"],
        "daily_lodging_cents": DEFAULTS["DAILY_LODGING_CENTS"],
        "daily_mie_cents": DEFAULTS["DAILY_MIE_CENTS"],
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
    }
    p.update(overrides)
    return p


def create_facility_payload(**overrides):
    p = {
        "name": DEFAULTS["FACILITY_NAME"],
        "state_code": DEFAULTS["FACILITY_STATE"],
        "per_diem_locality_code": DEFAULTS["LOCALITY_CODE"],
        "billing_contact_email": DEFAULTS["BILLING_EMAIL"],
        "is_compact_member": True,
        "max_concurrent_travelers": 2,
    }
    p.update(overrides)
    return p


def create_clinician_payload(**overrides):
    p = {
        "full_name": DEFAULTS["CLIN_NAME"],
        "discipline": DEFAULTS["DISCIPLINE"],
        "specialty": DEFAULTS["SPECIALTY"],
        "employment_type": DEFAULTS["EMPLOYMENT_TYPE"],
        "primary_residence_state": DEFAULTS["RESIDENCE_STATE"],
        "tax_home_verified": True,
    }
    p.update(overrides)
    return p


def create_license_payload(clinician_id, **overrides):
    p = {
        "clinician_id": clinician_id,
        "state_code": DEFAULTS["LICENSE_STATE"],
        "license_type": DEFAULTS["LICENSE_TYPE"],
        "license_number": DEFAULTS["LICENSE_NUMBER"],
        "expires_on": DEFAULTS["LICENSE_EXPIRES"],
        "is_compact": True,
    }
    p.update(overrides)
    return p


def create_assignment_payload(clinician_id, facility_id, **overrides):
    p = {
        "clinician_id": clinician_id,
        "facility_id": facility_id,
        "specialty": DEFAULTS["SPECIALTY"],
        "required_license_type": DEFAULTS["LICENSE_TYPE"],
        "start_date": DEFAULTS["START_DATE"],
        "term_weeks": DEFAULTS["TERM_WEEKS"],
        "weekly_guaranteed_hours": DEFAULTS["WEEKLY_GUARANTEED_HOURS"],
        "base_pay_rate_cents_per_hour": DEFAULTS["BASE_PAY"],
        "bill_rate_cents_per_hour": DEFAULTS["BILL_RATE"],
        "shift": "DAY",
    }
    p.update(overrides)
    return p


def create_credential_item_payload(item_type, document_ref="doc-ref", expires_on="2027-12-31", **overrides):
    p = {"item_type": item_type, "document_ref": document_ref}
    if expires_on is not None:
        p["expires_on"] = expires_on
    p.update(overrides)
    return p


def create_timesheet_payload(assignment_id, week_start_date, daily_hours, callback_hours=0, **overrides):
    p = {
        "assignment_id": assignment_id,
        "week_start_date": week_start_date,
        "daily_hours": daily_hours,
        "callback_hours": callback_hours,
    }
    p.update(overrides)
    return p


def create_extension_payload(expected_assignment_version, proposed_additional_weeks,
                             proposed_pay_rate_cents_per_hour, proposed_bill_rate_cents_per_hour, **overrides):
    p = {
        "expected_assignment_version": expected_assignment_version,
        "proposed_additional_weeks": proposed_additional_weeks,
        "proposed_pay_rate_cents_per_hour": proposed_pay_rate_cents_per_hour,
        "proposed_bill_rate_cents_per_hour": proposed_bill_rate_cents_per_hour,
    }
    p.update(overrides)
    return p


def revise_contract_payload(expected_contract_version, term_weeks, weekly_guaranteed_hours,
                            base_pay_rate_cents_per_hour, bill_rate_cents_per_hour, **overrides):
    p = {
        "expected_contract_version": expected_contract_version,
        "term_weeks": term_weeks,
        "weekly_guaranteed_hours": weekly_guaranteed_hours,
        "base_pay_rate_cents_per_hour": base_pay_rate_cents_per_hour,
        "bill_rate_cents_per_hour": bill_rate_cents_per_hour,
    }
    p.update(overrides)
    return p
