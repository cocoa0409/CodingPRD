"""Priority preemption: victim selection and the all-or-nothing rule
(PRD §3.6)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    TEST_USERS, create_booking_payload,
    make_researcher_headers,
    setup_canonical_stack, setup_priority_user, approve_booking,
    create_booking_request, set_clock, get_booking, get_grant,
)

ADMIN = TEST_USERS["admin_headers"]
STAFF = TEST_USERS["staff_headers"]
FINANCE = TEST_USERS["finance_headers"]


def _priority_setup(api):
    """Canonical stack + a second INTERNAL user holding an ACTIVE
    priority-conveying STARTUP award. The PRIORITY booking is requested FIRST
    while the window is free; the STANDARD victim is approved afterwards
    (REQUESTED bookings never block, PRD §3.2)."""
    stack = setup_canonical_stack()
    prio = setup_priority_user(stack, stack["i1"]["id"])
    b3 = validate_success(
        api.create_booking(
            create_booking_payload(
                prio["u2"]["id"], stack["i1"]["id"], grant_id=prio["g2"]["id"],
                start_at="2026-09-01T10:00:00Z", end_at="2026-09-01T11:00:00Z",
                priority="PRIORITY",
            ),
            make_researcher_headers(prio["u2"]["id"]),
        ),
        201,
    )
    b1 = create_booking_request(stack)  # 2026-09-01 09:00-10:30 STANDARD
    b1 = approve_booking(b1["id"])
    return stack, prio, b1, b3


class TestPreemptionClearsVictims:
    def test_priority_preemption_clears_standard_victims(self, api):
        """PRD §3.6: "When a `PRIORITY` booking reaches approval and its window
        is occupied, the system selects victims: bookings on the same
        instrument in `APPROVED` status with `priority` `STANDARD` whose
        buffered half-open intervals overlap the incoming window. Victims are
        ranked most-recently-created first, with earlier `start_at` breaking
        ties." and "When the victim set fully clears the window, each victim
        transitions to `PREEMPTED` with `cancellation_reason` `PREEMPTION`,
        `penalty_waived` true, and `penalty_cents` zero, and each victim's
        grant encumbrance is released exactly as on a cancellation, with the
        victim grant's status recomputed."

        Design: Corner/state_machines/priority_preemption_clears_standard_victims
        """
        stack, prio, b1, b3 = _priority_setup(api)
        approved = validate_success(api.approve_booking(b3["id"], STAFF), 200)
        assert approved["status"] == "APPROVED"
        assert approved["estimated_charge_cents"] == 12000, (
            "60 min x 200 cents/min"
        )

        victim = get_booking(b1["id"])
        assert victim["status"] == "PREEMPTED"
        assert victim["cancellation_reason"] == "PREEMPTION"
        assert victim["penalty_waived"] is True
        assert victim["penalty_cents"] == 0

        g1 = get_grant(stack["g1"]["id"])
        assert g1["budget_encumbered_cents"] == 0, "victim encumbrance released"
        g2 = get_grant(prio["g2"]["id"])
        assert g2["budget_encumbered_cents"] == 12000, "winner encumbers its grant"


class TestPreemptionAllOrNothing:
    def test_priority_preemption_blocked_is_all_or_nothing(self, api):
        """PRD §3.6: "The selection is all-or-nothing: after bumping every
        eligible victim, if any overlapping booking remains — one already
        `IN_PROGRESS`, or an `APPROVED` booking that is itself `PRIORITY` —
        approval fails with `ERR_PREEMPTION_BLOCKED` and *no* victim is
        bumped."

        Design: Corner/state_machines/priority_preemption_blocked_is_all_or_nothing
        """
        stack = setup_canonical_stack()
        prio = setup_priority_user(stack, stack["i1"]["id"])
        b3 = validate_success(
            api.create_booking(
                create_booking_payload(
                    prio["u2"]["id"], stack["i1"]["id"], grant_id=prio["g2"]["id"],
                    start_at="2026-09-01T10:00:00Z", end_at="2026-09-01T11:00:00Z",
                    priority="PRIORITY",
                ),
                make_researcher_headers(prio["u2"]["id"]),
            ),
            201,
        )
        b1 = create_booking_request(stack)
        b1 = approve_booking(b1["id"])
        b4 = create_booking_request(
            stack, start_at="2026-09-01T11:00:00Z", end_at="2026-09-01T12:00:00Z"
        )
        b4 = approve_booking(b4["id"])
        set_clock("2026-09-01T08:55:00Z")
        validate_success(api.check_in_booking(b1["id"], STAFF), 200)

        res = api.approve_booking(b3["id"], STAFF)
        validate_error(res, "ERR_PREEMPTION_BLOCKED", expected_status=409)

        assert get_booking(b4["id"])["status"] == "APPROVED", (
            "no partial bumping: the eligible victim of the same window survives"
        )
        assert get_booking(b1["id"])["status"] == "IN_PROGRESS"
        assert get_booking(b3["id"])["status"] == "REQUESTED"
        g1 = get_grant(stack["g1"]["id"])
        assert g1["budget_encumbered_cents"] == 30000, (
            "no encumbrance moved: 18000 (b1) + 12000 (b4)"
        )
        g2 = get_grant(prio["g2"]["id"])
        assert g2["budget_encumbered_cents"] == 0
