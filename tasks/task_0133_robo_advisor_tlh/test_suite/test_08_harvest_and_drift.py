"""Harvest detection, drift recompute, and harvest opportunity
lifecycle.

Coverage targets (PRD §3.7, §3.8):
- Harvest threshold at -50000 cents inclusive.
- HarvestOpportunity DETECTED -> APPROVED preconditions.
- BLOCKED state when no eligible replacement exists.
- BLOCKED -> DETECTED cycle when a new CorrelationLink resolves it.
- Drift threshold boundary 5.00.
- ERR_DRIFT_BELOW_THRESHOLD when below.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    DRIFT_TRIGGER_PCT,
    MIN_HARVEST_THRESHOLD_CENTS,
    TEST_USERS,
    advance_clock_to,
    api_client,
    create_correlation_link,
    create_security,
    iso_instant_utc,
    list_harvest_opportunities,
    quarter_key_of,
    re_get_account,
    recompute_positions,
    set_pricing,
    setup_account_with_drift,
    setup_account_with_position_at_loss,
    setup_harvest_blocked_no_replacement,
    setup_harvest_detected_with_replacement,
    validate_error,
    validate_success,
)
from datetime import date


# ===========================================================================
# Harvest threshold boundary — PRD §3.7
# ===========================================================================
class TestHarvestThreshold:

    def test_detection_at_exact_minus_50000_inclusive(self, api):
        """PRD §3.7: "When the unrealized P&L is at most negative
        five hundred dollars — that is, unrealized_loss_cents is less
        than or equal to negative fifty thousand cents, with the
        boundary inclusive — the system creates a new
        HarvestOpportunity row in DETECTED carrying account_id,
        position_id, the computed unrealized_loss_cents, and the
        detected_at server clock timestamp."

        Claim: at exactly -50000 cents unrealized loss, a
        HarvestOpportunity in DETECTED (or BLOCKED if no replacement)
        is created.
        """
        scenario = setup_account_with_position_at_loss(
            unrealized_loss_cents_target=-MIN_HARVEST_THRESHOLD_CENTS,
        )
        recompute_positions(
            scenario["account"]["id"], intent="detect",
        )
        opps = list_harvest_opportunities(scenario["account"]["id"])
        # Without a CorrelationLink the opp is BLOCKED, but the row
        # MUST exist with unrealized_loss_cents == -50000.
        assert any(
            o.get("unrealized_loss_cents") == -50_000
            and o.get("status") in {"DETECTED", "BLOCKED"}
            for o in opps
        ), (
            f"expected an opportunity at -50000 boundary; got opps="
            f"{opps}"
        )

    def test_no_detection_at_minus_49900(self, api):
        """PRD §3.7: "Below that threshold magnitude (a smaller
        loss), nothing is created, and a recompute call with
        intent=detect that finds no position past the threshold
        returns ERR_HARVEST_THRESHOLD_NOT_MET."

        Claim: at unrealized_loss_cents == -49900 (below threshold
        magnitude), no opportunity is created and the recompute call
        returns ERR_HARVEST_THRESHOLD_NOT_MET.
        """
        scenario = setup_account_with_position_at_loss(
            unrealized_loss_cents_target=-49_900,
        )
        resp = api.recompute_positions(
            scenario["account"]["id"], {"intent": "detect"},
            TEST_USERS["advisor_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_HARVEST_THRESHOLD_NOT_MET.value,
        )


# ===========================================================================
# Detected vs BLOCKED — PRD §3.7
# ===========================================================================
class TestHarvestBlockedAndDetected:

    def test_blocked_when_no_replacement_exists(self, api):
        """PRD §3.7: "When no candidate qualifies — typically because
        no correlated investable security outside the group has been
        linked — the opportunity is created in BLOCKED instead of
        DETECTED, and replacement_security_id stays null."

        Claim: with no CorrelationLink to any investable security in
        a different group, the opportunity is BLOCKED and
        replacement_security_id is null.
        """
        scenario = setup_harvest_blocked_no_replacement()
        opp = scenario["opportunity"]
        assert opp is not None
        assert opp["status"] == "BLOCKED"
        assert opp.get("replacement_security_id") in (None,)

    def test_blocked_to_detected_after_correlation_link_added(self, api):
        """PRD §3.7: "Adding a new CorrelationLink between two
        securities can resolve a blocked opportunity: the system
        re-evaluates positions whose blocked opportunities now have
        an eligible replacement, and those opportunities transition
        from BLOCKED back to DETECTED with replacement_security_id
        populated."

        Claim: after adding a CorrelationLink to an eligible
        replacement Security, the previously BLOCKED opp transitions
        to DETECTED with replacement_security_id populated.
        """
        scenario = setup_harvest_blocked_no_replacement()
        account = scenario["account"]
        # Add an investable security in a different group + correlate
        # it to the held one.
        from test_helpers import random_group_id, random_ticker
        new_security = create_security(
            asset_class="US_EQUITY",
            ticker=random_ticker("X"),
            substantially_identical_group_id=random_group_id(),
            last_price_cents=10_000,
        )
        create_correlation_link(
            scenario["security_held"], new_security, 0.95,
        )
        # Re-evaluate.
        recompute_positions(account["id"], intent="detect")
        opps = list_harvest_opportunities(account["id"])
        # The opportunity originally BLOCKED for our position now
        # transitions to DETECTED (PRD §3.7).
        held_pos_id = scenario["opportunity"]["position_id"]
        detected_opp = next(
            (
                o for o in opps
                if o.get("position_id") == held_pos_id
                and o.get("status") == "DETECTED"
            ),
            None,
        )
        assert detected_opp is not None, (
            f"expected BLOCKED->DETECTED after correlation-link; "
            f"got {opps}"
        )
        assert detected_opp.get("replacement_security_id") == new_security["id"]


# ===========================================================================
# Approve — PRD §3.7
# ===========================================================================
class TestHarvestApprove:

    def test_approve_requires_replacement_security_id(self, api):
        """PRD §3.7: "An Advisor approves a DETECTED opportunity only
        when the account's compliance_status is ACTIVE, the account's
        investment_status is not REBALANCING (a rebalance in flight
        cannot be intersected by a harvest execute), and
        replacement_security_id is not null."

        Claim: approve of a BLOCKED opportunity (where
        replacement_security_id is null) -> ERR_INVALID_STATE.
        """
        scenario = setup_harvest_blocked_no_replacement()
        opp = scenario["opportunity"]
        resp = api.approve_harvest_opportunity(
            scenario["account"]["id"], opp["id"],
            TEST_USERS["advisor_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_approve_detected_transitions_to_approved(self, api):
        """PRD §3.7: "Approval moves the opportunity from DETECTED to
        APPROVED and has no other side effects."

        Claim: approve of a DETECTED opp -> status=APPROVED.
        """
        scenario = setup_harvest_detected_with_replacement()
        opp = scenario["opportunity"]
        assert opp is not None
        resp = api.approve_harvest_opportunity(
            scenario["account"]["id"], opp["id"],
            TEST_USERS["advisor_headers"],
        )
        data = validate_success(resp)
        assert data["status"] == "APPROVED"


# ===========================================================================
# Drift threshold — PRD §3.8 / §3.8 drift formula
# ===========================================================================
class TestDriftThreshold:

    def test_drift_at_exact_500_succeeds(self, api):
        """PRD §3.8: "a non-force start requires max_drift_pct to be
        at least 5.00 percentage points, and a request that fails the
        gate is rejected with ERR_DRIFT_BELOW_THRESHOLD."

        Claim: with max_drift_pct exactly 5.00, rebalance start
        succeeds (201 with RebalanceRun created).
        """
        scenario = setup_account_with_drift(target_drift_pct=5.00)
        account = scenario["account"]
        # Sanity: verify drift after recompute equals 5.00.
        from test_helpers import recompute_drift
        recompute_drift(account["id"])
        refreshed = re_get_account(account["id"])
        assert abs(refreshed["max_drift_pct"] - 5.00) < 0.01, (
            f"setup expected drift=5.00 (or close); got "
            f"{refreshed['max_drift_pct']}"
        )
        # Start rebalance — should be accepted.
        qk = quarter_key_of(date.today())
        resp = api.start_rebalance(
            account["id"], {"quarter_key": qk},
            TEST_USERS["advisor_headers"],
        )
        # PRD §4 declares POST /accounts/{id}/rebalance/start as
        # code: 201 with output RebalanceRun.
        validate_success(resp, expected_status=201)

    def test_drift_below_threshold_rejected(self, api):
        """PRD §3.8: "a non-force start requires max_drift_pct to be
        at least 5.00 percentage points, and a request that fails the
        gate is rejected with ERR_DRIFT_BELOW_THRESHOLD."

        Claim: with max_drift_pct strictly below 5.00 and force
        omitted, rebalance start -> ERR_DRIFT_BELOW_THRESHOLD.
        """
        # Build account at drift 0.00 (perfectly balanced).
        scenario = setup_account_with_drift(target_drift_pct=0.00)
        account = scenario["account"]
        qk = quarter_key_of(date.today())
        resp = api.start_rebalance(
            account["id"], {"quarter_key": qk},
            TEST_USERS["advisor_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_DRIFT_BELOW_THRESHOLD.value,
        )
