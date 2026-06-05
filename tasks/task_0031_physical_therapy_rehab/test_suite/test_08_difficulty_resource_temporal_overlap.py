"""Difficulty Rule 8 — resource_temporal_overlap.

Two overlap rules with different interval semantics:
  (A) Visit-on-Therapist: HALF-OPEN [start, end). Adjacent visits at the same
      instant are PERMITTED.
  (B) Grant-on-Plan: CLOSED-CLOSED [from, to]. Adjacent grants sharing a single
      day are REJECTED.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    setup_poc_with_grant,
    setup_active_poc,
    schedule_visit,
    create_grant,
    create_visit_payload,
    create_authorization_grant_payload,
    create_patient,
    create_draft_poc,
    record_initial_evaluation,
    activate_poc,
    make_therapist_headers,
    TEST_USERS,
)


class TestTherapistDoubleBookHalfOpenAdjacentPermitted:
    """Existing visit [11:00, 12:00). Adjacent [12:00, 13:00) succeeds (touch is
    permitted). Overlapping [11:30, 12:30) is REJECTED with ERR_THERAPIST_DOUBLE_BOOKED.
    """

    def test_adjacent_visit_at_same_utc_instant_is_permitted(self, api):
        """PRD §3.5: "the new visit's `[scheduled_start_utc, scheduled_end_utc)` interval
        must not overlap any other `SCHEDULED` or `COMPLETED` visit on the same
        `therapist_id` — overlap is evaluated under **half-open** semantics, which means
        that two adjacent visits touching at exactly the same UTC instant (one ending and
        another starting at the same instant) are permitted; a true overlap is rejected
        with `ERR_THERAPIST_DOUBLE_BOOKED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/therapist_double_book_half_open_adjacent_permitted
        """
        # 2 patients, each with their own POC + grant, sharing 1 therapist.
        ctx1 = setup_poc_with_grant(insurance_type="COMMERCIAL", total_units_granted=10)
        th = ctx1["therapist"]["id"]
        # Second patient + POC + grant under the SAME therapist.
        pt2 = create_patient(insurance_type="COMMERCIAL", full_name="Pat2",
                             date_of_birth="1971-01-01")
        poc2 = create_draft_poc(pt2["id"], th)
        record_initial_evaluation(poc2["id"], th, performed_on="2026-06-01")
        activate_poc(poc2["id"], th)
        grant2 = create_grant(poc2["id"], total_units_granted=10,
                              effective_from="2026-06-01", effective_to="2026-07-31")
        # Existing visit on therapist: [11:00, 12:00).
        schedule_visit(
            ctx1["grant"]["id"], th,
            "2026-06-10T11:00:00Z", "2026-06-10T12:00:00Z",
            planned_minutes=60, cpt_code="CPT_97110_THER_EX",
        )
        # New adjacent visit: [12:00, 13:00). Should be PERMITTED (half-open).
        res = api.create_visit(
            create_visit_payload(
                authorization_grant_id=grant2["id"],
                therapist_id=th,
                scheduled_start_utc="2026-06-10T12:00:00Z",
                scheduled_end_utc="2026-06-10T13:00:00Z",
                planned_minutes=60, cpt_code="CPT_97110_THER_EX",
            ),
            make_therapist_headers(th),
        )
        adj = validate_success(res, 201)
        assert adj["status"] == "SCHEDULED"

    def test_overlapping_visit_rejected_with_double_booked(self, api):
        """PRD §3.5: "a true overlap is rejected with `ERR_THERAPIST_DOUBLE_BOOKED`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/therapist_double_book_half_open_adjacent_permitted
        """
        ctx1 = setup_poc_with_grant(insurance_type="COMMERCIAL", total_units_granted=10)
        th = ctx1["therapist"]["id"]
        pt2 = create_patient(insurance_type="COMMERCIAL", full_name="Pat2",
                             date_of_birth="1971-01-01")
        poc2 = create_draft_poc(pt2["id"], th)
        record_initial_evaluation(poc2["id"], th, performed_on="2026-06-01")
        activate_poc(poc2["id"], th)
        grant2 = create_grant(poc2["id"], total_units_granted=10,
                              effective_from="2026-06-01", effective_to="2026-07-31")
        # Existing [11:00, 12:00).
        schedule_visit(
            ctx1["grant"]["id"], th,
            "2026-06-10T11:00:00Z", "2026-06-10T12:00:00Z",
            planned_minutes=60, cpt_code="CPT_97110_THER_EX",
        )
        # True overlap [11:30, 12:30) → ERR_THERAPIST_DOUBLE_BOOKED.
        res = api.create_visit(
            create_visit_payload(
                authorization_grant_id=grant2["id"],
                therapist_id=th,
                scheduled_start_utc="2026-06-10T11:30:00Z",
                scheduled_end_utc="2026-06-10T12:30:00Z",
                planned_minutes=60, cpt_code="CPT_97110_THER_EX",
            ),
            make_therapist_headers(th),
        )
        validate_error(res, "ERR_THERAPIST_DOUBLE_BOOKED", expected_status=409)


class TestAuthorizationGrantWindowClosedClosedAdjacentRejected:
    """Existing grant [2026-06-01, 2026-06-30]. New grant [2026-06-30, 2026-07-29]
    shares the single day 2026-06-30 → REJECTED.
    """

    def test_adjacent_grants_sharing_single_day_are_rejected(self, api):
        """PRD §3.4: "two grants on the same plan whose `[effective_from, effective_to]`
        intervals share even a single day are rejected with `ERR_GRANT_WINDOW_OVERLAP`
        (HTTP 409). The closed-closed framing means that adjacent grants which touch on
        the same date — for example one ending on the 14th and another starting on the
        14th — are treated as overlapping and rejected."

        Design: Difficulty/resource_temporal_overlap/authorization_grant_window_closed_closed_adjacent_rejected
        """
        ctx = setup_active_poc(insurance_type="COMMERCIAL")
        create_grant(
            ctx["poc"]["id"], total_units_granted=10,
            effective_from="2026-06-01", effective_to="2026-06-30",
        )
        res = api.create_authorization_grant(
            create_authorization_grant_payload(
                plan_of_care_id=ctx["poc"]["id"],
                total_units_granted=10,
                effective_from="2026-06-30",  # shares this day with the existing grant's end
                effective_to="2026-07-29",
            ),
            TEST_USERS["case_manager_headers"],
        )
        validate_error(res, "ERR_GRANT_WINDOW_OVERLAP", expected_status=409)

    def test_grants_with_a_clean_gap_are_accepted(self, api):
        """PRD §3.4: "two grants on the same plan whose `[effective_from, effective_to]`
        intervals share even a single day are rejected with `ERR_GRANT_WINDOW_OVERLAP`
        (HTTP 409)."

        Companion boundary: when the second grant starts on the day STRICTLY after the
        first ends, no day is shared, so creation succeeds.

        Design: Difficulty/resource_temporal_overlap/authorization_grant_window_closed_closed_adjacent_rejected
        """
        ctx = setup_active_poc(insurance_type="COMMERCIAL")
        create_grant(
            ctx["poc"]["id"], total_units_granted=10,
            effective_from="2026-06-01", effective_to="2026-06-29",
        )
        res = api.create_authorization_grant(
            create_authorization_grant_payload(
                plan_of_care_id=ctx["poc"]["id"],
                total_units_granted=10,
                effective_from="2026-06-30",  # gap of 1 day after the first grant ends 06-29
                effective_to="2026-07-29",
            ),
            TEST_USERS["case_manager_headers"],
        )
        validate_success(res, 201)
