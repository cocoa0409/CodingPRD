"""Unit designation: the counters, the two fractions and the rent ceiling.

Nearly all of the restriction arithmetic in this contract originates one unit at a
time, and every development figure downstream of it is re-derived from the whole
unit set rather than adjusted in place. These tests pin the derived read model, the
payload rules that guard a designation, the four-input rent ceiling and each of its
three structurally different binding terms.
"""

from test_helpers import (
    ALLOCATION_OFFICER,
    COMPLIANCE_OFFICER,
    ApiErrorId,
    assert_fields,
    assert_nulls,
    assert_page,
    assert_project_fractions,
    assert_unit_counts,
    constants,
    factories,
    fixtures,
    validate_error,
    validate_success,
)


class TestDerivedReadModel:
    """What a development and its unit list expose once the roster is filed."""

    def test_project_read_returns_every_derived_fraction_after_designation(self, api):
        """Read the development back after all four of its units are designated.

        Two restricted units of 800 and 900 square feet out of four units and 3,400
        square feet put both fractions on 5,000 basis points, so the read has to
        expose the stored inputs and the recomputed figures together — a snapshot
        taken at write time and served stale would not do, and neither would
        publishing the fractions only on the list endpoint.

        PRD: "The `applicable_fraction_bps` is the smaller of the two fractions."
        PRD: "Fetch one development with both status axes, the derived unit-designation counts, the applicable fraction, the set-aside ratio and both fifty-percent-test ratios."
        PRD: "On creation the server solves `aggregate_basis_cents` as the land cost plus the filed depreciable basis"

        Design: Corner/entities/project_read_returns_every_derived_fraction_after_designation
        """
        deal = fixtures.setup_units(api)

        project = validate_success(api.get_project(deal.project_id, ALLOCATION_OFFICER))

        assert_fields(
            project,
            "project",
            total_units=constants.COMPACT_TOTAL_UNITS,
            total_floor_space_sqft=constants.COMPACT_TOTAL_FLOOR_SPACE_SQFT,
            aggregate_basis_cents=constants.COMPACT_AGGREGATE_BASIS_CENTS,
            set_aside_ratio_bps=5000,
            set_aside_satisfied=True,
            development_status="PLANNING",
            compliance_status="UNRESTRICTED",
        )
        assert_unit_counts(project, restricted=2, market=2, employee=0, designated=4)
        assert_project_fractions(
            project, unit_fraction=5000, floor_space_fraction=5000, applicable_fraction=5000
        )
        assert_nulls(
            project,
            ("provisional_fifty_percent_ratio_bps", "final_fifty_percent_ratio_bps"),
            "project",
        )

    def test_unit_restriction_list_paginates_with_limit_offset_total_count_and_has_more(
        self, api
    ):
        """Page through the four unit designations, then filter to the restricted two.

        The count in `meta` describes the filtered set rather than the page, the
        requested window is echoed back instead of the defaults, and a second page
        genuinely skips the rows the first one served. Narrowing by designation
        drops the count to two, which proves the filter runs before the count.

        PRD: "`limit` defaults to 10, has a minimum of 1 and a maximum of 100. `offset` defaults to 0 and has a minimum of 0."
        PRD: "Both are echoed in `meta`, alongside `total_count` (the number of rows matching the filters before the page window is applied) and `has_more` (true when rows remain beyond the current window)."
        PRD: "List unit designations, optionally narrowed to one development, designation or status. Ordered by `unit_number` ascending."

        Design: Corner/entities/unit_restriction_list_paginates_with_limit_offset_total_count_and_has_more
        """
        deal = fixtures.setup_units(api)

        first_page, _ = assert_page(
            api.list_unit_restrictions(
                COMPLIANCE_OFFICER, project_id=deal.project_id, limit=2, offset=0
            ),
            total_count=4,
            has_more=True,
            limit=2,
            offset=0,
        )
        assert len(first_page) == 2, "a limit of 2 must serve exactly two rows"

        second_page, _ = assert_page(
            api.list_unit_restrictions(
                COMPLIANCE_OFFICER, project_id=deal.project_id, limit=2, offset=2
            ),
            total_count=4,
            has_more=False,
            limit=2,
            offset=2,
        )
        assert len(second_page) == 2
        overlap = {row["id"] for row in first_page} & {row["id"] for row in second_page}
        assert not overlap, "the offset must skip the rows the first page served"

        restricted, _ = assert_page(
            api.list_unit_restrictions(
                COMPLIANCE_OFFICER, project_id=deal.project_id, designation="RESTRICTED"
            ),
            total_count=2,
            has_more=False,
            limit=constants.DEFAULT_LIMIT,
            offset=constants.DEFAULT_OFFSET,
        )
        assert [row["designation"] for row in restricted] == ["RESTRICTED"] * 2, (
            "the designation filter must exclude the market rows"
        )


class TestDesignationPayloadRules:
    """The inputs a designation must carry, and the band the election allows."""

    def test_unit_creation_missing_required_market_rent_cents_returns_4XX_invalid_request(
        self, api
    ):
        """Designate a market unit without its market rent, then with it.

        The achievable unrestricted rent is a declared input with no default, so
        omitting it is a payload failure even though the row is otherwise storable;
        the elected band does default to null, which is why the same market row is
        accepted once the rent is supplied. Nothing may be stored by the refusal.

        PRD: "Designating a unit takes the owning `project_id`, a `unit_number` label, the `bedroom_count` (zero or more, since a studio is a legitimate restricted unit), the unit's `floor_space_sqft` (greater than zero), a `designation` of `RESTRICTED`, `MARKET` or `EMPLOYEE_UNIT`, the monthly `utility_allowance_cents` deducted from the gross rent ceiling (zero or more), and the achievable unrestricted monthly rent as `market_rent_cents` (greater than zero)."
        PRD: "All required inputs present and non-null; every enum value inside its declared set; every `_cents` and `_bps` field an integer that is not negative"
        PRD: "For a unit that is not `RESTRICTED`, `restricted_rent_cents` stays null."

        Design: Corner/entities/unit_creation_missing_required_market_rent_cents_returns_4XX_invalid_request
        """
        deal = fixtures.setup_project(api)

        missing = api.create_unit_restriction(
            deal.developer_headers,
            project_id=deal.project_id,
            unit_number="201",
            bedroom_count=1,
            floor_space_sqft=850,
            designation="MARKET",
            utility_allowance_cents=10000,
        )
        validate_error(missing, ApiErrorId.ERR_INVALID_REQUEST, 400)

        unit = validate_success(
            api.create_unit_restriction(
                deal.developer_headers,
                project_id=deal.project_id,
                unit_number="201",
                bedroom_count=1,
                floor_space_sqft=850,
                designation="MARKET",
                utility_allowance_cents=10000,
                market_rent_cents=180000,
            ),
            201,
        )
        assert_fields(unit, "unit_restriction", status="PROPOSED")
        assert_nulls(unit, ("ami_percent", "restricted_rent_cents"), "unit_restriction")

        project = fixtures.read_project(api, deal)
        assert_unit_counts(project, designated=1, market=1, restricted=0)

    def test_ami_band_above_sixty_is_allowed_only_under_the_average_income_election(
        self, api
    ):
        """File the identical seventy-percent band under two different elections.

        The band rule is conditional on the parent development's election, not on
        the payload, so the same filing is refused under the sixty-percent minimum
        election and accepted under the averaging election — where the elected band
        then feeds the rent formula. The two presence cases share the same code.

        PRD: "The field is required when the designation is `RESTRICTED` and must be omitted otherwise; when supplied it must be one of 20, 30, 40, 50, 60, 70 or 80; and a band above 60 is permitted only when the development's `set_aside_election` is `AVG_INCOME`. Any of those three failures is `ERR_AMI_PERCENT_NOT_ALLOWED`, on both initial designation and later redesignation."
        PRD: "The **effective band** is the smaller of the unit's own `ami_percent` and that election cap, so a unit that elected a 70-percent band in a `MIN_40_60` development charges against 60."

        Design: Corner/validations/ami_band_above_sixty_is_allowed_only_under_the_average_income_election
        """
        deal = fixtures.setup_project(api)
        averaging = fixtures.file_second_project(
            api, deal, name="Bayside Mix", set_aside_election="AVG_INCOME"
        )

        too_high = api.create_unit_restriction(
            deal.developer_headers,
            **factories.unit_payload(deal.project_id, "101", ami_percent=70)
        )
        validate_error(too_high, ApiErrorId.ERR_AMI_PERCENT_NOT_ALLOWED, 422)

        allowed = validate_success(
            api.create_unit_restriction(
                deal.developer_headers,
                **factories.unit_payload(averaging["id"], "101", ami_percent=70)
            ),
            201,
        )
        assert_fields(
            allowed,
            "unit_restriction",
            imputed_household_size=3,
            restricted_rent_cents=129750,
        )

        band_absent = api.create_unit_restriction(
            deal.developer_headers,
            project_id=deal.project_id,
            unit_number="102",
            bedroom_count=2,
            floor_space_sqft=900,
            designation="RESTRICTED",
            utility_allowance_cents=12000,
            market_rent_cents=150000,
        )
        validate_error(band_absent, ApiErrorId.ERR_AMI_PERCENT_NOT_ALLOWED, 422)

        band_on_market = api.create_unit_restriction(
            deal.developer_headers,
            project_id=deal.project_id,
            unit_number="201",
            bedroom_count=1,
            floor_space_sqft=850,
            designation="MARKET",
            ami_percent=60,
            utility_allowance_cents=10000,
            market_rent_cents=180000,
        )
        validate_error(band_on_market, ApiErrorId.ERR_AMI_PERCENT_NOT_ALLOWED, 422)

        within_band = validate_success(
            api.create_unit_restriction(
                deal.developer_headers,
                **factories.unit_payload(deal.project_id, "101", ami_percent=60)
            ),
            201,
        )
        assert within_band["restricted_rent_cents"] == 109500

        project = fixtures.read_project(api, deal)
        assert_unit_counts(project, designated=1, restricted=1)
        assert_fields(project, "project", unit_fraction_bps=2500, set_aside_satisfied=False)
        sibling = validate_success(api.get_project(averaging["id"], ALLOCATION_OFFICER))
        assert_unit_counts(sibling, designated=1, label="sibling project")


class TestRestrictedRentCeiling:
    """Four inputs, three nested clamps, and both of the clamp boundaries."""

    def test_restricted_rent_ceiling_binds_on_ami_then_on_market_then_on_the_program_floor(
        self, api
    ):
        """Three units alike in every input but the achievable market rent.

        Each one is priced by a structurally different binding term: the utility
        adjusted income ceiling, the market rent, and the program floor. The third
        is the interesting one — its floor answer sits above both caps, which can
        only happen if the floor is applied last rather than folded inside the
        smaller-of comparison.

        PRD: "The smaller of the utility-adjusted AMI ceiling and the unit's `market_rent_cents` is taken. Finally, and last of all, a program rent floor of 25,000 cents is applied by taking the larger of that floor and the value just computed, which means the floor can legitimately raise the answer above both caps."
        PRD: "First, the unit's `imputed_household_size` is the larger of 1 and one more than `bedroom_count`, so a studio imputes a one-person household and a three-bedroom imputes four."
        PRD: "In all three cases `set_aside_ratio_bps` is the count of qualifying units multiplied by 10,000, divided by `total_units`, floored to a whole basis point."

        Design: Difficulty/combinatorial_formula/restricted_rent_ceiling_binds_on_ami_then_on_market_then_on_the_program_floor
        """
        deal = fixtures.setup_project(api, project_kind="ten_unit")

        income_bound = fixtures.designate_unit(
            api, deal, unit_number="101", floor_space_sqft=700, market_rent_cents=150000
        )
        market_bound = fixtures.designate_unit(
            api, deal, unit_number="102", floor_space_sqft=800, market_rent_cents=95000
        )
        floor_bound = fixtures.designate_unit(
            api, deal, unit_number="103", floor_space_sqft=900, market_rent_cents=20000
        )

        assert_fields(
            income_bound,
            "unit 101",
            imputed_household_size=3,
            restricted_rent_cents=109500,
        )
        assert market_bound["restricted_rent_cents"] == 95000, (
            "a market rent under the income ceiling binds instead of it"
        )
        assert floor_bound["restricted_rent_cents"] == constants.RENT_FLOOR_CENTS
        assert floor_bound["restricted_rent_cents"] > 20000, (
            "the program floor must override the market cap, not be clamped by it"
        )

        project = fixtures.read_project(api, deal)
        assert_unit_counts(project, restricted=3)
        assert_fields(
            project, "project", set_aside_ratio_bps=3000, set_aside_satisfied=False
        )

    def test_restricted_rent_clamps_at_the_exact_ceiling_and_at_the_exact_program_floor(
        self, api
    ):
        """Five units on the same income ceiling, straddling both clamps by one cent.

        Holding household size, band and allowance fixed puts the income ceiling on
        exactly 109,500, so a market rent that ties it must resolve to the same
        figure and one cent under it must bind instead. At the other end a market
        rent one cent under the program floor is lifted to the floor while one cent
        above it is left alone: both clamps are inclusive on the tie.

        PRD: "Thirty percent of that annual income figure is taken — multiplied by 30, divided by 100 — and **floored to whole cents first**; only then is the result divided by 12 and **floored again** to produce the maximum monthly gross rent."
        PRD: "The `utility_allowance_cents` is subtracted from that AMI-derived gross ceiling and from nothing else — it is never subtracted from market rent."
        PRD: "The smaller of the utility-adjusted AMI ceiling and the unit's `market_rent_cents` is taken. Finally, and last of all, a program rent floor of 25,000 cents is applied by taking the larger of that floor and the value just computed, which means the floor can legitimately raise the answer above both caps."

        Design: Difficulty/boundary_precision_check/restricted_rent_clamps_at_the_exact_ceiling_and_at_the_exact_program_floor
        """
        deal = fixtures.setup_project(
            api,
            project_overrides={
                "name": "Rent Boundary House",
                "total_units": 5,
                "total_floor_space_sqft": 4250,
            },
        )

        rents = {}
        for unit_number, market_rent in (
            ("101", 150000),
            ("102", 109500),
            ("103", 109499),
            ("104", 24999),
        ):
            row = fixtures.designate_unit(
                api,
                deal,
                unit_number=unit_number,
                floor_space_sqft=850,
                market_rent_cents=market_rent,
            )
            rents[unit_number] = row

        last = validate_success(
            api.create_unit_restriction(
                deal.developer_headers,
                **factories.unit_payload(
                    deal.project_id, "105", floor_space_sqft=850, market_rent_cents=25001
                )
            ),
            201,
        )
        assert_fields(
            last, "unit 105", restricted_rent_cents=25001, imputed_household_size=3
        )

        assert rents["101"]["restricted_rent_cents"] == 109500
        assert rents["102"]["restricted_rent_cents"] == 109500, (
            "a market rent exactly equal to the ceiling resolves to the ceiling"
        )
        assert rents["103"]["restricted_rent_cents"] == 109499, (
            "a market rent one cent under the ceiling binds instead"
        )
        assert rents["104"]["restricted_rent_cents"] == constants.RENT_FLOOR_CENTS

        for unit_number, row in rents.items():
            assert row["status"] == "PROPOSED", (
                "unit {0} must open PROPOSED".format(unit_number)
            )
        project = fixtures.read_project(api, deal)
        assert_unit_counts(project, restricted=5)
        assert_project_fractions(project, applicable_fraction=10000)
        assert_fields(
            project, "project", set_aside_ratio_bps=10000, set_aside_satisfied=True
        )


EMPLOYEE_UNIT_ROSTER = (
    {"unit_number": "101", "bedroom_count": 1, "floor_space_sqft": 700,
     "designation": "RESTRICTED", "ami_percent": 60,
     "utility_allowance_cents": 10000, "market_rent_cents": 150000},
    {"unit_number": "102", "bedroom_count": 2, "floor_space_sqft": 800,
     "designation": "RESTRICTED", "ami_percent": 60,
     "utility_allowance_cents": 12000, "market_rent_cents": 150000},
    {"unit_number": "103", "bedroom_count": 2, "floor_space_sqft": 900,
     "designation": "RESTRICTED", "ami_percent": 60,
     "utility_allowance_cents": 12000, "market_rent_cents": 150000},
    {"unit_number": "104", "bedroom_count": 3, "floor_space_sqft": 950,
     "designation": "RESTRICTED", "ami_percent": 60,
     "utility_allowance_cents": 14000, "market_rent_cents": 190000},
    {"unit_number": "301", "bedroom_count": 2, "floor_space_sqft": 860,
     "designation": "EMPLOYEE_UNIT",
     "utility_allowance_cents": 12000, "market_rent_cents": 150000},
    {"unit_number": "302", "bedroom_count": 2, "floor_space_sqft": 860,
     "designation": "EMPLOYEE_UNIT",
     "utility_allowance_cents": 12000, "market_rent_cents": 150000},
    {"unit_number": "201", "bedroom_count": 2, "floor_space_sqft": 860,
     "designation": "MARKET",
     "utility_allowance_cents": 12000, "market_rent_cents": 180000},
    {"unit_number": "202", "bedroom_count": 2, "floor_space_sqft": 860,
     "designation": "MARKET",
     "utility_allowance_cents": 12000, "market_rent_cents": 180000},
    {"unit_number": "203", "bedroom_count": 2, "floor_space_sqft": 860,
     "designation": "MARKET",
     "utility_allowance_cents": 12000, "market_rent_cents": 180000},
    {"unit_number": "204", "bedroom_count": 1, "floor_space_sqft": 850,
     "designation": "MARKET",
     "utility_allowance_cents": 10000, "market_rent_cents": 180000},
)


class TestFractionInputSets:
    """Which rows enter the two numerators, and whether a round trip is exact."""

    def test_applicable_fraction_counts_only_restricted_rows_and_excludes_employee_units_from_both_numerators(
        self, api
    ):
        """Ten units — four restricted, two employee and four market — then one is moved.

        The employee rows sit inside both denominators but outside both numerators,
        so the unit side reads 4,000 while the floor-space side floors to 3,941 and
        the applicable fraction takes the smaller of the two. Redesignating one
        employee unit as restricted moves it into both numerators at once, and the
        denominators never move.

        PRD: "Units in every status count toward both numerators — `PROPOSED`, `ACTIVE` and `RELEASED` alike — while `MARKET` and `EMPLOYEE_UNIT` units are excluded from both numerators but never from the two denominators."
        PRD: "The **floor-space fraction**, stored as `floor_space_fraction_bps`, is the summed `floor_space_sqft` of the development's `RESTRICTED` units multiplied by 10,000, divided by `total_floor_space_sqft`, again floored."
        PRD: "The `applicable_fraction_bps` is the smaller of the two fractions."
        PRD: "Under `MIN_40_60` the qualifying units are the restricted units whose `ami_percent` is at most 60, and the ratio must reach 4,000 basis points — forty percent of total units."

        Design: Corner/calculations/applicable_fraction_counts_only_restricted_rows_and_excludes_employee_units_from_both_numerators
        """
        deal = fixtures.setup_units(
            api, project_kind="ten_unit", roster=EMPLOYEE_UNIT_ROSTER
        )

        before = validate_success(api.get_project(deal.project_id, COMPLIANCE_OFFICER))
        assert_project_fractions(
            before, unit_fraction=4000, floor_space_fraction=3941, applicable_fraction=3941
        )
        assert_unit_counts(before, restricted=4, employee=2, market=4, designated=10)
        assert_fields(
            before, "project", set_aside_ratio_bps=4000, set_aside_satisfied=True
        )

        promoted = validate_success(
            api.patch_unit_restriction(
                deal.unit_id("301"),
                deal.developer_headers,
                designation="RESTRICTED",
                ami_percent=60,
            )
        )
        assert promoted["restricted_rent_cents"] == 109500, (
            "the promoted row must now carry a restricted ceiling"
        )

        after = validate_success(api.get_project(deal.project_id, COMPLIANCE_OFFICER))
        assert_project_fractions(
            after, unit_fraction=5000, floor_space_fraction=4952, applicable_fraction=4952
        )
        assert_unit_counts(after, restricted=5, employee=1, market=4, designated=10)
        assert_fields(
            after,
            "project",
            total_units=constants.TEN_UNIT_TOTAL_UNITS,
            total_floor_space_sqft=constants.TEN_UNIT_TOTAL_FLOOR_SPACE_SQFT,
        )

    def test_redesignating_a_unit_and_reverting_it_restores_the_applicable_fraction_to_the_exact_basis_point(
        self, api
    ):
        """Move the 950 square-foot restricted unit to market, then back again.

        The reverted figure is the floor of 3,350 times 10,000 over 8,500, so a round
        trip only lands back on it if the fractions are re-derived over the whole
        unit set: taking 950 square feet out and putting it back through two separate
        floor operations would drift. The unit's own ceiling is nulled on the way out
        and recomputed on the way back.

        PRD: "Because every derived development figure is re-derived from scratch on each designation change rather than incrementally adjusted, redesignating a unit and then reverting it restores the prior applicable fraction exactly."
        PRD: "For a unit that is not `RESTRICTED`, `restricted_rent_cents` stays null."
        PRD: "Five counters on the development are re-derived on every designation and every redesignation: `restricted_unit_count`, `market_unit_count` and `employee_unit_count` count the development's units carrying each designation; `designated_unit_count` counts all of its units regardless of designation; and each such re-derivation increments the development's `version` by 1."

        Design: Difficulty/compensating_invariant/redesignating_a_unit_and_reverting_it_restores_the_applicable_fraction_to_the_exact_basis_point
        """
        deal = fixtures.ten_unit_deal(api, stage=fixtures.setup_units)
        unit_id = deal.unit_id("104")

        outbound = validate_success(
            api.patch_unit_restriction(
                unit_id,
                deal.developer_headers,
                designation="MARKET",
                utility_allowance_cents=10000,
                market_rent_cents=180000,
            )
        )
        assert_nulls(outbound, ("restricted_rent_cents",), "unit 104 as market")

        midpoint = fixtures.read_project(api, deal)
        assert_project_fractions(
            midpoint, unit_fraction=3000, floor_space_fraction=2823, applicable_fraction=2823
        )
        assert_unit_counts(midpoint, restricted=3, market=7, designated=10)
        assert_fields(
            midpoint, "project", set_aside_ratio_bps=3000, set_aside_satisfied=False
        )

        reverted = validate_success(
            api.patch_unit_restriction(
                unit_id,
                deal.developer_headers,
                designation="RESTRICTED",
                ami_percent=60,
                utility_allowance_cents=12000,
                market_rent_cents=150000,
            )
        )
        assert_fields(
            reverted,
            "unit 104 restored",
            designation="RESTRICTED",
            ami_percent=60,
            restricted_rent_cents=109500,
            unit_number="104",
            floor_space_sqft=950,
        )

        restored = fixtures.read_project(api, deal)
        assert_project_fractions(
            restored, unit_fraction=4000, floor_space_fraction=3941, applicable_fraction=3941
        )
        assert_unit_counts(restored, restricted=4, market=6, employee=0, designated=10)
        assert_fields(
            restored, "project", set_aside_ratio_bps=4000, set_aside_satisfied=True
        )


class TestRosterAggregates:
    """Limits that only the collection can breach, and the recording gate they feed."""

    def test_unit_roster_aggregates_block_a_duplicate_a_fifth_unit_and_an_under_designated_recording(
        self, api
    ):
        """Two units filed on a four-unit development, then a duplicate and a recording.

        Every individual filing here is valid; only the collection breaches a limit.
        The set-aside is already satisfied at two restricted units of four, so the
        refused recording can only come from the designation-count gate behind it.
        Re-filing an existing unit number is the duplicate error rather than the
        count error, because uniqueness is tested first, and the fifth designation
        is refused only once the roster is complete.

        PRD: "A `unit_number` is unique within its development across every unit status, `RELEASED` ones included, and a repeat is `ERR_DUPLICATE_UNIT_NUMBER`; separately, the number of designated units may never exceed the development's `total_units`, and an attempt to designate one more than that is `ERR_UNIT_COUNT_EXCEEDS_TOTAL`, evaluated immediately after the uniqueness test."
        PRD: "Then the development's `designated_unit_count` must equal its `total_units`, so that every unit in the building carries a designation and no unrestricted unit can hide outside the covenant; under-designation is `ERR_UNIT_COUNT_MISMATCH`."
        PRD: "A first recording moves the agreement `DRAFT` → `RECORDED`, stamps the supplied `instrument_number` and stamps `recording_date` from the logical clock. It also moves the development's compliance axis `UNRESTRICTED` → `RESTRICTED` and increments the development's `version` by 1."

        Design: Corner/validations/unit_roster_aggregates_block_a_duplicate_a_fifth_unit_and_an_under_designated_recording
        """
        deal = fixtures.setup_project(api)
        fixtures.designate_unit(api, deal, unit_number="101", floor_space_sqft=800)
        fixtures.designate_unit(api, deal, unit_number="102", floor_space_sqft=900)
        fixtures.setup_drafted_agreement(api, deal)

        duplicate = api.create_unit_restriction(
            deal.developer_headers,
            **factories.unit_payload(
                deal.project_id,
                "101",
                bedroom_count=1,
                floor_space_sqft=700,
                designation="MARKET",
                utility_allowance_cents=10000,
                market_rent_cents=170000,
            )
        )
        validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_UNIT_NUMBER, 409)

        under_designated = fixtures.read_project(api, deal)
        assert under_designated["set_aside_satisfied"] is True, (
            "the set-aside gate must already pass, so only the count gate can fire"
        )
        early = api.record_regulatory_agreement(
            deal.agreement_id, COMPLIANCE_OFFICER, instrument_number="KC-2026-0009"
        )
        validate_error(early, ApiErrorId.ERR_UNIT_COUNT_MISMATCH, 422)

        still_draft = fixtures.read_agreement(api, deal)
        assert_fields(still_draft, "regulatory_agreement", status="DRAFT")
        assert_nulls(still_draft, ("instrument_number",), "regulatory_agreement")

        for unit_number in ("201", "202"):
            fixtures.designate_unit(
                api,
                deal,
                unit_number=unit_number,
                bedroom_count=1,
                floor_space_sqft=850,
                designation="MARKET",
                utility_allowance_cents=10000,
                market_rent_cents=180000,
            )
        complete = fixtures.read_project(api, deal)
        assert_unit_counts(complete, designated=4)

        recorded = validate_success(
            api.record_regulatory_agreement(
                deal.agreement_id, COMPLIANCE_OFFICER, instrument_number="KC-2026-0010"
            )
        )
        assert_fields(
            recorded,
            "regulatory_agreement",
            status="RECORDED",
            instrument_number="KC-2026-0010",
        )
        restricted = fixtures.read_project(api, deal)
        assert_fields(restricted, "project", compliance_status="RESTRICTED")

        fifth = api.create_unit_restriction(
            deal.developer_headers,
            **factories.unit_payload(
                deal.project_id,
                "203",
                bedroom_count=1,
                floor_space_sqft=800,
                designation="MARKET",
                utility_allowance_cents=10000,
                market_rent_cents=175000,
            )
        )
        validate_error(fifth, ApiErrorId.ERR_UNIT_COUNT_EXCEEDS_TOTAL, 422)

        final = fixtures.read_project(api, deal)
        assert_unit_counts(final, designated=4)
        assert_project_fractions(final, applicable_fraction=5000)
