"""First-day letter: due-date business-day arithmetic, roster preconditions,
overdue counting, and document submission bookkeeping (PRD §3.2, §3.3, §3.8)."""
from test_helpers import (
    RAM,
    ApiErrorId,
    create_agency,
    create_document_submission_payload,
    create_examination,
    create_officer,
    get_exam,
    issue_first_day_letter,
    make_remediation_owner_headers,
    set_logical_clock,
    setup_exam_first_day_issued,
    setup_exam_with_items,
    setup_exam_with_overdue_items,
    validate_error,
    validate_success,
)

class TestFirstDayLetterDueDate:
    def test_friday_start_counts_start_day_as_day_one(self, api):
        """PRD §3.2: "Creation also computes the `first_day_letter_due_date` by
        counting ten business days forward from the scheduled start: when
        `scheduled_start_date` falls on a business day, that day itself counts
        as day one; when it falls on a Saturday or Sunday, the following Monday
        becomes day one. Counting then advances calendar day by calendar day,
        incrementing the count only on business days, until the count reaches
        ten — that tenth business day is the due date, inclusive."

        A Friday 2026-07-03 start counts 7/3 as day 1; the tenth business day is
        Thursday 2026-07-16 — not 2026-07-17 (naive +14 calendar days) and not
        2026-07-15 (start-as-day-0).

        Design: Difficulty/dual_variant_calc/first_day_due_date_business_day_rollover
        """
        agency = create_agency(agency_code="FRB")
        exam = create_examination(
            agency["id"], exam_cycle_code="2026-Q3-COMP", exam_type="COMPLIANCE",
            scheduled_start_date="2026-07-03T00:00:00Z",
            scheduled_end_date="2026-08-01T00:00:00Z")
        due = exam["first_day_letter_due_date"]
        assert due.startswith("2026-07-16"), (
            f"ten business days from Fri 2026-07-03 (day 1) must land on "
            f"2026-07-16, got {due}"
        )
        assert not due.startswith("2026-07-17")
        assert not due.startswith("2026-07-15")

    def test_saturday_start_rolls_day_one_to_monday(self, api):
        """PRD §3.2: "Creation also computes the `first_day_letter_due_date` by
        counting ten business days forward from the scheduled start: when
        `scheduled_start_date` falls on a business day, that day itself counts
        as day one; when it falls on a Saturday or Sunday, the following Monday
        becomes day one. Counting then advances calendar day by calendar day,
        incrementing the count only on business days, until the count reaches
        ten — that tenth business day is the due date, inclusive."

        A Saturday 2026-07-04 start rolls day 1 to Monday 2026-07-06; the tenth
        business day is Friday 2026-07-17.

        Design: Difficulty/dual_variant_calc/first_day_due_date_business_day_rollover
        """
        agency = create_agency(agency_code="FRBW")
        exam = create_examination(
            agency["id"], exam_cycle_code="2026-Q3-WKND", exam_type="COMPLIANCE",
            scheduled_start_date="2026-07-04T00:00:00Z",
            scheduled_end_date="2026-08-01T00:00:00Z")
        due = exam["first_day_letter_due_date"]
        assert due.startswith("2026-07-17"), (
            f"ten business days from Sat 2026-07-04 (day 1 = Mon 7/6) must land "
            f"on 2026-07-17, got {due}"
        )


class TestLetterPreconditions:
    def test_issue_first_day_letter_requires_at_least_one_item(self, api):
        """PRD §3.2: "Otherwise, once the manager has composed the first-day
        roster — at least one first-day item must exist — issuing the first-day
        letter moves the examination `SCHEDULED` → `FIRST_DAY_ISSUED`."
        PRD §2.9: "The target resource's current state permits the requested
        transition — otherwise `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/issue_first_day_letter_requires_at_least_one_item
        """
        agency = create_agency(agency_code="PD")
        exam = create_examination(agency["id"])
        resp = api.issue_first_day_letter(exam["id"], RAM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_begin_fieldwork_blocked_by_pending_items(self, api):
        """PRD §3.3: "Once every first-day item stands `SUBMITTED` or `WAIVED`,
        beginning fieldwork moves the examination `FIRST_DAY_ISSUED` →
        `FIELDWORK`; attempting it with any item still `PENDING` fails the state
        check with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/begin_fieldwork_blocked_by_pending_items
        """
        ctx = setup_exam_first_day_issued()
        resp = api.begin_fieldwork(ctx["exam"]["id"], RAM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestOverdueCountingAndPostureGate:
    def test_item_due_today_is_not_overdue(self, api):
        """PRD §3.8: "first the `overdue_item_count`, the number of the
        examination's first-day items still `PENDING` whose `due_date` falls
        strictly before the current logical date — an item due on the current
        date is not yet overdue"

        Design: Corner/calculations/overdue_count_excludes_items_due_today
        """
        ctx = setup_exam_with_items(
            num_items=1, item_due_date="2026-07-25T00:00:00Z",
            clock_start="2026-07-01T00:00:00Z")
        issue_first_day_letter(ctx["exam"]["id"])
        set_logical_clock("2026-07-25T00:00:00Z")
        exam = get_exam(ctx["exam"]["id"])
        assert exam["overdue_item_count"] == 0, (
            "an item due exactly on the current logical date is not overdue"
        )
        assert exam["posture"] == "NORMAL"

    def test_posture_restricted_at_one_overdue_item(self, api):
        """PRD §3.8: "otherwise it is `RESTRICTED` when at least one first-day
        item is overdue or any milestone stands overdue; otherwise it is
        `NORMAL`."

        Design: Corner/calculations/posture_restricted_at_one_overdue_item
        """
        ctx = setup_exam_with_overdue_items(num_items=1)
        exam = get_exam(ctx["exam"]["id"])
        assert exam["overdue_item_count"] == 1
        assert exam["posture"] == "RESTRICTED", (
            "one overdue item is below the FROZEN threshold of three"
        )

    def test_posture_restricted_blocks_first_day_item_creation(self, api):
        """PRD §3.2: "Two constraints guard item creation: the examination's
        `posture` must be `NORMAL`, because a `RESTRICTED` or `FROZEN`
        examination accepts no new first-day items (`ERR_EXAM_POSTURE_FROZEN`)"

        Design: Corner/validations/posture_restricted_blocks_first_day_item_creation
        """
        ctx = setup_exam_with_overdue_items(num_items=1)
        exam = get_exam(ctx["exam"]["id"])
        assert exam["posture"] == "RESTRICTED"
        resp = api.create_first_day_item(
            ctx["exam"]["id"],
            {"request_ref": "F2", "description": "d",
             "due_date": "2026-08-30T00:00:00Z"},
            RAM)
        validate_error(resp, ApiErrorId.ERR_EXAM_POSTURE_FROZEN)


class TestDocumentSubmissionBookkeeping:
    def test_page_count_total_sums_manifest_and_round_starts_at_one(self, api):
        """PRD §3.3: "The server stamps each accepted submission with its
        `submission_round`, computed as the count of prior submissions against
        the same item plus one, and stores `page_count_total`, the sum of every
        manifest entry's `page_count`, computed once at creation."

        Design: Corner/calculations/page_count_total_sums_manifest
        """
        ctx = setup_exam_first_day_issued(item_due_date="2026-08-15T00:00:00Z")
        officer = create_officer()
        owner_headers = make_remediation_owner_headers(officer["id"])
        item = ctx["items"][0]
        manifest = [
            {"doc_id": "a", "title": "t1", "page_count": 10, "sha256": "h1"},
            {"doc_id": "b", "title": "t2", "page_count": 25, "sha256": "h2"},
            {"doc_id": "c", "title": "t3", "page_count": 7, "sha256": "h3"},
        ]
        resp = api.create_document_submission(
            item["id"],
            create_document_submission_payload(document_manifest=manifest),
            owner_headers)
        data = validate_success(resp, 201)
        assert data["page_count_total"] == 42, "10 + 25 + 7 must sum to 42"
        assert data["submission_round"] == 1
        assert data["quality_status"] == "PENDING_REVIEW"
