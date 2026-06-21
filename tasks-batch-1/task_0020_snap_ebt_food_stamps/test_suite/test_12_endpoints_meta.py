"""List-endpoint envelope and filter semantics."""
from test_helpers import (
    validate_paginated, TEST_USERS,
    set_clock, create_household,
)

CW = TEST_USERS["caseworker_headers"]


# ─── Corner / endpoints / list_households_with_pagination_meta ──

def test_list_households_filters_by_state_code_with_pagination_meta(api):
    """GET /snap/households filtered by state_code returns only matching
    rows; the response envelope carries the four pagination meta fields
    PRD §2.3 mandates: limit, offset, total_count, has_more.

    PRD §2.3: "List endpoints accept two query parameters, `limit` and
    `offset`. The `limit` parameter defaults to 10, takes a minimum of
    1, and is capped at a maximum of 100. The `offset` parameter
    defaults to 0. Result rows are returned in ascending `created_at`
    order (oldest first). On every list response, the `meta` envelope
    carries the echoed `limit` and `offset`, a `total_count` of all
    matching rows ignoring pagination, and a `has_more` boolean that
    is true when more rows exist beyond the current page."
    PRD §4: "GET | `/snap/households` | List households; supports
    filtering by `case_number`, `status`, `state_code`. | `Caseworker`,
    `FraudInvestigator`, `BenefitIssuer`"

    Design: Corner/endpoints/list_households_with_pagination_meta
    """
    set_clock("2026-09-01T00:00:00Z")
    create_household(case_number="CA-120001", state_code="CA",
                     address_line="1")
    create_household(case_number="CA-120002", state_code="CA",
                     address_line="2")
    create_household(case_number="CA-120003", state_code="TX",
                     address_line="3")
    resp = api.list_households(CW, params={"state_code": "CA",
                                           "limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 2, (
        f"only CA-state households must be returned, got {len(data)}"
    )
    # PRD §2.3 mandates the four pagination fields on every list response.
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert isinstance(meta["total_count"], int) and meta["total_count"] == 2
    assert isinstance(meta["has_more"], bool) and meta["has_more"] is False
