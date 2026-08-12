"""Entity creation defaults, schema validation, and existence errors (PRD §2.11, §3)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS, make_customer_headers,
    assert_bin, assert_formula, assert_customer,
    create_ingredient_payload, create_bin_payload, create_customer_payload,
    create_formula_payload, create_order_payload,
    make_customer,
)

MM = TEST_USERS["mill_manager_headers"]
NUT = TEST_USERS["nutritionist_headers"]


def test_entity_defaults_applied_on_creation(api):
    """PRD §3.3: "the bin starts `EMPTY` with no `ingredient_id` assigned"
    PRD §3.4: "A new formula starts in `DRAFT` with empty `lines` — nothing has been solved yet."
    PRD §3.5: "A new customer starts `ACTIVE`."
    PRD §2.10: "The live exposure, `credit_used_cents`, is the sum of `quoted_total_cents` over the customer's orders in `CONFIRMED` or `IN_PRODUCTION`, plus the sum of `final_total_cents` over the customer's orders in `COMPLETED`."

    Design: Corner/entities/entity_defaults_applied_on_creation
    """
    bin_data = get_success_data(api.create_bin(create_bin_payload("BIN-1", 50), MM))
    assert_bin(bin_data)
    assert bin_data["status"] == "EMPTY"
    assert bin_data["on_hand_tons"] == 0
    assert bin_data["ingredient_id"] is None
    assert isinstance(bin_data["version"], int) and bin_data["version"] >= 1

    formula = get_success_data(api.create_formula(create_formula_payload("F-1"), NUT))
    assert_formula(formula)
    assert formula["status"] == "DRAFT"
    assert formula["lines"] == []
    # With empty lines every nutrient total is zero, below the stated floors.
    assert formula["meets_constraints"] is False

    customer = get_success_data(api.create_customer(
        create_customer_payload("Acme Farms", 1000000), MM))
    assert_customer(customer)
    assert customer["status"] == "ACTIVE"
    # No orders exist, so every status-filtered exposure sum is empty.
    assert customer["credit_used_cents"] == 0


def test_bin_get_with_unknown_id_returns_404(api):
    """PRD §2.11: "Existence — path identifiers resolve left to right, and body identifiers (formula, order, line, bin, ingredient, truck, contract) exist; customer-scoped callers see only their own resources (`ERR_NOT_FOUND`)."

    Design: Corner/entities/bin_get_with_unknown_id_returns_404
    """
    resp = api.get_bin(NON_EXISTENT_UUID, MM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_ingredient_create_with_invalid_enum_rejected(api):
    """PRD §2.11: "Request schema — required fields present, types valid, enum members in range, tonnages positive, datetimes parseable, and any planned end strictly after its planned start (`ERR_INVALID_REQUEST`)."
    PRD §3.1: "a `hazard_class` of `STANDARD` or `MEDICATED`"

    Design: Corner/entities/ingredient_create_with_invalid_enum_rejected
    """
    payload = create_ingredient_payload("CORN", code="X", name="Mystery",
                                        hazard_class="TOXIC")
    resp = api.create_ingredient(payload, MM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_order_create_with_unknown_formula_returns_404(api):
    """PRD §2.11: "Existence — path identifiers resolve left to right, and body identifiers (formula, order, line, bin, ingredient, truck, contract) exist; customer-scoped callers see only their own resources (`ERR_NOT_FOUND`)."

    Design: Corner/entities/order_create_with_unknown_formula_returns_404
    """
    customer = make_customer("Acme Farms", 1000000)
    resp = api.create_order(
        create_order_payload(NON_EXISTENT_UUID, 10, customer["version"]),
        make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
