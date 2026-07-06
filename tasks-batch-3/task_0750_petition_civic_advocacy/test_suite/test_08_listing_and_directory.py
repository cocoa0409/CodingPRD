"""Pagination envelope on listing endpoints and representative directory lookup.

Queue-B breadth: list_petitions_pagination_envelope, representative_lookup_by_jurisdiction.
"""
import pytest
from test_helpers import (
    validate_paginated, get_success_data,
    register_member, create_draft_petition,
    create_representative_payload,
    TEST_USERS,
)

GUEST = TEST_USERS["guest_headers"]
ADMIN = TEST_USERS["admin_headers"]


def test_list_petitions_reports_pagination_meta(api):
    """PRD §2.3: "Every list response reports limit, offset, total_count, and has_more in
    the meta object, where total_count is the count of all matching items before the
    limit/offset window is applied and has_more is true when items remain beyond the
    returned page."

    Design: Corner/endpoints/list_petitions_pagination_envelope
    """
    author = register_member()
    create_draft_petition(author["id"], goal=10)
    create_draft_petition(author["id"], goal=10)
    resp = api.list_petitions(GUEST, params={"author_user_id": author["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_representative_lookup_by_jurisdiction(api):
    """PRD §3.2: "Anyone may look up representatives, filtering by jurisdiction or office,
    which is how a campaigner finds the right person to petition."

    Design: Corner/endpoints/representative_lookup_by_jurisdiction
    """
    rep = get_success_data(api.create_representative(
        create_representative_payload(full_name="Jane Rep", office="Assembly",
                                      jurisdiction="US-CA-12", contact_email="jane@gov.example"),
        ADMIN))
    resp = api.list_representatives(GUEST, params={"jurisdiction": "US-CA-12"})
    data, meta = validate_paginated(resp)
    ids = [r["id"] for r in data]
    assert rep["id"] in ids
    match = next(r for r in data if r["id"] == rep["id"])
    assert match["jurisdiction"] == "US-CA-12"
