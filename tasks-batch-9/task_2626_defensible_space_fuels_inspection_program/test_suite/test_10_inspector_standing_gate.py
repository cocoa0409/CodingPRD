"""Scheduling reads the inspector's standing on another entity's row."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ERR_INSPECTOR_SUSPENDED,
    create_inspector,
    create_parcel,
    get_inspector,
    inspection_payload,
    list_inspections,
    open_cycle,
    schedule_inspection,
)
from test_helpers.test_users import PROGRAM_ADMIN_HEADERS

WINDOW = ("2026-08-20T15:00:00Z", "2026-08-20T17:00:00Z")


def _staffing_world(client):
    """Two equally certified inspectors, one ACTIVE and one SUSPENDED, and a
    HIGH-hazard parcel with no inspection on it at all, so no window is occupied.
    """
    cycle = open_cycle(client)
    active = create_inspector(client, certification_level="ADVANCED", status="ACTIVE")
    suspended = create_inspector(
        client, certification_level="ADVANCED", status="SUSPENDED"
    )
    parcel = create_parcel(client)
    return {
        "cycle": cycle,
        "active": active,
        "suspended": suspended,
        "parcel": parcel,
    }


class TestInspectorStandingGate:
    """A suspended inspector cannot be assigned, and nothing is written when the
    assignment is refused."""

    def test_suspended_inspector_is_refused_and_no_workload_is_recorded(self, client):
        """The refusal is attributable to the inspector's row alone: the window is
        free, the cycle is active and the parcel is only HIGH.

        PRD: "Second, a SUSPENDED inspector cannot be assigned at all, and the
        attempt answers ERR_INSPECTOR_SUSPENDED."

        PRD: "Inspector standing - the assigned or acting inspector's status is
        ACTIVE."

        PRD: "Inspector reads expose assigned_open_count, which starts at 0 and
        thereafter tracks the inspector's live workload exactly as described in
        section 2.10."

        Design: Difficulty/cross_entity_state_dependency/inspection_scheduling_gated_on_inspector_status_active
        """
        world = _staffing_world(client)
        suspended = get_inspector(client, world["suspended"]["id"])
        assert suspended["status"] == "SUSPENDED"
        assert suspended["assigned_open_count"] == 0

        validate_error(
            client.create_inspection(
                inspection_payload(
                    world["parcel"]["id"],
                    world["cycle"]["id"],
                    world["suspended"]["id"],
                    *WINDOW
                ),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_INSPECTOR_SUSPENDED,
        )

        rows, _meta = list_inspections(client, parcel_id=world["parcel"]["id"])
        assert rows == [], "a refused booking must leave no inspection behind"
        assert get_inspector(client, world["suspended"]["id"])["assigned_open_count"] == 0

    def test_the_same_payload_succeeds_for_the_active_inspector(self, client):
        """Swapping only the inspector_id books the visit and moves that
        inspector's live workload to 1.

        PRD: "Second, a SUSPENDED inspector cannot be assigned at all, and the
        attempt answers ERR_INSPECTOR_SUSPENDED."

        PRD: "An inspector's assigned_open_count must always equal the number of
        inspections carrying that inspector_id whose status is SCHEDULED, NOTICED
        or ACCESS_DENIED."

        Design: Difficulty/cross_entity_state_dependency/inspection_scheduling_gated_on_inspector_status_active
        """
        world = _staffing_world(client)

        inspection = schedule_inspection(
            client,
            world["parcel"]["id"],
            world["cycle"]["id"],
            world["active"]["id"],
            scheduled_start_utc=WINDOW[0],
            scheduled_end_utc=WINDOW[1],
        )
        assert inspection["status"] == "SCHEDULED"
        assert inspection["inspector_id"] == world["active"]["id"]
        assert get_inspector(client, world["active"]["id"])["assigned_open_count"] == 1
        assert (
            get_inspector(client, world["suspended"]["id"])["assigned_open_count"] == 0
        )
