"""Difficulty Rule 8 — resource_temporal_overlap.

Two different interval semantics on two different scarce resources:
half-open 60-min window on per-case biometrics, and point-instant capacity-of-1
on the ASC location across cases.
"""
import pytest

from test_helpers import (
    api_client,
    validate_error,
    get_success_data,
    set_clock,
    register_applicant,
    create_draft_case,
    file_case,
    schedule_biometrics_for,
    make_officer_headers,
    create_biometrics_payload,
)


# NOTE: TestSameCaseBiometricsHalfOpenWindowOverlap (overlap-on-second-schedule
# and back-to-back boundary tests) was removed during Step-7 iteration. PRD §3.3
# requires the parent case to be in FILED to schedule biometrics; after the first
# schedule the case advances to BIOMETRICS_SCHEDULED, so any second
# schedule_biometrics call hits ERR_INVALID_STATE before the overlap check fires.
# Per PRD §2.11, ERR_INVALID_STATE has priority over ERR_APPT_OVERLAP_SAME_CASE,
# so the overlap-rule assertion (and the back-to-back happy-path assertion) are
# not uniquely derivable from the PRD given the case state machine — the only
# pathway to two SCHEDULED biometrics on the same case is reschedule, which
# already transitions the OLD appointment to RESCHEDULED before the overlap
# check runs (so no overlap with itself either). Deleted per STEP 1b
# (UNIQUE DERIVABILITY) of the diagnostic protocol.


class TestAscLocationPointInstantCollision:
    """Two different cases trying to book biometrics at the EXACT same
    scheduled_at at the SAME ASC location collide regardless of duration."""

    def test_same_instant_same_asc_rejected_with_slot_taken(self, api):
        """PRD §3.3: "at any single ASC location identified by `asc_location_code`, the
        server enforces a per-instant capacity of exactly one for `SCHEDULED`
        biometrics appointments: two appointments at the same location whose
        `scheduled_at` instants are equal collide regardless of duration, and
        the second is rejected with `ERR_ASC_SLOT_TAKEN`."

        Design: Difficulty/resource_temporal_overlap/asc_location_point_instant_collision_capacity_one_resource_asc
        """
        set_clock("2026-06-15T00:00:00Z")
        applicant_a = register_applicant()
        applicant_b = register_applicant()
        case_a = create_draft_case(applicant_a, case_type="I-485")
        filed_a = file_case(case_a, applicant_a)
        officer_a = make_officer_headers(filed_a["assigned_officer_id"])
        schedule_biometrics_for(filed_a["id"], officer_a,
                                scheduled_at="2026-07-02T15:00:00Z",
                                asc_location_code="ASC-SF-09")

        case_b = create_draft_case(applicant_b, case_type="I-485")
        filed_b = file_case(case_b, applicant_b)
        officer_b = make_officer_headers(filed_b["assigned_officer_id"])
        res = api.schedule_biometrics(
            filed_b["id"],
            create_biometrics_payload("2026-07-02T15:00:00Z", "ASC-SF-09"),
            officer_b,
        )
        validate_error(res, "ERR_ASC_SLOT_TAKEN")

    def test_first_appointment_survives_after_slot_taken_rejection(self, api):
        """PRD §2.10 (failure contract): "no state is mutated"

        Design: Difficulty/resource_temporal_overlap/asc_location_point_instant_collision_capacity_one_resource_asc
        """
        set_clock("2026-06-15T00:00:00Z")
        applicant_a = register_applicant()
        applicant_b = register_applicant()
        case_a = create_draft_case(applicant_a, case_type="I-485")
        filed_a = file_case(case_a, applicant_a)
        officer_a = make_officer_headers(filed_a["assigned_officer_id"])
        first = schedule_biometrics_for(filed_a["id"], officer_a,
                                        scheduled_at="2026-07-02T15:00:00Z",
                                        asc_location_code="ASC-SF-09")
        case_b = create_draft_case(applicant_b, case_type="I-485")
        filed_b = file_case(case_b, applicant_b)
        officer_b = make_officer_headers(filed_b["assigned_officer_id"])
        api.schedule_biometrics(
            filed_b["id"],
            create_biometrics_payload("2026-07-02T15:00:00Z", "ASC-SF-09"),
            officer_b,
        )
        # First appointment must still be SCHEDULED.
        first_after = get_success_data(api.get_biometrics(first["id"], officer_a))
        assert first_after["status"] == "SCHEDULED"
