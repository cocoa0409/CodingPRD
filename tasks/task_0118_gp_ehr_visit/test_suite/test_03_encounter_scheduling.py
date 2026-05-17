"""Encounter scheduling: time-range, provider conflict, patient buffer.

PRD §3.3 scheduling-time constraints (ERR_INVALID_TIME_RANGE,
ERR_PROVIDER_TIME_CONFLICT, ERR_PATIENT_TIME_CONFLICT).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    anchor_clock,
    create_encounter_payload,
    iso_anchor_offset,
    schedule_encounter,
    setup_existing_patient_encounter_for_buffer,
    setup_existing_provider_encounter_for_overlap,
    setup_existing_provider_encounter_for_priority_pair,
    setup_patient_with_pcp,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.3 ERR_INVALID_TIME_RANGE — duration / ordering
# ===========================================================================
class TestInvalidTimeRange:
    """PRD §3.3 scheduling-time constraint."""

    def test_end_equals_start_rejected(self, api, receptionist_headers):
        """PRD §3.3: "The time window must satisfy scheduled_end
        strictly later than scheduled_start, and the duration from
        start to end must be no more than 120 minutes. A request
        violating either of those conditions is rejected with
        ERR_INVALID_TIME_RANGE."

        Claim: scheduled_end == scheduled_start returns
        ERR_INVALID_TIME_RANGE.
        """
        anchor_clock()
        patient, provider = setup_patient_with_pcp()
        start = iso_anchor_offset(minutes=60)
        res = api.create_encounter(
            patient["id"],
            create_encounter_payload(
                provider_id=provider["id"],
                scheduled_start=start, scheduled_end=start,
            ),
            receptionist_headers,
        )
        validate_error(res, "ERR_INVALID_TIME_RANGE")

    def test_end_before_start_rejected(self, api, receptionist_headers):
        """PRD §3.3: "The time window must satisfy scheduled_end
        strictly later than scheduled_start, and the duration from
        start to end must be no more than 120 minutes. A request
        violating either of those conditions is rejected with
        ERR_INVALID_TIME_RANGE."

        Claim: scheduled_end < scheduled_start returns
        ERR_INVALID_TIME_RANGE.
        """
        anchor_clock()
        patient, provider = setup_patient_with_pcp()
        start = iso_anchor_offset(minutes=60)
        end = iso_anchor_offset(minutes=30)
        res = api.create_encounter(
            patient["id"],
            create_encounter_payload(
                provider_id=provider["id"],
                scheduled_start=start, scheduled_end=end,
            ),
            receptionist_headers,
        )
        validate_error(res, "ERR_INVALID_TIME_RANGE")

    def test_duration_121_minutes_rejected(self, api,
                                            receptionist_headers):
        """PRD §3.3: "The time window must satisfy scheduled_end
        strictly later than scheduled_start, and the duration from
        start to end must be no more than 120 minutes."

        Claim: duration of 121 minutes is rejected; 120 minutes is
        accepted.
        """
        anchor_clock()
        patient, provider = setup_patient_with_pcp()
        start = iso_anchor_offset(minutes=60)
        end_121 = iso_anchor_offset(minutes=60 + 121)
        res = api.create_encounter(
            patient["id"],
            create_encounter_payload(
                provider_id=provider["id"],
                scheduled_start=start, scheduled_end=end_121,
            ),
            receptionist_headers,
        )
        validate_error(res, "ERR_INVALID_TIME_RANGE")

    def test_duration_120_minutes_accepted(self, api,
                                            receptionist_headers):
        """PRD §3.3: "the duration from start to end must be no more
        than 120 minutes."

        Claim: a 120-minute encounter (exactly at the inclusive
        boundary) is accepted.
        """
        anchor_clock()
        patient, provider = setup_patient_with_pcp()
        start = iso_anchor_offset(hours=2)
        end_120 = iso_anchor_offset(hours=4)
        res = api.create_encounter(
            patient["id"],
            create_encounter_payload(
                provider_id=provider["id"],
                scheduled_start=start, scheduled_end=end_120,
            ),
            receptionist_headers,
        )
        validate_success(res, expected_status=201)


# ===========================================================================
# §3.3 ERR_PROVIDER_TIME_CONFLICT — closed-open intervals
# ===========================================================================
class TestProviderTimeConflict:
    """PRD §3.3 provider closed-open overlap."""

    # difficulty: resource_temporal_overlap/provider_closed_open_overlap
    def test_provider_boundary_touch_accepted(
        self, api, receptionist_headers,
    ):
        """PRD §3.3: "The new window must not temporally overlap any
        other non-terminal encounter belonging to the same
        provider_id. Overlap here is evaluated under closed-open
        interval semantics: an existing encounter whose
        [scheduled_start, scheduled_end) shares any positive-measure
        interval with the new request's [scheduled_start,
        scheduled_end) is a conflict, but back-to-back encounters
        that meet exactly at the boundary instant are permitted."

        Claim: scheduling B starting exactly when A ends (10:30) is
        accepted on the same Provider.
        """
        setup = setup_existing_provider_encounter_for_overlap(
            start_iso="2026-07-01T10:00:00.000Z",
            end_iso="2026-07-01T10:30:00.000Z",
        )
        res = api.create_encounter(
            setup["patient_y"]["id"],
            create_encounter_payload(
                provider_id=setup["provider"]["id"],
                scheduled_start="2026-07-01T10:30:00.000Z",
                scheduled_end="2026-07-01T11:00:00.000Z",
            ),
            receptionist_headers,
        )
        validate_success(res, expected_status=201)

    # difficulty: resource_temporal_overlap/provider_closed_open_overlap
    def test_provider_one_minute_overlap_rejected(
        self, api, receptionist_headers,
    ):
        """PRD §3.3: "an existing encounter whose [scheduled_start,
        scheduled_end) shares any positive-measure interval with the
        new request's [scheduled_start, scheduled_end) is a conflict
        ... A conflict yields ERR_PROVIDER_TIME_CONFLICT."

        Claim: scheduling B with a 1-minute genuine overlap on the
        same Provider returns ERR_PROVIDER_TIME_CONFLICT.
        """
        setup = setup_existing_provider_encounter_for_overlap(
            start_iso="2026-07-01T10:00:00.000Z",
            end_iso="2026-07-01T10:30:00.000Z",
        )
        res = api.create_encounter(
            setup["patient_y"]["id"],
            create_encounter_payload(
                provider_id=setup["provider"]["id"],
                scheduled_start="2026-07-01T10:29:00.000Z",
                scheduled_end="2026-07-01T10:59:00.000Z",
            ),
            receptionist_headers,
        )
        validate_error(res, "ERR_PROVIDER_TIME_CONFLICT")


# ===========================================================================
# §3.3 ERR_PATIENT_TIME_CONFLICT — closed-closed 15-min buffer
# ===========================================================================
class TestPatientTimeConflict:
    """PRD §3.3 patient closed-closed 15-min buffer."""

    # difficulty: resource_temporal_overlap/patient_closed_closed_15min_buffer_overlap
    def test_patient_15min_buffer_inclusive_rejected(
        self, api, receptionist_headers,
    ):
        """PRD §3.3: "the new window is rejected if any other
        non-terminal encounter for the same patient ends within 15
        minutes before the new scheduled_start or begins within 15
        minutes after the new scheduled_end. A conflict yields
        ERR_PATIENT_TIME_CONFLICT. Back-to-back patient visits within
        15 minutes are forbidden."

        Claim: scheduling B exactly 15 minutes after A ends on the
        SAME patient is rejected (the buffer is inclusive).
        """
        setup = setup_existing_patient_encounter_for_buffer(
            start_iso="2026-07-01T10:00:00.000Z",
            end_iso="2026-07-01T10:30:00.000Z",
        )
        res = api.create_encounter(
            setup["patient"]["id"],
            create_encounter_payload(
                provider_id=setup["provider_b"]["id"],
                scheduled_start="2026-07-01T10:45:00.000Z",
                scheduled_end="2026-07-01T11:00:00.000Z",
            ),
            receptionist_headers,
        )
        validate_error(res, "ERR_PATIENT_TIME_CONFLICT")

    # difficulty: resource_temporal_overlap/patient_closed_closed_15min_buffer_overlap
    def test_patient_16min_after_accepted(
        self, api, receptionist_headers,
    ):
        """PRD §3.3: "the new window is rejected if any other
        non-terminal encounter for the same patient ends within 15
        minutes before the new scheduled_start or begins within 15
        minutes after the new scheduled_end. ... Back-to-back patient
        visits within 15 minutes are forbidden."

        Claim: scheduling B 16 minutes after A ends on the SAME
        patient passes (outside the inclusive 15-min buffer).
        """
        setup = setup_existing_patient_encounter_for_buffer(
            start_iso="2026-07-01T10:00:00.000Z",
            end_iso="2026-07-01T10:30:00.000Z",
        )
        res = api.create_encounter(
            setup["patient"]["id"],
            create_encounter_payload(
                provider_id=setup["provider_b"]["id"],
                scheduled_start="2026-07-01T10:46:00.000Z",
                scheduled_end="2026-07-01T11:01:00.000Z",
            ),
            receptionist_headers,
        )
        validate_success(res, expected_status=201)


# ===========================================================================
# §2.7 / §3.3 priority pair: ERR_INVALID_TIME_RANGE vs
# ERR_PROVIDER_TIME_CONFLICT
# ===========================================================================
class TestSchedulingValidationPriority:
    """Verifies the documented §2.7 ordering of business validations
    that fire together on /encounters create."""

    # difficulty: priority_pair_validation_conflict/business_referential_vs_business_temporal_on_referral_create
    def test_invalid_time_range_wins_over_provider_conflict(
        self, api, receptionist_headers,
    ):
        """PRD §2.7: "Business-safety, business-referential,
        business-temporal, business-constraint, and business-fiscal
        rules, evaluated in the order in which they are described in
        §3."

        PRD §3.3 lists the time-range check ("The time window must
        satisfy scheduled_end strictly later than scheduled_start,
        and the duration from start to end must be no more than 120
        minutes.") BEFORE the provider-overlap check ("The new
        window must not temporally overlap any other non-terminal
        encounter belonging to the same provider_id."). So when both
        fail, ERR_INVALID_TIME_RANGE wins over
        ERR_PROVIDER_TIME_CONFLICT.

        Claim: a request with scheduled_end == scheduled_start AND
        within the existing provider window returns
        ERR_INVALID_TIME_RANGE, NOT ERR_PROVIDER_TIME_CONFLICT.
        """
        setup = setup_existing_provider_encounter_for_priority_pair()
        # 10:00 == 10:00 (invalid range) AND inside E0
        # (10:00..10:30) → both checks would fail.
        res = api.create_encounter(
            setup["patient"]["id"],
            create_encounter_payload(
                provider_id=setup["provider"]["id"],
                scheduled_start="2026-06-01T10:00:00.000Z",
                scheduled_end="2026-06-01T10:00:00.000Z",
            ),
            receptionist_headers,
        )
        validate_error(res, "ERR_INVALID_TIME_RANGE")

    # difficulty: priority_pair_validation_conflict/business_referential_vs_business_temporal_on_referral_create
    def test_provider_conflict_when_time_range_valid(
        self, api, receptionist_headers,
    ):
        """PRD §3.3: "an existing encounter whose [scheduled_start,
        scheduled_end) shares any positive-measure interval with the
        new request's [scheduled_start, scheduled_end) is a conflict
        ... A conflict yields ERR_PROVIDER_TIME_CONFLICT."

        Claim: with a VALID time range (start < end, duration <= 120)
        but inside the existing provider window, the response is
        ERR_PROVIDER_TIME_CONFLICT — confirming that absent the
        higher-priority ERR_INVALID_TIME_RANGE failure, the
        provider-conflict rule does fire.
        """
        setup = setup_existing_provider_encounter_for_priority_pair()
        res = api.create_encounter(
            setup["patient"]["id"],
            create_encounter_payload(
                provider_id=setup["provider"]["id"],
                scheduled_start="2026-06-01T10:05:00.000Z",
                scheduled_end="2026-06-01T10:20:00.000Z",
            ),
            receptionist_headers,
        )
        validate_error(res, "ERR_PROVIDER_TIME_CONFLICT")
