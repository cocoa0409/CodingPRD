"""Composition of tier selection, both allowance caps and the off-posted test on a line."""

from test_helpers import (
    assert_invoice_line,
    assert_retailer_invoice,
    new_tier,
    read_invoice,
    read_invoice_line,
    read_tier,
    set_clock,
    setup_certified_schedule,
    setup_invoice_with_lines,
    run_posting,
    read_item,
    read_schedule,
)


def _two_tier_scene():
    """One posted item carrying a five-case and a ten-case tier, then made effective."""
    scene = setup_certified_schedule()
    item = scene["items"][0]
    scene["tier_five"] = new_tier(
        item["id"], scene["agent_headers"], min_cases=5, discount_pct=0.05
    )
    scene["tier_ten"] = new_tier(
        item["id"], scene["agent_headers"], min_cases=10, discount_pct=0.12
    )
    set_clock("2026-10-01T00:00:00Z")
    scene["posting_run"] = run_posting(scene["program"]["id"])
    scene["schedule"] = read_schedule(scene["schedule"]["id"])
    scene["items"] = [read_item(item["id"]) for item in scene["items"]]
    return scene


def _zero_case_scene():
    """One posted item with a two-case tier, then an invoice holding a zero-case line."""
    scene = setup_certified_schedule()
    item = scene["items"][0]
    scene["tier"] = new_tier(
        item["id"], scene["agent_headers"], min_cases=2, discount_pct=0.10
    )
    set_clock("2026-10-01T00:00:00Z")
    scene["posting_run"] = run_posting(scene["program"]["id"])
    scene["items"] = [read_item(entry["id"]) for entry in scene["items"]]
    setup_invoice_with_lines(
        scene,
        "2026-10-05T00:00:00Z",
        [
            {
                "item_id": item["id"],
                "cases_quantity": 0,
                "bottles_quantity": 5,
                "case_price_charged_cents": 120_000,
                "unit_price_charged_cents": 11_000,
                "promotional_allowance_cents": 2_750,
                "depletion_allowance_cents": 1,
            },
            {
                "item_id": item["id"],
                "cases_quantity": 2,
                "bottles_quantity": 0,
                "case_price_charged_cents": 120_000,
                "unit_price_charged_cents": 11_000,
                "promotional_allowance_cents": 0,
                "depletion_allowance_cents": 300,
            },
        ],
    )
    return scene


def test_line_takes_the_eligible_tier_with_the_greatest_min_cases():
    """Two eligible tiers; the deeper threshold wins and prices the case quantity.

    PRD §3.8: "If some are, the selected tier is the one with the greatest `min_cases`;
    ties are broken by the greatest `discount_pct`; any remaining tie is broken by the
    earliest `created_at` — ascending."

    Design: Difficulty/combinatorial_formula/invoice_line_net_price_composes_tier_selection_with_two_independent_allowance_caps
    """
    scene = _two_tier_scene()
    item = scene["items"][0]

    tier_five = read_tier(scene["tier_five"]["id"])
    tier_ten = read_tier(scene["tier_ten"]["id"])
    assert tier_five["discounted_case_price_cents"] == 114_000
    assert tier_ten["discounted_case_price_cents"] == 105_600

    setup_invoice_with_lines(
        scene,
        "2026-10-05T00:00:00Z",
        [
            {
                "item_id": item["id"],
                "cases_quantity": 12,
                "bottles_quantity": 7,
                "case_price_charged_cents": 120_000,
                "unit_price_charged_cents": 11_000,
                "promotional_allowance_cents": 100_000,
                "depletion_allowance_cents": 3_000,
            }
        ],
    )

    line = read_invoice_line(scene["lines"][0]["id"])
    assert_invoice_line(line)
    assert line["gross_cents"] == 1_517_000
    assert line["quantity_discount_cents"] == 172_800


def test_line_net_price_deducts_both_capped_allowances_and_keeps_the_excesses_as_exposure():
    """The promotional cap floors, the depletion cap is per case, and only the allowed parts reduce the bill.

    PRD §3.8: "The `net_price_cents` is then `gross_cents`, less
    `quantity_discount_cents`, less `allowed_promotional_cents`, less
    `allowed_depletion_cents`."

    Design: Difficulty/combinatorial_formula/invoice_line_net_price_composes_tier_selection_with_two_independent_allowance_caps
    """
    scene = _two_tier_scene()
    item = scene["items"][0]

    setup_invoice_with_lines(
        scene,
        "2026-10-05T00:00:00Z",
        [
            {
                "item_id": item["id"],
                "cases_quantity": 12,
                "bottles_quantity": 7,
                "case_price_charged_cents": 120_000,
                "unit_price_charged_cents": 11_000,
                "promotional_allowance_cents": 100_000,
                "depletion_allowance_cents": 3_000,
            }
        ],
    )

    line = read_invoice_line(scene["lines"][0]["id"])
    assert line["allowed_promotional_cents"] == 75_850
    assert line["excess_promotional_cents"] == 24_150
    assert line["allowed_depletion_cents"] == 1_800
    assert line["excess_depletion_cents"] == 1_200
    assert line["net_price_cents"] == 1_266_550
    assert line["posted_gross_cents"] == 1_517_000
    assert line["variance_cents"] == 0
    assert line["finding_variance_cents"] == 25_350
    assert line["is_off_posted"] is True

    invoice = read_invoice(scene["invoice"]["id"])
    assert_retailer_invoice(invoice)
    assert invoice["total_allowance_cents"] == 77_650
    assert invoice["validation_status"] == "FLAGGED"


def test_zero_case_line_finds_no_eligible_tier_and_collapses_the_depletion_cap():
    """With no cases on the line the two per-case instruments both fall to nothing.

    PRD §3.8: "The depletion cap is `cases_quantity` multiplied by the program's
    `depletion_allowance_per_case_cents` — with the default of 150 cents per case, a
    dollar fifty per case, and nothing at all allowed for loose bottles."

    Design: Difficulty/boundary_precision_check/zero_case_line_collapses_the_depletion_cap_to_zero_and_empties_the_eligible_tier_set
    """
    scene = _zero_case_scene()

    line_zero = read_invoice_line(scene["lines"][0]["id"])
    assert_invoice_line(line_zero)
    assert line_zero["cases_quantity"] == 0
    assert line_zero["bottles_quantity"] == 5
    assert line_zero["gross_cents"] == 55_000
    assert line_zero["quantity_discount_cents"] == 0
    assert line_zero["allowed_promotional_cents"] == 2_750
    assert line_zero["excess_promotional_cents"] == 0
    assert line_zero["allowed_depletion_cents"] == 0
    assert line_zero["excess_depletion_cents"] == 1
    assert line_zero["net_price_cents"] == 52_250


def test_zero_case_line_is_off_posted_on_the_over_cap_allowance_alone():
    """Charged prices match the posting exactly, yet one cent of over-cap allowance exposes the line.

    PRD §3.8: "The `finding_variance_cents` is the absolute value of `variance_cents`,
    plus `excess_promotional_cents`, plus `excess_depletion_cents` — a line can therefore
    be exposed for charging exactly the posted price while handing over an over-cap
    allowance."

    Design: Difficulty/boundary_precision_check/zero_case_line_collapses_the_depletion_cap_to_zero_and_empties_the_eligible_tier_set
    """
    scene = _zero_case_scene()

    line_zero = read_invoice_line(scene["lines"][0]["id"])
    assert line_zero["posted_gross_cents"] == 55_000
    assert line_zero["variance_cents"] == 0
    assert line_zero["finding_variance_cents"] == 1
    assert line_zero["is_off_posted"] is True

    invoice = read_invoice(scene["invoice"]["id"])
    assert invoice["validation_status"] == "FLAGGED"
    assert invoice["off_posted_line_count"] == 1
    assert invoice["total_variance_cents"] == 1


def test_two_case_control_line_takes_the_tier_and_the_whole_depletion_allowance():
    """The sibling line proves the collapse is the zero quantity, not the configuration.

    PRD §3.8: "The `quantity_discount_cents` is then `cases_quantity` multiplied by the
    difference between the item's own `case_price_cents` and the selected tier's
    `discounted_case_price_cents`."

    Design: Difficulty/boundary_precision_check/zero_case_line_collapses_the_depletion_cap_to_zero_and_empties_the_eligible_tier_set
    """
    scene = _zero_case_scene()

    line_two = read_invoice_line(scene["lines"][1]["id"])
    assert_invoice_line(line_two)
    assert line_two["gross_cents"] == 240_000
    assert line_two["quantity_discount_cents"] == 24_000
    assert line_two["allowed_depletion_cents"] == 300
    assert line_two["excess_depletion_cents"] == 0
    assert line_two["net_price_cents"] == 215_700
    assert line_two["variance_cents"] == 0
    assert line_two["finding_variance_cents"] == 0
    assert line_two["is_off_posted"] is False

    invoice = read_invoice(scene["invoice"]["id"])
    assert invoice["line_count"] == 2
    assert invoice["subtotal_cents"] == 267_950
    assert invoice["surcharge_cents"] == 0
    assert invoice["total_cents"] == 267_950
    assert invoice["total_allowance_cents"] == 3_050
