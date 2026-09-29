"""Cross-cutting compliance behaviour: optimistic concurrency on the two guarded
writes, the parent version counter under child consent writes, the conditional
third hop of the revocation cascade, and the measurement-day rollover that
precedes every disposition count.

Every precondition is built from scratch through the documented endpoints,
because each test starts against an empty database and the logical clock starts
at 2026-08-01T00:00:00Z.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from test_helpers import (
    DEFAULT_CLOCK,
    OFFICER_LAUNCHER_USER_ID,
    ApiErrorId,
    AttemptOutcome,
    CampaignStatus,
    CaptureMethod,
    Channel,
    ComplianceWorld,
    ConsentStatus,
    ConsentType,
    IntakeStatus,
    InternalDncStatus,
    ListType,
    PropagationStatus,
    RevocationChannelReceived,
    RevocationMethod,
    RevocationScope,
    ScrubJobStatus,
    SuppressionStatus,
    assert_attempt_budget_conserved,
    assert_consent_census_conserved,
    assert_decimal_equals,
    assert_error,
    assert_fields_equal,
    assert_ok,
    assert_page,
    assert_status,
    assert_timestamp_equals,
    assert_total_count,
    assert_version_is,
    factories,
)


def _contact_and_approved_script(
    world: ComplianceWorld,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Publish the CA policy, import one CA contact and approve one CA VOICE script.

    Nothing here touches the contact after its import, so the returned contact
    still carries the version it was minted with.
    """
    world.set_clock(DEFAULT_CLOCK)
    world.create_ca_policy()
    contact = world.create_ca_contact()
    script = world.approved_script()
    return contact, script


class TestStaleVersionPreconditions:
    """The two guarded writes and the counter they are guarded by."""

    def test_01_replaying_the_pre_capture_contact_version_is_refused_and_writes_nothing(
        self, world: ComplianceWorld
    ):
        """A second consent capture that replays the version read before the first
        capture is refused, and the refused write leaves the contact untouched.

        PRD 2.6: "If `expected_contact_version` does not equal the contact's
        current `version`, the create is refused with `ERR_STALE_CONTACT_VERSION`
        (HTTP 412), forcing the capturing client to re-read the contact's
        suppression status and consent census first."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_contact_version_on_consent_create_returns_412
        """
        contact, script = _contact_and_approved_script(world)
        pre_capture_version = contact["version"]

        voice_consent = world.create_consent(
            contact["id"],
            script["id"],
            expected_contact_version=pre_capture_version,
            channel=Channel.VOICE,
            consent_type=ConsentType.EXPRESS_WRITTEN,
            capture_method=CaptureMethod.WEB_FORM,
        )

        refused = world.api.create_consent_record(
            factories.consent_record_payload(
                contact_id=contact["id"],
                disclosure_script_id=script["id"],
                expected_contact_version=pre_capture_version,
                channel=Channel.SMS,
                consent_type=ConsentType.EXPRESS_WRITTEN,
                capture_method=CaptureMethod.SMS_DOUBLE_OPT_IN,
                signature_evidence="evidence-c1-sms",
            ),
            world.officer,
        )
        assert_error(refused, ApiErrorId.STALE_CONTACT_VERSION)

        after = world.read_contact(contact["id"])
        assert_version_is(after, 2)
        assert_fields_equal(after, total_consent_count=1, active_consent_count=1)
        assert_consent_census_conserved(after)

        kept = assert_ok(world.api.get_consent_record(voice_consent["id"], world.officer))
        assert_status(kept, ConsentStatus.ACTIVE)
        assert_fields_equal(kept, channel=Channel.VOICE)

    def test_02_replaying_the_creation_campaign_version_is_refused_after_the_scrub_ran(
        self, world: ComplianceWorld, draft_campaign: Dict[str, Any]
    ):
        """Queueing a second scrub with the version captured at campaign creation is
        refused, and the campaign keeps exactly the one job it already ran.

        PRD 2.6: "A `POST /compliance/scrub-jobs` request must carry
        `expected_campaign_version` holding the `version` of the target `Campaign`
        as the client last read it."
        PRD 2.6: "A mismatch is refused with `ERR_STALE_CAMPAIGN_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_campaign_version_on_scrub_create_returns_412
        """
        campaign = draft_campaign["campaign"]
        creation_version = campaign["version"]

        job = world.create_scrub_job(
            campaign["id"], list_types=[ListType.NATIONAL, ListType.INTERNAL]
        )
        completed = world.execute_scrub_job(job["id"])
        assert_status(completed, ScrubJobStatus.COMPLETED)

        refused = world.api.create_scrub_job(
            factories.scrub_job_payload(
                campaign_id=campaign["id"],
                expected_campaign_version=creation_version,
                list_types=[ListType.NATIONAL],
            ),
            world.manager,
        )
        assert_error(refused, ApiErrorId.STALE_CAMPAIGN_VERSION)

        after = world.read_campaign(campaign["id"])
        assert_version_is(after, 3)
        assert_status(after, CampaignStatus.PENDING_LAUNCH)
        assert_fields_equal(after, latest_scrub_status=ScrubJobStatus.COMPLETED)

        rows, meta = assert_page(
            world.api.list_campaign_scrub_jobs(campaign["id"], world.manager)
        )
        assert_total_count(meta, 1)
        assert len(rows) == 1, "only the executed job should exist: %r" % (rows,)

    def test_03_launching_with_the_freshly_read_campaign_version_bumps_the_row_to_four(
        self, world: ComplianceWorld, scrubbed_campaign: Dict[str, Any]
    ):
        """Certification succeeds against the version just read, increments the row by
        exactly one, and the identical replay is refused on the version precondition
        rather than on the campaign's new state.

        PRD 2.4: "`version` (integer): a counter that starts at 1 when the row is
        created and increments by exactly 1 on every mutation of that row."
        PRD 3.7: "Its `launch_certified_by_user_id` records the certifying officer's
        `X-User-ID`."
        PRD 2.6: "The same field and the same rejection apply to
        `POST /compliance/campaigns/{id}/launch`, where `expected_campaign_version`
        is likewise a required input and a mismatch yields
        `ERR_STALE_CAMPAIGN_VERSION` (HTTP 412)."
        PRD 2.8: "Checks are evaluated in the following order, and the first failing
        check ends the request."

        Design: Corner/cross_cutting_complexity_layers/correct_expected_campaign_version_on_launch_succeeds_and_bumps_the_row
        """
        campaign = scrubbed_campaign["campaign"]
        read_version = world.campaign_version(campaign["id"])
        assert read_version == 3, (
            "expected the scrubbed campaign at version 3, got %s" % (read_version,)
        )

        launched = assert_ok(
            world.api.launch_campaign(
                campaign["id"],
                factories.campaign_launch_payload(
                    expected_campaign_version=read_version,
                    certification_note="Certified for CA outreach",
                ),
                world.launcher,
            )
        )
        assert_version_is(launched, 4)
        assert_status(launched, CampaignStatus.ACTIVE)
        assert_fields_equal(
            launched, launch_certified_by_user_id=OFFICER_LAUNCHER_USER_ID
        )

        replay = world.api.launch_campaign(
            campaign["id"],
            factories.campaign_launch_payload(
                expected_campaign_version=read_version,
                certification_note="Certified for CA outreach",
            ),
            world.launcher,
        )
        assert_error(replay, ApiErrorId.STALE_CAMPAIGN_VERSION)

    def test_04_create_suspend_and_reinstate_each_bump_the_contact_version(
        self, world: ComplianceWorld
    ):
        """Each consent write that recomputes the census bumps the parent contact, so
        capture, suspension and reinstatement carry it from 1 to 4 while the total
        consent count stays at one.

        PRD 2.4: "`version` (integer): a counter that starts at 1 when the row is
        created and increments by exactly 1 on every mutation of that row."
        PRD 3.2: "the record moves `ACTIVE → SUSPENDED`, the contact's
        `active_consent_count` and `suspended_consent_count` are recomputed while
        `total_consent_count` stays put, and the contact's `version` increments."
        PRD 3.2: "Both branches increment the record's `reinstatement_count` by one
        and recompute the contact's census with the total unchanged, and both
        increment the contact's `version`: the branch out of `SUSPENDED` clears
        `suspended_reason` back to null and rebalances the active and suspended
        counters, while the branch out of `REVOKED` clears `revoked_at` back to null
        and rebalances the active and revoked counters."

        Design: Corner/cross_cutting_complexity_layers/contact_version_increments_on_every_consent_write
        """
        contact, script = _contact_and_approved_script(world)

        consent = world.create_consent(
            contact["id"],
            script["id"],
            expected_contact_version=contact["version"],
            channel=Channel.VOICE,
            consent_type=ConsentType.EXPRESS_WRITTEN,
            capture_method=CaptureMethod.WEB_FORM,
        )
        world.suspend_consent(consent["id"], reason="Evidence handle under audit")

        reinstated = world.reinstate_consent(
            consent["id"], reinstatement_note="Audit cleared the original signature"
        )
        assert_status(reinstated, ConsentStatus.ACTIVE)
        assert reinstated["suspended_reason"] is None, (
            "reinstatement out of SUSPENDED must clear suspended_reason, got %r"
            % (reinstated.get("suspended_reason"),)
        )
        assert_fields_equal(reinstated, reinstatement_count=1)

        after = world.read_contact(contact["id"])
        assert_version_is(after, 4)
        assert_fields_equal(
            after,
            active_consent_count=1,
            suspended_consent_count=0,
            total_consent_count=1,
        )
        assert_consent_census_conserved(after)


class TestRevocationCascadeScope:
    """The third cascade hop only reaches scrubs that asked for the internal list."""

    def test_05_validation_spares_a_scrub_that_never_requested_the_internal_list(
        self, world: ComplianceWorld
    ):
        """Honouring a revocation revokes the consent and suppresses the consumer, but a
        campaign whose only completed scrub asked for the national list alone keeps
        that scrub and stays running.

        PRD 3.3: "the request's `intake_status` moves `RECEIVED → VALIDATED` with
        `validated_at` stamped at the current clock instant, while the propagation
        dimension moves `NOT_STARTED → IN_PROGRESS` in the same request."
        PRD 3.3: "Rows moving `ACTIVE → REVOKED` and rows moving
        `SUSPENDED → REVOKED` are treated identically here; each moved row is
        counted, and the running total is stored on the revocation request as
        `consent_records_revoked_count`."
        PRD 3.3: "The third hop, caused by the second, invalidates the scrubs that
        were computed before this suppression existed: every scrub job whose status
        is `COMPLETED`, whose `expires_at` is still later than the current clock
        instant, whose `list_types` includes `INTERNAL`, and whose campaign's
        `target_state_codes` contains the consumer's `state_code`, moves
        `COMPLETED → INVALIDATED` with `invalidation_reason` set to
        `NEW_INTERNAL_SUPPRESSION`."

        Design: Corner/cross_cutting_complexity_layers/revocation_cascade_skips_a_scrub_that_never_asked_for_the_internal_list
        """
        built = world.build(stop_after="launch", list_types=[ListType.NATIONAL])
        contact = built["contact"]
        campaign = built["campaign"]
        consent = built["consent"]
        scrub_job = built["scrub_job"]

        revocation = world.create_revocation(
            contact["id"],
            channel_received=RevocationChannelReceived.SMS,
            method=RevocationMethod.REPLY_STOP,
            scope=RevocationScope.ALL_CHANNELS,
            received_note="STOP",
        )
        validated = world.validate_revocation(
            revocation["id"],
            validation_note="Number and identity match the account",
        )
        assert_fields_equal(
            validated,
            intake_status=IntakeStatus.VALIDATED,
            propagation_status=PropagationStatus.IN_PROGRESS,
            consent_records_revoked_count=1,
        )

        revoked = assert_ok(
            world.api.get_consent_record(consent["id"], world.officer)
        )
        assert_status(revoked, ConsentStatus.REVOKED)
        assert_timestamp_equals(revoked["revoked_at"], "2026-08-03T00:00:00.000Z")

        suppressed_contact = world.read_contact(contact["id"])
        assert_fields_equal(
            suppressed_contact,
            internal_dnc_status=InternalDncStatus.SUPPRESSED,
            revoked_consent_count=1,
        )
        assert_consent_census_conserved(suppressed_contact)

        _rows, meta = assert_page(
            world.api.list_suppression_entries(
                world.officer,
                {"list_type": ListType.INTERNAL, "status": SuppressionStatus.ACTIVE},
            )
        )
        assert_total_count(meta, 1)

        spared = assert_ok(world.api.get_scrub_job(scrub_job["id"], world.officer))
        assert_status(spared, ScrubJobStatus.COMPLETED)
        assert spared["invalidation_reason"] is None, (
            "a national-only scrub must not be invalidated, got %r"
            % (spared.get("invalidation_reason"),)
        )
        assert_fields_equal(spared, list_types=[ListType.NATIONAL])

        still_running = world.read_campaign(campaign["id"])
        assert_status(still_running, CampaignStatus.ACTIVE)
        assert_fields_equal(
            still_running, latest_scrub_status=ScrubJobStatus.COMPLETED
        )
        assert still_running["suspension_reason"] is None, (
            "the campaign must not be suspended, got %r"
            % (still_running.get("suspension_reason"),)
        )


class TestMeasurementDayRollover:
    """A disposition recorded on a new UTC date closes the previous day first."""

    def test_06_the_first_outcome_of_a_new_utc_date_closes_the_previous_day(
        self, world: ComplianceWorld
    ):
        """Recording a live answer on the day after the measured day appends the closing
        day to the rate history, zeroes today's four counters, and only then counts
        the new disposition — leaving today's regulatory rate at 0.00 while the
        rolling rate still averages the closed day.

        PRD 3.8: "When the UTC calendar date of the current clock instant differs
        from the campaign's `measurement_date`, the closing day's figures are
        appended to `daily_rate_history` as an entry carrying that `date`, its
        `live_answer_count`, its `abandoned_count` and its regulatory `rate_pct`;
        the history is kept ordered by `date` ascending."
        PRD 3.8: "All four of today's counters then reset to 0 and
        `measurement_date` becomes the new UTC date — and only then is the current
        disposition counted."
        PRD 3.8: "Each day is rounded first and the mean of those rounded values is
        rounded second; pooling the days' abandoned counts and live-answer counts
        and dividing once is a different number and is not what this rate means."

        Design: Corner/cross_cutting_complexity_layers/measurement_date_rollover_resets_the_daily_counters_before_counting
        """
        built = world.build(stop_after="launch", abandonment_limit_pct=60.0)
        campaign_id = built["campaign"]["id"]
        contact_id = built["contact"]["id"]

        first = world.create_attempt(campaign_id, contact_id, Channel.VOICE)
        world.record_outcome(
            first["id"],
            outcome=AttemptOutcome.CONNECTED_LIVE,
            agent_connect_seconds=1,
        )

        world.set_clock("2026-08-03T00:31:00Z")
        second = world.create_attempt(campaign_id, contact_id, Channel.VOICE)
        world.record_outcome(
            second["id"],
            outcome=AttemptOutcome.ABANDONED,
            abandon_message_played=True,
        )

        measured_day = world.read_campaign(campaign_id)
        assert_fields_equal(
            measured_day,
            measurement_date="2026-08-03",
            live_answer_count_today=2,
            abandoned_count_today=1,
        )
        assert_decimal_equals(measured_day["regulatory_abandonment_rate_pct"], 50.00)

        world.set_clock("2026-08-04T00:00:00Z")
        third = world.create_attempt(campaign_id, contact_id, Channel.VOICE)
        world.record_outcome(
            third["id"],
            outcome=AttemptOutcome.CONNECTED_LIVE,
            agent_connect_seconds=2,
        )

        rolled = world.read_campaign(campaign_id)
        assert_fields_equal(rolled, measurement_date="2026-08-04")

        history = rolled["daily_rate_history"]
        assert len(history) == 1, "expected one closed day in the history: %r" % (
            history,
        )
        assert_fields_equal(
            history[0],
            date="2026-08-03",
            live_answer_count=2,
            abandoned_count=1,
        )
        assert_decimal_equals(history[0]["rate_pct"], 50.00)

        assert_fields_equal(
            rolled,
            live_answer_count_today=1,
            abandoned_count_today=0,
            machine_count_today=0,
            no_answer_count_today=0,
        )
        assert_decimal_equals(rolled["regulatory_abandonment_rate_pct"], 0.00)
        assert_decimal_equals(rolled["internal_abandonment_rate_pct"], 0.00)
        assert_decimal_equals(rolled["rolling_compliance_rate_pct"], 25.00)
        assert_status(rolled, CampaignStatus.ACTIVE)

        spent = world.read_contact(contact_id)
        assert_fields_equal(spent, attempt_budget_remaining=0)
        assert_attempt_budget_conserved(spent)
