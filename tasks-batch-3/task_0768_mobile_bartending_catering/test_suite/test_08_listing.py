"""Filtered list endpoints and pagination metadata.

Design queue:
  B (Corner): endpoints/list_events_by_client_pagination,
              endpoints/assignments_reverse_lookup_by_bartender
"""
from test_helpers import (
    validate_paginated, get_success_data,
    create_draft_event, create_bartender, add_assignment,
    create_client_payload, create_package_payload, create_event_payload,
    TEST_USERS, make_client_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COORD = TEST_USERS["coordinator_headers"]


def test_list_events_by_client_reports_pagination_totals(api):
    """PRD §2.3: "total_count is the count of all rows matching the filter
    before pagination is applied and has_more is true when more rows exist
    beyond the current page."

    Design: Corner/endpoints/list_events_by_client_pagination
    """
    client = get_success_data(api.create_client(create_client_payload(), ADMIN))
    package = get_success_data(api.create_package(create_package_payload(), ADMIN))
    headers = make_client_headers(client["id"])
    for title, guests in (("A", 40), ("B", 60)):
        get_success_data(api.create_event(
            create_event_payload(client["id"], package["id"], title=title, guest_count=guests,
                                 event_start="2026-06-01T18:00:00Z",
                                 event_end="2026-06-01T22:00:00Z"), headers))
    data, meta = validate_paginated(api.list_events(headers, params={"client_id": client["id"]}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(data) == 2


def test_list_assignments_filtered_by_bartender(api):
    """PRD §4: "GET | `/assignments` | List assignments filtered by bartender or
    event | PlatformAdmin, Coordinator, Bartender".

    Design: Corner/endpoints/assignments_reverse_lookup_by_bartender
    """
    bundle = create_draft_event(api)
    bartender = create_bartender(api)
    asg = add_assignment(api, bundle["event"]["id"], bartender["id"], role_on_event="BACK")
    data, meta = validate_paginated(
        api.list_assignments(COORD, params={"bartender_id": bartender["id"]}))
    assert len(data) == 1
    assert data[0]["id"] == asg["id"]
