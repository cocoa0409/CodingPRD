"""Check-in path: credit consumption and ledger conservation, insufficient-funds rejection,
and validation precedence (state and sanitation gates outrank the fiscal gate)."""
from test_helpers import (
    validate_success, validate_error,
    setup_credit_consumption_invariant,
    setup_reserved_credit_booking_zero_balance,
    setup_confirmed_credit_booking_tank_in_cycle,
    setup_confirmed_credit_booking_zero_balance_clean_tank,
    get_ledger_for_membership,
    api_client, TEST_USERS,
)

FRONTDESK = TEST_USERS["frontdesk_headers"]


# ─── Credit consumption invariant (ci_credit_ledger_conservation_consume) ──
def test_checkin_consume_keeps_balance_equal_to_ledger_sum(api):
    """PRD §3.6: "On a successful credit check-in the platform appends a `CONSUME` ledger
    entry whose `delta` is the negative of the credits required, records that count in
    `credits_consumed`, and recomputes the membership's `credit_balance`."

    Design: Difficulty/compensating_invariant/ci_credit_ledger_conservation_consume
    """
    # SOLO included 4 -> balance 4; CONSUME -1 at check-in -> balance 3; credits_consumed 1.
    ctx = setup_credit_consumption_invariant()
    bk, ship = ctx["booking"], ctx["membership"]
    checked_in = validate_success(api.check_in_booking(bk["id"], FRONTDESK), 200)
    assert checked_in["credits_consumed"] == 1

    membership = validate_success(api.get_membership(ship["id"], FRONTDESK), 200)
    ledger = get_ledger_for_membership(ship["id"])
    assert membership["credit_balance"] == 3, (
        f"expected balance 3 after consume, got {membership['credit_balance']}"
    )
    assert membership["credit_balance"] == sum(e["delta"] for e in ledger), (
        "credit_balance must equal the running ledger sum"
    )


def test_checkin_appends_consume_ledger_entry(api):
    """PRD §2.9: "A membership's `credit_balance` is, at every moment, the sum of the `delta`
    values across all `CreditLedgerEntry` rows for that membership". PRD §3.3: "a `reason`
    (one of `GRANT`, `CONSUME`, `FORFEIT`, or `EXPIRE`), and a signed `delta` (positive for
    `GRANT`, negative for `CONSUME`, `FORFEIT`, and `EXPIRE`)."

    Design: Difficulty/compensating_invariant/ci_credit_ledger_conservation_consume
    """
    ctx = setup_credit_consumption_invariant()
    bk, ship = ctx["booking"], ctx["membership"]
    validate_success(api.check_in_booking(bk["id"], FRONTDESK), 200)
    ledger = get_ledger_for_membership(ship["id"])
    consumes = [e for e in ledger if e["reason"] == "CONSUME" and e["delta"] == -1]
    assert len(consumes) == 1, f"expected one CONSUME -1 entry, got {consumes}"


# ─── Priority pair: state over fiscal (ppvc_state_over_fiscal_on_checkin) ──
def test_checkin_reserved_zero_balance_reports_invalid_state(api):
    """PRD §2.7: "Only once a request is authenticated, authorized, resolvable, well-formed,
    and in-range does the system evaluate state-machine legality, which fails with
    `ERR_INVALID_STATE` (HTTP 409) when a transition is not defined from the resource's current
    state. Beyond that point, the domain-specific business checks described in §3 apply".

    Design: Difficulty/priority_pair_validation_conflict/ppvc_state_over_fiscal_on_checkin
    """
    # Booking is RESERVED (no check-in edge) AND membership has zero credits: state wins.
    ctx = setup_reserved_credit_booking_zero_balance()
    bk = ctx["booking"]
    res = api.check_in_booking(bk["id"], FRONTDESK)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_checkin_confirmed_zero_balance_surfaces_fiscal_not_state(api):
    """PRD §2.7: "Only once a request is authenticated, authorized, resolvable, well-formed,
    and in-range does the system evaluate state-machine legality, which fails with
    `ERR_INVALID_STATE` (HTTP 409) when a transition is not defined from the resource's current
    state. Beyond that point, the domain-specific business checks described in §3 apply".

    Design: Difficulty/priority_pair_validation_conflict/ppvc_state_over_fiscal_on_checkin
    """
    # With the state precondition satisfied (CONFIRMED) the lower-priority fiscal gate is the
    # one that surfaces — confirming the state check pre-empts it when the booking is RESERVED.
    ctx = setup_confirmed_credit_booking_zero_balance_clean_tank()
    bk = ctx["booking"]
    res = api.check_in_booking(bk["id"], FRONTDESK)
    validate_error(res, "ERR_INSUFFICIENT_FUNDS", expected_status=402)


# ─── Priority pair: safety over fiscal (ppvc_safety_over_fiscal_on_checkin) ──
def test_checkin_in_cycle_tank_zero_balance_reports_tank_unavailable(api):
    """PRD §3.6: "The tank must be available on both axes — `IN_SERVICE` operationally and
    `CLEAN` on sanitation — and a tank failing either is refused with `ERR_TANK_UNAVAILABLE`.
    For a credit-funded session the membership must be `ACTIVE` and must hold enough credits
    ... and a balance below that requirement is refused with `ERR_INSUFFICIENT_FUNDS`".

    Design: Difficulty/priority_pair_validation_conflict/ppvc_safety_over_fiscal_on_checkin
    """
    # Tank IN_CYCLE (sanitation gate) AND zero credits: the tank-availability error wins.
    ctx = setup_confirmed_credit_booking_tank_in_cycle(zero_balance=True)
    bk = ctx["booking"]
    res = api.check_in_booking(bk["id"], FRONTDESK)
    validate_error(res, "ERR_TANK_UNAVAILABLE", expected_status=409)


def test_checkin_clean_tank_zero_balance_surfaces_fiscal_not_tank(api):
    """PRD §3.6: "The tank must be available on both axes — `IN_SERVICE` operationally and
    `CLEAN` on sanitation — and a tank failing either is refused with `ERR_TANK_UNAVAILABLE`.
    For a credit-funded session the membership must be `ACTIVE` and must hold enough credits
    ... and a balance below that requirement is refused with `ERR_INSUFFICIENT_FUNDS`".

    Design: Difficulty/priority_pair_validation_conflict/ppvc_safety_over_fiscal_on_checkin
    """
    # With the tank CLEAN+IN_SERVICE (sanitation gate satisfied) the lower-priority fiscal gate
    # is the one that surfaces — confirming the tank-availability check pre-empts it when the
    # tank is IN_CYCLE.
    ctx = setup_confirmed_credit_booking_zero_balance_clean_tank()
    bk = ctx["booking"]
    res = api.check_in_booking(bk["id"], FRONTDESK)
    validate_error(res, "ERR_INSUFFICIENT_FUNDS", expected_status=402)


# ─── Insufficient funds (insufficient_credits_checkin_returns_402) ────────
def test_checkin_zero_credits_clean_tank_reports_insufficient_funds(api):
    """PRD §3.6: "For a credit-funded session the membership must be `ACTIVE` and must hold
    enough credits: the credits required are 1 for a solo booking and 2 for a couples booking,
    and a balance below that requirement is refused with `ERR_INSUFFICIENT_FUNDS`".

    Design: Corner/validations/insufficient_credits_checkin_returns_402
    """
    # CONFIRMED CREDIT booking, balance 0, CLEAN+IN_SERVICE tank -> only the fiscal gate fires.
    ctx = setup_confirmed_credit_booking_zero_balance_clean_tank()
    bk = ctx["booking"]
    res = api.check_in_booking(bk["id"], FRONTDESK)
    validate_error(res, "ERR_INSUFFICIENT_FUNDS", expected_status=402)
