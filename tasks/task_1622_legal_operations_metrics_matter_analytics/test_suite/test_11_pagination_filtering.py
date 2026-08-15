"""List endpoint pagination envelope and filter semantics (PRD §2.2, §2.3)."""

from test_helpers import (
    create_active_matter,
    create_matter,
    setup_matter_graph,
    validate_paginated,
    ANALYST,
)


def _create_matters(graph, count):
    for _ in range(count):
        create_matter(
            graph["practice_area"]["id"],
            graph["matter_type"]["id"],
            graph["fiscal_period"]["id"],
            graph["counsel"]["id"],
            primary_firm_id=graph["firm"]["id"],
        )


def test_list_matters_pagination_defaults(api):
    """PRD §2.3: "List endpoints accept two query parameters. `limit` sets the
    maximum number of items returned: when omitted it defaults to 10, and it may
    range from a minimum of 1 to a maximum of 100. `offset` sets how many items
    are skipped and defaults to 0."
    PRD §2.3: "Paginated list responses carry four pagination fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/endpoints/list_matters_pagination_defaults
    """
    graph = setup_matter_graph(activate=False, assignment_hours=None)
    _create_matters(graph, 14)  # plus the graph's own matter = 15 total

    res = api.list_matters(ANALYST)
    body = res.json()
    assert body["response_type"] == "array"
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert isinstance(body["meta"].get("api_request_timestamp"), str)

    data, meta = validate_paginated(res)
    assert len(data) == 10
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 15
    assert meta["has_more"] is True


def test_list_matters_pagination_offset_boundary(api):
    """PRD §2.3: "`offset` sets how many items are skipped and defaults to 0."
    PRD §2.3: "Paginated list responses carry four pagination fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/endpoints/list_matters_pagination_offset_boundary
    """
    graph = setup_matter_graph(activate=False, assignment_hours=None)
    _create_matters(graph, 2)  # 3 matters total

    data, meta = validate_paginated(
        api.list_matters(ANALYST, params={"limit": 1, "offset": 2})
    )
    assert len(data) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False  # offset 2 + limit 1 covers all 3 rows

    data, meta = validate_paginated(
        api.list_matters(ANALYST, params={"limit": 10, "offset": 3})
    )
    assert len(data) == 0
    assert meta["has_more"] is False


def test_list_matters_filter_by_status(api):
    """PRD §3.3: "Matters can be listed filtered by `status`, `practice_area_id`,
    `matter_type_id`, `fiscal_period_id`, `primary_firm_id`, or
    `lead_counsel_id`."

    Design: Corner/endpoints/list_matters_filter_by_status
    """
    graph = setup_matter_graph(activate=False, assignment_hours=None)
    intake_matter = graph["matter"]
    active_matter = create_active_matter(graph, allocated_hours=5)

    data, meta = validate_paginated(api.list_matters(ANALYST, params={"status": "ACTIVE"}))
    assert meta["total_count"] == 1
    assert len(data) == 1
    assert data[0]["id"] == active_matter["id"]
    assert data[0]["status"] == "ACTIVE"
    assert all(row["id"] != intake_matter["id"] for row in data)
