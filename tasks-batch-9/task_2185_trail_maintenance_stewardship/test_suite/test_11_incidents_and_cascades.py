"""Incident reporting, the four-level severe-incident cascade, and closure."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_extra_party,
    assert_incident,
    build_user_headers,
    confirm_party,
    file_incident,
    read_agreement,
    read_incident,
    read_party,
    read_segment,
    read_shift,
    read_volunteer,
    register_volunteer_on_party,
    set_clock,
    setup_confirmed_party,
    setup_started_party,
    start_party,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]
SAFETY_ALT = TEST_USERS["safety_officer_alt_headers"]


def _two_parties_then_severe_incident():
    """P1 in progress with Milo aboard, P2 confirmed with Nadia, then a SEVERE incident."""
    world = setup_confirmed_party(with_first_aider=True)
    add_extra_party(
        world,
        key="p2",
        start_at="2026-09-05T16:00:00.000Z",
        end_at="2026-09-05T20:00:00.000Z",
    )
    world["shift_aid"] = register_volunteer_on_party(
        world["p2_id"], world["lead_id"], world["aid_id"], role_on_crew="FIRST_AIDER"
    )
    confirm_party(world["p2_id"], world["lead_id"])

    set_clock("2026-09-05T09:00:00.000Z")
    start_party(world["party_id"], world["lead_id"])
    set_clock("2026-09-05T11:00:00.000Z")

    world["incident"] = file_incident(
        world["party_id"],
        world["lead_headers"],
        severity_class="SEVERE",
        first_aid_rendered=True,
        narrative="Saw kickback laceration on the lower reroute.",
        occurred_at="2026-09-05T11:00:00.000Z",
        injured_volunteer_id=world["saw_id"],
    )
    return world


def test_severe_incident_closes_the_segment_and_suspends_the_adoption_and_party(api):
    """PRD 3.9: "Filing one raises the segment's `open_severe_incident_count`, which drives the posture to `INCIDENT_CLOSED`; that suspends the segment's `ACTIVE` adoption with `suspension_reason` `SEGMENT_INCIDENT`; that suspends the agreement's `CONFIRMED` work parties and blocks its `PLANNED` ones; and that withdraws the `REGISTERED` shifts on the parties that actually moved to `SUSPENDED`, decrementing each volunteer's `active_registration_count`."
    PRD 3.9: "On creation the server copies the party's `trail_segment_id` onto the incident, records the filer's `X-User-ID` as `reported_by_user_id`, and lands the incident in `OPEN` with `closed_by_user_id`, `corrective_action` and `closed_at` null."
    PRD 2.6: "If `open_severe_incident_count` is at least 1, the posture is `INCIDENT_CLOSED`."

    Design: Difficulty/transitive_cascade/severe_incident_cascades_segment_then_agreement_then_party_then_shift
    """
    world = _two_parties_then_severe_incident()

    assert_incident(world["incident"])
    assert world["incident"]["trail_segment_id"] == world["seg_id"]
    assert read_incident(world["incident"]["id"])["status"] == "OPEN"

    segment = read_segment(world["seg_id"])
    assert segment["open_severe_incident_count"] == 1
    assert segment["posture"] == "INCIDENT_CLOSED"

    agreement = read_agreement(world["agreement_id"])
    assert agreement["status"] == "SUSPENDED"
    assert agreement["suspension_reason"] == "SEGMENT_INCIDENT"

    party_two = read_party(world["p2_id"])
    assert party_two["schedule_status"] == "SUSPENDED"
    assert party_two["readiness_status"] == "BLOCKED"
    assert party_two["block_reason"] == "AGREEMENT_SUSPENDED"


def test_severe_incident_cascade_withdraws_shifts_only_on_the_suspended_party(api):
    """PRD 2.10: "The deepest cascade runs four levels. A severe incident raises a segment's `open_severe_incident_count`, which drives the posture to `INCIDENT_CLOSED`; that suspends every `ACTIVE` adoption agreement on the segment; that in turn moves every `CONFIRMED` work party under the agreement's plans to `SUSPENDED` while setting `readiness_status` to `BLOCKED`, and blocks (without moving the schedule axis of) every `PLANNED` work party; and finally, on each party that actually moved to `SUSPENDED`, every `REGISTERED` shift moves to `WITHDRAWN` and the affected volunteer's `active_registration_count` drops by 1."
    PRD 2.10: "Parties that stayed `PLANNED` keep their rosters intact."

    Design: Difficulty/transitive_cascade/severe_incident_cascades_segment_then_agreement_then_party_then_shift
    """
    world = _two_parties_then_severe_incident()

    assert read_shift(world["shift_aid"]["id"])["status"] == "WITHDRAWN"
    assert read_volunteer(world["aid_id"])["active_registration_count"] == 0
    assert read_party(world["p2_id"])["registered_count"] == 0

    assert read_party(world["party_id"])["schedule_status"] == "IN_PROGRESS", (
        "an IN_PROGRESS party is not part of the suspension sweep"
    )
    assert read_shift(world["shift_saw_id"])["status"] == "REGISTERED"


def test_a_moderate_incident_cannot_be_closed_directly_from_open(api):
    """PRD 3.9: "A `MINOR` incident has no review step and is closed directly from `OPEN`; `MODERATE` and `SEVERE` incidents must pass through `UNDER_REVIEW` first, and an attempt to close them directly from `OPEN` finds no declared transition."
    PRD 3.9: "A `SafetyOfficer` opens formal review of an incident whose `severity_class` is `MODERATE` or `SEVERE`, moving it `OPEN → UNDER_REVIEW` with `updated_at` refreshed and `version` advanced by 1."
    PRD 3.9: "Closure stores `closed_by_user_id`, `corrective_action` and `closed_at`, and `CLOSED` is terminal."

    Design: Corner/state_machines/moderate_incident_cannot_close_directly_from_open
    """
    world = setup_started_party()
    incident = file_incident(
        world["party_id"],
        world["lead_headers"],
        severity_class="MODERATE",
        first_aid_rendered=True,
        narrative="Turned ankle on the talus crossing.",
        occurred_at="2026-09-05T09:00:00.000Z",
        injured_volunteer_id=world["saw_id"],
    )
    assert incident["status"] == "OPEN"

    early = api.close_incident(
        incident["id"], {"corrective_action": "Reroute the talus approach."}, SAFETY
    )
    validate_error(early, ApiErrorId.ERR_INVALID_STATE.value, 409)

    reviewed = validate_success(api.review_incident(incident["id"], SAFETY))
    assert reviewed["status"] == "UNDER_REVIEW"

    closed = validate_success(
        api.close_incident(
            incident["id"],
            {"corrective_action": "Reroute the talus approach."},
            SAFETY_ALT,
        )
    )
    assert closed["status"] == "CLOSED"
    assert closed["closed_by_user_id"] == "safety-2"

    segment = read_segment(world["seg_id"])
    assert segment["posture"] == "OPEN"
    assert segment["open_severe_incident_count"] == 0


def test_an_incident_cannot_be_closed_by_the_person_who_reported_it(api):
    """PRD 2.1: "Certifying a shift's hours requires that the acting `X-User-ID` differ from the `hours_verified_by_user_id` already recorded on that shift, and closing an incident requires that the acting `X-User-ID` differ from the `reported_by_user_id` recorded on that incident. Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD 3.9: "Closing an incident, from either `OPEN` for a `MINOR` one or `UNDER_REVIEW` for the rest, is a `SafetyOfficer` act requiring a non-empty `corrective_action` and requiring that the acting `X-User-ID` differ from the recorded `reported_by_user_id`; a closer who is also the reporter is refused with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/state_machines/incident_cannot_be_closed_by_its_own_reporter
    """
    world = setup_started_party()
    incident = file_incident(
        world["party_id"],
        build_user_headers("safety-9", "Volunteer"),
        severity_class="MINOR",
        first_aid_rendered=False,
        narrative="Blister, self-treated.",
        occurred_at="2026-09-05T09:00:00.000Z",
    )
    assert incident["reported_by_user_id"] == "safety-9"

    same_person = api.close_incident(
        incident["id"],
        {"corrective_action": "Add moleskin to the kit."},
        build_user_headers("safety-9", "SafetyOfficer"),
    )
    validate_error(same_person, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    closed = validate_success(
        api.close_incident(
            incident["id"], {"corrective_action": "Add moleskin to the kit."}, SAFETY
        )
    )
    assert closed["status"] == "CLOSED"
    assert read_incident(incident["id"])["closed_by_user_id"] == "safety-1"


def test_incident_listing_is_filterable_by_trail_segment(api):
    """PRD 3.9: "Incident listings may be narrowed by `work_party_id`, by `trail_segment_id`, by `injured_volunteer_id` and by `status`."
    PRD 3.9: "On creation the server copies the party's `trail_segment_id` onto the incident, records the filer's `X-User-ID` as `reported_by_user_id`, and lands the incident in `OPEN` with `closed_by_user_id`, `corrective_action` and `closed_at` null."

    Design: Corner/endpoints/incidents_filtered_list_by_trail_segment_returns_array
    """
    world = setup_started_party()
    incident = file_incident(
        world["party_id"],
        world["lead_headers"],
        severity_class="MINOR",
        first_aid_rendered=True,
        narrative="Hand blister dressed on site.",
        occurred_at="2026-09-05T09:00:00.000Z",
        injured_volunteer_id=world["saw_id"],
    )

    response = api.list_incidents(SAFETY, params={"trail_segment_id": world["seg_id"]})
    rows, meta = validate_paginated(response)
    assert len(rows) == 1
    assert rows[0]["id"] == incident["id"]
    assert meta["total_count"] == 1
    assert meta["has_more"] is False

    assert read_incident(incident["id"])["trail_segment_id"] == world["seg_id"]
    segment = read_segment(world["seg_id"])
    assert segment["open_severe_incident_count"] == 0
    assert segment["posture"] == "OPEN"
