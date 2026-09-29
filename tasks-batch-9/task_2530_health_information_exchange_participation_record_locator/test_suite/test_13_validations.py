"""Where a rule fires, where it deliberately does not, and which rule wins.

Each test here drives one validation to both sides of its own boundary, or sets
two rules against each other on a single request so the precedence ordering is
observable rather than incidental.
"""

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers.factories import threshold_config_payload
from test_helpers.fixtures import HieHarness
from test_helpers.test_users import (
    make_clinician_headers,
    make_headers_without_role,
    make_privacy_officer_headers,
)


def _testing_participant(hie: HieHarness, legal_name: str, email: str, **overrides):
    overrides.setdefault("org_type", "HOSPITAL")
    overrides.setdefault("declared_annual_patient_volume", 60000)
    return hie.participant_in_conformance_testing(
        legal_name=legal_name, primary_contact_email=email, **overrides
    )


class TestQualitySampleCoherence:
    """The three internal-consistency legs, and the ceiling they stop short of."""

    def test_each_leg_of_the_sample_coherence_rule_fires_on_its_own(self, hie: HieHarness):
        """Impossible counts and an overlapping window are all refused the same way.

        PRD 3.9: "Three further checks reject a sample with
        `ERR_QUALITY_SAMPLE_INVALID`: `messages_rejected` plus
        `required_fields_missing_count` exceeding `messages_received`;
        `duplicate_count` exceeding `messages_received`; and a window overlapping
        any existing sample on the same feed."

        PRD 2.9: "An internally inconsistent or overlapping quality sample —
        `ERR_QUALITY_SAMPLE_INVALID`, on `POST /hie/data-feeds/{id}/quality-samples`."

        Design: Corner/Validations/quality_sample_with_impossible_counts_or_an_overlapping_window_is_rejected
        """
        participant = _testing_participant(
            hie, "Brackenmoor Hospital", "hie@brackenmoor.example"
        )
        feed = hie.provision_feed(participant["id"], feed_type="ADT")
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

        validate_error(
            hie.client.record_quality_sample(
                hie.admin,
                feed["id"],
                period_start="2026-07-01T00:00:00Z",
                period_end="2026-08-01T00:00:00Z",
                messages_received=1000,
                messages_rejected=600,
                required_fields_missing_count=401,
                duplicate_count=0,
                timeliness_p95_seconds=200,
            ),
            "ERR_QUALITY_SAMPLE_INVALID",
            422,
        )
        validate_error(
            hie.client.record_quality_sample(
                hie.admin,
                feed["id"],
                period_start="2026-07-01T00:00:00Z",
                period_end="2026-08-01T00:00:00Z",
                messages_received=1000,
                messages_rejected=0,
                required_fields_missing_count=0,
                duplicate_count=1001,
                timeliness_p95_seconds=200,
            ),
            "ERR_QUALITY_SAMPLE_INVALID",
            422,
        )
        validate_error(
            hie.client.record_quality_sample(
                hie.admin,
                feed["id"],
                period_start="2026-06-15T00:00:00Z",
                period_end="2026-07-15T00:00:00Z",
                messages_received=1000,
                messages_rejected=0,
                required_fields_missing_count=0,
                duplicate_count=0,
                timeliness_p95_seconds=200,
            ),
            "ERR_QUALITY_SAMPLE_INVALID",
            422,
        )

        after = hie.get_data_feed(feed["id"])
        assert after["sample_count"] == 1
        assert after["status"] == "MONITORED"

    def test_counts_touching_the_ceiling_are_accepted_and_score_the_lowest_grade(
        self, hie: HieHarness
    ):
        """Equality is not excess: 400 + 600 == 1000 and 1000 duplicates both pass.

        PRD 3.9: "Three further checks reject a sample with
        `ERR_QUALITY_SAMPLE_INVALID`: `messages_rejected` plus
        `required_fields_missing_count` exceeding `messages_received`;
        `duplicate_count` exceeding `messages_received`; and a window overlapping
        any existing sample on the same feed."

        PRD 3.9: "Second read `penalty_points` from the provisional grade alone —
        zero points for `A`, one for `B`, three for `C`, six for `D`."

        Design: Corner/Validations/quality_sample_counts_touching_the_ceiling_are_accepted_and_score_49_00
        """
        participant = _testing_participant(hie, "Crowmere District Hospital", "hie@crowmere.example")
        feed = hie.provision_feed(participant["id"], feed_type="ADT")

        sample = hie.record_sample(
            feed["id"],
            period_start="2026-06-01T00:00:00Z",
            period_end="2026-07-01T00:00:00Z",
            messages_received=1000,
            messages_rejected=400,
            required_fields_missing_count=600,
            duplicate_count=1000,
            timeliness_p95_seconds=300,
        )
        assert sample["reject_rate"] == pytest.approx(0.4000, abs=0.0001)

        degraded = hie.get_data_feed(feed["id"])
        assert degraded["status"] == "DEGRADED"
        assert degraded["status_reason"] == "REJECT_RATE_BREACH"
        assert degraded["sample_count"] == 1

        scorecard = hie.get_scorecard(participant["id"])
        assert scorecard["completeness_component"] == pytest.approx(40.00, abs=0.01)
        assert scorecard["duplicate_component"] == pytest.approx(0.00, abs=0.01)
        assert scorecard["timeliness_component"] == pytest.approx(100, abs=0.01)
        assert scorecard["base_quality_score"] == pytest.approx(55.00, abs=0.001)
        assert scorecard["provisional_grade"] == "D"
        assert scorecard["penalty_points"] == 6
        assert scorecard["quality_score"] == pytest.approx(49.00, abs=0.001)
        assert scorecard["grade"] == "D"


class TestPrecedenceOverTheReferentialLookup:
    """Authentication and schema both outrank the path-id resolution."""

    def test_authentication_then_schema_then_the_missing_participant(self, hie: HieHarness):
        """The same unknown id yields three different codes depending on what else is wrong.

        PRD 2.9: "When a single request violates more than one rule, the response
        reports the violation with the lowest precedence number in the ordering
        below. The ordering is total and observable: a test that trips both a schema
        fault and a business fault must see the schema fault."

        PRD 2.9: "`X-User-Role` absent or empty, on any endpoint —
        `ERR_UNAUTHENTICATED`."

        PRD 2.9: "Schema faults on any write endpoint — `ERR_INVALID_REQUEST`. This
        covers a missing required field, a wrong JSON type, an enum value outside
        its declared domain, a numeric field outside its declared range (weights
        outside zero through one; thresholds outside zero through one; negative
        counts; an `ssn_last4` that is not exactly four digits; a `phone_digits`
        value that is not ten digits; a timestamp that is not ISO 8601 UTC), and any
        interval whose start is not strictly before its end (`period_start` at or
        after `period_end`, or `effective_from` at or after `effective_until`)."

        PRD 2.9: "A path identifier that resolves to nothing, on any endpoint
        carrying a path id — the family-specific not-found code from §2.7."

        Design: Corner/Validations/unauthenticated_and_schema_checks_outrank_the_referential_lookup
        """
        validate_error(
            hie.client.get_participant(make_headers_without_role(), NON_EXISTENT_UUID),
            "ERR_UNAUTHENTICATED",
            401,
        )
        validate_error(
            hie.client.schedule_conformance_test(
                hie.admin,
                NON_EXISTENT_UUID,
                scheduled_start="2026-08-01T00:00:00Z",
                scheduled_end="2026-08-01T06:00:00Z",
            ),
            "ERR_INVALID_REQUEST",
            400,
        )
        validate_error(
            hie.client.get_participant(hie.admin, NON_EXISTENT_UUID),
            "ERR_PARTICIPANT_NOT_FOUND",
            404,
        )


class TestSubscriptionCoherencePrecedence:
    """The conduit organization check is read before the scope-shape check."""

    def test_the_conduit_organization_error_outranks_the_scope_mismatch(self, hie: HieHarness):
        """One request violates both rules; the lower precedence number is reported.

        PRD 3.9: "A `subscription_scope` of `CLUSTER` requires a non-null
        `cluster_id` and any other scope requires it to be null, with either
        violation refused as `ERR_SUBSCRIPTION_SCOPE_MISMATCH`."

        PRD 3.9: "And a `subscription_scope` of `PUBLIC_HEALTH_CONDUIT` requires the
        owning participant's `org_type` to be `PUBLIC_HEALTH`, refused otherwise
        with `ERR_CONDUIT_ORG_TYPE_INVALID`."

        PRD 2.9: "A public-health conduit subscription for a non-public-health
        organization — `ERR_CONDUIT_ORG_TYPE_INVALID`, on `POST
        /hie/participants/{id}/notification-subscriptions`."

        PRD 2.9: "`subscription_scope` and `cluster_id` disagree —
        `ERR_SUBSCRIPTION_SCOPE_MISMATCH`, on `POST
        /hie/participants/{id}/notification-subscriptions`."

        Design: Corner/Validations/conduit_org_type_error_outranks_the_subscription_scope_mismatch
        """
        hie.activate_threshold_config(
            config_label="REF-PROB-V4",
            headers=make_privacy_officer_headers("privacy-tuner-1"),
        )
        clinic = _testing_participant(
            hie,
            "Dunhollow Family Clinic",
            "hie@dunhollow.example",
            org_type="CLINIC",
            declared_annual_patient_volume=18000,
        )
        record = hie.contribute_record(
            clinic["id"],
            headers=hie.admin,
            source_mrn="V4-0001",
            given_name="Ferran",
            family_name="Okonkwo",
            birth_date="1968-02-14",
            sex="M",
            ssn_last4="3320",
            postal_code="12208",
            phone_digits="5185550142",
        )
        public_health = _testing_participant(
            hie,
            "State Bureau of Communicable Disease",
            "hie@statebureau.example",
            org_type="PUBLIC_HEALTH",
            declared_annual_patient_volume=12000,
        )

        validate_error(
            hie.client.create_notification_subscription(
                hie.admin,
                clinic["id"],
                subscription_scope="PUBLIC_HEALTH_CONDUIT",
                event_types=["ADMISSION", "DISCHARGE"],
                delivery_endpoint_url="https://dunhollow.example/adt",
                cluster_id=record["cluster_id"],
            ),
            "ERR_CONDUIT_ORG_TYPE_INVALID",
            422,
        )
        validate_error(
            hie.client.create_notification_subscription(
                hie.admin,
                public_health["id"],
                subscription_scope="PUBLIC_HEALTH_CONDUIT",
                event_types=["ADMISSION", "DISCHARGE"],
                delivery_endpoint_url="https://statebureau.example/adt",
                cluster_id=record["cluster_id"],
            ),
            "ERR_SUBSCRIPTION_SCOPE_MISMATCH",
            422,
        )
        validate_error(
            hie.client.create_notification_subscription(
                hie.admin,
                public_health["id"],
                subscription_scope="CLUSTER",
                event_types=["ADMISSION"],
                delivery_endpoint_url="https://statebureau.example/adt",
            ),
            "ERR_SUBSCRIPTION_SCOPE_MISMATCH",
            422,
        )

        accepted = get_success_data(
            hie.client.create_notification_subscription(
                hie.admin,
                public_health["id"],
                subscription_scope="PUBLIC_HEALTH_CONDUIT",
                event_types=["ADMISSION", "DISCHARGE"],
                delivery_endpoint_url="https://statebureau.example/adt",
            )
        )
        assert accepted["status"] == "PENDING_ACTIVATION"
        assert accepted["cluster_id"] is None
        assert accepted["subscriber_participant_id"] == public_health["id"]
        assert hie.get_participant(public_health["id"])["active_subscription_count"] == 0


class TestDirectiveAttachesOnlyToALiveCluster:
    """The addressed cluster's own status decides whether a directive may be recorded."""

    POLICY_OFFICER = "privacy-policy-1"
    TUNER = "privacy-tuner-1"

    def test_the_merged_away_cluster_refuses_the_directive_the_survivor_accepts(
        self, hie: HieHarness
    ):
        """Identical payloads, correct versions on both, and only the survivor succeeds.

        PRD 3.6: "The addressed cluster must be `ACTIVE`; a cluster that has been
        absorbed by a merge rejects the recording with `ERR_CLUSTER_MERGED_AWAY`."

        PRD 2.9: "The addressed identity cluster is `MERGED_AWAY` —
        `ERR_CLUSTER_MERGED_AWAY`, on `POST
        /hie/identity-clusters/{id}/consent-directives`, `POST
        /hie/break-glass-accesses` and `POST
        /hie/participants/{id}/notification-subscriptions`."

        PRD 3.6: "The stored directive is born with `status` `ACTIVE`, `cluster_id`
        taken from the path, `recorded_by_user_id` set from the acting `X-User-ID`,
        and `policy_id` pinned to the `id` of the consent policy generation that was
        `ACTIVE` and governing the clock at recording time."

        Design: Corner/Validations/directives_attach_to_the_surviving_cluster_but_not_to_the_merged_away_one
        """
        policy_officer = make_privacy_officer_headers(self.POLICY_OFFICER)
        policy = hie.activate_consent_policy(
            policy_version="V5-POLICY-1",
            model="OPT_OUT",
            sensitive_categories_segmented=["BEHAVIORAL_HEALTH"],
            default_share_for_treatment=True,
            effective_from="2026-01-01T00:00:00Z",
            headers=policy_officer,
        )
        hie.activate_threshold_config(
            config_label="REF-DET-V5",
            score_variant_mode="DETERMINISTIC_FIRST",
            headers=make_privacy_officer_headers(self.TUNER),
        )
        first = _testing_participant(
            hie,
            "Eastgate Memorial Hospital",
            "hie@eastgate.example",
            declared_annual_patient_volume=96000,
        )
        second = _testing_participant(
            hie,
            "Fallowbrook Urgent Care",
            "hie@fallowbrook.example",
            org_type="CLINIC",
            declared_annual_patient_volume=24000,
        )

        left_record = hie.contribute_record(
            first["id"],
            headers=hie.admin,
            source_mrn="V5-A1",
            given_name="Gwendolyn",
            family_name="Ashworth",
            birth_date="1981-11-22",
            sex="F",
            ssn_last4="5074",
            postal_code="44113",
            phone_digits="2165550188",
        )
        winner_id = left_record["cluster_id"]
        right_record = hie.contribute_record(
            second["id"],
            headers=hie.admin,
            source_mrn="V5-B1",
            given_name="Gwen",
            family_name="Ashworth-Reyes",
            birth_date="1981-11-22",
            sex="F",
            ssn_last4="5074",
            postal_code="60614",
            phone_digits="3125550133",
        )
        assert right_record["cluster_id"] == winner_id
        loser_id = right_record["prior_cluster_id"]
        assert loser_id is not None and loser_id != winner_id

        absorbed = validate_success(
            hie.client.list_identity_clusters(hie.privacy_officer, merged_into_cluster_id=winner_id),
            200,
        )
        assert [row["id"] for row in absorbed] == [loser_id]
        assert absorbed[0]["status"] == "MERGED_AWAY"
        assert absorbed[0]["member_record_count"] == 0

        survivor = hie.get_cluster(winner_id)
        assert survivor["status"] == "ACTIVE"
        assert survivor["member_record_count"] == 2
        assert survivor["participant_count"] == 2

        validate_error(
            hie.client.record_consent_directive(
                policy_officer,
                loser_id,
                directive_type="OPT_OUT",
                scope="ALL_PARTICIPANTS",
                expected_cluster_version=absorbed[0]["version"],
            ),
            "ERR_CLUSTER_MERGED_AWAY",
            409,
        )

        directive = get_success_data(
            hie.client.record_consent_directive(
                policy_officer,
                winner_id,
                directive_type="OPT_OUT",
                scope="ALL_PARTICIPANTS",
                expected_cluster_version=survivor["version"],
            )
        )
        assert directive["status"] == "ACTIVE"
        assert directive["cluster_id"] == winner_id
        assert directive["policy_id"] == policy["id"]
        assert directive["recorded_by_user_id"] == self.POLICY_OFFICER
        assert hie.get_cluster(winner_id)["active_directive_count"] == 1


class TestInvoicePeriodWindowing:
    """A period must have elapsed, and must not overlap anything still standing."""

    VOID_REASON = "Issued against the wrong basis variant; reissuing."

    def test_the_same_period_is_refused_then_billed_then_blocked_then_billed_again(
        self, hie: HieHarness
    ):
        """Only the clock and the incumbent's status change; the payload never does.

        PRD 3.9: "`billing_period_end` must be strictly after
        `billing_period_start`, and it must be at or before the logical clock — a
        period that has not fully elapsed is refused with
        `ERR_INVOICE_PERIOD_NOT_ELAPSED`."

        PRD 3.9: "The submitted half-open period must not overlap the period of any
        existing invoice for the same participant whose `status` is `ISSUED`,
        `PAID`, `DELINQUENT` or `WRITTEN_OFF`; `VOID` invoices are excluded from
        that test, so voiding an invoice frees its window for re-issue."

        Design: Corner/Validations/invoice_periods_must_be_elapsed_and_non_overlapping_unless_the_incumbent_is_void
        """
        participant = _testing_participant(
            hie,
            "Glassford Regional Hospital",
            "hie@glassford.example",
            declared_annual_patient_volume=120000,
        )
        assert participant["provisional_monthly_fee_cents"] == 267500
        assert hie.get_participant(participant["id"])["outstanding_balance_cents"] == 0

        def issue(start: str, end: str):
            return hie.client.issue_participation_invoice(
                hie.admin,
                participant["id"],
                billing_period_start=start,
                billing_period_end=end,
                basis_variant="PROVISIONAL",
                due_date="2026-09-15T00:00:00Z",
            )

        validate_error(
            issue("2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z"),
            "ERR_INVOICE_PERIOD_NOT_ELAPSED",
            422,
        )

        assert hie.set_clock("2026-09-01T00:00:00Z").startswith("2026-09-01T00:00:00")

        first = get_success_data(issue("2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z"))
        assert first["volume_fee_cents"] == 17500
        assert first["total_cents"] == 267500
        assert first["status"] == "ISSUED"
        assert hie.get_participant(participant["id"])["outstanding_balance_cents"] == 267500

        validate_error(
            issue("2026-08-15T00:00:00Z", "2026-09-01T00:00:00Z"),
            "ERR_INVOICE_PERIOD_OVERLAP",
            409,
        )

        voided = validate_success(
            hie.client.administer_participation_invoice(
                hie.admin, first["id"], action="VOID", reason=self.VOID_REASON
            ),
            200,
        )
        assert voided["status"] == "VOID"
        assert hie.get_participant(participant["id"])["outstanding_balance_cents"] == 0

        again = get_success_data(issue("2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z"))
        assert again["id"] != first["id"]
        assert again["total_cents"] == 267500
        assert again["status"] == "ISSUED"
        assert hie.get_participant(participant["id"])["outstanding_balance_cents"] == 267500


class TestThresholdGenerationAdmissibility:
    """Three aggregate rules that no per-field range check could catch."""

    TUNER = "privacy-tuner-1"

    def test_the_weight_sum_tolerance_and_the_bound_ordering_are_enforced_together(
        self, hie: HieHarness
    ):
        """A sum of 1.0002 is refused, 1.0001 is admitted, and equal bounds are refused.

        PRD 3.3: "Three admissibility rules are checked at draft time, and any
        violation yields `ERR_THRESHOLD_CONFIG_INVALID`: the six weights must sum to
        1.0000, tolerating an absolute difference of at most 0.0001;
        `auto_link_threshold` must be strictly greater than `review_lower_bound`;
        and `partial_credit_factor` must lie strictly inside the open interval
        between zero and one, so neither exactly zero nor exactly one is admissible
        at this gate."

        PRD 3.3: "Drafting sets `status` to `DRAFT`, `scored_link_count` to 0, and
        `tuned_by_user_id` to the acting `X-User-ID`."

        Design: Corner/Validations/threshold_config_weights_and_bounds_are_validated_as_an_aggregate
        """
        tuner = make_privacy_officer_headers(self.TUNER)

        validate_error(
            hie.client.draft_match_threshold_config(
                tuner,
                **threshold_config_payload(
                    config_label="V7-SUM-1_0002", weight_phone_digits=0.0702
                ),
            ),
            "ERR_THRESHOLD_CONFIG_INVALID",
            422,
        )
        validate_error(
            hie.client.draft_match_threshold_config(
                tuner,
                **threshold_config_payload(
                    config_label="V7-BOUNDS-EQUAL",
                    auto_link_threshold=0.7500,
                    review_lower_bound=0.7500,
                ),
            ),
            "ERR_THRESHOLD_CONFIG_INVALID",
            422,
        )
        validate_error(
            hie.client.draft_match_threshold_config(
                tuner,
                **threshold_config_payload(
                    config_label="V7-PARTIAL-1_0", partial_credit_factor=1.0
                ),
            ),
            "ERR_THRESHOLD_CONFIG_INVALID",
            422,
        )

        admitted = get_success_data(
            hie.client.draft_match_threshold_config(
                tuner,
                **threshold_config_payload(
                    config_label="V7-SUM-1_0001", weight_phone_digits=0.0701
                ),
            )
        )
        assert admitted["status"] == "DRAFT"
        assert admitted["tuned_by_user_id"] == self.TUNER
        assert admitted["scored_link_count"] == 0


class TestReviewNoteLengthIsConditional:
    """The forty-character minimum binds an unjustified note and nothing else."""

    TUNER = "privacy-tuner-1"
    FIRST_REVIEWER = "privacy-reviewer-1"
    SECOND_REVIEWER = "privacy-reviewer-2"
    FIRST_JUSTIFICATION = (
        "Massive gastrointestinal bleed in progress; anticoagulant history "
        "required before transfusion."
    )
    SECOND_JUSTIFICATION = (
        "Mass casualty bus collision triage; identity and allergy reconciliation "
        "for four arrivals."
    )

    def test_a_short_note_passes_a_justified_decision_and_fails_an_unjustified_one(
        self, hie: HieHarness
    ):
        """Thirteen characters suffice to justify; twenty-one do not to condemn.

        PRD 3.8: "When the `outcome` is `UNJUSTIFIED` the `review_note` is
        additionally held to the same forty-character minimum as the original
        justification, and a shorter note is refused with
        `ERR_JUSTIFICATION_TOO_SHORT`."

        PRD 3.8: "A `JUSTIFIED` finding sets `sanction_points_awarded` to 0; the
        invoking participant's `sanction_points_active` is recomputed and comes out
        unchanged."

        PRD 3.8: "supplying a `justification_text` that must be at least forty
        characters after trimming — a shorter justification is refused with
        `ERR_JUSTIFICATION_TOO_SHORT`."

        Design: Corner/Validations/review_note_length_is_enforced_only_for_an_unjustified_outcome
        """
        hie.activate_threshold_config(
            config_label="REF-PROB-V8", headers=make_privacy_officer_headers(self.TUNER)
        )
        participant = hie.certified_participant(
            legal_name="Havenwood Regional Hospital",
            org_type="HOSPITAL",
            declared_annual_patient_volume=84000,
            primary_contact_email="hie@havenwood.example",
        )
        record = hie.contribute_record(
            participant["id"],
            headers=hie.admin,
            source_mrn="V8-0001",
            given_name="Isadora",
            family_name="Petrakis",
            birth_date="1972-04-18",
            sex="F",
            ssn_last4="9042",
            postal_code="02139",
            phone_digits="6175550171",
        )
        cluster_id = record["cluster_id"]

        first_session = hie.open_break_glass(
            cluster_id,
            participant["id"],
            emergency_category="LIFE_THREATENING",
            justification_text=self.FIRST_JUSTIFICATION,
            clinician_user_id="clin-v8-1",
        )
        second_session = hie.open_break_glass(
            cluster_id,
            participant["id"],
            emergency_category="DISASTER",
            justification_text=self.SECOND_JUSTIFICATION,
            clinician_user_id="clin-v8-2",
        )

        first_reviewer = make_privacy_officer_headers(self.FIRST_REVIEWER)
        second_reviewer = make_privacy_officer_headers(self.SECOND_REVIEWER)
        validate_success(
            hie.client.claim_break_glass_review(first_reviewer, first_session["id"]), 200
        )
        validate_success(
            hie.client.claim_break_glass_review(second_reviewer, second_session["id"]), 200
        )

        justified = validate_success(
            hie.client.decide_break_glass_review(
                first_reviewer,
                first_session["id"],
                outcome="JUSTIFIED",
                review_note="Verified need",
            ),
            200,
        )
        assert justified["review_status"] == "JUSTIFIED"
        assert justified["sanction_points_awarded"] == 0
        assert justified["review_claimed_by_user_id"] == self.FIRST_REVIEWER

        validate_error(
            hie.client.decide_break_glass_review(
                second_reviewer,
                second_session["id"],
                outcome="UNJUSTIFIED",
                review_note="Override was needless",
            ),
            "ERR_JUSTIFICATION_TOO_SHORT",
            422,
        )
        assert hie.get_break_glass(second_session["id"])["review_status"] == "UNDER_REVIEW"

        validate_error(
            hie.client.open_break_glass_access(
                make_clinician_headers("clin-v8-3"),
                cluster_id=cluster_id,
                invoking_participant_id=participant["id"],
                emergency_category="UNCONSCIOUS_PATIENT",
                justification_text="Patient unresponsive",
            ),
            "ERR_JUSTIFICATION_TOO_SHORT",
            422,
        )

        owner = hie.get_participant(participant["id"])
        assert owner["sanction_points_active"] == 0
        assert owner["onboarding_status"] == "CERTIFIED"


class TestReconciledIssuanceNeedsItsOwnBasis:
    """The qualifying sample set is derived first, and then billed."""

    def test_an_empty_sample_set_refuses_the_issuance_the_first_sample_unlocks(
        self, hie: HieHarness
    ):
        """The identical request fails, then bills 8,000 units at the grade-A multiplier.

        PRD 3.9: "When the qualifying sample set for a `RECONCILED` issuance is
        empty the issuance is refused with `ERR_NO_RECONCILIATION_BASIS`."

        PRD 3.9: "Under the `RECONCILED` variant the billable volume is the sum of
        `messages_received` over every quality sample whose window is fully
        contained in the billing period — that is, whose `period_start` is at or
        after `billing_period_start` and whose `period_end` is at or before
        `billing_period_end` — and whose owning feed's `status` at issuance is
        `MONITORED` or `DEGRADED`, with `PROVISIONING`, `SUSPENDED` and `RETIRED`
        feeds excluded."

        PRD 3.9: "The `RECONCILED` multiplier is read from the participant's
        `quality_grade` at issuance, captured on the invoice as
        `quality_grade_snapshot`: grade `A` multiplies by 0.95, `B` by 1.00, `C` by
        1.08, `D` by 1.20, and `UNGRADED` by 1.00."

        Design: Corner/Validations/reconciled_issuance_requires_the_sample_set_its_own_calculation_consumes
        """
        participant = _testing_participant(
            hie,
            "Ironvale Community Hospital",
            "hie@ironvale.example",
            declared_annual_patient_volume=120000,
        )
        feed = hie.provision_feed(participant["id"], feed_type="ADT")
        assert hie.set_clock("2026-09-01T00:00:00Z").startswith("2026-09-01T00:00:00")

        def issue():
            return hie.client.issue_participation_invoice(
                hie.admin,
                participant["id"],
                billing_period_start="2026-08-01T00:00:00Z",
                billing_period_end="2026-09-01T00:00:00Z",
                basis_variant="RECONCILED",
                due_date="2026-09-15T00:00:00Z",
            )

        validate_error(issue(), "ERR_NO_RECONCILIATION_BASIS", 409)

        hie.record_sample(
            feed["id"],
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-09-01T00:00:00Z",
            messages_received=8000,
            messages_rejected=100,
            required_fields_missing_count=200,
            duplicate_count=50,
            timeliness_p95_seconds=250,
        )
        scorecard = hie.get_scorecard(participant["id"])
        assert scorecard["quality_score"] == pytest.approx(98.78, abs=0.001)
        assert scorecard["grade"] == "A"

        invoice = get_success_data(issue())
        assert invoice["basis_variant"] == "RECONCILED"
        assert invoice["billable_volume_units"] == 8000
        assert invoice["volume_fee_cents"] == 14000
        assert invoice["quality_grade_snapshot"] == "A"
        assert invoice["quality_multiplier"] == pytest.approx(0.95, abs=0.01)
        assert invoice["total_cents"] == 250800
        assert invoice["status"] == "ISSUED"
