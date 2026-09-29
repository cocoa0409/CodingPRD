"""Rounding sessions and the deficiency tickets they carry: the single linear
close step, the two guards that can refuse it or refuse a late ticket, the
severity day allowance that is not accelerated, the synchronous visibility of a
ticket's consequences, and filtered pagination over the ticket collection."""

from test_helpers import (
    ApiErrorId,
    assign_owner,
    create_chapter,
    create_standard,
    create_unit,
    open_rounding_session,
    raise_deficiency,
    raise_tickets,
    read_readiness,
    read_unit,
    run_tracer,
    set_clock,
    ticket_action,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Private setup chains — every test rebuilds its own world from scratch.
# ---------------------------------------------------------------------------

def _setup_standard():
    """Chapter EC carrying one standard a deficiency ticket can reference."""
    chapter = create_chapter("EC", "Environment of Care", 100, 1)
    standard = create_standard(
        chapter["id"], "EC.02.06.01", "Safe environment", "DIRECT_IMPACT"
    )
    return {"chapter": chapter, "standard": standard}


def _setup_unit_with_open_session(
    unit_name="ED-3",
    unit_type="ED",
    bed_count=18,
    round_type="ENVIRONMENT_OF_CARE",
    clock="2026-08-10T00:00:00Z",
    window_start="2026-08-10T08:00:00Z",
    window_end="2026-08-10T12:00:00Z",
    with_standard=True,
):
    """One unit carrying a single OPEN rounding session at the given clock."""
    built = _setup_standard() if with_standard else {}
    unit = create_unit(unit_name, unit_type, bed_count)
    if clock is not None:
        set_clock(clock)
    session = open_rounding_session(unit["id"], round_type, window_start, window_end)
    built.update({"unit": unit, "session": session})
    return built


# ---------------------------------------------------------------------------
# state_machines / rounding_session_close_sets_closed_at_and_bumps_version
# ---------------------------------------------------------------------------

def test_closing_a_rounding_session_stamps_closed_at_and_advances_version(
    api, safety_officer_headers
):
    """PRD §3.5: "The `SafetyOfficer` closes it, the server requires that no ticket of that session sits in `ESCALATED` — otherwise the request is rejected with `ERR_ESCALATED_TICKET_BLOCKS_CLOSE` — and on success the session moves `OPEN → CLOSED` with `closed_at` stamped from the logical clock and its `version` advanced."
    PRD §3.5: "A new session begins at `state` `OPEN` with `deficiency_count` at zero and `closed_at` null; its lifecycle is a single linear step to the terminal `CLOSED`."
    PRD §2.5: "Most resources additionally carry `updated_at`, an ISO 8601 UTC instant in the same format that is refreshed on every mutation, and `version`, an integer that starts at 1 when the resource is created and increases by one on every mutation of that resource."

    Design: Corner/state_machines/rounding_session_close_sets_closed_at_and_bumps_version
    """
    built = _setup_unit_with_open_session(with_standard=False)
    session = built["session"]
    assert session["version"] == 1
    assert session["closed_at"] is None

    closed = validate_success(
        api.close_rounding_session(session["id"], {}, safety_officer_headers)
    )
    assert closed["state"] == "CLOSED"
    assert closed["closed_at"] == "2026-08-10T00:00:00.000Z"
    assert closed["version"] == 2
    assert closed["deficiency_count"] == 0


# ---------------------------------------------------------------------------
# state_machines / deficiency_on_closed_session_returns_session_already_closed
# ---------------------------------------------------------------------------

def test_raising_a_deficiency_on_a_closed_session_returns_session_already_closed(
    api, safety_officer_headers, director_headers
):
    """PRD §3.5: "Ticketing a deficiency requires the session to be `OPEN`, or the write is refused with `ERR_SESSION_ALREADY_CLOSED`."
    PRD §2.11: "15. Raising a deficiency requires the rounding session's `state` to be `OPEN` — `ERR_SESSION_ALREADY_CLOSED`, 409, on `POST /accreditation/rounding-sessions/{id}/deficiencies`."
    PRD §2.9: "The **unit penalty ledger** pins `HospitalUnit.open_deficiency_penalty_points` to the sum of `penalty_points` over every deficiency ticket of that unit that has not reached `VERIFIED` — that is, every ticket in `OPEN`, `IN_PROGRESS`, `REMEDIATED` or `ESCALATED`."

    Design: Corner/state_machines/deficiency_on_closed_session_returns_session_already_closed
    """
    built = _setup_unit_with_open_session()
    session_id = built["session"]["id"]
    validate_success(api.close_rounding_session(session_id, {}, safety_officer_headers))

    validate_error(
        api.create_deficiency(
            session_id,
            {
                "standard_id": built["standard"]["id"],
                "description": "Late finding",
                "severity": "MODERATE",
            },
            safety_officer_headers,
        ),
        ApiErrorId.ERR_SESSION_ALREADY_CLOSED,
    )

    session = validate_success(api.get_rounding_session(session_id, director_headers))
    assert session["deficiency_count"] == 0
    assert session["state"] == "CLOSED"

    unit = read_unit(built["unit"]["id"])
    assert unit["open_deficiency_penalty_points"] == 0
    assert unit["posture"] == "OPEN"


# ---------------------------------------------------------------------------
# state_machines / close_session_with_escalated_ticket_returns_escalated_blocks_close
# ---------------------------------------------------------------------------

def test_closing_a_session_holding_an_escalated_ticket_is_blocked(
    api, safety_officer_headers, director_headers
):
    """PRD §2.11: "25. Closing a rounding session requires that none of its tickets is in `ESCALATED` — `ERR_ESCALATED_TICKET_BLOCKS_CLOSE`, 409, on `POST /accreditation/rounding-sessions/{id}/close`."
    PRD §3.5: "And any escalated ticket, regardless of severity, blocks its own session from closing."
    PRD §3.5: "When the ticket's rounding session has `round_type` `LIFE_SAFETY`, escalation raises the ticket's `severity` to `IMMEDIATE_THREAT` and recomputes its `penalty_points` to the fifteen points that severity carries; an `ENVIRONMENT_OF_CARE` escalation leaves severity and points as they were."

    Design: Corner/state_machines/close_session_with_escalated_ticket_returns_escalated_blocks_close
    """
    built = _setup_unit_with_open_session(unit_name="OR-3", unit_type="OR", bed_count=6)
    ticket = raise_deficiency(
        built["session"]["id"],
        built["standard"]["id"],
        "MODERATE",
        "Sterile storage temperature drift",
    )
    escalated = ticket_action(ticket["id"], "ESCALATE", note="Unresolved after two shifts")
    assert escalated["state"] == "ESCALATED"
    assert escalated["severity"] == "MODERATE"
    assert escalated["penalty_points"] == 3

    validate_error(
        api.close_rounding_session(built["session"]["id"], {}, safety_officer_headers),
        ApiErrorId.ERR_ESCALATED_TICKET_BLOCKS_CLOSE,
    )

    session = validate_success(
        api.get_rounding_session(built["session"]["id"], director_headers)
    )
    assert session["state"] == "OPEN"
    assert session["closed_at"] is None

    unit = read_unit(built["unit"]["id"])
    assert unit["posture"] == "OPEN"
    assert unit["open_deficiency_penalty_points"] == 3


# ---------------------------------------------------------------------------
# calculations / deficiency_severity_days_low_is_forty_five_unaccelerated
# ---------------------------------------------------------------------------

def test_low_severity_ticket_on_an_unassessed_unit_gets_forty_five_unhalved_days(
    api, safety_officer_headers
):
    """PRD §3.5: "**Second**, a base allowance is taken from the severity: a `LOW` deficiency gets forty-five days, a `MODERATE` one thirty days, a `HIGH` one fourteen days, and an `IMMEDIATE_THREAT` one a single day."
    PRD §3.5: "**Third**, if the snapshot band was `AT_RISK` or `NOT_READY`, the allowance is halved — specifically, it becomes the larger of one day and the base allowance divided by two with any fraction discarded — and the ticket's `accelerated` flag is set to true; if the snapshot band was `READY`, `CONDITIONAL` or `NOT_ASSESSED`, the allowance stands unchanged and `accelerated` is false."
    PRD §3.5: "**Fourth**, `due_at` is set to the current logical clock plus that many days, counted as exact twenty-four-hour multiples."
    PRD §3.5: "**Fifth**, `penalty_points` is set from the severity — one point for `LOW`, three for `MODERATE`, seven for `HIGH`, fifteen for `IMMEDIATE_THREAT`."

    Design: Corner/calculations/deficiency_severity_days_low_is_forty_five_unaccelerated
    """
    built = _setup_unit_with_open_session(
        unit_name="AMB-1",
        unit_type="AMBULATORY",
        bed_count=0,
        clock=None,
        window_start="2026-08-01T08:00:00Z",
        window_end="2026-08-01T12:00:00Z",
    )

    ticket = validate_success(
        api.create_deficiency(
            built["session"]["id"],
            {
                "standard_id": built["standard"]["id"],
                "description": "Unlabelled spray bottle",
                "severity": "LOW",
            },
            safety_officer_headers,
        ),
        201,
    )
    assert ticket["due_at"] == "2026-09-15T00:00:00.000Z"
    assert ticket["accelerated"] is False
    assert ticket["penalty_points"] == 1
    assert ticket["state"] == "OPEN"

    unit = read_unit(built["unit"]["id"])
    assert unit["open_deficiency_penalty_points"] == 1
    assert unit["readiness_band"] == "NOT_ASSESSED"
    assert unit["posture"] == "OPEN"


# ---------------------------------------------------------------------------
# consistency_model / deficiency_creation_is_immediately_visible_everywhere
# ---------------------------------------------------------------------------

def test_deficiency_creation_is_visible_in_the_unit_ledger_and_readiness_at_once(
    api, safety_officer_headers
):
    """PRD §2.9: "Derived state is recomputed synchronously, in the same request, and cascades follow the graph without regard to which aggregate the client addressed."
    PRD §3.5: "**Sixth**, the ticket is inserted and its points are added to the unit's `open_deficiency_penalty_points`."
    PRD §3.5: "**Seventh** and last, the unit's `readiness_score`, `readiness_band` and `posture` are recomputed."
    PRD §3.3: "The score is the base minus the capped penalty, floored at zero so it can never go negative, rounded half up to two decimal places."

    Design: Corner/consistency_model/deficiency_creation_is_immediately_visible_everywhere
    """
    chapter = create_chapter("EC", "Environment of Care", 100, 1)
    first = create_standard(
        chapter["id"], "EC.02.06.01", "Safe environment", "DIRECT_IMPACT"
    )
    second = create_standard(
        chapter["id"], "EC.02.05.01", "Utility systems", "INDIRECT_IMPACT"
    )
    assign_owner(first["id"], "owner-1", "PRIMARY")
    unit = create_unit("ICU-19", "ICU", 12)
    run_tracer(
        unit["id"],
        chapter["id"],
        [
            {"standard_id": first["id"], "result": "COMPLIANT", "weight": 39},
            {"standard_id": second["id"], "result": "NON_COMPLIANT", "weight": 11},
        ],
        window_start="2026-08-10T08:00:00Z",
        window_end="2026-08-10T12:00:00Z",
        start_clock="2026-08-10T09:00:00Z",
    )

    before = read_readiness(unit["id"])
    assert float(before["readiness_score"]) == 78.00
    assert before["readiness_band"] == "CONDITIONAL"

    session = open_rounding_session(
        unit["id"], "LIFE_SAFETY", "2026-08-10T13:00:00Z", "2026-08-10T15:00:00Z"
    )

    ticket = validate_success(
        api.create_deficiency(
            session["id"],
            {
                "standard_id": first["id"],
                "description": "Sprinkler head obstruction",
                "severity": "HIGH",
            },
            safety_officer_headers,
        ),
        201,
    )
    assert ticket["penalty_points"] == 7
    assert ticket["accelerated"] is False
    assert ticket["due_at"] == "2026-08-24T09:00:00.000Z"

    unit_after = validate_success(api.get_unit(unit["id"], safety_officer_headers))
    assert unit_after["open_deficiency_penalty_points"] == 7
    assert unit_after["posture"] == "OPEN"

    readiness = validate_success(
        api.get_unit_readiness(unit["id"], safety_officer_headers)
    )
    assert float(readiness["readiness_score"]) == 71.00
    assert readiness["penalty_points_applied"] == 7
    assert readiness["readiness_band"] == "AT_RISK"


# ---------------------------------------------------------------------------
# cross_cutting_complexity_layers / pagination_with_filtering_state_and_offset
# ---------------------------------------------------------------------------

def test_deficiency_ticket_page_filtered_by_state_reports_the_filtered_total(
    api, safety_officer_headers
):
    """PRD §2.3: "Collection reads also accept filters that narrow the result set by a stored attribute before pagination."
    PRD §2.3: "The standards of a chapter may be filtered by `compliance_state`; the owner assignments of a standard by `status`; a standard's evidence repository by `validation_state`; the mock tracer collection by `unit_id`, `chapter_id` and `state`; both observation collections — the one scoped to a tracer and the one scoped to a standard — by `result`; the rounding-session collection by `unit_id`, `round_type` and `state`; the deficiency-ticket collection by `rounding_session_id`, `standard_id`, `state` and `severity`; the survey-finding collection by `survey_window_id`, `standard_id`, `unit_id` and `state`; and a chapter's periodic performance review collection by `state`."
    PRD §2.3: "The `meta` object of every collection response carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` is the size of the filtered result set before pagination is applied and `has_more` indicates whether rows remain beyond the current page."
    PRD §2.3: "Unless a specific endpoint says otherwise, every collection is sorted by `created_at` in ascending order."

    Design: Corner/cross_cutting_complexity_layers/pagination_with_filtering_state_and_offset
    """
    built = _setup_unit_with_open_session(
        unit_name="MED-18",
        unit_type="MED_SURG",
        bed_count=24,
        clock=None,
        window_start="2026-08-01T08:00:00Z",
        window_end="2026-08-01T12:00:00Z",
    )
    tickets = raise_tickets(
        built["session"]["id"], built["standard"]["id"], ["LOW", "LOW", "LOW"]
    )
    started = ticket_action(tickets[0]["id"], "START_WORK", note="Cleaning scheduled")
    assert started["state"] == "IN_PROGRESS"

    rows, meta = validate_paginated(
        api.list_deficiency_tickets(
            safety_officer_headers, {"state": "OPEN", "limit": 1, "offset": 1}
        )
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert meta["limit"] == 1
    assert meta["offset"] == 1
    assert len(rows) == 1
    assert rows[0]["id"] == tickets[2]["id"]
    assert rows[0]["state"] == "OPEN"

    session_rows, session_meta = validate_paginated(
        api.list_deficiency_tickets(
            safety_officer_headers,
            {
                "rounding_session_id": built["session"]["id"],
                "severity": "LOW",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert session_meta["total_count"] == 3
    assert session_rows[0]["id"] == tickets[0]["id"]

    unit = read_unit(built["unit"]["id"])
    assert unit["open_deficiency_penalty_points"] == 3
