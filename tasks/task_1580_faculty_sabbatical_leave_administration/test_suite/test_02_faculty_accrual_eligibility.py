"""Faculty records, credit accrual, and the certified/provisional split."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    activate_grant_at,
    complete_grant_at,
    create_application,
    create_cycle,
    create_department,
    create_faculty,
    decide_application,
    get_success_data,
    grant_for_application,
    make_faculty_headers,
    open_cycle,
    run_accruals,
    separate_faculty,
    set_clock,
    setup_full_award,
    setup_professional_grant,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
PROVOST = TEST_USERS["provost_headers"]


class TestFacultyCreation:
    def test_missing_required_salary_rejected(self, api):
        """PRD 3.2: "A `LeaveAdministrator` registers a faculty member with an
        `employee_number` (unique across the institution), `full_name`, the home
        `department_id`, an `academic_rank` of `ASSISTANT_PROFESSOR`,
        `ASSOCIATE_PROFESSOR`, or `FULL_PROFESSOR`, the `hire_date`, and a
        strictly positive `annual_base_salary`."
        PRD 2.9: "Required fields are present, enum values are in range, numbers
        are in domain ... else `ERR_INVALID_REQUEST` or `ERR_INVALID_PAGINATION`."

        Design: Corner/entities/faculty_create_missing_required_field
        """
        dept = create_department()
        resp = api.create_faculty_member(
            {
                "employee_number": "F100",
                "full_name": "Fac Uno",
                "department_id": dept["id"],
                "academic_rank": "ASSOCIATE_PROFESSOR",
                "hire_date": "2020-08-01T00:00:00Z",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_invalid_academic_rank_rejected(self, api):
        """PRD 3.2: "an `academic_rank` of `ASSISTANT_PROFESSOR`,
        `ASSOCIATE_PROFESSOR`, or `FULL_PROFESSOR`"
        PRD 2.9: "Required fields are present, enum values are in range, numbers
        are in domain ... else `ERR_INVALID_REQUEST` or `ERR_INVALID_PAGINATION`."

        Design: Corner/entities/faculty_create_invalid_enum_rejected
        """
        dept = create_department()
        resp = api.create_faculty_member(
            {
                "employee_number": "F100",
                "full_name": "Fac Uno",
                "department_id": dept["id"],
                "academic_rank": "DEAN",
                "hire_date": "2020-08-01T00:00:00Z",
                "annual_base_salary": 120000.00,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_bad_department_foreign_key_returns_404(self, api):
        """PRD 2.9: "Path identifiers and body foreign-key references are
        resolved left to right ... and the first missing reference yields its
        corresponding error: `ERR_DEPARTMENT_NOT_FOUND`"

        Design: Corner/entities/faculty_create_bad_department_fk_returns_404
        """
        resp = api.create_faculty_member(
            {
                "employee_number": "F100",
                "full_name": "Fac Uno",
                "department_id": NON_EXISTENT_UUID,
                "academic_rank": "ASSOCIATE_PROFESSOR",
                "hire_date": "2020-08-01T00:00:00Z",
                "annual_base_salary": 120000.00,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DEPARTMENT_NOT_FOUND)


class TestFacultyPagination:
    def test_faculty_list_pagination_envelope(self, api):
        """PRD 2.3: "A `limit` outside the range 1 through 100, or a negative
        `offset`, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400). The
        `meta` object of a list response carries `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/entities/faculty_list_pagination_envelope
        """
        dept = create_department()
        create_faculty(dept["id"], employee_number="F100")
        create_faculty(dept["id"], employee_number="F200",
                       academic_rank="ASSISTANT_PROFESSOR", annual_base_salary=100000.00)
        create_faculty(dept["id"], employee_number="F300",
                       academic_rank="FULL_PROFESSOR", annual_base_salary=140000.00)

        rows, meta = validate_paginated(
            api.list_faculty_members(ADMIN, params={"limit": 1, "offset": 1})
        )
        assert len(rows) == 1
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 1
        assert meta["offset"] == 1

        for bad_params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
            resp = api.list_faculty_members(ADMIN, params=bad_params)
            validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION)


class TestDoubleSeparation:
    def test_faculty_double_separation_rejected(self, api):
        """PRD 3.9: "A `LeaveAdministrator` separates a faculty member by
        supplying a `separation_date`; the member must not already be
        `SEPARATED` (`ERR_INVALID_FACULTY_STATE`)."

        Design: Corner/validations/faculty_double_separation_rejected
        """
        dept = create_department()
        faculty = create_faculty(dept["id"])
        separate_faculty(faculty["id"], "2026-08-01T00:00:00Z")
        again = api.separate_faculty_member(
            faculty["id"], {"separation_date": "2026-08-02T00:00:00Z"}, ADMIN
        )
        validate_error(again, ApiErrorId.ERR_INVALID_FACULTY_STATE)


class TestAccrualGapMonths:
    def test_leave_covered_months_are_never_backfilled(self, api):
        """PRD 3.2: "A month is covered when some grant of the faculty in
        `ACTIVE`, `COMPLETED`, or `CURTAILED` status has a half-open window
        containing the first day of that month."
        PRD 3.2: "Months that go unearned — leave-covered, overdue-blocked, or
        post-separation — are never backfilled; regardless of earnings, the
        member's `last_accrued_month` advances to the through-month."
        PRD 3.9: "For each `IN_PROGRESS` obligation whose faculty member is
        `ACTIVE`, the run credits one additional `fulfilled_months` for every
        whole month after `last_credited_month` up to and including the month
        before the clock's current month"

        Design: Corner/calculations/accrual_gap_months_on_leave_not_backfilled
        """
        dept = create_department()
        faculty = create_faculty(dept["id"], hire_date="2026-06-01T00:00:00Z")
        run0 = validate_success(api.run_accruals({}, ADMIN))
        # Watermark starts at 2026-05 (month before hire month); through-month
        # 2026-07 -> earns 2026-06 and 2026-07.
        assert run0["earn_entries_created"] == 2

        # PROFESSIONAL leave 2026-09-01..2027-03-01, activated and completed.
        app = create_application(
            faculty["id"],
            leave_type="PROFESSIONAL",
            requested_duration_semesters=1,
            requested_salary_pct=100,
            proposed_start_date="2026-09-01T00:00:00Z",
            proposed_end_date="2027-03-01T00:00:00Z",
        )
        submit_application(app["id"], faculty["id"])
        decide_application(app["id"], "APPROVED")
        grant = grant_for_application(app["id"])
        activate_grant_at(grant["id"], "2026-09-01T00:00:00Z")
        complete_grant_at(grant["id"], "2027-03-01T00:00:00Z")

        set_clock("2027-04-15T00:00:00Z")
        run1 = validate_success(api.run_accruals({}, ADMIN))
        # Months (2026-07, 2027-03]: only 2026-08 and 2027-03 earn; the six
        # leave-covered months 2026-09..2027-02 are permanently skipped.
        assert run1["earn_entries_created"] == 2
        # Obligation (required 6, watermark 2027-02): only 2027-03 credits.
        assert run1["obligation_months_credited"] == 1

        fresh = validate_success(api.get_faculty_member(faculty["id"], ADMIN))
        assert fresh["credit_balance"] == 4
        assert fresh["lifetime_service_months"] == 4

        obligations, _ = validate_paginated(
            api.list_service_obligations(ADMIN, params={"faculty_id": faculty["id"]})
        )
        assert len(obligations) == 1
        assert obligations[0]["required_months"] == 6
        assert obligations[0]["fulfilled_months"] == 1


class TestAccrualFrozenWhileReportOverdue:
    def test_overdue_report_blocks_earnings_and_watermark_advances(self, api):
        """PRD 3.2: "A run-time check blocks the member entirely if any of
        their accomplishment reports is `OVERDUE`"
        PRD 3.2: "Months that go unearned — leave-covered, overdue-blocked, or
        post-separation — are never backfilled; regardless of earnings, the
        member's `last_accrued_month` advances to the through-month."
        PRD 3.9: "submitting from `OVERDUE` sets `submitted_late` true"

        Design: Corner/calculations/accrual_frozen_while_report_overdue
        """
        ctx = setup_full_award(courses_to_cover=3, award_quota=1)
        faculty = ctx["faculty"]
        grant = ctx["grant"]
        activate_grant_at(grant["id"], grant["start_date"])
        complete_grant_at(grant["id"], grant["end_date"])

        # Report due 2027-09-29; sweep at 2027-10-01 flips it OVERDUE.
        set_clock("2027-10-01T00:00:00Z")
        reports, _ = validate_paginated(
            api.list_accomplishment_reports(ADMIN, params={"faculty_id": faculty["id"]})
        )
        assert len(reports) == 1
        report = reports[0]
        assert report["status"] == "OVERDUE"

        run1 = validate_success(api.run_accruals({}, ADMIN))
        # PRD 3.2 blocks "the member entirely" — the block is per-member, so
        # the run-level earn total still includes the other (unblocked)
        # faculty. Obligation crediting is not report-gated: the ON_LEAVE
        # months 2027-01..2027-06 precede the obligation watermark, so
        # 2027-07..2027-09 credit.
        assert run1["obligation_months_credited"] == 3
        # The blocked member earns nothing, yet the watermark still advances
        # to the through-month 2027-09 (months 2026-08..2027-09 are lost).
        blocked = validate_success(api.get_faculty_member(faculty["id"], ADMIN))
        assert blocked["credit_balance"] == 36  # 72 earned - 36 consumed
        assert blocked["lifetime_service_months"] == 72
        assert blocked["last_accrued_month"] == "2027-09"

        late = validate_success(
            api.submit_accomplishment_report(
                report["id"], {"report_text": "Late accomplishments."},
                make_faculty_headers(faculty["id"]),
            )
        )
        assert late["submitted_late"] is True

        set_clock("2027-11-15T00:00:00Z")
        run2 = validate_success(api.run_accruals({}, ADMIN))

        fresh = validate_success(api.get_faculty_member(faculty["id"], ADMIN))
        # Watermark was 2027-09, so the blocked months are never backfilled:
        # only 2027-10 earns now that the report is clear.
        # 72 earned - 36 consumed + 1 = 37.
        assert fresh["credit_balance"] == 37
        assert fresh["last_accrued_month"] == "2027-10"


class TestCertifiedVsProvisionalEligibility:
    def test_eligibility_read_diverges_certified_vs_provisional(self, api):
        """PRD 3.2: "The certified figure is the accrued reality — the same
        chronological actuals carried on `lifetime_service_months` — and the
        authoritative submission gate (§3.3) requires at least seventy-two
        certified months for a sabbatical. The provisional figure is
        forward-looking: it adds to the certified months the whole months from
        the month after `last_accrued_month` through the month before the
        proposed start date, assuming the member remains `ACTIVE` throughout.
        Identical ledger data can therefore yield `eligible_provisional` true
        while `eligible_certified` is still false; only the certified number
        opens the submission gate."

        Design: Difficulty/dual_variant_calc/certified_vs_provisional_eligibility_diverge
        """
        dept = create_department()
        faculty = create_faculty(dept["id"], hire_date="2020-09-01T00:00:00Z")
        run_accruals()
        # 2020-09..2026-07 = 71 certified months.
        eligibility = validate_success(
            api.get_faculty_eligibility(
                faculty["id"], ADMIN,
                params={"proposed_start_date": "2027-01-01T00:00:00Z"},
            )
        )
        assert eligibility["certified_service_months"] == 71
        # 71 + projected 2026-08..2026-12 = 76.
        assert eligibility["provisional_service_months"] == 76
        assert eligibility["eligible_certified"] is False
        assert eligibility["eligible_provisional"] is True

    def test_submit_gate_uses_certified_variant(self, api):
        """PRD 3.3: "A sabbatical demands at least seventy-two certified
        service months on `lifetime_service_months`
        (`ERR_INSUFFICIENT_SERVICE_MONTHS`)"
        PRD 3.2: "only the certified number opens the submission gate."

        Design: Difficulty/dual_variant_calc/certified_vs_provisional_eligibility_diverge
        """
        dept = create_department()
        faculty = create_faculty(dept["id"], hire_date="2020-09-01T00:00:00Z")
        run_accruals()
        cycle = open_cycle(create_cycle()["id"])
        app = create_application(
            faculty["id"],
            leave_type="SABBATICAL",
            cycle_id=cycle["id"],
            requested_duration_semesters=1,
            requested_salary_pct=100,
            proposed_start_date="2027-01-01T00:00:00Z",
            proposed_end_date="2027-07-01T00:00:00Z",
        )
        resp = api.submit_leave_application(app["id"], make_faculty_headers(faculty["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SERVICE_MONTHS)


class TestCreditLedgerConservation:
    def test_award_consume_deducts_36_and_leaves_lifetime(self, api):
        """PRD 3.2: "A sabbatical award posts a `CONSUME` entry of negative
        thirty-six credits per semester"
        PRD 3.2: "`CONSUME` and `RESTORE` never touch the lifetime figure."

        Design: Difficulty/compensating_invariant/credit_ledger_consume_restore_conservation
        """
        ctx = setup_full_award(courses_to_cover=3, award_quota=1)
        faculty = ctx["faculty"]
        fresh = validate_success(api.get_faculty_member(faculty["id"], ADMIN))
        assert fresh["credit_balance"] == 36  # 72 earned - 36 consumed
        assert fresh["lifetime_service_months"] == 72

    def test_cancellation_restore_returns_balance_exactly(self, api):
        """PRD 3.2: "a cancellation restores the full thirty-six per semester
        and a curtailment restores six per unused month, so a consume followed
        by its matching restore leaves `credit_balance` exactly where it stood
        before the pair."
        PRD 3.2: "`credit_balance` is the sum of `credits_delta` over all of
        the faculty's entries"

        Design: Difficulty/compensating_invariant/credit_ledger_consume_restore_conservation
        """
        ctx = setup_full_award(courses_to_cover=3, award_quota=1)
        faculty = ctx["faculty"]
        separate_faculty(faculty["id"], "2026-12-15T00:00:00Z")

        fresh = validate_success(api.get_faculty_member(faculty["id"], ADMIN))
        assert fresh["credit_balance"] == 72
        assert fresh["lifetime_service_months"] == 72

        entries, _ = validate_paginated(
            api.list_accrual_ledger_entries(faculty["id"], ADMIN, params={"limit": 100})
        )
        deltas = {(e["entry_type"], e["credits_delta"]) for e in entries}
        assert ("CONSUME", -36) in deltas
        assert ("RESTORE", 36) in deltas
        assert sum(e["credits_delta"] for e in entries) == 72
