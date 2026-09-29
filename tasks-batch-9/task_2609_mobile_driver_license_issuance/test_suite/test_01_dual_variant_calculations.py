"""Two computations over one input set that must not be allowed to collapse.

Each family here reads both variants side by side out of a single response, so
an implementation that computes one number and reports it twice is caught by the
difference rather than by either value alone.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import assert_field_values
from test_helpers.fixtures import (
    adjudicate_session,
    append_evidence,
    create_holder,
    create_presentation_ready_world,
    create_profile,
    disclose,
    grant_consent,
    open_presentation_session,
    open_proofing_session,
    set_clock,
    submit_session,
)
from test_helpers.test_users import (
    ADJUDICATOR,
    ADMIN,
    PRIVACY_AUDITOR,
    make_verifier_operator_headers,
)


class TestStrictAdjudicationScoreDivergesFromOptimisticPreview:
    """Recency and the resubmission penalty move only the strict variant."""

    @staticmethod
    def _returned_then_resubmitted_session(api):
        """A session whose latest document scan is WEAK and which has been
        submitted twice."""
        create_profile(api)
        holder = create_holder(api)
        session = open_proofing_session(api, holder["id"])
        append_evidence(
            api,
            session["id"],
            [
                {
                    "evidence_type": "DOCUMENT_SCAN",
                    "quality": "STRONG",
                    "captured_at": "2026-07-10T09:00:00Z",
                    "source_reference": "scan-strong-1",
                },
                {
                    "evidence_type": "BIOMETRIC_MATCH",
                    "quality": "FAIR",
                    "captured_at": "2026-07-12T09:00:00Z",
                    "source_reference": "bio-fair-1",
                },
            ],
        )
        submit_session(api, session["id"])
        adjudicate_session(
            api,
            session["id"],
            "RETURN",
            "document scan predates the address of record",
        )
        append_evidence(
            api,
            session["id"],
            [
                {
                    "evidence_type": "DOCUMENT_SCAN",
                    "quality": "WEAK",
                    "captured_at": "2026-07-20T09:00:00Z",
                    "source_reference": "scan-weak-2",
                }
            ],
        )
        submit_session(api, session["id"])
        return session

    def test_the_two_variants_land_two_assurance_bands_apart(self, api):
        """The optimistic variant takes the strongest scan and skips the penalty;
        the strict variant takes the latest scan and pays it.

        PRD 3.2: "The advisory variant is optimistic instead: for each evidence
        type present it takes the **strongest** item of that type regardless of
        when it was captured, sums those, and applies no repeat-attempt penalty
        whatsoever. For an identical evidence set the optimistic score is
        therefore never below the strict score, and is strictly greater whenever
        a weaker item of some type was captured later than a stronger one, or
        whenever the session has been submitted more than once."

        Design: Difficulty/dual_variant_calc/proofing_strict_latest_evidence_diverges_from_optimistic_preview
        """
        session = self._returned_then_resubmitted_session(api)

        preview = validate_success(
            api.get_assurance_preview(session["id"], ADJUDICATOR)
        )
        assert_field_values(
            preview,
            {
                "preview_score": 370,
                "preview_assurance_level": "IAL1_5",
                "adjudication_score": 155,
                "adjudication_assurance_level": "IAL1",
            },
        )
        assert preview["preview_score"] - preview["adjudication_score"] == 215

    def test_the_preview_reports_both_levers_and_changes_nothing(self, api):
        """The preview exposes the submission count and the distinct type count
        that drive the gap, and leaves the session untouched.

        PRD 3.2: "A read-only preview capability returns both computations side
        by side so the agent can see the gap before submitting: `preview_score`
        with its mapped `preview_assurance_level` from the optimistic variant,
        `adjudication_score` with its mapped `adjudication_assurance_level` from
        the strict variant, plus the session's current `submission_count` and the
        `evidence_type_count` - the number of distinct evidence types present.
        The preview mutates nothing."

        Design: Difficulty/dual_variant_calc/proofing_strict_latest_evidence_diverges_from_optimistic_preview
        """
        session = self._returned_then_resubmitted_session(api)
        before = validate_success(api.get_proofing_session(session["id"], ADJUDICATOR))

        preview = validate_success(
            api.get_assurance_preview(session["id"], ADJUDICATOR)
        )
        assert_field_values(
            preview, {"submission_count": 2, "evidence_type_count": 2}
        )

        after = validate_success(api.get_proofing_session(session["id"], ADJUDICATOR))
        assert_field_values(
            after,
            {
                "state": before["state"],
                "submission_count": before["submission_count"],
                "version": before["version"],
            },
        )


class TestRollingWindowExposureDivergesFromSinceAttestation:
    """The same log, two windows: one entry falls out of the shorter window."""

    OVER_ASKED = ["family_name", "age_over_21", "birth_date", "address"]

    @classmethod
    def _verifier_with_two_logged_disclosures(cls, api):
        world = create_presentation_ready_world(
            api,
            verifier_overrides={
                "organization_name": "Prairie Cellars",
                "category": "AGE_RESTRICTED_RETAIL",
                "purpose_scope": ["family_name", "age_over_21"],
                "retention_ceiling_days": 30,
            },
            reader_app_overrides={
                "app_identifier": "till-reader",
                "certificate_serial": "SER-A1",
                "requested_elements": cls.OVER_ASKED,
                "base_rate_cents": 30,
            },
        )
        operator = make_verifier_operator_headers(world["verifier"]["id"])
        validate_success(
            api.attest_retention(
                world["verifier"]["id"], {"attested_max_retention_days": 10}, operator
            )
        )

        set_clock(api, "2026-08-02T00:00:00Z")
        first = open_presentation_session(
            api, world, requested_elements=cls.OVER_ASKED, retention_days=5
        )
        grant_consent(api, first["id"], world["holder"]["id"])
        disclose(api, first["id"], world["verifier"]["id"])

        set_clock(api, "2026-09-15T00:00:00Z")
        second = open_presentation_session(
            api,
            world,
            requested_elements=["family_name", "age_over_21", "address"],
            retention_days=5,
        )
        grant_consent(api, second["id"], world["holder"]["id"])
        world["second_session"] = second
        return world

    def test_the_rolling_window_index_is_a_strict_subset_of_the_wider_window(self, api):
        """The 44-day-old entry is outside the 30-day rolling window but inside
        the since-attestation window, so the two indices disagree.

        PRD 3.9: "The **rolling-window** variant counts entries whose
        `recorded_at` falls at or after the current logical instant less 30 days
        and at or before the current logical instant, with the lower bound
        inclusive. The **since-last-attestation** variant counts entries whose
        `recorded_at` is at or after the verifier's `last_attestation_at` as it
        stood **before** the attestation being processed"

        Design: Difficulty/dual_variant_calc/verifier_exposure_rolling_window_diverges_from_since_attestation
        """
        world = self._verifier_with_two_logged_disclosures(api)
        disclose(api, world["second_session"]["id"], world["verifier"]["id"])

        report = validate_success(
            api.get_exposure_index(world["verifier"]["id"], PRIVACY_AUDITOR)
        )
        assert_field_values(
            report,
            {
                "rolling_window_index": 6,
                "rolling_window_entry_count": 1,
                "since_last_attestation_index": 18,
                "since_attestation_entry_count": 2,
            },
        )

    def test_the_disclosure_writes_the_rolling_variant_and_trips_no_threshold(self, api):
        """The over-ask is scored on the second disclosure and the value written
        onto the verifier is the rolling-window one, well under probation.

        PRD 3.9: "Both variants write `exposure_index` when they run for real,
        and both apply the same **threshold triggers immediately after the index
        is written**. ... Otherwise an index of 60 or more drives an `APPROVED`
        verifier to `PROBATION` and increments `probation_strike_count` by 1. ...
        The rolling-window variant runs on every disclosure, as described in
        3.8."

        Design: Difficulty/dual_variant_calc/verifier_exposure_rolling_window_diverges_from_since_attestation
        """
        world = self._verifier_with_two_logged_disclosures(api)

        completed = disclose(
            api, world["second_session"]["id"], world["verifier"]["id"]
        )
        assert_field_values(
            completed,
            {
                "state": "COMPLETED",
                "excess_element_count": 1,
                "disclosed_element_count": 2,
            },
        )

        verifier = validate_success(api.get_verifier(world["verifier"]["id"], ADMIN))
        assert_field_values(
            verifier, {"exposure_index": 6, "trust_status": "APPROVED"}
        )
