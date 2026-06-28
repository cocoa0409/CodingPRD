"""State-machine corners: invalid transitions, terminal lockdown, firing cascades
(manual and clock-sweep), initial enrollment state.

Queue B (Corner): section state_machines (non-stub instances).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_member, create_open_visit, add_piece, create_batch, create_series,
    create_booking, load_piece, setup_settled_visit, fire_piece_to_ready,
    DEFAULT_CLOCK, TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]
MANAGER = TEST_USERS["manager_headers"]


def test_void_settled_visit_rejected(api):
    """PRD §3.9: "A visit may be voided only while it is OPEN." PRD §3.8: the visit
    "moves from OPEN to SETTLED, which is terminal."

    Design: Corner/state_machines/void_visit_from_settled_invalid_state
    """
    settled, _piece = setup_settled_visit(bisque_price_cents=3000)
    assert settled["status"] == "SETTLED"
    res = api.void_visit(settled["id"], MANAGER)
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_visit(settled["id"], STAFF), 200)
    assert after["status"] == "SETTLED", after["status"]


def test_pickup_painted_piece_rejected(api):
    """PRD §3.3: "Marking a READY piece picked up advances it from READY to
    PICKED_UP; this is permitted only from READY."

    Design: Corner/state_machines/pickup_piece_before_ready_invalid_state
    """
    visit = create_open_visit()
    piece = add_piece(visit["id"], bisque_price_cents=3000, sku="MUG-12OZ", name="Mug")
    res = api.pickup_piece(piece["id"], STAFF)
    validate_error(res, "ERR_INVALID_STATE")


def test_complete_firing_cascades_ready_at(api):
    """PRD §3.5: "every FIRING piece on the batch cascades to READY, each stamped
    with a ready_at equal to the current logical-clock instant, and the batch
    becomes COMPLETED." PRD §2.4: at startup "the clock reads exactly
    2026-04-01T00:00:00Z."

    Design: Corner/state_machines/full_firing_cascade_sets_ready_at
    """
    visit = create_open_visit()
    piece = add_piece(visit["id"], bisque_price_cents=3000, sku="MUG-12OZ", name="Mug")
    batch = create_batch(capacity_slots=4)
    load_piece(batch, piece["id"])
    api.start_firing(batch["id"], STAFF)
    completed = validate_success(api.complete_firing(batch["id"], STAFF), 200)
    assert completed["status"] == "COMPLETED", completed["status"]

    piece_after = validate_success(api.get_piece(piece["id"], STAFF), 200)
    assert piece_after["status"] == "READY", piece_after["status"]
    assert piece_after["ready_at"] is not None and piece_after["ready_at"].startswith("2026-04-01T00:00:00")


def test_clock_sweep_completes_firing(api):
    """PRD §3.5: "the logical clock is advanced to or past the batch's
    firing_completes_at and the completion sweep finishes it automatically." PRD
    §3.4: turnaround "defaulting to 48 hours."

    Design: Corner/state_machines/clock_sweep_completes_firing_batch
    """
    visit = create_open_visit()
    piece = add_piece(visit["id"], bisque_price_cents=3000, sku="MUG-12OZ", name="Mug")
    batch = create_batch(capacity_slots=4, turnaround_hours=48)
    load_piece(batch, piece["id"])
    api.start_firing(batch["id"], STAFF)  # started at default 2026-04-01, completes 2026-04-03

    api.set_clock({"to_iso8601": "2026-04-03T00:00:00Z"}, MANAGER)
    batch_after = validate_success(api.get_batch(batch["id"], STAFF), 200)
    assert batch_after["status"] == "COMPLETED", batch_after["status"]
    piece_after = validate_success(api.get_piece(piece["id"], STAFF), 200)
    assert piece_after["status"] == "READY", piece_after["status"]


def test_enrollment_initial_state(api):
    """PRD §3.10: "the series' price_cents is snapshotted onto the enrollment as its
    amount_paid_cents." PRD §3.10: "An enrollment travels through ENROLLED,
    ATTENDED, WITHDRAWN, and REFUNDED" (starting ENROLLED). PRD §3.10: base award is
    "amount_paid_cents divided by 100 and floored."

    Design: Corner/state_machines/enrollment_initial_state_enrolled
    """
    member = create_member()
    series = create_series(session_count=4, seat_capacity=5, price_cents=12000,
                           starts_at="2026-07-01T18:00:00Z")
    enr = validate_success(api.enroll(series["id"], {"member_id": member["id"]}, STAFF), 201)
    assert enr["status"] == "ENROLLED", enr["status"]
    assert enr["amount_paid_cents"] == 12000, enr["amount_paid_cents"]
    assert enr["points_earned"] == 120, enr["points_earned"]  # floor(12000/100), <6 sessions


def test_cancelled_booking_paydeposit_rejected(api):
    """PRD §3.6: "Cancelling a booking moves it from DEPOSIT_PENDING to CANCELLED."
    PRD §3.6: "Paying the deposit moves it from DEPOSIT_PENDING to CONFIRMED" — only
    from DEPOSIT_PENDING.

    Design: Corner/state_machines/terminal_party_booking_cancel_then_paydeposit_invalid
    """
    member = create_member()
    booking = create_booking(member["id"], package_tier="BASIC", guest_count=6,
                             scheduled_for="2026-09-01T18:00:00Z")
    api.cancel_booking(booking["id"], MANAGER)
    res = api.pay_deposit(booking["id"], {"amount_cents": 6750}, STAFF)
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_booking(booking["id"], STAFF), 200)
    assert after["status"] == "CANCELLED", after["status"]
