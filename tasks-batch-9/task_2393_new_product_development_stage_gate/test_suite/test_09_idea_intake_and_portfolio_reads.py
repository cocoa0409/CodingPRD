"""Idea intake defaults, configuration reads, portfolio listing and intake rejections."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_project,
    assert_stage_gate,
    intake_project,
    is_valid_uuid,
    make_innovation_lead_headers,
    make_portfolio_admin_headers,
    project_payload,
    register_stage_gate,
    screen_project,
    set_clock,
    stage_gate_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

SNACK_IDEA = {
    "name": "Toffee Crunch Bites",
    "brand": "GrainWell",
    "category": "SNACK",
    "project_type": "LINE_EXTENSION",
    "strategic_fit_score": 8,
    "consumer_need_score": 7,
    "target_gross_margin_pct": 36,
    "category_attractiveness_score": 7,
    "development_budget_cap_usd": 500000.00,
}


def test_intake_returns_every_declared_default_on_both_status_tracks(api):
    """A bare intake answers 201 with the two tracks at their start states and the
    derived fields at zero rather than absent.

    PRD: "A freshly intaken project has `dev_status` `IDEA`, `commercial_status`
    `NOT_STARTED`, `next_gate_number` 2, `screening_decision` `PENDING`,
    `screening_score` and `launch_date` and `shelf_reset_window_id` and
    `post_launch_decision` all null, `development_budget_committed_usd` `0.00`,
    `launch_readiness_pct` `0.00`, `authorized_acv_pct` `0.00`, `recycle_count` 0, and
    `open_gate_conditions` false."
    PRD: "Operations that create a new stored row return `201 Created`."

    Design: Corner/entities/entity_create_innovation_project_returns_defaults_and_system_fields
    """
    set_clock("2026-08-01T00:00:00Z")

    project = validate_success(
        api.create_project(
            project_payload(**SNACK_IDEA), make_innovation_lead_headers("lead-c1")
        ),
        201,
    )

    assert_project(project)
    assert project["dev_status"] == "IDEA"
    assert project["commercial_status"] == "NOT_STARTED"
    assert project["screening_decision"] == "PENDING"
    assert project["next_gate_number"] == 2
    assert project["recycle_count"] == 0
    assert project["open_gate_conditions"] is False
    assert project["development_budget_committed_usd"] == pytest.approx(0.00, abs=0.01)
    assert project["launch_readiness_pct"] == pytest.approx(0.00, abs=0.01)
    assert project["authorized_acv_pct"] == pytest.approx(0.00, abs=0.01)
    for null_field in (
        "screening_score",
        "launch_date",
        "shelf_reset_window_id",
        "post_launch_decision",
    ):
        assert project.get(null_field) is None, (
            f"{null_field} is null on a freshly intaken project, got {project.get(null_field)!r}"
        )


def test_intake_captures_the_acting_lead_as_owner_with_a_bare_uuid_identity(api):
    """The creating lead's opaque identifier lands in `owner_user_id`, and the row is
    addressed by a bare UUID at version 1.

    PRD: "The acting user's opaque identifier is captured as `owner_user_id`, which is
    what later bars that same person from voting at the project's gates."
    PRD: "Every stored resource is addressed by an `id` that the server mints as a UUID.
    Identifiers carry no type prefix and clients never supply them."

    Design: Corner/entities/entity_create_innovation_project_returns_defaults_and_system_fields
    """
    set_clock("2026-08-01T00:00:00Z")

    project = validate_success(
        api.create_project(
            project_payload(**SNACK_IDEA), make_innovation_lead_headers("lead-c1")
        ),
        201,
    )

    assert project["owner_user_id"] == "lead-c1", (
        "owner_user_id is taken from X-User-ID, never from the request body"
    )
    assert is_valid_uuid(project["id"]), f"id must be a bare UUID, got {project['id']!r}"
    assert "_" not in project["id"] and ":" not in project["id"], (
        "identifiers carry no type prefix"
    )
    assert project["version"] == 1, "version starts at 1 on insert"


def test_stage_gate_read_echoes_the_stored_configuration(api, gate_chair_headers):
    """Reading a registered gate returns its checklist array in order, its empty veto
    list and its four bars exactly as supplied.

    PRD: "A **stage gate** configuration is registered per category with a `gate_number`,
    a `category`, the `stage_from` development state a project must hold to convene it
    (`SCREENED` or `PILOT_QUALIFIED`), the `stage_to` state a passing decision moves it to
    (`PILOT_QUALIFIED` or `LAUNCH_READY`), the `required_deliverable_types` checklist that
    is auto-created when a project enters `stage_from`, a `quorum_size` of at least one
    ballot, the `veto_functions` whose rejection is fatal rather than merely recycling, and
    the four bars a passing decision must clear: `npv_hurdle_usd`, `payback_months_max`,
    `gross_margin_floor_pct` and `readiness_floor_index`."
    PRD: "The `required_deliverable_types` array may legitimately be empty and must
    contain no duplicates."

    Design: Corner/entities/entity_get_stage_gate_returns_stored_configuration
    """
    created = validate_success(
        api.create_stage_gate(
            stage_gate_payload(
                gate_number=2,
                category="SNACK",
                stage_from="SCREENED",
                stage_to="PILOT_QUALIFIED",
                required_deliverable_types=["CONSUMER_CONCEPT_TEST", "PRELIM_BUSINESS_CASE"],
                quorum_size=2,
                veto_functions=[],
                npv_hurdle_usd=250000.00,
                payback_months_max=24,
                gross_margin_floor_pct=30.00,
                readiness_floor_index=55.00,
            ),
            make_portfolio_admin_headers("admin-g1"),
        ),
        201,
    )

    gate = validate_success(api.get_stage_gate(created["id"], gate_chair_headers))

    assert_stage_gate(gate)
    assert gate["required_deliverable_types"] == [
        "CONSUMER_CONCEPT_TEST",
        "PRELIM_BUSINESS_CASE",
    ], "the checklist array is stored in the order it was registered"
    assert gate["veto_functions"] == [], "an empty veto list stays an empty array"
    assert gate["quorum_size"] == 2
    assert gate["gate_number"] == 2 and gate["category"] == "SNACK"
    assert gate["stage_from"] == "SCREENED" and gate["stage_to"] == "PILOT_QUALIFIED"
    assert gate["npv_hurdle_usd"] == pytest.approx(250000.00, abs=0.01)
    assert gate["payback_months_max"] == 24
    assert gate["gross_margin_floor_pct"] == pytest.approx(30.00, abs=0.01)
    assert gate["readiness_floor_index"] == pytest.approx(55.00, abs=0.01)
    assert gate["version"] == 1, "a read is not a write, so the configuration is still at 1"


def _three_snack_ideas_one_screened():
    """A snack gate 2 and three snack ideas, the last of which is screened."""
    set_clock("2026-08-01T00:00:00Z")
    register_stage_gate(
        gate_number=2, category="SNACK", stage_from="SCREENED",
        stage_to="PILOT_QUALIFIED", required_deliverable_types=[],
    )
    first = intake_project(owner_user_id="lead-l1", **dict(SNACK_IDEA))
    set_clock("2026-08-01T01:00:00Z")
    second = intake_project(
        owner_user_id="lead-l1", **dict(SNACK_IDEA, name="Toffee Crunch Minis")
    )
    set_clock("2026-08-01T02:00:00Z")
    third = intake_project(
        owner_user_id="lead-l1", **dict(SNACK_IDEA, name="Toffee Crunch Bars")
    )
    screened = screen_project(
        third["id"], chair_user_id="chair-l1",
        screening_notes="Fits the better-for-you platform.",
    )
    return first, second, screened


def test_project_list_counts_the_whole_set_beyond_the_returned_page(api,
                                                                   portfolio_admin_headers):
    """Three projects read with `limit` 2 return two rows, `total_count` 3 and
    `has_more` true.

    PRD: "`limit` caps the number of rows returned; it defaults to 10, may not be below 1
    and may not exceed 100."
    PRD: "Both `limit` and `offset` are echoed in the `meta` object alongside
    `total_count` (the number of rows matching the filters before pagination) and
    `has_more` (true when rows remain beyond the current page)."

    Design: Corner/entities/entity_list_innovation_projects_paginates_and_filters_by_dev_status
    """
    _three_snack_ideas_one_screened()

    rows, meta = validate_paginated(
        api.list_projects(portfolio_admin_headers, params={"limit": 2, "offset": 0})
    )

    assert len(rows) == 2, f"limit 2 caps the page at two rows, got {len(rows)}"
    assert meta["total_count"] == 3, "total_count counts the whole matching set"
    assert meta["has_more"] is True, "a third row remains beyond the page"
    assert meta["limit"] == 2 and meta["offset"] == 0, "both are echoed in meta"


def test_project_list_filters_by_dev_status_and_orders_by_creation(api,
                                                                  portfolio_admin_headers):
    """A `dev_status` filter narrows `total_count` to the single screened row while the
    unfiltered list stays in creation order.

    PRD: "List endpoints also accept optional equality filters drawn from the listed
    entity's own fields."
    PRD: "Unless a specific list says otherwise, rows are ordered by `created_at`
    ascending."

    Design: Corner/entities/entity_list_innovation_projects_paginates_and_filters_by_dev_status
    """
    first, second, screened = _three_snack_ideas_one_screened()

    filtered, filtered_meta = validate_paginated(
        api.list_projects(portfolio_admin_headers, params={"dev_status": "SCREENED"})
    )

    assert filtered_meta["total_count"] == 1, "only the screened project matches"
    assert filtered_meta["has_more"] is False
    assert [row["id"] for row in filtered] == [screened["id"]]
    assert filtered[0]["dev_status"] == "SCREENED"

    everything, meta = validate_paginated(
        api.list_projects(portfolio_admin_headers, params={"limit": 100})
    )
    assert meta["total_count"] == 3
    ids = [row["id"] for row in everything]
    assert ids.index(first["id"]) < ids.index(second["id"]), (
        "the unfiltered list orders rows by created_at ascending"
    )
    by_id = {row["id"]: row for row in everything}
    assert by_id[first["id"]]["dev_status"] == "IDEA"
    assert by_id[second["id"]]["dev_status"] == "IDEA"


def test_unknown_project_id_answers_the_project_family_not_found(api,
                                                                 portfolio_admin_headers):
    """A well-formed UUID that resolves to nothing is a 404 carrying the project
    family's own error id.

    PRD: "**Path existence** — every identifier in the URL resolves to a stored row,
    resolved outer to inner, so a nested path with two unknown identifiers reports the
    outer resource first. Each resource family has its own 404 code:
    `ERR_PROJECT_NOT_FOUND` for a project, `ERR_STAGE_GATE_NOT_FOUND` for a gate
    configuration, `ERR_GATE_REVIEW_NOT_FOUND` for a review, `ERR_DELIVERABLE_NOT_FOUND`
    for a checklist item, `ERR_BUSINESS_CASE_NOT_FOUND` for a business case,
    `ERR_FORMULATION_NOT_FOUND` for a formulation revision, `ERR_PILOT_LINE_NOT_FOUND` for
    a pilot line, `ERR_PILOT_RUN_NOT_FOUND` for a pilot run,
    `ERR_SHELF_LIFE_STUDY_NOT_FOUND` for a stability study,
    `ERR_LABEL_APPROVAL_NOT_FOUND` for a label approval, `ERR_RETAILER_NOT_FOUND` for a
    retailer, `ERR_RESET_WINDOW_NOT_FOUND` for a reset window, and
    `ERR_PRESENTATION_NOT_FOUND` for a trade presentation."

    Design: Corner/entities/entity_get_unknown_project_id_not_found
    """
    error = validate_error(
        api.get_project(NON_EXISTENT_UUID, portfolio_admin_headers),
        ApiErrorId.ERR_PROJECT_NOT_FOUND,
    )

    assert error["error_id"] == ApiErrorId.ERR_PROJECT_NOT_FOUND.value
    assert isinstance(error.get("message"), str) and error["message"], (
        "the error payload carries a human-readable message"
    )


def test_intake_without_a_target_margin_is_a_shape_violation(api, innovation_lead_headers,
                                                             portfolio_admin_headers):
    """Omitting `target_gross_margin_pct` answers 400 and stores nothing.

    PRD: "An `InnovationLead` intakes an idea by supplying a `name` of 1 to 120
    characters, the owning `brand`, the `category`, the `project_type`, four rating inputs
    — `strategic_fit_score`, `consumer_need_score` and `category_attractiveness_score`
    each on a `0.00` to `10.00` scale, plus `target_gross_margin_pct` between `0.00` and
    `100.00` — and a `development_budget_cap_usd` of at least `0.00`."
    PRD: "**Request shape** — the body parses, required fields are present, enum values
    are legal, numbers lie inside their declared ranges and datetimes are ISO 8601.
    Otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/entity_create_project_missing_target_margin_rejected
    """
    payload = project_payload(**SNACK_IDEA)
    payload.pop("target_gross_margin_pct")

    validate_error(
        api.create_project(payload, innovation_lead_headers),
        ApiErrorId.ERR_INVALID_REQUEST,
    )

    _, meta = validate_paginated(api.list_projects(portfolio_admin_headers))
    assert meta["total_count"] == 0, "a rejected intake stores no partial row"


def test_intake_with_illegal_category_or_out_of_range_rating_is_rejected(
        api, innovation_lead_headers, portfolio_admin_headers):
    """An out-of-vocabulary `category` and a `strategic_fit_score` above 10.00 both stop
    at request-shape validation.

    PRD: "The following closed vocabularies are used throughout and any other value is a
    shape violation answering `ERR_INVALID_REQUEST`."
    PRD: "**Request shape** — the body parses, required fields are present, enum values
    are legal, numbers lie inside their declared ranges and datetimes are ISO 8601.
    Otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/entity_invalid_category_enum_and_out_of_range_score_rejected
    """
    validate_error(
        api.create_project(
            project_payload(**dict(SNACK_IDEA, name="Frozen Yuzu Pops", category="FROZEN")),
            innovation_lead_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
    )

    validate_error(
        api.create_project(
            project_payload(**dict(SNACK_IDEA, strategic_fit_score=12.5)),
            innovation_lead_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
    )

    _, meta = validate_paginated(api.list_projects(portfolio_admin_headers))
    assert meta["total_count"] == 0, "neither rejected intake stored a row"
