"""Sizing the bond issue, closing it, and unwinding it by mandatory redemption.

The sizing chain is an ordered arithmetic pipeline whose intermediate figures are
each pinned, and the rounding step at its end is what decides whether the issue
fits its volume cap award at all. Closing then runs the provisional fifty-percent
test and commits the cap; redemption is the branch sibling that gives it back.
"""

from test_helpers import (
    ALLOCATION_OFFICER,
    COMPLIANCE_OFFICER,
    TRUSTEE,
    ApiErrorId,
    assert_bond_sizing,
    assert_fields,
    assert_nulls,
    assert_page,
    assert_par_conservation,
    assert_pool_ledger,
    assert_project_fractions,
    assert_unit_counts,
    constants,
    factories,
    fixtures,
    validate_error,
    validate_success,
)


class TestTheSizingChain:
    """Provisional par, the two percent allowance, and the denomination round-up."""

    def test_the_allowance_is_charged_on_provisional_par_and_par_rounds_up_to_the_next_denomination(
        self, api
    ):
        """One sizing filing whose three solved figures are each pinned separately.

        Eligible cost 190,000,000 plus capitalized interest 6,000,000 gives a
        provisional par of 196,000,000. The allowance is two percent of *that*, so
        3,920,000, and unrounded par is 199,920,000 — only 80,000 short of a
        denomination boundary. The round-up to the next 500,000 cents therefore
        lands on exactly 200,000,000, where a floor would have left 199,500,000 and
        no rounding at all would have left 199,920,000. The negative-arbitrage
        allowance is then charged on the *final* par, so 4,000,000 rather than the
        3,998,400 that the unrounded figure would have produced.

        PRD: "Provisional par is the eligible cost plus the capitalized interest. The `issuance_allowance_cents` is two percent of provisional par, rounded half up to whole cents. Unrounded par is provisional par plus that allowance."
        PRD: "Then `par_amount_cents` is unrounded par raised to the next whole authorized denomination of 500,000 cents — five thousand dollars — by dividing unrounded par by 500,000, rounding that quotient **up** to a whole number, and multiplying back by 500,000; this step never lowers par."
        PRD: "Finally `negative_arbitrage_allowance_cents` is 200 basis points of the final `par_amount_cents` — two percent of par — with the quotient floored to whole cents."
        PRD: "On success the issue opens in `DRAFT` with `closing_date`, `conversion_date`, `redemption_date`, `dscr_bps`, `dscr_basis` and `min_occupancy_bps` all null, `operating_months` an empty list, `cumulative_funded_cents` at zero, `negative_arbitrage_cents` at zero and `undrawn_cents` equal to the full `par_amount_cents`."

        Design: Corner/calculations/bond_sizing_applies_the_two_percent_allowance_and_the_five_thousand_dollar_round_up
        """
        deal = fixtures.setup_awarded_cap(api)

        issue = validate_success(
            api.create_bond_issue(
                deal.developer_headers,
                **factories.bond_issue_payload(deal.project_id, deal.allocation_id)
            ),
            201,
        )

        assert_fields(
            issue,
            "bond_issue",
            status="DRAFT",
            issuance_allowance_cents=3920000,
            par_amount_cents=200000000,
            negative_arbitrage_allowance_cents=4000000,
            cumulative_funded_cents=0,
            undrawn_cents=200000000,
            negative_arbitrage_cents=0,
        )
        assert_bond_sizing(issue)
        assert_par_conservation(issue)
        assert_nulls(
            issue,
            (
                "closing_date",
                "conversion_date",
                "redemption_date",
                "dscr_bps",
                "dscr_basis",
                "min_occupancy_bps",
            ),
            "bond_issue",
        )
        assert issue["operating_months"] == [], "a freshly sized issue reports no months"

        project = fixtures.read_project(api, deal)
        assert_fields(project, "project", development_status="PLANNING")
        assert_nulls(project, ("provisional_fifty_percent_ratio_bps",), "project")

    def test_par_that_fits_the_award_before_the_round_up_is_refused_after_it(self, api):
        """The same award accepts a smaller filing and refuses the boundary one.

        The award is set to exactly the unrounded par of the first filing,
        199,920,000, so every step of that sizing fits the award until the
        denomination round-up pushes par 80,000 above it. The comparison is against
        the rounded par alone, which the second filing proves: eligible cost
        189,000,000 sizes to 199,000,000 and is accepted against the same untouched
        award. The refused call must leave no issue behind and must not move the
        allocation or the pool.

        PRD: "Because the denomination step rounds par up, a deal that fits its award before rounding can fail after it, and that is exactly what the next check catches: the solved `par_amount_cents` must be no greater than the referenced allocation's `awarded_amount_cents`, and an overshoot is `ERR_PAR_EXCEEDS_CAP_AWARD`."
        PRD: "Awarding a request moves it `PENDING` → `AWARDED`, stamps `awarded_amount_cents`, `expiry_date` and `decided_by_user_id` from the acting `X-User-ID`, and re-derives the pool: `reserved_cents` drops by this allocation's `requested_amount_cents`, `committed_cents` rises by the `awarded_amount_cents`, `available_cents` and `awardable_cents` follow from those two, `pool_status` is re-derived, and the pool's `version` increments by 1."

        Design: Corner/validations/par_that_fits_before_the_denomination_round_up_fails_after_it
        """
        deal = fixtures.setup_awarded_cap(
            api, award_overrides={"awarded_amount_cents": 199920000}
        )

        validate_error(
            api.create_bond_issue(
                deal.developer_headers,
                **factories.bond_issue_payload(deal.project_id, deal.allocation_id)
            ),
            ApiErrorId.ERR_PAR_EXCEEDS_CAP_AWARD,
            422,
        )

        accepted = validate_success(
            api.create_bond_issue(
                deal.developer_headers,
                **factories.bond_issue_payload(
                    deal.project_id,
                    deal.allocation_id,
                    eligible_cost_cents=189000000,
                )
            ),
            201,
        )
        assert_fields(
            accepted,
            "bond_issue",
            par_amount_cents=199000000,
            issuance_allowance_cents=3900000,
            negative_arbitrage_allowance_cents=3980000,
            status="DRAFT",
        )
        assert_bond_sizing(accepted)

        assert_page(
            api.list_bond_issues(TRUSTEE, project_id=deal.project_id),
            total_count=1,
        )

        allocation = fixtures.read_allocation(api, deal)
        assert_fields(
            allocation,
            "allocation",
            status="AWARDED",
            awarded_amount_cents=199920000,
        )
        assert_pool_ledger(
            fixtures.read_pool(api, deal),
            reserved_cents=0,
            committed_cents=199920000,
        )


class TestClosingTheIssue:
    """The four closing preconditions and the provisional fifty-percent gate."""

    def test_issuance_waits_on_the_agreement_reaching_recorded(self, api):
        """A byte-identical issue request fails, then succeeds, on a sibling's state.

        The gate lives on the regulatory agreement rather than on the issue, and it
        is the compliance officer who opens it while the trustee is the one blocked.
        Nothing about the issue, the award or the development changes between the two
        attempts — only the agreement's status — and the second attempt then carries
        out all five effects of a closing at once.

        PRD: "the development must have a regulatory agreement in `RECORDED`, and neither `DRAFT` nor `AMENDMENT_PENDING` nor `RELEASED` will do, or the attempt is `ERR_REG_AGREEMENT_NOT_RECORDED`"
        PRD: "A successful closing therefore does five things at once. It moves the issue `DRAFT` → `ISSUED` and stamps `closing_date`. It writes the computed ratio to the development's `provisional_fifty_percent_ratio_bps` and sets `automatic_credit_triggered` to whether that ratio reached 5,000 basis points. It moves the development's development axis `PLANNING` → `FINANCED`. It moves the referenced cap allocation `AWARDED` → `COMMITTED`, which re-derives the pool's `reserved_cents`, `committed_cents`, `available_cents`, `awardable_cents` and `pool_status`."
        PRD: "There is no idempotent replay anywhere in this domain"

        Design: Difficulty/cross_entity_state_dependency/bond_issuance_waits_on_the_regulatory_agreement_reaching_recorded
        """
        deal = fixtures.setup_drafted_agreement(api, project_kind="ten_unit")
        fixtures.setup_cap_request(api, deal)
        fixtures.setup_awarded_cap(api, deal)
        fixtures.setup_sized_bond(api, deal)

        validate_error(
            api.issue_bond_issue(
                deal.bond_issue_id, TRUSTEE, closing_date=constants.CLOSING_DATE
            ),
            ApiErrorId.ERR_REG_AGREEMENT_NOT_RECORDED,
            409,
        )

        blocked = fixtures.read_bond_issue(api, deal)
        assert_fields(blocked, "bond_issue", status="DRAFT")
        assert_nulls(blocked, ("closing_date",), "bond_issue")
        assert_fields(
            fixtures.read_project(api, deal), "project", development_status="PLANNING"
        )
        assert_fields(fixtures.read_allocation(api, deal), "allocation", status="AWARDED")

        recorded = validate_success(
            api.record_regulatory_agreement(
                deal.agreement_id,
                COMPLIANCE_OFFICER,
                instrument_number=constants.INSTRUMENT_NUMBER,
            )
        )
        assert_fields(recorded, "agreement", status="RECORDED")
        assert_fields(
            fixtures.read_project(api, deal), "project", compliance_status="RESTRICTED"
        )

        issued = validate_success(
            api.issue_bond_issue(
                deal.bond_issue_id, TRUSTEE, closing_date=constants.CLOSING_DATE
            )
        )
        assert_fields(issued, "bond_issue", status="ISSUED")
        assert issued["closing_date"].startswith("2026-09-15T00:00:00"), (
            "the closing stamps the supplied instant, got {0}".format(
                issued["closing_date"]
            )
        )

        assert_fields(
            fixtures.read_project(api, deal),
            "project",
            development_status="FINANCED",
            provisional_fifty_percent_ratio_bps=5000,
            automatic_credit_triggered=True,
        )
        assert_fields(
            fixtures.read_allocation(api, deal), "allocation", status="COMMITTED"
        )
        assert_pool_ledger(
            fixtures.read_pool(api, deal),
            reserved_cents=0,
            committed_cents=200000000,
        )

    def test_a_ratio_of_exactly_5000_bps_issues_while_4987_bps_is_refused(self, api):
        """Two developments with the identical filed basis, one denomination apart.

        Both developments file land 40,000,000 and depreciable basis 360,000,000, so
        both carry an aggregate basis of 400,000,000. The first sizes to par
        200,000,000 and lands on exactly 5,000 basis points, which the inclusive
        threshold admits. The second sizes to 199,500,000 — one denomination step
        lower — and lands on floor(4,987.5) = 4,987, so the flooring is what removes
        the half basis point and the closing is refused. The refused closing leaves
        the issue in `DRAFT`, the development unrated and the cap uncommitted.

        PRD: "The ratio is the issue's `par_amount_cents` multiplied by 10,000, divided by the development's `aggregate_basis_cents` — the land cost plus the depreciable basis as filed at creation — with the quotient floored to a whole basis point. The test passes when that ratio is at least 5,000 basis points; the passing side is inclusive, so exactly 5,000 basis points triggers the credit. A ratio below 5,000 basis points refuses the closing outright with `ERR_FIFTY_PERCENT_TEST_FAILED`, on the reasoning that a bond issue that cannot trigger the automatic credit would strand the development."

        Design: Difficulty/boundary_precision_check/fifty_percent_ratio_of_exactly_5000_bps_issues_while_4987_bps_is_refused
        """
        deal = fixtures.ten_unit_deal(api, stage=fixtures.setup_issued_bond)
        assert_fields(
            deal.bond_issue, "bond_issue", par_amount_cents=200000000, status="ISSUED"
        )
        assert_fields(
            fixtures.read_project(api, deal),
            "project",
            provisional_fifty_percent_ratio_bps=5000,
            automatic_credit_triggered=True,
            development_status="FINANCED",
        )

        second = fixtures.file_second_project(api, deal)
        for spec in factories.COMPACT_ROSTER:
            validate_success(
                api.create_unit_restriction(
                    deal.developer_headers, **dict(spec, project_id=second["id"])
                ),
                201,
            )
        second_agreement = validate_success(
            api.create_regulatory_agreement(
                deal.developer_headers, **factories.agreement_payload(second["id"])
            ),
            201,
        )
        validate_success(
            api.record_regulatory_agreement(
                second_agreement["id"], COMPLIANCE_OFFICER, instrument_number="KC-2026-0002"
            )
        )
        second_request = validate_success(
            api.create_volume_cap_allocation(
                deal.developer_headers,
                **factories.cap_request_payload(
                    second["id"], deal.pool_id, requested_amount_cents=199500000
                )
            ),
            201,
        )
        fixtures.award_allocation(
            api, deal, second_request["id"], awarded_amount_cents=199500000
        )
        second_issue = validate_success(
            api.create_bond_issue(
                deal.developer_headers,
                **factories.bond_issue_payload(
                    second["id"], second_request["id"], eligible_cost_cents=189500000
                )
            ),
            201,
        )
        assert_fields(
            second_issue,
            "second_bond_issue",
            par_amount_cents=199500000,
            issuance_allowance_cents=3910000,
        )

        validate_error(
            api.issue_bond_issue(
                second_issue["id"], TRUSTEE, closing_date=constants.CLOSING_DATE
            ),
            ApiErrorId.ERR_FIFTY_PERCENT_TEST_FAILED,
            422,
        )

        refused = validate_success(api.get_bond_issue(second_issue["id"], TRUSTEE))
        assert_fields(refused, "second_bond_issue", status="DRAFT")
        assert_nulls(refused, ("closing_date",), "second_bond_issue")

        second_read = validate_success(
            api.get_project(second["id"], deal.developer_headers)
        )
        assert_fields(
            second_read,
            "second_project",
            aggregate_basis_cents=400000000,
            automatic_credit_triggered=False,
            development_status="PLANNING",
        )
        assert_nulls(
            second_read, ("provisional_fifty_percent_ratio_bps",), "second_project"
        )
        assert_fields(
            validate_success(
                api.get_volume_cap_allocation(second_request["id"], ALLOCATION_OFFICER)
            ),
            "second_allocation",
            status="AWARDED",
        )
        assert_pool_ledger(
            fixtures.read_pool(api, deal),
            reserved_cents=0,
            committed_cents=399500000,
            available_cents=200500000,
        )


class TestReadingTheFinancedDevelopment:
    """What the development read exposes the moment the bonds have closed."""

    def test_the_project_read_after_issuance_exposes_the_provisional_ratio_and_the_status_filter(
        self, api
    ):
        """One read of the financed development, one of its untouched sibling, one list.

        Immediately after closing the development carries exactly one of the two
        fifty-percent ratios: the provisional variant is stamped at 5,000 basis
        points while the final variant waits for an accepted cost certification, and
        the credit flag is set on the provisional pass alone. The same read still has
        to serve every derived roster figure, and the filtered list must return this
        development only — the sponsor's bare second development is untouched by the
        first one's closing even though both are counted as active.

        PRD: "It writes the computed ratio to the development's `provisional_fifty_percent_ratio_bps` and sets `automatic_credit_triggered` to whether that ratio reached 5,000 basis points."
        PRD: "The **unit fraction**, stored as `unit_fraction_bps`, is the number of the development's `RESTRICTED` units multiplied by 10,000, divided by `total_units`, with the quotient floored to a whole basis point."
        PRD: "In all three cases `set_aside_ratio_bps` is the count of qualifying units multiplied by 10,000, divided by `total_units`, floored to a whole basis point."

        Design: Corner/endpoints/project_read_after_issuance_exposes_the_provisional_ratio_and_the_status_filter
        """
        deal = fixtures.setup_issued_bond(api)
        bare = fixtures.file_second_project(api, deal, name="Harborview Terrace")

        financed = validate_success(api.get_project(deal.project_id, TRUSTEE))
        assert_fields(
            financed,
            "project",
            aggregate_basis_cents=400000000,
            provisional_fifty_percent_ratio_bps=5000,
            automatic_credit_triggered=True,
            development_status="FINANCED",
            compliance_status="RESTRICTED",
            set_aside_ratio_bps=5000,
            set_aside_satisfied=True,
        )
        assert_nulls(
            financed,
            (
                "final_fifty_percent_ratio_bps",
                "placed_in_service_date",
                "compliance_start_date",
            ),
            "project",
        )
        assert_unit_counts(financed, restricted=2, market=2, designated=4)
        assert_project_fractions(
            financed, unit_fraction=5000, floor_space_fraction=5000,
            applicable_fraction=5000,
        )

        items, _ = assert_page(
            api.list_projects(
                ALLOCATION_OFFICER,
                developer_id=deal.developer_id,
                development_status="FINANCED",
                limit=10,
                offset=0,
            ),
            total_count=1,
            has_more=False,
        )
        assert items[0]["id"] == deal.project_id, (
            "the FINANCED filter must return the closed development only"
        )

        untouched = validate_success(api.get_project(bare["id"], ALLOCATION_OFFICER))
        assert_fields(untouched, "second_project", automatic_credit_triggered=False)
        assert_nulls(
            untouched, ("provisional_fifty_percent_ratio_bps",), "second_project"
        )

        assert_fields(
            fixtures.read_developer(api, deal), "developer", active_project_count=2
        )


class TestBondLifecycleRefusals:
    """A replayed closing, an unaffordable draw, and a conversion short on occupancy."""

    def test_replayed_issuance_excess_arbitrage_and_weak_occupancy_are_each_refused(
        self, api
    ):
        """One issue priced at an 800 basis point spread, walked to three refusals.

        With a bond yield of 1,000 basis points against an investment yield of 200,
        carrying cost is the binding constraint: a single 181-day draw of the whole
        par projects an accrual of 8,044,444 against an allowance of 4,000,000, so
        funding is refused and the draw stays `APPROVED` with the issue untouched. A
        30-day draw of half the par then accrues 1,333,333 and funds, which is the
        first funding and therefore starts construction. Finally the conversion probe
        isolates the third refusal: trailing-quarter coverage passes at 12,000 basis
        points, but the weakest month houses three of four units — 7,500 basis points
        against a 9,000 floor — so occupancy is the error reported, not coverage.

        PRD: "the issue must be in `DRAFT`, or the attempt is `ERR_BOND_ISSUE_STATE_INVALID`"
        PRD: "A funding attempt projects that series forward to include the draw being funded, and refuses when the projected `negative_arbitrage_cents` would exceed the issue's `negative_arbitrage_allowance_cents`. Equality is allowed; only a strict overshoot is `ERR_NEGATIVE_ARBITRAGE_ALLOWANCE_EXCEEDED`."
        PRD: "that undrawn balance is multiplied by the spread in basis points, divided by 10,000, multiplied by the number of whole days in the draw's half-open period from `period_start` up to but not including `period_end`, and divided by a 360-day year"
        PRD: "If this is the first funded draw on the issue — that is, the issue's `cumulative_funded_cents` was zero immediately before — then the development also moves `FINANCED` → `UNDER_CONSTRUCTION`"
        PRD: "Then stabilization: `min_occupancy_bps` must be at least 9,000 basis points, which is ninety percent physical occupancy in the weakest month of the window, and a shortfall is `ERR_OCCUPANCY_BELOW_STABILIZATION`. Both thresholds are inclusive — exactly 11,500 basis points of coverage and exactly 9,000 basis points of occupancy pass — and when both fail, the coverage failure is the one reported."

        Design: Corner/errors/bond_lifecycle_errors_cover_replayed_issuance_arbitrage_and_weak_occupancy
        """
        deal = fixtures.setup_issued_bond(api, bond_overrides={"bond_yield_bps": 1000})

        validate_error(
            api.issue_bond_issue(
                deal.bond_issue_id, TRUSTEE, closing_date="2026-09-16T00:00:00Z"
            ),
            ApiErrorId.ERR_BOND_ISSUE_STATE_INVALID,
            409,
        )
        replayed = fixtures.read_bond_issue(api, deal)
        assert replayed["closing_date"].startswith("2026-09-15T00:00:00"), (
            "the refused replay must not restamp the closing date, got {0}".format(
                replayed["closing_date"]
            )
        )

        fixtures.submit_draw(
            api,
            deal,
            draw_number=1,
            period_start="2026-09-15T00:00:00Z",
            period_end="2027-03-15T00:00:00Z",
            requested_amount_cents=200000000,
        )
        fixtures.approve_draw(api, deal, 1)
        validate_error(
            api.fund_draw_request(
                deal.draw_id(1), TRUSTEE, funding_date="2026-09-20T00:00:00Z"
            ),
            ApiErrorId.ERR_NEGATIVE_ARBITRAGE_ALLOWANCE_EXCEEDED,
            422,
        )

        unfunded = validate_success(api.get_draw_request(deal.draw_id(1), TRUSTEE))
        assert_fields(
            unfunded,
            "draw",
            status="APPROVED",
            negative_arbitrage_accrual_cents=0,
        )
        assert_nulls(unfunded, ("funding_date",), "draw")

        after_refusal = fixtures.read_bond_issue(api, deal)
        assert_fields(
            after_refusal,
            "bond_issue",
            cumulative_funded_cents=0,
            undrawn_cents=200000000,
            negative_arbitrage_cents=0,
        )
        assert_par_conservation(after_refusal)
        assert_fields(
            fixtures.read_project(api, deal), "project", development_status="FINANCED"
        )

        fixtures.submit_draw(
            api,
            deal,
            draw_number=2,
            period_start="2027-03-15T00:00:00Z",
            period_end="2027-04-14T00:00:00Z",
            requested_amount_cents=100000000,
        )
        fixtures.approve_draw(api, deal, 2)
        funded = fixtures.fund_draw(api, deal, 2, funding_date="2027-03-20T00:00:00Z")
        assert_fields(
            funded, "draw", status="FUNDED", negative_arbitrage_accrual_cents=1333333
        )
        assert_fields(
            deal.bond_issue,
            "bond_issue",
            negative_arbitrage_cents=1333333,
            cumulative_funded_cents=100000000,
            undrawn_cents=100000000,
        )
        assert_par_conservation(deal.bond_issue)
        assert_fields(
            fixtures.read_project(api, deal),
            "project",
            development_status="UNDER_CONSTRUCTION",
        )

        fixtures.record_month(api, deal, 1, occupied_units=3)
        fixtures.record_month(api, deal, 2)
        fixtures.record_month(api, deal, 3)

        validate_error(
            api.convert_bond_issue(
                deal.bond_issue_id,
                TRUSTEE,
                dscr_basis="T3",
                conversion_date="2027-06-01T00:00:00Z",
            ),
            ApiErrorId.ERR_OCCUPANCY_BELOW_STABILIZATION,
            422,
        )

        unconverted = fixtures.read_bond_issue(api, deal)
        assert_fields(unconverted, "bond_issue", status="ISSUED")
        assert_nulls(
            unconverted, ("dscr_bps", "min_occupancy_bps", "conversion_date"), "bond_issue"
        )
        assert_fields(
            fixtures.read_project(api, deal),
            "project",
            development_status="PLACED_IN_SERVICE",
        )


class TestMandatoryRedemption:
    """The unwind, whose effects run development first and then the pool."""

    def test_redemption_withdraws_the_development_then_releases_cap_back_into_the_pool(
        self, api
    ):
        """One redemption on an issued deal with no draws, followed down two links.

        Redemption is a two-link chain on the financing axis. The first link
        withdraws the development and moves the award `COMMITTED` → `RELEASED`; it is
        that allocation transition, not the redemption itself, that drives the second
        link, where the pool's committed figure falls back to zero and the whole
        600,000,000 becomes awardable again. What redemption deliberately does not
        touch is the compliance axis: the recorded covenant survives the financing
        that paid for it, so the development stays `RESTRICTED`.

        PRD: "It stamps `redemption_date` and moves the issue `ISSUED` → `MANDATORY_REDEEMED`, which is terminal."
        PRD: "The development moves to `WITHDRAWN` — from `FINANCED`, from `UNDER_CONSTRUCTION` or from `PLACED_IN_SERVICE`, with the identical effect set in each case — its `automatic_credit_triggered` is set back to false and its `provisional_fifty_percent_ratio_bps` is cleared to null."
        PRD: "The referenced allocation moves `COMMITTED` → `RELEASED`, the pool is re-derived so that `committed_cents` falls by the `awarded_amount_cents`, and deferred allocations of that pool may consequently be reinstated exactly as described in §3.3."

        Design: Difficulty/transitive_cascade/mandatory_redemption_withdraws_the_project_then_releases_cap_back_into_the_pool
        """
        deal = fixtures.ten_unit_deal(api, stage=fixtures.setup_issued_bond)

        redeemed = fixtures.redeem_bond(
            api,
            deal,
            redemption_date="2026-12-01T00:00:00Z",
            reason=(
                "Failure to satisfy the good-costs requirement within the "
                "spend-down period"
            ),
        )
        assert_fields(redeemed, "bond_issue", status="MANDATORY_REDEEMED")
        assert redeemed["redemption_date"].startswith("2026-12-01T00:00:00"), (
            "the redemption stamps the supplied instant, got {0}".format(
                redeemed["redemption_date"]
            )
        )

        assert_fields(
            deal.project,
            "project",
            development_status="WITHDRAWN",
            compliance_status="RESTRICTED",
            automatic_credit_triggered=False,
        )
        assert_nulls(deal.project, ("provisional_fifty_percent_ratio_bps",), "project")
        assert_fields(deal.allocation, "allocation", status="RELEASED")

        assert_pool_ledger(
            deal.pool,
            reserved_cents=0,
            committed_cents=0,
            available_cents=constants.POOL_TOTAL_CAP_CENTS,
            awardable_cents=constants.POOL_TOTAL_CAP_CENTS,
            pool_status="OPEN",
        )
        assert deal.pool["total_cap_cents"] == constants.POOL_TOTAL_CAP_CENTS, (
            "the pool's total cap is untouched by the release"
        )
