"""Watch rotations: overlap rule, crew-rest threshold (10h boundary), and violations."""
import pytest

from test_helpers import (
    TEST_USERS,
    confirm_assignment,
    confirm_job_order,
    create_crew_member,
    create_job_order,
    create_tariff_rate,
    create_tug,
    create_vessel,
    create_watch_rotation_payload,
    propose_assignment,
    record_passed_inspection,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import make_tug_captain_headers


def _setup_confirmed_assignment_for_watches(job_end="2026-06-03T10:00:00Z", assignment_end="2026-06-03T10:00:00Z"):
    """Tug + vessel + crew member + tariff + CONFIRMED job + CONFIRMED assignment.
    Returns (tug, crew_member, assignment)."""
    tug = create_tug(name="Tug Atlas", bollard_pull_tons=60.0)
    vessel = create_vessel(name="MV Aurora", imo_number="IMO9074729")
    crew = create_crew_member(full_name="Deckhand Okafor", crew_role="DECKHAND")
    tariff = create_tariff_rate(tariff_code="TAR-DOCK-01")
    set_clock("2026-06-01T00:00:00Z")
    job = create_job_order(
        vessel["id"],
        tariff["id"],
        scheduled_start="2026-06-01T08:00:00Z",
        scheduled_end=job_end,
    )
    job = confirm_job_order(job["id"])
    record_passed_inspection(tug["id"])
    asg = propose_assignment(
        job["id"],
        tug["id"],
        job["version"],
        window_start="2026-06-01T08:00:00Z",
        window_end=assignment_end,
    )
    confirm_assignment(asg["id"], tug["id"])
    return tug, crew, asg


class TestCrewRestBoundary:
    def test_crew_rest_exactly_ten_hours_allowed(self, api):
        """PRD §3.5: "The remainder of the day, 1,440 minutes minus the worked
        minutes, is the member's rest, and it must come to at least ten hours."

        Design: Corner/calculations/crew_rest_exactly_ten_hours_allowed
        """
        tug, crew, asg = _setup_confirmed_assignment_for_watches()
        # Prior watch: 14h worked inside the 24h lookback before the new watch start.
        res1 = api.create_watch_rotation(
            create_watch_rotation_payload(
                asg["id"],
                crew["id"],
                watch_start="2026-06-01T12:00:00Z",
                watch_end="2026-06-02T02:00:00Z",
            ),
            make_tug_captain_headers(tug["id"]),
        )
        validate_success(res1, 201)
        # New watch starts 2026-06-02T08:00; rest = 1440 - 840 = exactly 600 minutes.
        res2 = api.create_watch_rotation(
            create_watch_rotation_payload(
                asg["id"],
                crew["id"],
                watch_start="2026-06-02T08:00:00Z",
                watch_end="2026-06-02T12:00:00Z",
            ),
            make_tug_captain_headers(tug["id"]),
        )
        watch2 = validate_success(res2, 201)
        assert watch2["crew_member_id"] == crew["id"]

    def test_crew_rest_violation_returns_error(self, api):
        """PRD §3.5: "A watch that would leave the member with less rest is rejected
        with `ERR_CREW_REST_VIOLATION`."

        Design: Corner/validations/crew_rest_violation_returns_error
        """
        tug, crew, asg = _setup_confirmed_assignment_for_watches()
        # Prior watch 18h inside the 24h lookback -> rest = 360 minutes < 600.
        res1 = api.create_watch_rotation(
            create_watch_rotation_payload(
                asg["id"],
                crew["id"],
                watch_start="2026-06-01T10:00:00Z",
                watch_end="2026-06-02T04:00:00Z",
            ),
            make_tug_captain_headers(tug["id"]),
        )
        validate_success(res1, 201)
        res2 = api.create_watch_rotation(
            create_watch_rotation_payload(
                asg["id"],
                crew["id"],
                watch_start="2026-06-02T08:00:00Z",
                watch_end="2026-06-02T12:00:00Z",
            ),
            make_tug_captain_headers(tug["id"]),
        )
        validate_error(res2, "ERR_CREW_REST_VIOLATION")


class TestWatchOverlap:
    def test_overlapping_watch_returns_watch_overlap(self, api):
        """PRD §3.5: "A new watch may not overlap any existing watch of the same
        crew member under the half-open convention of §2.4; an overlapping entry is
        rejected with `ERR_WATCH_OVERLAP`."

        Design: Corner/validations/overlapping_watch_returns_watch_overlap
        """
        tug, crew, asg = _setup_confirmed_assignment_for_watches(
            job_end="2026-06-01T20:00:00Z", assignment_end="2026-06-01T20:00:00Z"
        )
        res1 = api.create_watch_rotation(
            create_watch_rotation_payload(
                asg["id"],
                crew["id"],
                watch_start="2026-06-01T08:00:00Z",
                watch_end="2026-06-01T12:00:00Z",
            ),
            make_tug_captain_headers(tug["id"]),
        )
        validate_success(res1, 201)
        # 11:00-13:00 overlaps the existing 08:00-12:00 watch.
        res2 = api.create_watch_rotation(
            create_watch_rotation_payload(
                asg["id"],
                crew["id"],
                watch_start="2026-06-01T11:00:00Z",
                watch_end="2026-06-01T13:00:00Z",
            ),
            make_tug_captain_headers(tug["id"]),
        )
        validate_error(res2, "ERR_WATCH_OVERLAP")
