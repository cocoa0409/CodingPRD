"""Shelf pricing: the provisional book-yield proposal, the final activation off
the measured cut-test basis, the one-pass margin tier, and the pricing state
machine of a retail case item (PRD §2.10, §2.11 and §3.4)."""

import pytest

from test_helpers import (
    ANALYST,
    MANAGER,
    activate_price_from_cutting_test,
    approve_cutting_test,
    assert_price_ends_in_nine,
    assert_retail_item,
    create_ground_item,
    create_grind_run,
    create_primal_purchase,
    create_retail_item,
    expected_shelf_price_cents,
    get_success_data,
    is_valid_uuid,
    price_activation_payload,
    price_proposal_payload,
    priced_item,
    propose_price,
    proposed_item,
    read_cutting_test,
    read_cutting_test_line,
    read_retail_item,
    reinstate_retail_item,
    reject_cutting_test,
    seeded_department,
    submitted_cutting_test,
    suspend_retail_item,
    validate_error,
    validate_paginated,
)

# PRD §3.4 arithmetic on the recurring RIB01 chain, recomputed from the PRD:
#   provisional basis  (84000 / 98.50) / 0.62      = 1375.4708 -> 2149 a pound
#   measured basis     79158 / 62.0 lb            = 1276.7419 -> 1999 a pound
#   price_variance_pct (1999 - 2149) / 2149        = -0.0698
RIB01_PROVISIONAL_BASIS = 1375.4708
RIB01_MEASURED_BASIS = 1276.7419
RIB01_PROVISIONAL_PRICE = 2149
RIB01_FINAL_PRICE = 1999
RIB01_VARIANCE = -0.0698
DEPARTMENT_MARGIN = 0.32


def test_provisional_price_comes_from_the_invoice_only_book_yield_basis(api):
    """The first-stage shelf tag on RIB01 prices the invoice cost of a usable pound over the book salable yield, without any measured bench performance.

    "It is the purchase's `invoice_cost_cents` divided by its `net_weight_lb` —
    freight and vendor allowance excluded — then divided by the standard book
    salable yield of sixty-two hundredths, rounded half up to four decimal places."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_retail_price_variant_divergence
    """
    department = seeded_department(api)
    item = create_retail_item(api, department["id"])
    purchase = create_primal_purchase(api, department["id"])

    proposed = propose_price(api, item["id"], purchase["id"])

    assert proposed["price_status"] == "PROPOSED"
    assert proposed["provisional_price_per_lb_cents"] == RIB01_PROVISIONAL_PRICE
    assert proposed["provisional_price_per_lb_cents"] == expected_shelf_price_cents(
        RIB01_PROVISIONAL_BASIS, DEPARTMENT_MARGIN
    )
    assert_price_ends_in_nine(proposed["provisional_price_per_lb_cents"])
    # The provisional tag is what the scale charges until an activation lands.
    assert proposed["active_price_per_lb_cents"] == RIB01_PROVISIONAL_PRICE
    # The book yield 0.62 stands in for a measurement nobody has taken yet, and
    # the whole-muscle shelf life is copied off the department.
    assert proposed["pricing_yield_pct_snapshot"] == pytest.approx(0.62, abs=0.0001)
    assert proposed["shelf_life_days"] == 5
    # Nothing of the final-price variant exists yet.
    assert proposed["final_price_per_lb_cents"] == 0
    assert proposed["price_variance_pct"] == pytest.approx(0.0, abs=0.0001)
    assert proposed["country_of_origin_label"] == "PENDING"
    assert_retail_item(proposed)


def test_final_price_diverges_from_the_provisional_price_on_the_measured_basis(api):
    """Activating RIB01 off the approved bench work reprices the same item from the same primal at the measured allocation instead of the book yield, and records the give-back as a negative variance.

    "The final cost basis is the item's `yield_adjusted_cost_per_lb_cents` — either
    the approved cutting-test line's `allocated_cost_per_lb_cents`, which already
    carries freight, allowance and this primal's measured yield, or the completed
    grind run's `blend_cost_per_lb_cents`."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_retail_price_variant_divergence
    """
    ctx = proposed_item(api)
    item = read_retail_item(api, ctx["whole_muscle_item"]["id"])
    assert item["provisional_price_per_lb_cents"] == RIB01_PROVISIONAL_PRICE

    activated = activate_price_from_cutting_test(
        api, item["id"], item["version"], ctx["cutting_test"]["id"]
    )

    assert activated["price_status"] == "PRICED"
    # The measured basis carries freight and the vendor allowance, and it is
    # struck over 62.0 measured salable pounds rather than the book 0.62.
    assert activated["yield_adjusted_cost_per_lb_cents"] == pytest.approx(
        RIB01_MEASURED_BASIS, abs=0.0001
    )
    assert activated["final_price_per_lb_cents"] == RIB01_FINAL_PRICE
    assert activated["final_price_per_lb_cents"] == expected_shelf_price_cents(
        RIB01_MEASURED_BASIS, DEPARTMENT_MARGIN
    )
    assert_price_ends_in_nine(activated["final_price_per_lb_cents"])
    assert activated["active_price_per_lb_cents"] == RIB01_FINAL_PRICE
    # The two variants of the same item's price genuinely disagree: 150 cents a
    # pound of margin the book yield had been giving away.
    assert activated["provisional_price_per_lb_cents"] == RIB01_PROVISIONAL_PRICE
    assert (
        activated["final_price_per_lb_cents"]
        - activated["provisional_price_per_lb_cents"]
    ) == -150
    assert activated["price_variance_pct"] == pytest.approx(RIB01_VARIANCE, abs=0.0001)
    # The book snapshot 0.62 is overwritten by the measured 62.0 / 98.50.
    assert activated["pricing_yield_pct_snapshot"] == pytest.approx(0.6294, abs=0.0001)
    assert activated["country_of_origin_label"] == "USA"


@pytest.mark.parametrize(
    "invoice_cost_cents,cost_basis,expected_price",
    [
        # first pass 593, under 800 cents, so no bump at all: 593 -> 599
        (25000, 403.2258, 599),
        # first pass 1186, in the 800-to-1600 band, bump 0.02: 1222 -> 1229
        (50000, 806.4516, 1229),
        # first pass 2372, at or above 1600, bump 0.04: 2520 -> 2529
        (100000, 1612.9032, 2529),
    ],
)
def test_first_pass_price_alone_picks_the_margin_bump(
    api, invoice_cost_cents, cost_basis, expected_price
):
    """The margin bump on a proposed shelf price is chosen by the first-pass price band alone, so three primals of different invoice cost take the zero, two-hundredths and four-hundredths bumps respectively.

    "That first-pass price selects a margin bump and nothing else: below eight
    dollars per pound — that is, under 800 cents — the bump is zero; from 800 cents
    up to but not including 1600 cents the bump is two hundredths; at 1600 cents or
    above the bump is four hundredths."

    Design: Difficulty/combinatorial_formula/retail_price_tier_selected_once_from_first_pass_price
    """
    department = seeded_department(api)
    item = create_retail_item(api, department["id"])
    purchase = create_primal_purchase(
        api,
        department["id"],
        gross_weight_lb=100.0,
        receiving_shrink_lb=0.0,
        invoice_cost_cents=invoice_cost_cents,
        freight_cost_cents=0,
        vendor_allowance_cents=0,
    )
    assert purchase["net_weight_lb"] == pytest.approx(100.00, abs=0.01)

    proposed = propose_price(api, item["id"], purchase["id"])

    assert proposed["provisional_price_per_lb_cents"] == expected_price
    assert proposed["provisional_price_per_lb_cents"] == expected_shelf_price_cents(
        cost_basis, DEPARTMENT_MARGIN
    )
    assert proposed["active_price_per_lb_cents"] == expected_price
    assert_price_ends_in_nine(proposed["provisional_price_per_lb_cents"])
    assert proposed["price_status"] == "PROPOSED"
    assert proposed["pricing_yield_pct_snapshot"] == pytest.approx(0.62, abs=0.0001)


def test_a_second_pass_price_that_crosses_into_the_next_band_keeps_its_first_pass_bump(api):
    """A pork loin whose first-pass price of 1590 sits just under the four-dollar-a-pound band takes the two-hundredths bump and keeps it, even though the resulting second-pass price of 1638 has itself crossed 1600.

    "A second-pass price is then the same cost basis divided by one minus the
    effective margin, again rounded half up to a whole cent. The tier is **never**
    re-evaluated against the second-pass price."

    Design: Difficulty/combinatorial_formula/retail_price_tier_selected_once_from_first_pass_price
    """
    department = seeded_department(api)
    item = create_retail_item(
        api,
        department["id"],
        item_code="PLN01",
        subprimal_code="PORK_LOIN_ROAST",
        product_class="VAC_PACKED",
    )
    purchase = create_primal_purchase(
        api,
        department["id"],
        primal_code="PORK_LOIN_BONELESS",
        product_class="VAC_PACKED",
        gross_weight_lb=100.0,
        receiving_shrink_lb=0.0,
        invoice_cost_cents=67034,
        freight_cost_cents=0,
        vendor_allowance_cents=0,
    )
    assert purchase["net_weight_lb"] == pytest.approx(100.00, abs=0.01)
    assert purchase["landed_cost_total_cents"] == 67034

    proposed = propose_price(api, item["id"], purchase["id"])

    # Basis 670.34 / 0.62 = 1081.1935; first pass 1081.1935 / 0.68 = 1590, which
    # is still under 1600, so the effective margin is 0.34 and the second pass is
    # 1638, nudged up to 1639.
    assert proposed["provisional_price_per_lb_cents"] == 1639
    assert proposed["provisional_price_per_lb_cents"] == expected_shelf_price_cents(
        1081.1935, DEPARTMENT_MARGIN
    )
    # Re-striking the band against the 1638 second pass would take the bump to
    # 0.04 and the price to 1689, which is not what this arithmetic does.
    assert proposed["provisional_price_per_lb_cents"] != 1689
    assert proposed["active_price_per_lb_cents"] == 1639
    assert proposed["shelf_life_days"] == 14
    assert proposed["price_status"] == "PROPOSED"


def test_effective_margin_is_capped_before_the_second_pass_is_struck(api):
    """A chuck item carrying its own fifty-eight-hundredths margin target takes the four-hundredths bump but prices at the sixty-hundredths ceiling rather than sixty-two hundredths.

    "The base margin is the item's own `target_margin_pct` when it is present and
    the department's `target_margin_pct` otherwise. A first-pass price is the cost
    basis divided by one minus that base margin, rounded half up to a whole cent."
    "The effective margin is the base margin plus that bump, capped at sixty
    hundredths."

    Design: Difficulty/combinatorial_formula/retail_price_tier_selected_once_from_first_pass_price
    """
    department = seeded_department(api)
    item = create_retail_item(
        api,
        department["id"],
        item_code="CHK01",
        subprimal_code="CHUCK_ROAST",
        target_margin_pct=0.58,
    )
    purchase = create_primal_purchase(
        api,
        department["id"],
        primal_code="BEEF_CHUCK_ROLL",
        gross_weight_lb=100.0,
        receiving_shrink_lb=0.0,
        invoice_cost_cents=50000,
        freight_cost_cents=0,
        vendor_allowance_cents=0,
    )

    proposed = propose_price(api, item["id"], purchase["id"])

    # Basis 806.4516; first pass 806.4516 / 0.42 = 1920, at or above 1600, so the
    # bump is 0.04 and 0.58 + 0.04 = 0.62 is held down to the 0.60 ceiling:
    # 806.4516 / 0.40 = 2016, nudged up to 2019.
    assert proposed["provisional_price_per_lb_cents"] == 2019
    assert proposed["provisional_price_per_lb_cents"] == expected_shelf_price_cents(
        806.4516, 0.58
    )
    # An uncapped 0.62 effective margin would have priced the item at 2129.
    assert proposed["provisional_price_per_lb_cents"] != 2129
    assert proposed["active_price_per_lb_cents"] == 2019
    assert proposed["price_status"] == "PROPOSED"


def test_activation_waits_for_the_cited_cutting_test_to_be_approved(api):
    """The very same activation of RIB01 is refused while the cutting test it cites is only submitted and succeeds once that test is approved, with nothing about the item itself changing in between.

    "For an item whose `cost_basis_source` is `CUT_TEST_LINE`, the named cutting
    test's `status` must be `APPROVED`, or the activation is refused with
    `ERR_SOURCE_TEST_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/price_activation_gated_on_source_cutting_test_status
    """
    ctx = submitted_cutting_test(api)
    item = propose_price(
        api, ctx["whole_muscle_item"]["id"], ctx["purchase"]["id"]
    )
    assert item["price_status"] == "PROPOSED"
    assert item["active_price_per_lb_cents"] == RIB01_PROVISIONAL_PRICE
    pinned_version = item["version"]

    refused = api.create_price_activation(
        item["id"],
        price_activation_payload(
            pinned_version, cutting_test_id=ctx["cutting_test"]["id"]
        ),
        MANAGER,
    )
    validate_error(refused, "ERR_SOURCE_TEST_NOT_APPROVED", 409)

    # The bench work is still only submitted, and the item is untouched.
    assert read_cutting_test(api, ctx["cutting_test"]["id"])["status"] == "SUBMITTED"
    held = read_retail_item(api, item["id"])
    assert held["price_status"] == "PROPOSED"
    assert held["final_price_per_lb_cents"] == 0
    assert held["active_price_per_lb_cents"] == RIB01_PROVISIONAL_PRICE
    assert held["version"] == pinned_version

    approved = approve_cutting_test(api, ctx["cutting_test"]["id"])
    assert approved["status"] == "APPROVED"

    fresh = read_retail_item(api, item["id"])
    activated = get_success_data(
        api.create_price_activation(
            item["id"],
            price_activation_payload(
                fresh["version"], cutting_test_id=ctx["cutting_test"]["id"]
            ),
            MANAGER,
        ),
        201,
    )
    assert activated["price_status"] == "PRICED"
    assert activated["final_price_per_lb_cents"] == RIB01_FINAL_PRICE
    assert activated["active_price_per_lb_cents"] == RIB01_FINAL_PRICE


def test_activation_is_refused_when_the_cited_cutting_test_was_rejected(api):
    """A cutting test the manager sent back is no basis for a shelf tag either, so citing the rejected test leaves RIB01 on its provisional price with no cost pushed down to the bench line.

    "For an item whose `cost_basis_source` is `CUT_TEST_LINE`, the named cutting
    test's `status` must be `APPROVED`, or the activation is refused with
    `ERR_SOURCE_TEST_NOT_APPROVED`."
    "Rejection stores the reason, moves the test `SUBMITTED → REJECTED`, and leaves
    every line's `allocated_cost_cents` at 0 — no cost is ever pushed down by a
    rejection."

    Design: Difficulty/cross_entity_state_dependency/price_activation_gated_on_source_cutting_test_status
    """
    ctx = submitted_cutting_test(api)
    item = propose_price(api, ctx["whole_muscle_item"]["id"], ctx["purchase"]["id"])
    rejected = reject_cutting_test(api, ctx["cutting_test"]["id"])
    assert rejected["status"] == "REJECTED"

    refused = api.create_price_activation(
        item["id"],
        price_activation_payload(
            item["version"], cutting_test_id=ctx["cutting_test"]["id"]
        ),
        MANAGER,
    )
    validate_error(refused, "ERR_SOURCE_TEST_NOT_APPROVED", 409)

    held = read_retail_item(api, item["id"])
    assert held["price_status"] == "PROPOSED"
    assert held["final_price_per_lb_cents"] == 0
    assert held["active_price_per_lb_cents"] == RIB01_PROVISIONAL_PRICE
    salable_line = read_cutting_test_line(api, ctx["lines"][0]["id"])
    assert salable_line["allocated_cost_cents"] == 0


def test_reinstating_a_suspended_item_restores_the_activated_shelf_price(api):
    """Pulling RIB01 out of the case and putting it back leaves the item priced at the same activated 1999 a pound it carried before the suspension.

    "Reinstating moves the item `SUSPENDED → PRICED` and restores
    `active_price_per_lb_cents` from `final_price_per_lb_cents`, which requires that
    `final_price_per_lb_cents` be greater than 0."

    Design: Corner/state_machines/retail_item_suspend_then_reinstate_restores_final_price
    """
    ctx = priced_item(api)
    item_id = ctx["whole_muscle_item"]["id"]
    priced = read_retail_item(api, item_id)
    assert priced["price_status"] == "PRICED"
    assert priced["final_price_per_lb_cents"] == RIB01_FINAL_PRICE

    suspended = suspend_retail_item(api, item_id)
    assert suspended["price_status"] == "SUSPENDED"
    # The activated price survives the suspension, which is what makes the
    # reinstatement precondition satisfiable.
    assert suspended["final_price_per_lb_cents"] == RIB01_FINAL_PRICE

    reinstated = reinstate_retail_item(api, item_id)
    assert reinstated["price_status"] == "PRICED"
    assert reinstated["final_price_per_lb_cents"] == RIB01_FINAL_PRICE
    assert reinstated["active_price_per_lb_cents"] == RIB01_FINAL_PRICE
    assert (
        reinstated["active_price_per_lb_cents"]
        == reinstated["final_price_per_lb_cents"]
    )
    # The round trip is not a repricing: the first-stage tag and the variance it
    # produced are exactly as the activation left them.
    assert reinstated["provisional_price_per_lb_cents"] == RIB01_PROVISIONAL_PRICE
    assert reinstated["price_variance_pct"] == pytest.approx(RIB01_VARIANCE, abs=0.0001)


def test_cost_basis_rules_follow_the_item_merchandising_class(api):
    """A vac-packed pork loin is no basis for a whole-muscle beef item's provisional tag, yet the ground item may cite that very purchase — and its activation then waits on a completed grind blend instead.

    "Compatibility here is asymmetric: a `WHOLE_MUSCLE` or `VAC_PACKED` item must
    cite a purchase whose `product_class` matches the item's exactly, whereas a
    `GROUND` item — whose measured basis only ever arrives from a completed grind
    blend — may cite any purchase of its department, which is precisely what makes a
    ground item eligible for a grind run in the first place."
    "For an item whose `cost_basis_source` is `GRIND_BLEND`, a `COMPLETED` grind run
    targeting the item must exist, or the activation is refused with
    `ERR_COST_BASIS_UNAVAILABLE`."

    Design: Corner/validations/price_basis_class_rules_depend_on_the_item_product_class
    """
    department = seeded_department(api)
    whole_muscle = create_retail_item(api, department["id"])
    ground = create_ground_item(api, department["id"])
    assert whole_muscle["cost_basis_source"] == "CUT_TEST_LINE"
    assert ground["cost_basis_source"] == "GRIND_BLEND"

    vac_purchase = create_primal_purchase(
        api,
        department["id"],
        primal_code="PORK_LOIN_BONELESS",
        product_class="VAC_PACKED",
        gross_weight_lb=60.0,
        receiving_shrink_lb=0.0,
        invoice_cost_cents=18000,
        freight_cost_cents=0,
        vendor_allowance_cents=0,
    )
    scheduled_run = create_grind_run(
        api,
        department["id"],
        ground["id"],
        "2026-08-06T06:00:00Z",
        "2026-08-06T07:00:00Z",
        declared_coo="USA",
        target_lean_pct=80.0,
    )
    assert scheduled_run["status"] == "SCHEDULED"

    mismatch = api.create_price_proposal(
        whole_muscle["id"], price_proposal_payload(vac_purchase["id"]), ANALYST
    )
    validate_error(mismatch, "ERR_PRODUCT_CLASS_MISMATCH", 422)
    assert read_retail_item(api, whole_muscle["id"])["price_status"] == "UNPRICED"

    # The same purchase is a perfectly good provisional basis for a ground item:
    # 18000 / 60.00 = 300.00 a pound, over the book 0.62 that is 483.8710, whose
    # first pass 712 is under 800 so it takes no bump and lands on 719.
    ground_proposed = propose_price(api, ground["id"], vac_purchase["id"])
    assert ground_proposed["price_status"] == "PROPOSED"
    assert ground_proposed["provisional_price_per_lb_cents"] == 719
    assert ground_proposed["provisional_price_per_lb_cents"] == expected_shelf_price_cents(
        483.8710, DEPARTMENT_MARGIN
    )
    assert ground_proposed["shelf_life_days"] == 2

    unavailable = api.create_price_activation(
        ground["id"],
        price_activation_payload(
            ground_proposed["version"], grind_run_id=scheduled_run["id"]
        ),
        MANAGER,
    )
    validate_error(unavailable, "ERR_COST_BASIS_UNAVAILABLE", 409)
    still_proposed = read_retail_item(api, ground["id"])
    assert still_proposed["price_status"] == "PROPOSED"
    assert still_proposed["final_price_per_lb_cents"] == 0
    assert still_proposed["yield_adjusted_cost_per_lb_cents"] == pytest.approx(
        0.0, abs=0.0001
    )


def test_a_seeded_case_item_reads_back_and_lists_the_way_it_was_written(api):
    """A newly seeded case item comes back identically from its own read and from the department-scoped listing, whose filtered page counts only the unpriced items.

    "A new item is `UNPRICED` with `country_of_origin_label` `PENDING`, and
    `pricing_yield_pct_snapshot`, `yield_adjusted_cost_per_lb_cents`,
    `provisional_price_per_lb_cents`, `final_price_per_lb_cents`,
    `active_price_per_lb_cents`, `price_variance_pct` and `shelf_life_days` all sit
    at 0."

    Design: Corner/endpoints/retail_item_write_then_read_then_scoped_list_round_trip
    """
    department = seeded_department(api)
    purchase = create_primal_purchase(api, department["id"])

    ribeye = create_retail_item(api, department["id"])
    chuck = create_retail_item(
        api,
        department["id"],
        item_code="CHK01",
        subprimal_code="CHUCK_ROAST",
        target_margin_pct=0.40,
    )
    ground = create_ground_item(api, department["id"])
    propose_price(api, ground["id"], purchase["id"])

    assert is_valid_uuid(ribeye["id"])
    assert ribeye["item_code"] == "RIB01"
    assert ribeye["price_status"] == "UNPRICED"
    assert ribeye["country_of_origin_label"] == "PENDING"
    assert ribeye["cost_basis_source"] == "CUT_TEST_LINE"
    assert ribeye["provisional_price_per_lb_cents"] == 0
    assert ribeye["final_price_per_lb_cents"] == 0
    assert ribeye["active_price_per_lb_cents"] == 0
    assert ribeye["shelf_life_days"] == 0
    assert ribeye["pricing_yield_pct_snapshot"] == pytest.approx(0.0, abs=0.0001)
    assert ribeye["yield_adjusted_cost_per_lb_cents"] == pytest.approx(0.0, abs=0.0001)
    assert ribeye["price_variance_pct"] == pytest.approx(0.0, abs=0.0001)
    assert ribeye["version"] == 1
    assert_retail_item(ribeye)

    read_back = read_retail_item(api, ribeye["id"])
    assert read_back["id"] == ribeye["id"]
    assert read_back["item_code"] == ribeye["item_code"]
    assert read_back["price_status"] == "UNPRICED"
    assert read_back["version"] == 1
    assert read_back["created_at"] == ribeye["created_at"]

    first_page, first_meta = validate_paginated(
        api.list_department_retail_items(
            department["id"],
            ANALYST,
            params={"price_status": "UNPRICED", "limit": 1, "offset": 0},
        )
    )
    # The ground item is already PROPOSED, so the filtered count is 2, not 3.
    assert first_meta["total_count"] == 2
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 1
    assert first_meta["offset"] == 0
    assert len(first_page) == 1

    second_page, second_meta = validate_paginated(
        api.list_department_retail_items(
            department["id"],
            ANALYST,
            params={"price_status": "UNPRICED", "limit": 1, "offset": 1},
        )
    )
    assert second_meta["total_count"] == 2
    assert second_meta["has_more"] is False
    assert len(second_page) == 1

    listed_ids = [first_page[0]["id"], second_page[0]["id"]]
    assert len(set(listed_ids)) == 2
    assert set(listed_ids) == {ribeye["id"], chuck["id"]}
    assert ground["id"] not in listed_ids


def test_replaying_the_pre_activation_item_version_blocks_a_second_activation(api):
    """Replaying the item version observed before the activation violates both the version pin at rung 7 and the state check at rung 8, and the lower rung answers: the second activation is refused on the stale pin and the shelf price does not move.

    "Activating a price requires `expected_retail_item_version` as a non-optional
    field in the request body, carrying the client's last observed `version` of the
    retail item. A mismatch with the item's current `version` is rejected with
    `ERR_STALE_PARENT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/replayed_item_version_blocks_a_second_price_activation
    """
    ctx = proposed_item(api)
    before = read_retail_item(api, ctx["whole_muscle_item"]["id"])
    assert before["price_status"] == "PROPOSED"
    assert before["provisional_price_per_lb_cents"] == RIB01_PROVISIONAL_PRICE
    stale_version = before["version"]

    activated = activate_price_from_cutting_test(
        api, before["id"], stale_version, ctx["cutting_test"]["id"]
    )
    assert activated["price_status"] == "PRICED"
    assert activated["final_price_per_lb_cents"] == RIB01_FINAL_PRICE
    assert activated["active_price_per_lb_cents"] == RIB01_FINAL_PRICE
    assert activated["price_variance_pct"] == pytest.approx(RIB01_VARIANCE, abs=0.0001)

    replayed = api.create_price_activation(
        before["id"],
        price_activation_payload(
            stale_version, cutting_test_id=ctx["cutting_test"]["id"]
        ),
        MANAGER,
    )
    validate_error(replayed, "ERR_STALE_PARENT_VERSION", 412)

    after = read_retail_item(api, before["id"])
    # Exactly one bump from the accepted activation, so the refused replay had no
    # effect of any kind on the price the scale is charging.
    assert after["version"] == stale_version + 1
    assert after["price_status"] == "PRICED"
    assert after["active_price_per_lb_cents"] == RIB01_FINAL_PRICE
    assert after["final_price_per_lb_cents"] == RIB01_FINAL_PRICE
    assert after["price_variance_pct"] == pytest.approx(RIB01_VARIANCE, abs=0.0001)
