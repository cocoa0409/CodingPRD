"""Per-line pricing and the order money roll-up.

The cut-charge tier, the master put-up rounding, the four-decimal copper
pass-through with its once-per-line rounding, the rebate tiers and the
free-freight waiver.
"""

import pytest

from test_helpers import (
    PRODUCT_P1,
    PRODUCT_P3,
    PRODUCT_P4,
    build_quote,
    create_branch,
    create_customer,
    create_product,
    issue_quote,
    make_sales_rep_headers,
    publish_index,
    read_quote,
    read_quote_line,
    validate_success,
)


# ══════════════════════════════════════════════════════════════════════════
# The cut-charge tier is keyed on the per-conductor billable length
# ══════════════════════════════════════════════════════════════════════════

def _paralleled_cut_quote():
    """A single 200 ft CUT line of P1 with three paralleled conductors,
    issued at the default clock against a 450 c/lb settlement."""
    branch = create_branch()
    customer = create_customer()
    product = create_product(PRODUCT_P1)
    publish_index("2026-07-30", 450)
    quote, lines = build_quote(
        customer["id"], branch["id"], product["id"],
        [{"put_up": "CUT", "requested_length_ft": 200, "parallel_set_size": 3}],
    )
    issue_quote(quote["id"], issuer="rep-2")
    return read_quote(quote["id"]), read_quote_line(lines[0]["id"])


def test_cut_charge_tier_uses_the_per_conductor_length_not_the_paralleled_total(api):
    """PRD §3.3: "The cut charge is then selected from a three-way tier, and
    the tier is keyed on the per-conductor `billable_length_ft`, never on the
    paralleled total."
    PRD §3.3: "Otherwise, a per-conductor billable length below 100 feet
    carries twice the part's `cut_charge_cents`, because short cuts cost the
    same setup as long ones; a per-conductor billable length from 100 feet up
    to but not including 500 feet carries exactly one times `cut_charge_cents`;
    and a per-conductor billable length of 500 feet or more carries no cut
    charge, the cut being absorbed into the volume."
    PRD §3.3: "Paralleling multiplies the resulting charge rather than the
    tier: `cut_charge_cents_total` is the per-conductor charge multiplied by
    `parallel_set_size`."
    PRD §3.4: "The line's total billable footage is its per-conductor
    `billable_length_ft` multiplied by its `parallel_set_size`."

    Design: Difficulty/combinatorial_formula/cut_charge_tier_keyed_on_per_conductor_billable_length_mode_a
    """
    _, line = _paralleled_cut_quote()

    assert line["billable_length_ft"] == 200
    assert line["cut_charge_cents_total"] == 10500, (
        "the 200 ft per-conductor length selects the one-times tier (3500) "
        "which is then multiplied by the paralleled set size of 3"
    )
    assert line["base_cents"] == 10800
    assert line["metal_cents"] == 3375
    assert line["deposit_cents_total"] == 0
    assert line["quoted_extended_cents"] == 24675


def test_paralleled_line_counts_every_conductor_in_the_physical_reel_count(api):
    """PRD §3.4: "Second, `physical_reel_count` is the sum across lines of
    each line's `reel_count` multiplied by its `parallel_set_size`, and
    `gross_freight_cents` is a flat base of 8,500 cents, plus 2,500 cents for
    every physical reel counted, plus the shipping branch's
    `delivery_surcharge_cents`."
    PRD §3.4: "Sixth, `quoted_total_cents` is `line_subtotal_cents` plus
    `freight_cents` less `rebate_cents`."

    Design: Difficulty/combinatorial_formula/cut_charge_tier_keyed_on_per_conductor_billable_length_mode_a
    """
    quote, _ = _paralleled_cut_quote()

    assert quote["physical_reel_count"] == 3
    assert quote["gross_freight_cents"] == 16000
    assert quote["quoted_total_cents"] == 40675


# ══════════════════════════════════════════════════════════════════════════
# The metal component is rounded once per line, then summed
# ══════════════════════════════════════════════════════════════════════════

def _two_identical_137_foot_lines():
    branch = create_branch()
    customer = create_customer()
    product = create_product(PRODUCT_P1)
    publish_index("2026-07-30", 450)
    quote, lines = build_quote(
        customer["id"], branch["id"], product["id"],
        [
            {"put_up": "CUT", "requested_length_ft": 137},
            {"put_up": "CUT", "requested_length_ft": 137},
        ],
    )
    issue_quote(quote["id"], issuer="rep-2")
    return read_quote(quote["id"]), [read_quote_line(l["id"]) for l in lines]


def test_metal_cents_is_rounded_half_up_once_on_each_line(api):
    """PRD §3.4: "For a `COPPER` part, `copper_adder_cents_per_ft` is the
    pinned entry's `price_cents_per_lb` multiplied by the part's
    `copper_lbs_per_1000ft` divided by one thousand — that is, cents per pound
    times pounds per foot."
    PRD §3.4: "From that, `metal_cents` is the `copper_adder_cents_per_ft`
    multiplied by the total billable footage and then rounded half up to whole
    cents — rounded once, on this line, before any summation."

    Design: Difficulty/combinatorial_formula/metal_rounding_per_line_then_sum_mode_b
    """
    _, lines = _two_identical_137_foot_lines()

    for line in lines:
        assert line["copper_adder_cents_per_ft"] == pytest.approx(5.6250, abs=5e-5), (
            "the pass-through is held at exactly four decimal places, unrounded"
        )
        assert line["metal_cents"] == 771


def test_line_subtotal_sums_the_already_rounded_per_line_values(api):
    """PRD §3.4: "It is forbidden to accumulate the unrounded pass-through
    across lines and round the sum once: two identical 137-foot lines of a
    part priced at 5.6250 cents per foot yield 771 plus 771, that is 1542
    metal cents in total, not the 1541 that a single rounding of the sum would
    produce."
    PRD §3.4: "First, `line_subtotal_cents` is the sum, across all lines, of
    the already-rounded per-line extended values."

    Design: Difficulty/combinatorial_formula/metal_rounding_per_line_then_sum_mode_b
    """
    quote, lines = _two_identical_137_foot_lines()

    assert sum(line["metal_cents"] for line in lines) == 1542
    assert quote["line_subtotal_cents"] == 13474, (
        "summing the unrounded pass-through first would yield 13473"
    )
    assert quote["quoted_total_cents"] == 26974


# ══════════════════════════════════════════════════════════════════════════
# The pinned six-step roll-up: rebate tier, then the free-freight waiver
# ══════════════════════════════════════════════════════════════════════════

def _aluminium_quote_at_surcharge(surcharge_cents):
    """A single 4800 ft aluminium CUT line out of a branch carrying
    `surcharge_cents` of delivery surcharge, authored by rep-1 and issued by
    rep-2 because the 480,000-cent subtotal is at the review threshold."""
    branch = create_branch(
        name=f"Surcharge {surcharge_cents} DC",
        delivery_surcharge_cents=surcharge_cents,
    )
    customer = create_customer()
    product = create_product(PRODUCT_P3)
    publish_index("2026-07-30", 450)
    quote, _ = build_quote(
        customer["id"], branch["id"], product["id"],
        [{"put_up": "CUT", "requested_length_ft": 4800}],
        creator="rep-1",
    )
    issue_quote(quote["id"], issuer="rep-2")
    return read_quote(quote["id"])


def test_free_freight_waiver_fires_at_exactly_the_post_rebate_threshold(api):
    """PRD §3.4: "Third, the volume rebate tier is selected on a basis equal
    to `line_subtotal_cents` plus `gross_freight_cents`: a basis below 200,000
    cents (2,000 dollars) sets `rebate_pct` to 0.000; a basis of 200,000 cents
    or more but below 500,000 cents (5,000 dollars) sets `rebate_pct` to
    0.015; a basis of 500,000 cents or more sets `rebate_pct` to 0.030."
    PRD §3.4: "Fifth, the free-freight waiver is tested on the post-rebate
    net: take `line_subtotal_cents` plus `gross_freight_cents` less
    `rebate_cents`, and if that net is 500,000 cents or more — the comparison
    is inclusive of the threshold — then `freight_cents` is 0, otherwise
    `freight_cents` equals `gross_freight_cents`."

    Design: Difficulty/combinatorial_formula/freight_waiver_and_rebate_tier_evaluation_order_mode_c
    """
    quote = _aluminium_quote_at_surcharge(23_400)

    assert quote["line_subtotal_cents"] == 480000
    assert quote["gross_freight_cents"] == 34400
    assert quote["rebate_pct"] == pytest.approx(0.03, abs=1e-9)
    assert quote["rebate_cents"] == 14400
    assert quote["freight_cents"] == 0, (
        "a post-rebate net of exactly 500000 waives the freight"
    )
    assert quote["quoted_total_cents"] == 465600


def test_one_cent_below_the_waiver_threshold_still_bills_the_full_freight(api):
    """PRD §3.4: "Fifth, the free-freight waiver is tested on the post-rebate
    net: take `line_subtotal_cents` plus `gross_freight_cents` less
    `rebate_cents`, and if that net is 500,000 cents or more — the comparison
    is inclusive of the threshold — then `freight_cents` is 0, otherwise
    `freight_cents` equals `gross_freight_cents`."
    PRD §3.4: "The rebate tier is emphatically not recomputed after the waiver
    zeroes freight, even though the basis would now be lower."

    Design: Difficulty/combinatorial_formula/freight_waiver_and_rebate_tier_evaluation_order_mode_c
    """
    quote = _aluminium_quote_at_surcharge(23_399)

    assert quote["gross_freight_cents"] == 34399
    assert quote["rebate_pct"] == pytest.approx(0.03, abs=1e-9)
    assert quote["rebate_cents"] == 14400, (
        "the rebate tier is selected before the waiver and never recomputed"
    )
    assert quote["freight_cents"] == 34399
    assert quote["quoted_total_cents"] == 499999


# ══════════════════════════════════════════════════════════════════════════
# Single-mode pricing corners
# ══════════════════════════════════════════════════════════════════════════

def test_aluminium_line_carries_a_zero_copper_pass_through(api):
    """PRD §3.4: "For a part whose `conductor_metal` is `ALUMINUM`, the copper
    pass-through `copper_adder_cents_per_ft` is exactly zero at four decimal
    places."
    PRD §3.4: "`base_cents` is the part's `base_price_cents_per_ft` multiplied
    by the same total billable footage, and being a product of integers it is
    exact."

    Design: Corner/calculations/aluminium_product_receives_zero_copper_adder
    """
    branch = create_branch()
    customer = create_customer()
    product = create_product(PRODUCT_P3)
    publish_index("2026-07-30", 450)
    quote, lines = build_quote(
        customer["id"], branch["id"], product["id"],
        [{"put_up": "CUT", "requested_length_ft": 1000}],
    )
    issue_quote(quote["id"], issuer="rep-1")

    line = read_quote_line(lines[0]["id"])
    assert line["copper_adder_cents_per_ft"] == pytest.approx(0.0, abs=5e-5)
    assert line["metal_cents"] == 0
    assert line["base_cents"] == 100000
    assert line["cut_charge_cents_total"] == 0
    assert line["quoted_extended_cents"] == 100000


def test_master_put_up_rounds_up_to_whole_reels(api):
    """PRD §3.3: "For a `MASTER_REEL` line, `reel_count` is
    `requested_length_ft` divided by the part's `master_reel_length_ft`,
    rounded up to the next whole number, and `billable_length_ft` is that reel
    count multiplied by `master_reel_length_ft` — the customer buys whole
    put-ups."
    PRD §3.3: "`deposit_cents_total` is the part's `reel_deposit_cents`
    multiplied by `reel_count` and again by `parallel_set_size` for a
    `MASTER_REEL` line, and is 0 for a `CUT` line — cut cable ships on a
    disposable reel and carries no refundable deposit."

    Design: Corner/calculations/master_put_up_rounds_up_to_whole_reels
    """
    branch = create_branch()
    customer = create_customer()
    product = create_product(PRODUCT_P1)
    publish_index("2026-07-30", 450)
    quote, lines = build_quote(
        customer["id"], branch["id"], product["id"],
        [{"put_up": "MASTER_REEL", "requested_length_ft": 2501}],
    )
    issue_quote(quote["id"], issuer="rep-2")

    line = read_quote_line(lines[0]["id"])
    refreshed = read_quote(quote["id"])

    assert line["reel_count"] == 2
    assert line["billable_length_ft"] == 5000
    assert line["base_cents"] == 90000
    assert line["metal_cents"] == 28125
    assert line["cut_charge_cents_total"] == 0
    assert line["deposit_cents_total"] == 25000
    assert line["quoted_extended_cents"] == 118125
    assert refreshed["physical_reel_count"] == 2
    assert refreshed["deposit_quoted_cents"] == 25000
    assert refreshed["quoted_total_cents"] == 131625


def test_cut_below_one_hundred_feet_carries_twice_the_cut_charge(api):
    """PRD §3.3: "Otherwise, a per-conductor billable length below 100 feet
    carries twice the part's `cut_charge_cents`, because short cuts cost the
    same setup as long ones; a per-conductor billable length from 100 feet up
    to but not including 500 feet carries exactly one times `cut_charge_cents`;
    and a per-conductor billable length of 500 feet or more carries no cut
    charge, the cut being absorbed into the volume."

    Design: Corner/calculations/short_cut_tier_doubles_the_cut_charge_below_100_ft
    """
    branch = create_branch()
    customer = create_customer()
    product = create_product(PRODUCT_P4)
    publish_index("2026-07-30", 450)
    quote, lines = build_quote(
        customer["id"], branch["id"], product["id"],
        [{"put_up": "CUT", "requested_length_ft": 60}],
    )
    issue_quote(quote["id"], issuer="rep-2")

    line = read_quote_line(lines[0]["id"])
    assert line["billable_length_ft"] == 60
    assert line["cut_charge_cents_total"] == 3000
    assert line["copper_adder_cents_per_ft"] == pytest.approx(0.9000, abs=5e-5)
    assert line["metal_cents"] == 54
    assert line["base_cents"] == 240
    assert line["quoted_extended_cents"] == 3294


def test_rebate_middle_tier_applies_between_the_two_breakpoints(api):
    """PRD §3.4: "Third, the volume rebate tier is selected on a basis equal
    to `line_subtotal_cents` plus `gross_freight_cents`: a basis below 200,000
    cents (2,000 dollars) sets `rebate_pct` to 0.000; a basis of 200,000 cents
    or more but below 500,000 cents (5,000 dollars) sets `rebate_pct` to
    0.015; a basis of 500,000 cents or more sets `rebate_pct` to 0.030."
    PRD §3.4: "Fourth, `rebate_cents` is `line_subtotal_cents` multiplied by
    `rebate_pct`, rounded half up to whole cents — the rebate applies to the
    subtotal alone and never to freight."
    PRD §2.9: "When that freshly computed subtotal reaches 250,000 cents
    (2,500 dollars) or more, the issuing operator's `X-User-ID` must differ
    from the quote's `created_by_user_id`; below that threshold a rep may
    issue their own quote."

    Design: Corner/calculations/rebate_middle_tier_applies_between_the_two_breakpoints
    """
    branch = create_branch()
    customer = create_customer()
    product = create_product(PRODUCT_P3)
    publish_index("2026-07-30", 450)
    quote, _ = build_quote(
        customer["id"], branch["id"], product["id"],
        [{"put_up": "CUT", "requested_length_ft": 1900}],
        creator="rep-1",
    )

    response = api.issue_quote(quote["id"], make_sales_rep_headers("rep-1"))
    validate_success(response, 200)

    refreshed = read_quote(quote["id"])
    assert refreshed["line_subtotal_cents"] == 190000
    assert refreshed["gross_freight_cents"] == 11000
    assert refreshed["rebate_pct"] == pytest.approx(0.015, abs=1e-9)
    assert refreshed["rebate_cents"] == 2850
    assert refreshed["freight_cents"] == 11000
    assert refreshed["quoted_total_cents"] == 198150
    assert refreshed["issued_by_user_id"] == "rep-1"
