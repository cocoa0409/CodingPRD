"""Visit scheduling: inspector travel buffer and facility-state gating."""
from test_helpers import (
    ApiErrorId,
    create_approved_facility,
    create_facility_for,
    create_prospect_client,
    schedule_visit,
    validate_error,
    validate_success,
)


class TestInspectorTravelBuffer:
    def test_inspector_visit_travel_buffer_strict_inequality_edges(
            self, api, account_manager_headers):
        """PRD section 3.5: "reject exactly when the new start is strictly
        earlier than the existing end plus two hours and the new end is strictly
        later than the existing start minus two hours. Both inequalities are
        strict, so a visit starting exactly at the existing end plus two hours
        is allowed."

        Design: Difficulty/resource_temporal_overlap/inspector_visit_travel_buffer_strict_inequality_edges
        """
        client = create_prospect_client(legal_name="Buffer Co")
        facility = create_facility_for(client["id"], name="B2 Plant")
        schedule_visit(facility["id"], visit_type="INITIAL",
                       inspector_user_id="sup-1",
                       scheduled_start="2026-08-03T10:00:00Z",
                       scheduled_end="2026-08-03T12:00:00Z")

        # 13:00 < 12:00 + 2h and 15:00 > 10:00 - 2h: conflict.
        resp = api.create_visit(
            {"facility_id": facility["id"], "visit_type": "ROUTINE",
             "inspector_user_id": "sup-1",
             "scheduled_start": "2026-08-03T13:00:00Z",
             "scheduled_end": "2026-08-03T15:00:00Z"},
            account_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INSPECTOR_SCHEDULE_CONFLICT)

        # 14:00 < 14:00 is false: the exact buffer edge is allowed.
        edge = validate_success(api.create_visit(
            {"facility_id": facility["id"], "visit_type": "ROUTINE",
             "inspector_user_id": "sup-1",
             "scheduled_start": "2026-08-03T14:00:00Z",
             "scheduled_end": "2026-08-03T16:00:00Z"},
            account_manager_headers), 201)
        assert edge["status"] == "SCHEDULED"

        # The buffer is per-inspector: sup-2 may overlap sup-1 freely.
        other = validate_success(api.create_visit(
            {"facility_id": facility["id"], "visit_type": "ROUTINE",
             "inspector_user_id": "sup-2",
             "scheduled_start": "2026-08-03T11:00:00Z",
             "scheduled_end": "2026-08-03T13:00:00Z"},
            account_manager_headers), 201)
        assert other["status"] == "SCHEDULED"

    def test_inspector_travel_buffer_leading_edge(self, api,
                                                  account_manager_headers):
        """PRD section 3.5: "An inspector double-booking guard rejects the
        schedule with `ERR_INSPECTOR_SCHEDULE_CONFLICT` when the new visit
        intersects any `SCHEDULED` or `IN_PROGRESS` visit of the same inspector
        after expanding that existing visit by a two-hour travel buffer on both
        sides".

        Design: Difficulty/resource_temporal_overlap/inspector_visit_travel_buffer_strict_inequality_edges
        """
        client = create_prospect_client(legal_name="Buffer Co 2")
        facility = create_facility_for(client["id"], name="B3 Plant")
        schedule_visit(facility["id"], visit_type="INITIAL",
                       inspector_user_id="sup-1",
                       scheduled_start="2026-08-03T10:00:00Z",
                       scheduled_end="2026-08-03T12:00:00Z")

        # New visit ending exactly at existing_start - 2h: 08:00 > 08:00 is
        # false, so no conflict.
        edge = validate_success(api.create_visit(
            {"facility_id": facility["id"], "visit_type": "ROUTINE",
             "inspector_user_id": "sup-1",
             "scheduled_start": "2026-08-03T06:00:00Z",
             "scheduled_end": "2026-08-03T08:00:00Z"},
            account_manager_headers), 201)
        assert edge["status"] == "SCHEDULED"

        # One minute inside the buffer: 08:01 > 08:00 and 06:00 < 14:00.
        resp = api.create_visit(
            {"facility_id": facility["id"], "visit_type": "ROUTINE",
             "inspector_user_id": "sup-1",
             "scheduled_start": "2026-08-03T05:00:00Z",
             "scheduled_end": "2026-08-03T08:01:00Z"},
            account_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INSPECTOR_SCHEDULE_CONFLICT)


class TestInitialVisitFacilityGate:
    def test_initial_visit_gated_on_facility_pending_review(
            self, api, account_manager_headers):
        """PRD section 3.5: "An `INITIAL` visit requires the facility to be in
        `PENDING_REVIEW`; the other types require only that the facility is not
        `DECOMMISSIONED`."

        Design: Difficulty/cross_entity_state_dependency/initial_visit_gated_on_facility_pending_review
        """
        client = create_prospect_client(legal_name="Init Co")
        facility, _line = create_approved_facility(client["id"])
        assert facility["status"] == "APPROVED"

        resp = api.create_visit(
            {"facility_id": facility["id"], "visit_type": "INITIAL",
             "inspector_user_id": "sup-4",
             "scheduled_start": "2026-07-01T09:00:00Z",
             "scheduled_end": "2026-07-01T12:00:00Z"},
            account_manager_headers)
        validate_error(resp, ApiErrorId.ERR_FACILITY_INVALID_STATE)

        routine = validate_success(api.create_visit(
            {"facility_id": facility["id"], "visit_type": "ROUTINE",
             "inspector_user_id": "sup-4",
             "scheduled_start": "2026-07-01T09:00:00Z",
             "scheduled_end": "2026-07-01T12:00:00Z"},
            account_manager_headers), 201)
        assert routine["status"] == "SCHEDULED", (
            "ROUTINE remains legal on an APPROVED facility")

    def test_initial_visit_accepted_while_facility_pending_review(
            self, api, account_manager_headers):
        """PRD section 3.5: "An `INITIAL` visit requires the facility to be in
        `PENDING_REVIEW`; the other types require only that the facility is not
        `DECOMMISSIONED`."

        Design: Difficulty/cross_entity_state_dependency/initial_visit_gated_on_facility_pending_review
        """
        client = create_prospect_client(legal_name="Init Co 2")
        facility = create_facility_for(client["id"], name="I2 Plant")
        assert facility["status"] == "PENDING_REVIEW"
        visit = validate_success(api.create_visit(
            {"facility_id": facility["id"], "visit_type": "INITIAL",
             "inspector_user_id": "sup-4",
             "scheduled_start": "2026-07-01T09:00:00Z",
             "scheduled_end": "2026-07-01T12:00:00Z"},
            account_manager_headers), 201)
        assert visit["status"] == "SCHEDULED", (
            "the INITIAL gate is open while PENDING_REVIEW")
