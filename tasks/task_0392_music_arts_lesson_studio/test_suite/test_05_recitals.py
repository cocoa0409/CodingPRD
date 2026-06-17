"""Recital events, registration, the waitlist, capacity boundary, and the
withdraw -> promotion cascade.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    create_registration_payload,
    setup_recital_with_registrations,
)

ADMIN = TEST_USERS["studio_admin_headers"]


# ===========================================================================
# Difficulty / transitive_cascade / withdraw_frees_seat_promotes_waitlist
# ===========================================================================
class TestWithdrawPromotesWaitlist:
    def test_withdraw_confirmed_promotes_earliest_waitlisted(self, api):
        """PRD 3.9: "When the withdrawal frees a `CONFIRMED` seat and a `WAITLISTED`
        registration exists, the system promotes the earliest-waiting registration — the
        one earliest by `registered_utc` ascending, then `created_at` ascending — from
        `WAITLISTED → CONFIRMED`, provided the event's `confirmed_count` is below
        `venue_capacity` after the withdrawal."

        Design: Difficulty/transitive_cascade/withdraw_frees_seat_promotes_waitlist
        """
        studio, family, students, event, regs = setup_recital_with_registrations(
            venue_capacity=1, num_students=2, register_count=2
        )
        sid = studio["id"]
        reg1, reg2 = regs
        assert reg1["status"] == "CONFIRMED"
        assert reg2["status"] == "WAITLISTED"

        validate_success(api.withdraw_registration(sid, reg1["id"], ADMIN), 200)
        reg2_after = validate_success(api.get_registration(sid, reg2["id"], ADMIN), 200)
        assert reg2_after["status"] == "CONFIRMED"

    def test_withdraw_keeps_confirmed_count_at_capacity(self, api):
        """PRD 3.9: "Withdrawing a registration ... moves the registration to
        `WITHDRAWN` (terminal) and recomputes the event's `confirmed_count` and
        `waitlist_count`." PRD 3.9: "Promotion recomputes `confirmed_count`,
        `waitlist_count`, and the `performance_order` of the `CONFIRMED` registrations."

        Design: Difficulty/transitive_cascade/withdraw_frees_seat_promotes_waitlist
        """
        studio, family, students, event, regs = setup_recital_with_registrations(
            venue_capacity=1, num_students=2, register_count=2
        )
        sid = studio["id"]
        reg1, reg2 = regs
        validate_success(api.withdraw_registration(sid, reg1["id"], ADMIN), 200)
        ev_after = validate_success(api.get_recital_event(sid, event["id"], ADMIN), 200)
        assert ev_after["confirmed_count"] == 1
        assert ev_after["waitlist_count"] == 0
        reg1_after = validate_success(api.get_registration(sid, reg1["id"], ADMIN), 200)
        assert reg1_after["status"] == "WITHDRAWN"


# ===========================================================================
# Difficulty / boundary_precision_check / recital_capacity_nth_confirms_n_plus_1_waitlists
# ===========================================================================
class TestRecitalCapacityBoundary:
    def test_third_registration_waitlists_at_capacity_two(self, api):
        """PRD 3.9: "A new `RecitalRegistration` records its `registered_utc` from the
        studio clock and is created `CONFIRMED` when the event's `confirmed_count` is
        below `venue_capacity`, otherwise `WAITLISTED`."

        Design: Difficulty/boundary_precision_check/recital_capacity_nth_confirms_n_plus_1_waitlists
        """
        studio, family, students, event, regs = setup_recital_with_registrations(
            venue_capacity=2, num_students=3, register_count=2
        )
        sid = studio["id"]
        assert regs[1]["status"] == "CONFIRMED"  # 2nd confirms (count was 1 < 2)
        reg3 = validate_success(
            api.create_registration(
                sid, create_registration_payload(event["id"], students[2]["id"]), ADMIN
            ),
            201,
        )
        assert reg3["status"] == "WAITLISTED"  # count is 2, not < 2

    def test_counts_reflect_two_confirmed_one_waitlisted(self, api):
        """PRD 2.9: "A recital event's `confirmed_count` and `waitlist_count` always
        reflect the live number of its `CONFIRMED` and `WAITLISTED` registrations."

        Design: Difficulty/boundary_precision_check/recital_capacity_nth_confirms_n_plus_1_waitlists
        """
        studio, family, students, event, regs = setup_recital_with_registrations(
            venue_capacity=2, num_students=3, register_count=2
        )
        sid = studio["id"]
        validate_success(
            api.create_registration(
                sid, create_registration_payload(event["id"], students[2]["id"]), ADMIN
            ),
            201,
        )
        ev = validate_success(api.get_recital_event(sid, event["id"], ADMIN), 200)
        assert ev["confirmed_count"] == 2
        assert ev["waitlist_count"] == 1


# ===========================================================================
# Difficulty / cross_entity_state_dependency / register_requires_event_reg_open
# ===========================================================================
class TestRegisterRequiresRegOpen:
    def test_register_after_close_returns_registration_closed(self, api):
        """PRD 3.9: "Registration is accepted only while the event is `REG_OPEN` and the
        studio clock is before `registration_deadline_utc`, else `ERR_REGISTRATION_CLOSED`
        (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/register_requires_event_reg_open
        """
        studio, family, students, event, regs = setup_recital_with_registrations(
            venue_capacity=5, num_students=1, register_count=0
        )
        sid = studio["id"]
        validate_success(api.close_registration(sid, event["id"], ADMIN), 200)
        res = api.create_registration(
            sid, create_registration_payload(event["id"], students[0]["id"]), ADMIN
        )
        validate_error(res, "ERR_REGISTRATION_CLOSED", expected_status=409)

    def test_register_open_event_succeeds_then_closed_blocks(self, api):
        """PRD 3.9: "Closing registration is a `StudioAdmin` action that moves an event
        `REG_OPEN → REG_CLOSED`, accepts no further registrations". PRD 3.9:
        "Registration is accepted only while the event is `REG_OPEN` ... else
        `ERR_REGISTRATION_CLOSED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/register_requires_event_reg_open
        """
        studio, family, students, event, regs = setup_recital_with_registrations(
            venue_capacity=5, num_students=2, register_count=1
        )
        sid = studio["id"]
        assert regs[0]["status"] == "CONFIRMED"  # accepted while REG_OPEN
        validate_success(api.close_registration(sid, event["id"], ADMIN), 200)
        res = api.create_registration(
            sid, create_registration_payload(event["id"], students[1]["id"]), ADMIN
        )
        validate_error(res, "ERR_REGISTRATION_CLOSED", expected_status=409)


# ===========================================================================
# Corner / state_machines / recital_cancel_withdraws_all_registrations
# ===========================================================================
def test_recital_cancel_withdraws_all_registrations(api):
    """PRD 3.9: "Cancelling an event is permitted from either `REG_OPEN` or `REG_CLOSED`,
    else `ERR_INVALID_STATE`; it moves the event to `CANCELLED` (the branch that diverges
    from `COMPLETED`) and cascades every `CONFIRMED` and `WAITLISTED` registration to
    `WITHDRAWN`."

    Design: Corner/state_machines/recital_cancel_withdraws_all_registrations
    """
    studio, family, students, event, regs = setup_recital_with_registrations(
        venue_capacity=5, num_students=2, register_count=2
    )
    sid = studio["id"]
    cancelled = validate_success(api.cancel_recital_event(sid, event["id"], ADMIN), 200)
    assert cancelled["status"] == "CANCELLED"
    reg1_after = validate_success(api.get_registration(sid, regs[0]["id"], ADMIN), 200)
    assert reg1_after["status"] == "WITHDRAWN"


# ===========================================================================
# Corner / validations / duplicate_recital_registration_rejected
# ===========================================================================
def test_duplicate_recital_registration_rejected(api):
    """PRD 3.9: "A student may hold at most one non-`WITHDRAWN` `RecitalRegistration`
    per event; a second attempt is rejected with `ERR_DUPLICATE_REGISTRATION` (HTTP
    409)."

    Design: Corner/validations/duplicate_recital_registration_rejected
    """
    studio, family, students, event, regs = setup_recital_with_registrations(
        venue_capacity=5, num_students=1, register_count=1
    )
    sid = studio["id"]
    res = api.create_registration(
        sid, create_registration_payload(event["id"], students[0]["id"]), ADMIN
    )
    validate_error(res, "ERR_DUPLICATE_REGISTRATION", expected_status=409)
