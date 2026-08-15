"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from .constants import TEST_DEFAULTS

VERIFIED_MATRICULA_DOCS = [
    {"doc_type": "MATRICULA_CONSULAR", "status": "VERIFIED"},
    {"doc_type": "PROOF_OF_ADDRESS", "status": "VERIFIED"},
]

ALL_FOUR_RATINGS = [
    {"criterion": "FEE_COMPLIANCE", "rating": 4},
    {"criterion": "ACCESS", "rating": 4},
    {"criterion": "ALT_ID", "rating": 4},
    {"criterion": "CHEX_POLICY", "rating": 4},
    {"criterion": "EDUCATION_SUPPORT", "rating": 4},
]


def create_account_standard_payload(**overrides) -> dict:
    defaults = {
        "code": TEST_DEFAULTS["STANDARD_CODE"],
        "name": TEST_DEFAULTS["STANDARD_NAME"],
        "effective_from": "2026-01-01",
        "monthly_fee_cap_cents": 500,
        "overdraft_fee_allowed": False,
        "min_opening_deposit_cap_cents": 2500,
        "accepted_alt_id_types": ["MATRICULA_CONSULAR"],
        "chex_second_look_required": True,
        "requires_financial_education": False,
        "rubric_mode": "STANDARD_RUBRIC",
    }
    defaults.update(overrides)
    return defaults


def create_partner_institution_payload(**overrides) -> dict:
    defaults = {
        "legal_name": TEST_DEFAULTS["LEGAL_NAME"],
        "charter_type": "CREDIT_UNION",
    }
    defaults.update(overrides)
    return defaults


def create_certification_review_payload(institution_id, standard_id,
                                        expected_institution_version, **overrides) -> dict:
    defaults = {
        "institution_id": institution_id,
        "standard_id": standard_id,
        "period_start": TEST_DEFAULTS["REVIEW_PERIOD_START"],
        "period_end": TEST_DEFAULTS["REVIEW_PERIOD_END"],
        "expected_institution_version": expected_institution_version,
    }
    defaults.update(overrides)
    return defaults


def make_criteria_ratings(fee=4, access=4, alt_id=4, chex=4, edu=4) -> list:
    """One rating per criterion, each 0..4 (PRD §3.1)."""
    return [
        {"criterion": "FEE_COMPLIANCE", "rating": fee},
        {"criterion": "ACCESS", "rating": access},
        {"criterion": "ALT_ID", "rating": alt_id},
        {"criterion": "CHEX_POLICY", "rating": chex},
        {"criterion": "EDUCATION_SUPPORT", "rating": edu},
    ]


def score_payload(ratings=None) -> dict:
    return {"criteria_ratings": ratings if ratings is not None else make_criteria_ratings()}


def create_participant_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Ana Ruiz",
        "date_of_birth": "1990-04-12",
        "contact_zip": "90001",
        "prior_banking_record": "CLEAN",
    }
    defaults.update(overrides)
    return defaults


def documents_payload(id_documents) -> dict:
    return {"id_documents": id_documents}


def create_referral_payload(participant_id, **overrides) -> dict:
    defaults = {
        "participant_id": participant_id,
        "created_via": "NAVIGATOR",
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(institution_id, **overrides) -> dict:
    defaults = {
        "institution_id": institution_id,
        "venue_code": "BR-1",
        "starts_at": "2026-05-10T09:00:00Z",
        "ends_at": "2026-05-10T13:00:00Z",
        "capacity": 2,
        "alt_id_accepted": True,
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(participant_id, institution_id, **overrides) -> dict:
    defaults = {
        "participant_id": participant_id,
        "institution_id": institution_id,
        "id_type_presented": "MATRICULA_CONSULAR",
    }
    defaults.update(overrides)
    return defaults


def decision_payload(outcome, **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def propose_payload(proposed_settlement_cents, **overrides) -> dict:
    defaults = {"proposed_settlement_cents": proposed_settlement_cents}
    defaults.update(overrides)
    return defaults


def create_education_pairing_payload(participant_id, coach_id, **overrides) -> dict:
    defaults = {
        "participant_id": participant_id,
        "coach_id": coach_id,
        "course_code": "FOUNDATIONS",
    }
    defaults.update(overrides)
    return defaults


def create_funding_grant_payload(**overrides) -> dict:
    defaults = {
        "funder_name": "City Foundation",
        "program_year": 2026,
        "total_cents": TEST_DEFAULTS["GRANT_TOTAL_CENTS"],
        "per_report_cap_cents": TEST_DEFAULTS["GRANT_CAP_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_partner_report_payload(institution_id, grant_id, expected_grant_version,
                                  **overrides) -> dict:
    defaults = {
        "institution_id": institution_id,
        "grant_id": grant_id,
        "period_start": TEST_DEFAULTS["REPORT_PERIOD_START"],
        "period_end": TEST_DEFAULTS["REPORT_PERIOD_END"],
        "evaluation_mode": "FINAL",
        "expected_grant_version": expected_grant_version,
    }
    defaults.update(overrides)
    return defaults


def create_campaign_payload(**overrides) -> dict:
    defaults = {
        "name": "Spring Push",
        "zip_cluster": "90001",
        "window_start": "2026-06-01",
        "window_end": "2026-08-01",
        "budget_cents": 50000,
        "per_conversion_cents": 1000,
    }
    defaults.update(overrides)
    return defaults
