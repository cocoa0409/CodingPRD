"""
The two temporal-overlap tests on inspection creation, and the opposite interval
conventions they use.

PRD §3.2: "Third and fourth are two temporal-overlap tests that share the
candidate window but deliberately use *different* interval semantics, and getting
them confused is the most common way to mis-implement this endpoint."
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import make_bridge_inspector_headers

DAY_ONE_START = "2026-09-01T08:00:00Z"
DAY_ONE_END = "2026-09-01T16:00:00Z"
ADJACENT_START = "2026-09-01T16:00:00Z"
ADJACENT_END = "2026-09-01T20:00:00Z"
ONE_MINUTE_EARLY = "2026-09-01T15:59:00Z"

BUFFER_EXACT_START = "2026-09-04T16:00:00Z"
BUFFER_EXACT_END = "2026-09-04T20:00:00Z"
ONE_HOUR_INSIDE = "2026-09-04T15:00:00Z"


def _open_window(client, bridge_id, leader_id, start, end, inspection_type="ROUTINE"):
    """Ask for a field window on one structure, on behalf of its own team leader."""
    return client.create_inspection(
        bridge_id,
        f.inspection_payload(leader_id, start, end, inspection_type=inspection_type),
        make_bridge_inspector_headers(leader_id),
    )


# ─── One leader, three structures: the half-open capacity test ──────────────
def _one_leader_with_two_back_to_back_windows(client, roster, bridge):
    """
    Ivy Inspector holding two touching windows on two different structures, plus a
    third empty structure to place the candidate window on, so that the
    same-structure buffer can never be the rule that decides the outcome.
    """
    willow = fx.create_bridge(
        client,
        f.bridge_payload(
            "STR-000002",
            name="Willow Slough Bridge",
            structure_type="CULVERT",
            deck_area_sqm=600,
            year_built=1988,
            adt=3000,
            detour_length_km=2.0,
            spans_water=True,
        ),
    )
    granite = fx.create_bridge(
        client,
        f.bridge_payload(
            "STR-000003",
            name="Granite Ridge Overpass",
            structure_type="ARCH",
            deck_area_sqm=800,
            year_built=1995,
            adt=7000,
            detour_length_km=5.0,
            spans_water=False,
        ),
    )
    first = get_success_data(
        _open_window(
            client, bridge["id"], roster.inspector_id, DAY_ONE_START, DAY_ONE_END
        ),
        201,
    )
    second = get_success_data(
        _open_window(
            client, willow["id"], roster.inspector_id, ADJACENT_START, ADJACENT_END
        ),
        201,
    )
    return {
        "willow": willow,
        "granite": granite,
        "first": first,
        "second": second,
    }


def test_a_window_starting_exactly_when_another_ends_is_allowed(
    client, roster, bridge
):
    """
    The leader's second window begins at the very instant the first ends. Under a
    half-open interval that is not an overlap, so the report opens normally.

    PRD §3.2: "Because the intervals are half-open, back-to-back windows that
    merely touch are allowed: a leader finishing at 16:00 may begin a new window at
    exactly 16:00".

    Design: Difficulty/resource_temporal_overlap/team_leader_half_open_window_adjacent_allowed_overlap_rejected
    """
    setup = _one_leader_with_two_back_to_back_windows(client, roster, bridge)

    assert setup["second"]["status"] == "DRAFT"
    assert setup["second"]["team_leader_id"] == roster.inspector_id
    assert setup["second"]["bridge_id"] == setup["willow"]["id"]
    assert setup["second"]["field_window_start"][:19] == ADJACENT_START[:19]
    assert setup["first"]["field_window_end"][:19] == ADJACENT_START[:19]
    assert c.TEAM_LEADER_CAPACITY == 1


def test_a_window_starting_one_minute_earlier_is_a_capacity_conflict(
    client, roster, bridge
):
    """
    Sixty seconds earlier and the same candidate window overlaps the leader's first
    window, so the person — not the structure — is the resource that is exhausted.

    PRD §3.2: "A conflict exists when the new window's start falls strictly earlier
    than an existing window's end *and* that existing window's start falls strictly
    earlier than the new window's end."
    PRD §3.2: "but a new window starting at 15:59 against an existing window ending
    at 16:00 overlaps and is rejected with `ERR_TEAM_LEADER_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/team_leader_half_open_window_adjacent_allowed_overlap_rejected
    """
    setup = _one_leader_with_two_back_to_back_windows(client, roster, bridge)

    response = _open_window(
        client,
        setup["granite"]["id"],
        roster.inspector_id,
        ONE_MINUTE_EARLY,
        ADJACENT_END,
    )

    validate_error(response, e.ERR_TEAM_LEADER_WINDOW_CONFLICT, 409)


def test_the_third_structure_has_no_window_of_its_own_to_conflict_with(
    client, roster, bridge
):
    """
    The candidate window is placed on a structure that has never been inspected, so
    the same-structure buffer is not in play and the rejected request leaves the
    leader holding exactly the two windows they started with.

    PRD §3.2: "The **same-structure access buffer** protects traffic control. Two
    inspections on the same structure need a three-day gap for setup and teardown".
    PRD §4: "List inspections; reverse-reachability channel for Inspection.bridge_id,
    team_leader_id and qa_reviewer_id".

    Design: Difficulty/resource_temporal_overlap/team_leader_half_open_window_adjacent_allowed_overlap_rejected
    """
    setup = _one_leader_with_two_back_to_back_windows(client, roster, bridge)

    _open_window(
        client,
        setup["granite"]["id"],
        roster.inspector_id,
        ONE_MINUTE_EARLY,
        ADJACENT_END,
    )

    on_the_third = fx.inspections_for_bridge(client, setup["granite"]["id"])
    assert on_the_third["rows"] == []
    assert on_the_third["meta"]["total_count"] == 0

    held_by_the_leader = fx.inspections_for_leader(client, roster.inspector_id)
    assert held_by_the_leader["meta"]["total_count"] == 2
    assert {row["id"] for row in held_by_the_leader["rows"]} == {
        setup["first"]["id"],
        setup["second"]["id"],
    }


def test_voiding_the_reserved_windows_releases_the_leader_capacity(
    client, roster, bridge
):
    """
    Both existing windows are voided, and the previously rejected 15:59 window is
    then accepted — a voided report reserves nothing.

    PRD §3.2: "Both tests consider only inspections whose status is `DRAFT`,
    `SUBMITTED`, `IN_QA` or `ACCEPTED`; a report that has been taken to `VOIDED`
    releases the window it reserved and drops out of both tests entirely."
    PRD §3.2: "Voiding is available to a `BridgeInspector` while the report is still
    `DRAFT` or `SUBMITTED` — a `DRAFT → VOIDED` or `SUBMITTED → VOIDED` move,
    carrying an optional `void_reason` — and is the intended escape hatch when
    weather or access forces a reschedule."

    Design: Difficulty/resource_temporal_overlap/team_leader_half_open_window_adjacent_allowed_overlap_rejected
    """
    setup = _one_leader_with_two_back_to_back_windows(client, roster, bridge)
    validate_error(
        _open_window(
            client,
            setup["granite"]["id"],
            roster.inspector_id,
            ONE_MINUTE_EARLY,
            ADJACENT_END,
        ),
        e.ERR_TEAM_LEADER_WINDOW_CONFLICT,
        409,
    )

    for reserved in (setup["first"], setup["second"]):
        voided = fx.void_report(client, reserved["id"], roster)
        assert voided["status"] == "VOIDED"

    rescheduled = get_success_data(
        _open_window(
            client,
            setup["granite"]["id"],
            roster.inspector_id,
            ONE_MINUTE_EARLY,
            ADJACENT_END,
        ),
        201,
    )
    assert rescheduled["status"] == "DRAFT"
    assert rescheduled["field_window_start"][:19] == ONE_MINUTE_EARLY[:19]


# ─── Three leaders, one structure: the inflated closed-interval test ────────
def _one_structure_with_a_window_exactly_three_days_later(client, roster, bridge):
    """
    Cedar Creek carrying Ivy's first-of-September window and Frank's window that
    starts exactly 72 hours after it ends, plus Gus who leads nothing at all, so
    only the same-structure buffer can decide any further request.
    """
    frank = fx.create_person(
        client,
        f.personnel_payload("Frank Field", fx.CURRENT_REFRESHER, team_leader_certified=True),
    )
    gus = fx.create_person(
        client,
        f.personnel_payload("Gus Gauge", fx.CURRENT_REFRESHER, team_leader_certified=True),
    )
    first = get_success_data(
        _open_window(
            client, bridge["id"], roster.inspector_id, DAY_ONE_START, DAY_ONE_END
        ),
        201,
    )
    second = _open_window(
        client,
        bridge["id"],
        frank["id"],
        BUFFER_EXACT_START,
        BUFFER_EXACT_END,
        inspection_type="SPECIAL",
    )
    return {"frank": frank, "gus": gus, "first": first, "second": second}


def test_a_window_exactly_seventy_two_hours_after_the_last_one_ends_is_allowed(
    client, roster, bridge
):
    """
    The buffer is measured from the existing window's end and the comparison is
    strict, so a start at exactly the end plus 72 hours is outside the inflated
    interval and opens normally.

    PRD §3.2: "A conflict exists when the new window's start falls earlier than an
    existing window's end plus 72 hours *and* that existing window's start falls
    earlier than the new window's end plus 72 hours."

    Design: Difficulty/resource_temporal_overlap/bridge_access_72h_buffer_gap_rejected
    """
    setup = _one_structure_with_a_window_exactly_three_days_later(client, roster, bridge)

    second = get_success_data(setup["second"], 201)
    assert second["status"] == "DRAFT"
    assert second["inspection_type"] == "SPECIAL"
    assert second["team_leader_id"] == setup["frank"]["id"]
    assert second["field_window_start"][:19] == BUFFER_EXACT_START[:19]
    assert c.BRIDGE_ACCESS_BUFFER_HOURS == 72


def test_a_window_one_hour_inside_the_buffer_is_a_same_structure_conflict(
    client, roster, bridge
):
    """
    One hour earlier than the accepted window and the candidate falls inside the
    72-hour inflation of Ivy's window, which is precisely the case the buffer rule
    works through.

    PRD §3.2: "Concretely: against an existing window running from 08:00 to 16:00 on
    the first of September, a new window starting at 15:59 on the fourth of
    September is rejected, because 15:59 on the fourth is earlier than 16:00 on the
    first plus 72 hours".
    PRD §2.8: "24. **Same-structure access buffer** —
    `ERR_BRIDGE_ACCESS_BUFFER_CONFLICT` (409). Applies to inspection creation."

    Design: Difficulty/resource_temporal_overlap/bridge_access_72h_buffer_gap_rejected
    """
    setup = _one_structure_with_a_window_exactly_three_days_later(client, roster, bridge)
    validate_success(setup["second"], 201)

    response = _open_window(
        client,
        bridge["id"],
        setup["gus"]["id"],
        ONE_HOUR_INSIDE,
        BUFFER_EXACT_END,
        inspection_type="SPECIAL",
    )

    validate_error(response, e.ERR_BRIDGE_ACCESS_BUFFER_CONFLICT, 409)


def test_the_rejected_window_belonged_to_a_leader_holding_nothing_else(
    client, roster, bridge
):
    """
    Gus leads no other report, so the capacity rule cannot have been what refused
    him; the structure keeps exactly the two windows it already had.

    PRD §3.2: "The **team-leader capacity** test protects the person, not the
    structure, and uses a plain half-open interval with a capacity of one."
    PRD §2.3: "`total_count` (the number of records matching the filters before
    pagination)".

    Design: Difficulty/resource_temporal_overlap/bridge_access_72h_buffer_gap_rejected
    """
    setup = _one_structure_with_a_window_exactly_three_days_later(client, roster, bridge)
    second = validate_success(setup["second"], 201)

    _open_window(
        client,
        bridge["id"],
        setup["gus"]["id"],
        ONE_HOUR_INSIDE,
        BUFFER_EXACT_END,
        inspection_type="SPECIAL",
    )

    led_by_gus = fx.inspections_for_leader(client, setup["gus"]["id"])
    assert led_by_gus["rows"] == []
    assert led_by_gus["meta"]["total_count"] == 0

    on_the_structure = fx.inspections_for_bridge(client, bridge["id"])
    assert on_the_structure["meta"]["total_count"] == 2
    assert {row["id"] for row in on_the_structure["rows"]} == {
        setup["first"]["id"],
        second["id"],
    }
