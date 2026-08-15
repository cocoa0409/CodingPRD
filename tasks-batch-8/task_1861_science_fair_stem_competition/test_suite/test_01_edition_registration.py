"""Edition setup, project registration, intake validation, and envelope checks.

Covers: edition creation defaults, required-field and enum intake checks,
path existence, pagination envelope, authentication/authorization denials,
team-size bounds, cross-edition referential integrity, project initial state,
the close-registration sweep, and terminal/invalid project transitions.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_category,
    add_mentor,
    api_client,
    assert_fair_edition,
    assert_judge_conflict,
    assert_project,
    close_registration,
    conflict_payload,
    create_edition,
    fd_headers,
    get_project,
    judge_payload,
    make_judge_headers,
    make_mentor_headers,
    open_registration,
    project_payload,
    register_project,
    setup_open_edition,
    setup_registration_closed,
    submit_project,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_project,
)


class TestFairEditionCreation:
    def test_fair_edition_creation_defaults(self, api):
        """PRD §3.1: "New editions are born in `SETUP` with `advancement_freeze`
        false."

        Design: Corner/entities/fair_edition_creation_defaults_and_system_fields
        """
        edition = create_edition(name="Defaults Edition", algorithm="MIN_MAX")
        assert_fair_edition(edition)
        assert edition["status"] == "SETUP", (
            f"new edition must be born SETUP, got {edition['status']}"
        )
        assert edition["advancement_freeze"] is False, (
            "new edition must be born with advancement_freeze false"
        )

    def test_fair_edition_missing_required_field(self, api):
        """PRD §2.8: "Required fields are present, types are correct, and enum
        values fall within their declared sets; failures report
        `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/fair_edition_missing_required_field_returns_invalid_request
        """
        resp = api_client.create_fair_edition(
            {"name": "Bad", "max_judges_per_project": 2, "min_quorum_ratio_pct": 50},
            fd_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_fair_edition_invalid_normalization_enum(self, api):
        """PRD §3.1: "a `normalization_algorithm` of either `Z_SCORE` or
        `MIN_MAX` (which fixes how every judge's scores will be normalized all
        season, per §3.5)". PRD §2.8: "enum values fall within their declared
        sets; failures report `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/fair_edition_invalid_enum_normalization_rejected
        """
        resp = api_client.create_fair_edition(
            {
                "name": "BadEnum",
                "normalization_algorithm": "RANK_SUM",
                "max_judges_per_project": 2,
                "min_quorum_ratio_pct": 50,
            },
            fd_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestProjectReadbackAndListing:
    def test_project_get_not_found(self, api):
        """PRD §2.8: "Every resource named in the path exists, validated left
        to right; the first missing identifier yields `ERR_NOT_FOUND` (404)."

        Design: Corner/entities/project_get_not_found_returns_404
        """
        resp = api_client.get_project(NON_EXISTENT_UUID, fd_headers())
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_list_projects_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned: it defaults to 10 when omitted, and accepts values from a
        minimum of 1 to a maximum of 100."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/list_projects_pagination_envelope
        """
        ctx = setup_open_edition(name="Pag Edition")
        register_project(ctx["edition"]["id"], ctx["category"]["id"], ctx["mentor"]["id"], title="T1")

        resp = api_client.list_projects(fd_headers())
        assert resp.json().get("response_type") == "array", (
            f"list endpoint must return response_type 'array', got {resp.json().get('response_type')!r}"
        )
        data, meta = validate_paginated(resp)
        assert meta["limit"] == 10, f"default limit must be 10, got {meta['limit']}"
        assert meta["offset"] == 0
        assert meta["total_count"] == 1, f"expected exactly one project, got {meta['total_count']}"
        assert meta["has_more"] is False
        assert len(data) == 1

    def test_initial_state_new_project(self, api):
        """PRD §3.2: "A new project starts with `registration_status` `DRAFT`,
        a null `ethics_status`, `inspection_status` `NOT_SCHEDULED`,
        `judging_status` `UNASSIGNED`, `advancement_result` `PENDING`, a null
        `advancement_rank`, and both aggregates null."

        Design: Corner/state_machines/initial_state_new_project_is_draft
        """
        ctx = setup_open_edition(name="Init Edition")
        project = register_project(
            ctx["edition"]["id"], ctx["category"]["id"], ctx["mentor"]["id"], title="NewP"
        )
        assert_project(project)
        assert project["registration_status"] == "DRAFT"
        assert project["ethics_status"] is None, "ethics_status must be unset until submit"
        assert project["inspection_status"] == "NOT_SCHEDULED"
        assert project["judging_status"] == "UNASSIGNED"
        assert project["advancement_result"] == "PENDING"
        assert project["advancement_rank"] is None


class TestAuthenticationAndAuthorization:
    def test_missing_headers_unauthenticated(self, api):
        """PRD §2.1: "A request that omits either header, or carries a role
        outside this declared set, is an `Anonymous` call and is rejected with
        `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/auth_missing_headers_unauthenticated
        """
        resp = api_client.list_fair_editions(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    def test_role_cannot_invoke_exclusive_endpoint(self, api):
        """PRD §2.1: "A request whose authenticated role is simply not
        permitted to invoke the target endpoint is rejected with
        `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/role_cannot_invoke_exclusive_endpoint
        """
        edition = create_edition(name="RBAC3 Edition")
        add_category(edition["id"])
        resp = api_client.open_registration(
            edition["id"], make_judge_headers(NON_EXISTENT_UUID)
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


class TestProjectIntakeValidation:
    def test_team_size_bounds(self, api):
        """PRD §3.2: "a `team_size` between 1 and 3 (anything outside that
        range fails fast as `ERR_INVALID_REQUEST`)".
        PRD §2.8: "Range violations on intake fields fail here as well: a
        `team_size` outside the 1-to-3 range, a `max_judges_per_project` below
        2, a `min_quorum_ratio_pct` outside 1 through 100, a negative
        `advancement_slots`, a `max_assignments` below 1, or a negative
        `total_cents`."

        Design: Corner/validations/team_size_aggregate_boundary
        """
        ctx = setup_open_edition(name="TS Edition")
        mentor_id = ctx["mentor"]["id"]

        resp0 = api_client.create_project(
            project_payload(ctx["edition"]["id"], ctx["category"]["id"], title="T0", team_size=0),
            make_mentor_headers(mentor_id),
        )
        validate_error(resp0, ApiErrorId.ERR_INVALID_REQUEST, 400)

        resp4 = api_client.create_project(
            project_payload(ctx["edition"]["id"], ctx["category"]["id"], title="T4", team_size=4),
            make_mentor_headers(mentor_id),
        )
        validate_error(resp4, ApiErrorId.ERR_INVALID_REQUEST, 400)

        resp3 = api_client.create_project(
            project_payload(ctx["edition"]["id"], ctx["category"]["id"], title="T3", team_size=3),
            make_mentor_headers(mentor_id),
        )
        project = validate_success(resp3, 201)
        assert project["team_size"] == 3, "team_size 3 is inside the 1-to-3 range and must be accepted"

    def test_cross_edition_category_rejected(self, api):
        """PRD §2.8: "A `category_id`, `mentor_id`, `judge_id`, or `project_id`
        referenced in a payload must exist and must belong to the same fair
        edition as the rest of the request; otherwise
        `ERR_REFERENTIAL_INTEGRITY` (422)."

        Design: Corner/validations/referential_integrity_cross_edition_category
        """
        e1 = create_edition(name="E1")
        e2 = create_edition(name="E2")
        add_category(e1["id"], code="C1", name="Cat1")
        c2 = add_category(e2["id"], code="C2", name="Cat2")
        mentor = add_mentor(full_name="Mentor RI")
        open_registration(e1["id"])
        open_registration(e2["id"])

        resp = api_client.create_project(
            project_payload(e1["id"], c2["id"], title="CrossRef"),
            make_mentor_headers(mentor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL_INTEGRITY, 422)


class TestEditionPhaseTransitions:
    def test_open_registration_requires_open_category(self, api):
        """PRD §3.1: "the edition must contain at least one category still in
        `OPEN` status, or the transition fails with `ERR_NO_OPEN_CATEGORY`."

        Design: Corner/state_machines/open_registration_requires_open_category
        """
        edition = create_edition(name="NoCat Edition")
        resp = api_client.open_registration(edition["id"], fd_headers())
        validate_error(resp, ApiErrorId.ERR_NO_OPEN_CATEGORY, 409)

        add_category(edition["id"])
        opened = validate_success(api_client.open_registration(edition["id"], fd_headers()))
        assert opened["status"] == "REGISTRATION_OPEN"

    def test_close_registration_sweep(self, api):
        """PRD §3.2: "every project still in `DRAFT` is withdrawn; every
        project in `SUBMITTED` whose `ethics_status` is `APPROVED` or
        `NOT_REQUIRED` at that moment is confirmed (`SUBMITTED` → `CONFIRMED`)".

        Design: Corner/state_machines/close_registration_withdraws_draft_side_effect
        """
        ctx = setup_open_edition(name="Close Edition")
        mentor_id = ctx["mentor"]["id"]
        pd = register_project(ctx["edition"]["id"], ctx["category"]["id"], mentor_id, title="PD")
        ps = register_project(ctx["edition"]["id"], ctx["category"]["id"], mentor_id, title="PS")
        submit_project(ps["id"], mentor_id)

        close_registration(ctx["edition"]["id"])

        pd_after = get_project(pd["id"])
        ps_after = get_project(ps["id"])
        assert pd_after["registration_status"] == "WITHDRAWN", (
            "DRAFT projects must be withdrawn by the closing sweep"
        )
        assert ps_after["registration_status"] == "CONFIRMED", (
            "SUBMITTED projects with ethics NOT_REQUIRED must be confirmed"
        )
        assert ps_after["ethics_status"] == "NOT_REQUIRED"


class TestProjectTransitionGuards:
    def test_submit_confirmed_project_rejected(self, api):
        """PRD §3.2: "Submitting moves a project `DRAFT` → `SUBMITTED`."
        PRD §2.8: "The target resource is in a state from which the requested
        transition is allowed; otherwise `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/invalid_transition_submit_confirmed_project
        """
        ctx = setup_registration_closed(num_projects=1, name="IT Edition")
        project = ctx["projects"][0]
        assert project["registration_status"] == "CONFIRMED"

        resp = api_client.submit_project(project["id"], make_mentor_headers(ctx["mentor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_withdrawn_project_is_terminal(self, api):
        """PRD §3.2: "Any transition trigger aimed at an already-`WITHDRAWN`
        project is rejected with `ERR_ALREADY_TERMINAL` (409), which takes
        precedence over the generic `ERR_INVALID_STATE` for that terminal
        source."

        Design: Corner/state_machines/terminal_lockdown_withdrawn_project
        """
        ctx = setup_open_edition(name="Term Edition")
        project = register_project(
            ctx["edition"]["id"], ctx["category"]["id"], ctx["mentor"]["id"], title="TP"
        )
        withdraw_project(project["id"], ctx["mentor"]["id"])

        resp = api_client.submit_project(project["id"], make_mentor_headers(ctx["mentor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL, 409)


class TestJudgeConflictRecord:
    def test_conflict_record_has_no_version_fields(self, api):
        """PRD §2.4: "a judge-conflict record and a score sheet are immutable
        once written, so each carries only `id` and `created_at` among the
        standard fields — both `updated_at` and `version` are absent from
        them."

        Design: Corner/entities/judge_conflict_immutable_no_version_field
        """
        ctx = setup_open_edition(name="Imm Edition")
        project = register_project(
            ctx["edition"]["id"], ctx["category"]["id"], ctx["mentor"]["id"], title="PI"
        )
        judge = validate_success(
            api_client.create_judge(
                judge_payload(ctx["edition"]["id"], full_name="JI", max_assignments=3),
                fd_headers(),
            ),
            201,
        )

        resp = api_client.declare_conflict(
            judge["id"], conflict_payload(project["id"], reason="same school"), fd_headers()
        )
        conflict = validate_success(resp, 201)
        assert_judge_conflict(conflict)
        assert conflict["reason"] == "same school"
