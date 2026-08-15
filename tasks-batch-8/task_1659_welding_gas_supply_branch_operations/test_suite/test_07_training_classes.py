"""Training classes: capacity boundary, enrollment lifecycle, class cascade,
room overlap, and attendance timing."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    get_class,
    get_enrollment,
    make_customer,
    make_enrollment,
    make_training_class,
    set_clock,
    validate_error,
    validate_success,
)

TRAINER_HEADERS = TEST_USERS["trainer_headers"]


class TestClassCapacityBoundary:
    def _cap2_class(self):
        customer = make_customer(account_no="ACC-BP2", name="Seats Co",
                                 terms="CASH")
        klass = make_training_class(
            title="Plasma Cutting Safety", room="ROOM_B",
            start_at="2026-09-05T09:00:00Z", end_at="2026-09-05T10:00:00Z",
            capacity=2, price_cents=9000)
        return customer, klass

    def test_enrollments_fill_to_exact_capacity(self, api,
                                                counter_rep_headers):
        """PRD §3.8: "Capacity is hard: `seats_booked` counts the enrollments
        in `ENROLLED`, `ATTENDED`, or `NO_SHOW` status, and when that count
        already equals the class's `capacity` the class is full and further
        enrollments are rejected with `ERR_CLASS_FULL`." seats 0 -> 1 -> 2:
        the second enrollment succeeds because the count equals capacity only
        after it lands.

        Design: Difficulty/boundary_precision_check/class_capacity_exact_fill_then_full
        """
        customer, klass = self._cap2_class()
        for name in ("A One", "A Two"):
            resp = api.create_enrollment(
                {"class_id": klass["id"], "customer_id": customer["id"],
                 "attendee_name": name}, counter_rep_headers)
            validate_success(resp, 201)
        assert get_class(klass["id"])["seats_booked"] == 2

    def test_enrollment_past_capacity_rejected(self, api, counter_rep_headers):
        """PRD §3.8: "Capacity is hard: `seats_booked` counts the enrollments
        in `ENROLLED`, `ATTENDED`, or `NO_SHOW` status, and when that count
        already equals the class's `capacity` the class is full and further
        enrollments are rejected with `ERR_CLASS_FULL`." At seats_booked 2 ==
        capacity 2 the third enrollment fails.

        Design: Difficulty/boundary_precision_check/class_capacity_exact_fill_then_full
        """
        customer, klass = self._cap2_class()
        for name in ("A One", "A Two"):
            resp = api.create_enrollment(
                {"class_id": klass["id"], "customer_id": customer["id"],
                 "attendee_name": name}, counter_rep_headers)
            validate_success(resp, 201)
        third = api.create_enrollment(
            {"class_id": klass["id"], "customer_id": customer["id"],
             "attendee_name": "A Three"}, counter_rep_headers)
        validate_error(third, ApiErrorId.ERR_CLASS_FULL)


class TestReferentialBeatsConstraintOnEnrollment:
    def _cancelled_full_class(self):
        """Cap-1 class whose only enrollment is NO_SHOW (seat stays
        consumed), then the class is cancelled — the cascade touches only
        ENROLLED enrollments, so seats_booked remains 1 == capacity."""
        c1 = make_customer(account_no="ACC-PP2", name="First Co", terms="CASH")
        c2 = make_customer(account_no="ACC-PP3", name="Second Co",
                           terms="CASH")
        klass = make_training_class(
            title="Oxy-Fuel Safety", room="ROOM_A",
            start_at="2026-09-01T09:00:00Z", end_at="2026-09-01T11:00:00Z",
            capacity=1, price_cents=15000)
        enrollment = make_enrollment(klass["id"], c1["id"], attendee_name="Al")
        set_clock("2026-09-01T10:00:00Z")
        return c1, c2, klass, enrollment

    def test_cancelled_full_class_reports_not_scheduled(self, api,
                                                        trainer_headers):
        """PRD §2.8: "A single request can violate several rules at once, so
        the API evaluates its checks as an ordered cascade of gates and
        reports the first gate that fails. The order below is normative:" —
        gate "8. **Linked-entity state.**" ("the class is `SCHEDULED` for
        enrollment creation and attendance marking
        (`ERR_CLASS_NOT_SCHEDULED`)") precedes gate "10. **Uniqueness and
        capacity.**" ("the class has seats (`ERR_CLASS_FULL`)"). PRD §3.8:
        "Advancing to `NO_SHOW` requires only that the class still be
        `SCHEDULED`, and the seat remains consumed", so the cancelled class is
        both non-SCHEDULED and full at once.

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_constraint_on_enrollment
        """
        _c1, c2, klass, enrollment = self._cancelled_full_class()
        validate_success(api.advance_enrollment(enrollment["id"],
                                                {"to": "NO_SHOW"},
                                                TRAINER_HEADERS))
        validate_success(api.advance_training_class(klass["id"],
                                                    {"to": "CANCELLED"},
                                                    TRAINER_HEADERS))
        assert get_class(klass["id"])["seats_booked"] == 1, \
            "NO_SHOW keeps its seat even through class cancellation"
        resp = api.create_enrollment(
            {"class_id": klass["id"], "customer_id": c2["id"],
             "attendee_name": "Bo"}, trainer_headers)
        validate_error(resp, ApiErrorId.ERR_CLASS_NOT_SCHEDULED)

    def test_each_gate_fires_in_isolation(self, api, trainer_headers):
        """PRD §3.8: "The class must still be `SCHEDULED`
        (`ERR_CLASS_NOT_SCHEDULED`)" fires alone when seats are free, and
        "when that count already equals the class's `capacity` the class is
        full and further enrollments are rejected with `ERR_CLASS_FULL`" fires
        alone while the class is SCHEDULED — the two isolated outcomes the
        ordered cascade of §2.8 compresses when both fail at once.

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_constraint_on_enrollment
        """
        customer = make_customer(account_no="ACC-PP2B", name="Iso Co",
                                 terms="CASH")
        # Referential leg alone: cancelled class with every seat free.
        cancelled = make_training_class(
            title="Cancelled Class", room="ROOM_A",
            start_at="2026-09-02T09:00:00Z", end_at="2026-09-02T10:00:00Z",
            capacity=3, price_cents=1000)
        validate_success(api.advance_training_class(cancelled["id"],
                                                    {"to": "CANCELLED"},
                                                    trainer_headers))
        resp = api.create_enrollment(
            {"class_id": cancelled["id"], "customer_id": customer["id"],
             "attendee_name": "Solo"}, trainer_headers)
        validate_error(resp, ApiErrorId.ERR_CLASS_NOT_SCHEDULED)
        # Capacity leg alone: SCHEDULED class already full.
        full = make_training_class(
            title="Full Class", room="ROOM_B",
            start_at="2026-09-03T09:00:00Z", end_at="2026-09-03T10:00:00Z",
            capacity=1, price_cents=1000)
        make_enrollment(full["id"], customer["id"], attendee_name="First")
        other = make_customer(account_no="ACC-PP2C", name="Other Co",
                              terms="CASH")
        resp2 = api.create_enrollment(
            {"class_id": full["id"], "customer_id": other["id"],
             "attendee_name": "Second"}, trainer_headers)
        validate_error(resp2, ApiErrorId.ERR_CLASS_FULL)


class TestEnrollmentLifecycle:
    def test_enrollment_cancel_frees_seat(self, api, counter_rep_headers,
                                          trainer_headers):
        """PRD §3.8: "Advancing to `CANCELLED` frees the seat, since cancelled
        enrollments no longer count toward `seats_booked`." and "Duplicates
        are rejected too — a second enrollment with the same class, paying
        customer, and attendee name in any non-`CANCELLED` status fails with
        `ERR_DUPLICATE_ENROLLMENT`" — so the same attendee may re-enroll once
        the first enrollment is cancelled.

        Design: Corner/state_machines/enrollment_cancel_frees_seat
        """
        customer = make_customer(account_no="ACC-SM7", name="Seat Co",
                                 terms="CASH")
        klass = make_training_class(
            title="CGA Fittings", room="ROOM_A",
            start_at="2026-09-10T09:00:00Z", end_at="2026-09-10T10:00:00Z",
            capacity=1, price_cents=5000)
        first = make_enrollment(klass["id"], customer["id"],
                                attendee_name="Sam")
        validate_success(api.advance_enrollment(first["id"],
                                                {"to": "CANCELLED"},
                                                counter_rep_headers))
        resp = api.create_enrollment(
            {"class_id": klass["id"], "customer_id": customer["id"],
             "attendee_name": "Sam"}, trainer_headers)
        validate_success(resp, 201)
        assert get_class(klass["id"])["seats_booked"] == 1, \
            "only the live enrollment counts"

    def test_class_cancel_cascades_enrolled_enrollments(self, api,
                                                        trainer_headers):
        """PRD §3.8: "Advancing to `CANCELLED` cancels the class and cascades
        downward: every enrollment still in `ENROLLED` status is moved to
        `CANCELLED`, while enrollments already marked `ATTENDED` or `NO_SHOW`
        are untouched, and `seats_booked` is recomputed."

        Design: Corner/state_machines/class_cancel_cascades_enrolled_enrollments
        """
        customer = make_customer(account_no="ACC-SM8", name="Class Co",
                                 terms="CASH")
        klass = make_training_class(
            title="Torch Safety", room="ROOM_B",
            start_at="2026-09-12T09:00:00Z", end_at="2026-09-12T11:00:00Z",
            capacity=3, price_cents=7000)
        e1 = make_enrollment(klass["id"], customer["id"],
                             attendee_name="P One")
        e2 = make_enrollment(klass["id"], customer["id"],
                             attendee_name="P Two")
        cancelled = validate_success(api.advance_training_class(
            klass["id"], {"to": "CANCELLED"}, trainer_headers))
        assert cancelled["status"] == "CANCELLED"
        assert get_enrollment(e1["id"])["status"] == "CANCELLED"
        assert get_enrollment(e2["id"])["status"] == "CANCELLED"
        assert get_class(klass["id"])["seats_booked"] == 0

    def test_duplicate_enrollment_rejected(self, api, trainer_headers):
        """PRD §3.8: "Duplicates are rejected too — a second enrollment with
        the same class, paying customer, and attendee name in any
        non-`CANCELLED` status fails with `ERR_DUPLICATE_ENROLLMENT`."

        Design: Corner/validations/duplicate_enrollment_rejected
        """
        customer = make_customer(account_no="ACC-VA8", name="Dup Co",
                                 terms="CASH")
        klass = make_training_class(
            title="Grinder Safety", room="ROOM_B",
            start_at="2026-09-15T09:00:00Z", end_at="2026-09-15T10:00:00Z",
            capacity=5, price_cents=4000)
        payload = {"class_id": klass["id"], "customer_id": customer["id"],
                   "attendee_name": "Kit"}
        validate_success(api.create_enrollment(payload, trainer_headers), 201)
        resp = api.create_enrollment(dict(payload), trainer_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENROLLMENT)

    def test_attendance_before_class_start_rejected(self, api,
                                                    trainer_headers):
        """PRD §3.8: "Advancing to `ATTENDED` requires the class to be
        `SCHEDULED` (`ERR_CLASS_NOT_SCHEDULED`) and the logical clock to be at
        or after the class's `start_at` (`ERR_CLASS_NOT_STARTED`)".

        Design: Corner/validations/attendance_before_class_start_rejected
        """
        customer = make_customer(account_no="ACC-VA16", name="Early Co",
                                 terms="CASH")
        klass = make_training_class(
            title="MIG Basics", room="ROOM_A",
            start_at="2026-09-20T09:00:00Z", end_at="2026-09-20T12:00:00Z",
            capacity=4, price_cents=12000)
        enrollment = make_enrollment(klass["id"], customer["id"],
                                     attendee_name="Early Bird")
        set_clock("2026-09-20T08:00:00Z")
        resp = api.advance_enrollment(enrollment["id"], {"to": "ATTENDED"},
                                      trainer_headers)
        validate_error(resp, ApiErrorId.ERR_CLASS_NOT_STARTED)


class TestRoomBookingWindows:
    def test_adjacent_and_other_room_classes_allowed(self, api,
                                                     trainer_headers):
        """PRD §3.8: "One room cannot hold two overlapping scheduled classes:
        a new class whose half-open window from `start_at` (inclusive) to
        `end_at` (exclusive) overlaps another `SCHEDULED` class in the same
        room is rejected with `ERR_ROOM_DOUBLE_BOOKED`, while a class that
        begins exactly when another ends is allowed."

        Design: Difficulty/resource_temporal_overlap/room_halfopen_interval_adjacency
        """
        validate_success(api.create_training_class(
            {"title": "A", "room": "ROOM_A",
             "start_at": "2026-09-01T09:00:00Z",
             "end_at": "2026-09-01T11:00:00Z", "capacity": 5,
             "price_cents": 1000}, trainer_headers), 201)
        adjacent = api.create_training_class(
            {"title": "B", "room": "ROOM_A",
             "start_at": "2026-09-01T11:00:00Z",
             "end_at": "2026-09-01T12:00:00Z", "capacity": 5,
             "price_cents": 1000}, trainer_headers)
        validate_success(adjacent, 201)
        other_room = api.create_training_class(
            {"title": "D", "room": "ROOM_B",
             "start_at": "2026-09-01T09:00:00Z",
             "end_at": "2026-09-01T11:00:00Z", "capacity": 5,
             "price_cents": 1000}, trainer_headers)
        validate_success(other_room, 201)

    def test_overlapping_class_rejected(self, api, trainer_headers):
        """PRD §3.8: "One room cannot hold two overlapping scheduled classes:
        a new class whose half-open window from `start_at` (inclusive) to
        `end_at` (exclusive) overlaps another `SCHEDULED` class in the same
        room is rejected with `ERR_ROOM_DOUBLE_BOOKED`". 10:30-11:30
        intersects the 09:00-11:00 booking.

        Design: Difficulty/resource_temporal_overlap/room_halfopen_interval_adjacency
        """
        validate_success(api.create_training_class(
            {"title": "A", "room": "ROOM_A",
             "start_at": "2026-09-01T09:00:00Z",
             "end_at": "2026-09-01T11:00:00Z", "capacity": 5,
             "price_cents": 1000}, trainer_headers), 201)
        resp = api.create_training_class(
            {"title": "C", "room": "ROOM_A",
             "start_at": "2026-09-01T10:30:00Z",
             "end_at": "2026-09-01T11:30:00Z", "capacity": 5,
             "price_cents": 1000}, trainer_headers)
        validate_error(resp, ApiErrorId.ERR_ROOM_DOUBLE_BOOKED)

    def test_service_tech_cannot_create_training_class(
            self, api, service_tech_headers):
        """PRD §2.1: "A request whose role is recognized but is not listed for
        the endpoint — or that fails a per-action role condition, such as the
        fulfillment-type split on order fulfillment or the per-target role
        split on repair-ticket and enrollment advancement described in §3 — is
        rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD §4 lists POST
        /training-classes under Trainer and BranchManager only.

        Design: Corner/rbac/service_tech_cannot_create_training_class
        """
        resp = api.create_training_class(
            {"title": "TIG Intro", "room": "ROOM_A",
             "start_at": "2026-10-01T09:00:00Z",
             "end_at": "2026-10-01T11:00:00Z", "capacity": 6,
             "price_cents": 10000}, service_tech_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
