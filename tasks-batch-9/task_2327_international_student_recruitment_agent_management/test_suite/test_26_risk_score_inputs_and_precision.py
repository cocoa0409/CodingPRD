"""What the risk figures read, how they decay and where they round.

Only adjudicated incidents enter the sum.  The decay ladder is inclusive at both
of its edges.  The document-quality term is a repeating fraction, so the single
rounding step at the end is observable to the cent of a point.
"""

import pytest

from test_helpers import constants as C
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_risk_profile, assert_score_2dp
from test_helpers.test_users import COMPLIANCE


class TestOnlyConfirmedIncidentsScore:
    def test_an_open_and_a_dismissed_incident_are_invisible_to_both_figures(
        self, client
    ):
        """Three identical incidents, one adjudication, one severity weight.

        "Two risk figures are maintained on every agency from the same underlying
        data, and only incidents in `CONFIRMED` contribute — those in `REPORTED` or
        `DISMISSED` never do."

        "A dismissed incident makes no risk contribution: the agency's scores are
        recomputed and, absent any other change, come back unchanged."

        Design: Corner/calculations/risk_score_ignores_reported_and_dismissed_incidents
        """
        agency = fx.register_agency(
            client, legal_name="Filtered Input Agency", complete_diligence=False
        )
        confirmed = fx.file_incident(client, agency["id"])
        left_open = fx.file_incident(client, agency["id"])
        dismissed = fx.file_incident(client, agency["id"])

        fx.resolve_incident(client, confirmed["id"], C.RESOLUTION_CONFIRM)
        fx.resolve_incident(
            client,
            dismissed["id"],
            C.RESOLUTION_DISMISS,
            note="Complainant retracted",
        )

        assert_risk_profile(
            fx.read_risk_profile(client, agency["id"]),
            rolling_risk_score=30.00,
            lifetime_risk_score=30.00,
            lifetime_minus_rolling_delta=0.00,
            confirmed_incident_count=1,
            reviewed_document_count=0,
            confirmed_fraud_document_count=0,
            posture_band=C.POSTURE_GOOD_STANDING,
        )

        by_id = {row["id"]: row for row in fx.read_incidents(client, agency_id=agency["id"])}
        assert by_id[left_open["id"]]["status"] == C.INCIDENT_REPORTED
        assert by_id[dismissed["id"]]["status"] == C.INCIDENT_DISMISSED


class TestDecayLadderEdges:
    @pytest.fixture()
    def aged_incidents(self, client):
        """Three HIGH incidents aged exactly 90, exactly 180 and 181 days."""
        fx.set_clock(client, "2027-01-15T00:00:00Z", COMPLIANCE)
        agency = fx.register_agency(
            client, legal_name="Decay Curve Agency", complete_diligence=False
        )
        return {
            "agency_id": agency["id"],
            "age_90": fx.file_incident(client, agency["id"], occurred_on="2026-10-17"),
            "age_180": fx.file_incident(client, agency["id"], occurred_on="2026-07-19"),
            "age_181": fx.file_incident(client, agency["id"], occurred_on="2026-07-18"),
        }

    def test_each_decay_step_lands_on_its_own_inclusive_edge(
        self, client, aged_incidents
    ):
        """Full weight at ninety days, three quarters at a hundred and eighty.

        "Each such incident contributes its severity weight multiplied by a decay
        factor determined by that same age: full weight, a factor of 1.00, while
        the age is at most 90 days; three quarters, a factor of 0.75, while the age
        is more than 90 days and at most 180 days; and half, a factor of 0.50, for
        anything older within the 365-day window."

        "After any risk recompute, a rolling figure at or above 85.00 targets
        `SUSPENDED`, at or above 65.00 but below 85.00 targets `PROBATION`, and at
        or above 40.00 but below 65.00 targets `WATCH`; below 40.00 the standing is
        left as it is."

        Design: Corner/calculations/risk_decay_boundaries_at_ninety_and_one_hundred_eighty_days
        """
        env = aged_incidents

        first = fx.resolve_incident(client, env["age_90"]["id"], C.RESOLUTION_CONFIRM)
        assert first["status"] == C.INCIDENT_CONFIRMED
        after_first = fx.read_agency(client, env["agency_id"])
        assert_score_2dp(after_first["rolling_risk_score"], 30.00, "age 90 rolling")
        assert after_first["compliance_posture"] == C.POSTURE_GOOD_STANDING

        fx.resolve_incident(client, env["age_180"]["id"], C.RESOLUTION_CONFIRM)
        after_second = fx.read_agency(client, env["agency_id"])
        assert_score_2dp(after_second["rolling_risk_score"], 52.50, "age 180 rolling")
        assert after_second["compliance_posture"] == C.POSTURE_WATCH

        fx.resolve_incident(client, env["age_181"]["id"], C.RESOLUTION_CONFIRM)
        after_third = fx.read_agency(client, env["agency_id"])
        assert_score_2dp(after_third["rolling_risk_score"], 67.50, "age 181 rolling")
        assert after_third["compliance_posture"] == C.POSTURE_PROBATION

    def test_the_undecayed_variant_ignores_the_ladder_and_the_band_ignores_it(
        self, client, aged_incidents
    ):
        """Ninety points of raw severity, sixty-seven and a half after decay.

        "`lifetime_risk_score` is the undecayed cumulative figure. It considers
        every confirmed incident with no window at all and applies no decay, so
        each contributes its full severity weight"

        "`posture_band`, the band the rolling figure currently falls in"

        Design: Corner/calculations/risk_decay_boundaries_at_ninety_and_one_hundred_eighty_days
        """
        env = aged_incidents
        for key in ("age_90", "age_180", "age_181"):
            fx.resolve_incident(client, env[key]["id"], C.RESOLUTION_CONFIRM)

        assert_risk_profile(
            fx.read_risk_profile(client, env["agency_id"]),
            rolling_risk_score=67.50,
            lifetime_risk_score=90.00,
            lifetime_minus_rolling_delta=22.50,
            confirmed_incident_count=3,
            reviewed_document_count=0,
            confirmed_fraud_document_count=0,
            posture_band=C.POSTURE_PROBATION,
        )


class TestFraudTermRoundsOnce:
    @pytest.fixture()
    def one_fraud_in_three_reviews(self, client):
        """Two clean verified documents and one confirmed forgery on one file."""
        agency = fx.register_agency(
            client, legal_name="Rounding Agency", complete_diligence=False
        )
        program = fx.create_program(client)
        application = fx.create_application(
            client, agency["id"], program["id"], student_ref="STU-001"
        )

        clean_passport = fx.upload_document(
            client,
            agency["id"],
            application["id"],
            C.DOC_PASSPORT,
            "hash-r-001",
            "MEA India",
        )
        clean_english = fx.upload_document(
            client,
            agency["id"],
            application["id"],
            C.DOC_ENGLISH_TEST,
            "hash-r-002",
            "IELTS",
        )
        forged_finance = fx.upload_document(
            client,
            agency["id"],
            application["id"],
            C.DOC_FINANCIAL_PROOF,
            "hash-r-003",
            "Unknown Bank",
            [
                C.SIGNAL_ISSUER_UNVERIFIED,
                C.SIGNAL_TRANSCRIPT_ANOMALY,
                C.SIGNAL_TRANSLATION_MISMATCH,
                C.SIGNAL_DATE_INCONSISTENCY,
            ],
        )

        fx.verify_document(client, clean_passport["id"], C.VERIFICATION_VERIFIED)
        fx.verify_document(client, clean_english["id"], C.VERIFICATION_VERIFIED)

        return {
            "agency_id": agency["id"],
            "application_id": application["id"],
            "forged": forged_finance,
        }

    def test_four_declared_signals_auto_flag_the_document_at_upload(
        self, client, one_fraud_in_three_reviews
    ):
        """Twenty-five plus twenty plus fifteen plus ten clears the threshold.

        "`fraud_index` is then the sum of the weights of the distinct signals in
        `fraud_signals`, capped at 100. `HASH_DUPLICATE` weighs 45,
        `ISSUER_UNVERIFIED` weighs 25, `TRANSCRIPT_ANOMALY` weighs 20,
        `TRANSLATION_MISMATCH` weighs 15, and `DATE_INCONSISTENCY` weighs 10"

        "A document whose index reaches 60 is auto-flagged at upload: it lands in
        `verification_state` `FLAGGED` rather than `PENDING`, and the owning
        application's `integrity_hold` is set to true"

        Design: Corner/calculations/risk_score_fraud_rate_rounds_to_two_decimals
        """
        env = one_fraud_in_three_reviews

        assert env["forged"]["fraud_index"] == 70
        assert env["forged"]["verification_state"] == C.VERIFICATION_FLAGGED

    def test_one_fraud_in_three_reviews_scores_exactly_forty_three_point_three_three(
        self, client, one_fraud_in_three_reviews
    ):
        """Forty times one third is a repeating decimal rounded once, at the end.

        "otherwise is `confirmed_fraud_document_count` divided by
        `reviewed_document_count`, where the reviewed count spans documents on all
        of that agency's applications whose `verification_state` is `VERIFIED`,
        `FLAGGED`, `CONFIRMED_FRAUD` or `CLEARED`, the fraud count spans those in
        `CONFIRMED_FRAUD`, and no date window applies to either. Forty points are
        allocated to that term."

        "Those contributions are summed, forty multiplied by the fraud rate is
        added, the total is rounded half up to two decimal places once, and the
        result is clamped to a maximum of 100.00."

        Design: Corner/calculations/risk_score_fraud_rate_rounds_to_two_decimals
        """
        env = one_fraud_in_three_reviews

        confirmed = fx.verify_document(
            client,
            env["forged"]["id"],
            C.VERIFICATION_CONFIRMED_FRAUD,
            note="Bank confirms the letter is fabricated",
        )
        assert confirmed["verification_state"] == C.VERIFICATION_CONFIRMED_FRAUD

        incidents = fx.read_incidents(client, agency_id=env["agency_id"])
        assert len(incidents) == 1
        assert incidents[0]["category"] == C.INCIDENT_DOCUMENT_FRAUD
        assert incidents[0]["severity"] == C.SEVERITY_HIGH
        assert incidents[0]["status"] == C.INCIDENT_CONFIRMED
        assert incidents[0]["occurred_on"] == C.DEFAULT_CLOCK_DATE

        assert_risk_profile(
            fx.read_risk_profile(client, env["agency_id"]),
            rolling_risk_score=43.33,
            lifetime_risk_score=43.33,
            lifetime_minus_rolling_delta=0.00,
            confirmed_incident_count=1,
            reviewed_document_count=3,
            confirmed_fraud_document_count=1,
            posture_band=C.POSTURE_WATCH,
        )

        assert (
            fx.read_agency(client, env["agency_id"])["compliance_posture"]
            == C.POSTURE_WATCH
        )
        assert (
            fx.read_application(client, env["application_id"])["integrity_hold"] is True
        )
