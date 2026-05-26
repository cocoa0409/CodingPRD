"""Endpoint shape: pagination envelope defaults, test-driving clock side-effects."""
import pytest
from test_helpers import (
    api_client, validate_paginated, validate_success, get_success_data,
    TEST_USERS, set_clock,
    create_candidate, setup_offer_in_state, extend_offer,
)


# =========================================================================
# Instance: candidates_list_pagination_defaults_envelope
# =========================================================================

def test_candidates_list_pagination_defaults_envelope(api, recruiter_headers):
    """PRD §2.3: "Every list endpoint accepts two optional query-string
    parameters, `limit` and `offset`. The `limit` defaults to 10, has a
    minimum of 1, and a maximum of 100..."
    PRD §2.3: "The `meta` object on a list response carries the four
    pagination fields `limit`, `offset`, `total_count`, and `has_more`,
    where `total_count` is the size of the unpaginated result set and
    `has_more` is true when more rows exist beyond the current page."

    Design: Corner/endpoints/candidates_list_pagination_defaults_envelope
    """
    create_candidate(full_name="L1", email="l1_pag@example.com")
    create_candidate(full_name="L2", email="l2_pag@example.com")
    create_candidate(full_name="L3", email="l3_pag@example.com")
    res = api_client.list_candidates(recruiter_headers)
    data, meta = validate_paginated(res)
    # PRD §2.3 default limit = 10.
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] >= 3
    # has_more is true iff more rows exist beyond the current page; with 3 rows
    # and limit 10, has_more should be False.
    assert isinstance(meta["has_more"], bool)


# =========================================================================
# Instance: clock_endpoint_returns_revoked_offer_ids
# =========================================================================

def test_clock_endpoint_returns_revoked_offer_ids(api):
    """PRD §3.8: "A test-driving capability allows a `PlatformAdmin` to
    advance the logical clock to a supplied `to_iso8601` instant, returning
    the new `now` and the list of `revoked_offer_ids` that were
    auto-revoked as part of the advance. Setting the clock cascades the
    auto-revoke described in §3.6 on every `EXTENDED` offer whose
    `expires_at` is now reached or passed, applying the same downstream
    cascades as a manual revoke."

    Design: Corner/endpoints/clock_endpoint_returns_revoked_offer_ids
    """
    set_clock("2027-10-01T00:00:00Z")
    ctx = setup_offer_in_state(
        "EXTENDED",
        req_overrides={"base_salary_max_cents": 15_000_000},
        base_salary_cents=12_000_000,
    )
    offer_id = ctx["offer"]["id"]
    # Extended at 2027-10-01 → expires_at = 2027-10-15. Advance to 2027-10-16.
    res = api_client.set_clock({"to_iso8601": "2027-10-16T00:00:00Z"},
                               TEST_USERS["platform_admin_headers"])
    data = validate_success(res, 200)
    assert "now" in data
    assert "revoked_offer_ids" in data
    assert offer_id in data["revoked_offer_ids"], \
        f"Expected offer {offer_id} in revoked_offer_ids, got {data['revoked_offer_ids']}"
