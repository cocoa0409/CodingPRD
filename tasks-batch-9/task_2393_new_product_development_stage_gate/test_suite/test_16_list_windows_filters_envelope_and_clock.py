"""Cross-cutting API surface: paging windows, conjunctive filters, the shared response
envelope, the logical clock as the only source of now, and child-list parent scoping."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    intake_project,
    is_iso8601_timestamp,
    open_reset_window,
    record_concept_test,
    register_retailer,
    register_stage_gate,
    schedule_gate_review,
    screen_project,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

SNACK_LINE_EXTENSION = {
    "brand": "GrainWell",
    "category": "SNACK",
    "project_type": "LINE_EXTENSION",
    "strategic_fit_score": 8,
    "consumer_need_score": 7,
    "target_gross_margin_pct": 36,
    "category_attractiveness_score": 7,
    "development_budget_cap_usd": 300000.00,
}
PERMISSIVE_GATE_2 = {
    "gate_number": 2,
    "stage_from": "SCREENED",
    "stage_to": "PILOT_QUALIFIED",
    "quorum_size": 1,
    "veto_functions": [],
    "npv_hurdle_usd": 0.00,
    "payback_months_max": 24,
    "gross_margin_floor_pct": 0.00,
    "readiness_floor_index": 0.00,
}
# (0.60 * 40.00 + 0.40 * 30.00) * 0.95 = 34.20 at a sample size of 200.
MODEST_READ = {
    "sample_size": 200,
    "purchase_intent_top2_pct": 40.00,
    "uniqueness_pct": 30.00,
}
# Twelve field dates, created newest first, so creation order matches the pinned order.
TWELVE_FIELD_DATES = [
    ("MONADIC", "2026-07-24T00:00:00Z"),
    ("MONADIC", "2026-07-23T00:00:00Z"),
    ("MONADIC", "2026-07-22T00:00:00Z"),
    ("MONADIC", "2026-07-21T00:00:00Z"),
    ("SEQUENTIAL_MONADIC", "2026-07-20T00:00:00Z"),
    ("SEQUENTIAL_MONADIC", "2026-07-19T00:00:00Z"),
    ("SEQUENTIAL_MONADIC", "2026-07-18T00:00:00Z"),
    ("SEQUENTIAL_MONADIC", "2026-07-17T00:00:00Z"),
    ("IN_HOME_USE", "2026-07-16T00:00:00Z"),
    ("IN_HOME_USE", "2026-07-15T00:00:00Z"),
    ("IN_HOME_USE", "2026-07-14T00:00:00Z"),
    ("IN_HOME_USE", "2026-07-13T00:00:00Z"),
]


def _project_with_twelve_concept_tests():
    """One IDEA project carrying twelve studies in descending fielded_at order."""
    set_clock("2026-08-03T00:00:00Z")
    project = intake_project(
        owner_user_id="lead-pg", name="Paged Concepts", **SNACK_LINE_EXTENSION
    )
    rows = [
        record_concept_test(
            project["id"], test_type=test_type, fielded_at=fielded_at, **MODEST_READ
        )
        for test_type, fielded_at in TWELVE_FIELD_DATES
    ]
    return project, rows


def _filter_fixture_projects():
    """Four projects across three categories, one screened through and one killed on score."""
    set_clock("2026-08-03T00:00:00Z")
    snack_gate = register_stage_gate(
        category="SNACK", required_deliverable_types=["CONSUMER_CONCEPT_TEST"],
        **PERMISSIVE_GATE_2,
    )
    register_stage_gate(
        category="DAIRY", required_deliverable_types=[], **PERMISSIVE_GATE_2
    )
    retailer = register_retailer(
        name="Filter Grocery", channel="GROCERY", acv_contribution_pct=25.00,
        presentation_lead_days=14,
    )
    window = open_reset_window(
        retailer["id"], category="SNACK", window_start="2026-10-05T00:00:00Z",
        window_end="2026-11-30T00:00:00Z", max_presentations=2,
    )
    snack_one = intake_project(
        owner_user_id="lead-fl", name="Filter Snack One", **SNACK_LINE_EXTENSION
    )
    snack_two = intake_project(
        owner_user_id="lead-fl", name="Filter Snack Two",
        **dict(SNACK_LINE_EXTENSION, project_type="NEW_BRAND", strategic_fit_score=9,
               consumer_need_score=8, target_gross_margin_pct=40,
               category_attractiveness_score=8),
    )
    beverage = intake_project(
        owner_user_id="lead-fl", name="Filter Beverage",
        **dict(SNACK_LINE_EXTENSION, brand="SpringWell", category="BEVERAGE"),
    )
    dairy = intake_project(
        owner_user_id="lead-fl", name="Filter Dairy",
        **dict(SNACK_LINE_EXTENSION, brand="MeadowWell", category="DAIRY",
               project_type="RENOVATION", strategic_fit_score=2, consumer_need_score=2,
               target_gross_margin_pct=10, category_attractiveness_score=2),
    )
    screened = screen_project(
        snack_one["id"], chair_user_id="chair-fl", screening_notes="Into stage 2."
    )
    killed = screen_project(
        dairy["id"], chair_user_id="chair-fl", screening_notes="Below the floor."
    )
    return {
        "snack_gate": snack_gate,
        "window": window,
        "screened_snack": screened,
        "idea_snack": snack_two,
        "idea_beverage": beverage,
        "killed_dairy": killed,
    }


def _ids(rows):
    return [row["id"] for row in rows]


def test_concept_test_list_defaults_to_ten_rows_of_a_twelve_row_child_list(
    api, innovation_lead_headers
):
    """With no query parameters the child list returns 10 of 12 rows and says so.

    PRD: "Collection endpoints are paginated by two query parameters. `limit` caps the number
    of rows returned; it defaults to 10, may not be below 1 and may not exceed 100. `offset`
    is the number of rows to skip and defaults to 0."

    Design: Corner/cross-cutting complexity layers/xc_pagination_defaults_and_bounds_on_a_twelve_row_child_list
    """
    project, created = _project_with_twelve_concept_tests()

    rows, meta = validate_paginated(
        api.list_concept_tests(project["id"], innovation_lead_headers)
    )

    assert len(rows) == 10, "the default window is ten rows wide"
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 12, "total_count counts the population, not the page"
    assert meta["has_more"] is True, "two rows remain beyond the default page"
    for row in rows:
        assert row["concept_score"] == pytest.approx(34.20, abs=0.01), (
            "(0.60 * 40.00 + 0.40 * 30.00) * 0.95 = 34.20"
        )
    assert _ids(rows) == _ids(created[:10]), (
        "fielded_at descending happens to be the creation order here"
    )


def test_concept_test_list_walks_to_a_short_final_page_in_the_pinned_order(
    api, innovation_lead_headers
):
    """Offset 10 with limit 5 returns the two lowest field dates and stops.

    PRD: "Concept tests for a project are ordered by `fielded_at` descending, then
    `created_at` ascending."

    Design: Corner/cross-cutting complexity layers/xc_pagination_defaults_and_bounds_on_a_twelve_row_child_list
    """
    project, created = _project_with_twelve_concept_tests()

    tail, tail_meta = validate_paginated(
        api.list_concept_tests(
            project["id"], innovation_lead_headers, params={"limit": 5, "offset": 10}
        )
    )
    head, head_meta = validate_paginated(
        api.list_concept_tests(project["id"], innovation_lead_headers, params={"limit": 1})
    )

    assert len(tail) == 2, "only two rows survive an offset of 10 over 12 rows"
    assert _ids(tail) == _ids(created[10:]), "the last page holds the two oldest field dates"
    assert tail_meta["limit"] == 5
    assert tail_meta["offset"] == 10
    assert tail_meta["total_count"] == 12, "total_count is unaffected by the window requested"
    assert tail_meta["has_more"] is False
    assert len(head) == 1
    assert head[0]["id"] == created[0]["id"], "the newest field date leads the order"
    assert head[0]["fielded_at"].startswith("2026-07-24")
    assert head[0]["is_authoritative"] is True
    assert tail[-1]["is_authoritative"] is False, (
        "the row created last carries the lowest fielded_at and no authority"
    )


def test_concept_test_list_accepts_the_maximum_limit_of_one_hundred(
    api, innovation_lead_headers
):
    """A limit of 100 is admissible and returns the whole twelve-row set in one page.

    PRD: "Both `limit` and `offset` are echoed in the `meta` object alongside `total_count`
    (the number of rows matching the filters before pagination) and `has_more` (true when rows
    remain beyond the current page)."

    Design: Corner/cross-cutting complexity layers/xc_pagination_defaults_and_bounds_on_a_twelve_row_child_list
    """
    project, created = _project_with_twelve_concept_tests()

    rows, meta = validate_paginated(
        api.list_concept_tests(project["id"], innovation_lead_headers, params={"limit": 100})
    )

    assert len(rows) == 12
    assert meta["limit"] == 100, "the requested limit is echoed, not the row count"
    assert meta["total_count"] == 12
    assert meta["has_more"] is False, "nothing remains beyond a page that holds everything"
    assert _ids(rows) == _ids(created), "the pinned order holds across the full page"


def test_concept_test_list_past_the_end_is_an_empty_page_and_not_a_not_found(
    api, innovation_lead_headers
):
    """Offset 12 over 12 rows answers 200 with an empty array and the full total_count.

    PRD: "Both `limit` and `offset` are echoed in the `meta` object alongside `total_count`
    (the number of rows matching the filters before pagination) and `has_more` (true when rows
    remain beyond the current page)."

    Design: Corner/cross-cutting complexity layers/xc_pagination_defaults_and_bounds_on_a_twelve_row_child_list
    """
    project, _created = _project_with_twelve_concept_tests()

    response = api.list_concept_tests(
        project["id"], innovation_lead_headers, params={"limit": 10, "offset": 12}
    )
    rows, meta = validate_paginated(response)

    assert response.status_code == 200, "walking past the end is not a missing resource"
    assert rows == []
    assert meta["offset"] == 12
    assert meta["total_count"] == 12, "the population is unchanged by an empty window"
    assert meta["has_more"] is False


def test_project_filters_compose_as_conjunctions_and_never_widen_a_page(
    api, portfolio_admin_headers
):
    """Category and dev_status narrow to the intersection rather than the union.

    PRD: "List endpoints also accept optional equality filters drawn from the listed entity's
    own fields. Stage gates filter on `category` and `gate_number`; retailers and pilot lines
    on `channel` and `allergen_regime` respectively; reset windows on `category`; projects on
    `dev_status`, `commercial_status`, `category` and `shelf_reset_window_id`; business cases
    on `status` and `variant_mode`; checklist items on `project_id`, `gate_id`,
    `prerequisite_deliverable_id`, `status` and `owner_function`; gate reviews on
    `project_id`, `gate_id` and `status`; formulations and stability studies on `status`;
    pilot runs on `formulation_id`, `pilot_line_id` and `status`; label approvals on
    `project_id`, `formulation_id` and `status`; trade presentations on `project_id`,
    `retailer_id`, `shelf_reset_window_id` and `status`."

    Design: Corner/cross-cutting complexity layers/xc_filters_compose_as_conjunctions_and_never_widen_a_page
    """
    context = _filter_fixture_projects()

    snack_rows, snack_meta = validate_paginated(
        api.list_projects(portfolio_admin_headers, params={"category": "SNACK"})
    )
    idea_rows, idea_meta = validate_paginated(
        api.list_projects(portfolio_admin_headers, params={"dev_status": "IDEA"})
    )
    both_rows, both_meta = validate_paginated(
        api.list_projects(
            portfolio_admin_headers, params={"category": "SNACK", "dev_status": "IDEA"}
        )
    )
    empty_rows, empty_meta = validate_paginated(
        api.list_projects(
            portfolio_admin_headers, params={"category": "SNACK", "dev_status": "KILLED"}
        )
    )

    assert snack_meta["total_count"] == 2
    assert set(_ids(snack_rows)) == {
        context["screened_snack"]["id"], context["idea_snack"]["id"]
    }
    assert idea_meta["total_count"] == 2
    assert set(_ids(idea_rows)) == {
        context["idea_snack"]["id"], context["idea_beverage"]["id"]
    }
    assert both_meta["total_count"] == 1, "the two terms intersect rather than union"
    assert _ids(both_rows) == [context["idea_snack"]["id"]]
    assert both_meta["total_count"] < snack_meta["total_count"], (
        "adding a term can only narrow a page"
    )
    assert empty_meta["total_count"] == 0, "a legal but unsatisfiable conjunction is empty"
    assert empty_rows == []


def test_unmatched_filters_return_an_empty_page_rather_than_a_not_found(
    api, portfolio_admin_headers
):
    """A window nobody has locked filters to zero rows, and screening leaves the other track.

    PRD: "Both `limit` and `offset` are echoed in the `meta` object alongside `total_count`
    (the number of rows matching the filters before pagination) and `has_more` (true when rows
    remain beyond the current page)."

    Design: Corner/cross-cutting complexity layers/xc_filters_compose_as_conjunctions_and_never_widen_a_page
    """
    context = _filter_fixture_projects()

    window_response = api.list_projects(
        portfolio_admin_headers,
        params={"shelf_reset_window_id": context["window"]["id"]},
    )
    window_rows, window_meta = validate_paginated(window_response)
    killed_rows, killed_meta = validate_paginated(
        api.list_projects(portfolio_admin_headers, params={"dev_status": "KILLED"})
    )
    commercial_rows, commercial_meta = validate_paginated(
        api.list_projects(
            portfolio_admin_headers,
            params={"commercial_status": "NOT_STARTED", "limit": 100},
        )
    )

    assert window_response.status_code == 200, "an unmatched filter value is not a 404"
    assert window_rows == []
    assert window_meta["total_count"] == 0, "no project has locked that window yet"
    assert killed_meta["total_count"] == 1
    assert _ids(killed_rows) == [context["killed_dairy"]["id"]]
    assert context["killed_dairy"]["screening_score"] == pytest.approx(21.25, abs=0.01), (
        "0.20*20 + 0.35*20 + 0.25*25 + 0.20*20 = 21.25, well below the 60.00 floor"
    )
    assert commercial_meta["total_count"] == 4, (
        "screening moves only the development track, so all four remain NOT_STARTED"
    )
    assert len(commercial_rows) == 4


def test_checklist_filters_intersect_project_gate_and_status(api, portfolio_admin_headers):
    """The three checklist filter terms conjoin on one project's auto-created item.

    PRD: "List endpoints also accept optional equality filters drawn from the listed entity's
    own fields."

    Design: Corner/cross-cutting complexity layers/xc_filters_compose_as_conjunctions_and_never_widen_a_page
    """
    context = _filter_fixture_projects()
    screened_id = context["screened_snack"]["id"]

    pending_rows, pending_meta = validate_paginated(
        api.list_deliverables(
            portfolio_admin_headers,
            params={
                "project_id": screened_id,
                "gate_id": context["snack_gate"]["id"],
                "status": "PENDING",
            },
        )
    )
    approved_rows, approved_meta = validate_paginated(
        api.list_deliverables(
            portfolio_admin_headers,
            params={"project_id": screened_id, "status": "APPROVED"},
        )
    )
    killed_rows, killed_meta = validate_paginated(
        api.list_deliverables(
            portfolio_admin_headers, params={"project_id": context["killed_dairy"]["id"]}
        )
    )

    assert pending_meta["total_count"] == 1
    assert pending_rows[0]["deliverable_type"] == "CONSUMER_CONCEPT_TEST"
    assert pending_rows[0]["owner_function"] == "MARKETING"
    assert approved_meta["total_count"] == 0, (
        "the same project filtered on a status it holds no rows in is empty"
    )
    assert approved_rows == []
    assert killed_meta["total_count"] == 0, "a rejected screen creates no checklist at all"
    assert killed_rows == []


def test_envelope_and_meta_are_uniform_across_object_array_and_error(
    api, innovation_lead_headers
):
    """One create, one read, one list and one refusal all parse as the same shape.

    PRD: "The `response_type` is either "object" for a single resource or "array" for a list
    of resources."
    PRD: "The `api_request_id` is a server-generated unique identifier for the request that
    starts with `req_`."
    PRD: "Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`)
    are included for list endpoints."
    PRD: "The `meta` object for error responses contains only `api_request_id` and
    `api_request_timestamp`."

    Design: Corner/cross-cutting complexity layers/xc_envelope_and_meta_are_uniform_across_object_array_and_error
    """
    set_clock("2026-08-03T00:00:00Z")

    create_response = api.create_project(
        dict(SNACK_LINE_EXTENSION, name="Envelope Probe"), innovation_lead_headers
    )
    created = validate_success(create_response, 201)
    read_response = api.get_project(created["id"], innovation_lead_headers)
    read_back = validate_success(read_response)
    list_response = api.list_projects(innovation_lead_headers)
    listed, list_meta = validate_paginated(list_response)
    missing_response = api.get_project(NON_EXISTENT_UUID, innovation_lead_headers)
    error_data = validate_error(missing_response, "ERR_PROJECT_NOT_FOUND", 404)

    assert create_response.json()["response_type"] == "object"
    assert read_response.json()["response_type"] == "object"
    assert read_back["id"] == created["id"]
    assert list_response.json()["response_type"] == "array"
    assert isinstance(list_response.json()["data"], list)
    assert isinstance(listed, list) and len(listed) == 1
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in list_meta, f"a list envelope carries {key} in meta"
    assert missing_response.json()["response_type"] == "error"
    assert error_data["error_id"] == "ERR_PROJECT_NOT_FOUND"
    assert error_data["message"].strip() != ""
    for response in (create_response, read_response, list_response, missing_response):
        body = response.json()
        meta = body["meta"]
        assert meta["api_request_id"].startswith("req_"), (
            "every response, including the 404, carries a request identifier"
        )
        assert is_iso8601_timestamp(meta["api_request_timestamp"])
        assert "error_id" not in body, "error_id lives inside data, never at the top level"
    for body in (create_response.json(), read_response.json(), list_response.json()):
        assert "error_id" not in body["meta"]
    assert "error_id" not in create_response.json()["data"]
    assert "error_id" not in read_response.json()["data"]
    assert set(missing_response.json()["meta"]) == {
        "api_request_id", "api_request_timestamp"
    }, "an error envelope carries no pagination fields in meta"


def test_the_logical_clock_is_the_only_source_of_now(api, gate_chair_headers):
    """Stored stamps are frozen at write time while the derived lock date tracks the clock.

    PRD: "Time is not read from the host. The system holds a **logical clock**, referred to
    throughout as the current instant, which begins at `2026-08-01T00:00:00Z` on a freshly
    started system and changes only when a `PortfolioAdmin` calls the clock-setting capability
    with a `to_iso8601` value; the response reports the new `current_utc`."
    PRD: "A dedicated launch-readiness read exposes the live picture without storing anything
    new: the current `launch_readiness_pct`, a `blocking_deliverable_types` array listing the
    required readiness types not yet `APPROVED` in checklist order, the current
    `authorized_acv_pct`, the locked `launch_date` if any, and an `earliest_lockable_date`
    computed on every read as the current instant plus the 45-whole-day lock lead time.
    `earliest_lockable_date` is derived on demand and never persisted."
    PRD: "`created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional
    digits, and `version` is an integer that starts at 1 on insert and increments by one on
    every accepted write to that row."

    Design: Corner/cross-cutting complexity layers/xc_the_logical_clock_is_the_only_source_of_now
    """
    set_clock("2026-08-03T00:00:00Z")
    register_stage_gate(
        category="SNACK", required_deliverable_types=[], **PERMISSIVE_GATE_2
    )
    project = intake_project(
        owner_user_id="lead-ck", name="Clock Probe", **SNACK_LINE_EXTENSION
    )

    first_readiness = validate_success(
        api.get_launch_readiness(project["id"], gate_chair_headers)
    )
    set_clock("2026-09-01T12:00:00Z")
    unwritten = validate_success(api.get_project(project["id"], gate_chair_headers))
    second_readiness = validate_success(
        api.get_launch_readiness(project["id"], gate_chair_headers)
    )
    screened = screen_project(
        project["id"], chair_user_id="chair-ck", screening_notes="Screened a month later."
    )
    set_clock("2026-08-10T00:00:00Z")
    after_rewind = validate_success(api.get_project(project["id"], gate_chair_headers))

    assert first_readiness["earliest_lockable_date"].startswith("2026-09-17T00:00:00"), (
        "2026-08-03 plus the 45-whole-day lock lead time"
    )
    assert is_iso8601_timestamp(unwritten["created_at"])
    assert is_iso8601_timestamp(unwritten["updated_at"])
    assert unwritten["created_at"].startswith("2026-08-03T00:00:00")
    assert unwritten["updated_at"] == project["updated_at"], (
        "moving the clock is not a write to the project"
    )
    assert unwritten["version"] == 1
    assert second_readiness["earliest_lockable_date"].startswith("2026-10-16T12:00:00"), (
        "the field is re-derived from the clock on every read"
    )
    assert screened["dev_status"] == "SCREENED"
    assert screened["updated_at"].startswith("2026-09-01T12:00:00"), (
        "the write is stamped from the clock as it stood at write time"
    )
    assert screened["created_at"].startswith("2026-08-03T00:00:00")
    assert after_rewind["created_at"] == screened["created_at"]
    assert after_rewind["updated_at"] == screened["updated_at"], (
        "rewinding the clock recomputes no stored timestamp"
    )
    assert after_rewind["version"] == 2, "the version moved exactly once, at the screen"


def test_nested_child_lists_are_scoped_to_their_path_parent(api, functional_reviewer_headers):
    """Two neighbouring projects never bleed into each other's studies or reviews.

    PRD: "Concept tests for a project are ordered by `fielded_at` descending, then
    `created_at` ascending."

    Design: Corner/cross-cutting complexity layers/xc_child_lists_are_scoped_to_their_parent
    """
    set_clock("2026-08-03T00:00:00Z")
    gate2 = register_stage_gate(
        category="SNACK", required_deliverable_types=[], **PERMISSIVE_GATE_2
    )
    alpha = intake_project(
        owner_user_id="lead-sc2", name="Scope Alpha", **SNACK_LINE_EXTENSION
    )
    beta = intake_project(
        owner_user_id="lead-sc2", name="Scope Beta", **SNACK_LINE_EXTENSION
    )
    screen_project(alpha["id"], chair_user_id="chair-sc2", screening_notes="Into stage 2.")
    screen_project(beta["id"], chair_user_id="chair-sc2", screening_notes="Into stage 2.")
    alpha_old = record_concept_test(
        alpha["id"], test_type="MONADIC", fielded_at="2026-07-20T00:00:00Z", **MODEST_READ
    )
    alpha_new = record_concept_test(
        alpha["id"], test_type="MONADIC", sample_size=200,
        purchase_intent_top2_pct=44.00, uniqueness_pct=30.00,
        fielded_at="2026-07-27T00:00:00Z",
    )
    beta_only = record_concept_test(
        beta["id"], test_type="IN_HOME_USE", sample_size=400,
        purchase_intent_top2_pct=50.00, uniqueness_pct=40.00,
        fielded_at="2026-07-28T00:00:00Z",
    )
    alpha_review = schedule_gate_review(
        alpha["id"], gate2["id"], chair_user_id="chair-sc2",
        scheduled_at="2026-08-10T09:00:00Z",
    )

    alpha_rows, alpha_meta = validate_paginated(
        api.list_concept_tests(alpha["id"], functional_reviewer_headers)
    )
    beta_rows, beta_meta = validate_paginated(
        api.list_concept_tests(beta["id"], functional_reviewer_headers)
    )
    alpha_reviews, alpha_review_meta = validate_paginated(
        api.list_gate_reviews(functional_reviewer_headers, params={"project_id": alpha["id"]})
    )
    beta_reviews, beta_review_meta = validate_paginated(
        api.list_gate_reviews(functional_reviewer_headers, params={"project_id": beta["id"]})
    )
    _in_session, in_session_meta = validate_paginated(
        api.list_gate_reviews(
            functional_reviewer_headers,
            params={"project_id": alpha["id"], "status": "IN_SESSION"},
        )
    )

    assert alpha_meta["total_count"] == 2
    assert set(_ids(alpha_rows)) == {alpha_old["id"], alpha_new["id"]}
    assert beta_only["id"] not in _ids(alpha_rows), "the neighbour's study never appears"
    assert beta_meta["total_count"] == 1
    assert _ids(beta_rows) == [beta_only["id"]]
    assert beta_rows[0]["concept_score"] == pytest.approx(46.00, abs=0.01), (
        "(0.60 * 50.00 + 0.40 * 40.00) * 1.00 at a sample size of 400"
    )
    assert alpha_review_meta["total_count"] == 1
    assert _ids(alpha_reviews) == [alpha_review["id"]]
    assert alpha_reviews[0]["status"] == "SCHEDULED"
    assert beta_review_meta["total_count"] == 0, "the flat list is scoped by its filter"
    assert beta_reviews == []
    assert in_session_meta["total_count"] == 0, "the two filter terms are conjunctive"


def test_a_nested_list_under_an_unknown_project_answers_not_found(
    api, functional_reviewer_headers
):
    """An unresolvable path parent is a 404, the opposite of an unmatched filter.

    PRD: "3. **Path existence** — every identifier in the URL resolves to a stored row,
    resolved outer to inner, so a nested path with two unknown identifiers reports the outer
    resource first."

    Design: Corner/cross-cutting complexity layers/xc_child_lists_are_scoped_to_their_parent
    """
    set_clock("2026-08-03T00:00:00Z")
    project = intake_project(
        owner_user_id="lead-sc2", name="Scope Alpha", **SNACK_LINE_EXTENSION
    )
    record_concept_test(
        project["id"], test_type="MONADIC", fielded_at="2026-07-20T00:00:00Z", **MODEST_READ
    )

    response = api.list_concept_tests(NON_EXISTENT_UUID, functional_reviewer_headers)
    error_data = validate_error(response, "ERR_PROJECT_NOT_FOUND", 404)
    present_rows, present_meta = validate_paginated(
        api.list_concept_tests(project["id"], functional_reviewer_headers)
    )

    assert response.status_code == 404, "an unknown parent is not an empty page"
    assert error_data["error_id"] == "ERR_PROJECT_NOT_FOUND"
    assert response.json()["response_type"] == "error"
    assert present_meta["total_count"] == 1, "the real parent still lists its own child"
    assert len(present_rows) == 1
