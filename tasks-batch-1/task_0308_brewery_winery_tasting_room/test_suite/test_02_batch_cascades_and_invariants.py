"""Batch branching state machine, depth-3 cascades, and compensating invariants.

Translates difficulty queue A (non_linear_state_machine, transitive_cascade,
compensating_invariant) plus the non-stub batch/cascade corners.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_tasting_order_payload, bottle_line, create_distribution_order_payload,
    create_winery, create_batch, create_batch_in_bottling, create_product,
    bottle_run, setup_active_product, setup_scheduled_shipment, set_clock,
    setup_submitted_distribution_order, TEST_USERS,
)

CO = TEST_USERS["compliance_officer_headers"]
CM = TEST_USERS["cellar_manager_headers"]
CLM = TEST_USERS["club_manager_headers"]
TRS = TEST_USERS["tasting_room_staff_headers"]


# ─── non_linear_state_machine ──────────────────────────

def test_batch_branch_ferment_to_dumped(api):
    """PRD §3.2: "A dump sets `loss_gallons` to the full `volume_in_gallons`,
    driving `available_bulk_gallons` to zero, and recomputes the winery's
    `bulk_volume_gallons` (this batch now contributing zero). A dump books no
    excise, because the lost bulk was never taxpaid."

    DUMP from FERMENTING zeroes available bulk (vs BEGIN_AGING which preserves it).

    Design: Difficulty/non_linear_state_machine/batch_branch_ferment_to_dumped
    """
    winery = create_winery(name="Dump Co", ttb_permit_number="DMP-1")
    batch = create_batch(winery["id"], volume_in_gallons=100)
    dumped = validate_success(api.transition_batch(batch["id"], {"action": "DUMP"}, CM), 200)
    assert dumped["status"] == "DUMPED"
    assert dumped["loss_gallons"] == 100, dumped["loss_gallons"]
    assert dumped["available_bulk_gallons"] == 0, dumped["available_bulk_gallons"]


def test_shipment_branch_held_billing_then_release_revert(api):
    """PRD §3.7: "if every gate passes, the shipment transitions `SCHEDULED →
    RELEASED`, and if any gate fails it diverts instead to `SCHEDULED → HELD`."
    PRD §3.7: "and the membership's `billing_status` must be `CURRENT` (otherwise
    the hold reason is `BILLING`)."
    PRD §3.7: "A held shipment that is later released has its `hold_reason` reset
    to `NONE` and applies the identical commit, loyalty, and ledger side effects."

    A PAST_DUE membership RELEASE diverts to HELD/BILLING; after billing is set
    CURRENT a second RELEASE reverts HELD->RELEASED with hold_reason NONE.

    Design: Difficulty/non_linear_state_machine/shipment_branch_held_then_release_revert
    """
    winery, product, release, member, membership, shipment = setup_scheduled_shipment(
        requested_bottles=6, pool_bottles=6, per_member_cap=6, tier="GOLD",
        bottled_bottles=20, list_price_cents=5000)
    get_success_data(api.set_membership_billing(membership["id"], {"billing_status": "PAST_DUE"}, CLM))

    held = validate_success(api.transition_shipment(shipment["id"], {"action": "RELEASE"}, CLM), 200)
    assert held["status"] == "HELD"
    assert held["hold_reason"] == "BILLING", held["hold_reason"]

    get_success_data(api.set_membership_billing(membership["id"], {"billing_status": "CURRENT"}, CLM))
    released = validate_success(api.transition_shipment(shipment["id"], {"action": "RELEASE"}, CLM), 200)
    assert released["status"] == "RELEASED"
    assert released["hold_reason"] == "NONE", released["hold_reason"]


# ─── transitive_cascade ────────────────────────────────

def test_bottling_depth3_batch_product_premises(api):
    """PRD §3.3: "In the second hop the run mints finished inventory: the product's
    `on_hand_bottles` increases by `requested_bottles`."
    PRD §3.3: "In the third hop the premises books the tax: the winery's
    `bottled_taxpaid_volume_gallons` increases by the removal gallons, and the
    winery's `excise_tax_owed_cents` increases by the excise this run accrues."
    PRD §3.3: "the rate is 107 cents per gallon."

    One WINE bottling run of 100x750ml cascades: Product.on_hand 100,
    winery taxpaid gallons 19.812913, excise 2120c.

    Design: Difficulty/transitive_cascade/bottling_depth3_batch_product_premises
    """
    winery = create_winery(name="Casc Co", ttb_permit_number="CSC-1")
    batch = create_batch_in_bottling(winery["id"],
                                     batch_overrides={"beverage_class": "WINE", "abv_percent": 13.5})
    product = create_product(winery["id"], batch["id"], sku="S1")
    bottle_run(batch["id"], product["id"], 100)

    p = get_success_data(api.get_product(product["id"], CM))
    w = get_success_data(api.get_winery(winery["id"], CO))
    assert p["on_hand_bottles"] == 100, p["on_hand_bottles"]
    assert w["bottled_taxpaid_volume_gallons"] == pytest.approx(19.812913, abs=1e-4), (
        w["bottled_taxpaid_volume_gallons"])
    assert w["excise_tax_owed_cents"] == 2120, w["excise_tax_owed_cents"]


def test_member_suspend_depth3_membership_shipment_release(api):
    """PRD §3.6: "Suspending a member fires a cascade: in the first hop every
    membership of this member whose status is `ACTIVE` is paused (`ACTIVE →
    PAUSED`), and in the second hop each such paused membership's `SCHEDULED`
    shipments are cancelled, and each of those cancellations frees the bottles it
    had reserved on its allocation release."

    Member SUSPEND -> membership PAUSED -> shipment CANCELLED -> release
    reserved_bottles freed 6 -> 0.

    Design: Difficulty/transitive_cascade/member_suspend_depth3_membership_shipment_release
    """
    winery, product, release, member, membership, shipment = setup_scheduled_shipment(
        requested_bottles=6, pool_bottles=6, per_member_cap=6, tier="GOLD",
        bottled_bottles=20, list_price_cents=5000)
    validate_success(api.transition_member(member["id"], {"action": "SUSPEND"}, CLM), 200)

    ms = get_success_data(api.get_membership(membership["id"], CLM))
    sh = get_success_data(api.get_shipment(shipment["id"], CLM))
    rel = get_success_data(api.get_release(release["id"], CM))
    assert ms["status"] == "PAUSED", ms["status"]
    assert sh["status"] == "CANCELLED", sh["status"]
    assert rel["reserved_bottles"] == 0, rel["reserved_bottles"]


# ─── compensating_invariant ────────────────────────────

def test_pos_pay_refund_conserves_product_on_hand(api):
    """PRD §3.9: "On payment, each `BOTTLE` line decrements the product's
    `on_hand_bottles` by its `quantity`".
    PRD §3.9: "A paid order may be refunded, transitioning `PAID → REFUNDED`, which
    compensates the payment: each `BOTTLE` line restores the product's
    `on_hand_bottles` by its `quantity`".

    PAY removes 3 (10 -> 7); REFUND restores 3 (7 -> 10), conserved at pre-PAY 10.

    Design: Difficulty/compensating_invariant/pos_pay_refund_conserves_product_on_hand
    """
    set_clock("2026-06-15T00:00:00Z")
    winery, batch, product = setup_active_product(
        bottled_bottles=10, product_overrides={"list_price_cents": 5000})
    order = get_success_data(api.create_tasting_order(
        create_tasting_order_payload(winery["id"], [bottle_line(product["id"], 3)],
                                     guest_age_verified=True), TRS))
    validate_success(api.transition_tasting_order(order["id"], {"action": "PAY"}, TRS), 200)
    after_pay = get_success_data(api.get_product(product["id"], CM))
    assert after_pay["on_hand_bottles"] == 7, after_pay["on_hand_bottles"]

    validate_success(api.transition_tasting_order(order["id"], {"action": "REFUND"}, TRS), 200)
    after_refund = get_success_data(api.get_product(product["id"], CM))
    assert after_refund["on_hand_bottles"] == 10, after_refund["on_hand_bottles"]


def test_release_reserve_cancel_conserves_pool_bottles(api):
    """PRD §3.7: "Scheduling reserves inventory: the release's `reserved_bottles`
    increases by `requested_bottles` and its `available_bottles` is recomputed."
    PRD §3.7: "a scheduled shipment can be cancelled (`SCHEDULED → CANCELLED`), and
    in either case the release's `reserved_bottles` decreases by `requested_bottles`,
    freeing the reservation."

    Schedule reserves 6 (reserved 6, available 0 of pool 6); CANCEL frees 6
    (reserved 0, available 6); pool sum conserved at 6.

    Design: Difficulty/compensating_invariant/release_reserve_cancel_conserves_pool_bottles
    """
    winery, product, release, member, membership, shipment = setup_scheduled_shipment(
        requested_bottles=6, pool_bottles=6, per_member_cap=6, tier="SILVER",
        bottled_bottles=20, list_price_cents=5000)
    before = get_success_data(api.get_release(release["id"], CM))
    assert before["reserved_bottles"] == 6 and before["available_bottles"] == 0

    validate_success(api.transition_shipment(shipment["id"], {"action": "CANCEL"}, CLM), 200)
    after = get_success_data(api.get_release(release["id"], CM))
    assert after["reserved_bottles"] == 0, after["reserved_bottles"]
    assert after["available_bottles"] == 6, after["available_bottles"]


# ─── Corner: state_machines / cascade (non-stub) ───────

def test_terminal_dumped_batch_no_transitions(api):
    """PRD §3.2: "`CLOSED` and `DUMPED` are the two terminal states."
    PRD §3.2: "it can begin aging, transitioning `FERMENTING → AGING`, which is
    permitted only while the batch is `FERMENTING`".

    From terminal DUMPED, BEGIN_AGING is rejected ERR_INVALID_STATE.

    Design: Corner/state_machines/terminal_dumped_batch_no_transitions
    """
    winery = create_winery(name="Tx Co", ttb_permit_number="TX-1")
    batch = create_batch(winery["id"])
    get_success_data(api.transition_batch(batch["id"], {"action": "DUMP"}, CM))
    res = api.transition_batch(batch["id"], {"action": "BEGIN_AGING"}, CM)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_dump_batch_past_fermenting_rejected(api):
    """PRD §3.2: "Alternatively, from `FERMENTING` the batch can be dumped,
    transitioning `FERMENTING → DUMPED`, a terminal branch sibling of begin-aging.
    Dumping is permitted only while the batch is `FERMENTING`".

    A batch advanced to AGING can no longer DUMP -> ERR_INVALID_STATE.

    Design: Corner/state_machines/dump_batch_with_inventory_rejected
    """
    winery = create_winery(name="Dx Co", ttb_permit_number="DX-1")
    batch = create_batch(winery["id"])
    get_success_data(api.transition_batch(batch["id"], {"action": "BEGIN_AGING"}, CM))
    res = api.transition_batch(batch["id"], {"action": "DUMP"}, CM)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_distribution_ship_removes_inventory_cascade(api):
    """PRD §3.11: "shipping removes the bottles by decreasing the product's
    `on_hand_bottles` by `bottles_ordered` and appends a compliance ledger entry
    of `entry_type` `DISTRIBUTION_REMOVAL`".

    SHIP a SUBMITTED order of 1 case (12 bottles): Product.on_hand 50 -> 38.

    Design: Corner/cross_cutting_complexity_layers/distribution_ship_removes_inventory_cascade
    """
    winery, product, dist = setup_submitted_distribution_order(
        case_count=1, bottled_bottles=50, list_price_cents=5000)
    shipped = validate_success(api.transition_distribution_order(dist["id"], {"action": "SHIP"}, CO), 200)
    assert shipped["status"] == "SHIPPED"
    p = get_success_data(api.get_product(product["id"], CM))
    assert p["on_hand_bottles"] == 38, p["on_hand_bottles"]
