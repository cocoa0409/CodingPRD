"""Case filing preconditions and automatic-stay activation.

PRD §3.4 / §2.7. Tests cover ERR_SCHEDULES_INCOMPLETE,
ERR_MEANS_TEST_NOT_RUN, ERR_PRESUMPTION_OF_ABUSE, the four side
effects of file_case, and chapter_effective assignment.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_case,
    create_debtor,
    file_case,
    income_line,
    make_debtor_headers,
    re_get_case,
    run_means_test,
    setup_draft_case_filing_ready,
    submit_all_other_schedules,
    submit_schedule,
    submit_schedule_i,
    submit_schedule_j,
    validate_error,
    validate_success,
)


# ===========================================================================
# ERR_SCHEDULES_INCOMPLETE — PRD §3.4
# ===========================================================================
class TestScheduleCompletenessGate:
    """PRD §3.4: 'schedule_completeness must be the empty list (any
    missing letter yields ERR_SCHEDULES_INCOMPLETE)'."""

    def test_file_with_missing_schedule_letter_rejected(self, api):
        """PRD §3.4: "schedule_completeness must be the empty list
        (any missing letter yields ERR_SCHEDULES_INCOMPLETE)".

        Claim: file_case with at least one missing schedule ->
        ERR_SCHEDULES_INCOMPLETE.
        """
        debtor = create_debtor(state_code="TX", household_size=1)
        case = create_case(debtor=debtor, chapter_requested="CHAPTER_7")
        # Submit only some schedules (omit J).
        for letter in ["A", "B", "C", "D", "E", "F", "G", "H"]:
            submit_schedule(
                case=case, debtor=debtor, schedule_type=letter,
                line_items=[],
            )
        submit_schedule_i(
            case=case, debtor=debtor, per_month_cents=200_000,
        )
        # J intentionally missing.
        run_means_test(case=case, debtor=debtor)
        resp = api.file_case(
            case["id"], None, make_debtor_headers(debtor["id"]),
        )
        # PRD §2.6 lists 'schedule completeness ... before DRAFT→FILED'
        # at priority 9, AFTER state (priority 4) and means-test-not-run
        # in some sequencing. But running means_test before file_case
        # already established the case has a MeansTestResult, so the
        # remaining gate is the schedules. Schedules gate fires first
        # per PRD §3.4 ordering ("schedule_completeness must be the
        # empty list ...; case must have an active MeansTestResult ...;
        # only when chapter_requested is CHAPTER_7, the means-test
        # result's presumption_of_abuse must be false"). Since
        # means_test already ran, only the schedule gate is failing.
        validate_error(resp, ApiErrorId.ERR_SCHEDULES_INCOMPLETE.value)


# ===========================================================================
# ERR_MEANS_TEST_NOT_RUN — PRD §3.4
# ===========================================================================
class TestMeansTestNotRun:
    """PRD §3.4: 'the case must have an active MeansTestResult
    referenced by means_test_result_id (absence yields
    ERR_MEANS_TEST_NOT_RUN)'."""

    def test_file_without_running_means_test_rejected(self, api):
        """PRD §3.4: "the case must have an active MeansTestResult
        referenced by means_test_result_id (absence yields
        ERR_MEANS_TEST_NOT_RUN)".

        Claim: with all schedules complete but means_test never run,
        file_case -> ERR_MEANS_TEST_NOT_RUN.
        """
        # All ten schedules but DON'T run the means test.
        debtor, case, _sch, _mtr = setup_draft_case_filing_ready(
            run_means=False,
        )
        resp = api.file_case(
            case["id"], None, make_debtor_headers(debtor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MEANS_TEST_NOT_RUN.value)


# ===========================================================================
# ERR_PRESUMPTION_OF_ABUSE — PRD §3.4
# ===========================================================================
class TestPresumptionGate:
    """PRD §3.4: 'only when chapter_requested is CHAPTER_7, the
    means-test result's presumption_of_abuse must be false (a true
    value at this point yields ERR_PRESUMPTION_OF_ABUSE and the
    Chapter 7 filing is blocked)'."""

    def test_chapter_7_blocked_when_presumption_true(self, api):
        """PRD §3.4: "only when chapter_requested is CHAPTER_7, the
        means-test result's presumption_of_abuse must be false (a true
        value at this point yields ERR_PRESUMPTION_OF_ABUSE and the
        Chapter 7 filing is blocked)".

        Claim: Ch7 + presumption_of_abuse=true -> ERR_PRESUMPTION_OF_ABUSE
        # difficulty: dual_variant_calc/means_test_chapter7_vs_chapter13_variants
        """
        # TX hh=1 median 6,000,000. Income 510_000/mo -> annualized
        # 6,120,000 -> presumption true.
        debtor, case, _sch, mtr = setup_draft_case_filing_ready(
            state_code="TX", household_size=1,
            chapter_requested="CHAPTER_7",
            income_amounts_cents=[510_000] * 6,
            monthly_expenses_cents=300_000,
        )
        assert mtr["presumption_of_abuse"] is True
        resp = api.file_case(
            case["id"], None, make_debtor_headers(debtor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PRESUMPTION_OF_ABUSE.value)

    def test_chapter_13_not_blocked_by_presumption(self, api):
        """PRD §3.3: "When the case is being filed under
        chapter_requested of CHAPTER_7, only the presumption-of-abuse
        flag is consulted at the filing gate; the disposable-income
        side of the calculation is ignored for that decision."
        PRD §3.4: "only when chapter_requested is CHAPTER_7, the
        means-test result's presumption_of_abuse must be false (a true
        value at this point yields ERR_PRESUMPTION_OF_ABUSE and the
        Chapter 7 filing is blocked)."

        Claim: a Ch13 case with presumption_of_abuse=true still
        files successfully (presumption gate is Ch7-only).
        # difficulty: dual_variant_calc/means_test_chapter7_vs_chapter13_variants
        """
        debtor, case, _sch, mtr = setup_draft_case_filing_ready(
            state_code="TX", household_size=1,
            chapter_requested="CHAPTER_13",
            income_amounts_cents=[510_000] * 6,
            monthly_expenses_cents=300_000,
        )
        assert mtr["presumption_of_abuse"] is True
        case_after = file_case(case=case, debtor=debtor)
        assert case_after["status"] == "FILED"


# ===========================================================================
# Filing side effects — PRD §3.4
# ===========================================================================
class TestFileCaseSideEffects:
    """PRD §3.4: 'the server commits four side effects atomically. The
    filing_date is set to the server's current clock. The
    chapter_effective is set to CHAPTER_7 when the requested chapter
    was CHAPTER_7 (the presumption check has already cleared) and to
    CHAPTER_13 otherwise — note that a debtor who explicitly requested
    CHAPTER_13 always ends up under that chapter regardless of
    presumption. The automatic_stay_active flag flips from false to
    true.'"""

    def test_file_case_sets_filing_date_and_status(self, api):
        """PRD §3.4: "The filing_date is set to the server's current
        clock."

        Claim: after file_case, status=FILED and filing_date is set.
        """
        debtor, case, _sch, _mtr = setup_draft_case_filing_ready(
            state_code="TX", household_size=1,
            chapter_requested="CHAPTER_7",
            monthly_income_cents=200_000,
            monthly_expenses_cents=100_000,
        )
        result = file_case(case=case, debtor=debtor)
        assert result["status"] == "FILED"
        assert result.get("filing_date"), (
            "filing_date should be set after file_case; got "
            f"{result.get('filing_date')!r}"
        )

    def test_file_case_flips_automatic_stay_active(self, api):
        """PRD §3.4: "The automatic_stay_active flag flips from false
        to true."

        Claim: automatic_stay_active was false in DRAFT and is true
        after file_case.
        """
        debtor, case, _sch, _mtr = setup_draft_case_filing_ready()
        assert case["automatic_stay_active"] is False
        result = file_case(case=case, debtor=debtor)
        assert result["automatic_stay_active"] is True

    def test_chapter_7_request_yields_chapter_7_effective(self, api):
        """PRD §3.4: "The chapter_effective is set to CHAPTER_7 when
        the requested chapter was CHAPTER_7 (the presumption check has
        already cleared) and to CHAPTER_13 otherwise".

        Claim: chapter_requested=CHAPTER_7 + presumption false ->
        chapter_effective=CHAPTER_7.
        """
        debtor, case, _sch, _mtr = setup_draft_case_filing_ready(
            chapter_requested="CHAPTER_7",
            monthly_income_cents=200_000,
            monthly_expenses_cents=100_000,
        )
        result = file_case(case=case, debtor=debtor)
        assert result["chapter_effective"] == "CHAPTER_7"

    def test_chapter_13_request_yields_chapter_13_effective(self, api):
        """PRD §3.4: "a debtor who explicitly requested CHAPTER_13
        always ends up under that chapter regardless of presumption."

        Claim: chapter_requested=CHAPTER_13 -> chapter_effective=
        CHAPTER_13.
        """
        debtor, case, _sch, _mtr = setup_draft_case_filing_ready(
            chapter_requested="CHAPTER_13",
            monthly_income_cents=200_000,
            monthly_expenses_cents=100_000,
        )
        result = file_case(case=case, debtor=debtor)
        assert result["chapter_effective"] == "CHAPTER_13"


# ===========================================================================
# Filing wrong-state — PRD §2.6
# ===========================================================================
class TestFileWrongState:
    """PRD §2.6: 'State-machine eligibility is checked fourth: a
    target resource in a state from which the requested transition is
    undefined yields ERR_INVALID_STATE.'"""

    def test_file_already_filed_case_rejected(self, api):
        """PRD §2.6: "a target resource in a state from which the
        requested transition is undefined yields ERR_INVALID_STATE".

        Claim: calling file_case on a case already FILED ->
        ERR_INVALID_STATE.
        """
        debtor, case, _sch, _mtr = setup_draft_case_filing_ready(
            chapter_requested="CHAPTER_13",
            monthly_income_cents=200_000,
            monthly_expenses_cents=100_000,
        )
        file_case(case=case, debtor=debtor)
        resp = api.file_case(
            case["id"], None, make_debtor_headers(debtor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
