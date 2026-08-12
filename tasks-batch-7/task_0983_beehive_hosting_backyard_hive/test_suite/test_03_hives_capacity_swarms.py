"""Hive placement: capacity boundary, site blocking, splits, removal
completion, and the swarm-response flow."""
import pytest

from test_helpers import (
    TEST_DEFAULTS,
    TEST_USERS,
    api_client,
    assert_hive,
    complete_course,
    create_active_host,
    create_and_verify_inspection,
    create_hive_payload,
    create_incident_payload,
    create_site_for,
    decide_removal,
    get_success_data,
    make_beekeeper_headers,
    make_host_headers,
    make_manager_headers,
    record_inspection,
    report_swarm,
    request_removal,
    resolve_incident_payload,
    schedule_removal_payload,
    setup_hive_scenario,
    setup_signed_agreement,
    sign_agreement_for,
    create_agreement_for,
    submit_inspection,
    validate_error,
    validate_paginated,
    validate_success,
    verify_inspection,
)

MGR = TEST_USERS["manager_headers"]
OPS = TEST_USERS["ops_headers"]


class TestSiteCapacityBoundary:
    def test_third_install_rejected_at_full_capacity(self, api, ops_headers):
        """PRD §2.8: "Adding a new hive — by installation, split, or swarm
        capture — requires occupancy to be strictly below
        `effective_capacity_hives`; when occupancy equals capacity the addition
        is rejected with `ERR_SITE_CAPACITY_EXCEEDED`, so the equality boundary
        is inclusive-reject."

        Design: Difficulty/boundary_precision_check/site_capacity_equal_boundary_blocks
        """
        ctx = setup_hive_scenario()
        # Second hive fills the site: occupancy 2 == effective capacity 2.
        validate_success(
            api.create_hive(
                create_hive_payload(ctx["site"]["id"], ctx["agreement"]["id"]),
                MGR,
            ),
            201,
        )
        res = api.create_hive(
            create_hive_payload(ctx["site"]["id"], ctx["agreement"]["id"]),
            MGR,
        )
        validate_error(res, "ERR_SITE_CAPACITY_EXCEEDED")

    def test_adv201_bonus_lifts_capacity_and_retry_succeeds(self, api, ops_headers):
        """PRD §2.8: "A site's `base_capacity_hives` (at least 1, defaulting to
        2 when omitted) is augmented by bonuses to yield
        `effective_capacity_hives`: one additional hive if the host's
        non-`CANCELLED` subscription plan is `PREMIUM`, and one further hive if
        the host holds a `COMPLETED` `ADV-201` enrollment."

        Design: Difficulty/boundary_precision_check/site_capacity_equal_boundary_blocks
        """
        ctx = setup_hive_scenario()
        host = ctx["host"]
        validate_success(
            api.create_hive(
                create_hive_payload(ctx["site"]["id"], ctx["agreement"]["id"]),
                MGR,
            ),
            201,
        )
        validate_error(
            api.create_hive(
                create_hive_payload(ctx["site"]["id"], ctx["agreement"]["id"]),
                MGR,
            ),
            "ERR_SITE_CAPACITY_EXCEEDED",
        )
        # ADV-201 requires a COMPLETED HOST-101 first (PRD §3.9).
        complete_course(host, "HOST-101", quiz_score=85)
        complete_course(host, "ADV-201", quiz_score=92)
        site = validate_success(api.get_site(ctx["site"]["id"], ops_headers))
        assert site["effective_capacity_hives"] == 3, "base 2 + 1 for ADV-201"
        third = validate_success(
            api.create_hive(
                create_hive_payload(ctx["site"]["id"], ctx["agreement"]["id"]),
                MGR,
            ),
            201,
        )
        assert third["lifecycle_status"] == "ACTIVE"


class TestSiteBlocking:
    def test_severe_incident_blocks_site_and_install_fails(self, api, ops_headers):
        """PRD §3.1: "reporting a `SEVERE` incident on the site blocks it
        immediately."
        PRD §3.1: "While `BLOCKED`, hive installs, splits, and swarm captures
        on the site are rejected with `ERR_SITE_BLOCKED`."

        Design: Difficulty/cross_entity_state_dependency/hive_install_blocked_when_site_blocked
        """
        ctx = setup_hive_scenario()
        host, site = ctx["host"], ctx["site"]
        validate_success(
            api.create_incident(
                create_incident_payload(site["id"], severity="SEVERE"),
                make_host_headers(host["id"]),
            ),
            201,
        )
        site_now = validate_success(api.get_site(site["id"], ops_headers))
        assert site_now["status"] == "BLOCKED", "SEVERE report auto-blocks"
        res = api.create_hive(
            create_hive_payload(site["id"], ctx["agreement"]["id"]), MGR,
        )
        validate_error(res, "ERR_SITE_BLOCKED")

    def test_install_succeeds_after_resolve_and_unblock(self, api):
        """PRD §3.1: "An `ApiaryManager` restores a `BLOCKED` site to `CLEAR`
        only once no incident on the site remains in `REPORTED` status."

        Design: Difficulty/cross_entity_state_dependency/hive_install_blocked_when_site_blocked
        """
        ctx = setup_hive_scenario()
        host, site = ctx["host"], ctx["site"]
        incident = validate_success(
            api.create_incident(
                create_incident_payload(site["id"], severity="SEVERE"),
                make_host_headers(host["id"]),
            ),
            201,
        )
        validate_error(
            api.create_hive(
                create_hive_payload(site["id"], ctx["agreement"]["id"]), MGR,
            ),
            "ERR_SITE_BLOCKED",
        )
        validate_success(
            api.resolve_incident(
                incident["id"], resolve_incident_payload("NO_FAULT"), MGR,
            ),
            200,
        )
        unblocked = validate_success(api.unblock_site(site["id"], MGR), 200)
        assert unblocked["status"] == "CLEAR"
        hive = validate_success(
            api.create_hive(
                create_hive_payload(site["id"], ctx["agreement"]["id"]), MGR,
            ),
            201,
        )
        assert_hive(hive)


class TestHiveSplit:
    def test_split_creates_child_with_lineage(self, api, ops_headers):
        """PRD §3.3: "splitting a hive creates a child hive on the same site
        under the same agreement, with the child's `parent_hive_id` set to the
        split parent's `id`, lifecycle `ACTIVE`, and posture `STABLE`."
        PRD §3.3: "hive listings accept optional filters on `site_id`,
        `agreement_id`, `parent_hive_id`, and `source_swarm_event_id`."

        Design: Corner/endpoints/hive_split_requires_strong_posture
        """
        ctx = setup_hive_scenario(site_overrides={"base_capacity_hives": 3})
        parent = ctx["hive"]
        child = validate_success(api.split_hive(parent["id"], MGR), 201)
        assert child["parent_hive_id"] == parent["id"]
        assert child["lifecycle_status"] == "ACTIVE"
        assert child["posture"] == "STABLE", (
            "child starts STABLE until its own verified inspection"
        )
        assert child["site_id"] == ctx["site"]["id"]
        assert child["agreement_id"] == ctx["agreement"]["id"]
        data, meta = validate_paginated(
            api.list_hives(ops_headers, params={"parent_hive_id": parent["id"]}),
        )
        assert [h["id"] for h in data] == [child["id"]], (
            "lineage filter returns exactly the child"
        )


class TestRemovalCompletion:
    def test_completion_removes_hive_and_frees_capacity(self, api, ops_headers):
        """PRD §3.8: "The scheduled job is later completed by a beekeeper,
        which stamps `completed_at`, moves the job to `COMPLETED`, and
        transitions the hive to `REMOVED`, freeing one unit of occupancy."

        Design: Corner/state_machines/removal_completion_removes_hive_and_frees_capacity
        """
        ctx = setup_hive_scenario()
        host, site, agreement = ctx["host"], ctx["site"], ctx["agreement"]
        hive2 = validate_success(
            api.create_hive(create_hive_payload(site["id"], agreement["id"]), MGR),
            201,
        )  # occupancy now 2 == capacity 2
        job = request_removal(host, ctx["hive"]["id"], reason="EXIT")
        decide_removal(job["id"], "APPROVE")
        validate_success(
            api.schedule_removal_job(
                job["id"],
                schedule_removal_payload("2026-06-10T09:00:00Z", "crew-9"),
                MGR,
            ),
            200,
        )
        done = validate_success(
            api.complete_removal_job(job["id"], TEST_USERS["beekeeper_headers"]),
            200,
        )
        assert done["status"] == "COMPLETED"
        hive_after = validate_success(api.get_hive(ctx["hive"]["id"], ops_headers))
        assert hive_after["lifecycle_status"] == "REMOVED"
        # The freed unit allows a fresh install on the same site.
        third = validate_success(
            api.create_hive(create_hive_payload(site["id"], agreement["id"]), MGR),
            201,
        )
        assert_hive(third)


class TestHostStandingGate:
    def test_install_rejected_when_host_suspended(self, api, ops_headers):
        """PRD §3.3: "Installation requires, in pipeline order: the referenced
        records to exist; the host to be `ACTIVE`."
        PRD §2.12 step 11: "host `ACTIVE` where required (agreement creation,
        hive installation, enrollment), `balance_due_cents` equal to zero for
        removal requests, agreement termination, subscription cancellation, and
        host reactivation, and `reputation_score` of at least 50 for agreement
        creation; surfaced as `ERR_HOST_NOT_ACTIVE`, `ERR_OUTSTANDING_BALANCE`,
        or `ERR_HOST_REPUTATION_TOO_LOW`."

        Design: Corner/errors/hive_install_host_suspended_rejected
        """
        ctx = setup_hive_scenario()
        suspended = validate_success(
            api.suspend_host(ctx["host"]["id"], ops_headers), 200,
        )
        assert suspended["status"] == "SUSPENDED"
        res = api.create_hive(
            create_hive_payload(ctx["site"]["id"], ctx["agreement"]["id"]), MGR,
        )
        validate_error(res, "ERR_HOST_NOT_ACTIVE")


class TestSwarmResponse:
    def _reported_swarm(self):
        ctx = setup_signed_agreement()
        host, site, agreement = ctx
        return host, site, agreement, report_swarm(host, site)

    def test_dispatch_after_capture_rejected(self, api, ops_headers):
        """PRD §3.7: "`CAPTURED`, `LOST`, and `EXPIRED` are all terminal."
        PRD §2.5: "once lazily expired, a swarm event is not actionable and
        operations on it are rejected with `ERR_SWARM_NOT_ACTIONABLE`."

        Design: Corner/state_machines/swarm_dispatch_after_capture_rejected
        """
        host, site, agreement, swarm = self._reported_swarm()
        bk1 = TEST_USERS["beekeeper_headers"]
        validate_success(api.dispatch_swarm_event(swarm["id"], bk1), 200)
        captured = validate_success(api.capture_swarm_event(swarm["id"], bk1), 200)
        assert captured["status"] == "CAPTURED"
        assert captured["captured_hive_id"], "capture created a hive"
        hive = validate_success(
            api.get_hive(captured["captured_hive_id"], ops_headers),
        )
        assert hive["site_id"] == site["id"]
        res = api.dispatch_swarm_event(
            swarm["id"], TEST_USERS["beekeeper2_headers"],
        )
        validate_error(res, "ERR_SWARM_NOT_ACTIONABLE")

    def test_capture_creates_cross_referenced_hive(self, api, ops_headers):
        """PRD §3.7: "On capture the server creates a new hive on the site
        under that agreement with `source_swarm_event_id` pointing back at the
        event, lifecycle `ACTIVE`, posture `STABLE`, occupancy rising by one,
        and the event's `captured_hive_id` set as it becomes `CAPTURED`."
        PRD §3.7: "A beekeeper answers the call by dispatching themselves,
        moving the event from `REPORTED` to `DISPATCHED` with their `X-User-ID`
        stored as `assigned_beekeeper_id`."

        Design: Corner/endpoints/swarm_capture_creates_hive_cross_reference
        """
        host, site, agreement, swarm = self._reported_swarm()
        bk1 = TEST_USERS["beekeeper_headers"]
        dispatched = validate_success(
            api.dispatch_swarm_event(swarm["id"], bk1), 200,
        )
        assert dispatched["status"] == "DISPATCHED"
        assert dispatched["assigned_beekeeper_id"] == "bk-1"

        captured = validate_success(api.capture_swarm_event(swarm["id"], bk1), 200)
        assert captured["status"] == "CAPTURED"
        assert captured["captured_hive_id"], "captured_hive_id set"

        hive = validate_success(
            api.get_hive(captured["captured_hive_id"], ops_headers),
        )
        assert hive["source_swarm_event_id"] == swarm["id"]
        assert hive["lifecycle_status"] == "ACTIVE"
        assert hive["posture"] == "STABLE"
        assert hive["agreement_id"] == agreement["id"]

        data, meta = validate_paginated(
            api.list_hives(
                ops_headers, params={"source_swarm_event_id": swarm["id"]},
            ),
        )
        assert [h["id"] for h in data] == [captured["captured_hive_id"]]
        assert meta["total_count"] == 1

    def test_swarm_expiry_boundary_72h(self, api, ops_headers):
        """PRD §2.5: "A swarm event more than 72 hours past its `reported_at`
        transitions from `REPORTED` or `DISPATCHED` to `EXPIRED`; once lazily
        expired, a swarm event is not actionable and operations on it are
        rejected with `ERR_SWARM_NOT_ACTIONABLE`."

        Design: Corner/complexity_layers/swarm_expiry_boundary_72h
        """
        host, site, agreement = setup_signed_agreement()
        swarm1 = report_swarm(host, site)
        swarm2 = report_swarm(host, site)
        # Both were reported at the default logical clock 2026-05-01T00:00:00Z.
        bk1 = TEST_USERS["beekeeper_headers"]

        # Exactly reported_at + 72h: "more than 72 hours" has not elapsed.
        api_client.set_clock("2026-05-04T00:00:00Z", ops_headers)
        dispatched = validate_success(
            api.dispatch_swarm_event(swarm1["id"], bk1), 200,
        )
        assert dispatched["status"] == "DISPATCHED", (
            "exactly 72h is still dispatchable (strictly-greater expiry)"
        )

        # One second past the boundary: lazily EXPIRED.
        api_client.set_clock("2026-05-04T00:00:01Z", ops_headers)
        expired = validate_success(api.get_swarm_event(swarm2["id"], ops_headers))
        assert expired["status"] == "EXPIRED", "lazy expiry materialized on read"
        validate_error(
            api.dispatch_swarm_event(swarm2["id"], bk1),
            "ERR_SWARM_NOT_ACTIONABLE",
        )
