"""Payload factories — one per entity, input fields only."""

from .constants import TEST_DEFAULTS


def create_literary_property_payload(**overrides) -> dict:
    defaults = {
        "title": "Test Property",
        "material_type": "SPEC_SCRIPT",
        "source_author_name": "A. Author",
        "genre": "DRAMA",
        "logline": "A test logline.",
    }
    defaults.update(overrides)
    return defaults


def create_rights_document_payload(**overrides) -> dict:
    defaults = {
        "doc_type": "CHAIN_OF_TITLE",
        "executed_on": "2026-01-15",
        "verified": True,
    }
    defaults.update(overrides)
    return defaults


def create_submission_payload(property_id: str, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "submitting_agency": "CAA",
        "submitter_contact_email": "desk@caa.example",
        "submitted_via": "AGENCY",
    }
    defaults.update(overrides)
    return defaults


def create_release_form_payload(**overrides) -> dict:
    defaults = {"expires_at": "2026-10-01T00:00:00Z"}
    defaults.update(overrides)
    return defaults


def create_reader_payload(**overrides) -> dict:
    defaults = {
        "display_name": "R1 Solberg",
        "specialty_genre": "DRAMA",
        "weekly_capacity": 3,
        "employment_type": "STAFF",
    }
    defaults.update(overrides)
    return defaults


def assign_reader_payload(**overrides) -> dict:
    defaults = {
        "window_start": "2026-09-01T00:00:00Z",
        "window_due": "2026-09-04T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def coverage_report_body_payload(**overrides) -> dict:
    defaults = {
        "logline_score": 8,
        "structure_score": 7,
        "character_score": 9,
        "dialogue_score": 6,
        "marketability_score": 8,
        "recommendation": "RECOMMEND",
        "synopsis_word_count": 400,
    }
    defaults.update(overrides)
    return defaults


def create_option_agreement_payload(
    property_id: str, expected_property_version: int, **overrides
) -> dict:
    defaults = {
        "property_id": property_id,
        "expected_property_version": expected_property_version,
        "option_fee_cents": TEST_DEFAULTS["OPTION_FEE_CENTS"],
        "purchase_price_cents": TEST_DEFAULTS["PURCHASE_PRICE_CENTS"],
        "initial_period_months": TEST_DEFAULTS["INITIAL_PERIOD_MONTHS"],
        "option_start_at": TEST_DEFAULTS["OPTION_START_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_development_project_payload(
    property_id: str, option_agreement_id: str, **overrides
) -> dict:
    defaults = {
        "property_id": property_id,
        "option_agreement_id": option_agreement_id,
        "budget_cents": TEST_DEFAULTS["BUDGET_CENTS"],
        "slate_year": TEST_DEFAULTS["SLATE_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_writer_payload(**overrides) -> dict:
    defaults = {
        "name": "W1 Ferrante",
        "guild_member": True,
        "quote_cents": 10_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_writer_engagement_payload(
    project_id: str, writer_id: str, expected_project_version: int, **overrides
) -> dict:
    defaults = {
        "project_id": project_id,
        "writer_id": writer_id,
        "engagement_type": "ORIGINAL_DRAFT",
        "total_fee_cents": TEST_DEFAULTS["ORIGINAL_DRAFT_FEE_CENTS"],
        "start_date": TEST_DEFAULTS["ENGAGEMENT_START_DATE"],
        "end_date": TEST_DEFAULTS["ENGAGEMENT_END_DATE"],
        "expected_project_version": expected_project_version,
    }
    defaults.update(overrides)
    return defaults


def create_committee_member_payload(**overrides) -> dict:
    defaults = {"display_name": "M1 Chair", "vote_weight_bps": 3000, "veto_power": False}
    defaults.update(overrides)
    return defaults


def create_greenlight_review_payload(
    project_id: str, expected_project_version: int, **overrides
) -> dict:
    defaults = {
        "project_id": project_id,
        "session_date": "2026-10-01",
        "expected_project_version": expected_project_version,
    }
    defaults.update(overrides)
    return defaults


def cast_vote_payload(vote_value: str, **overrides) -> dict:
    defaults = {"vote_value": vote_value}
    defaults.update(overrides)
    return defaults
