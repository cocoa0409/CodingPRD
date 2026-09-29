"""The two engines that compute one number two different ways.

The participation fee and the identity match score are each specified as a single
engine with two variants, and in both cases the variant choice is observable on
identical inputs.
"""

import pytest

from prd_bench_local_runner.testing import validate_success

from test_helpers.factories import patient_record_payload
from test_helpers.fixtures import HieHarness


class TestParticipationFeeVariants:
    """PROVISIONAL bills a promise; RECONCILED bills observed traffic."""

    @staticmethod
    def _participant_with_june_sample(hie: HieHarness):
        participant = hie.participant_in_conformance_testing(
            legal_name="Cascade Regional Health",
            declared_annual_patient_volume=360012,
            primary_contact_email="ops@cascade.example",
        )
        feed = hie.provision_feed(participant["id"], feed_type="CCDA")
        hie.record_sample(
            feed["id"],
            period_start="2026-06-01T00:00:00Z",
            period_end="2026-07-01T00:00:00Z",
            messages_received=10000,
            messages_rejected=300,
            required_fields_missing_count=500,
            duplicate_count=100,
            timeliness_p95_seconds=240,
        )
        return participant

    def test_provisional_and_reconciled_invoices_diverge_on_the_same_june_period(
        self, hie: HieHarness
    ):
        """The same participant and the same billing period bill differently per variant.

        PRD 3.9: "The same participant and period will generally produce a
        materially different figure under each variant, and the difference is
        intentional: the provisional basis bills a promise, the reconciled basis
        bills observed traffic adjusted for how clean it was."

        Design: Difficulty/dual_variant_calc/participation_fee_provisional_vs_reconciled_diverge_on_same_billing_period
        """
        participant = self._participant_with_june_sample(hie)

        provisional = hie.issue_invoice(
            participant["id"],
            billing_period_start="2026-06-01T00:00:00Z",
            billing_period_end="2026-07-01T00:00:00Z",
            basis_variant="PROVISIONAL",
            due_date="2026-08-15T00:00:00Z",
        )
        assert provisional["billable_volume_units"] == 30001
        assert provisional["volume_fee_cents"] == 49877
        assert provisional["quality_multiplier"] == pytest.approx(1.00, abs=0.01)
        assert provisional["total_cents"] == 299877

        validate_success(
            hie.client.administer_participation_invoice(
                hie.admin,
                provisional["id"],
                action="VOID",
                reason="Re-issued on a reconciled basis once the June samples landed",
            ),
            200,
        )

        reconciled = hie.issue_invoice(
            participant["id"],
            billing_period_start="2026-06-01T00:00:00Z",
            billing_period_end="2026-07-01T00:00:00Z",
            basis_variant="RECONCILED",
            due_date="2026-08-15T00:00:00Z",
        )
        assert reconciled["billable_volume_units"] == 10000
        assert reconciled["volume_fee_cents"] == 17500
        assert reconciled["quality_grade_snapshot"] == "A"
        assert reconciled["quality_multiplier"] == pytest.approx(0.95, abs=0.01)
        assert reconciled["total_cents"] == 254125

        assert provisional["total_cents"] - reconciled["total_cents"] == 45752
        assert hie.get_invoice(provisional["id"])["status"] == "VOID"
        assert hie.get_participant(participant["id"])["outstanding_balance_cents"] == 254125

    def test_registration_pins_the_provisional_variant_and_its_tier(self, hie: HieHarness):
        """Registration bills the declared volume unconditionally on the PROVISIONAL basis.

        PRD 3.9: "Under the `PROVISIONAL` variant — used unconditionally at
        participant registration, and available at issuance by naming it as
        `basis_variant` — the billable volume is `declared_annual_patient_volume`
        divided by twelve and rounded **up** to a whole unit, and
        `quality_multiplier` is forced to 1.00 no matter what scorecard history
        exists."

        PRD 3.1: "Because no data feeds exist yet, `quality_score` is null and
        `quality_grade` is `UNGRADED`."

        Design: Difficulty/dual_variant_calc/participation_fee_provisional_vs_reconciled_diverge_on_same_billing_period
        """
        participant = hie.register_participant(
            legal_name="Cascade Regional Health",
            declared_annual_patient_volume=360012,
            primary_contact_email="ops@cascade.example",
        )
        assert participant["provisional_monthly_fee_cents"] == 299877
        assert participant["fee_tier"] == "TIER_2"
        assert participant["quality_score"] is None
        assert participant["quality_grade"] == "UNGRADED"


class TestMatchScoreVariants:
    """One demographic pair, two verdicts, decided by the pinned generation."""

    LEFT_PAIR_ONE = patient_record_payload(
        source_mrn="N-1001",
        given_name="Bill",
        family_name="Smith",
        birth_date="1965-11-30",
        sex="M",
        ssn_last4="9902",
        postal_code="60601",
        phone_digits="3125550100",
    )
    RIGHT_PAIR_ONE = patient_record_payload(
        source_mrn="S-2001",
        given_name="Guillermo",
        family_name="Herrera",
        birth_date="1965-11-30",
        sex="M",
        ssn_last4="9902",
        postal_code="10002",
        phone_digits="9175550188",
    )
    LEFT_PAIR_TWO = patient_record_payload(
        source_mrn="N-1002",
        given_name="Walter",
        family_name="Pearson",
        birth_date="1972-03-08",
        sex="M",
        ssn_last4="5510",
        postal_code="97201",
        phone_digits="5035550190",
    )
    RIGHT_PAIR_TWO = patient_record_payload(
        source_mrn="S-2002",
        given_name="Gualterio",
        family_name="Cardoso",
        birth_date="1972-03-08",
        sex="M",
        ssn_last4="5510",
        postal_code="33101",
        phone_digits="7865550175",
    )

    def test_agreement_on_only_birth_date_and_last_four_links_deterministically_and_is_rejected_probabilistically(
        self, hie: HieHarness
    ):
        """The same conjunction earns 1.0000 one way and 0.5300 the other.

        PRD 3.4: "The choice is observably consequential for the same pair of
        records: a pair agreeing on nothing but `ssn_last4` and `birth_date` earns
        a partial weighted total under the probabilistic variant, which may well
        fall below the review band, while the same pair earns a flat 1.0000 under
        the deterministic variant and is auto-linked outright."

        Design: Difficulty/dual_variant_calc/match_score_deterministic_vs_probabilistic_diverge_on_same_demographic_pair
        """
        deterministic = hie.activate_threshold_config(
            config_label="REF-DET-A", score_variant_mode="DETERMINISTIC_FIRST"
        )
        left_participant = hie.participant_in_conformance_testing(
            legal_name="Northline Hospital", primary_contact_email="it@northline.example"
        )
        right_participant = hie.participant_in_conformance_testing(
            legal_name="Southbay Clinic",
            org_type="CLINIC",
            primary_contact_email="it@southbay.example",
        )

        left_one = hie.contribute_record(
            left_participant["id"], headers=hie.admin, **self.LEFT_PAIR_ONE
        )
        right_one = hie.contribute_record(
            right_participant["id"], headers=hie.admin, **self.RIGHT_PAIR_ONE
        )

        probabilistic = hie.activate_threshold_config(
            config_label="REF-PROB-A", score_variant_mode="PROBABILISTIC_ONLY"
        )

        left_two = hie.contribute_record(
            left_participant["id"], headers=hie.admin, **self.LEFT_PAIR_TWO
        )
        right_two = hie.contribute_record(
            right_participant["id"], headers=hie.admin, **self.RIGHT_PAIR_TWO
        )

        first_link = validate_success(
            hie.client.list_match_links(
                hie.privacy_officer, left_record_id=left_one["id"], right_record_id=right_one["id"]
            ),
            200,
        )[0]
        assert first_link["match_score"] == pytest.approx(1.0000, abs=0.0001)
        assert first_link["score_variant"] == "DETERMINISTIC"
        assert first_link["status"] == "AUTO_LINKED"
        assert first_link["threshold_config_id"] == deterministic["id"]

        second_link = validate_success(
            hie.client.list_match_links(
                hie.privacy_officer, left_record_id=left_two["id"], right_record_id=right_two["id"]
            ),
            200,
        )[0]
        assert second_link["match_score"] == pytest.approx(0.5300, abs=0.0001)
        assert second_link["score_variant"] == "PROBABILISTIC"
        assert second_link["status"] == "REJECTED"
        assert second_link["threshold_config_id"] == probabilistic["id"]

        assert (
            hie.get_record(left_two["id"])["cluster_id"]
            != hie.get_record(right_two["id"])["cluster_id"]
        )

    def test_activating_a_second_generation_retires_the_first_and_leaves_its_scored_count(
        self, hie: HieHarness
    ):
        """Activation retires the incumbent and never re-scores the links it produced.

        PRD 3.3: "Activation is deliberately **not** retroactive: match links
        already created keep the `threshold_config_id` pinned to them at proposal
        time and are never re-scored, so the exchange can always explain why a
        historical link was routed the way it was."

        Design: Difficulty/dual_variant_calc/match_score_deterministic_vs_probabilistic_diverge_on_same_demographic_pair
        """
        deterministic = hie.activate_threshold_config(
            config_label="REF-DET-A", score_variant_mode="DETERMINISTIC_FIRST"
        )
        left_participant = hie.participant_in_conformance_testing(
            legal_name="Northline Hospital", primary_contact_email="it@northline.example"
        )
        right_participant = hie.participant_in_conformance_testing(
            legal_name="Southbay Clinic",
            org_type="CLINIC",
            primary_contact_email="it@southbay.example",
        )
        hie.contribute_record(left_participant["id"], headers=hie.admin, **self.LEFT_PAIR_ONE)
        right_one = hie.contribute_record(
            right_participant["id"], headers=hie.admin, **self.RIGHT_PAIR_ONE
        )
        link = hie.only_link_between(right_one["id"])

        hie.activate_threshold_config(
            config_label="REF-PROB-A", score_variant_mode="PROBABILISTIC_ONLY"
        )

        retired = validate_success(
            hie.client.get_match_threshold_config(hie.privacy_officer, deterministic["id"]), 200
        )
        assert retired["status"] == "RETIRED"
        assert retired["scored_link_count"] == 1

        unchanged = validate_success(
            hie.client.get_match_link(hie.privacy_officer, link["id"]), 200
        )
        assert unchanged["threshold_config_id"] == deterministic["id"]
        assert unchanged["score_variant"] == "DETERMINISTIC"
        assert unchanged["match_score"] == pytest.approx(1.0000, abs=0.0001)
