"""Multi-input formula conformance: pool sizing (§3.6), the per-usage-line
rounding order of statement line gross amounts (§3.7), and the administration
fee band keyed on each line's own gross amount (§3.7)."""

from test_helpers import (
    CANONICAL_SCHEDULE,
    TEST_DEFAULTS,
    TEST_USERS,
    append_line,
    assert_pool_value_conservation,
    assert_royalty_pool,
    assert_royalty_statement,
    assert_statement_line,
    assert_statement_totals,
    calculate_pool,
    create_batch,
    create_collective,
    create_composition,
    create_effective_schedule,
    create_label,
    create_period,
    create_pool,
    create_publisher,
    create_recording,
    file_and_approve_registration,
    finalize_pool,
    period_version,
    seal_and_match_batch,
    setup_gb_individual_usage,
    statement_payload,
    validate_paginated,
    validate_success,
)

ADMIN_HEADERS = TEST_USERS["royalty_admin_headers"]

# ─── Composite preambles built from the helper atoms ───

_THREE_TIER_SCHEDULES = (
    ("CRB-2026-FAM", "FAMILY"),
    ("CRB-2026-STU", "STUDENT"),
    ("CRB-2026-FREE", "FREE_AD_SUPPORTED"),
)

# tier -> reported plays on the single GB line of that tier
_TIER_LINE_PLAYS = {
    "FAMILY": 200000,
    "STUDENT": 900000,
    "FREE_AD_SUPPORTED": 100000,
}

# tier -> (subscriber_count, gross_revenue_cents) of the GB pool of that tier
_TIER_POOL_INPUTS = {
    "FAMILY": (1400, 1000000),
    "STUDENT": (1, 1000),
    "FREE_AD_SUPPORTED": (100, 10000000),
}


def _setup_three_tier_gb_pools(api):
    """One EFFECTIVE WORLD schedule per tier, one sealed and matched batch
    carrying a single exact-ISRC GB line per tier, and one DRAFT GB pool per
    tier whose three sizing signals rank differently in each tier."""
    for proceeding_ref, tier in _THREE_TIER_SCHEDULES:
        create_effective_schedule(
            api,
            proceeding_ref=proceeding_ref,
            territory_code="WORLD",
            subscription_tier=tier,
            revenue_share_bps=7000,
            per_subscriber_minimum_cents=500,
            mechanical_share_bps=4000,
            performance_share_bps=6000,
            statutory_floor_per_play_millicents=100,
            effective_from=TEST_DEFAULTS["SCHEDULE_EFFECTIVE_FROM"],
            effective_to=TEST_DEFAULTS["SCHEDULE_EFFECTIVE_TO"],
        )

    period = create_period(api)
    recording = create_recording(
        api,
        identifier=TEST_DEFAULTS["RECORDING_A_ISRC"],
        title=TEST_DEFAULTS["RECORDING_A_TITLE"],
        artist=TEST_DEFAULTS["RECORDING_A_ARTIST"],
    )

    batch = create_batch(api, period["id"])
    for tier, plays in _TIER_LINE_PLAYS.items():
        append_line(
            api,
            batch["id"],
            reported_isrc=TEST_DEFAULTS["RECORDING_A_ISRC"],
            reported_title=TEST_DEFAULTS["RECORDING_A_TITLE"],
            territory_code="GB",
            subscription_tier=tier,
            play_count=plays,
        )
    batch_after_match = seal_and_match_batch(api, batch["id"])

    pools = {}
    for tier, (subscriber_count, gross_revenue_cents) in _TIER_POOL_INPUTS.items():
        pools[tier] = create_pool(
            api,
            period["id"],
            territory_code="GB",
            subscription_tier=tier,
            subscriber_count=subscriber_count,
            gross_revenue_cents=gross_revenue_cents,
        )

    return {
        "period": period,
        "recording": recording,
        "batch": batch_after_match,
        "pools": pools,
    }


def _setup_direct_master_statement_inputs(api):
    """The GB/INDIVIDUAL usage preamble with both matched lines resolved by
    exact ISRC and the third line left unresolved, a single WORLD MASTER
    direct-deal claim approved for the label, and the pool FINALIZED."""
    fixture = setup_gb_individual_usage(api, fuzzy_second_line=False, third_line=True)
    fixture["master_registration"] = file_and_approve_registration(
        api,
        fixture["recording_a"]["id"],
        fixture["label"]["id"],
        right_type="MASTER",
        routing="DIRECT",
        share_bps=10000,
        territory_set=["WORLD"],
    )
    pool = create_pool(
        api,
        fixture["period"]["id"],
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        subscriber_count=TEST_DEFAULTS["CANONICAL_SUBSCRIBER_COUNT"],
        gross_revenue_cents=TEST_DEFAULTS["CANONICAL_GROSS_REVENUE_CENTS"],
    )
    calculate_pool(api, pool["id"])
    fixture["pool"] = finalize_pool(api, pool["id"])
    return fixture


def _setup_collective_publishing_statement_inputs(api):
    """The same GB/INDIVIDUAL usage, but the recording is linked to a
    composition whose MECHANICAL (6000 bps) and PERFORMANCE (10000 bps) shares
    are both approved to the same collective, so one statement carries two
    collective-routed lines of different volume."""
    label = create_label(api)
    publisher = create_publisher(api)
    collective = create_collective(api)
    schedule = create_effective_schedule(api, **CANONICAL_SCHEDULE)

    period = create_period(api)
    composition = create_composition(api)
    recording_a = create_recording(
        api,
        identifier=TEST_DEFAULTS["RECORDING_A_ISRC"],
        title=TEST_DEFAULTS["RECORDING_A_TITLE"],
        artist=TEST_DEFAULTS["RECORDING_A_ARTIST"],
        linked_work_id=composition["id"],
    )
    recording_b = create_recording(
        api,
        identifier=TEST_DEFAULTS["RECORDING_B_ISRC"],
        title=TEST_DEFAULTS["RECORDING_B_TITLE"],
        artist=TEST_DEFAULTS["RECORDING_B_ARTIST"],
    )

    batch = create_batch(api, period["id"])
    for plays in (300000, 150000):
        append_line(
            api,
            batch["id"],
            reported_isrc=TEST_DEFAULTS["RECORDING_A_ISRC"],
            reported_title=TEST_DEFAULTS["RECORDING_A_TITLE"],
            reported_artist=TEST_DEFAULTS["RECORDING_A_ARTIST"],
            territory_code="GB",
            subscription_tier="INDIVIDUAL",
            play_count=plays,
        )
    append_line(
        api,
        batch["id"],
        reported_title=TEST_DEFAULTS["RECORDING_B_TITLE"],
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        play_count=50000,
    )
    batch_after_match = seal_and_match_batch(api, batch["id"])

    master_registration = file_and_approve_registration(
        api,
        recording_a["id"],
        label["id"],
        right_type="MASTER",
        routing="DIRECT",
        share_bps=10000,
        territory_set=["WORLD"],
    )
    mechanical_registration = file_and_approve_registration(
        api,
        composition["id"],
        publisher["id"],
        right_type="MECHANICAL",
        routing="COLLECTIVE",
        collective_id=collective["id"],
        share_bps=6000,
        territory_set=["GB"],
    )
    performance_registration = file_and_approve_registration(
        api,
        composition["id"],
        publisher["id"],
        right_type="PERFORMANCE",
        routing="COLLECTIVE",
        collective_id=collective["id"],
        share_bps=10000,
        territory_set=["GB"],
    )

    pool = create_pool(
        api,
        period["id"],
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        subscriber_count=TEST_DEFAULTS["CANONICAL_SUBSCRIBER_COUNT"],
        gross_revenue_cents=TEST_DEFAULTS["CANONICAL_GROSS_REVENUE_CENTS"],
    )
    calculate_pool(api, pool["id"])

    return {
        "label": label,
        "publisher": publisher,
        "collective": collective,
        "schedule": schedule,
        "period": period,
        "composition": composition,
        "recording_a": recording_a,
        "recording_b": recording_b,
        "batch": batch_after_match,
        "master_registration": master_registration,
        "mechanical_registration": mechanical_registration,
        "performance_registration": performance_registration,
        "pool": finalize_pool(api, pool["id"]),
    }


def _build_statement(api, rights_holder_id, period_id):
    """Build a draft statement, reading the period version immediately before."""
    payload = statement_payload(
        rights_holder_id, period_id, period_version(api, period_id)
    )
    return validate_success(api.create_statement(payload, ADMIN_HEADERS), 201)


def _lines(api, statement_id, **filters):
    params = {"statement_id": statement_id}
    params.update(filters)
    lines, _meta = validate_paginated(
        api.list_statement_lines(ADMIN_HEADERS, params=params)
    )
    return lines


# ─── pool_distributable_three_way_min_max_with_cap ─────

class TestPoolDistributableThreeWayMinMaxWithCap:

    def test_revenue_share_wins_when_it_sits_between_the_minimum_and_the_cap(self, api):
        """A GB FAMILY pool whose revenue share equals its per-subscriber minimum and stays under three times that minimum distributes 700000 cents on the REVENUE_SHARE basis.

        PRD: "It is `REVENUE_SHARE` when `revenue_share_pool_cents` is greater than or equal to `minimum_pool_cents`, and greater than or equal to `statutory_floor_cents`, and less than or equal to three times `minimum_pool_cents`."

        Design: Difficulty/combinatorial_formula/pool_distributable_three_way_min_max_with_cap
        """
        fixture = _setup_three_tier_gb_pools(api)

        pool = validate_success(
            api.calculate_pool(fixture["pools"]["FAMILY"]["id"], ADMIN_HEADERS), 200
        )

        assert_royalty_pool(pool)
        assert pool["revenue_share_pool_cents"] == 700000
        assert pool["minimum_pool_cents"] == 700000
        assert pool["statutory_floor_cents"] == 20000
        assert pool["distributable_cents"] == 700000
        assert pool["allocation_basis"] == "REVENUE_SHARE"
        assert_pool_value_conservation(pool)

    def test_statutory_floor_wins_when_it_is_the_largest_of_the_three_signals(self, api):
        """A GB STUDENT pool whose statutory floor towers over both money signals distributes 90000 cents on the STATUTORY_FLOOR basis.

        PRD: "`distributable_cents` is the largest of three quantities: the lesser of `revenue_share_pool_cents` and three times `minimum_pool_cents`; `minimum_pool_cents` itself; and `statutory_floor_cents`."

        Design: Difficulty/combinatorial_formula/pool_distributable_three_way_min_max_with_cap
        """
        fixture = _setup_three_tier_gb_pools(api)

        pool = validate_success(
            api.calculate_pool(fixture["pools"]["STUDENT"]["id"], ADMIN_HEADERS), 200
        )

        assert_royalty_pool(pool)
        assert pool["revenue_share_pool_cents"] == 700
        assert pool["minimum_pool_cents"] == 500
        assert pool["statutory_floor_cents"] == 90000
        assert pool["distributable_cents"] == 90000
        assert pool["allocation_basis"] == "STATUTORY_FLOOR"
        assert_pool_value_conservation(pool)

    def test_cap_binds_the_amount_while_the_basis_still_names_the_minimum(self, api):
        """A GB FREE_AD_SUPPORTED pool whose revenue share runs far past three times its per-subscriber minimum distributes exactly the 150000-cent cap and reports PER_SUBSCRIBER_MINIMUM.

        PRD: "Otherwise it is `PER_SUBSCRIBER_MINIMUM` when `minimum_pool_cents` is greater than or equal to `statutory_floor_cents`."

        Design: Difficulty/combinatorial_formula/pool_distributable_three_way_min_max_with_cap
        """
        fixture = _setup_three_tier_gb_pools(api)

        pool = validate_success(
            api.calculate_pool(
                fixture["pools"]["FREE_AD_SUPPORTED"]["id"], ADMIN_HEADERS
            ),
            200,
        )

        assert_royalty_pool(pool)
        assert pool["revenue_share_pool_cents"] == 7000000
        assert pool["minimum_pool_cents"] == 50000
        assert pool["statutory_floor_cents"] == 10000
        assert pool["distributable_cents"] == 150000
        assert pool["distributable_cents"] != 7000000, (
            "an uncapped maximum over the three signals is not the specified amount"
        )
        assert pool["distributable_cents"] != 10000, (
            "a minimum over the three signals is not the specified amount"
        )
        assert pool["allocation_basis"] == "PER_SUBSCRIBER_MINIMUM"
        assert_pool_value_conservation(pool)


# ─── statement_line_rounding_order_per_usage_line ──────

class TestStatementLineRoundingOrderPerUsageLine:

    def test_master_gross_rounds_each_contributing_usage_line_before_summing(self, api):
        """Two matched usage lines attributed 599999 and 299999 cents collapse into one MASTER line whose gross_cents is 674998, the sum of two separately rounded master slices.

        PRD: "Each contributing usage line's contribution is rounded to a whole cent **first**, and the rounded contributions are then summed into the line's `gross_cents`."

        Design: Difficulty/combinatorial_formula/statement_line_rounding_order_per_usage_line
        """
        fixture = _setup_direct_master_statement_inputs(api)

        statement = _build_statement(
            api, fixture["label"]["id"], fixture["period"]["id"]
        )
        usage_lines = _lines(api, statement["id"], line_type="USAGE")

        assert len(usage_lines) == 1
        line = usage_lines[0]
        assert_statement_line(line)
        assert line["right_type"] == "MASTER"
        assert line["routing"] == "DIRECT"
        assert line["play_count"] == 450000
        assert line["gross_cents"] == 674998
        assert line["gross_cents"] != 674999, (
            "674999 is the value produced by summing the attributed amounts "
            "first and rounding the aggregated base once"
        )

    def test_direct_deal_fee_applies_the_flat_holder_rate_to_that_gross(self, api):
        """The direct-deal MASTER line withholds the label's flat 800 basis points on its 674998-cent gross, giving admin_fee_cents 54000 and net_cents 620998.

        PRD: "On a line whose `routing` is `DIRECT`, the rate is instead the flat `direct_deal_rate_bps` of the payee holder, regardless of volume."

        Design: Difficulty/combinatorial_formula/statement_line_rounding_order_per_usage_line
        """
        fixture = _setup_direct_master_statement_inputs(api)

        statement = _build_statement(
            api, fixture["label"]["id"], fixture["period"]["id"]
        )
        usage_lines = _lines(api, statement["id"], line_type="USAGE")

        assert len(usage_lines) == 1
        line = usage_lines[0]
        assert_statement_line(line)
        assert line["payee_holder_id"] == fixture["label"]["id"]
        assert line["gross_cents"] == 674998
        assert line["admin_fee_cents"] == 54000
        assert line["net_cents"] == 620998

    def test_residual_line_carries_the_pool_rounding_residue_untaxed(self, api):
        """The two cents of attribution residue reach the residual payee as a RESIDUAL line of gross 2, fee 0 and net 2.

        PRD: "When the pool's `residual_payee_holder_id` equals this statement's `rights_holder_id` and the pool's `rounding_residual_cents` is not zero, the statement also carries a residual line: `line_type` `RESIDUAL`, `work_id` null, `right_type` null, `routing` null, `play_count` 0, `share_bps` 10,000, `gross_cents` equal to the pool's `rounding_residual_cents`, `admin_fee_cents` 0, and `net_cents` equal to that same residual."

        Design: Difficulty/combinatorial_formula/statement_line_rounding_order_per_usage_line
        """
        fixture = _setup_direct_master_statement_inputs(api)
        assert fixture["pool"]["rounding_residual_cents"] == 2
        assert fixture["pool"]["residual_payee_holder_id"] == fixture["label"]["id"]

        statement = _build_statement(
            api, fixture["label"]["id"], fixture["period"]["id"]
        )
        residual_lines = _lines(api, statement["id"], line_type="RESIDUAL")

        assert len(residual_lines) == 1
        line = residual_lines[0]
        assert_statement_line(line)
        assert line["gross_cents"] == 2
        assert line["admin_fee_cents"] == 0
        assert line["net_cents"] == 2
        assert line["play_count"] == 0
        assert line["share_bps"] == 10000
        assert line["work_id"] is None
        assert line["right_type"] is None
        assert line["routing"] is None

    def test_statement_header_sums_the_two_materialised_lines(self, api):
        """The label's statement header reports gross 675000, admin fee 54000, net payable 621000 over exactly two lines.

        PRD: "The statement header aggregates its lines: `gross_cents` is the sum of the lines' `gross_cents`, `admin_fee_cents` the sum of their `admin_fee_cents`, `net_payable_cents` the sum of their `net_cents` — which is necessarily `gross_cents` minus `admin_fee_cents` — and `line_count` the number of lines."

        Design: Difficulty/combinatorial_formula/statement_line_rounding_order_per_usage_line
        """
        fixture = _setup_direct_master_statement_inputs(api)

        statement = _build_statement(
            api, fixture["label"]["id"], fixture["period"]["id"]
        )
        all_lines = _lines(api, statement["id"])

        assert_royalty_statement(statement)
        assert statement["gross_cents"] == 675000
        assert statement["admin_fee_cents"] == 54000
        assert statement["net_payable_cents"] == 621000
        assert statement["line_count"] == 2
        assert_statement_totals(statement, all_lines)


# ─── admin_fee_tier_keyed_on_gross_not_net_or_aggregate ─

class TestAdminFeeTierKeyedOnGrossNotNetOrAggregate:

    def test_mechanical_line_takes_the_first_band_on_its_own_gross(self, api):
        """The collective's MECHANICAL line of 54000 cents gross falls in the 1,200 basis point band on its own gross, giving admin_fee_cents 6480 and net_cents 47520.

        PRD: "On a line whose `routing` is `COLLECTIVE`, the rate is 1,200 basis points while `gross_cents` is below 100,000 cents, 900 basis points while `gross_cents` is below 1,000,000 cents, and 600 basis points otherwise."

        Design: Difficulty/combinatorial_formula/admin_fee_tier_keyed_on_gross_not_net_or_aggregate
        """
        fixture = _setup_collective_publishing_statement_inputs(api)

        statement = _build_statement(
            api, fixture["collective"]["id"], fixture["period"]["id"]
        )
        mechanical_lines = _lines(api, statement["id"], right_type="MECHANICAL")

        assert len(mechanical_lines) == 1
        line = mechanical_lines[0]
        assert_statement_line(line)
        assert line["routing"] == "COLLECTIVE"
        assert line["gross_cents"] == 54000
        assert line["admin_fee_cents"] == 6480
        assert line["admin_fee_cents"] != 4860, (
            "4860 is the fee produced by banding this line on the statement's "
            "aggregate gross instead of its own gross"
        )
        assert line["net_cents"] == 47520

    def test_performance_line_takes_the_second_band_on_its_own_gross(self, api):
        """The collective's PERFORMANCE line of 135000 cents gross is charged 900 basis points of that gross, giving admin_fee_cents 12150 and net_cents 122850.

        PRD: "**Second**, `admin_fee_cents` is `gross_cents` multiplied by that rate, divided by 10,000, rounded half up to a whole cent."

        Design: Difficulty/combinatorial_formula/admin_fee_tier_keyed_on_gross_not_net_or_aggregate
        """
        fixture = _setup_collective_publishing_statement_inputs(api)

        statement = _build_statement(
            api, fixture["collective"]["id"], fixture["period"]["id"]
        )
        performance_lines = _lines(api, statement["id"], right_type="PERFORMANCE")

        assert len(performance_lines) == 1
        line = performance_lines[0]
        assert_statement_line(line)
        assert line["routing"] == "COLLECTIVE"
        assert line["gross_cents"] == 135000
        assert line["admin_fee_cents"] == 12150
        assert line["net_cents"] == 122850

    def test_statement_fee_is_the_sum_of_two_separately_banded_lines(self, api):
        """Two lines banded on their own gross amounts sum to a statement admin fee of 18630, not the 17010 that banding the 189000-cent aggregate would produce.

        PRD: "The rule looks circular — the fee band depends on the amount payable, and the amount payable is gross less the fee — and the resolution of that apparent circularity is that the band is keyed on `gross_cents` and never on `net_cents`, in three strictly ordered steps."

        Design: Difficulty/combinatorial_formula/admin_fee_tier_keyed_on_gross_not_net_or_aggregate
        """
        fixture = _setup_collective_publishing_statement_inputs(api)

        statement = _build_statement(
            api, fixture["collective"]["id"], fixture["period"]["id"]
        )
        all_lines = _lines(api, statement["id"])

        assert_royalty_statement(statement)
        assert statement["gross_cents"] == 189000
        assert statement["admin_fee_cents"] == 18630
        assert statement["admin_fee_cents"] != 17010, (
            "17010 is the total produced by banding both lines on the "
            "statement's aggregate gross of 189000"
        )
        assert statement["net_payable_cents"] == 170370
        assert statement["line_count"] == 2
        assert_statement_totals(statement, all_lines)
