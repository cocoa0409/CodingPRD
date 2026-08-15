"""Regulatory notification lifecycle (filing, OCC, supersession,
acknowledgement) and the start-abatement gates."""
from test_helpers import (
    ADMIN,
    REG,
    ApiErrorId,
    acknowledge_notification,
    add_supervisor,
    api_client,
    assert_notification,
    file_notification,
    get_project,
    list_project_notifications,
    make_supervisor_headers,
    set_clock,
    setup_acknowledged_notification,
    setup_assessed_project,
    setup_start_ready_project,
    setup_supervisor_coverage,
    setup_verified_containment,
    validate_error,
    validate_success,
)


class TestNotificationAcknowledgement:
    def test_acknowledge_already_acknowledged_rejected(self):
        """PRD section 3.3: "A `RegulatorClerk` then acknowledges the filing,
        moving it from `FILED` to `ACKNOWLEDGED` and stamping
        `acknowledged_at` with the current logical time."
        PRD section 2.10: "any attempt to act on a resource from a state that
        does not permit the transition — terminal or otherwise — is rejected
        with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/acknowledge_already_acknowledged_returns_invalid_state
        """
        ctx = setup_assessed_project(name="P-SM5")
        project = get_project(ctx["project"]["id"])
        notification = file_notification(
            project["id"], expected_project_version=project["version"])
        first = acknowledge_notification(notification["id"])
        assert first["acknowledged_at"].startswith("2026-08-01T00:00:00"), (
            f"acknowledged_at must be stamped from the logical clock default, "
            f"got {first['acknowledged_at']}"
        )
        resp = api_client.acknowledge_notification(notification["id"], REG)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        listing = list_project_notifications(project["id"])
        mine = [n for n in listing if n["id"] == notification["id"]]
        assert mine and mine[0]["acknowledged_at"] == first["acknowledged_at"], \
            "a rejected re-acknowledgement must not move acknowledged_at"

    def test_supervisor_cannot_acknowledge_notification(self):
        """PRD section 2.1: "`RegulatorClerk` — regulator staff. Acknowledges
        filed notifications."
        PRD section 2.1: "Beyond authentication, each endpoint restricts which
        roles may call it; a call from a role outside the permitted set is
        rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/supervisor_cannot_acknowledge_notification
        """
        ctx = setup_assessed_project(name="P-R3")
        supervisor = add_supervisor()
        notification = file_notification(ctx["project"]["id"])
        resp = api_client.acknowledge_notification(
            notification["id"], make_supervisor_headers(supervisor["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        listing = list_project_notifications(ctx["project"]["id"])
        mine = [n for n in listing if n["id"] == notification["id"]]
        assert mine and mine[0]["status"] == "FILED", \
            "notification must remain FILED after a rejected acknowledgement"


class TestNotificationSupersedeAndOcc:
    def test_second_filing_supersedes_and_recomputes_window(self):
        """PRD section 3.3: "Filing a new notification for a project that
        already has one in `FILED` or `ACKNOWLEDGED` status automatically
        transitions the earlier one to `SUPERSEDED`, and the filing itself
        increments the project's `version` by 1."
        PRD section 3.3: "Whenever the system speaks of a project's "latest"
        notification — including the notification listing of a project — it
        means the ordering by `filed_at` descending with ties broken by
        `created_at` descending."
        PRD section 3.3: "`waiting_days` is 3 for an `EMERGENCY` notification
        and 10 for `INITIAL` or `REVISION`, and `earliest_start_at` is
        `filed_at` plus that many calendar days of exactly 86,400 seconds
        each, computed to the second."

        Design: Corner/state_machines/notification_supersede_side_effect
        """
        ctx = setup_assessed_project(name="P-SM9")
        p_id = ctx["project"]["id"]
        v0 = get_project(p_id)["version"]
        n1 = file_notification(p_id, notification_type="INITIAL",
                               declared_acm_sq_ft=100,
                               expected_project_version=v0)
        acknowledge_notification(n1["id"])
        v1 = get_project(p_id)["version"]
        assert v1 == v0 + 1, "filing must increment the project version by 1"

        set_clock("2026-08-02T00:00:00Z")
        resp = api_client.create_notification(
            {
                "project_id": p_id,
                "notification_type": "REVISION",
                "declared_acm_sq_ft": 130,
                "expected_project_version": v1,
            },
            ADMIN,
        )
        n2 = validate_success(resp, expected_status=201)
        assert_notification(n2)
        assert n2["status"] == "FILED"
        assert n2["earliest_start_at"].startswith("2026-08-12T00:00:00"), (
            f"REVISION filed 2026-08-02 waits 10 days: expected earliest "
            f"2026-08-12T00:00:00Z, got {n2['earliest_start_at']}"
        )
        v2 = get_project(p_id)["version"]
        assert v2 == v1 + 1, "the second filing must also increment by 1"

        listing = list_project_notifications(p_id)
        assert len(listing) == 2
        assert listing[0]["id"] == n2["id"], \
            "latest notification (filed_at DESC) must sort first"
        assert listing[0]["status"] == "FILED"
        assert listing[1]["id"] == n1["id"]
        assert listing[1]["status"] == "SUPERSEDED", \
            "the earlier ACKNOWLEDGED notification must be superseded"

    def test_create_notification_stale_version_rejected(self):
        """PRD section 2.8: "A `POST /abatement/notifications` request must
        carry `expected_project_version` holding the `version` of the parent
        project as the client last observed it. If the project's current
        `version` has advanced beyond that value, the filing is rejected."
        PRD section 3.3: "if another write has advanced the project since the
        client last read it, the filing is rejected with `ERR_STALE_VERSION`
        (412) rather than silently superseding a notification the client never
        saw."

        Design: Corner/cross_cutting_layers/create_notification_stale_version_rejected
        """
        ctx = setup_assessed_project(name="P-L1")
        p_id = ctx["project"]["id"]
        v0 = get_project(p_id)["version"]
        n1 = file_notification(p_id, notification_type="INITIAL",
                               declared_acm_sq_ft=100,
                               expected_project_version=v0)
        assert n1["status"] == "FILED"

        resp = api_client.create_notification(
            {
                "project_id": p_id,
                "notification_type": "REVISION",
                "declared_acm_sq_ft": 120,
                "expected_project_version": v0,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        listing = list_project_notifications(p_id)
        assert len(listing) == 1, "no second notification may be persisted"
        assert listing[0]["id"] == n1["id"]
        assert listing[0]["status"] == "FILED", \
            "the first filing must remain FILED after the stale rejection"


class TestWaitingPeriod:
    def test_emergency_notification_three_day_wait(self):
        """PRD section 3.3: "At filing, the server stamps `filed_at` from the
        logical clock and computes the waiting window: `waiting_days` is 3 for
        an `EMERGENCY` notification and 10 for `INITIAL` or `REVISION`, and
        `earliest_start_at` is `filed_at` plus that many calendar days of
        exactly 86,400 seconds each, computed to the second."

        Design: Corner/calculations/emergency_notification_three_day_wait
        """
        ctx = setup_start_ready_project(
            name="P-C3", notification_type="EMERGENCY",
            base_abatement_cost_cents=1_000)
        notification = ctx["notification"]
        assert notification["waiting_days"] == 3, (
            f"EMERGENCY waits 3 days, got {notification['waiting_days']}"
        )
        assert notification["earliest_start_at"].startswith(
            "2026-08-04T00:00:00"), (
            f"filed 2026-08-01 + 3 days: expected 2026-08-04, "
            f"got {notification['earliest_start_at']}"
        )
        set_clock("2026-08-04T00:00:00Z")
        resp = api_client.start_abatement(ctx["project"]["id"], ADMIN)
        data = validate_success(resp)
        assert data["status"] == "IN_PROGRESS", \
            "start at exactly the 3-day boundary must succeed"

    def test_one_second_before_earliest_start_rejected(self):
        """PRD section 3.3: "the current logical time must be at or after that
        notification's `earliest_start_at` — equality is allowed — otherwise
        `ERR_WAITING_PERIOD_NOT_ELAPSED`".

        Design: Difficulty/boundary_precision_check/waiting_period_exact_earliest_start_allowed
        """
        ctx = setup_start_ready_project(name="P-BND2A")
        notification = ctx["notification"]
        assert notification["waiting_days"] == 10
        assert notification["earliest_start_at"].startswith(
            "2026-08-11T00:00:00"), (
            f"INITIAL filed 2026-08-01 + 10 days: expected 2026-08-11, "
            f"got {notification['earliest_start_at']}"
        )
        set_clock("2026-08-10T23:59:59Z")
        resp = api_client.start_abatement(ctx["project"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_WAITING_PERIOD_NOT_ELAPSED)

    def test_exactly_at_earliest_start_allowed(self):
        """PRD section 3.3: "the current logical time must be at or after that
        notification's `earliest_start_at` — equality is allowed — otherwise
        `ERR_WAITING_PERIOD_NOT_ELAPSED`".

        Design: Difficulty/boundary_precision_check/waiting_period_exact_earliest_start_allowed
        """
        ctx = setup_start_ready_project(name="P-BND2B")
        set_clock("2026-08-11T00:00:00Z")
        resp = api_client.start_abatement(ctx["project"]["id"], ADMIN)
        data = validate_success(resp)
        assert data["status"] == "IN_PROGRESS", \
            "start at exactly earliest_start_at must succeed (>= semantics)"


class TestStartAbatementGates:
    def test_start_with_unacknowledged_notification_rejected(self):
        """PRD section 3.3: "the gate evaluates four conditions in order: the
        project's latest notification must be `ACKNOWLEDGED` (a missing or
        unacknowledged filing fails with
        `ERR_NOTIFICATION_NOT_ACKNOWLEDGED`)".

        Design: Difficulty/cross_entity_state_dependency/start_abatement_requires_acknowledged_notification
        """
        # Start-ready chain, but the notification is NOT acknowledged.
        ctx = setup_assessed_project(name="P-XD1")
        ctx["supervisor"] = add_supervisor()
        ctx["containment"] = setup_verified_containment(
            ctx["project"]["id"], ctx["supervisor"]["id"])
        ctx["notification"] = file_notification(ctx["project"]["id"])
        ctx["assignment"] = setup_supervisor_coverage(
            ctx["project"]["id"], ctx["supervisor"]["id"])
        set_clock("2026-08-11T00:00:00Z")
        resp = api_client.start_abatement(ctx["project"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOTIFICATION_NOT_ACKNOWLEDGED)

    def test_start_after_acknowledgement_succeeds(self):
        """PRD section 3.3: "A `ContractorAdmin` triggers the transition from
        `ASSESSED` to `IN_PROGRESS`, and the gate evaluates four conditions in
        order: the project's latest notification must be `ACKNOWLEDGED` (a
        missing or unacknowledged filing fails with
        `ERR_NOTIFICATION_NOT_ACKNOWLEDGED`)".
        PRD section 3.3: "A successful start increments the project's
        `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/start_abatement_requires_acknowledged_notification
        """
        ctx = setup_start_ready_project(name="P-XD1B")
        set_clock("2026-08-11T00:00:00Z")
        # Re-read: the setup chain's notification filing already incremented
        # the project version once after ctx["project"] was last fetched.
        before = get_project(ctx["project"]["id"])["version"]
        resp = api_client.start_abatement(ctx["project"]["id"], ADMIN)
        data = validate_success(resp)
        assert data["status"] == "IN_PROGRESS"
        assert data["version"] == before + 1, \
            "a successful start must increment the project version by 1"

    def test_start_without_supervisor_coverage_rejected(self):
        """PRD section 3.3: "and supervisor coverage must exist — at least one
        crew assignment of the project with `role_on_site` `SUPERVISOR` in
        `SCHEDULED` status whose window covers the current instant, meaning
        its `start_at` is at or before now and its `end_at` is strictly after
        now — otherwise `ERR_SUPERVISOR_COVERAGE_REQUIRED`."

        Design: Corner/validations/start_without_supervisor_coverage_rejected
        """
        ctx = setup_assessed_project(name="P-V10", base_abatement_cost_cents=1_000)
        supervisor = add_supervisor()
        setup_verified_containment(ctx["project"]["id"], supervisor["id"])
        setup_acknowledged_notification(ctx["project"]["id"])
        # No crew assignment exists.
        set_clock("2026-08-11T00:00:00Z")
        resp = api_client.start_abatement(ctx["project"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SUPERVISOR_COVERAGE_REQUIRED)
