"""Visit admission gates: duplicate visits, child age band, credit funding,
walk-in capacity, check-in window, grip-sock resolution, and the parallel
admission/payment dimensions (PRD §3.4, §3.5)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_DEFAULTS,
    set_clock, add_child, create_reservation,
    setup_reserved_visit, setup_guardian_with_child_and_waiver,
    create_plus_plan, check_in_visit, get_visit_fresh,
    guardian_headers,
)
from test_helpers import api_client


class TestDuplicateVisit:
    def test_duplicate_reservation_same_child_slot_rejected(self, api):
        """PRD §3.4: "no second visit may be created for the same child on the
        same slot while one already exists in `RESERVED` or `CHECKED_IN` — a
        violation is `ERR_DUPLICATE_VISIT` (HTTP 409)."

        Design: Corner/validations/duplicate_reservation_same_child_slot_rejected
        """
        ctx = setup_reserved_visit(email="gp2@x.com")
        res = api.create_visit(
            {"session_slot_id": ctx["slot"]["id"],
             "child_id": ctx["child"]["id"],
             "guardian_id": ctx["guardian"]["id"],
             "visit_type": "RESERVATION", "booked_duration_minutes": 60},
            ctx["g_headers"])
        validate_error(res, ApiErrorId.ERR_DUPLICATE_VISIT, expected_status=409)


class TestChildAgeGate:
    def test_visit_for_overaged_child_rejected(self, api):
        """PRD §3.1: "the child's age at any slot's date must fall between 1
        and 12 inclusive for a visit to be created on that slot; a child
        outside that band is rejected with `ERR_CHILD_AGE_OUT_OF_RANGE`
        (HTTP 422)."

        Born 2012-01-15, slot date 2026-06-06 -> age 14, outside the band.

        Design: Corner/validations/visit_for_overaged_child_rejected
        """
        ctx = setup_reserved_visit(email="gq2@x.com")
        teen = add_child(ctx["guardian"], full_name="Teen",
                         birth_date="2012-01-15")
        res = api.create_visit(
            {"session_slot_id": ctx["slot"]["id"], "child_id": teen["id"],
             "guardian_id": ctx["guardian"]["id"], "visit_type": "RESERVATION",
             "booked_duration_minutes": 60}, ctx["g_headers"])
        validate_error(res, ApiErrorId.ERR_CHILD_AGE_OUT_OF_RANGE,
                       expected_status=422)


class TestCreditFundingGates:
    def test_credit_reservation_without_membership_rejected(self, api):
        """PRD §3.4: "Setting `use_credit` true funds the visit from membership
        credits instead of money: it requires an `ACTIVE` membership (else
        `ERR_MEMBERSHIP_REQUIRED`, HTTP 422)".

        Design: Corner/validations/credit_reservation_without_membership_rejected
        """
        ctx = setup_reserved_visit(email="gv2@x.com")  # no membership
        child2 = add_child(ctx["guardian"], full_name="K2",
                           birth_date="2019-06-15")
        res = api.create_visit(
            {"session_slot_id": ctx["slot"]["id"], "child_id": child2["id"],
             "guardian_id": ctx["guardian"]["id"], "visit_type": "RESERVATION",
             "booked_duration_minutes": 60, "use_credit": True},
            ctx["g_headers"])
        validate_error(res, ApiErrorId.ERR_MEMBERSHIP_REQUIRED,
                       expected_status=422)


class TestWalkInCapacity:
    def test_walkin_at_full_capacity_returns_slot_at_capacity(self, api):
        """PRD §3.4: "the capacity gate: the sum of `reserved_count` and
        `checked_in_count` must be strictly below `capacity`, otherwise
        `ERR_SLOT_AT_CAPACITY` (HTTP 409)."

        Capacity 4: 2 RESERVED + 2 CHECKED_IN walk-ins fill the slot; the
        third walk-in at occupancy 4 >= 4 is rejected.

        Design: Corner/validations/walkin_at_full_capacity_returns_slot_at_capacity
        """
        ctx = setup_reserved_visit(capacity=4, email="gs2@x.com")
        guardian, slot, gh = ctx["guardian"], ctx["slot"], ctx["g_headers"]
        fd = ctx["fd_headers"]
        kids = [add_child(guardian, full_name=f"K{i}",
                          birth_date="2019-06-15") for i in range(2, 6)]
        create_reservation(guardian, slot, kids[0])  # reserved_count 2

        set_clock(TEST_DEFAULTS["CHECKIN_TIME"])
        for kid in kids[1:3]:  # two walk-ins admitted at the desk
            res = api.create_visit(
                {"session_slot_id": slot["id"], "child_id": kid["id"],
                 "guardian_id": guardian["id"], "visit_type": "WALK_IN",
                 "sock_method": "OWN_GRIP_SOCKS"}, fd)
            admitted = validate_success(res, 201)
            assert admitted["admission_status"] == "CHECKED_IN"

        res = api.create_visit(
            {"session_slot_id": slot["id"], "child_id": kids[3]["id"],
             "guardian_id": guardian["id"], "visit_type": "WALK_IN",
             "sock_method": "OWN_GRIP_SOCKS"}, fd)
        validate_error(res, ApiErrorId.ERR_SLOT_AT_CAPACITY, expected_status=409)


class TestCheckInWindow:
    def test_checkin_outside_window_rejected(self, api):
        """PRD §3.5: "The logical clock must sit inside the check-in window,
        from ten minutes before the slot's `start_at` through fifteen minutes
        after it, inclusive; outside that window the rejection is
        `ERR_CHECKIN_WINDOW_CLOSED` (HTTP 422)."

        At 13:00 for a 14:00 slot (window opens 13:50), check-in fails.

        Design: Corner/validations/checkin_outside_window_rejected
        """
        ctx = setup_reserved_visit(email="gr2@x.com")
        set_clock("2026-06-06T13:00:00Z")
        res = api.check_in_visit(ctx["visit"]["id"],
                                 {"sock_method": "OWN_GRIP_SOCKS"},
                                 ctx["fd_headers"])
        validate_error(res, ApiErrorId.ERR_CHECKIN_WINDOW_CLOSED,
                       expected_status=422)


class TestGripSocksGate:
    def test_grip_socks_membership_claim_without_plan_rejected(self, api):
        """PRD §3.5: "`MEMBERSHIP_PROVIDED` requires the guardian's membership
        to be `ACTIVE` on a plan whose `socks_included` is true". "An
        unresolvable declaration is rejected with `ERR_GRIP_SOCKS_REQUIRED`
        (HTTP 422)."

        Design: Corner/validations/grip_socks_membership_claim_without_plan_rejected
        """
        ctx = setup_reserved_visit(email="gu2@x.com")  # membership NONE
        set_clock(TEST_DEFAULTS["CHECKIN_TIME"])
        res = api.check_in_visit(ctx["visit"]["id"],
                                 {"sock_method": "MEMBERSHIP_PROVIDED"},
                                 ctx["fd_headers"])
        validate_error(res, ApiErrorId.ERR_GRIP_SOCKS_REQUIRED,
                       expected_status=422)


class TestParallelAdmissionPaymentDimensions:
    def test_pay_and_checkin_move_independent_dimensions(self, api):
        """PRD §3.4: "A reserved visit can be prepaid by the guardian or the
        desk, moving `payment_status` from `PENDING` to `PREPAID` and
        collecting the quoted amount."
        PRD §3.5: "Payment then reconciles along the visit's parallel
        `payment_status` dimension, which evolves independently of
        `admission_status`."

        Pay flips payment PENDING->PREPAID while admission stays RESERVED;
        check-in then flips admission RESERVED->CHECKED_IN while payment
        stays PREPAID.

        Design: Difficulty/non_linear_state_machine/visit_parallel_admission_payment_dimensions
        """
        ctx = setup_reserved_visit(email="g7@x.com")
        visit, gh, fd = ctx["visit"], ctx["g_headers"], ctx["fd_headers"]
        assert visit["admission_status"] == "RESERVED"
        assert visit["payment_status"] == "PENDING"

        paid = validate_success(api.pay_visit(visit["id"], gh), 200)
        assert paid["payment_status"] == "PREPAID"
        assert paid["admission_status"] == "RESERVED", \
            "paying must not move the admission dimension"

        set_clock(TEST_DEFAULTS["CHECKIN_TIME"])
        checked_in = check_in_visit(visit, fd)
        assert checked_in["admission_status"] == "CHECKED_IN"
        assert checked_in["payment_status"] == "PREPAID", \
            "check-in must not move the payment dimension"

    def test_credit_visit_stays_pending_until_checkout_settles(self, api):
        """PRD §3.4: "A reservation, typically placed by the guardian from
        home, requires `booked_duration_minutes` and starts life `RESERVED`
        with `payment_status` `PENDING`."
        PRD §3.5: "Credit visits skip money entirely: the held credit converts
        to consumed (the guardian's `credits_held` drops by one and
        `credits_consumed` rises by one), the monetary charge is waived, and
        the visit settles."

        A credit visit keeps payment_status PENDING through check-in and
        settles (SETTLED) at check-out without any monetary charge.

        Design: Difficulty/non_linear_state_machine/visit_parallel_admission_payment_dimensions
        """
        plan = create_plus_plan()
        ctx = setup_reserved_visit(plan=plan, use_credit=True, email="g7b@x.com")
        visit = ctx["visit"]
        assert visit["payment_status"] == "PENDING"

        set_clock(TEST_DEFAULTS["CHECKIN_TIME"])
        checked_in = check_in_visit(visit, ctx["fd_headers"],
                                    sock_method="MEMBERSHIP_PROVIDED")
        assert checked_in["admission_status"] == "CHECKED_IN"
        assert checked_in["payment_status"] == "PENDING"

        set_clock(TEST_DEFAULTS["CHECKOUT_TIME"])
        completed = validate_success(
            api.check_out_visit(checked_in["id"], ctx["fd_headers"]), 200)
        assert completed["admission_status"] == "COMPLETED"
        assert completed["payment_status"] == "SETTLED"


class TestManagerOverride:
    def test_manager_can_check_in_visit(self, api):
        """PRD §3.5: "Checking in a reserved visit — `FrontDesk`, with
        `Manager` override — moves `admission_status` from `RESERVED` to
        `CHECKED_IN`."
        PRD §2.1: "A `Manager` is a superset role and may perform every
        operation open to `FrontDesk` and `CafeStaff` in addition to
        manager-exclusive operations."

        Design: Corner/rbac/manager_can_check_in_visit
        """
        ctx = setup_reserved_visit(email="gac@x.com")
        set_clock(TEST_DEFAULTS["CHECKIN_TIME"])
        checked_in = validate_success(api.check_in_visit(
            ctx["visit"]["id"], {"sock_method": "OWN_GRIP_SOCKS"},
            ctx["mgr_headers"]), 200)
        assert checked_in["admission_status"] == "CHECKED_IN"
