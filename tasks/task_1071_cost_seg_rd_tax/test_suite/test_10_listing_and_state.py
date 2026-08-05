"""Listing/pagination envelope and terminal-state lockdown.

Translates queue B (Corner/endpoints listing, Corner/state_machines terminal lockdown) instances.
"""
from test_helpers import validate_paginated, validate_error, get_success_data, ApiErrorId, TEST_USERS, fixtures

SM = TEST_USERS["study_manager_headers"]


# ---------------------------------------------------------------------------
# Corner/endpoints/list_studies_pagination_envelope
# ---------------------------------------------------------------------------
def test_list_studies_pagination_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more`
    inside the `meta` object of the envelope."

    Two studies for one client, limit 1 → total_count 2, has_more true, one item returned.

    Design: Corner/endpoints/list_studies_pagination_envelope
    """
    cli = fixtures.create_client(api)
    fixtures.create_study(api, cli["id"], "RD_CREDIT", tax_year=2023)
    fixtures.create_study(api, cli["id"], "RD_CREDIT", tax_year=2027)
    resp = api.list_studies(SM, params={"client_id": cli["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ---------------------------------------------------------------------------
# Corner/state_machines/cancel_already_cancelled_study_returns_invalid_state
# ---------------------------------------------------------------------------
def test_cancel_already_cancelled_study_rejected(api):
    """PRD §3.2: "From DRAFT, SCOPING, ENGINEERING, or IN_REVIEW, a StudyManager may cancel a
    study, moving it to the terminal CANCELLED state."
    PRD §2.1: "then whether the target resource is in a state from which the requested
    transition is legal (ERR_INVALID_STATE)."

    A study already in terminal CANCELLED cannot be cancelled again.

    Design: Corner/state_machines/cancel_already_cancelled_study_returns_invalid_state
    """
    cli = fixtures.create_client(api)
    st = fixtures.create_study(api, cli["id"], "RD_CREDIT", tax_year=2024)
    get_success_data(api.cancel_study(st["id"], SM))
    resp = api.cancel_study(st["id"], SM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
