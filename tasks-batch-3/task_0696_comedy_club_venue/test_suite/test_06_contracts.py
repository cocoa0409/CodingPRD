"""Performer contract negotiation: the offer/counter cycle, the round cap, and
the OCC-guarded signing.

Translates the non_linear_state_machine (cyclic lineup) and boundary
(counter_rounds) difficulty instances plus the OCC corner instances.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    setup_offered_lineup_slot, setup_slot_at_counter_limit, counter_slot,
    TEST_USERS, make_performer_headers,
)

BOOKER = TEST_USERS["booker_headers"]


# ---------------------------------------------------------------------------
# Difficulty A — non_linear_state_machine / lineup_slot_offer_counter_cycle
# ---------------------------------------------------------------------------
def test_lineup_slot_cycles_offered_countered_offered(api):
    """PRD §3.9: "The performer who owns the slot may counter the offer, supplying
    a `counter_fee_cents`; this advances `contract_status` from `OFFERED` to
    `COUNTERED`, overwrites `offered_fee_cents` with the countered figure, and
    increases `counter_rounds` by 1."
    PRD §3.9: "A `Booker` may revise the offer in reply, supplying a
    `new_offered_fee_cents`; this returns `contract_status` from `COUNTERED` to
    `OFFERED` and overwrites `offered_fee_cents`, reopening the loop."

    Design: Difficulty/non_linear_state_machine/lineup_slot_offer_counter_cycle
    """
    ctx = setup_offered_lineup_slot(offered_fee_cents=30000, role="HEADLINER",
                                    standard_fee_cents=30000)
    slot_id = ctx["slot"]["id"]
    perf_id = ctx["performer"]["id"]
    countered = counter_slot(perf_id, slot_id, 40000)
    assert countered["contract_status"] == "COUNTERED", \
        f"expected COUNTERED after counter, got {countered['contract_status']}"
    revised = validate_success(
        api.revise_offer(slot_id, {"new_offered_fee_cents": 35000}, BOOKER)
    )
    assert revised["contract_status"] == "OFFERED", \
        f"expected OFFERED after revise (cycled back), got {revised['contract_status']}"
    assert revised["counter_rounds"] == 1, \
        f"counter_rounds must be 1, got {revised['counter_rounds']}"
    assert revised["offered_fee_cents"] == 35000, \
        f"offered_fee_cents must be the revised 35000, got {revised['offered_fee_cents']}"


def test_counter_increments_round_and_overwrites_fee(api):
    """PRD §3.9: "this advances `contract_status` from `OFFERED` to `COUNTERED`,
    overwrites `offered_fee_cents` with the countered figure, and increases
    `counter_rounds` by 1."

    Design: Difficulty/non_linear_state_machine/lineup_slot_offer_counter_cycle
    """
    ctx = setup_offered_lineup_slot(offered_fee_cents=30000, role="HEADLINER",
                                    standard_fee_cents=30000)
    countered = counter_slot(ctx["performer"]["id"], ctx["slot"]["id"], 42000)
    assert countered["counter_rounds"] == 1, \
        f"first counter must set counter_rounds 1, got {countered['counter_rounds']}"
    assert countered["offered_fee_cents"] == 42000, \
        f"counter must overwrite offered_fee_cents to 42000, got {countered['offered_fee_cents']}"


# ---------------------------------------------------------------------------
# Difficulty A — boundary_precision_check / counter_rounds_at_limit_boundary
# ---------------------------------------------------------------------------
def test_revise_blocked_at_counter_limit(api):
    """PRD §3.9: "The loop is capped at three rounds: a counter or a revise-offer
    attempted once `counter_rounds` has reached 3 is rejected with
    `ERR_COUNTER_LIMIT_REACHED`."

    Design: Difficulty/boundary_precision_check/counter_rounds_at_limit_boundary
    """
    ctx = setup_slot_at_counter_limit(offered_fee_cents=20000)
    assert ctx["slot"]["counter_rounds"] == 3, "precondition: counter_rounds == 3"
    resp = api.revise_offer(ctx["slot"]["id"], {"new_offered_fee_cents": 23500}, BOOKER)
    validate_error(resp, ApiErrorId.ERR_COUNTER_LIMIT_REACHED)


def test_counter_allowed_below_limit(api):
    """PRD §3.9: "The loop is capped at three rounds: a counter or a revise-offer
    attempted once `counter_rounds` has reached 3 is rejected with
    `ERR_COUNTER_LIMIT_REACHED`."

    Design: Difficulty/boundary_precision_check/counter_rounds_at_limit_boundary
    """
    # One counter below the cap is accepted (counter_rounds goes 0 -> 1).
    ctx = setup_offered_lineup_slot(offered_fee_cents=20000, role="FEATURE",
                                    standard_fee_cents=20000)
    countered = counter_slot(ctx["performer"]["id"], ctx["slot"]["id"], 21000)
    assert countered["contract_status"] == "COUNTERED", \
        f"counter below cap must succeed, got {countered['contract_status']}"
    assert countered["counter_rounds"] == 1, \
        f"counter_rounds must be 1, got {countered['counter_rounds']}"


# ---------------------------------------------------------------------------
# Corner B — cross_cutting_complexity_layers: OCC on sign
# ---------------------------------------------------------------------------
def test_sign_with_stale_slot_version_rejected(api):
    """PRD §2.8: "A request to sign a `LineupSlot` must carry
    `expected_lineup_slot_version`, holding the `version` of the target
    `LineupSlot` that the client last observed. If a counter or a revised offer
    has advanced that slot's `version` since the client read it, the fee the
    signer believes they are freezing is stale, and the signing is rejected with
    `ERR_STALE_VERSION` and HTTP status 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_slot_version_on_sign
    """
    ctx = setup_offered_lineup_slot(offered_fee_cents=25000, role="OPENER",
                                    standard_fee_cents=25000)
    stale_version = ctx["slot"]["version"]
    # A counter advances the slot version.
    counter_slot(ctx["performer"]["id"], ctx["slot"]["id"], 27000)
    resp = api.sign_lineup_slot(
        ctx["slot"]["id"], {"expected_lineup_slot_version": stale_version}, BOOKER
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_sign_with_current_version_freezes_fee_and_bumps_version(api):
    """PRD §3.9: "Signing advances `contract_status` to `SIGNED`, copies the
    current `offered_fee_cents` into `agreed_fee_cents` (frozen), and is guarded
    by the OCC rule of §2.8 through `expected_lineup_slot_version`."
    PRD §2.4: "and `version`, an integer that begins at 1 and increases by 1 on
    every mutation, used for optimistic concurrency control."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_sign
    """
    ctx = setup_offered_lineup_slot(offered_fee_cents=25000, role="OPENER",
                                    standard_fee_cents=25000)
    current_version = ctx["slot"]["version"]
    signed = validate_success(
        api.sign_lineup_slot(
            ctx["slot"]["id"], {"expected_lineup_slot_version": current_version}, BOOKER
        )
    )
    assert signed["contract_status"] == "SIGNED", \
        f"expected SIGNED, got {signed['contract_status']}"
    assert signed["agreed_fee_cents"] == 25000, \
        f"agreed_fee_cents must freeze to 25000, got {signed['agreed_fee_cents']}"
    assert signed["version"] == current_version + 1, \
        f"version must increment to {current_version + 1}, got {signed['version']}"
