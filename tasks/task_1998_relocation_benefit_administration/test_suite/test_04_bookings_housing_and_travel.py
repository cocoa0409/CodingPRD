"""Service bookings: nights math and boundaries, half-open overlap, ledger moves."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    make_employee_headers,
    assert_case_ledger,
    assert_service_booking,
    create_case,
    authorize_case,
    start_case,
    create_case_in_progress,
    create_housing_booking,
    create_travel_booking,
    create_booking_payload,
    confirm_booking,
    complete_booking,
    cancel_booking,
    get_case,
)

MC = TEST_USERS["coordinator_headers"]


class TestBookingMath:
    def test_temp_housing_total_is_nights_times_rate(self):
        """PRD §3.4: "A housing stay is treated as a half-open interval — the
        check-in day counts, the check-out day does not — and `nights` is the
        count of whole days between the two dates"
        PRD §3.4: "The booking's `total_cents` is `nights` multiplied by the
        nightly rate for housing, and simply `amount_cents` for travel, which
        always carries zero `nights`."
        PRD §3.4: "Bookings are born `HELD` and hold no funds in that state."

        Design: Corner/calculations/temp_housing_total_is_nights_times_rate
        """
        ctx = create_case_in_progress()
        case_id = ctx["case"]["id"]
        emp_id = ctx["employee"]["id"]

        resp = api_client.create_service_booking(
            create_booking_payload(case_id, kind="TEMP_HOUSING",
                                   start_date="2026-10-01T00:00:00Z",
                                   end_date="2026-10-04T00:00:00Z",
                                   amount_cents=15000),
            make_employee_headers(emp_id))
        booking = validate_success(resp, 201)
        assert_service_booking(booking)
        assert booking["nights"] == 3  # [Oct 1, Oct 4): Oct 1, 2, 3
        assert booking["total_cents"] == 45000
        assert booking["status"] == "HELD"
        # HELD holds no funds.
        assert_case_ledger(get_case(case_id), committed=0, paid=0, released=0)

    def test_reversed_dates_booking_rejected(self):
        """PRD §3.4: "A supplied end date that does not fall after the start
        date is rejected with `ERR_INVALID_DATES` (HTTP 422)."

        Design: Corner/validations/reversed_dates_booking_rejected
        """
        ctx = create_case_in_progress()
        case_id = ctx["case"]["id"]
        emp_id = ctx["employee"]["id"]
        resp = api_client.create_service_booking(
            create_booking_payload(case_id, kind="TEMP_HOUSING",
                                   start_date="2026-09-10T00:00:00Z",
                                   end_date="2026-09-01T00:00:00Z",
                                   amount_cents=15000),
            make_employee_headers(emp_id))
        validate_error(resp, ApiErrorId.ERR_INVALID_DATES)

    def test_complete_held_booking_rejected(self):
        """PRD §3.4: "Completion (`CONFIRMED` → `COMPLETED`, by a coordinator)
        converts the commitment into spend: the committed column falls by
        `total_cents` and `total_paid_cents` rises by the same amount."
        PRD §2.10: "State validity**: the target resource is in a legal source
        state for the requested transition (`ERR_INVALID_STATE`, HTTP 409)"

        Design: Corner/state_machines/complete_held_booking_rejected
        """
        ctx = create_case_in_progress()
        case_id = ctx["case"]["id"]
        emp_id = ctx["employee"]["id"]
        booking = create_travel_booking(case_id, emp_id, 30000)
        assert booking["status"] == "HELD"

        resp = api_client.complete_booking(booking["id"], MC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert_case_ledger(get_case(case_id), committed=0, paid=0, released=0)


class TestNightsBoundary:
    def test_nights_exactly_at_max_allowed(self):
        """PRD §3.4: "The stay may not exceed the policy's
        `temp_housing_max_nights`: a stay of exactly that many nights is
        allowed, while one night more is rejected with
        `ERR_NIGHTS_LIMIT_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/nights_exactly_at_max_allowed
        """
        ctx = create_case_in_progress()  # default max 30 nights
        case_id = ctx["case"]["id"]
        emp_id = ctx["employee"]["id"]

        # Exactly 30 nights: allowed. [Oct 1, Oct 31) = 30 half-open nights.
        ok = validate_success(api_client.create_service_booking(
            create_booking_payload(case_id, kind="TEMP_HOUSING",
                                   start_date="2026-10-01T00:00:00Z",
                                   end_date="2026-10-31T00:00:00Z",
                                   amount_cents=5000),
            make_employee_headers(emp_id)), 201)
        assert ok["nights"] == 30
        assert ok["total_cents"] == 150000
        assert ok["status"] == "HELD"

        # 31 nights: one more than the ceiling. [Dec 1, Jan 1) = 31 nights.
        resp = api_client.create_service_booking(
            create_booking_payload(case_id, kind="TEMP_HOUSING",
                                   start_date="2026-12-01T00:00:00Z",
                                   end_date="2027-01-01T00:00:00Z",
                                   amount_cents=5000),
            make_employee_headers(emp_id))
        validate_error(resp, ApiErrorId.ERR_NIGHTS_LIMIT_EXCEEDED)

    def test_nights_boundary_on_smaller_ceiling(self):
        """PRD §3.4: "The stay may not exceed the policy's
        `temp_housing_max_nights`: a stay of exactly that many nights is
        allowed, while one night more is rejected with
        `ERR_NIGHTS_LIMIT_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/nights_exactly_at_max_allowed
        """
        ctx = create_case_in_progress(
            policy_overrides={"job_level": "ASSOCIATE",
                              "temp_housing_cap_cents": 150000,
                              "temp_housing_max_nights": 14,
                              "travel_cap_cents": 60000,
                              "misc_cap_cents": 100000,
                              "repayment_window_months": 12},
            employee_overrides={"job_level": "ASSOCIATE"})
        case_id = ctx["case"]["id"]
        emp_id = ctx["employee"]["id"]

        # Exactly 14 nights: allowed. [Oct 1, Oct 15) = 14 half-open nights.
        ok = validate_success(api_client.create_service_booking(
            create_booking_payload(case_id, kind="TEMP_HOUSING",
                                   start_date="2026-10-01T00:00:00Z",
                                   end_date="2026-10-15T00:00:00Z",
                                   amount_cents=5000),
            make_employee_headers(emp_id)), 201)
        assert ok["nights"] == 14
        assert ok["total_cents"] == 70000

        # 15 nights: rejected. [Nov 1, Nov 16) = 15 nights.
        resp = api_client.create_service_booking(
            create_booking_payload(case_id, kind="TEMP_HOUSING",
                                   start_date="2026-11-01T00:00:00Z",
                                   end_date="2026-11-16T00:00:00Z",
                                   amount_cents=5000),
            make_employee_headers(emp_id))
        validate_error(resp, ApiErrorId.ERR_NIGHTS_LIMIT_EXCEEDED)


class TestHalfOpenOverlap:
    def test_housing_half_open_overlap_rules(self):
        """PRD §3.4: "Nor may the half-open stay interval overlap any other
        non-`CANCELLED` housing booking of the same case — intervals that merely
        touch at a boundary are permitted, but a true overlap is rejected with
        `ERR_HOUSING_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/housing_half_open_overlap_rules
        """
        ctx = create_case_in_progress()
        case_id = ctx["case"]["id"]
        emp_id = ctx["employee"]["id"]
        b1 = create_housing_booking(case_id, emp_id,
                                    start_date="2026-09-01T00:00:00Z",
                                    end_date="2026-09-10T00:00:00Z",
                                    nightly_cents=15000)
        confirm_booking(b1["id"])

        # Adjacent: [Sep 10, Sep 15) touches [Sep 1, Sep 10) at the boundary.
        adjacent = validate_success(api_client.create_service_booking(
            create_booking_payload(case_id, kind="TEMP_HOUSING",
                                   start_date="2026-09-10T00:00:00Z",
                                   end_date="2026-09-15T00:00:00Z",
                                   amount_cents=15000),
            make_employee_headers(emp_id)), 201)
        assert adjacent["status"] == "HELD"
        assert adjacent["nights"] == 5
        assert adjacent["total_cents"] == 75000

        # Intersecting: [Sep 9, Sep 11) truly overlaps B1.
        resp = api_client.create_service_booking(
            create_booking_payload(case_id, kind="TEMP_HOUSING",
                                   start_date="2026-09-09T00:00:00Z",
                                   end_date="2026-09-11T00:00:00Z",
                                   amount_cents=15000),
            make_employee_headers(emp_id))
        validate_error(resp, ApiErrorId.ERR_HOUSING_OVERLAP)

    def test_cancelled_booking_frees_the_interval(self):
        """PRD §3.4: "Nor may the half-open stay interval overlap any other
        non-`CANCELLED` housing booking of the same case — intervals that merely
        touch at a boundary are permitted, but a true overlap is rejected with
        `ERR_HOUSING_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/housing_half_open_overlap_rules
        """
        ctx = create_case_in_progress()
        case_id = ctx["case"]["id"]
        emp_id = ctx["employee"]["id"]
        b1 = create_housing_booking(case_id, emp_id,
                                    start_date="2026-09-01T00:00:00Z",
                                    end_date="2026-09-10T00:00:00Z",
                                    nightly_cents=15000)
        confirm_booking(b1["id"])

        # While B1 is live, an overlapping stay is refused.
        resp = api_client.create_service_booking(
            create_booking_payload(case_id, kind="TEMP_HOUSING",
                                   start_date="2026-09-05T00:00:00Z",
                                   end_date="2026-09-12T00:00:00Z",
                                   amount_cents=15000),
            make_employee_headers(emp_id))
        validate_error(resp, ApiErrorId.ERR_HOUSING_OVERLAP)

        # Once B1 is cancelled it no longer blocks the interval.
        cancel_booking(b1["id"])
        freed = validate_success(api_client.create_service_booking(
            create_booking_payload(case_id, kind="TEMP_HOUSING",
                                   start_date="2026-09-05T00:00:00Z",
                                   end_date="2026-09-12T00:00:00Z",
                                   amount_cents=15000),
            make_employee_headers(emp_id)), 201)
        assert freed["status"] == "HELD"
        assert freed["nights"] == 7
        assert freed["total_cents"] == 105000


class TestLedgerConservation:
    def test_booking_confirm_cancel_ledger_conservation(self):
        """PRD §2.6: "Across a confirm-then-cancel pair on the same booking, the
        paid column never changes, the committed column rises and then falls by
        the same amount, and the released column gains that amount only at the
        cancellation."

        Design: Difficulty/compensating_invariant/booking_confirm_cancel_ledger_conservation
        """
        ctx = create_case_in_progress()
        case_id = ctx["case"]["id"]
        emp_id = ctx["employee"]["id"]
        booking = create_housing_booking(case_id, emp_id,
                                         start_date="2026-09-01T00:00:00Z",
                                         end_date="2026-09-10T00:00:00Z",
                                         nightly_cents=15000)
        assert booking["total_cents"] == 135000

        confirm_booking(booking["id"])
        mid = get_case(case_id)
        assert_case_ledger(mid, committed=135000, paid=0, released=0)
        sum_mid = (mid["total_paid_cents"] + mid["total_committed_cents"]
                   + mid["total_released_cents"])

        cancel_booking(booking["id"])
        end = get_case(case_id)
        assert_case_ledger(end, committed=0, paid=0, released=135000)
        sum_end = (end["total_paid_cents"] + end["total_committed_cents"]
                   + end["total_released_cents"])
        assert sum_mid == sum_end == 135000, "authorized funds are conserved"

        cancelled = validate_success(api_client.get_service_booking(booking["id"], MC))
        assert cancelled["status"] == "CANCELLED"

    def test_booking_confirm_complete_ledger_conservation(self):
        """PRD §2.6: "Approving or confirming moves an amount into the committed
        column; completing, paying, or settling moves that amount out of
        committed and the final amount into paid; cancelling moves the held
        amount out of committed and into released."
        PRD §3.4: "Completion (`CONFIRMED` → `COMPLETED`, by a coordinator)
        converts the commitment into spend: the committed column falls by
        `total_cents` and `total_paid_cents` rises by the same amount."

        Design: Difficulty/compensating_invariant/booking_confirm_cancel_ledger_conservation
        """
        ctx = create_case_in_progress()
        case_id = ctx["case"]["id"]
        emp_id = ctx["employee"]["id"]
        booking = create_travel_booking(case_id, emp_id, 61000)

        confirm_booking(booking["id"])
        assert_case_ledger(get_case(case_id), committed=61000, paid=0, released=0)

        completed = complete_booking(booking["id"])
        assert completed["status"] == "COMPLETED"
        end = get_case(case_id)
        assert_case_ledger(end, committed=0, paid=61000, released=0)
        # Conservation across the confirm-then-complete pair: 61000 throughout.
        assert end["total_paid_cents"] + end["total_committed_cents"] \
            + end["total_released_cents"] == 61000

    def test_read_after_write_reflects_mutation_immediately(self):
        """PRD §3.4: "Confirmation by a coordinator (`HELD` → `CONFIRMED`)
        requires the case still `IN_PROGRESS` and commits `total_cents` to the
        case ledger's committed column, incrementing both the case and booking
        versions."
        PRD §2.6: "Every relocation case carries a three-column cost ledger
        maintained entirely by the system."

        Design: Corner/consistency_model/read_after_write_reflects_mutation_immediately
        """
        ctx = create_case_in_progress()
        case_id = ctx["case"]["id"]
        emp_id = ctx["employee"]["id"]
        booking = create_housing_booking(case_id, emp_id,
                                         start_date="2026-10-01T00:00:00Z",
                                         end_date="2026-10-04T00:00:00Z",
                                         nightly_cents=10000)
        confirm_booking(booking["id"])
        # The very next read reflects the committed funds.
        case_after = get_case(case_id)
        assert case_after["total_committed_cents"] == 30000
        confirmed = validate_success(api_client.get_service_booking(booking["id"], MC))
        assert confirmed["status"] == "CONFIRMED"


class TestCaseBookingSubresource:
    def test_case_service_bookings_subresource_lists_children(self):
        """PRD §4: "GET | `/relocation-cases/{id}/service-bookings` | List a
        case's service bookings | All roles"
        PRD §3.4: "A case's bookings are listed with optional `kind` and
        `status` filters."

        Design: Corner/endpoints/case_service_bookings_subresource_lists_children
        """
        ctx = create_case_in_progress()
        case_id = ctx["case"]["id"]
        emp_id = ctx["employee"]["id"]
        sb1 = create_travel_booking(case_id, emp_id, 30000)
        sb2 = create_housing_booking(case_id, emp_id,
                                     start_date="2026-10-01T00:00:00Z",
                                     end_date="2026-10-04T00:00:00Z",
                                     nightly_cents=10000)

        # A second case with its own booking must not leak into the list.
        other = create_case(emp_id, destination_city="Boulder")
        authorize_case(other["id"])
        start_case(other["id"])
        create_travel_booking(other["id"], emp_id, 9999,
                              start_date="2026-11-01T00:00:00Z")

        resp = api_client.list_case_service_bookings(case_id, MC)
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2
        assert {b["id"] for b in data} == {sb1["id"], sb2["id"]}
        assert all(b["case_id"] == case_id for b in data)
