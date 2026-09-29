"""Endpoint contract behaviour: sub-resource scoping, list filters and derived reads."""

from test_helpers import (
    STATE_CA,
    STATE_NV,
    PHONE_C2,
    AllegedViolationType,
    AttemptOutcome,
    CampaignStatus,
    ComplaintSource,
    ComplaintStatus,
    ConsentStatus,
    EmergencyStatus,
    IntakeStatus,
    InternalDncStatus,
    ListType,
    PolicyStatus,
    PropagationStatus,
    RejectionReason,
    RevocationChannelReceived,
    RevocationMethod,
    RevocationScope,
    RiskTier,
    ScrubJobStatus,
    SuspensionReason,
    VoidReason,
    assert_attempt_budget_conserved,
    assert_consent_census_conserved,
    assert_decimal_equals,
    assert_fields_equal,
    assert_fields_null,
    assert_ok,
    assert_status,
    assert_timestamp_equals,
    assert_total_count,
    assert_version_is,
    factories,
    ids_of,
    validate_paginated,
)


class TestLogicalClockEndpoint:
    """Driving the clock changes later writes only."""

    def test_01_moving_the_clock_forward_leaves_earlier_rows_at_their_original_stamp(
        self, world
    ):
        """A clock jump rewrites no history: an existing contact keeps its created_at
        and its version, while the next import is stamped at the new instant.

        PRD 2.5: "A `PlatformAdmin` moves it by supplying a `to_iso8601` instant to the
        clock endpoint; the call mutates no entity and every subsequent request observes
        the new instant."

        PRD 2.4: "`created_at` (string): an ISO 8601 timestamp in UTC with three
        fractional digits, for example `2026-08-01T00:00:00.000Z`, recording when the row
        was first created."

        Design: Corner/endpoints/clock_endpoint_moves_the_logical_clock_without_rewriting_history
        """
        world.set_clock("2026-08-03T00:00:00Z")
        contact = world.create_ca_contact(attempt_budget_total=3)
        assert_timestamp_equals(contact["created_at"], "2026-08-03T00:00:00.000Z")
        assert_version_is(contact, 1)

        world.set_clock("2026-08-05T09:15:00Z")

        unchanged = world.read_contact(contact["id"])
        assert_timestamp_equals(unchanged["created_at"], "2026-08-03T00:00:00.000Z")
        assert_version_is(unchanged, 1)

        later = world.create_ca_contact(phone_number=PHONE_C2)
        assert_timestamp_equals(later["created_at"], "2026-08-05T09:15:00.000Z")


class TestCampaignScrubHistorySubResource:
    """A campaign's scrub history is scoped to that campaign."""

    def test_02_scrub_history_returns_only_the_path_campaigns_own_jobs(
        self, api, world, draft_campaign
    ):
        """With two campaigns each holding one completed scrub, the nested read on the
        first returns exactly its own job and never the sibling's.

        PRD 3.4: "a campaign's jobs may be listed newest `requested_at` first, narrowed
        by `status` and paged with `limit` and `offset`."

        PRD 2.3: "Every list response carries `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object of the envelope, where `total_count` counts
        the rows matching the filters before pagination is applied and `has_more` says
        whether any matching row remains beyond the returned page."

        Design: Corner/endpoints/campaign_scrub_jobs_sub_resource_returns_only_that_campaigns_jobs
        """
        campaign_a = draft_campaign["campaign"]
        job_a = world.scrub_campaign(campaign_a["id"])

        campaign_b = world.create_campaign(
            dialer_profile_id=draft_campaign["profile"]["id"],
            agent_script_id=draft_campaign["script"]["id"],
            name="CA Aug Overflow",
        )
        job_b = world.scrub_campaign(campaign_b["id"])

        rows, meta = validate_paginated(
            api.list_campaign_scrub_jobs(campaign_a["id"], world.manager)
        )
        assert_total_count(meta, 1)
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert ids_of(rows) == [job_a["id"]]
        assert job_b["id"] not in ids_of(rows)

        assert_fields_equal(
            job_b,
            campaign_id=campaign_b["id"],
            status=ScrubJobStatus.COMPLETED,
        )


class TestContactRevocationHistorySubResource:
    """A consumer's revocation history narrows by intake status."""

    def test_03_revocation_history_filtered_by_intake_status_hides_the_rejected_row(
        self, api, world
    ):
        """A rejected intake is excluded by an intake_status filter of RECEIVED while the
        still-received one is returned, and the unfiltered read shows both.

        PRD 3.1: "A `ComplianceOfficer`, a `DialerOperator` or the `Consumer` themselves
        may also list every revocation request received for that consumer, newest
        `received_at` first, narrowing the list by `intake_status`, by
        `propagation_status`, and paging it with `limit` and `offset`."

        PRD 3.3: "The officer supplies a `rejection_reason` of `NOT_CONSUMER`,
        `UNVERIFIABLE_IDENTITY` or `DUPLICATE`; `intake_status` moves `RECEIVED →
        REJECTED`, the reason is stored, and `propagation_status` stays exactly where it
        was at `NOT_STARTED`, because the two dimensions move under different triggers
        and a rejected intake never propagates."

        Design: Corner/endpoints/contact_revocation_sub_resource_filters_by_intake_status
        """
        world.set_clock("2026-08-03T14:00:00Z")
        world.create_ca_policy()
        contact = world.create_ca_contact()
        script = world.approved_script()
        world.create_consent(contact["id"], script["id"])

        rejected_request = world.create_revocation(contact["id"])
        assert_ok(
            api.reject_revocation_request(
                rejected_request["id"],
                factories.revocation_reject_payload(
                    RejectionReason.UNVERIFIABLE_IDENTITY
                ),
                world.officer,
            )
        )

        received_request = world.create_revocation(
            contact["id"],
            channel_received=RevocationChannelReceived.WEB,
            method=RevocationMethod.WEB_PORTAL,
            scope=RevocationScope.VOICE,
            received_note="Portal opt-out",
        )

        rows, meta = validate_paginated(
            api.list_contact_revocation_requests(
                contact["id"],
                world.officer,
                {"intake_status": IntakeStatus.RECEIVED},
            )
        )
        assert_total_count(meta, 1)
        assert meta["has_more"] is False
        assert ids_of(rows) == [received_request["id"]]

        stored = assert_ok(
            api.get_revocation_request(rejected_request["id"], world.officer)
        )
        assert_fields_equal(
            stored,
            intake_status=IntakeStatus.REJECTED,
            rejection_reason=RejectionReason.UNVERIFIABLE_IDENTITY,
            propagation_status=PropagationStatus.NOT_STARTED,
        )

        _, unfiltered_meta = validate_paginated(
            api.list_contact_revocation_requests(contact["id"], world.officer)
        )
        assert_total_count(unfiltered_meta, 2)


class TestCampaignRead:
    """The campaign read projects its newest scrub."""

    def test_04_campaign_read_shows_the_scrub_derived_target_count_and_promotion(
        self, api, world, scrubbed_campaign
    ):
        """After one completed scrub over a single unsuppressed consumer the campaign
        read reports COMPLETED, an eligible target count of one and PENDING_LAUNCH, with
        the launch fields still null.

        PRD 3.4: "Finally the campaign is updated: its `latest_scrub_status` becomes
        `COMPLETED`, its own `eligible_target_count` is overwritten with this job's, its
        `version` increments and its `updated_at` refreshes — and if it was in `DRAFT` it
        moves `DRAFT → PENDING_LAUNCH`, becoming launchable only because a child job
        completed."

        PRD 3.4: "`eligible_target_count` is `contacts_scrubbed_count` less
        `contacts_suppressed_count`, and can never be negative because the suppressed
        contacts are a subset of the examined ones."

        Design: Corner/endpoints/campaign_read_reflects_the_scrub_derived_target_count
        """
        campaign = world.read_campaign(scrubbed_campaign["campaign"]["id"])
        assert_status(campaign, CampaignStatus.PENDING_LAUNCH)
        assert_fields_equal(
            campaign,
            eligible_target_count=1,
            latest_scrub_status=ScrubJobStatus.COMPLETED,
        )
        assert_fields_null(
            campaign,
            "launch_certified_by_user_id",
            "pinned_script_version",
            "measurement_date",
        )
        assert_version_is(campaign, 3)

        job = assert_ok(
            api.get_scrub_job(scrubbed_campaign["scrub_job"]["id"], world.manager)
        )
        assert_fields_equal(
            job,
            contacts_scrubbed_count=1,
            contacts_suppressed_count=0,
            eligible_target_count=1,
        )


class TestCampaignSuspension:
    """Manual suspension performs the shared housekeeping."""

    def test_05_manual_suspension_voids_pending_attempts_and_credits_the_budget(
        self, api, world, active_campaign
    ):
        """Suspending a running campaign by hand records MANUAL, voids its pending
        attempt with CAMPAIGN_SUSPENDED and hands the consumer their budget unit back.

        PRD 3.7: "Every one of the five suspension paths does the same housekeeping: each
        of the campaign's contact attempts still sitting at `PENDING` is voided with
        `void_reason` `CAMPAIGN_SUSPENDED`, each such void credits its consumer's attempt
        budget as §2.10 requires, and the campaign's `version` increments."

        PRD 3.8: "In every case `voided_at` is stamped at the current clock instant, the
        reason is stored, the attempt's `outcome` becomes `VOIDED`, the consumer's
        `attempts_charged` decreases by one and `attempt_budget_remaining` increases by
        one with the contact's `version` incrementing, and the campaign's
        `permitted_attempt_count` decreases by one while `voided_attempt_count` increases
        by one."

        Design: Corner/endpoints/suspend_endpoint_voids_pending_attempts_and_credits_the_budget
        """
        campaign = active_campaign["campaign"]
        contact = active_campaign["contact"]

        attempt = world.create_attempt(campaign["id"], contact["id"])
        assert_status(attempt, AttemptOutcome.PENDING, field="outcome")

        suspended = world.suspend_campaign(
            campaign["id"], suspension_note="Vendor list audit"
        )
        assert_fields_equal(
            suspended,
            status=CampaignStatus.SUSPENDED,
            suspension_reason=SuspensionReason.MANUAL,
            permitted_attempt_count=0,
            voided_attempt_count=1,
        )

        voided = assert_ok(api.get_contact_attempt(attempt["id"], world.officer))
        assert_fields_equal(
            voided,
            outcome=AttemptOutcome.VOIDED,
            void_reason=VoidReason.CAMPAIGN_SUSPENDED,
        )
        assert_timestamp_equals(voided["voided_at"], "2026-08-03T00:00:00.000Z")

        credited = world.read_contact(contact["id"])
        assert_fields_equal(credited, attempts_charged=0, attempt_budget_remaining=3)
        assert_attempt_budget_conserved(credited)


class TestAttemptVoiding:
    """Voiding is admissible from a recorded disposition, not only from PENDING."""

    def test_06_void_from_connected_live_reverses_the_live_answer_and_the_budget(
        self, api, world, active_campaign
    ):
        """An attempt already recorded as a live connect may still be voided, which drops
        the live-answer count back to zero and returns the consumer's budget unit.

        PRD 3.8: "Voiding an attempt is a `ComplianceOfficer`'s compliance correction and
        is admissible from every one of the five recordable states, so that `PENDING →
        VOIDED`, `CONNECTED_LIVE → VOIDED`, `ABANDONED → VOIDED`, `MACHINE_ANSWERED →
        VOIDED` and `NO_ANSWER → VOIDED` are all available so long as `voided_at` is
        still null"

        PRD 3.8: "voiding from `CONNECTED_LIVE` decreases `live_answer_count_today` by
        one and recomputes both measures"

        Design: Corner/endpoints/void_is_allowed_from_a_recorded_outcome_not_only_from_pending
        """
        campaign = active_campaign["campaign"]
        contact = active_campaign["contact"]

        attempt = world.create_attempt(campaign["id"], contact["id"])
        recorded = world.record_outcome(
            attempt["id"],
            outcome=AttemptOutcome.CONNECTED_LIVE,
            agent_connect_seconds=1,
        )
        assert_status(recorded, AttemptOutcome.CONNECTED_LIVE, field="outcome")

        voided = assert_ok(
            api.void_contact_attempt(
                attempt["id"],
                factories.attempt_void_payload(
                    void_reason=VoidReason.COMPLIANCE_CORRECTION
                ),
                world.officer,
            )
        )
        assert_fields_equal(
            voided,
            outcome=AttemptOutcome.VOIDED,
            void_reason=VoidReason.COMPLIANCE_CORRECTION,
        )

        campaign_after = world.read_campaign(campaign["id"])
        assert_fields_equal(
            campaign_after,
            live_answer_count_today=0,
            voided_attempt_count=1,
            status=CampaignStatus.ACTIVE,
        )
        assert_decimal_equals(campaign_after["regulatory_abandonment_rate_pct"], 0.00)
        assert_decimal_equals(campaign_after["internal_abandonment_rate_pct"], 0.00)

        credited = world.read_contact(contact["id"])
        assert_fields_equal(credited, attempts_charged=0, attempt_budget_remaining=3)
        assert_attempt_budget_conserved(credited)


class TestConsentRecordListing:
    """Consent listings narrow by consumer and by status."""

    def test_07_consent_listing_narrows_by_contact_and_by_status(self, api, world):
        """With one active record on the first consumer and a suspended record on the
        second, each filter combination returns exactly its own row.

        PRD 3.2: "Listing consent records may be narrowed by `contact_id`, by the
        `disclosure_script_id` the records were captured under, by `channel` and by
        `status`, with `limit` and `offset` for paging."

        PRD 3.2: "the record moves `ACTIVE → SUSPENDED`, the contact's
        `active_consent_count` and `suspended_consent_count` are recomputed while
        `total_consent_count` stays put, and the contact's `version` increments."

        Design: Corner/endpoints/consent_records_listing_filters_by_contact_and_status
        """
        world.set_clock("2026-08-03T00:00:00Z")
        world.create_ca_policy()
        first = world.create_ca_contact()
        second = world.create_second_ca_contact()
        script = world.approved_script()

        active_record = world.create_consent(first["id"], script["id"])
        suspended_record = world.create_consent(
            second["id"], script["id"], signature_evidence="evidence-c2"
        )
        world.suspend_consent(
            suspended_record["id"], reason="Double opt-in token unverified"
        )

        rows, meta = validate_paginated(
            api.list_consent_records(
                world.officer,
                {"contact_id": first["id"], "status": ConsentStatus.ACTIVE},
            )
        )
        assert_total_count(meta, 1)
        assert meta["has_more"] is False
        assert meta["offset"] == 0
        assert ids_of(rows) == [active_record["id"]]

        suspended_rows, suspended_meta = validate_paginated(
            api.list_consent_records(
                world.officer, {"status": ConsentStatus.SUSPENDED}
            )
        )
        assert_total_count(suspended_meta, 1)
        assert ids_of(suspended_rows) == [suspended_record["id"]]

        second_after = world.read_contact(second["id"])
        assert_fields_equal(
            second_after, suspended_consent_count=1, active_consent_count=0
        )
        assert_consent_census_conserved(second_after)


class TestCallingWindowPolicyListing:
    """Policy listings narrow by state and by emergency status."""

    def test_08_policy_listing_narrows_by_state_and_emergency_status(self, api, world):
        """An emergency declared on the California policy leaves that policy ACTIVE with
        an ACTIVE emergency, while the untouched Nevada policy stays at NONE, and each
        filter returns exactly one row.

        PRD 3.5: "Policies may be read individually — returning the derived minute bounds
        and the emergency status — or listed, narrowed by `state_code`, by the
        `supersedes_policy_id` they name, by `status` and by `emergency_status`, and paged
        with `limit` and `offset`."

        PRD 3.5: "The declaration is a self-loop on `status`, `ACTIVE → ACTIVE` — the
        policy stays `ACTIVE` — with the change landing on the independent
        `emergency_status` field, which moves `NONE → ACTIVE`, alongside
        `emergency_declared_at` stamped at the current clock instant and the note stored."

        Design: Corner/endpoints/calling_window_policy_listing_filters_by_state_and_emergency_status
        """
        world.set_clock("2026-08-03T00:00:00Z")
        california = world.create_ca_policy()
        nevada = world.create_policy(state_code=STATE_NV)

        assert_ok(
            api.declare_policy_emergency(
                california["id"],
                factories.declare_emergency_payload(
                    emergency_note="Statewide wildfire evacuation"
                ),
                world.admin,
            )
        )

        rows, meta = validate_paginated(
            api.list_calling_window_policies(
                world.admin,
                {
                    "state_code": STATE_CA,
                    "emergency_status": EmergencyStatus.ACTIVE,
                },
            )
        )
        assert_total_count(meta, 1)
        assert meta["has_more"] is False
        assert ids_of(rows) == [california["id"]]

        declared = assert_ok(
            api.get_calling_window_policy(california["id"], world.admin)
        )
        assert_fields_equal(
            declared,
            status=PolicyStatus.ACTIVE,
            emergency_status=EmergencyStatus.ACTIVE,
        )
        assert_timestamp_equals(
            declared["emergency_declared_at"], "2026-08-03T00:00:00.000Z"
        )

        untouched = assert_ok(api.get_calling_window_policy(nevada["id"], world.admin))
        assert_fields_equal(untouched, emergency_status=EmergencyStatus.NONE)
        assert_fields_null(untouched, "emergency_declared_at")

        quiet_rows, quiet_meta = validate_paginated(
            api.list_calling_window_policies(
                world.admin, {"emergency_status": EmergencyStatus.NONE}
            )
        )
        assert_total_count(quiet_meta, 1)
        assert ids_of(quiet_rows) == [nevada["id"]]


class TestScrubJobRead:
    """Reading a scrub job returns the dated evidence it stored."""

    def test_09_scrub_job_read_returns_the_counts_and_the_validity_window(
        self, api, world, scrubbed_campaign
    ):
        """The completed job read reports the lists it ran against, both stamps at the
        instant it ran, an expiry 31 days later and no failure or invalidation reason.

        PRD 3.4: "The job's `completed_at` is stamped at the current clock instant and
        `expires_at` is set to 31 days after `completed_at`."

        PRD 3.4: "`contacts_scrubbed_count` is the number of contacts whose `state_code`
        appears in the campaign's `target_state_codes`."

        Design: Corner/endpoints/scrub_job_read_returns_the_stored_job
        """
        job = assert_ok(
            api.get_scrub_job(scrubbed_campaign["scrub_job"]["id"], world.admin)
        )
        assert_status(job, ScrubJobStatus.COMPLETED)
        assert_timestamp_equals(job["requested_at"], "2026-08-03T00:00:00.000Z")
        assert_timestamp_equals(job["completed_at"], "2026-08-03T00:00:00.000Z")
        assert_timestamp_equals(job["expires_at"], "2026-09-03T00:00:00.000Z")
        assert job["list_types"] == [ListType.NATIONAL, ListType.INTERNAL]
        assert_fields_equal(
            job,
            campaign_id=scrubbed_campaign["campaign"]["id"],
            contacts_scrubbed_count=1,
            contacts_suppressed_count=0,
            eligible_target_count=1,
        )
        assert_fields_null(job, "failure_reason", "invalidation_reason")


class TestRevocationRequestRead:
    """One revocation row carries two independent state dimensions."""

    def test_10_validated_revocation_read_shows_intake_and_propagation_together(
        self, api, world
    ):
        """After validation the read shows VALIDATED intake alongside IN_PROGRESS
        propagation, the ten-business-day deadline, and the consent it revoked.

        PRD 3.3: "The intake dimension, `intake_status`, starts at `RECEIVED` and moves to
        either `VALIDATED` or `REJECTED`; `REJECTED` is terminal. The propagation
        dimension, `propagation_status`, starts at `NOT_STARTED`, is advanced to
        `IN_PROGRESS` by validation, and from there reaches either `PROPAGATED` or
        `OVERDUE`, both of which are terminal for that dimension."

        PRD 3.3: "Intake also fixes the deadline. `propagation_deadline_at` is ten
        business days after `received_at`, counted as follows."

        Design: Corner/endpoints/revocation_request_read_shows_both_state_dimensions
        """
        world.set_clock("2026-08-03T14:00:00Z")
        world.create_ca_policy()
        contact = world.create_ca_contact()
        script = world.approved_script()
        consent = world.create_consent(contact["id"], script["id"])

        revocation = world.create_revocation(contact["id"])
        world.validate_revocation(revocation["id"])

        row = assert_ok(api.get_revocation_request(revocation["id"], world.operator))
        assert_fields_equal(
            row,
            intake_status=IntakeStatus.VALIDATED,
            propagation_status=PropagationStatus.IN_PROGRESS,
            consent_records_revoked_count=1,
        )
        assert_timestamp_equals(row["received_at"], "2026-08-03T14:00:00.000Z")
        assert_timestamp_equals(row["validated_at"], "2026-08-03T14:00:00.000Z")
        assert_timestamp_equals(
            row["propagation_deadline_at"], "2026-08-17T14:00:00.000Z"
        )
        assert_fields_null(row, "propagated_at", "rejection_reason", "target_systems")

        revoked = assert_ok(api.get_consent_record(consent["id"], world.officer))
        assert_status(revoked, ConsentStatus.REVOKED)

        suppressed = world.read_contact(contact["id"])
        assert_fields_equal(
            suppressed, internal_dnc_status=InternalDncStatus.SUPPRESSED
        )


class TestComplaintRead:
    """Intake computes only the provisional score."""

    def test_11_open_complaint_read_shows_the_provisional_score_and_null_findings(
        self, api, world, active_campaign
    ):
        """A direct time-window complaint against a consumer with one charged attempt
        scores 20.00 provisionally, with every adjudication field still null.

        PRD 3.9: "Both variants begin with the source weight multiplied by 10 source
        points plus the violation weight multiplied by 8 violation points."

        PRD 3.9: "To those two weighted terms it adds an attempt contribution: the lesser
        of the consumer's `attempts_charged` and a cap of 5 attempts, multiplied by 2
        provisional points per attempt."

        PRD 3.9: "`pattern_cluster_size` is the number of complaints in that cluster,
        counting the anchor itself when the anchor qualifies, and it is 1 for a lone
        qualifying complaint."

        Design: Corner/endpoints/complaint_read_shows_the_provisional_score_before_adjudication
        """
        campaign = active_campaign["campaign"]
        contact = active_campaign["contact"]

        attempt = world.create_attempt(campaign["id"], contact["id"])
        world.record_outcome(
            attempt["id"],
            outcome=AttemptOutcome.CONNECTED_LIVE,
            agent_connect_seconds=1,
        )

        complaint = world.create_complaint(
            contact["id"],
            campaign["id"],
            source=ComplaintSource.DIRECT,
            alleged_violation_type=AllegedViolationType.TIME_WINDOW,
            narrative="Consumer reported an unwanted call",
            litigation_flag=False,
        )

        row = assert_ok(api.get_complaint(complaint["id"], world.admin))
        assert_status(row, ComplaintStatus.OPEN)
        assert_decimal_equals(row["provisional_risk_score"], 20.00)
        assert_fields_null(
            row,
            "adjudicated_risk_score",
            "verified_attempt_count",
            "exposure_cents",
            "willful",
            "finding_note",
            "dismissal_note",
        )
        assert_fields_equal(row, pattern_cluster_size=1, litigation_flag=False)

        unchanged_tier = world.read_contact(contact["id"])
        assert_fields_equal(unchanged_tier, risk_tier=RiskTier.LOW)
