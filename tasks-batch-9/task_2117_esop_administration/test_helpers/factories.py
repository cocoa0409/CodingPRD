"""Payload factories — one per entity, input fields only."""

PLAN_DEFAULTS = {
    "plan_name": "Ironwood Manufacturing ESOP",
    "sponsor_name": "Ironwood Manufacturing Inc.",
    "plan_year": 2026,
    "total_shares_outstanding": 1_000_000,
    "vesting_schedule": "GRADED_6YR",
    "service_measurement_method": "TERMINATION_DATE_MEASURE",
    "forfeiture_policy": "REALLOCATE_PRO_RATA",
    "distribution_policy": "FIVE_YEAR_INSTALLMENT",
}

PARTICIPANT_DEFAULTS = {
    "employee_number": "E-001",
    "date_of_birth": "1980-04-11",
    "hire_date": "2015-01-05",
    "eligible_compensation_cents": 34_500_000,
}

VALUATION_DEFAULTS = {
    "plan_year": 2026,
    "enterprise_value_cents": 12_000_000_000,
    "debt_outstanding_cents": 3_000_000_000,
    "non_operating_assets_cents": 500_000_000,
    "control_premium_bps": 1500,
    "marketability_discount_bps": 2500,
    "effective_from_date": "2026-01-01",
    "effective_to_date": "2027-01-01",
}

LOAN_DEFAULTS = {
    "lender_name": "First Meridian Bank",
    "original_principal_cents": 4_000_000_000,
    "original_interest_cents": 1_600_000_000,
    "shares_pledged": 600_000,
    "release_method": "PRINCIPAL_ONLY",
}


def create_plan_payload(**overrides) -> dict:
    payload = dict(PLAN_DEFAULTS)
    payload.update(overrides)
    return payload


def create_participant_payload(plan_id, **overrides) -> dict:
    payload = dict(PARTICIPANT_DEFAULTS)
    payload["plan_id"] = plan_id
    payload.update(overrides)
    return payload


def create_valuation_payload(plan_id, expected_plan_version, **overrides) -> dict:
    payload = dict(VALUATION_DEFAULTS)
    payload["plan_id"] = plan_id
    payload["expected_plan_version"] = expected_plan_version
    payload.update(overrides)
    return payload


def resubmit_valuation_payload(**overrides) -> dict:
    payload = {
        "enterprise_value_cents": VALUATION_DEFAULTS["enterprise_value_cents"],
        "debt_outstanding_cents": VALUATION_DEFAULTS["debt_outstanding_cents"],
        "non_operating_assets_cents": VALUATION_DEFAULTS["non_operating_assets_cents"],
        "control_premium_bps": VALUATION_DEFAULTS["control_premium_bps"],
        "marketability_discount_bps": VALUATION_DEFAULTS["marketability_discount_bps"],
    }
    payload.update(overrides)
    return payload


def create_loan_payload(plan_id, **overrides) -> dict:
    payload = dict(LOAN_DEFAULTS)
    payload["plan_id"] = plan_id
    payload.update(overrides)
    return payload


def create_loan_payment_payload(loan_id, payment_date="2026-06-30",
                                principal_cents=400_000_000,
                                interest_cents=200_000_000, **overrides) -> dict:
    payload = {
        "loan_id": loan_id,
        "payment_date": payment_date,
        "principal_cents": principal_cents,
        "interest_cents": interest_cents,
    }
    payload.update(overrides)
    return payload


def create_allocation_run_payload(plan_id, valuation_id, expected_plan_version,
                                  contributed_shares=500, plan_year=2026,
                                  **overrides) -> dict:
    payload = {
        "plan_id": plan_id,
        "valuation_id": valuation_id,
        "plan_year": plan_year,
        "contributed_shares": contributed_shares,
        "expected_plan_version": expected_plan_version,
    }
    payload.update(overrides)
    return payload


def create_distribution_election_payload(participant_id, election_type="TERMINATION",
                                         requested_shares=1, **overrides) -> dict:
    payload = {
        "participant_id": participant_id,
        "election_type": election_type,
        "requested_shares": requested_shares,
    }
    payload.update(overrides)
    return payload


def create_put_option_exercise_payload(distribution_election_id, shares_tendered=1,
                                       **overrides) -> dict:
    payload = {
        "distribution_election_id": distribution_election_id,
        "shares_tendered": shares_tendered,
    }
    payload.update(overrides)
    return payload


def terminate_payload(termination_date="2026-01-15",
                      termination_reason="TERMINATION", **overrides) -> dict:
    payload = {
        "termination_date": termination_date,
        "termination_reason": termination_reason,
    }
    payload.update(overrides)
    return payload
