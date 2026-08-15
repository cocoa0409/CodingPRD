"""Competency requirements/completions (ROLLING vs FISCAL expiry) and competency
sessions/bookings capacity rules (PRD §3.4)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_competency_completion,
    book_session,
    create_nurse,
    create_requirement,
    create_session,
    get_session,
    record_completion,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client, TEST_USERS, make_nurse_headers

SPEC1 = TEST_USERS["specialist_1"]
MGR1 = TEST_USERS["manager_1"]


class TestCompetencyExpiryDualVariant:
    """Difficulty instance: competency_expiry_rolling_vs_fiscal_divergence — identical
    completed_on yields divergent expires_on under the two window modes."""

    def _setup_requirements_and_nurse(self):
        set_clock()
        req_roll = create_requirement(
            code="ROLLING12", name="Rolling Annual Skills", validity_months=12,
            window_mode="ROLLING", mandatory=True, applies_to=["STAFF"],
        )
        req_fisc = create_requirement(
            code="FISCAL12", name="Fiscal Annual Skills", validity_months=12,
            window_mode="FISCAL", mandatory=True, applies_to=["STAFF"],
        )
        nurse = create_nurse(full_name="Dana Roll", email="dana.roll@x.com",
                             primary_state_of_residence="AZ", employment_type="STAFF",
                             hire_date="2026-07-01")
        return req_roll, req_fisc, nurse

    def test_rolling_variant_expiry_is_anniversary_based(self):
        """PRD §3.4: "Under `ROLLING`, expiry is the anniversary of `completed_on` plus
        `validity_months` months, keeping the same day of month; when the target month
        lacks that day, the target month's last day is used."

        Design: Difficulty/dual_variant_calc/competency_expiry_rolling_vs_fiscal_divergence
        """
        req_roll, _req_fisc, nurse = self._setup_requirements_and_nurse()
        completion = record_completion(nurse["id"], req_roll["id"],
                                       completed_on="2026-07-15")
        assert_competency_completion(completion)
        assert completion["expires_on"] == "2027-07-15", (
            f"ROLLING: 2026-07-15 + 12 months; got {completion['expires_on']}"
        )

    def test_fiscal_variant_diverges_from_rolling(self):
        """PRD §3.4: "Under `FISCAL`, expiry is the first occurrence of the fiscal-year
        end, June 30, that falls on or after `completed_on` — so a completion dated
        exactly June 30 expires that same day."
        PRD §3.4: "Under `ROLLING`, expiry is the anniversary of `completed_on` plus
        `validity_months` months, keeping the same day of month; ..."

        Design: Difficulty/dual_variant_calc/competency_expiry_rolling_vs_fiscal_divergence
        """
        req_roll, req_fisc, nurse = self._setup_requirements_and_nurse()
        c_roll = record_completion(nurse["id"], req_roll["id"], completed_on="2026-07-15")
        c_fisc = record_completion(nurse["id"], req_fisc["id"], completed_on="2026-07-15")
        assert c_fisc["expires_on"] == "2027-06-30", (
            f"FISCAL: first 06-30 on or after 2026-07-15; got {c_fisc['expires_on']}"
        )
        assert c_roll["expires_on"] == "2027-07-15"
        assert c_roll["expires_on"] != c_fisc["expires_on"], (
            "identical completed_on must diverge across the two variants"
        )


class TestCompetencyCompletionRules:
    def test_competency_fiscal_cycle_end_same_day(self):
        """PRD §3.4: "Under `FISCAL`, expiry is the first occurrence of the fiscal-year
        end, June 30, that falls on or after `completed_on` — so a completion dated
        exactly June 30 expires that same day."
        PRD §2.5: "Setting the clock mutates no entity: licenses, certifications, and
        completions do not expire merely because the clock advanced past their dates."

        Design: Corner/calculations/competency_fiscal_cycle_end_same_day
        """
        set_clock()
        req = create_requirement(code="FISCAL12", name="Fiscal Annual Skills",
                                 validity_months=12, window_mode="FISCAL",
                                 mandatory=True, applies_to=["STAFF"])
        nurse1 = create_nurse(full_name="Fay Edge", email="fay.edge@x.com",
                              employment_type="STAFF", hire_date="2026-06-01")
        nurse2 = create_nurse(full_name="Gus Edge", email="gus.edge@x.com",
                              employment_type="STAFF", hire_date="2026-06-01")

        c1 = record_completion(nurse1["id"], req["id"], completed_on="2026-06-30")
        c2 = record_completion(nurse2["id"], req["id"], completed_on="2026-07-01")
        assert c1["expires_on"] == "2026-06-30", (
            "completed exactly on the fiscal-year end expires that same day"
        )
        assert c2["expires_on"] == "2027-06-30", "first 06-30 on or after 2026-07-01"
        assert c1["status"] == "CURRENT" and c2["status"] == "CURRENT", (
            "lapse is sweep-driven; the clock alone never lapses a completion"
        )

    def test_requirement_not_applicable_rejected(self):
        """PRD §3.4: "The requirement must exist, else `ERR_REQUIREMENT_NOT_FOUND`; its
        `applies_to` must contain the nurse's employment type, else
        `ERR_REQUIREMENT_NOT_APPLICABLE`; and `completed_on` must not lie in the
        future, else `ERR_INVALID_DATE_RANGE`."

        Design: Corner/validations/requirement_not_applicable_rejected
        """
        set_clock()
        req = create_requirement(code="STAFF_ONLY", name="Staff Only Module",
                                 validity_months=12, window_mode="ROLLING",
                                 mandatory=True, applies_to=["STAFF"])
        nurse = create_nurse(full_name="Tra Vel", email="tra.vel@x.com",
                             employment_type="TRAVEL")
        resp = api_client.create_competency_completion(
            {"nurse_id": nurse["id"], "requirement_id": req["id"],
             "completed_on": "2026-07-15"},
            make_nurse_headers(nurse["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REQUIREMENT_NOT_APPLICABLE)
        data, meta = validate_paginated(
            api_client.list_competency_completions(SPEC1, params={"nurse_id": nurse["id"]})
        )
        assert meta["total_count"] == 0

    def test_completion_create_requirement_not_found_returns_404(self):
        """PRD §3.4: "The requirement must exist, else `ERR_REQUIREMENT_NOT_FOUND`; its
        `applies_to` must contain the nurse's employment type, else
        `ERR_REQUIREMENT_NOT_APPLICABLE`; and `completed_on` must not lie in the
        future, else `ERR_INVALID_DATE_RANGE`."

        Design: Corner/validations/completion_create_requirement_not_found_returns_404
        """
        set_clock()
        nurse = create_nurse(full_name="Req Miss", email="req.miss@x.com")
        resp = api_client.create_competency_completion(
            {"nurse_id": nurse["id"], "requirement_id": NON_EXISTENT_UUID,
             "completed_on": "2026-07-15"},
            make_nurse_headers(nurse["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REQUIREMENT_NOT_FOUND)
        _data, meta = validate_paginated(
            api_client.list_competency_completions(SPEC1, params={"nurse_id": nurse["id"]})
        )
        assert meta["total_count"] == 0


class TestSessionCapacity:
    """Difficulty instance: session_capacity_exact_full_boundary (capacity reached =>
    rejection) and corner sibling on aggregate-overlap semantics."""

    def _setup_session_capacity_2(self, title="Skills Fair"):
        set_clock()
        req = create_requirement(code=f"SKILLS_FAIR_{title.replace(' ', '_')}",
                                 name=title, validity_months=12, window_mode="ROLLING",
                                 mandatory=False,
                                 applies_to=["STAFF", "TRAVEL", "PER_DIEM"])
        session = create_session(
            req["id"], capacity=2,
            starts_at="2026-08-05T09:00:00Z", ends_at="2026-08-05T12:00:00Z",
            title=f"{title} AM",
        )
        nurses = [
            create_nurse(full_name=f"Cap {tag}", email=f"cap.{tag}@x.com")
            for tag in ("one", "two", "three")
        ]
        return session, nurses

    def test_bookings_admitted_up_to_capacity(self):
        """PRD §3.4: "Booking a nurse into a session is rejected once the session's
        `booked_count` has reached `capacity` (`ERR_SESSION_FULL`) and when the same
        nurse already holds a booking in that session (`ERR_BOOKING_DUPLICATE`); ..."
        PRD §3.4: "A booking is born with `attended` false, tied to its session by
        `session_id`, and increments `booked_count` by 1."

        Design: Difficulty/boundary_precision_check/session_capacity_exact_full_boundary
        """
        session, nurses = self._setup_session_capacity_2()
        b1 = book_session(session["id"], nurses[0]["id"])
        assert b1["attended"] is False
        b2 = book_session(session["id"], nurses[1]["id"])
        assert b2["session_id"] == session["id"]
        after = get_session(session["id"])
        assert after["booked_count"] == 2, "booked_count 0 -> 1 -> 2"

    def test_booking_rejected_exactly_at_capacity(self):
        """PRD §3.4: "Booking a nurse into a session is rejected once the session's
        `booked_count` has reached `capacity` (`ERR_SESSION_FULL`) ..."

        Design: Difficulty/boundary_precision_check/session_capacity_exact_full_boundary
        """
        session, nurses = self._setup_session_capacity_2()
        book_session(session["id"], nurses[0]["id"])
        book_session(session["id"], nurses[1]["id"])

        resp = api_client.book_session(session["id"], {"nurse_id": nurses[2]["id"]}, MGR1)
        validate_error(resp, ApiErrorId.ERR_SESSION_FULL)
        after = get_session(session["id"])
        assert after["booked_count"] == 2, "the rejection must not free or add a seat"
        data, meta = validate_paginated(
            api_client.list_session_bookings(MGR1, params={"nurse_id": nurses[2]["id"]})
        )
        assert meta["total_count"] == 0, "the third nurse holds no booking"

    def test_full_overlap_bookings_tolerated_below_capacity(self):
        """PRD §3.4: "Booking a nurse into a session is rejected once the session's
        `booked_count` has reached `capacity` (`ERR_SESSION_FULL`) and when the same
        nurse already holds a booking in that session (`ERR_BOOKING_DUPLICATE`);
        bookings may otherwise overlap freely — aggregate capacity, not scheduling
        collision, is the constraint."

        Design: Difficulty/resource_temporal_overlap/session_capacity_aggregate_overlap
        """
        session, nurses = self._setup_session_capacity_2(title="Skills Fair Overlap")
        b1 = book_session(session["id"], nurses[0]["id"])
        b2 = book_session(session["id"], nurses[1]["id"])
        assert b1["nurse_id"] != b2["nurse_id"]
        after = get_session(session["id"])
        assert after["booked_count"] == 2, (
            "both bookings occupy the identical session window; overlap alone is no conflict"
        )

    def test_aggregate_occupation_not_geometry_is_the_collision_rule(self):
        """PRD §3.4: "...bookings may otherwise overlap freely — aggregate capacity,
        not scheduling collision, is the constraint."
        PRD §3.4: "Booking a nurse into a session is rejected once the session's
        `booked_count` has reached `capacity` (`ERR_SESSION_FULL`) ..."

        Design: Difficulty/resource_temporal_overlap/session_capacity_aggregate_overlap
        """
        session, nurses = self._setup_session_capacity_2(title="Skills Fair Aggregate")
        book_session(session["id"], nurses[0]["id"])
        book_session(session["id"], nurses[1]["id"])
        resp = api_client.book_session(session["id"], {"nurse_id": nurses[2]["id"]}, MGR1)
        validate_error(resp, ApiErrorId.ERR_SESSION_FULL)
        assert get_session(session["id"])["booked_count"] == 2


class TestSessionBookings:
    def test_booking_duplicate_rejected(self):
        """PRD §3.4: "Booking a nurse into a session is rejected once the session's
        `booked_count` has reached `capacity` (`ERR_SESSION_FULL`) and when the same
        nurse already holds a booking in that session (`ERR_BOOKING_DUPLICATE`); ..."

        Design: Corner/validations/booking_duplicate_rejected
        """
        set_clock()
        req = create_requirement(code="SKILLS_FAIR_DUP", name="Skills Fair",
                                 validity_months=12, window_mode="ROLLING",
                                 mandatory=False, applies_to=["STAFF"])
        session = create_session(req["id"], capacity=5, title="Fair A")
        nurse = create_nurse(full_name="Dup Booker", email="dup.booker@x.com")
        book_session(session["id"], nurse["id"])

        resp = api_client.book_session(session["id"], {"nurse_id": nurse["id"]}, MGR1)
        validate_error(resp, ApiErrorId.ERR_BOOKING_DUPLICATE)
        assert get_session(session["id"])["booked_count"] == 1, (
            "capacity remains; the duplicate rule, not the capacity rule, fired"
        )

    def test_booking_delete_attended_rejected(self):
        """PRD §3.4: "Deleting a booking frees a seat by decrementing `booked_count`,
        and is allowed only while `attended` is still false — otherwise
        `ERR_INVALID_BOOKING_STATE`. Deletion returns 204 with no body."
        PRD §3.4: "After the session has ended — completing before `ends_at` is
        `ERR_SESSION_NOT_ENDED` — marking the booking complete sets `attended` true and
        creates a linked completion with `source` `SESSION`, `completed_on` set to the
        session's start date, and the booking's `completion_id` pointing at the new
        row; the usual supersede and posture recompute follow."
        PRD §3.4: "Under `ROLLING`, expiry is the anniversary of `completed_on` plus
        `validity_months` months, keeping the same day of month; ..."

        Design: Corner/validations/booking_delete_attended_rejected
        """
        set_clock()
        req = create_requirement(code="SKILLS_FAIR_DEL", name="Skills Fair",
                                 validity_months=12, window_mode="ROLLING",
                                 mandatory=True, applies_to=["STAFF"])
        session = create_session(req["id"], capacity=5, title="Fair C")
        nurse = create_nurse(full_name="Del Booking", email="del.booking@x.com")
        booking = book_session(session["id"], nurse["id"])

        set_clock("2026-08-05T12:30:00Z")
        done = validate_success(api_client.complete_session_booking(booking["id"], MGR1), 200)
        assert done["attended"] is True
        assert done["completion_id"], "completion_id links the new row"

        completions, meta = validate_paginated(
            api_client.list_competency_completions(SPEC1, params={"nurse_id": nurse["id"]})
        )
        assert meta["total_count"] == 1
        completion = completions[0]
        assert_competency_completion(completion)
        assert completion["source"] == "SESSION"
        assert completion["completed_on"] == "2026-08-05", "the session's start date"
        assert completion["expires_on"] == "2027-08-05", "ROLLING 12 months"

        resp = api_client.delete_session_booking(booking["id"], MGR1)
        validate_error(resp, ApiErrorId.ERR_INVALID_BOOKING_STATE)
        still = validate_success(api_client.get_session_booking(booking["id"], MGR1), 200)
        assert still["attended"] is True
        assert get_session(session["id"])["booked_count"] == 1, (
            "an attended booking does not free its seat"
        )

    def test_session_booking_complete_before_end_rejected(self):
        """PRD §3.4: "After the session has ended — completing before `ends_at` is
        `ERR_SESSION_NOT_ENDED` — marking the booking complete sets `attended` true and
        creates a linked completion with `source` `SESSION`, ..."

        Design: Corner/validations/session_booking_complete_before_end_rejected
        """
        set_clock()
        req = create_requirement(code="SKILLS_FAIR_EARLY", name="Skills Fair",
                                 validity_months=12, window_mode="ROLLING",
                                 mandatory=True, applies_to=["STAFF"])
        session = create_session(req["id"], capacity=5, title="Fair B")
        nurse = create_nurse(full_name="Mid Session", email="mid.session@x.com")
        booking = book_session(session["id"], nurse["id"])

        set_clock("2026-08-05T11:00:00Z")
        resp = api_client.complete_session_booking(booking["id"], MGR1)
        validate_error(resp, ApiErrorId.ERR_SESSION_NOT_ENDED)
        after = validate_success(api_client.get_session_booking(booking["id"], MGR1), 200)
        assert after["attended"] is False
        _data, meta = validate_paginated(
            api_client.list_competency_completions(SPEC1, params={"nurse_id": nurse["id"]})
        )
        assert meta["total_count"] == 0, "no completion is created mid-session"
