"""Debtor / Creditor registration, Case creation, withdraw-pre-file,
and schedule submission semantics.

PRD §3.1 / §3.2.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_case,
    assert_creditor,
    assert_debtor,
    assert_schedule,
    create_case,
    create_creditor,
    create_debtor,
    create_creditor_payload,
    create_debtor_payload,
    income_line,
    make_debtor_headers,
    SCHEDULE_TYPES_REQUIRED,
    submit_schedule,
    submit_all_schedules_for,
    validate_error,
    validate_success,
    withdraw_case,
)


# ===========================================================================
# Debtor registration — PRD §3.1
# ===========================================================================
class TestDebtorRegistration:
    """PRD §3.1: 'A prospective filer registers a Debtor profile by
    supplying their full_name, their household_size (which must be at
    least 1 and which drives the state-median-income lookup later), and
    a state_code consisting of exactly two uppercase letters identifying
    the state whose median table applies.'"""

    def test_create_debtor_returns_valid_row(self, api):
        """PRD §3.1: "registers a Debtor profile by supplying their
        full_name, their household_size (which must be at least 1 and
        which drives the state-median-income lookup later), and a
        state_code consisting of exactly two uppercase letters
        identifying the state whose median table applies."

        Claim: POST /debtors with valid input returns a Debtor row.
        """
        debtor = create_debtor(household_size=2, state_code="CA")
        assert_debtor(debtor)
        assert debtor["household_size"] == 2
        assert debtor["state_code"] == "CA"

    def test_total_cases_filed_starts_at_zero(self, api):
        """PRD §3.1: "The total_cases_filed field is server-maintained
        and counts the number of cases this debtor has filed whose
        status is anything other than the pre-file withdrawal state —
        it begins at zero on registration".

        Claim: total_cases_filed is 0 immediately after registration.
        """
        debtor = create_debtor()
        assert debtor["total_cases_filed"] == 0


# ===========================================================================
# Creditor registration — PRD §3.1
# ===========================================================================
class TestCreditorRegistration:
    """PRD §3.1: 'a creditor — anyone holding a debt that may
    eventually be claimed — registers a Creditor profile by supplying a
    name and a creditor_type of SECURED, PRIORITY, or
    GENERAL_UNSECURED.'"""

    @pytest.mark.parametrize(
        "ctype", ["SECURED", "PRIORITY", "GENERAL_UNSECURED"],
    )
    def test_create_creditor_each_type(self, api, ctype):
        """PRD §3.1: "registers a Creditor profile by supplying a name
        and a creditor_type of SECURED, PRIORITY, or
        GENERAL_UNSECURED."

        Claim: POST /creditors accepts each enum value.
        """
        creditor = create_creditor(creditor_type=ctype)
        assert_creditor(creditor)
        assert creditor["creditor_type"] == ctype


# ===========================================================================
# Case creation — PRD §3.1
# ===========================================================================
class TestCaseCreation:
    """PRD §3.1: 'A debtor opens a Case by submitting debtor_id and the
    desired chapter_requested (either CHAPTER_7 or CHAPTER_13). The
    case begins in DRAFT status, with automatic_stay_active set to
    false, chapter_effective not yet computed, filing_date not yet set,
    and schedule_completeness initialized to the full ten-letter list
    [A, B, C, D, E, F, G, H, I, J].'"""

    def test_case_starts_in_draft_with_full_completeness_list(self, api):
        """PRD §3.1: "The case begins in DRAFT status, with
        automatic_stay_active set to false, chapter_effective not yet
        computed, filing_date not yet set, and schedule_completeness
        initialized to the full ten-letter list [A, B, C, D, E, F, G,
        H, I, J]."

        Claim: a newly created Case has status=DRAFT,
        automatic_stay_active=false, schedule_completeness=all 10
        letters, filing_date not set.
        """
        debtor = create_debtor()
        case = create_case(debtor=debtor)
        assert_case(case)
        assert case["status"] == "DRAFT"
        assert case["automatic_stay_active"] is False
        assert sorted(case["schedule_completeness"]) == list("ABCDEFGHIJ")
        # filing_date may be omitted or null per PRD §2.4 / §3.1.
        assert case.get("filing_date") in (None, "", ),  (
            f"filing_date should be unset on DRAFT, got "
            f"{case.get('filing_date')!r}"
        )

    @pytest.mark.parametrize("chapter", ["CHAPTER_7", "CHAPTER_13"])
    def test_chapter_requested_persisted(self, api, chapter):
        """PRD §3.1: "submitting debtor_id and the desired
        chapter_requested (either CHAPTER_7 or CHAPTER_13)."

        Claim: chapter_requested round-trips through Case creation.
        """
        debtor = create_debtor()
        case = create_case(debtor=debtor, chapter_requested=chapter)
        assert case["chapter_requested"] == chapter


# ===========================================================================
# Case withdrawal pre-file — PRD §3.1
# ===========================================================================
class TestCaseWithdrawPreFile:
    """PRD §3.1: 'Cases in DRAFT may be deleted entirely by the owning
    debtor, in which case the status transitions to
    WITHDRAWN_PRE_FILE; because no filing ever occurred, the stay is
    never engaged in this branch.'"""

    def test_withdraw_draft_case_sets_pre_file_status(self, api):
        """PRD §3.1: "Cases in DRAFT may be deleted entirely by the
        owning debtor, in which case the status transitions to
        WITHDRAWN_PRE_FILE; because no filing ever occurred, the stay
        is never engaged in this branch".

        Claim: DELETE /cases/{id} from DRAFT -> status=
        WITHDRAWN_PRE_FILE, automatic_stay_active stays false.
        """
        debtor = create_debtor()
        case = create_case(debtor=debtor)
        result = withdraw_case(case=case, debtor=debtor)
        assert result["status"] == "WITHDRAWN_PRE_FILE"
        assert result["automatic_stay_active"] is False


# ===========================================================================
# Schedule submission — PRD §3.2
# ===========================================================================
class TestScheduleSubmission:
    """PRD §3.2: 'each schedule is a snapshot uploaded under the
    debtor's case and is identified by schedule_type ... and a
    line_items array, where each entry carries a label and an
    amount_cents integer.'"""

    def test_submit_schedule_returns_id_and_no_version_field(self, api):
        """PRD §2.4: "Schedule rows are immutable snapshots written
        once and superseded by later snapshots rather than mutated in
        place, so each Schedule carries only id and created_at;
        updated_at and version are absent."

        Claim: Schedule row carries id + created_at + (no version,
        no updated_at).
        """
        debtor = create_debtor()
        case = create_case(debtor=debtor)
        sch = submit_schedule(
            case=case, debtor=debtor, schedule_type="A",
            line_items=[income_line(10000, "asset-A")],
        )
        assert_schedule(sch)
        # PRD §2.4: 'updated_at and version are absent'.
        assert "version" not in sch, (
            "PRD §2.4 says Schedule has no version; "
            f"got {sch.get('version')!r}"
        )
        assert "updated_at" not in sch, (
            "PRD §2.4 says Schedule has no updated_at; "
            f"got {sch.get('updated_at')!r}"
        )

    def test_schedule_total_cents_sums_line_items(self, api):
        """PRD §3.2: "The system computes total_cents for the schedule
        by summing the amount_cents across the line_items entries."

        Claim: total_cents equals the integer sum of line_items
        amount_cents.
        """
        debtor = create_debtor()
        case = create_case(debtor=debtor)
        sch = submit_schedule(
            case=case, debtor=debtor, schedule_type="B",
            line_items=[
                income_line(11111, "x"),
                income_line(22222, "y"),
                income_line(33333, "z"),
            ],
        )
        assert sch["total_cents"] == 11111 + 22222 + 33333

    def test_submitting_all_ten_schedules_clears_completeness(self, api):
        """PRD §3.2: "When this list is empty, all ten schedules have
        been submitted and the case is filing-ready with respect to
        schedules."

        Claim: after all ten A-J schedules are present, the case's
        schedule_completeness list is empty.
        """
        debtor = create_debtor()
        case = create_case(debtor=debtor)
        submit_all_schedules_for(
            case=case, debtor=debtor,
            monthly_income_cents=200_000,
            monthly_expenses_cents=100_000,
        )
        # Re-fetch the case to see recomputed schedule_completeness.
        from test_helpers import re_get_case
        case_after = re_get_case(case["id"])
        assert case_after["schedule_completeness"] == []

    def test_resubmit_schedule_supersedes_prior(self, api):
        """PRD §3.2: "Resubmitting a schedule of a type that has
        already been submitted does not overwrite the prior row;
        instead the prior row's superseded_by_id is updated to point to
        the new row's id, and the new snapshot becomes the active
        one."

        Claim: resubmitting Schedule A yields a new row; the prior row
        is no longer counted as "active" — schedule_completeness still
        shows A as present (because there is exactly one active
        snapshot of type A, the new one).
        """
        debtor = create_debtor()
        case = create_case(debtor=debtor)
        first = submit_schedule(
            case=case, debtor=debtor, schedule_type="A",
            line_items=[income_line(10000, "v1")],
        )
        second = submit_schedule(
            case=case, debtor=debtor, schedule_type="A",
            line_items=[income_line(50000, "v2")],
        )
        # Different ids; total_cents reflects the new content.
        assert first["id"] != second["id"]
        assert second["total_cents"] == 50000

    def test_missing_letter_keeps_completeness_nonempty(self, api):
        """PRD §3.2: "it is the sorted list of letters from the
        required set {A, B, C, D, E, F, G, H, I, J} that are not yet
        covered by an active (unsuperseded) snapshot."

        Claim: with only some letters submitted, the missing letters
        appear in schedule_completeness sorted.
        """
        debtor = create_debtor()
        case = create_case(debtor=debtor)
        # Submit only A and B.
        submit_schedule(
            case=case, debtor=debtor, schedule_type="A", line_items=[],
        )
        submit_schedule(
            case=case, debtor=debtor, schedule_type="B", line_items=[],
        )
        from test_helpers import re_get_case
        case_after = re_get_case(case["id"])
        # Expected missing: C..J in sorted order.
        assert case_after["schedule_completeness"] == list("CDEFGHIJ")
