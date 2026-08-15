"""Custom gas mixture blending: pinned price quote, plant gating, tank
selection, composition validation, and conformance grading (PRD §3.9, §3.4)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_test_blend_order,
    create_test_customer,
    create_test_plant,
    create_test_tank,
    get_blend_order,
    get_tank,
    setup_approved_blend,
    setup_awaiting_analysis_blend,
    validate_error,
    validate_success,
)

PM = TEST_USERS["plant_manager_headers"]
OP = TEST_USERS["production_operator_headers"]
QM = TEST_USERS["quality_manager_headers"]
LAB = TEST_USERS["lab_analyst_headers"]
BC = TEST_USERS["billing_clerk_headers"]


# --- Difficulty: combinatorial_formula / blend_quote_fee_tier_keyed_on_cost_not_total ---

def _create_air_blend():
    customer = create_test_customer(account_name="C-CF3", credit_limit_cents=100000)
    return create_test_blend_order(customer["id"])


def test_blend_service_fee_keyed_on_component_cost(api):
    """PRD §3.9: "Second, `service_fee_cents` is keyed only on that component
    cost, never on the total: a cost below 100000 cents pays a flat 15000 cents;
    a cost from 100000 up to and including 499999 cents pays 12% of the cost
    rounded half-up to whole cents; a cost of 500000 cents or more pays 10% of
    the cost rounded half-up to whole cents."

    Design: Difficulty/combinatorial_formula/blend_quote_fee_tier_keyed_on_cost_not_total
    """
    blend = _create_air_blend()
    assert blend["component_cost_cents"] == 142000, (
        "round(0.21*1000*300) + round(0.79*1000*100) = 63000 + 79000"
    )
    assert blend["service_fee_cents"] == 17040, (
        "round_half_up(0.12 * 142000) = 17040; keying on the 159040 total would "
        "give 19085, which the pinned order forbids"
    )


def test_blend_total_is_cost_plus_fee(api):
    """PRD §3.9: "First, `component_cost_cents` is the sum over components of
    each component's percentage of the batch quantity multiplied by its unit cost
    — that is, `target_pct` divided by 100, times `batch_qty_liters`, times
    `unit_cost_cents_per_liter` — with each component's contribution rounded
    half-up to whole cents before summing."
    PRD §3.9: "Third, `total_price_cents` is the component cost plus the service
    fee."

    Design: Difficulty/combinatorial_formula/blend_quote_fee_tier_keyed_on_cost_not_total
    """
    blend = _create_air_blend()
    assert blend["total_price_cents"] == 159040, "142000 + 17040"
    assert blend["total_price_cents"] == (
        blend["component_cost_cents"] + blend["service_fee_cents"]
    )
    assert blend["status"] == "DRAFT"


# --- Difficulty: cross_entity_state_dependency / blend_start_requires_plant_operating ---

def test_start_blend_rejected_during_plant_shutdown(api):
    """PRD §3.1: "While a plant is in `MAINTENANCE_SHUTDOWN`, all four production
    transitions — starting a fill, completing a fill, starting a blend, and
    completing a blend — are rejected with `ERR_PLANT_NOT_OPERATING`; returning
    the plant to `OPERATING` re-enables them."
    PRD §3.9: "Production then begins with the start-blend action, permitted from
    `APPROVED` or from `REWORK` (else `ERR_BLEND_ORDER_INVALID_STATE`) and only
    while the plant of the selected tanks is `OPERATING` (else
    `ERR_PLANT_NOT_OPERATING`)."

    Design: Difficulty/cross_entity_state_dependency/blend_start_requires_plant_operating
    """
    ctx = setup_approved_blend()
    validate_success(
        api.set_plant_status(ctx["plant"]["id"],
                             {"target_status": "MAINTENANCE_SHUTDOWN"}, PM),
        200,
    )
    res = api.start_blend(ctx["blend"]["id"], OP)
    validate_error(res, ApiErrorId.ERR_PLANT_NOT_OPERATING.value)
    assert get_blend_order(ctx["blend"]["id"])["status"] == "APPROVED"


def test_start_blend_succeeds_after_plant_resume(api):
    """PRD §3.1: "returning the plant to `OPERATING` re-enables them."
    PRD §3.9: "The chosen tank is stamped onto each component as
    `selected_tank_id`, the blend moves to `BLENDING`, and its `version`
    increments."

    Design: Difficulty/cross_entity_state_dependency/blend_start_requires_plant_operating
    """
    ctx = setup_approved_blend()
    validate_success(
        api.set_plant_status(ctx["plant"]["id"],
                             {"target_status": "MAINTENANCE_SHUTDOWN"}, PM),
        200,
    )
    validate_success(
        api.set_plant_status(ctx["plant"]["id"], {"target_status": "OPERATING"}, PM),
        200,
    )
    started = validate_success(api.start_blend(ctx["blend"]["id"], OP), 200)
    assert started["status"] == "BLENDING"
    for component in started["components"]:
        assert component.get("selected_tank_id"), (
            "the server stamps a selected tank per component"
        )


# --- Corner: validations / blend_component_sum_invalid_rejected ---

def test_blend_component_sum_invalid_rejected(api):
    """PRD §3.9: "Composition rules are strict: at least two components are
    required, and the `target_pct` values — each taken at 2 decimal places — must
    sum to exactly 100.00; any breach is rejected with
    `ERR_BLEND_COMPONENT_SUM_INVALID`."

    Design: Corner/validations/blend_component_sum_invalid_rejected
    """
    customer = create_test_customer(account_name="C-VA4", credit_limit_cents=100000)
    res = api.create_blend_order(
        {
            "customer_id": customer["id"],
            "batch_qty_liters": 1000,
            "components": [
                {"product_code": "O2", "target_pct": 20.99, "tolerance_pct": 0.50,
                 "unit_cost_cents_per_liter": 300},
                {"product_code": "N2", "target_pct": 79.00, "tolerance_pct": 0.50,
                 "unit_cost_cents_per_liter": 100},
            ],
        },
        BC,
    )
    validate_error(res, ApiErrorId.ERR_BLEND_COMPONENT_SUM_INVALID.value)


# --- Corner: calculations / blend_conformance_tolerance_equality_passes ---

def test_blend_conformance_tolerance_equality_passes(api):
    """PRD §3.4: "A deviation at or below the component's `tolerance_pct` is OK;
    a deviation above tolerance but at or below twice the tolerance is MARGINAL;
    a deviation above twice the tolerance is FAIL — equality at tolerance is OK,
    and equality at twice the tolerance is MARGINAL."
    PRD §3.9: "For each component, the selected tank's `drawn_liters` increases
    by the component's required quantity, with `current_level_liters` and
    `low_level_flag` recomputed per tank"

    Design: Corner/calculations/blend_conformance_tolerance_equality_passes
    """
    ctx = setup_awaiting_analysis_blend()
    blend = ctx["blend"]
    res = api.create_purity_analysis(
        {"subject_type": "BLEND_ORDER", "blend_order_id": blend["id"],
         "readings": [{"product_code": "O2", "actual_pct": 21.50},
                      {"product_code": "N2", "actual_pct": 78.50}]},
        LAB,
    )
    analysis = validate_success(res, 201)
    assert analysis["result"] == "PASS", (
        "deviation 0.50 == tolerance 0.50 lands inside the OK band"
    )
    assert get_blend_order(blend["id"])["status"] == "RELEASED"

    o2_tank = get_tank(ctx["tanks"]["O2"][0]["id"])
    n2_tank = get_tank(ctx["tanks"]["N2"][0]["id"])
    assert o2_tank["drawn_liters"] == pytest.approx(210.0, abs=0.01)
    assert n2_tank["drawn_liters"] == pytest.approx(790.0, abs=0.01)
    assert o2_tank["current_level_liters"] == pytest.approx(4790.0, abs=0.01)
    assert n2_tank["current_level_liters"] == pytest.approx(4210.0, abs=0.01)


# --- Corner: calculations / blend_tank_selector_picks_highest_level ---

def test_blend_tank_selector_picks_highest_level(api):
    """PRD §3.9: "a tank is eligible when it stores the component's
    `product_code`, is `IN_SERVICE`, and has headroom — `current_level_liters`
    minus `reserved_liters` — of at least the required quantity plus the
    100-liter minimum reserve, where the required quantity is the component's
    percentage of the batch quantity rounded half-up to 2 decimal places.
    Eligible tanks are ranked by `current_level_liters` descending with ties
    broken by earliest `created_at`."

    Design: Corner/calculations/blend_tank_selector_picks_highest_level
    """
    plant = create_test_plant(plant_name="P-CA4")
    create_test_tank(plant["id"], product_code="O2", initial_level_liters=3000)
    high = create_test_tank(plant["id"], product_code="O2", initial_level_liters=5000)
    n2 = create_test_tank(plant["id"], product_code="N2", initial_level_liters=5000)
    customer = create_test_customer(account_name="C-CA4", credit_limit_cents=100000)
    blend = create_test_blend_order(customer["id"])
    validate_success(api.approve_blend_order(blend["id"], QM), 200)

    started = validate_success(api.start_blend(blend["id"], OP), 200)
    assert started["status"] == "BLENDING"
    by_product = {c["product_code"]: c for c in started["components"]}
    assert by_product["O2"]["selected_tank_id"] == high["id"], (
        "5000 > 3000: level descending wins"
    )
    assert by_product["N2"]["selected_tank_id"] == n2["id"]
