"""Thresholds tested at the exact rung and one unit either side: the ninety
percent utilisation gate, the empty-set edge of release coverage, and the
five-million-cent welfare band floor.
"""

from test_helpers import (
    NO_PSYCH_SCREENING,
    TEST_USERS,
    ApiErrorId,
    assert_money,
    collect_release,
    get_production,
    get_shoot_block,
    setup_active_welfare_protocol,
    setup_cleared_applicant,
    setup_docusoap_production,
    setup_executed_agreement,
    setup_location,
    setup_planned_welfare_protocol,
    setup_production,
    setup_published_casting_call,
    setup_rolling_shoot_block,
    validate_error,
    validate_success,
)

PA = TEST_USERS["production_admin_headers"]

FOUR_EPISODE_DOCUSOAP = {
    "format_type": "DOCUSOAP",
    "jurisdiction_code": "CA",
    "episode_order": 4,
    "stipend_pool_cents": 10_000_000,
    "welfare_budget_cents": 10_000_000,
    "minor_participant_cap": 0,
}

SEASON_COVERAGE = {
    "coverage_start_utc": "2026-09-15T00:00:00Z",
    "coverage_end_utc": "2026-12-15T00:00:00Z",
}

PLAIN_TERMS = {
    "exclusivity_window_days": 0,
    "confidentiality_tier": "STANDARD",
    "depiction_rights_scope": "FULL",
    "stipend_structure": "PER_EPISODE",
    "episodes_committed": 4,
    "press_appearance_obligation_count": 0,
    "reunion_obligation": False,
}


class TestStipendUtilisationAtNinetyPercent:
    """The utilisation gate is an integer comparison, so a four-cent shortfall
    on a nine-million-cent commitment is decisive."""

    def _execute_at(self, base_stipend_cents: int, title: str, season_number: int):
        production = setup_docusoap_production(
            title=title, season_number=season_number, **FOUR_EPISODE_DOCUSOAP
        )
        call = setup_published_casting_call(
            production["id"], min_age=18, max_age=60, exclusivity_window_days=0
        )
        applicant = setup_cleared_applicant(
            call["id"], items=NO_PSYCH_SCREENING, legal_name="Omar Vance",
            date_of_birth="1987-05-05",
        )
        agreement = setup_executed_agreement(
            applicant["id"],
            production["id"],
            base_stipend_cents=base_stipend_cents,
            **PLAIN_TERMS,
        )
        return production, agreement

    def test_exactly_ninety_percent_restricts(self, api):
        """PRD §2.7: "The utilisation test is performed by integer
        cross-multiplication: `stipend_committed_cents` multiplied by 100 is
        compared against `stipend_pool_cents` multiplied by 90, and the posture
        restricts when the former is greater than or equal to the latter."
        PRD §2.7: "Exactly ninety percent restricts; anything below it, however
        narrowly, does not."
        PRD §2.8: "The posture utilisation test uses integer
        cross-multiplication only, with no floating-point division anywhere in
        its evaluation."

        Design: Difficulty/boundary_precision_check/stipend_utilisation_exactly_ninety_percent_restricts
        """
        production, agreement = self._execute_at(2_250_000, "Harbour Lives HI", 3)
        assert_money(
            agreement["total_stipend_commitment_cents"], 9_000_000, "final stipend"
        )

        rolled_up = get_production(production["id"])
        assert_money(
            rolled_up["stipend_committed_cents"], 9_000_000, "committed stipend"
        )
        # 9,000,000 * 100 == 10,000,000 * 90, and the test is >=.
        assert (
            rolled_up["stipend_committed_cents"] * 100
            == rolled_up["stipend_pool_cents"] * 90
        )
        assert rolled_up["casting_posture"] == "RESTRICTED"

    def test_four_cents_below_the_gate_stays_open(self, api):
        """PRD §2.7: "Exactly ninety percent restricts; anything below it,
        however narrowly, does not."
        PRD §2.7: "Otherwise the posture is `OPEN`."
        PRD §3.6: "The **base component** is `base_stipend_cents` multiplied by
        the episode count used, multiplied by that tier multiplier, rounded half
        up to whole cents."

        Design: Difficulty/boundary_precision_check/stipend_utilisation_exactly_ninety_percent_restricts
        """
        production, agreement = self._execute_at(2_249_999, "Harbour Lives LO", 4)
        # One cent less per episode, four cents less in total.
        assert_money(
            agreement["total_stipend_commitment_cents"], 8_999_996, "final stipend"
        )

        rolled_up = get_production(production["id"])
        assert_money(
            rolled_up["stipend_committed_cents"], 8_999_996, "committed stipend"
        )
        assert (
            rolled_up["stipend_committed_cents"] * 100
            < rolled_up["stipend_pool_cents"] * 90
        ), "899,999,600 is below 900,000,000"
        assert rolled_up["casting_posture"] == "OPEN"


class TestReleaseCoverageEmptySet:
    """Coverage is an integer comparison over a possibly empty sum, and a
    REFUSED release is a row that contributes nothing."""

    def _rolling_block(self, expected_crowd_headcount: int, start_utc: str, end_utc: str):
        production = setup_production(
            title="Island Trials S8",
            season_number=8,
            minor_participant_cap=0,
        )
        setup_active_welfare_protocol(
            production["id"],
            kind="DUTY_OF_CARE_OFFICER",
            cost_cents=1_000_000,
            **SEASON_COVERAGE,
        )
        assert_money(
            get_production(production["id"])["welfare_committed_cents"],
            1_060_000,
            "committed welfare",
        )
        stage = setup_location(
            name="Stage A", capacity=500, filming_permit_number="PRM-1001"
        )
        block = setup_rolling_shoot_block(
            production["id"],
            stage["id"],
            block_kind="STUDIO",
            start_utc=start_utc,
            end_utc=end_utc,
            participant_agreement_ids=[],
            expected_crowd_headcount=expected_crowd_headcount,
            onset_minor_hours=0,
        )
        assert block["status"] == "ROLLING"
        return block

    def test_a_block_expecting_no_crowd_wraps_with_no_releases_at_all(self, api):
        """PRD §3.8: "`covered_head_count` is the sum of `head_count` over the
        block's releases whose `disposition` is `COLLECTED` or
        `BLURRED_WAIVER`; a `REFUSED` release contributes nothing."
        PRD §3.8: "A block expecting no crowd at all, with no releases
        collected, is vacuously complete, because the sum over an empty set is 0
        and 0 is not less than 0."
        PRD §3.8: "Wrapping moves a block `ROLLING → WRAPPED`, is admitted only
        from `ROLLING`, and re-evaluates coverage at wrap time; incomplete
        coverage is refused with `ERR_RELEASE_COVERAGE_INCOMPLETE`."

        Design: Difficulty/boundary_precision_check/release_coverage_empty_set_is_vacuously_complete_at_wrap
        """
        block = self._rolling_block(0, "2026-10-10T08:00:00Z", "2026-10-10T12:00:00Z")

        wrapped = validate_success(api.wrap_shoot_block(block["id"], PA))
        assert wrapped["covered_head_count"] == 0
        assert wrapped["release_coverage_complete"] is True
        assert wrapped["status"] == "WRAPPED"

    def test_a_refused_release_covers_nothing_and_the_wrap_is_refused(self, api):
        """PRD §3.8: "`release_coverage_complete` is true when
        `covered_head_count` is greater than or equal to
        `expected_crowd_headcount` **and** every release of the block whose
        `subject_kind` is `MINOR_INCIDENTAL` carries `guardian_signature` true."
        PRD §3.8: "`covered_head_count` is the sum of `head_count` over the
        block's releases whose `disposition` is `COLLECTED` or
        `BLURRED_WAIVER`; a `REFUSED` release contributes nothing."
        PRD §2.8: "Release coverage is compared with integer head counts, and
        exact equality between coverage and expectation counts as complete."

        Design: Difficulty/boundary_precision_check/release_coverage_empty_set_is_vacuously_complete_at_wrap
        """
        block = self._rolling_block(10, "2026-10-11T08:00:00Z", "2026-10-11T12:00:00Z")
        collect_release(
            block["id"],
            subject_kind="INCIDENTAL_CROWD",
            head_count=10,
            disposition="REFUSED",
        )

        validate_error(
            api.wrap_shoot_block(block["id"], PA),
            ApiErrorId.ERR_RELEASE_COVERAGE_INCOMPLETE.value,
            422,
        )
        still_rolling = get_shoot_block(block["id"])
        assert still_rolling["status"] == "ROLLING"
        assert still_rolling["covered_head_count"] == 0, (
            "ten refused heads are ten uncovered heads"
        )
        assert still_rolling["release_coverage_complete"] is False


class TestWelfareBandFloor:
    """The band floor is inclusive, so a single cent of extra cost can raise the
    committed welfare figure by more than 150,000 cents."""

    def _standard_tier_production(self, title: str):
        production = setup_docusoap_production(
            title=title, season_number=5, **FOUR_EPISODE_DOCUSOAP
        )
        assert production["duty_of_care_tier"] == "STANDARD"
        return production

    def test_one_cent_below_the_floor_takes_the_lower_band(self, api):
        """PRD §3.7: "Step two selects the band rate from that pre-surcharge
        subtotal: four hundredths when the subtotal is below 5,000,000 cents,
        seven hundredths when it is at least 5,000,000 cents and below
        20,000,000 cents, and nine hundredths when it is 20,000,000 cents or
        more."
        PRD §2.8: "The welfare surcharge is whole cents, rounded half up."
        PRD §3.7: "Step four sets `welfare_committed_cents` to the protocol
        subtotal plus that surcharge."

        Design: Difficulty/boundary_precision_check/welfare_band_floor_exactly_five_million_crosses_rate
        """
        production = self._standard_tier_production("Harbour Lives Band Low")
        setup_planned_welfare_protocol(
            production["id"],
            kind="INSURANCE_RIDER",
            cost_cents=4_999_999,
            carrier_certificate_number="CERT-4499",
            **SEASON_COVERAGE,
        )

        # 4,999,999 x 0.04 is 199,999.96, which rounds half up to 200,000.
        after = get_production(production["id"])
        assert_money(
            after["welfare_committed_cents"], 5_199_999, "committed welfare"
        )
        assert after["casting_posture"] == "OPEN"

    def test_reaching_the_floor_exactly_jumps_the_committed_figure(self, api):
        """PRD §3.7: "Step two selects the band rate from that pre-surcharge
        subtotal: four hundredths when the subtotal is below 5,000,000 cents,
        seven hundredths when it is at least 5,000,000 cents and below
        20,000,000 cents, and nine hundredths when it is 20,000,000 cents or
        more."
        PRD §3.7: "Step one sums `cost_cents` over the production's protocols
        whose `status` is `PLANNED` or `ACTIVE`, excluding both `EXPIRED` and
        `CANCELLED` rows, to give the protocol subtotal; coverage dates play no
        part in membership, only the sweep's expiry transition does."
        PRD §3.7: "Step three multiplies the subtotal by that band rate and
        again by the tier factor for the production's current
        `duty_of_care_tier` — one for `STANDARD`, one and a half for
        `ENHANCED`, two for `CRITICAL` — rounding the product half up to whole
        cents to give the duty-of-care surcharge."

        Design: Difficulty/boundary_precision_check/welfare_band_floor_exactly_five_million_crosses_rate
        """
        production = self._standard_tier_production("Harbour Lives Band")
        setup_planned_welfare_protocol(
            production["id"],
            kind="INSURANCE_RIDER",
            cost_cents=4_999_999,
            carrier_certificate_number="CERT-4499",
            **SEASON_COVERAGE,
        )
        below_floor = get_production(production["id"])["welfare_committed_cents"]
        assert_money(below_floor, 5_199_999, "committed welfare below the floor")

        # One more cent of cost, on a protocol whose coverage window does not
        # even overlap the first one, because coverage dates play no part.
        setup_planned_welfare_protocol(
            production["id"],
            kind="AFTERCARE_PROGRAM",
            cost_cents=1,
            coverage_start_utc="2026-12-15T00:00:00Z",
            coverage_end_utc="2027-06-30T00:00:00Z",
        )
        at_floor = get_production(production["id"])["welfare_committed_cents"]
        # Subtotal 5,000,000 now takes 0.07 for a surcharge of 350,000.
        assert_money(at_floor, 5_350_000, "committed welfare at the floor")
        assert at_floor - below_floor == 150_001, (
            "a one-cent input change moved the committed figure by 150,001 cents"
        )
        assert get_production(production["id"])["casting_posture"] == "OPEN"
