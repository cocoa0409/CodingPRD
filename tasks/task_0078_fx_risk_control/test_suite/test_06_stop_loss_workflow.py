"""Stop-loss creation, triggering, override/execute lifecycle.

Citations refer to PRD.md §3.5.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_stop_loss_event,
    create_stop_loss,
    make_risk_officer_headers,
    post_quote,
    run_sweep,
    setup_long_position_with_price_stop,
    setup_trader_with_limits,
    setup_triggered_forced_flatten,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_stop_loss_payload


# ===========================================================================
# Stop-loss creation in ARMED — PRD §3.5
# ===========================================================================
def test_create_stop_loss_starts_in_armed(api):
    """PRD §3.5: "The rule is created with its `state` field set to `ARMED`
    and with `triggered_at` and `triggering_value` both null."

    Claim: a fresh stop-loss has state=ARMED, triggered_at=null,
    triggering_value=null.
    """
    ctx = setup_trader_with_limits()
    sl = create_stop_loss(
        trader_id=ctx["trader"]["id"],
        pair_code=ctx["pair"]["code"],
        rule_mode="PRICE",
        threshold_value=1.0950,
        action="ALERT",
    )
    assert_stop_loss_event(sl)
    assert sl["state"] == "ARMED"
    assert sl["triggered_at"] is None
    assert sl["triggering_value"] is None


@pytest.mark.parametrize("threshold_value", [0.0, -0.0001, -100.0])
def test_threshold_value_must_be_strictly_positive(api, risk_officer_headers, threshold_value):
    """PRD §3.5: "a strictly positive `threshold_value` (a violation of
    either constraint surfaces `ERR_INVALID_STOPLOSS_MODE` at HTTP 422)."

    Claim: threshold_value <= 0 → ERR_INVALID_STOPLOSS_MODE.
    """
    ctx = setup_trader_with_limits()
    res = api.create_stop_loss(
        create_stop_loss_payload(
            trader_id=ctx["trader"]["id"],
            pair_code=ctx["pair"]["code"],
            rule_mode="PRICE",
            threshold_value=threshold_value,
            action="ALERT",
        ),
        risk_officer_headers,
    )
    validate_error(
        res, ApiErrorId.ERR_INVALID_STOPLOSS_MODE.value, expected_status=422,
    )


@pytest.mark.parametrize("bad_mode", ["PRICE_ABOVE", "lossamount", "", "INVALID"])
def test_invalid_rule_mode_rejected(api, risk_officer_headers, bad_mode):
    """PRD §3.5: "The `ERR_INVALID_STOPLOSS_MODE` code is reserved for the
    narrower failure where `rule_mode` is not one of `PRICE`,
    `LOSS_AMOUNT`, `LOSS_RATIO`, or where the supplied `threshold_value`
    is not strictly greater than zero." (cross-ref: PRD §2.9)

    Claim: rule_mode outside {PRICE, LOSS_AMOUNT, LOSS_RATIO} →
    ERR_INVALID_STOPLOSS_MODE.
    """
    ctx = setup_trader_with_limits()
    res = api.create_stop_loss(
        create_stop_loss_payload(
            trader_id=ctx["trader"]["id"],
            pair_code=ctx["pair"]["code"],
            rule_mode=bad_mode,
            threshold_value=1.0,
            action="ALERT",
        ),
        risk_officer_headers,
    )
    validate_error(
        res, ApiErrorId.ERR_INVALID_STOPLOSS_MODE.value, expected_status=422,
    )


# ===========================================================================
# PRICE rule triggering — PRD §3.5
# ===========================================================================
class TestPriceTriggerBoundary:
    """PRD §3.5: "If the trader's `net_base` is positive — they are long the
    base currency — the trigger fires when `mid_rate` is less than or
    equal to `threshold_value`".

    # difficulty: boundary_precision_check/stop_loss_price_le_inclusive
    """

    def test_long_price_strictly_above_threshold_does_not_trigger(self, api):
        """PRD §3.5: long-side PRICE trigger fires "when `mid_rate` is less
        than or equal to `threshold_value`". A mid_rate strictly above the
        threshold therefore does NOT fire.

        Claim: at threshold 1.0950, a quote at 1.0951 leaves state ARMED.

        # difficulty: boundary_precision_check/stop_loss_price_le_inclusive
        """
        state = setup_long_position_with_price_stop(
            pair_mid_rate=1.100000,
            threshold_value=1.0950,
        )
        post_quote(state["ctx"]["pair"]["code"], 1.0951)
        # Re-evaluate explicitly.
        res = api.evaluate_stop_loss(
            state["stop_loss"]["id"],
            TEST_USERS["risk_officer_headers"],
        )
        sl = validate_success(res, 200)
        assert sl["state"] == "ARMED", (
            f"mid_rate 1.0951 > threshold 1.0950; expected ARMED, got {sl['state']!r}"
        )

    def test_long_price_at_threshold_triggers_inclusive(self, api):
        """PRD §3.5: long-side PRICE trigger fires "when `mid_rate` is less
        than or equal to `threshold_value`" — inclusive at the boundary.

        Claim: at threshold 1.0950, a quote at 1.0950 (exactly) → state
        TRIGGERED, triggering_value == 1.0950.
        """
        state = setup_long_position_with_price_stop(
            pair_mid_rate=1.100000,
            threshold_value=1.0950,
        )
        post_quote(state["ctx"]["pair"]["code"], 1.0950)
        res = api.evaluate_stop_loss(
            state["stop_loss"]["id"],
            TEST_USERS["risk_officer_headers"],
        )
        sl = validate_success(res, 200)
        assert sl["state"] == "TRIGGERED", (
            f"mid_rate == threshold; PRD §3.5 says '<='; expected TRIGGERED, "
            f"got {sl['state']!r}"
        )
        assert sl["triggering_value"] == 1.0950 or float(sl["triggering_value"]) == 1.0950


# ===========================================================================
# Trader acknowledge — PRD §3.5
# ===========================================================================
def test_trader_acknowledges_triggered_event(api):
    """PRD §3.5: "From `TRIGGERED`, the owning trader (matched on
    `X-User-ID == trader_id`) acknowledges the event, transitioning it to
    `ACKNOWLEDGED`".

    Claim: the owning trader's /acknowledge call transitions TRIGGERED →
    ACKNOWLEDGED.
    """
    state = setup_triggered_forced_flatten()
    # Use the per-trader builder, NOT a shared constant.
    sl = state["stop_loss"]
    res = api.acknowledge_stop_loss(sl["id"], state["ctx"]["trader_headers"])
    ack = validate_success(res, 200)
    assert ack["state"] == "ACKNOWLEDGED"


def test_non_owner_trader_cannot_acknowledge(api):
    """PRD §3.5: "the owning trader (matched on `X-User-ID == trader_id`)
    acknowledges the event".

    Claim: a Trader call whose X-User-ID differs from event.trader_id
    cannot acknowledge — surfaces 403/404/409 (PRD does not pin which of
    {ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_SEGREGATION_VIOLATION,
    ERR_INVALID_STATE} is returned; we only assert the call is refused).
    """
    state = setup_triggered_forced_flatten()
    # Make a different real Trader.
    other = setup_trader_with_limits()
    from test_helpers import make_trader_headers
    res = api.acknowledge_stop_loss(
        state["stop_loss"]["id"],
        make_trader_headers(other["trader"]["id"]),
    )
    assert res.status_code in (403, 404, 409), (
        f"PRD §3.5: non-owner acknowledge must be refused; got {res.status_code}"
    )


# ===========================================================================
# Override / execute segregation — PRD §3.5
# ===========================================================================
def test_override_cycle_overridden_then_armed_after_sweep(api):
    """PRD §3.5: "From `ACKNOWLEDGED`, a `RiskOfficer` whose `X-User-ID` is
    NOT the affected trader's id may override the event (segregation of
    duties), transitioning it to `OVERRIDDEN`; ... An overridden event
    does NOT immediately re-arm; instead, on the next sweep run, every
    event sitting in `OVERRIDDEN` is transitioned back to `ARMED`, and its
    `triggered_at` and `triggering_value` are cleared."

    Claim: the cycle TRIGGERED → ACKNOWLEDGED → OVERRIDDEN → (sweep) →
    ARMED is observable, and ARMED's triggered_at and triggering_value
    are null.

    # difficulty: non_linear_state_machine/stop_loss_override_cycle
    """
    state = setup_triggered_forced_flatten()
    sl = state["stop_loss"]
    pair_code = state["ctx"]["pair"]["code"]
    # Trader acknowledges first.
    ack = validate_success(
        api.acknowledge_stop_loss(sl["id"], state["ctx"]["trader_headers"]),
        200,
    )
    assert ack["state"] == "ACKNOWLEDGED"
    # RiskOfficer overrides (distinct X-User-ID from trader.id).
    over = validate_success(
        api.override_stop_loss(
            sl["id"],
            make_risk_officer_headers("ro-overrider"),
        ),
        200,
    )
    assert over["state"] == "OVERRIDDEN"
    # Move the market clear of the threshold before sweeping so the
    # re-armed rule does not immediately re-trigger on the still-crossed
    # quote. PRD §3.5: "A `PRICE` rule trips when the current `mid_rate`
    # crosses the `threshold_value`" — for a long position with
    # threshold 1.0950, a quote of 1.1100 sits on the non-triggering side.
    post_quote(pair_code, 1.110000)
    # Sweep re-arms OVERRIDDEN → ARMED (PRD §3.10 step 4).
    run_sweep()
    # Re-fetch via evaluate (PRD §3.5: idempotent for an ARMED rule that
    # has not crossed).
    res = api.evaluate_stop_loss(sl["id"], TEST_USERS["risk_officer_headers"])
    sl_after = validate_success(res, 200)
    assert sl_after["state"] == "ARMED", (
        f"PRD §3.5: OVERRIDDEN → ARMED on next sweep; got {sl_after['state']!r}"
    )
    assert sl_after["triggered_at"] is None
    assert sl_after["triggering_value"] is None


def test_self_override_rejected_segregation(api):
    """PRD §3.5: "a `RiskOfficer` whose `X-User-ID` is NOT the affected
    trader's id may override the event (segregation of duties)".

    Claim: a RiskOfficer call whose X-User-ID equals the event's trader_id
    is rejected with ERR_SEGREGATION_VIOLATION (PRD §2.9 priority 5
    rule names this error_id for "approve own request, override own
    stop-loss, execute own stop-loss are forbidden").
    """
    state = setup_triggered_forced_flatten()
    sl = state["stop_loss"]
    validate_success(
        api.acknowledge_stop_loss(sl["id"], state["ctx"]["trader_headers"]),
        200,
    )
    spoofed = make_risk_officer_headers(state["ctx"]["trader"]["id"])
    res = api.override_stop_loss(sl["id"], spoofed)
    validate_error(
        res, ApiErrorId.ERR_SEGREGATION_VIOLATION.value, expected_status=403,
    )


def test_execute_on_alert_rule_rejected(api):
    """PRD §3.5: "Executing a rule whose `action` is `ALERT` is not
    permitted — only `FORCED_FLATTEN` executes; alert-only rules can only
    progress through acknowledgement and override."

    Claim: /execute on a TRIGGERED ALERT rule → ERR_INVALID_STATE (the
    state is not 'TRIGGERED + FORCED_FLATTEN', the only state from which
    execute is legal per PRD §3.5).
    """
    state = setup_long_position_with_price_stop(
        pair_mid_rate=1.100000,
        threshold_value=1.0950,
        action="ALERT",
    )
    # Trigger it.
    post_quote(state["ctx"]["pair"]["code"], 1.0950)
    api.evaluate_stop_loss(state["stop_loss"]["id"], TEST_USERS["risk_officer_headers"])
    # Attempt /execute.
    res = api.execute_stop_loss(
        state["stop_loss"]["id"],
        make_risk_officer_headers("ro-executor"),
    )
    validate_error(
        res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409,
    )
