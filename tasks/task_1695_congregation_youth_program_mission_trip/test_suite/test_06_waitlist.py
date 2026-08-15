"""Waitlist: the capacity fork on review-APPROVE and the head-of-queue
promotion rule."""
from test_helpers import (
    ApiErrorId,
    create_submitted_registration,
    make_director_headers,
    make_guardian_headers,
    review_registration,
    set_clock,
    setup_program_with_open_trip,
    validate_error,
    validate_success,
)

DIRECTOR = make_director_headers()


class TestWaitlistForkAndHeadSelector:
    def test_waitlist_capacity_fork_and_head_selector(self, api):
        """PRD §3.3: "If `seats_taken` is below `capacity_youth`, the
        registration becomes `APPROVED` and `seats_taken` is recomputed; if the
        trip is full, the same approval forks the registration to `WAITLISTED` —
        a successful outcome, not an error."
        PRD §3.3: "the head of a trip's waitlist is the `WAITLISTED` registration
        with the earliest `created_at`, ties broken by the participant's
        `created_at` ascending; a registration `id` is never a tie-break input.
        Promotion from `WAITLISTED` to `APPROVED`, by a director or trip leader,
        requires the trip to be `REGISTRATION_OPEN`, at least one free seat
        (`seats_taken` below `capacity_youth`, else `ERR_NO_WAITLIST_CAPACITY`,
        HTTP 409), and the target to be the head of that order (else
        `ERR_WAITLIST_NOT_HEAD`, HTTP 409)."

        Design: Corner/state_machines/waitlist_capacity_fork_and_head_selector
        """
        program, trip = setup_program_with_open_trip(
            destination_type="IN_STATE", capacity_youth=1,
            base_cost_cents=100, deposit_cents=50, start_date="2027-06-15",
            end_date="2027-06-16", emergency_protocol_text="")

        # Stagger creation instants so created_at strictly orders the queue.
        set_clock("2026-08-01T01:00:00Z")
        _, reg1, _ = create_submitted_registration(
            trip["id"], "guardian-1",
            registration_overrides={"insurance_tier": "NONE"})
        r1 = review_registration(reg1["id"], "APPROVE")
        assert r1["registration_status"] == "APPROVED", "seat 1 of 1"

        set_clock("2026-08-01T02:00:00Z")
        _, reg2, _ = create_submitted_registration(
            trip["id"], "guardian-2",
            participant_overrides={"family_key": "fam-2",
                                   "first_name": "B", "last_name": "Two"},
            registration_overrides={"insurance_tier": "NONE"})
        r2 = review_registration(reg2["id"], "APPROVE")
        assert r2["registration_status"] == "WAITLISTED", (
            "full trip forks the approval to WAITLISTED (a success branch)")

        set_clock("2026-08-01T03:00:00Z")
        _, reg3, _ = create_submitted_registration(
            trip["id"], "guardian-3",
            participant_overrides={"family_key": "fam-3",
                                   "first_name": "C", "last_name": "Three"},
            registration_overrides={"insurance_tier": "NONE"})
        r3 = review_registration(reg3["id"], "APPROVE")
        assert r3["registration_status"] == "WAITLISTED"

        # Promotion while the trip is still full.
        e_full = api.promote_registration(reg2["id"], DIRECTOR)
        validate_error(e_full, ApiErrorId.ERR_NO_WAITLIST_CAPACITY, 409)

        # Free the seat, then promote out of order: reg3 is behind reg2.
        vacated = api.withdraw_registration(
            reg1["id"], make_guardian_headers("guardian-1"))
        validate_success(vacated, 200)
        e_head = api.promote_registration(reg3["id"], DIRECTOR)
        validate_error(e_head, ApiErrorId.ERR_WAITLIST_NOT_HEAD, 409)

        promoted = api.promote_registration(reg2["id"], DIRECTOR)
        assert validate_success(promoted, 200)["registration_status"] == \
            "APPROVED"
