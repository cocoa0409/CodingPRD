"""Remediation: action-plan lifecycle, due-date extension caps, and clock-based
overdue tracking (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    assert_action_plan,
    assert_extension_request,
    create_action_plan_payload,
    create_and_approve_extension,
    create_extension_request_payload,
    create_issued_finding,
    get_success_data,
    is_iso8601_timestamp,
    make_manager_headers,
    respond_to_finding,
    set_clock,
    setup_action_plan,
    setup_agreed_finding,
    setup_engagement_in_fieldwork,
    create_active_rating_config,
    validate_error,
    validate_success,
)


class TestActionPlanLifecycle:
    def test_action_plan_validation_rework_cycle(self, api, owner_headers):
        """PRD §3.7: "the `due_date` must lie strictly after the logical clock's
        current instant; a date in the present or past fails with
        `ERR_DUE_DATE_NOT_FUTURE`."
        PRD §3.7: "Rejection — a request carrying a `rejection_note` — returns
        the plan to `IN_PROGRESS` for rework, a validation-failure loop that may
        repeat."
        PRD §3.7: "Validation moves the plan to its terminal `VALIDATED` status,
        records `validated_by_user_id` from the caller, stamps `validated_at`
        from the logical clock"
        PRD §3.7: "At creation the server copies `due_date` into
        `original_due_date`, an immutable record of the initial commitment that
        later extensions never touch."

        Design: Corner/state_machines/action_plan_validation_rework_cycle
        """
        ctx = setup_agreed_finding(entity_name="E")
        mgr_h = make_manager_headers(ctx["mgr"]["id"])

        # A past due date is rejected at creation (clock reads 2026-01-15).
        past = api.create_action_plan(
            create_action_plan_payload(ctx["finding"]["id"], description="late",
                                       due_date="2026-01-10T00:00:00Z"),
            owner_headers,
        )
        validate_error(past, ApiErrorId.ERR_DUE_DATE_NOT_FUTURE, expected_status=422)

        ap = get_success_data(api.create_action_plan(
            create_action_plan_payload(ctx["finding"]["id"], description="fix",
                                       due_date="2026-06-01T00:00:00Z"),
            owner_headers,
        ))
        assert ap["status"] == "OPEN"
        assert ap["original_due_date"] == "2026-06-01T00:00:00Z"
        assert ap["extension_count"] == 0

        # OPEN -> IN_PROGRESS -> SUBMITTED_FOR_VALIDATION -> IN_PROGRESS (rework).
        get_success_data(api.start_action_plan(ap["id"], owner_headers))
        get_success_data(api.submit_action_plan_validation(ap["id"], owner_headers))
        rejected = get_success_data(api.reject_action_plan_validation(
            ap["id"], {"rejection_note": "evidence insufficient"}, mgr_h,
        ))
        assert rejected["status"] == "IN_PROGRESS"

        # Second submit validates; the terminal plan rejects further decisions.
        get_success_data(api.submit_action_plan_validation(ap["id"], owner_headers))
        validated = get_success_data(api.validate_action_plan(ap["id"], mgr_h))
        assert validated["status"] == "VALIDATED"
        assert validated["validated_by_user_id"] == ctx["mgr"]["id"]
        assert is_iso8601_timestamp(validated["validated_at"])
        assert validated["original_due_date"] == "2026-06-01T00:00:00Z"
        assert validated["extension_count"] == 0
        assert_action_plan(validated)

        revalidate = api.validate_action_plan(ap["id"], mgr_h)
        validate_error(revalidate, ApiErrorId.ERR_ACTION_PLAN_INVALID_STATE, expected_status=409)


class TestActionPlanCrossEntityGate:
    def test_action_plan_start_gated_by_finding_agreed(self, api, owner_headers):
        """PRD §3.7: "Starting the work is a `ManagementOwner` action requiring
        the plan to be `OPEN` (else `ERR_ACTION_PLAN_INVALID_STATE`) and — a
        cross-entity gate — the parent finding to be `AGREED`; starting
        remediation on a finding still under negotiation fails with
        `ERR_FINDING_NOT_AGREED`."
        PRD §3.6: "Accepting the response moves it to `ACCEPTED`, records the
        caller as `reviewed_by_user_id`, and bubbles up: the parent finding
        transitions from `UNDER_REVIEW` to `AGREED`."

        Design: Difficulty/cross_entity_state_dependency/action_plan_start_gated_by_finding_agreed
        """
        ctx = setup_engagement_in_fieldwork(entity_name="Entity G2", budget_hours=100)
        create_active_rating_config()
        from test_helpers import create_auditor
        mgr2 = create_auditor(full_name="Mike Mgr2", grade="MANAGER")
        finding = create_issued_finding(ctx, title="Gap", likelihood=3, impact=4, issuer=mgr2)
        resp = respond_to_finding(finding["id"], response_text="Acknowledged")
        # Finding is UNDER_REVIEW; the plan is creatable but not startable.
        ap = get_success_data(api.create_action_plan(
            create_action_plan_payload(finding["id"], due_date="2026-06-01T00:00:00Z"),
            owner_headers,
        ))
        assert ap["status"] == "OPEN"

        early = api.start_action_plan(ap["id"], owner_headers)
        validate_error(early, ApiErrorId.ERR_FINDING_NOT_AGREED, expected_status=422)

        # Accepting the response flips the finding to AGREED; the same call
        # now succeeds.
        get_success_data(api.accept_management_response(
            resp["id"], make_manager_headers(mgr2["id"]),
        ))
        started = get_success_data(api.start_action_plan(ap["id"], owner_headers))
        assert started["status"] == "IN_PROGRESS"

    def test_action_plan_start_after_agreement_from_open(self, api, owner_headers):
        """PRD §3.7: "Starting the work is a `ManagementOwner` action requiring
        the plan to be `OPEN` (else `ERR_ACTION_PLAN_INVALID_STATE`) and — a
        cross-entity gate — the parent finding to be `AGREED`"

        Design: Difficulty/cross_entity_state_dependency/action_plan_start_gated_by_finding_agreed
        """
        ctx = setup_action_plan(due_date="2026-06-01T00:00:00Z", start=False,
                                entity_name="Entity G2b")
        started = get_success_data(api.start_action_plan(ctx["action_plan"]["id"], owner_headers))
        assert started["status"] == "IN_PROGRESS"


class TestExtensionDecisionLockdown:
    def test_extension_pending_uniqueness_and_decision_lockdown(self, api, owner_headers, cae_headers):
        """PRD §3.7: "Finally, only one request may be in flight per plan:
        creating a second `PENDING` request fails with
        `ERR_EXTENSION_ALREADY_PENDING`."
        PRD §3.7: "Decisions belong to the `ChiefAuditExecutive`, and both
        decision actions require the request to be `PENDING`, else
        `ERR_EXTENSION_INVALID_STATE`."
        PRD §3.7: "On approval the request records `decided_by_user_id`, and its
        `approved_days` is computed as the whole days between the plan's prior
        `due_date` and the `requested_due_date`"

        Design: Corner/state_machines/extension_pending_uniqueness_and_decision_lockdown
        """
        ctx = setup_action_plan(due_date="2026-06-01T00:00:00Z", entity_name="E")
        ap = ctx["action_plan"]

        ext1 = get_success_data(api.create_extension_request(
            create_extension_request_payload(ap["id"], requested_due_date="2026-07-01T00:00:00Z",
                                             reason="r1"),
            owner_headers,
        ))
        assert ext1["status"] == "PENDING"

        # A second in-flight request for the same plan is rejected.
        second = api.create_extension_request(
            create_extension_request_payload(ap["id"], requested_due_date="2026-08-01T00:00:00Z",
                                             reason="r2"),
            owner_headers,
        )
        validate_error(second, ApiErrorId.ERR_EXTENSION_ALREADY_PENDING, expected_status=409)

        approved = get_success_data(api.approve_extension_request(ext1["id"], cae_headers))
        assert approved["status"] == "APPROVED"
        assert approved["approved_days"] == 30  # 2026-06-01 -> 2026-07-01
        assert_extension_request(approved)

        # A decided request is terminal.
        reapprove = api.approve_extension_request(ext1["id"], cae_headers)
        validate_error(reapprove, ApiErrorId.ERR_EXTENSION_INVALID_STATE, expected_status=409)

        ap_after = get_success_data(api.get_action_plan(ap["id"], cae_headers))
        assert ap_after["due_date"] == "2026-07-01T00:00:00Z"
        assert ap_after["extension_count"] == 1


class TestExtensionGuards:
    def test_extension_monotonic_cap_and_count_rejections(self, api, owner_headers, cae_headers):
        """PRD §3.7: "The shift must be strictly monotonic:
        `requested_due_date` must be strictly after the plan's current
        `due_date`, else `ERR_EXTENSION_NOT_MONOTONIC`."
        PRD §3.7: "And the cumulative cap must hold: the plan's
        `cumulative_extended_days` plus the requested whole-day shift must not
        exceed 180, where the boundary is inclusive — a cumulative total of
        exactly 180 days is permitted, 181 is not — else
        `ERR_EXTENSION_CUMULATIVE_CAP_EXCEEDED`."
        PRD §3.7: "The plan's `extension_count` must be below two — the cap is
        two approved extensions per plan — else `ERR_EXTENSION_COUNT_EXCEEDED`."

        Design: Corner/state_machines/extension_monotonic_cap_and_count_rejections
        """
        ctx = setup_action_plan(due_date="2026-06-01T00:00:00Z", entity_name="E")
        ap = ctx["action_plan"]

        # Non-monotonic: 2026-05-01 precedes the current due date.
        backwards = api.create_extension_request(
            create_extension_request_payload(ap["id"], requested_due_date="2026-05-01T00:00:00Z",
                                             reason="backwards"),
            owner_headers,
        )
        validate_error(backwards, ApiErrorId.ERR_EXTENSION_NOT_MONOTONIC, expected_status=422)

        # +100 days approved (cumulative 100).
        ext1 = get_success_data(api.create_extension_request(
            create_extension_request_payload(ap["id"], requested_due_date="2026-09-09T00:00:00Z",
                                             reason="p1"),
            owner_headers,
        ))
        get_success_data(api.approve_extension_request(ext1["id"], cae_headers))

        # +81 more days would push the cumulative total to 181 > 180.
        over_cap = api.create_extension_request(
            create_extension_request_payload(ap["id"], requested_due_date="2026-11-29T00:00:00Z",
                                             reason="p2"),
            owner_headers,
        )
        validate_error(over_cap, ApiErrorId.ERR_EXTENSION_CUMULATIVE_CAP_EXCEEDED,
                       expected_status=422)

        # +80 days lands exactly on 180 and is permitted.
        ext2 = get_success_data(api.create_extension_request(
            create_extension_request_payload(ap["id"], requested_due_date="2026-11-28T00:00:00Z",
                                             reason="p2b"),
            owner_headers,
        ))
        get_success_data(api.approve_extension_request(ext2["id"], cae_headers))
        ap_after = get_success_data(api.get_action_plan(ap["id"], cae_headers))
        assert ap_after["cumulative_extended_days"] == 180
        assert ap_after["extension_count"] == 2

        # The count cap is reached; a third request is rejected.
        third = api.create_extension_request(
            create_extension_request_payload(ap["id"], requested_due_date="2026-12-15T00:00:00Z",
                                             reason="p3"),
            owner_headers,
        )
        validate_error(third, ApiErrorId.ERR_EXTENSION_COUNT_EXCEEDED, expected_status=422)


class TestExtensionCumulativeBoundary:
    def test_extension_cumulative_cap_exactly_180_approved(self, api, cae_headers):
        """PRD §3.7: "And the cumulative cap must hold: the plan's
        `cumulative_extended_days` plus the requested whole-day shift must not
        exceed 180, where the boundary is inclusive — a cumulative total of
        exactly 180 days is permitted, 181 is not — else
        `ERR_EXTENSION_CUMULATIVE_CAP_EXCEEDED`."
        PRD §3.7: "The approval then cascades: the plan's `due_date` is set to
        the `requested_due_date`, `extension_count` increments by one, and
        `cumulative_extended_days` increases by `approved_days`"

        Design: Difficulty/boundary_precision_check/extension_cumulative_cap_exactly_180_approved
        """
        ctx = setup_action_plan(due_date="2026-06-01T00:00:00Z", start=True,
                                entity_name="Entity B1")
        ap = ctx["action_plan"]

        # First approval: +100 days (2026-06-01 -> 2026-09-09).
        first = create_and_approve_extension(ap["id"], "2026-09-09T00:00:00Z", reason="phase 1")
        assert first["approved_days"] == 100

        # Second request: +80 days (2026-09-09 -> 2026-11-28) — lands on 180.
        from test_helpers import create_extension_request_payload
        from test_helpers import TEST_USERS
        ext2 = get_success_data(api.create_extension_request(
            create_extension_request_payload(ap["id"],
                                             requested_due_date="2026-11-28T00:00:00Z",
                                             reason="phase 2"),
            TEST_USERS["owner_headers"],
        ))
        approved = get_success_data(api.approve_extension_request(ext2["id"], cae_headers))
        assert approved["status"] == "APPROVED"
        assert approved["approved_days"] == 80

        ap_after = get_success_data(api.get_action_plan(ap["id"], cae_headers))
        assert ap_after["cumulative_extended_days"] == 180, (
            "The inclusive cap accepts exactly 180 days"
        )
        assert ap_after["extension_count"] == 2
        assert ap_after["due_date"] == "2026-11-28T00:00:00Z"

    def test_extension_approved_days_computed_at_approval(self, api, cae_headers, owner_headers):
        """PRD §3.7: "On approval the request records `decided_by_user_id`, and
        its `approved_days` is computed as the whole days between the plan's
        prior `due_date` and the `requested_due_date` — always at least one day,
        given monotonicity."

        Design: Difficulty/boundary_precision_check/extension_cumulative_cap_exactly_180_approved
        """
        ctx = setup_action_plan(due_date="2026-06-01T00:00:00Z", entity_name="Entity B1b")
        ap = ctx["action_plan"]
        ext = get_success_data(api.create_extension_request(
            create_extension_request_payload(ap["id"],
                                             requested_due_date="2026-06-11T00:00:00Z",
                                             reason="short"),
            owner_headers,
        ))
        assert ext["approved_days"] is None, "approved_days is unset until approval"
        approved = get_success_data(api.approve_extension_request(ext["id"], cae_headers))
        assert approved["approved_days"] == 10  # 2026-06-01 -> 2026-06-11
        assert approved["decided_by_user_id"] == "cae-1"
        ap_after = get_success_data(api.get_action_plan(ap["id"], cae_headers))
        assert ap_after["cumulative_extended_days"] == 10
        assert ap_after["extension_count"] == 1


class TestExtensionStatePriority:
    def test_extension_create_state_beats_count_cap(self, api, owner_headers):
        """PRD §3.7: "The action plan must be in `OPEN` or `IN_PROGRESS`; a plan
        already submitted for validation or validated rejects new extension
        requests with `ERR_ACTION_PLAN_INVALID_STATE`."
        PRD §2.7: "when several violations are present, the error surfaced is
        the one belonging to the earliest stage."
        PRD §2.7 stage 7: "**State legality** — the target resource must be in a
        legal from-state for the requested transition."

        Design: Difficulty/priority_pair_validation_conflict/extension_create_state_beats_count_cap
        """
        ctx = setup_action_plan(due_date="2026-06-01T00:00:00Z", start=True,
                                entity_name="Entity S")
        ap = ctx["action_plan"]
        mgr_h = make_manager_headers(ctx["mgr"]["id"])

        # Two approved extensions: count reaches the cap (cumulative 75).
        create_and_approve_extension(ap["id"], "2026-07-01T00:00:00Z", reason="r1")
        create_and_approve_extension(ap["id"], "2026-08-15T00:00:00Z", reason="r2")

        # Walk the plan to its terminal VALIDATED state.
        get_success_data(api.submit_action_plan_validation(ap["id"], owner_headers))
        get_success_data(api.validate_action_plan(ap["id"], mgr_h))

        # Both the state gate (VALIDATED) and the count cap (2) are violated;
        # state legality is the earlier pipeline stage and must surface.
        resp = api.create_extension_request(
            create_extension_request_payload(ap["id"],
                                             requested_due_date="2026-09-01T00:00:00Z",
                                             reason="r3"),
            owner_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ACTION_PLAN_INVALID_STATE, expected_status=409)

        ap_after = get_success_data(api.get_action_plan(ap["id"], owner_headers))
        assert ap_after["extension_count"] == 2
        assert ap_after["cumulative_extended_days"] == 75

    def test_extension_create_on_validated_plan_rejected(self, api, owner_headers):
        """PRD §3.7: "The action plan must be in `OPEN` or `IN_PROGRESS`; a plan
        already submitted for validation or validated rejects new extension
        requests with `ERR_ACTION_PLAN_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/extension_create_state_beats_count_cap
        """
        ctx = setup_action_plan(due_date="2026-06-01T00:00:00Z", start=True,
                                entity_name="Entity S2")
        ap = ctx["action_plan"]
        mgr_h = make_manager_headers(ctx["mgr"]["id"])
        # No extensions: only the state gate is violated on this plan.
        get_success_data(api.submit_action_plan_validation(ap["id"], owner_headers))
        get_success_data(api.validate_action_plan(ap["id"], mgr_h))

        resp = api.create_extension_request(
            create_extension_request_payload(ap["id"],
                                             requested_due_date="2026-09-01T00:00:00Z",
                                             reason="r3"),
            owner_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ACTION_PLAN_INVALID_STATE, expected_status=409)
        ap_after = get_success_data(api.get_action_plan(ap["id"], owner_headers))
        assert ap_after["extension_count"] == 0


class TestOverdueTracking:
    def test_overdue_days_due_today_zero_boundary(self, api):
        """PRD §3.7: "An action plan's days overdue are the whole days from its
        current `due_date` to the logical-clock date, floored at zero; a plan
        due today has zero days overdue and is therefore not overdue — overdue
        requires at least one full day."
        PRD §3.7: "A finding's `open_overdue_action_count` is the number of its
        action plans that are not `VALIDATED` and are at least one day overdue;
        the count is re-evaluated against the logical clock whenever it is read"

        Design: Corner/calculations/overdue_days_due_today_zero_boundary
        """
        ctx = setup_action_plan(due_date="2026-02-01T00:00:00Z", entity_name="E")
        finding = ctx["finding"]
        mgr_h = make_manager_headers(ctx["mgr"]["id"])

        # At clock == due_date the plan is 0 days overdue: not counted.
        set_clock("2026-02-01T00:00:00Z")
        on_due_day = get_success_data(api.get_finding(finding["id"], mgr_h))
        assert on_due_day["open_overdue_action_count"] == 0

        # One day later the count flips to 1.
        set_clock("2026-02-02T00:00:00Z")
        next_day = get_success_data(api.get_finding(finding["id"], mgr_h))
        assert next_day["open_overdue_action_count"] == 1


class TestExtensionApprovalCascade:
    def test_extension_approval_two_hop_overdue_recompute(self, api, owner_headers, cae_headers):
        """PRD §3.7: "The approval then cascades: the plan's `due_date` is set
        to the `requested_due_date`, `extension_count` increments by one, and
        `cumulative_extended_days` increases by `approved_days`; and because an
        extended plan may cease to be overdue, the parent finding's
        `open_overdue_action_count` is recomputed as a second-level effect."

        Design: Difficulty/transitive_cascade/extension_approval_two_hop_overdue_recompute
        """
        ctx = setup_action_plan(due_date="2026-06-01T00:00:00Z", entity_name="Entity X")
        finding, ap = ctx["finding"], ctx["action_plan"]
        mgr_h = make_manager_headers(ctx["mgr"]["id"])

        # Advance the clock so the plan is 14 days overdue.
        set_clock("2026-06-15T00:00:00Z")
        before = get_success_data(api.get_finding(finding["id"], mgr_h))
        assert before["open_overdue_action_count"] == 1

        ext = get_success_data(api.create_extension_request(
            create_extension_request_payload(ap["id"],
                                             requested_due_date="2026-09-01T00:00:00Z",
                                             reason="Vendor dependency"),
            owner_headers,
        ))
        approved = get_success_data(api.approve_extension_request(ext["id"], cae_headers))
        assert approved["status"] == "APPROVED"
        assert approved["approved_days"] == 92  # 2026-06-01 -> 2026-09-01

        ap_after = get_success_data(api.get_action_plan(ap["id"], cae_headers))
        assert ap_after["due_date"] == "2026-09-01T00:00:00Z"
        assert ap_after["extension_count"] == 1
        assert ap_after["cumulative_extended_days"] == 92

        # Cascade L2: the due_date mutation recomputes the overdue count.
        after = get_success_data(api.get_finding(finding["id"], mgr_h))
        assert after["open_overdue_action_count"] == 0, (
            "The extended plan is no longer overdue at clock 2026-06-15"
        )

    def test_extension_denial_leaves_plan_untouched(self, api, owner_headers, cae_headers):
        """PRD §3.7: "Denial simply moves the request to `DENIED` and records
        `decided_by_user_id` from the caller."

        Design: Difficulty/transitive_cascade/extension_approval_two_hop_overdue_recompute
        """
        ctx = setup_action_plan(due_date="2026-06-01T00:00:00Z", entity_name="Entity X2")
        finding, ap = ctx["finding"], ctx["action_plan"]
        mgr_h = make_manager_headers(ctx["mgr"]["id"])

        set_clock("2026-06-15T00:00:00Z")
        before = get_success_data(api.get_finding(finding["id"], mgr_h))
        assert before["open_overdue_action_count"] == 1

        ext = get_success_data(api.create_extension_request(
            create_extension_request_payload(ap["id"],
                                             requested_due_date="2026-09-01T00:00:00Z",
                                             reason="Vendor dependency"),
            owner_headers,
        ))
        denied = get_success_data(api.deny_extension_request(ext["id"], cae_headers))
        assert denied["status"] == "DENIED"
        assert denied["decided_by_user_id"] == "cae-1"

        # Denial mutates nothing downstream: due date and overdue count persist.
        ap_after = get_success_data(api.get_action_plan(ap["id"], cae_headers))
        assert ap_after["due_date"] == "2026-06-01T00:00:00Z"
        assert ap_after["extension_count"] == 0
        after = get_success_data(api.get_finding(finding["id"], mgr_h))
        assert after["open_overdue_action_count"] == 1
