"""Boundary precision: exact endpoint behaviour one unit either side of a limit.

Three different metrics are exercised — a numeric drift threshold, a cohort
cardinality, and a whole-day date distance — each through its own endpoint.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_harvest_proposal_payload,
    drift_evaluation_payload,
    get_account,
    make_sponsor_operator_headers,
    record_performance,
    set_clock,
    setup_funded_account,
    setup_harvest_ready_account,
    setup_platform,
    transfer_in,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["portfolio_manager_headers"]

# --------------------------------------------------------------------------
# Drift threshold: a three-sleeve model on a 25,000,000c account.
# --------------------------------------------------------------------------
_DRIFT_SECURITIES = [
    ("ALFA", "Alfa Industrials", 10_000),
    ("BETA", "Beta Materials", 5_000),
    ("CETA", "Ceta Utilities", 2_500),
]
_DRIFT_SLEEVES = [("ALFA", 5000), ("BETA", 3000), ("CETA", 2000)]


def _drift_env(ceta_shares, ceta_cost_basis_cents, cash_cents):
    """Account tracking ALFA 5000 / BETA 3000 / CETA 2000 against a 1000 bps
    tolerance, holding 1250 ALFA and 1500 BETA plus the given CETA position."""
    return setup_funded_account(
        securities=_DRIFT_SECURITIES,
        sleeves=_DRIFT_SLEEVES,
        model_overrides={"drift_threshold_bps": 1000},
        account_overrides={"cash_reserve_bps": 100},
        cash_cents=cash_cents,
        positions=[
            ("ALFA", 1250, 12_500_000),
            ("BETA", 1500, 7_500_000),
            ("CETA", ceta_shares, ceta_cost_basis_cents),
        ],
    )


def test_drift_equal_to_the_tolerance_breaches_and_moves_the_account_to_drifted(api):
    """PRD §3.6: "A drift result is judged against the strategy's `drift_threshold_bps` with an **inclusive** comparison: an account is breached when `drift_bps` is greater than or equal to the threshold."

    Design: Difficulty/boundary_precision_check/drift_at_threshold_breaches_one_bps_below_does_not
    """
    env = _drift_env(1000, 2_500_000, 2_500_000)

    response = api.evaluate_drift(
        env["account"]["id"],
        drift_evaluation_payload("SETTLED"),
        make_sponsor_operator_headers(env["sponsor"]["id"]),
    )
    account = validate_success(response, 200)

    assert account["market_value_cents"] == 25000000
    assert account["drift_bps"] == 1000
    assert account["implementation_status"] == "DRIFTED"


def test_drift_one_basis_point_below_the_tolerance_leaves_the_account_synced(api):
    """PRD §3.6: "An account in `SYNCED` whose result is breached moves `SYNCED → DRIFTED`; an account in `DRIFTED` whose result is strictly below the threshold moves `DRIFTED → SYNCED`, closing the monitoring cycle `SYNCED → DRIFTED → SYNCED`."

    Design: Difficulty/boundary_precision_check/drift_at_threshold_breaches_one_bps_below_does_not
    """
    env = _drift_env(1001, 2_502_500, 2_497_500)

    response = api.evaluate_drift(
        env["account"]["id"],
        drift_evaluation_payload("SETTLED"),
        make_sponsor_operator_headers(env["sponsor"]["id"]),
    )
    account = validate_success(response, 200)

    assert account["market_value_cents"] == 25000000
    assert account["drift_bps"] == 999
    assert account["implementation_status"] == "SYNCED"


# --------------------------------------------------------------------------
# Dispersion cohort cardinality: exactly zero reporting accounts.
# --------------------------------------------------------------------------
def _dispersion_env():
    """One account tracking a PUBLISHED single-sleeve version, never observed."""
    return setup_funded_account(
        securities=[("ALFA", "Alfa Industrials", 10_000)],
        sleeves=[("ALFA", 10000)],
    )


def test_dispersion_read_is_refused_when_the_cohort_holds_zero_accounts(api):
    """PRD §3.6: "If the cohort is empty the report is refused with `ERR_DISPERSION_SET_EMPTY`."

    Design: Difficulty/boundary_precision_check/dispersion_empty_cohort_rejected_at_zero_accounts
    """
    env = _dispersion_env()

    response = api.get_dispersion(
        env["model_version"]["id"], MANAGER, params={"basis": "EQUAL_WEIGHTED"}
    )
    validate_error(response, ApiErrorId.ERR_DISPERSION_SET_EMPTY.value)


def test_dispersion_refusal_body_carries_no_cohort_figures(api):
    """PRD §3.6: "An account joins the cohort when its `current_model_version_id` is the version in question, its `implementation_status` is anything other than `SUSPENDED`, and it has reported at least one performance observation — an account whose `latest_return_bps` is still null is excluded from the count, from the mean and from the minimum-and-maximum scan alike."

    Design: Difficulty/boundary_precision_check/dispersion_empty_cohort_rejected_at_zero_accounts
    """
    env = _dispersion_env()

    account = get_account(env["account"]["id"])
    assert account["current_model_version_id"] == env["model_version"]["id"]
    assert account["latest_return_bps"] is None

    response = api.get_dispersion(
        env["model_version"]["id"], MANAGER, params={"basis": "EQUAL_WEIGHTED"}
    )
    validate_error(response, ApiErrorId.ERR_DISPERSION_SET_EMPTY.value)

    body = response.json()["data"]
    assert "account_count" not in body
    assert "mean_return_bps" not in body
    assert "dispersion_bps" not in body


def test_dispersion_reports_a_cohort_of_one_once_that_account_has_reported(api):
    """PRD §3.6: "Otherwise `account_count` reports the cohort size, `min_return_bps` and `max_return_bps` report the smallest and largest `latest_return_bps` in the cohort, and `dispersion_bps` is the difference between the largest and the smallest."

    Design: Difficulty/boundary_precision_check/dispersion_empty_cohort_rejected_at_zero_accounts
    """
    env = _dispersion_env()
    record_performance(
        env["account"]["id"], env["sponsor"]["id"], "2026-07-01T00:00:00Z", 250, 25_000_000
    )

    response = api.get_dispersion(
        env["model_version"]["id"], MANAGER, params={"basis": "EQUAL_WEIGHTED"}
    )
    report = validate_success(response, 200)

    assert report["account_count"] == 1
    assert report["min_return_bps"] == 250
    assert report["max_return_bps"] == 250
    assert report["dispersion_bps"] == 0
    assert report["mean_return_bps"] == 250
    assert report["mean_abs_deviation_bps"] == 0


# --------------------------------------------------------------------------
# Wash-sale lookback: a TRADE lot exactly 30 versus 31 whole days back.
# --------------------------------------------------------------------------
_WASH_SECURITIES = [
    ("ALFA", "Alfa Industrials", 10_000),
    ("BETA", "Beta Materials", 10_000),
]
_WASH_SLEEVES = [("ALFA", 5000), ("BETA", 5000)]


def _wash_env():
    """BETA lots booked on 2026-07-01 and ALFA lots booked on 2026-07-02, with
    the clock finally standing at 2026-08-01 — so the ALFA purchase sits exactly
    30 whole days back and the BETA purchase 31."""
    set_clock("2026-07-01T00:00:00Z")
    env = setup_harvest_ready_account(
        securities=_WASH_SECURITIES,
        sleeves=_WASH_SLEEVES,
        harvest_budget_cents=500_000,
    )
    account_id = env["account"]["id"]
    sponsor_id = env["sponsor"]["id"]
    beta_id = env["securities"]["BETA"]["id"]
    alfa_id = env["securities"]["ALFA"]["id"]

    transfer_in(account_id, sponsor_id, beta_id, 100, 1_200_000, "TRANSFER_IN")
    transfer_in(account_id, sponsor_id, beta_id, 10, 100_000, "TRADE")

    set_clock("2026-07-02T00:00:00Z")
    transfer_in(account_id, sponsor_id, alfa_id, 100, 1_200_000, "TRANSFER_IN")
    transfer_in(account_id, sponsor_id, alfa_id, 10, 100_000, "TRADE")

    set_clock("2026-08-01T00:00:00Z")
    env["account"] = get_account(account_id)
    return env


def test_harvest_proposal_collides_with_a_trade_lot_exactly_thirty_days_back(api):
    """PRD §2.10: "The **lookback clause** applies when a harvest proposal is created: the proposal is rejected when a tax lot exists for that account and security whose `origin` is `TRADE`, whose `status` is `OPEN` or `CLOSED`, and whose `open_date` falls on a date within the closed interval running from 30 days before the current clock date to 30 days after it — a purchase exactly 30 days before the proposal collides, one 31 days before does not."

    Design: Difficulty/boundary_precision_check/wash_lookback_at_thirty_days_collides_thirty_one_days_clears
    """
    env = _wash_env()

    response = api.create_harvest_proposal(
        create_harvest_proposal_payload(
            env["account"]["id"],
            env["securities"]["ALFA"]["id"],
            100,
            env["account"]["version"],
        ),
        MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_WASH_SALE_WINDOW_CONFLICT.value)


def test_harvest_proposal_clears_a_trade_lot_thirty_one_days_back(api):
    """PRD §2.10: "The **lookback clause** applies when a harvest proposal is created: the proposal is rejected when a tax lot exists for that account and security whose `origin` is `TRADE`, whose `status` is `OPEN` or `CLOSED`, and whose `open_date` falls on a date within the closed interval running from 30 days before the current clock date to 30 days after it — a purchase exactly 30 days before the proposal collides, one 31 days before does not."

    Design: Difficulty/boundary_precision_check/wash_lookback_at_thirty_days_collides_thirty_one_days_clears
    """
    env = _wash_env()

    response = api.create_harvest_proposal(
        create_harvest_proposal_payload(
            env["account"]["id"],
            env["securities"]["BETA"]["id"],
            100,
            env["account"]["version"],
        ),
        MANAGER,
    )
    proposal = validate_success(response, 201)

    assert proposal["status"] == "PROPOSED"


def test_proposal_cleared_by_the_lookback_quotes_its_signed_and_absolute_losses(api):
    """PRD §3.8: "`target_loss_cents` is the **signed net** realized amount summed across every slice the walk touched, so a winning lot nets against a losing one and the figure can even come out positive. `proposed_loss_cents` is the absolute value of the sum of **only the negative** per-slice realized amounts, with gains not netted against it at all."

    Design: Difficulty/boundary_precision_check/wash_lookback_at_thirty_days_collides_thirty_one_days_clears
    """
    env = _wash_env()

    response = api.create_harvest_proposal(
        create_harvest_proposal_payload(
            env["account"]["id"],
            env["securities"]["BETA"]["id"],
            100,
            env["account"]["version"],
        ),
        MANAGER,
    )
    proposal = validate_success(response, 201)

    assert proposal["quoted_price_cents"] == 10000
    assert proposal["target_loss_cents"] == -200000
    assert proposal["proposed_loss_cents"] == 200000
