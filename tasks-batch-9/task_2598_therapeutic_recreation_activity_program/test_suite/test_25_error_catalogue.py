"""Error-catalogue corner cases.

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
from test_helpers.constants import (
    ABSENT_UUID,
    ABSENT_UUID_2,
    ABSENT_UUID_3,
    ABSENT_UUID_4,
    ABSENT_UUID_5,
    ABSENT_UUID_6,
    ABSENT_UUID_7,
    ABSENT_UUID_8,
)
from test_helpers.test_users import COMPLIANCE_B_USER_ID, make_headers


def test_unrecognized_role_header_returns_401_unauthorized(api):
    """A caller declaring a capacity outside the seven recognized department roles
    is turned away as unauthenticated, before any authorization consideration.

    PRD §2.1: "if the value of `X-User-Role` is not one of the seven role names
    below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before
    any other consideration"

    Design: Corner/errors/unrecognized_role_header_returns_401_unauthorized
    """
    validate_error(
        api.list_residents(make_headers("custodian-01", "Custodian")),
        ApiErrorId.UNAUTHENTICATED.value,
        401,
    )


def test_remaining_not_found_codes_each_triggerable_not_found(
    api, director, therapist, coordinator, compliance
):
    """Each addressable entity answers an absent identifier with its own dedicated
    lookup failure rather than one generic 404, whether the identifier arrives in
    the path or as a foreign key in the body.

    PRD §2.9: "Each segment has its own dedicated error identifier, all of them
    HTTP 404: a resident identifier yields `ERR_RESIDENT_NOT_FOUND`, a plan
    identifier yields `ERR_PLAN_NOT_FOUND`"

    Design: Corner/errors/remaining_not_found_codes_each_triggerable_not_found
    """
    program = fx.create_program(
        api,
        name="Sweep Program",
        domain="SOCIAL",
        staffing_ratio_denominator=4,
        max_group_size=10,
        max_supervision_tier="TIER_3",
    )

    validate_error(
        api.get_assessment(ABSENT_UUID, therapist),
        ApiErrorId.ASSESSMENT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_activity_plan(ABSENT_UUID_2, therapist),
        ApiErrorId.PLAN_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.create_session(
            f.session_payload(
                program["id"],
                ABSENT_UUID_3,
                starts_at="2026-09-14T10:00:00Z",
                ends_at="2026-09-14T11:00:00Z",
                assigned_staff_count=2,
            ),
            director,
        ),
        ApiErrorId.ROOM_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_volunteer_assignment(ABSENT_UUID_4, coordinator),
        ApiErrorId.ASSIGNMENT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.create_outing(
            f.outing_payload(
                program["id"],
                ABSENT_UUID_5,
                destination="Nowhere",
                departure_at="2026-09-14T09:00:00Z",
                return_at="2026-09-14T12:00:00Z",
                escort_count=1,
            ),
            director,
        ),
        ApiErrorId.VEHICLE_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_outing(ABSENT_UUID_6, director),
        ApiErrorId.OUTING_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_council_request(ABSENT_UUID_7, director),
        ApiErrorId.COUNCIL_REQUEST_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_survey_packet(ABSENT_UUID_8, compliance),
        ApiErrorId.SURVEY_PACKET_NOT_FOUND.value,
        404,
    )


def test_plan_outing_consent_invalid_state_codes_returns_4xx(api, director, therapist):
    """A plan, an outing and a consent row each answer an undeclared transition
    with their own state code, and each rejected call leaves its row untouched.

    PRD §3.2: "Any action that is not declared for the plan's present status is
    refused with `ERR_PLAN_INVALID_STATE`"

    Design: Corner/errors/plan_outing_consent_invalid_state_codes_returns_4XX
    """
    resident, assessment = fx.assessed_resident(
        api,
        resident_kwargs={
            "full_name": "State Sweep Sara",
            "room_number": "701A",
            "admission_date": "2026-07-31",
        },
        cognitive_level="INTACT",
        functional_mobility="INDEPENDENT",
        interest_domains=["SOCIAL"],
        preferred_group_size="LARGE",
        effective_date="2026-07-31",
    )
    plan = fx.active_plan(
        api,
        resident["id"],
        assessment["id"],
        targets=f.domain_targets(social=2),
        cycle_start_at="2026-08-01T00:00:00Z",
    )
    program = fx.create_program(
        api,
        name="State Sweep Program",
        domain="SOCIAL",
        staffing_ratio_denominator=4,
        max_group_size=10,
        max_supervision_tier="TIER_3",
    )
    vehicle = fx.create_vehicle(
        api,
        label="Van 20",
        ambulatory_seats=8,
        wheelchair_stations=2,
        turnaround_minutes=30,
    )
    outing = fx.create_outing(
        api,
        program["id"],
        vehicle["id"],
        destination="Aquarium",
        departure_at="2026-09-15T09:00:00Z",
        return_at="2026-09-15T12:00:00Z",
        escort_count=1,
    )
    consent = fx.add_rider(
        api,
        outing["id"],
        resident["id"],
        responsible_party_name="Sara Family",
        responsible_party_relation="ADULT_CHILD",
    )
    fx.decide_consent(api, outing["id"], consent["id"], "DENIED")

    validate_error(
        api.transition_activity_plan(plan["id"], {"action": "REACTIVATE"}, therapist),
        ApiErrorId.PLAN_INVALID_STATE.value,
        409,
    )
    validate_error(
        api.outing_logistics(outing["id"], {"action": "DEPART"}, director),
        ApiErrorId.OUTING_INVALID_STATE.value,
        409,
    )
    validate_error(
        api.decide_outing_consent(
            outing["id"], consent["id"], {"decision": "REVOKED"}, director
        ),
        ApiErrorId.CONSENT_INVALID_STATE.value,
        409,
    )

    assert_values(
        validate_success(api.get_activity_plan(plan["id"], therapist), 200),
        status="ACTIVE",
        revision_count=0,
    )
    assert_values(
        validate_success(api.get_outing(outing["id"], director), 200),
        logistics_status="PLANNING",
        departed_at=None,
        consent_status="CONSENT_BLOCKED",
    )
    assert_values(
        validate_success(api.get_outing_consent(consent["id"], director), 200),
        status="DENIED",
    )


def test_volunteer_council_packet_invalid_state_codes_returns_4xx(
    api, director, coordinator, compliance
):
    """The volunteer lifecycle, the assignment lifecycle, the council disposition
    lifecycle and the survey packet lifecycle each answer an undeclared step with
    their own state code, and the packet's state rule precedes its narrative rule.

    PRD §3.7: "`ORIENTATION_COMPLETED` is accepted only from `SCREENING` and
    drives the volunteer to `CLEARED`."

    Design: Corner/errors/volunteer_council_packet_invalid_state_codes_returns_4XX
    """
    applicant = fx.create_volunteer(
        api, full_name="Applicant Andy", volunteer_type="ADULT_COMMUNITY"
    )
    volunteer = fx.cleared_volunteer(
        api,
        cleared_on="2026-07-05",
        completed_on="2026-07-09",
        full_name="Cleared Cleo",
        volunteer_type="ADULT_COMMUNITY",
    )
    program = fx.create_program(
        api,
        name="State Sweep Volunteers",
        domain="CREATIVE",
        staffing_ratio_denominator=4,
        max_group_size=10,
        max_supervision_tier="TIER_2",
        volunteer_eligible=True,
        required_screening_level="BASIC",
    )
    room = fx.create_room(api, name="State Sweep Room", capacity=10, buffer_minutes=0)
    session = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-09-16T10:00:00Z",
        ends_at="2026-09-16T11:00:00Z",
        assigned_staff_count=2,
    )
    assignment = fx.assign_volunteer(
        api, volunteer["id"], session["id"], role_type="COMPANION"
    )
    validate_success(
        api.update_volunteer_assignment(
            assignment["id"],
            {"status": "WITHDRAWN", "withdrawn_reason": "Family emergency"},
            coordinator,
        ),
        200,
    )
    resident = fx.create_resident(
        api,
        full_name="Council Cora",
        room_number="702A",
        admission_date="2026-07-31",
    )
    request = fx.council_request(
        api,
        resident["id"],
        requested_domain="CREATIVE",
        vote_count=6,
        note="More pottery",
    )
    validate_success(
        api.review_council_request(
            request["id"],
            {"decision": "DECLINED", "decision_note": "No kiln available"},
            director,
        ),
        200,
    )
    packet = fx.open_packet(api, window_start="2026-08-01", window_end="2026-08-01")

    validate_error(
        api.volunteer_screening(
            applicant["id"],
            {"event_type": "ORIENTATION_COMPLETED", "completed_on": "2026-07-10"},
            coordinator,
        ),
        ApiErrorId.VOLUNTEER_INVALID_STATE.value,
        409,
    )
    validate_error(
        api.update_volunteer_assignment(
            assignment["id"], {"status": "CONFIRMED"}, coordinator
        ),
        ApiErrorId.ASSIGNMENT_INVALID_STATE.value,
        409,
    )
    validate_error(
        api.review_council_request(
            request["id"],
            {"decision": "ADOPTED", "decision_note": "Reconsidering"},
            director,
        ),
        ApiErrorId.COUNCIL_REQUEST_INVALID_STATE.value,
        409,
    )
    validate_error(
        api.attest_survey_packet(packet["id"], {"action": "ATTEST"}, compliance),
        ApiErrorId.PACKET_INVALID_STATE.value,
        409,
    )

    assert_values(
        validate_success(api.get_volunteer(applicant["id"], coordinator), 200),
        status="APPLICANT",
        screening_level="NONE",
    )
    assert_values(
        validate_success(api.get_volunteer_assignment(assignment["id"], coordinator), 200),
        status="WITHDRAWN",
    )
    assert_values(
        validate_success(api.get_council_request(request["id"], director), 200),
        status="DECLINED",
    )
    assert_values(
        validate_success(api.get_survey_packet(packet["id"], compliance), 200),
        status="OPEN",
        attested_by_user_id=None,
    )


def test_documentation_field_pairing_and_completeness_rejected(api, aide):
    """The point-of-care documentation fields are paired to the outcome in both
    directions, and the session cannot be closed while any enrolled resident is
    still undocumented.

    PRD §3.6: "A missing `engagement_level` on an attendance, or an
    `engagement_level` supplied alongside a refusal or an absence, reports
    `ERR_ENGAGEMENT_LEVEL_REQUIRED`."

    Design: Corner/errors/documentation_field_pairing_and_completeness_rejected
    """
    resident_a, _ = fx.assessed_resident(
        api,
        resident_kwargs={
            "full_name": "Pairing A",
            "room_number": "703A",
            "admission_date": "2026-07-31",
        },
        cognitive_level="INTACT",
        functional_mobility="INDEPENDENT",
        interest_domains=["SOCIAL"],
        preferred_group_size="LARGE",
        effective_date="2026-07-31",
    )
    resident_b, _ = fx.assessed_resident(
        api,
        resident_kwargs={
            "full_name": "Pairing B",
            "room_number": "703B",
            "admission_date": "2026-07-31",
        },
        cognitive_level="INTACT",
        functional_mobility="INDEPENDENT",
        interest_domains=["SOCIAL"],
        preferred_group_size="LARGE",
        effective_date="2026-07-31",
    )
    program = fx.create_program(
        api,
        name="Pairing Program",
        domain="SOCIAL",
        staffing_ratio_denominator=4,
        max_group_size=10,
        max_supervision_tier="TIER_3",
    )
    room = fx.create_room(api, name="Pairing Room", capacity=10, buffer_minutes=0)
    session = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-08-03T09:00:00Z",
        ends_at="2026-08-03T10:00:00Z",
        assigned_staff_count=2,
    )
    record_a = fx.enroll(api, session["id"], resident_a["id"])
    record_b = fx.enroll(api, session["id"], resident_b["id"])
    fx.advance_clock(api, "2026-08-03T09:00:00Z")
    fx.start_session(api, session["id"])

    validate_error(
        api.document_participation(record_a["id"], {"outcome": "ATTENDED"}, aide),
        ApiErrorId.ENGAGEMENT_LEVEL_REQUIRED.value,
        422,
    )
    validate_error(
        api.document_participation(
            record_a["id"], {"outcome": "ABSENT", "engagement_level": "ACTIVE"}, aide
        ),
        ApiErrorId.ENGAGEMENT_LEVEL_REQUIRED.value,
        422,
    )
    validate_error(
        api.document_participation(record_a["id"], {"outcome": "REFUSED"}, aide),
        ApiErrorId.REFUSAL_REASON_REQUIRED.value,
        422,
    )

    documented = validate_success(
        api.document_participation(
            record_a["id"], {"outcome": "ATTENDED", "engagement_level": "ACTIVE"}, aide
        ),
        200,
    )
    assert_values(documented, status="ATTENDED", engagement_level="ACTIVE")

    validate_error(
        api.session_status(session["id"], {"action": "CLOSE_DOCUMENTATION"}, aide),
        ApiErrorId.DOCUMENTATION_INCOMPLETE.value,
        409,
    )

    assert_values(
        validate_success(api.get_session(session["id"], aide), 200),
        status="IN_PROGRESS",
        documented_at=None,
    )
    assert_values(
        validate_success(api.get_participation(record_b["id"], aide), 200),
        status="PLANNED",
    )


def test_enrollment_tier_duplicate_and_capacity_rejected(api, aide, director):
    """Three enrollment refusals on one fixture, in the department's own precedence
    order: the tier ceiling first, then the duplicate row, then the fire-code seat
    ceiling that the room rather than the program design sets.

    PRD §3.5: "The resident's `supervision_tier` must be at or below the program's
    `max_supervision_tier` under the `TIER_1` below `TIER_2` below `TIER_3`
    ordering, otherwise `ERR_SUPERVISION_TIER_UNSUPPORTED`."

    Design: Corner/errors/enrollment_tier_duplicate_and_capacity_rejected
    """
    low, _ = fx.assessed_resident(
        api,
        resident_kwargs={
            "full_name": "Low Tier Lou",
            "room_number": "704A",
            "admission_date": "2026-07-31",
        },
        cognitive_level="INTACT",
        functional_mobility="INDEPENDENT",
        interest_domains=["PHYSICAL"],
        preferred_group_size="SMALL",
        effective_date="2026-07-31",
    )
    high, _ = fx.assessed_resident(
        api,
        resident_kwargs={
            "full_name": "High Tier Hank",
            "room_number": "704B",
            "admission_date": "2026-07-31",
        },
        cognitive_level="SEVERE_IMPAIRMENT",
        functional_mobility="INDEPENDENT",
        interest_domains=["PHYSICAL"],
        preferred_group_size="SOLO",
        effective_date="2026-07-31",
    )
    spare, _ = fx.assessed_resident(
        api,
        resident_kwargs={
            "full_name": "Spare Tier Sid",
            "room_number": "704C",
            "admission_date": "2026-07-31",
        },
        cognitive_level="INTACT",
        functional_mobility="INDEPENDENT",
        interest_domains=["PHYSICAL"],
        preferred_group_size="SMALL",
        effective_date="2026-07-31",
    )
    program = fx.create_program(
        api,
        name="Tier Ceiling Walk",
        domain="PHYSICAL",
        staffing_ratio_denominator=4,
        max_group_size=10,
        max_supervision_tier="TIER_1",
    )
    room = fx.create_room(api, name="One Seat Room", capacity=1, buffer_minutes=0)
    session = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-09-17T10:00:00Z",
        ends_at="2026-09-17T11:00:00Z",
        assigned_staff_count=4,
    )
    record = fx.enroll(api, session["id"], low["id"])

    validate_error(
        api.create_enrollment(session["id"], f.enrollment_payload(high["id"]), aide),
        ApiErrorId.SUPERVISION_TIER_UNSUPPORTED.value,
        422,
    )
    validate_error(
        api.create_enrollment(session["id"], f.enrollment_payload(low["id"]), aide),
        ApiErrorId.DUPLICATE_ENROLLMENT.value,
        409,
    )
    validate_error(
        api.create_enrollment(session["id"], f.enrollment_payload(spare["id"]), aide),
        ApiErrorId.SESSION_CAPACITY_EXCEEDED.value,
        409,
    )

    assert_values(
        validate_success(api.get_session(session["id"], director), 200),
        effective_capacity=1,
        enrolled_count=1,
    )
    assert_values(
        validate_success(api.get_participation(record["id"], aide), 200),
        status="PLANNED",
    )
    rows, meta = validate_paginated(
        api.list_session_participation(session["id"], director)
    )
    assert meta["total_count"] == 1, (
        "Only the one admitted enrollment may sit on the roster, "
        f"got total_count {meta['total_count']!r}"
    )
    assert [row["id"] for row in rows] == [record["id"]], (
        f"The roster's only row is {record['id']!r}, got {rows!r}"
    )


def test_plan_targets_and_provenance_rejected(api, therapist):
    """Two independent refusals of a plan draft: a target map with nothing scored
    at all, and a clinically overtaken assessment cited as the plan's justification.

    PRD §3.2: "A map that omits a domain, carries an extra key, holds an
    out-of-range value, or sets all five domains to zero is rejected with
    `ERR_PLAN_TARGETS_INVALID`"

    Design: Corner/errors/plan_targets_and_provenance_rejected
    """
    resident = fx.create_resident(
        api,
        full_name="Provenance Pia",
        room_number="705A",
        admission_date="2026-07-31",
    )
    old_assessment = fx.file_assessment(
        api,
        resident["id"],
        cognitive_level="INTACT",
        functional_mobility="INDEPENDENT",
        interest_domains=["SOCIAL"],
        preferred_group_size="LARGE",
        effective_date="2026-07-20",
    )
    new_assessment = fx.file_assessment(
        api,
        resident["id"],
        cognitive_level="MILD_IMPAIRMENT",
        functional_mobility="ASSIST_1",
        interest_domains=["SOCIAL", "PHYSICAL"],
        preferred_group_size="SMALL",
        effective_date="2026-07-28",
    )
    version = fx.resident_version(api, resident["id"])

    validate_error(
        api.create_activity_plan(
            f.plan_payload(
                resident["id"],
                new_assessment["id"],
                version,
                cycle_start_at="2026-08-01T00:00:00Z",
                targets=f.domain_targets(),
            ),
            therapist,
        ),
        ApiErrorId.PLAN_TARGETS_INVALID.value,
        422,
    )
    validate_error(
        api.create_activity_plan(
            f.plan_payload(
                resident["id"],
                old_assessment["id"],
                version,
                cycle_start_at="2026-08-01T00:00:00Z",
                targets=f.domain_targets(social=2, physical=1),
            ),
            therapist,
        ),
        ApiErrorId.STALE_ASSESSMENT_REFERENCE.value,
        422,
    )

    assert_values(
        validate_success(api.get_assessment(old_assessment["id"], therapist), 200),
        superseded=True,
    )
    assert_values(
        validate_success(api.get_assessment(new_assessment["id"], therapist), 200),
        superseded=False,
    )

    created = validate_success(
        api.create_activity_plan(
            f.plan_payload(
                resident["id"],
                new_assessment["id"],
                version,
                cycle_start_at="2026-08-01T00:00:00Z",
                targets=f.domain_targets(social=2, physical=1),
            ),
            therapist,
        ),
        201,
    )
    assert_values(created, status="DRAFT", target_total_sessions=3)
    assert_values(
        validate_success(api.get_activity_plan(created["id"], therapist), 200),
        status="DRAFT",
        target_total_sessions=3,
        source_assessment_id=new_assessment["id"],
    )


def test_outing_bedbound_rider_and_vehicle_conflict_rejected(api, director):
    """A bedbound resident is refused the manifest outright, and the vehicle's
    turnaround shadow reaches forward past a booked outing's return so a departure
    inside that shadow cannot reserve the same bus.

    PRD §3.8: "a resident whose `functional_mobility` is `BEDBOUND` may never be
    added to a manifest no matter who consents, reported as
    `ERR_RESIDENT_INELIGIBLE_FOR_OUTING`"

    Design: Corner/errors/outing_bedbound_rider_and_vehicle_conflict_rejected
    """
    bedbound, _ = fx.assessed_resident(
        api,
        resident_kwargs={
            "full_name": "Bedbound Bert",
            "room_number": "706A",
            "admission_date": "2026-07-31",
        },
        cognitive_level="MODERATE_IMPAIRMENT",
        functional_mobility="BEDBOUND",
        interest_domains=["SPIRITUAL"],
        preferred_group_size="SOLO",
        effective_date="2026-07-31",
    )
    program = fx.create_program(
        api,
        name="Conflict Outing Program",
        domain="SPIRITUAL",
        staffing_ratio_denominator=4,
        max_group_size=10,
        max_supervision_tier="TIER_3",
    )
    vehicle = fx.create_vehicle(
        api,
        label="Van 21",
        ambulatory_seats=8,
        wheelchair_stations=2,
        turnaround_minutes=30,
    )
    morning = fx.create_outing(
        api,
        program["id"],
        vehicle["id"],
        destination="Morning Chapel",
        departure_at="2026-09-18T09:00:00Z",
        return_at="2026-09-18T11:00:00Z",
        escort_count=1,
    )
    fx.book_transport(api, morning["id"], vehicle_id=vehicle["id"])
    afternoon = fx.create_outing(
        api,
        program["id"],
        vehicle["id"],
        destination="Afternoon Chapel",
        departure_at="2026-09-18T11:15:00Z",
        return_at="2026-09-18T13:00:00Z",
        escort_count=1,
    )
    current_vehicle_version = fx.vehicle_version(api, vehicle["id"])

    validate_error(
        api.create_outing_consent(
            morning["id"],
            f.consent_payload(
                bedbound["id"],
                responsible_party_name="Bert Family",
                responsible_party_relation="GUARDIAN",
            ),
            director,
        ),
        ApiErrorId.RESIDENT_INELIGIBLE_FOR_OUTING.value,
        422,
    )
    validate_error(
        api.book_transport(
            afternoon["id"],
            {"expected_vehicle_version": current_vehicle_version},
            director,
        ),
        ApiErrorId.VEHICLE_TIME_CONFLICT.value,
        409,
    )

    assert_values(
        validate_success(api.get_outing(morning["id"], director), 200),
        logistics_status="TRANSPORT_BOOKED",
        roster_count=0,
        manifest_count=0,
    )
    assert_values(
        validate_success(api.get_outing(afternoon["id"], director), 200),
        logistics_status="PLANNING",
    )
    assert_values(
        validate_success(api.get_vehicle(vehicle["id"], director), 200),
        reserved_ambulatory_seats=1,
        reserved_wheelchair_stations=0,
    )


def test_finalize_with_expired_consent_rejected(api, director):
    """A consent granted but lapsing the day before the bus leaves is not effective,
    so the consent dimension never completes and finalization is refused on the
    consent rule even though the escort roster already satisfies the ratio.

    PRD §3.8: "The `effective` flag is then recomputed: it is true exactly when
    `status` is `GRANTED` **and** either `expires_on` is null or `expires_on` is at
    or after the calendar date of the outing's `departure_at`."

    Design: Corner/errors/finalize_with_expired_consent_rejected
    """
    resident, _ = fx.assessed_resident(
        api,
        resident_kwargs={
            "full_name": "Expiring Consent Cal",
            "room_number": "707A",
            "admission_date": "2026-07-31",
        },
        cognitive_level="INTACT",
        functional_mobility="INDEPENDENT",
        interest_domains=["SOCIAL"],
        preferred_group_size="LARGE",
        effective_date="2026-07-31",
    )
    program = fx.create_program(
        api,
        name="Expiring Consent Program",
        domain="SOCIAL",
        staffing_ratio_denominator=4,
        max_group_size=10,
        max_supervision_tier="TIER_3",
    )
    vehicle = fx.create_vehicle(
        api,
        label="Van 22",
        ambulatory_seats=8,
        wheelchair_stations=2,
        turnaround_minutes=30,
    )
    outing = fx.create_outing(
        api,
        program["id"],
        vehicle["id"],
        destination="Country Drive",
        departure_at="2026-09-19T09:00:00Z",
        return_at="2026-09-19T12:00:00Z",
        escort_count=1,
    )
    consent = fx.add_rider(
        api,
        outing["id"],
        resident["id"],
        responsible_party_name="Cal Family",
        responsible_party_relation="POA",
        expires_on="2026-09-18",
    )
    # A grant re-stores expires_on from the request, so the lapse date must be
    # supplied on the decision itself for the consent to keep it.
    fx.decide_consent(
        api, outing["id"], consent["id"], "GRANTED", expires_on="2026-09-18"
    )
    fx.book_transport(api, outing["id"], vehicle_id=vehicle["id"])

    validate_error(
        api.outing_logistics(outing["id"], {"action": "FINALIZE"}, director),
        ApiErrorId.CONSENT_INCOMPLETE.value,
        409,
    )

    assert_values(
        validate_success(api.get_outing_consent(consent["id"], director), 200),
        status="GRANTED",
        effective=False,
        expires_on="2026-09-18",
    )
    assert_values(
        validate_success(api.get_outing(outing["id"], director), 200),
        consent_status="COLLECTING",
        logistics_status="TRANSPORT_BOOKED",
        escort_count=1,
        required_escorts=1,
    )


def test_packet_attestation_without_remediation_note_rejected(
    api, compliance, compliance_b
):
    """A compiled packet carrying a deficiency flag cannot be signed off without a
    remediation narrative, and the identical call succeeds once the narrative is
    supplied by an officer other than the compiler.

    PRD §3.9: "it requires a non-empty `remediation_note` whenever
    `deficiency_flags` is non-empty, reporting `ERR_REMEDIATION_NOTE_REQUIRED`
    otherwise"

    Design: Corner/errors/packet_attestation_without_remediation_note_rejected
    """
    packet = fx.compiled_packet(
        api, headers=compliance, window_start="2026-08-01", window_end="2026-08-01"
    )

    validate_error(
        api.attest_survey_packet(packet["id"], {"action": "ATTEST"}, compliance_b),
        ApiErrorId.REMEDIATION_NOTE_REQUIRED.value,
        422,
    )

    refused = validate_success(api.get_survey_packet(packet["id"], compliance), 200)
    assert_values(refused, status="COMPILED", attested_by_user_id=None)
    assert refused["deficiency_flags"] == ["F248_INSUFFICIENT_FREQUENCY"], (
        "An empty surveyed cohort scores 0.0, which is strictly below the 50.0 "
        "frequency threshold and raises exactly that one flag, got "
        f"{refused['deficiency_flags']!r}"
    )
    assert refused["provision_score"] == 0.0, (
        "The single flag's deduction is clamped at 0.0 below, "
        f"got {refused['provision_score']!r}"
    )

    attested = validate_success(
        api.attest_survey_packet(
            packet["id"],
            {
                "action": "ATTEST",
                "remediation_note": (
                    "Census empty during window; calendar relaunch scheduled"
                ),
            },
            compliance_b,
        ),
        200,
    )
    assert_values(
        attested,
        status="ATTESTED",
        attested_by_user_id=COMPLIANCE_B_USER_ID,
        remediation_note="Census empty during window; calendar relaunch scheduled",
    )
    assert_values(
        validate_success(api.get_survey_packet(packet["id"], compliance), 200),
        status="ATTESTED",
        attested_by_user_id=COMPLIANCE_B_USER_ID,
    )


def test_participation_record_unknown_id_not_found(api, aide):
    """A participation record only ever exists as the product of an enrollment, so
    an unused record identifier is a lookup failure on both the read and the
    documentation route, ahead of every documentation-pairing rule.

    PRD §2.9: "a participation record identifier yields
    `ERR_PARTICIPATION_RECORD_NOT_FOUND`"

    Design: Corner/errors/participation_record_unknown_id_not_found
    """
    validate_error(
        api.get_participation(ABSENT_UUID, aide),
        ApiErrorId.PARTICIPATION_RECORD_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.document_participation(
            ABSENT_UUID, {"outcome": "ATTENDED", "engagement_level": "ACTIVE"}, aide
        ),
        ApiErrorId.PARTICIPATION_RECORD_NOT_FOUND.value,
        404,
    )

    rows, meta = validate_paginated(api.list_participation(aide))
    assert meta["total_count"] == 0, (
        "No enrollment has ever been made, so the flat participation collection "
        f"is empty, got total_count {meta['total_count']!r}"
    )
    assert rows == [], f"Expected no participation rows at all, got {rows!r}"


def test_volunteer_clearance_screening_and_overlap_rejected_clearance_expired(
    api, coordinator
):
    """A volunteer who has never been screened at all cannot be rostered onto a
    session, and the refusal leaves them with no committed hours.

    PRD §3.7: "the volunteer's `status` must be exactly `CLEARED`, so `APPLICANT`,
    `SCREENING`, `EXPIRED`, `SUSPENDED`, and `TERMINATED` are all refused with
    `ERR_VOLUNTEER_CLEARANCE_EXPIRED`"

    Design: Corner/errors/volunteer_clearance_screening_and_overlap_rejected
    """
    fx.advance_clock(api, "2026-08-03T00:00:00Z")
    program = fx.create_program(
        api,
        name="Basic Bar Program",
        domain="CREATIVE",
        staffing_ratio_denominator=4,
        max_group_size=10,
        max_supervision_tier="TIER_2",
        volunteer_eligible=True,
        required_screening_level="BASIC",
    )
    room = fx.create_room(api, name="Overlap Room Two", capacity=10, buffer_minutes=0)
    session = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-08-03T11:00:00Z",
        ends_at="2026-08-03T13:00:00Z",
        assigned_staff_count=2,
    )
    applicant = fx.create_volunteer(
        api, full_name="Not Cleared Nick", volunteer_type="ADULT_COMMUNITY"
    )

    validate_error(
        api.create_volunteer_assignment(
            f.assignment_payload(
                applicant["id"], session["id"], role_type="COMPANION"
            ),
            coordinator,
        ),
        ApiErrorId.VOLUNTEER_CLEARANCE_EXPIRED.value,
        409,
    )

    stored = validate_success(api.get_volunteer(applicant["id"], coordinator), 200)
    assert_values(stored, status="APPLICANT", screening_level="NONE")
    assert stored["scheduled_hours_week"] == 0.0, (
        "A refused assignment commits no forward-looking hours, "
        f"got {stored['scheduled_hours_week']!r}"
    )

    rows, meta = validate_paginated(
        api.list_volunteer_assignments(coordinator, {"volunteer_id": applicant["id"]})
    )
    assert meta["total_count"] == 0, (
        "The unscreened volunteer holds no assignment at all, "
        f"got total_count {meta['total_count']!r}"
    )
    assert rows == [], f"Expected no assignment rows, got {rows!r}"


def test_volunteer_clearance_screening_and_overlap_rejected_time_conflict(
    api, coordinator
):
    """A fully cleared volunteer already promised to a morning session cannot also be
    promised to a session that starts before the first one ends, and the refusal
    leaves the earlier promise untouched.

    PRD §3.7: "the target session's half-open interval must not intersect the
    interval of any other session on which the same volunteer already holds a
    `PROPOSED` or `CONFIRMED` assignment, because a volunteer is never
    double-booked, and a conflict reports `ERR_VOLUNTEER_TIME_CONFLICT`"

    Design: Corner/errors/volunteer_clearance_screening_and_overlap_rejected
    """
    fx.advance_clock(api, "2026-08-03T00:00:00Z")
    program = fx.create_program(
        api,
        name="Overlap Bar Program",
        domain="CREATIVE",
        staffing_ratio_denominator=4,
        max_group_size=10,
        max_supervision_tier="TIER_2",
        volunteer_eligible=True,
        required_screening_level="BASIC",
    )
    room_one = fx.create_room(
        api, name="Overlap Room One", capacity=10, buffer_minutes=0
    )
    room_two = fx.create_room(
        api, name="Overlap Room Two", capacity=10, buffer_minutes=0
    )
    morning = fx.create_session(
        api,
        program["id"],
        room_one["id"],
        starts_at="2026-08-03T10:00:00Z",
        ends_at="2026-08-03T12:00:00Z",
        assigned_staff_count=2,
    )
    midday = fx.create_session(
        api,
        program["id"],
        room_two["id"],
        starts_at="2026-08-03T11:00:00Z",
        ends_at="2026-08-03T13:00:00Z",
        assigned_staff_count=2,
    )
    volunteer = fx.cleared_volunteer(
        api,
        cleared_on="2026-07-06",
        completed_on="2026-07-10",
        full_name="Fully Cleared Fred",
        volunteer_type="ADULT_COMMUNITY",
    )
    first = fx.assign_volunteer(
        api, volunteer["id"], morning["id"], role_type="GROUP_ASSISTANT"
    )

    validate_error(
        api.create_volunteer_assignment(
            f.assignment_payload(
                volunteer["id"], midday["id"], role_type="COMPANION"
            ),
            coordinator,
        ),
        ApiErrorId.VOLUNTEER_TIME_CONFLICT.value,
        409,
    )

    kept = validate_success(
        api.get_volunteer_assignment(first["id"], coordinator), 200
    )
    assert_values(kept, status="PROPOSED", session_id=morning["id"])
    assert kept["hours"] == 2.0, (
        "The surviving assignment still spans the two-hour morning session, "
        f"got {kept['hours']!r}"
    )

    stored = validate_success(api.get_volunteer(volunteer["id"], coordinator), 200)
    assert_values(stored, status="CLEARED", screening_level="FULL")
    assert stored["scheduled_hours_week"] == 2.0, (
        "Only the morning session counts toward the volunteer's week, "
        f"got {stored['scheduled_hours_week']!r}"
    )

    rows, meta = validate_paginated(
        api.list_volunteer_assignments(coordinator, {"volunteer_id": volunteer["id"]})
    )
    assert meta["total_count"] == 1, (
        "The double-booking attempt created no second assignment, "
        f"got total_count {meta['total_count']!r}"
    )
    assert rows[0]["id"] == first["id"], (
        f"Expected only the morning assignment to survive, got {rows!r}"
    )
