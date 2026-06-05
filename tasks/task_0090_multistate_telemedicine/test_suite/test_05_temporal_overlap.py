"""License half-open period overlap and visit point-plus-buffer slot conflict.

Depth coverage for the two distinct interval geometries: half-open [effective, expiration)
overlap on StateLicense (adjacency allowed), and symmetric 30-minute exclusive buffer on
Visit.scheduled_at (a gap of exactly 30 abuts and is accepted).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    make_patient_headers,
    board_headers,
    set_clock,
    create_physician,
    issue_license,
    create_patient,
    request_visit,
    setup_licensed_physician,
)


class TestLicensePeriodOverlap:
    """Half-open interval overlap is rejected; adjacency at the shared endpoint is allowed."""

    def test_overlapping_license_period_rejected(self, api):
        """PRD §3.1: "a new license for the same `physician_id` and `state_code` is
        rejected with `ERR_LICENSE_PERIOD_OVERLAP` if its interval overlaps that of any
        existing non-`REVOKED` license for that same physician and state."
        PRD §3.1: "Two intervals overlap when the new license's `effective_date` is earlier
        than the existing license's `expiration_date` and the existing license's
        `effective_date` is earlier than the new license's `expiration_date`."

        Design: Difficulty/resource_temporal_overlap/state_license_half_open_period_overlap_rejected
        """
        physician = create_physician(home_state_code="CA")
        issue_license(physician["id"], state_code="CA", issuance_type="FULL",
                      effective_date="2026-01-01T00:00:00.000Z", expiration_date="2026-07-01T00:00:00.000Z")
        # New [2026-06-30, 2027-06-30) overlaps existing [2026-01-01, 2026-07-01).
        res = api.create_state_license(physician["id"], {
            "state_code": "CA", "issuance_type": "FULL",
            "effective_date": "2026-06-30T00:00:00.000Z", "expiration_date": "2027-06-30T00:00:00.000Z",
        }, board_headers())
        validate_error(res, "ERR_LICENSE_PERIOD_OVERLAP")
        data, meta = validate_paginated(api.list_state_licenses(physician["id"], board_headers()))
        assert meta["total_count"] == 1, (
            f"overlapping license should not be created; expected 1 license, got {meta['total_count']}"
        )

    def test_adjacent_license_period_accepted(self, api):
        """PRD §3.1: "Adjacency is explicitly allowed: when the new license's
        `effective_date` equals an existing license's `expiration_date`, the two half-open
        intervals share only the excluded endpoint and therefore do not overlap, so
        consecutive non-overlapping terms in the same state are valid."

        Design: Difficulty/resource_temporal_overlap/state_license_half_open_period_overlap_rejected
        """
        physician = create_physician(home_state_code="CA")
        issue_license(physician["id"], state_code="CA", issuance_type="FULL",
                      effective_date="2026-01-01T00:00:00.000Z", expiration_date="2026-07-01T00:00:00.000Z")
        # New starts exactly at prior expiration -> adjacency, accepted.
        res = api.create_state_license(physician["id"], {
            "state_code": "CA", "issuance_type": "FULL",
            "effective_date": "2026-07-01T00:00:00.000Z", "expiration_date": "2027-01-01T00:00:00.000Z",
        }, board_headers())
        created = validate_success(res, 201)
        assert created["status"] == "ACTIVE", f"adjacent license should be created ACTIVE, got {created['status']}"


class TestVisitSlotBuffer:
    """Point-plus-30-minute symmetric exclusive buffer; a gap of exactly 30 abuts."""

    def test_visit_within_buffer_rejected(self, api):
        """PRD §3.2: "a new visit conflicts with any existing non-terminal visit for the
        same `physician_id` — that is, any visit whose `status` is not `CANCELLED`,
        `VOIDED`, or `COMPLETED` — when the absolute difference between the two
        `scheduled_at` instants is strictly less than thirty minutes."
        PRD §3.2: "A conflicting request is rejected with `ERR_VISIT_SLOT_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/visit_point_buffer_slot_conflict_rejected
        """
        physician, _ = setup_licensed_physician(state_code="CA")
        patient = create_patient(residence_state_code="CA")
        request_visit(physician["id"], patient["id"], determined_state_code="CA",
                      scheduled_at="2026-04-01T10:00:00.000Z")
        # Second visit 29 minutes later -> within the 30-min exclusive buffer.
        res = api.create_visit({
            "physician_id": physician["id"], "patient_id": patient["id"], "modality": "VIDEO",
            "scheduled_at": "2026-04-01T10:29:00.000Z", "determined_state_code": "CA", "list_fee_cents": 10000,
        }, make_patient_headers(patient["id"]))
        validate_error(res, "ERR_VISIT_SLOT_CONFLICT")
        data, meta = validate_paginated(api.list_visits(board_headers(), params={"physician_id": physician["id"]}))
        assert meta["total_count"] == 1, (
            f"conflicting visit should not be created; expected 1 visit, got {meta['total_count']}"
        )

    def test_visit_exactly_thirty_minutes_apart_accepted(self, api):
        """PRD §3.2: "The thirty-minute buffer is an exclusive boundary: a gap of exactly
        thirty minutes does not conflict, because the two slots merely abut."

        Design: Difficulty/resource_temporal_overlap/visit_point_buffer_slot_conflict_rejected
        """
        physician, _ = setup_licensed_physician(state_code="CA")
        patient = create_patient(residence_state_code="CA")
        request_visit(physician["id"], patient["id"], determined_state_code="CA",
                      scheduled_at="2026-04-01T10:00:00.000Z")
        # Second visit exactly 30 minutes later -> abuts, accepted.
        res = api.create_visit({
            "physician_id": physician["id"], "patient_id": patient["id"], "modality": "VIDEO",
            "scheduled_at": "2026-04-01T10:30:00.000Z", "determined_state_code": "CA", "list_fee_cents": 10000,
        }, make_patient_headers(patient["id"]))
        created = validate_success(res, 201)
        assert created["status"] == "REQUESTED", f"abutting visit should be created, got {created['status']}"
