"""Round trips that must leave the poundage and money ledgers exactly as found."""
import pytest

from test_helpers import (
    AM_HEADERS,
    WH_HEADERS,
    add_contract_hop_line,
    add_malt_line,
    approve_credit,
    cancel_order,
    confirm_order,
    create_brewer,
    create_contract,
    create_malt_product,
    create_order,
    create_program,
    create_released_lot,
    create_variety,
    get_brewer,
    make_brewer_headers,
    pick_order,
    pin_clock,
    ship_order,
    validate_success,
)

BUCKETS = ("remaining_lbs", "committed_lbs", "carried_forward_out_lbs",
           "defaulted_lbs", "resold_lbs")


def assert_identity_holds(contract, expected_allocated):
    """allocated_lbs must equal the sum of the five partition buckets."""
    total = sum(contract[bucket] for bucket in BUCKETS)
    assert contract["allocated_lbs"] == expected_allocated, (
        f"allocated_lbs must read {expected_allocated}, got "
        f"{contract['allocated_lbs']}")
    assert total == expected_allocated, (
        "the five buckets must sum to allocated_lbs, got "
        + ", ".join(f"{bucket}={contract[bucket]}" for bucket in BUCKETS))


@pytest.fixture
def contract_with_a_draft_commitment():
    """A 5,000 lb Citra contract and a DRAFT order holding one 1,200 lb line."""
    pin_clock()
    brewer = create_brewer(name="Ledger Balance Brewing",
                           credit_limit_cents=5000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    program = create_program(crop_year=2026)
    variety = create_variety()
    contract = create_contract(brewer["id"], variety["id"], program["id"],
                               contracted_lbs=5000, price_per_lb_cents=285.50,
                               delivery_window_start="2026-09-01T00:00:00Z",
                               delivery_window_end="2026-12-31T00:00:00Z")
    order = create_order(brewer["id"],
                         requested_ship_date="2026-09-20T00:00:00Z",
                         purchase_order_ref="PO-CONS-1")
    line = add_contract_hop_line(order["id"], brewer["id"], variety["id"],
                                 contract["id"], 1200)
    return {"brewer": brewer, "program": program, "variety": variety,
            "contract": contract, "order": order, "line": line}


def test_confirming_moves_poundage_between_buckets_without_touching_allocated(
        api, contract_with_a_draft_commitment):
    """5000 == 5000 + 0 at signing becomes 5000 == 3800 + 1200 on confirmation.

    PRD §2.11: "Order activity never touches `allocated_lbs`. Confirming an order
    moves poundage out of `remaining_lbs` and into `committed_lbs`; cancelling the
    order moves exactly the same poundage back, so a confirm-then-cancel round
    trip leaves all five buckets where they started."

    Design: Difficulty/compensating_invariant/contract_poundage_conserved_across_commit_and_release
    """
    world = contract_with_a_draft_commitment
    at_signing = world["contract"]
    assert_identity_holds(at_signing, 5000)
    assert at_signing["remaining_lbs"] == 5000, (
        f"nothing is committed at signing, got {at_signing['remaining_lbs']}")
    assert at_signing["committed_lbs"] == 0, (
        f"the committed bucket starts empty, got {at_signing['committed_lbs']}")
    assert at_signing["carried_forward_out_lbs"] == 0 and \
        at_signing["defaulted_lbs"] == 0 and at_signing["resold_lbs"] == 0, (
        "the three disposal buckets start empty, got "
        f"{at_signing['carried_forward_out_lbs']}, "
        f"{at_signing['defaulted_lbs']}, {at_signing['resold_lbs']}")

    order = confirm_order(world["order"]["id"], world["brewer"]["id"])
    assert order["total_cents"] == 397600, (
        "342600 + 43000 freight + 4500 pallet break + 7500 surcharge = 397600, "
        f"got {order['total_cents']}")

    mid = validate_success(api.get_hop_contract(world["contract"]["id"],
                                               AM_HEADERS))
    assert_identity_holds(mid, 5000)
    assert mid["committed_lbs"] == 1200, (
        f"the line's 1200 lbs are committed, got {mid['committed_lbs']}")
    assert mid["remaining_lbs"] == 3800, (
        f"5000 less 1200 leaves 3800, got {mid['remaining_lbs']}")
    assert mid["status"] == "ACTIVE", (
        f"a commitment is not a state change, got {mid['status']}")
    assert mid["shortfall_lbs"] == 0, (
        f"no harvest has been reported, got {mid['shortfall_lbs']}")


def test_cancelling_restores_every_bucket_without_double_crediting_remaining(
        api, contract_with_a_draft_commitment):
    """The release is a field-level compensation: back to 5000 == 5000, not 6200.

    PRD §3.8: "each `CONTRACT` hop line's `quantity` is subtracted from its
    contract's `committed_lbs` and added back to `remaining_lbs`, leaving
    `allocated_lbs` unchanged"

    Design: Difficulty/compensating_invariant/contract_poundage_conserved_across_commit_and_release
    """
    world = contract_with_a_draft_commitment
    confirm_order(world["order"]["id"], world["brewer"]["id"])
    mid = validate_success(api.get_hop_contract(world["contract"]["id"],
                                               AM_HEADERS))

    cancelled = cancel_order(world["order"]["id"],
                             cancel_reason="brewer rescheduled the brew day")
    assert cancelled["fulfillment_status"] == "CANCELLED", (
        f"the order is cancelled, got {cancelled['fulfillment_status']}")

    after = validate_success(api.get_hop_contract(world["contract"]["id"],
                                                 AM_HEADERS))
    assert_identity_holds(after, 5000)
    assert after["committed_lbs"] == 0, (
        f"the commitment is released, got {after['committed_lbs']}")
    assert after["remaining_lbs"] == 5000, (
        "the poundage returns without being double-credited to 6200, got "
        f"{after['remaining_lbs']}")
    assert after["status"] == "ACTIVE", (
        f"the release is not a state change, got {after['status']}")
    assert after["shortfall_lbs"] == 0, (
        f"the shortfall figure is untouched, got {after['shortfall_lbs']}")
    assert after["version"] > mid["version"], (
        "commit and release are separate writes, got version "
        f"{after['version']} against {mid['version']}")

    line = validate_success(api.get_order_line(
        world["line"]["id"], make_brewer_headers(world["brewer"]["id"])))
    assert line["status"] == "REMOVED", (
        f"the cancelled order's line is removed, got {line['status']}")

    variety = validate_success(api.get_hop_variety(world["variety"]["id"],
                                                   AM_HEADERS))
    assert variety["available_spot_lbs"] == 20000, (
        "a CONTRACT line never touches the spot pool in either direction, got "
        f"{variety['available_spot_lbs']}")


@pytest.fixture
def picked_malt_order_ready_to_invoice():
    """A PICKED ambient malt order of 150,025 cents against an empty ledger.

    Malt needs no reefer, so the order can ship with no cold-chain load in play
    and the whole movement is monetary.
    """
    pin_clock()
    brewer = create_brewer(name="Credit Memo Brewing", credit_limit_cents=5000000,
                           cold_chain_certified=True, legacy_trailing_lbs=0)
    product = create_malt_product()
    lot = create_released_lot(product["id"], quantity_lbs=5000,
                              lot_code="LOT-AR-1", diastatic_power=95.00)
    order = create_order(brewer["id"],
                         requested_ship_date="2026-09-05T00:00:00Z",
                         purchase_order_ref="PO-CONS-2")
    line = add_malt_line(order["id"], brewer["id"], lot["id"], 1650)
    order = confirm_order(order["id"], brewer["id"])
    approve_credit(order["id"], note="within limit")
    order = pick_order(order["id"])
    return {"brewer": brewer, "product": product, "lot": lot, "order": order,
            "line": line}


def test_shipping_moves_the_money_between_buckets_leaving_exposure_flat(
        api, picked_malt_order_ready_to_invoice):
    """150,025 leaves the open-order bucket and enters ar_balance_cents intact.

    PRD §3.8: "because a `SHIPPED` order is excluded from
    `open_order_exposure_cents` at the same moment its total enters
    `ar_balance_cents`, `credit_exposure_cents` does not move at all on a ship"

    Design: Difficulty/compensating_invariant/brewer_ar_balance_conserved_across_invoice_and_credit_memo
    """
    world = picked_malt_order_ready_to_invoice
    assert world["order"]["total_cents"] == 150025, (
        "113025 + 25000 freight + 4500 pallet break + 7500 surcharge = 150025, "
        f"got {world['order']['total_cents']}")
    assert world["order"]["fee_variant"] == "PROVISIONAL", (
        f"the order is priced provisionally, got {world['order']['fee_variant']}")

    before = get_brewer(world["brewer"]["id"])
    assert before["ar_balance_cents"] == 0, (
        f"nothing is invoiced yet, got {before['ar_balance_cents']}")
    assert before["open_order_exposure_cents"] == 150025, (
        "the money sits entirely in the open-order bucket, got "
        f"{before['open_order_exposure_cents']}")
    assert before["credit_exposure_cents"] == 150025, (
        f"total exposure is the same 150025, got {before['credit_exposure_cents']}")

    shipped = ship_order(world["order"]["id"])
    assert shipped["fulfillment_status"] == "SHIPPED", (
        f"the order ships, got {shipped['fulfillment_status']}")
    assert shipped["invoiced_at"].startswith("2026-08-01T00:00:00"), (
        f"the invoice is stamped with the logical clock, got {shipped['invoiced_at']}")

    after = get_brewer(world["brewer"]["id"])
    assert after["ar_balance_cents"] == 150025, (
        f"the receivable now carries the invoice, got {after['ar_balance_cents']}")
    assert after["open_order_exposure_cents"] == 0, (
        "a SHIPPED order leaves the open-order bucket, got "
        f"{after['open_order_exposure_cents']}")
    assert after["credit_exposure_cents"] == 150025, (
        "total exposure is flat across the ship rather than 300050, got "
        f"{after['credit_exposure_cents']}")
    assert after["credit_utilization_pct"] == pytest.approx(3.00, abs=0.005), (
        f"150025 of 5000000 is 3.00 percent, got {after['credit_utilization_pct']}")
    assert after["credit_status"] == "GOOD_STANDING", (
        f"three percent is comfortable, got {after['credit_status']}")


def test_cancelling_a_shipped_order_credits_exactly_what_was_invoiced(
        api, picked_malt_order_ready_to_invoice):
    """The credit memo drives the receivable to 0 without refilling the other bucket.

    PRD §3.8: "When `invoiced_at` is not null, a credit memo for `total_cents`
    plus any `final_freight_adjustment_cents` already booked is subtracted from
    `ar_balance_cents`, restoring the pre-invoice balance exactly"

    Design: Difficulty/compensating_invariant/brewer_ar_balance_conserved_across_invoice_and_credit_memo
    """
    world = picked_malt_order_ready_to_invoice
    ship_order(world["order"]["id"])
    invoiced = get_brewer(world["brewer"]["id"])
    assert invoiced["ar_balance_cents"] == 150025, (
        f"the invoice is booked before the reversal, got "
        f"{invoiced['ar_balance_cents']}")

    cancelled = cancel_order(world["order"]["id"],
                             cancel_reason="load refused at the dock")
    assert cancelled["fulfillment_status"] == "CANCELLED", (
        f"a SHIPPED order may be cancelled, got {cancelled['fulfillment_status']}")
    assert cancelled["cancel_reason"] == "load refused at the dock", (
        f"the stated reason is recorded, got {cancelled['cancel_reason']}")
    assert cancelled["final_freight_adjustment_cents"] == 0, (
        "deliver never ran so there is no freight adjustment to reverse, got "
        f"{cancelled['final_freight_adjustment_cents']}")

    after = get_brewer(world["brewer"]["id"])
    assert after["ar_balance_cents"] == 0, (
        "the credit memo is exactly the 150025 that was invoiced, got "
        f"{after['ar_balance_cents']}")
    assert after["open_order_exposure_cents"] == 0, (
        "the reversal must not push the open-order bucket back to 150025, got "
        f"{after['open_order_exposure_cents']}")
    assert after["credit_exposure_cents"] == 0, (
        f"the whole exposure is unwound, got {after['credit_exposure_cents']}")
    assert after["credit_utilization_pct"] == pytest.approx(0.00, abs=0.005), (
        f"an empty ledger is 0.00 percent, got {after['credit_utilization_pct']}")
    assert after["credit_status"] == "GOOD_STANDING", (
        f"the brewery is clear, got {after['credit_status']}")

    line = validate_success(api.get_order_line(
        world["line"]["id"], make_brewer_headers(world["brewer"]["id"])))
    assert line["status"] == "REMOVED", (
        f"the line is removed by the cancel, got {line['status']}")

    lot = validate_success(api.get_malt_lot(world["lot"]["id"], WH_HEADERS))
    assert lot["committed_lbs"] == 0, (
        "the physical release accompanies the monetary one, got "
        f"{lot['committed_lbs']}")
    assert lot["available_lbs"] == 5000, (
        f"all 5000 lbs are available again, got {lot['available_lbs']}")
    assert lot["status"] == "RELEASED", (
        f"the cancel does not disturb the lot's state, got {lot['status']}")
    assert lot["analysis_count"] == 1, (
        f"nor its analysis history, got {lot['analysis_count']}")
