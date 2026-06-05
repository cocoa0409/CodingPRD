"""Validation-precedence tests: where two guards both fail on one call, PRD §2.6
pins which error is reported. Each test cites the explicit PRD ordering.
"""
from test_helpers import (
    get_success_data, validate_error, ApiErrorId,
    make_customer_headers,
    create_active_plan, create_active_cleaner, create_suspended_cleaner,
    create_customer, create_address,
    setup_completed_booking,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ===========================================================================
# Queue A — Rule 5: priority_pair_validation_conflict
# ===========================================================================
def test_ownership_beats_safety_on_booking_create_with_suspended_pin(api):
    """PRD §2.6: "then ownership for entity-backed actors
    (`ERR_FORBIDDEN_OWNERSHIP`)... Only after these five gates pass does the
    server evaluate domain-specific business rules. Within the business tier the
    ordering, where multiple apply to the same call, runs: cleaner-cleared
    check..."
    PRD §2.1: "a customer acting on a booking, address, series, preferred-pro
    association, tip, or ledger entry that they do not own is rejected with
    `ERR_FORBIDDEN_OWNERSHIP`."

    Customer B creates a booking FOR Customer A (ownership violation) while ALSO
    pinning a SUSPENDED cleaner (safety violation); ownership (gate 4) precedes
    the business cleaner-cleared check, so ERR_FORBIDDEN_OWNERSHIP is returned.

    Design: Difficulty/priority_pair_validation_conflict/ownership_vs_safety_on_booking_create_with_suspended_pin
    """
    get_success_data(api.set_clock({"to_iso8601": "2026-06-01T00:00:00Z"}, ADMIN))
    plan = create_active_plan()
    cleaner = create_suspended_cleaner(service_postal_codes=["94110"])
    cust_a = create_customer()
    cust_b = create_customer()
    addr_a = create_address(cust_a["id"], postal_code="94110", home_size="STUDIO")
    # Customer B acts on Customer A's address/customer_id while pinning the suspended cleaner.
    validate_error(
        api.create_booking({
            "customer_id": cust_a["id"], "address_id": addr_a["id"],
            "pricing_plan_id": plan["id"], "scheduled_start": "2026-06-10T09:00:00Z",
            "cleaner_id": cleaner["id"],
        }, make_customer_headers(cust_b["id"])),
        ApiErrorId.ERR_FORBIDDEN_OWNERSHIP.value,
    )


def test_referential_beats_temporal_on_request_reclean(api):
    """PRD §2.6: "Within the business tier the ordering, where multiple apply to
    the same call, runs: cleaner-cleared check, reclean eligibility, reclean
    window..."
    PRD §3.7: "A request on an ineligible booking — one that is not completed, is
    itself a re-clean, or already has an open re-clean — is rejected with
    `ERR_RECLEAN_NOT_ELIGIBLE`, and a request that arrives after the 72-hour
    window has closed is rejected with `ERR_RECLEAN_WINDOW_CLOSED`."

    Requesting a reclean on an is_reclean booking that is ALSO past its 72h window
    violates both; reclean eligibility (earlier in the business tier) wins, so
    ERR_RECLEAN_NOT_ELIGIBLE is returned.

    Design: Difficulty/priority_pair_validation_conflict/referential_vs_temporal_on_request_reclean
    """
    # Build: complete original -> request -> schedule -> complete the reclean,
    # then advance the clock 100h past the reclean's completion (window closed
    # AND the target is itself an is_reclean booking).
    world = setup_completed_booking(
        home_size="STUDIO", add_ons=(), supplies_provided_by="CUSTOMER", rating=4,
        booking_start="2026-06-10T09:00:00Z", complete_clock="2026-06-10T11:00:00Z",
    )
    cust = world["customer"]
    cust_hdr = make_customer_headers(cust["id"])
    get_success_data(api.request_reclean(world["booking"]["id"], cust_hdr))
    spawned = get_success_data(
        api.schedule_reclean(world["booking"]["id"], {"scheduled_start": "2026-06-13T09:00:00Z"}, ADMIN)
    )
    # complete the reclean booking
    get_success_data(api.set_clock({"to_iso8601": "2026-06-13T11:00:00Z"}, ADMIN))
    from test_helpers import make_cleaner_headers
    cleaner_hdr = make_cleaner_headers(world["cleaner"]["id"])
    get_success_data(api.complete_booking(spawned["id"], {}, cleaner_hdr))
    # move 100h past the reclean's completion -> window closed
    get_success_data(api.set_clock({"to_iso8601": "2026-06-17T18:00:00Z"}, ADMIN))
    validate_error(
        api.request_reclean(spawned["id"], cust_hdr),
        ApiErrorId.ERR_RECLEAN_NOT_ELIGIBLE.value,
    )


def test_isolated_ownership_violation_on_booking_create(api):
    """PRD §2.1: "a customer acting on a booking, address, series, preferred-pro
    association, tip, or ledger entry that they do not own is rejected with
    `ERR_FORBIDDEN_OWNERSHIP`."

    Isolated ownership failure (a valid ACTIVE cleaner is available, so the safety
    check would pass): Customer B booking for Customer A is rejected with
    ERR_FORBIDDEN_OWNERSHIP, confirming gate-4 fires on its own.

    Design: Difficulty/priority_pair_validation_conflict/ownership_vs_safety_on_booking_create_with_suspended_pin
    """
    get_success_data(api.set_clock({"to_iso8601": "2026-06-01T00:00:00Z"}, ADMIN))
    plan = create_active_plan()
    create_active_cleaner(service_postal_codes=["94110"])  # eligible, so no safety failure
    cust_a = create_customer()
    cust_b = create_customer()
    addr_a = create_address(cust_a["id"], postal_code="94110", home_size="STUDIO")
    validate_error(
        api.create_booking({
            "customer_id": cust_a["id"], "address_id": addr_a["id"],
            "pricing_plan_id": plan["id"], "scheduled_start": "2026-06-10T09:00:00Z",
        }, make_customer_headers(cust_b["id"])),
        ApiErrorId.ERR_FORBIDDEN_OWNERSHIP.value,
    )


def test_isolated_reclean_window_closed_on_eligible_booking(api):
    """PRD §3.7: "a request that arrives after the 72-hour window has closed is
    rejected with `ERR_RECLEAN_WINDOW_CLOSED`."

    Isolated temporal failure (the booking is an eligible non-reclean COMPLETED
    booking, so eligibility passes): a request 100h after completion is rejected
    with ERR_RECLEAN_WINDOW_CLOSED, confirming the window check fires on its own —
    the loser that the combined conflict pre-empts.

    Design: Difficulty/priority_pair_validation_conflict/referential_vs_temporal_on_request_reclean
    """
    from test_helpers import make_cleaner_headers
    world = setup_completed_booking(
        home_size="STUDIO", add_ons=(), supplies_provided_by="CUSTOMER", rating=4,
        booking_start="2026-06-10T09:00:00Z", complete_clock="2026-06-10T11:00:00Z",
    )
    cust_hdr = make_customer_headers(world["customer"]["id"])
    # 100h past the 2026-06-10T11:00 completion -> window (72h) closed
    get_success_data(api.set_clock({"to_iso8601": "2026-06-14T15:00:00Z"}, ADMIN))
    validate_error(
        api.request_reclean(world["booking"]["id"], cust_hdr),
        ApiErrorId.ERR_RECLEAN_WINDOW_CLOSED.value,
    )


# ===========================================================================
# Queue B — Corner: validations (existence before state)
# ===========================================================================
def test_existence_before_state_on_cancel_unknown_booking(api):
    """PRD §2.5: "The first identifier that does not resolve to an existing
    resource causes the request to fail immediately with `ERR_NOT_FOUND`, before
    later identifiers or business checks are considered."
    PRD §2.6: "then existence of every referenced identifier (`ERR_NOT_FOUND`),
    ... then whether the target resource is in a state from which the requested
    transition is defined (`ERR_INVALID_STATE`)."

    Cancelling a non-existent booking id returns ERR_NOT_FOUND — the state check
    never runs.

    Design: Corner/validations/existence_before_state_on_cancel_unknown_booking
    """
    cust = create_customer()
    cust_hdr = make_customer_headers(cust["id"])
    validate_error(
        api.cancel_booking("00000000-0000-4000-8000-000000000abc", cust_hdr),
        ApiErrorId.ERR_NOT_FOUND.value,
    )
