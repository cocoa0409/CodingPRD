"""Workshop open guard and waitlist promotion cycle."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    set_clock, create_customer, create_workshop,
    setup_open_workshop_with_session, register_customer, make_customer_headers,
    get_success_data,
)
from test_helpers import TEST_USERS


def test_open_workshop_with_no_sessions_rejected(api):
    """PRD §3.6: "A workshop opens from DRAFT to OPEN, which requires at least one
    session to exist, otherwise ERR_NO_SESSIONS"

    Design: Corner/state_machines/open_workshop_with_no_sessions_rejected
    """
    workshop = create_workshop()
    resp = api.open_workshop(workshop["id"], TEST_USERS["store_manager_headers"])
    validate_error(resp, ApiErrorId.ERR_NO_SESSIONS)


def test_waitlisted_promoted_to_registered_on_cancel(api):
    """PRD §3.6: "If any waitlisted registrations remain for that session, the one
    with the smallest created_at is promoted from WAITLISTED to REGISTERED, its
    waitlist_rank is cleared, and registered_count is incremented back."

    Design: Difficulty/non_linear_state_machine/workshop_registration_cyclic_waitlist_promotion
    """
    set_clock("2026-05-01T00:00:00Z")
    c1 = create_customer()
    c2 = create_customer()
    workshop, session, _ = setup_open_workshop_with_session(
        "2026-08-01T10:00:00Z", "2026-08-01T12:00:00Z", capacity=1
    )
    reg1 = register_customer(workshop["id"], session["id"], c1["id"])
    reg2 = register_customer(workshop["id"], session["id"], c2["id"])
    assert reg1["status"] == "REGISTERED"
    assert reg2["status"] == "WAITLISTED"
    api.cancel_registration(reg1["id"], make_customer_headers(c1["id"]))
    resp = api.get_registration(reg2["id"], make_customer_headers(c2["id"]))
    data = validate_success(resp)
    assert data["status"] == "REGISTERED"


def test_waitlist_promotion_keeps_registered_count(api):
    """PRD §3.6: "It moves the registration to the terminal CANCELLED state and
    decrements the session's registered_count."

    Design: Difficulty/non_linear_state_machine/workshop_registration_cyclic_waitlist_promotion
    """
    set_clock("2026-05-01T00:00:00Z")
    c1 = create_customer()
    c2 = create_customer()
    workshop, session, _ = setup_open_workshop_with_session(
        "2026-08-01T10:00:00Z", "2026-08-01T12:00:00Z", capacity=1
    )
    reg1 = register_customer(workshop["id"], session["id"], c1["id"])
    register_customer(workshop["id"], session["id"], c2["id"])
    api.cancel_registration(reg1["id"], make_customer_headers(c1["id"]))
    resp = api.get_session(session["id"], TEST_USERS["store_manager_headers"])
    data = validate_success(resp)
    # one cancelled, one promoted -> registered_count back to 1.
    assert data["registered_count"] == 1
