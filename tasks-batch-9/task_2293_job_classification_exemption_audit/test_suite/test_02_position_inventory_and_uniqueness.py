"""Job inventory lookups, request-shape rejections and code uniqueness."""

from test_helpers import (
    AUDITOR_HEADERS,
    COMPENSATION_MANAGER_HEADERS,
    COMPLIANCE_ANALYST_HEADERS,
    ErrorId,
    PROGRAM_ADMIN_HEADERS,
    UNKNOWN_UUID_A,
    UNKNOWN_UUID_C,
    UNKNOWN_UUID_D,
    assert_created_at_ascending,
    assert_error_envelope,
    assert_family_risk,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_positions_listing_reports_collection_wide_total_count_and_has_more(api, pinned_clock):
    """Pagination metadata describes the whole collection, not the returned page.

    PRD: "List responses populate `limit`, `offset`, `total_count` and `has_more` in the `meta`
    object of the envelope, where `total_count` is the number of rows matching the collection
    before the pagination window is applied and `has_more` states whether any rows remain beyond
    it."

    Design: Corner/entities/positions_listing_under_a_family_reports_total_count_and_has_more
    """
    fixtures.register_state_rule(api, factories.california_rule_payload())
    project = fixtures.create_project(api)
    family = fixtures.create_family(api, project["id"])
    created = [
        fixtures.create_position(
            api,
            family["id"],
            title=title,
            job_code=job_code,
            incumbent_count=1,
            avg_weekly_hours=42,
        )
        for title, job_code in (
            ("Supervisor One", "SS-301"),
            ("Supervisor Two", "SS-302"),
            ("Supervisor Three", "SS-303"),
        )
    ]

    first_rows, first_meta = validate_paginated(
        api.list_family_positions(family["id"], AUDITOR_HEADERS, params={"limit": 2, "offset": 0})
    )
    assert len(first_rows) == 2, f"first page must hold 2 rows, got {len(first_rows)}"
    assert first_meta["total_count"] == 3, (
        f"total_count must describe all 3 jobs, got {first_meta['total_count']}"
    )
    assert first_meta["has_more"] is True, "rows remain beyond the first page"
    assert [row["job_code"] for row in first_rows] == ["SS-301", "SS-302"], (
        f"created_at ascending puts SS-301 then SS-302 first, got {[r['job_code'] for r in first_rows]}"
    )
    assert_created_at_ascending(first_rows, "first page")

    second_rows, second_meta = validate_paginated(
        api.list_family_positions(family["id"], AUDITOR_HEADERS, params={"limit": 2, "offset": 2})
    )
    assert len(second_rows) == 1, f"second page must hold 1 row, got {len(second_rows)}"
    assert second_meta["total_count"] == 3, (
        f"total_count must stay 3 on the second page, got {second_meta['total_count']}"
    )
    assert second_meta["has_more"] is False, "no rows remain beyond the second page"

    paged_ids = [row["id"] for row in first_rows + second_rows]
    assert sorted(paged_ids) == sorted(job["id"] for job in created), (
        "the two pages together must contain each job exactly once"
    )


def test_position_get_with_unknown_id_returns_position_not_found(api, pinned_clock):
    """An unresolvable path parameter is rejected at the path-existence check.

    PRD: "The rejection carries the not-found code of the first path segment that fails to
    resolve: `ERR_AUDIT_PROJECT_NOT_FOUND`, `ERR_JOB_FAMILY_NOT_FOUND`, `ERR_POSITION_NOT_FOUND`"

    Design: Corner/entities/position_get_with_unknown_id_returns_position_not_found
    """
    response = api.get_position(UNKNOWN_UUID_A, COMPLIANCE_ANALYST_HEADERS)

    validate_error(response, ErrorId.POSITION_NOT_FOUND, 404)
    assert_error_envelope(response.json())


def test_position_create_missing_required_annual_salary_is_rejected(api, pinned_clock):
    """A missing required field is a request-shape failure that writes nothing.

    PRD: "On every creating or acting endpoint, the body conforms to the endpoint's input schema:
    required fields present, types correct, enum values inside the declared set, numeric values
    inside the declared range"

    Design: Corner/entities/position_create_missing_required_annual_salary_is_rejected
    """
    fixtures.register_state_rule(api, factories.california_rule_payload())
    project = fixtures.create_project(api)
    family = fixtures.create_family(api, project["id"])

    payload = factories.position_payload(family["id"])
    payload.pop("annual_salary_cents")
    validate_error(
        api.create_position(payload, PROGRAM_ADMIN_HEADERS), ErrorId.INVALID_REQUEST, 400
    )

    rows, meta = validate_paginated(api.list_family_positions(family["id"], AUDITOR_HEADERS))
    assert meta["total_count"] == 0, f"no job may have been created, got {meta['total_count']}"
    assert rows == [], f"no job may have been created, got {rows}"
    assert_family_risk(fixtures.read_family(api, family["id"]), 0, "LOW", headcount=0)


def test_position_create_with_unknown_salary_basis_enum_is_rejected(api, pinned_clock):
    """An enum value outside the declared set is a request-shape failure.

    PRD: "Any failure yields `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/position_create_with_unknown_salary_basis_enum_is_rejected
    """
    fixtures.register_state_rule(api, factories.california_rule_payload())
    project = fixtures.create_project(api)
    family = fixtures.create_family(api, project["id"])

    validate_error(
        api.create_position(
            factories.position_payload(family["id"], salary_basis="PIECE_RATE"),
            PROGRAM_ADMIN_HEADERS,
        ),
        ErrorId.INVALID_REQUEST,
        400,
    )

    _, meta = validate_paginated(api.list_family_positions(family["id"], AUDITOR_HEADERS))
    assert meta["total_count"] == 0, f"no job may have been created, got {meta['total_count']}"


def test_position_create_with_unknown_job_family_returns_job_family_not_found(api, pinned_clock):
    """A body foreign key that resolves to nothing yields the matching 404.

    PRD: "Every entity referenced by a foreign-key field in the body exists, else the matching
    404 -- `ERR_AUDIT_PROJECT_NOT_FOUND` for `audit_project_id`, `ERR_JOB_FAMILY_NOT_FOUND` for
    `job_family_id` or `parent_family_id`"

    Design: Corner/entities/position_create_with_unknown_job_family_returns_job_family_not_found
    """
    fixtures.register_state_rule(api, factories.california_rule_payload())

    validate_error(
        api.create_position(factories.position_payload(UNKNOWN_UUID_C), PROGRAM_ADMIN_HEADERS),
        ErrorId.JOB_FAMILY_NOT_FOUND,
        404,
    )


def test_job_family_with_unknown_parent_family_returns_job_family_not_found(api, pinned_clock):
    """The optional parent pointer is a foreign key and is resolved like any other.

    PRD: "A family may optionally name a `parent_family_id`, which points at another job family
    and defaults to null."

    Design: Corner/entities/job_family_with_unknown_parent_family_returns_job_family_not_found
    """
    project = fixtures.create_project(api)

    validate_error(
        api.create_job_family(
            factories.job_family_payload(
                project["id"],
                name="Shift Leadership",
                code="OPS-SHIFT",
                parent_family_id=UNKNOWN_UUID_D,
            ),
            PROGRAM_ADMIN_HEADERS,
        ),
        ErrorId.JOB_FAMILY_NOT_FOUND,
        404,
    )

    _, meta = validate_paginated(api.list_project_job_families(project["id"], AUDITOR_HEADERS))
    assert meta["total_count"] == 0, f"no family may have been created, got {meta['total_count']}"

    validate_error(
        api.set_audit_project_status(
            project["id"], factories.project_status_payload("FIELDWORK"), PROGRAM_ADMIN_HEADERS
        ),
        ErrorId.PROJECT_STAGE_PRECONDITION_UNMET,
        409,
    )


def test_reclassification_case_with_end_date_before_start_date_is_rejected(
    api, ca_planning_engagement
):
    """Schema validation of the window precedes every temporal separation rule.

    PRD: "`scheduled_end_at` strictly later than `scheduled_start_at`, `effective_end_date` on or
    after `effective_date`, `effective_date` not in the past relative to the logical clock"

    Design: Corner/entities/reclassification_case_with_end_date_before_start_date_is_rejected
    """
    position_id = ca_planning_engagement["position_id"]

    validate_error(
        api.create_reclassification_case(
            factories.reclassification_case_payload(
                position_id, effective_date="2026-10-01", effective_end_date="2026-09-30"
            ),
            COMPENSATION_MANAGER_HEADERS,
        ),
        ErrorId.INVALID_REQUEST,
        400,
    )

    _, meta = validate_paginated(
        api.list_position_reclassification_cases(position_id, COMPENSATION_MANAGER_HEADERS)
    )
    assert meta["total_count"] == 0, f"no case may have been created, got {meta['total_count']}"


def test_duplicate_family_code_inside_one_engagement_is_rejected(api, pinned_clock):
    """Two families in one engagement may not share a code, and the original survives.

    PRD: "Creating one requires the `audit_project_id` of the engagement it belongs to, a display
    `name`, and a `code` that must be unique among that engagement's families; a duplicate `code`
    is rejected with `ERR_DUPLICATE_CODE`."

    Design: Corner/validations/duplicate_family_code_inside_one_project_is_rejected
    """
    project = fixtures.create_project(api)
    family = fixtures.create_family(api, project["id"], name="Operations Leadership", code="OPS-LEAD")

    validate_error(
        api.create_job_family(
            factories.job_family_payload(
                project["id"], name="Operations Leadership Duplicate", code="OPS-LEAD"
            ),
            PROGRAM_ADMIN_HEADERS,
        ),
        ErrorId.DUPLICATE_CODE,
        409,
    )

    survivor = fixtures.read_family(api, family["id"])
    assert survivor["name"] == "Operations Leadership", (
        f"the original family name must not be overwritten, got {survivor['name']}"
    )
    rows, meta = validate_paginated(api.list_project_job_families(project["id"], AUDITOR_HEADERS))
    assert meta["total_count"] == 1, f"exactly one family may exist, got {meta['total_count']}"
    assert len(rows) == 1, f"exactly one family may exist, got {len(rows)}"


def test_the_same_family_code_under_a_different_engagement_is_accepted(api, pinned_clock):
    """Family-code uniqueness is scoped to one engagement, not to the whole registry.

    PRD: "a `code` is unique among the job families of one `audit_project_id`"

    Design: Corner/validations/the_same_family_code_under_a_different_project_is_accepted
    """
    project_a = fixtures.create_project(api, name="FY26 Classification Audit", fiscal_year=2026)
    project_b = fixtures.create_project(api, name="FY27 Classification Audit", fiscal_year=2027)
    fixtures.create_family(api, project_a["id"], name="Operations Leadership", code="OPS-LEAD")

    family_b = validate_success(
        api.create_job_family(
            factories.job_family_payload(
                project_b["id"], name="Operations Leadership", code="OPS-LEAD"
            ),
            PROGRAM_ADMIN_HEADERS,
        ),
        201,
    )

    assert family_b["code"] == "OPS-LEAD", f"code must be echoed back, got {family_b['code']}"
    assert family_b["audit_project_id"] == project_b["id"], (
        "the new family must hang off the second engagement"
    )
    assert family_b["version"] == 1, f"version must start at 1, got {family_b['version']}"

    for label, project_id in (("first", project_a["id"]), ("second", project_b["id"])):
        _, meta = validate_paginated(api.list_project_job_families(project_id, AUDITOR_HEADERS))
        assert meta["total_count"] == 1, (
            f"the {label} engagement must hold exactly one family, got {meta['total_count']}"
        )
