"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "CONSTRUCTION_BUDGET": 200000000,
    "PERCENT_RATE": 0.01,
    "DEADLINE": "2026-06-01T00:00:00Z",
}


def make_project_payload(**overrides) -> dict:
    payload = {
        "name": "Test Project",
        "construction_budget_cents": DEFAULTS["CONSTRUCTION_BUDGET"],
        "percent_rate": DEFAULTS["PERCENT_RATE"],
    }
    payload.update(overrides)
    return payload


def make_certify_payload(certified_construction_budget_cents: int) -> dict:
    return {"certified_construction_budget_cents": certified_construction_budget_cents}


def make_commission_payload(allocation_cents, expected_project_version, **overrides) -> dict:
    payload = {
        "title": "Test Commission",
        "allocation_cents": allocation_cents,
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return payload


def make_call_payload(**overrides) -> dict:
    payload = {
        "call_type": "RFP",
        "submission_deadline": DEFAULTS["DEADLINE"],
        "quorum_min": 1,
    }
    payload.update(overrides)
    return payload


def make_panelist_payload(**overrides) -> dict:
    payload = {"evaluator_name": "Panelist"}
    payload.update(overrides)
    return payload


def make_artist_payload(**overrides) -> dict:
    payload = {"display_name": "Test Artist", "email": "artist@example.com"}
    payload.update(overrides)
    return payload


def make_submission_payload(artist_id, **overrides) -> dict:
    payload = {"artist_id": artist_id, "proposed_budget_cents": 800000}
    payload.update(overrides)
    return payload


def make_score_payload(panelist_id, artistic_merit, feasibility, community_impact, durability) -> dict:
    return {
        "panelist_id": panelist_id,
        "artistic_merit": artistic_merit,
        "feasibility": feasibility,
        "community_impact": community_impact,
        "durability": durability,
    }


def make_contract_payload(submission_id, contract_amount_cents) -> dict:
    return {"submission_id": submission_id, "contract_amount_cents": contract_amount_cents}


def make_milestone_schedule_payload(milestones, expected_contract_version) -> dict:
    return {"milestones": milestones, "expected_contract_version": expected_contract_version}


def make_site_payload(**overrides) -> dict:
    payload = {"name": "Test Site", "address": "1 Civic Plaza"}
    payload.update(overrides)
    return payload


def make_artwork_payload(**overrides) -> dict:
    payload = {"title": "Test Artwork", "acquisition_type": "DONATION"}
    payload.update(overrides)
    return payload


def make_install_payload(site_id, install_date) -> dict:
    return {"site_id": site_id, "install_date": install_date}


def make_deaccession_payload(deaccession_method, **overrides) -> dict:
    payload = {"deaccession_method": deaccession_method}
    payload.update(overrides)
    return payload


def make_conservation_payload(record_type, condition_after, **overrides) -> dict:
    payload = {"record_type": record_type, "condition_after": condition_after}
    payload.update(overrides)
    return payload


def make_loan_payload(borrower_name, loan_start, loan_end) -> dict:
    return {"borrower_name": borrower_name, "loan_start": loan_start, "loan_end": loan_end}
