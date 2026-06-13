"""Second assertion per difficulty-queue instance.

Each test here is the complementary case for one §1.8 instance already covered
once elsewhere — a sibling branch, a boundary on the other side, a side-effect the
first test did not pin, or the PRD's own worked counter-example. Every assertion
remains verbatim-covered and uniquely derivable from PRD prose.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_member_payload, create_membership_payload, create_shipment_payload,
    create_tasting_order_payload, bottle_line, create_reservation_payload,
    create_distribution_order_payload,
    setup_active_product, setup_club_ready, setup_scheduled_shipment,
    setup_open_release, setup_active_member, setup_active_membership,
    set_clock, create_winery, create_batch, create_batch_in_bottling,
    create_product, bottle_run, create_confirmed_reservation, TEST_USERS,
)

CO = TEST_USERS["compliance_officer_headers"]
CM = TEST_USERS["cellar_manager_headers"]
CLM = TEST_USERS["club_manager_headers"]
TRS = TEST_USERS["tasting_room_staff_headers"]


# ─── dual_variant_calc (complements) ───────────────────

def test_excise_identical_gallons_diverge_taxpaid_volume_equal(api):
    """PRD §3.3: "the winery's `bottled_taxpaid_volume_gallons` increases by the
    removal gallons".
    PRD §3.3: "For a `BEER` batch the gallons are first converted to barrels by
    dividing the removal gallons by 31.0 gallons per barrel, and the excise in
    cents is that barrel count multiplied by 1800 cents per barrel".

    The same physical removal (100x750ml) books identical taxpaid gallons
    (19.812913) on both a WINE and a BEER premises even though the excise differs
    (2120c vs 1150c) — the divergence is in the rate class, not the gallons.

    Design: Difficulty/dual_variant_calc/excise_wine_tier_vs_beer_barrel_diverge
    """
    set_clock("2026-06-15T00:00:00Z")
    w_wine = create_winery(name="Wine2 Co", ttb_permit_number="WINE-2")
    w_beer = create_winery(name="Beer2 Co", ttb_permit_number="BEER-2")
    b_wine = create_batch_in_bottling(w_wine["id"],
                                      batch_overrides={"beverage_class": "WINE", "abv_percent": 13.5})
    b_beer = create_batch_in_bottling(w_beer["id"],
                                      batch_overrides={"beverage_class": "BEER", "abv_percent": 5.0})
    p_wine = create_product(w_wine["id"], b_wine["id"], sku="WS2")
    p_beer = create_product(w_beer["id"], b_beer["id"], sku="BS2")
    bottle_run(b_wine["id"], p_wine["id"], 100)
    bottle_run(b_beer["id"], p_beer["id"], 100)
    wine = get_success_data(api.get_winery(w_wine["id"], CO))
    beer = get_success_data(api.get_winery(w_beer["id"], CO))
    assert wine["bottled_taxpaid_volume_gallons"] == pytest.approx(19.812913, abs=1e-4)
    assert beer["bottled_taxpaid_volume_gallons"] == pytest.approx(19.812913, abs=1e-4)
    assert wine["excise_tax_owed_cents"] != beer["excise_tax_owed_cents"]


def test_loyalty_gold_multiplier_variant(api):
    """PRD §3.7: "The tier multiplier is 1 for `SILVER`, 2 for `GOLD`, and 3 for
    `PLATINUM`. The points earned are the net spend in cents divided by 100 cents
    per point, taken as a floor to whole points, then multiplied by the tier
    multiplier".
    PRD §3.7: "if `requested_bottles` is at least 12, a volume kicker of 0.05 is
    added to that base percentage".

    A GOLD shipment of 12 @ 5000c: discount 0.10+0.05 kicker = 0.15 -> net 51000c,
    points floor(510)*2 = 1020; the membership balance equals the winery liability
    (one membership), 1020. Distinct multiplier from the PLATINUM case.

    Design: Difficulty/dual_variant_calc/loyalty_membership_balance_vs_winery_liability
    """
    winery, product, release, member, membership = setup_club_ready(
        pool_bottles=12, per_member_cap=12, tier="GOLD",
        bottled_bottles=50, list_price_cents=5000)
    shipment = get_success_data(api.create_shipment(
        create_shipment_payload(winery["id"], membership["id"], release["id"], 12), CLM))
    get_success_data(api.transition_shipment(shipment["id"], {"action": "RELEASE"}, CLM))
    ms = get_success_data(api.get_membership(membership["id"], CLM))
    w = get_success_data(api.get_winery(winery["id"], CO))
    assert ms["loyalty_points"] == 1020, ms["loyalty_points"]
    assert w["loyalty_point_liability"] == 1020, w["loyalty_point_liability"]


# ─── combinatorial_formula (complements) ───────────────

def test_shipment_pricing_below_kicker_platinum_plain_15(api):
    """PRD §3.7: "the same `PLATINUM` membership claiming fewer than 12 bottles gets
    a plain 0.15."
    PRD §3.7: "The `subtotal_cents` is `requested_bottles` multiplied by the
    product's `list_price_cents`."

    PLATINUM 6 bottles @ 5000c: below the 12-bottle kicker, plain 0.15 on a 30000c
    subtotal -> discount 4500c, total 25500c.

    Design: Difficulty/combinatorial_formula/shipment_pricing_kicker_then_cap_mode_a
    """
    winery, product, release, member, membership = setup_club_ready(
        pool_bottles=12, per_member_cap=12, tier="PLATINUM",
        bottled_bottles=50, list_price_cents=5000)
    shipment = validate_success(api.create_shipment(
        create_shipment_payload(winery["id"], membership["id"], release["id"], 6), CLM), 201)
    assert shipment["subtotal_cents"] == 30000, shipment["subtotal_cents"]
    assert shipment["discount_cents"] == 4500, shipment["discount_cents"]
    assert shipment["total_cents"] == 25500, shipment["total_cents"]


def test_pos_no_member_discount_is_zero(api):
    """PRD §3.9: "with no member attached it is zero."
    PRD §3.9: "The `subtotal_cents` is the sum of those per-line rounded totals
    across all lines".

    Three BOTTLE lines of 333c with no member attached: subtotal 999c,
    member_discount_cents 0, total 999c.

    Design: Difficulty/combinatorial_formula/pos_total_round_per_line_then_sum_mode_b
    """
    set_clock("2026-06-15T00:00:00Z")
    winery, batch, product = setup_active_product(
        bottled_bottles=10, product_overrides={"list_price_cents": 333})
    line_items = [bottle_line(product["id"], 1) for _ in range(3)]
    order = validate_success(api.create_tasting_order(
        create_tasting_order_payload(winery["id"], line_items, guest_age_verified=True), TRS), 201)
    assert order["subtotal_cents"] == 999, order["subtotal_cents"]
    assert order["member_discount_cents"] == 0, order["member_discount_cents"]
    assert order["total_cents"] == 999, order["total_cents"]


def test_distribution_invoice_freight_high_at_threshold(api):
    """PRD §3.11: "if the rounded wholesale base is at least 50000 cents, freight is
    1500 cents".
    PRD §3.11: "its `bottles_ordered` is the `case_count` multiplied by 12 bottles
    per case".

    2 cases @4200c list: bottles 24, gross 100800, base 50400 >= 50000 -> freight
    1500 -> total 51900. Confirms freight keys on the post-discount base.

    Design: Difficulty/combinatorial_formula/distribution_invoice_freight_keyed_on_base_mode_c
    """
    winery, batch, product = setup_active_product(
        bottled_bottles=0, product_overrides={"list_price_cents": 4200})
    dist = validate_success(api.create_distribution_order(
        create_distribution_order_payload(winery["id"], product["id"], case_count=2), CO), 201)
    assert dist["bottles_ordered"] == 24, dist["bottles_ordered"]
    assert dist["wholesale_total_cents"] == 51900, dist["wholesale_total_cents"]


# ─── non_linear_state_machine (complements) ────────────

def test_batch_begin_aging_preserves_bulk_sibling_branch(api):
    """PRD §3.2: "From `FERMENTING` it can begin aging, transitioning `FERMENTING →
    AGING`... this records no removal but causes the winery's `bulk_volume_gallons`
    to be recomputed."

    The sibling branch of DUMP: BEGIN_AGING preserves available_bulk_gallons (100,
    not zeroed) — the asymmetry that distinguishes the two FERMENTING exits.

    Design: Difficulty/non_linear_state_machine/batch_branch_ferment_to_dumped
    """
    winery = create_winery(name="Age Co", ttb_permit_number="AGE-2")
    batch = create_batch(winery["id"], volume_in_gallons=100)
    aged = validate_success(api.transition_batch(batch["id"], {"action": "BEGIN_AGING"}, CM), 200)
    assert aged["status"] == "AGING"
    assert aged["available_bulk_gallons"] == 100, aged["available_bulk_gallons"]
    assert aged["loss_gallons"] == 0, aged["loss_gallons"]


def test_shipment_held_then_release_commits_inventory(api):
    """PRD §3.7: "A held shipment that is later released has its `hold_reason` reset
    to `NONE` and applies the identical commit, loyalty, and ledger side effects."
    PRD §3.7: "The release's `reserved_bottles` decreases by `requested_bottles` and
    its `committed_bottles` increases by the same".

    After the BILLING hold is cleared and the second RELEASE fires, the release
    commits the 6 reserved bottles: reserved 0, committed 6.

    Design: Difficulty/non_linear_state_machine/shipment_branch_held_then_release_revert
    """
    winery, product, release, member, membership, shipment = setup_scheduled_shipment(
        requested_bottles=6, pool_bottles=6, per_member_cap=6, tier="GOLD",
        bottled_bottles=20, list_price_cents=5000)
    get_success_data(api.set_membership_billing(membership["id"], {"billing_status": "PAST_DUE"}, CLM))
    get_success_data(api.transition_shipment(shipment["id"], {"action": "RELEASE"}, CLM))
    get_success_data(api.set_membership_billing(membership["id"], {"billing_status": "CURRENT"}, CLM))
    get_success_data(api.transition_shipment(shipment["id"], {"action": "RELEASE"}, CLM))
    rel = get_success_data(api.get_release(release["id"], CM))
    assert rel["reserved_bottles"] == 0, rel["reserved_bottles"]
    assert rel["committed_bottles"] == 6, rel["committed_bottles"]


# ─── transitive_cascade (complements) ──────────────────

def test_bottling_hop1_debits_batch_bulk(api):
    """PRD §3.3: "In the first hop the run adds its removal gallons to the batch's
    `bottled_volume_gallons` and recomputes the batch's `available_bulk_gallons`."

    The first cascade hop: bottling 100x750ml (~19.812913 gal) from a 100-gal batch
    leaves available_bulk_gallons ~80.187 and bottled_volume_gallons ~19.812913.

    Design: Difficulty/transitive_cascade/bottling_depth3_batch_product_premises
    """
    winery = create_winery(name="Casc2 Co", ttb_permit_number="CSC-2")
    batch = create_batch_in_bottling(winery["id"],
                                     batch_overrides={"beverage_class": "WINE", "abv_percent": 13.5,
                                                      "volume_in_gallons": 100})
    product = create_product(winery["id"], batch["id"], sku="S1")
    bottle_run(batch["id"], product["id"], 100)
    b = get_success_data(api.get_batch(batch["id"], CM))
    assert b["bottled_volume_gallons"] == pytest.approx(19.812913, abs=1e-4), b["bottled_volume_gallons"]
    assert b["available_bulk_gallons"] == pytest.approx(80.187087, abs=1e-4), b["available_bulk_gallons"]


def test_member_suspend_cascade_frees_release_available(api):
    """PRD §3.6: "each of those cancellations frees the bottles it had reserved on
    its allocation release."
    PRD §3.5: "`available_bottles` is always `pool_bottles` minus `reserved_bottles`
    minus `committed_bottles`, never negative."

    After the member-suspend cascade cancels the SCHEDULED shipment, the release's
    available_bottles is restored to the full pool of 6 (reserved freed).

    Design: Difficulty/transitive_cascade/member_suspend_depth3_membership_shipment_release
    """
    winery, product, release, member, membership, shipment = setup_scheduled_shipment(
        requested_bottles=6, pool_bottles=6, per_member_cap=6, tier="GOLD",
        bottled_bottles=20, list_price_cents=5000)
    get_success_data(api.transition_member(member["id"], {"action": "SUSPEND"}, CLM))
    rel = get_success_data(api.get_release(release["id"], CM))
    assert rel["available_bottles"] == 6, rel["available_bottles"]


# ─── priority_pair_validation_conflict (complements) ───

def test_invalid_state_on_pay_voided_order(api):
    """PRD §3.9: "Paying an order transitions it `OPEN → PAID`. Payment is permitted
    only while the order is `OPEN`".
    PRD §3.9: "An open order may instead be voided, transitioning `OPEN → VOID`...
    `VOID` and `REFUNDED` are terminal."

    PAY on a terminal VOID order returns ERR_INVALID_STATE (state check precedes
    every business gate), the sibling of the already-RELEASED shipment case.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_age_on_shipment_release
    """
    set_clock("2026-06-15T00:00:00Z")
    winery, batch, product = setup_active_product(
        bottled_bottles=10, product_overrides={"list_price_cents": 5000})
    order = get_success_data(api.create_tasting_order(
        create_tasting_order_payload(winery["id"], [bottle_line(product["id"], 1)],
                                     guest_age_verified=True), TRS))
    get_success_data(api.transition_tasting_order(order["id"], {"action": "VOID"}, TRS))
    res = api.transition_tasting_order(order["id"], {"action": "PAY"}, TRS)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_inventory_surfaces_once_age_gate_passes(api):
    """PRD §2.9: "then the fiscal sufficiency checks — inventory and bulk sufficiency
    (`ERR_INSUFFICIENT_INVENTORY`, `ERR_INSUFFICIENT_BULK`)".
    PRD §3.9: "every `BOTTLE` line's product must be `ACTIVE` with `free_bottles` at
    least the line's `quantity` (otherwise `ERR_INSUFFICIENT_INVENTORY`)".

    With guest_age_verified=true the age gate passes, so the same 999-bottle line on
    a 10-stock product surfaces the lower-priority ERR_INSUFFICIENT_INVENTORY —
    confirming age (p8) genuinely pre-empted inventory (p15) in the paired test.

    Design: Difficulty/priority_pair_validation_conflict/age_safety_beats_inventory_fiscal_on_pos_pay
    """
    set_clock("2026-06-15T00:00:00Z")
    winery, batch, product = setup_active_product(
        bottled_bottles=10, product_overrides={"list_price_cents": 5000})
    order = get_success_data(api.create_tasting_order(
        create_tasting_order_payload(winery["id"], [bottle_line(product["id"], 999)],
                                     guest_age_verified=True), TRS))
    res = api.transition_tasting_order(order["id"], {"action": "PAY"}, TRS)
    validate_error(res, "ERR_INSUFFICIENT_INVENTORY", expected_status=409)


# ─── boundary_precision_check (complements) ────────────

def test_state_limit_strict_greater_one_case_over_holds(api):
    """PRD §3.8: "If that running total of prior cases plus this shipment's cases is
    strictly greater than the destination state's case limit, the gate fails and the
    shipment is held with reason `STATE_LIMIT`".
    PRD §3.8: "The per-state limits are 24.0 cases for `CA`".

    The X+1 side of the boundary: 24 prior cases RELEASED to CA, then claiming 1
    more makes 25 > 24 -> the RELEASE diverts to HELD with hold_reason STATE_LIMIT.

    Design: Difficulty/boundary_precision_check/state_limit_strict_greater_at_exact_case_limit
    """
    set_clock("2026-06-15T00:00:00Z")
    winery, product, release = setup_open_release(
        pool_bottles=300, per_member_cap=300, bottled_bottles=300,
        opens_at="2026-06-01T00:00:00Z", closes_at="2026-07-01T00:00:00Z",
        product_overrides={"list_price_cents": 5000})
    member = setup_active_member(winery["id"], ship_to_state_code="CA")
    membership = setup_active_membership(winery["id"], member["id"], tier="SILVER")
    sh_prior = get_success_data(api.create_shipment(
        create_shipment_payload(winery["id"], membership["id"], release["id"], 288), CLM))
    get_success_data(api.transition_shipment(sh_prior["id"], {"action": "RELEASE"}, CLM))
    sh = get_success_data(api.create_shipment(
        create_shipment_payload(winery["id"], membership["id"], release["id"], 12), CLM))
    held = validate_success(api.transition_shipment(sh["id"], {"action": "RELEASE"}, CLM), 200)
    assert held["status"] == "HELD", held["status"]
    assert held["hold_reason"] == "STATE_LIMIT", held["hold_reason"]


def test_non_empty_line_items_pos_accepted(api):
    """PRD §3.9: "A new order is `OPEN` with its computed totals — `subtotal_cents`,
    `member_discount_cents`, `loyalty_redeemed_cents`, `total_cents`, and
    `loyalty_points_earned` — initialized."

    The accepted side of the empty-collection field-validity boundary: a tasting
    order with one valid BOTTLE line is created 201 in status OPEN (whereas the
    empty line_items array is rejected ERR_INVALID_REQUEST).

    Design: Difficulty/boundary_precision_check/empty_line_items_zero_quantity_pos_rejected
    """
    set_clock("2026-06-15T00:00:00Z")
    winery, batch, product = setup_active_product(
        bottled_bottles=10, product_overrides={"list_price_cents": 5000})
    order = validate_success(api.create_tasting_order(
        create_tasting_order_payload(winery["id"], [bottle_line(product["id"], 1)],
                                     guest_age_verified=True), TRS), 201)
    assert order["status"] == "OPEN", order["status"]


# ─── cross_entity_state_dependency (complements) ───────

def test_membership_activate_succeeds_once_member_active(api):
    """PRD §3.6: "It is activated, transitioning `ENROLLED → ACTIVE`, permitted only
    while the membership is `ENROLLED` and only while the owning member is `ACTIVE`".

    The positive side of the dependency: once the member is ACTIVE, the same
    membership ACTIVATE succeeds and the membership reaches ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/membership_activate_requires_member_active
    """
    set_clock("2026-06-15T00:00:00Z")
    winery = create_winery(name="Dep2 Co", ttb_permit_number="DEP-2")
    member = get_success_data(api.create_member(
        create_member_payload(winery["id"], full_name="Ann Active", email="ann@x.com"), CLM))
    get_success_data(api.transition_member(member["id"], {"action": "ACTIVATE"}, CLM))
    membership = get_success_data(api.create_membership(
        create_membership_payload(winery["id"], member["id"], tier="SILVER"), CLM))
    activated = validate_success(api.transition_membership(membership["id"], {"action": "ACTIVATE"}, CLM), 200)
    assert activated["status"] == "ACTIVE", activated["status"]


def test_product_activate_succeeds_when_batch_in_bottling(api):
    """PRD §3.4: "A `CellarManager` activates a product, transitioning `DRAFT →
    ACTIVE`, which is permitted only while the product is `DRAFT`, only if its source
    batch is in `BOTTLING` or `CLOSED`".

    The positive side of the dependency: once the source batch reaches BOTTLING, the
    same product ACTIVATE succeeds and the product reaches ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/product_activate_requires_batch_bottling_or_closed
    """
    winery = create_winery(name="Bat2 Co", ttb_permit_number="BAT-2")
    batch = create_batch_in_bottling(winery["id"])
    product = create_product(winery["id"], batch["id"], sku="S1")
    pv = product["version"]
    activated = validate_success(api.transition_product(
        product["id"], {"action": "ACTIVATE", "expected_product_version": pv}, CM), 200)
    assert activated["status"] == "ACTIVE", activated["status"]


# ─── resource_temporal_overlap (complements) ───────────

def test_table_adjacent_window_does_not_conflict(api):
    """PRD §3.10: "two reservations that merely touch — where one's `ends_at` equals
    the other's `starts_at` — do not conflict".

    Adjacency (not overlap): after a CONFIRMED 18:00-19:00 on T1, a 19:00-20:00
    reservation on T1 CONFIRMs successfully because the interval is half-open.

    Design: Difficulty/resource_temporal_overlap/table_double_booked_half_open_overlap
    """
    winery = create_winery(name="Adj Co", ttb_permit_number="ADJ-1")
    create_confirmed_reservation(winery["id"], table_code="T1",
                                 starts_at="2026-06-20T18:00:00Z",
                                 ends_at="2026-06-20T19:00:00Z")
    res2 = get_success_data(api.create_reservation(
        create_reservation_payload(winery["id"], table_code="T1", party_size=2,
                                   starts_at="2026-06-20T19:00:00Z",
                                   ends_at="2026-06-20T20:00:00Z"), TRS))
    confirmed = validate_success(api.transition_reservation(res2["id"], {"action": "CONFIRM"}, TRS), 200)
    assert confirmed["status"] == "CONFIRMED", confirmed["status"]


def test_release_window_open_at_opens_at_inclusive(api):
    """PRD §3.7: "the current instant is at or after `opens_at` (inclusive) and
    strictly before `closes_at` (exclusive)".

    The inclusive side of the window: with the clock exactly at opens_at
    (2026-06-15) and closes_at strictly later (2026-06-20), scheduling succeeds and
    the shipment is created SCHEDULED.

    Design: Difficulty/resource_temporal_overlap/release_window_closed_aggregate_window
    """
    set_clock("2026-06-15T00:00:00Z")
    winery, product, release = setup_open_release(
        pool_bottles=6, per_member_cap=6, bottled_bottles=20,
        opens_at="2026-06-15T00:00:00Z", closes_at="2026-06-20T00:00:00Z",
        product_overrides={"list_price_cents": 5000})
    member = setup_active_member(winery["id"], ship_to_state_code="CA")
    membership = setup_active_membership(winery["id"], member["id"], tier="SILVER")
    shipment = validate_success(api.create_shipment(
        create_shipment_payload(winery["id"], membership["id"], release["id"], 6), CLM), 201)
    assert shipment["status"] == "SCHEDULED", shipment["status"]


# ─── compensating_invariant (complements) ──────────────

def test_pos_refund_reverses_loyalty_points(api):
    """PRD §3.9: "A paid order may be refunded, transitioning `PAID → REFUNDED`,
    which compensates the payment: each `BOTTLE` line restores the product's
    `on_hand_bottles` by its `quantity`, the `loyalty_points_earned` are reversed
    off the membership's `loyalty_points`".

    Conserved quantity = membership loyalty_points: PAY mints points, REFUND
    reverses them back to the pre-PAY balance of 0.

    Design: Difficulty/compensating_invariant/pos_pay_refund_conserves_product_on_hand
    """
    set_clock("2026-06-15T00:00:00Z")
    winery, batch, product = setup_active_product(
        bottled_bottles=10, product_overrides={"list_price_cents": 5000})
    member = get_success_data(api.create_member(
        create_member_payload(winery["id"], full_name="Lou Loyal", email="lou@x.com"), CLM))
    member = get_success_data(api.transition_member(member["id"], {"action": "ACTIVATE"}, CLM))
    membership = get_success_data(api.create_membership(
        create_membership_payload(winery["id"], member["id"], tier="GOLD"), CLM))
    get_success_data(api.transition_membership(membership["id"], {"action": "ACTIVATE"}, CLM))

    order = get_success_data(api.create_tasting_order(
        create_tasting_order_payload(winery["id"], [bottle_line(product["id"], 3)],
                                     member_id=member["id"], guest_age_verified=True), TRS))
    get_success_data(api.transition_tasting_order(order["id"], {"action": "PAY"}, TRS))
    after_pay = get_success_data(api.get_membership(membership["id"], CLM))
    assert after_pay["loyalty_points"] > 0, after_pay["loyalty_points"]

    get_success_data(api.transition_tasting_order(order["id"], {"action": "REFUND"}, TRS))
    after_refund = get_success_data(api.get_membership(membership["id"], CLM))
    assert after_refund["loyalty_points"] == 0, after_refund["loyalty_points"]


def test_release_reserve_then_release_pool_identity_holds(api):
    """PRD §3.5: "`available_bottles` is always `pool_bottles` minus
    `reserved_bottles` minus `committed_bottles`, never negative."
    PRD §3.7: "The release's `reserved_bottles` decreases by `requested_bottles` and
    its `committed_bottles` increases by the same".

    Across schedule (reserved 6) then RELEASE (committed 6), the pool identity
    reserved+committed+available == pool 6 holds at every step.

    Design: Difficulty/compensating_invariant/release_reserve_cancel_conserves_pool_bottles
    """
    winery, product, release, member, membership, shipment = setup_scheduled_shipment(
        requested_bottles=6, pool_bottles=6, per_member_cap=6, tier="SILVER",
        bottled_bottles=20, list_price_cents=5000)
    r1 = get_success_data(api.get_release(release["id"], CM))
    assert r1["reserved_bottles"] + r1["committed_bottles"] + r1["available_bottles"] == 6

    get_success_data(api.transition_shipment(shipment["id"], {"action": "RELEASE"}, CLM))
    r2 = get_success_data(api.get_release(release["id"], CM))
    assert r2["committed_bottles"] == 6, r2["committed_bottles"]
    assert r2["reserved_bottles"] + r2["committed_bottles"] + r2["available_bottles"] == 6
