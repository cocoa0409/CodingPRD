"""The mock tracer program from scheduling to terminal state: the declared
initial state, the temporal and posture gates on START, the terminal lockdown of
COMPLETED, the observation and completion preconditions, the hospital-wide
immediate-threat freeze, and the stale-unit-view guard on scheduling."""

from test_helpers import (
    ApiErrorId,
    assign_owner,
    create_chapter,
    create_standard,
    create_unit,
    open_rounding_session,
    raise_deficiency,
    read_chapter,
    read_standard,
    read_unit,
    record_observation,
    schedule_tracer,
    set_clock,
    ticket_action,
    tracer_action,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Private setup chains — each test rebuilds its own world from scratch.
# ---------------------------------------------------------------------------

def _setup_mapped_chapter_and_unit(
    chapter_code="EC",
    chapter_name="Environment of Care",
    weight_pct=100,
    standard_code="EC.02.06.01",
    standard_title="Safe environment",
    risk_tier="DIRECT_IMPACT",
    unit_name="ICU-2",
    unit_type="ICU",
    bed_count=12,
):
    """One chapter carrying one owned standard (so `mapped_standard_count` is 1)
    plus one freshly registered unit in posture OPEN at version 1."""
    chapter = create_chapter(chapter_code, chapter_name, weight_pct, 1)
    standard = create_standard(chapter["id"], standard_code, standard_title, risk_tier)
    assign_owner(standard["id"], "owner-1", "PRIMARY")
    unit = create_unit(unit_name, unit_type, bed_count)
    return {"chapter": chapter, "standard": standard, "unit": unit}


def _setup_scheduled_tracer(unit_name="ICU-2"):
    """The world above with one SCHEDULED tracer occupying 2026-08-20T08:00:00Z
    to 2026-08-20T10:00:00Z, the logical clock left at its starting instant."""
    built = _setup_mapped_chapter_and_unit(unit_name=unit_name)
    built["tracer"] = schedule_tracer(
        built["unit"]["id"],
        built["chapter"]["id"],
        "2026-08-20T08:00:00Z",
        "2026-08-20T10:00:00Z",
        tracer_type="SYSTEM",
        expected_unit_version=built["unit"]["version"],
    )
    return built


def _setup_completed_tracer_scoring_one_hundred():
    """Unit MED-3 with one COMPLETED tracer on chapter EC whose single
    COMPLIANT observation freezes `tracer_score` at 100.00 at clock
    2026-08-05T09:00:00Z."""
    built = _setup_mapped_chapter_and_unit(unit_name="MED-3", unit_type="MED_SURG", bed_count=24)
    tracer = schedule_tracer(
        built["unit"]["id"],
        built["chapter"]["id"],
        "2026-08-05T08:00:00Z",
        "2026-08-05T10:00:00Z",
        tracer_type="PATIENT",
        expected_unit_version=built["unit"]["version"],
    )
    set_clock("2026-08-05T09:00:00Z")
    tracer_action(tracer["id"], "START")
    record_observation(tracer["id"], built["standard"]["id"], "COMPLIANT", 4)
    built["tracer"] = tracer_action(tracer["id"], "COMPLETE")
    return built


def _setup_unit_with_completed_in_progress_and_scheduled_tracers():
    """Unit ICU-6 on chapter EC (weight 100) carrying T1 COMPLETED at 78.00,
    T2 IN_PROGRESS over 2026-08-10T08:00Z-12:00Z and T3 SCHEDULED over
    2026-08-10T13:00Z-14:00Z, plus one OPEN ENVIRONMENT_OF_CARE session already
    holding two HIGH tickets (fourteen points, still below the restriction
    threshold). The logical clock stands at 2026-08-10T08:00:00Z."""
    chapter = create_chapter("EC", "Environment of Care", 100, 1)
    first = create_standard(chapter["id"], "EC.02.06.01", "Safe environment", "DIRECT_IMPACT")
    second = create_standard(chapter["id"], "EC.02.05.01", "Utility systems", "INDIRECT_IMPACT")
    assign_owner(first["id"], "owner-1", "PRIMARY")
    unit = create_unit("ICU-6", "ICU", 14)

    completed = schedule_tracer(
        unit["id"],
        chapter["id"],
        "2026-08-05T08:00:00Z",
        "2026-08-05T10:00:00Z",
        tracer_type="SYSTEM",
        expected_unit_version=unit["version"],
    )
    set_clock("2026-08-05T09:00:00Z")
    tracer_action(completed["id"], "START")
    record_observation(completed["id"], first["id"], "COMPLIANT", 39)
    record_observation(completed["id"], second["id"], "NON_COMPLIANT", 11)
    completed = tracer_action(completed["id"], "COMPLETE")

    # Every write above bumped the unit, so each schedule re-reads its version.
    in_progress = schedule_tracer(
        unit["id"],
        chapter["id"],
        "2026-08-10T08:00:00Z",
        "2026-08-10T12:00:00Z",
        tracer_type="PATIENT",
    )
    scheduled = schedule_tracer(
        unit["id"],
        chapter["id"],
        "2026-08-10T13:00:00Z",
        "2026-08-10T14:00:00Z",
        tracer_type="INDIVIDUAL",
    )
    set_clock("2026-08-10T08:00:00Z")
    in_progress = tracer_action(in_progress["id"], "START")

    session = open_rounding_session(
        unit["id"], "ENVIRONMENT_OF_CARE", "2026-08-10T08:00:00Z", "2026-08-10T12:00:00Z"
    )
    raise_deficiency(session["id"], first["id"], "HIGH", "Blocked panel")
    raise_deficiency(session["id"], first["id"], "HIGH", "Eyewash overdue")
    return {
        "chapter": chapter,
        "first_standard": first,
        "second_standard": second,
        "unit": unit,
        "completed_tracer": completed,
        "in_progress_tracer": in_progress,
        "scheduled_tracer": scheduled,
        "session": session,
    }


def _setup_escalated_immediate_threat_on_another_unit():
    """Chapter LS with one owned standard, unit ICU-11 holding a LIFE_SAFETY
    ticket escalated to IMMEDIATE_THREAT, and a clean unit MED-11 still OPEN.
    The logical clock stands at 2026-08-10T00:00:00Z."""
    chapter = create_chapter("LS", "Life Safety", 100, 1)
    standard = create_standard(chapter["id"], "LS.02.01.01", "Sprinkler coverage", "DIRECT_IMPACT")
    assign_owner(standard["id"], "owner-1", "PRIMARY")
    threatened = create_unit("ICU-11", "ICU", 10)
    clean = create_unit("MED-11", "MED_SURG", 26)
    set_clock("2026-08-10T00:00:00Z")
    session = open_rounding_session(
        threatened["id"], "LIFE_SAFETY", "2026-08-10T08:00:00Z", "2026-08-10T12:00:00Z"
    )
    ticket = raise_deficiency(session["id"], standard["id"], "HIGH", "Egress door chained shut")
    ticket = ticket_action(ticket["id"], "ESCALATE", note="Immediate jeopardy to egress")
    return {
        "chapter": chapter,
        "standard": standard,
        "threatened_unit": threatened,
        "clean_unit": clean,
        "session": session,
        "ticket": ticket,
    }


# ---------------------------------------------------------------------------
# state_machines
# ---------------------------------------------------------------------------

def test_newly_scheduled_tracer_starts_in_scheduled_state(api, tracer_surveyor_headers):
    """PRD §3.4: "A successfully scheduled tracer begins at `state` `SCHEDULED` with `started_at`, `completed_at` and `abort_reason` all null, `scored_weight`, `earned_weight` and `tracer_score` at zero and `contributes_to_readiness` false."
    PRD §3.4: "It also increments the unit's `scheduled_tracer_count` by one and advances the unit's `version` — which is precisely why a client scheduling two tracers back to back must re-read the unit between them."
    PRD §2.5: "Most resources additionally carry `updated_at`, an ISO 8601 UTC instant in the same format that is refreshed on every mutation, and `version`, an integer that starts at 1 when the resource is created and increases by one on every mutation of that resource."

    Design: Corner/state_machines/tracer_initial_state_is_scheduled
    """
    built = _setup_mapped_chapter_and_unit()
    assert built["unit"]["version"] == 1

    tracer = validate_success(
        api.create_mock_tracer(
            {
                "unit_id": built["unit"]["id"],
                "chapter_id": built["chapter"]["id"],
                "tracer_type": "SYSTEM",
                "window_start": "2026-08-20T08:00:00Z",
                "window_end": "2026-08-20T10:00:00Z",
                "expected_unit_version": built["unit"]["version"],
            },
            tracer_surveyor_headers,
        ),
        201,
    )

    assert tracer["state"] == "SCHEDULED"
    assert tracer["started_at"] is None
    assert tracer["completed_at"] is None
    assert tracer["abort_reason"] is None
    assert tracer["contributes_to_readiness"] is False
    assert float(tracer["scored_weight"]) == 0
    assert float(tracer["earned_weight"]) == 0
    assert float(tracer["tracer_score"]) == 0.00

    unit = read_unit(built["unit"]["id"])
    assert unit["scheduled_tracer_count"] == 1
    assert unit["version"] == 2


def test_start_tracer_before_window_start_is_rejected(api, tracer_surveyor_headers):
    """PRD §3.4: "`START` moves the tracer `SCHEDULED → IN_PROGRESS` and requires two things: the unit's `posture` must be `OPEN`, else `ERR_UNIT_POSTURE_RESTRICTED`, and the logical clock must be at or after the tracer's `window_start`, else `ERR_TRACER_WINDOW_NOT_STARTED`."
    PRD §2.11: "`START` requires the logical clock to be at or after the tracer's `window_start` — `ERR_TRACER_WINDOW_NOT_STARTED`, 409, on `POST /accreditation/mock-tracers/{id}/transition`."
    PRD §2.4: "Time in this system is not wall-clock time. The server maintains a **logical clock** that begins at the fixed instant `2026-08-01T00:00:00Z` and never falls back to real time; every deadline, window boundary, expiry and "current instant" in this specification means the value of that logical clock at the moment the request is processed."

    Design: Corner/state_machines/tracer_start_before_window_start_rejected
    """
    built = _setup_scheduled_tracer()

    # The clock still stands at its starting instant, well before 2026-08-20T08:00Z.
    response = api.transition_mock_tracer(
        built["tracer"]["id"], {"action": "START"}, tracer_surveyor_headers
    )
    validate_error(response, ApiErrorId.ERR_TRACER_WINDOW_NOT_STARTED)

    tracer = validate_success(api.get_mock_tracer(built["tracer"]["id"], tracer_surveyor_headers))
    assert tracer["state"] == "SCHEDULED"
    assert tracer["started_at"] is None

    unit = read_unit(built["unit"]["id"])
    assert unit["scheduled_tracer_count"] == 1


def test_abort_after_completion_returns_invalid_state_transition(api, tracer_surveyor_headers):
    """PRD §3.4: "The tracer lifecycle spans `SCHEDULED`, `IN_PROGRESS`, and the two terminal states `COMPLETED` and `ABORTED`, and is driven by an operation taking an `action` and an optional `abort_reason`."
    PRD §2.11: "The requested action is a declared transition out of the resource's current state (evidence `SUBMIT` from `DRAFT` or `REJECTED` and `REJECT` from `SUBMITTED` or `VALIDATED`; tracer `START` from `SCHEDULED` and `ABORT` from `SCHEDULED` or `IN_PROGRESS`; deficiency-ticket, survey-window, finding and self-assessment actions as declared in §3; self-assessment revision from `RETURNED_FOR_REASSESSMENT`) — `ERR_INVALID_STATE_TRANSITION`, 409, on every action-driven write: `POST /accreditation/evidence-items/{id}/transition`, `POST /accreditation/mock-tracers/{id}/transition`, `POST /accreditation/deficiency-tickets/{id}/transition`, `POST /accreditation/survey-windows/{id}/transition`, `POST /accreditation/owner-assignments/{id}/revoke`, `POST /accreditation/rounding-sessions/{id}/close` and `POST /accreditation/ppr-self-assessments/{id}/revise`."
    PRD §3.4: "`completed_at` is stamped with the current logical clock."

    Design: Corner/state_machines/tracer_abort_after_completion_returns_invalid_state_transition
    """
    built = _setup_completed_tracer_scoring_one_hundred()
    assert built["tracer"]["state"] == "COMPLETED"
    assert float(built["tracer"]["tracer_score"]) == 100.00
    assert built["tracer"]["completed_at"] == "2026-08-05T09:00:00.000Z"

    response = api.transition_mock_tracer(
        built["tracer"]["id"],
        {"action": "ABORT", "abort_reason": "Late cancellation"},
        tracer_surveyor_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    tracer = validate_success(api.get_mock_tracer(built["tracer"]["id"], tracer_surveyor_headers))
    assert tracer["state"] == "COMPLETED"
    assert float(tracer["tracer_score"]) == 100.00
    assert tracer["abort_reason"] is None

    unit = read_unit(built["unit"]["id"])
    assert float(unit["readiness_score"]) == 100.00
    assert unit["readiness_band"] == "READY"


def test_observation_on_scheduled_tracer_returns_not_in_progress(api, tracer_surveyor_headers):
    """PRD §3.4: "The tracer's `state` must be `IN_PROGRESS` or the write is refused with `ERR_TRACER_NOT_IN_PROGRESS`, and the observed standard must belong to the tracer's own `chapter_id` or the write is refused with `ERR_STANDARD_CHAPTER_MISMATCH` — a tracer sampling one chapter cannot record evidence about another."
    PRD §2.11: "`COMPLETE` requires the tracer's `state` to be `IN_PROGRESS`, and recording an observation likewise requires the tracer to be `IN_PROGRESS` — `ERR_TRACER_NOT_IN_PROGRESS`, 409, on `POST /accreditation/mock-tracers/{id}/transition` and `POST /accreditation/mock-tracers/{id}/observations`."
    PRD §2.3: "The `meta` object of every collection response carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` is the size of the filtered result set before pagination is applied and `has_more` indicates whether rows remain beyond the current page."

    Design: Corner/state_machines/observation_on_scheduled_tracer_returns_not_in_progress
    """
    built = _setup_scheduled_tracer()
    assert built["tracer"]["state"] == "SCHEDULED"

    response = api.create_tracer_observation(
        built["tracer"]["id"],
        {"standard_id": built["standard"]["id"], "result": "COMPLIANT", "weight": 1},
        tracer_surveyor_headers,
    )
    validate_error(response, ApiErrorId.ERR_TRACER_NOT_IN_PROGRESS)

    rows, meta = validate_paginated(
        api.list_tracer_observations(built["tracer"]["id"], tracer_surveyor_headers)
    )
    assert meta["total_count"] == 0
    assert rows == []

    tracer = validate_success(api.get_mock_tracer(built["tracer"]["id"], tracer_surveyor_headers))
    assert float(tracer["scored_weight"]) == 0


def test_complete_tracer_without_observations_returns_no_observations_recorded(
    api, tracer_surveyor_headers
):
    """PRD §3.4: "It moves the tracer `IN_PROGRESS → COMPLETED`, requires the current `state` to be `IN_PROGRESS` (else `ERR_TRACER_NOT_IN_PROGRESS`) and requires at least one observation to exist on the tracer (else `ERR_NO_OBSERVATIONS_RECORDED`)."
    PRD §2.11: "`COMPLETE` requires at least one observation on the tracer — `ERR_NO_OBSERVATIONS_RECORDED`, 422, on `POST /accreditation/mock-tracers/{id}/transition`."
    PRD §3.4: "Starting stamps `started_at` with the current logical clock, decrements the unit's `scheduled_tracer_count` by one, recomputes the unit's readiness, and advances the tracer's `version`."
    PRD §3.3: "If no chapter participates, the computation stops immediately with `readiness_score` 0.00 and `readiness_band` `NOT_ASSESSED`, and the penalty is **not** applied — an unassessed unit is not punished for its open deficiencies."

    Design: Corner/state_machines/complete_tracer_without_observations_returns_no_observations_recorded
    """
    built = _setup_scheduled_tracer()
    set_clock("2026-08-20T08:00:00Z")
    started = tracer_action(built["tracer"]["id"], "START")
    assert started["state"] == "IN_PROGRESS"
    assert started["started_at"] == "2026-08-20T08:00:00.000Z"

    response = api.transition_mock_tracer(
        built["tracer"]["id"], {"action": "COMPLETE"}, tracer_surveyor_headers
    )
    validate_error(response, ApiErrorId.ERR_NO_OBSERVATIONS_RECORDED)

    tracer = validate_success(api.get_mock_tracer(built["tracer"]["id"], tracer_surveyor_headers))
    assert tracer["state"] == "IN_PROGRESS"
    assert tracer["completed_at"] is None

    unit = read_unit(built["unit"]["id"])
    assert unit["readiness_band"] == "NOT_ASSESSED"


def test_posture_restriction_aborts_only_the_scheduled_tracer(api, safety_officer_headers):
    """PRD §3.3: "`OPEN → RESTRICTED` fires automatically whenever the unit's `open_deficiency_penalty_points` changes — on ticket creation, on escalation, on a failed verification — and the resulting total is at least fifteen points."
    PRD §3.3: "That transition drags a cascade behind it: every mock tracer of the unit still in `SCHEDULED` moves to `ABORTED` with `abort_reason` set to `UNIT_POSTURE_RESTRICTED`, which zeroes `scheduled_tracer_count` and forces a recomputation of `readiness_score` and `readiness_band`."
    PRD §3.3: "Severity determines a ticket's points: a `LOW` ticket is worth one point, a `MODERATE` ticket three, a `HIGH` ticket seven, and an `IMMEDIATE_THREAT` ticket fifteen."
    PRD §3.3: "The band is then read off four thresholds: `READY` at 90.00 or above, `CONDITIONAL` at 75.00 or above, `AT_RISK` at 60.00 or above, and `NOT_READY` below that."

    Design: Corner/state_machines/posture_restriction_spares_in_progress_and_completed_tracers
    """
    built = _setup_unit_with_completed_in_progress_and_scheduled_tracers()
    assert float(built["completed_tracer"]["tracer_score"]) == 78.00
    assert built["in_progress_tracer"]["state"] == "IN_PROGRESS"
    assert read_unit(built["unit"]["id"])["posture"] == "OPEN"

    # The third HIGH ticket takes the ledger from fourteen to twenty-one points.
    raise_deficiency(
        built["session"]["id"], built["second_standard"]["id"], "HIGH", "Damaged ceiling tile"
    )

    unit = read_unit(built["unit"]["id"])
    assert unit["open_deficiency_penalty_points"] == 21
    assert unit["posture"] == "RESTRICTED"
    assert unit["scheduled_tracer_count"] == 0
    assert float(unit["readiness_score"]) == 57.00
    assert unit["readiness_band"] == "NOT_READY"

    aborted = validate_success(
        api.get_mock_tracer(built["scheduled_tracer"]["id"], safety_officer_headers)
    )
    assert aborted["state"] == "ABORTED"
    assert aborted["abort_reason"] == "UNIT_POSTURE_RESTRICTED"

    spared_in_progress = validate_success(
        api.get_mock_tracer(built["in_progress_tracer"]["id"], safety_officer_headers)
    )
    assert spared_in_progress["state"] == "IN_PROGRESS"
    assert spared_in_progress["abort_reason"] is None

    spared_completed = validate_success(
        api.get_mock_tracer(built["completed_tracer"]["id"], safety_officer_headers)
    )
    assert spared_completed["state"] == "COMPLETED"
    assert spared_completed["abort_reason"] is None


# ---------------------------------------------------------------------------
# validations
# ---------------------------------------------------------------------------

def test_tracer_zero_length_window_returns_invalid_interval(api, tracer_surveyor_headers):
    """PRD §3.4: "The `window_end` must be strictly after `window_start`, or `ERR_INVALID_INTERVAL`."
    PRD §2.11: "Interval sanity: `window_end` strictly after `window_start` — `ERR_INVALID_INTERVAL`, 422, on `POST /accreditation/mock-tracers` and `POST /accreditation/rounding-sessions`."

    Design: Corner/validations/tracer_zero_length_window_returns_invalid_interval
    """
    built = _setup_mapped_chapter_and_unit(unit_name="ICU-9", bed_count=10)

    response = api.create_mock_tracer(
        {
            "unit_id": built["unit"]["id"],
            "chapter_id": built["chapter"]["id"],
            "tracer_type": "SYSTEM",
            "window_start": "2026-08-20T08:00:00Z",
            "window_end": "2026-08-20T08:00:00Z",
            "expected_unit_version": built["unit"]["version"],
        },
        tracer_surveyor_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_INTERVAL)

    unit = read_unit(built["unit"]["id"])
    assert unit["scheduled_tracer_count"] == 0
    assert unit["version"] == built["unit"]["version"]


def test_observation_naming_standard_of_another_chapter_is_rejected(api, tracer_surveyor_headers):
    """PRD §3.4: "The tracer's `state` must be `IN_PROGRESS` or the write is refused with `ERR_TRACER_NOT_IN_PROGRESS`, and the observed standard must belong to the tracer's own `chapter_id` or the write is refused with `ERR_STANDARD_CHAPTER_MISMATCH` — a tracer sampling one chapter cannot record evidence about another."
    PRD §2.11: "Chapter membership: every `standard_id` inside `self_ratings` belongs to the path chapter, and every observation's `standard_id` belongs to the tracer's `chapter_id` — `ERR_STANDARD_CHAPTER_MISMATCH`, 422, on `POST /accreditation/chapters/{id}/ppr-self-assessments`, `POST /accreditation/ppr-self-assessments/{id}/revise` and `POST /accreditation/mock-tracers/{id}/observations`."
    PRD §3.1: "The new standard begins at `compliance_state` `UNMAPPED`, with `active_owner_count` and `validated_evidence_count` at zero and `last_noncompliant_observed_at` null."

    Design: Corner/validations/observation_standard_outside_tracer_chapter_rejected
    """
    built = _setup_mapped_chapter_and_unit(
        weight_pct=60, unit_name="ICU-10", bed_count=10
    )
    other_chapter = create_chapter("IC", "Infection Control", 40, 1)
    other_standard = create_standard(
        other_chapter["id"], "IC.01.01.01", "Hand hygiene program", "DIRECT_IMPACT"
    )
    tracer = schedule_tracer(
        built["unit"]["id"],
        built["chapter"]["id"],
        "2026-08-20T08:00:00Z",
        "2026-08-20T10:00:00Z",
        tracer_type="SYSTEM",
        expected_unit_version=built["unit"]["version"],
    )
    set_clock("2026-08-20T08:00:00Z")
    tracer_action(tracer["id"], "START")

    response = api.create_tracer_observation(
        tracer["id"],
        {"standard_id": other_standard["id"], "result": "NON_COMPLIANT", "weight": 5},
        tracer_surveyor_headers,
    )
    # The standard exists, so this is a membership failure and not a 404.
    validate_error(response, ApiErrorId.ERR_STANDARD_CHAPTER_MISMATCH)

    rows, meta = validate_paginated(
        api.list_tracer_observations(tracer["id"], tracer_surveyor_headers)
    )
    assert meta["total_count"] == 0
    assert rows == []
    assert read_standard(other_standard["id"])["compliance_state"] == "UNMAPPED"


def test_tracer_scheduling_on_unmapped_chapter_is_rejected(api, tracer_surveyor_headers):
    """PRD §3.4: "And the target chapter must actually have accountability in place: its `mapped_standard_count` must be at least one, or the request fails with `ERR_CHAPTER_NOT_MAPPED`, since tracing standards nobody owns produces findings nobody can answer."
    PRD §2.9: "The **chapter mapped-standard ledger** pins `Chapter.mapped_standard_count` to the number of standards in that chapter whose `active_owner_count` is at least 1."
    PRD §3.1: "If that count moved from zero to one, the standard transitions `UNMAPPED → MAPPED` and its chapter's `mapped_standard_count` increases by one — the count only moves on that zero-to-one edge, so a second owner leaves it alone."

    Design: Corner/validations/tracer_scheduling_on_unmapped_chapter_rejected
    """
    chapter = create_chapter("LD", "Leadership", 100, 1)
    standard = create_standard(
        chapter["id"], "LD.03.01.01", "Safety culture", "SITUATIONAL_DECISION_RULE"
    )
    unit = create_unit("ED-10", "ED", 16)
    assert read_chapter(chapter["id"])["mapped_standard_count"] == 0

    payload = {
        "unit_id": unit["id"],
        "chapter_id": chapter["id"],
        "tracer_type": "SYSTEM",
        "window_start": "2026-08-20T08:00:00Z",
        "window_end": "2026-08-20T10:00:00Z",
        "expected_unit_version": unit["version"],
    }
    validate_error(
        api.create_mock_tracer(payload, tracer_surveyor_headers),
        ApiErrorId.ERR_CHAPTER_NOT_MAPPED,
    )

    assign_owner(standard["id"], "owner-1", "PRIMARY")
    assert read_chapter(chapter["id"])["mapped_standard_count"] == 1

    # The rejected attempt performed no write, so the same unit version is current.
    tracer = validate_success(api.create_mock_tracer(payload, tracer_surveyor_headers), 201)
    assert tracer["state"] == "SCHEDULED"


def test_immediate_threat_anywhere_blocks_tracer_on_an_open_unit(api, tracer_surveyor_headers):
    """PRD §3.4: "No deficiency ticket anywhere in the hospital may be sitting in `ESCALATED` with `severity` `IMMEDIATE_THREAT`, or the request fails with `ERR_IMMEDIATE_THREAT_ACTIVE` — an unresolved immediate threat freezes the rehearsal program hospital-wide, not just on the affected unit."
    PRD §2.11: "No deficiency ticket anywhere in the hospital is in `ESCALATED` with `severity` `IMMEDIATE_THREAT` — `ERR_IMMEDIATE_THREAT_ACTIVE`, 409, on `POST /accreditation/mock-tracers` and on the `OPEN_SURVEY` action of `POST /accreditation/survey-windows/{id}/transition`."
    PRD §3.5: "When the ticket's rounding session has `round_type` `LIFE_SAFETY`, escalation raises the ticket's `severity` to `IMMEDIATE_THREAT` and recomputes its `penalty_points` to the fifteen points that severity carries; an `ENVIRONMENT_OF_CARE` escalation leaves severity and points as they were."

    Design: Corner/validations/immediate_threat_anywhere_blocks_tracer_on_an_open_unit
    """
    built = _setup_escalated_immediate_threat_on_another_unit()
    assert built["ticket"]["state"] == "ESCALATED"
    assert built["ticket"]["severity"] == "IMMEDIATE_THREAT"
    assert built["ticket"]["penalty_points"] == 15
    assert read_unit(built["threatened_unit"]["id"])["posture"] == "RESTRICTED"

    clean = read_unit(built["clean_unit"]["id"])
    assert clean["posture"] == "OPEN"

    # The target unit passes the posture rung, so the refusal can only be the
    # hospital-wide immediate-threat freeze.
    response = api.create_mock_tracer(
        {
            "unit_id": clean["id"],
            "chapter_id": built["chapter"]["id"],
            "tracer_type": "SYSTEM",
            "window_start": "2026-08-20T08:00:00Z",
            "window_end": "2026-08-20T10:00:00Z",
            "expected_unit_version": clean["version"],
        },
        tracer_surveyor_headers,
    )
    validate_error(response, ApiErrorId.ERR_IMMEDIATE_THREAT_ACTIVE)

    assert read_unit(clean["id"])["scheduled_tracer_count"] == 0


# ---------------------------------------------------------------------------
# cross_cutting_complexity_layers
# ---------------------------------------------------------------------------

def test_stale_unit_version_rejects_second_tracer_schedule(api, tracer_surveyor_headers):
    """PRD §2.7: "Scheduling a mock tracer — `POST /accreditation/mock-tracers` — requires a non-optional `expected_unit_version` field in the request body carrying the client's last observed `version` of the target `HospitalUnit`."
    PRD §2.7: "If that value does not equal the unit's current `version` at write time, the request is rejected with `ERR_STALE_UNIT_VERSION` (HTTP 412)."
    PRD §2.7: "Scheduling a second tracer on the same unit for a different window is perfectly legal, so the rejection is not about duplication; it exists because the surveyor's picture of the unit — its `posture`, its `open_deficiency_penalty_points`, its already-scheduled tracers — has moved on since they read it."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_unit_version_rejects_tracer_schedule
    """
    built = _setup_mapped_chapter_and_unit(unit_name="ICU-16")
    stale_version = built["unit"]["version"]
    schedule_tracer(
        built["unit"]["id"],
        built["chapter"]["id"],
        "2026-08-20T08:00:00Z",
        "2026-08-20T10:00:00Z",
        tracer_type="PATIENT",
        expected_unit_version=stale_version,
    )

    unit = read_unit(built["unit"]["id"])
    assert unit["version"] == stale_version + 1
    assert unit["scheduled_tracer_count"] == 1

    # A window a full day later can never collide, so only the version is at issue.
    payload = {
        "unit_id": built["unit"]["id"],
        "chapter_id": built["chapter"]["id"],
        "tracer_type": "SYSTEM",
        "window_start": "2026-08-21T08:00:00Z",
        "window_end": "2026-08-21T10:00:00Z",
        "expected_unit_version": stale_version,
    }
    validate_error(
        api.create_mock_tracer(payload, tracer_surveyor_headers),
        ApiErrorId.ERR_STALE_UNIT_VERSION,
    )
    assert read_unit(built["unit"]["id"])["scheduled_tracer_count"] == 1

    payload["expected_unit_version"] = unit["version"]
    second = validate_success(api.create_mock_tracer(payload, tracer_surveyor_headers), 201)
    assert second["state"] == "SCHEDULED"
    assert read_unit(built["unit"]["id"])["scheduled_tracer_count"] == 2
