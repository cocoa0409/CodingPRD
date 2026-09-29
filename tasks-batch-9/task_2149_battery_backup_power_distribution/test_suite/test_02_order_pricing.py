"""Order pricing: line discounts, per-line rounding and total assembly."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_warehouse, create_account, create_battery_model, create_order,
    add_line, submit_order, read_order, read_order_line, read_account,
    api_client, TEST_USERS,
)

REP = TEST_USERS["sales_rep_headers"]


def _three_line_micro_order():
    """A PLATINUM order carrying three identical five-unit lines of a 6001 cent model."""
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.0, dock_capacity_kg_per_window=100000.0)
    account = create_account(name="Pinnacle Power", account_tier="PLATINUM",
                             state_code="TX", credit_limit_cents=100000000,
                             storm_priority_rank=1)
    model = create_battery_model("IB-MICRO-6")
    order = create_order(account["id"], warehouse["id"], requested_ship_date="2026-08-12")
    lines = [add_line(order["id"], model["id"], 5, core_expected_count=0) for _ in range(3)]
    return {"warehouse": warehouse, "account": account, "model": model,
            "order": order, "lines": lines}


def test_subtotal_sums_the_individually_rounded_line_totals():
    """PRD §3.3: "The line's `line_total_cents` is then the snapshot unit price
    multiplied by the line quantity multiplied by one minus that discount,
    **rounded half up to a whole cent on this line**. Only after every line has
    been rounded individually are the rounded line totals summed into the
    order's `subtotal_cents`. Summing the unrounded products and rounding once
    at the end is explicitly not the rule and yields a different subtotal."
    PRD §3.3: "The tier component comes from the buying account's
    `account_tier`: 12 percent for `PLATINUM`, 7 percent for `GOLD` and nothing
    at all for `STANDARD`."

    Design: Difficulty/combinatorial_formula/subtotal_rounds_each_line_before_summing
    """
    ctx = _three_line_micro_order()
    submitted = submit_order(ctx["order"]["id"])

    for line in ctx["lines"]:
        stored = read_order_line(line["id"])
        assert stored["discount_pct"] == pytest.approx(0.12, abs=1e-9), \
            f"PLATINUM tier alone discounts 12 percent, got {stored['discount_pct']}"
        assert stored["line_total_cents"] == 26404, \
            f"Expected 26404 on a line rounded by itself, got {stored['line_total_cents']}"

    assert submitted["subtotal_cents"] == 79212, \
        f"Expected 79212 from three rounded lines, got {submitted['subtotal_cents']}"
    assert submitted["subtotal_cents"] != 79213, \
        "79213 is the forbidden sum-then-round result"


def test_order_total_adds_core_deposit_and_forecast_hazmat_fee_to_the_subtotal():
    """PRD §3.3: "Step four computes `core_deposit_charge_cents` as the sum,
    over every line, of the line's quantity less its promised core count,
    multiplied by that line's model `core_deposit_cents` — the buyer is charged
    a deposit only for the units it did not promise to exchange."
    PRD §3.3: "Step five sets `total_cents` to the subtotal plus the core
    deposit charge plus the hazmat fee plus `service_contract_fee_cents`, which
    is zero until a service contract attaches."
    PRD §3.3: "The two components are added, and if the order's warehouse holds
    a hazmat endorsement the sum is multiplied by 0.85 — a fifteen percent
    endorsed-site discount — and rounded half up to whole cents; an unendorsed
    site pays the sum unreduced."

    Design: Difficulty/combinatorial_formula/subtotal_rounds_each_line_before_summing
    """
    ctx = _three_line_micro_order()
    submitted = submit_order(ctx["order"]["id"])

    assert submitted["core_deposit_charge_cents"] == 7500, \
        f"Expected 7500 of deposit on 15 unpromised units, got {submitted['core_deposit_charge_cents']}"
    assert submitted["hazmat_fee_cents"] == 2210, \
        f"Expected the endorsed-site forecast surcharge 2210, got {submitted['hazmat_fee_cents']}"
    assert submitted["total_cents"] == 88922, \
        f"Expected 88922, got {submitted['total_cents']}"
    assert submitted["service_contract_fee_cents"] == 0


def _twenty_unit_high_value_order():
    """A single 20-unit line whose subtotal lands just under the waiver threshold."""
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.0, dock_capacity_kg_per_window=100000.0)
    account = create_account(name="Gulf Coast Standby", account_tier="STANDARD",
                             state_code="TX", credit_limit_cents=100000000,
                             storm_priority_rank=7)
    model = create_battery_model("IB-PWR-2500")
    order = create_order(account["id"], warehouse["id"], requested_ship_date="2026-08-14")
    line = add_line(order["id"], model["id"], 20, core_expected_count=0)
    return {"warehouse": warehouse, "account": account, "model": model,
            "order": order, "line": line}


def test_hazmat_waiver_is_decided_on_the_subtotal_alone():
    """PRD §3.3: "Step two decides `hazmat_fee_waived`, and it is keyed on
    `subtotal_cents` **alone**: the flag is true when the subtotal is at least
    5000000 cents — that is, fifty thousand dollars of product before any fee —
    and false otherwise."
    PRD §3.3: "That decision is made exactly once, at submission, and is never
    re-decided when the hazmat fee or the service-contract fee changes later,
    even though those fees are part of the order total."

    Design: Difficulty/combinatorial_formula/hazmat_waiver_keyed_on_subtotal_not_on_total
    """
    ctx = _twenty_unit_high_value_order()
    submitted = submit_order(ctx["order"]["id"])

    assert submitted["subtotal_cents"] == 4995005, \
        f"Expected 4995005, got {submitted['subtotal_cents']}"
    assert submitted["hazmat_fee_waived"] is False, \
        "A subtotal of 4995005 is below the 5000000 cent waiver threshold"
    assert submitted["hazmat_fee_cents"] == 18785, \
        f"An unwaived order carries the forecast surcharge, got {submitted['hazmat_fee_cents']}"


def test_order_total_can_exceed_the_waiver_threshold_while_the_fee_still_applies():
    """PRD §3.3: "Step three sets `hazmat_fee_cents` to zero when the waiver
    applies and otherwise to the forecast hazmat surcharge described below."
    PRD §3.3: "The volume component comes from the line's own quantity: 5
    percent at 100 units or more, 3 percent at 25 units or more but fewer than
    100, 1 percent at 10 units or more but fewer than 25, and nothing below 10."

    Design: Difficulty/combinatorial_formula/hazmat_waiver_keyed_on_subtotal_not_on_total
    """
    ctx = _twenty_unit_high_value_order()
    submitted = submit_order(ctx["order"]["id"])
    line = read_order_line(ctx["line"]["id"])

    assert line["discount_pct"] == pytest.approx(0.01, abs=1e-9), \
        f"20 units on a STANDARD account discounts 1 percent, got {line['discount_pct']}"
    assert submitted["core_deposit_charge_cents"] == 44000, \
        f"Expected 44000, got {submitted['core_deposit_charge_cents']}"
    assert submitted["total_cents"] == 5057790, \
        f"Expected 5057790, got {submitted['total_cents']}"
    assert submitted["total_cents"] > 5000000 and submitted["hazmat_fee_cents"] > 0, \
        "The total clears the threshold yet the fee is still charged"


def _order_of(quantity, tier="STANDARD", account_name="Delta Fleet", rank=5,
              site_code="TX-DAL", sku="IB-AGM-95"):
    """A one-line order of `quantity` AGM units at an endorsed Texas site.

    `site_code` and `sku` are parameters because a warehouse `code` and a
    catalog `sku` are both unique across their collections: a test that builds
    two of these environments must name them distinctly.
    """
    from test_helpers import create_warehouse
    warehouse = create_warehouse(code=site_code, state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.0, dock_capacity_kg_per_window=100000.0)
    account = create_account(name=account_name, account_tier=tier, state_code="TX",
                             credit_limit_cents=100000000, storm_priority_rank=rank)
    model = create_battery_model("IB-AGM-95", sku=sku)
    order = create_order(account["id"], warehouse["id"], requested_ship_date="2026-08-10")
    line = add_line(order["id"], model["id"], quantity, core_expected_count=0)
    return {"warehouse": warehouse, "account": account, "model": model,
            "order": order, "line": line}


def test_volume_break_steps_up_at_exactly_twenty_five_units():
    """PRD §3.3: "The volume component comes from the line's own quantity: 5
    percent at 100 units or more, 3 percent at 25 units or more but fewer than
    100, 1 percent at 10 units or more but fewer than 25, and nothing below 10."
    PRD §3.3: "The line's `line_total_cents` is then the snapshot unit price
    multiplied by the line quantity multiplied by one minus that discount,
    **rounded half up to a whole cent on this line**."

    Design: Corner/calculations/volume_discount_step_at_exactly_twenty_five_units
    """
    below = _order_of(24, site_code="TX-DAL", sku="IB-AGM-95-A")
    submitted_below = submit_order(below["order"]["id"])
    line_below = read_order_line(below["line"]["id"])
    assert line_below["discount_pct"] == pytest.approx(0.01, abs=1e-9)
    assert line_below["line_total_cents"] == 617760
    assert submitted_below["total_cents"] == 694930

    at_break = _order_of(25, site_code="TX-HOU", sku="IB-AGM-95-B")
    submitted_at = submit_order(at_break["order"]["id"])
    line_at = read_order_line(at_break["line"]["id"])
    assert line_at["discount_pct"] == pytest.approx(0.03, abs=1e-9), \
        f"25 units reaches the 3 percent break, got {line_at['discount_pct']}"
    assert line_at["line_total_cents"] == 630500
    assert submitted_at["total_cents"] == 710638


def test_tier_and_volume_discounts_are_capped_at_fifteen_percent():
    """PRD §3.3: "The two components are added together, the sum is capped at 15
    percent — no combination of tier and volume may ever discount a line further
    — and the capped figure is rounded half up to four decimal places and stored
    as `discount_pct`."
    PRD §3.3: "The tier component comes from the buying account's
    `account_tier`: 12 percent for `PLATINUM`, 7 percent for `GOLD` and nothing
    at all for `STANDARD`."

    Design: Corner/calculations/combined_discount_is_capped_at_fifteen_percent
    """
    ctx = _order_of(100, tier="PLATINUM", account_name="Pinnacle Power", rank=1)
    submitted = submit_order(ctx["order"]["id"])
    line = read_order_line(ctx["line"]["id"])

    assert line["discount_pct"] == pytest.approx(0.15, abs=1e-9), \
        f"0.12 plus 0.05 clamps to 0.15, got {line['discount_pct']}"
    assert line["line_total_cents"] == 2210000
    assert submitted["subtotal_cents"] == 2210000
    assert submitted["core_deposit_charge_cents"] == 250000
    assert submitted["hazmat_fee_cents"] == 66725
    assert submitted["total_cents"] == 2526725


def test_hazmat_fee_is_waived_when_the_subtotal_lands_on_the_threshold():
    """PRD §3.3: "Step two decides `hazmat_fee_waived`, and it is keyed on
    `subtotal_cents` **alone**: the flag is true when the subtotal is at least
    5000000 cents — that is, fifty thousand dollars of product before any fee —
    and false otherwise."
    PRD §3.3: "Step three sets `hazmat_fee_cents` to zero when the waiver
    applies and otherwise to the forecast hazmat surcharge described below."

    Design: Corner/calculations/hazmat_fee_is_waived_when_subtotal_reaches_the_threshold_exactly
    """
    from test_helpers import create_warehouse, read_account
    warehouse = create_warehouse(code="TX-DAL", state_code="TX", hazmat_endorsement=True,
                                 storm_reserve_pct=0.0, dock_capacity_kg_per_window=100000.0)
    account = create_account(name="Delta Fleet", account_tier="STANDARD", state_code="TX",
                             credit_limit_cents=100000000, storm_priority_rank=5)
    model = create_battery_model("IB-31-FLD", sku="IB-BANK-50K", nominal_voltage=48,
                                 amp_hour_capacity=1000, list_price_cents=5000000)
    order = create_order(account["id"], warehouse["id"], requested_ship_date="2026-08-10")
    add_line(order["id"], model["id"], 1, core_expected_count=0)

    submitted = submit_order(order["id"])
    assert submitted["subtotal_cents"] == 5000000
    assert submitted["hazmat_fee_waived"] is True, \
        "A subtotal of exactly 5000000 cents reaches the threshold"
    assert submitted["hazmat_fee_cents"] == 0
    assert submitted["total_cents"] == 5002200
    assert read_account(account["id"])["open_receivable_cents"] == 5002200
