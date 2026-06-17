"""Lesson occurrence scheduling, completion, cancellation, makeup requests, and the
makeup-credit lifecycle (mint / consume / void / cap).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    TEST_USERS,
    create_makeup_occurrence_payload,
    setup_active_enrollment,
    setup_roster,
    create_enrollment,
    activate_enrollment,
    create_occurrence,
    set_clock,
    create_studio,
    make_parent_guardian_headers,
    make_instructor_headers,
)
from test_helpers import api_client
from test_helpers.factories import (
    create_family_payload,
    create_student_payload,
    create_instructor_payload,
    create_room_payload,
    create_enrollment_payload,
)

ADMIN = TEST_USERS["studio_admin_headers"]


# ===========================================================================
# Difficulty / non_linear_state_machine / occurrence_cyclic_makeup_pending_roundtrip
# ===========================================================================
class TestOccurrenceCyclicMakeupRoundtrip:
    def _setup_makeup_pending(self, api):
        studio, family, student, instructor, room, enr = setup_active_enrollment(
            instructor_overrides={
                "instruments": ["PIANO"],
                "weekly_availability": [
                    {"weekday": 0, "start_min": 0, "end_min": 1440},
                    {"weekday": 1, "start_min": 0, "end_min": 1440},
                ],
                "hourly_rate_cents": 6000,
            }
        )
        sid = studio["id"]
        occ = create_occurrence(sid, enr["id"], "2026-01-26T10:00:00.000Z")
        validate_success(api.request_makeup(sid, occ["id"], ADMIN), 200)
        credits, _ = validate_paginated(
            api.list_makeup_credits(sid, ADMIN, params={"enrollment_id": enr["id"]})
        )
        return sid, occ, credits[0]

    def test_request_makeup_moves_occurrence_to_makeup_pending(self, api):
        """PRD 3.5: "On success the occurrence moves `SCHEDULED → MAKEUP_PENDING` and one
        `OUTSTANDING` makeup credit is minted for the enrollment with its
        `origin_occurrence_id` set to this occurrence."

        Design: Difficulty/non_linear_state_machine/occurrence_cyclic_makeup_pending_roundtrip
        """
        studio, family, student, instructor, room, enr = setup_active_enrollment(
            instructor_overrides={
                "instruments": ["PIANO"],
                "weekly_availability": [{"weekday": 0, "start_min": 0, "end_min": 1440}],
                "hourly_rate_cents": 6000,
            }
        )
        sid = studio["id"]
        occ = create_occurrence(sid, enr["id"], "2026-01-26T10:00:00.000Z")
        pending = validate_success(api.request_makeup(sid, occ["id"], ADMIN), 200)
        assert pending["status"] == "MAKEUP_PENDING"
        credits, meta = validate_paginated(
            api.list_makeup_credits(sid, ADMIN, params={"enrollment_id": enr["id"]})
        )
        assert meta["total_count"] == 1
        assert credits[0]["status"] == "OUTSTANDING"

    def test_scheduling_makeup_consumes_credit_and_restores_origin(self, api):
        """PRD 3.6: "On success the system creates a new `LessonOccurrence` with
        `is_makeup` set to true and `consumed_credit_id` pointing at the credit, moves
        the credit `OUTSTANDING → CONSUMED`, and restores the origin occurrence from
        `MAKEUP_PENDING → SCHEDULED`".

        Design: Difficulty/non_linear_state_machine/occurrence_cyclic_makeup_pending_roundtrip
        """
        sid, occ, credit = self._setup_makeup_pending(api)
        makeup = validate_success(
            api.create_makeup_occurrence(
                sid,
                create_makeup_occurrence_payload(credit["id"], "2026-01-27T10:00:00.000Z"),
                ADMIN,
            ),
            201,
        )
        assert makeup["is_makeup"] is True
        origin = validate_success(api.get_occurrence(sid, occ["id"], ADMIN), 200)
        assert origin["status"] == "SCHEDULED"
        credit_after = validate_success(api.get_makeup_credit(sid, credit["id"], ADMIN), 200)
        assert credit_after["status"] == "CONSUMED"


# ===========================================================================
# Difficulty / boundary_precision_check / cancellation_notice_exact_24h_earns_credit
# ===========================================================================
class TestCancellationNoticeBoundary:
    def _setup_occ_at_exact_notice(self, api, clock_iso):
        studio, family, student, instructor, room, enr = setup_active_enrollment(
            instructor_overrides={
                "instruments": ["PIANO"],
                "weekly_availability": [
                    {"weekday": 0, "start_min": 0, "end_min": 1440},
                    {"weekday": 1, "start_min": 0, "end_min": 1440},
                ],
                "hourly_rate_cents": 6000,
            },
            enrollment_overrides={"weekday": 1, "start_min": 900, "duration_min": 60},
        )
        sid = studio["id"]
        occ = create_occurrence(sid, enr["id"], "2026-01-20T15:00:00.000Z")
        set_clock(sid, clock_iso)
        return sid, enr, occ

    def test_cancel_exactly_24h_before_takes_notice_branch(self, api):
        """PRD 3.5: "When the gap from the studio clock to `scheduled_start_utc` is at
        least `cancellation_notice_hours`, the cancellation is timely: the occurrence
        moves `SCHEDULED → CANCELLED_NOTICE` and the system mints one `OUTSTANDING`
        makeup credit for the enrollment".

        Design: Difficulty/boundary_precision_check/cancellation_notice_exact_24h_earns_credit
        """
        # Exactly 24h before the 15:00 start.
        sid, enr, occ = self._setup_occ_at_exact_notice(api, "2026-01-19T15:00:00.000Z")
        cancelled = validate_success(api.cancel_occurrence(sid, occ["id"], ADMIN), 200)
        assert cancelled["status"] == "CANCELLED_NOTICE"

    def test_cancel_exactly_24h_before_mints_outstanding_credit(self, api):
        """PRD 3.5: "the occurrence moves `SCHEDULED → CANCELLED_NOTICE` and the system
        mints one `OUTSTANDING` makeup credit for the enrollment — provided the
        enrollment's outstanding-credit count is below `makeup_credit_cap_per_enrollment`".

        Design: Difficulty/boundary_precision_check/cancellation_notice_exact_24h_earns_credit
        """
        sid, enr, occ = self._setup_occ_at_exact_notice(api, "2026-01-19T15:00:00.000Z")
        validate_success(api.cancel_occurrence(sid, occ["id"], ADMIN), 200)
        credits, meta = validate_paginated(
            api.list_makeup_credits(sid, ADMIN, params={"enrollment_id": enr["id"]})
        )
        assert meta["total_count"] == 1
        assert credits[0]["status"] == "OUTSTANDING"


# ===========================================================================
# Difficulty / cross_entity_state_dependency / complete_occurrence_requires_active_enrollment
# ===========================================================================
class TestCompleteRequiresActiveEnrollment:
    def _setup_frozen_with_past_scheduled_occ(self, api):
        # Occurrence in the past, then freeze (freeze only cancels occurrences at/after
        # the clock, so this past occurrence stays SCHEDULED).
        studio, family, student, instructor, room, enr = setup_active_enrollment(
            instructor_overrides={
                "instruments": ["PIANO"],
                "weekly_availability": [{"weekday": 0, "start_min": 0, "end_min": 1440}],
                "hourly_rate_cents": 6000,
            }
        )
        sid = studio["id"]
        occ = create_occurrence(sid, enr["id"], "2026-01-05T10:00:00.000Z")
        set_clock(sid, "2026-01-06T00:00:00.000Z")
        validate_success(api.freeze_enrollment(sid, enr["id"], ADMIN), 200)
        return sid, instructor, occ

    def test_complete_under_frozen_enrollment_rejected(self, api):
        """PRD 3.5: "It requires the occurrence to be `SCHEDULED`, else
        `ERR_INVALID_STATE`; the studio clock to be at or after `scheduled_start_utc`,
        else `ERR_LESSON_NOT_STARTED` (HTTP 409); and the parent enrollment's
        `lifecycle_status` to be `ACTIVE`, else `ERR_ENROLLMENT_NOT_ACTIVE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/complete_occurrence_requires_active_enrollment
        """
        sid, instructor, occ = self._setup_frozen_with_past_scheduled_occ(api)
        res = api.complete_occurrence(sid, occ["id"], make_instructor_headers(instructor["id"]))
        validate_error(res, "ERR_ENROLLMENT_NOT_ACTIVE", expected_status=409)

    def test_complete_blocked_by_enrollment_state_not_occurrence_state(self, api):
        """PRD 3.5: "the parent enrollment's `lifecycle_status` to be `ACTIVE`, else
        `ERR_ENROLLMENT_NOT_ACTIVE` (HTTP 409)." The occurrence here is still SCHEDULED
        and its start is in the past, so only the enrollment-not-active gate can fire.

        Design: Difficulty/cross_entity_state_dependency/complete_occurrence_requires_active_enrollment
        """
        sid, instructor, occ = self._setup_frozen_with_past_scheduled_occ(api)
        # Confirm the occurrence itself is still SCHEDULED (freeze left the past occ alone).
        occ_now = validate_success(api.get_occurrence(sid, occ["id"], ADMIN), 200)
        assert occ_now["status"] == "SCHEDULED"
        res = api.complete_occurrence(sid, occ["id"], make_instructor_headers(instructor["id"]))
        validate_error(res, "ERR_ENROLLMENT_NOT_ACTIVE", expected_status=409)


# ===========================================================================
# Difficulty / compensating_invariant / makeup_credit_mint_then_void_leaves_count_unchanged
# ===========================================================================
class TestMakeupCreditMintThenVoid:
    def _setup_one_outstanding_credit(self, api):
        studio, family, student, instructor, room, enr = setup_active_enrollment(
            instructor_overrides={
                "instruments": ["PIANO"],
                "weekly_availability": [{"weekday": 0, "start_min": 0, "end_min": 1440}],
                "hourly_rate_cents": 6000,
            }
        )
        sid = studio["id"]
        occ = create_occurrence(sid, enr["id"], "2026-01-26T10:00:00.000Z")
        validate_success(api.request_makeup(sid, occ["id"], ADMIN), 200)
        credits, _ = validate_paginated(
            api.list_makeup_credits(sid, ADMIN, params={"enrollment_id": enr["id"]})
        )
        return sid, enr, credits[0]

    def test_credit_is_outstanding_before_cancel(self, api):
        """PRD 3.5: "On success the occurrence moves `SCHEDULED → MAKEUP_PENDING` and one
        `OUTSTANDING` makeup credit is minted for the enrollment".

        Design: Difficulty/compensating_invariant/makeup_credit_mint_then_void_leaves_count_unchanged
        """
        sid, enr, credit = self._setup_one_outstanding_credit(api)
        assert credit["status"] == "OUTSTANDING"

    def test_cancel_enrollment_voids_outstanding_credit(self, api):
        """PRD 3.2: "every `OUTSTANDING` makeup credit for the enrollment moves to
        `VOIDED`". PRD 3.6: "minting a credit then consuming or voiding it returns the
        count to its prior value."

        Design: Difficulty/compensating_invariant/makeup_credit_mint_then_void_leaves_count_unchanged
        """
        sid, enr, credit = self._setup_one_outstanding_credit(api)
        validate_success(api.cancel_enrollment(sid, enr["id"], ADMIN), 200)
        after = validate_success(api.get_makeup_credit(sid, credit["id"], ADMIN), 200)
        assert after["status"] == "VOIDED"


# ===========================================================================
# Corner / state_machines / complete_occurrence_before_start_returns_lesson_not_started
# ===========================================================================
def test_complete_occurrence_before_start_returns_lesson_not_started(api):
    """PRD 3.5: "the studio clock to be at or after `scheduled_start_utc`, else
    `ERR_LESSON_NOT_STARTED` (HTTP 409)".

    Design: Corner/state_machines/complete_occurrence_before_start_returns_lesson_not_started
    """
    studio, family, student, instructor, room, enr = setup_active_enrollment(
        instructor_overrides={
            "instruments": ["PIANO"],
            "weekly_availability": [{"weekday": 0, "start_min": 0, "end_min": 1440}],
            "hourly_rate_cents": 6000,
        }
    )
    sid = studio["id"]
    occ = create_occurrence(sid, enr["id"], "2026-01-26T10:00:00.000Z")  # clock still 2026-01-01
    res = api.complete_occurrence(sid, occ["id"], make_instructor_headers(instructor["id"]))
    validate_error(res, "ERR_LESSON_NOT_STARTED", expected_status=409)


# ===========================================================================
# Corner / state_machines / occurrence_initial_state_scheduled_with_computed_end
# ===========================================================================
def test_occurrence_initial_state_scheduled_with_computed_end(api):
    """PRD 3.5: "the system sets `scheduled_end_utc` to `scheduled_start_utc` plus the
    enrollment's `duration_min` (a half-open interval), copies the enrollment's
    `room_id` and `instructor_id` onto the occurrence, sets `is_makeup` to false and
    leaves `consumed_credit_id` unset, and starts the occurrence in `SCHEDULED`."

    Design: Corner/state_machines/occurrence_initial_state_scheduled_with_computed_end
    """
    studio, family, student, instructor, room, enr = setup_active_enrollment(
        instructor_overrides={
            "instruments": ["PIANO"],
            "weekly_availability": [{"weekday": 0, "start_min": 0, "end_min": 1440}],
            "hourly_rate_cents": 6000,
        },
        enrollment_overrides={"duration_min": 60},
    )
    sid = studio["id"]
    occ = validate_success(
        api.create_occurrence(
            sid, {"enrollment_id": enr["id"], "scheduled_start_utc": "2026-01-05T10:00:00.000Z"}, ADMIN
        ),
        201,
    )
    assert occ["status"] == "SCHEDULED"
    assert occ["scheduled_end_utc"] == "2026-01-05T11:00:00.000Z"
    assert occ["is_makeup"] is False


# ===========================================================================
# Corner / state_machines / late_cancel_under_notice_no_credit
# ===========================================================================
def test_late_cancel_under_notice_no_credit(api):
    """PRD 3.5: "When the gap is less than `cancellation_notice_hours`, the cancellation
    is late: the occurrence moves `SCHEDULED → CANCELLED_LATE` (terminal) and no makeup
    credit is minted — a late cancellation forfeits."

    Design: Corner/state_machines/late_cancel_under_notice_no_credit
    """
    studio, family, student, instructor, room, enr = setup_active_enrollment(
        instructor_overrides={
            "instruments": ["PIANO"],
            "weekly_availability": [
                {"weekday": 0, "start_min": 0, "end_min": 1440},
                {"weekday": 1, "start_min": 0, "end_min": 1440},
            ],
            "hourly_rate_cents": 6000,
        },
        enrollment_overrides={"weekday": 1, "start_min": 900, "duration_min": 60},
    )
    sid = studio["id"]
    occ = create_occurrence(sid, enr["id"], "2026-01-20T15:00:00.000Z")
    set_clock(sid, "2026-01-20T03:00:00.000Z")  # 12h before, under the 24h notice
    parent_hdr = make_parent_guardian_headers(family["id"])
    cancelled = validate_success(api.cancel_occurrence(sid, occ["id"], parent_hdr), 200)
    assert cancelled["status"] == "CANCELLED_LATE"
    credits, meta = validate_paginated(
        api.list_makeup_credits(sid, ADMIN, params={"enrollment_id": enr["id"]})
    )
    assert meta["total_count"] == 0


# ===========================================================================
# Corner / validations / makeup_cap_exceeded_rejected
# ===========================================================================
def test_makeup_cap_exceeded_rejected(api):
    """PRD 3.5: "the enrollment's outstanding-credit count to be below
    `makeup_credit_cap_per_enrollment`, else `ERR_MAKEUP_CAP_EXCEEDED`."

    Design: Corner/validations/makeup_cap_exceeded_rejected
    """
    studio, family, student, instructor, room, enr = setup_active_enrollment(
        studio_overrides={"makeup_credit_cap_per_enrollment": 1},
        instructor_overrides={
            "instruments": ["PIANO"],
            "weekly_availability": [
                {"weekday": 0, "start_min": 0, "end_min": 1440},
                {"weekday": 1, "start_min": 0, "end_min": 1440},
            ],
            "hourly_rate_cents": 6000,
        },
    )
    sid = studio["id"]
    occ1 = create_occurrence(sid, enr["id"], "2026-01-19T10:00:00.000Z")
    occ2 = create_occurrence(sid, enr["id"], "2026-01-26T10:00:00.000Z")
    validate_success(api.request_makeup(sid, occ1["id"], ADMIN), 200)  # mints the 1 allowed credit
    res = api.request_makeup(sid, occ2["id"], ADMIN)
    validate_error(res, "ERR_MAKEUP_CAP_EXCEEDED", expected_status=409)
