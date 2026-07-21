"""How a rebate is priced: tier selection, per-line rounding, bonus and cap."""

from test_helpers import (
    TEST_USERS,
    api_client,
    attach_receipt,
    read_program,
    read_receipt,
    setup_catalogue,
    setup_claim_under_review,
    validate_receipt,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
PROCESSOR = TEST_USERS["claims_processor_headers"]


# --------------------------------------------------------------------------- #
# Provisional and final valuations run over different receipt sets
# --------------------------------------------------------------------------- #

def _dual_variant_setup():
    """A dealer claim with two receipts (30 + 25 units); only the first is validated."""
    ctx = setup_catalogue(
        program_overrides={"name": "Spring Tools Rebate"},
        budget_total_cents=100000000,
        offer_overrides={"name": "Tools Dealer Offer", "dealer_tier_enabled": True},
        claimant_overrides={"legal_name": "Northgate Tools LLC", "email": "ap@northgate.example"},
    )
    claim = validate_success(
        api_client.create_claim(
            {"offer_id": ctx["offer"]["id"], "claimant_id": ctx["claimant"]["id"]},
            ctx["headers"],
        ),
        201,
    )
    receipt_one = attach_receipt(
        claim["id"],
        ctx["claimant"],
        serial_number="SN-DV-1",
        purchase_date="2026-06-15T00:00:00Z",
        lines=[{"sku": "TOOLS-A", "quantity": 30, "unit_price_cents": 1999}],
    )
    receipt_two = attach_receipt(
        claim["id"],
        ctx["claimant"],
        serial_number="SN-DV-2",
        purchase_date="2026-06-16T00:00:00Z",
        lines=[{"sku": "TOOLS-B", "quantity": 25, "unit_price_cents": 999}],
    )
    ctx["claim"] = validate_success(api_client.submit_claim(claim["id"], ctx["headers"]))
    ctx["receipt_one"] = receipt_one
    ctx["receipt_two"] = receipt_two
    return ctx


def test_provisional_valuation_prices_all_receipts_at_the_top_dealer_tier(api):
    """PRD §3.5: "The provisional valuation includes *all* receipts attached to the
    claim, whether or not they have been validated; the tier it selects therefore
    reflects unverified units."
    PRD §3.5: "For a claimant of type `DEALER` the rate depends on the offer's
    `dealer_tier_enabled` flag: when that flag is false the rate is five percent
    whatever the unit count; when it is true, a unit total of 9 or fewer earns five
    percent, a unit total from 10 through 49 earns eight percent, and a unit total
    of 50 or more earns twelve percent."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_rebate_diverges_by_tier_on_claim
    """
    ctx = _dual_variant_setup()
    assert ctx["claim"]["provisional_rebate_cents"] == 10193
    assert ctx["claim"]["total_units"] == 55
    assert ctx["claim"]["adjudication_status"] == "SUBMITTED"


def test_final_valuation_drops_unvalidated_receipts_into_a_cheaper_tier(api):
    """PRD §3.5: "The final valuation includes *only* receipts whose `validated`
    flag is true. Receipts attached to any other claim never contribute to either
    valuation."
    PRD §3.6: "`final_rebate_cents` is stamped with the final valuation and
    `total_units` is recomputed over validated receipts only."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_rebate_diverges_by_tier_on_claim
    """
    ctx = _dual_variant_setup()
    validate_success(api.review_claim(ctx["claim"]["id"], PROCESSOR))
    validate_receipt(ctx["receipt_one"]["id"])

    approved = validate_success(api.approve_claim(ctx["claim"]["id"], PROCESSOR))
    assert approved["provisional_rebate_cents"] == 10193
    assert approved["final_rebate_cents"] == 4798
    assert approved["total_units"] == 30
    assert approved["adjudication_status"] == "APPROVED"
    assert read_receipt(ctx["receipt_two"]["id"])["validated"] is False


# --------------------------------------------------------------------------- #
# Per-line rounding order
# --------------------------------------------------------------------------- #

def _rounding_setup():
    return setup_claim_under_review(
        program_overrides={"name": "Rounding Program"},
        budget_total_cents=100000000,
        offer_overrides={"name": "Rounding Offer"},
        claimant_overrides={"legal_name": "Rounding Dealer", "email": "r@round.example"},
        serial_number="SN-RND-1",
        purchase_date="2026-06-20T00:00:00Z",
        lines=[
            {"sku": "TOOLS-A", "quantity": 1, "unit_price_cents": 1050},
            {"sku": "TOOLS-B", "quantity": 1, "unit_price_cents": 1050},
            {"sku": "TOOLS-C", "quantity": 1, "unit_price_cents": 1050},
        ],
    )


def test_each_line_rebate_is_rounded_before_the_lines_are_summed(api):
    """PRD §3.5: "For each line, multiply its `quantity` by its `unit_price_cents`
    by the selected rate, round that single result half up to whole cents, and add
    it to a running total. The rounding order is pinned: rounding each line before
    summing is correct, and summing the unrounded line values before rounding once
    is wrong and yields a different number of cents."

    Design: Difficulty/combinatorial_formula/per_line_rounding_order_pinned_on_rebate
    """
    ctx = _rounding_setup()
    assert ctx["claim"]["provisional_rebate_cents"] == 159

    approved = validate_success(api.approve_claim(ctx["claim"]["id"], PROCESSOR))
    assert approved["final_rebate_cents"] == 159


def test_receipt_gross_amount_stays_the_unrounded_sum_of_its_lines(api):
    """PRD §3.3: "On creation the server computes `line_count` as the number of
    entries in `lines`, `units` as the sum of the `quantity` values across those
    entries, and `gross_amount_cents` as the sum, over the entries, of `quantity`
    multiplied by `unit_price_cents`."
    PRD §3.5: "Walk the included receipts in ascending order of their `created_at`,
    and within each receipt walk its `lines` in the order the client submitted
    them."

    Design: Difficulty/combinatorial_formula/per_line_rounding_order_pinned_on_rebate
    """
    ctx = _rounding_setup()
    receipt = read_receipt(ctx["receipt"]["id"])
    assert receipt["gross_amount_cents"] == 3150
    assert receipt["line_count"] == 3

    approved = validate_success(api.approve_claim(ctx["claim"]["id"], PROCESSOR))
    assert approved["final_rebate_cents"] == 159, (
        "Three lines of 52.5 cents each round up individually to 53, summing to 159"
    )


# --------------------------------------------------------------------------- #
# Tier boundary and the consumer bonus / cap
# --------------------------------------------------------------------------- #

def test_dealer_tier_boundary_sits_between_nine_and_ten_units(api):
    """PRD §3.5: "For a claimant of type `DEALER` the rate depends on the offer's
    `dealer_tier_enabled` flag: when that flag is false the rate is five percent
    whatever the unit count; when it is true, a unit total of 9 or fewer earns five
    percent, a unit total from 10 through 49 earns eight percent, and a unit total
    of 50 or more earns twelve percent."
    PRD §3.5: "Sum the `quantity` values of every line of every included receipt to
    get the claim-level unit total."

    Design: Corner/calculations/dealer_tier_boundary_between_nine_and_ten_units
    """
    ctx = setup_claim_under_review(
        program_overrides={"name": "Tier Program"},
        budget_total_cents=100000000,
        offer_overrides={"name": "Tier Offer"},
        claimant_overrides={"legal_name": "Tier Dealer", "email": "ti@ti.example"},
        serial_number="SN-T9",
        lines=[{"sku": "TOOLS-A", "quantity": 9, "unit_price_cents": 1000}],
    )
    claim_nine = ctx["claim"]

    claim_ten = validate_success(
        api.create_claim(
            {"offer_id": ctx["offer"]["id"], "claimant_id": ctx["claimant"]["id"]},
            ctx["headers"],
        ),
        201,
    )
    receipt_ten = attach_receipt(
        claim_ten["id"],
        ctx["claimant"],
        serial_number="SN-T10",
        lines=[{"sku": "TOOLS-A", "quantity": 10, "unit_price_cents": 1000}],
    )
    validate_success(api.submit_claim(claim_ten["id"], ctx["headers"]))
    validate_success(api.review_claim(claim_ten["id"], PROCESSOR))
    validate_receipt(receipt_ten["id"])

    approved_nine = validate_success(api.approve_claim(claim_nine["id"], PROCESSOR))
    approved_ten = validate_success(api.approve_claim(claim_ten["id"], PROCESSOR))

    assert approved_nine["provisional_rebate_cents"] == 450
    assert approved_nine["final_rebate_cents"] == 450
    assert approved_nine["total_units"] == 9
    assert approved_ten["final_rebate_cents"] == 800
    assert approved_ten["total_units"] == 10


def test_consumer_bonus_is_added_once_and_then_the_offer_cap_clamps(api):
    """PRD §3.5: "If the claimant's `type` is `CONSUMER` and the running total from
    step three is greater than zero, add a flat 500 cents to it, once per claim."
    PRD §3.5: "The rebate is the lesser of the step-four total and the offer's
    `max_rebate_cents_per_claim`. No rounding is performed at step four or step
    five; both operands are already whole cents."

    Design: Corner/calculations/consumer_bonus_applied_once_and_offer_cap_clamps_the_total
    """
    ctx = setup_catalogue(
        channel="CONSUMER",
        claimant_type="CONSUMER",
        program_overrides={"name": "Cap Program"},
        budget_total_cents=100000000,
        offer_overrides={"name": "Cap Offer", "max_rebate_cents_per_claim": 2000},
        claimant_overrides={"legal_name": "Cap Consumer", "email": "cap@cap.example"},
    )
    claim = validate_success(
        api.create_claim(
            {"offer_id": ctx["offer"]["id"], "claimant_id": ctx["claimant"]["id"]},
            ctx["headers"],
        ),
        201,
    )
    receipt_a = attach_receipt(
        claim["id"],
        ctx["claimant"],
        serial_number="SN-CAP-1",
        purchase_date="2026-06-20T00:00:00Z",
        retailer_name="MegaMart",
        lines=[{"sku": "APPLIANCE-X", "quantity": 2, "unit_price_cents": 5000}],
    )
    receipt_b = attach_receipt(
        claim["id"],
        ctx["claimant"],
        serial_number="SN-CAP-2",
        purchase_date="2026-06-21T00:00:00Z",
        retailer_name="MegaMart",
        lines=[{"sku": "APPLIANCE-Y", "quantity": 2, "unit_price_cents": 5000}],
    )
    submitted = validate_success(api.submit_claim(claim["id"], ctx["headers"]))
    assert submitted["provisional_rebate_cents"] == 2000, (
        "1000 + 1000 plus the single 500-cent bonus is 2500, clamped by the 2000-cent cap"
    )

    validate_success(api.review_claim(claim["id"], PROCESSOR))
    validate_receipt(receipt_a["id"])
    validate_receipt(receipt_b["id"])

    approved = validate_success(api.approve_claim(claim["id"], PROCESSOR))
    assert approved["final_rebate_cents"] == 2000
    assert read_program(ctx["program"]["id"])["committed_cents"] == 2000
