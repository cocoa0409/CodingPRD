"""The cross-cutting layers: optimistic concurrency and counter-driven triggers.

These behaviours are not owned by any one endpoint. Version guards recur on three
unrelated write paths, and two separate counters — a failure streak and a reject
rate — fire state transitions when they cross their declared boundaries. Each
case walks the boundary from the accepting side to the refusing side and back.
"""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers.fixtures import HieHarness
from test_helpers.test_users import (
    make_hie_admin_headers,
    make_participant_admin_headers,
    make_privacy_officer_headers,
)


class TestAllThreeVersionGuards:
    """One guard per declared concurrency rule, each on its own write endpoint."""

    POLICY_OFFICER = "privacy-policy-1"
    TUNER = "privacy-tuner-1"
    STEWARD = "privacy-steward-1"
    SIGNATORY = "admin-legal-1"

    def _participant(self, hie: HieHarness, legal_name: str, email: str, org_type: str, volume: int):
        return hie.participant_in_conformance_testing(
            legal_name=legal_name,
            org_type=org_type,
            declared_annual_patient_volume=volume,
            primary_contact_email=email,
            signatory_headers=make_hie_admin_headers(self.SIGNATORY),
        )

    def test_a_stale_number_is_refused_on_each_path_and_the_refreshed_one_is_accepted(
        self, hie: HieHarness
    ):
        """Feed provisioning, directive recording and link confirmation each guard a parent.

        PRD 2.6: "When `expected_cluster_version` does not equal the cluster's
        current `version` the request is rejected with `ERR_STALE_CLUSTER_VERSION`
        (HTTP 412)."

        PRD 2.6: "A mismatch with the participant's current `version` is rejected
        with `ERR_STALE_PARTICIPANT_VERSION` (HTTP 412)."

        PRD 3.1: "Each step is requested as an `action` value on a single
        multiplexed onboarding capability, and every step increments the
        participant's `version` by 1."

        PRD 2.10: "Second, **every mutated row advances**: each entity a cascade
        touches has its own `updated_at` refreshed and its own `version` incremented
        by exactly 1, including entities the caller never named."

        Design: Corner/Cross-Cutting Complexity Layers/all_three_concurrency_rules_reject_a_stale_version_and_accept_the_refreshed_one
        """
        policy_officer = make_privacy_officer_headers(self.POLICY_OFFICER)
        hie.activate_consent_policy(
            policy_version="H1-POLICY-1",
            model="OPT_OUT",
            sensitive_categories_segmented=["HIV"],
            default_share_for_treatment=True,
            effective_from="2026-01-01T00:00:00Z",
            headers=policy_officer,
        )
        hie.activate_threshold_config(
            config_label="REF-PROB-H1", headers=make_privacy_officer_headers(self.TUNER)
        )
        left_owner = self._participant(
            hie, "Cedarbluff Regional Hospital", "hie@cedarbluff.example", "HOSPITAL", 72000
        )
        right_owner = self._participant(
            hie, "Dovewood Family Clinic", "hie@dovewood.example", "CLINIC", 24000
        )
        assert left_owner["version"] == 3

        first_feed = get_success_data(
            hie.client.provision_data_feed(
                hie.admin, left_owner["id"], feed_type="CCDA", expected_participant_version=3
            )
        )
        assert first_feed["status"] == "PROVISIONING"
        assert first_feed["generation"] == 1

        validate_error(
            hie.client.provision_data_feed(
                hie.admin, left_owner["id"], feed_type="ADT", expected_participant_version=3
            ),
            "ERR_STALE_PARTICIPANT_VERSION",
            412,
        )
        assert hie.participant_version(left_owner["id"]) == 4

        second_feed = get_success_data(
            hie.client.provision_data_feed(
                hie.admin, left_owner["id"], feed_type="ADT", expected_participant_version=4
            )
        )
        assert second_feed["status"] == "PROVISIONING"
        assert second_feed["generation"] == 1
        assert hie.participant_version(left_owner["id"]) == 5

        left_record = hie.contribute_record(
            left_owner["id"],
            headers=hie.admin,
            source_mrn="H1-A1",
            given_name="Maria",
            family_name="Gonzalez",
            birth_date="1991-07-22",
            sex="F",
            ssn_last4="3321",
            postal_code="78701",
            phone_digits="5125550143",
        )
        right_record = hie.contribute_record(
            right_owner["id"],
            headers=hie.admin,
            source_mrn="H1-B1",
            given_name="Mari",
            family_name="Gonzales",
            birth_date="1991-07-22",
            sex="F",
            ssn_last4="3321",
            postal_code="78701",
            phone_digits="2125550143",
        )
        cluster_id = left_record["cluster_id"]
        proposed = hie.get_cluster(cluster_id)
        assert proposed["pending_review_link_count"] == 1
        assert proposed["version"] == 2

        directive = get_success_data(
            hie.client.record_consent_directive(
                policy_officer,
                cluster_id,
                directive_type="OPT_OUT",
                scope="ALL_PARTICIPANTS",
                expected_cluster_version=2,
            )
        )
        assert directive["status"] == "ACTIVE"

        validate_error(
            hie.client.record_consent_directive(
                policy_officer,
                cluster_id,
                directive_type="SENSITIVE_CATEGORY_RESTRICTION",
                scope="ALL_PARTICIPANTS",
                restricted_categories=["HIV"],
                expected_cluster_version=2,
            ),
            "ERR_STALE_CLUSTER_VERSION",
            412,
        )
        assert hie.cluster_version(cluster_id) == 3

        steward = make_privacy_officer_headers(self.STEWARD)
        link = hie.only_link_between(right_record["id"])
        assert link["left_record_id"] == left_record["id"]

        validate_error(
            hie.client.record_steward_decision(
                steward,
                link["id"],
                decision="CONFIRM",
                expected_cluster_version=2,
                review_note="Same patient",
            ),
            "ERR_STALE_CLUSTER_VERSION",
            412,
        )
        confirmed = validate_success(
            hie.client.record_steward_decision(
                steward,
                link["id"],
                decision="CONFIRM",
                expected_cluster_version=3,
                review_note="Same patient",
            ),
            200,
        )
        assert confirmed["status"] == "LINKED"

        merged = hie.get_cluster(cluster_id)
        assert merged["version"] == 4
        assert merged["member_record_count"] == 2
        assert merged["status"] == "ACTIVE"


class TestTheFailureStreakTripsRemediation:
    """The trigger is a counter with a boundary, not a per-result reaction."""

    SIGNATORY = "admin-legal-1"

    @staticmethod
    def _booked_run(hie: HieHarness, participant_id: str):
        return get_success_data(
            hie.client.schedule_conformance_test(
                hie.admin,
                participant_id,
                profile="ADT_PUBLISHER",
                scheduled_start="2026-08-01T00:00:00Z",
                scheduled_end="2026-08-01T06:00:00Z",
            )
        )

    def test_only_the_third_consecutive_failure_fires_remediation_and_resuming_resets_the_streak(
        self, hie: HieHarness
    ):
        """Two failures change nothing; the third transitions, and the reset spares the history.

        PRD 3.2: "On a failure, `consecutive_failed_attempts` is incremented by 1,
        and when it reaches the consecutive-failure limit of three the server
        immediately fires the system transition `CONFORMANCE_TESTING → REMEDIATION`
        on the owning participant, incrementing `remediation_count` by 1, leaving
        `suspension_reason` untouched and leaving `passed_profiles` intact."

        PRD 3.2: "Booking also increments the participant's
        `conformance_attempt_count` by 1."

        PRD 3.1: "A `ParticipantAdmin` acting for its own organization closes the
        loop by resuming conformance, `REMEDIATION → CONFORMANCE_TESTING`, which
        resets `consecutive_failed_attempts` to 0 while deliberately preserving both
        `passed_profiles` and `conformance_attempt_count` — nothing already proven is
        thrown away."

        PRD 3.2: "On a pass, the run's `profile` is appended to the participant's
        `passed_profiles` with set semantics — deduplicated and re-sorted in
        ascending order — and `consecutive_failed_attempts` is reset to 0."

        Design: Corner/Cross-Cutting Complexity Layers/three_consecutive_failed_runs_trip_remediation_and_resuming_resets_the_counter
        """
        participant = hie.participant_in_conformance_testing(
            legal_name="Elmshade Community Hospital",
            org_type="HOSPITAL",
            declared_annual_patient_volume=48000,
            primary_contact_email="hie@elmshade.example",
            signatory_headers=make_hie_admin_headers(self.SIGNATORY),
        )

        for attempt in (1, 2, 3):
            run = self._booked_run(hie, participant["id"])
            assert run["attempt_number"] == attempt
            result = validate_success(
                hie.client.submit_conformance_result(
                    hie.admin,
                    run["id"],
                    assertions_total=200,
                    assertions_passed=180,
                    failure_categories=["VOCABULARY"],
                ),
                200,
            )
            assert result["status"] == "FAILED"
            if attempt == 1:
                assert result["pass_rate"] == pytest.approx(0.9000, abs=0.0001)
            owner = hie.get_participant(participant["id"])
            assert owner["consecutive_failed_attempts"] == attempt
            if attempt < 3:
                assert owner["onboarding_status"] == "CONFORMANCE_TESTING"
                assert owner["remediation_count"] == 0
            else:
                assert owner["onboarding_status"] == "REMEDIATION"
                assert owner["remediation_count"] == 1
                assert owner["conformance_attempt_count"] == 3

        resumed = validate_success(
            hie.client.transition_onboarding(
                make_participant_admin_headers(participant["id"]),
                participant["id"],
                action="RESUME_CONFORMANCE",
            ),
            200,
        )
        assert resumed["onboarding_status"] == "CONFORMANCE_TESTING"
        assert resumed["consecutive_failed_attempts"] == 0
        assert resumed["remediation_count"] == 1
        assert resumed["conformance_attempt_count"] == 3

        fourth = self._booked_run(hie, participant["id"])
        assert fourth["attempt_number"] == 4
        passed = validate_success(
            hie.client.submit_conformance_result(
                hie.admin, fourth["id"], assertions_total=200, assertions_passed=200
            ),
            200,
        )
        assert passed["status"] == "PASSED"
        assert passed["pass_rate"] == pytest.approx(1.0000, abs=0.0001)

        after = hie.get_participant(participant["id"])
        assert after["onboarding_status"] == "CONFORMANCE_TESTING"
        assert after["consecutive_failed_attempts"] == 0
        assert after["passed_profiles"] == ["ADT_PUBLISHER"]


class TestTheDegradationBoundaryIsStrict:
    """A single extra rejected message is the whole difference."""

    SAMPLE_SHAPE = dict(
        messages_received=2000,
        required_fields_missing_count=20,
        duplicate_count=10,
        timeliness_p95_seconds=200,
    )

    def test_the_rate_at_the_boundary_monitors_and_one_cent_above_it_degrades(
        self, hie: HieHarness
    ):
        """0.0500 monitors, 0.0505 degrades, and 0.0500 again restores monitoring.

        PRD 3.9: "The degradation boundary is a reject rate of 0.0500."

        PRD 3.9: "Thereafter an accepted sample whose `reject_rate` is strictly
        greater than 0.0500 drives `MONITORED → DEGRADED`, setting `status_reason`
        to `REJECT_RATE_BREACH`; an accepted sample whose `reject_rate` is at or
        below 0.0500 drives `DEGRADED → MONITORED`, clearing `status_reason`."

        PRD 3.9: "Each accepted sample records the addressed feed as its
        `data_feed_id` and stores its own `reject_rate`, computed as
        `messages_rejected` divided by the greater of one and `messages_received`,
        rounded half up to four decimal places — the guard in the denominator means
        a window with no traffic yields a reject rate of exactly zero rather than an
        undefined value."

        Design: Corner/Cross-Cutting Complexity Layers/feed_degradation_fires_strictly_above_the_reject_rate_and_recovers_at_it
        """
        participant = hie.participant_in_conformance_testing(
            legal_name="Foxglove Valley Hospital",
            org_type="HOSPITAL",
            declared_annual_patient_volume=60000,
            primary_contact_email="hie@foxglove.example",
        )
        feed = hie.provision_feed(participant["id"], feed_type="CCDA")
        assert feed["status"] == "PROVISIONING"
        assert feed["version"] == 1

        at_boundary = hie.record_sample(
            feed["id"],
            period_start="2026-06-01T00:00:00Z",
            period_end="2026-06-15T00:00:00Z",
            messages_rejected=100,
            **self.SAMPLE_SHAPE,
        )
        assert at_boundary["reject_rate"] == pytest.approx(0.0500, abs=0.0001)
        monitored = hie.get_data_feed(feed["id"])
        assert monitored["status"] == "MONITORED"
        assert monitored["status_reason"] is None
        assert monitored["latest_reject_rate"] == pytest.approx(0.0500, abs=0.0001)
        assert monitored["version"] == 2

        above_boundary = hie.record_sample(
            feed["id"],
            period_start="2026-06-15T00:00:00Z",
            period_end="2026-07-01T00:00:00Z",
            messages_rejected=101,
            **self.SAMPLE_SHAPE,
        )
        assert above_boundary["reject_rate"] == pytest.approx(0.0505, abs=0.0001)
        degraded = hie.get_data_feed(feed["id"])
        assert degraded["status"] == "DEGRADED"
        assert degraded["status_reason"] == "REJECT_RATE_BREACH"
        assert degraded["latest_reject_rate"] == pytest.approx(0.0505, abs=0.0001)
        assert degraded["version"] == 3

        back_to_boundary = hie.record_sample(
            feed["id"],
            period_start="2026-07-01T00:00:00Z",
            period_end="2026-07-15T00:00:00Z",
            messages_rejected=100,
            **self.SAMPLE_SHAPE,
        )
        assert back_to_boundary["reject_rate"] == pytest.approx(0.0500, abs=0.0001)
        recovered = hie.get_data_feed(feed["id"])
        assert recovered["status"] == "MONITORED"
        assert recovered["status_reason"] is None
        assert recovered["latest_reject_rate"] == pytest.approx(0.0500, abs=0.0001)
        assert recovered["version"] == 4
        assert recovered["sample_count"] == 3
