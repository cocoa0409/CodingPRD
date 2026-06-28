"""Membership state machine: activate, freeze/reactivate cycle with credit
preservation, and the cancellation cascade that voids enrollments/credits/invoice.
"""
import pytest

from test_helpers import (
    validate_success, get_success_data, TEST_USERS, set_clock,
    setup_membership_with_credit, setup_billable_membership,
    create_program, create_room, create_instructor, create_session,
    create_active_membership, create_child, enroll_child, cancel_session,
    renew_membership,
)
from test_helpers import fixtures as fx

STAFF = TEST_USERS["front_desk_headers"]


def test_freeze_then_reactivate_returns_active_and_preserves_credits(api):
    """PRD §3.2: "A frozen membership suspends billing — any renew attempt while
    FROZEN is rejected — but preserves all of its makeup credits across the freeze."
    PRD §3.2: "Reactivating a FROZEN membership runs the same activate operation
    and returns it to ACTIVE, valid only from FROZEN in that path."

    A CORE membership holding one AVAILABLE credit, frozen then reactivated,
    returns to ACTIVE with makeup_credit_balance still 1.

    Design: Difficulty/non_linear_state_machine/membership_active_freeze_reactivate_cycle
    """
    set_clock("2026-05-01T00:00:00Z")
    # Mint one credit, then freeze + reactivate.
    program = create_program(level_index=0, tuition_cents=2500)
    room = create_room(physical_capacity=12)
    instructor = create_instructor(certified_level_indices=[0])
    session = create_session(program["id"], room["id"], instructor["id"], capacity=5)
    family, membership = create_active_membership(tier="CORE")
    child = create_child(family["id"], birth_date="2024-01-01")
    enroll_child(child["id"], session["id"], membership["id"], kind="RECURRING")
    cancel_session(session["id"])  # mints one AVAILABLE credit
    parent_headers = fx.make_parent_headers(family["id"])
    get_success_data(api.freeze_membership(membership["id"], parent_headers))
    reactivated = validate_success(api.activate_membership(membership["id"], parent_headers), 200)
    assert reactivated["status"] == "ACTIVE"
    assert reactivated["makeup_credit_balance"] == 1, (
        f"credit must survive the freeze, balance={reactivated['makeup_credit_balance']}"
    )


def test_freeze_reactivate_valid_transition_lands_active(api):
    """PRD §3.2: "Reactivating a FROZEN membership runs the same activate operation
    and returns it to ACTIVE, valid only from FROZEN in that path."

    Reactivation from FROZEN is a valid transition that lands the membership ACTIVE.

    Design: Difficulty/non_linear_state_machine/membership_active_freeze_reactivate_cycle
    """
    set_clock("2026-05-01T00:00:00Z")
    family, membership = create_active_membership(tier="PLUS")
    parent_headers = fx.make_parent_headers(family["id"])
    frozen = validate_success(api.freeze_membership(membership["id"], parent_headers), 200)
    assert frozen["status"] == "FROZEN"
    reactivated = validate_success(api.activate_membership(membership["id"], parent_headers), 200)
    assert reactivated["status"] == "ACTIVE"


def test_cancel_active_membership_cascades_to_enrollments_credits_invoice(api):
    """PRD §3.2: "Every AVAILABLE makeup credit on the membership transitions to
    EXPIRED and the membership's makeup_credit_balance is reconciled to 0."
    PRD §3.2: "From an ACTIVE membership, every ENROLLED or WAITLISTED enrollment
    billed to that membership is transitioned to CANCELLED"
    PRD §3.2: "The membership's current OPEN invoice, if any, is voided to VOID."

    Cancelling an ACTIVE membership that has one ENROLLED enrollment, one AVAILABLE
    credit, and one OPEN invoice: enrollment -> CANCELLED, balance -> 0, invoice -> VOID,
    membership -> CANCELLED.

    Design: Corner/cross_cutting_complexity_layers/membership_cancel_cascade_voids_enrollments_and_credits
    """
    set_clock("2026-05-01T00:00:00Z")
    program = create_program(level_index=0, tuition_cents=2500)
    room = create_room(physical_capacity=12)
    instructor = create_instructor(certified_level_indices=[0])
    sess_a = create_session(program["id"], room["id"], instructor["id"],
                            start_at="2026-05-10T09:00:00Z", end_at="2026-05-10T10:00:00Z", capacity=5)
    sess_b = create_session(program["id"], room["id"], instructor["id"],
                            start_at="2026-05-17T09:00:00Z", end_at="2026-05-17T10:00:00Z", capacity=5)
    family, membership = create_active_membership(tier="CORE")
    mem_id = membership["id"]
    child = create_child(family["id"], birth_date="2024-01-01")
    enroll_child(child["id"], sess_a["id"], mem_id, kind="RECURRING")
    cancel_session(sess_a["id"])  # mints one AVAILABLE credit, cancels enr_a
    enr_b = enroll_child(child["id"], sess_b["id"], mem_id, kind="RECURRING")
    set_clock("2026-06-01T00:00:00Z")
    invoice = validate_success(api.renew_membership(mem_id, STAFF), 201)
    # Cancel as the owning parent.
    parent_headers = fx.make_parent_headers(family["id"])
    cancelled = validate_success(api.cancel_membership(mem_id, parent_headers), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["makeup_credit_balance"] == 0
    enr_b_after = get_success_data(api.get_enrollment(enr_b["id"], STAFF))
    assert enr_b_after["status"] == "CANCELLED"
    invoice_after = get_success_data(api.get_invoice(invoice["id"], STAFF))
    assert invoice_after["status"] == "VOID"
