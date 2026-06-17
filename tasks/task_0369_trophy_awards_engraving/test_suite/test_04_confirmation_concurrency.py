"""Confirmation: OCC version guard, component reservation gates, promo gates, proof gate (A + B)."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    make_customer_headers,
    make_staff_headers,
    fixtures,
    factories,
)

STAFF = make_staff_headers()


# ─── dual_variant_calc: two component gates diverge (available vs physical) ───
def test_component_available_vs_physical_two_gates_diverge(api):
    """PRD §3.5: "Finally, for every line, each component named in the product's `bom` must
    have an `available_qty` at least equal to the quantity the line would reserve, or
    confirmation is rejected with `ERR_COMPONENT_SHORTAGE`."

    Design: Difficulty/dual_variant_calc/component_available_vs_physical_two_gates_diverge
    """
    fixtures.set_clock()
    fixtures.create_active_rush_policy()
    component = fixtures.create_component(on_hand_qty=5, reorder_point=0)
    product = fixtures.create_product(
        component["id"], sku="ASA-2", base_price_cents=1000,
        engraving_price_per_char_cents=0, standard_lead_days=3,
    )
    customer = fixtures.register_customer()
    cust = make_customer_headers(customer["id"])
    # Order A: qty=5 confirmed -> reserves all 5 (available_qty -> 0).
    order_a = fixtures.create_order(customer)
    line_a = fixtures.add_line(order_a, customer, product["id"], quantity=5)
    fixtures.add_approved_proof(line_a, customer, content_ref="X")
    priced_a = fixtures.price(order_a, customer)
    validate_success(
        api.confirm_order(order_a["id"], {"expected_order_version": priced_a["version"]}, cust)
    )
    # Order B: qty=1; confirm must fail because available_qty==0 despite on_hand still 5.
    order_b = fixtures.create_order(customer)
    line_b = fixtures.add_line(order_b, customer, product["id"], quantity=1)
    fixtures.add_approved_proof(line_b, customer, content_ref="Y")
    priced_b = fixtures.price(order_b, customer)
    resp = api.confirm_order(order_b["id"], {"expected_order_version": priced_b["version"]}, cust)
    validate_error(resp, ApiErrorId.ERR_COMPONENT_SHORTAGE.value)
    comp = validate_success(api.get_component(component["id"], STAFF))
    assert comp["on_hand_qty"] == 5
    assert comp["available_qty"] == 0
    order_b_reread = validate_success(api.get_order(order_b["id"], cust))
    assert order_b_reread["production_status"] == "PRICED"


def test_first_confirm_reserves_full_available_qty(api):
    """PRD §3.5: "Confirmation also creates the material reservations: one
    `ComponentAllocation` in `alloc_status` `RESERVED` is created for each (line,
    bom-component) pair, with its `qty` equal to the component's `qty_per_unit` multiplied by
    the line's `quantity`, and its `order_line_id` and `component_id` set accordingly. Each
    affected component's `allocated_qty`, `available_qty`, and `low_stock` are recomputed."

    Design: Difficulty/dual_variant_calc/component_available_vs_physical_two_gates_diverge
    """
    fixtures.set_clock()
    fixtures.create_active_rush_policy()
    component = fixtures.create_component(on_hand_qty=5, reorder_point=0)
    product = fixtures.create_product(
        component["id"], sku="ASA-2B", base_price_cents=1000,
        engraving_price_per_char_cents=0, standard_lead_days=3,
    )
    customer = fixtures.register_customer()
    cust = make_customer_headers(customer["id"])
    order_a = fixtures.create_order(customer)
    line_a = fixtures.add_line(order_a, customer, product["id"], quantity=5)
    fixtures.add_approved_proof(line_a, customer, content_ref="X")
    priced_a = fixtures.price(order_a, customer)
    validate_success(
        api.confirm_order(order_a["id"], {"expected_order_version": priced_a["version"]}, cust)
    )
    comp = validate_success(api.get_component(component["id"], STAFF))
    # available passes for the first confirm: on_hand 5, reserved 5, available 0, on_hand intact.
    assert comp["allocated_qty"] == 5
    assert comp["available_qty"] == 0
    assert comp["on_hand_qty"] == 5


# ─── resource_temporal_overlap: aggregate capacity overbook ───
def test_component_aggregate_capacity_overlap_rejects_overbook(api):
    """PRD §2.9: "Its `available_qty` is `on_hand_qty` minus `allocated_qty`, and this
    figure must never fall below zero — the workflow rules in Section 3 are designed so that
    reservations and consumptions can never drive it negative."
    PRD §3.5: "Finally, for every line, each component named in the product's `bom` must
    have an `available_qty` at least equal to the quantity the line would reserve, or
    confirmation is rejected with `ERR_COMPONENT_SHORTAGE`."

    Design: Difficulty/resource_temporal_overlap/component_aggregate_capacity_overlap_rejects_overbook
    """
    fixtures.set_clock()
    fixtures.create_active_rush_policy()
    component = fixtures.create_component(on_hand_qty=3, reorder_point=0)
    product = fixtures.create_product(
        component["id"], sku="ASA-15", base_price_cents=1000,
        engraving_price_per_char_cents=0, standard_lead_days=3,
    )
    customer = fixtures.register_customer()
    cust = make_customer_headers(customer["id"])
    order_a = fixtures.create_order(customer)
    line_a = fixtures.add_line(order_a, customer, product["id"], quantity=2)
    fixtures.add_approved_proof(line_a, customer, content_ref="A")
    priced_a = fixtures.price(order_a, customer)
    validate_success(
        api.confirm_order(order_a["id"], {"expected_order_version": priced_a["version"]}, cust)
    )
    order_b = fixtures.create_order(customer)
    line_b = fixtures.add_line(order_b, customer, product["id"], quantity=2)
    fixtures.add_approved_proof(line_b, customer, content_ref="B")
    priced_b = fixtures.price(order_b, customer)
    resp = api.confirm_order(order_b["id"], {"expected_order_version": priced_b["version"]}, cust)
    validate_error(resp, ApiErrorId.ERR_COMPONENT_SHORTAGE.value)
    comp = validate_success(api.get_component(component["id"], STAFF))
    assert comp["allocated_qty"] == 2
    assert comp["available_qty"] == 1


def test_first_confirm_occupies_pool_leaving_one_available(api):
    """PRD §2.9: "Each `Component` tracks `on_hand_qty`, the physical units actually in the
    building, and a derived `allocated_qty`, the sum of `qty` across all of that component's
    allocations currently in `RESERVED` status. Its `available_qty` is `on_hand_qty` minus
    `allocated_qty`, and this figure must never fall below zero".

    Design: Difficulty/resource_temporal_overlap/component_aggregate_capacity_overlap_rejects_overbook
    """
    fixtures.set_clock()
    fixtures.create_active_rush_policy()
    component = fixtures.create_component(on_hand_qty=3, reorder_point=0)
    product = fixtures.create_product(
        component["id"], sku="ASA-15B", base_price_cents=1000,
        engraving_price_per_char_cents=0, standard_lead_days=3,
    )
    customer = fixtures.register_customer()
    cust = make_customer_headers(customer["id"])
    order_a = fixtures.create_order(customer)
    line_a = fixtures.add_line(order_a, customer, product["id"], quantity=2)
    fixtures.add_approved_proof(line_a, customer, content_ref="A")
    priced_a = fixtures.price(order_a, customer)
    validate_success(
        api.confirm_order(order_a["id"], {"expected_order_version": priced_a["version"]}, cust)
    )
    comp = validate_success(api.get_component(component["id"], STAFF))
    # One confirm occupies 2 of the 3-unit pool; available is the remaining capacity.
    assert comp["allocated_qty"] == 2
    assert comp["available_qty"] == 1


# ─── resource_temporal_overlap: due-date buffer window ───
def test_due_date_buffer_window_rejects_infeasible(api):
    """PRD §3.4: "The system computes the number of business days from the current date to
    the `due_date`, counting only weekdays and excluding the current day itself. If that
    count is below the active policy's `rush_min_business_days`, the due date is infeasible
    and pricing is rejected with `ERR_DUE_DATE_INFEASIBLE`."

    Design: Difficulty/resource_temporal_overlap/due_date_buffer_window_rejects_infeasible
    """
    fixtures.set_clock()
    fixtures.create_active_rush_policy(name="tight", rush_min_business_days=2)
    component = fixtures.create_component(on_hand_qty=10)
    product = fixtures.create_product(
        component["id"], sku="ASA-16", product_type="MEDAL", base_price_cents=500,
        engraving_price_per_char_cents=0, standard_lead_days=2,
    )
    customer = fixtures.register_customer()
    order = fixtures.create_order(customer, service_level="RUSH",
                                  due_date="2026-06-16T00:00:00Z")
    fixtures.add_line(order, customer, product["id"], quantity=1)
    resp = api.price_order(order["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_DUE_DATE_INFEASIBLE.value)
    cust = make_customer_headers(customer["id"])
    reread = validate_success(api.get_order(order["id"], cust))
    assert reread["production_status"] == "DRAFT"


def test_due_date_feasible_at_min_business_days_prices(api):
    """PRD §3.4: "If that count is below the active policy's `rush_min_business_days`, the
    due date is infeasible and pricing is rejected with `ERR_DUE_DATE_INFEASIBLE`."

    Design: Difficulty/resource_temporal_overlap/due_date_buffer_window_rejects_infeasible
    """
    fixtures.set_clock()
    fixtures.create_active_rush_policy(name="tight", rush_min_business_days=2)
    component = fixtures.create_component(on_hand_qty=10)
    product = fixtures.create_product(
        component["id"], sku="ASA-16B", product_type="MEDAL", base_price_cents=500,
        engraving_price_per_char_cents=0, standard_lead_days=2,
    )
    customer = fixtures.register_customer()
    # Due 2026-06-17 (Wed) -> business_days=2 == rush_min_business_days, so feasible.
    order = fixtures.create_order(customer, service_level="RUSH",
                                  due_date="2026-06-17T00:00:00Z")
    fixtures.add_line(order, customer, product["id"], quantity=1)
    priced = fixtures.price(order, customer)
    assert priced["production_status"] == "PRICED"


# ─── cross_entity_state_dependency: confirm reads child proof state across all lines ───
def test_confirm_blocked_when_a_line_proof_not_approved(api):
    """PRD §3.5: "Every line on the order must have at least one proof in `proof_status`
    `APPROVED`; a line lacking an approved proof causes `ERR_PROOF_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/confirm_blocked_when_a_line_proof_not_approved
    """
    fixtures.set_clock()
    fixtures.create_active_rush_policy()
    component = fixtures.create_component(on_hand_qty=20)
    product = fixtures.create_product(
        component["id"], sku="ASA-13", base_price_cents=4000,
        engraving_price_per_char_cents=0, standard_lead_days=3,
    )
    customer = fixtures.register_customer()
    cust = make_customer_headers(customer["id"])
    order = fixtures.create_order(customer)
    l1 = fixtures.add_line(order, customer, product["id"], quantity=1)
    l2 = fixtures.add_line(order, customer, product["id"], quantity=1)
    fixtures.add_approved_proof(l1, customer, content_ref="A")
    # L2's proof is only SENT, never approved.
    p2 = fixtures.add_sent_proof(l2, content_ref="B")
    priced = fixtures.price(order, customer)
    resp = api.confirm_order(order["id"], {"expected_order_version": priced["version"]}, cust)
    validate_error(resp, ApiErrorId.ERR_PROOF_NOT_APPROVED.value)
    reread = validate_success(api.get_order(order["id"], cust))
    assert reread["production_status"] == "PRICED"
    p2_reread = validate_success(api.get_proof(p2["id"], cust))
    assert p2_reread["proof_status"] == "SENT"


def test_confirm_succeeds_once_all_lines_have_approved_proof(api):
    """PRD §3.5: "Every line on the order must have at least one proof in `proof_status`
    `APPROVED`; a line lacking an approved proof causes `ERR_PROOF_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/confirm_blocked_when_a_line_proof_not_approved
    """
    fixtures.set_clock()
    fixtures.create_active_rush_policy()
    component = fixtures.create_component(on_hand_qty=20)
    product = fixtures.create_product(
        component["id"], sku="ASA-13B", base_price_cents=4000,
        engraving_price_per_char_cents=0, standard_lead_days=3,
    )
    customer = fixtures.register_customer()
    cust = make_customer_headers(customer["id"])
    order = fixtures.create_order(customer)
    l1 = fixtures.add_line(order, customer, product["id"], quantity=1)
    l2 = fixtures.add_line(order, customer, product["id"], quantity=1)
    fixtures.add_approved_proof(l1, customer, content_ref="A")
    p2 = fixtures.add_sent_proof(l2, content_ref="B")
    priced = fixtures.price(order, customer)
    # First confirm blocked: L2 proof still SENT.
    blocked = api.confirm_order(order["id"], {"expected_order_version": priced["version"]}, cust)
    validate_error(blocked, ApiErrorId.ERR_PROOF_NOT_APPROVED.value)
    # Approve L2's proof; now confirm reads all child proofs as APPROVED and succeeds.
    validate_success(api.approve_proof(l2["id"], p2["id"], cust))
    reread = validate_success(api.get_order(order["id"], cust))
    confirmed = validate_success(
        api.confirm_order(order["id"], {"expected_order_version": reread["version"]}, cust)
    )
    assert confirmed["production_status"] == "CONFIRMED"


# ─── OCC: correct version succeeds and increments ───
def test_occ_confirm_correct_version_succeeds_then_increments(api):
    """PRD §2.8: "The confirmation request must carry `expected_order_version` equal to the
    target order's current `version`; if another writer has advanced that order's `version`
    since the caller last read it — by re-pricing it, editing it, or confirming it first —
    the confirmation is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.5: "The order's `version` increments."

    Design: Corner/cross_cutting_complexity_layers/occ_confirm_correct_version_succeeds_then_increments
    """
    ctx = fixtures.setup_priced_order(
        product_overrides={"base_price_cents": 4000, "standard_lead_days": 3}, on_hand_qty=10
    )
    order, cust_obj = ctx["order"], ctx["customer"]
    cust = make_customer_headers(cust_obj["id"])
    confirmed = validate_success(
        api.confirm_order(order["id"], {"expected_order_version": order["version"]}, cust)
    )
    assert confirmed["production_status"] == "CONFIRMED"
    assert confirmed["version"] == order["version"] + 1


def test_occ_confirm_stale_version_returns_stale_version(api):
    """PRD §2.8: "The confirmation request must carry `expected_order_version` equal to the
    target order's current `version`; if another writer has advanced that order's `version`
    since the caller last read it — by re-pricing it, editing it, or confirming it first —
    the confirmation is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_confirm_stale_version_returns_stale_version
    """
    ctx = fixtures.setup_priced_order(
        product_overrides={"base_price_cents": 4000, "standard_lead_days": 3}, on_hand_qty=10
    )
    order, cust_obj = ctx["order"], ctx["customer"]
    cust = make_customer_headers(cust_obj["id"])
    resp = api.confirm_order(order["id"], {"expected_order_version": order["version"] - 1}, cust)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    reread = validate_success(api.get_order(order["id"], cust))
    assert reread["production_status"] == "PRICED"


# ─── Promo gates at confirm ───
def test_promo_min_subtotal_not_met_on_confirm(api):
    """PRD §3.5: "the order's subtotal must also meet the promo's `min_subtotal_cents`, or it
    is rejected with `ERR_PROMO_MIN_NOT_MET`."

    Design: Corner/validations/promo_min_subtotal_not_met_on_confirm
    """
    fixtures.set_clock()
    fixtures.create_active_rush_policy()
    promo = fixtures.create_promo(code="BIG10", kind="PERCENT", percent_off=0.10,
                                  min_subtotal_cents=100000)
    component = fixtures.create_component(on_hand_qty=10)
    product = fixtures.create_product(
        component["id"], sku="EP-25", base_price_cents=4000,
        engraving_price_per_char_cents=0, standard_lead_days=5,
    )
    customer = fixtures.register_customer()
    cust = make_customer_headers(customer["id"])
    order = fixtures.create_order(customer, promo_code_id=promo["id"])
    line = fixtures.add_line(order, customer, product["id"], quantity=1)
    fixtures.add_approved_proof(line, customer, content_ref="X")
    priced = fixtures.price(order, customer)
    resp = api.confirm_order(order["id"], {"expected_order_version": priced["version"]}, cust)
    validate_error(resp, ApiErrorId.ERR_PROMO_MIN_NOT_MET.value)
    reread = validate_success(api.get_order(order["id"], cust))
    assert reread["production_status"] == "PRICED"


def test_promo_max_uses_exhausted_returns_promo_invalid(api):
    """PRD §3.5: "If a `promo_code_id` is set, the promo must be active and, where
    `max_uses` is not null, its `uses_count` must still be below `max_uses`, or the
    confirmation is rejected with `ERR_PROMO_INVALID`".

    Design: Corner/validations/promo_max_uses_exhausted_returns_promo_invalid
    """
    fixtures.set_clock()
    fixtures.create_active_rush_policy()
    promo = fixtures.create_promo(code="ONCE", kind="FLAT", flat_off_cents=1000,
                                  min_subtotal_cents=5000, max_uses=1)
    component = fixtures.create_component(on_hand_qty=20)
    product = fixtures.create_product(
        component["id"], sku="EP-28", base_price_cents=6000,
        engraving_price_per_char_cents=0, standard_lead_days=5,
    )
    customer = fixtures.register_customer()
    cust = make_customer_headers(customer["id"])
    # Order A redeems the promo (uses_count -> 1).
    order_a = fixtures.create_order(customer, promo_code_id=promo["id"])
    la = fixtures.add_line(order_a, customer, product["id"], quantity=1)
    fixtures.add_approved_proof(la, customer, content_ref="A")
    priced_a = fixtures.price(order_a, customer)
    validate_success(
        api.confirm_order(order_a["id"], {"expected_order_version": priced_a["version"]}, cust)
    )
    # Order B tries the same exhausted promo.
    order_b = fixtures.create_order(customer, promo_code_id=promo["id"])
    lb = fixtures.add_line(order_b, customer, product["id"], quantity=1)
    fixtures.add_approved_proof(lb, customer, content_ref="B")
    priced_b = fixtures.price(order_b, customer)
    resp = api.confirm_order(order_b["id"], {"expected_order_version": priced_b["version"]}, cust)
    validate_error(resp, ApiErrorId.ERR_PROMO_INVALID.value)
    promo_reread = validate_success(api.get_promo_code(promo["id"], cust))
    assert promo_reread["uses_count"] == 1
    order_b_reread = validate_success(api.get_order(order_b["id"], cust))
    assert order_b_reread["production_status"] == "PRICED"


# ─── State machine: confirm from DRAFT rejected ───
def test_confirm_from_draft_returns_invalid_state(api):
    """PRD §3.5: "A customer confirms a priced order, advancing it `PRICED → CONFIRMED`."
    PRD §3.5: "The order must be in `PRICED`, or the transition is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/confirm_from_draft_returns_invalid_state
    """
    fixtures.set_clock()
    component = fixtures.create_component(on_hand_qty=10)
    product = fixtures.create_product(
        component["id"], sku="EP-9", base_price_cents=4000,
        engraving_price_per_char_cents=0, standard_lead_days=3,
    )
    customer = fixtures.register_customer()
    cust = make_customer_headers(customer["id"])
    order = fixtures.create_order(customer)
    fixtures.add_line(order, customer, product["id"], quantity=1)
    reread = validate_success(api.get_order(order["id"], cust))
    resp = api.confirm_order(order["id"], {"expected_order_version": reread["version"]}, cust)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    final = validate_success(api.get_order(order["id"], cust))
    assert final["production_status"] == "DRAFT"


# ─── Consistency: confirm response is immediately authoritative ───
def test_confirm_changes_visible_in_same_response_immediate(api):
    """PRD §3.5: "When all checks pass, the invoice arithmetic of Section 3.4 runs and locks
    `invoice_subtotal_cents` and `invoice_total_cents`."
    PRD §3.5: "The deposit is then computed: `deposit_due_cents` is the invoice total
    multiplied by one half, rounded up to the next whole cent".

    Design: Corner/consistency_model/confirm_changes_visible_in_same_response_immediate
    """
    ctx = fixtures.setup_priced_order(
        product_overrides={"base_price_cents": 4000, "standard_lead_days": 3}, on_hand_qty=10
    )
    order, cust_obj = ctx["order"], ctx["customer"]
    cust = make_customer_headers(cust_obj["id"])
    confirmed = validate_success(
        api.confirm_order(order["id"], {"expected_order_version": order["version"]}, cust)
    )
    assert confirmed["production_status"] == "CONFIRMED"
    assert confirmed["invoice_total_cents"] == 4000
    assert confirmed["deposit_due_cents"] == 2000
