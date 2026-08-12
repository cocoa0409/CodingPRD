"""Settlement statements: per-ticket transport rounding order, the
dispute/revise/reissue cycle with its OCC guard, and issue-time arithmetic."""
import pytest

from test_helpers import (
    ApiErrorId,
    close_campaign_and_pool,
    generate_settlements_payload,
    make_member_headers,
    revise_settlement_payload,
    setup_disputed_settlement,
    setup_single_member_closed_pool,
    setup_two_ticket_credited_world,
    validate_error,
    validate_success,
)


def test_transport_allowance_rounds_per_ticket_then_sums(api, pool_accountant_headers):
    """PRD §3.10: "Each ticket's allowance is its `adjusted_net_tons_final`
    multiplied by the band rate, rounded half-up to integer cents; the
    statement's `transport_credit_cents` is the sum of those per-ticket rounded
    allowances. The rounding order is pinned: round each ticket first, then sum —
    summing first and rounding once is a different, non-conformant algorithm."

    Design: Difficulty/combinatorial_formula/transport_allowance_round_per_ticket_then_sum
    """
    world = setup_two_ticket_credited_world(gross_weight_lbs=72050,
                                            tare_weight_lbs=32000,
                                            sugar_pct=16.00, trash_pct=2.00,
                                            haul_distance_miles=22.5)
    # Two tickets at 20.0250 adjusted tons x 180 cents/ton = 3604.50 cents each,
    # rounded per ticket: 3605 + 3605 = 7210 (sum-then-round would give 7209).
    close_campaign_and_pool(world, gross_pool_value_cents=1000000,
                            shipped_lbs=80100)
    settlements = validate_success(api.generate_settlements(
        generate_settlements_payload(world["campaign"]["id"]),
        pool_accountant_headers), 201)
    assert len(settlements) == 1
    assert settlements[0]["transport_credit_cents"] == 7210


def test_transport_allowance_world_sugar_and_gross(api, pool_accountant_headers):
    """PRD §3.10: "For each `CREDITED` ticket, its remaining pounds are the sum
    of `remaining_lbs` over its pile allocations, and its sugar pounds are that
    remaining mass multiplied by its `final_sugar_pct` divided by 100, rounded
    half-up to 2 decimal places."
    PRD §3.10: "a raw gross entitlement of `sugar_lbs` multiplied by the pool's
    `final_price_cents_per_lb`, rounded half-up to integer cents".

    Design: Difficulty/combinatorial_formula/transport_allowance_round_per_ticket_then_sum
    """
    world = setup_two_ticket_credited_world(gross_weight_lbs=72050,
                                            tare_weight_lbs=32000,
                                            sugar_pct=16.00, trash_pct=2.00,
                                            haul_distance_miles=22.5)
    close_campaign_and_pool(world, gross_pool_value_cents=1000000,
                            shipped_lbs=80100)
    settlements = validate_success(api.generate_settlements(
        generate_settlements_payload(world["campaign"]["id"]),
        pool_accountant_headers), 201)
    assert len(settlements) == 1
    # two tickets x 40050 lbs remaining x 16.00% = 6408.00 lbs each
    assert settlements[0]["sugar_lbs"] == pytest.approx(12816.00, abs=1e-9)
    # single member absorbs the rounding delta against the declared gross
    assert settlements[0]["gross_entitlement_cents"] == 1000000


def test_settlement_dispute_then_revise_returns_to_draft(api, pool_accountant_headers):
    """PRD §3.10: "The owning member — and only the owning member, else
    `ERR_FORBIDDEN` — may dispute an `ISSUED` statement, moving it to `DISPUTED`
    with an optional `reason`. The accountant may then revise it, which pulls the
    statement from `DISPUTED` back to `DRAFT` for regeneration of its computed
    fields; per §2.6 the revision request must carry
    `expected_settlement_version` matching the statement's current `version`,
    else `ERR_STALE_VERSION` (412)".

    Design: Difficulty/non_linear_state_machine/settlement_dispute_revise_reissue_cycle
    """
    world = setup_single_member_closed_pool()
    settlement = world["settlement"]
    # generated: gross 1000000 (single member absorbs the delta), transport
    # 23.6640 t x 180 = 4259.52 -> 4260
    assert settlement["status"] == "DRAFT"
    assert settlement["gross_entitlement_cents"] == 1000000
    assert settlement["transport_credit_cents"] == 4260

    issued = validate_success(
        api.issue_settlement(settlement["id"], pool_accountant_headers), 200)
    assert issued["status"] == "ISSUED"
    assert issued["advances_posted_cents"] == 0
    assert issued["final_payment_cents"] == 1000000

    disputed = validate_success(api.dispute_settlement(
        settlement["id"], {"reason": "review"},
        make_member_headers(world["member"]["id"])), 200)
    assert disputed["status"] == "DISPUTED"

    revised = validate_success(api.revise_settlement(
        settlement["id"],
        revise_settlement_payload(disputed["version"]),
        pool_accountant_headers), 200)
    assert revised["status"] == "DRAFT"


def test_settlement_reissue_after_revise_recomputes_same_amounts(api,
                                                                 pool_accountant_headers):
    """PRD §3.10: "`final_payment_cents` is `gross_entitlement_cents` minus
    `advances_posted_cents`, and it may be negative when advances exceeded
    entitlement — a clawback. `total_payment_cents` is `final_payment_cents`
    plus `transport_credit_cents`. The statement moves from `DRAFT` to `ISSUED`
    and its `version` increments."

    Design: Difficulty/non_linear_state_machine/settlement_dispute_revise_reissue_cycle
    """
    world = setup_disputed_settlement()
    settlement = world["settlement"]
    validate_success(api.revise_settlement(
        settlement["id"],
        revise_settlement_payload(world["settlement_disputed_version"]),
        pool_accountant_headers), 200)
    reissued = validate_success(
        api.issue_settlement(settlement["id"], pool_accountant_headers), 200)
    assert reissued["status"] == "ISSUED"
    assert reissued["final_payment_cents"] == 1000000
    assert reissued["total_payment_cents"] == 1004260  # + 4260 transport


def test_occ_settlement_revise_stale_version(api, pool_accountant_headers):
    """PRD §2.6: "Revising a disputed settlement statement requires the request
    body to carry `expected_settlement_version`, a non-optional field holding the
    `version` of the target `SettlementStatement` as the client last observed it.
    A mismatch with the statement's current `version` is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/occ_settlement_revise_stale_version
    """
    world = setup_disputed_settlement()
    settlement = world["settlement"]
    assert settlement["status"] == "DISPUTED"  # state precondition holds
    # The ISSUED-era version went stale when the dispute bumped the version.
    res = api.revise_settlement(
        settlement["id"],
        revise_settlement_payload(world["settlement_issued_version"]),
        pool_accountant_headers)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)
    revised = validate_success(api.revise_settlement(
        settlement["id"],
        revise_settlement_payload(world["settlement_disputed_version"]),
        pool_accountant_headers), 200)
    assert revised["status"] == "DRAFT"
