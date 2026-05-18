"""Model portfolios, allocation validation, and band-driven assignment.

Coverage targets (PRD §3.2):
- target_allocation weight bounds and sum-to-one.
- Horizon-band tiers (SHORT 1-5, MID 6-15, LONG 16-40).
- Assignment selects active model with matching risk and horizon
  bands.
- Horizon edit re-runs assignment when crossing a band boundary.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_account,
    create_client,
    create_model_portfolio,
    create_model_portfolio_payload,
    re_get_account,
    seed_nine_model_portfolios,
    setup_active_client_with_account,
    submit_questionnaire,
    activate_client,
    validate_error,
    validate_success,
)


# ===========================================================================
# Allocation validation — PRD §3.2
# ===========================================================================
class TestAllocationValidation:

    def test_weight_out_of_unit_interval_rejected(self, api):
        """PRD §3.2: "Any individual weight outside the closed unit
        interval, or a sum that does not equal one, is rejected with
        ERR_ALLOCATION_INVALID."

        Claim: a target_allocation with a weight > 1 ->
        ERR_ALLOCATION_INVALID.
        """
        bad = {
            "US_EQUITY": 1.50, "INTL_EQUITY": -0.50,
            "US_BOND": 0.00, "INTL_BOND": 0.00, "CASH": 0.00,
        }
        resp = api.create_model_portfolio(
            create_model_portfolio_payload(target_allocation=bad),
            TEST_USERS["advisor_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_INVALID.value)

    def test_weights_must_sum_to_one(self, api):
        """PRD §3.2: "Any individual weight outside the closed unit
        interval, or a sum that does not equal one, is rejected with
        ERR_ALLOCATION_INVALID."

        Claim: target_allocation summing to 0.99 -> ERR_ALLOCATION_INVALID.
        """
        bad = {
            "US_EQUITY": 0.50, "INTL_EQUITY": 0.20,
            "US_BOND": 0.20, "INTL_BOND": 0.05, "CASH": 0.04,
        }  # sum = 0.99
        resp = api.create_model_portfolio(
            create_model_portfolio_payload(target_allocation=bad),
            TEST_USERS["advisor_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_INVALID.value)

    def test_valid_allocation_accepted(self, api):
        """PRD §3.2: "the five weights must sum to exactly one".

        Claim: a valid allocation summing to 1.000 is accepted.
        """
        ok = {
            "US_EQUITY": 0.40, "INTL_EQUITY": 0.20,
            "US_BOND": 0.30, "INTL_BOND": 0.05, "CASH": 0.05,
        }
        resp = api.create_model_portfolio(
            create_model_portfolio_payload(target_allocation=ok),
            TEST_USERS["advisor_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert abs(sum(data["target_allocation"].values()) - 1.0) < 1e-6


# ===========================================================================
# Horizon bands — PRD §3.2
# ===========================================================================
class TestHorizonAssignment:

    @pytest.mark.parametrize(
        "horizon,expected_band",
        [
            (1, "SHORT"),
            (5, "SHORT"),
            (6, "MID"),
            (15, "MID"),
            (16, "LONG"),
            (40, "LONG"),
        ],
    )
    def test_horizon_to_band_mapping(self, api, horizon, expected_band):
        """PRD §3.2: "SHORT covers years one through five, MID covers
        years six through fifteen, and LONG covers years sixteen
        through forty."

        Claim: time_horizon_years -> horizon_band per the tiering.
        Verified observationally by creating an Account, ensuring the
        nine-model grid exists, activating the client, and checking
        that the assigned ModelPortfolio.horizon_band matches.
        """
        # Seed all 9 models so every (risk_band, horizon_band)
        # combination has an assignable model.
        seed_nine_model_portfolios()
        client = create_client(time_horizon_years=horizon)
        account = create_account(client)
        # Force MODERATE risk band for predictable lookup.
        submit_questionnaire(
            client,
            q1_loss_tolerance=3, q2_volatility_comfort=3,
            q3_growth_vs_stability=3, q4_liquidity_need=2,
            q5_experience=3, scoring_method="STANDARD",
        )
        activate_client(client)
        refreshed = re_get_account(account["id"])
        assigned_model_id = refreshed.get("model_portfolio_id")
        assert assigned_model_id is not None, (
            "model_portfolio_id must be populated on activation"
        )
        # Fetch the model to verify its horizon_band.
        resp = api.list_model_portfolios(
            TEST_USERS["advisor_headers"],
            params={"limit": 100},
        )
        items = resp.json()["data"]
        if isinstance(items, dict):
            items = items.get("items", [])
        assigned = next(
            (m for m in items if m["id"] == assigned_model_id), None,
        )
        assert assigned is not None, (
            f"assigned model {assigned_model_id} not found in list"
        )
        assert assigned["horizon_band"] == expected_band

    def test_assignment_runs_on_activation(self, api):
        """PRD §3.1: "that activation step kicks the model assignment
        calculation, populating model_portfolio_id on every Account
        of the client where the field was previously null."

        Claim: prior to activate the account has model_portfolio_id
        null; after activate it is populated.
        """
        seed_nine_model_portfolios()
        client = create_client(time_horizon_years=10)
        account = create_account(client)
        # Account at creation should have model_portfolio_id null
        # (PRD §3.3 says default null until first assignment).
        assert account.get("model_portfolio_id") in (None,)
        submit_questionnaire(client)
        activate_client(client)
        refreshed = re_get_account(account["id"])
        assert refreshed["model_portfolio_id"] is not None
