"""Settlement issuance math: dual rate-basis variants, per-bushel tiering,
pinned evaluation order with floor, and the fuel-surcharge boundary."""
from test_helpers import (
    assert_settlement,
    create_active_season,
    create_draft_settlement,
    harvest_contract,
    issue_settlement_and_get,
    open_settlement_window,
    setup_settling_season_with_draft_settlement,
)


def _issue(ctx):
    settlement = create_draft_settlement(ctx["contract"]["id"])
    return issue_settlement_and_get(ctx["contract"]["id"], settlement["id"])


def test_per_acre_vs_per_bushel_base_amounts(api):
    """PRD section 3.8: "If the contract's `rate_basis` is `PER_ACRE`, the
    base is A multiplied by the contract's `rate_cents_per_acre`, rounded
    half-up to whole cents; bushels are ignored. If `rate_basis` is
    `PER_BUSHEL`, tiered pricing applies to NB: when NB is at most 10,000
    bushels, the base is NB multiplied by `rate_cents_per_bushel`, rounded
    half-up to whole cents".

    Design: Difficulty/dual_variant_calc/settlement_per_acre_vs_per_bushel_produce_different_amounts
    """
    ctx = create_active_season()
    season_id = ctx["season"]["id"]
    machine_id = ctx["machine"]["id"]

    ctx_a = harvest_contract(
        season_id, machine_id, sequence_index=1, actual_acres=100,
        tickets=[{"gross_bushels": 4000, "moisture_pct": 14.0, "used_our_trucks": False}],
        contract_overrides={"grower_name": "A", "rate_basis": "PER_ACRE",
                            "rate_cents_per_acre": 3200, "rate_cents_per_bushel": 0,
                            "committed_acres": 200},
    )
    ctx_b = harvest_contract(
        season_id, machine_id, sequence_index=2, actual_acres=100,
        tickets=[{"gross_bushels": 4000, "moisture_pct": 14.0, "used_our_trucks": False,
                  "delivered_at": "2026-08-11T12:00:00Z"}],
        contract_overrides={"grower_name": "B", "rate_basis": "PER_BUSHEL",
                            "rate_cents_per_acre": 0, "rate_cents_per_bushel": 25,
                            "committed_acres": 200},
        stop_overrides={"planned_start_date": "2026-08-10", "planned_end_date": "2026-08-12"},
        assignment_overrides={"assigned_start_date": "2026-08-10", "assigned_end_date": "2026-08-13"},
    )
    open_settlement_window(season_id)

    issued_a = _issue(ctx_a)
    issued_b = _issue(ctx_b)
    assert_settlement(issued_a)
    assert_settlement(issued_b)
    # A: 100 acres * 3200 cents; B: NB 4000 * 25 cents.
    assert issued_a["base_amount_cents"] == 320000, (
        f"PER_ACRE base must be 320000, got {issued_a['base_amount_cents']!r}"
    )
    assert issued_b["base_amount_cents"] == 100000, (
        f"PER_BUSHEL base must be 100000, got {issued_b['base_amount_cents']!r}"
    )
    assert issued_a["base_amount_cents"] != issued_b["base_amount_cents"], (
        "identical acres and bushels under different rate bases must price differently"
    )


def test_dual_variant_totals_equal_base_when_no_adjustments(api):
    """PRD section 3.8: "The base plus the fuel surcharge plus the hauling
    total minus the moisture discount, floored at zero".
    PRD section 3.8: "If the delta is strictly less than 0.10, the surcharge
    is zero."

    Design: Difficulty/dual_variant_calc/settlement_per_acre_vs_per_bushel_produce_different_amounts
    """
    ctx = create_active_season()
    season_id = ctx["season"]["id"]
    machine_id = ctx["machine"]["id"]

    ctx_a = harvest_contract(
        season_id, machine_id, sequence_index=1, actual_acres=100,
        tickets=[{"gross_bushels": 4000, "moisture_pct": 14.0, "used_our_trucks": False}],
        contract_overrides={"grower_name": "A", "rate_basis": "PER_ACRE",
                            "rate_cents_per_acre": 3200, "rate_cents_per_bushel": 0,
                            "committed_acres": 200},
    )
    ctx_b = harvest_contract(
        season_id, machine_id, sequence_index=2, actual_acres=100,
        tickets=[{"gross_bushels": 4000, "moisture_pct": 14.0, "used_our_trucks": False,
                  "delivered_at": "2026-08-11T12:00:00Z"}],
        contract_overrides={"grower_name": "B", "rate_basis": "PER_BUSHEL",
                            "rate_cents_per_acre": 0, "rate_cents_per_bushel": 25,
                            "committed_acres": 200},
        stop_overrides={"planned_start_date": "2026-08-10", "planned_end_date": "2026-08-12"},
        assignment_overrides={"assigned_start_date": "2026-08-10", "assigned_end_date": "2026-08-13"},
    )
    open_settlement_window(season_id)

    issued_a = _issue(ctx_a)
    issued_b = _issue(ctx_b)
    # Diesel 300 -> 300: no surcharge; dry grain and grower-hauled: no
    # hauling, no moisture discount. The total equals the frozen base.
    for issued, expected in ((issued_a, 320000), (issued_b, 100000)):
        assert issued["fuel_surcharge_cents"] == 0
        assert issued["hauling_add_on_total_cents"] == 0
        assert issued["moisture_discount_cents"] == 0
        assert issued["total_amount_cents"] == expected, (
            f"total must equal base when no adjustments apply, got {issued['total_amount_cents']!r}"
        )


def test_moisture_shrink_per_bushel_variant(api):
    """PRD section 3.7: "the shrink factor is then one minus the product of
    the excess tenths and 0.001".
    PRD section 3.8: "This discount applies only when `rate_basis` is
    `PER_ACRE`; under `PER_BUSHEL` the shrink is already reflected in net
    bushels, so a second discount would double-count and the value is zero."

    Design: Difficulty/dual_variant_calc/moisture_shrink_per_bushel_vs_flat_discount_per_acre
    """
    ctx = setup_settling_season_with_draft_settlement(
        contract_overrides={"rate_basis": "PER_BUSHEL", "rate_cents_per_acre": 0,
                            "rate_cents_per_bushel": 25},
        actual_acres=50,
        stop_overrides={"planned_acres": 50},
        tickets=[{"delivered_at": "2026-08-05T12:00:00Z", "gross_bushels": 1000,
                  "moisture_pct": 17.0, "used_our_trucks": False}],
    )
    ticket = ctx["tickets"][0]
    # 17.0 -> 20 excess tenths -> factor 0.98 -> 1000 * 0.98 = 980.0
    assert ticket["net_bushels"] == 980.0 or abs(ticket["net_bushels"] - 980.0) < 0.05, (
        f"ticket net_bushels must be 980.0, got {ticket['net_bushels']!r}"
    )

    issued = issue_settlement_and_get(ctx["contract"]["id"], ctx["settlement"]["id"])
    # NB = 980.0 -> base = round_half_up(980 * 25) = 24500
    assert issued["base_amount_cents"] == 24500, (
        f"PER_BUSHEL base over shrunk NB must be 24500, got {issued['base_amount_cents']!r}"
    )
    assert issued["moisture_discount_cents"] == 0, (
        f"PER_BUSHEL must not double-count moisture, got {issued['moisture_discount_cents']!r}"
    )


def test_flat_moisture_discount_per_acre_variant(api):
    """PRD section 3.8: "For a per-acre contract, the system examines every
    ticket whose `moisture_pct` exceeds 15.0, counts each such ticket's
    excess tenths exactly as in the shrink calculation (the difference from
    15.0, multiplied by ten, rounded half-up to a whole number), and charges
    200 cents per excess tenth per affected ticket".

    Design: Difficulty/dual_variant_calc/moisture_shrink_per_bushel_vs_flat_discount_per_acre
    """
    ctx = setup_settling_season_with_draft_settlement(
        contract_overrides={"rate_basis": "PER_ACRE", "rate_cents_per_acre": 3200,
                            "rate_cents_per_bushel": 0},
        actual_acres=50,
        stop_overrides={"planned_acres": 50},
        tickets=[{"delivered_at": "2026-08-10T12:00:00Z", "gross_bushels": 1000,
                  "moisture_pct": 17.0, "used_our_trucks": False}],
    )
    issued = issue_settlement_and_get(ctx["contract"]["id"], ctx["settlement"]["id"])
    # 50 acres * 3200 = 160000; one wet ticket: 20 tenths * 200 = 4000.
    assert issued["base_amount_cents"] == 160000, (
        f"PER_ACRE base must be 160000, got {issued['base_amount_cents']!r}"
    )
    assert issued["moisture_discount_cents"] == 4000, (
        f"moisture discount must be 4000, got {issued['moisture_discount_cents']!r}"
    )


def test_settlement_total_pinned_eval_order(api):
    """PRD section 3.8: "Issuance computes and permanently freezes five
    amounts, in a pinned evaluation order — base first, then fuel surcharge,
    then hauling, then moisture discount".
    PRD section 3.8: "The base plus the fuel surcharge plus the hauling total
    minus the moisture discount, floored at zero — the total never goes
    negative. Hauling is added before the moisture discount is subtracted so
    the discount cannot erode the hauling recovery."

    Design: Difficulty/combinatorial_formula/settlement_total_pinned_eval_order_base_fuel_hauling_minus_moisture
    """
    ctx = setup_settling_season_with_draft_settlement(
        season_overrides={"diesel_baseline_per_gallon_cents": 300,
                          "current_diesel_per_gallon_cents": 360},
        contract_overrides={"rate_basis": "PER_ACRE", "rate_cents_per_acre": 3200,
                            "rate_cents_per_bushel": 0},
        actual_acres=100,
        tickets=[{"delivered_at": "2026-08-06T12:00:00Z", "gross_bushels": 1000,
                  "moisture_pct": 17.0, "used_our_trucks": True}],
    )
    issued = issue_settlement_and_get(ctx["contract"]["id"], ctx["settlement"]["id"])
    assert_settlement(issued)
    # base 100 * 3200 = 320000; delta 0.20 >= 0.10 -> fuel 320000*0.2*0.5 = 32000;
    # hauling 1000 * 12 = 12000; moisture 20 tenths * 200 = 4000.
    assert issued["base_amount_cents"] == 320000
    assert issued["fuel_surcharge_cents"] == 32000, (
        f"fuel surcharge must be 32000, got {issued['fuel_surcharge_cents']!r}"
    )
    assert issued["hauling_add_on_total_cents"] == 12000, (
        f"hauling total must be 12000, got {issued['hauling_add_on_total_cents']!r}"
    )
    assert issued["moisture_discount_cents"] == 4000
    # Pinned order: 320000 + 32000 + 12000 - 4000 = 360000.
    assert issued["total_amount_cents"] == 360000, (
        f"total must be 360000, got {issued['total_amount_cents']!r}"
    )


def test_settlement_total_floored_at_zero(api):
    """PRD section 3.8: "The base plus the fuel surcharge plus the hauling
    total minus the moisture discount, floored at zero — the total never goes
    negative."

    Design: Difficulty/combinatorial_formula/settlement_total_pinned_eval_order_base_fuel_hauling_minus_moisture
    """
    ctx = setup_settling_season_with_draft_settlement(
        contract_overrides={"rate_basis": "PER_ACRE", "rate_cents_per_acre": 100,
                            "rate_cents_per_bushel": 0, "committed_acres": 1},
        actual_acres=1,
        stop_overrides={"planned_acres": 1},
        tickets=[{"delivered_at": "2026-08-06T12:00:00Z", "gross_bushels": 100,
                  "moisture_pct": 20.0, "used_our_trucks": False}],
    )
    issued = issue_settlement_and_get(ctx["contract"]["id"], ctx["settlement"]["id"])
    # base = 1 * 100 = 100; moisture 20.0 -> 50 tenths -> discount 10000.
    assert issued["base_amount_cents"] == 100
    assert issued["moisture_discount_cents"] == 10000
    assert issued["total_amount_cents"] == 0, (
        f"total must floor at 0, got {issued['total_amount_cents']!r}"
    )


def test_per_bushel_tier_straddling_blended_rate(api):
    """PRD section 3.8: "when NB exceeds 10,000, the first 10,000 bushels are
    priced at `rate_cents_per_bushel` and the remainder at
    `rate_cents_per_bushel` multiplied by 0.9 — a ten percent volume discount
    — with the sum of the two tiers rounded half-up to whole cents."

    Design: Difficulty/combinatorial_formula/per_bushel_tier_straddling_produces_blended_rate
    """
    ctx = setup_settling_season_with_draft_settlement(
        contract_overrides={"rate_basis": "PER_BUSHEL", "rate_cents_per_acre": 0,
                            "rate_cents_per_bushel": 25, "committed_acres": 200},
        actual_acres=200,
        stop_overrides={"planned_acres": 200},
        tickets=[
            {"delivered_at": "2026-08-06T10:00:00Z", "gross_bushels": 6000,
             "moisture_pct": 14.0, "used_our_trucks": False},
            {"delivered_at": "2026-08-06T15:00:00Z", "gross_bushels": 5000,
             "moisture_pct": 14.0, "used_our_trucks": False},
        ],
    )
    issued = issue_settlement_and_get(ctx["contract"]["id"], ctx["settlement"]["id"])
    # NB = 11000 -> 10000 * 25 + 1000 * 25 * 0.9 = 250000 + 22500 = 272500.
    assert issued["base_amount_cents"] == 272500, (
        f"tier-straddling base must be 272500, got {issued['base_amount_cents']!r}"
    )
    assert issued["fuel_surcharge_cents"] == 0


def test_per_bushel_at_tier_boundary_no_discount(api):
    """PRD section 3.8: "when NB is at most 10,000 bushels, the base is NB
    multiplied by `rate_cents_per_bushel`, rounded half-up to whole cents".

    Design: Difficulty/combinatorial_formula/per_bushel_tier_straddling_produces_blended_rate
    """
    ctx = setup_settling_season_with_draft_settlement(
        contract_overrides={"rate_basis": "PER_BUSHEL", "rate_cents_per_acre": 0,
                            "rate_cents_per_bushel": 25, "committed_acres": 200},
        actual_acres=200,
        stop_overrides={"planned_acres": 200},
        tickets=[{"delivered_at": "2026-08-06T10:00:00Z", "gross_bushels": 10000,
                  "moisture_pct": 14.0, "used_our_trucks": False}],
    )
    issued = issue_settlement_and_get(ctx["contract"]["id"], ctx["settlement"]["id"])
    # NB = 10000 exactly -> all of it at full rate: 250000.
    assert issued["base_amount_cents"] == 250000, (
        f"NB at the tier boundary must price entirely at full rate, got {issued['base_amount_cents']!r}"
    )


def test_fuel_surcharge_at_exactly_10_percent_triggers(api):
    """PRD section 3.8: "If the delta is greater than or equal to 0.10 — note
    the boundary is inclusive, so a delta of exactly 0.10 triggers the
    surcharge — the surcharge is `base_amount_cents` multiplied by the delta
    and then multiplied by 0.5 (half of the increase is passed through to the
    grower), rounded half-up to whole cents."

    Design: Difficulty/boundary_precision_check/fuel_surcharge_delta_pct_at_exactly_10_percent_triggers
    """
    ctx = setup_settling_season_with_draft_settlement(
        season_overrides={"diesel_baseline_per_gallon_cents": 300,
                          "current_diesel_per_gallon_cents": 330},
        contract_overrides={"rate_basis": "PER_ACRE", "rate_cents_per_acre": 3200,
                            "rate_cents_per_bushel": 0},
        actual_acres=100,
    )
    issued = issue_settlement_and_get(ctx["contract"]["id"], ctx["settlement"]["id"])
    # delta = 30/300 = 0.10 exactly -> round_half_up(320000 * 0.10 * 0.5) = 16000.
    assert issued["base_amount_cents"] == 320000
    assert issued["fuel_surcharge_cents"] == 16000, (
        f"delta of exactly 0.10 must trigger the surcharge, got {issued['fuel_surcharge_cents']!r}"
    )


def test_fuel_surcharge_below_10_percent_zero(api):
    """PRD section 3.8: "If the delta is strictly less than 0.10, the
    surcharge is zero."

    Design: Difficulty/boundary_precision_check/fuel_surcharge_delta_pct_at_exactly_10_percent_triggers
    """
    ctx = setup_settling_season_with_draft_settlement(
        season_overrides={"season_year": 2027,
                          "diesel_baseline_per_gallon_cents": 300,
                          "current_diesel_per_gallon_cents": 329},
        contract_overrides={"rate_basis": "PER_ACRE", "rate_cents_per_acre": 3200,
                            "rate_cents_per_bushel": 0},
        actual_acres=100,
    )
    issued = issue_settlement_and_get(ctx["contract"]["id"], ctx["settlement"]["id"])
    # delta = 29/300 < 0.10 -> no surcharge.
    assert issued["base_amount_cents"] == 320000
    assert issued["fuel_surcharge_cents"] == 0, (
        f"delta below 0.10 must yield no surcharge, got {issued['fuel_surcharge_cents']!r}"
    )
