"""Contamination events, room health posture, quarantine cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_cycle_to_fruiting,
    create_active_commitment_with_line,
    create_room,
    create_scheduled_room_cycle,
    create_spawned_batch,
    get_first_spent_lot_for_cycle,
    get_success_data,
    place_room_cycle,
    report_and_confirm_contamination,
    report_contamination_event_payload,
    setup_fruiting_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)

QUALITY = TEST_USERS["quality_inspector_headers"]
ANY = TEST_USERS["any_headers"]


def test_contamination_dismiss_leaves_posture_clear(api):
    """PRD §3.7: "A new event is `REPORTED`, and a merely reported event
    never moves the room's posture."
    PRD §3.7: "A false alarm can be dismissed while still `REPORTED`, moving
    the event to `DISMISSED` with no posture change."

    Design: Corner/state_machines/contamination_dismiss_leaves_posture_clear
    """
    room = create_room()
    event = get_success_data(api.report_contamination_event(
        report_contamination_event_payload(
            room_id=room["id"], pathogen="BACTERIAL_BLOTCH",
            severity=5, affected_zone_pct=5.0,
        ),
        QUALITY,
    ))
    mid = get_success_data(api.get_room(room["id"], ANY))
    assert mid["health_status"] == "CLEAR", "REPORTED never moves posture, even at severity 5"

    get_success_data(api.dismiss_contamination_event(event["id"], QUALITY))
    end = get_success_data(api.get_room(room["id"], ANY))
    event_after = get_success_data(api.get_contamination_event(event["id"], ANY))
    assert event_after["status"] == "DISMISSED"
    assert end["health_status"] == "CLEAR"


def test_contamination_dismiss_leaves_room_clear_at_severity_5(api):
    """PRD §3.7: "A new event is `REPORTED`, and a merely reported event
    never moves the room's posture."
    PRD §3.7: "A false alarm can be dismissed while still `REPORTED`, moving
    the event to `DISMISSED` with no posture change."

    Design: Corner/state_machines/contamination_dismiss_leaves_posture_clear
    """
    room = create_room()
    event = get_success_data(api.report_contamination_event(
        report_contamination_event_payload(
            room_id=room["id"], pathogen="BACTERIAL_BLOTCH",
            severity=5, affected_zone_pct=5.0,
        ),
        QUALITY,
    ))
    get_success_data(api.dismiss_contamination_event(event["id"], QUALITY))
    assert get_success_data(api.get_room(room["id"], ANY))["health_status"] == "CLEAR"


def test_contamination_low_severity_watch_only(api):
    """PRD §3.7: "If the confirmed `severity` is 4 or higher, the room's
    `health_status` goes to `QUARANTINED`, and the quarantine cascades ... If
    the confirmed severity is 3 or lower and the room is `CLEAR`, the room
    moves to `WATCH` instead."

    Design: Corner/state_machines/contamination_low_severity_watch_only
    """
    _variety, _batch, room, rc = setup_fruiting_cycle()
    report_and_confirm_contamination(
        room, rc, severity=2, pathogen="COBWEB", affected_zone_pct=10.0,
    )

    room_after = get_success_data(api.get_room(room["id"], ANY))
    assert room_after["health_status"] == "WATCH", "severity 2 (< 4) -> WATCH, not QUARANTINED"
    rc_after = get_success_data(api.get_room_cycle(rc["id"], ANY))
    assert rc_after["status"] == "FRUITING", "no abort cascade below severity 4"

    lots, _meta = validate_paginated(
        api.list_spent_lots(ANY, params={"room_cycle_id": rc["id"]})
    )
    assert lots == [], "no spent lot is created without an abort"


def test_contamination_low_severity_does_not_create_spent_lot(api):
    """PRD §3.7: "If the confirmed `severity` is 4 or higher, the room's
    `health_status` goes to `QUARANTINED`, and the quarantine cascades: any
    room cycle of that room in `SPAWN_RUN`, `CASING`, or `FRUITING` is
    aborted, producing a spent lot ..." — the cascade (and thus the spent
    lot) fires only at severity 4 or higher.

    Design: Corner/state_machines/contamination_low_severity_watch_only
    """
    _variety, _batch, room, rc = setup_fruiting_cycle()
    report_and_confirm_contamination(
        room, rc, severity=2, pathogen="COBWEB", affected_zone_pct=10.0,
    )
    room_after = get_success_data(api.get_room(room["id"], ANY))
    rc_after = get_success_data(api.get_room_cycle(rc["id"], ANY))
    assert room_after["health_status"] == "WATCH"
    assert rc_after["status"] == "FRUITING"
    lots, _meta = validate_paginated(
        api.list_spent_lots(ANY, params={"room_cycle_id": rc["id"]})
    )
    assert lots == []


def test_room_parallel_occupancy_health_dimensions(api):
    """PRD §3.2: "A room carries two independent status dimensions that
    evolve in parallel: `occupancy_status`, which cycles `IDLE → OCCUPIED →
    TURNAROUND → IDLE` entirely through system-driven hops, and
    `health_status`, which moves among `CLEAR`, `WATCH`, and `QUARANTINED`
    based on contamination events (§3.7)."
    PRD §3.7: "If the confirmed severity is 3 or lower and the room is
    `CLEAR`, the room moves to `WATCH` instead." and "clearing the final open
    event returns it to `CLEAR`."

    A severity-2 confirm moves health CLEAR->WATCH while occupancy stays
    OCCUPIED; the later remediate+clear returns health to CLEAR with
    occupancy untouched throughout.

    Design: Difficulty/non_linear_state_machine/room_parallel_occupancy_health_dimensions
    """
    batch, _variety = create_spawned_batch()
    room = create_room()
    rc = create_scheduled_room_cycle(batch, room)
    rc = place_room_cycle(rc)
    room_mid = get_success_data(api.get_room(room["id"], ANY))
    assert room_mid["occupancy_status"] == "OCCUPIED"
    assert room_mid["health_status"] == "CLEAR"

    event = get_success_data(api.report_contamination_event(
        report_contamination_event_payload(
            room_id=room["id"], room_cycle_id=rc["id"],
            pathogen="COBWEB", severity=2, affected_zone_pct=10.0,
        ),
        QUALITY,
    ))
    get_success_data(api.confirm_contamination_event(event["id"], QUALITY))
    after_confirm = get_success_data(api.get_room(room["id"], ANY))
    assert after_confirm["health_status"] == "WATCH"
    assert after_confirm["occupancy_status"] == "OCCUPIED"

    get_success_data(api.remediate_contamination_event(event["id"], QUALITY))
    get_success_data(api.clear_contamination_event(event["id"], QUALITY))
    after_clear = get_success_data(api.get_room(room["id"], ANY))
    assert after_clear["health_status"] == "CLEAR"
    assert after_clear["occupancy_status"] == "OCCUPIED", (
        "health dimension moved twice; occupancy dimension never moved"
    )
    event_after = get_success_data(api.get_contamination_event(event["id"], ANY))
    assert event_after["status"] == "CLEARED"


def test_room_occupancy_unaffected_by_health_transitions(api):
    """PRD §3.2: "A room carries two independent status dimensions that
    evolve in parallel."
    PRD §3.7: "The room's health posture is recomputed after every confirm,
    dismiss, or clear on any event of the room."

    Design: Difficulty/non_linear_state_machine/room_parallel_occupancy_health_dimensions
    """
    batch, _variety = create_spawned_batch()
    room = create_room()
    rc = create_scheduled_room_cycle(batch, room)
    place_room_cycle(rc)

    event = get_success_data(api.report_contamination_event(
        report_contamination_event_payload(
            room_id=room["id"], room_cycle_id=rc["id"],
            pathogen="COBWEB", severity=2, affected_zone_pct=10.0,
        ),
        QUALITY,
    ))
    get_success_data(api.confirm_contamination_event(event["id"], QUALITY))
    mid = get_success_data(api.get_room(room["id"], ANY))
    assert (mid["health_status"], mid["occupancy_status"]) == ("WATCH", "OCCUPIED")

    get_success_data(api.remediate_contamination_event(event["id"], QUALITY))
    get_success_data(api.clear_contamination_event(event["id"], QUALITY))
    end = get_success_data(api.get_room(room["id"], ANY))
    assert (end["health_status"], end["occupancy_status"]) == ("CLEAR", "OCCUPIED")


def test_contamination_confirm_deep_cascade(api):
    """PRD §3.7: "If the confirmed `severity` is 4 or higher, the room's
    `health_status` goes to `QUARANTINED`, and the quarantine cascades: any
    room cycle of that room in `SPAWN_RUN`, `CASING`, or `FRUITING` is
    aborted, producing a spent lot with `disposal_only` set to true and
    recomputing both the variety's `planned_production_kg` and the
    `supply_at_risk` flags of the variety's `ACTIVE` commitment lines."
    PRD §3.2: "An abort consumes the tonnage (no credit back), still produces
    a spent lot at the same 0.75 factor, sets the lot's `disposal_only` to
    true if and only if the abort was caused by the quarantine cascade, moves
    the room `OCCUPIED → TURNAROUND`."

    Design: Difficulty/transitive_cascade/contamination_confirm_deep_cascade
    """
    variety, batch, room, rc = setup_fruiting_cycle()
    buyer, commitment, line = create_active_commitment_with_line(
        variety, committed_kg=500.0,
    )
    line_before = get_success_data(api.get_commitment_line(line["id"], ANY))
    assert line_before["supply_at_risk"] is False, (
        "planned_production 10000.0 kg >= 500.0 kg open commitment"
    )

    event = get_success_data(api.report_contamination_event(
        report_contamination_event_payload(
            room_id=room["id"], room_cycle_id=rc["id"],
            pathogen="TRICHODERMA", severity=4, affected_zone_pct=35.0,
        ),
        QUALITY,
    ))
    get_success_data(api.confirm_contamination_event(event["id"], QUALITY))

    event_after = get_success_data(api.get_contamination_event(event["id"], ANY))
    assert event_after["status"] == "CONFIRMED"

    room_after = get_success_data(api.get_room(room["id"], ANY))
    assert room_after["health_status"] == "QUARANTINED"

    rc_after = get_success_data(api.get_room_cycle(rc["id"], ANY))
    assert rc_after["status"] == "ABORTED", "quarantine cascade aborts the FRUITING cycle"

    lot = get_first_spent_lot_for_cycle(rc["id"])
    assert lot["tonnage"] == pytest.approx(30.0, abs=0.01), "round(40.0 * 0.75, 2)"
    assert lot["disposal_only"] is True

    line_after = get_success_data(api.get_commitment_line(line["id"], ANY))
    assert line_after["supply_at_risk"] is True, (
        "variety planned_production_kg dropped to 0.0 < 500.0 remaining"
    )

    assert room_after["occupancy_status"] == "TURNAROUND", (
        "abort moved occupancy as well"
    )


def test_contamination_confirm_flips_supply_at_risk(api):
    """PRD §3.7: "the quarantine cascades: ... recomputing both the variety's
    `planned_production_kg` and the `supply_at_risk` flags of the variety's
    `ACTIVE` commitment lines."
    PRD §3.6: "each active line's `supply_at_risk` flag tracks the planning
    book: it is true whenever the variety's `planned_production_kg` — the sum
    of `scheduled_projection_kg` over that variety's cycles in `SCHEDULED`,
    `SPAWN_RUN`, `CASING`, or `FRUITING` — falls below the line's undelivered
    remainder, `committed_kg` minus `delivered_kg`."

    Design: Difficulty/transitive_cascade/contamination_confirm_deep_cascade
    """
    variety, _batch, room, rc = setup_fruiting_cycle()
    _buyer, _commitment, line = create_active_commitment_with_line(
        variety, committed_kg=500.0,
    )
    event = get_success_data(api.report_contamination_event(
        report_contamination_event_payload(
            room_id=room["id"], room_cycle_id=rc["id"],
            pathogen="TRICHODERMA", severity=4, affected_zone_pct=35.0,
        ),
        QUALITY,
    ))
    get_success_data(api.confirm_contamination_event(event["id"], QUALITY))

    line_after = get_success_data(api.get_commitment_line(line["id"], ANY))
    assert line_after["supply_at_risk"] is True
    room_after = get_success_data(api.get_room(room["id"], ANY))
    assert room_after["health_status"] == "QUARANTINED"
    rc_after = get_success_data(api.get_room_cycle(rc["id"], ANY))
    assert rc_after["status"] == "ABORTED"


def test_event_state_guards(api):
    """PRD §3.7: "Confirmed events proceed through remediation: a `CONFIRMED`
    event begins remediation, moving to `REMEDIATING`, and a `REMEDIATING`
    event is cleared, moving to `CLEARED` — each step from the wrong state is
    rejected with `ERR_EVENT_INVALID_STATE`."
    PRD §3.7: "Confirming requires the event to be `REPORTED` (otherwise
    `ERR_EVENT_INVALID_STATE`)."

    Design: Corner/errors/event_state_guards
    """
    room = create_room()
    event = get_success_data(api.report_contamination_event(
        report_contamination_event_payload(
            room_id=room["id"], pathogen="VIRUS", severity=1, affected_zone_pct=5.0,
        ),
        QUALITY,
    ))
    # Remediate while REPORTED: wrong state.
    r1 = api.remediate_contamination_event(event["id"], QUALITY)
    validate_error(r1, ApiErrorId.ERR_EVENT_INVALID_STATE)

    # Confirm succeeds (severity 1 -> room WATCH).
    get_success_data(api.confirm_contamination_event(event["id"], QUALITY))
    mid = get_success_data(api.get_contamination_event(event["id"], ANY))
    assert mid["status"] == "CONFIRMED"
    room_mid = get_success_data(api.get_room(room["id"], ANY))
    assert room_mid["health_status"] == "WATCH"

    # Second confirm: no self-transition.
    r2 = api.confirm_contamination_event(event["id"], QUALITY)
    validate_error(r2, ApiErrorId.ERR_EVENT_INVALID_STATE)


def test_event_remediate_from_reported_rejected(api):
    """PRD §3.7: "a `CONFIRMED` event begins remediation, moving to
    `REMEDIATING`" — remediating a still-`REPORTED` event is from the wrong
    state and is rejected with `ERR_EVENT_INVALID_STATE`.

    Design: Corner/errors/event_state_guards
    """
    room = create_room()
    event = get_success_data(api.report_contamination_event(
        report_contamination_event_payload(
            room_id=room["id"], pathogen="VIRUS", severity=1, affected_zone_pct=5.0,
        ),
        QUALITY,
    ))
    resp = api.remediate_contamination_event(event["id"], QUALITY)
    validate_error(resp, ApiErrorId.ERR_EVENT_INVALID_STATE)
    after = get_success_data(api.get_contamination_event(event["id"], ANY))
    assert after["status"] == "REPORTED"
