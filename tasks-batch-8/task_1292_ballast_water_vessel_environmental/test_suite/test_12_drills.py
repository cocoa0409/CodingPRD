"""Crew training drills: completion recurrence, officer requirement, and the
cancellation window."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_drill,
    assert_timestamp_equals,
    create_drill,
    create_vessel,
    get_drill,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers import api_client


class TestDrillCompletion:
    def test_drill_next_due_marpol_awareness_365d(self, api, vessel_master_headers):
        """PRD section 3.9: "Completion by the `VesselMaster` — supplying
        `completed_at` and the final `attendees` list — moves the drill from
        `SCHEDULED` to `COMPLETED`, stamps `completed_at`, and computes `next_due_at`
        from the drill's recurrence interval: 90 days for `BWMS_OPERATION`, 180 days
        for `EMERGENCY_BALLAST_EXCHANGE`, 90 days for `OIL_SPILL_RESPONSE`, 180 days
        for `SEWAGE_SYSTEM`, 180 days for `GARBAGE_MANAGEMENT`, and 365 days for
        `MARPOL_AWARENESS`."

        Design: Corner/calculations/drill_next_due_marpol_awareness_365d
        """
        set_clock()
        vessel = create_vessel(imo_number="9100035", vessel_name="MV Dowitcher",
                               bwms_type="NONE", gross_tonnage=8000,
                               keel_laid_date="2016-01-01T00:00:00Z",
                               ballast_capacity_m3=4000)
        drill = create_drill(vessel["id"], drill_kind="MARPOL_AWARENESS",
                             scheduled_for="2026-07-20T00:00:00Z",
                             attendees=["CREW:A", "CREW:B"])

        resp = api.complete_drill(
            vessel["id"], drill["id"],
            {"completed_at": "2026-08-05T00:00:00Z", "attendees": ["CREW:A", "CREW:B"]},
            vessel_master_headers,
        )
        completed = validate_success(resp, 200)
        assert_drill(completed)
        assert completed["completion_status"] == "COMPLETED"
        # completed_at 2026-08-05T00:00:00Z + 365 days.
        assert_timestamp_equals(completed["next_due_at"], "2027-08-05T00:00:00Z",
                                label="MARPOL_AWARENESS next_due_at")


class TestOfficerRequirement:
    def test_bwms_drill_without_officer_returns_422(self, api, vessel_master_headers):
        """PRD section 3.9: "For a `BWMS_OPERATION` drill the `officer_present` flag
        must be true — the attendee list must include at least one officer — or the
        completion is rejected with `ERR_OFFICER_REQUIRED` (HTTP 422)."

        Design: Corner/validations/bwms_drill_without_officer_returns_422
        """
        set_clock()
        vessel = create_vessel(imo_number="9100049", vessel_name="MV Upupa",
                               bwms_type="NONE", gross_tonnage=8000,
                               keel_laid_date="2016-01-01T00:00:00Z",
                               ballast_capacity_m3=4000)
        drill = create_drill(vessel["id"], drill_kind="BWMS_OPERATION",
                             scheduled_for="2026-08-20T00:00:00Z",
                             attendees=["CREW:John Doe", "CREW:Jane Roe"])

        resp = api.complete_drill(
            vessel["id"], drill["id"],
            {"completed_at": "2026-08-20T12:00:00Z",
             "attendees": ["CREW:John Doe", "CREW:Jane Roe"]},
            vessel_master_headers,
        )
        validate_error(resp, ApiErrorId.ERR_OFFICER_REQUIRED)

        current = get_drill(vessel["id"], drill["id"])
        assert current["completion_status"] == "SCHEDULED", (
            "rejected completion must leave the drill SCHEDULED"
        )


class TestCancelWindow:
    def test_drill_cancel_after_scheduled_time_returns_409(self, api, vessel_master_headers):
        """PRD section 3.9: "A drill may be cancelled by the `VesselMaster` while
        still `SCHEDULED` and no later than `scheduled_for`, moving it to
        `CANCELLED`."
        PRD section 3.9: "A drill still `SCHEDULED` more than 30 days past
        `scheduled_for` flips to `OVERDUE`"
        PRD section 2.5: "An attempt to invoke a state transition that the target
        entity's current state does not permit is rejected with `ERR_INVALID_STATE`
        (HTTP 409)"

        Design: Corner/state_machines/drill_cancel_after_scheduled_time_returns_409
        """
        set_clock()
        vessel = create_vessel(imo_number="9100027", vessel_name="MV Redshank",
                               bwms_type="NONE", gross_tonnage=8000,
                               keel_laid_date="2016-01-01T00:00:00Z",
                               ballast_capacity_m3=4000)
        # scheduled_for 2026-07-25, clock 2026-08-01: past the cancel window but
        # within the 30-day overdue grace (flips at 2026-08-24), so still SCHEDULED.
        drill = create_drill(vessel["id"], drill_kind="MARPOL_AWARENESS",
                             scheduled_for="2026-07-25T00:00:00Z", attendees=["CREW:A"])
        assert drill["completion_status"] == "SCHEDULED"

        resp = api.cancel_drill(vessel["id"], drill["id"], vessel_master_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
