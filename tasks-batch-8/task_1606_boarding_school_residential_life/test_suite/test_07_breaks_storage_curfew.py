"""Breaks, break housing, storage pricing/capacity, and curfew accounting."""
import pytest

from test_helpers import (
    TEST_USERS, api_client,
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    assert_break_housing_request, assert_storage_reservation, assert_storage_unit,
    assert_sign_event,
    create_storage_reservation_payload, create_break_housing_request_payload,
    create_sign_event_payload,
    make_student_headers, make_dean_headers, make_dorm_parent_headers,
    make_front_desk_headers,
    make_parent, make_student, make_dean, make_dorm_parent, make_front_desk,
    make_break_period, make_storage_unit, make_storage_reservation,
    make_break_housing_request, make_approved_guardian,
    setup_international_with_break_storage, setup_confirmed_residency,
    set_clock, get_student,
)


class TestStorageFeeRounding:
    def _setup_student_break_unit(self):
        parent = make_parent()
        student = make_student(parent["id"], grade=12, gender="MALE",
                               legal_name="Stu E")
        break_period = make_break_period()  # starts_on 2026-11-24
        unit = make_storage_unit(capacity_cuft=100)
        return student, break_period, unit

    def test_early_bird_line_fee_rounds_half_up(self, api):
        """PRD §3.8: "The base rate is 250 cents per cubic foot per week. A
        reservation created at least 30 days before its break's `starts_on` earns
        the `early_bird` flag and a fifteen-percent discount on the rate. The
        line fee is the volume multiplied by the weeks multiplied by the
        applicable rate, rounded half-up to whole cents per reservation line".

        Design: Difficulty/combinatorial_formula/storage_fee_per_line_rounding_then_sum
        """
        student, break_period, unit = self._setup_student_break_unit()
        # Default clock 2026-08-01 is well over 30 days before 2026-11-24.
        res1 = make_storage_reservation(unit["id"], break_period["id"],
                                        student["id"], volume_cuft=1, weeks=1,
                                        items_description="Skis")
        assert_storage_reservation(res1)
        assert res1["early_bird"] is True
        assert res1["fee_cents"] == 213  # round_half_up(1 * 1 * 250 * 0.85)

    def test_per_line_rounding_sums_to_426_not_425(self, api):
        """PRD §2.8: "Storage fees and break-housing charges round half-up to
        whole cents, and storage rounding happens per reservation line before any
        summation — the rejected alternative of summing-then-rounding produces a
        different total (two early-bird one-cubic-foot, one-week lines total 426
        cents when rounded per line, versus 425 cents if rounded only after
        aggregation)."

        Design: Difficulty/combinatorial_formula/storage_fee_per_line_rounding_then_sum
        """
        student, break_period, unit = self._setup_student_break_unit()
        res1 = make_storage_reservation(unit["id"], break_period["id"],
                                        student["id"], volume_cuft=1, weeks=1,
                                        items_description="Skis")
        res2 = make_storage_reservation(unit["id"], break_period["id"],
                                        student["id"], volume_cuft=1, weeks=1,
                                        items_description="Box of books")
        assert res1["fee_cents"] == 213
        assert res2["fee_cents"] == 213
        # Per-line order totals 426; sum-then-round would give 425.
        assert res1["fee_cents"] + res2["fee_cents"] == 426


class TestBreakHousingPinnedOrder:
    def _setup_two_line_break_housing(self):
        ctx = setup_international_with_break_storage(num_reservations=2,
                                                     volume_cuft=1, weeks=1)
        bhr = make_break_housing_request(ctx["student"]["id"],
                                         ctx["break_period"]["id"],
                                         reason="Cannot fly home")
        ctx["bhr"] = bhr
        return ctx

    def test_room_charge_and_storage_total_on_approval(self, api):
        """PRD §3.8: "Approval — allowed while the break is `UPCOMING` or
        `ACTIVE` — moves it to `APPROVED` and computes the full fee breakdown in
        a pinned evaluation order, so that no figure depends on a later one:
        1. `room_charge_cents` is a flat 20000 cents.
        2. `storage_total_cents` sums the `fee_cents` of the student's storage
        reservations for the same break whose status is `RESERVED`, `CHECKED_IN`,
        or `EXPIRED`".

        Design: Difficulty/combinatorial_formula/break_housing_total_pinned_evaluation_order
        """
        ctx = self._setup_two_line_break_housing()
        decided = validate_success(api.decide_break_housing(
            ctx["bhr"]["id"], "APPROVE", make_dean_headers(ctx["dean"]["id"])), 200)
        assert_break_housing_request(decided)
        assert decided["status"] == "APPROVED"
        assert decided["room_charge_cents"] == 20000
        assert decided["storage_total_cents"] == 426  # two 213-cent lines

    def test_deposit_credit_and_fee_follow_pinned_order(self, api):
        """PRD §3.8: "3. `deposit_credit_cents` is ten percent of the sum of the
        room charge and the storage total, rounded half-up to whole cents, and
        capped at 5000 cents.
        4. `fee_cents` is the room charge plus the storage total minus the
        deposit credit."

        Design: Difficulty/combinatorial_formula/break_housing_total_pinned_evaluation_order
        """
        ctx = self._setup_two_line_break_housing()
        decided = validate_success(api.decide_break_housing(
            ctx["bhr"]["id"], "APPROVE", make_dean_headers(ctx["dean"]["id"])), 200)
        # min(5000, round_half_up(0.10 * (20000 + 426))) = 2043
        assert decided["deposit_credit_cents"] == 2043
        assert decided["fee_cents"] == 20000 + 426 - 2043  # 18383


class TestStorageCapacityBoundary:
    def _setup_unit_capacity_ten(self):
        parent = make_parent()
        student = make_student(parent["id"], grade=11, gender="FEMALE",
                               legal_name="Stu S")
        break_period = make_break_period()
        unit = make_storage_unit(label="UNIT-C", capacity_cuft=10)
        make_storage_reservation(unit["id"], break_period["id"], student["id"],
                                 volume_cuft=6, weeks=1, items_description="Trunk")
        return student, break_period, unit

    def test_reservation_reaching_exact_capacity_accepted(self, api, admin_headers):
        """PRD §3.8: "Aggregate capacity is enforced per unit and break: the sum
        of `volume_cuft` over that unit's reservations for the same break in
        `RESERVED` or `CHECKED_IN` status, plus the new volume, must not exceed
        `capacity_cuft` (`ERR_STORAGE_CAPACITY_EXCEEDED`). The unit's `used_cuft`
        tracks exactly that sum."

        Design: Difficulty/resource_temporal_overlap/storage_aggregate_capacity_boundary
        """
        student, break_period, unit = self._setup_unit_capacity_ten()
        # Default clock is >= 30 days before the break, so the early-bird rate
        # applies: round_half_up(4 * 1 * 250 * 0.85) = 850.
        res2 = make_storage_reservation(unit["id"], break_period["id"],
                                        student["id"], volume_cuft=4, weeks=1,
                                        items_description="Bike box")
        assert res2["fee_cents"] == 850

        fetched = validate_success(api.get_storage_unit(unit["id"], admin_headers), 200)
        assert fetched["used_cuft"] == 10

    def test_one_cubic_foot_over_capacity_rejected(self, api):
        """PRD §3.8: "the sum of `volume_cuft` over that unit's reservations for
        the same break in `RESERVED` or `CHECKED_IN` status, plus the new volume,
        must not exceed `capacity_cuft` (`ERR_STORAGE_CAPACITY_EXCEEDED`)".

        Design: Difficulty/resource_temporal_overlap/storage_aggregate_capacity_boundary
        """
        student, break_period, unit = self._setup_unit_capacity_ten()
        make_storage_reservation(unit["id"], break_period["id"], student["id"],
                                 volume_cuft=4, weeks=1, items_description="Bike box")
        res = api.create_storage_reservation(
            create_storage_reservation_payload(unit["id"], break_period["id"],
                                               volume_cuft=1, weeks=1,
                                               items_description="Duffel"),
            make_student_headers(student["id"]))
        validate_error(res, ApiErrorId.ERR_STORAGE_CAPACITY_EXCEEDED)


class TestEarlyBirdCutoff:
    def test_early_bird_boundary_inclusive_at_thirty_days(self, api):
        """PRD §3.8: "A reservation created at least 30 days before its break's
        `starts_on` earns the `early_bird` flag and a fifteen-percent discount on
        the rate."

        Design: Corner/calculations/storage_early_bird_cutoff
        """
        parent = make_parent()
        student = make_student(parent["id"], grade=11, gender="FEMALE",
                               legal_name="Stu X")
        break_period = make_break_period()  # starts_on 2026-11-24
        unit = make_storage_unit(label="UNIT-D", capacity_cuft=100)

        # 2026-10-25T00:00:00Z is exactly 30 days before 2026-11-24.
        set_clock("2026-10-25T00:00:00Z")
        res_a = make_storage_reservation(unit["id"], break_period["id"],
                                         student["id"], volume_cuft=1, weeks=1,
                                         items_description="Box A")
        assert res_a["early_bird"] is True
        assert res_a["fee_cents"] == 213

        # One day later the window has closed.
        set_clock("2026-10-26T00:00:00Z")
        res_b = make_storage_reservation(unit["id"], break_period["id"],
                                         student["id"], volume_cuft=1, weeks=1,
                                         items_description="Box B")
        assert res_b["early_bird"] is False
        assert res_b["fee_cents"] == 250


class TestCurfewLateness:
    def test_curfew_tier_boundaries_on_weekday_nights(self, api):
        """PRD §3.9: "The applicable curfew is the dorm's `curfew_weekend` when
        the event falls on a Friday or Saturday, and `curfew_weekday` otherwise.
        The `minutes_late` on the event is the whole minutes by which
        `occurred_at` passed that same-day curfew, never below zero, and always 0
        for a sign-out. Late points then ladder into the student's official
        demerit total on the same schedule as leave returns: 0 points when on
        time, 1 point for 1 through 15 minutes late, 2 for 16 through 60, and 3
        beyond 60 — after which standing re-evaluation runs".

        Design: Corner/calculations/curfew_points_late_tiers
        """
        from test_helpers import make_dorm, make_room, make_active_term, \
            propose_assignment, confirm_assignment
        dorm = make_dorm(name="Winslow House", curfew_weekday="22:30",
                         curfew_weekend="23:30")
        room = make_room(dorm["id"], room_number="W-101", beds=2)
        term = make_active_term()
        stu_a = make_student(make_parent()["id"], grade=10, gender="MALE",
                             legal_name="Stu S")
        stu_b = make_student(make_parent()["id"], grade=10, gender="FEMALE",
                             legal_name="Stu T")
        confirm_assignment(propose_assignment(stu_a["id"], room["id"], term["id"])["id"])
        confirm_assignment(propose_assignment(stu_b["id"], room["id"], term["id"])["id"])
        fd = make_front_desk("FD One")

        # 2026-09-07 is a Monday, 2026-09-08 a Tuesday: weekday curfew 22:30.
        ev0 = validate_success(api.create_sign_event(
            create_sign_event_payload(stu_a["id"], "SIGN_IN",
                                      occurred_at="2026-09-07T22:30:00Z"),
            make_front_desk_headers(fd["id"])), 201)
        assert_sign_event(ev0)
        assert ev0["minutes_late"] == 0  # exactly at curfew is not late

        ev1 = validate_success(api.create_sign_event(
            create_sign_event_payload(stu_a["id"], "SIGN_IN",
                                      occurred_at="2026-09-08T22:45:00Z"),
            make_front_desk_headers(fd["id"])), 201)
        assert ev1["minutes_late"] == 15  # top of the 1-point tier

        ev2 = validate_success(api.create_sign_event(
            create_sign_event_payload(stu_b["id"], "SIGN_IN",
                                      occurred_at="2026-09-08T22:46:00Z"),
            make_front_desk_headers(fd["id"])), 201)
        assert ev2["minutes_late"] == 16  # first minute of the 2-point tier

        assert get_student(stu_a["id"])["demerit_points"] == 1
        assert get_student(stu_b["id"])["demerit_points"] == 2


class TestBreakHousingRules:
    def test_checkin_before_break_active_rejected(self, api):
        """PRD §3.8: "Check-in to break housing is a dorm-parent action allowed
        only while the break is `ACTIVE` (`ERR_BREAK_NOT_ACTIVE`)".

        Design: Corner/state_machines/break_housing_checkin_before_break_active_returns_error
        """
        guardian = make_approved_guardian(max_wards=5)
        parent = make_parent()
        student = make_student(parent["id"], grade=11, gender="FEMALE",
                               is_international=True, guardian_id=guardian["id"],
                               legal_name="Stu L")
        dean = make_dean("Dean One")
        dp = make_dorm_parent()
        break_period = make_break_period()  # stays UPCOMING at the default clock
        bhr = make_break_housing_request(student["id"], break_period["id"],
                                         reason="Visa travel delay")
        validate_success(api.decide_break_housing(bhr["id"], "APPROVE",
                                                  make_dean_headers(dean["id"])), 200)

        res = api.break_housing_check_in(bhr["id"], make_dorm_parent_headers(dp["id"]))
        validate_error(res, ApiErrorId.ERR_BREAK_NOT_ACTIVE)

    def test_duplicate_break_request_rejected(self, api):
        """PRD §3.8: "one non-terminal request per student per break is the limit
        (`ERR_DUPLICATE_BREAK_REQUEST`)".

        Design: Corner/validations/duplicate_break_request_rejected
        """
        guardian = make_approved_guardian(max_wards=5)
        parent = make_parent()
        student = make_student(parent["id"], grade=11, gender="FEMALE",
                               is_international=True, guardian_id=guardian["id"],
                               legal_name="Stu T")
        break_period = make_break_period()
        make_break_housing_request(student["id"], break_period["id"],
                                   reason="Long flight")

        res = api.create_break_housing_request(
            create_break_housing_request_payload(break_period["id"],
                                                 reason="Duplicate filing"),
            make_student_headers(student["id"]))
        validate_error(res, ApiErrorId.ERR_DUPLICATE_BREAK_REQUEST)

    def test_domestic_student_break_housing_rejected(self, api):
        """PRD §3.8: "Break housing exists for international students only — a
        domestic student's request is rejected with
        `ERR_NOT_ELIGIBLE_BREAK_HOUSING`."

        Design: Corner/validations/domestic_student_break_housing_rejected
        """
        parent = make_parent()
        student = make_student(parent["id"], grade=10, gender="MALE",
                               legal_name="Stu U")
        break_period = make_break_period()

        res = api.create_break_housing_request(
            {"break_period_id": break_period["id"]},
            make_student_headers(student["id"]))
        validate_error(res, ApiErrorId.ERR_NOT_ELIGIBLE_BREAK_HOUSING)
