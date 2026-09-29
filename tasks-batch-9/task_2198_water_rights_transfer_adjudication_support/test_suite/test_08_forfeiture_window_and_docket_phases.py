"""The forfeiture lookback window and the docket-phase gate on examination.

PRD §3.2: "The scoring window is a closed ten-year band ending with the year
*before* the calendar year of the logical clock, taken in UTC; the current calendar
year is deliberately excluded because its reporting year is not yet complete."
"""
import pytest
from test_helpers import ApiErrorId, api_client, get_success_data, validate_error
from test_helpers.fixtures import (
    ADJUDICATOR,
    ANALYST,
    certify_study,
    create_study,
    file_claim,
    open_docket,
    read_claim,
    read_docket,
    read_right,
    set_clock,
    setup_base_right,
)

CLOCK = "2026-06-15T00:00:00Z"


class TestFiveConsecutiveNonUseYearsIsTheForfeitureBoundary:
    """PRD §3.2 — "Statutory forfeiture eligibility is that boolean, and it is
    inclusive: exactly five consecutive non-use years is eligible, four is not."

    With the logical clock at 2026-06-15 the window is the closed band
    2016 through 2025. Two rights sit either side of the boundary. One reported
    300.000 AF under a meter in both 2020 and 2025, leaving a longest run of four
    idle years, 2021 through 2024. The other reported only in 2020, plus a 2026
    reading that the window excludes, leaving a run of five, 2021 through 2025.
    """

    def _four_year_run(self):
        return setup_base_right(clock=CLOCK, use_years=(2020, 2025))

    def _five_year_run(self):
        bundle = setup_base_right(clock=CLOCK, use_years=(2020, 2026))
        study = get_success_data(create_study(bundle["right"]["id"], 2020, 2020))
        certify_study(study["id"], bundle["right"]["id"])
        bundle["right"] = read_right(bundle["right"]["id"])
        return bundle

    def _assessment(self, right_id):
        return get_success_data(
            api_client.get_forfeiture_assessment(right_id, ANALYST)
        )

    def test_four_consecutive_idle_years_are_not_yet_eligible(self):
        """PRD §3.2: "`consecutive_nonuse_years` is the length of the longest
        unbroken run of non-use years inside the window."

        PRD §3.2: "The raw score is then: nine points for each consecutive non-use
        year, plus twenty-five points multiplied by the unverified ratio, plus thirty
        points multiplied by one minus utilization ... less a flat ten-point credit
        when any record in the window carries a `verification_source` of `METER`." Four idle years give
        36.00, both records are metered so the unverified component is 0.00, a mean
        of 300.000 against 400.00 authorized gives an underuse component of 7.50,
        and the meter credit takes 10.00 off: 33.50, which PRD §3.2 bands `LOW`
        because "anything below reads `LOW`".

        Design: Difficulty/boundary_precision_check/forfeiture_five_year_boundary
        """
        bundle = self._four_year_run()

        assessment = self._assessment(bundle["right"]["id"])

        assert assessment["lookback_start_year"] == 2016
        assert assessment["lookback_end_year"] == 2025
        assert assessment["nonuse_year_count"] == 8
        assert assessment["consecutive_nonuse_years"] == 4
        assert assessment["nonuse_component"] == pytest.approx(36.00, abs=0.01)
        assert assessment["unverified_component"] == pytest.approx(0.00, abs=0.01)
        assert assessment["underuse_component"] == pytest.approx(7.50, abs=0.01)
        assert assessment["suspended_penalty"] == pytest.approx(0.00, abs=0.01)
        assert assessment["meter_credit"] == pytest.approx(10.00, abs=0.01)
        assert assessment["forfeiture_risk_score"] == pytest.approx(33.50, abs=0.01)
        assert assessment["forfeiture_risk_band"] == "LOW"
        assert assessment["forfeiture_eligible"] is False
        assert read_right(bundle["right"]["id"])["consecutive_nonuse_years"] == 4

    def test_declaration_is_refused_one_year_short_of_the_statute(self):
        """PRD §3.2: "Declaring forfeiture — analyst or adjudicator work,
        accompanied by a `finding_note` — is rejected with
        `ERR_FORFEITURE_NOT_ELIGIBLE` (HTTP 422) when `consecutive_nonuse_years`
        falls short of five."

        The right therefore stays exactly as it was, `ACTIVE` and with its ledger
        intact.

        Design: Difficulty/boundary_precision_check/forfeiture_five_year_boundary
        """
        bundle = self._four_year_run()

        response = api_client.declare_forfeiture(
            bundle["right"]["id"], "Non-use asserted over the last decade.", ANALYST
        )

        validate_error(
            response,
            ApiErrorId.ERR_FORFEITURE_NOT_ELIGIBLE.value,
            expected_status=422,
        )
        right = read_right(bundle["right"]["id"])
        assert right["status"] == "ACTIVE"
        assert right["consecutive_nonuse_years"] == 4

    def test_the_current_calendar_year_cannot_break_the_run(self):
        """PRD §3.2: "the current calendar year is deliberately excluded because
        its reporting year is not yet complete."

        A 2026 reading exists on this right, but 2026 falls outside the
        2016-through-2025 band, so the run 2021 through 2025 is unbroken at five
        years and scores nine points apiece for 45.00 — a total of 42.50, which PRD
        §3.2 bands `ELEVATED` because "a score from 40.00 up to but not including
        70.00 reads `ELEVATED`".

        Design: Difficulty/boundary_precision_check/forfeiture_five_year_boundary
        """
        bundle = self._five_year_run()

        assessment = self._assessment(bundle["right"]["id"])

        assert assessment["lookback_start_year"] == 2016
        assert assessment["lookback_end_year"] == 2025
        assert assessment["nonuse_year_count"] == 9
        assert assessment["consecutive_nonuse_years"] == 5
        assert assessment["nonuse_component"] == pytest.approx(45.00, abs=0.01)
        assert assessment["underuse_component"] == pytest.approx(7.50, abs=0.01)
        assert assessment["meter_credit"] == pytest.approx(10.00, abs=0.01)
        assert assessment["forfeiture_risk_score"] == pytest.approx(42.50, abs=0.01)
        assert assessment["forfeiture_risk_band"] == "ELEVATED"
        assert assessment["forfeiture_eligible"] is True

    def test_five_consecutive_idle_years_forfeit_the_whole_ledger(self):
        """PRD §3.2: "The first link zeroes all four volume buckets —
        `certified_hcu_af`, `encumbered_af`, `transferred_away_af` and
        `transferable_af` all become 0.00 — and bumps the right's `version`."

        The single qualifying 2020 record certified 165.75 AF onto this right; the
        declaration wipes all of it and `FORFEITED` is terminal and sticky.

        Design: Difficulty/boundary_precision_check/forfeiture_five_year_boundary
        """
        bundle = self._five_year_run()
        assert bundle["right"]["certified_hcu_af"] == pytest.approx(165.75, abs=0.01)
        assert bundle["right"]["transferable_af"] == pytest.approx(165.75, abs=0.01)

        right = get_success_data(
            api_client.declare_forfeiture(
                bundle["right"]["id"],
                "Five consecutive years of non-use established on the record.",
                ANALYST,
            )
        )

        assert right["status"] == "FORFEITED"
        assert right["certified_hcu_af"] == pytest.approx(0.00, abs=0.01)
        assert right["encumbered_af"] == pytest.approx(0.00, abs=0.01)
        assert right["transferred_away_af"] == pytest.approx(0.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(0.00, abs=0.01)


class TestExaminationIsGatedByTheDocketPhase:
    """PRD §3.10 — "Examination is adjudicator-only and valid only while the docket
    reads `EXAMINATION`."

    One docket `CV-2026-0007` in basin `ALDER-BASIN` closes filing at
    2026-04-01 and holds a single claim asserting 180.00 AF with an 1901 priority
    date. The claim cannot be examined until its parent docket has moved, and the
    docket cannot move until the filing deadline arrives.
    """

    DEADLINE = "2026-04-01T00:00:00Z"

    def _docket_with_claim(self):
        bundle = setup_base_right(clock="2026-03-01T00:00:00Z")
        bundle["docket"] = open_docket(
            self.DEADLINE, basin_code="ALDER-BASIN", docket_number="CV-2026-0007"
        )
        bundle["claim"] = file_claim(
            bundle["docket"]["id"],
            bundle["right"]["id"],
            "1901-05-01T00:00:00Z",
            180.00,
        )
        bundle["docket"] = read_docket(bundle["docket"]["id"])
        return bundle

    def _examine(self, claim_id):
        return api_client.examine_adjudication_claim(
            claim_id, 150.00, "Historic diversion records reviewed.", ADJUDICATOR
        )

    def test_examination_is_refused_while_the_docket_still_takes_claims(self):
        """PRD §3.10: "Examination is adjudicator-only and valid only while the
        docket reads `EXAMINATION`."

        The docket is still `OPEN_FOR_CLAIMS`, so the operation fails on the parent
        entity's phase with `ERR_DOCKET_PHASE_INVALID` even though the claim itself
        is `FILED` and the recommendation is a perfectly valid 150.00 against a
        180.00 claim. Neither of the claim's two dimensions moves.

        Design: Difficulty/cross_entity_state_dependency/claim_examination_gated_by_docket_phase
        """
        bundle = self._docket_with_claim()
        assert bundle["docket"]["phase"] == "OPEN_FOR_CLAIMS"
        assert bundle["claim"]["filing_status"] == "FILED"

        response = self._examine(bundle["claim"]["id"])

        validate_error(
            response, ApiErrorId.ERR_DOCKET_PHASE_INVALID.value, expected_status=409
        )
        claim = read_claim(bundle["claim"]["id"])
        assert claim["filing_status"] == "FILED"
        assert claim["verification_status"] == "UNVERIFIED"
        assert claim["examiner_recommended_af"] is None
        assert read_docket(bundle["docket"]["id"])["phase"] == "OPEN_FOR_CLAIMS"

    def test_the_docket_cannot_advance_before_the_filing_deadline(self):
        """PRD §3.10: "Advancing to `EXAMINATION` requires two things at once: the
        logical clock must have reached `claim_filing_deadline`, a temporal failure
        reported as `ERR_WINDOW_STILL_OPEN` (409), and the docket must hold at least
        one claim".

        At a clock of 2026-03-01 against a 2026-04-01 deadline the docket is
        genuinely early, so the phase does not move and the claim it holds is still
        counted.

        Design: Difficulty/cross_entity_state_dependency/claim_examination_gated_by_docket_phase
        """
        bundle = self._docket_with_claim()

        response = api_client.advance_docket_phase(
            bundle["docket"]["id"], "EXAMINATION", ADJUDICATOR
        )

        validate_error(
            response, ApiErrorId.ERR_WINDOW_STILL_OPEN.value, expected_status=409
        )
        docket = read_docket(bundle["docket"]["id"])
        assert docket["phase"] == "OPEN_FOR_CLAIMS"
        assert docket["claim_count"] == 1

    def test_reaching_the_deadline_advances_the_docket_and_unblocks_examination(self):
        """PRD §3.10: "Reaching `EXAMINATION` closes filing permanently".

        The clock is set to exactly the 2026-04-01 deadline instant, which PRD
        §3.10 treats as reached, so the docket advances. The identical examination
        that was refused a moment earlier now succeeds: PRD §3.10 — "The claim moves
        `FILED → EXAMINED` and `verification_status` is left untouched." No docket
        counter records a decree yet.

        Design: Difficulty/cross_entity_state_dependency/claim_examination_gated_by_docket_phase
        """
        bundle = self._docket_with_claim()
        self._examine(bundle["claim"]["id"])
        set_clock(self.DEADLINE)

        docket = get_success_data(
            api_client.advance_docket_phase(
                bundle["docket"]["id"], "EXAMINATION", ADJUDICATOR
            )
        )
        claim = get_success_data(self._examine(bundle["claim"]["id"]))

        assert docket["phase"] == "EXAMINATION"
        assert claim["filing_status"] == "EXAMINED"
        assert claim["examiner_recommended_af"] == pytest.approx(150.00, abs=0.01)
        assert claim["claimed_af"] == pytest.approx(180.00, abs=0.01)
        assert claim["verification_status"] == "UNVERIFIED"
        assert claim["decreed_af"] is None
        final = read_docket(bundle["docket"]["id"])
        assert final["claim_count"] == 1
        assert final["decreed_claim_count"] == 0
        assert final["total_decreed_af"] == pytest.approx(0.00, abs=0.01)
