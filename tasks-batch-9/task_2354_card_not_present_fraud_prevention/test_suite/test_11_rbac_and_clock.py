"""The logical clock and the role headers every request is judged against."""

from __future__ import annotations

from test_helpers import (
    ADMIN,
    CHECKOUT,
    CLOCK_EPOCH,
    ENGINEER,
    ENGINEER_APPROVER,
    POLICY_ENGINEER_APPROVER_ID,
    POLICY_ENGINEER_AUTHOR_ID,
    REFERENCE_RULES,
    STANDARD_ORDER_CENTS,
    TIER_EXCEPTION_CAP_CENTS,
    ApiClient,
    ApiErrorId,
    AssessmentState,
    CaseAction,
    CaseState,
    CustomerTier,
    DecisionReason,
    ExceptionAction,
    ExceptionState,
    FinalDisposition,
    NON_EXISTENT_UUID,
    Role,
    Seniority,
    SignalFamily,
    add_rule_payload,
    assign_case_payload,
    assign_case_to,
    assert_net_approved_ledger,
    assert_score,
    build_lead,
    build_reviewed_assessment,
    build_scoring_env,
    create_analyst,
    create_customer,
    create_customer_payload,
    create_rule_pack_payload,
    draft_rule_pack,
    emulator_hard_decline_rule_payload,
    exception_decision_payload,
    make_headers,
    make_headers_with_empty_role,
    make_headers_without_role,
    make_review_lead_headers,
    make_risk_analyst_headers,
    parse_instant,
    read_analyst,
    read_assessment,
    read_case,
    read_customer,
    read_rule_pack,
    request_address_whitelist_exception,
    resolve_case_as_analyst,
    resolve_case_as_lead,
    RulePackStatus,
    set_clock,
    set_clock_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

#: One second before the epoch the clock already reads.
ONE_SECOND_BEFORE_EPOCH = "2026-07-31T23:59:59Z"


class TestLogicalClockMonotonicity:
    """The clock never falls back, but re-setting it to its own reading is fine."""

    def test_rewinding_is_refused_while_resetting_the_same_instant_is_accepted(
        self, api: ApiClient
    ) -> None:
        """The guard compares strictly, so an equal instant is not a rewind.

        PRD: "The clock is monotonic: a `current_utc` earlier than the clock's present
        reading is rejected with `ERR_CLOCK_NOT_MONOTONIC`."
        PRD: "Advancing the clock writes no entity — it is purely a time move, which is
        precisely what makes it the lever for pushing a sibling assessment out of a
        velocity window or letting a step-up challenge lapse."

        Design: Corner/endpoints/clock_endpoint_rejects_non_monotonic_time_but_allows_equal
        """
        set_clock(api, CLOCK_EPOCH)

        rewind = api.set_clock(set_clock_payload(ONE_SECOND_BEFORE_EPOCH), ADMIN)
        validate_error(rewind, ApiErrorId.ERR_CLOCK_NOT_MONOTONIC, 422)

        again = validate_success(
            api.set_clock(set_clock_payload(CLOCK_EPOCH), ADMIN), 200
        )
        assert parse_instant(again["current_utc"]) == parse_instant(CLOCK_EPOCH), (
            "re-setting the clock to its present reading is accepted"
        )

        customer = create_customer(api, email="clock@example.com")
        assert parse_instant(customer["created_at"]) == parse_instant(CLOCK_EPOCH), (
            "the refused rewind never took effect"
        )


class TestRoleHeaderIsReadBeforeAnythingElse:
    """The two header failures are distinct, and neither degrades into a 403."""

    def test_a_missing_role_and_an_unknown_role_are_each_their_own_401(
        self, api: ApiClient
    ) -> None:
        """Writes and reads alike are gated, and nothing reaches the database.

        PRD: "A request with a missing or empty `X-User-Role` is rejected with
        `ERR_MISSING_ROLE`. A request whose `X-User-Role` is not one of the five
        recognised role names is rejected with `ERR_INVALID_ROLE`. A syntactically valid
        role that is simply not permitted on the addressed operation is rejected with
        `ERR_UNAUTHORIZED`."
        PRD: "Every request — without exception, including reads — must carry two
        headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`,
        declaring the capacity in which it acts."

        Design: Corner/rbac/missing_or_unknown_role_header_rejected
        """
        set_clock(api, CLOCK_EPOCH)

        no_role = api.create_customer(
            create_customer_payload(email="norole@example.com"),
            make_headers_without_role(),
        )
        validate_error(no_role, ApiErrorId.ERR_MISSING_ROLE, 401)

        empty_role = api.create_customer(
            create_customer_payload(email="emptyrole@example.com"),
            make_headers_with_empty_role(),
        )
        validate_error(empty_role, ApiErrorId.ERR_MISSING_ROLE, 401)

        unknown_role = api.create_customer(
            create_customer_payload(email="badrole@example.com"),
            make_headers("fraud-manager-1", "FraudManager"),
        )
        validate_error(unknown_role, ApiErrorId.ERR_INVALID_ROLE, 401)
        assert unknown_role.json()["data"]["error_id"] != ApiErrorId.ERR_UNAUTHORIZED, (
            "an unrecognised role name is not merely an unpermitted role"
        )

        unauthenticated_read = api.list_customers(make_headers_without_role())
        validate_error(unauthenticated_read, ApiErrorId.ERR_MISSING_ROLE, 401)

        _rows, meta = validate_paginated(api.list_customers(ADMIN))
        assert meta["total_count"] == 0, "not one refused request created a row"


class TestRoleGateOutranksTheBody:
    """An unpermitted role is answered before the request body is examined."""

    def test_the_checkout_service_cannot_author_a_rule_pack_however_it_is_shaped(
        self, api: ApiClient
    ) -> None:
        """A well-formed pack and a mis-weighted pack both come back as the same 403.

        PRD: "`PolicyEngineer` alone owns rule packs, their rules and the scoring
        models."
        PRD: "1. **Authentication and authorisation** — missing role, unrecognised role,
        role not permitted on this operation, then the entity-backed user-context check
        (§2.1)."

        Design: Corner/rbac/checkout_service_cannot_author_rule_packs
        """
        set_clock(api, CLOCK_EPOCH)

        well_formed = api.create_rule_pack(
            create_rule_pack_payload(version_label="P-forbidden"), CHECKOUT
        )
        validate_error(well_formed, ApiErrorId.ERR_UNAUTHORIZED, 403)

        mis_weighted = api.create_rule_pack(
            create_rule_pack_payload(
                version_label="P-forbidden-2", rule_weight=0.40, model_weight=0.50
            ),
            CHECKOUT,
        )
        validate_error(mis_weighted, ApiErrorId.ERR_UNAUTHORIZED, 403)
        assert mis_weighted.json()["data"]["error_id"] != (
            ApiErrorId.ERR_WEIGHTS_NOT_NORMALIZED
        ), "the authorisation band is evaluated before the fiscal band"

        _rows, meta = validate_paginated(api.list_rule_packs(ENGINEER))
        assert meta["total_count"] == 0, "the refused drafts persisted nothing"


class TestQueueStaffingAndExceptionDecisionsAreLeadOnly:
    """The analyst who will work a case still may not staff it or decide policy."""

    def test_the_same_analyst_row_is_refused_on_assign_auto_assign_and_decision(
        self, api: ApiClient
    ) -> None:
        """Three writes are refused under the RiskAnalyst role and nothing moves.

        PRD: "`RiskAnalyst` works the queue and alone requests policy exceptions, but
        may never staff the queue or decide an exception."
        PRD: "`ReviewLead` alone staffs the queue (both by name and automatically) and
        alone decides policy exceptions, but may never request one."

        Design: Corner/rbac/risk_analyst_cannot_staff_the_queue_or_decide_exceptions
        """
        env = build_scoring_env(api)
        analyst = create_analyst(
            api,
            display_name="AN1",
            seniority=Seniority.SENIOR,
            skill_families=[SignalFamily.BEHAVIORAL],
            shift_capacity_cases=2,
        )
        assert int(analyst["version"]) == 1

        _assessment, case = build_reviewed_assessment(api, env, STANDARD_ORDER_CENTS)
        assert case["state"] == CaseState.QUEUED

        exception = request_address_whitelist_exception(
            api,
            env.customer_id,
            analyst["id"],
            env.address_id,
            max_amount_cents=TIER_EXCEPTION_CAP_CENTS[CustomerTier.STANDARD],
        )
        assert exception["state"] == ExceptionState.REQUESTED

        customer_version = int(read_customer(api, env.customer_id)["version"])
        analyst_headers = make_risk_analyst_headers(analyst["id"])

        by_name = api.assign_case(
            case["id"],
            assign_case_payload(analyst["id"], int(analyst["version"])),
            analyst_headers,
        )
        validate_error(by_name, ApiErrorId.ERR_UNAUTHORIZED, 403)

        automatic = api.auto_assign_case(case["id"], analyst_headers)
        validate_error(automatic, ApiErrorId.ERR_UNAUTHORIZED, 403)

        decision = api.decide_policy_exception(
            exception["id"],
            exception_decision_payload(ExceptionAction.APPROVE, customer_version),
            analyst_headers,
        )
        validate_error(decision, ApiErrorId.ERR_UNAUTHORIZED, 403)

        untouched_case = read_case(api, case["id"])
        assert untouched_case["state"] == CaseState.QUEUED
        assert untouched_case["assigned_analyst_id"] is None

        untouched_analyst = read_analyst(api, analyst["id"])
        assert untouched_analyst["open_case_count"] == 0
        assert int(untouched_analyst["version"]) == 1

        still_requested = validate_success(
            api.get_policy_exception(exception["id"], ADMIN), 200
        )
        assert still_requested["state"] == ExceptionState.REQUESTED
        assert still_requested["approved_by_analyst_id"] is None
        assert int(read_customer(api, env.customer_id)["version"]) == customer_version


class TestResolveIsTheOneSharedWrite:
    """Both entity-backed roles resolve cases, but only the lead may resolve another's."""

    def test_a_lead_closes_another_analysts_case_and_the_holder_is_credited(
        self, api: ApiClient
    ) -> None:
        """One decline by the lead, one approve by the owner, one ledger to reconcile.

        PRD: "Ownership is then enforced asymmetrically: a `RiskAnalyst` may act only on
        a case whose `assigned_analyst_id` equals their own `X-User-ID`, and otherwise
        receives `ERR_NOT_CASE_OWNER`, whereas a `ReviewLead` may resolve any `ASSIGNED`
        case."
        PRD: "`ASSIGNED → RESOLVED_DECLINE` stamps `resolved_at` and evaluates
        `resolved_late` the same way, decrements the analyst's `open_case_count` by one
        and increments their `version` by one when an analyst held the case, and cascades
        the assessment `IN_REVIEW → DECIDED_DECLINE`: `decision_reason` becomes
        `MANUAL_REVIEW`, `final_disposition` becomes `DECLINED`, `decided_at` is stamped,
        the customer's `declined_count` and `version` each rise by one"

        Design: Corner/rbac/resolve_is_shared_between_risk_analyst_and_review_lead
        """
        env = build_scoring_env(api)
        analyst = create_analyst(
            api,
            display_name="AN1",
            seniority=Seniority.SENIOR,
            skill_families=[SignalFamily.BEHAVIORAL],
            shift_capacity_cases=2,
        )
        lead = build_lead(api, skill_families=[SignalFamily.BEHAVIORAL])

        first_assessment, first_case = build_reviewed_assessment(
            api, env, STANDARD_ORDER_CENTS
        )
        second_assessment, second_case = build_reviewed_assessment(
            api, env, STANDARD_ORDER_CENTS
        )
        assert_score(first_assessment["blended_score"], 50.00, "blended_score")
        assert_score(second_assessment["blended_score"], 50.00, "blended_score")

        assign_case_to(api, first_case["id"], analyst, lead["id"])
        assign_case_to(api, second_case["id"], lead, lead["id"])

        lead_closed = resolve_case_as_lead(
            api,
            first_case["id"],
            lead["id"],
            CaseAction.DECLINE,
            resolution_note="lead override on another analyst's case",
        )
        assert lead_closed["state"] == CaseState.RESOLVED_DECLINE
        assert lead_closed["assigned_analyst_id"] == analyst["id"], (
            "the case is still recorded against the analyst who held it"
        )

        holder = read_analyst(api, analyst["id"])
        assert holder["open_case_count"] == 0
        assert holder["resolved_case_count"] == 1, (
            "the holder's counters move, not the acting lead's"
        )

        declined = read_assessment(api, first_assessment["id"])
        assert declined["state"] == AssessmentState.DECIDED_DECLINE
        assert declined["decision_reason"] == DecisionReason.MANUAL_REVIEW
        assert declined["final_disposition"] == FinalDisposition.DECLINED

        owner_closed = resolve_case_as_analyst(
            api,
            second_case["id"],
            lead["id"],
            CaseAction.APPROVE,
            resolution_note="lead resolves own case",
        )
        assert owner_closed["state"] == CaseState.RESOLVED_APPROVE

        lead_row = read_analyst(api, lead["id"])
        assert lead_row["open_case_count"] == 0
        assert lead_row["resolved_case_count"] == 1

        customer = read_customer(api, env.customer_id)
        assert customer["approved_count"] == 1
        assert customer["declined_count"] == 1
        assert customer["lifetime_net_approved_cents"] == STANDARD_ORDER_CENTS
        assert assert_net_approved_ledger(api, env.customer_id, ADMIN) == (
            STANDARD_ORDER_CENTS
        )


class TestEngineerIdentityIsTrackedAcrossTheWorkflow:
    """The author's token is recorded at drafting and refused at activation."""

    def test_the_drafting_engineer_cannot_activate_but_a_second_one_can(
        self, api: ApiClient
    ) -> None:
        """The refused activation leaves the pack DRAFT at version 1.

        PRD: "the acting engineer must not be the pack's `created_by_user_id`
        (`ERR_ACTIVATION_SEGREGATION_VIOLATION`)"
        PRD: "A successful activation sets `status` to `ACTIVE`, stamps `activated_at`
        with the current instant, records the acting engineer's `X-User-ID` as
        `activated_by_user_id`, and increments the pack's `version`."

        Design: Corner/rbac/pack_activation_by_its_own_author_rejected
        """
        set_clock(api, CLOCK_EPOCH)
        pack = draft_rule_pack(api, version_label="P-sod")
        assert pack["created_by_user_id"] == POLICY_ENGINEER_AUTHOR_ID
        add_rule_payload(api, pack["id"], REFERENCE_RULES[0])
        # Accepting the rule increments the pack's ``rule_count``, and a change to a
        # derived field is itself a mutation of the pack row, so the drafting
        # baseline is read back rather than assumed to still be 1.
        drafted = read_rule_pack(api, pack["id"])
        assert drafted["rule_count"] == 1
        drafted_version = int(drafted["version"])

        self_activation = api.activate_rule_pack(pack["id"], ENGINEER)
        validate_error(
            self_activation, ApiErrorId.ERR_ACTIVATION_SEGREGATION_VIOLATION, 409
        )

        still_draft = read_rule_pack(api, pack["id"])
        assert still_draft["status"] == RulePackStatus.DRAFT
        assert still_draft["activated_at"] is None
        assert still_draft["activated_by_user_id"] is None
        assert int(still_draft["version"]) == drafted_version, (
            "a refused activation is not a mutation"
        )

        activated = validate_success(
            api.activate_rule_pack(pack["id"], ENGINEER_APPROVER), 200
        )
        assert activated["status"] == RulePackStatus.ACTIVE
        assert parse_instant(activated["activated_at"]) == parse_instant(CLOCK_EPOCH)
        assert activated["activated_by_user_id"] == POLICY_ENGINEER_APPROVER_ID
        assert activated["created_by_user_id"] == POLICY_ENGINEER_AUTHOR_ID, (
            "the author is still recorded alongside the approver"
        )
        assert int(activated["version"]) == drafted_version + 1, (
            "a successful activation increments the pack's version by exactly one"
        )


class TestEntityBackedIdentityIsResolvedButOpaqueIdentityIsNot:
    """Only the two analyst-backed roles pay the user-context resolution cost."""

    def test_an_unknown_lead_is_a_401_while_an_unknown_engineer_token_is_accepted(
        self, api: ApiClient
    ) -> None:
        """The engineer's request gets as far as the pack's DRAFT gate.

        PRD: "For both entity-backed roles, a request that omits `X-User-ID`, or supplies
        a value that no `Analyst` row carries as its `id`, is rejected with
        `ERR_INVALID_USER_CONTEXT`. This check runs on every endpoint those two roles are
        authorised for."
        PRD: "When `X-User-Role` is `PolicyEngineer`, `X-User-ID` is an opaque engineer
        token not tied to any persisted entity."

        Design: Corner/rbac/review_lead_x_user_id_must_name_an_analyst_row_rejected
        """
        env = build_scoring_env(api)
        analyst = create_analyst(
            api,
            display_name="AN1",
            seniority=Seniority.SENIOR,
            skill_families=[SignalFamily.BEHAVIORAL],
            shift_capacity_cases=2,
        )
        _assessment, case = build_reviewed_assessment(api, env, STANDARD_ORDER_CENTS)

        phantom_lead = api.assign_case(
            case["id"],
            assign_case_payload(analyst["id"], int(analyst["version"])),
            make_review_lead_headers(NON_EXISTENT_UUID),
        )
        validate_error(phantom_lead, ApiErrorId.ERR_INVALID_USER_CONTEXT, 401)

        assert read_case(api, case["id"])["state"] == CaseState.QUEUED
        assert int(read_analyst(api, analyst["id"])["version"]) == 1

        phantom_engineer = api.create_rule(
            env.pack_id,
            emulator_hard_decline_rule_payload(points=45, evaluation_order=5),
            make_headers(NON_EXISTENT_UUID, Role.POLICY_ENGINEER),
        )
        validate_error(phantom_engineer, ApiErrorId.ERR_RULE_PACK_NOT_DRAFT, 409)
        assert phantom_engineer.json()["data"]["error_id"] != (
            ApiErrorId.ERR_INVALID_USER_CONTEXT
        ), "an opaque engineer token is never resolved against a stored row"
