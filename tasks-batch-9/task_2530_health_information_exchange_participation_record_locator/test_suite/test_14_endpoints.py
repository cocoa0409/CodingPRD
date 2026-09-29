"""Whole endpoint families walked end to end on one row.

Each test drives a create, its individual read, its filtered list read and its
not-found sibling — or an action endpoint in both directions — so that the views
of a single row are checked against each other rather than in isolation.
"""

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.fixtures import HieHarness
from test_helpers.test_users import (
    make_clinician_headers,
    make_participant_admin_headers,
    make_privacy_officer_headers,
)


def _testing_participant(hie: HieHarness, legal_name: str, email: str, **overrides):
    overrides.setdefault("org_type", "HOSPITAL")
    overrides.setdefault("declared_annual_patient_volume", 60000)
    return hie.participant_in_conformance_testing(
        legal_name=legal_name, primary_contact_email=email, **overrides
    )


class TestConsentPolicyReadFamily:
    """A drafted generation, its individual read, its filtered list and its absence."""

    POLICY_OFFICER = "privacy-policy-1"

    def test_the_drafted_generation_reads_back_identically_from_every_channel(
        self, hie: HieHarness
    ):
        """One row, three views, and an unknown id that names the policy family.

        PRD 3.3: "Drafting sets `status` to `DRAFT` and `directive_count` to 0, and
        immediately runs an interval-overlap check against every existing policy
        whose `status` is `DRAFT` or `ACTIVE`: any overlap of the half-open
        intervals is rejected with `ERR_CONSENT_POLICY_INTERVAL_OVERLAP`."

        PRD 3.3: "Activating a draft policy moves it `DRAFT → ACTIVE`, records the
        acting `X-User-ID` as `activated_by_user_id`, and re-runs the overlap test
        against the currently `ACTIVE` set, again rejecting with
        `ERR_CONSENT_POLICY_INTERVAL_OVERLAP`."

        PRD 3.3: "Policies are readable individually and as a list filterable by
        `status` and by `model`."

        Design: Corner/Endpoints/consent_policy_create_read_and_list_round_trip
        """
        officer = make_privacy_officer_headers(self.POLICY_OFFICER)
        created = get_success_data(
            hie.client.draft_consent_policy(
                officer,
                policy_version="STATEWIDE-2026.3",
                model="OPT_IN",
                sensitive_categories_segmented=["BEHAVIORAL_HEALTH", "SUD"],
                default_share_for_treatment=False,
                effective_from="2026-10-01T00:00:00Z",
                effective_until="2027-10-01T00:00:00Z",
            )
        )
        assert created["status"] == "DRAFT"
        assert created["directive_count"] == 0
        assert created["activated_by_user_id"] is None
        assert created["version"] == 1
        assert created["effective_until"] == "2027-10-01T00:00:00Z"

        fetched = validate_success(
            hie.client.get_consent_policy(officer, created["id"]), 200
        )
        assert fetched["policy_version"] == "STATEWIDE-2026.3"
        assert fetched["model"] == "OPT_IN"
        assert fetched["sensitive_categories_segmented"] == ["BEHAVIORAL_HEALTH", "SUD"]
        assert fetched["default_share_for_treatment"] is False
        assert fetched["effective_from"] == "2026-10-01T00:00:00Z"
        assert fetched["status"] == "DRAFT"

        listed, meta = validate_paginated(
            hie.client.list_consent_policies(officer, status="DRAFT")
        )
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert [row["id"] for row in listed] == [created["id"]]
        assert listed[0]["status"] == "DRAFT"

        validate_error(
            hie.client.get_consent_policy(officer, NON_EXISTENT_UUID),
            "ERR_CONSENT_POLICY_NOT_FOUND",
            404,
        )


class TestFeedSuspendAndRestore:
    """The status-transition endpoint run in both directions on one feed."""

    SUSPENSION_REASON = "Interface engine migration window"

    def test_suspending_removes_the_only_sample_and_restoring_returns_it(self, hie: HieHarness):
        """The feed keeps its sample either way; only the scorecard input set moves.

        PRD 3.9: "A `HieAdmin` may also suspend a feed directly by supplying a
        `reason`, from any of `PROVISIONING`, `MONITORED` or `DEGRADED` into
        `SUSPENDED`, with `status_reason` set to that `reason` and the scorecard
        re-run with this feed's samples now excluded from the input set."

        PRD 3.9: "Restoring a suspended feed drives `SUSPENDED → MONITORED`, clears
        `status_reason`, and re-runs the scorecard with those samples back in;
        restoration requires that the owning participant's `onboarding_status` is
        not `SUSPENDED`, since a suspended organization cannot have a live pipe."

        PRD 3.9: "When the qualifying set is empty the participant is ungraded:
        `quality_score` is null, `grade` and `provisional_grade` are both
        `UNGRADED`, `penalty_points` is zero, and the four components,
        `average_p95_seconds` and `base_quality_score` are all reported as zero."

        PRD 2.10: "Second, **every mutated row advances**: each entity a cascade
        touches has its own `updated_at` refreshed and its own `version` incremented
        by exactly 1, including entities the caller never named."

        Design: Corner/Endpoints/feed_suspend_and_restore_round_trip_removes_and_returns_the_sample_set
        """
        participant = _testing_participant(
            hie, "Juniper Bluff Hospital", "hie@juniperbluff.example"
        )
        feed = hie.provision_feed(participant["id"], feed_type="ADT")
        assert feed["generation"] == 1
        assert feed["version"] == 1
        hie.record_sample(
            feed["id"],
            period_start="2026-06-01T00:00:00Z",
            period_end="2026-07-01T00:00:00Z",
            messages_received=8000,
            messages_rejected=100,
            required_fields_missing_count=200,
            duplicate_count=50,
            timeliness_p95_seconds=250,
        )

        monitored = hie.get_data_feed(feed["id"])
        assert monitored["status"] == "MONITORED"
        assert monitored["latest_reject_rate"] == pytest.approx(0.0125, abs=0.0001)
        assert monitored["version"] == 2
        before = hie.get_scorecard(participant["id"])
        assert before["samples_counted"] == 1
        assert before["quality_score"] == pytest.approx(98.78, abs=0.001)
        assert before["grade"] == "A"

        suspended = validate_success(
            hie.client.transition_data_feed_status(
                hie.admin, feed["id"], action="SUSPEND", reason=self.SUSPENSION_REASON
            ),
            200,
        )
        assert suspended["status"] == "SUSPENDED"
        assert suspended["status_reason"] == self.SUSPENSION_REASON
        assert suspended["sample_count"] == 1
        assert suspended["version"] == 3

        ungraded = hie.get_scorecard(participant["id"])
        assert ungraded["samples_counted"] == 0
        assert ungraded["quality_score"] is None
        assert ungraded["grade"] == "UNGRADED"
        assert ungraded["provisional_grade"] == "UNGRADED"
        assert ungraded["penalty_points"] == 0
        assert ungraded["base_quality_score"] == pytest.approx(0, abs=0.01)

        restored = validate_success(
            hie.client.transition_data_feed_status(hie.admin, feed["id"], action="RESTORE"),
            200,
        )
        assert restored["status"] == "MONITORED"
        assert restored["status_reason"] is None
        assert restored["version"] == 4

        after = hie.get_scorecard(participant["id"])
        assert after["samples_counted"] == 1
        assert after["quality_score"] == pytest.approx(98.78, abs=0.001)
        assert after["grade"] == "A"


class TestClusterScopedSubscriptionAssociation:
    """Both ends of the association resolve before anything is written."""

    TUNER = "privacy-tuner-1"

    def test_the_body_cluster_and_the_path_participant_are_each_resolved(self, hie: HieHarness):
        """An unknown cluster names the cluster family, an unknown path the participant family.

        PRD 2.9: "A path identifier that resolves to nothing, on any endpoint
        carrying a path id — the family-specific not-found code from §2.7."

        PRD 2.9: "A body identifier that resolves to nothing — the family-specific
        not-found code from §2.7, on locator-query submission, emergency-session
        invocation, directive recording and subscription creation."

        PRD 3.9: "Subscriptions are readable individually and as a list filterable
        by `subscriber_participant_id`, `cluster_id`,
        `activating_conformance_test_id`, `status` and `subscription_scope`."

        Design: Corner/Endpoints/cluster_scoped_subscription_requires_both_endpoints_of_the_association
        """
        hie.activate_threshold_config(
            config_label="REF-PROB-E3", headers=make_privacy_officer_headers(self.TUNER)
        )
        participant = _testing_participant(
            hie,
            "Kestrel Point Hospital",
            "hie@kestrelpoint.example",
            declared_annual_patient_volume=72000,
        )
        record = hie.contribute_record(
            participant["id"],
            headers=hie.admin,
            source_mrn="E3-0001",
            given_name="Lorcan",
            family_name="Delacroix",
            birth_date="1990-07-30",
            sex="M",
            ssn_last4="1188",
            postal_code="70118",
            phone_digits="5045550125",
        )
        cluster_id = record["cluster_id"]

        validate_error(
            hie.client.create_notification_subscription(
                hie.admin,
                participant["id"],
                subscription_scope="CLUSTER",
                event_types=["ADMISSION", "DISCHARGE", "TRANSFER"],
                delivery_endpoint_url="https://kestrelpoint.example/adt",
                cluster_id=NON_EXISTENT_UUID,
            ),
            "ERR_CLUSTER_NOT_FOUND",
            404,
        )
        validate_error(
            hie.client.create_notification_subscription(
                hie.admin,
                NON_EXISTENT_UUID,
                subscription_scope="CLUSTER",
                event_types=["ADMISSION"],
                delivery_endpoint_url="https://kestrelpoint.example/adt",
                cluster_id=cluster_id,
            ),
            "ERR_PARTICIPANT_NOT_FOUND",
            404,
        )

        created = get_success_data(
            hie.client.create_notification_subscription(
                hie.admin,
                participant["id"],
                subscription_scope="CLUSTER",
                event_types=["ADMISSION", "DISCHARGE", "TRANSFER"],
                delivery_endpoint_url="https://kestrelpoint.example/adt",
                cluster_id=cluster_id,
            )
        )
        assert created["status"] == "PENDING_ACTIVATION"
        assert created["cluster_id"] == cluster_id
        assert created["subscriber_participant_id"] == participant["id"]
        assert created["event_types"] == ["ADMISSION", "DISCHARGE", "TRANSFER"]
        assert created["activating_conformance_test_id"] is None

        listed, meta = validate_paginated(
            hie.client.list_notification_subscriptions(hie.admin, cluster_id=cluster_id)
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in listed] == [created["id"]]
        assert listed[0]["subscription_scope"] == "CLUSTER"
        assert hie.get_participant(participant["id"])["active_subscription_count"] == 0


class TestSegmentedLocatorDisclosure:
    """The stored query row and the audit trail are two views of one computation."""

    POLICY_OFFICER = "privacy-policy-1"
    TUNER = "privacy-tuner-1"
    CLINICIAN = "clin-e4-1"

    def test_a_segmented_member_is_withheld_and_still_earns_its_audit_row(self, hie: HieHarness):
        """One member discloses, the other is segmented away, and both are audited.

        PRD 3.7: "Otherwise, if the member's `sensitive_categories` has at least
        one category in common with the suppressed-category set, the member is
        recorded with an `action` of `WITHHELD` — carrying a `suppression_reason`
        of `PURPOSE_RESTRICTED` when `purpose_of_use` is `PAYMENT` or
        `OPERATIONS`, and of `SENSITIVE_CATEGORY` otherwise."

        PRD 3.7: "The **governing directive** is the first row of that ordered set
        whose `directive_type` is `OPT_IN` or `OPT_OUT`, and its `id` is recorded
        as `governing_directive_id`; when no such row exists,
        `governing_directive_id` stays null and the policy default governs
        instead."

        PRD 3.7: "otherwise `PARTIAL_SEGMENTED` when at least one member was
        disclosed and at least one was withheld"

        PRD 3.7: "Exactly one access audit entry is written per cluster member, in
        the same ascending `created_at` order, and entries are written for
        withheld members just as for disclosed ones."

        Design: Corner/Endpoints/segmented_locator_query_returns_partial_disclosure_with_one_audit_row_per_member
        """
        policy = hie.activate_consent_policy(
            policy_version="E4-POLICY-1",
            model="OPT_OUT",
            sensitive_categories_segmented=["BEHAVIORAL_HEALTH"],
            default_share_for_treatment=True,
            effective_from="2026-01-01T00:00:00Z",
            headers=make_privacy_officer_headers(self.POLICY_OFFICER),
        )
        hie.activate_threshold_config(
            config_label="REF-DET-E4",
            score_variant_mode="DETERMINISTIC_FIRST",
            headers=make_privacy_officer_headers(self.TUNER),
        )

        querier = hie.certified_participant_with_document_feed(
            legal_name="Lantern Cove Medical Center",
            org_type="HOSPITAL",
            declared_annual_patient_volume=96000,
            primary_contact_email="hie@lanterncove.example",
        )
        contributor = _testing_participant(
            hie,
            "Marrowbrook Behavioral Clinic",
            "hie@marrowbrook.example",
            org_type="CLINIC",
            declared_annual_patient_volume=24000,
        )

        open_record = hie.contribute_record(
            querier["id"],
            headers=hie.admin,
            source_mrn="E4-A1",
            given_name="Nadia",
            family_name="Vasquez",
            birth_date="1984-03-27",
            sex="F",
            ssn_last4="4451",
            postal_code="19104",
            phone_digits="2155550190",
        )
        segmented_record = hie.contribute_record(
            contributor["id"],
            headers=hie.admin,
            source_mrn="E4-B1",
            given_name="Nadia",
            family_name="Vasquez",
            birth_date="1984-03-27",
            sex="F",
            ssn_last4="4451",
            postal_code="19147",
            phone_digits="2155550177",
            sensitive_categories=["BEHAVIORAL_HEALTH"],
        )
        cluster_id = open_record["cluster_id"]
        assert segmented_record["cluster_id"] == cluster_id
        assert hie.get_cluster(cluster_id)["member_record_count"] == 2

        directive = hie.record_directive(
            cluster_id,
            directive_type="SENSITIVE_CATEGORY_RESTRICTION",
            scope="ALL_PARTICIPANTS",
            restricted_categories=["BEHAVIORAL_HEALTH"],
            headers=make_privacy_officer_headers(self.POLICY_OFFICER),
        )
        assert directive["status"] == "ACTIVE"

        query = hie.submit_query(
            querier["id"],
            purpose_of_use="TREATMENT",
            family_name="Vasquez",
            given_name="Nadia",
            birth_date="1984-03-27",
            sex="F",
            ssn_last4="4451",
            headers=make_clinician_headers(self.CLINICIAN),
        )
        assert query["cluster_id"] == cluster_id
        assert query["top_candidate_score"] == pytest.approx(1.0000, abs=0.0001)
        assert query["consent_decision"] == "PARTIAL_SEGMENTED"
        assert query["disclosed_record_count"] == 1
        assert query["withheld_record_count"] == 1
        assert query["withheld_categories"] == ["BEHAVIORAL_HEALTH"]
        assert query["governing_policy_id"] == policy["id"]
        assert query["governing_directive_id"] is None
        assert query["clinician_user_id"] == self.CLINICIAN

        read_back = validate_success(
            hie.client.get_record_locator_query(hie.privacy_officer, query["id"]), 200
        )
        assert read_back["consent_decision"] == "PARTIAL_SEGMENTED"
        assert read_back["disclosed_record_count"] == 1
        assert read_back["purpose_of_use"] == "TREATMENT"

        entries, meta = validate_paginated(
            hie.client.list_access_audit_entries(
                hie.privacy_officer, query_id=query["id"], limit=100
            )
        )
        assert meta["total_count"] == 2
        assert entries[0]["record_id"] == open_record["id"]
        assert entries[0]["action"] == "DISCLOSED"
        assert entries[0]["disclosing_participant_id"] == querier["id"]
        assert entries[0]["suppression_reason"] is None
        assert entries[1]["record_id"] == segmented_record["id"]
        assert entries[1]["action"] == "WITHHELD"
        assert entries[1]["disclosing_participant_id"] == contributor["id"]
        assert entries[1]["suppression_reason"] == "SENSITIVE_CATEGORY"
        assert entries[1]["sensitive_category_hit"] == ["BEHAVIORAL_HEALTH"]
        assert entries[1]["reviewed"] is False


class TestInvoiceSettlementIsExact:
    """Payment is a conditional action: only the exact remaining balance settles."""

    DELINQUENCY_REASON = "Premature delinquency declaration"

    def test_a_cent_either_side_is_refused_and_only_the_exact_figure_settles(
        self, hie: HieHarness
    ):
        """One cent short and one cent over both bounce, and PAID refuses a second tender.

        PRD 3.9: "The tendered figure must equal the invoice's `total_cents` minus
        its currently stored `amount_paid_cents` — which is `total_cents` itself
        for an invoice nothing has been tendered against — so both partial payment
        and overpayment are refused with `ERR_PAYMENT_AMOUNT_MISMATCH`."

        PRD 3.9: "Declaring an invoice delinquent drives `ISSUED → DELINQUENT` and
        requires the logical clock to be strictly past `due_date`; an attempt at or
        before `due_date` fails the transition precondition with
        `ERR_INVALID_STATE_TRANSITION`."

        PRD 2.9: "The terminal sets are: `Participant` in `WITHDRAWN` or
        `TERMINATED`; `ConformanceTest` in `PASSED` or `WAIVED`; `ConsentPolicy` in
        `SUPERSEDED`; `MatchThresholdConfig` in `RETIRED`; `MatchLink` in
        `REJECTED`; `ConsentDirective` in `SUPERSEDED` or `REVOKED`; `DataFeed` in
        `RETIRED`; `NotificationSubscription` in `TERMINATED`;
        `ParticipationInvoice` in `PAID`, `WRITTEN_OFF` or `VOID`; and for a
        `BreakGlassAccess`, a `session_status` of `CLOSED` or `EXPIRED` blocks
        closure while a `review_status` of `JUSTIFIED` or `UNJUSTIFIED` blocks both
        review actions."

        Design: Corner/Endpoints/invoice_payment_settles_only_on_the_exact_remaining_balance
        """
        participant = _testing_participant(
            hie,
            "Northgate Valley Hospital",
            "hie@northgate.example",
            declared_annual_patient_volume=120000,
        )
        hie.set_clock("2026-09-01T00:00:00Z")
        invoice = hie.issue_invoice(
            participant["id"],
            billing_period_start="2026-08-01T00:00:00Z",
            billing_period_end="2026-09-01T00:00:00Z",
            basis_variant="PROVISIONAL",
            due_date="2026-09-15T00:00:00Z",
        )
        assert invoice["total_cents"] == 267500
        assert invoice["amount_paid_cents"] == 0

        payer = make_participant_admin_headers(participant["id"])
        validate_error(
            hie.client.pay_participation_invoice(payer, invoice["id"], 267499),
            "ERR_PAYMENT_AMOUNT_MISMATCH",
            422,
        )
        validate_error(
            hie.client.pay_participation_invoice(payer, invoice["id"], 267501),
            "ERR_PAYMENT_AMOUNT_MISMATCH",
            422,
        )
        validate_error(
            hie.client.administer_participation_invoice(
                hie.admin,
                invoice["id"],
                action="DECLARE_DELINQUENT",
                reason=self.DELINQUENCY_REASON,
            ),
            "ERR_INVALID_STATE_TRANSITION",
            409,
        )

        untouched = hie.get_invoice(invoice["id"])
        assert untouched["status"] == "ISSUED"
        assert untouched["amount_paid_cents"] == 0

        settled = validate_success(
            hie.client.pay_participation_invoice(payer, invoice["id"], 267500), 200
        )
        assert settled["status"] == "PAID"
        assert settled["amount_paid_cents"] == 267500
        assert hie.get_participant(participant["id"])["outstanding_balance_cents"] == 0

        validate_error(
            hie.client.pay_participation_invoice(payer, invoice["id"], 267500),
            "ERR_TERMINAL_STATE",
            409,
        )
