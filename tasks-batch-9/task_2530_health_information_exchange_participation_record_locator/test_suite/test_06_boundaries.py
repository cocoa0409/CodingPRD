"""Values sitting exactly on a declared edge, and their nearest neighbours.

One edge is numeric — the auto-link threshold, compared inclusively at the fourth
decimal — and one is temporal, the exclusive lower bound of the ninety-day quality
window.
"""

import pytest

from prd_bench_local_runner.testing import validate_success

from test_helpers.factories import patient_record_payload
from test_helpers.fixtures import HieHarness
from test_helpers.test_users import make_privacy_officer_headers


class TestAutoLinkThresholdIsInclusive:
    """A pair scoring exactly the threshold links; one ten-thousandth higher reviews."""

    TUNER = "privacy-tuner-1"
    NGUYEN_LEFT = patient_record_payload(
        source_mrn="B1-0001",
        given_name="Robert",
        family_name="Nguyen",
        birth_date="1979-04-12",
        sex="M",
        ssn_last4="4417",
        postal_code="94110",
        phone_digits="4155550111",
    )
    NGUYEN_RIGHT = patient_record_payload(
        source_mrn="B2-0001",
        given_name="Robert",
        family_name="Nguyen",
        birth_date="1979-04-12",
        sex="M",
        ssn_last4="4417",
        postal_code="02139",
        phone_digits="4155550111",
    )
    OKONJO_LEFT = patient_record_payload(
        source_mrn="B1-0002",
        given_name="Amara",
        family_name="Okonjo",
        birth_date="1986-09-30",
        sex="F",
        ssn_last4="7734",
        postal_code="80202",
        phone_digits="3035550122",
    )
    OKONJO_RIGHT = patient_record_payload(
        source_mrn="B2-0002",
        given_name="Amara",
        family_name="Okonjo",
        birth_date="1986-09-30",
        sex="F",
        ssn_last4="7734",
        postal_code="33139",
        phone_digits="3035550122",
    )

    def _two_contributors(self, hie: HieHarness):
        left = hie.participant_in_conformance_testing(
            legal_name="Bayfront Medical Group",
            org_type="CLINIC",
            declared_annual_patient_volume=60000,
            primary_contact_email="hie@bayfront.example",
        )
        right = hie.participant_in_conformance_testing(
            legal_name="Copley Square Health Partners",
            org_type="CLINIC",
            declared_annual_patient_volume=48000,
            primary_contact_email="hie@copleysquare.example",
        )
        return left, right

    @staticmethod
    def _link_between(hie: HieHarness, left_record_id: str, right_record_id: str):
        links = validate_success(
            hie.client.list_match_links(
                hie.privacy_officer,
                left_record_id=left_record_id,
                right_record_id=right_record_id,
                limit=100,
            ),
            200,
        )
        assert len(links) == 1
        return links[0]

    def test_score_equal_to_the_auto_link_threshold_is_linked_outright(
        self, hie: HieHarness
    ):
        """0.9200 against a threshold of 0.9200 takes the auto-link branch.

        PRD 3.4: "When `match_score` is at or above the pinned generation's
        `auto_link_threshold`, the link goes `PROPOSED → AUTO_LINKED`; this branch
        additionally requires that both records have `match_state` `CLUSTERED` and
        that both of their clusters have `status` `ACTIVE`."

        Design: Difficulty/boundary_precision_check/match_score_exactly_at_auto_link_threshold_links_but_one_ten_thousandth_higher_reviews
        """
        generation_one = hie.activate_threshold_config(
            headers=make_privacy_officer_headers(self.TUNER),
            config_label="REF-BOUND-G1",
            auto_link_threshold=0.9200,
            review_lower_bound=0.7500,
            score_variant_mode="PROBABILISTIC_ONLY",
        )
        left_participant, right_participant = self._two_contributors(hie)

        left_record = hie.contribute_record(
            left_participant["id"], headers=hie.admin, **self.NGUYEN_LEFT
        )
        right_record = hie.contribute_record(
            right_participant["id"], headers=hie.admin, **self.NGUYEN_RIGHT
        )

        link = self._link_between(hie, left_record["id"], right_record["id"])
        assert link["match_score"] == pytest.approx(0.9200, abs=0.00001)
        assert link["status"] == "AUTO_LINKED"
        assert link["threshold_config_id"] == generation_one["id"]
        assert link["cluster_id"] == left_record["cluster_id"]
        # The merge already ran inside the contribution, so the incoming record's
        # own cluster is the loser it now names through `prior_cluster_id`, while
        # its `cluster_id` has been repointed at the winner.
        loser_cluster_id = right_record["prior_cluster_id"]
        assert right_record["cluster_id"] == left_record["cluster_id"]
        assert link["merged_away_cluster_id"] == loser_cluster_id

        winner = hie.get_cluster(left_record["cluster_id"])
        assert winner["status"] == "ACTIVE"
        assert winner["member_record_count"] == 2
        assert hie.get_cluster(loser_cluster_id)["status"] == "MERGED_AWAY"

    def test_raising_the_threshold_by_one_ten_thousandth_sends_the_same_score_to_review(
        self, hie: HieHarness
    ):
        """0.9200 against a threshold of 0.9201 falls into the review band instead.

        PRD 3.4: "When `match_score` is at or above `review_lower_bound` and
        strictly below `auto_link_threshold`, the link goes
        `PROPOSED → PENDING_REVIEW`."

        PRD 3.3: "Activation is deliberately **not** retroactive: match links
        already created keep the `threshold_config_id` pinned to them at proposal
        time and are never re-scored, so the exchange can always explain why a
        historical link was routed the way it was."

        Design: Difficulty/boundary_precision_check/match_score_exactly_at_auto_link_threshold_links_but_one_ten_thousandth_higher_reviews
        """
        tuner = make_privacy_officer_headers(self.TUNER)
        generation_one = hie.activate_threshold_config(
            headers=tuner,
            config_label="REF-BOUND-G1",
            auto_link_threshold=0.9200,
            review_lower_bound=0.7500,
            score_variant_mode="PROBABILISTIC_ONLY",
        )
        left_participant, right_participant = self._two_contributors(hie)
        nguyen_left = hie.contribute_record(
            left_participant["id"], headers=hie.admin, **self.NGUYEN_LEFT
        )
        nguyen_right = hie.contribute_record(
            right_participant["id"], headers=hie.admin, **self.NGUYEN_RIGHT
        )
        linked_under_generation_one = self._link_between(
            hie, nguyen_left["id"], nguyen_right["id"]
        )
        assert linked_under_generation_one["status"] == "AUTO_LINKED"

        okonjo_left = hie.contribute_record(
            left_participant["id"], headers=hie.admin, **self.OKONJO_LEFT
        )

        generation_two_draft = hie.draft_threshold_config(
            headers=tuner,
            config_label="REF-BOUND-G2",
            auto_link_threshold=0.9201,
            review_lower_bound=0.7500,
            score_variant_mode="PROBABILISTIC_ONLY",
        )
        generation_two = validate_success(
            hie.client.activate_match_threshold_config(tuner, generation_two_draft["id"]), 200
        )
        assert generation_two["status"] == "ACTIVE"

        okonjo_right = hie.contribute_record(
            right_participant["id"], headers=hie.admin, **self.OKONJO_RIGHT
        )
        reviewed_link = self._link_between(hie, okonjo_left["id"], okonjo_right["id"])
        assert reviewed_link["match_score"] == pytest.approx(0.9200, abs=0.00001)
        assert reviewed_link["status"] == "PENDING_REVIEW"
        assert reviewed_link["threshold_config_id"] == generation_two["id"]

        retired = validate_success(
            hie.client.get_match_threshold_config(hie.privacy_officer, generation_one["id"]), 200
        )
        assert retired["status"] == "RETIRED"

        untouched = validate_success(
            hie.client.get_match_link(
                hie.privacy_officer, linked_under_generation_one["id"]
            ),
            200,
        )
        assert untouched["threshold_config_id"] == generation_one["id"]
        assert untouched["status"] == "AUTO_LINKED"
        assert untouched["match_score"] == pytest.approx(0.9200, abs=0.00001)


class TestQualityWindowLowerBoundIsExclusive:
    """A sample ending exactly at `window_start` contributes nothing at all."""

    EDGE_SAMPLE = {
        "period_start": "2026-04-03T00:00:00Z",
        "period_end": "2026-05-03T00:00:00Z",
        "messages_received": 5000,
        "messages_rejected": 100,
        "required_fields_missing_count": 150,
        "duplicate_count": 40,
        "timeliness_p95_seconds": 220,
    }
    INSIDE_SAMPLE = {
        "period_start": "2026-05-03T00:00:01Z",
        "period_end": "2026-06-03T00:00:00Z",
        "messages_received": 8000,
        "messages_rejected": 100,
        "required_fields_missing_count": 200,
        "duplicate_count": 50,
        "timeliness_p95_seconds": 250,
    }
    # Its window is wedged into the one second between the excluded edge sample's
    # exclusive end and the inside sample's inclusive start, so it overlaps
    # neither of them while its `period_end` sits one second past `window_start`.
    ONE_SECOND_PAST_THE_EDGE_SAMPLE = {
        "period_start": "2026-05-03T00:00:00Z",
        "period_end": "2026-05-03T00:00:01Z",
        "messages_received": 8000,
        "messages_rejected": 100,
        "required_fields_missing_count": 200,
        "duplicate_count": 50,
        "timeliness_p95_seconds": 250,
    }

    def _participant_with_edge_sample(self, hie: HieHarness):
        participant = hie.participant_in_conformance_testing(
            legal_name="Windward Point Hospital",
            org_type="HOSPITAL",
            declared_annual_patient_volume=72000,
            primary_contact_email="hie@windwardpoint.example",
        )
        feed = hie.provision_feed(participant["id"], feed_type="ADT")
        assert feed["status"] == "PROVISIONING"
        sample = hie.record_sample(feed["id"], **self.EDGE_SAMPLE)
        assert sample["reject_rate"] == pytest.approx(0.0200, abs=0.0001)
        return participant, feed

    def test_sample_ending_on_the_window_edge_leaves_the_scorecard_ungraded(
        self, hie: HieHarness
    ):
        """The feed is MONITORED with one sample and the participant is still UNGRADED.

        PRD 3.9: "Restrict to samples whose `period_end` is strictly later than
        ninety days before the logical clock — an exclusive lower bound — and at
        or before the logical clock, an inclusive upper bound."

        PRD 3.9: "When the qualifying set is empty the participant is ungraded:
        `quality_score` is null, `grade` and `provisional_grade` are both
        `UNGRADED`, `penalty_points` is zero, and the four components,
        `average_p95_seconds` and `base_quality_score` are all reported as zero."

        Design: Difficulty/boundary_precision_check/quality_sample_ending_exactly_at_window_start_is_excluded_leaving_scorecard_ungraded
        """
        participant, feed = self._participant_with_edge_sample(hie)

        scorecard = hie.get_scorecard(participant["id"])
        assert scorecard["window_start"].startswith("2026-05-03T00:00:00")
        assert scorecard["samples_counted"] == 0
        assert scorecard["quality_score"] is None
        assert scorecard["grade"] == "UNGRADED"
        assert scorecard["provisional_grade"] == "UNGRADED"
        assert scorecard["penalty_points"] == 0
        assert scorecard["base_quality_score"] == pytest.approx(0, abs=0.01)
        assert scorecard["average_p95_seconds"] == pytest.approx(0, abs=0.01)

        live_feed = hie.get_data_feed(feed["id"])
        assert live_feed["status"] == "MONITORED"
        assert live_feed["sample_count"] == 1

    def test_sample_ending_one_second_past_the_edge_joins_the_window(self, hie: HieHarness):
        """The same window predicate admits a period_end one second later.

        PRD 3.9: "Restrict to samples whose `period_end` is strictly later than
        ninety days before the logical clock — an exclusive lower bound — and at
        or before the logical clock, an inclusive upper bound."

        PRD 3.9: "The scorecard read reports `participant_id` alongside every
        value named in this paragraph and the three before it, and the participant
        row itself carries the latest `quality_score` and `quality_grade`, the
        latter drawn from `A`, `B`, `C`, `D` or `UNGRADED`."

        Design: Difficulty/boundary_precision_check/quality_sample_ending_exactly_at_window_start_is_excluded_leaving_scorecard_ungraded
        """
        participant, feed = self._participant_with_edge_sample(hie)

        hie.record_sample(feed["id"], **self.INSIDE_SAMPLE)
        one_counted = hie.get_scorecard(participant["id"])
        assert one_counted["samples_counted"] == 1
        assert one_counted["base_quality_score"] == pytest.approx(98.78, abs=0.01)
        assert one_counted["quality_score"] == pytest.approx(98.78, abs=0.01)
        assert one_counted["grade"] == "A"
        assert one_counted["average_p95_seconds"] == pytest.approx(250.00, abs=0.01)

        hie.record_sample(feed["id"], **self.ONE_SECOND_PAST_THE_EDGE_SAMPLE)
        two_counted = hie.get_scorecard(participant["id"])
        assert two_counted["samples_counted"] == 2
        assert two_counted["quality_score"] == pytest.approx(98.78, abs=0.01)
        assert two_counted["grade"] == "A"
        assert two_counted["average_p95_seconds"] == pytest.approx(250.00, abs=0.01)

        refreshed = hie.get_participant(participant["id"])
        assert refreshed["quality_score"] == pytest.approx(98.78, abs=0.01)
        assert refreshed["quality_grade"] == "A"
