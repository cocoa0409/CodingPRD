"""Branch performance scoring: the two instruments, their history window and its guards."""

from test_helpers import (
    APPROVER,
    STRATEGIST,
    ApiErrorId,
    api_client,
    branch_payload,
    make_branch_manager_headers,
    performance_snapshot_payload,
    read_branch,
    receiving_branch_payload,
    record_snapshot,
    setup_market,
    validate_error,
    validate_success,
)

RIVERBEND = {
    "name": "Riverbend North",
    "region_code": "MW-04",
    "population": 120000,
    "median_household_income_cents": 8500000,
    "deposit_market_total_cents": 240000000000,
    "competitor_branch_count": 24,
    "household_growth_pct_bps": 350,
    "digital_penetration_bps": 5200,
}

DETERIORATING_HISTORY = [
    {
        "period_label": "2025-Q4",
        "period_end_date": "2025-12-31",
        "deposits_cents": 9600000000,
        "transaction_count": 8100,
        "digital_active_bps": 7200,
        "revenue_cents": 300000000,
        "noninterest_expense_cents": 165000000,
    },
    {
        "period_label": "2026-Q1",
        "period_end_date": "2026-03-31",
        "deposits_cents": 7200000000,
        "transaction_count": 6300,
        "digital_active_bps": 6400,
        "revenue_cents": 240000000,
        "noninterest_expense_cents": 156000000,
    },
    {
        "period_label": "2026-Q2",
        "period_end_date": "2026-06-30",
        "deposits_cents": 4800000000,
        "transaction_count": 3600,
        "digital_active_bps": 5400,
        "revenue_cents": 140000000,
        "noninterest_expense_cents": 120000000,
    },
]


def _deteriorating_branch() -> dict:
    """Riverbend North branch with three steadily worsening reporting periods."""
    market = setup_market(**RIVERBEND)
    branch = validate_success(
        api_client.create_branch(
            branch_payload(
                market["id"],
                monthly_transaction_count=3600,
                annual_revenue_cents=140000000,
            ),
            STRATEGIST,
        ),
        expected_status=201,
    )
    periods = [
        record_snapshot(branch["id"], **period) for period in DETERIORATING_HISTORY
    ]
    return {"market": market, "branch": branch, "periods": periods}


def test_01_the_point_in_time_instrument_reports_only_the_newest_period():
    """On a three-period history the point-in-time read returns the newest period's composite
    and its band, ignoring the two better periods before it.

    PRD: "Under `POINT_IN_TIME` the branch's `performance_score_bps` is exactly the `composite_score_bps` of the single newest snapshot; the two prior periods are ignored entirely."
    PRD: "The response reports `branch_id`, the `scoring_variant` actually applied, the resulting `performance_score_bps` and `performance_band`, and the `contributing_snapshot_count` — one under the point-in-time variant, and up to three under the trailing blend."
    Design: Difficulty/dual_variant_calc/branch_score_point_in_time_vs_trailing_blend_band_divergence
    """
    ctx = _deteriorating_branch()
    newest = ctx["periods"][-1]
    assert newest["composite_score_bps"] == 3332
    assert newest["band"] == "WATCH"

    scored = validate_success(
        api_client.get_branch_performance_score(
            ctx["branch"]["id"], STRATEGIST, {"scoring_variant": "POINT_IN_TIME"}
        )
    )

    assert scored["branch_id"] == ctx["branch"]["id"]
    assert scored["scoring_variant"] == "POINT_IN_TIME"
    assert scored["performance_score_bps"] == 3332
    assert scored["performance_band"] == "WATCH"
    assert scored["contributing_snapshot_count"] == 1


def test_02_the_trailing_blend_instrument_smooths_the_same_history_into_another_band():
    """The blend of the same three periods lands 1896 basis points above the point-in-time
    figure and in a different band, and it is the figure the branch persists.

    PRD: "Under `TRAILING_BLEND` the three newest snapshots are blended at weights of 5000, 3000 and 2000 basis points respectively, taken as a prefix of that weight list truncated to however many snapshots actually exist and then renormalised: multiply each available snapshot's `composite_score_bps` by its weight, sum those products, divide by the sum of the weights actually used, and round half up."
    PRD: "Each snapshot composite entering the blend is **already** rounded from the four-factor step, and the blend rounds exactly once more — no other rounding order is permitted, and for identical snapshot histories the two variants routinely produce different scores and can produce different bands."
    Design: Difficulty/dual_variant_calc/branch_score_point_in_time_vs_trailing_blend_band_divergence
    """
    ctx = _deteriorating_branch()

    blended = validate_success(
        api_client.get_branch_performance_score(
            ctx["branch"]["id"], STRATEGIST, {"scoring_variant": "TRAILING_BLEND"}
        )
    )
    point_in_time = validate_success(
        api_client.get_branch_performance_score(
            ctx["branch"]["id"], STRATEGIST, {"scoring_variant": "POINT_IN_TIME"}
        )
    )

    assert blended["performance_score_bps"] == 5228
    assert blended["performance_band"] == "STABLE"
    assert blended["contributing_snapshot_count"] == 3
    assert (
        blended["performance_score_bps"] - point_in_time["performance_score_bps"] == 1896
    )

    branch = read_branch(ctx["branch"]["id"])
    assert branch["performance_score_bps"] == 5228
    assert branch["performance_band"] == "STABLE"
    assert branch["snapshot_count"] == 3


def test_03_a_two_period_blend_renormalizes_over_the_weights_actually_used():
    """With only two periods on file the weight vector is truncated and the divisor is the
    8000 basis points actually used, never padded back out to 10000.

    PRD: "With only two snapshots the weights used are 5000 and 3000 and the divisor is 8000; with one snapshot the blend degenerates to that snapshot's composite."
    PRD: "The four factors are blended into `composite_score_bps` at fixed weights — 35 percent deposits, 20 percent transactions, 15 percent digital adoption and 30 percent profitability."
    Design: Corner/calculations/branch_score_trailing_blend_renormalizes_a_two_snapshot_prefix
    """
    market = setup_market()
    branch = validate_success(
        api_client.create_branch(
            branch_payload(
                market["id"], branch_code="RB-201", scoring_variant="TRAILING_BLEND"
            ),
            STRATEGIST,
        ),
        expected_status=201,
    )

    older = record_snapshot(branch["id"])
    newer = record_snapshot(
        branch["id"],
        period_label="2026-Q2",
        period_end_date="2026-06-30",
        deposits_cents=12000000000,
        transaction_count=9000,
        digital_active_bps=6000,
        revenue_cents=40000000,
        noninterest_expense_cents=20000000,
    )

    assert older["composite_score_bps"] == 4535
    assert newer["composite_score_bps"] == 9400

    scored = read_branch(branch["id"])
    assert scored["performance_score_bps"] == 7576
    assert scored["performance_band"] == "CORE"

    on_demand = validate_success(
        api_client.get_branch_performance_score(branch["id"], STRATEGIST)
    )
    assert on_demand["performance_score_bps"] == 7576
    assert on_demand["contributing_snapshot_count"] == 2


def test_04_naming_a_variant_on_the_read_leaves_the_persisted_score_alone():
    """A branch scored point-in-time by ingestion can be read under the blend on demand: the
    read returns the other instrument's figure without touching the stored one.

    PRD: "Alongside the persisted figures, the system offers an on-demand scoring capability: a `NetworkStrategist`, `ConsolidationApprover`, `NetworkOpsAdmin` or the branch's own `BranchManager` may request a branch's score under an explicitly named `scoring_variant` without persisting anything."
    PRD: "The branch row is not mutated and its `version` does not move."
    Design: Corner/calculations/performance_score_query_variant_overrides_persisted_variant_without_writing
    """
    market = setup_market()
    branch = validate_success(
        api_client.create_branch(
            branch_payload(
                market["id"], branch_code="RB-202", scoring_variant="POINT_IN_TIME"
            ),
            STRATEGIST,
        ),
        expected_status=201,
    )
    record_snapshot(branch["id"])
    record_snapshot(
        branch["id"],
        period_label="2026-Q2",
        period_end_date="2026-06-30",
        deposits_cents=12000000000,
        transaction_count=9000,
        digital_active_bps=6000,
        revenue_cents=40000000,
        noninterest_expense_cents=20000000,
    )
    persisted = read_branch(branch["id"])

    queried = validate_success(
        api_client.get_branch_performance_score(
            branch["id"], APPROVER, {"scoring_variant": "TRAILING_BLEND"}
        )
    )
    assert queried["performance_score_bps"] == 7576
    assert queried["scoring_variant"] == "TRAILING_BLEND"
    assert queried["contributing_snapshot_count"] == 2

    after = read_branch(branch["id"])
    assert after["performance_score_bps"] == 9400
    assert after["performance_band"] == "CORE"
    assert after["scoring_variant"] == "POINT_IN_TIME"
    assert after["version"] == persisted["version"]

    fallback = validate_success(
        api_client.get_branch_performance_score(branch["id"], APPROVER)
    )
    assert fallback["performance_score_bps"] == 9400
    assert fallback["scoring_variant"] == "POINT_IN_TIME"


def test_05_scoring_a_branch_with_no_reporting_history_is_refused():
    """Both instruments are undefined over an empty history, so the on-demand score is
    refused while the branch row itself stays readable and unscored.

    PRD: "Requesting this for a branch whose `snapshot_count` is zero is rejected with `ERR_NO_PERFORMANCE_HISTORY`, since there is nothing to blend."
    PRD: "A branch with no snapshots at all is a fifth case — its `performance_band` reads `UNSCORED` and its `performance_score_bps` is null, because both variants are undefined over an empty history."
    Design: Corner/validations/performance_score_for_a_branch_with_no_snapshots_returns_no_performance_history
    """
    market = setup_market()
    branch = validate_success(
        api_client.create_branch(
            branch_payload(market["id"], branch_code="RB-801"), STRATEGIST
        ),
        expected_status=201,
    )
    assert branch["performance_band"] == "UNSCORED"

    validate_error(
        api_client.get_branch_performance_score(branch["id"], STRATEGIST),
        ApiErrorId.ERR_NO_PERFORMANCE_HISTORY.value,
    )
    validate_error(
        api_client.get_branch_performance_score(
            branch["id"], STRATEGIST, {"scoring_variant": "POINT_IN_TIME"}
        ),
        ApiErrorId.ERR_NO_PERFORMANCE_HISTORY.value,
    )

    readable = read_branch(branch["id"])
    assert readable["performance_score_bps"] is None
    assert readable["performance_band"] == "UNSCORED"


def test_06_a_branch_manager_may_score_and_report_only_their_own_branch():
    """The manager's authority is scoped to the branch they are: the identical request is
    accepted for their own branch and refused for a peer in the same trade area, on the
    write and on the read alike.

    PRD: "Recording a reporting period for a branch is available to a `NetworkStrategist` for any branch and to a `BranchManager` for their own branch only."
    PRD: "5. **Branch ownership for a `BranchManager`** — `ERR_BRANCH_OWNERSHIP_REQUIRED`, on recording a performance period for a branch and on the on-demand performance score of a branch."
    Design: Corner/rbac/branch_manager_snapshot_for_a_peer_branch_returns_403
    """
    market = setup_market()
    own = validate_success(
        api_client.create_branch(branch_payload(market["id"]), STRATEGIST),
        expected_status=201,
    )
    peer = validate_success(
        api_client.create_branch(receiving_branch_payload(market["id"]), STRATEGIST),
        expected_status=201,
    )
    manager = make_branch_manager_headers(own["id"])

    period = validate_success(
        api_client.create_performance_snapshot(
            own["id"],
            performance_snapshot_payload(
                period_label="2026-Q2", period_end_date="2026-06-30"
            ),
            manager,
        ),
        expected_status=201,
    )
    assert period["composite_score_bps"] == 4535
    assert period["band"] == "STABLE"
    assert "version" not in period

    validate_error(
        api_client.create_performance_snapshot(
            peer["id"],
            performance_snapshot_payload(
                period_label="2026-Q2",
                period_end_date="2026-06-30",
                deposits_cents=9600000000,
                transaction_count=8100,
                digital_active_bps=6100,
                revenue_cents=96000000,
                noninterest_expense_cents=52000000,
            ),
            manager,
        ),
        ApiErrorId.ERR_BRANCH_OWNERSHIP_REQUIRED.value,
    )
    validate_error(
        api_client.get_branch_performance_score(
            peer["id"], manager, {"scoring_variant": "POINT_IN_TIME"}
        ),
        ApiErrorId.ERR_BRANCH_OWNERSHIP_REQUIRED.value,
    )

    untouched = read_branch(peer["id"])
    assert untouched["snapshot_count"] == 0
    assert untouched["performance_band"] == "UNSCORED"

    own_score = validate_success(
        api_client.get_branch_performance_score(
            own["id"], manager, {"scoring_variant": "POINT_IN_TIME"}
        )
    )
    assert own_score["performance_score_bps"] == 4535
    assert own_score["performance_band"] == "STABLE"
    assert own_score["contributing_snapshot_count"] == 1

    scored = read_branch(own["id"])
    assert scored["snapshot_count"] == 1
    assert scored["performance_score_bps"] == 4535
