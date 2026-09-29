"""Lifecycles that are not a single forward march.

An emergency session carries two independent axes on one row; a data feed travels
a cycle and drags the participant's grade with it in both directions.
"""

import pytest

from prd_bench_local_runner.testing import validate_success

from test_helpers.fixtures import HieHarness
from test_helpers.test_users import make_clinician_headers, make_privacy_officer_headers

EMERGENCY_JUSTIFICATION = (
    "Unconscious trauma patient in resuscitation bay 3 with no identification "
    "and no responsive next of kin."
)
JUSTIFIED_NOTE = (
    "Emergency access was clinically appropriate and proportionate to the presenting condition."
)


class TestBreakGlassParallelAxes:
    """`session_status` and `review_status` never gate one another."""

    @staticmethod
    def _session(hie: HieHarness):
        hie.activate_threshold_config(config_label="REF-PROB-B")
        participant = hie.certified_participant(
            legal_name="Harborview Medical Center",
            declared_annual_patient_volume=240000,
            primary_contact_email="hie@harborview.example",
        )
        record = hie.contribute_record(
            participant["id"],
            headers=hie.admin,
            source_mrn="H-3001",
            given_name="Dana",
            family_name="Okafor",
            birth_date="1988-09-14",
            sex="F",
            ssn_last4="7781",
            postal_code="98104",
            phone_digits="2065550133",
        )
        session = hie.open_break_glass(
            record["cluster_id"],
            participant["id"],
            justification_text=EMERGENCY_JUSTIFICATION,
            clinician_user_id="clin-d-1",
        )
        return participant, session

    def test_closing_the_session_leaves_the_review_axis_untouched(self, hie: HieHarness):
        """Closure moves only `session_status`; the review is still waiting.

        PRD 3.8: "Closure recomputes `disclosed_record_count` as the sum of
        `disclosed_record_count` over every locator query citing this session,
        recomputes `disclosed_sensitive_count` as the count of audit entries under
        this session whose `action` is `BREAK_GLASS_DISCLOSED` and whose
        `sensitive_category_hit` is non-empty, leaves `review_status` untouched, and
        increments `version` by 1."

        Design: Difficulty/non_linear_state_machine/break_glass_session_and_review_dimensions_advance_independently
        """
        _, session = self._session(hie)
        assert session["opened_at"].startswith("2026-08-01T00:00:00")
        assert session["expires_at"].startswith("2026-08-01T04:00:00")
        assert session["session_status"] == "OPEN"
        assert session["review_status"] == "PENDING_REVIEW"

        closed = validate_success(
            hie.client.close_break_glass_access(
                make_clinician_headers("clin-d-1"), session["id"]
            ),
            200,
        )
        assert closed["session_status"] == "CLOSED"
        assert closed["review_status"] == "PENDING_REVIEW"
        assert closed["version"] == session["version"] + 1

    def test_the_review_axis_advances_to_justified_while_the_session_stays_closed(
        self, hie: HieHarness
    ):
        """A claim and a JUSTIFIED decision run their course on a closed session.

        PRD 3.8: "A review may be claimed and decided while the session is still
        `OPEN`, and a session may expire while its review is `UNDER_REVIEW`."

        Design: Difficulty/non_linear_state_machine/break_glass_session_and_review_dimensions_advance_independently
        """
        participant, session = self._session(hie)
        clinician_headers = make_clinician_headers("clin-d-1")
        validate_success(
            hie.client.close_break_glass_access(clinician_headers, session["id"]), 200
        )

        reviewer = make_privacy_officer_headers("privacy-reviewer-1")
        claimed = validate_success(
            hie.client.claim_break_glass_review(reviewer, session["id"]), 200
        )
        assert claimed["session_status"] == "CLOSED"
        assert claimed["review_status"] == "UNDER_REVIEW"
        assert claimed["review_claimed_by_user_id"] == "privacy-reviewer-1"

        decided = validate_success(
            hie.client.decide_break_glass_review(
                reviewer, session["id"], outcome="JUSTIFIED", review_note=JUSTIFIED_NOTE
            ),
            200,
        )
        assert decided["session_status"] == "CLOSED"
        assert decided["review_status"] == "JUSTIFIED"
        assert decided["sanction_points_awarded"] == 0

        refreshed = hie.get_participant(participant["id"])
        assert refreshed["sanction_points_active"] == 0
        assert refreshed["onboarding_status"] == "CERTIFIED"


class TestDataFeedMonitoringCycle:
    """One feed row travels PROVISIONING, MONITORED, DEGRADED, SUSPENDED, MONITORED."""

    CLEAN_SAMPLE = {
        "period_start": "2026-06-01T00:00:00Z",
        "period_end": "2026-07-01T00:00:00Z",
        "messages_received": 10000,
        "messages_rejected": 300,
        "required_fields_missing_count": 500,
        "duplicate_count": 100,
        "timeliness_p95_seconds": 240,
    }
    BREACHING_SAMPLE = {
        "period_start": "2026-07-01T00:00:00Z",
        "period_end": "2026-07-15T00:00:00Z",
        "messages_received": 5000,
        "messages_rejected": 400,
        "required_fields_missing_count": 100,
        "duplicate_count": 50,
        "timeliness_p95_seconds": 200,
    }

    @staticmethod
    def _participant_with_feed(hie: HieHarness):
        participant = hie.participant_in_conformance_testing(
            legal_name="Riverbend Laboratory",
            org_type="LAB",
            declared_annual_patient_volume=48000,
            primary_contact_email="feeds@riverbend.example",
        )
        feed = hie.provision_feed(participant["id"], feed_type="CCDA")
        assert feed["status"] == "PROVISIONING"
        return participant, feed

    def test_a_clean_then_breaching_sample_walk_the_feed_into_degraded(self, hie: HieHarness):
        """The first sample lifts the feed out of provisioning; the second degrades it.

        PRD 3.9: "Thereafter an accepted sample whose `reject_rate` is strictly
        greater than 0.0500 drives `MONITORED → DEGRADED`, setting `status_reason` to
        `REJECT_RATE_BREACH`; an accepted sample whose `reject_rate` is at or below
        0.0500 drives `DEGRADED → MONITORED`, clearing `status_reason`."

        Design: Difficulty/non_linear_state_machine/data_feed_cycles_monitored_degraded_suspended_and_back_to_monitored
        """
        _, feed = self._participant_with_feed(hie)

        hie.record_sample(feed["id"], **self.CLEAN_SAMPLE)
        after_first = hie.get_data_feed(feed["id"])
        assert after_first["status"] == "MONITORED"
        assert after_first["latest_reject_rate"] == pytest.approx(0.0300, abs=0.0001)

        hie.record_sample(feed["id"], **self.BREACHING_SAMPLE)
        after_second = hie.get_data_feed(feed["id"])
        assert after_second["status"] == "DEGRADED"
        assert after_second["latest_reject_rate"] == pytest.approx(0.0800, abs=0.0001)
        assert after_second["sample_count"] == 2

    def test_suspension_ungrades_the_participant_and_restoration_returns_the_same_score(
        self, hie: HieHarness
    ):
        """Leaving and re-entering the qualifying statuses is exactly reversible.

        PRD 3.9: "Restoring a suspended feed drives `SUSPENDED → MONITORED`, clears
        `status_reason`, and re-runs the scorecard with those samples back in;
        restoration requires that the owning participant's `onboarding_status` is
        not `SUSPENDED`, since a suspended organization cannot have a live pipe."

        Design: Difficulty/non_linear_state_machine/data_feed_cycles_monitored_degraded_suspended_and_back_to_monitored
        """
        participant, feed = self._participant_with_feed(hie)
        hie.record_sample(feed["id"], **self.CLEAN_SAMPLE)
        hie.record_sample(feed["id"], **self.BREACHING_SAMPLE)

        suspended = validate_success(
            hie.client.transition_data_feed_status(
                hie.admin,
                feed["id"],
                action="SUSPEND",
                reason="Interface engine cutover requested by the participant",
            ),
            200,
        )
        assert suspended["status"] == "SUSPENDED"

        while_suspended = hie.get_scorecard(participant["id"])
        assert while_suspended["samples_counted"] == 0
        assert while_suspended["quality_score"] is None
        assert while_suspended["grade"] == "UNGRADED"

        restored = validate_success(
            hie.client.transition_data_feed_status(
                hie.admin,
                feed["id"],
                action="RESTORE",
                reason="Interface engine cutover complete",
            ),
            200,
        )
        assert restored["status"] == "MONITORED"

        after_restore = hie.get_scorecard(participant["id"])
        assert after_restore["samples_counted"] == 2
        assert after_restore["quality_score"] == pytest.approx(97.25, abs=0.01)
        assert after_restore["grade"] == "A"

        refreshed = hie.get_participant(participant["id"])
        assert refreshed["quality_score"] == pytest.approx(97.25, abs=0.01)
        assert refreshed["quality_grade"] == "A"
