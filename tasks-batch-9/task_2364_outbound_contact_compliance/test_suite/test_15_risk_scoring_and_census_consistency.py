"""Complaint scoring, statutory exposure, tiering cascades and the immediacy of
derived state.

Every precondition is built through the documented endpoints against an empty
database, and every instant comes from the logical clock.
"""

from __future__ import annotations

from test_helpers import (
    OFFICER_LAUNCHER_USER_ID,
    PHONE_C1,
    AllegedViolationType,
    AttemptOutcome,
    CampaignStatus,
    ComplaintSource,
    ComplaintStatus,
    ComplianceWorld,
    ConsentStatus,
    InternalDncStatus,
    ListType,
    RiskTier,
    ScrubJobStatus,
    SuppressionStatus,
    assert_decimal_equals,
    assert_fields_equal,
    assert_fields_null,
    assert_ok,
    assert_page,
    assert_status,
    assert_timestamp_equals,
    assert_total_count,
    assert_version_is,
)


def _log_dnc_complaint(world: ComplianceWorld, contact_id: str, campaign_id: str):
    """Register one direct do-not-call complaint against a campaign."""
    return world.create_complaint(
        contact_id,
        campaign_id,
        source=ComplaintSource.DIRECT,
        alleged_violation_type=AllegedViolationType.DNC_VIOLATION,
        litigation_flag=False,
    )


class TestComplaintScoringAndStatutoryExposure:
    """The two scoring variants, the exposure formula and the tier ladder."""

    def test_01_statutory_exposure_triples_for_a_willful_finding(
        self, world: ComplianceWorld
    ):
        """One verified attempt found willful is 150000 cents of exposure, and the
        adjudicated score is 22.00 against a provisional 20.00.

        PRD 3.9: "Both variants begin with the source weight multiplied by 10
        source points plus the violation weight multiplied by 8 violation
        points."
        PRD 3.9: "the lesser of the consumer's `attempts_charged` and a cap of 5
        attempts, multiplied by 2 provisional points per attempt"
        PRD 3.9: "Its attempt contribution is uncapped and worth more:
        `verified_attempt_count` multiplied by 4 adjudicated points per attempt"
        PRD 3.9: "`exposure_cents` is `verified_attempt_count` multiplied by a
        statutory base of 50000 cents per attempt, multiplied by 3 when the
        supplied `willful` is true and by 1 when it is false."

        Design: Corner/calculations/statutory_exposure_triples_for_a_willful_finding
        """
        built = world.build(clock="2026-08-03T00:00:00Z")
        campaign_id = built["campaign"]["id"]
        contact_id = built["contact"]["id"]

        world.connected_attempt(campaign_id, contact_id)

        complaint = world.create_complaint(
            contact_id,
            campaign_id,
            source=ComplaintSource.DIRECT,
            alleged_violation_type=AllegedViolationType.TIME_WINDOW,
            litigation_flag=False,
        )
        assert_decimal_equals(complaint["provisional_risk_score"], 20.00)

        found = world.substantiate_complaint(complaint["id"], willful=True)

        assert_status(found, ComplaintStatus.SUBSTANTIATED)
        assert_fields_equal(found, verified_attempt_count=1, exposure_cents=150000)
        assert_decimal_equals(found["adjudicated_risk_score"], 22.00)

        contact = world.read_contact(contact_id)
        assert_fields_equal(
            contact,
            risk_tier=RiskTier.MEDIUM,
            internal_dnc_status=InternalDncStatus.CLEAR,
        )

    def test_02_risk_tier_follows_the_peak_adjudicated_score(
        self, world: ComplianceWorld
    ):
        """A 51.00 litigation finding lifts the consumer to HIGH, and a later
        20.00 finding leaves the peak — and the tier — untouched.

        PRD 3.9: "To that it adds a flat litigation bonus of 15 points when the
        complaint's `litigation_flag` is true, and nothing when it is false."
        PRD 3.9: "Otherwise the thresholds are inclusive at each step: a peak of
        at least 55 makes the tier `CRITICAL`, otherwise a peak of at least 40
        makes it `HIGH`, otherwise a peak of at least 20 makes it `MEDIUM`, and
        anything below 20 leaves it `LOW`."

        Design: Corner/calculations/contact_risk_tier_tracks_the_peak_adjudicated_score
        """
        built = world.build(clock="2026-08-03T00:00:00Z")
        campaign_id = built["campaign"]["id"]
        contact_id = built["contact"]["id"]

        world.connected_attempt(campaign_id, contact_id)

        litigation_complaint = world.create_complaint(
            contact_id,
            campaign_id,
            source=ComplaintSource.LITIGATION,
            alleged_violation_type=AllegedViolationType.NO_CONSENT,
            litigation_flag=True,
        )
        peak = world.substantiate_complaint(litigation_complaint["id"], willful=False)
        assert_decimal_equals(peak["adjudicated_risk_score"], 51.00)
        assert_fields_equal(peak, verified_attempt_count=1, exposure_cents=50000)

        after_peak = world.read_contact(contact_id)
        assert_fields_equal(after_peak, risk_tier=RiskTier.HIGH)

        minor_complaint = world.create_complaint(
            contact_id,
            campaign_id,
            source=ComplaintSource.DIRECT,
            alleged_violation_type=AllegedViolationType.ABANDONMENT,
            litigation_flag=False,
        )
        minor = world.substantiate_complaint(minor_complaint["id"], willful=False)
        assert_decimal_equals(minor["adjudicated_risk_score"], 20.00)

        contact = world.read_contact(contact_id)
        assert_fields_equal(
            contact,
            risk_tier=RiskTier.HIGH,
            internal_dnc_status=InternalDncStatus.CLEAR,
        )

    def test_03_a_critical_score_freezes_the_consumer_and_their_consents(
        self, world: ComplianceWorld
    ):
        """Two verified attempts on a willful litigation finding score exactly
        55.00, which suppresses the consumer and suspends their live consent.

        PRD 3.9: "A peak of exactly 55.00 is `CRITICAL`; a peak of 54.99 is
        `HIGH`."
        PRD 3.9: "When the recomputed `risk_tier` is `CRITICAL`, the consumer's
        `internal_dnc_status` becomes `SUPPRESSED`, an `ACTIVE` internal-list
        suppression entry is created for their `phone_number` if none already
        exists, and every one of their `ACTIVE` consent records moves
        `ACTIVE → SUSPENDED` with `suspended_reason` set to `CRITICAL risk
        tier`."

        Design: Corner/calculations/critical_adjudicated_score_suppresses_the_contact_and_its_consents
        """
        built = world.build(clock="2026-08-03T00:00:00Z")
        campaign_id = built["campaign"]["id"]
        contact_id = built["contact"]["id"]

        world.connected_attempt(campaign_id, contact_id)

        world.set_clock("2026-08-03T00:31:00Z")
        second = world.create_attempt(campaign_id, contact_id)
        world.record_outcome(second["id"], outcome=AttemptOutcome.NO_ANSWER)

        complaint = world.create_complaint(
            contact_id,
            campaign_id,
            source=ComplaintSource.LITIGATION,
            alleged_violation_type=AllegedViolationType.NO_CONSENT,
            litigation_flag=True,
        )
        found = world.substantiate_complaint(complaint["id"], willful=True)

        assert_decimal_equals(found["adjudicated_risk_score"], 55.00)
        assert_fields_equal(found, verified_attempt_count=2, exposure_cents=300000)

        contact = world.read_contact(contact_id)
        assert_fields_equal(
            contact,
            risk_tier=RiskTier.CRITICAL,
            internal_dnc_status=InternalDncStatus.SUPPRESSED,
        )

        consent = assert_ok(
            world.api.get_consent_record(built["consent"]["id"], world.officer)
        )
        assert_status(consent, ConsentStatus.SUSPENDED)
        assert_fields_equal(consent, suspended_reason="CRITICAL risk tier")

        entries, meta = assert_page(
            world.api.list_suppression_entries(
                world.officer,
                {"list_type": ListType.INTERNAL, "status": SuppressionStatus.ACTIVE},
            )
        )
        assert_total_count(meta, 1)
        assert_fields_equal(
            entries[0],
            phone_number=PHONE_C1,
            list_type=ListType.INTERNAL,
            status=SuppressionStatus.ACTIVE,
        )

    def test_04_dismissal_shrinks_every_remaining_cluster_members_count(
        self, world: ComplianceWorld
    ):
        """Three same-day complaints of one kind against one campaign each carry a
        cluster size of 3; dismissing one rewrites the survivors to 2.

        PRD 3.9: "A complaint's cluster consists of the complaints sharing its
        `campaign_id` and its `alleged_violation_type`, whose `status` is `OPEN`
        or `SUBSTANTIATED`, and whose `received_at` lies within 30 days of the
        anchor complaint's `received_at` on either side"
        PRD 3.9: "Because a dismissed complaint leaves the cluster, dismissal
        shrinks every remaining member's count."
        PRD 3.9: "It produces none of the substantiation side effects:
        `adjudicated_risk_score`, `verified_attempt_count`, `exposure_cents` and
        `willful` all stay null, and the consumer's `risk_tier` is not recomputed
        at all."

        Design: Corner/calculations/complaint_pattern_cluster_counts_only_open_and_substantiated_members
        """
        built = world.build(clock="2026-08-03T00:00:00Z")
        campaign_id = built["campaign"]["id"]
        contact_id = built["contact"]["id"]

        world.connected_attempt(campaign_id, contact_id)

        first = _log_dnc_complaint(world, contact_id, campaign_id)
        second = _log_dnc_complaint(world, contact_id, campaign_id)
        third = _log_dnc_complaint(world, contact_id, campaign_id)

        assert third["pattern_cluster_size"] == 3, (
            "the third member must see a cluster of 3, got %s"
            % (third.get("pattern_cluster_size"),)
        )
        first_read = assert_ok(world.api.get_complaint(first["id"], world.officer))
        assert first_read["pattern_cluster_size"] == 3, (
            "earlier members must be rewritten to 3, got %s"
            % (first_read.get("pattern_cluster_size"),)
        )

        dismissed = world.dismiss_complaint(third["id"])
        assert_status(dismissed, ComplaintStatus.DISMISSED)
        assert_fields_null(
            dismissed,
            "adjudicated_risk_score",
            "verified_attempt_count",
            "exposure_cents",
            "willful",
        )

        for survivor_id in (first["id"], second["id"]):
            survivor = assert_ok(world.api.get_complaint(survivor_id, world.officer))
            assert survivor["pattern_cluster_size"] == 2, (
                "a survivor must shrink to 2, got %s"
                % (survivor.get("pattern_cluster_size"),)
            )

        contact = world.read_contact(contact_id)
        assert_fields_equal(
            contact,
            risk_tier=RiskTier.LOW,
            internal_dnc_status=InternalDncStatus.CLEAR,
        )


class TestDerivedStateIsSettledInsideTheTriggeringRequest:
    """Immediate, synchronous propagation of every derived consequence."""

    def test_05_the_launch_response_already_carries_every_certification_effect(
        self, world: ComplianceWorld
    ):
        """Certification returns the running campaign with its pin, its certifier
        and its zeroed measurement day already set, and a following read agrees.

        PRD 2.10: "is applied inside the request that triggered it, and every
        read that follows sees the settled result."
        PRD 3.7: "Its `launch_certified_by_user_id` records the certifying
        officer's `X-User-ID`."
        PRD 3.7: "Its `pinned_script_version` captures the script's `version` at
        this instant, and it is a genuine pin: later edits to that script never
        change the number recorded here."
        PRD 3.7: "`measurement_date` becomes the UTC calendar date of the current
        clock instant, all four of today's counters are set to 0, and both
        `regulatory_abandonment_rate_pct` and `internal_abandonment_rate_pct` are
        set to `0.00`."

        Design: Corner/consistency_model/launch_response_already_carries_every_certification_side_effect
        """
        built = world.build(clock="2026-08-03T00:00:00Z", stop_after="scrub")
        campaign_id = built["campaign"]["id"]

        launched = world.launch_campaign(campaign_id)

        assert_status(launched, CampaignStatus.ACTIVE)
        assert_version_is(launched, 4)
        assert_fields_equal(
            launched,
            pinned_script_version=3,
            launch_certified_by_user_id=OFFICER_LAUNCHER_USER_ID,
            measurement_date="2026-08-03",
            live_answer_count_today=0,
            abandoned_count_today=0,
            machine_count_today=0,
            no_answer_count_today=0,
        )
        assert_decimal_equals(launched["regulatory_abandonment_rate_pct"], 0.00)
        assert_decimal_equals(launched["internal_abandonment_rate_pct"], 0.00)

        reread = world.read_campaign(campaign_id)
        settled_fields = (
            "status",
            "version",
            "pinned_script_version",
            "launch_certified_by_user_id",
            "measurement_date",
            "live_answer_count_today",
            "abandoned_count_today",
            "machine_count_today",
            "no_answer_count_today",
            "regulatory_abandonment_rate_pct",
            "internal_abandonment_rate_pct",
        )
        for field_name in settled_fields:
            assert reread[field_name] == launched[field_name], (
                "read-back disagrees on %s: %r vs %r"
                % (field_name, reread.get(field_name), launched.get(field_name))
            )

    def test_06_the_scrub_execution_response_already_carries_the_derived_counts(
        self, world: ComplianceWorld
    ):
        """Execution returns the completed job with its counts and validity window
        set, and the campaign is already launchable on the very next read.

        PRD 2.10: "is applied inside the request that triggered it, and every
        read that follows sees the settled result."
        PRD 3.4: "`eligible_target_count` is `contacts_scrubbed_count` less
        `contacts_suppressed_count`, and can never be negative because the
        suppressed contacts are a subset of the examined ones."
        PRD 3.4: "The job's `completed_at` is stamped at the current clock instant
        and `expires_at` is set to 31 days after `completed_at`."
        PRD 3.4: "its `latest_scrub_status` becomes `COMPLETED`, its own
        `eligible_target_count` is overwritten with this job's, its `version`
        increments and its `updated_at` refreshes"

        Design: Corner/consistency_model/scrub_execution_response_already_carries_the_derived_counts
        """
        built = world.build(clock="2026-08-03T00:00:00Z", stop_after="campaign")
        campaign_id = built["campaign"]["id"]

        job = world.create_scrub_job(campaign_id)
        executed = world.execute_scrub_job(job["id"])

        assert_status(executed, ScrubJobStatus.COMPLETED)
        assert_fields_equal(
            executed,
            contacts_scrubbed_count=1,
            contacts_suppressed_count=0,
            eligible_target_count=1,
        )
        assert_timestamp_equals(executed["completed_at"], "2026-08-03T00:00:00.000Z")
        assert_timestamp_equals(executed["expires_at"], "2026-09-03T00:00:00.000Z")
        assert_fields_null(executed, "failure_reason", "invalidation_reason")

        campaign = world.read_campaign(campaign_id)
        assert_status(campaign, CampaignStatus.PENDING_LAUNCH)
        assert_version_is(campaign, 3)
        assert_fields_equal(
            campaign,
            latest_scrub_status=ScrubJobStatus.COMPLETED,
            eligible_target_count=1,
        )
