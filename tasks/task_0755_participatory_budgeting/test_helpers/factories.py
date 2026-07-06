"""Payload factories — one per entity, input fields only."""

# Default half-open windows used across the suite (PRD §2.8): submission
# [2026-03-01, 2026-04-01), voting [2026-04-01, 2026-05-01); adjacency allowed.
DEFAULT_WINDOWS = {
    "submission_start": "2026-03-01T00:00:00Z",
    "submission_end": "2026-04-01T00:00:00Z",
    "voting_start": "2026-04-01T00:00:00Z",
    "voting_end": "2026-05-01T00:00:00Z",
}


def create_budget_cycle_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Cycle",
        "fiscal_year": 2027,
        "total_budget_cents": 100_000,
        "voting_method": "ALLOCATION",
        "per_project_cap_cents": 100_000,
        "per_voter_allocation_cap_cents": 100_000,
        **DEFAULT_WINDOWS,
    }
    defaults.update(overrides)
    return defaults


def create_category_payload(**overrides) -> dict:
    defaults = {
        "name": "General",
        "category_budget_cap_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults


def create_resident_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Resident",
        "date_of_birth": "1990-01-01",
        "residency_document_ref": "doc-ref-1",
        "residency_address": "1 Main St",
    }
    defaults.update(overrides)
    return defaults


def create_proposal_payload(category_id, **overrides) -> dict:
    defaults = {
        "category_id": category_id,
        "title": "Test Proposal",
        "summary": "A test proposal summary.",
    }
    defaults.update(overrides)
    return defaults


def create_cost_line_item_payload(**overrides) -> dict:
    defaults = {
        "label": "Line item",
        "unit_cost_cents": 30_000,
        "quantity": 1,
        "contingency_pct": 0.10,
    }
    defaults.update(overrides)
    return defaults


def create_ballot_entry_payload(proposal_id, **overrides) -> dict:
    defaults = {"proposal_id": proposal_id}
    defaults.update(overrides)
    return defaults


def create_milestone_payload(**overrides) -> dict:
    defaults = {
        "title": "Milestone",
        "scheduled_start": "2026-05-01T00:00:00Z",
        "scheduled_end": "2026-05-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_report_back_payload(**overrides) -> dict:
    defaults = {
        "period_label": "Q1",
        "narrative": "Progress narrative.",
        "spent_cents": 1000,
    }
    defaults.update(overrides)
    return defaults
