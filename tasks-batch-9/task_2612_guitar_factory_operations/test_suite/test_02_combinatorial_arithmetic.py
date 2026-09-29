"""
Three arithmetic mechanisms that only come out right when every step is taken in
the pinned order: per-line rounding on a quote, the four-term cure composition,
and the customs declaration whose fee tier must not be re-derived.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers import test_users as U

DOT = {"option_code": "INL-DOT", "option_group": "INLAY", "upcharge_cents": 12004,
       "complexity_class": "ARTISAN", "lead_time_days": 10,
       "incompatible_option_codes": ["INL-VINE"]}
GOLD = {"option_code": "HW-GOLD", "option_group": "HARDWARE",
        "upcharge_cents": 22004, "complexity_class": "ARTISAN",
        "lead_time_days": 12}
PICKUP = {"option_code": "EL-PICKUP", "option_group": "ELECTRONICS",
          "upcharge_cents": 32004, "complexity_class": "ARTISAN",
          "lead_time_days": 20, "requires_finish_system": "POLY"}


def three_artisan_options_on_a_plain_order(api):
    """
    A plain polyurethane order at 300000 cents with no artist tier, carrying
    three artisan options whose upcharges each land on a fractional cent.
    """
    env = X.build_clock(api)
    env["optC"] = F.create_option(api, dict(DOT))["id"]
    env["optD"] = F.create_option(api, dict(GOLD))["id"]
    env["optE"] = F.create_option(api, dict(PICKUP))["id"]
    order = F.create_order(api, F.order_payload(
        order_code="ORD-002", model_code="D28", base_price_cents=300000,
        is_custom_shop=False, artist_tier="NONE", finish_system="POLY",
        promised_date="2026-11-01T00:00:00Z"), U.COORDINATOR_HEADERS)
    env["bo2"] = order["id"]
    env["selC"] = F.create_selection(api, env["bo2"], env["optC"],
                                     order["version"], quantity=1,
                                     headers=U.COORDINATOR_HEADERS)["id"]
    X.read_order_version(api, env, "bo2", "bo2_v2")
    env["selD"] = F.create_selection(api, env["bo2"], env["optD"], env["bo2_v2"],
                                     quantity=1,
                                     headers=U.COORDINATOR_HEADERS)["id"]
    X.read_order_version(api, env, "bo2", "bo2_v3")
    return env


def test_the_third_option_line_is_rounded_on_its_own_before_the_total_is_summed(api):
    """
    The line for the last option is rounded by itself, and the total is the sum
    of the three already-rounded lines rather than a single rounding of their
    combined raw upcharges.

    PRD: "Rounding each line gives 16205, 29705 and 43205, an options subtotal
    of 89115 and a total of 389115."

    Design: Difficulty/combinatorial_formula/quote_nested_rounding_round_each_line_then_sum
    """
    env = three_artisan_options_on_a_plain_order(api)

    created = validate_success(api.create_option_selection(env["bo2"], {
        "option_id": env["optE"], "quantity": 1,
        "expected_build_order_version": env["bo2_v3"],
    }, U.COORDINATOR_HEADERS), 201)
    assert created["line_total_cents"] == 43205

    order = validate_success(api.get_build_order(env["bo2"], U.COORDINATOR_HEADERS))
    assert order["provisional_quote_total_cents"] == 389115


def test_each_of_the_three_lines_carries_its_own_rounded_amount(api):
    """
    Every included selection persists the amount its own line rounded to, so the
    intermediate rounding is visible on the rows and not merely implied by the
    total.

    PRD: "Summing first would give 66012, then 89116 after the multiplier, and a
    total of 389116 — one cent higher, and wrong."

    Design: Difficulty/combinatorial_formula/quote_nested_rounding_round_each_line_then_sum
    """
    env = three_artisan_options_on_a_plain_order(api)
    selE = F.create_selection(api, env["bo2"], env["optE"], env["bo2_v3"],
                              quantity=1, headers=U.COORDINATOR_HEADERS)["id"]

    lines = {
        validate_success(api.get_option_selection(sid, U.COORDINATOR_HEADERS))
        ["line_total_cents"]
        for sid in (env["selC"], env["selD"], selE)
    }
    assert lines == {16205, 29705, 43205}

    order = validate_success(api.get_build_order(env["bo2"], U.COORDINATOR_HEADERS))
    assert order["provisional_quote_total_cents"] == 389115
    assert order["provisional_quote_total_cents"] != 389116


def test_closing_the_spray_composes_the_cure_from_all_four_dimensions(api, chain_a):
    """
    A twelve-coat nitrocellulose run in a booth reading 52.0 percent and 27.0
    degrees earns a humidity penalty that rounds up and a temperature relief
    that rounds down, and the per-system floor never binds.

    PRD: "A `NITRO` run of twelve coats whose booth reads a `latest_rh_pct` of
    52.0 and a `latest_temp_c` of 27.0, sprayed to completion at
    2026-08-05T09:00:00Z with `cure_suspended_minutes` at zero, has four extra
    coats and 408 coat hours; the humidity excess of 7.0 divided by 5.0 is 1.4,
    which rounds **up** to two steps and 24 penalty hours; the temperature
    excess of 6.0 divided by 2.0 is exactly three steps, giving 24 relief hours
    capped at nothing; `cure_hours` is the larger of 240 and 408, or 408, and
    `cure_ready_at` is 2026-08-22T09:00:00Z."

    Design: Difficulty/combinatorial_formula/cure_hours_composed_from_four_dimensions_with_asymmetric_rounding
    """
    run = validate_success(
        api.complete_spray(chain_a["fr1"], U.FINISH_TECH_HEADERS))
    assert run["status"] == "CURING"
    assert run["spray_completed_at"] == "2026-08-05T09:00:00Z"
    assert run["cure_hours"] == 408
    assert run["cure_ready_at"] == "2026-08-22T09:00:00Z"
    assert run["cure_suspended_minutes"] == 0


def test_the_climate_terms_can_push_the_cure_past_the_projected_booth_hold(api, chain_a):
    """
    The booth hold was projected from the coat schedule alone, so the cure that
    the humidity and temperature terms produce may finish after the hold ends,
    and that divergence is merely informational.

    PRD: "Because the booth hold was projected without the climate terms, a
    humid booth can push the real `cure_ready_at` past `booth_hold_until`."

    Design: Difficulty/combinatorial_formula/cure_hours_composed_from_four_dimensions_with_asymmetric_rounding
    """
    before = validate_success(
        api.get_finish_run(chain_a["fr1"], U.FINISH_TECH_HEADERS))
    assert before["booth_hold_from"] == "2026-08-01T00:00:00Z"
    assert before["booth_hold_until"] == "2026-08-18T04:00:00Z"

    run = validate_success(
        api.complete_spray(chain_a["fr1"], U.FINISH_TECH_HEADERS))
    assert run["cure_ready_at"] == "2026-08-22T09:00:00Z"
    assert run["booth_hold_until"] == "2026-08-18T04:00:00Z"


def locked_order_at_four_hundred_ninety_eight_thousand(api):
    """
    A plain order at 498000 cents with no options, confirmed and locked so its
    binding total is exactly the list price and no protected wood is involved.
    """
    env = X.build_clock(api)
    order = F.create_order(api, F.order_payload(
        order_code="ORD-EXP", model_code="D28", base_price_cents=498000,
        is_custom_shop=False, artist_tier="NONE", finish_system="POLY",
        promised_date="2026-12-01T00:00:00Z"), U.COORDINATOR_HEADERS)
    env["boX"] = order["id"]
    F.confirm_order(api, env["boX"], 50000, U.COORDINATOR_HEADERS)
    F.lock_options(api, env["boX"], U.COORDINATOR_HEADERS)
    return env


def test_the_customs_declaration_prices_the_fee_then_the_insurance_on_fee_plus_goods(api):
    """
    The documentation fee comes from the goods value, and the insurance is
    charged on the goods value plus that fee, never on the insurance itself.

    PRD: "**Step four** sets `insurance_cents` to `goods_value_cents` plus
    `doc_fee_cents`, multiplied by 90 basis points, divided by 10000 and rounded
    half up; the insurance base includes the documentation fee and excludes
    insurance itself."

    Design: Difficulty/combinatorial_formula/export_declared_value_tier_pinned_to_goods_not_declared
    """
    env = locked_order_at_four_hundred_ninety_eight_thousand(api)

    shipment = validate_success(api.create_export_shipment({
        "build_order_id": env["boX"], "destination_country_code": "JP",
    }, U.COMPLIANCE_HEADERS), 201)
    assert shipment["status"] == "DOCS_PENDING"
    assert shipment["goods_value_cents"] == 498000
    assert shipment["doc_fee_cents"] == 7470
    assert shipment["insurance_cents"] == 4549
    assert shipment["declared_value_cents"] == 510019


def test_the_fee_tier_is_never_re_derived_from_the_declared_value_it_inflated(api):
    """
    The goods value sits under the first-tier ceiling while the resulting
    declared value sits above it, and the shipment must keep the first-tier rate
    rather than dropping to the second on its own output.

    PRD: "The forbidden reading would notice that 510019 exceeds 500000, drop to
    the second tier, and produce a fee of 5478, insurance of 4531 and a declared
    value of 508009."

    Design: Difficulty/combinatorial_formula/export_declared_value_tier_pinned_to_goods_not_declared
    """
    env = locked_order_at_four_hundred_ninety_eight_thousand(api)

    shipment = validate_success(api.create_export_shipment({
        "build_order_id": env["boX"], "destination_country_code": "JP",
    }, U.COMPLIANCE_HEADERS), 201)
    assert shipment["declared_value_cents"] == 510019
    assert shipment["declared_value_cents"] != 508009
    assert shipment["doc_fee_cents"] != 5478
    assert shipment["cites_permit_required"] is False
    assert shipment["required_cites_appendix"] == "NONE"
