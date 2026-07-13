"""Specialist assignment, the selection policy, and the caseload cascade (PRD §3.6)."""

from test_helpers import (
    ApiErrorId,
    assign_case,
    assert_open_caseload_conserved,
    assert_restoration_case,
    assert_specialist,
    book_engagement,
    create_confirmed_fraud_alert,
    create_specialist,
    create_verified_subscriber,
    get_alert,
    get_case,
    get_specialist,
    get_subscriber,
    list_cases,
    make_specialist_headers,
    setup_open_case,
    setup_three_open_cases,
    setup_tier1_specialist_at_capacity_and_critical_case,
    setup_two_specialists_two_open_cases,
    validate_error,
    validate_success,
)


class TestAssignCascade:
    """assign -> active_case_count -> AT_CAPACITY -> exclusion from the selection policy."""

    def test_auto_assign_picks_the_oldest_tied_specialist_and_drives_them_to_capacity(
        self, api, admin_headers
    ):
        """PRD §3.6: "Otherwise the candidates are ordered by three keys, each ascending and applied
        in order: first by `active_case_count`, lowest first, to spread the load; then by tier rank,
        lowest first, so that a `TIER3` specialist is not burned on a case a `TIER1` could handle;
        and finally, when both keys tie, by `created_at`, oldest first."
        PRD §3.6: "Whenever that count is recomputed, the specialist's `status` becomes
        `AT_CAPACITY` when the count is greater than or equal to `max_caseload` — the comparison is
        inclusive, so a specialist with a `max_caseload` of two who is holding two cases is at
        capacity, not one case short of it — and `AVAILABLE` otherwise."

        Design: Difficulty/transitive_cascade/assign_cascade_count_then_capacity_then_selector_exclusion
        """
        ctx = setup_two_specialists_two_open_cases()

        assigned = validate_success(api.assign_case(ctx["case1"]["id"], {}, admin_headers))
        assert_restoration_case(assigned)
        assert assigned["status"] == "ASSIGNED"
        assert assigned["specialist_id"] == ctx["ada"]["id"], (
            "both specialists tie on count and tier rank, so created_at ASC picks Ada"
        )

        ada = get_specialist(ctx["ada"]["id"])
        assert_specialist(ada)
        assert ada["active_case_count"] == 1, "the assigned case now points at Ada"
        assert ada["status"] == "AT_CAPACITY", "1 >= max_caseload 1"

    def test_a_specialist_at_capacity_drops_out_of_the_next_auto_assignment(
        self, api, admin_headers
    ):
        """PRD §3.6: "And a specialist who has become `AT_CAPACITY` drops straight out of the
        eligibility filter above, so the *next* auto-assignment will not consider them at all — this
        is precisely how a run of assignments drains the pool."
        PRD §3.6: "The eligibility filter admits every specialist whose `status` is `AVAILABLE`,
        whose tier rank is at or above the case's `required_specialist_tier` rank, and whose
        `active_case_count` is strictly below their `max_caseload`."

        Design: Difficulty/transitive_cascade/assign_cascade_count_then_capacity_then_selector_exclusion
        """
        ctx = setup_two_specialists_two_open_cases()
        validate_success(api.assign_case(ctx["case1"]["id"], {}, admin_headers))
        assert get_specialist(ctx["ada"]["id"])["status"] == "AT_CAPACITY"

        second = validate_success(api.assign_case(ctx["case2"]["id"], {}, admin_headers))
        assert second["status"] == "ASSIGNED"
        assert second["specialist_id"] == ctx["bo"]["id"], (
            "Ada is AT_CAPACITY and therefore no longer a candidate"
        )

        bo = get_specialist(ctx["bo"]["id"])
        assert bo["active_case_count"] == 1
        assert bo["status"] == "AVAILABLE", "1 < max_caseload 5"


class TestCaseloadBoundary:
    """The AT_CAPACITY comparison is >=, not >."""

    def test_capacity_flips_when_the_count_equals_max_caseload(self, api, admin_headers):
        """PRD §3.6: "Whenever that count is recomputed, the specialist's `status` becomes
        `AT_CAPACITY` when the count is greater than or equal to `max_caseload` — the comparison is
        inclusive, so a specialist with a `max_caseload` of two who is holding two cases is at
        capacity, not one case short of it — and `AVAILABLE` otherwise."

        Design: Difficulty/boundary_precision_check/specialist_capacity_boundary_is_gte_not_gt
        """
        ctx = setup_three_open_cases(
            specialist_overrides={"full_name": "Cap Two", "tier": "TIER2", "max_caseload": 2}
        )
        specialist_id = ctx["specialist"]["id"]

        validate_success(
            api.assign_case(
                ctx["cases"][0]["id"], {"specialist_id": specialist_id}, admin_headers
            )
        )
        after_one = get_specialist(specialist_id)
        assert after_one["active_case_count"] == 1
        assert after_one["status"] == "AVAILABLE", "1 < 2, still below the boundary"

        validate_success(
            api.assign_case(
                ctx["cases"][1]["id"], {"specialist_id": specialist_id}, admin_headers
            )
        )
        after_two = get_specialist(specialist_id)
        assert after_two["active_case_count"] == 2
        assert after_two["status"] == "AT_CAPACITY", "2 >= 2 — the comparison is inclusive"

    def test_assigning_past_max_caseload_is_rejected(self, api, admin_headers):
        """PRD §3.6: "When a `specialist_id` *is* named, two checks run against that specialist:
        their tier rank must be at or above the rank of the case's `required_specialist_tier`, or
        the request fails with `ERR_SPECIALIST_TIER_INSUFFICIENT`; and their `active_case_count`
        must be strictly below their `max_caseload`, or it fails with `ERR_SPECIALIST_AT_CAPACITY`."

        Design: Difficulty/boundary_precision_check/specialist_capacity_boundary_is_gte_not_gt
        """
        ctx = setup_three_open_cases(
            specialist_overrides={"full_name": "Cap Two", "tier": "TIER2", "max_caseload": 2}
        )
        specialist_id = ctx["specialist"]["id"]
        for case in ctx["cases"][:2]:
            validate_success(
                api.assign_case(case["id"], {"specialist_id": specialist_id}, admin_headers)
            )

        resp = api.assign_case(
            ctx["cases"][2]["id"], {"specialist_id": specialist_id}, admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_SPECIALIST_AT_CAPACITY)

        third = get_case(ctx["cases"][2]["id"])
        assert third["status"] == "OPEN"
        assert third["specialist_id"] is None

        after = get_specialist(specialist_id)
        assert after["active_case_count"] == 2, "the rejected assign changed nothing"
        assert after["status"] == "AT_CAPACITY"


class TestAssignValidationPrecedence:
    """Competency (safety) is screened before caseload (constraint)."""

    def test_tier_insufficiency_is_reported_even_though_the_specialist_is_also_full(
        self, api, admin_headers
    ):
        """PRD §2.5: "A case-assign naming a specialist who is both under-qualified and full reports
        `ERR_SPECIALIST_TIER_INSUFFICIENT`, because competency precedes caseload."
        PRD §3.6: "When a `specialist_id` *is* named, two checks run against that specialist: their
        tier rank must be at or above the rank of the case's `required_specialist_tier`, or the
        request fails with `ERR_SPECIALIST_TIER_INSUFFICIENT`; and their `active_case_count` must be
        strictly below their `max_caseload`, or it fails with `ERR_SPECIALIST_AT_CAPACITY`."

        Design: Difficulty/priority_pair_validation_conflict/assign_safety_tier_beats_constraint_caseload
        """
        ctx = setup_tier1_specialist_at_capacity_and_critical_case()
        assert ctx["critical_case"]["required_specialist_tier"] == "TIER3", (
            "a CRITICAL alert implies TIER3"
        )
        assert ctx["specialist"]["status"] == "AT_CAPACITY", (
            "the caseload rule is violated too, so both checks could fire"
        )
        assert ctx["specialist"]["active_case_count"] == 1

        resp = api.assign_case(
            ctx["critical_case"]["id"],
            {"specialist_id": ctx["specialist"]["id"]},
            admin_headers,
        )
        error = validate_error(resp, ApiErrorId.ERR_SPECIALIST_TIER_INSUFFICIENT)
        assert error["error_id"] != "ERR_SPECIALIST_AT_CAPACITY", (
            "the caseload rule must not pre-empt the competency rule"
        )

    def test_the_rejected_assign_leaves_the_case_open_and_unassigned(self, api, admin_headers):
        """PRD §2.5: "A case-assign naming a specialist who is both under-qualified and full reports
        `ERR_SPECIALIST_TIER_INSUFFICIENT`, because competency precedes caseload."
        PRD §3.6: "Assignment then cascades. The case's `specialist_id` is written. The chosen
        specialist's `active_case_count` recomputes upward by one, since a non-terminal case now
        points at them."

        Design: Difficulty/priority_pair_validation_conflict/assign_safety_tier_beats_constraint_caseload
        """
        ctx = setup_tier1_specialist_at_capacity_and_critical_case()

        resp = api.assign_case(
            ctx["critical_case"]["id"],
            {"specialist_id": ctx["specialist"]["id"]},
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SPECIALIST_TIER_INSUFFICIENT)

        case = get_case(ctx["critical_case"]["id"])
        assert case["status"] == "OPEN"
        assert case["specialist_id"] is None

        specialist = get_specialist(ctx["specialist"]["id"])
        assert specialist["active_case_count"] == 1, "no cascade fired on the rejected assign"
        assert specialist["status"] == "AT_CAPACITY"


class TestAssignRequiresActiveEnrollment:
    """The gate is evaluated against the subscriber who owns the case."""

    def test_assign_is_refused_while_the_cases_subscriber_is_suspended(self, api, admin_headers):
        """PRD §2.7: "A subscriber whose `enrollment_status` is not `ACTIVE` is, for operational
        purposes, frozen. Any request that would drive protection work forward on behalf of such a
        subscriber is rejected with `ERR_ENROLLMENT_NOT_ACTIVE`."
        PRD §3.6: "Assignment requires the case to be `OPEN` and the case's subscriber to be
        `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/case_assign_requires_subscriber_enrollment_active
        """
        ctx = setup_open_case(
            plan_overrides={
                "tier": "ADVANTAGE",
                "monthly_fee_cents": 1999,
                "child_monitoring_included": False,
                "max_family_members": 2,
            },
            specialist_overrides={"full_name": "Nia Fox", "tier": "TIER2", "max_caseload": 3},
        )
        validate_success(
            api.suspend_subscriber(
                ctx["subscriber"]["id"],
                {"reason": "Chargeback under investigation"},
                admin_headers,
            )
        )

        resp = api.assign_case(
            ctx["case"]["id"], {"specialist_id": ctx["specialist"]["id"]}, admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE)

        assert get_subscriber(ctx["subscriber"]["id"])["enrollment_status"] == "SUSPENDED"

    def test_the_refused_assign_fires_no_cascade_and_succeeds_after_reactivation(
        self, api, admin_headers
    ):
        """PRD §2.7: "The gate is evaluated against the subscriber who *owns* the target resource,
        which is not always the subscriber in the request body — for a bureau-profile action it is
        the profile's `subscriber_id`, for a case action it is the case's `subscriber_id`, and for a
        claim it is the claim's `subscriber_id`."
        PRD §3.6: "Assignment requires the case to be `OPEN` and the case's subscriber to be
        `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/case_assign_requires_subscriber_enrollment_active
        """
        ctx = setup_open_case(
            plan_overrides={
                "tier": "ADVANTAGE",
                "monthly_fee_cents": 1999,
                "child_monitoring_included": False,
                "max_family_members": 2,
            },
            specialist_overrides={"full_name": "Nia Fox", "tier": "TIER2", "max_caseload": 3},
        )
        validate_success(
            api.suspend_subscriber(
                ctx["subscriber"]["id"], {"reason": "Chargeback"}, admin_headers
            )
        )
        validate_error(
            api.assign_case(
                ctx["case"]["id"], {"specialist_id": ctx["specialist"]["id"]}, admin_headers
            ),
            ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE,
        )

        case = get_case(ctx["case"]["id"])
        assert case["status"] == "OPEN" and case["specialist_id"] is None
        blocked = get_specialist(ctx["specialist"]["id"])
        assert blocked["active_case_count"] == 0, "no caseload cascade fired"
        assert blocked["status"] == "AVAILABLE"

        validate_success(api.reactivate_subscriber(ctx["subscriber"]["id"], admin_headers))
        assigned = validate_success(
            api.assign_case(
                ctx["case"]["id"], {"specialist_id": ctx["specialist"]["id"]}, admin_headers
            )
        )
        assert assigned["status"] == "ASSIGNED"


class TestCaseloadConservation:
    """assign (+1) then resolve (-1) returns every derived value to its pre-assign state."""

    def test_assign_then_resolve_returns_the_caseload_to_zero(self, api, admin_headers):
        """PRD §2.8: "First, **open-caseload conservation**: summing `active_case_count` over every
        specialist always equals the number of restoration cases that have a specialist attached and
        are in one of the non-terminal working states. An assign followed by a resolve therefore
        returns both sides of that identity — and the specialist's derived `status` — to exactly
        their pre-assign values."
        PRD §3.6: "The specialist's compensation: the case has left the working set, so
        `active_case_count` recomputes downward by one, and their `status` flips back to `AVAILABLE`
        if the new count is below `max_caseload`."

        Design: Difficulty/compensating_invariant/assign_then_resolve_conserves_open_caseload
        """
        ctx = setup_open_case(
            plan_overrides={
                "tier": "ADVANTAGE",
                "monthly_fee_cents": 1999,
                "child_monitoring_included": False,
                "max_family_members": 2,
            },
            specialist_overrides={"full_name": "Wren Solo", "tier": "TIER2", "max_caseload": 1},
            alert_overrides={"alert_type": "DARK_WEB", "severity": "LOW"},
        )
        specialist_id = ctx["specialist"]["id"]
        case_id = ctx["case"]["id"]

        before = get_specialist(specialist_id)
        assert before["active_case_count"] == 0 and before["status"] == "AVAILABLE"
        assert_open_caseload_conserved([before], list_cases())

        assign_case(case_id, specialist_id)
        mid = get_specialist(specialist_id)
        assert mid["active_case_count"] == 1 and mid["status"] == "AT_CAPACITY"
        assert_open_caseload_conserved([mid], list_cases())

        book_engagement(specialist_id, case_id)
        validate_success(
            api.resolve_case(
                case_id,
                {"resolution_summary": "Credentials rotated; no loss."},
                make_specialist_headers(specialist_id),
            )
        )

        after = get_specialist(specialist_id)
        assert after["active_case_count"] == 0, "the resolved case left the working set"
        assert after["status"] == "AVAILABLE", "the derived status returned to its pre-assign value"
        assert_open_caseload_conserved([after], list_cases())
        assert get_case(case_id)["status"] == "RESOLVED"

    def test_resolution_carries_the_origin_alert_to_resolved_and_lowers_the_risk(
        self, api, admin_headers
    ):
        """PRD §3.6: "And the cross-entity hop: the origin alert — the one whose `origin_alert_id`
        names it — is carried to `RESOLVED` by the system, from `CONFIRMED_FRAUD` or from
        `ESCALATED`, which in turn recomputes both of the subscriber's risk variants."
        PRD §3.6: "Since a `RESOLVED` alert counts for nothing in either variant, and since an alert
        leaving `ESCALATED` also sheds its escalation weight, resolution measurably lowers the
        subscriber's exposure."

        Design: Difficulty/compensating_invariant/assign_then_resolve_conserves_open_caseload
        """
        ctx = setup_open_case(
            plan_overrides={
                "tier": "ADVANTAGE",
                "monthly_fee_cents": 1999,
                "child_monitoring_included": False,
                "max_family_members": 2,
            },
            specialist_overrides={"full_name": "Wren Solo", "tier": "TIER2", "max_caseload": 1},
            alert_overrides={"alert_type": "DARK_WEB", "severity": "LOW"},
        )
        specialist_id = ctx["specialist"]["id"]
        case_id = ctx["case"]["id"]
        assert get_subscriber(ctx["subscriber"]["id"])["risk_score"] == 25

        assign_case(case_id, specialist_id)
        book_engagement(specialist_id, case_id)
        validate_success(
            api.resolve_case(
                case_id,
                {"resolution_summary": "Credentials rotated; no loss."},
                make_specialist_headers(specialist_id),
            )
        )

        assert get_alert(ctx["alert"]["id"])["status"] == "RESOLVED"
        after = get_subscriber(ctx["subscriber"]["id"])
        assert after["risk_score"] == 10, "the resolved alert contributes nothing"
        assert after["underwriting_risk_score"] == 10


class TestSelectionPolicyAndTierFloor:
    def test_auto_assign_with_no_eligible_candidate_is_rejected(self, api, admin_headers):
        """PRD §3.6: "The eligibility filter admits every specialist whose `status` is `AVAILABLE`,
        whose tier rank is at or above the case's `required_specialist_tier` rank, and whose
        `active_case_count` is strictly below their `max_caseload`. If that candidate set is empty,
        the assign is rejected with `ERR_NO_ELIGIBLE_SPECIALIST`."
        PRD §3.6: "The alert's severity implies a tier: `CRITICAL` implies `TIER3`, `HIGH` implies
        `TIER2`, and `MEDIUM` or `LOW` imply `TIER1`."

        Design: Corner/calculations/auto_assign_with_empty_candidate_pool_rejected
        """
        ctx = setup_open_case(
            plan_overrides={
                "tier": "ADVANTAGE",
                "monthly_fee_cents": 1999,
                "child_monitoring_included": False,
                "max_family_members": 2,
            },
            specialist_overrides={"full_name": "Junior Only", "tier": "TIER1", "max_caseload": 5},
            alert_overrides={
                "alert_type": "ACCOUNT_TAKEOVER",
                "severity": "CRITICAL",
                "source_detail": "retirement account drained",
            },
        )
        assert ctx["case"]["required_specialist_tier"] == "TIER3"

        resp = api.assign_case(ctx["case"]["id"], {}, admin_headers)
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_SPECIALIST)

        case = get_case(ctx["case"]["id"])
        assert case["status"] == "OPEN" and case["specialist_id"] is None
        assert get_specialist(ctx["specialist"]["id"])["active_case_count"] == 0

    def test_plan_min_specialist_tier_raises_the_case_floor_above_the_severity(self, api):
        """PRD §3.6: "The alert's severity implies a tier: `CRITICAL` implies `TIER3`, `HIGH`
        implies `TIER2`, and `MEDIUM` or `LOW` imply `TIER1`. The subscriber's plan also carries a
        floor, `min_specialist_tier`. The case's `required_specialist_tier` is whichever of those
        two has the *higher* rank."

        Design: Corner/calculations/required_specialist_tier_floored_by_plan_min_tier
        """
        _, subscriber = create_verified_subscriber(
            plan_overrides={"min_specialist_tier": "TIER2"},
            full_name="Floor Tier",
            ssn_last4="3030",
        )

        _alert, case = create_confirmed_fraud_alert(
            subscriber["id"],
            alert_type="DARK_WEB",
            severity="LOW",
            source_detail="minor leak",
        )

        assert case["required_specialist_tier"] == "TIER2", (
            "LOW severity implies TIER1, but the plan floor of TIER2 outranks it"
        )
        assert case["status"] == "OPEN"
        assert case["specialist_id"] is None

    def test_assign_naming_an_unknown_specialist_is_not_found(self, api, admin_headers):
        """PRD §2.5: "Existence — every resource named in the request path is resolved first, left
        to right, and only then every foreign key supplied in the request body. The rejection
        carries the not-found code of the *first* identifier that fails to resolve:
        `ERR_PLAN_NOT_FOUND`, `ERR_SUBSCRIBER_NOT_FOUND`, `ERR_FAMILY_MEMBER_NOT_FOUND`,
        `ERR_BUREAU_PROFILE_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
        `ERR_SPECIALIST_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, or `ERR_WALLET_ITEM_NOT_FOUND` as
        appropriate."

        Design: Corner/errors/assign_with_unknown_specialist_id_not_found
        """
        ctx = setup_open_case(
            plan_overrides={
                "tier": "ADVANTAGE",
                "monthly_fee_cents": 1999,
                "child_monitoring_included": False,
                "max_family_members": 2,
            }
        )

        resp = api.assign_case(
            ctx["case"]["id"],
            {"specialist_id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"},
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SPECIALIST_NOT_FOUND)

        case = get_case(ctx["case"]["id"])
        assert case["status"] == "OPEN" and case["specialist_id"] is None


class TestImmediateConsistency:
    def test_the_assign_cascade_is_visible_without_any_retry(self, api, admin_headers):
        """PRD §2.8: "Because they are recomputed rather than incrementally patched, two
        conservation properties hold and must survive round-trips."
        PRD §2.4: "When assigning a case changes a specialist's derived caseload, the specialist has
        been mutated in exactly the same sense. Each entity named as touched by a transition in §3
        increments its own `version` by one for that request, independently of the others."
        PRD §3.6: "Assignment then cascades. The case's `specialist_id` is written. The chosen
        specialist's `active_case_count` recomputes upward by one, since a non-terminal case now
        points at them. That new count may flip their `status` to `AT_CAPACITY`."

        Design: Corner/consistency_model/cascaded_fields_visible_in_the_same_response_immediate
        """
        ctx = setup_open_case(
            plan_overrides={
                "tier": "ADVANTAGE",
                "monthly_fee_cents": 1999,
                "child_monitoring_included": False,
                "max_family_members": 2,
            },
            specialist_overrides={"full_name": "Imm Spec", "tier": "TIER2", "max_caseload": 1},
            alert_overrides={"alert_type": "DARK_WEB", "severity": "LOW"},
        )
        specialist_id = ctx["specialist"]["id"]

        assigned = validate_success(
            api.assign_case(ctx["case"]["id"], {"specialist_id": specialist_id}, admin_headers)
        )
        assert assigned["status"] == "ASSIGNED", "the assign response already shows the new status"
        assert assigned["specialist_id"] == specialist_id

        specialist = validate_success(api.get_specialist(specialist_id, admin_headers))
        assert specialist["active_case_count"] == 1, "no lag: the derived count is already current"
        assert specialist["status"] == "AT_CAPACITY"
        assert specialist["version"] == 2, "version 1 at registration plus the assign cascade"