"""Validation precedence: state check precedes business-rule checks (queue A)."""
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


def test_state_beats_proof_not_approved_on_confirm(api):
    """PRD §2.7: "Only after all four of those pass does the system evaluate whether the
    target resource is in a valid state for the requested transition (`ERR_INVALID_STATE`),
    and only then are the domain-specific business rules described throughout Section 3
    applied."
    PRD §3.5: "The order must be in `PRICED`, or the transition is rejected with
    `ERR_INVALID_STATE`. Every line on the order must have at least one proof in
    `proof_status` `APPROVED`; a line lacking an approved proof causes
    `ERR_PROOF_NOT_APPROVED`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_proof_not_approved_on_confirm
    """
    fixtures.set_clock()
    component = fixtures.create_component(on_hand_qty=10)
    product = fixtures.create_product(
        component["id"], sku="ASA-9", base_price_cents=4000,
        engraving_price_per_char_cents=0, standard_lead_days=3,
    )
    customer = fixtures.register_customer()
    cust = make_customer_headers(customer["id"])
    order = fixtures.create_order(customer)
    fixtures.add_line(order, customer, product["id"], quantity=1)
    # Price then edit -> the order is back in DRAFT (never has an approved proof).
    fixtures.create_active_rush_policy()
    fixtures.price(order, customer)
    edited = validate_success(api.edit_order(order["id"], {"service_level": "EXPEDITED"}, cust))
    assert edited["production_status"] == "DRAFT"
    resp = api.confirm_order(order["id"], {"expected_order_version": edited["version"]}, cust)
    # Wrong-state (DRAFT, not PRICED) precedes the proof-not-approved business rule.
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    reread = validate_success(api.get_order(order["id"], cust))
    assert reread["production_status"] == "DRAFT"


def test_state_beats_proof_not_approved_confirm_from_draft_direct(api):
    """PRD §2.7: "and a request whose target is in the wrong state but also violates a
    business rule returns `ERR_INVALID_STATE` first."
    PRD §3.5: "The order must be in `PRICED`, or the transition is rejected with
    `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_proof_not_approved_on_confirm
    """
    fixtures.set_clock()
    component = fixtures.create_component(on_hand_qty=10)
    product = fixtures.create_product(
        component["id"], sku="ASA-9B", base_price_cents=4000,
        engraving_price_per_char_cents=0, standard_lead_days=3,
    )
    customer = fixtures.register_customer()
    cust = make_customer_headers(customer["id"])
    order = fixtures.create_order(customer)
    fixtures.add_line(order, customer, product["id"], quantity=1)
    # Order is DRAFT with NO proof at all; confirm should report wrong-state, not proof gap.
    reread = validate_success(api.get_order(order["id"], cust))
    resp = api.confirm_order(order["id"], {"expected_order_version": reread["version"]}, cust)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    final = validate_success(api.get_order(order["id"], cust))
    assert final["production_status"] == "DRAFT"


def test_state_beats_deposit_required_on_start_production(api):
    """PRD §2.7: "and a request whose target is in the wrong state but also violates a
    business rule returns `ERR_INVALID_STATE` first."
    PRD §3.7: "This step requires the order to be in `CONFIRMED` and its `payment_status`
    to be `DEPOSIT_PAID` or `PAID_IN_FULL`; starting production while the order is still
    `UNPAID` is rejected with `ERR_DEPOSIT_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_deposit_required_on_start_production
    """
    # Order is PRICED (not CONFIRMED) and UNPAID; start-production must report wrong-state.
    ctx = fixtures.setup_priced_order(
        product_overrides={"base_price_cents": 4000, "standard_lead_days": 3}, on_hand_qty=10
    )
    order, cust_obj = ctx["order"], ctx["customer"]
    cust = make_customer_headers(cust_obj["id"])
    resp = api.start_production(order["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    reread = validate_success(api.get_order(order["id"], cust))
    assert reread["production_status"] == "PRICED"


def test_state_beats_deposit_required_start_production_from_priced_unpaid(api):
    """PRD §2.7: "Only after all four of those pass does the system evaluate whether the
    target resource is in a valid state for the requested transition (`ERR_INVALID_STATE`),
    and only then are the domain-specific business rules described throughout Section 3
    applied."
    PRD §3.7: "starting production while the order is still `UNPAID` is rejected with
    `ERR_DEPOSIT_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_deposit_required_on_start_production
    """
    ctx = fixtures.setup_priced_order(
        product_overrides={"base_price_cents": 5000, "standard_lead_days": 3}, on_hand_qty=10
    )
    order, cust_obj = ctx["order"], ctx["customer"]
    cust = make_customer_headers(cust_obj["id"])
    # The order is PRICED and UNPAID — both the state gate and the deposit gate would fail;
    # PRD pins ERR_INVALID_STATE as the reported error.
    resp = api.start_production(order["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    reread = validate_success(api.get_order(order["id"], cust))
    assert reread["payment_status"] == "UNPAID"
