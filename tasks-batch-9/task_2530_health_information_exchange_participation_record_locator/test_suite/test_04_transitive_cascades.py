"""Cascades that run three and four links deep from a single request.

Two triggers each open a chain in which every link exists only because the link
before it fired: an unjustified emergency review that crosses the sanction
threshold, and a steward confirmation that merges two identity clusters.
"""

import pytest

from prd_bench_local_runner.testing import validate_success

from test_helpers.factories import patient_record_payload
from test_helpers.fixtures import HieHarness
from test_helpers.test_users import make_privacy_officer_headers

CARDIAC_JUSTIFICATION = (
    "Cardiac arrest in progress; prior medication and allergy history required "
    "before pushing vasoactive agents."
)
HAEMORRHAGE_JUSTIFICATION = (
    "Massive haemorrhage protocol activated; transfusion history and antibody "
    "screen needed immediately."
)
FIRST_UNJUSTIFIED_NOTE = (
    "No arrest documented in the encounter record; emergency override was not "
    "supported by the clinical facts."
)
SECOND_UNJUSTIFIED_NOTE = (
    "No haemorrhage protocol activation exists for this encounter; the override "
    "was not clinically justified."
)
REVIEWER_USER_ID = "privacy-reviewer-1"


class TestSanctionThresholdCascade:
    """One review decision suspends the organization, its feeds and its grade."""

    JUNE_SAMPLE = {
        "period_start": "2026-06-01T00:00:00Z",
        "period_end": "2026-07-01T00:00:00Z",
        "messages_received": 10000,
        "messages_rejected": 300,
        "required_fields_missing_count": 500,
        "duplicate_count": 100,
        "timeliness_p95_seconds": 240,
    }
    RECORD = patient_record_payload(
        source_mrn="P-4001",
        given_name="Iris",
        family_name="Delacroix",
        birth_date="1954-02-19",
        sex="F",
        ssn_last4="6620",
        postal_code="43215",
        phone_digits="6145550164",
    )

    def _certified_with_feed_and_cluster(self, hie: HieHarness):
        """A certified hospital with one graded CCDA feed and one clustered patient."""
        hie.activate_threshold_config(
            headers=make_privacy_officer_headers("privacy-tuner-1"),
            config_label="REF-PROB-C",
            score_variant_mode="PROBABILISTIC_ONLY",
        )
        participant = hie.certified_participant(
            legal_name="Pinecrest Regional Hospital",
            org_type="HOSPITAL",
            declared_annual_patient_volume=180000,
            primary_contact_email="hie@pinecrest.example",
        )
        feed = hie.provision_feed(participant["id"], feed_type="CCDA")
        hie.record_sample(feed["id"], **self.JUNE_SAMPLE)
        record = hie.contribute_record(participant["id"], headers=hie.admin, **self.RECORD)
        return participant, feed, record

    def test_twelfth_sanction_point_suspends_the_participant_its_feed_and_its_grade(
        self, hie: HieHarness
    ):
        """A single unjustified finding runs the four-link chain to an UNGRADED scorecard.

        PRD 3.8: "When an `UNJUSTIFIED` decision pushes `sanction_points_active`
        to twelve points or more and the invoking participant's
        `onboarding_status` is `CERTIFIED`, a four-link cascade fires inside that
        same request."

        PRD 3.8: "Link 3, caused by link 2, moves every data feed of that
        participant whose `status` is `PROVISIONING`, `MONITORED` or `DEGRADED`
        to `SUSPENDED` with `status_reason` set to the literal
        `PARTICIPANT_SUSPENSION_CASCADE`, processed in ascending `created_at`
        order."

        Design: Difficulty/transitive_cascade/unjustified_break_glass_review_cascades_sanction_suspension_feed_and_scorecard
        """
        participant, feed, record = self._certified_with_feed_and_cluster(hie)
        cluster_id = record["cluster_id"]

        first_session = hie.open_break_glass(
            cluster_id,
            participant["id"],
            emergency_category="LIFE_THREATENING",
            justification_text=CARDIAC_JUSTIFICATION,
            clinician_user_id="clin-f-1",
        )
        first_decided = hie.unjustified_review(
            first_session["id"], FIRST_UNJUSTIFIED_NOTE, reviewer_user_id=REVIEWER_USER_ID
        )
        assert first_decided["sanction_points_awarded"] == 6
        assert hie.get_participant(participant["id"])["onboarding_status"] == "CERTIFIED"

        second_session = hie.open_break_glass(
            cluster_id,
            participant["id"],
            emergency_category="LIFE_THREATENING",
            justification_text=HAEMORRHAGE_JUSTIFICATION,
            clinician_user_id="clin-f-2",
        )
        reviewer = make_privacy_officer_headers(REVIEWER_USER_ID)
        validate_success(
            hie.client.claim_break_glass_review(reviewer, second_session["id"]), 200
        )
        decided = validate_success(
            hie.client.decide_break_glass_review(
                reviewer,
                second_session["id"],
                outcome="UNJUSTIFIED",
                review_note=SECOND_UNJUSTIFIED_NOTE,
            ),
            200,
        )
        assert decided["sanction_points_awarded"] == 6
        assert decided["decided_at"].startswith("2026-08-01T00:00:00")
        assert decided["review_status"] == "UNJUSTIFIED"
        assert decided["session_status"] == "OPEN"

        suspended = hie.get_participant(participant["id"])
        assert suspended["sanction_points_active"] == 12
        assert suspended["onboarding_status"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "AUTOMATIC_SANCTION_THRESHOLD"
        assert suspended["quality_score"] is None
        assert suspended["quality_grade"] == "UNGRADED"

        cascaded_feed = hie.get_data_feed(feed["id"])
        assert cascaded_feed["status"] == "SUSPENDED"
        assert cascaded_feed["status_reason"] == "PARTICIPANT_SUSPENSION_CASCADE"
        assert cascaded_feed["sample_count"] == 1

        scorecard = hie.get_scorecard(participant["id"])
        assert scorecard["samples_counted"] == 0
        assert scorecard["quality_score"] is None
        assert scorecard["grade"] == "UNGRADED"

    def test_eleven_active_points_leave_the_whole_chain_unfired(self, hie: HieHarness):
        """One point short of the threshold, link 2 never fires and neither do 3 and 4.

        PRD 3.8: "The threshold comparison is inclusive at twelve: eleven points
        do not suspend, twelve do."

        PRD 3.8: "An `UNJUSTIFIED` finding computes `sanction_points_awarded` as
        the category's own weight — six points for `LIFE_THREATENING`, four for
        `UNCONSCIOUS_PATIENT`, three for `DISASTER` — plus a surcharge of two
        additional points when the session's `disclosed_sensitive_count` is
        greater than zero."

        Design: Difficulty/transitive_cascade/unjustified_break_glass_review_cascades_sanction_suspension_feed_and_scorecard
        """
        participant, feed, record = self._certified_with_feed_and_cluster(hie)
        cluster_id = record["cluster_id"]

        awarded = []
        for category, clinician in (
            ("UNCONSCIOUS_PATIENT", "clin-g-1"),
            ("UNCONSCIOUS_PATIENT", "clin-g-2"),
            ("DISASTER", "clin-g-3"),
        ):
            session = hie.open_break_glass(
                cluster_id,
                participant["id"],
                emergency_category=category,
                justification_text=CARDIAC_JUSTIFICATION,
                clinician_user_id=clinician,
            )
            assert session["disclosed_sensitive_count"] == 0
            decided = hie.unjustified_review(
                session["id"], FIRST_UNJUSTIFIED_NOTE, reviewer_user_id=REVIEWER_USER_ID
            )
            awarded.append(decided["sanction_points_awarded"])

        assert awarded == [4, 4, 3]

        still_certified = hie.get_participant(participant["id"])
        assert still_certified["sanction_points_active"] == 11
        assert still_certified["onboarding_status"] == "CERTIFIED"
        assert still_certified["suspension_reason"] is None

        assert hie.get_data_feed(feed["id"])["status"] == "MONITORED"

        scorecard = hie.get_scorecard(participant["id"])
        assert scorecard["samples_counted"] == 1
        assert scorecard["quality_score"] == pytest.approx(97.45, abs=0.01)
        assert scorecard["grade"] == "A"


class TestConfirmedMergeCascade:
    """A steward's CONFIRM merges two clusters and then re-points their consent."""

    LEFT_RECORD = patient_record_payload(
        source_mrn="A-5001",
        given_name="Maria",
        family_name="Gonzalez",
        birth_date="1991-07-22",
        sex="F",
        ssn_last4="3321",
        postal_code="78701",
        phone_digits="5125550143",
    )
    RIGHT_RECORD = patient_record_payload(
        source_mrn="R-6001",
        given_name="Mari",
        family_name="Gonzales",
        birth_date="1991-07-22",
        sex="F",
        ssn_last4="3321",
        postal_code="78701",
        phone_digits="2125550143",
    )
    STEWARD_USER_ID = "privacy-steward-1"
    CONFIRM_NOTE = "Same patient confirmed against the state driver licence index."

    def _pending_review_pair(self, hie: HieHarness):
        """Two contributors and one 0.7700 link parked in PENDING_REVIEW."""
        hie.activate_consent_policy(policy_version="SP-2026.1", effective_from="2026-01-01T00:00:00Z")
        hie.activate_threshold_config(
            headers=make_privacy_officer_headers("privacy-tuner-1"),
            config_label="REF-PROB-D",
            score_variant_mode="PROBABILISTIC_ONLY",
        )
        winner_participant = hie.participant_in_conformance_testing(
            legal_name="Alto Mesa Hospital",
            org_type="HOSPITAL",
            declared_annual_patient_volume=96000,
            primary_contact_email="hie@altomesa.example",
        )
        loser_participant = hie.participant_in_conformance_testing(
            legal_name="Rio Vista Family Clinic",
            org_type="CLINIC",
            declared_annual_patient_volume=36000,
            primary_contact_email="hie@riovista.example",
        )
        left_record = hie.contribute_record(
            winner_participant["id"], headers=hie.admin, **self.LEFT_RECORD
        )
        right_record = hie.contribute_record(
            loser_participant["id"], headers=hie.admin, **self.RIGHT_RECORD
        )
        link = hie.only_link_between(right_record["id"])
        return {
            "winner_cluster_id": left_record["cluster_id"],
            "loser_cluster_id": right_record["cluster_id"],
            "left_record": left_record,
            "right_record": right_record,
            "link": link,
        }

    def _confirm(self, hie: HieHarness, link_id: str, winner_cluster_id: str):
        return validate_success(
            hie.client.record_steward_decision(
                make_privacy_officer_headers(self.STEWARD_USER_ID),
                link_id,
                decision="CONFIRM",
                expected_cluster_version=hie.cluster_version(winner_cluster_id),
                review_note=self.CONFIRM_NOTE,
            ),
            200,
        )

    def test_confirm_merges_the_clusters_and_supersedes_the_duplicate_directive(
        self, hie: HieHarness
    ):
        """LINKED causes the merge, and the merge causes the consent supersession.

        PRD 3.5: "Caused by step 1, the two clusters merge. The cluster with the
        earlier `created_at` wins; the loser moves `ACTIVE → MERGED_AWAY` with
        `merged_into_cluster_id` set to the winner."

        PRD 3.5: "Caused by step 2, every consent directive whose `cluster_id`
        was the loser is re-pointed at the winner."

        Design: Difficulty/transitive_cascade/confirmed_match_link_cascades_cluster_merge_into_directive_supersession
        """
        pair = self._pending_review_pair(hie)
        winner_cluster_id = pair["winner_cluster_id"]
        loser_cluster_id = pair["loser_cluster_id"]

        assert pair["link"]["match_score"] == pytest.approx(0.7700, abs=0.0001)
        assert pair["link"]["status"] == "PENDING_REVIEW"

        older_directive = hie.record_directive(
            winner_cluster_id,
            directive_type="OPT_IN",
            scope="ALL_PARTICIPANTS",
            effective_from="2026-03-01T00:00:00Z",
        )
        newer_directive = hie.record_directive(
            loser_cluster_id,
            directive_type="OPT_IN",
            scope="ALL_PARTICIPANTS",
            effective_from="2026-05-01T00:00:00Z",
        )

        decided = self._confirm(hie, pair["link"]["id"], winner_cluster_id)
        assert decided["status"] == "LINKED"
        assert decided["cluster_id"] == winner_cluster_id
        assert decided["merged_away_cluster_id"] == loser_cluster_id
        assert decided["reviewed_by_user_id"] == self.STEWARD_USER_ID

        loser = hie.get_cluster(loser_cluster_id)
        assert loser["status"] == "MERGED_AWAY"
        assert loser["merged_into_cluster_id"] == winner_cluster_id

        moved_record = hie.get_record(pair["right_record"]["id"])
        assert moved_record["cluster_id"] == winner_cluster_id
        assert moved_record["prior_cluster_id"] == loser_cluster_id

        winner = hie.get_cluster(winner_cluster_id)
        assert winner["member_record_count"] == 2
        assert winner["participant_count"] == 2
        assert winner["active_directive_count"] == 1

        superseded = validate_success(
            hie.client.get_consent_directive(hie.privacy_officer, older_directive["id"]), 200
        )
        assert superseded["status"] == "SUPERSEDED"

        survivor = validate_success(
            hie.client.get_consent_directive(hie.privacy_officer, newer_directive["id"]), 200
        )
        assert survivor["status"] == "ACTIVE"
        assert survivor["cluster_id"] == winner_cluster_id
        assert survivor["supersedes_directive_id"] == older_directive["id"]

    def test_supersession_follows_effective_from_not_which_cluster_won_the_merge(
        self, hie: HieHarness
    ):
        """Give the winner the later directive and the loser's is the one superseded.

        PRD 3.5: "Where the winner already holds an `ACTIVE` directive sharing
        the same `(directive_type, scope, scoped_participant_id)` triple, the one
        with the **earlier** `effective_from` moves `ACTIVE → SUPERSEDED`, ties
        broken by ascending `created_at`, and the survivor's
        `supersedes_directive_id` is set to the superseded row's `id`."

        Design: Difficulty/transitive_cascade/confirmed_match_link_cascades_cluster_merge_into_directive_supersession
        """
        pair = self._pending_review_pair(hie)
        winner_cluster_id = pair["winner_cluster_id"]
        loser_cluster_id = pair["loser_cluster_id"]

        winner_directive = hie.record_directive(
            winner_cluster_id,
            directive_type="OPT_IN",
            scope="ALL_PARTICIPANTS",
            effective_from="2026-06-01T00:00:00Z",
        )
        loser_directive = hie.record_directive(
            loser_cluster_id,
            directive_type="OPT_IN",
            scope="ALL_PARTICIPANTS",
            effective_from="2026-03-01T00:00:00Z",
        )

        self._confirm(hie, pair["link"]["id"], winner_cluster_id)

        superseded = validate_success(
            hie.client.get_consent_directive(hie.privacy_officer, loser_directive["id"]), 200
        )
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["cluster_id"] == winner_cluster_id

        survivor = validate_success(
            hie.client.get_consent_directive(hie.privacy_officer, winner_directive["id"]), 200
        )
        assert survivor["status"] == "ACTIVE"
        assert survivor["supersedes_directive_id"] == loser_directive["id"]

        assert hie.get_cluster(winner_cluster_id)["active_directive_count"] == 1
