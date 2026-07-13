"""Automation journeys: the step graph, the ACTIVE/PAUSED cycle and enrollment advancement."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_subscriber,
    advance_epoch_to,
    assert_journey_enrollment,
    condition_step,
    create_audience,
    create_journey_payload,
    create_published_template,
    create_template,
    email_step,
    enrollments_of_journey,
    enrollments_of_subscriber,
    ops_run,
    provision_tenant,
    read_journey,
    read_subscriber,
    sends_of_journey,
    set_clock,
    setup_active_journey,
    unsubscribe,
    validate_error,
    validate_paginated,
    validate_success,
    wait_step,
)


class TestJourneyCreationAndActivation:
    def test_a_backward_branch_target_is_refused_at_creation(self, api):
        """PRD §3.10: "Both branch targets must be **strictly greater** than the branching step's
        own `step_index` — the graph is forward-only, so no enrollment can loop — and a journey
        whose steps violate that is refused at creation with `ERR_JOURNEY_STEP_ORDER`."

        Design: Corner/validations/backward_journey_step_index_rejected
        """
        tenant = provision_tenant(with_approver=False)
        audience = create_audience(tenant, double_optin_required=False)
        template = create_published_template(tenant)

        steps = [
            wait_step(0, 1),
            condition_step(1, condition_min_score=60, on_true=2, on_false=0),
            email_step(2, template["id"]),
        ]
        resp = api.create_journey(
            create_journey_payload(tenant.id, audience["id"], steps, name="Loopy"),
            tenant.author_headers,
        )
        validate_error(resp, ApiErrorId.ERR_JOURNEY_STEP_ORDER.value)

        journeys, _ = validate_paginated(
            api.list_journeys(tenant.author_headers, {"account_id": tenant.id})
        )
        assert journeys == []

    def test_activation_is_refused_while_an_email_step_points_at_a_draft_template(self, api):
        """PRD §3.10: "Activation moves a journey `DRAFT → ACTIVE` or, on a later pass,
        `PAUSED → ACTIVE`; activating an already-`ACTIVE` journey is refused with
        `ERR_INVALID_STATE`. Every step whose `kind` is `EMAIL` must reference a template that is
        `PUBLISHED` and belongs to the journey's own account, or activation is refused with
        `ERR_JOURNEY_TEMPLATE_INVALID`."

        Design: Corner/validations/journey_activate_with_draft_template_rejected
        """
        tenant = provision_tenant(with_approver=False)
        audience = create_audience(tenant, double_optin_required=False)
        template = create_template(tenant)  # still DRAFT
        journey = validate_success(
            api.create_journey(
                create_journey_payload(
                    tenant.id, audience["id"], [email_step(0, template["id"])], name="J"
                ),
                tenant.author_headers,
            ),
            201,
        )

        resp = api.activate_journey(journey["id"], tenant.author_headers)
        validate_error(resp, ApiErrorId.ERR_JOURNEY_TEMPLATE_INVALID.value)

        validate_success(api.publish_template(template["id"], tenant.author_headers))
        activated = validate_success(api.activate_journey(journey["id"], tenant.author_headers))
        assert activated["status"] == "ACTIVE", "the same request succeeds once the template is PUBLISHED"

    def test_pausing_a_draft_journey_is_refused(self, api):
        """PRD §3.10: "Pausing moves a journey `ACTIVE → PAUSED`, and pausing anything not `ACTIVE`
        is refused with `ERR_INVALID_STATE`. While paused, no trigger creates a new enrollment, and
        existing enrollments keep their `ACTIVE` status but are skipped by the operations epoch. The
        cycle between `ACTIVE` and `PAUSED` may repeat without bound."

        Design: Corner/state_machines/pause_draft_journey_rejected_invalid_state
        """
        tenant = provision_tenant(with_approver=False)
        audience = create_audience(tenant, double_optin_required=False)
        journey = validate_success(
            api.create_journey(
                create_journey_payload(tenant.id, audience["id"], [wait_step(0, 24)], name="J"),
                tenant.author_headers,
            ),
            201,
        )

        resp = api.pause_journey(journey["id"], tenant.author_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        assert read_journey(journey["id"])["status"] == "DRAFT"

    def test_activating_an_unknown_journey_is_a_not_found(self, api):
        """PRD §2.5: "Path identifiers resolve, left to right, the leftmost miss winning —
        `ERR_ACCOUNT_NOT_FOUND`, `ERR_AUDIENCE_NOT_FOUND`, `ERR_SUBSCRIBER_NOT_FOUND`,
        `ERR_TEMPLATE_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_JOURNEY_NOT_FOUND`,
        `ERR_IMPORT_JOB_NOT_FOUND` or `ERR_SEND_NOT_FOUND` as appropriate."

        Design: Corner/errors/err_journey_not_found_on_activate
        """
        tenant = provision_tenant(with_approver=False)
        resp = api.activate_journey(NON_EXISTENT_UUID, tenant.author_headers)
        validate_error(resp, ApiErrorId.ERR_JOURNEY_NOT_FOUND.value)


class TestPauseCycle:
    def test_paused_journey_is_skipped_and_resumes_on_reactivation(self, api):
        """PRD §3.10: "Pausing moves a journey `ACTIVE → PAUSED`, and pausing anything not `ACTIVE`
        is refused with `ERR_INVALID_STATE`. While paused, no trigger creates a new enrollment, and
        existing enrollments keep their `ACTIVE` status but are skipped by the operations epoch. The
        cycle between `ACTIVE` and `PAUSED` may repeat without bound."
        PRD §3.10: "Reactivating a paused journey does not shift any enrollment's `next_action_at`;
        the enrollments simply become eligible again."
        PRD §3.10: "A `WAIT` step sets `next_action_at` to the clock plus `wait_hours`, advances
        `current_step_index` by one, and **stops** the enrollment for this epoch."

        Design: Corner/state_machines/journey_active_pause_active_cycle_gates_ops_run
        """
        env = setup_active_journey(steps=[{"step_index": 0, "kind": "WAIT", "wait_hours": 24}])
        add_subscriber(env.audience_id, "s1@x.com", env.tenant.author_headers)
        validate_success(api.pause_journey(env.journey_id, env.tenant.author_headers))
        set_clock("2026-05-01T02:00:00Z")

        while_paused = ops_run()
        assert while_paused["enrollments_advanced"] == 0, "PAUSED journeys are skipped"

        reactivated = validate_success(
            api.activate_journey(env.journey_id, env.tenant.author_headers)
        )
        assert reactivated["status"] == "ACTIVE"

        while_active = ops_run()
        assert while_active["enrollments_advanced"] == 1

        enrollments = enrollments_of_journey(env.journey_id)
        assert_journey_enrollment(enrollments[0])
        assert enrollments[0]["current_step_index"] == 1
        assert enrollments[0]["status"] == "ACTIVE"
        assert read_journey(env.journey_id)["active_enrollment_count"] == 1


class TestEnrollmentAdvancement:
    def test_enrollment_completes_after_its_last_step_and_mints_a_journey_send(self, api):
        """PRD §3.10: "An `EMAIL` step mints a send carrying the journey's id in `journey_id`, a
        null `campaign_id`, the `subscriber_id`, `delivery_status` `QUEUED`, `engagement_status`
        `NOT_OPENED` and a null `variant_label`; it advances `current_step_index` by one and
        **continues** to the next step within the same epoch."
        PRD §3.10: "When `current_step_index` has advanced past the last step, the enrollment moves
        `ACTIVE → COMPLETED` and `active_enrollment_count` is recomputed."
        PRD §3.10: "Journey emails are included in the plan: they never touch `send_credit_balance`,
        `reserved_send_credits` or `consumed_send_credits`, though they *do* count as scored sends
        for the account's reputation once they are delivered or bounce."

        Design: Corner/state_machines/enrollment_completes_after_last_step_and_mints_journey_send
        """
        # step 0 = WAIT 1h, step 1 = EMAIL against the journey's published template.
        env = setup_active_journey(wait_hours=1)
        subscriber = add_subscriber(env.audience_id, "s1@x.com", env.tenant.author_headers)

        advance_epoch_to("2026-05-01T02:00:00Z")  # WAIT step runs, then stops
        summary = advance_epoch_to("2026-05-01T04:00:00Z")  # EMAIL step runs, then COMPLETED

        assert summary["sends_created"] == 1

        enrollments = enrollments_of_subscriber(subscriber["id"])
        assert enrollments[0]["status"] == "COMPLETED"
        assert enrollments[0]["current_step_index"] == 2

        after = read_journey(env.journey_id)
        assert after["active_enrollment_count"] == 0
        assert after["entered_count"] == 1

        journey_sends = sends_of_journey(env.journey_id)
        assert len(journey_sends) == 1
        assert journey_sends[0]["campaign_id"] is None
        assert journey_sends[0]["variant_label"] is None
        assert journey_sends[0]["delivery_status"] == "QUEUED"
        assert env.tenant.refresh()["send_credit_balance"] == 0, "journey emails consume no credits"

    def test_a_due_enrollment_of_an_unsubscribed_contact_is_suppressed(self, api):
        """PRD §3.10: "Before anything is executed, the contact's consent is re-checked: if the
        subscriber's `consent_state` is anything other than `CONFIRMED` — `UNSUBSCRIBED`, `CLEANED`,
        `ARCHIVED` or even back to `PENDING` — the enrollment moves `ACTIVE → SUPPRESSED`, no email
        is minted, the current step is not executed, and `active_enrollment_count` is recomputed."
        PRD §3.2: "Existing journey enrollments are not disturbed here either; as §3.10 explains,
        they are retired lazily, the next time they come due."

        Design: Difficulty/cross_entity_state_dependency/enrollment_advance_gated_on_subscriber_consent
        """
        env = setup_active_journey()  # step 0 = WAIT 24h, step 1 = EMAIL
        subscriber = add_subscriber(env.audience_id, "s1@x.com", env.tenant.author_headers)
        unsubscribe(subscriber)
        set_clock("2026-05-02T00:00:00Z")

        summary = ops_run()

        assert read_subscriber(subscriber["id"])["consent_state"] == "UNSUBSCRIBED"

        enrollments = enrollments_of_subscriber(subscriber["id"])
        assert len(enrollments) == 1
        assert enrollments[0]["status"] == "SUPPRESSED"
        assert enrollments[0]["current_step_index"] == 0, "the WAIT step never ran"
        assert summary["sends_created"] == 0

    def test_a_suppressed_enrollment_mints_no_journey_send(self, api):
        """PRD §3.10: "Before anything is executed, the contact's consent is re-checked: if the
        subscriber's `consent_state` is anything other than `CONFIRMED` — `UNSUBSCRIBED`, `CLEANED`,
        `ARCHIVED` or even back to `PENDING` — the enrollment moves `ACTIVE → SUPPRESSED`, no email
        is minted, the current step is not executed, and `active_enrollment_count` is recomputed."
        PRD §3.10: "Because an enrollment appeared, that journey's `active_enrollment_count` and
        `entered_count` are both recomputed — `active_enrollment_count` counting the journey's
        `ACTIVE` enrollments and `entered_count` counting all of its enrollments across every
        status."

        Design: Difficulty/cross_entity_state_dependency/enrollment_advance_gated_on_subscriber_consent
        """
        env = setup_active_journey()
        subscriber = add_subscriber(env.audience_id, "s1@x.com", env.tenant.author_headers)
        unsubscribe(subscriber)
        set_clock("2026-05-02T00:00:00Z")

        ops_run()

        journey = read_journey(env.journey_id)
        assert journey["active_enrollment_count"] == 0
        assert journey["entered_count"] == 1
        assert sends_of_journey(env.journey_id) == []
