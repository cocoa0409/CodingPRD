"""Attestation campaigns, outreach windows, sweeps, escalation, and the
provider-suspension cascade (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    advance_clock_and_sweep,
    create_attestation_campaign_payload,
    create_draft_request,
    create_open_campaign,
    create_provider,
    create_sent_request,
    create_target,
    expire_sent_request,
    get_provider,
    get_request,
    publish_batch,
    set_clock,
    setup_suspended_provider_via_attestation,
    setup_two_consecutive_expiries,
    create_batch,
    list_batch_items,
    validate_error,
    validate_success,
)


class TestSendGuards:
    def test_send_from_draft_campaign_rejected(self, api, data_steward_headers):
        """PRD §3.8: "Dispatch is guarded, with the checks evaluated in this order after
        state legality: the provider must be `ACTIVE`, failing as
        `ERR_PROVIDER_NOT_LINKABLE`; the provider must not already carry another request
        in `SENT` or `ESCALATED` status, failing as `ERR_ATTESTATION_ALREADY_INFLIGHT`
        (HTTP 409); and the campaign must be `OPEN`, failing as `ERR_CAMPAIGN_NOT_OPEN`
        (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/attestation_send_depends_on_campaign_open
        """
        set_clock()
        provider = create_provider()
        campaign = validate_success(
            api.create_attestation_campaign(
                create_attestation_campaign_payload(name="CS", window_days=5),
                data_steward_headers,
            ),
            201,
        )
        assert campaign["status"] == "DRAFT"
        req = create_draft_request(campaign["id"], provider["id"])
        res = api.send_attestation_request(req["id"], data_steward_headers)
        validate_error(res, ApiErrorId.ERR_CAMPAIGN_NOT_OPEN)

    def test_request_stays_draft_when_campaign_not_open(self, api, data_steward_headers):
        """PRD §3.8: "the campaign must be `OPEN`, failing as `ERR_CAMPAIGN_NOT_OPEN`
        (HTTP 409)." A rejected dispatch performs no transition, so the request remains
        `DRAFT`.

        Design: Difficulty/cross_entity_state_dependency/attestation_send_depends_on_campaign_open
        """
        set_clock()
        provider = create_provider()
        campaign = validate_success(
            api.create_attestation_campaign(
                create_attestation_campaign_payload(name="CS2", window_days=5),
                data_steward_headers,
            ),
            201,
        )
        req = create_draft_request(campaign["id"], provider["id"])
        validate_error(
            api.send_attestation_request(req["id"], data_steward_headers),
            ApiErrorId.ERR_CAMPAIGN_NOT_OPEN,
        )
        after = get_request(req["id"])
        assert after["status"] == "DRAFT", (
            f"Request must remain DRAFT after a rejected send, got {after['status']}"
        )

    def test_second_send_while_inflight_rejected(self, api, data_steward_headers):
        """PRD §3.8: "the provider must not already carry another request in `SENT` or
        `ESCALATED` status, failing as `ERR_ATTESTATION_ALREADY_INFLIGHT` (HTTP 409)".

        Design: Difficulty/resource_temporal_overlap/attestation_inflight_window_overlap_rejected
        """
        set_clock()
        provider = create_provider()
        campaign = create_open_campaign(window_days=5, name="CW")
        create_sent_request(campaign["id"], provider["id"])
        req2 = create_draft_request(campaign["id"], provider["id"])
        res = api.send_attestation_request(req2["id"], data_steward_headers)
        validate_error(res, ApiErrorId.ERR_ATTESTATION_ALREADY_INFLIGHT)

    def test_second_request_stays_draft_while_inflight(self, api, data_steward_headers):
        """PRD §3.8: "the provider must not already carry another request in `SENT` or
        `ESCALATED` status, failing as `ERR_ATTESTATION_ALREADY_INFLIGHT` (HTTP 409)".
        The blocked request keeps its `DRAFT` status.

        Design: Difficulty/resource_temporal_overlap/attestation_inflight_window_overlap_rejected
        """
        set_clock()
        provider = create_provider()
        campaign = create_open_campaign(window_days=5, name="CW2")
        req1 = create_sent_request(campaign["id"], provider["id"])
        req2 = create_draft_request(campaign["id"], provider["id"])
        validate_error(
            api.send_attestation_request(req2["id"], data_steward_headers),
            ApiErrorId.ERR_ATTESTATION_ALREADY_INFLIGHT,
        )
        assert get_request(req2["id"])["status"] == "DRAFT"
        assert get_request(req1["id"])["status"] == "SENT"


class TestRespondWindow:
    def test_window_closed_beats_missing_payload(self, api, provider_contact_headers):
        """PRD §3.8: "The response must arrive while the logical clock is strictly
        earlier than `due_at`, or it is rejected with `ERR_ATTESTATION_WINDOW_CLOSED`
        (HTTP 409); this window check is evaluated before the payload check."

        Design: Difficulty/priority_pair_validation_conflict/window_closed_vs_correction_payload_on_respond
        """
        set_clock()
        provider = create_provider()
        campaign = create_open_campaign(window_days=5, name="CT")
        req = create_sent_request(campaign["id"], provider["id"])
        set_clock("2026-08-10T00:00:00Z")  # past due_at (08-01 + 5 days)
        res = api.respond_attestation_request(
            req["id"], {"attestation_outcome": "CORRECTED"}, provider_contact_headers
        )
        validate_error(res, ApiErrorId.ERR_ATTESTATION_WINDOW_CLOSED)

    def test_request_stays_sent_after_window_closed_rejection(
        self, api, provider_contact_headers, data_steward_headers
    ):
        """PRD §3.8: "The response must arrive while the logical clock is strictly
        earlier than `due_at`, or it is rejected with `ERR_ATTESTATION_WINDOW_CLOSED`
        (HTTP 409)". The rejected response performs no transition; until the sweep runs
        the request remains `SENT`.

        Design: Difficulty/priority_pair_validation_conflict/window_closed_vs_correction_payload_on_respond
        """
        set_clock()
        provider = create_provider()
        campaign = create_open_campaign(window_days=5, name="CT2")
        req = create_sent_request(campaign["id"], provider["id"])
        set_clock("2026-08-10T00:00:00Z")
        validate_error(
            api.respond_attestation_request(
                req["id"], {"attestation_outcome": "CORRECTED"}, provider_contact_headers
            ),
            ApiErrorId.ERR_ATTESTATION_WINDOW_CLOSED,
        )
        after = validate_success(
            api.get_attestation_request(req["id"], data_steward_headers)
        )
        assert after["status"] == "SENT", (
            f"Request must remain SENT until the sweep runs, got {after['status']}"
        )

    def test_corrected_without_payload_rejected(self, api, provider_contact_headers):
        """PRD §3.8: "A `CORRECTED` outcome must carry the corrections in
        `corrected_payload`, or the call fails with `ERR_CORRECTION_PAYLOAD_REQUIRED`
        (HTTP 422)."

        Design: Corner/errors/error_correction_payload_required
        """
        set_clock()
        provider = create_provider()
        campaign = create_open_campaign(window_days=5, name="CE2")
        req = create_sent_request(campaign["id"], provider["id"])
        res = api.respond_attestation_request(
            req["id"], {"attestation_outcome": "CORRECTED"}, provider_contact_headers
        )
        validate_error(res, ApiErrorId.ERR_CORRECTION_PAYLOAD_REQUIRED)


class TestCampaignClose:
    def test_close_blocked_by_sent_request(self, api, data_steward_headers):
        """PRD §3.8: "closing it moves it to `CLOSED`, but only while no request in the
        campaign remains in `SENT` or `ESCALATED` status — otherwise the close is
        rejected with `ERR_CAMPAIGN_HAS_OPEN_REQUESTS` (HTTP 409) — and closing
        withdraws any requests still in `DRAFT`."

        Design: Corner/errors/error_campaign_close_with_open_requests
        """
        set_clock()
        provider = create_provider()
        campaign = create_open_campaign(window_days=5, name="CE4")
        create_sent_request(campaign["id"], provider["id"])
        res = api.close_campaign(campaign["id"], data_steward_headers)
        validate_error(res, ApiErrorId.ERR_CAMPAIGN_HAS_OPEN_REQUESTS)


class TestSweep:
    def test_sweep_expires_only_due_requests(self, api, data_steward_headers):
        """PRD §3.8: "every `SENT` request whose `due_at` has been reached or passed by
        the logical clock transitions to `EXPIRED`, each expiry triggers a recomputation
        of the provider's `staleness_flag` and a fresh quality-score run in which the
        attestation component drops, and the sweep reports the damage as
        `expired_count` alongside the `expired_request_ids` it touched."

        Design: Corner/complexity_layers/scheduled_sweep_expires_only_due_requests
        """
        set_clock()
        p1 = create_provider()
        p2 = create_provider(npi="1234567894", location_key="LOC2")
        camp5 = create_open_campaign(window_days=5, name="CL5A")   # due 2026-08-06
        camp15 = create_open_campaign(window_days=15, name="CL5B")  # due 2026-08-16
        req1 = create_sent_request(camp5["id"], p1["id"])
        req2 = create_sent_request(camp15["id"], p2["id"])
        sweep = advance_clock_and_sweep("2026-08-10T00:00:00Z")
        assert sweep["expired_count"] == 1, (
            f"Only the request due 2026-08-06 is due at 2026-08-10, got {sweep['expired_count']}"
        )
        assert req1["id"] in sweep["expired_request_ids"]
        assert get_request(req1["id"])["status"] == "EXPIRED"
        assert get_request(req2["id"])["status"] == "SENT", (
            "The request due 2026-08-16 must remain SENT at 2026-08-10"
        )


class TestEscalation:
    def test_escalate_after_escalation_window_rejected(self, api, data_steward_headers):
        """PRD §3.8: "a steward may escalate an `EXPIRED` request to `ESCALATED`, but
        only within one additional window — while the logical clock remains strictly
        earlier than `due_at` plus `window_days` — with later attempts rejected as
        `ERR_ESCALATION_WINDOW_CLOSED` (HTTP 409)."

        Design: Corner/errors/error_escalation_window_closed
        """
        set_clock()
        provider = create_provider()
        campaign = create_open_campaign(window_days=5, name="CE1")
        req = create_sent_request(campaign["id"], provider["id"])
        req = expire_sent_request(req["id"], "2026-08-07T00:00:00Z")
        assert req["status"] == "EXPIRED"
        # due_at is 2026-08-06; escalation window closes at 2026-08-11.
        set_clock("2026-08-20T00:00:00Z")
        res = api.escalate_attestation_request(req["id"], data_steward_headers)
        validate_error(res, ApiErrorId.ERR_ESCALATION_WINDOW_CLOSED)

    def test_first_escalation_does_not_suspend(self, api, data_steward_headers):
        """PRD §3.8: "the system counts the provider's consecutive requests that reached
        expiry, scanning backward by `sent_at` and stopping at the first `RESPONDED` or
        `WITHDRAWN`, and when that count reaches two — the threshold is inclusive, so
        exactly the second consecutive expiry suspends — the provider's
        `lifecycle_status` moves `ACTIVE` → `SUSPENDED`." After exactly one consecutive
        expiry the provider must remain ACTIVE.

        Design: Difficulty/boundary_precision_check/attestation_suspend_threshold_exactly_two
        """
        set_clock()
        provider = create_provider()
        campaign = create_open_campaign(window_days=5, name="CB")
        req = create_sent_request(campaign["id"], provider["id"])
        expire_sent_request(req["id"], "2026-08-07T00:00:00Z")
        validate_success(api.escalate_attestation_request(req["id"], data_steward_headers))
        after = get_provider(provider["id"])
        assert after["lifecycle_status"] == "ACTIVE", (
            "Exactly one consecutive expiry must not suspend the provider, "
            f"got {after['lifecycle_status']}"
        )

    def test_first_escalation_moves_request_to_escalated(self, api, data_steward_headers):
        """PRD §3.8: "a steward may escalate an `EXPIRED` request to `ESCALATED`, but
        only within one additional window". The valid EXPIRED → ESCALATED transition
        succeeds below the suspension threshold.

        Design: Difficulty/boundary_precision_check/attestation_suspend_threshold_exactly_two
        """
        set_clock()
        provider = create_provider()
        campaign = create_open_campaign(window_days=5, name="CB2")
        req = create_sent_request(campaign["id"], provider["id"])
        expire_sent_request(req["id"], "2026-08-07T00:00:00Z")
        escalated = validate_success(
            api.escalate_attestation_request(req["id"], data_steward_headers)
        )
        assert escalated["status"] == "ESCALATED"


class TestEscalationSuspensionCycle:
    def test_second_consecutive_escalation_suspends_provider(
        self, api, data_steward_headers
    ):
        """PRD §3.8: "when that count reaches two — the threshold is inclusive, so
        exactly the second consecutive expiry suspends — the provider's
        `lifecycle_status` moves `ACTIVE` → `SUSPENDED`."

        Design: Difficulty/non_linear_state_machine/attestation_request_cyclic_escalation
        """
        set_clock()
        provider = create_provider()
        _, req1, req2 = setup_two_consecutive_expiries(provider["id"], window_days=10)
        res = api.escalate_attestation_request(req2["id"], data_steward_headers)
        escalated = validate_success(res)
        assert escalated["status"] == "ESCALATED"
        after = get_provider(provider["id"])
        assert after["lifecycle_status"] == "SUSPENDED", (
            "The second consecutive expiry, once escalated, must suspend the provider, "
            f"got {after['lifecycle_status']}"
        )

    def test_expiries_without_escalation_leave_provider_active(
        self, api, data_steward_headers
    ):
        """PRD §3.8: "each expiry triggers a recomputation of the provider's
        `staleness_flag` and a fresh quality-score run in which the attestation
        component drops" — suspension is attached to escalation ("Escalation carries
        teeth"), not to expiry itself, so two un-escalated expiries leave the provider
        ACTIVE.

        Design: Difficulty/non_linear_state_machine/attestation_request_cyclic_escalation
        """
        set_clock()
        provider = create_provider()
        _, req1, req2 = setup_two_consecutive_expiries(provider["id"], window_days=10)
        assert get_request(req1["id"])["status"] == "EXPIRED"
        assert get_request(req2["id"])["status"] == "EXPIRED"
        after = get_provider(provider["id"])
        assert after["lifecycle_status"] == "ACTIVE", (
            "Expiries alone must not suspend; suspension is an escalation consequence, "
            f"got {after['lifecycle_status']}"
        )


class TestSuspensionDistributionCascade:
    def test_second_escalation_suspends_and_excludes_from_snapshot(
        self, api, data_steward_headers, distribution_operator_headers
    ):
        """PRD §3.8: "when that count reaches two — the threshold is inclusive, so
        exactly the second consecutive expiry suspends — the provider's
        `lifecycle_status` moves `ACTIVE` → `SUSPENDED`."
        PRD §3.9: "A provider is eligible when its `lifecycle_status` is `ACTIVE` at the
        cutoff and its score meets the target's `required_quality_floor`".

        Design: Difficulty/transitive_cascade/attestation_expiry_to_suspend_to_distribution
        """
        set_clock()
        provider = create_provider()
        target = create_target(target_code="CLAIMS", required_quality_floor=0)
        setup_suspended_provider_via_attestation(provider["id"], window_days=5)
        after = get_provider(provider["id"])
        assert after["lifecycle_status"] == "SUSPENDED"
        batch = create_batch(target["id"])
        publish_batch(batch["id"])
        items = list_batch_items(batch["id"])
        offending = [
            i for i in items
            if i["provider_id"] == provider["id"] and i["change_kind"] in ("ADD", "UPDATE")
        ]
        assert offending == [], (
            f"A suspended provider must not appear as ADD/UPDATE in the snapshot: {offending}"
        )

    def test_snapshot_of_only_suspended_provider_is_empty(
        self, api, data_steward_headers, distribution_operator_headers
    ):
        """PRD §3.9: "A provider is eligible when its `lifecycle_status` is `ACTIVE` at
        the cutoff and its score meets the target's `required_quality_floor`" and "the
        batch's `provider_count` records how many items were materialized."

        Design: Difficulty/transitive_cascade/attestation_expiry_to_suspend_to_distribution
        """
        set_clock()
        provider = create_provider()
        target = create_target(target_code="CLAIMS", required_quality_floor=0)
        setup_suspended_provider_via_attestation(provider["id"], window_days=5)
        batch = create_batch(target["id"])
        published = publish_batch(batch["id"])
        assert published["provider_count"] == 0, (
            f"With the only provider suspended, provider_count must be 0, "
            f"got {published['provider_count']}"
        )
        assert list_batch_items(batch["id"]) == []
