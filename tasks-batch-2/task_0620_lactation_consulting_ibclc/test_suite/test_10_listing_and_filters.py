"""Filtered listing with pagination metadata and foreign-key reverse reachability
(endpoints section breadth from queue B).
"""
from test_helpers import (
    validate_paginated, get_success_data,
    setup_practice_with_consultant_and_client, create_consult,
    create_completed_consult,
    create_feeding_assessment_payload,
    create_consultant, make_consultant_headers,
    TEST_USERS,
)

FRONT_DESK = TEST_USERS["front_desk_headers"]


# ─── endpoints / list_consults_filtered_by_client_pagination ────────────────

def test_list_consults_filtered_by_client_with_pagination(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to
    return".
    PRD §2.3: "List-based responses include the following fields in the `meta` object
    of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    A client with two consults, queried with limit=1, returns a one-element array,
    total_count 2, has_more true.

    Design: Corner/endpoints/list_consults_filtered_by_client_pagination
    """
    ctx = setup_practice_with_consultant_and_client()
    prac, cons1, client = ctx["practice"], ctx["consultant"], ctx["client"]
    cons2 = create_consultant(prac["id"], full_name="Bea IBCLC")
    create_consult(prac["id"], client["id"], cons1["id"],
                   "2026-06-10T15:00:00Z", "2026-06-10T16:00:00Z")
    create_consult(prac["id"], client["id"], cons2["id"],
                   "2026-06-11T15:00:00Z", "2026-06-11T16:00:00Z")

    resp = api.list_consults(FRONT_DESK, params={
        "client_id": client["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1, f"expected 1 item, got {len(data)}"
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, "has_more must be true when more remain"


# ─── endpoints / fk_reverse_reachability_feeding_assessment_by_consult ──────

def test_feeding_assessment_reachable_by_consult_filter(api):
    """PRD §2.6: "The topology is flat: peer resources live at top-level collection
    paths, and a child is discovered through a filtered list query rather than a
    deeply nested URL."
    PRD §4 endpoint table: GET `/feeding-assessments` lists feeding assessments
    (filterable by consult).

    A feeding assessment created for a consult is discoverable via
    GET /feeding-assessments?consult_id= as a single-element array.

    Design: Corner/endpoints/fk_reverse_reachability_feeding_assessment_by_consult
    """
    ctx = setup_practice_with_consultant_and_client()
    prac, cons, client = ctx["practice"], ctx["consultant"], ctx["client"]
    consult = create_consult(prac["id"], client["id"], cons["id"],
                             "2026-06-10T15:00:00Z", "2026-06-10T16:00:00Z")
    get_success_data(api.create_feeding_assessment(
        create_feeding_assessment_payload(consult["id"]), make_consultant_headers(cons["id"])))

    resp = api.list_feeding_assessments(
        make_consultant_headers(cons["id"]), params={"consult_id": consult["id"]})
    data, _meta = validate_paginated(resp)
    assert len(data) == 1, f"expected 1 assessment, got {len(data)}"
    assert data[0]["consult_id"] == consult["id"], "filtered assessment must match consult"
