"""Read-your-write across the derived fields a single measurement window feeds.

One accepted quality sample is the only write in this file. Everything else is a
read, and every read must already agree with it: the sample's own computed rate,
the feed's monitoring status, the participant row's denormalized pair, and the
on-demand scorecard. Nothing here is allowed to lag behind by a request.
"""

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers.fixtures import HieHarness
from test_helpers.test_users import make_hie_admin_headers


class TestOneSamplePublishesEveryDerivedField:
    """The stored pair and the recomputed scorecard must match field for field."""

    SIGNATORY = "admin-legal-1"

    def test_the_first_sample_settles_the_feed_the_participant_row_and_the_scorecard(
        self, hie: HieHarness
    ):
        """After one window the rate, the status and both grade views are already readable.

        PRD 3.9: "The first accepted sample on a feed drives
        `PROVISIONING → MONITORED`, sets `latest_reject_rate`, and re-runs the
        scorecard because the feed has just entered the qualifying status set."

        PRD 3.9: "Each accepted sample records the addressed feed as its
        `data_feed_id` and stores its own `reject_rate`, computed as
        `messages_rejected` divided by the greater of one and `messages_received`,
        rounded half up to four decimal places — the guard in the denominator means a
        window with no traffic yields a reject rate of exactly zero rather than an
        undefined value."

        PRD 3.9: "The scorecard is computed on demand and re-computed on every event
        that can change its inputs — a newly accepted sample, and every feed
        transition into or out of the qualifying statuses."

        PRD 3.9: "Three ratio components are then formed, each expressed on a
        hundred-point scale: `completeness_component` is one hundred times the
        quantity one minus the sum of `required_fields_missing_count` divided by the
        greater of one and the received total; `rejection_component` is one hundred
        times the quantity one minus the sum of `messages_rejected` divided by the
        greater of one and the received total; and `duplicate_component` is one
        hundred times the quantity one minus the sum of `duplicate_count` divided by
        the greater of one and the received total."

        PRD 3.9: "`base_quality_score` is the weighted blend of those four components
        — thirty hundredths of `completeness_component`, plus thirty hundredths of
        `rejection_component`, plus fifteen hundredths of `duplicate_component`, plus
        twenty-five hundredths of `timeliness_component` — rounded half up to two
        decimal places."

        PRD 3.9: "First derive a `provisional_grade` from `base_quality_score`: `A` at
        ninety-two or above, `B` at eighty-four or above, `C` at seventy or above, and
        `D` below that."

        PRD 3.9: "The scorecard read reports `participant_id` alongside every value
        named in this paragraph and the three before it, and the participant row
        itself carries the latest `quality_score` and `quality_grade`, the latter
        drawn from `A`, `B`, `C`, `D` or `UNGRADED`."

        Design: Corner/Consistency Model/one_quality_sample_publishes_every_derived_field_in_the_same_request
        """
        participant = hie.register_participant(
            legal_name="Gladewater Regional Hospital",
            org_type="HOSPITAL",
            declared_annual_patient_volume=72000,
            primary_contact_email="hie@gladewater.example",
        )
        assert participant["quality_grade"] == "UNGRADED"
        assert participant["quality_score"] is None

        hie.submit_for_legal_review(participant["id"])
        executed = hie.execute_agreement(
            participant["id"],
            agreement_version="DURSA-2026.1",
            signed_at="2026-08-01T00:00:00Z",
            headers=make_hie_admin_headers(self.SIGNATORY),
        )
        assert executed["onboarding_status"] == "CONFORMANCE_TESTING"

        feed = get_success_data(
            hie.client.provision_data_feed(
                hie.admin,
                participant["id"],
                feed_type="CCDA",
                expected_participant_version=executed["version"],
            )
        )
        assert feed["status"] == "PROVISIONING"

        sample = hie.record_sample(
            feed["id"],
            period_start="2026-06-01T00:00:00Z",
            period_end="2026-07-01T00:00:00Z",
            messages_received=8000,
            messages_rejected=100,
            required_fields_missing_count=200,
            duplicate_count=50,
            timeliness_p95_seconds=250,
        )
        assert sample["data_feed_id"] == feed["id"]
        assert sample["reject_rate"] == pytest.approx(0.0125, abs=0.0001)

        monitored = hie.get_data_feed(feed["id"])
        assert monitored["status"] == "MONITORED"
        assert monitored["latest_reject_rate"] == pytest.approx(0.0125, abs=0.0001)
        assert monitored["sample_count"] == 1

        graded = hie.get_participant(participant["id"])
        assert graded["quality_score"] == pytest.approx(98.78, abs=0.001)
        assert graded["quality_grade"] == "A"

        scorecard = validate_success(
            hie.client.get_participant_scorecard(hie.admin, participant["id"]), 200
        )
        assert scorecard["participant_id"] == participant["id"]
        assert scorecard["samples_counted"] == 1
        assert scorecard["completeness_component"] == pytest.approx(97.50, abs=0.01)
        assert scorecard["rejection_component"] == pytest.approx(98.75, abs=0.01)
        assert scorecard["duplicate_component"] == pytest.approx(99.375, abs=0.001)
        assert scorecard["timeliness_component"] == pytest.approx(100, abs=0.01)
        assert scorecard["base_quality_score"] == pytest.approx(98.78, abs=0.001)
        assert scorecard["provisional_grade"] == "A"
        assert scorecard["penalty_points"] == 0
        assert scorecard["quality_score"] == pytest.approx(98.78, abs=0.001)
        assert scorecard["grade"] == "A"
