"""Lottery guards: execution state, decline state, cross-school ownership, and
per-year uniqueness (PRD §2.1, §3.4)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_open_school, create_lottery, create_open_lottery, add_lottery_entry,
    create_lottery_entry_payload,
    make_staff_headers, make_school_operator_headers, api_client,
)

STAFF = make_staff_headers("staff_1")


class TestLotteryExecuteBeforeSealRejected:
    def test_execute_on_open_lottery_rejected(self, api):
        """PRD §3.4: "Executing a `SEALED` lottery (`SEALED` → `EXECUTED`, same
        invalid-state guard) runs the assignment."
        PRD §3.4: "Each new entry records its `lottery_id`, lands with
        `outcome` `ENTERED` and `rank_position` null"

        Design: Corner/state_machines/sm_lottery_execute_before_seal_rejected
        """
        ctx = create_open_school(school_name="SM Lottery Academy",
                                 applicant_id="applicant_s5")
        lottery = create_open_lottery(ctx["school"]["id"], academic_year=2028, capacity=5)
        entry = add_lottery_entry(lottery["id"], ctx["school"]["id"],
                                  student_ref="stu_s5", preference_codes=[])
        res = api.execute_lottery(lottery["id"], STAFF)
        validate_error(res, ApiErrorId.ERR_LOTTERY_INVALID_STATE, expected_status=409)
        current = validate_success(api.get_lottery(lottery["id"], STAFF), 200)
        assert current["status"] == "OPEN"
        entries = validate_success(api.list_lottery_entries(lottery["id"], STAFF), 200)
        assert entries[0]["id"] == entry["id"]
        assert entries[0]["rank_position"] is None


class TestDeclineEnteredEntryRejected:
    def test_decline_requires_offered_outcome(self, api):
        """PRD §3.4: "When the owning `SchoolOperator` declines an offered seat
        — the entry must be `OFFERED`, else `ERR_ENTRY_INVALID_STATE`, and
        ownership is checked per §2.1 — the entry becomes `DECLINED`"

        Design: Corner/state_machines/sm_decline_entered_entry_rejected
        """
        ctx = create_open_school(school_name="SM Decline Academy",
                                 applicant_id="applicant_s6")
        lottery = create_open_lottery(ctx["school"]["id"], academic_year=2028, capacity=5)
        entry = add_lottery_entry(lottery["id"], ctx["school"]["id"],
                                  student_ref="stu_s6", preference_codes=[])
        assert entry["outcome"] == "ENTERED"
        res = api.decline_entry(entry["id"],
                                make_school_operator_headers(ctx["school"]["id"]))
        validate_error(res, ApiErrorId.ERR_ENTRY_INVALID_STATE, expected_status=409)
        entries = validate_success(api.list_lottery_entries(lottery["id"], STAFF), 200)
        assert entries[0]["outcome"] == "ENTERED"


class TestCrossSchoolOwnershipRejected:
    def test_operator_of_other_school_cannot_add_entry(self, api):
        """PRD §2.1: "Concretely, when a `SchoolOperator` adds a lottery entry,
        declines an offer, submits or resubmits a corrective plan, pays an
        invoice, or files an appeal, the caller's `X-User-ID` must equal the
        owning school's `id` — that is, the lottery entry's lottery's
        `school_id`, the corrective plan's intervention's `school_id`, the
        invoice's `school_id`, or the appeal's `school_id` — and a mismatch is
        rejected with `ERR_RESOURCE_OWNERSHIP_MISMATCH` (HTTP 403)."

        Design: Corner/validations/val_ownership_cross_school_entry_rejected
        """
        ctx_a = create_open_school(school_name="Val Own Academy A",
                                   applicant_id="applicant_v2",
                                   reviewer_id="rev_v2a", panelist_id="rev_panel_v2a",
                                   interview_start="2026-06-12T10:00:00Z",
                                   interview_end="2026-06-12T11:00:00Z")
        ctx_b = create_open_school(school_name="Val Own Academy B",
                                   applicant_id="applicant_v2b",
                                   reviewer_id="rev_v2b", panelist_id="rev_panel_v2b",
                                   interview_start="2026-06-12T12:00:00Z",
                                   interview_end="2026-06-12T13:00:00Z")
        lottery_b = create_open_lottery(ctx_b["school"]["id"], academic_year=2028,
                                        capacity=10)
        res = api.add_lottery_entry(
            lottery_b["id"],
            create_lottery_entry_payload(student_ref="stu_cross"),
            make_school_operator_headers(ctx_a["school"]["id"]))
        validate_error(res, ApiErrorId.ERR_RESOURCE_OWNERSHIP_MISMATCH,
                       expected_status=403)
        entries = validate_success(api.list_lottery_entries(lottery_b["id"], STAFF), 200)
        assert entries == []


class TestDuplicateLotteryYearRejected:
    def test_second_lottery_same_academic_year_rejected(self, api):
        """PRD §2.9: "The aggregate layer also enforces the system's uniqueness
        constraints, each rejected with `ERR_DUPLICATE_RECORD` (HTTP 409): at
        most one score per application, reviewer, and criterion; at most one
        monitoring report per school per `fiscal_year`; at most one lottery per
        school per `academic_year`; at most one fee invoice per school per
        `fiscal_year`; and at most one performance target per combination of
        `contract_id`, `domain`, and `metric_code`."

        Design: Corner/validations/val_duplicate_lottery_year_rejected
        """
        ctx = create_open_school(school_name="Val DupLot Academy",
                                 applicant_id="applicant_v3")
        create_lottery(ctx["school"]["id"], academic_year=2028, capacity=10)
        res = api.create_lottery(ctx["school"]["id"],
                                 {"academic_year": 2028, "capacity": 40}, STAFF)
        validate_error(res, ApiErrorId.ERR_DUPLICATE_RECORD, expected_status=409)
