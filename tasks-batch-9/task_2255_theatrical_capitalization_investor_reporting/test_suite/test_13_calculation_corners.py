"""
The arithmetic corners: empty input sets, rounding ties, and signed residues.

Each figure here is chosen so that a plausible wrong implementation — an
unfiltered sum, a truncation, a hard-coded constant, a single rounding at the
end — reports a different number than the documented procedure does.
"""

from typing import Dict, List, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from test_helpers import (
    COMPTROLLER_HEADERS,
    GM_HEADERS,
    PRODUCER_HEADERS,
    ApiClient,
    World,
    factories,
    fixtures,
)

UNIT_PRICE_CENTS = 40_000_000


def _three_investor_offering(api: ApiClient) -> Tuple[World, List[str]]:
    """Three one-unit accounts under a single 40,000,000-per-unit instrument."""
    world = fixtures.base_world(api)
    fixtures.open_offering(world)
    fixtures.with_effective_document(
        world,
        offering_amount_cents=120_000_000,
        unit_price_cents=UNIT_PRICE_CENTS,
        max_investors=3,
    )
    investor_ids: List[str] = []
    for index in range(3):
        investor_id = fixtures.new_accredited_investor(
            world,
            legal_name=f"Investor {index + 1}",
            contact_email=f"investor{index + 1}@example.com",
        )
        investor_ids.append(investor_id)
        fixtures.accept_subscription(
            world, fixtures.new_subscription(world, investor_id, units=1)
        )
    fixtures.capitalize(world)
    return world, investor_ids


def _accounts_by_investor(api: ApiClient, world: World) -> Dict[str, dict]:
    rows, meta = validate_paginated(
        api.list_investor_accounts(
            COMPTROLLER_HEADERS, {"production_id": world.production_id}
        )
    )
    assert meta["total_count"] == len(rows)
    return {row["investor_id"]: row for row in rows}


class TestEmptyParticipantSet:
    """The fixed-gross sum over no participants is 0, not a zero-value row."""

    def test_a_week_with_no_participants_keeps_its_whole_royalty_base(
        self, api: ApiClient
    ):
        """The royalty base becomes operating profit untouched, and nothing is allocated.

        "Under the **fixed-gross variant** — the structure every production starts
        in — `royalty_pool_cents` is the sum, over each participant in the ordered
        set, of that participant's `fixed_gross_pct` applied to the wrap's
        `adjusted_gross_cents` and rounded half up to whole cents *per
        participant* before summing."

        "If the wrap's `royalty_pool_cents` is 0, or the point total is 0, or the
        eligible set is empty, **no allocation rows are created at all** and the
        split stops."

        Design: Corner/calculations/fixed_gross_certification_with_no_participants_yields_zero_pool
        """
        world = fixtures.running_world(api)
        fixtures.with_submitted_standard_week(world)
        wrap_id = world.wrap_id or ""

        certified = fixtures.certify_wrap(world, wrap_id)
        assert certified["status"] == "CERTIFIED"
        assert certified["certified_by_user_id"] == fixtures.CERTIFIER_USER_ID
        assert certified["submitted_by_user_id"] == fixtures.SUBMITTER_USER_ID
        assert certified["royalty_basis_applied"] == "FIXED_GROSS"
        assert certified["royalty_pool_cents"] == 0
        assert certified["weekly_operating_profit_cents"] == 28_250_000
        assert certified["deferred_royalty_added_cents"] == 0
        assert certified["version"] == 3

        _, meta = validate_paginated(
            api.list_royalty_allocations(COMPTROLLER_HEADERS, {"wrap_id": wrap_id})
        )
        assert meta["total_count"] == 0

        production = world.production()
        assert production["recouped_amount_cents"] == 28_250_000
        assert production["recoupment_pct"] == 0.2354
        assert production["distributable_cash_cents"] == 28_250_000
        assert production["deferred_royalty_cents"] == 0
        assert production["version"] == 8


class TestBudgetRollupInputSets:
    """One roll-up counts every line; the other counts only the committed ones."""

    def test_committing_one_of_three_lines_moves_only_the_narrower_rollup(
        self, api: ApiClient
    ):
        """75,000,000 planned in total, of which 40,000,000 is now committed.

        "`budget_total_cents` becomes the sum of `amount_cents` over every budget
        line of the production whose `commitment_status` is `PLANNED`,
        `COMMITTED`, or `SPENT` — that is, over all of them, because lines are
        never soft-deleted. `budget_committed_cents` becomes the narrower sum of
        `amount_cents` over the lines whose `commitment_status` is `COMMITTED` or
        `SPENT`."

        Design: Corner/calculations/capitalization_rollup_input_set_filtering
        """
        world = fixtures.base_world(api)
        approved = get_success_data(
            api.approve_budget(world.production_id, PRODUCER_HEADERS), 200
        )
        assert approved["budget_status"] == "APPROVED"

        line_ids = []
        for component, description, amount in (
            ("PRODUCTION", "Scenery build", 40_000_000),
            ("REHEARSAL", "Rehearsal salaries", 15_000_000),
            ("RESERVE", "Closing reserve", 20_000_000),
        ):
            line_ids.append(
                get_success_data(
                    api.create_budget_line(
                        factories.budget_line_payload(
                            world.production_id,
                            amount,
                            world.production_version(),
                            component=component,
                            description=description,
                        ),
                        GM_HEADERS,
                    ),
                    201,
                )["id"]
            )

        committed = get_success_data(
            api.commit_budget_line(line_ids[0], GM_HEADERS), 200
        )
        assert committed["commitment_status"] == "COMMITTED"
        assert committed["version"] == 2

        production = world.production()
        assert production["budget_total_cents"] == 75_000_000
        assert production["budget_committed_cents"] == 40_000_000
        assert production["budget_status"] == "APPROVED"
        assert production["version"] == 6

        _, planned_meta = validate_paginated(
            api.list_budget_lines(
                GM_HEADERS,
                {"production_id": world.production_id, "commitment_status": "PLANNED"},
            )
        )
        assert planned_meta["total_count"] == 2

        committed_rows, committed_meta = validate_paginated(
            api.list_budget_lines(
                GM_HEADERS,
                {"production_id": world.production_id, "commitment_status": "COMMITTED"},
            )
        )
        assert committed_meta["total_count"] == 1
        assert committed_rows[0]["id"] == line_ids[0]


class TestRecoupmentPercentagePrecision:
    """A ledger that lands exactly on the fourth-decimal tie must round up."""

    def test_a_tie_at_the_fourth_decimal_rounds_away_from_zero(self, api: ApiClient):
        """28,254,000 of 120,000,000 is 0.235450 exactly and must publish as 0.2355.

        "Its `recoupment_pct` is `recouped_amount_cents` divided by
        `capitalization_target_cents`, rounded half up to four decimals."

        Design: Corner/calculations/recoupment_pct_uses_round_half_up_at_four_decimals
        """
        world = fixtures.running_world(api)
        fixtures.with_submitted_standard_week(world, running_expenses_cents=33_496_000)
        certified = fixtures.certify_wrap(world, world.wrap_id or "")

        assert certified["royalty_base_cents"] == 28_254_000
        assert certified["weekly_operating_profit_cents"] == 28_254_000

        production = world.production()
        assert production["recouped_amount_cents"] == 28_254_000
        # Truncation or half-even would report 0.2354 here.
        assert production["recoupment_pct"] == 0.2355

        report = get_success_data(
            api.get_recoupment_report(world.production_id, COMPTROLLER_HEADERS), 200
        )
        assert report["cash_basis_recouped_cents"] == 28_254_000
        assert report["cash_basis_recoupment_pct"] == 0.2355
        assert report["accrual_basis_recouped_cents"] == 28_254_000
        assert report["accrual_basis_recoupment_pct"] == 0.2355
        assert report["recoupment_status"] == "UNRECOUPED"
        assert report["deferred_royalty_cents"] == 0


class TestOwnershipResidue:
    """Three equal accounts cannot split 1.000000 evenly at six decimals."""

    def test_the_shortfall_is_pinned_to_the_first_ordered_account(
        self, api: ApiClient
    ):
        """Two accounts read 0.333333 and the first reads 0.333334.

        "Otherwise each account's `ownership_pct` is its own `units_total` divided
        by the production-wide total, rounded half up to six decimals. The rounded
        shares are then reconciled: subtract their sum from 1.000000 and add the
        signed difference — which may be negative — to the first account in the
        order, that is, to the account with the largest `units_total`, or the
        earliest-created among those tied for largest."

        Design: Corner/calculations/ownership_allocation_residue_across_three_equal_accounts
        """
        world, investor_ids = _three_investor_offering(api)
        accounts = _accounts_by_investor(api, world)
        assert len(accounts) == 3

        assert accounts[investor_ids[0]]["ownership_pct"] == 0.333334
        assert accounts[investor_ids[1]]["ownership_pct"] == 0.333333
        assert accounts[investor_ids[2]]["ownership_pct"] == 0.333333
        assert (
            round(sum(row["ownership_pct"] for row in accounts.values()), 6)
            == 1.000000
        )

        for account in accounts.values():
            assert account["units_total"] == 1
            assert account["contributed_cents"] == UNIT_PRICE_CENTS
            assert account["basis"] == "RECOUPMENT_RETURN"
            assert account["recoupment_credited_cents"] == 0
            assert account["declared_distribution_cents"] == 0
            assert account["distributions_paid_cents"] == 0

        production = world.production()
        assert production["capital_raised_cents"] == 120_000_000
        assert production["active_investor_count"] == 3
        assert production["offering_status"] == "CAPITALIZED"
        assert production["version"] == 6


class TestDistributionResidue:
    """An odd declaration over three equal accounts leaves one cent over."""

    def test_the_odd_cent_lands_on_the_first_ordered_account_only(
        self, api: ApiClient
    ):
        """Two accounts are owed 3,333,330 and the first is owed 3,333,341.

        "Compute each surviving account's share as the distribution's
        `total_amount_cents` multiplied by that account's `ownership_pct`,
        rounded half up to whole cents — each share rounded first. Subtract the
        sum of those rounded shares from `total_amount_cents` and add the signed
        residue to the first account in the order."

        Design: Corner/calculations/distribution_waterfall_pushes_signed_residue_onto_first_account
        """
        world, investor_ids = _three_investor_offering(api)
        fixtures.with_active_operating_budget(world)
        fixtures.advance_operating_status(world, "REHEARSAL", "PREVIEWS", "RUNNING")
        fixtures.with_submitted_standard_week(world)
        fixtures.certify_wrap(world, world.wrap_id or "")
        assert world.production()["distributable_cash_cents"] == 28_250_000

        declared = get_success_data(
            fixtures.declare_distribution(world, 10_000_001), 201
        )
        assert declared["status"] == "DECLARED"
        breakdown = declared["allocation_breakdown"]
        assert len(breakdown) == 3

        amounts = {entry["investor_id"]: entry["amount_cents"] for entry in breakdown}
        assert amounts[investor_ids[0]] == 3_333_341
        assert amounts[investor_ids[1]] == 3_333_330
        assert amounts[investor_ids[2]] == 3_333_330
        assert sum(amounts.values()) == 10_000_001

        accounts = _accounts_by_investor(api, world)
        assert accounts[investor_ids[0]]["declared_distribution_cents"] == 3_333_341
        assert accounts[investor_ids[0]]["distributions_paid_cents"] == 0
        assert accounts[investor_ids[1]]["declared_distribution_cents"] == 3_333_330
        assert accounts[investor_ids[2]]["declared_distribution_cents"] == 3_333_330

        production = world.production()
        assert production["distributed_total_cents"] == 10_000_001
        assert production["distributable_cash_cents"] == 18_249_999
        assert production["version"] == 11


class TestConfiguredSubsidiaryRightsShare:
    """The licensing multiplier is the production's own term, not the default."""

    def test_the_configured_quarter_share_is_applied_and_rounds_up_at_the_half_cent(
        self, api: ApiClient
    ):
        """12,345,679 at 0.25 is 3,086,419.75, which publishes as 3,086,420.

        "Allocation computes `investor_share_cents` as the row's
        `gross_income_cents` multiplied by the production's
        `subsidiary_rights_investor_share_pct`, read from the production at that
        moment, and rounded half up to whole cents."

        Design: Corner/calculations/subsidiary_rights_share_reads_the_production_constant
        """
        world = fixtures.capitalized_world(
            api, subsidiary_rights_investor_share_pct=0.25
        )
        assert world.production()["subsidiary_rights_investor_share_pct"] == 0.25
        before_version = world.production_version()

        income = fixtures.with_recorded_income(
            world, gross_income_cents=12_345_679, source="FILM_LICENSE"
        )
        assert income["investor_share_cents"] == 0

        allocated = get_success_data(
            api.allocate_subsidiary_rights_income(income["id"], COMPTROLLER_HEADERS), 200
        )
        # The 0.4 default would have produced 4,938,272, and truncation 3,086,419.
        assert allocated["investor_share_cents"] == 3_086_420
        assert allocated["status"] == "ALLOCATED"

        production = world.production()
        assert production["recouped_amount_cents"] == 3_086_420
        assert production["recoupment_pct"] == 0.0257
        assert production["distributable_cash_cents"] == 3_086_420
        assert production["version"] == before_version + 1


class TestFrozenSettlementVariant:
    """Certification reads the basis at that instant, not at submission."""

    def test_a_conversion_after_submission_settles_the_week_on_the_pool_variant(
        self, api: ApiClient
    ):
        """The same stored inputs owe 9,887,500 under POOL and 0 under FIXED_GROSS.

        "On certification the wrap's `royalty_basis_applied` is frozen to whatever
        the production's `royalty_basis` reads at that instant, and that frozen
        value selects between two settlement variants that produce genuinely
        different numbers from identical inputs."

        Design: Corner/calculations/royalty_basis_applied_is_frozen_at_certification
        """
        world = fixtures.running_world(api)
        fixtures.with_submitted_standard_week(world)
        wrap_id = world.wrap_id or ""
        submitted = get_success_data(api.get_weekly_wrap(wrap_id, GM_HEADERS), 200)
        assert submitted["royalty_basis_applied"] is None

        converted = get_success_data(
            api.convert_royalties_to_pool(world.production_id, PRODUCER_HEADERS), 200
        )
        assert converted["royalty_basis"] == "POOL"

        certified = fixtures.certify_wrap(world, wrap_id)
        assert certified["royalty_basis_applied"] == "POOL"
        # 28,250,000 * 0.35, floored at an empty guarantee sum and capped at the base.
        assert certified["royalty_pool_cents"] == 9_887_500
        assert certified["weekly_operating_profit_cents"] == 18_362_500
        assert certified["deferred_royalty_added_cents"] == 0

        _, meta = validate_paginated(
            api.list_royalty_allocations(GM_HEADERS, {"wrap_id": wrap_id})
        )
        assert meta["total_count"] == 0

        production = world.production()
        assert production["royalty_basis"] == "POOL"
        assert production["total_pool_points"] == 0
        assert production["recouped_amount_cents"] == 18_362_500
        assert production["recoupment_pct"] == 0.1530
        assert production["version"] == 9
