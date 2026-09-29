"""Rejection-ladder precedence (PRD §2.8).

Each pair below is provoked twice from the same endpoint: once with both faults
present at the same time, to prove the higher-ranked rule short-circuits the
request, and once with only the lower-ranked fault present, to prove that rule
was masked rather than absent.
"""
from typing import Any, Dict

from test_helpers import (
    AQUARIST_HEADERS,
    Builder,
    validate_error,
    validate_paginated,
)
from test_helpers.api_errors import (
    ERR_BIOLOAD_CAPACITY_EXCEEDED,
    ERR_EXHIBIT_CLOSED,
    ERR_GUEST_CAPACITY_EXCEEDED,
    ERR_INVALID_STATE,
    ERR_NO_APPROVED_PLAN_ENTRY,
    ERR_SESSION_IN_PAST,
)


# ---------------------------------------------------------------------------
# World builders
# ---------------------------------------------------------------------------
def _over_capacity_world(build: Builder) -> Dict[str, Any]:
    """An exhibit of capacity 10 whose APPROVED line names a 12-unit species.

    Every placement onto it therefore breaches PRD §2.8 rank 45, whatever the
    specimen's disposition happens to be.
    """
    return build.quarantined_specimen(
        exhibit_overrides={"bioload_capacity_units": 10.0},
        species_overrides={"bioload_units_per_specimen": 12.0},
        entry_overrides={"planned_count": 1, "sustainability_requirement": "GREEN_ONLY"},
    )


def _unplanned_exhibit_world(build: Builder) -> Dict[str, Any]:
    """A cleared specimen plus a second exhibit that has no plan line for it.

    The second exhibit is served by its own plant, so that plant's alarm band
    can be driven independently of the exhibit the specimen was planned for.
    """
    world = build.cleared_specimen()
    plant_b = build.create_plant()
    exhibit_b = build.create_exhibit(plant_b)
    world["plant_b"] = plant_b
    world["exhibit_b"] = exhibit_b
    return world


def _interaction_exhibit(build: Builder) -> Dict[str, Any]:
    """An OPEN exhibit with its guest-interaction programme enabled."""
    plant = build.create_plant()
    return build.create_exhibit(plant, interaction_program_enabled=True)


def _placement_attempt(api, build: Builder, specimen_id: str, exhibit_id: str):
    """Place a specimen using a freshly read exhibit version (rank 9 satisfied)."""
    payload = {
        "exhibit_id": exhibit_id,
        "expected_exhibit_version": build.exhibit_version(exhibit_id),
    }
    return api.place_specimen(specimen_id, payload, AQUARIST_HEADERS)


def _session_payload(exhibit_id: str, starts_at: str, ends_at: str, max_guests: int, guest_count: int) -> Dict[str, Any]:
    return {
        "exhibit_id": exhibit_id,
        "program_type": "FEEDING_ENCOUNTER",
        "starts_at": starts_at,
        "ends_at": ends_at,
        "max_guests": max_guests,
        "guest_count": guest_count,
        "safety_briefing_confirmed": True,
    }


# ---------------------------------------------------------------------------
# PAIR A — rank 10 ERR_INVALID_STATE over rank 45 ERR_BIOLOAD_CAPACITY_EXCEEDED
# ---------------------------------------------------------------------------
def test_placing_a_quarantined_specimen_over_capacity_reports_the_invalid_state(api, build):
    """A quarantined specimen over an exhibit's capacity is refused for its state.

    PRD §2.8: "A placement of a specimen whose `disposition_status` is not `CLEARED` returns `ERR_INVALID_STATE` (rank 10) even when the exhibit is simultaneously over its bioload capacity (rank 45)."

    Design: Difficulty/priority_pair_validation_conflict/priority_pair_a_invalid_state_masks_bioload_capacity
    """
    world = _over_capacity_world(build)
    specimen = world["specimen"]
    exhibit = world["exhibit"]

    # Both faults hold at once: the animal is still in QUARANTINE (§3.6) and
    # 0.00 + 12.00 exceeds the capacity of 10.00 (§2.8 rank 45).
    assert specimen["disposition_status"] == "QUARANTINE", specimen["disposition_status"]
    assert specimen["bioload_units"] == 12.00, specimen["bioload_units"]
    before = build.get_exhibit(exhibit["id"])
    assert before["bioload_capacity_units"] == 10.00, before["bioload_capacity_units"]
    assert before["occupied_bioload_units"] == 0.00, before["occupied_bioload_units"]
    # An OPEN posture keeps ranks 15 and 16 out of the comparison entirely.
    assert before["posture"] == "OPEN", before["posture"]

    response = _placement_attempt(api, build, specimen["id"], exhibit["id"])
    validate_error(response, ERR_INVALID_STATE, 409)

    # Nothing is persisted by a rejected placement (§2.6, §3.6).
    after = build.get_exhibit(exhibit["id"])
    assert after["occupied_bioload_units"] == 0.00, after["occupied_bioload_units"]
    assert after["version"] == before["version"], after["version"]
    reread = build.get_specimen(specimen["id"])
    assert reread["disposition_status"] == "QUARANTINE", reread["disposition_status"]
    assert reread["exhibit_id"] is None, reread["exhibit_id"]


def test_placing_a_cleared_specimen_over_capacity_reports_the_bioload_breach(api, build):
    """Once the state fault is repaired the same payload surfaces the capacity breach.

    PRD §2.8: "The exhibit's `occupied_bioload_units` plus the candidate specimen's `bioload_units` does not exceed `bioload_capacity_units` — `ERR_BIOLOAD_CAPACITY_EXCEEDED` (409). Applies to exhibit placement."

    Design: Difficulty/priority_pair_validation_conflict/priority_pair_a_invalid_state_masks_bioload_capacity
    """
    world = build.cleared_specimen(world=_over_capacity_world(build))
    specimen = world["specimen"]
    exhibit = world["exhibit"]

    # Only the capacity fault remains: quarantine clearance took the disposition
    # dimension to CLEARED (§3.6) while the ledger is untouched.
    assert specimen["disposition_status"] == "CLEARED", specimen["disposition_status"]
    assert specimen["health_status"] == "HEALTHY", specimen["health_status"]
    before = build.get_exhibit(exhibit["id"])
    assert before["posture"] == "OPEN", before["posture"]
    assert before["occupied_bioload_units"] == 0.00, before["occupied_bioload_units"]

    response = _placement_attempt(api, build, specimen["id"], exhibit["id"])
    validate_error(response, ERR_BIOLOAD_CAPACITY_EXCEEDED, 409)

    after = build.get_exhibit(exhibit["id"])
    assert after["occupied_bioload_units"] == 0.00, after["occupied_bioload_units"]
    assert after["bioload_utilization_pct"] == 0.00, after["bioload_utilization_pct"]
    reread = build.get_specimen(specimen["id"])
    assert reread["disposition_status"] == "CLEARED", reread["disposition_status"]
    assert reread["exhibit_id"] is None, reread["exhibit_id"]


# ---------------------------------------------------------------------------
# PAIR B — rank 15 ERR_EXHIBIT_CLOSED over rank 24 ERR_NO_APPROVED_PLAN_ENTRY
# ---------------------------------------------------------------------------
def test_placing_into_a_closed_unplanned_exhibit_reports_the_closed_exhibit(api, build):
    """A CLOSED exhibit outranks the absence of an approved plan line.

    PRD §2.8: "A placement into a `CLOSED` exhibit returns `ERR_EXHIBIT_CLOSED` (rank 15) even when there is also no approved plan entry for that exhibit-and-species pair (rank 24)."

    Design: Difficulty/priority_pair_validation_conflict/priority_pair_b_exhibit_closed_masks_missing_plan_entry
    """
    world = _unplanned_exhibit_world(build)
    specimen = world["specimen"]
    exhibit_b = world["exhibit_b"]

    # A CRITICAL reading on exhibit B's own plant closes it (§3.1, §3.2).
    build.append_graded_reading(world["plant_b"], "CRITICAL")
    plant_b = build.get_plant(world["plant_b"]["id"])
    assert plant_b["alarm_state"] == "CRITICAL", plant_b["alarm_state"]
    closed = build.get_exhibit(exhibit_b["id"])
    assert closed["posture"] == "CLOSED", closed["posture"]
    assert closed["last_posture_reason"] == "LSS_CRITICAL", closed["last_posture_reason"]

    # The specimen itself is faultless for ranks 10 and 14.
    assert specimen["disposition_status"] == "CLEARED", specimen["disposition_status"]
    assert specimen["health_status"] == "HEALTHY", specimen["health_status"]

    response = _placement_attempt(api, build, specimen["id"], exhibit_b["id"])
    validate_error(response, ERR_EXHIBIT_CLOSED, 409)

    after = build.get_exhibit(exhibit_b["id"])
    assert after["occupied_bioload_units"] == 0.00, after["occupied_bioload_units"]
    reread = build.get_specimen(specimen["id"])
    assert reread["exhibit_id"] is None, reread["exhibit_id"]
    assert reread["disposition_status"] == "CLEARED", reread["disposition_status"]


def test_placing_into_a_recovered_unplanned_exhibit_reports_the_missing_plan_entry(api, build):
    """With the posture recovered the same payload surfaces the missing plan line.

    PRD §2.8: "An `APPROVED` collection plan entry exists for the target exhibit and the specimen's species — `ERR_NO_APPROVED_PLAN_ENTRY` (409). Applies to exhibit placement."

    Design: Difficulty/priority_pair_validation_conflict/priority_pair_b_exhibit_closed_masks_missing_plan_entry
    """
    world = _unplanned_exhibit_world(build)
    specimen = world["specimen"]
    exhibit_b = world["exhibit_b"]
    plant_b = world["plant_b"]

    build.append_graded_reading(plant_b, "CRITICAL")

    # §3.1: from CRITICAL a NORMAL reading de-escalates only once the incremented
    # consecutive_normal_readings has reached 2, and clears to NORMAL at 3.
    build.advance(hours=1)
    build.append_graded_reading(plant_b, "NORMAL")
    assert build.get_plant(plant_b["id"])["alarm_state"] == "CRITICAL"
    assert build.get_exhibit(exhibit_b["id"])["posture"] == "CLOSED"

    build.advance(hours=1)
    build.append_graded_reading(plant_b, "NORMAL")
    assert build.get_plant(plant_b["id"])["alarm_state"] == "WARNING"
    restricted = build.get_exhibit(exhibit_b["id"])
    assert restricted["posture"] == "RESTRICTED", restricted["posture"]
    assert restricted["last_posture_reason"] == "LSS_WARNING", restricted["last_posture_reason"]

    build.advance(hours=1)
    build.append_graded_reading(plant_b, "NORMAL")
    assert build.get_plant(plant_b["id"])["alarm_state"] == "NORMAL"
    reopened = build.get_exhibit(exhibit_b["id"])
    assert reopened["posture"] == "OPEN", reopened["posture"]
    assert reopened["last_posture_reason"] is None, reopened["last_posture_reason"]

    # Only the plan-line fault is left: exhibit B never had a line for this species.
    response = _placement_attempt(api, build, specimen["id"], exhibit_b["id"])
    validate_error(response, ERR_NO_APPROVED_PLAN_ENTRY, 409)

    after = build.get_exhibit(exhibit_b["id"])
    assert after["occupied_bioload_units"] == 0.00, after["occupied_bioload_units"]
    reread = build.get_specimen(specimen["id"])
    assert reread["exhibit_id"] is None, reread["exhibit_id"]
    assert reread["disposition_status"] == "CLEARED", reread["disposition_status"]


# ---------------------------------------------------------------------------
# PAIR C — rank 32 ERR_SESSION_IN_PAST over rank 38 ERR_GUEST_CAPACITY_EXCEEDED
# ---------------------------------------------------------------------------
def test_booking_an_overbooked_session_in_the_past_reports_the_past_start(api, build):
    """A back-dated booking is refused for its start instant, not its guest count.

    PRD §2.8: "And a session created with a start instant already in the past returns `ERR_SESSION_IN_PAST` (rank 32) even when its `guest_count` also exceeds `max_guests` (rank 38)."

    Design: Difficulty/priority_pair_validation_conflict/priority_pair_c_session_in_past_masks_guest_capacity
    """
    exhibit = _interaction_exhibit(build)
    assert exhibit["posture"] == "OPEN", exhibit["posture"]
    assert exhibit["interaction_program_enabled"] is True, exhibit["interaction_program_enabled"]

    # The clock stands at 2026-08-01T00:00:00Z, so this window is wholly past,
    # and 9 guests against 6 places breaks rank 38 at the same time.
    response = api.create_interaction_session(
        _session_payload(
            exhibit["id"], "2026-07-31T10:00:00Z", "2026-07-31T11:00:00Z", max_guests=6, guest_count=9
        ),
        AQUARIST_HEADERS,
    )
    validate_error(response, ERR_SESSION_IN_PAST, 422)

    sessions, meta = validate_paginated(api.list_exhibit_interaction_sessions(exhibit["id"], AQUARIST_HEADERS))
    assert meta["total_count"] == 0, meta
    assert sessions == [], sessions
    after = build.get_exhibit(exhibit["id"])
    assert after["suspended_session_count"] == 0, after["suspended_session_count"]
    assert after["version"] == exhibit["version"], after["version"]


def test_booking_a_session_starting_exactly_now_reports_the_past_start(api, build):
    """The rank 32 comparison is strict, so a start equal to the clock is refused.

    PRD §2.8: "At session creation, `starts_at` is strictly later than the logical clock — `ERR_SESSION_IN_PAST` (422). Applies to session creation. Strict: a start instant exactly equal to the clock is rejected."

    Design: Difficulty/priority_pair_validation_conflict/priority_pair_c_session_in_past_masks_guest_capacity
    """
    exhibit = _interaction_exhibit(build)

    # guest_count sits inside max_guests here, so rank 38 cannot contribute.
    response = api.create_interaction_session(
        _session_payload(
            exhibit["id"], build.now, "2026-08-01T01:00:00Z", max_guests=6, guest_count=4
        ),
        AQUARIST_HEADERS,
    )
    validate_error(response, ERR_SESSION_IN_PAST, 422)

    sessions, meta = validate_paginated(api.list_exhibit_interaction_sessions(exhibit["id"], AQUARIST_HEADERS))
    assert meta["total_count"] == 0, meta
    assert sessions == [], sessions


def test_booking_an_overbooked_future_session_reports_the_guest_capacity(api, build):
    """Moving only the window into the future surfaces the masked capacity rule.

    PRD §2.8: "`guest_count` is no greater than `max_guests` — `ERR_GUEST_CAPACITY_EXCEEDED` (422). Applies to session creation and session transitions."

    Design: Difficulty/priority_pair_validation_conflict/priority_pair_c_session_in_past_masks_guest_capacity
    """
    exhibit = _interaction_exhibit(build)

    # Identical 9-over-6 overload, window now strictly after the clock.
    response = api.create_interaction_session(
        _session_payload(
            exhibit["id"], "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z", max_guests=6, guest_count=9
        ),
        AQUARIST_HEADERS,
    )
    validate_error(response, ERR_GUEST_CAPACITY_EXCEEDED, 422)

    # No row was written, so the rank 34 turnover buffer can never have applied.
    sessions, meta = validate_paginated(api.list_exhibit_interaction_sessions(exhibit["id"], AQUARIST_HEADERS))
    assert meta["total_count"] == 0, meta
    assert sessions == [], sessions
    after = build.get_exhibit(exhibit["id"])
    assert after["suspended_session_count"] == 0, after["suspended_session_count"]
    assert after["version"] == exhibit["version"], after["version"]
