"""Check-in/check-out charging: provisional block quote vs final tiered
charge, terminal-state lockdown, no-show sweep, waiver-expiry gating, and
the state-beats-safety error precedence (PRD §2.8, §3.4, §3.5)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    get_success_data, ApiErrorId, TEST_DEFAULTS,
    set_clock, reset_clock, run_ops_as_admin,
    setup_reserved_visit, check_in_visit, get_visit_fresh,
    make_staff, staff_headers, create_slot, create_open_slot,
    register_guardian, guardian_headers, add_child, sign_waiver,
    create_reservation,
)
from test_helpers import api_client


class TestProvisionalVsFinalCharge:
    def test_prepaid_90_minute_quote_2100_final_1650(self, api):
        """PRD §3.4: "Its `quoted_cents` is a provisional block price: the
        booked minutes are divided into 60-minute blocks with any partial
        block counting as a whole one, and the quote is 1,200 cents for the
        first block plus 900 cents for each additional block — a 90-minute
        booking therefore quotes 2,100 cents."
        PRD §3.5: "A 90-minute stay therefore costs 1,650 cents, or 1,485
        cents for a member, and the result is recorded as
        `final_charge_cents`."
        PRD §3.5: "A `PREPAID` visit also settles to `SETTLED`, recording
        `refund_delta_cents` as the amount by which its `quoted_cents`
        exceeded the final charge".

        Design: Difficulty/dual_variant_calc/visit_charge_provisional_block_vs_final_tiered
        """
        ctx = setup_reserved_visit(booked_duration_minutes=90, email="g1@x.com")
        visit, gh, fd = ctx["visit"], ctx["g_headers"], ctx["fd_headers"]
        assert visit["quoted_cents"] == 2100  # PROVISIONAL: 1200 + 900

        validate_success(api.pay_visit(visit["id"], gh), 200)
        set_clock(TEST_DEFAULTS["CHECKIN_TIME"])          # 14:05
        check_in_visit(visit, fd)
        set_clock("2026-06-06T15:35:00Z")                 # 90 elapsed minutes
        out = validate_success(api.check_out_visit(visit["id"], fd), 200)

        assert out["final_charge_cents"] == 1650  # FINAL: 60*20 + 30*15
        assert out["refund_delta_cents"] == 450   # 2100 - 1650
        assert out["payment_status"] == "SETTLED"
        assert out["admission_status"] == "COMPLETED"

    def test_member_90_minute_final_charge_1485(self, api):
        """PRD §3.5: "when the guardian's membership is `ACTIVE`, the
        resulting amount is reduced by ten percent and rounded half-up. A
        90-minute stay therefore costs 1,650 cents, or 1,485 cents for a
        member".

        The provisional block quote (2,100) is undiscounted; the member
        discount applies only to the final tiered charge.

        Design: Difficulty/dual_variant_calc/visit_charge_provisional_block_vs_final_tiered
        """
        from test_helpers import create_plus_plan
        plan = create_plus_plan()
        ctx = setup_reserved_visit(plan=plan, booked_duration_minutes=90,
                                   email="g1m@x.com")
        visit, gh, fd = ctx["visit"], ctx["g_headers"], ctx["fd_headers"]
        assert visit["quoted_cents"] == 2100

        validate_success(api.pay_visit(visit["id"], gh), 200)
        set_clock(TEST_DEFAULTS["CHECKIN_TIME"])
        check_in_visit(visit, fd, sock_method="MEMBERSHIP_PROVIDED")
        set_clock("2026-06-06T15:35:00Z")
        out = validate_success(api.check_out_visit(visit["id"], fd), 200)

        assert out["final_charge_cents"] == 1485  # round_half_up(1650 * 0.9)
        assert out["refund_delta_cents"] == 615   # 2100 - 1485
        assert out["payment_status"] == "SETTLED"


class TestCompletedVisitTerminal:
    def test_checkout_of_completed_visit_rejected(self, api):
        """PRD §3.5: "Check-out — again `FrontDesk` with `Manager` override —
        moves the visit from `CHECKED_IN` to `COMPLETED`".
        PRD §2.8: "Fourth, state: the target resource must be in a valid
        from-state for the requested transition, yielding `ERR_INVALID_STATE`
        (HTTP 409)".

        COMPLETED is not a valid from-state for check-out; a second check-out
        fails and recomputes nothing.

        Design: Corner/state_machines/checkout_of_completed_visit_rejected
        """
        ctx = setup_reserved_visit(email="gj@x.com")
        visit, fd = ctx["visit"], ctx["fd_headers"]
        set_clock(TEST_DEFAULTS["CHECKIN_TIME"])          # 14:05
        check_in_visit(visit, fd)
        set_clock(TEST_DEFAULTS["CHECKOUT_TIME"])         # 15:00, 55 elapsed
        out = validate_success(api.check_out_visit(visit["id"], fd), 200)
        assert out["final_charge_cents"] == 1100          # 55 min * 20c

        res = api.check_out_visit(visit["id"], fd)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        fresh = get_visit_fresh(visit["id"], ctx["mgr_headers"])
        assert fresh["admission_status"] == "COMPLETED"
        assert fresh["final_charge_cents"] == 1100, "no recomputation on a rejected retry"


class TestNoShowSweep:
    def test_ops_run_marks_overdue_reserved_visit_no_show(self, api):
        """PRD §3.5: "A reservation that is never checked in does not linger:
        once the logical clock reaches fifteen minutes past the slot's
        `start_at`, the operations sweep marks it `NO_SHOW`." and "either way
        `reserved_count` drops by one."

        At 14:16 for a 14:00 slot (grace is start+15min), the sweep flips the
        visit to NO_SHOW and frees the reserved count.

        Design: Corner/state_machines/ops_run_marks_overdue_reserved_visit_no_show
        """
        ctx = setup_reserved_visit(email="gk@x.com")
        set_clock("2026-06-06T14:16:00Z")
        run_ops_as_admin()

        visit = get_visit_fresh(ctx["visit"]["id"], ctx["mgr_headers"])
        assert visit["admission_status"] == "NO_SHOW"
        slot = get_success_data(
            api.get_session_slot(ctx["slot"]["id"], ctx["mgr_headers"]))
        assert slot["reserved_count"] == 0


class TestCheckInResponseTimestamp:
    def test_checkin_response_sets_checked_in_at(self, api):
        """PRD §3.5: "A successful check-in stamps `checked_in_at`".
        PRD §2.4: "All system-stamped timestamps described in §3 (signing,
        check-in, check-out, completion, resolution) are taken from this
        logical clock."

        The check-in response itself carries checked_in_at equal to the
        logical clock.

        Design: Corner/endpoints/checkin_response_sets_checked_in_at
        """
        ctx = setup_reserved_visit(email="gaa@x.com")
        set_clock(TEST_DEFAULTS["CHECKIN_TIME"])  # 2026-06-06T14:05:00Z
        checked_in = check_in_visit(ctx["visit"], ctx["fd_headers"])
        assert checked_in["admission_status"] == "CHECKED_IN"
        assert checked_in["checked_in_at"].startswith("2026-06-06T14:05:00")


class TestCheckInGatedByWaiver:
    def test_expired_waiver_blocks_checkin(self, api):
        """PRD §3.1: "A waiver whose `expires_at` has been reached by the
        logical clock is flipped to `EXPIRED` by the operations sweep, after
        which check-in is refused until a fresh waiver is signed."
        PRD §3.5: "The guardian must hold a current waiver — one in `SIGNED`
        status whose `expires_at` is strictly in the future — otherwise
        `ERR_WAIVER_INVALID` (HTTP 422)."

        Waiver signed 2026-06-01 (expires 2027-06-01); slot 2027-06-10
        14:00-15:30; ops run at 13:55 flips the waiver EXPIRED while the
        check-in window and slot state are otherwise valid.

        Design: Difficulty/cross_entity_state_dependency/checkin_gated_by_waiver_state
        """
        reset_clock()
        mgr = make_staff("MANAGER", "Mgr One")
        fd = make_staff("FRONT_DESK", "FD One")
        mh, fh = staff_headers(mgr), staff_headers(fd)
        # Slot opened at setup: PRD §3.3 requires the target slot of a visit
        # creation to be OPEN ("The target slot must be `OPEN`").
        slot = create_open_slot(mh, slot_date="2027-06-10",
                                start_at="2027-06-10T14:00:00Z",
                                end_at="2027-06-10T15:30:00Z")
        guardian = register_guardian("G W", "gw@x.com", "404")
        gh = guardian_headers(guardian)
        child = add_child(guardian, birth_date="2020-01-15")
        waiver = sign_waiver(guardian)
        visit = create_reservation(guardian, slot, child)

        set_clock("2027-06-10T13:55:00Z")  # inside window [13:50, 14:15]
        run_ops_as_admin()  # waiver expires; visit not swept (no-show at 14:15)

        res = api.check_in_visit(visit["id"], {"sock_method": "OWN_GRIP_SOCKS"}, fh)
        validate_error(res, ApiErrorId.ERR_WAIVER_INVALID, expected_status=422)

        fresh = get_visit_fresh(visit["id"], mh)
        assert fresh["admission_status"] == "RESERVED"
        waivers = get_success_data(api.list_waivers(guardian["id"], gh))
        w = next(w for w in waivers if w["id"] == waiver["id"])
        assert w["status"] == "EXPIRED"

    def test_no_waiver_at_all_blocks_checkin(self, api):
        """PRD §3.5: "The guardian must hold a current waiver — one in
        `SIGNED` status whose `expires_at` is strictly in the future —
        otherwise `ERR_WAIVER_INVALID` (HTTP 422)."

        A guardian who never signed any waiver fails the same gate.

        Design: Difficulty/cross_entity_state_dependency/checkin_gated_by_waiver_state
        """
        reset_clock()
        mgr = make_staff("MANAGER", "Mgr One")
        fd = make_staff("FRONT_DESK", "FD One")
        mh, fh = staff_headers(mgr), staff_headers(fd)
        slot = create_open_slot(mh)
        guardian = register_guardian("G W2", "gw2b@x.com", "405")
        gh = guardian_headers(guardian)
        child = add_child(guardian, birth_date="2020-01-15")
        # No waiver signed at all; reservations are booked from home, before
        # the desk gates bite.
        visit = create_reservation(guardian, slot, child)

        set_clock(TEST_DEFAULTS["CHECKIN_TIME"])
        res = api.check_in_visit(visit["id"], {"sock_method": "OWN_GRIP_SOCKS"}, fh)
        validate_error(res, ApiErrorId.ERR_WAIVER_INVALID, expected_status=422)


class TestStateBeatsWaiverSafety:
    def test_cancelled_visit_checkin_reports_state_error(self, api):
        """PRD §2.8: "When several checks could reject the same request, they
        are evaluated in a fixed tier order, and the earliest failing tier
        determines the error."
        PRD §2.8: "Fourth, state: the target resource must be in a valid
        from-state for the requested transition, yielding `ERR_INVALID_STATE`
        (HTTP 409), with the slot-open gate for visit creation and check-in
        reported as `ERR_SLOT_NOT_OPEN` (HTTP 409)."
        PRD §2.8: "Fifth, business safety: waiver validity, grip-sock
        resolvability, child age, allergen intersection, lost-child gates,
        and child-reunion requirements."

        A check-in that would fail both the state tier (visit already
        CANCELLED; the sweep has also auto-closed the slot) and the safety
        tier (waiver EXPIRED) reports a state-tier error.

        Design: Difficulty/priority_pair_validation_conflict/checkin_state_beats_waiver_safety
        """
        ctx = setup_reserved_visit(email="g9@x.com")
        visit, fd = ctx["visit"], ctx["fd_headers"]
        # Staff cancel is unrestricted (no cutoff for staff).
        validate_success(api.cancel_visit(visit["id"], fd), 200)
        # Advance a year: the sweep expires the waiver and closes the slot.
        set_clock("2027-06-02T10:00:00Z")
        run_ops_as_admin()

        res = api.check_in_visit(visit["id"], {"sock_method": "OWN_GRIP_SOCKS"}, fd)
        # Both state-tier candidates beat the waiver safety tier; the PRD
        # fixes the tier order but not the order within the state tier.
        actual = validate_error_is_one_of(
            res, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_SLOT_NOT_OPEN])
        assert res.status_code == 409
        fresh = get_visit_fresh(visit["id"], ctx["mgr_headers"])
        assert fresh["admission_status"] == "CANCELLED"

    def test_cancelled_visit_checkin_on_open_slot_is_invalid_state(self, api):
        """PRD §2.8: "the earliest failing tier determines the error."
        PRD §2.8: "Fourth, state: the target resource must be in a valid
        from-state for the requested transition, yielding `ERR_INVALID_STATE`
        (HTTP 409)".
        PRD §3.5: "The guardian must hold a current waiver — one in `SIGNED`
        status whose `expires_at` is strictly in the future — otherwise
        `ERR_WAIVER_INVALID` (HTTP 422)."

        With the slot OPEN (state-tier slot gate passes) and the waiver
        EXPIRED (safety tier), a check-in against a CANCELLED visit reports
        ERR_INVALID_STATE: the state tier precedes business safety.

        Design: Difficulty/priority_pair_validation_conflict/checkin_state_beats_waiver_safety
        """
        reset_clock()
        mgr = make_staff("MANAGER", "Mgr One")
        fd = make_staff("FRONT_DESK", "FD One")
        mh, fh = staff_headers(mgr), staff_headers(fd)
        # Slot opened at setup: PRD §3.3 requires the target slot of a visit
        # creation to be OPEN ("The target slot must be `OPEN`").
        slot = create_open_slot(mh, slot_date="2027-06-10",
                                start_at="2027-06-10T14:00:00Z",
                                end_at="2027-06-10T15:30:00Z")
        guardian = register_guardian("G 9B", "g9b@x.com", "909")
        gh = guardian_headers(guardian)
        child = add_child(guardian, birth_date="2020-01-15")
        sign_waiver(guardian)  # expires 2027-06-01
        visit = create_reservation(guardian, slot, child)
        # Staff cancel while the visit is RESERVED.
        validate_success(api.cancel_visit(visit["id"], fh), 200)

        set_clock("2027-06-10T13:55:00Z")  # inside check-in window
        run_ops_as_admin()  # flips the waiver to EXPIRED

        res = api.check_in_visit(visit["id"], {"sock_method": "OWN_GRIP_SOCKS"}, fh)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        fresh = get_visit_fresh(visit["id"], mh)
        assert fresh["admission_status"] == "CANCELLED"
