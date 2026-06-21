"""List-endpoint pagination envelope shape.

Translates the non-stub `endpoints` corner whose asserted rule (the empty-list
pagination envelope) is verbatim-stated and uniquely derivable from PRD prose.
"""
import pytest

from test_helpers import validate_paginated, create_winery, TEST_USERS

CLM = TEST_USERS["club_manager_headers"]


def test_list_shipments_empty_pagination_envelope(api):
    """PRD §2.3: "Every list response carries the pagination fields `limit`,
    `offset`, `total_count`, and `has_more` inside the `meta` object of the
    envelope."
    PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`,
    `total_count`, `has_more`) are included for list endpoints."

    GET /shipments against a fresh winery returns the paginated envelope with
    total_count 0 and has_more false.

    Design: Corner/endpoints/list_shipments_pagination_envelope
    """
    winery = create_winery(name="Ls Co", ttb_permit_number="LS-1")
    data, meta = validate_paginated(api.list_shipments(CLM, params={"winery_id": winery["id"]}))
    assert meta["total_count"] == 0, meta["total_count"]
    assert meta["has_more"] is False, meta["has_more"]
