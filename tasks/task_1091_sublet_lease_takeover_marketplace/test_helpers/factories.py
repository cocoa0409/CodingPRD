"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "MONTHLY_RENT": 300000,
    "SECURITY_DEPOSIT": 500000,
    "ASKING_RENT": 300000,
    "ANNUAL_INCOME": 15000000,
    "CREDIT_SCORE": 720,
    "TERM_START": "2026-01-01",
    "TERM_END": "2026-12-31",
    "AVAILABLE_FROM": "2026-06-01",
    "AVAILABLE_TO": "2026-12-31",
}


def create_landlord_payload(**overrides) -> dict:
    defaults = {"name": "LL", "email": "ll@x.com"}
    defaults.update(overrides)
    return defaults


def create_leaseholder_payload(**overrides) -> dict:
    defaults = {"name": "LH", "email": "lh@x.com"}
    defaults.update(overrides)
    return defaults


def create_applicant_payload(**overrides) -> dict:
    defaults = {
        "name": "AP",
        "email": "ap@x.com",
        "annual_income_cents": DEFAULTS["ANNUAL_INCOME"],
        "monthly_debt_cents": 0,
        "credit_score": DEFAULTS["CREDIT_SCORE"],
    }
    defaults.update(overrides)
    return defaults


def create_lease_payload(landlord_id, leaseholder_id, **overrides) -> dict:
    defaults = {
        "landlord_id": landlord_id,
        "leaseholder_id": leaseholder_id,
        "monthly_rent_cents": DEFAULTS["MONTHLY_RENT"],
        "security_deposit_cents": DEFAULTS["SECURITY_DEPOSIT"],
        "term_start_date": DEFAULTS["TERM_START"],
        "term_end_date": DEFAULTS["TERM_END"],
        "allows_sublet": True,
        "allows_assignment": False,
    }
    defaults.update(overrides)
    return defaults


def create_listing_payload(lease_id, **overrides) -> dict:
    defaults = {
        "lease_id": lease_id,
        "listing_type": "SUBLET",
        "asking_rent_cents": DEFAULTS["ASKING_RENT"],
        "available_from": DEFAULTS["AVAILABLE_FROM"],
        "available_to": DEFAULTS["AVAILABLE_TO"],
        "min_term_months": 2,
        "screening_policy": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(listing_id, applicant_id, **overrides) -> dict:
    defaults = {
        "listing_id": listing_id,
        "applicant_id": applicant_id,
        "proposed_move_in_date": "2026-06-10",
        "proposed_move_out_date": "2026-08-31",
    }
    defaults.update(overrides)
    return defaults


def create_screening_report_payload(**overrides) -> dict:
    defaults = {"credit_score": DEFAULTS["CREDIT_SCORE"], "income_verified": True}
    defaults.update(overrides)
    return defaults


def create_agreement_payload(application_id, expected_listing_version, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "expected_listing_version": expected_listing_version,
        "occupancy_start_date": "2026-06-10",
        "occupancy_end_date": "2026-08-31",
    }
    defaults.update(overrides)
    return defaults


def create_signature_payload(signer_role, **overrides) -> dict:
    defaults = {"signer_role": signer_role}
    defaults.update(overrides)
    return defaults


def create_dispute_payload(agreement_id, raised_by, **overrides) -> dict:
    defaults = {"agreement_id": agreement_id, "raised_by": raised_by, "reason": "dispute reason"}
    defaults.update(overrides)
    return defaults


def create_fee_payload(agreement_id, fee_type, amount_cents, **overrides) -> dict:
    defaults = {"agreement_id": agreement_id, "fee_type": fee_type, "amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_appointment_payload(agreement_id, scheduled_start, scheduled_end, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults
