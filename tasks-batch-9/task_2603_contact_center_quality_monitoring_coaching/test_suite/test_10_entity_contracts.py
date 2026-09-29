"""Entity-level contract surface: the declared shape of a created row, the
computed fields a read must expose, the envelope and pagination rules, the
per-type not-found catalogue, and the defaults an omitted input materialises."""
from test_helpers import (
    ABSENT_UUID,
    ApiErrorId,
    assert_agent,
    assert_attainment,
    assert_calibration_submission,
    assert_evaluation_form,
    assert_evaluator,
    assert_evaluator_load,
    assert_form_behavior,
    assert_instant,
    assert_interaction,
    assert_money,
    assert_plan_counters,
    assert_scores,
    assert_system_fields,
    factories as f,
    fixtures as fx,
    ids_of,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

NOW = "2026-08-05T09:00:00Z"


class TestFormCreateShapeAndEnvelope:
    """One atomic authoring call must answer the standard envelope carrying
    every declared field of the new form."""

    def test_the_created_form_carries_the_envelope_and_its_computed_rollups(self, api):
        """201, meta, response_type and the two rollups in one answer.

        PRD: "A freshly created form is born in `DRAFT` with
        `behavior_weight_total` set to the sum of its behaviours' `weight_pct`
        values carried to two decimals, `compliance_behavior_count` set to the
        number of behaviours flagged compliance-critical, a form-level
        `guidance_version` of `1`, and both `activated_at` and `retired_at` null."
        PRD: "When `min_compliance_item_score` is omitted it defaults to `3`, and
        it may never be less than `1`."
        PRD: "The `api_request_id` is a server-generated unique identifier for the
        request that starts with `req_`."

        Design: Corner/entities/entity_form_create_returns_declared_shape_and_envelope
        """
        fx.set_clock(api, NOW)

        response = api.create_form(
            f.evaluation_form_payload(), fx.make_quality_manager_headers()
        )

        form = validate_success(response, 201)
        body = response.json()
        assert set(body.keys()) == {"meta", "response_type", "data"}
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert body["meta"]["api_request_timestamp"]
        assert_evaluation_form(form)
        assert form["status"] == "DRAFT"
        assert_money(form["behavior_weight_total"], 100.00)
        assert form["compliance_behavior_count"] == 1
        assert form["guidance_version"] == 1
        assert form["min_compliance_item_score"] == 3
        assert form["activated_at"] is None
        assert form["retired_at"] is None
        assert form["version"] == 1
        assert is_valid_uuid(form["id"])
        assert_instant(form["created_at"], NOW)
        assert_instant(form["updated_at"], NOW)

    def test_the_behaviour_children_are_born_with_their_own_declared_defaults(self, api):
        """Four rows, each with guidance_version one and the default ceiling.

        PRD: "The behaviours themselves arrive in the same payload as a
        `behaviors` array, and each element becomes a stored behaviour row whose
        `form_id` is the newly minted form."
        PRD: "Each stored behaviour is born with a per-behaviour
        `guidance_version` of `1`."

        Design: Corner/entities/entity_form_create_returns_declared_shape_and_envelope
        """
        fx.set_clock(api, NOW)
        form = fx.create_form(api)

        rows, meta = validate_paginated(
            api.list_form_behaviors(form["id"], fx.make_quality_manager_headers())
        )

        assert meta["total_count"] == 4
        assert sorted(row["code"] for row in rows) == [
            "DISCLOSE",
            "GREET",
            "RESOLVE",
            "SURVEY",
        ]
        for row in rows:
            assert_form_behavior(row)
            assert row["form_id"] == form["id"]
            assert row["guidance_version"] == 1
            assert row["max_points"] == 5


class TestInteractionReadExposesStoredAndComputedFields:
    """A read echoes every stored input and adds the derived duration without
    writing anything."""

    def test_the_read_returns_the_stored_inputs_and_the_derived_duration(self, api):
        """Ten minutes of contact becomes six hundred whole seconds.

        PRD: "From that interval the server computes `duration_seconds` as the
        number of whole seconds between the two instants, discarding any
        fractional remainder — this value later becomes the contact's weight in
        the duration-weighted quality index."
        PRD: "The server writes the remaining fields itself:
        `recording_consent_status` starts at `PENDING` for every channel including
        `EMAIL`, `captured_disclosures` starts as the empty array,
        `compliance_hold` starts `false`, and `sampled_count` starts at `0`."

        Design: Corner/entities/entity_interaction_get_returns_stored_and_computed_fields
        """
        fx.set_clock(api, NOW)
        agent = fx.create_agent(api)
        created = fx.create_interaction(
            api, agent["id"], required_disclosures=["RECORDING"], csat_score=4
        )

        interaction = validate_success(
            api.get_interaction(created["id"], fx.make_evaluator_headers("eve-reader"))
        )

        assert_interaction(interaction)
        assert interaction["agent_id"] == agent["id"]
        assert interaction["channel"] == "VOICE"
        assert_instant(interaction["started_at"], "2026-08-03T10:00:00Z")
        assert_instant(interaction["ended_at"], "2026-08-03T10:10:00Z")
        assert interaction["duration_seconds"] == 600
        assert interaction["required_disclosures"] == ["RECORDING"]
        assert interaction["captured_disclosures"] == []
        assert interaction["recording_consent_status"] == "PENDING"
        assert interaction["csat_score"] == 4
        assert interaction["repeat_contact_within_72h"] is False
        assert interaction["customer_flagged"] is False
        assert interaction["compliance_hold"] is False
        assert interaction["sampled_count"] == 0
        assert interaction["version"] == 1


class TestEvaluationListingPaginatesAndFilters:
    """The list envelope reports the filtered cardinality, not the table's."""

    @staticmethod
    def _one_submitted_and_one_draft(api):
        """Two evaluations on one evaluator, one scored and one still open."""
        env = fx.two_selection_env(
            api, per_agent_target_volume=4, mix=dict(f.ALL_RANDOM_MIX)
        )
        env.evaluation = fx.open_evaluation(
            api, env.selection["id"], env.evaluator["id"]
        )
        env.evaluation = fx.submit_evaluation(
            api, env.evaluation["id"], env.evaluator["id"], f.PASSING_ITEM_SCORES
        )
        env.evaluation2 = fx.open_evaluation(
            api, env.selection2["id"], env.evaluator["id"]
        )
        return env

    def test_the_defaults_hold_and_the_filter_owns_the_total_count(self, api):
        """Ten and zero by default; one page of one; one DRAFT row.

        PRD: "`limit` controls the page size: it defaults to `10`, may not be
        smaller than `1`, and may not be larger than `100`."
        PRD: "`total_count` is the number of rows matching the filters *before*
        the page window is applied, and `has_more` is true when rows remain beyond
        the current window."

        Design: Corner/entities/entity_evaluations_list_paginates_and_filters
        """
        env = self._one_submitted_and_one_draft(api)
        headers = fx.make_quality_manager_headers()

        rows, meta = validate_paginated(api.list_evaluations(headers))
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert set(ids_of(rows)) == {env.evaluation["id"], env.evaluation2["id"]}

        page, page_meta = validate_paginated(
            api.list_evaluations(headers, {"limit": 1, "offset": 0})
        )
        assert len(page) == 1
        assert page_meta["total_count"] == 2
        assert page_meta["has_more"] is True

        drafts, draft_meta = validate_paginated(
            api.list_evaluations(headers, {"review_status": "DRAFT"})
        )
        assert draft_meta["total_count"] == 1
        assert draft_meta["has_more"] is False
        assert ids_of(drafts) == [env.evaluation2["id"]]


class TestNotFoundCatalogueIsPerType:
    """Twelve routes, one absent identifier, twelve distinct error identifiers."""

    def test_each_path_id_answers_its_own_entity_not_found_error(self, api):
        """A single generic not-found identifier would fail all twelve at once.

        PRD: "Each miss returns HTTP 404 with the error identifying the *type*
        that could not be found: `ERR_FORM_NOT_FOUND`, `ERR_AGENT_NOT_FOUND`,
        `ERR_EVALUATOR_NOT_FOUND`, `ERR_INTERACTION_NOT_FOUND`,
        `ERR_SCAN_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_SELECTION_NOT_FOUND`,
        `ERR_EVALUATION_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`,
        `ERR_SUBMISSION_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND` or
        `ERR_COACHING_PLAN_NOT_FOUND`."
        PRD: "**Path existence** — every identifier in the path resolves, left to
        right, else the matching not-found error (HTTP 404)."

        Design: Corner/entities/entity_not_found_catalog_across_every_path_id
        """
        fx.set_clock(api, NOW)
        headers = fx.make_quality_manager_headers()
        probes = [
            (api.get_form, ApiErrorId.FORM_NOT_FOUND),
            (api.get_agent, ApiErrorId.AGENT_NOT_FOUND),
            (api.get_evaluator, ApiErrorId.EVALUATOR_NOT_FOUND),
            (api.get_interaction, ApiErrorId.INTERACTION_NOT_FOUND),
            (api.get_scan, ApiErrorId.SCAN_NOT_FOUND),
            (api.get_plan, ApiErrorId.PLAN_NOT_FOUND),
            (api.get_selection, ApiErrorId.SELECTION_NOT_FOUND),
            (api.get_evaluation, ApiErrorId.EVALUATION_NOT_FOUND),
            (api.get_session, ApiErrorId.SESSION_NOT_FOUND),
            (api.get_submission, ApiErrorId.SUBMISSION_NOT_FOUND),
            (api.get_dispute, ApiErrorId.DISPUTE_NOT_FOUND),
            (api.get_coaching_plan, ApiErrorId.COACHING_PLAN_NOT_FOUND),
        ]

        for reader, expected in probes:
            response = reader(ABSENT_UUID, headers)
            validate_error(response, expected.value, 404)
            body = response.json()
            assert body["response_type"] == "error"
            assert set(body["data"].keys()) == {"error_id", "message"}

    def test_the_error_envelope_carries_only_the_two_meta_fields(self, api):
        """An error answer is not a list answer wearing a 404.

        PRD: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/entities/entity_not_found_catalog_across_every_path_id
        """
        fx.set_clock(api, NOW)

        response = api.get_plan(ABSENT_UUID, fx.make_quality_manager_headers())

        validate_error(response, ApiErrorId.PLAN_NOT_FOUND.value, 404)
        meta = response.json()["meta"]
        assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}


class TestRequiredFieldOmissionsOutrankBusinessRules:
    """Stage three of the ladder answers before any state or history rule."""

    def test_a_missing_required_input_answers_four_hundred_not_the_state_error(self, api):
        """The plan names a DRAFT form and still answers on request shape.

        PRD: "**Request shape** — on every write endpoint: the body parses, every
        required input field is present and non-null, every field carries its
        declared JSON type, every enum-typed field carries a declared member,
        integers are integers, decimals carry at most two fractional digits,
        datetimes are RFC 3339 UTC with a trailing `Z`, and every declared numeric
        range holds (`weight_pct` from `0.01` to `100.00`, `silence_pct` from
        `0.00` to `100.00`, `sentiment_delta` from `-1.00` to `1.00`, `csat_score`
        from `1` to `5`, `max_points` one of `3`, `4` or `5`,
        `per_agent_target_volume` from `1` to `50`, `target_score` above `0.00`
        and at most `100.00`, recognition `points` from `1` to `500`)."
        PRD: "When a request violates more than one rule, exactly one error is
        returned, and which one is fixed by the following precedence ladder."

        Design: Corner/entities/entity_required_field_omissions_rejected_before_business_rules
        """
        fx.set_clock(api, NOW)
        form = fx.create_form(api)
        agent = fx.create_agent(api)
        headers = fx.make_quality_manager_headers()

        plan_body = f.sample_plan_payload(form["id"], mix=f.source_mix())
        plan_body.pop("per_agent_target_volume")
        validate_error(
            api.create_plan(plan_body, headers), ApiErrorId.INVALID_REQUEST.value, 400
        )

        interaction_body = f.interaction_payload(agent["id"])
        interaction_body.pop("ended_at")
        validate_error(
            api.create_interaction(interaction_body, headers),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

        coaching_body = f.coaching_plan_payload(
            agent["id"], ABSENT_UUID, agent["version"], target_score=90.00
        )
        coaching_body.pop("source_evaluation_id")
        validate_error(
            api.create_coaching_plan(coaching_body, fx.make_supervisor_headers()),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

    def test_none_of_the_rejected_writes_left_a_row_behind(self, api):
        """A four hundred persists nothing at all.

        PRD: "Only after every applicable stage passes does the operation apply
        its side effects."

        Design: Corner/entities/entity_required_field_omissions_rejected_before_business_rules
        """
        fx.set_clock(api, NOW)
        form = fx.create_form(api)
        headers = fx.make_quality_manager_headers()
        plan_body = f.sample_plan_payload(form["id"], mix=f.source_mix())
        plan_body.pop("per_agent_target_volume")

        validate_error(
            api.create_plan(plan_body, headers), ApiErrorId.INVALID_REQUEST.value, 400
        )

        _, plan_meta = validate_paginated(api.list_plans(headers))
        assert plan_meta["total_count"] == 0
        _, coaching_meta = validate_paginated(api.list_coaching_plans(headers))
        assert coaching_meta["total_count"] == 0


class TestDeclaredDefaultsMaterialiseOnOmission:
    """An omitted optional input becomes its declared default, never null."""

    def test_an_evaluator_created_with_only_a_name_lands_on_every_default(self, api):
        """Three concurrent assignments, calibrated standing, no deviation yet.

        PRD: "An evaluator carries a `full_name` and an optional
        `max_open_assignments` capping how many selections they may hold
        concurrently in the assigned state; it defaults to `3` and must be at
        least `1` and at most `20`."
        PRD: "A new evaluator begins with `calibration_status` at `CALIBRATED`,
        `open_assignment_count` at `0`, and `last_deviation_pct` null."

        Design: Corner/entities/entity_declared_defaults_applied_on_omission
        """
        fx.set_clock(api, NOW)

        evaluator = validate_success(
            api.create_evaluator(
                {"full_name": "Eve Evaluator"}, fx.make_quality_manager_headers()
            ),
            201,
        )

        assert_evaluator(evaluator)
        assert evaluator["max_open_assignments"] == 3
        assert evaluator["calibration_status"] == "CALIBRATED"
        assert_evaluator_load(evaluator, 0)
        assert evaluator["last_deviation_pct"] is None
        assert evaluator["version"] == 1

    def test_a_bare_interaction_and_a_bare_agent_land_on_their_defaults(self, api):
        """Five minutes of email, empty arrays, a null satisfaction rating.

        PRD: "`required_disclosures` is an array of disclosure codes the channel
        or jurisdiction demands on this contact, drawn from `RECORDING`,
        `MINI_MIRANDA`, `RATE_CHANGE` and `THIRD_PARTY`, and defaults to the empty
        array; `customer_flagged` (default `false`) records that the customer
        asked for the contact to be reviewed; `csat_score` is the post-contact
        satisfaction rating, an integer from `1` to `5`, and is null when the
        customer did not respond; and `repeat_contact_within_72h` (default
        `false`) records that the same customer came back inside three days."
        PRD: "A new agent starts with `quality_index_rolling` and
        `quality_index_period` both null, `open_compliance_findings` at `0`,
        `consecutive_passing_evaluations` at `0`, `coaching_state` at `NONE`, and
        `recognition_points` at `0`."

        Design: Corner/entities/entity_declared_defaults_applied_on_omission
        """
        fx.set_clock(api, NOW)
        agent = fx.create_agent(api)

        interaction = validate_success(
            api.create_interaction(
                {
                    "agent_id": agent["id"],
                    "channel": "EMAIL",
                    "started_at": "2026-08-04T08:00:00Z",
                    "ended_at": "2026-08-04T08:05:00Z",
                },
                fx.make_quality_manager_headers(),
            ),
            201,
        )

        assert_interaction(interaction)
        assert interaction["required_disclosures"] == []
        assert interaction["captured_disclosures"] == []
        assert interaction["customer_flagged"] is False
        assert interaction["csat_score"] is None
        assert interaction["repeat_contact_within_72h"] is False
        assert interaction["recording_consent_status"] == "PENDING"
        assert interaction["compliance_hold"] is False
        assert interaction["sampled_count"] == 0
        assert interaction["duration_seconds"] == 300

        assert_agent(agent)
        assert agent["quality_index_rolling"] is None
        assert agent["quality_index_period"] is None
        assert agent["open_compliance_findings"] == 0
        assert agent["consecutive_passing_evaluations"] == 0
        assert agent["coaching_state"] == "NONE"
        assert agent["recognition_points"] == 0


class TestOneSubmitLeavesFourEntitiesConsistent:
    """The scoring event is not a single-row write: it lands on the plan, the
    interaction, the evaluator and the agent at once."""

    def test_the_submit_recomputes_every_dependent_entitys_rollups(self, api):
        """Four entities read consistently off one call.

        PRD: "**Step three:** the underlying selection moves `ASSIGNED →
        EVALUATED` and the evaluator's `open_assignment_count` is recomputed
        downward, releasing capacity."
        PRD: "`sampled_count` is always the number of selections referencing this
        interaction whose status is `SELECTED`, `ASSIGNED` or `EVALUATED`."
        PRD: "**Step four:** the agent's `quality_index_rolling` and
        `quality_index_period` are recomputed as described in §3.9, and
        `consecutive_passing_evaluations` is recomputed."

        Design: Corner/entities/entity_computed_rollups_recomputed_across_four_entities
        """
        env = fx.draft_evaluation_env(api)

        evaluation = validate_success(
            api.submit_evaluation(
                env.evaluation["id"],
                f.submit_payload(f.PASSING_ITEM_SCORES),
                fx.make_evaluator_headers(env.evaluator["id"]),
            )
        )

        assert_scores(
            evaluation,
            weighted_score=82.00,
            raw_weighted_score=82.00,
            adjusted_weighted_score=None,
            auto_fail_triggered=False,
            compliance_result="PASS",
        )
        assert evaluation["review_status"] == "SUBMITTED"
        assert evaluation["feedback_status"] == "PENDING"
        assert_instant(evaluation["submitted_at"], "2026-08-05T09:00:00Z")

        plan = fx.read_plan(api, env.plan["id"])
        assert_plan_counters(
            plan, selections_count=1, excluded_count=0, targeted_reserved_count=0
        )
        assert_attainment(
            plan,
            env.agent["id"],
            consumed=1,
            remaining=3,
            by_source={"RANDOM": 1, "TARGETED": 0, "CUSTOMER_FLAGGED": 0},
        )
        interaction = fx.read_interaction(api, env.interaction["id"])
        assert interaction["sampled_count"] == 1
        assert interaction["compliance_hold"] is False
        assert_evaluator_load(fx.read_evaluator(api, env.evaluator["id"]), 0)
        agent = fx.read_agent(api, env.agent["id"])
        assert_money(agent["quality_index_rolling"], 82.00)
        assert_money(agent["quality_index_period"], 82.00)
        assert agent["open_compliance_findings"] == 0
        assert agent["coaching_state"] == "NONE"

    def test_a_passing_score_below_the_high_floor_leaves_the_streak_at_zero(self, api):
        """Eighty-two points pass the compliance verdict but break the run.

        PRD: "It is the length of the trailing run of the agent's evaluations,
        ordered by `submitted_at` ascending with `created_at` ascending as the
        tie-break, whose `compliance_result` is `PASS` and whose effective score is
        at least `85.00`; any evaluation with a `FAIL` verdict or a score below
        `85.00` resets it to `0`."

        Design: Corner/entities/entity_computed_rollups_recomputed_across_four_entities
        """
        env = fx.draft_evaluation_env(api)

        validate_success(
            api.submit_evaluation(
                env.evaluation["id"],
                f.submit_payload(f.PASSING_ITEM_SCORES),
                fx.make_evaluator_headers(env.evaluator["id"]),
            )
        )

        agent = fx.read_agent(api, env.agent["id"])
        assert agent["consecutive_passing_evaluations"] == 0


class TestSystemFieldsAreServerOwnedAcrossTheLifecycle:
    """Two writes, one read, and a version that counts only the writes."""

    def test_activation_and_retirement_each_stamp_once_and_bump_once(self, api):
        """One to two to three, with created_at frozen throughout.

        PRD: "`version` (integer): an integer that starts at `1` on creation and
        increments by exactly one on every mutation of the row, including mutations
        caused by a cascade the client did not directly request."
        PRD: "Activation stamps `activated_at` with the current logical-clock
        instant, sets the status, and increments the form's `version`."
        PRD: "Retirement moves an `ACTIVE` form to `RETIRED`, stamps `retired_at`
        with the current logical-clock instant, and increments `version`;
        attempting it on a form that is not `ACTIVE` answers
        `ERR_FORM_NOT_ACTIVE`."

        Design: Corner/entities/entity_system_fields_owned_by_server_across_lifecycle
        """
        fx.set_clock(api, NOW)
        created = fx.create_form(api)
        assert created["version"] == 1

        fx.set_clock(api, "2026-08-06T12:00:00Z")
        activated = fx.activate_form(api, created["id"])
        assert activated["version"] == 2
        assert activated["status"] == "ACTIVE"
        assert_instant(activated["activated_at"], "2026-08-06T12:00:00Z")
        assert activated["retired_at"] is None
        assert_instant(activated["updated_at"], "2026-08-06T12:00:00Z")
        assert_instant(activated["created_at"], NOW)

        read_back = fx.read_form(api, created["id"])
        assert read_back["version"] == 2
        assert_instant(read_back["updated_at"], "2026-08-06T12:00:00Z")

        fx.set_clock(api, "2026-08-07T08:30:00Z")
        retired = fx.retire_form(api, created["id"])
        assert retired["version"] == 3
        assert retired["status"] == "RETIRED"
        assert_instant(retired["retired_at"], "2026-08-07T08:30:00Z")
        assert_instant(retired["activated_at"], "2026-08-06T12:00:00Z")
        assert retired["id"] == created["id"]
        assert is_valid_uuid(retired["id"])


class TestTypeConstraintsSplitAcrossTwoStatuses:
    """An enum or range violation is a four hundred; a degenerate interval is a
    four twenty-two."""

    def test_enum_range_and_scale_violations_all_answer_four_hundred(self, api):
        """An unknown channel, a sixth satisfaction point, a sixth scale point.

        PRD: "`max_points` (default `5`, and restricted to `3`, `4` or `5`) sets
        the scale ceiling for the behaviour"
        PRD: "A value outside those bounds, or a non-integer value, is a malformed
        request and is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/entity_type_constraints_reject_enum_range_and_interval_violations
        """
        fx.set_clock(api, NOW)
        agent = fx.create_agent(api)
        headers = fx.make_quality_manager_headers()

        validate_error(
            api.create_interaction(
                f.interaction_payload(agent["id"], channel="FAX"), headers
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )
        validate_error(
            api.create_interaction(
                f.interaction_payload(agent["id"], csat_score=6), headers
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )
        validate_error(
            api.create_form(
                f.evaluation_form_payload(
                    auto_fail_policy="ZERO_TOTAL",
                    behaviors=[
                        f.behavior_payload(
                            "DISCLOSE",
                            100.00,
                            compliance_critical=True,
                            auto_fail_on_violation=True,
                            max_points=6,
                            allows_not_applicable=False,
                        )
                    ],
                ),
                headers,
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

    def test_an_empty_interval_answers_the_temporal_error_and_persists_nothing(self, api):
        """Equal endpoints are not a shape problem; they are a time problem.

        PRD: "The payload names the handling agent through `agent_id`, declares
        the `channel` as `VOICE`, `CHAT` or `EMAIL`, and supplies `started_at` and
        `ended_at` as ISO 8601 UTC instants; `ended_at` must be strictly after
        `started_at`, or the request is rejected with `ERR_INVALID_TIME_RANGE`."

        Design: Corner/entities/entity_type_constraints_reject_enum_range_and_interval_violations
        """
        fx.set_clock(api, NOW)
        agent = fx.create_agent(api)
        headers = fx.make_quality_manager_headers()

        validate_error(
            api.create_interaction(
                f.interaction_payload(
                    agent["id"],
                    started_at="2026-08-03T10:00:00Z",
                    ended_at="2026-08-03T10:00:00Z",
                ),
                headers,
            ),
            ApiErrorId.INVALID_TIME_RANGE.value,
            422,
        )

        _, interaction_meta = validate_paginated(api.list_interactions(headers))
        assert interaction_meta["total_count"] == 0
        _, form_meta = validate_paginated(api.list_forms(headers))
        assert form_meta["total_count"] == 0


class TestCalibrationSubmissionIsImmutableAndVersionless:
    """The one entity outside the common-field contract."""

    def test_the_submission_carries_no_version_and_no_deviation_until_close(self, api):
        """A record of what an evaluator said, not a row to be rewritten.

        PRD: "A calibration submission is immutable once written: it carries only
        `id` and `created_at`, and both `updated_at` and `version` are absent from
        its representation."
        PRD: "The stored row takes `evaluator_id` from the acting `X-User-ID` and
        `weighted_score` from the renormalised weighted score of the submitted map
        against the session's form; `deviation_pct` and `alignment` are
        deliberately left null until the session closes, because a deviation only
        means something once the session is settled."

        Design: Corner/entities/entity_calibration_submission_is_immutable_and_versionless
        """
        fx.set_clock(api, NOW)
        form = fx.create_active_form(api)
        agent = fx.create_agent(api)
        interaction = fx.create_verified_interaction(api, agent["id"])
        evaluator = fx.create_evaluator(api)
        session = fx.create_session(api, form["id"], interaction["id"])
        fx.start_scoring(api, session["id"])

        submission = fx.create_submission(
            api, session["id"], evaluator["id"], f.HIGH_ITEM_SCORES_86
        )

        assert_calibration_submission(submission)
        assert submission["session_id"] == session["id"]
        assert submission["evaluator_id"] == evaluator["id"]
        # 30.00 + 20.00 + 21.00 + 15.00 = 86.00 over a full denominator.
        assert_money(submission["weighted_score"], 86.00)
        assert submission["deviation_pct"] is None
        assert submission["alignment"] is None

        read_back = fx.read_submission(api, submission["id"])
        assert "version" not in read_back
        assert "updated_at" not in read_back
        assert_system_fields(read_back, versioned=False)

    def test_the_parent_session_records_the_participant_but_not_the_variance(self, api):
        """Creating a reading counts it and leaves the settlement figures null.

        PRD: "Creating one recomputes the session's `participant_count` and
        increments the session's `version`."
        PRD: "That figure is fixed at creation and is never re-derived when the
        session closes, so a later guidance rewrite cannot move the reference every
        participant was measured against."

        Design: Corner/entities/entity_calibration_submission_is_immutable_and_versionless
        """
        fx.set_clock(api, NOW)
        form = fx.create_active_form(api)
        agent = fx.create_agent(api)
        interaction = fx.create_verified_interaction(api, agent["id"])
        evaluator = fx.create_evaluator(api)
        session = fx.create_session(api, form["id"], interaction["id"])
        fx.start_scoring(api, session["id"])

        fx.create_submission(api, session["id"], evaluator["id"], f.HIGH_ITEM_SCORES_86)

        settled = fx.read_session(api, session["id"])
        assert_money(settled["benchmark_weighted_score"], 82.00)
        assert settled["participant_count"] == 1
        assert settled["variance_pct"] is None
        assert settled["mean_abs_deviation"] is None


class TestChildRoutesRequireTheNamedParent:
    """The behaviour listing resolves its parent before it lists anything."""

    def test_an_absent_parent_is_a_not_found_rather_than_an_empty_page(self, api):
        """No parent, no listing.

        PRD: "Because behaviour rows are created as a cascade of form creation and
        are never addressable by their own creation call, the behaviour listing of a
        form is the only discovery channel for them; it is paginated with `limit`
        and `offset` and ordered by `code` ascending."
        PRD: "**Path existence** — every identifier in the path resolves, left to
        right, else the matching not-found error (HTTP 404)."

        Design: Corner/entities/entity_child_routes_require_the_named_parent
        """
        fx.set_clock(api, NOW)
        fx.create_form(api)

        response = api.list_form_behaviors(
            ABSENT_UUID, fx.make_quality_manager_headers()
        )

        validate_error(response, ApiErrorId.FORM_NOT_FOUND.value, 404)

    def test_each_parents_listing_returns_only_its_own_children(self, api):
        """Four behaviours on one scorecard, one on the other, no leakage.

        PRD: "The behaviours themselves arrive in the same payload as a
        `behaviors` array, and each element becomes a stored behaviour row whose
        `form_id` is the newly minted form."
        PRD: "A freshly created form is born in `DRAFT` with
        `behavior_weight_total` set to the sum of its behaviours' `weight_pct`
        values carried to two decimals, `compliance_behavior_count` set to the
        number of behaviours flagged compliance-critical, a form-level
        `guidance_version` of `1`, and both `activated_at` and `retired_at` null."

        Design: Corner/entities/entity_child_routes_require_the_named_parent
        """
        fx.set_clock(api, NOW)
        headers = fx.make_quality_manager_headers()
        first = fx.create_form(api)
        second = fx.create_form(
            api,
            behaviors=[
                f.behavior_payload(
                    "MINI_MIRANDA",
                    100.00,
                    label="Mini Miranda",
                    compliance_critical=True,
                )
            ],
        )

        first_rows, first_meta = validate_paginated(
            api.list_form_behaviors(first["id"], headers)
        )
        second_rows, second_meta = validate_paginated(
            api.list_form_behaviors(second["id"], headers)
        )

        assert first_meta["total_count"] == 4
        assert {row["code"] for row in first_rows} == {
            "DISCLOSE",
            "GREET",
            "RESOLVE",
            "SURVEY",
        }
        assert all(row["form_id"] == first["id"] for row in first_rows)
        assert all(row["guidance_version"] == 1 for row in first_rows)
        assert second_meta["total_count"] == 1
        assert second_rows[0]["code"] == "MINI_MIRANDA"
        assert second_rows[0]["form_id"] == second["id"]
        assert_money(second["behavior_weight_total"], 100.00)
        assert second["compliance_behavior_count"] == 1


class TestBodyForeignKeysAreResolvedPerEndpointInDeclarationOrder:
    """A flat topology means the not-found answers come from the body."""

    def test_each_absent_body_reference_answers_its_own_type(self, api):
        """Five bodies, five different four-oh-fours, no state error among them.

        PRD: "Identifier resolution is strictly ordered, and the first
        unresolvable identifier decides the answer. Identifiers appearing in the
        request **path** are resolved first, left to right; only then are foreign
        keys in the request **body** resolved, in the order the endpoint's input
        list declares them."
        PRD: "**Body reference existence** — every foreign key in the body
        resolves, in declaration order, else the matching not-found error (HTTP
        404)."

        Design: Corner/entities/entity_topology_body_fk_ids_validated_per_endpoint
        """
        env = fx.program_env(api)
        headers = fx.make_quality_manager_headers()

        validate_error(
            api.create_plan(
                f.sample_plan_payload(
                    ABSENT_UUID,
                    period_start="2026-09-01T00:00:00Z",
                    period_end="2026-09-30T23:59:59Z",
                ),
                headers,
            ),
            ApiErrorId.FORM_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.create_selection(
                f.sample_selection_payload(ABSENT_UUID, env.interaction["id"]), headers
            ),
            ApiErrorId.PLAN_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.create_selection(
                f.sample_selection_payload(env.plan["id"], ABSENT_UUID), headers
            ),
            ApiErrorId.INTERACTION_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.create_evaluation(
                f.evaluation_payload(ABSENT_UUID),
                fx.make_evaluator_headers(env.evaluator["id"]),
            ),
            ApiErrorId.SELECTION_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.create_submission(
                f.calibration_submission_payload(ABSENT_UUID, f.PASSING_ITEM_SCORES),
                fx.make_evaluator_headers(env.evaluator["id"]),
            ),
            ApiErrorId.SESSION_NOT_FOUND.value,
            404,
        )

    def test_the_rejected_bodies_left_the_graph_untouched(self, api):
        """No half-written child anywhere.

        PRD: "Creating a sampling plan therefore resolves `form_id`; creating a
        selection resolves `plan_id` and then `interaction_id`; creating a coaching
        plan resolves `agent_id` and then `source_evaluation_id`; creating an
        analytics scan resolves `interaction_id`; creating an evaluation resolves
        `selection_id`; assigning a selection resolves the path selection and then
        the body's `assigned_evaluator_id`; creating a calibration session resolves
        `form_id` and then `interaction_id`; creating a calibration submission
        resolves `session_id`; filing a dispute resolves `evaluation_id`."

        Design: Corner/entities/entity_topology_body_fk_ids_validated_per_endpoint
        """
        env = fx.program_env(api)
        headers = fx.make_quality_manager_headers()

        validate_error(
            api.create_selection(
                f.sample_selection_payload(env.plan["id"], ABSENT_UUID), headers
            ),
            ApiErrorId.INTERACTION_NOT_FOUND.value,
            404,
        )

        plan = fx.read_plan(api, env.plan["id"])
        assert_plan_counters(plan, selections_count=0, excluded_count=0)
        assert plan["agent_volume_attainment"] == {}
        _, meta = validate_paginated(api.list_selections(headers))
        assert meta["total_count"] == 0
