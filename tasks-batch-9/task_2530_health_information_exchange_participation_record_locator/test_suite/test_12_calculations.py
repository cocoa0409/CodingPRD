"""Every published number, re-derived from the specification that defines it.

Conformance outcomes, the participation fee ladder, the scorecard blend, the
non-linear match-score adjustments and the sanction decay window are each pinned
here on inputs chosen so that a wrong rounding order, a wrong band edge or a
wrong input set is visible in the response body.
"""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from test_helpers.factories import conformance_test_payload
from test_helpers.fixtures import HieHarness
from test_helpers.test_users import make_privacy_officer_headers


class TestConformanceOutcomeArithmetic:
    """The pass rate and the critical-failure flag decide the branch together."""

    @staticmethod
    def _testing_participant(hie: HieHarness, legal_name: str, email: str):
        return hie.participant_in_conformance_testing(
            legal_name=legal_name,
            org_type="HOSPITAL",
            declared_annual_patient_volume=60000,
            primary_contact_email=email,
        )

    @staticmethod
    def _booked_run(hie: HieHarness, participant_id: str, profile: str):
        return get_success_data(
            hie.client.schedule_conformance_test(
                hie.admin,
                participant_id,
                **conformance_test_payload(
                    profile=profile,
                    scheduled_start="2026-08-01T00:00:00Z",
                    scheduled_end="2026-08-01T06:00:00Z",
                ),
            )
        )

    def test_the_pass_rate_floor_is_inclusive_and_one_assertion_below_it_fails(
        self, hie: HieHarness
    ):
        """190 of 200 passes at exactly 0.9500 while 189 of 200 fails at 0.9450.

        PRD 3.2: "`pass_rate` is `assertions_passed` divided by `assertions_total`,
        rounded half up to four decimal places."

        PRD 3.2: "The floor is inclusive, which is observable at the boundary: 190
        assertions passed out of 200 yields exactly 0.9500 and passes, while 189
        out of 200 yields 0.9450 and fails."

        Design: Corner/Calculations/conformance_pass_rate_at_the_floor_passes_and_one_assertion_below_fails
        """
        participant = self._testing_participant(
            hie, "Thornapple Valley Hospital", "hie@thornapple.example"
        )
        at_the_floor = self._booked_run(hie, participant["id"], "ADT_PUBLISHER")
        one_below = self._booked_run(hie, participant["id"], "DOCUMENT_SOURCE")

        passing = validate_success(
            hie.client.submit_conformance_result(
                hie.admin, at_the_floor["id"], assertions_total=200, assertions_passed=190
            ),
            200,
        )
        assert passing["pass_rate"] == pytest.approx(0.9500, abs=0.0001)
        assert passing["status"] == "PASSED"
        assert passing["critical_failure"] is False

        failing = validate_success(
            hie.client.submit_conformance_result(
                hie.admin, one_below["id"], assertions_total=200, assertions_passed=189
            ),
            200,
        )
        assert failing["pass_rate"] == pytest.approx(0.9450, abs=0.0001)
        assert failing["status"] == "FAILED"
        assert failing["critical_failure"] is False

        owner = hie.get_participant(participant["id"])
        assert owner["passed_profiles"] == ["ADT_PUBLISHER"]
        assert owner["consecutive_failed_attempts"] == 1

    def test_a_critical_category_fails_the_run_while_an_ordinary_one_does_not(
        self, hie: HieHarness
    ):
        """Two runs at 0.9800 diverge purely on whether the tagged category is critical.

        PRD 3.2: "`critical_failure` is true exactly when `failure_categories` has
        at least one member in common with the two categories the exchange treats
        as non-negotiable: `SECURITY` and `PATIENT_ID_INTEGRITY`."

        PRD 3.2: "A run tagged with a critical failure category fails even at a
        perfect `pass_rate` of 1.0000."

        Design: Corner/Calculations/conformance_critical_failure_category_fails_despite_a_high_pass_rate
        """
        participant = self._testing_participant(
            hie, "Underhill Medical Center", "hie@underhill.example"
        )
        critical_run = self._booked_run(hie, participant["id"], "ADT_PUBLISHER")
        ordinary_run = self._booked_run(hie, participant["id"], "DOCUMENT_SOURCE")

        critical = validate_success(
            hie.client.submit_conformance_result(
                hie.admin,
                critical_run["id"],
                assertions_total=200,
                assertions_passed=196,
                failure_categories=["SECURITY"],
            ),
            200,
        )
        assert critical["pass_rate"] == pytest.approx(0.9800, abs=0.0001)
        assert critical["critical_failure"] is True
        assert critical["status"] == "FAILED"

        ordinary = validate_success(
            hie.client.submit_conformance_result(
                hie.admin,
                ordinary_run["id"],
                assertions_total=200,
                assertions_passed=196,
                failure_categories=["VOCABULARY"],
            ),
            200,
        )
        assert ordinary["pass_rate"] == pytest.approx(0.9800, abs=0.0001)
        assert ordinary["critical_failure"] is False
        assert ordinary["status"] == "PASSED"

        owner = hie.get_participant(participant["id"])
        assert owner["passed_profiles"] == ["DOCUMENT_SOURCE"]
        assert owner["consecutive_failed_attempts"] == 0


class TestParticipationFeeLadder:
    """One unit past the first-tier cap is charged at the second-tier rate only."""

    def test_only_the_volume_above_the_first_tier_cap_pays_the_marginal_rate(
        self, hie: HieHarness
    ):
        """Monthly volumes of 24,750 and 24,751 units differ by exactly one cent.

        PRD 3.9: "The tier ladder is fixed: the first 24,750 billable volume units
        fall in tier one, the next 75,000 units (carrying the ladder up to a
        cumulative 99,750 units) fall in tier two, and everything beyond 99,750
        units falls in tier three."

        PRD 3.9: "Each tier's charge is computed as its quantity multiplied by its
        rate and **individually rounded half up to a whole cent**; only then are
        the three rounded charges added to give `volume_fee_cents`."

        PRD 3.9: "The `fee_tier` reached is `TIER_3` when the tier-three quantity
        is greater than zero, otherwise `TIER_2` when the tier-two quantity is
        greater than zero, otherwise `TIER_1`."

        Design: Corner/Calculations/participation_fee_charges_the_marginal_rate_only_above_the_first_tier_cap
        """
        at_the_cap = hie.register_participant(
            legal_name="Vesper Ridge Hospital",
            org_type="HOSPITAL",
            declared_annual_patient_volume=297000,
            primary_contact_email="hie@vesperridge.example",
        )
        assert at_the_cap["provisional_monthly_fee_cents"] == 293313
        assert at_the_cap["fee_tier"] == "TIER_1"

        one_unit_over = hie.register_participant(
            legal_name="Westmarch General Hospital",
            org_type="HOSPITAL",
            declared_annual_patient_volume=297012,
            primary_contact_email="hie@westmarch.example",
        )
        assert one_unit_over["provisional_monthly_fee_cents"] == 293314
        assert one_unit_over["fee_tier"] == "TIER_2"

        assert (
            one_unit_over["provisional_monthly_fee_cents"]
            - at_the_cap["provisional_monthly_fee_cents"]
            == 1
        )


class TestScorecardArithmetic:
    """The four components, the weighted blend and the input set that feeds them."""

    def test_the_blend_rounds_half_up_and_reads_the_upper_timeliness_band_inclusively(
        self, hie: HieHarness
    ):
        """A p95 of exactly 900 seconds scores 85 and the blend of 94.825 becomes 94.83.

        PRD 3.9: "`completeness_component` is one hundred times the quantity one
        minus the sum of `required_fields_missing_count` divided by the greater of
        one and the received total; `rejection_component` is one hundred times the
        quantity one minus the sum of `messages_rejected` divided by the greater of
        one and the received total; and `duplicate_component` is one hundred times
        the quantity one minus the sum of `duplicate_count` divided by the greater
        of one and the received total."

        PRD 3.9: "`timeliness_component` is one hundred when that average is at
        most three hundred seconds, eighty-five when it is at most nine hundred
        seconds, sixty when it is at most one hour, and thirty otherwise."

        PRD 3.9: "`base_quality_score` is the weighted blend of those four
        components — thirty hundredths of `completeness_component`, plus thirty
        hundredths of `rejection_component`, plus fifteen hundredths of
        `duplicate_component`, plus twenty-five hundredths of
        `timeliness_component` — rounded half up to two decimal places."

        Design: Corner/Calculations/quality_score_rounds_half_up_at_the_third_decimal_and_honours_the_900_second_band
        """
        participant = hie.participant_in_conformance_testing(
            legal_name="Yarrowfield Community Hospital",
            org_type="HOSPITAL",
            declared_annual_patient_volume=60000,
            primary_contact_email="hie@yarrowfield.example",
        )
        feed = hie.provision_feed(participant["id"], feed_type="ADT")
        hie.record_sample(
            feed["id"],
            period_start="2026-06-01T00:00:00Z",
            period_end="2026-07-01T00:00:00Z",
            messages_received=8000,
            messages_rejected=100,
            required_fields_missing_count=250,
            duplicate_count=60,
            timeliness_p95_seconds=900,
        )

        scorecard = hie.get_scorecard(participant["id"])
        assert scorecard["samples_counted"] == 1
        assert scorecard["completeness_component"] == pytest.approx(96.875, abs=0.01)
        assert scorecard["rejection_component"] == pytest.approx(98.75, abs=0.01)
        assert scorecard["duplicate_component"] == pytest.approx(99.25, abs=0.01)
        assert scorecard["timeliness_component"] == pytest.approx(85, abs=0.01)
        assert scorecard["average_p95_seconds"] == pytest.approx(900.00, abs=0.01)
        assert scorecard["base_quality_score"] == pytest.approx(94.83, abs=0.001)
        assert scorecard["provisional_grade"] == "A"
        assert scorecard["penalty_points"] == 0
        assert scorecard["quality_score"] == pytest.approx(94.83, abs=0.001)
        assert scorecard["grade"] == "A"

    def test_a_degraded_feed_still_feeds_the_scorecard_but_a_suspended_one_does_not(
        self, hie: HieHarness
    ):
        """Suspending the noisy feed drops its window and lifts the grade from B to A.

        PRD 3.9: "Start with every quality sample whose owning feed belongs to this
        participant and whose owning feed's `status` is `MONITORED` or `DEGRADED`;
        feeds in `PROVISIONING`, `SUSPENDED` or `RETIRED` contribute nothing at
        all."

        PRD 3.9: "A `HieAdmin` may also suspend a feed directly by supplying a
        `reason`, from any of `PROVISIONING`, `MONITORED` or `DEGRADED` into
        `SUSPENDED`, with `status_reason` set to that `reason` and the scorecard
        re-run with this feed's samples now excluded from the input set."

        Design: Corner/Calculations/quality_score_input_set_drops_a_suspended_feed_but_keeps_a_degraded_one
        """
        participant = hie.participant_in_conformance_testing(
            legal_name="Zephyr Hollow Health System",
            org_type="HOSPITAL",
            declared_annual_patient_volume=60000,
            primary_contact_email="hie@zephyrhollow.example",
        )
        adt_feed = hie.provision_feed(participant["id"], feed_type="ADT")
        hie.record_sample(
            adt_feed["id"],
            period_start="2026-06-01T00:00:00Z",
            period_end="2026-07-01T00:00:00Z",
            messages_received=8000,
            messages_rejected=100,
            required_fields_missing_count=200,
            duplicate_count=50,
            timeliness_p95_seconds=250,
        )
        ccda_feed = hie.provision_feed(participant["id"], feed_type="CCDA")
        noisy_sample = hie.record_sample(
            ccda_feed["id"],
            period_start="2026-06-01T00:00:00Z",
            period_end="2026-07-01T00:00:00Z",
            messages_received=4000,
            messages_rejected=600,
            required_fields_missing_count=800,
            duplicate_count=200,
            timeliness_p95_seconds=1500,
        )
        assert noisy_sample["reject_rate"] == pytest.approx(0.1500, abs=0.0001)
        degraded = hie.get_data_feed(ccda_feed["id"])
        assert degraded["status"] == "DEGRADED"
        assert degraded["status_reason"] == "REJECT_RATE_BREACH"

        with_both = hie.get_scorecard(participant["id"])
        assert with_both["samples_counted"] == 2
        assert with_both["average_p95_seconds"] == pytest.approx(875.00, abs=0.01)
        assert with_both["base_quality_score"] == pytest.approx(91.69, abs=0.001)
        assert with_both["provisional_grade"] == "B"
        assert with_both["penalty_points"] == 1
        assert with_both["quality_score"] == pytest.approx(90.69, abs=0.001)
        assert with_both["grade"] == "B"

        suspended = validate_success(
            hie.client.transition_data_feed_status(
                hie.admin,
                ccda_feed["id"],
                action="SUSPEND",
                reason="Vendor interface outage under investigation",
            ),
            200,
        )
        assert suspended["status"] == "SUSPENDED"
        assert suspended["status_reason"] == "Vendor interface outage under investigation"

        with_one = hie.get_scorecard(participant["id"])
        assert with_one["samples_counted"] == 1
        assert with_one["base_quality_score"] == pytest.approx(98.78, abs=0.001)
        assert with_one["penalty_points"] == 0
        assert with_one["quality_score"] == pytest.approx(98.78, abs=0.001)
        assert with_one["grade"] == "A"
        assert hie.get_participant(participant["id"])["quality_grade"] == "A"


class TestMatchScoreNonLinearAdjustments:
    """A birth-date disagreement caps the weighted total before any band is read."""

    TUNER = "privacy-tuner-1"

    def test_a_birth_date_disagreement_caps_the_weighted_total_and_rejects_the_pair(
        self, hie: HieHarness
    ):
        """A raw 0.6500 becomes 0.6000 under the veto and lands below the review band.

        PRD 3.4: "Otherwise, if the field is one of the four fuzzy-eligible fields
        — `family_name`, `given_name`, `postal_code` and `phone_digits` — and the
        first three characters of the two normalized values are equal, agreement is
        the generation's `partial_credit_factor`."

        PRD 3.4: "First the *birth-date veto cap*: when the birth-date agreement is
        zero, the score is replaced by the lesser of itself and 0.6000 — two people
        who do not share a date of birth cannot be auto-linked on names alone."

        PRD 3.4: "When `match_score` is strictly below `review_lower_bound`, the
        link goes `PROPOSED → REJECTED`."

        PRD 3.4: "`PROPOSED → REJECTED` mutates nothing — no cluster change and no
        change to `pending_review_link_count`."

        Design: Corner/Calculations/match_score_birth_date_disagreement_caps_the_score_and_rejects_the_link
        """
        tuner = make_privacy_officer_headers(self.TUNER)
        hie.activate_threshold_config(config_label="REF-PROB-C6", headers=tuner)
        left_participant = hie.participant_in_conformance_testing(
            legal_name="Amberton Hospital",
            org_type="HOSPITAL",
            declared_annual_patient_volume=48000,
            primary_contact_email="hie@amberton.example",
        )
        right_participant = hie.participant_in_conformance_testing(
            legal_name="Bellhaven Family Clinic",
            org_type="CLINIC",
            declared_annual_patient_volume=18000,
            primary_contact_email="hie@bellhaven.example",
        )

        left_record = hie.contribute_record(
            left_participant["id"],
            headers=hie.admin,
            source_mrn="C6-A1",
            given_name="Desmond",
            family_name="Achebe",
            birth_date="1975-05-09",
            sex="M",
            ssn_last4="6613",
            postal_code="30303",
            phone_digits="4045550166",
        )
        right_record = hie.contribute_record(
            right_participant["id"],
            headers=hie.admin,
            source_mrn="C6-B1",
            given_name="Desmond",
            family_name="Acheson",
            birth_date="1975-05-10",
            sex="M",
            ssn_last4="6613",
            postal_code="30303",
            phone_digits="4045550166",
        )

        links, meta = validate_paginated(
            hie.client.list_match_links(
                tuner,
                left_record_id=left_record["id"],
                right_record_id=right_record["id"],
            )
        )
        assert meta["total_count"] == 1
        link = links[0]
        assert link["match_score"] == pytest.approx(0.6000, abs=0.0001)
        assert link["status"] == "REJECTED"
        assert link["score_variant"] == "PROBABILISTIC"

        agreement = link["field_agreement_map"]
        assert agreement["family_name"] == pytest.approx(0.50, abs=0.0001)
        assert agreement["given_name"] == pytest.approx(1, abs=0.0001)
        assert agreement["birth_date"] == pytest.approx(0, abs=0.0001)
        assert agreement["ssn_last4"] == pytest.approx(1, abs=0.0001)

        right_cluster = hie.get_cluster(right_record["cluster_id"])
        assert right_cluster["member_record_count"] == 1
        assert right_cluster["pending_review_link_count"] == 0
        assert right_cluster["status"] == "ACTIVE"


class TestSanctionDecayWindow:
    """The active sanction total is a step function of the logical clock."""

    TUNER = "privacy-tuner-1"
    REVIEWER = "privacy-reviewer-1"
    CLINICIAN = "clin-c7-1"
    JUSTIFICATION = (
        "Unresponsive patient without identification; allergy and medication "
        "history required urgently."
    )
    REVIEW_NOTE = (
        "Encounter notes show the patient was alert and able to consent; the "
        "override was unnecessary."
    )

    def test_an_unjustified_finding_decays_to_zero_exactly_at_the_boundary(
        self, hie: HieHarness
    ):
        """Four points survive to the last second of the window and vanish at 180 days.

        PRD 3.8: "An `UNJUSTIFIED` finding computes `sanction_points_awarded` as
        the category's own weight — six points for `LIFE_THREATENING`, four for
        `UNCONSCIOUS_PATIENT`, three for `DISASTER` — plus a surcharge of two
        additional points when the session's `disclosed_sensitive_count` is greater
        than zero."

        PRD 3.8: "A participant's `sanction_points_active` is the sum of
        `sanction_points_awarded` over the break-the-glass sessions whose
        `invoking_participant_id` is that participant, whose `review_status` is
        `UNJUSTIFIED`, and whose `decided_at` is strictly later than one hundred
        eighty days before the logical clock."

        PRD 3.8: "The lower bound is exclusive, which is observable: a decision
        exactly one hundred eighty days old has already decayed and contributes
        nothing."

        PRD 3.8: "The threshold comparison is inclusive at twelve: eleven points do
        not suspend, twelve do."

        Design: Corner/Calculations/sanction_points_decay_exactly_at_the_180_day_boundary
        """
        hie.activate_threshold_config(
            config_label="REF-PROB-C7", headers=make_privacy_officer_headers(self.TUNER)
        )
        participant = hie.certified_participant(
            legal_name="Cedarloft Regional Hospital",
            org_type="HOSPITAL",
            declared_annual_patient_volume=108000,
            primary_contact_email="hie@cedarloft.example",
        )
        record = hie.contribute_record(
            participant["id"],
            headers=hie.admin,
            source_mrn="C7-0001",
            given_name="Elowen",
            family_name="Marchetti",
            birth_date="1959-10-03",
            sex="F",
            ssn_last4="7781",
            postal_code="97205",
            phone_digits="5035550119",
        )
        session = hie.open_break_glass(
            record["cluster_id"],
            participant["id"],
            emergency_category="UNCONSCIOUS_PATIENT",
            justification_text=self.JUSTIFICATION,
            clinician_user_id=self.CLINICIAN,
        )
        decided = hie.unjustified_review(
            session["id"], review_note=self.REVIEW_NOTE, reviewer_user_id=self.REVIEWER
        )
        assert decided["review_status"] == "UNJUSTIFIED"
        assert decided["disclosed_sensitive_count"] == 0
        assert decided["sanction_points_awarded"] == 4
        assert decided["decided_at"].startswith("2026-08-01T00:00:00")

        assert hie.set_clock("2027-01-27T23:59:59Z").startswith("2027-01-27T23:59:59")
        inside = hie.get_participant(participant["id"])
        assert inside["sanction_points_active"] == 4
        assert inside["onboarding_status"] == "CERTIFIED"

        assert hie.set_clock("2027-01-28T00:00:00Z").startswith("2027-01-28T00:00:00")
        decayed = hie.get_participant(participant["id"])
        assert decayed["sanction_points_active"] == 0
        assert decayed["onboarding_status"] == "CERTIFIED"

        assert hie.get_break_glass(session["id"])["sanction_points_awarded"] == 4
