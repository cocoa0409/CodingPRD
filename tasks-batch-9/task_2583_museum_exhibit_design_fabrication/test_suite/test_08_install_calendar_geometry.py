"""The two interval geometries of the install calendar.

A window's buffers belong to the window that carries them, so the shift that
refuses a neighbour is the neighbour itself; a dust-generating shift takes the
larger of the 120-minute floor and the zone's own settling period; and gallery
closures are counted across the whole project on their nominal instants with the
shared instant counted twice, which the half-open per-zone rule ignores. Every
test builds its own commission and asserts the pinned buffers, effective instants
and refusals of PRD sections 3.8 and 2.11.
"""

import datetime

from test_helpers import (
    ERR_CLOSURE_CAPACITY_EXCEEDED,
    ERR_ZONE_WINDOW_CONFLICT,
    OBJECTIVE_PRIMARY,
    OPERATIONS,
    PM,
    PackageStage,
    Phase,
    WindowDecision,
    WindowStatus,
    WorkClass,
    get_success_data,
    validate_error,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

DAY = "2026-09-10"


def _instant(value):
    """Parse an ISO 8601 UTC instant so two spellings of one moment compare equal."""
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _at(clock_time):
    """The named wall-clock minute of the single install day these tests schedule."""
    return "%sT%s:00Z" % (DAY, clock_time)


def _commission_in_fabrication(api, zone_specs, project_overrides=None):
    """Walk a fresh commission to FABRICATION with the requested gallery zones.

    Two interactives carry the project's two learning objectives between them, so
    the objective-coverage gate on the advance into FABRICATION is satisfied
    without any artifact case competing for a zone slot.
    """
    fx.set_clock(api)
    project = fx.create_project(api, **(project_overrides or {}))
    project_id = project["id"]
    fx.advance(api, project_id, Phase.SCHEMATIC)
    zones = [fx.create_zone(api, project_id, **spec) for spec in zone_specs]
    fx.create_interactive(
        api, project_id, code="INT-RIVER", objective_code=OBJECTIVE_PRIMARY
    )
    fx.create_interactive(api, project_id)
    fx.approve_package(api, project_id, PackageStage.SCHEMATIC)
    fx.advance(api, project_id, Phase.DESIGN_DEV)
    fx.approve_package(api, project_id, PackageStage.DESIGN_DEV)
    fx.advance(api, project_id, Phase.FABRICATION)
    return project_id, zones


def _request_window(api, project_id, zone_id, start, end, **overrides):
    """Ask for a shift on a zone between the two named minutes of the install day."""
    return fx.create_window(
        api, project_id, zone_id, starts_at=_at(start), ends_at=_at(end), **overrides
    )


def _refuse_approval(api, window_id, expected_error, expected_status):
    """Rule APPROVE on a window and require the named refusal, leaving it REQUESTED."""
    response = api.window_decision(
        window_id, f.window_decision_payload(WindowDecision.APPROVE), OPERATIONS
    )
    validate_error(response, expected_error, expected_status)
    still = get_success_data(api.get_install_window(window_id, PM), 200)
    assert still["status"] == WindowStatus.REQUESTED
    return still


# ---------------------------------------------------------------------------
# the buffer belongs to the neighbour, not to the window being judged
# ---------------------------------------------------------------------------
def test_two_quiet_shifts_may_sit_back_to_back_on_one_zone(api):
    """Zero-buffer shifts that touch at a single instant both get approved.

    "The `effective_start_at` is the `starts_at` moved earlier by the pre-access buffer and the `effective_end_at` is the `ends_at` moved later by the settling buffer; these two effective instants, not the nominal ones, are what the calendar reasons about."
    "Touching edges therefore do not conflict, which is why two `QUIET` windows, whose buffers are both zero, may sit back to back with a zero-minute gap, while two `DUST_GENERATING` windows an hour apart do conflict because each has spread two hours past its nominal end."
    Design: Difficulty/resource_temporal_overlap/the_buffer_belongs_to_the_neighbouring_window_not_the_one_being_approved
    """
    project_id, zones = _commission_in_fabrication(api, [{}])
    zone_id = zones[0]["id"]

    morning = _request_window(api, project_id, zone_id, "08:00", "10:15")
    assert morning["pre_access_buffer_minutes"] == 0
    assert morning["settling_buffer_minutes"] == 0
    assert _instant(morning["effective_start_at"]) == _instant(_at("08:00"))
    assert _instant(morning["effective_end_at"]) == _instant(_at("10:15"))
    assert fx.decide_window(api, morning["id"])["status"] == WindowStatus.APPROVED

    midday = _request_window(api, project_id, zone_id, "10:15", "11:00")
    approved = fx.decide_window(api, midday["id"])
    assert approved["status"] == WindowStatus.APPROVED
    assert _instant(approved["effective_start_at"]) == _instant(_at("10:15"))


def test_a_noisy_shift_spreads_its_effective_bounds_by_its_own_two_buffers(api):
    """The noisy shift reaches a quarter hour back and half an hour forward.

    "The `pre_access_buffer_minutes` — the time the crew needs to protect objects and lay down floor covering before the nominal start — is 0 for `QUIET`, 15 for `NOISY`, 30 for `DUST_GENERATING` and 45 for `CRANE_ACCESS`."
    "The `effective_start_at` is the `starts_at` moved earlier by the pre-access buffer and the `effective_end_at` is the `ends_at` moved later by the settling buffer; these two effective instants, not the nominal ones, are what the calendar reasons about."
    Design: Difficulty/resource_temporal_overlap/the_buffer_belongs_to_the_neighbouring_window_not_the_one_being_approved
    """
    project_id, zones = _commission_in_fabrication(api, [{}])
    zone_id = zones[0]["id"]

    noisy = _request_window(
        api, project_id, zone_id, "12:00", "14:00", work_class=WorkClass.NOISY
    )
    assert noisy["pre_access_buffer_minutes"] == 15
    assert noisy["settling_buffer_minutes"] == 30
    assert _instant(noisy["effective_start_at"]) == _instant(_at("11:45"))
    assert _instant(noisy["effective_end_at"]) == _instant(_at("14:30"))

    approved = fx.decide_window(api, noisy["id"])
    assert approved["status"] == WindowStatus.APPROVED
    assert approved["pre_access_buffer_minutes"] == 15
    assert approved["settling_buffer_minutes"] == 30


def test_the_neighbours_pre_access_buffer_refuses_the_zero_buffer_shift_behind_it(api):
    """A quiet shift ending at 11:45 is fine while one starting at 11:46 is not.

    "Two windows on the same zone conflict when the interval each defines with its effective instants overlaps the other's, and the comparison is **half-open**: they conflict when the new window's `effective_start_at` is strictly before the other's `effective_end_at` and the other's `effective_start_at` is strictly before the new window's `effective_end_at`."
    Design: Difficulty/resource_temporal_overlap/the_buffer_belongs_to_the_neighbouring_window_not_the_one_being_approved
    """
    project_id, zones = _commission_in_fabrication(api, [{}])
    zone_id = zones[0]["id"]
    noisy = _request_window(
        api, project_id, zone_id, "12:00", "14:00", work_class=WorkClass.NOISY
    )
    fx.decide_window(api, noisy["id"])

    up_to_the_buffer = _request_window(api, project_id, zone_id, "11:30", "11:45")
    assert up_to_the_buffer["pre_access_buffer_minutes"] == 0
    assert fx.decide_window(api, up_to_the_buffer["id"])["status"] == WindowStatus.APPROVED

    inside_the_buffer = _request_window(api, project_id, zone_id, "11:46", "11:50")
    assert inside_the_buffer["pre_access_buffer_minutes"] == 0
    assert _instant(inside_the_buffer["effective_start_at"]) == _instant(_at("11:46"))
    _refuse_approval(api, inside_the_buffer["id"], ERR_ZONE_WINDOW_CONFLICT, 409)


# ---------------------------------------------------------------------------
# the dust settling buffer takes the larger of the floor and the zone override
# ---------------------------------------------------------------------------
def _dust_shift_on_each_zone(api):
    """One identical dust-generating shift on a slow-venting zone and a fast one.

    The first zone vents in 240 minutes, four hours, well past the constant floor;
    the second claims 60 minutes, an hour under it.
    """
    project_id, zones = _commission_in_fabrication(
        api,
        [
            {
                "zone_code": "Z-A",
                "visitor_route_order": 1,
                "dust_settling_buffer_minutes": 240,
            },
            {
                "zone_code": "Z-B",
                "visitor_route_order": 2,
                "dust_settling_buffer_minutes": 60,
            },
        ],
    )
    slow_zone, quick_zone = zones
    shifts = {}
    for key, zone in (("slow", slow_zone), ("quick", quick_zone)):
        shifts[key] = _request_window(
            api,
            project_id,
            zone["id"],
            "08:00",
            "10:00",
            work_class=WorkClass.DUST_GENERATING,
            noise_dba=70.0,
        )
    return project_id, slow_zone, quick_zone, shifts


def test_the_settling_buffer_takes_the_larger_of_the_constant_and_the_zone_override(api):
    """The same dust shift settles for four hours on one zone and two on the other.

    "The `settling_buffer_minutes` — the time airborne dust and noise need to clear before visitors return — is 0 for `QUIET`, 30 for `NOISY`, 120 for `DUST_GENERATING` and 60 for `CRANE_ACCESS`, except that for `DUST_GENERATING` work the buffer is the **larger** of that 120-minute floor and the zone's own `dust_settling_buffer_minutes`, so a zone with a slow air exchange lengthens the window it hosts."
    Design: Difficulty/resource_temporal_overlap/the_dust_settling_buffer_takes_the_larger_of_the_constant_and_the_zone_override
    """
    project_id, slow_zone, quick_zone, shifts = _dust_shift_on_each_zone(api)

    assert slow_zone["dust_settling_buffer_minutes"] == 240
    assert quick_zone["dust_settling_buffer_minutes"] == 60

    slow = shifts["slow"]
    assert slow["pre_access_buffer_minutes"] == 30
    assert slow["settling_buffer_minutes"] == 240
    assert _instant(slow["effective_start_at"]) == _instant(_at("07:30"))
    assert _instant(slow["effective_end_at"]) == _instant(_at("14:00"))

    quick = shifts["quick"]
    assert quick["pre_access_buffer_minutes"] == 30
    assert quick["settling_buffer_minutes"] == 120
    assert _instant(quick["effective_start_at"]) == _instant(_at("07:30"))
    assert _instant(quick["effective_end_at"]) == _instant(_at("12:00"))

    assert fx.decide_window(api, slow["id"])["status"] == WindowStatus.APPROVED
    assert fx.decide_window(api, quick["id"])["status"] == WindowStatus.APPROVED


def test_the_slow_venting_zone_pushes_the_conflict_boundary_out_to_its_own_settling_end(api):
    """On the four-hour zone the calendar is free at 14:00 and occupied at 13:45.

    "Two windows on the same zone conflict when the interval each defines with its effective instants overlaps the other's, and the comparison is **half-open**: they conflict when the new window's `effective_start_at` is strictly before the other's `effective_end_at` and the other's `effective_start_at` is strictly before the new window's `effective_end_at`."
    Design: Difficulty/resource_temporal_overlap/the_dust_settling_buffer_takes_the_larger_of_the_constant_and_the_zone_override
    """
    project_id, slow_zone, quick_zone, shifts = _dust_shift_on_each_zone(api)
    fx.decide_window(api, shifts["slow"]["id"])

    after_settling = _request_window(api, project_id, slow_zone["id"], "14:00", "14:30")
    assert fx.decide_window(api, after_settling["id"])["status"] == WindowStatus.APPROVED

    inside_settling = _request_window(api, project_id, slow_zone["id"], "13:45", "14:00")
    _refuse_approval(api, inside_settling["id"], ERR_ZONE_WINDOW_CONFLICT, 409)


def test_the_constant_floor_governs_the_zone_whose_override_is_shorter(api):
    """On the one-hour zone the boundary sits at the 120-minute floor, not at 60.

    "Two windows on the same zone conflict when the interval each defines with its effective instants overlaps the other's, and the comparison is **half-open**: they conflict when the new window's `effective_start_at` is strictly before the other's `effective_end_at` and the other's `effective_start_at` is strictly before the new window's `effective_end_at`."
    Design: Difficulty/resource_temporal_overlap/the_dust_settling_buffer_takes_the_larger_of_the_constant_and_the_zone_override
    """
    project_id, slow_zone, quick_zone, shifts = _dust_shift_on_each_zone(api)
    fx.decide_window(api, shifts["quick"]["id"])

    after_settling = _request_window(api, project_id, quick_zone["id"], "12:00", "12:30")
    assert fx.decide_window(api, after_settling["id"])["status"] == WindowStatus.APPROVED

    inside_settling = _request_window(api, project_id, quick_zone["id"], "11:45", "12:00")
    _refuse_approval(api, inside_settling["id"], ERR_ZONE_WINDOW_CONFLICT, 409)

    late_shift = _request_window(api, project_id, quick_zone["id"], "14:00", "14:30")
    assert fx.decide_window(api, late_shift["id"])["status"] == WindowStatus.APPROVED


# ---------------------------------------------------------------------------
# the project-wide closure sweep counts the instant the per-zone rule ignores
# ---------------------------------------------------------------------------
def _commission_tolerating_one_closure(api):
    """A commission that will tolerate a single closure at a time, with one running.

    Both zones may be closed to visitors, and the morning closure on the first
    zone has already been approved.
    """
    project_id, zones = _commission_in_fabrication(
        api,
        [
            {"zone_code": "Z-A", "visitor_route_order": 1, "closure_allowed": True},
            {"zone_code": "Z-B", "visitor_route_order": 2, "closure_allowed": True},
        ],
        project_overrides={"max_concurrent_closures": 1},
    )
    morning = _request_window(
        api,
        project_id,
        zones[0]["id"],
        "08:00",
        "10:00",
        requires_gallery_closure=True,
    )
    assert fx.decide_window(api, morning["id"])["status"] == WindowStatus.APPROVED
    return project_id, zones[0], zones[1], morning


def test_two_closures_sharing_a_single_instant_exceed_a_capacity_of_one(api):
    """A closure starting exactly when the first ends is counted as concurrent.

    "It sweeps the endpoints in ascending timestamp order, adding one at each start and subtracting one at each end, and **at an equal timestamp every start is processed before every end**, with ties broken by the owning window's `created_at` ascending."
    "That ordering makes the interval closed rather than half-open, so a closure beginning at exactly the instant another ends *does* count as concurrent — the precise opposite of the per-zone rule, and the two geometries must not be conflated."
    Design: Difficulty/resource_temporal_overlap/the_project_wide_closure_capacity_counts_the_shared_instant_the_per_zone_rule_ignores
    """
    project_id, first_zone, second_zone, morning = _commission_tolerating_one_closure(api)
    project = fx.read_project(api, project_id)
    assert project["max_concurrent_closures"] == 1

    handover = _request_window(
        api,
        project_id,
        second_zone["id"],
        "10:00",
        "12:00",
        requires_gallery_closure=True,
    )
    _refuse_approval(api, handover["id"], ERR_CLOSURE_CAPACITY_EXCEEDED, 409)

    unaffected = get_success_data(api.get_install_window(morning["id"], PM), 200)
    assert unaffected["status"] == WindowStatus.APPROVED


def test_cancelling_the_rival_and_starting_a_minute_later_drops_the_peak_back_to_one(api):
    """Only APPROVED and IN_PROGRESS closures are counted, and 10:01 no longer collides.

    "The closure-capacity check considers every window in the project whose `requires_gallery_closure` is true and whose status is `APPROVED` or `IN_PROGRESS`, together with the window currently being approved, and it uses each window's **nominal** `starts_at` and `ends_at` with no buffers at all."
    "The peak is the highest running total the sweep reaches, and when it exceeds the project's `max_concurrent_closures`, which defaults to 2, the approval is refused."
    Design: Difficulty/resource_temporal_overlap/the_project_wide_closure_capacity_counts_the_shared_instant_the_per_zone_rule_ignores
    """
    project_id, first_zone, second_zone, morning = _commission_tolerating_one_closure(api)
    handover = _request_window(
        api,
        project_id,
        second_zone["id"],
        "10:00",
        "12:00",
        requires_gallery_closure=True,
    )
    _refuse_approval(api, handover["id"], ERR_CLOSURE_CAPACITY_EXCEEDED, 409)

    cancelled = fx.cancel_window(api, handover["id"])
    assert cancelled["status"] == WindowStatus.CANCELLED

    one_minute_later = _request_window(
        api,
        project_id,
        second_zone["id"],
        "10:01",
        "12:00",
        requires_gallery_closure=True,
    )
    approved = fx.decide_window(api, one_minute_later["id"])
    assert approved["status"] == WindowStatus.APPROVED
    assert _instant(approved["starts_at"]) == _instant(_at("10:01"))


def test_the_same_shared_instant_needs_no_capacity_when_no_closure_is_asked_for(api):
    """The identical span is approved on the first zone itself when it asks for no closure.

    "Fourth, and only for a closure request, the project-wide capacity sweep, answering `ERR_CLOSURE_CAPACITY_EXCEEDED` (HTTP 409)."
    "Touching edges therefore do not conflict, which is why two `QUIET` windows, whose buffers are both zero, may sit back to back with a zero-minute gap, while two `DUST_GENERATING` windows an hour apart do conflict because each has spread two hours past its nominal end."
    Design: Difficulty/resource_temporal_overlap/the_project_wide_closure_capacity_counts_the_shared_instant_the_per_zone_rule_ignores
    """
    project_id, first_zone, second_zone, morning = _commission_tolerating_one_closure(api)

    open_gallery_shift = _request_window(
        api,
        project_id,
        first_zone["id"],
        "10:00",
        "12:00",
        requires_gallery_closure=False,
    )
    approved = fx.decide_window(api, open_gallery_shift["id"])
    assert approved["status"] == WindowStatus.APPROVED
    assert approved["requires_gallery_closure"] is False
    assert _instant(approved["effective_start_at"]) == _instant(_at("10:00"))
