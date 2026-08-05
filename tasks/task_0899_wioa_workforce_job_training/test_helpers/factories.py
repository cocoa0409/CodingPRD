"""Payload factories — one per entity, input fields only (WIOA PRD)."""

DEFAULTS = {
    "AREA_NAME": "Area A",
    "PROGRAM_YEAR": 2026,
    "ITA_BUDGET_TOTAL": 5_000_000,
    "ITA_INDIVIDUAL_CAP": 800_000,
    "SUPPORTIVE_ANNUAL_CAP": 200_000,
    "PROVIDER_NAME": "Prov A",
    "PROGRAM_NAME": "Weld 101",
    "CIP_CODE": "48.0508",
    "PROGRAM_COST": 1_000_000,
    "EMPLOYER_NAME": "Acme",
}


def create_local_area_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["AREA_NAME"],
        "program_year": DEFAULTS["PROGRAM_YEAR"],
        "ita_budget_total_cents": DEFAULTS["ITA_BUDGET_TOTAL"],
        "ita_individual_cap_cents": DEFAULTS["ITA_INDIVIDUAL_CAP"],
        "supportive_annual_cap_cents": DEFAULTS["SUPPORTIVE_ANNUAL_CAP"],
    }
    payload.update(overrides)
    return payload


def create_participant_payload(**overrides) -> dict:
    payload = {
        "full_name": "P One",
        "funding_stream": "ADULT",
    }
    payload.update(overrides)
    return payload


def create_career_plan_payload(**overrides) -> dict:
    payload = {
        "goal_occupation": "Welder",
        "service_track": "TRAINING",
    }
    payload.update(overrides)
    return payload


def create_training_provider_payload(**overrides) -> dict:
    payload = {"name": DEFAULTS["PROVIDER_NAME"]}
    payload.update(overrides)
    return payload


def create_program_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["PROGRAM_NAME"],
        "cip_code": DEFAULTS["CIP_CODE"],
        "total_cost_cents": DEFAULTS["PROGRAM_COST"],
        "credential_type": "CERTIFICATE",
    }
    payload.update(overrides)
    return payload


def create_voucher_payload(program_id, career_plan_id, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "career_plan_id": career_plan_id,
        "authorized_cost_cents": 100_000,
        "planned_start_date": "2026-06-01T00:00:00Z",
        "planned_end_date": "2026-09-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_disbursement_payload(**overrides) -> dict:
    payload = {"amount_cents": 30_000}
    payload.update(overrides)
    return payload


def create_supportive_payload(**overrides) -> dict:
    payload = {
        "service_type": "CHILDCARE",
        "amount_cents": 50_000,
    }
    payload.update(overrides)
    return payload


def create_employer_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["EMPLOYER_NAME"],
        "size": "SMALL",
        "max_concurrent_ojt_slots": 5,
    }
    payload.update(overrides)
    return payload


def create_ojt_payload(participant_id, **overrides) -> dict:
    payload = {
        "participant_id": participant_id,
        "reimbursement_rate": 0.5,
        "wage_cents_per_hour": 2000,
        "planned_hours": 100,
        "obligated_amount_cents": 100_000,
        "start_date": "2026-06-01T00:00:00Z",
        "end_date": "2026-12-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_referral_payload(employer_id, **overrides) -> dict:
    payload = {
        "employer_id": employer_id,
        "job_title": "Welder I",
    }
    payload.update(overrides)
    return payload
