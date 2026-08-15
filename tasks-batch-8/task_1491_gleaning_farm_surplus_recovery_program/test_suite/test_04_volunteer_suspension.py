"""Volunteer no-show accumulation, auto-suspension, and reinstatement (PRD §3.2, §3.3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    coordinator_headers,
    get_volunteer,
    harvest_event_leaving_pending_no_show,
    invite,
    make_volunteer_headers,
    new_crew_leader,
    new_event,
    new_farm,
    new_offer,
    new_vehicle,
    new_volunteer,
    publish_event,
    sign_waiver,
    validate_error,
    validate_success,
)


def _suspended_volunteer_setup():
    """Volunteer VX left PENDING on two events that both finish without them:
    two PENDING -> NO_SHOW sweeps push no_show_count to 2."""
    farm = new_farm(farm_name="FV", county_code="VVV")
    lead = new_crew_leader()
    coord = new_volunteer(full_name="Coord V")
    vx = new_volunteer(full_name="Vol X")
    common = {"farm": farm, "lead": lead, "coord": coord,
              "county_code": "VVV"}
    e1 = harvest_event_leaving_pending_no_show(
        vx["id"], window_start="2026-08-05T00:00:00Z", window_end="2026-08-09T00:00:00Z",
        event_start="2026-08-06T08:00:00Z", event_end="2026-08-06T12:00:00Z",
        clock_iso="2026-08-06T09:00:00Z", **common)
    e2 = harvest_event_leaving_pending_no_show(
        vx["id"], window_start="2026-08-09T00:00:00Z", window_end="2026-08-13T00:00:00Z",
        event_start="2026-08-10T08:00:00Z", event_end="2026-08-10T12:00:00Z",
        clock_iso="2026-08-10T09:00:00Z", **common)
    return {"farm": farm, "lead": lead, "coord": coord,
            "vx": vx, "e1": e1, "e2": e2}


class TestVolunteerSuspensionCycle:
    def test_two_no_shows_suspend_volunteer(self, api):
        """PRD §3.2: "the computed `no_show_count` tracks how many of their assignments
        have ended `NO_SHOW`: when that count reaches two, the system moves the
        volunteer to `SUSPENDED`."
        PRD §3.3: "every assignment still `PENDING` becomes `NO_SHOW`, incrementing
        that volunteer's `no_show_count`"

        Design: Difficulty/non_linear_state_machine/volunteer_suspend_reinstate_cycle
        """
        ctx = _suspended_volunteer_setup()
        vx = get_volunteer(ctx["vx"]["id"])
        assert vx["no_show_count"] == 2, "two PENDING->NO_SHOW sweeps must accumulate"
        assert vx["status"] == "SUSPENDED", "count reaching 2 flips ACTIVE -> SUSPENDED"
        assert ctx["e1"]["target_assignment"]["status"] == "NO_SHOW"
        assert ctx["e2"]["target_assignment"]["status"] == "NO_SHOW"

    def test_reinstate_restores_active_and_resets_counter(self, api):
        """PRD §3.2: "A coordinator can later reinstate a suspended volunteer,
        returning them to `ACTIVE` and resetting `no_show_count` to zero."

        Design: Difficulty/non_linear_state_machine/volunteer_suspend_reinstate_cycle
        """
        ctx = _suspended_volunteer_setup()
        resp = api.reinstate_volunteer(ctx["vx"]["id"], coordinator_headers())
        validate_success(resp, 200)
        vx = get_volunteer(ctx["vx"]["id"])
        assert vx["status"] == "ACTIVE"
        assert vx["no_show_count"] == 0, "reinstate resets the no-show counter"


class TestFinishCascadeSuspension:
    def test_finish_cascade_suspends_after_two_no_shows(self, api):
        """PRD §3.3: "The finish sweep resolves the whole roster: every `CONFIRMED`
        assignment becomes `COMPLETED`, and every assignment still `PENDING` becomes
        `NO_SHOW`, incrementing that volunteer's `no_show_count` and flipping the
        volunteer to `SUSPENDED` when the count reaches two."

        Design: Difficulty/transitive_cascade/event_finish_noshow_suspension_depth3
        """
        ctx = _suspended_volunteer_setup()
        vx = get_volunteer(ctx["vx"]["id"])
        assert vx["no_show_count"] == 2
        assert vx["status"] == "SUSPENDED", (
            "the finish cascade crossed event -> assignment -> volunteer"
        )

    def test_suspended_volunteer_confirm_rejected(self, api):
        """PRD §3.2: "Last, standing: a `SUSPENDED` volunteer cannot confirm and is
        rejected with `ERR_VOLUNTEER_SUSPENDED`."

        Design: Difficulty/transitive_cascade/event_finish_noshow_suspension_depth3
        """
        ctx = _suspended_volunteer_setup()
        # A third, still-OPEN event on a fresh offer; VX is invited and waivered.
        farm = ctx["farm"]
        lead = ctx["lead"]
        vehicle = new_vehicle()
        offer3 = new_offer(
            farm["id"], estimated_lbs=50.0,
            window_start="2026-08-14T00:00:00Z", window_end="2026-08-25T00:00:00Z",
        )
        ev3 = new_event(offer3["id"], lead["id"], vehicle["id"],
                        scheduled_start="2026-08-15T08:00:00Z",
                        scheduled_end="2026-08-15T12:00:00Z", crew_capacity=3)
        publish_event(ev3["id"])
        asg3 = invite(ev3["id"], ctx["vx"]["id"])
        sign_waiver(ev3["id"], ctx["vx"]["id"], lead["id"])

        resp = api.confirm_assignment(asg3["id"], make_volunteer_headers(ctx["vx"]["id"]))
        validate_error(resp, ApiErrorId.ERR_VOLUNTEER_SUSPENDED, 422)
        assert get_volunteer(ctx["vx"]["id"])["status"] == "SUSPENDED"
