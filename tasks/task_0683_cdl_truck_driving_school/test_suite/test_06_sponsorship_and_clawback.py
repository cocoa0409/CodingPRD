"""Carrier sponsorship: acceptance, the conflict guard, fulfillment, and the linear
clawback decay on forfeiture.

Translates queue A (dual_variant_calc/reimbursement_clawback_vs_finance_schedule_distinct_domains,
transitive_cascade/withdraw_forfeits_sponsorship_computes_clawback_depth2,
boundary_precision_check/sponsorship_offer_empty_set_accept_allowed) and queue B
(calculations, validations) instances.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_program, create_carrier, create_enrollment,
    create_enrollment_in_training,
    setup_accepted_sponsorship, extend_offer, accept_offer,
)

ADMIN = TEST_USERS["school_admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


# ---- Queue A: dual_variant_calc / reimbursement_clawback_vs_finance_schedule_distinct_domains ----

def test_clawback_linear_decay_partial_service():
    """PRD §3.6: "Otherwise clawback_cents is the carrier's reimbursement_cents
    multiplied by the remaining months and divided by the carrier's commitment_months,
    rounded half-up to an integer number of cents." PRD §3.6: "First compute the
    remaining months as the carrier's commitment_months minus the offer's months_served."

    Design: Difficulty/dual_variant_calc/reimbursement_clawback_vs_finance_schedule_distinct_domains
    """
    # commitment 12, reimbursement 600000, months_served advanced to 5.
    ctx = setup_accepted_sponsorship(
        commitment_months=12, reimbursement_cents=600000, months_served=5)
    resp = api_client.forfeit_sponsorship_offer(ctx["offer_id"], ADMIN)
    offer = validate_success(resp)
    assert offer["status"] == "FORFEITED"
    # remaining = 12 - 5 = 7; clawback = round_half_up(600000 * 7 / 12) = 350000.
    assert offer["clawback_cents"] == 350000


def test_forfeit_clears_sponsoring_carrier_on_enrollment():
    """PRD §3.6: "either path moves the offer from ACCEPTED to FORFEITED, computes
    clawback_cents, and clears the enrollment's sponsoring_carrier_id."

    Design: Difficulty/dual_variant_calc/reimbursement_clawback_vs_finance_schedule_distinct_domains
    """
    ctx = setup_accepted_sponsorship(
        commitment_months=12, reimbursement_cents=600000, months_served=5)
    api_client.forfeit_sponsorship_offer(ctx["offer_id"], ADMIN)
    enr = validate_success(api_client.get_enrollment(ctx["enrollment_id"], REGISTRAR))
    assert enr["sponsoring_carrier_id"] is None, "sponsoring_carrier_id must be cleared on forfeit"


# ---- Queue A: transitive_cascade / withdraw_forfeits_sponsorship_computes_clawback_depth2 ----

def test_withdraw_forfeits_accepted_sponsorship_full_clawback():
    """PRD §3.9: "If the enrollment has an ACCEPTED sponsorship offer, that offer is
    moved to FORFEITED with its clawback_cents computed per §3.6". PRD §3.6: "when a
    graduate forfeits with months_served equal to 0, the remaining months equal the full
    commitment and the clawback equals the entire reimbursement_cents."

    Design: Difficulty/transitive_cascade/withdraw_forfeits_sponsorship_computes_clawback_depth2
    """
    # months_served 0 -> full clawback of the entire reimbursement (600000).
    ctx = setup_accepted_sponsorship(
        commitment_months=12, reimbursement_cents=600000, months_served=0)
    validate_success(api_client.withdraw_enrollment(ctx["enrollment_id"], REGISTRAR))
    enr = validate_success(api_client.get_enrollment(ctx["enrollment_id"], REGISTRAR))
    assert enr["status"] == "WITHDRAWN"
    offer = validate_success(api_client.get_sponsorship_offer(ctx["offer_id"], REGISTRAR))
    assert offer["status"] == "FORFEITED"
    assert offer["clawback_cents"] == 600000


def test_withdraw_forfeit_is_caused_by_withdrawal_cascade():
    """PRD §3.9: "Withdrawal is a cascading event." PRD §3.9: "If the enrollment has an
    ACCEPTED sponsorship offer, that offer is moved to FORFEITED with its clawback_cents
    computed per §3.6".

    Design: Difficulty/transitive_cascade/withdraw_forfeits_sponsorship_computes_clawback_depth2
    """
    ctx = setup_accepted_sponsorship(
        commitment_months=12, reimbursement_cents=600000, months_served=0)
    # Before withdrawal the offer is still ACCEPTED.
    pre = validate_success(api_client.get_sponsorship_offer(ctx["offer_id"], REGISTRAR))
    assert pre["status"] == "ACCEPTED"
    api_client.withdraw_enrollment(ctx["enrollment_id"], REGISTRAR)
    post = validate_success(api_client.get_sponsorship_offer(ctx["offer_id"], REGISTRAR))
    assert post["status"] == "FORFEITED"
    assert post["clawback_cents"] == 600000


# ---- Queue A: boundary_precision_check / sponsorship_offer_empty_set_accept_allowed ----

def test_accept_first_offer_succeeds_empty_accepted_set():
    """PRD §3.6: "A Registrar accepts an OFFERED offer, provided the enrollment has no
    other ACCEPTED sponsorship offer ... Acceptance moves the offer to ACCEPTED and sets
    the enrollment's sponsoring_carrier_id to the offer's carrier."

    Design: Difficulty/boundary_precision_check/sponsorship_offer_empty_set_accept_allowed
    """
    program = create_program()
    carrier = create_carrier(commitment_months=12, reimbursement_cents=600000)
    enr = create_enrollment(program["id"])
    offer = extend_offer(enr["id"], carrier["id"])
    accepted = validate_success(api_client.accept_sponsorship_offer(offer["id"], REGISTRAR))
    assert accepted["status"] == "ACCEPTED"
    final = validate_success(api_client.get_enrollment(enr["id"], REGISTRAR))
    assert final["sponsoring_carrier_id"] == carrier["id"]


def test_accept_only_offer_sets_carrier_on_enrollment():
    """PRD §3.6: "Acceptance moves the offer to ACCEPTED and sets the enrollment's
    sponsoring_carrier_id to the offer's carrier."

    Design: Difficulty/boundary_precision_check/sponsorship_offer_empty_set_accept_allowed
    """
    program = create_program()
    carrier = create_carrier()
    enr = create_enrollment(program["id"])
    offer = extend_offer(enr["id"], carrier["id"])
    accept_offer(offer["id"])
    final = validate_success(api_client.get_enrollment(enr["id"], REGISTRAR))
    assert final["sponsoring_carrier_id"] == carrier["id"]


# ---- Queue B: calculations / clawback_zero_when_commitment_fully_served ----

def test_clawback_zero_when_commitment_fully_served():
    """PRD §3.6: "When months_served reaches at least the carrier's commitment_months,
    the offer automatically transitions from ACCEPTED to FULFILLED, its clawback_cents
    is set to 0, and the service obligation is discharged."

    Design: Corner/calculations/clawback_zero_when_commitment_fully_served
    """
    program = create_program()
    carrier = create_carrier(commitment_months=12, reimbursement_cents=600000)
    enr = create_enrollment(program["id"])
    offer = extend_offer(enr["id"], carrier["id"])
    accept_offer(offer["id"])
    # Advance service to the full commitment -> auto-FULFILLED, clawback 0.
    resp = api_client.advance_service_months(offer["id"], 12, ADMIN)
    data = validate_success(resp)
    assert data["status"] == "FULFILLED"
    assert data["clawback_cents"] == 0


# ---- Queue B: validations / second_sponsorship_accept_conflict ----

def test_second_sponsorship_accept_conflict():
    """PRD §3.6: "A Registrar accepts an OFFERED offer, provided the enrollment has no
    other ACCEPTED sponsorship offer — a second acceptance is rejected with
    ERR_SPONSORSHIP_CONFLICT."

    Design: Corner/validations/second_sponsorship_accept_conflict
    """
    program = create_program()
    carrier_a = create_carrier(name="A", reimbursement_cents=600000)
    carrier_b = create_carrier(name="B", reimbursement_cents=400000)
    enr = create_enrollment(program["id"])
    offer_a = extend_offer(enr["id"], carrier_a["id"])
    offer_b = extend_offer(enr["id"], carrier_b["id"])
    accept_offer(offer_a["id"])
    # Second acceptance while one is already ACCEPTED.
    resp = api_client.accept_sponsorship_offer(offer_b["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_SPONSORSHIP_CONFLICT.value)
