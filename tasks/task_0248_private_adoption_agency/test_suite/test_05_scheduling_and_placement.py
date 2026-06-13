"""Scheduling and placement tests: visit half-open overlap, counseling buffered overlap,
finalize visit-count boundary, and corner placement/visit/phase claims.

Difficulty queue (A): resource_temporal_overlap, boundary_precision_check (finalize).
Corner queue (B): calculations / validations / consistency_model instances.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_agency, set_clock, create_case, create_birth_parent,
    current_case_version, create_irrevocable_consent,
    setup_active_placement, setup_active_placement_in_state,
    setup_finalizable_in_state_placement, setup_case_with_irrevocable_consent,
    schedule_visit,
    create_visit_payload, create_counseling_session_payload,
    TEST_USERS,
)

CW = TEST_USERS["caseworker_headers"]
SUP = TEST_USERS["supervisor_headers"]
ADMIN = TEST_USERS["agency_admin_headers"]


# ─── resource_temporal_overlap / visit_overlap_half_open_touching_allowed ──
class TestVisitHalfOpenOverlap:
    def _active_placement_with_first_visit(self):
        base = setup_active_placement(child_state="NV", family_state="CA",
                                      to_iso8601="2026-06-04T08:00:00.000Z")
        v1 = schedule_visit(base["case_id"], base["placement_id"],
                            "2026-06-10T09:00:00.000Z", "2026-06-10T12:00:00.000Z")
        return base, v1

    def test_touching_visit_accepted(self):
        """PRD §3.6: "The visit window is half-open and touching is allowed: an existing
        visit occupies its window up to but not including its window_end, so a new visit
        whose window_start exactly equals an existing visit's window_end does not overlap."

        Design: Difficulty/resource_temporal_overlap/visit_overlap_half_open_touching_allowed
        """
        base, v1 = self._active_placement_with_first_visit()
        touch = api_client.create_visit(create_visit_payload(
            base["case_id"], base["placement_id"],
            "2026-06-10T12:00:00.000Z", "2026-06-10T15:00:00.000Z"), CW)
        v_touch = validate_success(touch, 201)
        assert v_touch["status"] == "SCHEDULED"

    def test_intruding_visit_rejected(self):
        """PRD §3.6: "Two visits overlap when the new visit's window_start is earlier than
        the existing visit's window_end and the existing visit's window_start is earlier
        than the new visit's window_end. An invalid or overlapping schedule is rejected
        with ERR_VISIT_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/visit_overlap_half_open_touching_allowed
        """
        base, v1 = self._active_placement_with_first_visit()
        res = api_client.create_visit(create_visit_payload(
            base["case_id"], base["placement_id"],
            "2026-06-10T11:00:00.000Z", "2026-06-10T13:00:00.000Z"), CW)
        validate_error(res, "ERR_VISIT_OVERLAP")


# ─── resource_temporal_overlap / counseling_buffer_back_to_back_rejected ──
class TestCounselingBufferOverlap:
    def _booked_session(self):
        agency = create_agency()
        case = create_case(agency["id"], child_state="CA", family_state="CA")
        bp = create_birth_parent(agency["id"], birth_state="CA")
        s1 = validate_success(api_client.create_counseling_session(
            create_counseling_session_payload(bp["id"], case["id"],
                                              "2026-06-10T09:00:00.000Z",
                                              "2026-06-10T10:00:00.000Z"), CW), 201)
        return case["id"], bp["id"], s1

    def test_back_to_back_session_rejected(self):
        """PRD §3.3: "Because the buffer is added to a closed interval, two back-to-back
        sessions whose candidate start_at exactly equals an existing end_at do conflict ...
        A violation of either the ordering rule or the buffer rule is rejected with
        ERR_SESSION_BUFFER_CONFLICT."

        Design: Difficulty/resource_temporal_overlap/counseling_buffer_back_to_back_rejected
        """
        case_id, bp_id, _ = self._booked_session()
        res = api_client.create_counseling_session(
            create_counseling_session_payload(bp_id, case_id,
                                              "2026-06-10T10:00:00.000Z",
                                              "2026-06-10T11:00:00.000Z"), CW)
        validate_error(res, "ERR_SESSION_BUFFER_CONFLICT")

    def test_session_clear_of_buffer_accepted(self):
        """PRD §3.3: "for a given birth parent, two non-cancelled sessions may not fall
        within sixty minutes of each other ... A candidate session conflicts with an
        existing one when the candidate's start_at is earlier than the existing session's
        end_at plus sixty minutes and the existing session's start_at is earlier than the
        candidate's end_at plus sixty minutes."

        Design: Difficulty/resource_temporal_overlap/counseling_buffer_back_to_back_rejected
        """
        case_id, bp_id, _ = self._booked_session()
        # Existing [09:00,10:00]. A candidate starting at 11:01 is clear: candidate.start
        # (11:01) is NOT earlier than existing.end+60 (11:00), so no conflict.
        ok = api_client.create_counseling_session(
            create_counseling_session_payload(bp_id, case_id,
                                              "2026-06-10T11:01:00.000Z",
                                              "2026-06-10T12:00:00.000Z"), CW)
        s2 = validate_success(ok, 201)
        assert s2["status"] == "BOOKED"


# ─── boundary_precision_check / finalize_requires_visit_count_at_threshold ──
class TestFinalizeVisitCountBoundary:
    def test_finalize_succeeds_at_required_visit_count(self):
        """PRD §3.6: "finalization requires the placement to be ACTIVE, requires the
        placement's completed_visit_count to be at least its required_visits, and requires
        that an agency fee invoice exists for the case in either ISSUED or PAID status".

        Design: Difficulty/boundary_precision_check/finalize_requires_visit_count_at_threshold
        """
        base = setup_finalizable_in_state_placement(to_iso8601="2026-06-04T08:00:00.000Z")
        placement = validate_success(api_client.get_placement(base["placement_id"], SUP), 200)
        assert placement["completed_visit_count"] == 3
        assert placement["required_visits"] == 3
        finalized = validate_success(api_client.finalize_placement(base["placement_id"], SUP), 200)
        assert finalized["status"] == "FINALIZED"

    def test_finalize_rejected_below_required_visit_count(self):
        """PRD §3.6: "If too few visits have been completed, finalization is rejected with
        ERR_VISITS_INCOMPLETE."

        Design: Difficulty/boundary_precision_check/finalize_requires_visit_count_at_threshold
        """
        # In-state ACTIVE placement (required_visits=3) with only 2 visits completed.
        base = setup_active_placement_in_state(to_iso8601="2026-06-04T08:00:00.000Z")
        v1 = schedule_visit(base["case_id"], base["placement_id"],
                            "2026-06-05T09:00:00.000Z", "2026-06-05T17:00:00.000Z")
        v2 = schedule_visit(base["case_id"], base["placement_id"],
                            "2026-06-06T09:00:00.000Z", "2026-06-06T17:00:00.000Z")
        set_clock(base["agency_id"], "2026-06-05T10:00:00.000Z")
        validate_success(api_client.complete_visit(v1["id"], CW), 200)
        set_clock(base["agency_id"], "2026-06-06T10:00:00.000Z")
        validate_success(api_client.complete_visit(v2["id"], CW), 200)
        from test_helpers import create_invoice_payload, get_success_data
        get_success_data(api_client.create_invoice(create_invoice_payload(base["case_id"]),
                                                   TEST_USERS["finance_officer_headers"]))
        res = api_client.finalize_placement(base["placement_id"], SUP)
        validate_error(res, "ERR_VISITS_INCOMPLETE")


# ─── Corner (B): calculations / required_visits_interstate_six ────────────
def test_required_visits_interstate_six():
    """PRD §3.6: "an interstate case requires six post-placement visits, while an in-state
    case requires three; the case is interstate exactly when its child_state differs from
    its family_state."

    Design: Corner/calculations/required_visits_interstate_six
    """
    base = setup_active_placement(child_state="NV", family_state="CA",
                                  to_iso8601="2026-06-04T08:00:00.000Z")
    placement = validate_success(api_client.get_placement(base["placement_id"], SUP), 200)
    assert placement["required_visits"] == 6
    case = validate_success(api_client.get_case(base["case_id"], SUP), 200)
    assert case["phase"] == "PLACED"


# ─── Corner (B): calculations / case_phase_consented_after_irrevocable_consent ──
def test_case_phase_consented_after_irrevocable_consent():
    """PRD §3.1: "Otherwise, if any consent record for the case is IRREVOCABLE, the phase
    is CONSENTED."
    PRD §3.4: "it moves the consent to IRREVOCABLE, recomputes the case phase (with an
    IRREVOCABLE consent the case advances to CONSENTED unless a later milestone already
    applies)".

    Design: Corner/calculations/case_phase_consented_after_irrevocable_consent
    """
    base = setup_case_with_irrevocable_consent(child_state="CA", family_state="CA",
                                               to_iso8601="2026-06-04T08:00:00.000Z")
    consent = validate_success(api_client.get_consent_record(base["consent_id"], SUP), 200)
    assert consent["status"] == "IRREVOCABLE"
    case = validate_success(api_client.get_case(base["case_id"], SUP), 200)
    assert case["phase"] == "CONSENTED"


# ─── Corner (B): validations / visit_complete_outside_window ──────────────
def test_visit_complete_outside_window():
    """PRD §3.6: "completion requires the visit to be SCHEDULED, requires the case's
    placement to be ACTIVE, and requires the agency clock to fall within the half-open
    window — at or after window_start and strictly before window_end. A completion attempt
    outside that window is rejected with ERR_VISIT_WINDOW_INVALID."

    Design: Corner/validations/visit_complete_outside_window
    """
    base = setup_active_placement(child_state="NV", family_state="CA",
                                  to_iso8601="2026-06-04T08:00:00.000Z")
    visit = schedule_visit(base["case_id"], base["placement_id"],
                           "2026-06-10T09:00:00.000Z", "2026-06-10T17:00:00.000Z")
    set_clock(base["agency_id"], "2026-06-10T17:00:00.000Z")  # exactly window_end (excluded)
    res = api_client.complete_visit(visit["id"], CW)
    validate_error(res, "ERR_VISIT_WINDOW_INVALID")


# ─── Corner (B): consistency_model / immediate_visibility_of_phase_after_activate ──
def test_immediate_visibility_of_phase_after_activate():
    """PRD §3.6: "On success the placement's placed_at is set to the agency clock, its
    required_visits is computed, and the case phase is recomputed to PLACED."
    PRD §2.8: "the system keeps them reconciled immediately."

    Design: Corner/consistency_model/immediate_visibility_of_phase_after_activate
    """
    base = setup_active_placement(child_state="NV", family_state="CA",
                                  to_iso8601="2026-06-04T08:00:00.000Z")
    case = validate_success(api_client.get_case(base["case_id"], SUP), 200)
    assert case["phase"] == "PLACED"
