"""Created shapes, omitted-input defaults, listing filters and reference lookups."""

import pytest

from test_helpers import (
    ApiErrorId,
    ChangeState,
    CleanupState,
    DependencyDirection,
    FlagLinkGuardKind,
    FlagState,
    ReleasePhase,
    RiskClass,
    TrainPhase,
    assert_change_dependency,
    assert_change_flag_link,
    assert_envelope_shape,
    assert_feature_flag,
    assert_instant,
    assert_release,
    assert_release_train,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import (
    DEFAULT_COOLDOWN_MINUTES,
    FLAG_EXPIRES_AT,
    RELEASE_FREEZE_AT,
    RELEASE_STABILIZATION_END_AT,
)
from test_helpers.factories import (
    make_change_request_payload,
    make_deployment_payload,
    make_incident_payload,
    make_release_payload,
)
from test_helpers.fixtures import (
    create_change,
    create_environment,
    create_flag,
    create_release,
    create_train,
    cut_release_at_freeze,
    declare_dependency,
    link_flag,
    plan_step,
    read_change,
    read_release,
    read_train,
    reset_clock,
    start_soak,
    submit_change,
    train_with_release,
)
from test_helpers.test_users import (
    CHANGE_APPROVER,
    COMPLIANCE_OFFICER,
    ENGINEER,
    PLATFORM_ADMIN,
    RELEASE_MANAGER,
    SRE,
    THIRD_ENGINEER_USER_ID,
)

#: Six syntactically valid UUIDs that name nothing, one per 404 family.
UNKNOWN_RELEASE_ID = "11111111-1111-4111-8111-111111111111"
UNKNOWN_TRAIN_ID = "22222222-2222-4222-8222-222222222222"
UNKNOWN_CHANGE_ID = "33333333-3333-4333-8333-333333333333"
UNKNOWN_FLAG_ID = "44444444-4444-4444-8444-444444444444"
UNKNOWN_STEP_ID = "55555555-5555-4555-8555-555555555555"
UNKNOWN_DEPLOYMENT_ID = "66666666-6666-4666-8666-666666666666"


class TestCreatedShapesAndOmittedInputDefaults:
    """Every optional input omitted from the payload lands on its declared default."""

    def test_new_train_defaults_its_capacity_and_zeroes_both_counters(self, api):
        """"One optional input, ``max_concurrent_stabilizing``, states how many of the
        train's releases may have overlapping stabilization spans; it must be at
        least 1 and defaults to 1 when omitted." A new train has "``phase``
        ``ACTIVE``, a null ``frozen_at``, and both of its computed counters at zero".

        Design: Corner/entities/create_release_train_applies_defaults_and_zero_counters
        """
        reset_clock(api)

        train = create_train(api)

        assert_release_train(train)
        assert train["phase"] == TrainPhase.ACTIVE
        assert train["max_concurrent_stabilizing"] == 1
        assert train["frozen_at"] is None
        assert train["freeze_exception_count"] == 0
        assert train["open_release_count"] == 0
        assert train["version"] == 1
        assert is_valid_uuid(train["id"])

    def test_new_flag_and_new_environment_take_their_declared_defaults(self, api):
        """One optional flag input, "``permanent``, defaults to false"; an environment
        defaults "``cooldown_minutes`` ... to 30" and "``requires_compliance_evidence``,
        defaulting to false", starting with "``active_deployment_count`` 0 ... and a
        null ``last_deployment_end_at``".

        Design: Corner/entities/create_feature_flag_omitting_permanent_defaults_to_false
        """
        reset_clock(api)

        flag = create_flag(api)
        environment = create_environment(api)

        assert flag["permanent"] is False
        assert environment["cooldown_minutes"] == DEFAULT_COOLDOWN_MINUTES
        assert environment["requires_compliance_evidence"] is False
        assert environment["blackout_start_at"] is None
        assert environment["blackout_end_at"] is None
        assert environment["active_deployment_count"] == 0
        assert environment["last_deployment_end_at"] is None

    def test_flag_read_echoes_the_stored_inputs_and_the_computed_defaults(self, api):
        """"The server stamps ``created_by_user_id`` from ``X-User-ID``. A new flag has
        ``state`` ``DRAFT``, ``cleanup_state`` ``COMPLIANT``, ``current_exposure_pct``
        0, ``applied_step_count`` 0, ``kill_switch_engaged`` false,
        ``stale_debt_points`` 0, and null ``last_sweep_at`` and ``archived_at``."

        Design: Corner/entities/get_feature_flag_returns_stored_and_computed_fields
        """
        reset_clock(api)
        created = create_flag(
            api, ENGINEER, key="checkout-v2", owner_user_id=THIRD_ENGINEER_USER_ID
        )

        flag = validate_success(
            api.get_feature_flag(created["id"], COMPLIANCE_OFFICER), 200
        )

        assert_feature_flag(flag)
        assert flag["key"] == "checkout-v2"
        assert flag["owner_user_id"] == THIRD_ENGINEER_USER_ID
        assert flag["created_by_user_id"] != flag["owner_user_id"]
        assert_instant(flag["expires_at"], FLAG_EXPIRES_AT, "expires_at")
        assert flag["state"] == FlagState.DRAFT
        assert flag["cleanup_state"] == CleanupState.COMPLIANT
        assert flag["current_exposure_pct"] == pytest.approx(0, abs=0.01)
        assert flag["applied_step_count"] == 0
        assert flag["kill_switch_engaged"] is False
        assert flag["stale_debt_points"] == 0
        assert flag["last_sweep_at"] is None
        assert flag["archived_at"] is None

    def test_release_derives_both_span_endpoints_from_its_train(self, api):
        """"Its ``freeze_at`` is the ``cut_at`` instant moved earlier by the train's
        ``code_freeze_lead_hours``. Its ``stabilization_end_at`` is the ``cut_at``
        instant moved later by the train's ``stabilization_hours``". Creation "raises
        the train's ``open_release_count`` by one".

        Design: Corner/entities/release_system_fields_are_server_minted_and_derived_from_train
        """
        reset_clock(api)
        train = create_train(api)

        release = create_release(api, train["id"])

        assert_release(release)
        assert_instant(release["freeze_at"], RELEASE_FREEZE_AT, "freeze_at")
        assert_instant(
            release["stabilization_end_at"],
            RELEASE_STABILIZATION_END_AT,
            "stabilization_end_at",
        )
        assert release["phase"] == ReleasePhase.OPEN
        assert release["version"] == 1
        assert release["released_at"] is None
        assert release["rolled_back_at"] is None
        assert release["committed_change_count"] == 0
        assert release["verified_change_count"] == 0
        assert release["risk_budget_consumed_points"] == 0
        assert release["readiness_score_projected"] == 100
        assert release["readiness_score_attested"] is None
        assert read_train(api, train["id"])["open_release_count"] == 1

    def test_client_supplied_values_for_computed_risk_fields_are_ignored(self, api):
        """A change "begins in ``state`` ``DRAFT`` with ``risk_score_preliminary``,
        ``risk_score_final`` and ``risk_class`` all null", and submission is what
        "pins ``risk_score_preliminary`` and the ``risk_class`` tier derived from it".

        Design: Corner/entities/change_request_risk_class_is_computed_extra_field_input_ignored
        """
        reset_clock(api)
        built = train_with_release(api)
        change = create_change(
            api,
            built["release"]["id"],
            payload=make_change_request_payload(
                title="Retry policy rewrite",
                summary_internal="Two-subsystem retry rewrite",
                lines_changed=300,
                touched_subsystem_count=2,
                declared_blast_radius="SINGLE_TENANT",
                risk_class=RiskClass.LOW,
                risk_score_preliminary=1,
            ),
        )
        assert change["risk_class"] is None
        assert change["risk_score_preliminary"] is None

        submitted = submit_change(api, change["id"])

        assert submitted["risk_score_preliminary"] == 33
        assert submitted["risk_class"] == RiskClass.MEDIUM
        assert submitted["state"] == ChangeState.RISK_CLASSIFIED


class TestInventoryListingPagesAndFilters:
    """"``total_count``" is reported over the filtered set, not over the page."""

    def test_two_pages_split_three_flags_and_agree_on_the_total(self, api):
        """"List responses include ``limit``, ``offset``, ``total_count`` and
        ``has_more`` in the envelope's ``meta`` object."

        Design: Corner/entities/list_feature_flags_paginates_with_total_count_and_has_more
        """
        reset_clock(api)
        created_ids = {
            create_flag(api, ENGINEER, key=key)["id"]
            for key in ("flag-a", "flag-b", "flag-c")
        }

        first_response = api.list_feature_flags(PLATFORM_ADMIN, {"limit": 2, "offset": 0})
        second_response = api.list_feature_flags(PLATFORM_ADMIN, {"limit": 2, "offset": 2})

        assert_envelope_shape(first_response.json(), "array")
        assert_envelope_shape(second_response.json(), "array")
        first_page, first_meta = validate_paginated(first_response)
        second_page, second_meta = validate_paginated(second_response)
        assert len(first_page) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert len(second_page) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
        assert second_meta["limit"] == 2
        assert second_meta["offset"] == 2
        paged_ids = [row["id"] for row in first_page + second_page]
        assert len(paged_ids) == len(set(paged_ids))
        assert set(paged_ids) == created_ids

    def test_state_filter_drops_the_rolling_flag_and_lowers_the_total(self, api):
        """"The flag inventory may be filtered by ``state``, by ``cleanup_state`` and
        by ``owner_user_id``, in any combination", and "``total_count``" is reported
        over that filtered set.

        Design: Corner/entities/list_feature_flags_state_filter_narrows_total_count
        """
        reset_clock(api)
        draft_flag = create_flag(api, ENGINEER, key="flag-a")
        rolling_flag = create_flag(api, ENGINEER, key="flag-b")
        step = plan_step(api, rolling_flag["id"], target_pct=5, soak_minutes=30)
        start_soak(api, step["id"])

        flags, meta = validate_paginated(
            api.list_feature_flags(SRE, {"state": FlagState.DRAFT})
        )

        assert meta["total_count"] == 1
        assert len(flags) == 1
        assert flags[0]["id"] == draft_flag["id"]
        assert flags[0]["state"] == FlagState.DRAFT
        assert rolling_flag["id"] not in [row["id"] for row in flags]


class TestJunctionRowsAreThinAndReadableFromBothEnds:
    """The five audit record types "are deliberately thinner"."""

    def test_dependency_edge_carries_no_version_and_answers_both_directions(self, api):
        """"For those five, **both ``updated_at`` and ``version`` are absent** from the
        resource entirely." The "``direction`` selector ... is ``OUTGOING`` when the
        change appears as the ``from_change_id`` of the edge and ``INCOMING`` when it
        appears as the ``to_change_id``".

        Design: Corner/entities/change_dependency_is_immutable_and_exposes_no_version_field
        """
        reset_clock(api)
        built = train_with_release(api)
        prerequisite = create_change(
            api,
            built["release"]["id"],
            title="Extract cache client",
            summary_internal="prerequisite",
            lines_changed=200,
            touched_subsystem_count=2,
            declared_blast_radius="SINGLE_TENANT",
        )
        dependent = create_change(
            api,
            built["release"]["id"],
            title="Adopt cache client",
            summary_internal="dependent",
            lines_changed=300,
            touched_subsystem_count=2,
            declared_blast_radius="SINGLE_TENANT",
        )
        submit_change(api, prerequisite["id"])
        submit_change(api, dependent["id"])

        edge = declare_dependency(
            api, dependent["id"], prerequisite["id"], note="library first"
        )

        assert_change_dependency(edge)
        outgoing, outgoing_meta = validate_paginated(
            api.list_dependencies(
                dependent["id"],
                CHANGE_APPROVER,
                {"direction": DependencyDirection.OUTGOING},
            )
        )
        assert outgoing_meta["total_count"] == 1
        assert outgoing[0]["id"] == edge["id"]
        assert outgoing[0]["from_change_id"] == dependent["id"]
        assert outgoing[0]["to_change_id"] == prerequisite["id"]
        assert outgoing[0]["note"] == "library first"
        assert "version" not in outgoing[0]
        assert "updated_at" not in outgoing[0]
        _, dependent_incoming_meta = validate_paginated(
            api.list_dependencies(
                dependent["id"],
                CHANGE_APPROVER,
                {"direction": DependencyDirection.INCOMING},
            )
        )
        assert dependent_incoming_meta["total_count"] == 0
        _, prerequisite_incoming_meta = validate_paginated(
            api.list_dependencies(
                prerequisite["id"],
                CHANGE_APPROVER,
                {"direction": DependencyDirection.INCOMING},
            )
        )
        assert prerequisite_incoming_meta["total_count"] == 1

    def test_flag_link_appears_on_both_sides_and_earns_the_whole_change_credit(
        self, api
    ):
        """"Links are many-to-many: one change may be guarded by several flags, and one
        flag may guard several changes." The flag credit "subtracts 15 points if at
        least one qualifying guard has ``guard_kind`` ``GATES_ENTIRE_CHANGE``".

        Design: Corner/entities/change_flag_link_is_visible_from_both_sides_of_the_junction
        """
        reset_clock(api)
        built = train_with_release(api)
        change = create_change(
            api,
            built["release"]["id"],
            title="Guarded path rewrite",
            summary_internal="Two-subsystem rewrite behind a flag",
            lines_changed=300,
            touched_subsystem_count=2,
            declared_blast_radius="SINGLE_TENANT",
        )
        flag = create_flag(api, ENGINEER, key="guarded-path")

        link = link_flag(
            api,
            change["id"],
            flag["id"],
            guard_kind=FlagLinkGuardKind.GATES_ENTIRE_CHANGE,
        )

        assert_change_flag_link(link)
        from_change_side, change_side_meta = validate_paginated(
            api.list_change_flag_links(change["id"], SRE)
        )
        from_flag_side, flag_side_meta = validate_paginated(
            api.list_flag_change_links(flag["id"], SRE)
        )
        assert change_side_meta["total_count"] == 1
        assert flag_side_meta["total_count"] == 1
        assert from_change_side[0]["id"] == link["id"]
        assert from_flag_side[0]["id"] == link["id"]
        for row in (from_change_side[0], from_flag_side[0]):
            assert row["change_request_id"] == change["id"]
            assert row["feature_flag_id"] == flag["id"]
            assert row["guard_kind"] == FlagLinkGuardKind.GATES_ENTIRE_CHANGE

        submitted = submit_change(api, change["id"])

        assert submitted["risk_score_preliminary"] == 18
        assert submitted["risk_class"] == RiskClass.LOW
        assert submitted["state"] == ChangeState.APPROVED
        assert submitted["risk_score_final"] == 18


class TestReferenceIntegrityAndMalformedBodies:
    """Path identifiers resolve before bodies, and bodies before business rules."""

    def test_each_entity_family_reports_its_own_not_found_identifier(self, api):
        """"Every identifier in the URL path resolves to an existing resource, checked
        left to right, reporting the first failure: ``ERR_RELEASE_TRAIN_NOT_FOUND``,
        ``ERR_RELEASE_NOT_FOUND``, ``ERR_CHANGE_REQUEST_NOT_FOUND``,
        ``ERR_FEATURE_FLAG_NOT_FOUND``, ``ERR_ROLLOUT_STEP_NOT_FOUND``,
        ``ERR_DEPLOYMENT_NOT_FOUND``".

        Design: Corner/entities/get_release_with_unknown_uuid_returns_release_not_found
        """
        reset_clock(api)

        probes = [
            (api.get_release(UNKNOWN_RELEASE_ID, RELEASE_MANAGER),
             ApiErrorId.ERR_RELEASE_NOT_FOUND),
            (api.get_release_train(UNKNOWN_TRAIN_ID, RELEASE_MANAGER),
             ApiErrorId.ERR_RELEASE_TRAIN_NOT_FOUND),
            (api.get_change_request(UNKNOWN_CHANGE_ID, ENGINEER),
             ApiErrorId.ERR_CHANGE_REQUEST_NOT_FOUND),
            (api.get_feature_flag(UNKNOWN_FLAG_ID, ENGINEER),
             ApiErrorId.ERR_FEATURE_FLAG_NOT_FOUND),
            (api.get_rollout_step(UNKNOWN_STEP_ID, ENGINEER),
             ApiErrorId.ERR_ROLLOUT_STEP_NOT_FOUND),
            (api.get_deployment(UNKNOWN_DEPLOYMENT_ID, SRE),
             ApiErrorId.ERR_DEPLOYMENT_NOT_FOUND),
        ]

        for response, expected in probes:
            validate_error(response, expected.value, 404)
            body = response.json()
            assert_envelope_shape(body, "error")
            assert "message" in body["data"]

    def test_unknown_parent_train_is_reported_before_the_body_is_examined(self, api):
        """"Where a path carries an identifier, that identifier is resolved before any
        body content is examined."

        Design: Corner/entities/create_release_under_unknown_release_train_returns_not_found
        """
        reset_clock(api)

        response = api.create_release(
            UNKNOWN_TRAIN_ID, make_release_payload(), RELEASE_MANAGER
        )

        validate_error(response, ApiErrorId.ERR_RELEASE_TRAIN_NOT_FOUND.value, 404)
        validate_error(
            api.get_release_train(UNKNOWN_TRAIN_ID, RELEASE_MANAGER),
            ApiErrorId.ERR_RELEASE_TRAIN_NOT_FOUND.value,
            404,
        )

    def test_missing_required_blast_radius_creates_no_change_request(self, api):
        """The body-shape rank requires that "every required input is present, every
        value has the declared type, every enum value is a member of its declared
        set", and the ladder applies "**no side effect whatsoever**".

        Design: Corner/entities/create_change_request_missing_required_blast_radius_returns_invalid_request
        """
        reset_clock(api)
        built = train_with_release(api)

        response = api.create_change_request(
            built["release"]["id"],
            make_change_request_payload(
                title="Missing blast radius",
                summary_internal="no blast radius declared",
                lines_changed=40,
                touched_subsystem_count=1,
                declared_blast_radius=...,
            ),
            ENGINEER,
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
        _, meta = validate_paginated(
            api.list_release_change_requests(built["release"]["id"], ENGINEER)
        )
        assert meta["total_count"] == 0
        assert read_release(api, built["release"]["id"])["committed_change_count"] == 0

    def test_enum_members_outside_their_declared_sets_are_malformed_requests(self, api):
        """A `strategy` must be one "of ``CANARY``, ``ALL_AT_ONCE`` or ``BLUE_GREEN``"
        and a `severity` one "of ``SEV1``, ``SEV2``, ``SEV3`` or ``SEV4``"; a member
        outside the declared set is ``ERR_INVALID_REQUEST``.

        Design: Corner/entities/create_deployment_with_invalid_enum_strategy_is_rejected
        """
        reset_clock(api)
        environment = create_environment(api)
        built = train_with_release(api)
        cut_release_at_freeze(api, built["release"]["id"])

        strategy_response = api.create_deployment(
            built["release"]["id"],
            make_deployment_payload(
                environment["id"],
                window_start_at="2026-08-10T02:00:00Z",
                window_end_at="2026-08-10T04:00:00Z",
                strategy="ROLLING",
            ),
            SRE,
        )
        severity_response = api.create_incident(
            make_incident_payload(
                built["train"]["id"],
                detected_at="2026-08-08T01:00:00Z",
                severity="SEV5",
                title="bad severity",
            ),
            SRE,
        )

        validate_error(strategy_response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
        validate_error(severity_response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
        _, deployment_meta = validate_paginated(
            api.list_deployments(SRE, {"release_id": built["release"]["id"]})
        )
        assert deployment_meta["total_count"] == 0
        _, incident_meta = validate_paginated(
            api.list_incidents(SRE, {"release_train_id": built["train"]["id"]})
        )
        assert incident_meta["total_count"] == 0


class TestDependencyGraphStaysAcyclic:
    """"the edge may not point a change at itself, the edge may not close a cycle"."""

    def test_self_edge_and_back_edge_are_both_refused_leaving_one_edge(self, api):
        """"Three structural rules apply, and all three report ``ERR_DEPENDENCY_CYCLE``:
        the edge may not point a change at itself, the edge may not close a cycle
        anywhere in the prerequisite graph, and both endpoints must belong to the
        same release."

        Design: Corner/entities/change_dependency_self_edge_and_back_edge_return_dependency_cycle
        """
        reset_clock(api)
        built = train_with_release(api)
        first = create_change(
            api,
            built["release"]["id"],
            title="First change",
            summary_internal="first",
            lines_changed=200,
            touched_subsystem_count=2,
            declared_blast_radius="SINGLE_TENANT",
        )
        second = create_change(
            api,
            built["release"]["id"],
            title="Second change",
            summary_internal="second",
            lines_changed=200,
            touched_subsystem_count=2,
            declared_blast_radius="SINGLE_TENANT",
        )
        submit_change(api, first["id"])
        submit_change(api, second["id"])
        edge = declare_dependency(api, first["id"], second["id"])

        self_edge = api.create_dependency(
            first["id"], {"to_change_id": first["id"]}, ENGINEER
        )
        back_edge = api.create_dependency(
            second["id"], {"to_change_id": first["id"]}, ENGINEER
        )

        validate_error(self_edge, ApiErrorId.ERR_DEPENDENCY_CYCLE.value, 409)
        validate_error(back_edge, ApiErrorId.ERR_DEPENDENCY_CYCLE.value, 409)
        first_outgoing, first_meta = validate_paginated(
            api.list_dependencies(
                first["id"], ENGINEER, {"direction": DependencyDirection.OUTGOING}
            )
        )
        assert first_meta["total_count"] == 1
        assert first_outgoing[0]["id"] == edge["id"]
        _, second_meta = validate_paginated(
            api.list_dependencies(
                second["id"], ENGINEER, {"direction": DependencyDirection.OUTGOING}
            )
        )
        assert second_meta["total_count"] == 0
        assert read_change(api, first["id"])["dependency_depth"] == 1
        assert read_change(api, second["id"])["dependency_depth"] == 0
