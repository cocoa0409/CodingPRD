"""Outreach attempt cadence, concurrency, and guard-chain claims
(PRD §2.4, §2.7, §2.8, §3.4)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, assert_outreach_attempt, assert_timestamp_instant_equal,
    setup_panel_scenario, setup_active_campaign, advance_clock, get_care_gap,
    record_attempt, close_gap_via_evidence, create_attempt_payload,
    make_admin_headers, make_panel_manager_headers,
)


class TestAttemptCadencePinnedOrder:
    def test_attempt_cadence_circular_pinned_order(self, api):
        """PRD §3.4: "Step two takes the cooldown from the campaign's
        `min_attempt_interval_hours`. Step three forms the candidate instant by
        adding the cooldown to `current_business_date`, then clips it into waking
        hours: if the candidate's local time-of-day is at or after
        `quiet_hours_start_min`, the candidate moves to `quiet_hours_end_min` on the
        next local day; if it is before `quiet_hours_end_min`, it moves to
        `quiet_hours_end_min` on the same local day. Step four sets
        `next_eligible_attempt_at` to the later of the clipped candidate and the
        campaign's `starts_at`."
        PRD §3.4: "The first non-`REVERSED` attempt moves the gap from `OPEN` to
        `OUTREACH_IN_PROGRESS`; further attempts are a self-loop within
        `OUTREACH_IN_PROGRESS`. Each non-`REVERSED` attempt increments the gap's
        `attempt_count` by one".

        Attempt at 2026-05-10T19:00 with a 72h cooldown lands the candidate at
        2026-05-13T19:00, already inside waking hours (08:00-21:00), so no clipping
        applies and the candidate is later than starts_at.

        Design: Difficulty/combinatorial_formula/attempt_cadence_circular_pinned_order
        """
        scenario = setup_panel_scenario(
            num_members=1, member_specs=[{"risk_tier": "HIGH"}])
        campaign = setup_active_campaign(
            scenario, advance_to="2026-05-10T19:00:00Z",
            min_attempt_interval_hours=72, quiet_hours_start_min=1260,
            quiet_hours_end_min=480, max_attempts_per_member=10)
        gap = scenario["gaps"][0]
        record_attempt(gap["id"], campaign["id"], outcome="NO_ANSWER",
                       panel_manager_id=scenario["panel_manager_id"])
        gap_after = get_care_gap(gap["id"])
        assert gap_after["attempt_count"] == 1, (
            f"Expected attempt_count 1, got {gap_after['attempt_count']}")
        assert gap_after["status"] == "OUTREACH_IN_PROGRESS", (
            f"Expected OUTREACH_IN_PROGRESS, got {gap_after['status']}")
        assert_timestamp_instant_equal(
            gap_after["next_eligible_attempt_at"], "2026-05-13T19:00:00Z",
            label="next_eligible_attempt_at")

    def test_attempt_stamped_from_registry_clock(self, api):
        """PRD §3.4: "A recorded attempt is stamped `attempted_at` from the registry's
        logical clock and denormalizes the `member_id` from its parent gap at write
        time."

        Design: Difficulty/combinatorial_formula/attempt_cadence_circular_pinned_order
        """
        scenario = setup_panel_scenario(
            num_members=1, member_specs=[{"risk_tier": "HIGH"}])
        campaign = setup_active_campaign(
            scenario, advance_to="2026-05-10T19:00:00Z",
            min_attempt_interval_hours=72, max_attempts_per_member=10)
        gap = scenario["gaps"][0]
        attempt = record_attempt(gap["id"], campaign["id"], outcome="NO_ANSWER",
                                 panel_manager_id=scenario["panel_manager_id"])
        assert_timestamp_instant_equal(attempt["attempted_at"], "2026-05-10T19:00:00Z",
                                       label="attempted_at")
        assert attempt["member_id"] == scenario["members"][0]["id"], (
            "attempt must denormalize member_id from its parent gap")


class TestAttemptStateVersusBusinessTemporal:
    def _closed_gap_with_future_cadence(self, api):
        """Close a gap after one attempt, while the 72h cadence cooldown is still
        outstanding, returning (scenario, campaign, gap_id)."""
        scenario = setup_panel_scenario(num_members=1)
        campaign = setup_active_campaign(scenario)  # clock at 2026-05-01T12:00
        gap_id = scenario["gaps"][0]["id"]
        record_attempt(gap_id, campaign["id"], outcome="NO_ANSWER",
                       panel_manager_id=scenario["panel_manager_id"])
        close_gap_via_evidence(gap_id)
        return scenario, campaign, gap_id

    def test_attempt_state_vs_business_temporal(self, api):
        """PRD §2.8: "then whether the target resource is in a state that permits the
        action (failure yields `ERR_INVALID_STATE`, HTTP 409), then the
        optimistic-concurrency check where one applies (failure yields
        `ERR_STALE_VERSION`), and only then the business rules in their own ascending
        priority order — cadence timing before campaign window, campaign window
        before consent, consent before the attempt cap, the cap before exclusion
        screening, exclusion screening before campaign liveness."

        A `CLOSED` gap attempted before its `next_eligible_attempt_at` violates both
        the state check and cadence timing; the state check wins.

        Design: Difficulty/priority_pair_validation_conflict/attempt_state_vs_business_temporal
        """
        scenario, campaign, gap_id = self._closed_gap_with_future_cadence(api)
        gap_now = get_care_gap(gap_id)
        assert gap_now["status"] == "CLOSED"
        # Clock is still 2026-05-01T12:00, before next_eligible (T+72h) — cadence
        # would also fail, but the state check fires first.
        resp = api.create_outreach_attempt(
            gap_id,
            create_attempt_payload(campaign_id=campaign["id"],
                                   expected_care_gap_version=gap_now["version"]),
            make_panel_manager_headers(scenario["panel_manager_id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_attempt_on_closed_gap_rejected_even_after_cadence(self, api):
        """PRD §2.8: "then whether the target resource is in a state that permits the
        action (failure yields `ERR_INVALID_STATE`, HTTP 409)".
        PRD §3.6: "An approved record becomes `APPROVED`, the gap becomes `CLOSED`".

        With cadence satisfied, the state check alone rejects the attempt on a
        CLOSED gap.

        Design: Difficulty/priority_pair_validation_conflict/attempt_state_vs_business_temporal
        """
        scenario, campaign, gap_id = self._closed_gap_with_future_cadence(api)
        # Move past the 72h cooldown (and within due_date + 30d lag, though CLOSED
        # gaps do not expire).
        advance_clock(scenario["registry"]["id"], "2026-05-10T12:00:00Z")
        gap_now = get_care_gap(gap_id)
        assert gap_now["status"] == "CLOSED"
        resp = api.create_outreach_attempt(
            gap_id,
            create_attempt_payload(campaign_id=campaign["id"],
                                   expected_care_gap_version=gap_now["version"]),
            make_panel_manager_headers(scenario["panel_manager_id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestAttemptGuards:
    def test_attempt_cap_reached_blocks(self, api):
        """PRD §3.4: "then the attempt cap, which rejects with
        `ERR_ATTEMPT_CAP_REACHED` once the gap's `attempt_count` has reached the
        campaign's `max_attempts_per_member`".

        Design: Corner/validations/attempt_cap_reached_blocks
        """
        scenario = setup_panel_scenario(num_members=1)
        campaign = setup_active_campaign(
            scenario, advance_to="2026-05-01T12:00:00Z",
            min_attempt_interval_hours=1, max_attempts_per_member=2)
        gap_id = scenario["gaps"][0]["id"]
        pm = scenario["panel_manager_id"]
        record_attempt(gap_id, campaign["id"], panel_manager_id=pm)
        advance_clock(scenario["registry"]["id"], "2026-05-01T13:00:00Z")
        record_attempt(gap_id, campaign["id"], panel_manager_id=pm)
        advance_clock(scenario["registry"]["id"], "2026-05-01T14:00:00Z")
        gap_now = get_care_gap(gap_id)
        assert gap_now["attempt_count"] == 2, (
            f"Expected attempt_count 2 at the cap, got {gap_now['attempt_count']}")
        resp = api.create_outreach_attempt(
            gap_id,
            create_attempt_payload(campaign_id=campaign["id"],
                                   expected_care_gap_version=gap_now["version"]),
            make_panel_manager_headers(pm))
        validate_error(resp, ApiErrorId.ERR_ATTEMPT_CAP_REACHED)

    def test_channel_consent_missing_blocks_call(self, api):
        """PRD §3.4: "then channel consent, which rejects with
        `ERR_CHANNEL_CONSENT_MISSING` (HTTP 403) when `phone_ok` is false and the
        channel is `CALL` or `TEXT`, or when `mail_ok` is false and the channel is
        `MAIL`".

        Design: Corner/validations/channel_consent_missing_blocks_call
        """
        scenario = setup_panel_scenario(
            num_members=1, member_specs=[{"phone_ok": False}])
        campaign = setup_active_campaign(scenario)  # clock at noon, waking hours
        gap = get_care_gap(scenario["gaps"][0]["id"])
        resp = api.create_outreach_attempt(
            gap["id"],
            create_attempt_payload(campaign_id=campaign["id"], channel="CALL",
                                   expected_care_gap_version=gap["version"]),
            make_panel_manager_headers(scenario["panel_manager_id"]))
        validate_error(resp, ApiErrorId.ERR_CHANNEL_CONSENT_MISSING)

    def test_attempt_occ_stale_version(self, api):
        """PRD §2.7: "Recording an outreach attempt against a care gap requires the
        request to carry `expected_care_gap_version` holding the caller's last
        observed `version` of that gap. If the gap's current `version` has advanced
        since — for example because a prior attempt already moved `attempt_count`
        and `next_eligible_attempt_at` — the attempt is rejected with
        `ERR_STALE_VERSION` (HTTP 412), since the caller's cadence computation was
        made against a stale record."

        Design: Corner/endpoints/attempt_occ_stale_version
        """
        scenario = setup_panel_scenario(num_members=1)
        campaign = setup_active_campaign(scenario)
        gap = scenario["gaps"][0]
        observed_version = gap["version"]
        record_attempt(gap["id"], campaign["id"],
                       panel_manager_id=scenario["panel_manager_id"])
        # Replaying with the pre-attempt version is stale.
        resp = api.create_outreach_attempt(
            gap["id"],
            create_attempt_payload(campaign_id=campaign["id"],
                                   expected_care_gap_version=observed_version),
            make_panel_manager_headers(scenario["panel_manager_id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_optimistic_concurrency_care_gap_version_increments(self, api):
        """PRD §3.4: "Each non-`REVERSED` attempt increments the gap's
        `attempt_count` by one, recomputes `next_eligible_attempt_at` via the cadence
        rule below, recomputes `priority_score`, and increments the gap's `version`."

        Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_care_gap_version_increments
        """
        scenario = setup_panel_scenario(num_members=1)
        campaign = setup_active_campaign(scenario)
        gap = scenario["gaps"][0]
        version_before = gap["version"]
        record_attempt(gap["id"], campaign["id"],
                       panel_manager_id=scenario["panel_manager_id"])
        gap_after = get_care_gap(gap["id"])
        assert gap_after["version"] == version_before + 1, (
            f"Expected version {version_before + 1}, got {gap_after['version']}")

    def test_immediate_consistency_attempt_visible_in_response(self, api):
        """PRD §3.4: "Each non-`REVERSED` attempt increments the gap's
        `attempt_count` by one, recomputes `next_eligible_attempt_at` via the cadence
        rule below, recomputes `priority_score`, and increments the gap's `version`."

        The parent gap read immediately after the write reflects the mutation.

        Design: Corner/consistency_model/immediate_consistency_attempt_visible_in_response
        """
        scenario = setup_panel_scenario(num_members=1)
        campaign = setup_active_campaign(scenario)
        gap = scenario["gaps"][0]
        record_attempt(gap["id"], campaign["id"],
                       panel_manager_id=scenario["panel_manager_id"])
        gap_after = get_care_gap(gap["id"])
        assert gap_after["attempt_count"] == 1, (
            f"Expected attempt_count 1, got {gap_after['attempt_count']}")
        assert gap_after["next_eligible_attempt_at"] is not None, (
            "next_eligible_attempt_at must be recomputed after a recorded attempt")


class TestOutreachAttemptRecord:
    def test_outreach_attempt_immutable_no_version_field(self, api):
        """PRD §2.4: "The exception is the outreach attempt record, which is an
        append-only ledger entry: it carries only `id` and `created_at`, and both
        `updated_at` and `version` are absent from it."

        Design: Corner/entities/outreach_attempt_immutable_no_version_field
        """
        scenario = setup_panel_scenario(num_members=1)
        campaign = setup_active_campaign(scenario)
        gap = scenario["gaps"][0]
        gap_now = get_care_gap(gap["id"])
        resp = api.create_outreach_attempt(
            gap["id"],
            create_attempt_payload(campaign_id=campaign["id"],
                                   expected_care_gap_version=gap_now["version"]),
            make_panel_manager_headers(scenario["panel_manager_id"]))
        data = validate_success(resp, 201)
        assert_outreach_attempt(data)
        assert data["id"] is not None

    def test_terminal_state_lockdown_expired_gap(self, api):
        """PRD §3.8: "Whenever the registry clock is at or past a gap's `due_date`
        plus the measure's `reporting_lag_days` and the gap still sits in any of
        `OPEN`, `OUTREACH_IN_PROGRESS`, `AWAITING_APPOINTMENT`, `PENDING_EVIDENCE`,
        or `REOPENED`, the system moves it to the terminal `EXPIRED` status and
        decrements the member's `open_gap_count` by one."
        PRD §2.8: "then whether the target resource is in a state that permits the
        action (failure yields `ERR_INVALID_STATE`, HTTP 409)".

        Design: Corner/state_machines/terminal_state_lockdown_expired_gap
        """
        scenario = setup_panel_scenario(num_members=1, reporting_lag_days=30)
        registry_id = scenario["registry"]["id"]
        advance_clock(registry_id, "2027-08-01T00:00:00Z")
        campaign = setup_active_campaign(
            scenario, advance_to=None,
            ends_at="2027-12-31T23:59:59Z")
        gap = get_care_gap(scenario["gaps"][0]["id"])
        assert gap["status"] == "EXPIRED", f"Expected EXPIRED, got {gap['status']}"
        resp = api.create_outreach_attempt(
            gap["id"],
            create_attempt_payload(campaign_id=campaign["id"],
                                   expected_care_gap_version=gap["version"]),
            make_panel_manager_headers(scenario["panel_manager_id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
