"""Interval semantics: which adjacency conflicts and which one is admitted.

Both resources in this module are guarded by an interval predicate, and both
predicates are stated in the PRD with their boundary behaviour spelled out — the
session turnover buffer over closed bounds plus a 30-minute pad, and the
treatment withdrawal window over a half-open interval.
"""
from datetime import datetime, timezone
from typing import Any, Dict

from test_helpers import (
    AQUARIST_HEADERS,
    VET_HEADERS,
    Builder,
    factories,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_SESSION_BUFFER_CONFLICT,
    ERR_TREATMENT_WITHDRAWAL_ACTIVE,
)


# --------------------------------------------------------------------------
# Local helpers
# --------------------------------------------------------------------------
def instant(value: str) -> datetime:
    """Parse an ISO-8601 UTC instant, tolerating the optional fractional part."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def exhibit_with_a_booked_hour(build: Builder) -> Dict[str, Any]:
    """An OPEN exhibit running guest programmes with one SCHEDULED 10:00-11:00 hour."""
    plant = build.create_plant(design_habitat="COLD_MARINE", redundancy_test_interval_days=90)
    exhibit = build.create_exhibit(plant, interaction_program_enabled=True)
    assert exhibit["posture"] == "OPEN", exhibit
    existing = build.book_session(
        exhibit["id"], "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z", max_guests=8
    )
    assert existing["status"] == "SCHEDULED", existing
    return {"plant": plant, "exhibit": exhibit, "existing": existing}


def specimen_under_a_ten_day_withdrawal(build: Builder) -> Dict[str, Any]:
    """A quarantined specimen with one OPEN treatment whose window is 08-01 to 08-11.

    The clock is then parked at 2026-08-20 so that every candidate case can carry
    an `opened_at` no later than the logical clock while its treatment window is
    positioned freely around the existing one.
    """
    world = build.quarantined_specimen()
    world["treatment"] = build.open_vet_case(
        world["specimen"]["id"],
        "TREATMENT",
        opened_at="2026-08-01T00:00:00Z",
        diagnosis_code="BACT-DERM-01",
        treatment_start_at="2026-08-01T00:00:00Z",
        withdrawal_days=10,
    )
    specimen = build.get_specimen(world["specimen"]["id"])
    assert specimen["health_status"] == "UNDER_TREATMENT", specimen
    assert instant(specimen["treatment_withdrawal_until"]) == instant("2026-08-11T00:00:00Z"), specimen
    build.advance_to("2026-08-20T00:00:00Z")
    world["specimen"] = specimen
    return world


def open_treatment_count(api, specimen_id: str) -> int:
    """How many TREATMENT cases the specimen carries, read back through its own list."""
    cases, meta = validate_paginated(
        api.list_specimen_veterinary_cases(specimen_id, VET_HEADERS, {"case_type": "TREATMENT"})
    )
    assert all(case["case_type"] == "TREATMENT" for case in cases), cases
    return meta["total_count"]


# --------------------------------------------------------------------------
# Session turnover buffer
# --------------------------------------------------------------------------
def test_back_to_back_session_with_no_gap_is_refused_by_the_turnover_buffer(api, build):
    """A programme starting the instant the previous one ends leaves no turnover time.

    PRD §3.9: "two adjacent sessions with a gap of zero conflict, because a keeper needs half an hour to turn a programme around"

    Design: Difficulty/resource_temporal_overlap/temporal_session_buffer_adjacency_conflicts_exact_thirty_minute_gap_clears
    """
    world = exhibit_with_a_booked_hour(build)

    response = api.create_interaction_session(
        factories.interaction_session_payload(
            world["exhibit"]["id"], "2026-08-02T11:00:00Z", "2026-08-02T12:00:00Z", max_guests=8
        ),
        AQUARIST_HEADERS,
    )
    validate_error(response, ERR_SESSION_BUFFER_CONFLICT, 409)

    sessions, meta = validate_paginated(
        api.list_exhibit_interaction_sessions(world["exhibit"]["id"], AQUARIST_HEADERS)
    )
    assert meta["total_count"] == 1, meta
    assert sessions[0]["id"] == world["existing"]["id"], sessions


def test_session_starting_twenty_nine_minutes_after_the_previous_one_is_refused(api, build):
    """One minute short of the pad still conflicts: the comparison is strict on 30.

    PRD §3.9: "a gap of exactly 30 minutes does **not** conflict; and a gap of 29 minutes does"

    Design: Difficulty/resource_temporal_overlap/temporal_session_buffer_adjacency_conflicts_exact_thirty_minute_gap_clears
    """
    world = exhibit_with_a_booked_hour(build)

    response = api.create_interaction_session(
        factories.interaction_session_payload(
            world["exhibit"]["id"], "2026-08-02T11:29:00Z", "2026-08-02T12:29:00Z", max_guests=8
        ),
        AQUARIST_HEADERS,
    )
    validate_error(response, ERR_SESSION_BUFFER_CONFLICT, 409)

    _, meta = validate_paginated(
        api.list_exhibit_interaction_sessions(world["exhibit"]["id"], AQUARIST_HEADERS)
    )
    assert meta["total_count"] == 1, meta


def test_session_starting_exactly_thirty_minutes_after_the_previous_one_is_booked(api, build):
    """The candidate starts exactly at the padded end, so it is not strictly before it.

    PRD §3.9: "Two sessions on the same exhibit conflict when the candidate starts strictly before the existing session's `ends_at` advanced by 30 minutes **and** the existing session starts strictly before the candidate's `ends_at` advanced by 30 minutes."

    Design: Difficulty/resource_temporal_overlap/temporal_session_buffer_adjacency_conflicts_exact_thirty_minute_gap_clears
    """
    world = exhibit_with_a_booked_hour(build)

    response = api.create_interaction_session(
        factories.interaction_session_payload(
            world["exhibit"]["id"], "2026-08-02T11:30:00Z", "2026-08-02T12:30:00Z", max_guests=8
        ),
        AQUARIST_HEADERS,
    )
    booked = validate_success(response, 201)
    assert booked["status"] == "SCHEDULED", booked
    assert instant(booked["starts_at"]) == instant("2026-08-02T11:30:00Z"), booked

    stored = build.get_session(booked["id"])
    assert stored["status"] == "SCHEDULED", stored
    _, meta = validate_paginated(
        api.list_exhibit_interaction_sessions(world["exhibit"]["id"], AQUARIST_HEADERS)
    )
    assert meta["total_count"] == 2, meta


def test_session_ending_exactly_thirty_minutes_before_the_booked_hour_is_booked(api, build):
    """The buffer is symmetric: a 30-minute gap on the leading side also clears.

    PRD §3.9: "a gap of exactly 30 minutes does **not** conflict; and a gap of 29 minutes does"

    Design: Difficulty/resource_temporal_overlap/temporal_session_buffer_adjacency_conflicts_exact_thirty_minute_gap_clears
    """
    world = exhibit_with_a_booked_hour(build)

    response = api.create_interaction_session(
        factories.interaction_session_payload(
            world["exhibit"]["id"], "2026-08-02T08:30:00Z", "2026-08-02T09:30:00Z", max_guests=8
        ),
        AQUARIST_HEADERS,
    )
    booked = validate_success(response, 201)
    assert booked["status"] == "SCHEDULED", booked

    assert build.get_session(booked["id"])["status"] == "SCHEDULED"
    _, meta = validate_paginated(
        api.list_exhibit_interaction_sessions(world["exhibit"]["id"], AQUARIST_HEADERS)
    )
    assert meta["total_count"] == 2, meta


def test_session_ending_twenty_nine_minutes_before_the_booked_hour_is_refused(api, build):
    """One minute short on the leading side conflicts through the second conjunct.

    PRD §3.9: "the existing session starts strictly before the candidate's `ends_at` advanced by 30 minutes"

    Design: Difficulty/resource_temporal_overlap/temporal_session_buffer_adjacency_conflicts_exact_thirty_minute_gap_clears
    """
    world = exhibit_with_a_booked_hour(build)

    response = api.create_interaction_session(
        factories.interaction_session_payload(
            world["exhibit"]["id"], "2026-08-02T08:31:00Z", "2026-08-02T09:31:00Z", max_guests=8
        ),
        AQUARIST_HEADERS,
    )
    validate_error(response, ERR_SESSION_BUFFER_CONFLICT, 409)

    _, meta = validate_paginated(
        api.list_exhibit_interaction_sessions(world["exhibit"]["id"], AQUARIST_HEADERS)
    )
    assert meta["total_count"] == 1, meta


# --------------------------------------------------------------------------
# Treatment withdrawal window
# --------------------------------------------------------------------------
def test_second_treatment_overlapping_an_open_withdrawal_window_is_refused(api, build):
    """A window opening a day inside the live one overlaps on both conjuncts.

    PRD §3.7: "A new treatment is refused with `ERR_TREATMENT_WITHDRAWAL_ACTIVE` when its candidate window overlaps the window of any of the same specimen's `OPEN` `TREATMENT` cases — overlap meaning the new window starts strictly before the existing one ends and the existing one starts strictly before the new one ends."

    Design: Difficulty/resource_temporal_overlap/temporal_treatment_withdrawal_half_open_upper_bound_permits_adjacency
    """
    world = specimen_under_a_ten_day_withdrawal(build)

    response = api.create_veterinary_case(
        factories.veterinary_case_payload(
            world["specimen"]["id"],
            "TREATMENT",
            "2026-08-20T00:00:00Z",
            diagnosis_code="PARA-GILL-01",
            treatment_start_at="2026-08-10T00:00:00Z",
            withdrawal_days=5,
        ),
        VET_HEADERS,
    )
    validate_error(response, ERR_TREATMENT_WITHDRAWAL_ACTIVE, 409)

    assert open_treatment_count(api, world["specimen"]["id"]) == 1
    specimen = build.get_specimen(world["specimen"]["id"])
    assert instant(specimen["treatment_withdrawal_until"]) == instant("2026-08-11T00:00:00Z"), specimen


def test_second_treatment_starting_exactly_at_the_open_window_end_is_accepted(api, build):
    """The upper bound is excluded, so a window butting against it does not overlap.

    PRD §3.7: "Because the interval is half-open, a new window starting exactly where an existing one ends does not conflict, and a `withdrawal_days` of 0 produces an empty window that can never conflict with anything."

    Design: Difficulty/resource_temporal_overlap/temporal_treatment_withdrawal_half_open_upper_bound_permits_adjacency
    """
    world = specimen_under_a_ten_day_withdrawal(build)

    response = api.create_veterinary_case(
        factories.veterinary_case_payload(
            world["specimen"]["id"],
            "TREATMENT",
            "2026-08-20T00:00:00Z",
            diagnosis_code="PARA-GILL-01",
            treatment_start_at="2026-08-11T00:00:00Z",
            withdrawal_days=5,
        ),
        VET_HEADERS,
    )
    opened = validate_success(response, 201)
    assert opened["status"] == "OPEN", opened
    assert opened["withdrawal_days"] == 5, opened

    assert open_treatment_count(api, world["specimen"]["id"]) == 2
    specimen = build.get_specimen(world["specimen"]["id"])
    # The latest end across the two open windows is 08-11 plus five days.
    assert instant(specimen["treatment_withdrawal_until"]) == instant("2026-08-16T00:00:00Z"), specimen
    assert specimen["health_status"] == "UNDER_TREATMENT", specimen
    assert specimen["disposition_status"] == "QUARANTINE", specimen


def test_second_treatment_with_a_zero_day_withdrawal_never_conflicts(api, build):
    """An empty window sits inside the live one and is still accepted.

    PRD §3.7: "a `withdrawal_days` of 0 produces an empty window that can never conflict with anything"

    Design: Difficulty/resource_temporal_overlap/temporal_treatment_withdrawal_half_open_upper_bound_permits_adjacency
    """
    world = specimen_under_a_ten_day_withdrawal(build)

    response = api.create_veterinary_case(
        factories.veterinary_case_payload(
            world["specimen"]["id"],
            "TREATMENT",
            "2026-08-20T00:00:00Z",
            diagnosis_code="PARA-GILL-01",
            treatment_start_at="2026-08-05T00:00:00Z",
            withdrawal_days=0,
        ),
        VET_HEADERS,
    )
    opened = validate_success(response, 201)
    assert opened["status"] == "OPEN", opened
    assert opened["withdrawal_days"] == 0, opened

    assert open_treatment_count(api, world["specimen"]["id"]) == 2
    specimen = build.get_specimen(world["specimen"]["id"])
    # The empty window ends at 08-05, so the ten-day case still holds the latest end.
    assert instant(specimen["treatment_withdrawal_until"]) == instant("2026-08-11T00:00:00Z"), specimen
