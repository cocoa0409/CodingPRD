"""Terms, scheduled breaks, students, enrollments, and the account ledger."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_academic_term,
    assert_enrollment,
    assert_scheduled_break,
    assert_student_account_entry,
    create_break,
    create_enrollment,
    create_student,
    create_term,
    list_account_entries,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import make_student_headers

REGISTRAR = TEST_USERS["registrar_clerk_headers"]
OFFICER = TEST_USERS["financial_aid_officer_headers"]
BURSAR = TEST_USERS["bursar_clerk_headers"]


class TestTermDayCounts:

    def test_term_creation_computes_calendar_days_then_break_deduction(self):
        """PRD section 3.1: "Upon creation the server derives three day-count
        figures. The `calendar_days` of a term are the count of calendar days
        from `start_date` through `end_date` inclusive."
        PRD section 3.1: "The `total_days` of the term are its
        `calendar_days` minus its `deductible_break_days`"
        PRD section 3.1: "the group is deductible when that span reaches at
        least 5 consecutive days."

        Design: Corner/entities/term_creation_computes_day_counts
        """
        term = create_term(name="Fall 2026", start_date="2026-08-24",
                           end_date="2026-12-11")
        assert_academic_term(term)
        assert term["calendar_days"] == 110
        assert term["deductible_break_days"] == 0
        assert term["total_days"] == 110

        brk = create_break(term["id"], start_date="2026-11-25",
                           end_date="2026-11-29")
        assert_scheduled_break(brk)
        term_after = validate_success(api_client.get_term(term["id"],
                                                          REGISTRAR), 200)
        assert term_after["deductible_break_days"] == 5
        assert term_after["total_days"] == 105

    def test_term_end_before_start_rejected(self):
        """PRD section 3.1: "the end date must fall strictly after the start
        date, or the request is rejected with `ERR_INVALID_FIELD`."

        Design: Corner/entities/term_end_before_start_rejected
        """
        resp = api_client.create_term(
            {"name": "Bad", "start_date": "2026-08-24",
             "end_date": "2026-08-01"},
            REGISTRAR)
        validate_error(resp, "ERR_INVALID_FIELD", expected_status=422)
        _, meta = validate_paginated(api_client.list_terms(REGISTRAR))
        assert meta["total_count"] == 0

    def test_student_missing_required_email_rejected(self):
        """PRD section 3.2: "a `RegistrarClerk` registers the student with an
        `external_ref` (the student information system's reference), a
        `full_name`, and a notification `email`."
        PRD section 2.9: "required fields are present, enum members are
        valid, types are correct, an end date is strictly after its start
        date, and amounts are positive where required; violations yield
        `ERR_INVALID_REQUEST` (400) or `ERR_INVALID_FIELD` (422)."

        Design: Corner/entities/student_missing_required_email_rejected
        """
        resp = api_client.create_student(
            {"external_ref": "SX", "full_name": "No Email"}, REGISTRAR)
        validate_error(resp, "ERR_INVALID_REQUEST", expected_status=400)


class TestEnrollmentCreation:

    def test_enrollment_creation_defaults_and_charge_entry(self):
        """PRD section 3.2: "Creation immediately posts the first ledger
        entry, a `CHARGE` entry for the full `institutional_charges_cents`,
        so the new enrollment's `balance_cents` equals the charges and its
        `status` begins as `ENROLLED`."

        Design: Corner/entities/enrollment_creation_defaults_and_charge_entry
        """
        term = create_term()
        student = create_student()
        enrollment = create_enrollment(student["id"], term["id"],
                                       institutional_charges_cents=600_000)
        assert_enrollment(enrollment)
        assert enrollment["status"] == "ENROLLED"
        assert enrollment["balance_cents"] == 600_000
        assert enrollment["balance_notification_sent"] is False
        assert isinstance(enrollment["version"], int)

        entries = list_account_entries(enrollment_id=enrollment["id"])
        assert len(entries) == 1
        assert_student_account_entry(entries[0])
        assert entries[0]["entry_type"] == "CHARGE"
        assert entries[0]["amount_cents"] == 600_000

    def test_account_entry_immutable_shape(self):
        """PRD section 2.4: "A scheduled break and a student account entry
        are immutable records once created: each carries only `id` and
        `created_at`, and both `updated_at` and `version` are absent from
        them."

        Design: Corner/entities/account_entry_immutable_shape
        """
        term = create_term()
        student = create_student()
        enrollment = create_enrollment(student["id"], term["id"],
                                       institutional_charges_cents=600_000)
        entries = list_account_entries(enrollment_id=enrollment["id"])
        assert len(entries) == 1
        entry_id = entries[0]["id"]

        fetched = validate_success(
            api_client.get_account_entry(entry_id, BURSAR), 200)
        assert_student_account_entry(fetched)
        assert fetched["id"] == entry_id

    def test_enrollment_computed_balance_input_ignored(self):
        """PRD section 2.6: "The enrollment's `balance_cents` is always a
        derived figure: the sum of the signed `amount_cents` over every
        account entry of the enrollment, where a positive value means the
        student owes the school."
        PRD section 3.2: "Creation immediately posts the first ledger entry,
        a `CHARGE` entry for the full `institutional_charges_cents`, so the
        new enrollment's `balance_cents` equals the charges"

        Design: Corner/entities/enrollment_computed_balance_input_ignored
        """
        term = create_term()
        student = create_student()
        resp = api_client.create_enrollment(
            student["id"],
            {"term_id": term["id"], "institutional_charges_cents": 600_000,
             "balance_cents": 999},
            REGISTRAR)
        enrollment = validate_success(resp, 201)
        assert enrollment["balance_cents"] == 600_000

    def test_enrollment_not_found_returns_404(self):
        """PRD section 2.9: "path and body resource identifiers are validated
        left to right; the first identifier that does not correspond to an
        existing resource yields `ERR_NOT_FOUND` (404)."

        Design: Corner/entities/enrollment_not_found_returns_404
        """
        resp = api_client.get_enrollment(NON_EXISTENT_UUID, REGISTRAR)
        validate_error(resp, "ERR_NOT_FOUND", expected_status=404)


class TestTermOverlap:
    """Closed-interval semantics for term date ranges (PRD section 3.1)."""

    def _create_fall(self):
        return create_term(name="Fall 2026", start_date="2026-08-24",
                           end_date="2026-12-11")

    def test_shared_endpoint_day_overlaps_but_next_day_is_adjacent(self):
        """PRD section 3.1: "A new term whose closed date interval intersects
        any existing term's closed interval is rejected with
        `ERR_TERM_OVERLAP`; two terms that merely touch — one ending on the
        day before the other begins — are permitted."

        Design: Difficulty/resource_temporal_overlap/term_closed_interval_overlap_with_adjacency_allowed
        """
        self._create_fall()
        # New term starts ON the existing term's last day -> shared date
        # 2026-12-11 lies in both closed intervals -> overlap.
        resp = api_client.create_term(
            {"name": "Winter Overlap", "start_date": "2026-12-11",
             "end_date": "2027-03-31"},
            REGISTRAR)
        validate_error(resp, "ERR_TERM_OVERLAP", expected_status=409)

        # Starting the day after -> adjacency, not overlap -> created.
        ok = api_client.create_term(
            {"name": "Winter Adjacent", "start_date": "2026-12-12",
             "end_date": "2027-03-31"},
            REGISTRAR)
        term = validate_success(ok, 201)
        assert_academic_term(term)

    @pytest.mark.parametrize("start_date,end_date", [
        ("2026-08-24", "2026-12-11"),  # identical interval
        ("2026-09-01", "2026-09-30"),  # strictly inside
        ("2026-08-01", "2027-03-31"),  # enclosing
        ("2026-08-01", "2026-08-24"),  # touches the first day
    ])
    def test_every_intersecting_interval_rejected(self, start_date, end_date):
        """PRD section 3.1: "A new term whose closed date interval intersects
        any existing term's closed interval is rejected with
        `ERR_TERM_OVERLAP`; two terms that merely touch — one ending on the
        day before the other begins — are permitted."

        Design: Difficulty/resource_temporal_overlap/term_closed_interval_overlap_with_adjacency_allowed
        """
        self._create_fall()
        resp = api_client.create_term(
            {"name": "Overlap", "start_date": start_date,
             "end_date": end_date},
            REGISTRAR)
        validate_error(resp, "ERR_TERM_OVERLAP", expected_status=409)

    def test_term_ending_day_before_existing_starts_is_adjacent(self):
        """PRD section 3.1: "A new term whose closed date interval intersects
        any existing term's closed interval is rejected with
        `ERR_TERM_OVERLAP`; two terms that merely touch — one ending on the
        day before the other begins — are permitted."

        Design: Difficulty/resource_temporal_overlap/term_closed_interval_overlap_with_adjacency_allowed
        """
        self._create_fall()
        ok = api_client.create_term(
            {"name": "Summer Prior", "start_date": "2026-06-01",
             "end_date": "2026-08-23"},
            REGISTRAR)
        term = validate_success(ok, 201)
        assert_academic_term(term)


class TestBreakGrouping:
    """Break merge/deduction grouping (PRD section 3.1)."""

    def _spring_term(self):
        # 2027-01-11..2027-04-30 -> 110 calendar days; does not overlap T1.
        return create_term(name="Spring 2027", start_date="2027-01-11",
                           end_date="2027-04-30")

    def test_adjacent_breaks_merge_into_one_deductible_group(self):
        """PRD section 3.1: "A break whose closed interval intersects another
        break of the same term is rejected with `ERR_BREAK_OVERLAP`;
        adjacency, by contrast, is not an overlap and instead causes the
        breaks to merge for deduction purposes."
        PRD section 3.1: "For reporting, the group's earliest break (by start
        date, then creation time) carries the group's entire span as its
        `deductible_days`; every other break in a deductible group carries
        zero, as does every break in a non-deductible group."

        Design: Difficulty/resource_temporal_overlap/break_adjacency_merges_for_deduction
        """
        term = self._spring_term()
        b1 = create_break(term["id"], start_date="2027-02-15",
                          end_date="2027-02-17")
        b2 = create_break(term["id"], start_date="2027-02-18",
                          end_date="2027-02-19")
        assert_scheduled_break(b1)
        assert_scheduled_break(b2)

        term_after = validate_success(api_client.get_term(term["id"],
                                                          REGISTRAR), 200)
        assert term_after["calendar_days"] == 110
        # Adjacent 3-day + 2-day breaks fuse into one 5-day deductible group.
        assert term_after["deductible_break_days"] == 5
        assert term_after["total_days"] == 105
        # The group's whole span is attributed to the earliest break.
        b1_after = [b for b in validate_success(
            api_client.list_breaks(term["id"], REGISTRAR), 200)
            if b["id"] == b1["id"]][0]
        b2_after = [b for b in validate_success(
            api_client.list_breaks(term["id"], REGISTRAR), 200)
            if b["id"] == b2["id"]][0]
        assert b1_after["deductible_days"] == 5
        assert b2_after["deductible_days"] == 0

        # A break genuinely intersecting existing breaks is rejected.
        resp = api_client.create_break(
            term["id"], {"start_date": "2027-02-16", "end_date": "2027-02-18"},
            REGISTRAR)
        validate_error(resp, "ERR_BREAK_OVERLAP", expected_status=409)

    def test_short_break_group_not_deductible_but_five_days_is(self):
        """PRD section 3.1: "A group's span is the count of days from its
        earliest start through its latest end inclusive, and the group is
        deductible when that span reaches at least 5 consecutive days."

        Design: Difficulty/resource_temporal_overlap/break_adjacency_merges_for_deduction
        """
        # 4-day break: below the 5-day deductible threshold.
        term_a = self._spring_term()
        brk_a = create_break(term_a["id"], start_date="2027-02-15",
                             end_date="2027-02-18")
        term_a_after = validate_success(api_client.get_term(term_a["id"],
                                                            REGISTRAR), 200)
        assert term_a_after["deductible_break_days"] == 0
        assert term_a_after["total_days"] == 110
        assert brk_a["deductible_days"] == 0

        # Exactly 5 days: the threshold is inclusive.
        term_b = create_term(name="Fall 2027", start_date="2027-08-23",
                             end_date="2027-12-10")
        brk_b = create_break(term_b["id"], start_date="2027-11-24",
                             end_date="2027-11-28")
        term_b_after = validate_success(api_client.get_term(term_b["id"],
                                                            REGISTRAR), 200)
        assert term_b_after["deductible_break_days"] == 5
        assert term_b_after["total_days"] == 105
        assert brk_b["deductible_days"] == 5
