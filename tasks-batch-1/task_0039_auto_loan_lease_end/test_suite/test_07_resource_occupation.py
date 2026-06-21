"""Resource occupation: a vehicle holds at most one open finance contract, released
on return/payoff; exactly one rate card is active; vehicle-availability gating.
"""
from test_helpers import (
    validate_success, validate_error,
    create_active_rate_card, create_customer, create_vehicle,
    create_loan_payload, create_rate_card_payload,
    setup_loan, setup_matured_lease, elect_lease_end,
    TEST_USERS, make_borrower_headers,
)

FM = TEST_USERS["finance_manager_headers"]


def test_loan_origination_on_financed_vehicle_rejected(api):
    """PRD §3.2: "The targeted vehicle must currently be `AVAILABLE` — a vehicle already financed
    cannot be financed again, and an attempt to do so is rejected with `ERR_VEHICLE_UNAVAILABLE`."

    Design: Difficulty/cross_entity_state_dependency/loan_origination_requires_vehicle_available
    """
    customer, vehicle, loan_a = setup_loan(fico_score=760)
    # Vehicle now FINANCED. A second loan on it must be rejected.
    res = api.create_loan(create_loan_payload(customer["id"], vehicle["id"]), FM)
    validate_error(res, "ERR_VEHICLE_UNAVAILABLE")


def test_loan_origination_blocked_while_vehicle_financed(api):
    """PRD §3.2: "The targeted vehicle must currently be `AVAILABLE` — a vehicle already financed
    cannot be financed again, and an attempt to do so is rejected with `ERR_VEHICLE_UNAVAILABLE`."

    Design: Difficulty/cross_entity_state_dependency/loan_origination_requires_vehicle_available
    """
    customer, vehicle, loan_a = setup_loan(fico_score=760)
    vehicle_state = validate_success(api.get_vehicle(vehicle["id"], FM), 200)
    assert vehicle_state["status"] == "FINANCED"
    res = api.create_loan(create_loan_payload(customer["id"], vehicle["id"]), FM)
    validate_error(res, "ERR_VEHICLE_UNAVAILABLE")


def test_vehicle_released_on_return_allows_reorigination(api):
    """PRD §3.6: "On a return the lease's `odometer_miles` is set from the settlement's
    `odometer_miles`, the lease advances `RETURNED` then to `SETTLED`, and the associated
    vehicle's `status` is set to `AVAILABLE`."
    PRD §3.2: "The targeted vehicle must currently be `AVAILABLE` — a vehicle already financed
    cannot be financed again, and an attempt to do so is rejected with `ERR_VEHICLE_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/vehicle_single_active_finance_occupation
    """
    customer, vehicle, matured = setup_matured_lease(fico_score=760)
    borrower = make_borrower_headers(customer["id"])
    elect_lease_end(matured["id"], customer["id"], "RETURN", 36000, matured["version"],
                    per_year_excess_miles=[0, 0, 0])
    # Vehicle released to AVAILABLE; a new loan now succeeds.
    new_loan = validate_success(api.create_loan(
        create_loan_payload(customer["id"], vehicle["id"]), FM), 201)
    assert new_loan["status"] == "CURRENT"


def test_vehicle_financed_again_after_reorigination(api):
    """PRD §3.2: "As the closing side effect, the associated vehicle's `status` is set to
    `FINANCED`."

    Design: Difficulty/resource_temporal_overlap/vehicle_single_active_finance_occupation
    """
    customer, vehicle, matured = setup_matured_lease(fico_score=760)
    elect_lease_end(matured["id"], customer["id"], "RETURN", 36000, matured["version"],
                    per_year_excess_miles=[0, 0, 0])
    validate_success(api.create_loan(create_loan_payload(customer["id"], vehicle["id"]), FM), 201)
    vehicle_after = validate_success(api.get_vehicle(vehicle["id"], FM), 200)
    assert vehicle_after["status"] == "FINANCED"


def test_activating_second_card_deactivates_first(api):
    """PRD §3.1: "Exactly one card is active at any time: when a `FinanceManager` activates a
    card, that card's `active` becomes true and the previously active card, if any, has its
    `active` set back to false as a cascading side effect of the same operation."

    Design: Difficulty/resource_temporal_overlap/rate_card_single_active_occupation
    """
    rc_a = validate_success(api.create_rate_card(
        create_rate_card_payload(name="2026-Q1"), FM), 201)
    rc_b = validate_success(api.create_rate_card(
        create_rate_card_payload(name="2026-Q2"), FM), 201)
    validate_success(api.activate_rate_card(rc_a["id"], FM), 200)
    validate_success(api.activate_rate_card(rc_b["id"], FM), 200)
    a_after = validate_success(api.get_rate_card(rc_a["id"], FM), 200)
    b_after = validate_success(api.get_rate_card(rc_b["id"], FM), 200)
    assert a_after["active"] is False
    assert b_after["active"] is True


def test_exactly_one_card_active_singleton(api):
    """PRD §3.1: "Exactly one card is active at any time: when a `FinanceManager` activates a
    card, that card's `active` becomes true and the previously active card, if any, has its
    `active` set back to false as a cascading side effect of the same operation."

    Design: Difficulty/resource_temporal_overlap/rate_card_single_active_occupation
    """
    rc_a = validate_success(api.create_rate_card(
        create_rate_card_payload(name="2026-Q1"), FM), 201)
    rc_b = validate_success(api.create_rate_card(
        create_rate_card_payload(name="2026-Q2"), FM), 201)
    assert rc_a["active"] is False  # newly created card starts inactive
    assert rc_b["active"] is False
    validate_success(api.activate_rate_card(rc_a["id"], FM), 200)
    validate_success(api.activate_rate_card(rc_b["id"], FM), 200)
    a_after = validate_success(api.get_rate_card(rc_a["id"], FM), 200)
    assert a_after["active"] is False


def test_mature_on_already_maturing_returns_not_maturable(api):
    """PRD §3.6: "Maturing is permitted only from `ACTIVE`; an attempt on a lease not in `ACTIVE`
    is rejected with `ERR_LEASE_NOT_MATURABLE`."

    Design: Corner/state_machines/mature_on_already_maturing_returns_not_maturable
    """
    customer, vehicle, matured = setup_matured_lease(fico_score=760)  # already MATURING
    res = api.mature_lease(matured["id"], FM)
    validate_error(res, "ERR_LEASE_NOT_MATURABLE")
