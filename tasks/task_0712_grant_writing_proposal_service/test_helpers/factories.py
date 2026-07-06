"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Each factory accepts **overrides so tests control
the values they care about. A monotonically-increasing EIN counter keeps the
unique-EIN rule satisfied across factory calls within a single test.
"""
import itertools

_ein_counter = itertools.count(1)


def unique_ein() -> str:
    """A fresh EIN string, unique within a test run."""
    return f"99-{next(_ein_counter):07d}"


def create_client_payload(**overrides) -> dict:
    defaults = {
        "org_name": "Test Org",
        "ein": unique_ein(),
        "mission_areas": ["EDUCATION"],
        "annual_budget_cents": 5_000_000,
        "contact_email": "test@x.org",
    }
    defaults.update(overrides)
    return defaults


def create_opportunity_payload(**overrides) -> dict:
    defaults = {
        "funder_name": "Test Funder",
        "title": "Test Opportunity",
        "focus_areas": ["EDUCATION"],
        "ceiling_amount_cents": 9_000_000,
        "floor_amount_cents": 0,
        "portal_name": "GRANTS_GOV",
        "deadline_utc": "2026-12-31T00:00:00Z",
        "min_org_budget_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_engagement_payload(**overrides) -> dict:
    defaults = {
        "client_id": None,
        "fee_model": "HOURLY",
        "hourly_rate_cents": 12_000,
    }
    defaults.update(overrides)
    return defaults


def create_match_payload(**overrides) -> dict:
    defaults = {"client_id": None, "opportunity_id": None}
    defaults.update(overrides)
    return defaults


def create_proposal_payload(**overrides) -> dict:
    defaults = {
        "engagement_id": None,
        "match_id": None,
        "requested_amount_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults


def create_budget_line_payload(**overrides) -> dict:
    defaults = {
        "proposal_id": None,
        "category": "PERSONNEL",
        "label": "Staff",
        "amount_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults


def create_deliverable_payload(**overrides) -> dict:
    defaults = {
        "proposal_id": None,
        "kind": "NARRATIVE",
        "title": "Test Narrative",
        "body": "draft text",
    }
    defaults.update(overrides)
    return defaults


def create_revision_request_payload(**overrides) -> dict:
    defaults = {"deliverable_id": None, "note": "Please revise"}
    defaults.update(overrides)
    return defaults


def create_submission_payload(**overrides) -> dict:
    defaults = {"proposal_id": None, "expected_proposal_version": None}
    defaults.update(overrides)
    return defaults


def create_time_entry_payload(**overrides) -> dict:
    defaults = {"engagement_id": None, "minutes": 60, "period_yyyymm": "202603"}
    defaults.update(overrides)
    return defaults


def create_invoice_payload(**overrides) -> dict:
    defaults = {"engagement_id": None}
    defaults.update(overrides)
    return defaults


def create_award_payload(**overrides) -> dict:
    defaults = {
        "submission_id": None,
        "expected_submission_version": None,
        "awarded_amount_cents": 1_000_000,
        "period_of_performance_months": 12,
        "report_cadence_months": 3,
    }
    defaults.update(overrides)
    return defaults


def create_compliance_report_payload(**overrides) -> dict:
    defaults = {
        "award_id": None,
        "covers_window_start_utc": None,
        "due_utc": None,
        "sequence_index": 99,
    }
    defaults.update(overrides)
    return defaults


def create_boilerplate_payload(**overrides) -> dict:
    defaults = {"client_id": None, "section_key": "ORG_HISTORY", "body": "Reusable text."}
    defaults.update(overrides)
    return defaults
