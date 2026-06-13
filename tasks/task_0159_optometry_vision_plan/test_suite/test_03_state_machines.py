"""State-machine transitions: lab-order remake loop, parallel claim dimensions,
encounter/prescription lifecycle, and invalid/terminal transitions.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    assert_version_incremented,
    TEST_USERS,
    setup_active_rx,
    setup_selfpay_dispensed_order,
    setup_order_after_n_remakes,
    setup_adjudicated_routine_claim,
    setup_finalized_routine_encounter,
    place_lab_order,
    issue_prescription,
)

FRONT_DESK = TEST_USERS["front_desk_headers"]
BILLER = TEST_USERS["biller_headers"]


def test_laborder_remake_cycle_loops_back_to_in_lab(api):
    """PRD §3.6: "Requesting a remake advances the order from `DISPENSED` to
    `REMAKE_REQUESTED` ... From `REMAKE_REQUESTED` the optician sends the order back to
    the lab, advancing it from `REMAKE_REQUESTED` to `IN_LAB` and incrementing the
    order's `remake_count` by one."

    Design: Difficulty/non_linear_state_machine/laborder_remake_cycle_dispensed_remake_inlab
    """
    ctx = setup_selfpay_dispensed_order()
    order_id, opt_h = ctx["order"]["id"], ctx["opt_h"]

    remake = validate_success(api.request_lab_order_remake(order_id, {"reason": "scratch"}, opt_h), 200)
    assert remake["status"] == "REMAKE_REQUESTED"

    in_lab = validate_success(api.send_lab_order_to_lab(order_id, opt_h), 200)
    assert in_lab["status"] == "IN_LAB"
    assert in_lab["remake_count"] == 1


def test_laborder_second_remake_cycle_returns_to_dispensed(api):
    """PRD §3.6: "From `REMAKE_REQUESTED` the optician sends the order back to the lab,
    advancing it from `REMAKE_REQUESTED` to `IN_LAB` and incrementing the order's
    `remake_count` by one."
    PRD §3.6: "From `IN_LAB`, the optician dispenses the finished eyewear to the
    patient ... dispensing advances the order from `IN_LAB` to `DISPENSED`."

    A second full DISPENSED -> REMAKE_REQUESTED -> IN_LAB -> DISPENSED loop advances
    remake_count to 2, re-visiting DISPENSED — a genuine cycle.

    Design: Difficulty/non_linear_state_machine/laborder_remake_cycle_dispensed_remake_inlab
    """
    ctx = setup_order_after_n_remakes(1)  # one completed cycle, remake_count == 1, DISPENSED
    order_id, opt_h, opt_id = ctx["order"]["id"], ctx["opt_h"], ctx["opt"]["id"]
    assert ctx["order"]["status"] == "DISPENSED"
    assert ctx["order"]["remake_count"] == 1

    remake = validate_success(api.request_lab_order_remake(order_id, {"reason": "again"}, opt_h), 200)
    assert remake["status"] == "REMAKE_REQUESTED"
    in_lab = validate_success(api.send_lab_order_to_lab(order_id, opt_h), 200)
    assert in_lab["status"] == "IN_LAB"
    assert in_lab["remake_count"] == 2
    dispensed = validate_success(api.dispense_lab_order(
        order_id, {"dispensing_optician_id": opt_id}, opt_h), 200)
    assert dispensed["status"] == "DISPENSED"


def test_claim_submission_dimension_independent_of_settlement(api):
    """PRD §3.9: "submission is permitted only when the claim's `claim_status` is
    `ADJUDICATED`, `SETTLED_PARTIAL`, or `SETTLED` and its `submission_status` is still
    `UNSUBMITTED`."
    PRD §3.9: "After submission, the biller records the carrier's acknowledgement by
    supplying an `outcome`, which moves the `submission_status` from `SUBMITTED` to
    `ACCEPTED` or from `SUBMITTED` to `REJECTED`."

    A partially-settled claim can be submitted and carrier-rejected while its
    claim_status stays SETTLED_PARTIAL — the two dimensions evolve independently.

    Design: Difficulty/non_linear_state_machine/claim_parallel_financial_and_submission_dimensions
    """
    ctx = setup_adjudicated_routine_claim()
    claim_id = ctx["claim"]["id"]
    partial = get_success_data(api.pay_claim(claim_id, {"amount_cents": 1000}, BILLER))
    assert partial["claim_status"] == "SETTLED_PARTIAL"

    get_success_data(api.submit_claim(claim_id, BILLER))
    acked = validate_success(api.carrier_ack_claim(claim_id, {"outcome": "REJECTED"}, BILLER), 200)
    assert acked["submission_status"] == "REJECTED"
    assert acked["claim_status"] == "SETTLED_PARTIAL"


def test_laborder_new_order_starts_placed(api):
    """PRD §3.5: "A new order begins `PLACED` with a `remake_count` of zero, and its
    `dispensing_optician_id` and `dispensed_at` are null until the order is dispensed."

    Design: Corner/state_machines/new_laborder_starts_in_placed
    """
    ctx = setup_active_rx(with_optician=True, patient_overrides={"plan_carrier": "NONE"})
    order = validate_success(api.create_lab_order({
        "prescription_id": ctx["rx"]["id"],
        "frame_charge_cents": 15000,
        "lens_charge_cents": 8000,
        "frame_brand_tier": "STANDARD",
    }, ctx["opt_h"]), 201)
    assert order["status"] == "PLACED"
    assert order["remake_count"] == 0


def test_claim_parallel_financial_and_submission_dimensions(api):
    """PRD §3.9: "The claim's carrier-submission status evolves on a parallel track
    that does not change its financial `claim_status`. A biller submits a claim to the
    carrier, advancing its `submission_status` from `UNSUBMITTED` to `SUBMITTED` ...
    After submission, the biller records the carrier's acknowledgement by supplying an
    `outcome`, which moves the `submission_status` from `SUBMITTED` to `ACCEPTED` or
    from `SUBMITTED` to `REJECTED`."

    Design: Difficulty/non_linear_state_machine/claim_parallel_financial_and_submission_dimensions
    """
    ctx = setup_adjudicated_routine_claim()
    claim_id = ctx["claim"]["id"]

    get_success_data(api.submit_claim(claim_id, BILLER))
    acked = validate_success(api.carrier_ack_claim(claim_id, {"outcome": "ACCEPTED"}, BILLER), 200)

    assert acked["submission_status"] == "ACCEPTED"
    assert acked["claim_status"] == "ADJUDICATED"


def test_claim_partial_then_full_payment_settles(api):
    """PRD §3.9: "A payment that is greater than zero but smaller than the full
    remaining responsibility advances the claim from `ADJUDICATED` to `SETTLED_PARTIAL`
    and increases `settled_cents` by the payment amount. ... A payment that exactly
    closes the remaining balance on a partially settled claim advances it from
    `SETTLED_PARTIAL` to `SETTLED`; in both closing cases `settled_cents` is set equal
    to `patient_responsibility_cents`."

    Design: Corner/state_machines/claim_partial_then_full_payment_settles
    """
    ctx = setup_adjudicated_routine_claim()
    claim_id = ctx["claim"]["id"]

    partial = validate_success(api.pay_claim(claim_id, {"amount_cents": 1000}, BILLER), 200)
    assert partial["claim_status"] == "SETTLED_PARTIAL"
    assert partial["settled_cents"] == 1000

    settled = validate_success(api.pay_claim(claim_id, {"amount_cents": 1500}, BILLER), 200)
    assert settled["claim_status"] == "SETTLED"
    assert settled["settled_cents"] == 2500


def test_finalize_open_encounter_invalid_state(api):
    """PRD §3.2: "Once `REFRACTED`, the conducting optometrist may finalize it,
    advancing it from `REFRACTED` to `FINALIZED`; finalization is legal only from
    `REFRACTED`. ... Any attempt to finalize or void an encounter that is not in the
    required starting state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/finalize_open_encounter_invalid_state
    """
    from test_helpers import setup_clinic, create_open_encounter
    ctx = setup_clinic(with_optician=False, patient_overrides={"plan_carrier": "NONE"})
    enc = create_open_encounter(ctx["pat"]["id"], ctx["od"]["id"])

    res = api.finalize_encounter(enc["id"], ctx["od_h"])
    validate_error(res, "ERR_INVALID_STATE")


def test_void_encounter_with_prescription_blocked(api):
    """PRD §3.2: "Alternatively, while still `OPEN` and before any prescription
    references it, a `FrontDesk` coordinator may void it, advancing it from `OPEN` to
    `VOIDED`; voiding is permitted only when the encounter is `OPEN` and no prescription
    references it."

    Design: Corner/state_machines/void_encounter_with_prescription_blocked_invalid_state
    """
    ctx = setup_active_rx(with_optician=False, patient_overrides={"plan_carrier": "NONE"})
    # The encounter is now REFRACTED (a prescription references it).
    res = api.void_encounter(ctx["enc"]["id"], FRONT_DESK)
    validate_error(res, "ERR_INVALID_STATE")


def test_revoke_already_revoked_prescription_invalid_state(api):
    """PRD §3.3: "An optometrist may also revoke an active prescription, moving it from
    `ACTIVE` to `REVOKED`. Revocation is permitted only when the prescription is
    `ACTIVE` and no lab order in `PLACED` or `IN_LAB` status references it; `REVOKED` is
    terminal."

    Design: Corner/state_machines/prescription_supersede_terminal_revoked
    """
    ctx = setup_active_rx(with_optician=False, patient_overrides={"plan_carrier": "NONE"})
    rx_id = ctx["rx"]["id"]
    get_success_data(api.revoke_prescription(rx_id, ctx["od_h"]))

    res = api.revoke_prescription(rx_id, ctx["od_h"])
    validate_error(res, "ERR_INVALID_STATE")


def test_third_remake_blocked_max_remakes(api):
    """PRD §3.6: "Requesting a remake advances the order from `DISPENSED` to
    `REMAKE_REQUESTED` and is permitted only when the order is `DISPENSED`, when the
    current clock instant is no later than 90 days after `dispensed_at`, and when the
    order's `remake_count` is below the maximum of two completed remakes; a request that
    falls outside the 90-day window or that has already reached two remakes is rejected
    with `ERR_REMAKE_WINDOW_CLOSED`."

    Design: Corner/state_machines/third_remake_blocked_max_remakes_terminal_count
    """
    ctx = setup_order_after_n_remakes(2)  # remake_count == 2, DISPENSED, in window
    assert ctx["order"]["remake_count"] == 2

    res = api.request_lab_order_remake(ctx["order"]["id"], {"reason": "r3"}, ctx["opt_h"])
    validate_error(res, "ERR_REMAKE_WINDOW_CLOSED")
