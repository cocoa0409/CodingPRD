"""Operations gated by the state of a different entity entirely.

In each pair the request body, the caller and every other precondition are held
constant; only a sibling row's state moves, and that alone decides whether the
operation is refused or accepted.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.factories import patient_record_payload
from test_helpers.fixtures import HieHarness
from test_helpers.test_users import make_clinician_headers, make_privacy_officer_headers


class TestLocatorQueryWaitsForTheDocumentFeed:
    """The query is refused while the CCDA feed is PROVISIONING and accepted once it is not."""

    QUERYING_CLINICIAN = "clin-m-1"
    RECORD = patient_record_payload(
        source_mrn="M-9001",
        given_name="Priya",
        family_name="Raghunathan",
        birth_date="1983-06-14",
        sex="F",
        ssn_last4="5108",
        postal_code="60614",
        phone_digits="3125550177",
    )
    DEMOGRAPHICS = {
        "family_name": "Raghunathan",
        "given_name": "Priya",
        "birth_date": "1983-06-14",
        "sex": "F",
        "ssn_last4": "5108",
        "postal_code": "60614",
        "phone_digits": "3125550177",
    }
    CLEAN_SAMPLE = {
        "period_start": "2026-06-01T00:00:00Z",
        "period_end": "2026-07-01T00:00:00Z",
        "messages_received": 10000,
        "messages_rejected": 300,
        "required_fields_missing_count": 500,
        "duplicate_count": 100,
        "timeliness_p95_seconds": 240,
    }
    BREACHING_SAMPLE = dict(CLEAN_SAMPLE, messages_rejected=800)

    def _certified_with_record(self, hie: HieHarness):
        """Governance, a certified hospital and one clustered patient — but no live feed."""
        policy = hie.activate_consent_policy(
            policy_version="SP-2026.6",
            model="OPT_OUT",
            default_share_for_treatment=True,
            effective_from="2026-01-01T00:00:00Z",
        )
        hie.activate_threshold_config(
            headers=make_privacy_officer_headers("privacy-tuner-1"),
            config_label="REF-PROB-M",
            score_variant_mode="PROBABILISTIC_ONLY",
        )
        participant = hie.certified_participant(
            legal_name="Meridian Lakes Health System",
            org_type="HOSPITAL",
            declared_annual_patient_volume=132000,
            primary_contact_email="hie@meridianlakes.example",
        )
        record = hie.contribute_record(participant["id"], headers=hie.admin, **self.RECORD)
        return policy, participant, record

    def _submit(self, hie: HieHarness, participant_id: str):
        return hie.client.submit_record_locator_query(
            make_clinician_headers(self.QUERYING_CLINICIAN),
            querying_participant_id=participant_id,
            purpose_of_use="TREATMENT",
            **self.DEMOGRAPHICS,
        )

    def test_identical_query_flips_from_refused_to_accepted_when_the_feed_is_sampled(
        self, hie: HieHarness
    ):
        """A PROVISIONING document feed cannot carry a response; a MONITORED one can.

        PRD 3.7: "And that participant must have at least one data feed of
        `feed_type` `CCDA` whose `status` is `MONITORED` or `DEGRADED`: a document
        feed still `PROVISIONING`, or one that is `SUSPENDED` or `RETIRED`, cannot
        carry a locator response, and the query is refused with
        `ERR_QUERY_FEED_NOT_OPERATIONAL`."

        PRD 3.9: "The first accepted sample on a feed drives
        `PROVISIONING → MONITORED`, sets `latest_reject_rate`, and re-runs the
        scorecard because the feed has just entered the qualifying status set."

        Design: Difficulty/cross_entity_state_dependency/locator_query_blocked_until_the_ccda_feed_leaves_provisioning
        """
        policy, participant, record = self._certified_with_record(hie)
        feed = hie.provision_feed(participant["id"], feed_type="CCDA")
        assert feed["status"] == "PROVISIONING"

        validate_error(
            self._submit(hie, participant["id"]), "ERR_QUERY_FEED_NOT_OPERATIONAL", 409
        )
        assert (
            validate_success(
                hie.client.list_record_locator_queries(hie.privacy_officer, limit=100), 200
            )
            == []
        )
        assert (
            validate_success(
                hie.client.list_access_audit_entries(hie.privacy_officer, limit=100), 200
            )
            == []
        )

        hie.record_sample(feed["id"], **self.CLEAN_SAMPLE)
        assert hie.get_data_feed(feed["id"])["status"] == "MONITORED"

        query = validate_success(self._submit(hie, participant["id"]), 201)
        assert query["consent_decision"] == "PERMITTED"
        assert query["cluster_id"] == record["cluster_id"]
        assert query["top_candidate_score"] == pytest.approx(1.0000, abs=0.0001)
        assert query["disclosed_record_count"] == 1
        assert query["withheld_record_count"] == 0
        assert query["governing_policy_id"] == policy["id"]
        assert query["governing_directive_id"] is None
        assert query["purpose_of_use"] == "TREATMENT"

        entries = hie.audit_entries_for_query(query["id"])
        assert len(entries) == 1
        assert entries[0]["action"] == "DISCLOSED"
        assert entries[0]["suppression_reason"] is None
        assert entries[0]["record_id"] == record["id"]

    def test_a_monitored_feed_of_the_wrong_type_does_not_open_the_gate(
        self, hie: HieHarness
    ):
        """Only a CCDA feed counts, and a DEGRADED one counts just as well.

        PRD 3.7: "And that participant must have at least one data feed of
        `feed_type` `CCDA` whose `status` is `MONITORED` or `DEGRADED`: a document
        feed still `PROVISIONING`, or one that is `SUSPENDED` or `RETIRED`, cannot
        carry a locator response, and the query is refused with
        `ERR_QUERY_FEED_NOT_OPERATIONAL`."

        PRD 3.9: "If that very first sample's `reject_rate` already exceeds
        0.0500, the feed continues along `MONITORED → DEGRADED` inside the same
        request, so the observable end state is `DEGRADED` with `status_reason`
        set to `REJECT_RATE_BREACH`."

        Design: Difficulty/cross_entity_state_dependency/locator_query_blocked_until_the_ccda_feed_leaves_provisioning
        """
        _policy, participant, record = self._certified_with_record(hie)

        adt_feed = hie.provision_feed(participant["id"], feed_type="ADT")
        hie.record_sample(adt_feed["id"], **self.CLEAN_SAMPLE)
        assert hie.get_data_feed(adt_feed["id"])["status"] == "MONITORED"

        validate_error(
            self._submit(hie, participant["id"]), "ERR_QUERY_FEED_NOT_OPERATIONAL", 409
        )

        document_feed = hie.provision_feed(participant["id"], feed_type="CCDA")
        hie.record_sample(document_feed["id"], **self.BREACHING_SAMPLE)
        degraded = hie.get_data_feed(document_feed["id"])
        assert degraded["status"] == "DEGRADED"
        assert degraded["status_reason"] == "REJECT_RATE_BREACH"

        query = validate_success(self._submit(hie, participant["id"]), 201)
        assert query["consent_decision"] == "PERMITTED"
        assert query["cluster_id"] == record["cluster_id"]
        assert query["disclosed_record_count"] == 1


class TestSubscriptionActivationWaitsForAPassedPublisherRun:
    """The gate is the existence of a strictly PASSED `ADT_PUBLISHER` run."""

    WAIVER_REASON = (
        "Interface engine upgrade already contracted; publisher gap accepted for "
        "one quarter."
    )
    SUBSCRIPTION = {
        "subscription_scope": "PATIENT_PANEL",
        "event_types": ["ADMISSION", "DISCHARGE"],
        "delivery_endpoint_url": "https://northgate.example/adt/hooks",
    }

    def _participant_in_testing(self, hie: HieHarness):
        return hie.participant_in_conformance_testing(
            legal_name="Northgate Community Hospital",
            org_type="HOSPITAL",
            declared_annual_patient_volume=90000,
            primary_contact_email="hie@northgate.example",
        )

    def _certify(self, hie: HieHarness, participant_id: str):
        hie.pass_profile(participant_id, "DOCUMENT_SOURCE")
        hie.pass_profile(participant_id, "QUERY_RESPONDER")
        return validate_success(
            hie.client.transition_onboarding(
                hie.certifier, participant_id, action="CERTIFY"
            ),
            200,
        )

    def test_a_waived_publisher_run_certifies_but_never_activates_a_subscription(
        self, hie: HieHarness
    ):
        """The sibling ConformanceTest is `WAIVED`, which the activation gate rejects.

        PRD 3.2: "Note the deliberate asymmetry between certification and
        subscription activation that this creates — a waived `ADT_PUBLISHER` run
        counts toward certification but, as §3.9 explains, does **not** unlock
        event notification delivery."

        PRD 3.9: "Driving `PENDING_ACTIVATION → ACTIVE` requires the subscriber
        participant to hold a conformance run whose `profile` is `ADT_PUBLISHER`
        and whose `status` is **strictly** `PASSED`; a `WAIVED` run satisfies
        certification but does not satisfy this gate, and its absence is refused
        with `ERR_SUBSCRIPTION_CONFORMANCE_MISSING`."

        Design: Difficulty/cross_entity_state_dependency/subscription_activation_blocked_until_a_fresh_adt_publisher_run_passes
        """
        participant = self._participant_in_testing(hie)
        first_attempt = hie.fail_profile(
            participant["id"],
            "ADT_PUBLISHER",
            assertions_total=200,
            assertions_passed=189,
            failure_categories=["VOCABULARY"],
        )
        assert first_attempt["attempt_number"] == 1
        assert first_attempt["status"] == "FAILED"
        waived = validate_success(
            hie.client.waive_conformance_test(
                hie.admin, first_attempt["id"], waiver_reason=self.WAIVER_REASON
            ),
            200,
        )
        assert waived["status"] == "WAIVED"

        certified = self._certify(hie, participant["id"])
        assert certified["onboarding_status"] == "CERTIFIED"
        assert "ADT_PUBLISHER" in certified["passed_profiles"]

        subscription = hie.create_subscription(participant["id"], **self.SUBSCRIPTION)
        assert subscription["status"] == "PENDING_ACTIVATION"

        validate_error(
            hie.client.transition_subscription_lifecycle(
                hie.admin, subscription["id"], action="ACTIVATE"
            ),
            "ERR_SUBSCRIPTION_CONFORMANCE_MISSING",
            409,
        )
        unchanged = validate_success(
            hie.client.get_notification_subscription(hie.admin, subscription["id"]), 200
        )
        assert unchanged["status"] == "PENDING_ACTIVATION"
        assert unchanged["activating_conformance_test_id"] is None
        assert hie.get_participant(participant["id"])["active_subscription_count"] == 0

    def test_a_second_publisher_attempt_that_passes_unlocks_activation_and_is_pinned(
        self, hie: HieHarness
    ):
        """Once the sibling run reaches PASSED, the same request succeeds and pins it.

        PRD 3.9: "On success the subscription records
        `activating_conformance_test_id` as the `id` of that qualifying run — the
        earliest by `created_at` when several qualify — and the participant's
        `active_subscription_count` increases by 1."

        PRD 3.2: "The created run has `status` `RUNNING`, its `participant_id`
        taken from the path, its `executed_by_user_id` recorded from the acting
        `X-User-ID`, and an `attempt_number` computed as one more than the count
        of that participant's prior runs for the same `profile` — equivalently, the
        run's one-based ordinal among same-profile runs ordered by ascending
        `created_at`."

        Design: Difficulty/cross_entity_state_dependency/subscription_activation_blocked_until_a_fresh_adt_publisher_run_passes
        """
        participant = self._participant_in_testing(hie)
        first_attempt = hie.fail_profile(
            participant["id"],
            "ADT_PUBLISHER",
            assertions_total=200,
            assertions_passed=189,
            failure_categories=["VOCABULARY"],
        )
        assert first_attempt["pass_rate"] == 0.9450
        assert first_attempt["status"] == "FAILED"

        second_attempt = hie.pass_profile(participant["id"], "ADT_PUBLISHER")
        assert second_attempt["attempt_number"] == 2
        assert second_attempt["pass_rate"] == 1.0000
        assert second_attempt["status"] == "PASSED"

        self._certify(hie, participant["id"])
        subscription = hie.create_subscription(participant["id"], **self.SUBSCRIPTION)

        activated = validate_success(
            hie.client.transition_subscription_lifecycle(
                hie.admin, subscription["id"], action="ACTIVATE"
            ),
            200,
        )
        assert activated["status"] == "ACTIVE"
        assert activated["activating_conformance_test_id"] == second_attempt["id"]
        assert hie.get_participant(participant["id"])["active_subscription_count"] == 1
