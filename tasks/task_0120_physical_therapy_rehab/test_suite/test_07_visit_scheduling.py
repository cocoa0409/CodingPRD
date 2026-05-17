"""Visit scheduling: out-of-window, double-booking (half-open vs
closed), POC visit limit, insufficient units, REEVAL_DUE block.

PRD §3.5 / §3.6 / §2.7.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    anchor_clock,
    assert_episode_unit_invariant,
    create_visit,
    iso_anchor_offset,
    iso_date_anchor_offset,
    make_therapist_headers,
    re_get_episode,
    setup_active_episode,
    setup_mergeable_clinician_schedule_pair,
    setup_patient_overlap_pair,
    setup_reeval_due_episode,
    validate_error,
    validate_success,
)
from test_helpers import create_visit_payload


# ===========================================================================
# Out-of-window — PRD §3.5.
# ===========================================================================
class TestOutOfAuthWindow:

    def test_visit_outside_authorization_window_rejected(self, api):
        """PRD §3.5: "The scheduled_start must fall within both the
        bound authorization's [valid_from, valid_through] window and
        the bound plan's [cert_period_start, cert_period_end] window
        — both windows are inclusive on both endpoints — and a window
        violation is rejected with ERR_OUT_OF_AUTH_WINDOW."

        Claim: scheduled_start past the authorization's valid_through
        → ERR_OUT_OF_AUTH_WINDOW.
        """
        # Build an episode whose authorization window ends at day=10.
        setup = setup_active_episode(
            unit_quota=60, cert_period_days=60,
        )
        therapist = setup["therapist"]
        # Schedule a visit 200 days in the future — past both the
        # authorization and the plan windows.
        far_future_start = iso_anchor_offset(days=200, hours=10)
        far_future_end = iso_anchor_offset(days=200, hours=11)
        res = api.create_visit(
            setup["episode"]["id"],
            create_visit_payload(
                plan_of_care_id=setup["plan_of_care"]["id"],
                authorization_id=setup["authorization"]["id"],
                clinician_id=therapist["id"],
                scheduled_start=far_future_start,
                scheduled_end=far_future_end,
                units_planned=3,
            ),
            make_therapist_headers(therapist["id"]),
        )
        validate_error(res, "ERR_OUT_OF_AUTH_WINDOW")


# ===========================================================================
# Half-open clinician double-booking — Difficulty design Rule 8.
# ===========================================================================
class TestClinicianDoubleBookingHalfOpen:

    def test_back_to_back_visits_do_not_overlap_half_open(self, api):
        """# difficulty: resource_temporal_overlap/clinician_double_booking_half_open
        PRD §3.5: "the new visit must not overlap any other visit in
        SCHEDULED, IN_SESSION, or SIGNED for the same clinician_id
        under half-open interval semantics — back-to-back visits
        sharing exactly the same instant on the boundary do not
        overlap — and violation yields ERR_CLINICIAN_DOUBLE_BOOKED."

        Claim: a second visit starting exactly at the first visit's
        scheduled_end is accepted (half-open: 11:00==11:00 is NOT
        overlap).
        """
        setup = setup_mergeable_clinician_schedule_pair()
        clinician = setup["clinician"]
        end_of_first = setup["pre_existing_end"]
        # Second visit on Patient B, same clinician, starting at the
        # boundary instant.
        new_end = iso_anchor_offset(days=1, hours=2)
        res = api.create_visit(
            setup["episode_b"]["id"],
            create_visit_payload(
                plan_of_care_id=setup["plan_of_care_b"]["id"],
                authorization_id=setup["authorization_b"]["id"],
                clinician_id=clinician["id"],
                scheduled_start=end_of_first,  # ==11:00
                scheduled_end=new_end,
                units_planned=3,
            ),
            make_therapist_headers(clinician["id"]),
        )
        data = validate_success(res, expected_status=201)
        assert data["status"] == "SCHEDULED"

    def test_overlapping_visit_for_same_clinician_rejected(self, api):
        """# difficulty: resource_temporal_overlap/clinician_double_booking_half_open
        PRD §3.5: "the new visit must not overlap any other visit in
        SCHEDULED, IN_SESSION, or SIGNED for the same clinician_id
        under half-open interval semantics ... violation yields
        ERR_CLINICIAN_DOUBLE_BOOKED."

        Claim: a visit starting at 10:59 — strictly before the first
        visit's 11:00 end — overlaps under half-open semantics →
        ERR_CLINICIAN_DOUBLE_BOOKED.
        """
        setup = setup_mergeable_clinician_schedule_pair()
        clinician = setup["clinician"]
        overlapping_start = iso_anchor_offset(
            days=1, hours=0, minutes=59,  # 10:59
        )
        overlapping_end = iso_anchor_offset(
            days=1, hours=1, minutes=30,  # 11:30
        )
        res = api.create_visit(
            setup["episode_b"]["id"],
            create_visit_payload(
                plan_of_care_id=setup["plan_of_care_b"]["id"],
                authorization_id=setup["authorization_b"]["id"],
                clinician_id=clinician["id"],
                scheduled_start=overlapping_start,
                scheduled_end=overlapping_end,
                units_planned=3,
            ),
            make_therapist_headers(clinician["id"]),
        )
        validate_error(res, "ERR_CLINICIAN_DOUBLE_BOOKED")


# ===========================================================================
# Closed patient double-booking — Difficulty design Rule 8.
# ===========================================================================
class TestPatientDoubleBookingClosed:

    def test_back_to_back_visits_overlap_closed_for_same_patient(self, api):
        """# difficulty: resource_temporal_overlap/patient_double_booking_closed
        PRD §3.5: "the new visit must not overlap any other visit in
        those same statuses for the same patient (resolved via the
        owning episode) under closed-interval semantics — back-to-back
        visits sharing the same instant on the boundary do overlap
        because the patient cannot be in two places at once — and
        violation yields ERR_PATIENT_DOUBLE_BOOKED."

        Claim: same patient, two episodes, two clinicians; second visit
        starts exactly at the first visit's scheduled_end (15:00 ==
        15:00) → ERR_PATIENT_DOUBLE_BOOKED.
        """
        setup = setup_patient_overlap_pair()
        end_of_first = setup["pre_existing_end"]
        new_end = iso_anchor_offset(days=1, hours=6)  # +1h
        res = api.create_visit(
            setup["episode_b"]["id"],
            create_visit_payload(
                plan_of_care_id=setup["plan_of_care_b"]["id"],
                authorization_id=setup["authorization_b"]["id"],
                clinician_id=setup["clinician_b"]["id"],
                scheduled_start=end_of_first,
                scheduled_end=new_end,
                units_planned=3,
            ),
            make_therapist_headers(setup["clinician_b"]["id"]),
        )
        validate_error(res, "ERR_PATIENT_DOUBLE_BOOKED")


# ===========================================================================
# POC visit limit — PRD §3.5.
# ===========================================================================
class TestPocVisitLimit:

    def test_visit_count_exceeding_planned_count_rejected(self, api):
        """PRD §3.5: "The total number of visits already in SCHEDULED,
        IN_SESSION, SIGNED, or BILLED on the plan plus this new one
        must not exceed PlanOfCare.planned_visit_count; an overflow
        is rejected with ERR_POC_VISIT_LIMIT."

        Claim: with planned_visit_count=2, creating a third visit →
        ERR_POC_VISIT_LIMIT.
        """
        setup = setup_active_episode(
            unit_quota=20,
            planned_visit_count=2,
            planned_units_per_visit=3,
        )
        therapist = setup["therapist"]
        # First visit.
        v1_start = iso_anchor_offset(days=1, hours=0)
        v1_end = iso_anchor_offset(days=1, hours=1)
        create_visit(
            episode_id=setup["episode"]["id"],
            plan_of_care_id=setup["plan_of_care"]["id"],
            authorization_id=setup["authorization"]["id"],
            clinician_id=therapist["id"],
            scheduled_start=v1_start, scheduled_end=v1_end,
            units_planned=3, acting_therapist_id=therapist["id"],
        )
        # Second visit.
        v2_start = iso_anchor_offset(days=2, hours=0)
        v2_end = iso_anchor_offset(days=2, hours=1)
        create_visit(
            episode_id=setup["episode"]["id"],
            plan_of_care_id=setup["plan_of_care"]["id"],
            authorization_id=setup["authorization"]["id"],
            clinician_id=therapist["id"],
            scheduled_start=v2_start, scheduled_end=v2_end,
            units_planned=3, acting_therapist_id=therapist["id"],
        )
        # Third visit — should be rejected.
        v3_start = iso_anchor_offset(days=3, hours=0)
        v3_end = iso_anchor_offset(days=3, hours=1)
        res = api.create_visit(
            setup["episode"]["id"],
            create_visit_payload(
                plan_of_care_id=setup["plan_of_care"]["id"],
                authorization_id=setup["authorization"]["id"],
                clinician_id=therapist["id"],
                scheduled_start=v3_start, scheduled_end=v3_end,
                units_planned=3,
            ),
            make_therapist_headers(therapist["id"]),
        )
        validate_error(res, "ERR_POC_VISIT_LIMIT")


# ===========================================================================
# Insufficient units — PRD §3.5.
# ===========================================================================
class TestInsufficientUnits:

    def test_visit_exceeding_authorized_units_rejected(self, api):
        """PRD §3.5: "The episode-level quota invariant must hold at
        scheduling time: total_reserved_units plus
        total_committed_units plus the new visit's units_planned must
        remain less than or equal to total_authorized_units, and a
        shortfall is rejected with ERR_INSUFFICIENT_UNITS."

        Claim: unit_quota=3, new visit units_planned=4 →
        ERR_INSUFFICIENT_UNITS.
        """
        # PRD §3.3 certify rule: unit_quota >= planned_visit_count *
        # planned_units_per_visit. Use planned product == unit_quota so
        # certify succeeds; the new 4-unit visit will then exceed the
        # 3-unit pool.
        setup = setup_active_episode(
            unit_quota=3,
            planned_visit_count=1,
            planned_units_per_visit=3,
        )
        therapist = setup["therapist"]
        res = api.create_visit(
            setup["episode"]["id"],
            create_visit_payload(
                plan_of_care_id=setup["plan_of_care"]["id"],
                authorization_id=setup["authorization"]["id"],
                clinician_id=therapist["id"],
                scheduled_start=iso_anchor_offset(days=1, hours=0),
                scheduled_end=iso_anchor_offset(days=1, hours=1),
                units_planned=4,
            ),
            make_therapist_headers(therapist["id"]),
        )
        validate_error(res, "ERR_INSUFFICIENT_UNITS")


# ===========================================================================
# REEVAL_DUE blocks visit scheduling — PRD §3.6.
# ===========================================================================
class TestReevalDueBlocksScheduling:

    def test_schedule_visit_on_reeval_due_episode_rejected(self, api):
        """PRD §3.6: "While the episode sits in REEVAL_DUE, scheduling
        new visits is blocked and is rejected with ERR_REEVAL_DUE."

        Claim: POST /episodes/{id}/visits on a REEVAL_DUE episode →
        ERR_REEVAL_DUE.
        """
        setup = setup_reeval_due_episode(
            unit_quota=20,
            planned_visit_count=10,
        )
        assert setup["episode"]["status"] == "REEVAL_DUE"
        therapist = setup["therapist"]
        res = api.create_visit(
            setup["episode"]["id"],
            create_visit_payload(
                plan_of_care_id=setup["plan_of_care"]["id"],
                authorization_id=setup["authorization"]["id"],
                clinician_id=therapist["id"],
                scheduled_start=iso_anchor_offset(days=40, hours=10),
                scheduled_end=iso_anchor_offset(days=40, hours=11),
                units_planned=3,
            ),
            make_therapist_headers(therapist["id"]),
        )
        validate_error(res, "ERR_REEVAL_DUE")


# ===========================================================================
# Unit pool invariant — PRD §2.7.
# ===========================================================================
class TestUnitPoolInvariant:

    def test_unit_invariant_holds_after_scheduling(self, api):
        """PRD §2.7: "The pool invariant the system protects at all
        times is that reserved units plus committed units never exceed
        authorized units."

        Claim: after scheduling, the invariant holds on the episode
        rollup.
        """
        setup = setup_active_episode(unit_quota=10)
        therapist = setup["therapist"]
        create_visit(
            episode_id=setup["episode"]["id"],
            plan_of_care_id=setup["plan_of_care"]["id"],
            authorization_id=setup["authorization"]["id"],
            clinician_id=therapist["id"],
            scheduled_start=iso_anchor_offset(days=1, hours=0),
            scheduled_end=iso_anchor_offset(days=1, hours=1),
            units_planned=3, acting_therapist_id=therapist["id"],
        )
        ep = re_get_episode(setup["episode"]["id"])
        assert_episode_unit_invariant(ep)
        assert ep["total_reserved_units"] == 3
        assert ep["total_authorized_units"] == 10
        assert ep["total_committed_units"] == 0
