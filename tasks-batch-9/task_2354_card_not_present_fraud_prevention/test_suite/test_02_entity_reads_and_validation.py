"""Roster reads, request-shape rejection and the immutability of a fraud rule."""

from __future__ import annotations

from test_helpers import (
    ADMIN,
    CHECKOUT,
    ENGINEER,
    ApiClient,
    ApiErrorId,
    AssessmentState,
    Decision,
    NON_EXISTENT_UUID,
    PROB_DECLINE_EXACTLY_AT_DECLINE_FLOOR,
    RuleCode,
    STANDARD_ORDER_CENTS,
    Seniority,
    SignalFamily,
    assert_created_at_ascending,
    assert_fraud_rule,
    build_approved_assessment,
    build_scoring_env,
    create_analyst,
    create_assessment_payload,
    create_customer,
    create_address,
    create_rule_payload,
    draft_rule_pack,
    get_success_data,
    open_and_score,
    open_assessment,
    read_rule_pack,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

#: A window whose end equals its start, which the strict inequality rejects.
ZERO_LENGTH_WINDOW_INSTANT = "2026-07-01T00:00:00Z"


class TestAnalystRosterListing:
    """Roster pages report the whole filtered set, not the page."""

    def test_paging_the_roster_reports_total_count_and_has_more(
        self, api: ApiClient
    ) -> None:
        """Three analysts across two pages of two: 2 rows then 1, total_count 3 both times.

        PRD: "Every list response repeats `limit` and `offset` in the envelope's `meta`
        object alongside `total_count` (the number of rows matching the filters before
        pagination) and `has_more` (true when rows remain beyond the current window)."
        PRD: "Unless a specific collection says otherwise, list results are ordered by
        `created_at` ascending."

        Design: Corner/entities/analyst_listing_paginates_with_total_count_and_has_more
        """
        set_clock(api)
        junior = create_analyst(
            api,
            display_name="AN1 Junior",
            seniority=Seniority.JUNIOR,
            skill_families=[SignalFamily.BEHAVIORAL],
            shift_capacity_cases=2,
        )
        create_analyst(
            api,
            display_name="AN2 Senior",
            seniority=Seniority.SENIOR,
            skill_families=[SignalFamily.DEVICE],
            shift_capacity_cases=2,
        )
        lead = create_analyst(
            api,
            display_name="LEAD1",
            seniority=Seniority.LEAD,
            skill_families=[SignalFamily.BEHAVIORAL],
            shift_capacity_cases=3,
        )

        first_rows, first_meta = validate_paginated(
            api.list_analysts(ADMIN, params={"limit": 2, "offset": 0})
        )
        assert len(first_rows) == 2
        assert first_meta["total_count"] == 3, (
            "total_count counts the whole filtered set, not the page"
        )
        assert first_meta["has_more"] is True
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert first_rows[0]["id"] == junior["id"], (
            "the roster is ordered by created_at ascending"
        )
        assert_created_at_ascending(first_rows)

        second_rows, second_meta = validate_paginated(
            api.list_analysts(ADMIN, params={"limit": 2, "offset": 2})
        )
        assert len(second_rows) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False, (
            "no rows remain beyond the second window"
        )
        assert second_meta["offset"] == 2
        assert second_rows[0]["id"] == lead["id"]

        _default_rows, default_meta = validate_paginated(api.list_analysts(ADMIN))
        assert default_meta["limit"] == 10, "limit defaults to 10"
        assert default_meta["offset"] == 0, "offset defaults to 0"

        filtered_rows, filtered_meta = validate_paginated(
            api.list_analysts(ADMIN, params={"seniority": Seniority.LEAD})
        )
        assert filtered_meta["total_count"] == 1, (
            "analysts filter on status and seniority"
        )
        assert filtered_rows[0]["id"] == lead["id"]


class TestRequestShapeRejection:
    """Shape checks precede the referential and eligibility work behind them."""

    def test_an_assessment_without_amount_cents_is_a_validation_error(
        self, api: ApiClient
    ) -> None:
        """The missing required field is reported even though no pack exists to pin.

        PRD: "3. **Request shape** — required fields present and non-null, then JSON
        types and enum membership (an unrecognised `action` value is an enum
        violation), then the fixed-format string checks, then numeric range checks,
        then the skill-family array check, then list pagination bounds, then
        clock-format."
        PRD: "Validation is a single ordered ladder, not a set of independent checks.
        The **first** violated rule decides the response, and no later rule is
        evaluated."

        Design: Corner/entities/assessment_missing_required_amount_cents_rejected
        """
        set_clock(api)
        customer = create_customer(api, email="shape@example.com", home_country="US")
        device = get_success_data(
            api.create_device(
                {"device_hash": "dev-shape-001", "tz_offset_minutes": -480}, CHECKOUT
            )
        )
        address = create_address(
            api, line1="100 Main St", postal_code="94105", country_code="US"
        )

        payload = create_assessment_payload(
            customer["id"], device["id"], address["id"]
        )
        payload.pop("amount_cents")
        response = api.create_assessment(payload, CHECKOUT)
        validate_error(response, ApiErrorId.ERR_VALIDATION, 422)
        assert response.json()["data"]["error_id"] != (
            ApiErrorId.ERR_NO_ACTIVE_RULE_PACK
        ), "the shape band is reached before anything is pinned"

        _rows, meta = validate_paginated(
            api.list_assessments(CHECKOUT, params={"customer_id": customer["id"]})
        )
        assert meta["total_count"] == 0, "a rejected create persists nothing"

    def test_analyst_constraints_are_each_enforced_and_persist_nothing(
        self, api: ApiClient
    ) -> None:
        """Seniority outside the enum, a zero capacity and an empty skill array all fail.

        PRD: "A platform administrator registers an analyst with a `display_name`, a
        `seniority` of `JUNIOR`, `SENIOR` or `LEAD`, a non-empty `skill_families` array
        drawn from `DEVICE`, `BEHAVIORAL`, `VELOCITY`, `IDENTITY`, `ADDRESS`, `PROMO`
        and `MODEL`, and a `shift_capacity_cases` of at least 1 giving the maximum
        number of cases the analyst may hold simultaneously."
        PRD: "An empty `skill_families` array, or one containing a value outside that
        enumeration, is `ERR_VALIDATION`."

        Design: Corner/entities/analyst_seniority_outside_enum_rejected
        """
        set_clock(api)
        for payload in (
            {
                "display_name": "Bad Seniority",
                "seniority": "PRINCIPAL",
                "skill_families": [SignalFamily.BEHAVIORAL],
                "shift_capacity_cases": 2,
            },
            {
                "display_name": "Zero Capacity",
                "seniority": Seniority.JUNIOR,
                "skill_families": [SignalFamily.BEHAVIORAL],
                "shift_capacity_cases": 0,
            },
            {
                "display_name": "Empty Skills",
                "seniority": Seniority.JUNIOR,
                "skill_families": [],
                "shift_capacity_cases": 2,
            },
        ):
            validate_error(
                api.create_analyst(payload, ADMIN), ApiErrorId.ERR_VALIDATION, 422
            )

        _rows, meta = validate_paginated(api.list_analysts(ADMIN))
        assert meta["total_count"] == 0, "not one of the three rejected rows persisted"

    def test_a_rule_pack_window_whose_end_equals_its_start_is_rejected(
        self, api: ApiClient
    ) -> None:
        """The window inequality is strict, and it bites at drafting time.

        PRD: "`effective_until` must be strictly after `effective_from`, or the draft
        is rejected with `ERR_INVALID_WINDOW`."
        PRD: "Three consistency rules are checked at drafting time and again at
        activation time."

        Design: Corner/entities/rule_pack_window_with_until_equal_to_from_rejected
        """
        set_clock(api)
        response = api.create_rule_pack(
            {
                "version_label": "P-zero-window",
                "blend_mode": "WEIGHTED",
                "rule_weight": 0.40,
                "model_weight": 0.60,
                "review_floor_score": 40.00,
                "decline_floor_score": 60.00,
                "effective_from": ZERO_LENGTH_WINDOW_INSTANT,
                "effective_until": ZERO_LENGTH_WINDOW_INSTANT,
            },
            ENGINEER,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_WINDOW, 422)

        _rows, meta = validate_paginated(api.list_rule_packs(ENGINEER))
        assert meta["total_count"] == 0, "the rejected draft was never stored"


class TestFraudRuleImmutability:
    """A fraud rule has no version and no updated_at, and nothing mutates it."""

    def test_a_stored_rule_exposes_no_version_and_no_updated_at(
        self, api: ApiClient
    ) -> None:
        """The rule reads back through both of its documented paths, versionless.

        PRD: "Every entity in this system carries all four **except `FraudRule`**,
        which is immutable once written: a fraud rule has only `id` and `created_at`,
        and both `updated_at` and `version` are absent from it entirely. There is no
        endpoint that mutates a fraud rule."
        PRD: "Each accepted rule increments the pack's `rule_count` by one."

        Design: Corner/entities/fraud_rule_is_immutable_with_no_version_or_update_endpoint
        """
        set_clock(api)
        pack = draft_rule_pack(api, version_label="P-immutable")
        created = validate_success(
            api.create_rule(
                pack["id"],
                create_rule_payload(
                    RuleCode.BEH_FAST_CHECKOUT, points=20, evaluation_order=10
                ),
                ENGINEER,
            ),
            201,
        )
        assert_fraud_rule(created)

        rows, meta = validate_paginated(api.list_rules(pack["id"], ENGINEER))
        assert meta["total_count"] == 1
        listed = rows[0]
        assert_fraud_rule(listed)
        assert listed["code"] == RuleCode.BEH_FAST_CHECKOUT
        assert listed["signal_family"] == SignalFamily.BEHAVIORAL
        assert listed["points"] == 20
        assert listed["evaluation_order"] == 10
        assert listed["hard_decline"] is False
        assert listed["rule_pack_id"] == pack["id"]

        direct = get_success_data(api.get_rule(listed["id"], ENGINEER))
        assert_fraud_rule(direct)
        assert direct["id"] == listed["id"]

        assert read_rule_pack(api, pack["id"])["rule_count"] == 1


class TestPathAndForeignKeyResolution:
    """Identifiers resolve left to right, and each names its own not-found code."""

    def test_adding_a_rule_to_an_unknown_pack_reports_the_pack_not_the_body(
        self, api: ApiClient
    ) -> None:
        """The parent identifier in the path decides the response before the body.

        PRD: "A request for the rules of a rule pack that does not exist reports
        `ERR_RULE_PACK_NOT_FOUND` before any rule, filter or body field is considered —
        and that holds equally for adding a rule to the pack, listing the pack's rules,
        and reading the pack's performance report."

        Design: Corner/entities/rule_creation_under_unknown_rule_pack_returns_404
        """
        set_clock(api)
        response = api.create_rule(
            NON_EXISTENT_UUID,
            create_rule_payload(
                RuleCode.BEH_FAST_CHECKOUT, points=20, evaluation_order=10
            ),
            ENGINEER,
        )
        validate_error(response, ApiErrorId.ERR_RULE_PACK_NOT_FOUND, 404)
        assert response.json()["data"]["error_id"] != ApiErrorId.ERR_VALIDATION

    def test_an_assessment_naming_an_unknown_device_reports_the_device_code(
        self, api: ApiClient
    ) -> None:
        """A valid customer with an unknown device resolves to ERR_DEVICE_NOT_FOUND.

        PRD: "Foreign keys arriving in a request body are resolved in the order the
        body's fields are documented, and each resolves to the target entity's own
        not-found code — for example, an assessment naming a valid customer but an
        unknown device reports `ERR_DEVICE_NOT_FOUND`."
        PRD: "2. **Existence** — the row addressed by the path `id`, then foreign keys
        named in the request body, then a parent rule pack named in the path, then a
        fraud rule addressed directly."

        Design: Corner/entities/assessment_with_unknown_device_fk_returns_404
        """
        set_clock(api)
        customer = create_customer(api, email="fk@example.com", home_country="US")
        address = create_address(
            api, line1="100 Main St", postal_code="94105", country_code="US"
        )

        response = api.create_assessment(
            create_assessment_payload(
                customer["id"], NON_EXISTENT_UUID, address["id"], amount_cents=20000
            ),
            CHECKOUT,
        )
        validate_error(response, ApiErrorId.ERR_DEVICE_NOT_FOUND, 404)

        _rows, meta = validate_paginated(
            api.list_assessments(CHECKOUT, params={"customer_id": customer["id"]})
        )
        assert meta["total_count"] == 0, "no assessment row was created"


class TestAssessmentListFilters:
    """Named filters intersect; they never widen the result set."""

    def test_state_and_decision_filters_each_narrow_the_same_three_rows(
        self, api: ApiClient
    ) -> None:
        """One approve, one decline and one abandoned attempt sit behind three filters.

        PRD: "Checkout assessments filter on `customer_id`, `device_profile_id`,
        `shipping_address_id`, `billing_address_id`, `rule_pack_id`, `risk_model_id`,
        `applied_exception_id`, `state`, `decision` and `outcome_label`."
        PRD: "Every list response repeats `limit` and `offset` in the envelope's `meta`
        object alongside `total_count` (the number of rows matching the filters before
        pagination) and `has_more` (true when rows remain beyond the current window)."

        Design: Corner/endpoints/assessment_list_filters_compose_across_state_and_decision
        """
        env = build_scoring_env(api)
        approved = build_approved_assessment(api, env, STANDARD_ORDER_CENTS)
        declined = open_and_score(
            api,
            env,
            amount_cents=STANDARD_ORDER_CENTS,
            model_raw_probability=PROB_DECLINE_EXACTLY_AT_DECLINE_FLOOR,
        )
        pending = open_assessment(api, env, amount_cents=STANDARD_ORDER_CENTS)

        assert approved["state"] == AssessmentState.DECIDED_APPROVE
        assert declined["state"] == AssessmentState.DECIDED_DECLINE
        assert pending["state"] == AssessmentState.PENDING_SIGNALS

        all_rows, all_meta = validate_paginated(api.list_assessments(CHECKOUT))
        assert all_meta["total_count"] == 3, "an unfiltered read returns every row"
        assert len(all_rows) == 3

        for params, expected_id, label in (
            (
                {"state": AssessmentState.DECIDED_APPROVE},
                approved["id"],
                "state=DECIDED_APPROVE",
            ),
            ({"decision": Decision.DECLINE}, declined["id"], "decision=DECLINE"),
            (
                {
                    "customer_id": env.customer_id,
                    "state": AssessmentState.PENDING_SIGNALS,
                },
                pending["id"],
                "customer_id with state=PENDING_SIGNALS",
            ),
        ):
            rows, meta = validate_paginated(api.list_assessments(CHECKOUT, params=params))
            assert meta["total_count"] == 1, f"{label} should match exactly one row"
            assert rows[0]["id"] == expected_id, f"{label} matched the wrong row"
            assert meta["has_more"] is False
