"""Voiding a posted ticket conserves both airspace and hauler balance."""
from test_helpers import (
    validate_success, make_gate_operator_headers, make_facility_admin_headers,
    setup_posted_ticket, get_facility,
)

POST_USER = "op_post"


def test_void_restores_facility_consumed_airspace(api):
    """PRD §3.7: "The facility's `consumed_airspace_cubic_yards` and `acceptance_posture` are
    recomputed and its `version` is incremented by 1."
    PRD §3.7: "The cell's `consumed_cubic_yards` is decreased by the ticket's
    `posted_airspace_cy`; if that cell was `FULL` and its `remaining_cubic_yards` is now
    greater than 0, it transitions `FULL → OPEN`."

    Design: Difficulty/compensating_invariant/post_void_conserves_facility_airspace
    """
    ctx = setup_posted_ticket()
    voided = validate_success(
        api.void_ticket(ctx["ticket"]["id"], make_gate_operator_headers(POST_USER)))
    assert voided["status"] == "VOIDED"
    facility = get_facility(ctx["facility"]["id"])
    assert facility["consumed_airspace_cubic_yards"] == 0.0


def test_void_restores_cell_consumed_airspace(api):
    """PRD §3.7: "The cell's `consumed_cubic_yards` is decreased by the ticket's
    `posted_airspace_cy`; if that cell was `FULL` and its `remaining_cubic_yards` is now
    greater than 0, it transitions `FULL → OPEN`."

    Design: Difficulty/compensating_invariant/post_void_conserves_facility_airspace
    """
    ctx = setup_posted_ticket()
    validate_success(api.void_ticket(ctx["ticket"]["id"], make_gate_operator_headers(POST_USER)))
    cell = validate_success(api.get_cell(ctx["cell"]["id"], make_gate_operator_headers(POST_USER)))
    assert cell["consumed_cubic_yards"] == 0.0
    assert cell["status"] == "OPEN"


def test_post_charges_then_void_reverses_hauler_balance(api):
    """PRD §3.7: "The hauler's `balance_cents` is decreased by the ticket's
    `tipping_fee_cents`, and if the balance is now below the credit limit while the account is
    `SUSPENDED`, the account transitions back `SUSPENDED → ACTIVE`."

    Design: Difficulty/compensating_invariant/post_void_conserves_hauler_balance
    """
    ctx = setup_posted_ticket()
    charged = validate_success(
        api.get_hauler_account(ctx["hauler"]["id"], make_facility_admin_headers("adm1")))
    assert charged["balance_cents"] == 2600
    validate_success(api.void_ticket(ctx["ticket"]["id"], make_gate_operator_headers(POST_USER)))
    reversed_ = validate_success(
        api.get_hauler_account(ctx["hauler"]["id"], make_facility_admin_headers("adm1")))
    assert reversed_["balance_cents"] == 0


def test_void_posted_ticket_is_terminal_voided(api):
    """PRD §3.7: "Voiding a `POSTED` ticket advances `POSTED → VOIDED` and reverses every
    effect of the post, conserving both airspace and balance."

    Design: Difficulty/compensating_invariant/post_void_conserves_hauler_balance
    """
    ctx = setup_posted_ticket()
    voided = validate_success(
        api.void_ticket(ctx["ticket"]["id"], make_gate_operator_headers(POST_USER)))
    assert voided["status"] == "VOIDED"
