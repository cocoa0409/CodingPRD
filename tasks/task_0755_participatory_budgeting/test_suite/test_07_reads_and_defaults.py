"""Reads, filtered listing, pagination envelope, required-field and default behavior."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    create_budget_cycle_payload, DEFAULT_WINDOWS,
    new_cycle, new_category, new_resident, transition, new_proposal,
    TEST_USERS,
)

ADMIN = TEST_USERS["budget_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ---------------------------------------------------------------------------
# Corner: entities / corner_create_cycle_missing_required_total_budget
# ---------------------------------------------------------------------------

def test_create_cycle_missing_total_budget_rejected(api):
    """PRD §3.2: "its money and rules: `total_budget_cents` (the total disbursable budget,
    which must be greater than zero)"
    PRD §2.9: "request-shape validation — required fields present ... (`ERR_VALIDATION`)"

    Design: Corner/entities/corner_create_cycle_missing_required_total_budget
    """
    payload = {
        "name": "NoBudget",
        "fiscal_year": 2027,
        "voting_method": "ALLOCATION",
        "per_project_cap_cents": 100000,
        "per_voter_allocation_cap_cents": 100000,
        **DEFAULT_WINDOWS,
    }
    resp = api.create_budget_cycle(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ---------------------------------------------------------------------------
# Corner: entities / corner_get_proposal_not_found
# ---------------------------------------------------------------------------

def test_get_nonexistent_proposal_not_found(api):
    """PRD §2.9: "the system validates the path identifiers left-to-right and rejects at the
    first one that does not resolve to an existing resource, returning the not-found error
    specific to that resource type. ... `ERR_PROPOSAL_NOT_FOUND` ... each HTTP 404."

    Design: Corner/entities/corner_get_proposal_not_found
    """
    resp = api.get_proposal("11111111-1111-4111-8111-111111111111", ANON)
    validate_error(resp, ApiErrorId.ERR_PROPOSAL_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Corner: entities / corner_cycle_defaults_min_age_and_language
# ---------------------------------------------------------------------------

def test_cycle_applies_default_min_age_and_language(api):
    """PRD §3.2: "`min_voter_age`, the minimum resident age in full years required to vote in
    this cycle, which must be zero or greater and defaults to 16 when omitted; and
    `default_language`, which defaults to `en`."

    Design: Corner/entities/corner_cycle_defaults_min_age_and_language
    """
    # Factory omits min_voter_age and default_language, so defaults apply.
    cyc = validate_success(api.create_budget_cycle(create_budget_cycle_payload(name="Def"), ADMIN), expected_status=201)
    assert cyc["min_voter_age"] == 16
    assert cyc["default_language"] == "en"


# ---------------------------------------------------------------------------
# Corner: endpoints / corner_proposals_filtered_list_by_category
# ---------------------------------------------------------------------------

def test_proposals_filtered_list_by_category(api):
    """PRD §3.3: "the proposal list additionally accepts `budget_cycle_id`, `category_id`, and
    `submitter_id` filters"
    PRD §2.3: "Every list-based response reports its pagination state in the `meta` object of
    the envelope through the fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/corner_proposals_filtered_list_by_category
    """
    cyc = new_cycle(api, name="PBfl")
    cat = new_category(api, cyc["id"])
    res = new_resident(api)
    transition(api, cyc["id"], "SUBMISSION")
    prop = new_proposal(api, cyc["id"], cat["id"], res["id"])
    data, meta = validate_paginated(api.list_proposals(ANON, params={"category_id": cat["id"]}))
    assert meta["total_count"] == 1, meta
    assert data[0]["id"] == prop["id"]


# ---------------------------------------------------------------------------
# Corner: endpoints / corner_proposals_subresource_pagination_envelope
# ---------------------------------------------------------------------------

def test_cycle_proposals_subresource_pagination_envelope(api):
    """PRD §2.3: "Every list-based response reports its pagination state in the `meta` object
    of the envelope through the fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/corner_proposals_subresource_pagination_envelope
    """
    cyc = new_cycle(api, name="PBpg")
    cat = new_category(api, cyc["id"])
    res = new_resident(api)
    transition(api, cyc["id"], "SUBMISSION")
    new_proposal(api, cyc["id"], cat["id"], res["id"])
    data, meta = validate_paginated(api.list_cycle_proposals(cyc["id"], ANON, params={"limit": 10, "offset": 0}))
    assert meta["total_count"] == 1, meta
    assert meta["has_more"] is False
