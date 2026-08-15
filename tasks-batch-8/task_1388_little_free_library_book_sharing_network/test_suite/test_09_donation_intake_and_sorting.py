"""Donation intake: batch linkage, grading gate, best-effort bulk intake."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_drive,
    create_active_school,
    create_active_steward,
    create_batch,
    get_linked_batch,
    intake_items,
    list_batch_items,
    pin_clock,
    propose_drive,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
HUB = TEST_USERS["hub_headers"]


class TestGradingGate:
    def test_batch_sort_complete_grading_gate_and_fix_path(self, api):
        """PRD §3.8: "The sort-complete step moves the batch from `RECEIVED` to
        `SORTED` only when `graded_count` equals `item_count`, failing with
        `ERR_UNGRADED_ITEMS` while any book is ungraded."
        PRD §3.8: "Grading a single book — setting its `condition_grade` to
        `A`, `B`, or `C` — is permitted only while the book is `AVAILABLE` and
        its batch is still `RECEIVED`, with anything else rejected as
        `ERR_INVALID_STATE`; each grading refreshes the batch's `graded_count`."

        Design: Corner/state_machines/batch_sort_complete_grading_gate_and_fix_path
        """
        pin_clock()
        batch = create_batch()
        intake_items(batch["id"], [
            {"title": "Graded", "category": "FICTION", "condition_grade": "A"},
            {"title": "Ungraded", "category": "FICTION"},
        ])
        items = list_batch_items(batch["id"])
        assert len(items) == 2
        # Items are listed oldest-first; index 1 is the ungraded one.
        ungraded_item = items[1]
        assert ungraded_item["condition_grade"] is None

        res = api.sort_complete_batch(batch["id"], HUB)
        validate_error(res, ApiErrorId.ERR_UNGRADED_ITEMS.value,
                       expected_status=422)

        graded = validate_success(
            api.grade_book_item(ungraded_item["id"], "B", HUB), 200
        )
        assert graded["condition_grade"] == "B"

        sorted_batch = validate_success(
            api.sort_complete_batch(batch["id"], HUB), 200
        )
        assert sorted_batch["status"] == "SORTED"
        assert sorted_batch["graded_count"] == 2
        assert sorted_batch["item_count"] == 2


class TestBulkIntake:
    def test_bulk_items_partial_success_semantics(self, api):
        """PRD §3.8: "Within the array, every element is judged on its own: an
        item whose category appears in the partner school's
        `restricted_categories` is rejected individually with
        `ERR_CONTENT_POLICY_VIOLATION`, and malformed entries fail individually
        too, while their valid siblings are still created."
        PRD §3.8: "The response reports a `created_count`, the
        `created_item_ids`, and a `rejected` array pairing each failure's
        `index` with its `error_id`."

        Design: Corner/endpoints/bulk_items_partial_success_semantics
        """
        pin_clock()
        batch = create_batch()
        summary = validate_success(
            api.intake_batch_items(batch["id"], [
                {"title": "Good Book", "category": "FICTION",
                 "condition_grade": "A"},
                {"category": "FICTION", "condition_grade": "B"},  # no title
            ], HUB),
            200,
        )
        assert summary["created_count"] == 1
        rejected_by_index = {entry["index"]: entry["error_id"]
                             for entry in summary["rejected"]}
        assert rejected_by_index == {1: "ERR_INVALID_REQUEST"}

        items = list_batch_items(batch["id"])
        assert len(items) == 1
        assert items[0]["title"] == "Good Book"
        assert items[0]["status"] == "AVAILABLE"

class TestBatchLinkage:
    def test_batch_drive_link_required_and_forbidden(self, api):
        """PRD §3.8: "The drive linkage is strict: a `BOOK_DRIVE` batch without
        a `drive_id` is rejected with `ERR_DRIVE_LINK_REQUIRED`, and a
        `drive_id` attached to any other source type is rejected with
        `ERR_DRIVE_LINK_FORBIDDEN`."

        Design: Corner/validations/batch_drive_link_required_and_forbidden
        """
        pin_clock()
        res1 = api.create_batch(
            {"source_type": "BOOK_DRIVE", "region_code": "OR"}, HUB
        )
        validate_error(res1, ApiErrorId.ERR_DRIVE_LINK_REQUIRED.value,
                       expected_status=422)

        res2 = api.create_batch(
            {
                "source_type": "PUBLIC_DROP",
                "drive_id": "00000000-0000-4000-8000-0000000000cc",
                "region_code": "OR",
            },
            HUB,
        )
        validate_error(res2, ApiErrorId.ERR_DRIVE_LINK_FORBIDDEN.value,
                       expected_status=422)

    def test_batch_for_proposed_drive_rejected_not_approved(self, api):
        """PRD §3.8: "the referenced drive must stand in `APPROVED` or `OPEN`,
        failing with `ERR_DRIVE_NOT_APPROVED` otherwise."

        Design: Corner/validations/batch_for_proposed_drive_rejected_not_approved
        """
        pin_clock()
        steward = create_active_steward(full_name="Link Tester",
                                        email="link@example.org")
        school = create_active_school(name="Link School")
        drive = propose_drive(school["id"], steward["id"], goal_books=5)

        res = api.create_batch(
            {"source_type": "BOOK_DRIVE", "drive_id": drive["id"],
             "region_code": "OR"},
            HUB,
        )
        validate_error(res, ApiErrorId.ERR_DRIVE_NOT_APPROVED.value,
                       expected_status=409)

    def test_drive_intake_rejected_when_drive_not_open(self, api):
        """PRD §3.8: "intake into a drive-linked batch faces two more gates:
        the drive must be `OPEN` (`ERR_DRIVE_NOT_OPEN`) and the current instant
        must fall before the drive's `ends_at` (`ERR_DRIVE_WINDOW_CLOSED`)."

        Design: Corner/errors/drive_intake_rejected_when_drive_not_open
        """
        pin_clock()
        steward = create_active_steward(full_name="Not Open",
                                        email="no@example.org")
        school = create_active_school(name="NO School")
        drive = propose_drive(school["id"], steward["id"], goal_books=5,
                              starts_at="2026-09-01T00:00:00Z",
                              ends_at="2026-10-01T00:00:00Z")
        approve_drive(drive["id"], school["id"])  # APPROVED, not swept to OPEN
        batch = get_linked_batch(drive["id"])

        res = api.intake_batch_items(batch["id"], [
            {"title": "Early", "category": "FICTION", "condition_grade": "A"},
        ], HUB)
        validate_error(res, ApiErrorId.ERR_DRIVE_NOT_OPEN.value,
                       expected_status=409)


class TestFieldValidation:
    def test_invalid_enum_rejected(self, api):
        """PRD §2.8: "Schema and field validity. Required fields are present,
        enum members are valid, and numeric ranges hold — failure is
        `ERR_INVALID_REQUEST` (400)."
        PRD §3.5: "Anyone — a passer-by, a steward, a moderator — reports an
        issue by naming the `box_id`, a `category` of `WEATHER_DAMAGE`,
        `VANDALISM`, `WEAR`, or `INSTALLATION_DEFECT`, and a free-text
        `description`."

        Design: Corner/validations/invalid_enum_rejected
        """
        pin_clock()
        steward = create_active_steward(full_name="Enum Tester",
                                        email="enum@example.org")
        from test_helpers import create_chartered_box

        box = create_chartered_box(steward, name="Enum Box")
        res = api.create_maintenance_request(
            {"box_id": box["id"], "category": "FLOOD",
             "description": "Water damage"},
            {},
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value,
                       expected_status=400)
