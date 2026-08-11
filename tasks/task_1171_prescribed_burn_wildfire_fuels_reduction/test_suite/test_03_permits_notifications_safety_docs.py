"""Permits, notifications, smoke approvals, contingency and ignition plans (PRD §3.3, §3.4)."""
from test_helpers import (
    ANY_READER_HEADERS,
    TEST_USERS,
    ApiErrorId,
    create_contingency_plan_payload,
    create_ignition_plan_payload,
    create_notification_payload,
    create_permit_payload,
    create_smoke_approval_payload,
    ctx_add_contingency,
    ctx_add_ignition,
    ctx_add_order,
    ctx_add_parcel,
    ctx_add_permit,
    ctx_add_plan,
    ctx_add_smoke,
    ctx_author,
    ctx_landowner,
    ctx_reviewer,
    reject_reason_payload,
    set_clock_payload,
    setup_approved_plan_ctx,
    setup_burn_ready_ctx,
    setup_registry,
    validate_error,
    validate_success,
)
from test_helpers import (
    ctx_add_execution,
    validate_paginated,
)

ADMIN = TEST_USERS["admin_headers"]
AQO = TEST_USERS["aqo_headers"]


def _setup_two_approved_plans(api, acres_a, acres_b, airshed_cap=500):
    """Two GRASS/FLAT parcels in airshed ASH-1, each with an APPROVED plan."""
    ctx = setup_registry(airshed_cap=airshed_cap)
    for key, acres in (("a", acres_a), ("b", acres_b)):
        ctx_add_parcel(ctx, key=f"parcel_{key}", name=f"P{key.upper()}", acreage=400,
                       fuel_model="GRASS", slope_class="FLAT", drought_index=5)
        ctx_add_plan(ctx, key=f"plan_{key}", parcel_key=f"parcel_{key}", approve=True,
                     planned_acres=acres,
                     planned_window_start="2026-05-10", planned_window_end="2026-05-20",
                     treatment_lines=[{"category": "BROADCAST", "rate_class": "GRASS",
                                       "acres": acres}])
    return ctx


class TestPermitSuspendReinstateLoop:
    def test_permit_suspend_reinstate_loop(self, api):
        """PRD §3.3: "Suspension — by a reviewer, or by the system when the plan is
        superseded or an execution enters `WILDFIRE_RESPONSE` — requires `ISSUED`
        (`ERR_PERMIT_NOT_ISSUED`), moves the permit to `SUSPENDED`"
        PRD §3.3: "Reinstatement requires the permit to be `SUSPENDED`
        (`ERR_PERMIT_NOT_SUSPENDED`) and the plan to be `APPROVED`
        (`ERR_PLAN_NOT_APPROVED`), and returns it to `ISSUED`."

        Design: Difficulty/non_linear_state_machine/permit_suspend_reinstate_loop
        """
        ctx = setup_approved_plan_ctx()
        ctx_add_contingency(ctx)
        permit = ctx_add_permit(ctx, notifications_required=1)
        assert permit["status"] == "ISSUED"
        suspended = validate_success(api.suspend_permit(permit["id"], ctx_reviewer(ctx)), 200)
        assert suspended["status"] == "SUSPENDED"
        reinstated = validate_success(api.reinstate_permit(permit["id"], ctx_reviewer(ctx)), 200)
        assert reinstated["status"] == "ISSUED"

    def test_permit_suspend_and_reinstate_from_wrong_states(self, api):
        """PRD §3.3: "Suspension — by a reviewer, or by the system when the plan is
        superseded or an execution enters `WILDFIRE_RESPONSE` — requires `ISSUED`
        (`ERR_PERMIT_NOT_ISSUED`)"
        PRD §3.3: "Reinstatement requires the permit to be `SUSPENDED`
        (`ERR_PERMIT_NOT_SUSPENDED`)"

        Design: Difficulty/non_linear_state_machine/permit_suspend_reinstate_loop
        """
        ctx = setup_approved_plan_ctx()
        ctx_add_contingency(ctx)
        permit = ctx_add_permit(ctx, notifications_required=0, issue=False)
        # UNDER_REVIEW: suspend is not legal
        validate_error(api.suspend_permit(permit["id"], ctx_reviewer(ctx)),
                       ApiErrorId.ERR_PERMIT_NOT_ISSUED)
        issued = validate_success(api.issue_permit(permit["id"], ctx_reviewer(ctx)), 200)
        assert issued["status"] == "ISSUED"
        # ISSUED: reinstate is not legal
        validate_error(api.reinstate_permit(permit["id"], ctx_reviewer(ctx)),
                       ApiErrorId.ERR_PERMIT_NOT_SUSPENDED)


class TestPermitIssuePlanGate:
    def test_permit_issue_requires_plan_approved(self, api):
        """PRD §3.3: "Issuance is a six-gate decision by an `AgencyReviewer`. The permit
        must be `UNDER_REVIEW` (`ERR_PERMIT_NOT_UNDER_REVIEW`); the reviewer's identity
        must differ from the plan's `author_boss_id`
        (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`); the plan must be `APPROVED`
        (`ERR_PLAN_NOT_APPROVED`)"

        Design: Difficulty/cross_entity_state_dependency/permit_issue_requires_plan_approved
        """
        ctx = setup_registry()
        ctx_add_parcel(ctx)
        plan = ctx_add_plan(ctx, submit=True)  # SUBMITTED, never approved
        permit = validate_success(api.create_permit(
            plan["id"], create_permit_payload(notifications_required=0),
            ctx_author(ctx)), 201)
        assert permit["status"] == "UNDER_REVIEW"
        validate_error(api.issue_permit(permit["id"], ctx_reviewer(ctx)),
                       ApiErrorId.ERR_PLAN_NOT_APPROVED)
        after = validate_success(api.get_permit(permit["id"], ANY_READER_HEADERS), 200)
        assert after["status"] == "UNDER_REVIEW"

    def test_permit_issue_succeeds_once_plan_approved(self, api):
        """PRD §3.3: "Issuance stamps `issued_by_boss_id` and moves the permit to
        `ISSUED`."

        Design: Difficulty/cross_entity_state_dependency/permit_issue_requires_plan_approved
        """
        ctx = setup_registry()
        ctx_add_parcel(ctx)
        plan = ctx_add_plan(ctx, submit=True)
        permit = validate_success(api.create_permit(
            plan["id"], create_permit_payload(notifications_required=0),
            ctx_author(ctx)), 201)
        # Approve the plan and satisfy the remaining gates, then issue succeeds.
        ctx["plan"] = validate_success(api.approve_plan(plan["id"], ctx_reviewer(ctx)), 200)
        ctx_add_contingency(ctx)
        issued = validate_success(api.issue_permit(permit["id"], ctx_reviewer(ctx)), 200)
        assert issued["status"] == "ISSUED"
        assert issued["issued_by_boss_id"] == ctx["boss_r"]["id"]


class TestNotificationGateBoundary:
    def test_notifications_exactly_required_count_issuable(self, api):
        """PRD §3.3: "`notifications_completed` must have reached `notifications_required`
        (`ERR_NOTIFICATIONS_INCOMPLETE`)"
        PRD §3.3: "When the neighbor has actually been reached, the author confirms the
        notification — possible only while `REQUESTED`, else
        `ERR_NOTIFICATION_NOT_REQUESTED` — which stamps `confirmed_at` with the current
        clock, moves it to `CONFIRMED`, and recomputes two rollups on the permit:
        `notifications_completed`, the count of its `CONFIRMED` notifications"

        Design: Difficulty/boundary_precision_check/notifications_exactly_required_count_issuable
        """
        ctx = setup_approved_plan_ctx()
        ctx_add_contingency(ctx)
        permit = ctx_add_permit(ctx, notifications_required=2, issue=False)
        issued = validate_success(api.issue_permit(permit["id"], ctx_reviewer(ctx)), 200)
        assert issued["notifications_completed"] == 2
        assert issued["status"] == "ISSUED"

    def test_notifications_below_required_count_rejected(self, api):
        """PRD §3.3: "`notifications_completed` must have reached `notifications_required`
        (`ERR_NOTIFICATIONS_INCOMPLETE`)"

        Design: Difficulty/boundary_precision_check/notifications_exactly_required_count_issuable
        """
        ctx = setup_approved_plan_ctx()
        ctx_add_contingency(ctx)
        permit = ctx_add_permit(ctx, notifications_required=2, confirm_count=1, issue=False)
        validate_error(api.issue_permit(permit["id"], ctx_reviewer(ctx)),
                       ApiErrorId.ERR_NOTIFICATIONS_INCOMPLETE)
        after = validate_success(api.get_permit(permit["id"], ANY_READER_HEADERS), 200)
        assert after["status"] == "UNDER_REVIEW"


class TestAirshedCapacity:
    def test_airshed_capacity_exact_cap_passes(self, api):
        """PRD §3.3: "the sum of `requested_acres` across the *other* approvals in
        `APPROVED` or `CONDITIONALLY_APPROVED` for the same `airshed_id` and the same
        `requested_burn_date`, plus this request's `requested_acres`, must not exceed the
        association's `airshed_daily_acres_cap` — a total exactly equal to the cap passes"

        Design: Difficulty/boundary_precision_check/airshed_capacity_exact_cap_passes
        """
        ctx = _setup_two_approved_plans(api, 300, 200)
        smoke_a = validate_success(api.create_smoke_approval(
            ctx["plan_a"]["id"], create_smoke_approval_payload(requested_acres=300),
            ctx_author(ctx)), 201)
        validate_success(api.decide_smoke_approval(smoke_a["id"], {"decision": "APPROVED"}, AQO), 200)
        smoke_b = validate_success(api.create_smoke_approval(
            ctx["plan_b"]["id"], create_smoke_approval_payload(requested_acres=200),
            ctx_author(ctx)), 201)
        decided = validate_success(
            api.decide_smoke_approval(smoke_b["id"], {"decision": "APPROVED"}, AQO), 200)
        assert decided["status"] == "APPROVED"  # 300 + 200 == 500 == cap: inclusive pass

    def test_airshed_capacity_one_over_cap_rejected(self, api):
        """PRD §3.3: "an excess is rejected with `ERR_AIRSHED_CAPACITY_EXCEEDED`"

        Design: Difficulty/boundary_precision_check/airshed_capacity_exact_cap_passes
        """
        ctx = _setup_two_approved_plans(api, 300, 200)
        smoke_a = validate_success(api.create_smoke_approval(
            ctx["plan_a"]["id"], create_smoke_approval_payload(requested_acres=300),
            ctx_author(ctx)), 201)
        validate_success(api.decide_smoke_approval(smoke_a["id"], {"decision": "APPROVED"}, AQO), 200)
        smoke_b = validate_success(api.create_smoke_approval(
            ctx["plan_b"]["id"], create_smoke_approval_payload(requested_acres=200),
            ctx_author(ctx)), 201)
        validate_success(api.decide_smoke_approval(smoke_b["id"], {"decision": "APPROVED"}, AQO), 200)
        # A third request of 1 acre pushes the same airshed/date over the 500 cap
        ctx_add_parcel(ctx, key="parcel_c", name="PC", acreage=400, fuel_model="GRASS",
                       slope_class="FLAT", drought_index=5)
        ctx_add_plan(ctx, key="plan_c", parcel_key="parcel_c", approve=True,
                     planned_acres=50,
                     treatment_lines=[{"category": "BROADCAST", "rate_class": "GRASS",
                                       "acres": 50}])
        smoke_c = validate_success(api.create_smoke_approval(
            ctx["plan_c"]["id"], create_smoke_approval_payload(requested_acres=1),
            ctx_author(ctx)), 201)
        validate_error(api.decide_smoke_approval(smoke_c["id"], {"decision": "APPROVED"}, AQO),
                       ApiErrorId.ERR_AIRSHED_CAPACITY_EXCEEDED)
        after = validate_success(api.get_smoke_approval(smoke_c["id"], ANY_READER_HEADERS), 200)
        assert after["status"] == "SUBMITTED"

    def test_airshed_aggregate_capacity_rejects_overflow(self, api):
        """PRD §3.3: "the sum of `requested_acres` across the *other* approvals in
        `APPROVED` or `CONDITIONALLY_APPROVED` for the same `airshed_id` and the same
        `requested_burn_date`, plus this request's `requested_acres`, must not exceed the
        association's `airshed_daily_acres_cap` — a total exactly equal to the cap passes,
        and an excess is rejected with `ERR_AIRSHED_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/airshed_aggregate_capacity_rejects_overflow
        """
        ctx = _setup_two_approved_plans(api, 300, 201)
        smoke_a = validate_success(api.create_smoke_approval(
            ctx["plan_a"]["id"], create_smoke_approval_payload(requested_acres=300),
            ctx_author(ctx)), 201)
        # A CONDITIONALLY_APPROVED approval consumes the same capacity
        validate_success(api.decide_smoke_approval(
            smoke_a["id"], {"decision": "CONDITIONALLY_APPROVED"}, AQO), 200)
        smoke_b = validate_success(api.create_smoke_approval(
            ctx["plan_b"]["id"], create_smoke_approval_payload(requested_acres=201),
            ctx_author(ctx)), 201)
        validate_error(api.decide_smoke_approval(smoke_b["id"], {"decision": "APPROVED"}, AQO),
                       ApiErrorId.ERR_AIRSHED_CAPACITY_EXCEEDED)
        after = validate_success(api.get_smoke_approval(smoke_b["id"], ANY_READER_HEADERS), 200)
        assert after["status"] == "SUBMITTED"

    def test_airshed_denial_runs_no_capacity_check(self, api):
        """PRD §3.3: "Denial runs no capacity check."

        Design: Difficulty/resource_temporal_overlap/airshed_aggregate_capacity_rejects_overflow
        """
        ctx = _setup_two_approved_plans(api, 300, 201)
        smoke_a = validate_success(api.create_smoke_approval(
            ctx["plan_a"]["id"], create_smoke_approval_payload(requested_acres=300),
            ctx_author(ctx)), 201)
        validate_success(api.decide_smoke_approval(smoke_a["id"], {"decision": "APPROVED"}, AQO), 200)
        smoke_b = validate_success(api.create_smoke_approval(
            ctx["plan_b"]["id"], create_smoke_approval_payload(requested_acres=201),
            ctx_author(ctx)), 201)
        denied = validate_success(
            api.decide_smoke_approval(smoke_b["id"], {"decision": "DENIED"}, AQO), 200)
        assert denied["status"] == "DENIED"  # over cap, but denial never checks capacity


class TestPermitNotificationSmokeErrors:
    def test_permit_issue_twice_rejected(self, api):
        """PRD §3.3: "The permit must be `UNDER_REVIEW` (`ERR_PERMIT_NOT_UNDER_REVIEW`)"

        Design: Corner/state_machines/permit_issue_twice_rejected
        """
        ctx = setup_approved_plan_ctx()
        ctx_add_contingency(ctx)
        permit = ctx_add_permit(ctx, notifications_required=1)
        assert permit["status"] == "ISSUED"
        validate_error(api.issue_permit(permit["id"], ctx_reviewer(ctx)),
                       ApiErrorId.ERR_PERMIT_NOT_UNDER_REVIEW)

    def test_second_permit_rejected_while_open(self, api):
        """PRD §3.3: "a plan may have at most one permit open — in `UNDER_REVIEW`,
        `ISSUED`, or `SUSPENDED` — with duplicates rejected as `ERR_PERMIT_ALREADY_OPEN`."

        Design: Corner/errors/second_permit_rejected_while_open
        """
        ctx = setup_registry()
        ctx_add_parcel(ctx)
        plan = ctx_add_plan(ctx, submit=True)
        validate_success(api.create_permit(
            plan["id"], create_permit_payload(notifications_required=1), ctx_author(ctx)), 201)
        validate_error(api.create_permit(
            plan["id"], create_permit_payload(notifications_required=1), ctx_author(ctx)),
            ApiErrorId.ERR_PERMIT_ALREADY_OPEN)

    def test_notification_confirm_twice_rejected(self, api):
        """PRD §3.3: "the author confirms the notification — possible only while
        `REQUESTED`, else `ERR_NOTIFICATION_NOT_REQUESTED`"

        Design: Corner/errors/notification_confirm_twice_rejected
        """
        ctx = setup_registry()
        ctx_add_parcel(ctx)
        plan = ctx_add_plan(ctx, submit=True)
        permit = validate_success(api.create_permit(
            plan["id"], create_permit_payload(notifications_required=1), ctx_author(ctx)), 201)
        notif = validate_success(api.create_notification(
            permit["id"], create_notification_payload(), ctx_author(ctx)), 201)
        validate_success(api.confirm_notification(notif["id"], ctx_author(ctx)), 200)
        validate_error(api.confirm_notification(notif["id"], ctx_author(ctx)),
                       ApiErrorId.ERR_NOTIFICATION_NOT_REQUESTED)

    def test_smoke_double_decide_rejected(self, api):
        """PRD §3.3: "deciding anything not `SUBMITTED` fails with
        `ERR_SMOKE_NOT_SUBMITTED`."

        Design: Corner/errors/smoke_double_decide_rejected
        """
        ctx = setup_approved_plan_ctx()
        smoke = ctx_add_smoke(ctx, decision="DENIED")
        assert smoke["status"] == "DENIED"
        validate_error(api.decide_smoke_approval(smoke["id"], {"decision": "APPROVED"}, AQO),
                       ApiErrorId.ERR_SMOKE_NOT_SUBMITTED)

    def test_aqo_cannot_issue_permit(self, api):
        """PRD §2.1: "A request whose role is not authorized for the target endpoint is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/rbac/aqo_cannot_issue_permit
        """
        ctx = setup_registry()
        ctx_add_parcel(ctx)
        plan = ctx_add_plan(ctx, submit=True)
        permit = validate_success(api.create_permit(
            plan["id"], create_permit_payload(notifications_required=0), ctx_author(ctx)), 201)
        validate_error(api.issue_permit(permit["id"], AQO),
                       ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)


class TestNotificationLeadTime:
    def test_notification_lead_time_exactly_48h_passes(self, api):
        """PRD §3.6: "the forty-eight-hour neighbor lead time must have elapsed:
        `notified_completed_at` must be set, and the current clock must be at least 48
        hours past it — exactly 48 hours and zero seconds passes — else
        `ERR_NOTIFICATION_LEAD_TIME_UNMET`."

        Design: Corner/calculations/notification_lead_time_exactly_48h_passes
        """
        ctx = setup_approved_plan_ctx()
        ctx_add_contingency(ctx)
        ctx_add_ignition(ctx)
        # One notification, confirmed while the clock reads 2026-05-10T08:00Z
        permit = validate_success(api.create_permit(
            ctx["plan"]["id"], create_permit_payload(notifications_required=1),
            ctx_author(ctx)), 201)
        notif = validate_success(api.create_notification(
            permit["id"], create_notification_payload(), ctx_author(ctx)), 201)
        validate_success(api.set_clock(set_clock_payload("2026-05-10T08:00:00Z"), ADMIN), 200)
        validate_success(api.confirm_notification(notif["id"], ctx_author(ctx)), 200)
        validate_success(api.issue_permit(permit["id"], ctx_reviewer(ctx)), 200)
        ctx_add_smoke(ctx, date="2026-05-12")
        ctx_add_order(ctx, fill="full")
        ctx_add_execution(ctx, date="2026-05-12")
        # Brief at exactly notified_completed_at + 48h00m00s
        validate_success(api.set_clock(set_clock_payload("2026-05-12T08:00:00Z"), ADMIN), 200)
        briefed = validate_success(api.brief_execution(ctx["execution"]["id"], ctx_author(ctx)), 200)
        assert briefed["phase"] == "BRIEFED"


class TestContingencyPlanLoop:
    def test_contingency_reject_revise_loop(self, api):
        """PRD §3.4: "The reviewer may instead reject it with a `reason`, moving it to
        `REJECTED`, and the author alone may return a `REJECTED` document to `DRAFT` for
        rework (`ERR_CONTINGENCY_NOT_REJECTED` from any other state,
        `ERR_NOT_RESOURCE_OWNER` for non-authors). The reject-revise loop may repeat as
        often as needed."

        Design: Difficulty/non_linear_state_machine/contingency_reject_revise_loop
        """
        ctx = setup_approved_plan_ctx()
        cont = ctx_add_contingency(ctx, accept=False)
        assert cont["status"] == "DRAFT"
        rejected = validate_success(api.reject_contingency_plan(
            cont["id"], reject_reason_payload("insufficient water"), ctx_reviewer(ctx)), 200)
        assert rejected["status"] == "REJECTED"
        revised = validate_success(api.revise_contingency_plan(cont["id"], ctx_author(ctx)), 200)
        assert revised["status"] == "DRAFT"
        accepted = validate_success(api.accept_contingency_plan(cont["id"], ctx_reviewer(ctx)), 200)
        assert accepted["status"] == "ACCEPTED"

    def test_contingency_loop_rejects_wrong_states(self, api):
        """PRD §3.4: "An `AgencyReviewer` accepts a `DRAFT` contingency plan — anything
        else earns `ERR_CONTINGENCY_NOT_DRAFT`"
        PRD §3.4: "the author alone may return a `REJECTED` document to `DRAFT` for rework
        (`ERR_CONTINGENCY_NOT_REJECTED` from any other state, `ERR_NOT_RESOURCE_OWNER` for
        non-authors)."

        Design: Difficulty/non_linear_state_machine/contingency_reject_revise_loop
        """
        ctx = setup_approved_plan_ctx()
        cont = ctx_add_contingency(ctx, accept=False)
        # revise requires REJECTED
        validate_error(api.revise_contingency_plan(cont["id"], ctx_author(ctx)),
                       ApiErrorId.ERR_CONTINGENCY_NOT_REJECTED)
        validate_success(api.reject_contingency_plan(
            cont["id"], reject_reason_payload("weak water plan"), ctx_reviewer(ctx)), 200)
        # accept/reject require DRAFT: the plan is now REJECTED
        validate_error(api.accept_contingency_plan(cont["id"], ctx_reviewer(ctx)),
                       ApiErrorId.ERR_CONTINGENCY_NOT_DRAFT)

    def test_contingency_second_accept_rejected(self, api):
        """PRD §3.4: "at most one contingency plan per burn plan may be `ACCEPTED`, a
        second acceptance rejected with `ERR_CONTINGENCY_ALREADY_ACCEPTED`."

        Design: Corner/errors/contingency_second_accept_rejected
        """
        ctx = setup_approved_plan_ctx()
        c1 = ctx_add_contingency(ctx, accept=False)
        c2 = validate_success(api.create_contingency_plan(
            ctx["plan"]["id"],
            create_contingency_plan_payload(escape_trigger_points="smoke on road"),
            ctx_author(ctx)), 201)
        validate_success(api.accept_contingency_plan(c1["id"], ctx_reviewer(ctx)), 200)
        validate_error(api.accept_contingency_plan(c2["id"], ctx_reviewer(ctx)),
                       ApiErrorId.ERR_CONTINGENCY_ALREADY_ACCEPTED)
        after = validate_success(api.get_contingency_plan(c2["id"], ANY_READER_HEADERS), 200)
        assert after["status"] == "DRAFT"


class TestIgnitionPlanOCC:
    def test_occ_ignition_plan_create_stale_plan_version(self, api):
        """PRD §2.8: "Because filing an ignition plan legitimately supersedes the prior
        ignition plan and advances the burn plan's own `version`, a second filing carrying
        an older value is stale; it is rejected with `ERR_STALE_VERSION` and HTTP status
        412."
        PRD §3.4: "Filing supersedes every prior ignition plan on the same plan in
        `DRAFT`, `ACCEPTED`, or `REJECTED`, moving those to `SUPERSEDED` without a version
        bump"

        Design: Corner/cross_cutting_layers/occ_ignition_plan_create_stale_plan_version
        """
        ctx = setup_approved_plan_ctx()
        plan_v = ctx["plan"]["version"]
        ign1 = validate_success(api.create_ignition_plan(
            ctx["plan"]["id"], create_ignition_plan_payload(plan_v), ctx_author(ctx)), 201)
        # ign1's filing advanced the plan version; the captured token is now stale
        validate_error(api.create_ignition_plan(
            ctx["plan"]["id"],
            create_ignition_plan_payload(plan_v, ignition_method="AERIAL",
                                         test_fire_required=False,
                                         steps=[{"step_index": 1, "zone_label": "south",
                                                 "technique": "sphere"}]),
            ctx_author(ctx)), ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        # A fresh write supersedes ign1
        plan_now = validate_success(api.get_burn_plan(ctx["plan"]["id"], ANY_READER_HEADERS), 200)
        ign2 = validate_success(api.create_ignition_plan(
            ctx["plan"]["id"],
            create_ignition_plan_payload(plan_now["version"], ignition_method="AERIAL",
                                         test_fire_required=False,
                                         steps=[{"step_index": 1, "zone_label": "south",
                                                 "technique": "sphere"}]),
            ctx_author(ctx)), 201)
        data, meta = validate_paginated(
            api.list_plan_ignition_plans(ctx["plan"]["id"], ANY_READER_HEADERS))
        assert meta["total_count"] == 2
        assert data[0]["id"] == ign1["id"] and data[0]["status"] == "SUPERSEDED"
        assert data[1]["id"] == ign2["id"] and data[1]["status"] == "DRAFT"
