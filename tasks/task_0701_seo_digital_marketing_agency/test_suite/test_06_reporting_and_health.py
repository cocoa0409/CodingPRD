"""Reporting: rank momentum, traffic window filtering, and account health scoring.

Covers queue A combinatorial_formula (account health three-input clamp) and the
queue B calculations / cross_cutting corner instances on reports and health.
"""
from test_helpers import (
    validate_success,
    get_success_data,
    api_client,
    TEST_USERS,
    factories,
    fixtures,
)

ADMIN = TEST_USERS["agency_admin_headers"]
AM = TEST_USERS["account_manager_headers"]


def _setup_health_scenario():
    """ACTIVE client, one TRACKING keyword (snapshots 50 -> 10), a LIVE campaign with
    one OPEN dispute (open_dispute_count 1). Returns (client, keyword)."""
    fixtures.set_clock("2026-04-01T00:00:00Z")
    client, retainer = fixtures.create_active_client_with_active_retainer(
        client_overrides={"company_name": "Health Co", "primary_domain": "health.example"},
        retainer_overrides={"monthly_credits": 20},
    )
    keyword = fixtures.create_tracking_keyword(
        client["id"], phrase="best seo agency", search_volume=1000, difficulty=40
    )
    fixtures.add_snapshot(keyword["id"], position=50, organic_traffic=100,
                          observed_at="2026-04-05T00:00:00Z")
    fixtures.add_snapshot(keyword["id"], position=10, organic_traffic=400,
                          observed_at="2026-04-20T00:00:00Z")
    campaign = fixtures.create_live_campaign(
        client["id"], retainer["id"], channel="BING", budget_cents=1000000
    )
    get_success_data(
        api_client.record_spend(campaign["id"], {"amount_cents": 500000}, AM)
    )
    get_success_data(
        api_client.create_dispute(
            factories.create_dispute_payload(
                ad_campaign_id=campaign["id"], client_id=client["id"],
                disputed_cents=100000,
            ),
            AM,
        )
    )
    return client, keyword


def test_report_rank_momentum_single_keyword(api):
    """PRD §3.3: "For each keyword with at least one in-window snapshot, its
    improvement is the position of the first in-window reading minus the position of
    the last in-window reading — a positive number means the rank moved toward
    position 1, an improvement — and any `position` of 0, meaning unranked, is treated
    as 101 for this arithmetic."
    PRD §3.3: "The `rank_momentum` is the mean of these per-keyword improvements
    across the keywords that had at least one in-window snapshot, rounded half up to
    two decimal places."

    One keyword with first reading 50 and last 10 in window -> improvement 40 ->
    rank_momentum 40.0.

    Design: Difficulty/combinatorial_formula/account_health_three_input_nonlinear_clamp
    """
    client, _ = _setup_health_scenario()
    report = validate_success(
        api.create_report(
            client["id"],
            {"period_start": "2026-04-01T00:00:00Z",
             "period_end": "2026-05-01T00:00:00Z"},
            AM,
        ),
        expected_status=201,
    )
    assert report["rank_momentum"] == 40.0, (
        f"rank_momentum should be 40.0, got {report['rank_momentum']}"
    )


def test_account_health_clamps_momentum_and_subtracts_dispute(api):
    """PRD §3.3: "Begin from a base of 100. Add a momentum term equal to the client's
    latest report `rank_momentum` multiplied by two, clamped to lie between negative
    thirty and positive thirty (use 0 if the client has no report yet). Subtract an
    overdue penalty of five for each of the client's deliverables that is currently
    `ASSIGNED`, `IN_PROGRESS`, or `IN_REVIEW` and whose sprint's `ends_at` is earlier
    than the current logical-clock time. Subtract a dispute penalty of ten for each
    unit of the client's `open_dispute_count`. Round the result half up to a whole
    number and clamp it to the range 0 through 100."

    momentum 40 -> term 80 clamps to +30; 0 overdue; 1 open dispute -> -10:
    clamp(100 + 30 - 0 - 10) = clamp(120) = 100.

    Design: Difficulty/combinatorial_formula/account_health_three_input_nonlinear_clamp
    """
    client, _ = _setup_health_scenario()
    validate_success(
        api.create_report(
            client["id"],
            {"period_start": "2026-04-01T00:00:00Z",
             "period_end": "2026-05-01T00:00:00Z"},
            AM,
        ),
        expected_status=201,
    )
    client_after = validate_success(api.get_client(client["id"], ADMIN))
    assert client_after["open_dispute_count"] == 1
    assert client_after["health_score"] == 100, (
        f"health should be clamp(100 + 30 - 10) = 100, "
        f"got {client_after['health_score']}"
    )


def test_report_total_traffic_window_filtering(api):
    """PRD §3.3: "The `total_traffic` is the sum of `organic_traffic` across all rank
    snapshots whose reading falls within the window, that is at or after
    `period_start` and strictly before `period_end`."

    In-window snapshots (100 + 400) sum to 500; a snapshot dated 2026-05-15 outside
    [04-01, 05-01) is excluded.

    Design: Corner/calculations/report_total_traffic_window_filtering
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    client, retainer = fixtures.create_active_client_with_active_retainer(
        client_overrides={"company_name": "Win Co", "primary_domain": "win.example"},
        retainer_overrides={"monthly_credits": 20},
    )
    keyword = fixtures.create_tracking_keyword(
        client["id"], phrase="window kw", search_volume=500, difficulty=20
    )
    fixtures.add_snapshot(keyword["id"], position=50, organic_traffic=100,
                          observed_at="2026-04-05T00:00:00Z")
    fixtures.add_snapshot(keyword["id"], position=10, organic_traffic=400,
                          observed_at="2026-04-20T00:00:00Z")
    fixtures.add_snapshot(keyword["id"], position=8, organic_traffic=999,
                          observed_at="2026-05-15T00:00:00Z")
    report = validate_success(
        api.create_report(
            client["id"],
            {"period_start": "2026-04-01T00:00:00Z",
             "period_end": "2026-05-01T00:00:00Z"},
            AM,
        ),
        expected_status=201,
    )
    assert report["total_traffic"] == 500, (
        f"total_traffic should sum only in-window snapshots (100+400)=500, "
        f"got {report['total_traffic']}"
    )
    assert report["rank_momentum"] == 40.0, (
        f"rank_momentum should be 40.0, got {report['rank_momentum']}"
    )


def test_get_client_recomputes_health_to_100_when_clean(api):
    """PRD §3.1: "Reading a single client recomputes and returns its `health_score`."
    PRD §3.3: "Begin from a base of 100. Add a momentum term equal to the client's
    latest report `rank_momentum` multiplied by two, clamped to lie between negative
    thirty and positive thirty (use 0 if the client has no report yet)."

    A fresh ACTIVE client with no reports, no disputes, no overdue work reconciles to
    health_score 100 on GET.

    Design: Corner/cross_cutting_complexity_layers/get_client_recomputes_health_derived_field
    """
    client, retainer = fixtures.create_active_client_with_active_retainer(
        client_overrides={"company_name": "Der Co", "primary_domain": "der.example"},
        retainer_overrides={"monthly_credits": 20},
    )
    fresh = validate_success(api.get_client(client["id"], ADMIN))
    assert fresh["status"] == "ACTIVE"
    assert fresh["health_score"] == 100, (
        f"clean ACTIVE client should reconcile to health 100, got {fresh['health_score']}"
    )


def test_snapshot_updates_current_and_best_rank(api):
    """PRD §3.2: "Appending a snapshot sets the keyword target's `current_rank` to the
    snapshot's `position`, and when that `position` is greater than 0 it lowers
    `best_rank` to the smaller of the existing best rank and the new position (treating
    a never-ranked best rank as effectively unbounded so the first positive reading
    becomes the best)."

    Snapshots position 30 then 12 -> current_rank 12, best_rank 12 (min positive).

    Design: Corner/endpoints/snapshot_updates_keyword_current_and_best_rank
    """
    client = fixtures.create_audited_client(
        company_name="Snp Co", primary_domain="snp.example"
    )
    keyword = fixtures.create_tracking_keyword(
        client["id"], phrase="rank kw", search_volume=300, difficulty=25
    )
    fixtures.add_snapshot(keyword["id"], position=30, organic_traffic=50)
    fixtures.add_snapshot(keyword["id"], position=12, organic_traffic=90)
    after = validate_success(api.get_keyword_target(keyword["id"], AM))
    assert after["current_rank"] == 12, f"current_rank should be 12, got {after['current_rank']}"
    assert after["best_rank"] == 12, f"best_rank should be 12, got {after['best_rank']}"
