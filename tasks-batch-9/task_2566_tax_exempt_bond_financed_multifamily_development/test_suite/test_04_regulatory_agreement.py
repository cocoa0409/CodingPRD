"""The land-use restriction agreement: drafting terms, recording and release.

Recording is the covenant's only substantive act before conversion, and it is
guarded by two gates that run in a fixed order and by the agreement's own state
machine. These tests also pin the fact that the development carries two
independent status axes, since recording moves one of them and only one.
"""

from test_helpers import (
    COMPLIANCE_OFFICER,
    ApiErrorId,
    assert_fields,
    assert_nulls,
    assert_page,
    assert_pool_ledger,
    constants,
    factories,
    fixtures,
    validate_error,
    validate_success,
)


def _restricted_unit(unit_number, floor_space_sqft, ami_percent):
    """One two-bedroom restricted designation at the given band."""
    return {
        "unit_number": unit_number,
        "bedroom_count": 2,
        "floor_space_sqft": floor_space_sqft,
        "designation": "RESTRICTED",
        "ami_percent": ami_percent,
        "utility_allowance_cents": 12000,
        "market_rent_cents": 150000,
    }


def _market_unit(unit_number, floor_space_sqft):
    """One one-bedroom market designation, which carries no band at all."""
    return {
        "unit_number": unit_number,
        "bedroom_count": 1,
        "floor_space_sqft": floor_space_sqft,
        "designation": "MARKET",
        "utility_allowance_cents": 10000,
        "market_rent_cents": 180000,
    }


# Four qualifying units out of ten give a set-aside ratio of exactly 4,000 basis
# points, and bands of 70/70/50/50 average to exactly 6,000 — both boundaries.
AVERAGE_INCOME_ROSTER = (
    _restricted_unit("101", 700, 70),
    _restricted_unit("102", 800, 70),
    _restricted_unit("103", 900, 50),
    _restricted_unit("104", 950, 50),
    _market_unit("201", 860),
    _market_unit("202", 860),
    _market_unit("203", 860),
    _market_unit("204", 860),
    _market_unit("205", 860),
    _market_unit("206", 850),
)


class TestDraftingTheCovenantTerms:
    """The election match and the statutory term minimums, both at the boundary."""

    def test_agreement_terms_pass_at_the_exact_fifteen_year_gap_and_fail_one_year_short(
        self, api
    ):
        """Four filings on one development, three refused and one on the boundary.

        The election-match rule runs before any term arithmetic, so a mismatched
        election never reaches the year checks. The term rule then has two halves: a
        floor of fifteen years on the compliance period, and a gap of at least
        fifteen further years on the extended-use commitment. Both are inclusive on
        the passing side, which is what the accepted fourth filing pins — and none of
        the three refusals may leave a row behind.

        PRD: "The agreement's `set_aside_election` must equal the development's own election; a mismatch is `ERR_SET_ASIDE_MISMATCH`."
        PRD: "And the term lengths must satisfy the statutory minimum: `compliance_period_years` must be at least 15, and `extended_use_years` must be at least 15 years longer than the compliance period — that is, at least the compliance period plus 15. Equality passes in both tests; anything shorter is `ERR_EXTENDED_USE_TOO_SHORT`."
        PRD: "The agreement opens in `DRAFT` with `instrument_number` and `recording_date` null, `amendment_count` at zero, `amendment_reason` null, and both `compliance_period_end_date` and `extended_use_end_date` null."

        Design: Corner/validations/agreement_terms_pass_at_the_exact_fifteen_year_gap_and_fail_one_year_short
        """
        deal = fixtures.setup_units(api)

        validate_error(
            api.create_regulatory_agreement(
                deal.developer_headers,
                **factories.agreement_payload(
                    deal.project_id, set_aside_election="MIN_20_50"
                )
            ),
            ApiErrorId.ERR_SET_ASIDE_MISMATCH,
            422,
        )
        validate_error(
            api.create_regulatory_agreement(
                deal.developer_headers,
                **factories.agreement_payload(
                    deal.project_id, compliance_period_years=14, extended_use_years=30
                )
            ),
            ApiErrorId.ERR_EXTENDED_USE_TOO_SHORT,
            422,
        )
        validate_error(
            api.create_regulatory_agreement(
                deal.developer_headers,
                **factories.agreement_payload(
                    deal.project_id, compliance_period_years=15, extended_use_years=29
                )
            ),
            ApiErrorId.ERR_EXTENDED_USE_TOO_SHORT,
            422,
        )

        drafted = validate_success(
            api.create_regulatory_agreement(
                deal.developer_headers,
                **factories.agreement_payload(
                    deal.project_id, compliance_period_years=15, extended_use_years=30
                )
            ),
            201,
        )
        assert_fields(
            drafted,
            "the accepted agreement",
            status="DRAFT",
            compliance_period_years=15,
            extended_use_years=30,
            amendment_count=0,
        )
        assert_nulls(
            drafted,
            [
                "instrument_number",
                "recording_date",
                "amendment_reason",
                "compliance_period_end_date",
                "extended_use_end_date",
            ],
            "the accepted agreement",
        )

        assert_fields(
            fixtures.read_project(api, deal),
            "the development under a DRAFT covenant",
            compliance_status="UNRESTRICTED",
        )
        assert_page(
            api.list_regulatory_agreements(
                COMPLIANCE_OFFICER, project_id=deal.project_id
            ),
            total_count=1,
        )


class TestRecordingGates:
    """The set-aside gate is evaluated under the agreement's own election."""

    def test_an_average_income_ceiling_of_exactly_6000_bps_records_and_6250_bps_does_not(
        self, api
    ):
        """The average-income election carries two thresholds and both are inclusive.

        One development sits on both boundaries at once: four qualifying units out of
        ten give a set-aside ratio of exactly 4,000 basis points, and bands of
        70/70/50/50 average to exactly 6,000 basis points. Recording succeeds. The
        second development moves a single unit from a 50 band to a 60 band, lifting
        the average to 6,250 basis points — fifty basis points of area median income
        over the line — and recording is refused even though its count ratio is far
        above threshold, because only the average moved.

        PRD: "the summed `ami_percent` of the qualifying units is multiplied by 100 and divided by the number of qualifying units, floored, and that average — expressed in basis points, so a set averaging sixty percent of area median income reads as 6,000 — may not exceed 6,000 basis points."
        PRD: "Both boundaries are inclusive: a ratio exactly equal to the threshold satisfies the election, and an average exactly equal to 6,000 basis points satisfies it too."
        PRD: "The development's `set_aside_satisfied` must be true, evaluated under the *agreement's* set-aside election — and this is checked first, before the designation-count rule"
        PRD: "What it deliberately does *not* do is activate anything: the development's unit designations stay in `PROPOSED`"

        Design: Difficulty/boundary_precision_check/average_income_ceiling_of_exactly_6000_bps_records_while_6250_bps_blocks_recording
        """
        deal = fixtures.setup_units(
            api,
            project_kind="ten_unit",
            project_overrides={
                "name": "Average Income Alpha",
                "set_aside_election": "AVG_INCOME",
            },
            roster=AVERAGE_INCOME_ROSTER,
        )
        alpha = fixtures.read_project(api, deal)
        assert_fields(
            alpha,
            "the development averaging exactly 6,000 bps",
            set_aside_ratio_bps=4000,
            set_aside_satisfied=True,
        )

        alpha_agreement = fixtures.setup_drafted_agreement(api, deal).agreement
        recorded = validate_success(
            api.record_regulatory_agreement(
                alpha_agreement["id"], COMPLIANCE_OFFICER, instrument_number="2026-0011"
            )
        )
        assert_fields(
            recorded,
            "the recorded agreement",
            status="RECORDED",
            instrument_number="2026-0011",
        )
        assert recorded["recording_date"].startswith("2026-08-01T00:00:00"), (
            "recording_date is stamped from the logical clock, which is still at its "
            "startup instant — got {0}".format(recorded["recording_date"])
        )
        assert_fields(
            fixtures.read_project(api, deal),
            "the development after recording",
            compliance_status="RESTRICTED",
        )
        for unit in fixtures.read_units(api, deal).values():
            assert unit["status"] == "PROPOSED", (
                "recording activates nothing, so unit {0} must still be PROPOSED, "
                "not {1}".format(unit["unit_number"], unit["status"])
            )

        beta = fixtures.file_second_project(
            api,
            deal,
            name="Average Income Beta",
            set_aside_election="AVG_INCOME",
        )
        for unit_number, ami_percent in (
            ("B101", 70),
            ("B102", 70),
            ("B103", 60),
            ("B104", 50),
        ):
            validate_success(
                api.create_unit_restriction(
                    deal.developer_headers,
                    **factories.unit_payload(
                        beta["id"],
                        unit_number,
                        floor_space_sqft=850,
                        ami_percent=ami_percent,
                    )
                ),
                201,
            )

        beta_agreement = validate_success(
            api.create_regulatory_agreement(
                deal.developer_headers,
                **factories.agreement_payload(
                    beta["id"], set_aside_election="AVG_INCOME"
                )
            ),
            201,
        )
        validate_error(
            api.record_regulatory_agreement(
                beta_agreement["id"], COMPLIANCE_OFFICER, instrument_number="2026-0012"
            ),
            ApiErrorId.ERR_SET_ASIDE_NOT_SATISFIED,
            422,
        )

        beta_read = validate_success(api.get_project(beta["id"], COMPLIANCE_OFFICER))
        assert_fields(
            beta_read,
            "the development averaging 6,250 bps",
            set_aside_ratio_bps=10000,
            set_aside_satisfied=False,
            compliance_status="UNRESTRICTED",
        )
        refused = validate_success(
            api.get_regulatory_agreement(beta_agreement["id"], COMPLIANCE_OFFICER)
        )
        assert refused["status"] == "DRAFT"
        assert_nulls(
            refused, ["instrument_number", "recording_date"], "the refused agreement"
        )


class TestRecordingDoesNotReplay:
    """RECORDED has an incoming record trigger only from AMENDMENT_PENDING."""

    def test_recording_an_already_recorded_agreement_is_refused(self, api):
        """A second recording under a different instrument number is not an overwrite.

        There is no idempotent replay in this domain, so the second recording is
        refused on state rather than quietly replacing the county's instrument
        number. What separates a rejected replay from an accepted re-recording is
        exactly what this test reads back: the first instrument number survives, the
        amendment counter is still zero, and the refused call wrote nothing at all.

        PRD: "It is available from `DRAFT` and, after an amendment, from `AMENDMENT_PENDING`; attempting it from `RECORDED` or `RELEASED` is `ERR_REG_AGREEMENT_STATE_INVALID`."
        PRD: "There is no idempotent replay anywhere in this domain: repeating a trigger that already fired hits this rule."
        PRD: "increments `amendment_count` by 1 — so the counter records completed amend-then-record cycles rather than opened amendments"

        Design: Corner/state_machines/recording_an_already_recorded_agreement_is_refused_because_no_trigger_replays
        """
        deal = fixtures.setup_recorded_agreement(api)
        recorded_version = deal.agreement["version"]

        validate_error(
            api.record_regulatory_agreement(
                deal.agreement_id, COMPLIANCE_OFFICER, instrument_number="KC-2026-0002"
            ),
            ApiErrorId.ERR_REG_AGREEMENT_STATE_INVALID,
            409,
        )

        after = fixtures.read_agreement(api, deal)
        assert_fields(
            after,
            "the agreement after the refused replay",
            status="RECORDED",
            instrument_number=constants.INSTRUMENT_NUMBER,
            amendment_count=0,
            version=recorded_version,
        )
        assert_nulls(
            after, ["amendment_reason"], "the agreement after the refused replay"
        )

        assert_fields(
            fixtures.read_project(api, deal),
            "the development after the refused replay",
            compliance_status="RESTRICTED",
            development_status="PLANNING",
        )


class TestTheTwoStatusAxes:
    """Recording moves the compliance axis; closing moves the development axis."""

    def test_the_compliance_axis_reaches_restricted_while_the_other_axis_is_still_planning(
        self, api
    ):
        """The combined state after both acts is FINANCED and RESTRICTED at once.

        A development carries two independent status dimensions. Recording the
        covenant advances only the compliance axis and leaves the development axis in
        `PLANNING`; closing the bonds advances only the development axis and leaves
        the compliance axis in `RESTRICTED`. A single status column cannot represent
        the combination, and an implementation that resets the compliance axis when
        the bonds close fails the reading taken after the closing.

        PRD: "It also moves the development's compliance axis `UNRESTRICTED` → `RESTRICTED` and increments the development's `version` by 1."
        PRD: "It moves the development's development axis `PLANNING` → `FINANCED`."
        PRD: "It writes the computed ratio to the development's `provisional_fifty_percent_ratio_bps` and sets `automatic_credit_triggered` to whether that ratio reached 5,000 basis points."
        PRD: "It moves the referenced cap allocation `AWARDED` → `COMMITTED`, which re-derives the pool's `reserved_cents`, `committed_cents`, `available_cents`, `awardable_cents` and `pool_status`."

        Design: Corner/state_machines/compliance_axis_reaches_restricted_while_the_development_axis_is_still_planning
        """
        deal = fixtures.setup_recorded_agreement(api)
        after_recording = fixtures.read_project(api, deal)
        assert_fields(
            after_recording,
            "the development after recording only",
            development_status="PLANNING",
            compliance_status="RESTRICTED",
        )

        fixtures.setup_cap_request(api, deal)
        fixtures.setup_awarded_cap(api, deal)
        fixtures.setup_sized_bond(api, deal)
        fixtures.setup_issued_bond(api, deal)

        after_closing = fixtures.read_project(api, deal)
        assert_fields(
            after_closing,
            "the development after closing",
            development_status="FINANCED",
            compliance_status="RESTRICTED",
            provisional_fifty_percent_ratio_bps=5000,
            automatic_credit_triggered=True,
        )
        assert_nulls(
            after_closing,
            ["final_fifty_percent_ratio_bps"],
            "the development after closing",
        )

        assert_fields(
            fixtures.read_bond_issue(api, deal),
            "the closed issue",
            status="ISSUED",
            par_amount_cents=constants.PAR_AMOUNT_CENTS,
        )
        assert_fields(
            fixtures.read_allocation(api, deal), "the award", status="COMMITTED"
        )
        assert_pool_ledger(
            fixtures.read_pool(api, deal),
            reserved_cents=0,
            committed_cents=constants.AWARDED_AMOUNT_CENTS,
            awardable_cents=(
                constants.POOL_TOTAL_CAP_CENTS - constants.AWARDED_AMOUNT_CENTS
            ),
            label="pool after the closing",
        )

        assert fixtures.read_unit(api, deal, "101")["status"] == "PROPOSED", (
            "designations activate at stabilization, not at recording or at closing"
        )


class TestExtendedUseRelease:
    """One clock advance can cross both compliance horizons in a single pass."""

    def test_a_clock_past_the_extended_use_end_releases_the_agreement_and_its_units(
        self, api
    ):
        """Both time gates fire in one pass, and the release cascades into the units.

        A single advance to 2057-03-02 is strictly past the compliance end of
        2042-03-01 and strictly past the extended-use end of 2057-03-01, so the
        compliance axis must land on `RELEASED` rather than stopping at the
        intermediate `EXTENDED_USE`. The release reaches only the units that were
        `ACTIVE`, clearing the restricted rent back to null on the restricted rows
        while the market rows simply follow into `RELEASED`, and a redesignation aimed
        at a released row is refused. The development axis and the committed award are
        untouched by the clock.

        PRD: "A single clock advance evaluates every time-gated transition in one pass."
        PRD: "A development in `EXTENDED_USE` whose `extended_use_end_date` is not null and which the new clock value has passed strictly moves `EXTENDED_USE` → `RELEASED`, and on that second step the cascade of §3.4 fires: the development's `RECORDED` regulatory agreement moves to `RELEASED`, and that release moves every `ACTIVE` unit designation of the development to `RELEASED` with its `restricted_rent_cents` cleared to null."
        PRD: "Patching a unit that has already reached `RELEASED` is `ERR_UNIT_RESTRICTION_STATE_INVALID`."
        PRD: "Units in every status count toward both numerators — `PROPOSED`, `ACTIVE` and `RELEASED` alike"

        Design: Corner/state_machines/clock_past_the_extended_use_end_releases_the_agreement_and_its_units_and_locks_patches
        """
        deal = fixtures.setup_converted_bond(api, dscr_basis="T3")

        agreement_at_conversion = fixtures.read_agreement(api, deal)
        assert_fields(
            agreement_at_conversion,
            "the agreement at conversion",
            status="RECORDED",
        )
        for field, instant in (
            ("compliance_period_end_date", "2042-03-01T00:00:00"),
            ("extended_use_end_date", "2057-03-01T00:00:00"),
        ):
            assert agreement_at_conversion[field].startswith(instant), (
                "the agreement at conversion: {0} expected {1}, got {2}".format(
                    field, instant, agreement_at_conversion[field]
                )
            )
        restricted_before = fixtures.read_unit(api, deal, "101")
        assert_fields(
            restricted_before,
            "the restricted unit at conversion",
            status="ACTIVE",
            restricted_rent_cents=109500,
        )

        fixtures.set_clock(api, "2057-03-02T00:00:00Z")

        project = fixtures.read_project(api, deal)
        assert_fields(
            project,
            "the development after the clock advance",
            compliance_status="RELEASED",
            development_status="STABILIZED",
            restricted_unit_count=2,
        )
        assert_fields(
            fixtures.read_agreement(api, deal),
            "the agreement after the clock advance",
            status="RELEASED",
        )

        released_restricted = fixtures.read_unit(api, deal, "101")
        assert_fields(
            released_restricted,
            "the released restricted unit",
            status="RELEASED",
            designation="RESTRICTED",
        )
        assert_nulls(
            released_restricted, ["restricted_rent_cents"], "the released restricted unit"
        )
        released_market = fixtures.read_unit(api, deal, "201")
        assert_fields(
            released_market, "the released market unit", status="RELEASED"
        )
        assert_nulls(
            released_market, ["restricted_rent_cents"], "the released market unit"
        )

        validate_error(
            api.patch_unit_restriction(
                deal.unit_id("101"), deal.developer_headers, designation="MARKET"
            ),
            ApiErrorId.ERR_UNIT_RESTRICTION_STATE_INVALID,
            409,
        )
        assert (
            fixtures.read_unit(api, deal, "101")["designation"] == "RESTRICTED"
        ), "the refused patch may not change the designation"

        assert fixtures.read_allocation(api, deal)["status"] == "COMMITTED", (
            "only an award still in AWARDED can lapse on a clock advance"
        )
