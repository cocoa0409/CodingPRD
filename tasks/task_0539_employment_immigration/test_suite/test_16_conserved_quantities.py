"""Compensating invariants: cap seats conserved across select/withdraw, and the
employer wage obligation conserved across certify/withdraw (PRD §3.5, §3.1).

Queue A / Difficulty — rule `compensating_invariant`.
"""
from test_helpers import (
    api_client, validate_success, TEST_USERS,
    create_employer, create_beneficiary, create_lca, certify_lca,
    setup_selected_registration, make_employer_agent_headers,
)

USCIS = TEST_USERS["uscis_officer_headers"]


def test_cap_seat_consumed_on_selection(api):
    """PRD §3.5: "The seat accounting obeys the invariant `available_seats` +
    `selected_count` = `selection_quota` at all times; `selected_count` is defined
    as the number of registrations for this `fiscal_year` whose `status` is
    `SELECTED`, and `available_seats` is `selection_quota` minus `selected_count`."

    Design: Difficulty/compensating_invariant/cap_seats_conserved_on_select_then_withdraw
    """
    emp = create_employer()
    ben = create_beneficiary(emp["id"])
    cap, reg = setup_selected_registration(emp["id"], ben["id"], 2027, 5)
    program = validate_success(api.get_cap_program(cap["id"], USCIS), 200)
    assert program["selected_count"] == 1
    assert program["available_seats"] == 4


def test_cap_seat_restored_on_withdrawal(api):
    """PRD §3.5: "A successful withdrawal is compensating — it decrements the
    program's `selected_count` by one and increments `available_seats` by one,
    returning the seat to the pool."

    Design: Difficulty/compensating_invariant/cap_seats_conserved_on_select_then_withdraw
    """
    emp = create_employer()
    ben = create_beneficiary(emp["id"])
    cap, reg = setup_selected_registration(emp["id"], ben["id"], 2027, 5)
    hdr = make_employer_agent_headers(emp["id"])
    validate_success(api.transition_registration(reg["id"], {"to_status": "WITHDRAWN"}, hdr), 200)
    program = validate_success(api.get_cap_program(cap["id"], USCIS), 200)
    assert program["selected_count"] == 0
    assert program["available_seats"] == 5


def test_wage_obligation_rises_on_certification(api):
    """PRD §3.1: "certifying an application adds that application's locked
    `required_wage_cents`, and withdrawing a certified application subtracts the
    same amount."

    Design: Difficulty/compensating_invariant/employer_wage_obligation_conserved_on_certify_then_withdraw
    """
    emp = create_employer()
    hdr = make_employer_agent_headers(emp["id"])
    lca = create_lca(emp["id"], offered_wage_cents=12000000, prevailing_wage_cents=10000000)
    certify_lca(emp["id"], lca["id"])
    after_certify = validate_success(api.get_employer(emp["id"], hdr), 200)
    assert after_certify["total_wage_obligation_cents"] == 12000000


def test_wage_obligation_restored_on_withdrawal(api):
    """PRD §3.1: "The invariant is that at any moment `total_wage_obligation_cents`
    equals the summed `required_wage_cents` of the employer's currently-`CERTIFIED`
    applications."

    Design: Difficulty/compensating_invariant/employer_wage_obligation_conserved_on_certify_then_withdraw
    """
    emp = create_employer()
    hdr = make_employer_agent_headers(emp["id"])
    lca = create_lca(emp["id"], offered_wage_cents=12000000, prevailing_wage_cents=10000000)
    certify_lca(emp["id"], lca["id"])
    validate_success(api.transition_lca(lca["id"], {"to_status": "WITHDRAWN"}, hdr), 200)
    after_withdraw = validate_success(api.get_employer(emp["id"], hdr), 200)
    assert after_withdraw["total_wage_obligation_cents"] == 0
