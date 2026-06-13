"""Dietary substitutions: surcharge billing, compensating revert, and applicability.

Queue A: compensating_invariant (substitution revert conserves Booking.charge_cents).
Queue B: approve surcharge, reject, cheaper-substitute floor, neutral-line rejection.
"""
from test_helpers import (
    validate_success,
    validate_error,
    setup_requested_substitution,
    make_instructor_headers,
    make_member_headers,
)


def test_substitution_revert_conserves_booking_charge(api):
    """PRD §3.9: "Approval advances the substitution REQUESTED -> APPROVED and
    computes the surcharge: the per-unit delta is the alternate unit cost minus
    the original line's unit_cost_cents, floored at 0 ... and the surcharge_cents
    is that delta multiplied by the line's qty_per_seat and by the booking's
    seats_requested, rounded half-up to whole cents once at the end. The surcharge
    is added to the parent booking's charge_cents".
    PRD §3.9: "A revert is a compensating operation: it subtracts the exact
    surcharge_cents that approval had added back out of the booking's charge_cents
    ... so that ... the booking's charge_cents and the sum of its three applied
    funding fields both return to their pre-approval totals".

    Approve adds surcharge 720 (delta 2400 * 0.05 * 6) lifting charge 52380 ->
    53100; revert subtracts exactly 720, returning charge to 52380.

    Design: Difficulty/compensating_invariant/substitution_revert_conserves_booking_charge
    """
    instr, member, session, line, booking, sub = setup_requested_substitution(
        skill_level="ADVANCED", base_price_cents=8500, seats_requested=6,
        dietary_tag="CONTAINS_DAIRY", line_unit_cost_cents=1850, line_qty_per_seat=0.05,
        alternate_unit_cost_cents=4250,
    )
    instr_headers = make_instructor_headers(instr["id"])
    assert booking["charge_cents"] == 52380

    validate_success(api.approve_substitution(sub["id"], instr_headers), 200)
    after_approve = validate_success(api.get_booking(booking["id"], make_member_headers(member["id"])), 200)
    assert after_approve["charge_cents"] == 53100, "approve adds surcharge 720"

    reverted = validate_success(api.revert_substitution(sub["id"], instr_headers), 200)
    assert reverted["status"] == "REVERTED"
    after_revert = validate_success(api.get_booking(booking["id"], make_member_headers(member["id"])), 200)
    assert after_revert["charge_cents"] == 52380, (
        f"revert conserves charge to pre-approval 52380, got {after_revert['charge_cents']}"
    )


def test_substitution_revert_restores_funding_split(api):
    """PRD §3.9: "reverses the waterfall debits in the opposite order - card
    first, then wallet, then gift card via REVERSAL ledger entries - so that each
    funding source returns to its pre-approval value and the booking's charge_cents
    and the sum of its three applied funding fields both return to their
    pre-approval totals".

    A second witness on the conserved quantity: after revert the three applied
    funding fields sum back to the original 52380 charge (paid entirely to card).

    Design: Difficulty/compensating_invariant/substitution_revert_conserves_booking_charge
    """
    instr, member, session, line, booking, sub = setup_requested_substitution(
        skill_level="ADVANCED", base_price_cents=8500, seats_requested=6,
        dietary_tag="CONTAINS_DAIRY", line_unit_cost_cents=1850, line_qty_per_seat=0.05,
        alternate_unit_cost_cents=4250,
    )
    instr_headers = make_instructor_headers(instr["id"])
    validate_success(api.approve_substitution(sub["id"], instr_headers), 200)
    validate_success(api.revert_substitution(sub["id"], instr_headers), 200)

    after = validate_success(api.get_booking(booking["id"], make_member_headers(member["id"])), 200)
    applied_sum = (
        after["gift_card_applied_cents"] + after["wallet_applied_cents"] + after["card_applied_cents"]
    )
    assert after["charge_cents"] == 52380
    assert applied_sum == 52380, (
        f"funding split restored to pre-approval total 52380, got {applied_sum}"
    )


def test_approve_substitution_bills_surcharge(api):
    """PRD §3.9: "the surcharge_cents is that delta multiplied by the line's
    qty_per_seat and by the booking's seats_requested, rounded half-up to whole
    cents once at the end. The surcharge is added to the parent booking's
    charge_cents".

    Delta 2400 * 0.05 * 6 = 720; charge 52380 -> 53100.

    Design: Corner/state_machines/substitution_approve_surcharge_billed
    """
    instr, member, session, line, booking, sub = setup_requested_substitution(
        skill_level="ADVANCED", base_price_cents=8500, seats_requested=6,
        dietary_tag="CONTAINS_DAIRY", line_unit_cost_cents=1850, line_qty_per_seat=0.05,
        alternate_unit_cost_cents=4250,
    )
    approved = validate_success(
        api.approve_substitution(sub["id"], make_instructor_headers(instr["id"])), 200
    )
    assert approved["surcharge_cents"] == 720
    after = validate_success(api.get_booking(booking["id"], make_member_headers(member["id"])), 200)
    assert after["charge_cents"] == 53100


def test_reject_substitution_leaves_charge_unchanged(api):
    """PRD §3.9: "An instructor may instead reject a REQUESTED substitution
    (REQUESTED -> REJECTED), which changes no charge."

    Rejecting a REQUESTED substitution moves it to REJECTED with the BEGINNER
    1-seat booking charge unchanged at 5000.

    Design: Corner/state_machines/substitution_reject_from_requested
    """
    instr, member, session, line, booking, sub = setup_requested_substitution(
        skill_level="BEGINNER", base_price_cents=5000, seats_requested=1,
        dietary_tag="CONTAINS_NUT", line_unit_cost_cents=500, line_qty_per_seat=0.02,
        alternate_unit_cost_cents=900,
    )
    assert booking["charge_cents"] == 5000
    rejected = validate_success(
        api.reject_substitution(sub["id"], make_instructor_headers(instr["id"])), 200
    )
    assert rejected["status"] == "REJECTED"
    after = validate_success(api.get_booking(booking["id"], make_member_headers(member["id"])), 200)
    assert after["charge_cents"] == 5000


def test_cheaper_substitute_floors_surcharge_to_zero(api):
    """PRD §3.9: "the per-unit delta is the alternate unit cost minus the original
    line's unit_cost_cents, floored at 0 so that a cheaper substitute is free
    rather than a credit".

    Alternate 100 < original 500: delta max(0, -400) = 0, surcharge 0, booking
    charge unchanged at 5000 (no credit issued).

    Design: Corner/calculations/cheaper_substitute_floors_surcharge_to_zero
    """
    instr, member, session, line, booking, sub = setup_requested_substitution(
        skill_level="BEGINNER", base_price_cents=5000, seats_requested=1,
        dietary_tag="CONTAINS_NUT", line_unit_cost_cents=500, line_qty_per_seat=0.02,
        alternate_unit_cost_cents=100,
    )
    approved = validate_success(
        api.approve_substitution(sub["id"], make_instructor_headers(instr["id"])), 200
    )
    assert approved["surcharge_cents"] == 0
    after = validate_success(api.get_booking(booking["id"], make_member_headers(member["id"])), 200)
    assert after["charge_cents"] == 5000


def test_substitution_on_neutral_line_rejected(api):
    """PRD §3.9: "At creation the named ingredient line must belong to the same
    session as the booking and its dietary_tag must not be NEUTRAL; a line that is
    on a different session or that is NEUTRAL makes the request inapplicable and it
    is rejected with ERR_SUBSTITUTION_NOT_APPLICABLE."

    Requesting a substitution against a NEUTRAL-tagged line is rejected
    ERR_SUBSTITUTION_NOT_APPLICABLE.

    Design: Corner/validations/substitution_on_neutral_line_rejected
    """
    from test_helpers import (
        create_instructor, create_member, create_published_template, create_session,
        add_ingredient_line, create_confirmed_booking,
    )
    instr = create_instructor()
    tmpl = create_published_template(
        skill_level="BEGINNER", base_price_cents=5000, default_capacity=2,
        station_fixed_cost_cents=1000,
    )
    session = create_session(
        tmpl["id"], instr["id"], station_id="ST-SN", planned_seats=2,
        start_at="2026-11-19T14:00:00Z", end_at="2026-11-19T16:00:00Z",
    )
    line = add_ingredient_line(
        session["id"], instr["id"], name="rice", qty_per_seat=0.1, unit_cost_cents=200
    )  # dietary_tag defaults to NEUTRAL
    validate_success(api.open_session(session["id"], make_instructor_headers(instr["id"])), 200)
    member = create_member()
    booking = create_confirmed_booking(session["id"], member["id"], 1)
    res = api.create_substitution(
        {"booking_id": booking["id"], "ingredient_line_id": line["id"],
         "alternate_unit_cost_cents": 500},
        make_member_headers(member["id"]),
    )
    validate_error(res, "ERR_SUBSTITUTION_NOT_APPLICABLE", expected_status=422)
