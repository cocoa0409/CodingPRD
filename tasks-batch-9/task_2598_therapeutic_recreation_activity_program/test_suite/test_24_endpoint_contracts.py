"""Endpoint-contract corner cases.

Every test here drives the live API over real HTTP against an empty database
whose logical clock reads 2026-08-01T00:00:00Z, and builds all of its state
through declared endpoints only.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_values
from test_helpers.constants import ABSENT_UUID, ABSENT_UUID_2


def test_resident_patch_updates_fields_and_bumps_version(api, director, therapist):
    """A census correction moves only the name and the room and advances the
    resident's version, leaving the supervision tier, the engagement figures and
    both gate fields exactly as the assessment left them.

    PRD §3.1: "Only `full_name`, `room_number`, and `status` may be edited"

    Design: Corner/endpoints/resident_patch_updates_fields_and_bumps_version
    """
    resident = validate_success(
        api.create_resident(
            f.resident_payload(
                full_name="Patch Petra",
                room_number="601A",
                admission_date="2026-07-31",
            ),
            director,
        ),
        201,
    )
    validate_success(
        api.create_assessment(
            resident["id"],
            f.assessment_payload(
                cognitive_level="MODERATE_IMPAIRMENT",
                functional_mobility="ASSIST_1",
                interest_domains=["CREATIVE"],
                preferred_group_size="SMALL",
                effective_date="2026-07-31",
            ),
            therapist,
        ),
        201,
    )

    before = validate_success(api.get_resident(resident["id"], director), 200)
    assert before["version"] == 2, (
        "Filing the assessment must already have advanced the resident once, "
        f"so the version before the census edit is 2, got {before['version']!r}"
    )
    assert before["supervision_tier"] == "TIER_2", (
        "MODERATE_IMPAIRMENT cognition sits in band 2 and ASSIST_1 function in "
        f"band 1, so the worse band is TIER_2, got {before['supervision_tier']!r}"
    )

    updated = validate_success(
        api.update_resident(
            resident["id"],
            {"full_name": "Patch Petra Novak", "room_number": "601B"},
            director,
        ),
        200,
    )
    assert_values(
        updated,
        full_name="Patch Petra Novak",
        room_number="601B",
        version=3,
    )

    stored = validate_success(api.get_resident(resident["id"], director), 200)
    assert_values(
        stored,
        full_name="Patch Petra Novak",
        room_number="601B",
        version=3,
        status="ADMITTED",
        supervision_tier="TIER_2",
        refusal_streak=0,
        enrollment_gate="NONE",
        care_plan_review_due=False,
    )
    assert stored["engagement_index"] == 0.0, (
        "A census edit never touches the engagement index, which is still 0.0, "
        f"got {stored['engagement_index']!r}"
    )


def test_outing_finalize_conditional_action_rejected(api, director):
    """Finalizing an outing is conditional on the escort roster: a single TIER_3
    rider forces a floor of two escorts, so FINALIZE at one escort is refused and
    the very same call succeeds once the escort count is raised.

    PRD §3.8: "`FINALIZE` moves `TRANSPORT_BOOKED → READY` and requires that
    `escort_count` is at or above `required_escorts` (equality passes)"

    Design: Corner/endpoints/outing_finalize_conditional_action_rejected
    """
    resident = fx.create_resident(
        api,
        full_name="Escort Ernest",
        room_number="602A",
        admission_date="2026-07-31",
    )
    fx.file_assessment(
        api,
        resident["id"],
        cognitive_level="SEVERE_IMPAIRMENT",
        functional_mobility="INDEPENDENT",
        interest_domains=["SOCIAL"],
        preferred_group_size="SOLO",
        effective_date="2026-07-31",
    )
    program = fx.create_program(
        api,
        name="Escort Outing Program",
        domain="SOCIAL",
        staffing_ratio_denominator=4,
        max_group_size=8,
        max_supervision_tier="TIER_3",
    )
    vehicle = fx.create_vehicle(
        api,
        label="Van 18",
        ambulatory_seats=8,
        wheelchair_stations=2,
        turnaround_minutes=30,
    )
    outing = fx.create_outing(
        api,
        program["id"],
        vehicle["id"],
        destination="Lighthouse",
        departure_at="2026-09-09T09:00:00Z",
        return_at="2026-09-09T13:00:00Z",
        escort_count=1,
    )
    consent = fx.add_rider(
        api,
        outing["id"],
        resident["id"],
        responsible_party_name="Ernest Family",
        responsible_party_relation="POA",
    )
    fx.decide_consent(api, outing["id"], consent["id"], "GRANTED")
    fx.book_transport(api, outing["id"], vehicle_id=vehicle["id"])

    validate_error(
        api.outing_logistics(outing["id"], {"action": "FINALIZE"}, director),
        ApiErrorId.SUPERVISION_RATIO_UNMET.value,
        409,
    )

    refused = validate_success(api.get_outing(outing["id"], director), 200)
    assert_values(
        refused,
        logistics_status="TRANSPORT_BOOKED",
        consent_status="CONSENT_COMPLETE",
        required_escorts=2,
        escort_count=1,
    )
    granted = validate_success(api.get_outing_consent(consent["id"], director), 200)
    assert_values(granted, status="GRANTED", effective=True)

    adjusted = validate_success(
        api.outing_logistics(
            outing["id"], {"action": "SET_ESCORTS", "escort_count": 2}, director
        ),
        200,
    )
    assert_values(adjusted, escort_count=2, ambulatory_seats_required=3)

    finalized = validate_success(
        api.outing_logistics(outing["id"], {"action": "FINALIZE"}, director), 200
    )
    assert_values(finalized, logistics_status="READY")
    assert_values(
        validate_success(api.get_outing(outing["id"], director), 200),
        logistics_status="READY",
        escort_count=2,
    )


def test_volunteer_assignment_link_requires_both_rows_not_found(api, coordinator):
    """The volunteer-to-session junction resolves its two body foreign keys in
    their declared order, so an absent volunteer reports the volunteer lookup
    failure and an absent session the session lookup failure; only when both
    rows exist is the assignment created.

    PRD §2.9: "Foreign keys arriving in a request **body** are resolved after
    every path identifier, and in the order the fields are declared for that
    endpoint."

    Design: Corner/endpoints/volunteer_assignment_link_requires_both_rows_not_found
    """
    program = fx.create_program(
        api,
        name="Link Program",
        domain="CREATIVE",
        staffing_ratio_denominator=4,
        max_group_size=10,
        max_supervision_tier="TIER_2",
        volunteer_eligible=True,
        required_screening_level="BASIC",
    )
    room = fx.create_room(api, name="Link Room", capacity=10, buffer_minutes=0)
    session = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-09-10T10:00:00Z",
        ends_at="2026-09-10T11:00:00Z",
        assigned_staff_count=2,
    )
    volunteer = fx.cleared_volunteer(
        api,
        cleared_on="2026-07-04",
        completed_on="2026-07-08",
        full_name="Linked Lena",
        volunteer_type="ADULT_COMMUNITY",
    )

    validate_error(
        api.create_volunteer_assignment(
            f.assignment_payload(ABSENT_UUID, session["id"], role_type="GROUP_ASSISTANT"),
            coordinator,
        ),
        ApiErrorId.VOLUNTEER_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.create_volunteer_assignment(
            f.assignment_payload(
                volunteer["id"], ABSENT_UUID_2, role_type="GROUP_ASSISTANT"
            ),
            coordinator,
        ),
        ApiErrorId.SESSION_NOT_FOUND.value,
        404,
    )

    created = validate_success(
        api.create_volunteer_assignment(
            f.assignment_payload(
                volunteer["id"], session["id"], role_type="GROUP_ASSISTANT"
            ),
            coordinator,
        ),
        201,
    )
    assert_values(created, status="PROPOSED", volunteer_id=volunteer["id"])
    assert created["hours"] == 1.0, (
        "A one-hour session yields one hour of assignment time, "
        f"got {created['hours']!r}"
    )

    stored = validate_success(
        api.get_volunteer_assignment(created["id"], coordinator), 200
    )
    assert_values(stored, status="PROPOSED", session_id=session["id"])

    rows, meta = validate_paginated(
        api.list_volunteer_assignments(coordinator, {"session_id": session["id"]})
    )
    assert meta["total_count"] == 1, (
        "Only the one fully valid association may exist on the session, "
        f"got total_count {meta['total_count']!r}"
    )
    assert [row["id"] for row in rows] == [created["id"]], (
        f"The session's only assignment is {created['id']!r}, got {rows!r}"
    )


def test_session_status_cancel_reason_contract_returns_4xx(api, director, aide):
    """The cancellation narrative is paired to the action: a cancellation without
    a reason and a start carrying one are both schema failures, and only the
    correctly paired cancellation moves the calendar slot.

    PRD §3.4: "A `cancel_reason` is required when the action is `CANCEL` and is
    rejected on any other action"

    Design: Corner/endpoints/session_status_cancel_reason_contract_returns_4XX
    """
    program = fx.create_program(
        api,
        name="Contract Program",
        domain="PHYSICAL",
        staffing_ratio_denominator=4,
        max_group_size=10,
        max_supervision_tier="TIER_3",
    )
    room = fx.create_room(api, name="Contract Room", capacity=10, buffer_minutes=0)
    session = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-09-11T10:00:00Z",
        ends_at="2026-09-11T11:00:00Z",
        assigned_staff_count=2,
    )

    validate_error(
        api.session_status(session["id"], {"action": "CANCEL"}, director),
        ApiErrorId.INVALID_REQUEST.value,
        400,
    )
    validate_error(
        api.session_status(
            session["id"], {"action": "START", "cancel_reason": "Not applicable"}, aide
        ),
        ApiErrorId.INVALID_REQUEST.value,
        400,
    )

    untouched = validate_success(api.get_session(session["id"], director), 200)
    assert_values(untouched, status="SCHEDULED", cancel_reason=None)

    cancelled = validate_success(
        api.session_status(
            session["id"],
            {"action": "CANCEL", "cancel_reason": "Van unavailable"},
            director,
        ),
        200,
    )
    assert_values(cancelled, status="CANCELLED", cancel_reason="Van unavailable")
    assert_values(
        validate_success(api.get_session(session["id"], director), 200),
        status="CANCELLED",
        cancel_reason="Van unavailable",
    )
