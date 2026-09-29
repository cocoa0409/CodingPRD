"""Role boundaries: exclusive surfaces, entity-backed ownership and segregation of duties.

Every test drives real HTTP against a live server whose database is empty and whose
logical clock reads 2026-08-01T00:00:00Z, and builds all of its own state through the
declared endpoints.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    COMPLIANCE_B_USER_ID,
    COMPLIANCE_USER_ID,
    THERAPIST_USER_ID,
    make_council_rep_headers,
    make_volunteer_headers,
)


def test_director_only_census_and_asset_setup_unauthorized(api, director, therapist, aide, coordinator):
    """The department-head surface is closed to every other role.

    An aide may not admit a resident to the activities census nor create a catalogue
    program, a therapist may not create an activity room, and a volunteer coordinator
    may not add a vehicle to the fleet: each attempt is a 403 that writes nothing, so
    the census the director then reads is still empty.

    PRD: "An `ActivityDirector` runs the department: census admission and census
    updates, catalog and fleet setup, calendar construction, outing logistics, council
    dispositions, and survey packet compilation."

    Design: Corner/rbac/director_only_census_and_asset_setup_unauthorized
    """
    admit = api.create_resident(
        f.resident_payload(
            full_name="Aide Admitted Amy", room_number="708A", admission_date="2026-07-31"
        ),
        aide,
    )
    validate_error(admit, ApiErrorId.UNAUTHORIZED.value, 403)

    program = api.create_program(
        f.program_payload(
            name="Aide Program",
            domain="SOCIAL",
            staffing_ratio_denominator=4,
            max_group_size=10,
            max_supervision_tier="TIER_2",
        ),
        aide,
    )
    validate_error(program, ApiErrorId.UNAUTHORIZED.value, 403)

    room = api.create_room(
        f.room_payload(name="Therapist Room", capacity=8, buffer_minutes=0), therapist
    )
    validate_error(room, ApiErrorId.UNAUTHORIZED.value, 403)

    vehicle = api.create_vehicle(
        f.vehicle_payload(label="Coordinator Van", ambulatory_seats=6, wheelchair_stations=2),
        coordinator,
    )
    validate_error(vehicle, ApiErrorId.UNAUTHORIZED.value, 403)

    _rows, meta = validate_paginated(api.list_residents(director))
    assert meta["total_count"] == 0, (
        f"The refused admission must have created nothing, saw {meta['total_count']} residents"
    )


def test_therapist_only_clinical_authorship_assessment_unauthorized(api, director, therapist):
    """Filing a resident assessment is licensure-bound to the recreation therapist.

    The director who admitted the resident may not file the clinical judgement on that
    resident, and the refused attempt leaves the assessment history untouched.

    PRD: "This is the only role that may file a resident assessment, the only role that
    may draft an activity plan, and the only role that may clear a therapist-review
    enrollment gate."

    Design: Corner/rbac/therapist_only_clinical_authorship_unauthorized
    """
    resident = fx.create_resident(api, full_name="Gated Gwen", room_number="709A")
    fx.file_assessment(api, resident["id"], effective_date="2026-07-31")

    refused = api.create_assessment(
        resident["id"],
        f.assessment_payload(
            cognitive_level="MILD_IMPAIRMENT",
            functional_mobility="ASSIST_1",
            interest_domains=["PHYSICAL"],
            preferred_group_size="SMALL",
            effective_date="2026-08-01",
        ),
        director,
    )
    validate_error(refused, ApiErrorId.UNAUTHORIZED.value, 403)

    _rows, meta = validate_paginated(
        api.list_resident_assessments(resident["id"], therapist)
    )
    assert meta["total_count"] == 1, (
        "The refused filing must not have appended an assessment, "
        f"saw {meta['total_count']} rows"
    )


def test_therapist_only_clinical_authorship_plan_create_unauthorized(api, director, therapist):
    """Drafting an activity plan is licensure-bound, and the role check outranks the
    optimistic-concurrency check.

    The director submits a well-formed draft that echoes a resident version which the
    therapist's own authoring pass has already made stale; the answer is still the
    authorization refusal and never the stale-version refusal, because the role rule is
    evaluated first.

    PRD: "This authorization check deliberately outranks every existence check in the
    system"

    Design: Corner/rbac/therapist_only_clinical_authorship_unauthorized
    """
    resident = fx.create_resident(api, full_name="Gated Gwen", room_number="709A")
    assessment = fx.file_assessment(api, resident["id"], effective_date="2026-07-31")
    stale_version = fx.resident_version(api, resident["id"])

    plan = fx.draft_plan(
        api, resident["id"], assessment["id"], targets=f.domain_targets(social=2)
    )
    get_success_data(
        api.transition_activity_plan(plan["id"], {"action": "ACTIVATE"}, therapist)
    )
    get_success_data(
        api.transition_activity_plan(
            plan["id"], {"action": "REVISE", "review_reason": "THERAPIST_REQUEST"}, therapist
        )
    )
    assert fx.resident_version(api, resident["id"]) != stale_version, (
        "Setup must leave the director's echoed resident version stale"
    )

    refused = api.create_activity_plan(
        f.plan_payload(
            resident["id"],
            assessment["id"],
            stale_version,
            targets=f.domain_targets(social=1),
        ),
        director,
    )
    validate_error(refused, ApiErrorId.UNAUTHORIZED.value, 403)

    _rows, meta = validate_paginated(
        api.list_activity_plans(therapist, {"resident_id": resident["id"]})
    )
    assert meta["total_count"] == 1, (
        f"Only the therapist's plan may exist, saw {meta['total_count']} plans"
    )


def test_therapist_only_clinical_authorship_gate_rule_reachable(api, therapist_b, aide):
    """Once the role check passes, the review gate is what refuses a reason-less enrollment.

    A second therapist enrolling a resident whose live plan is under revision, and
    supplying no override reason at all, reaches the review gate itself and is refused
    with the gate error rather than with an authorization error; the session roster stays
    empty and the resident stays gated.

    PRD: "anything else — an aide trying, a therapist trying without a reason, an empty
    reason string — is refused with `ERR_ENROLLMENT_GATED`"

    Design: Corner/rbac/therapist_only_clinical_authorship_unauthorized
    """
    resident = fx.create_resident(api, full_name="Gated Gwen", room_number="709A")
    assessment = fx.file_assessment(api, resident["id"], effective_date="2026-07-31")
    plan = fx.active_plan(
        api, resident["id"], assessment["id"], targets=f.domain_targets(social=2)
    )
    get_success_data(
        api.transition_activity_plan(
            plan["id"], {"action": "REVISE", "review_reason": "THERAPIST_REQUEST"}, therapist_b
        )
    )
    assert fx.read_resident(api, resident["id"])["enrollment_gate"] == "THERAPIST_REVIEW"

    program, room = fx.calendar(
        api,
        program_kwargs={"name": "Gate Probe Program", "max_supervision_tier": "TIER_3"},
        room_kwargs={"name": "Gate Probe Room", "capacity": 10, "buffer_minutes": 0},
    )
    session = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-09-21T10:00:00Z",
        ends_at="2026-09-21T11:00:00Z",
        assigned_staff_count=4,
    )

    refused = api.create_enrollment(
        session["id"], f.enrollment_payload(resident["id"]), therapist_b
    )
    validate_error(refused, ApiErrorId.ENROLLMENT_GATED.value, 409)

    assert fx.read_session(api, session["id"])["enrolled_count"] == 0
    assert fx.read_resident(api, resident["id"])["enrollment_gate"] == "THERAPIST_REVIEW"


def test_volunteer_coordinator_owns_volunteer_surface_unauthorized(api, director, coordinator):
    """Registration, the screening ledger and assignment creation belong to the coordinator.

    The activity director — who otherwise runs the department — may neither register a
    volunteer, nor post a suspension onto a cleared volunteer's screening ledger, nor
    assign a volunteer to a session; the cleared volunteer is still CLEARED afterwards.
    Reading that volunteer is a shared operation and does succeed for the director.

    PRD: "A `VolunteerCoordinator` owns the entire volunteer surface: registration, the
    screening lifecycle, and assignment of volunteers to sessions."

    Design: Corner/rbac/volunteer_coordinator_owns_volunteer_surface_unauthorized
    """
    volunteer = fx.cleared_volunteer(
        api, full_name="Surface Sam", volunteer_type="ADULT_COMMUNITY"
    )
    program, room = fx.calendar(
        api,
        program_kwargs={
            "name": "Coordinator Surface Program",
            "domain": "CREATIVE",
            "max_supervision_tier": "TIER_2",
            "volunteer_eligible": True,
        },
        room_kwargs={"name": "Coordinator Surface Room", "capacity": 10},
    )
    session = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-09-22T10:00:00Z",
        ends_at="2026-09-22T11:00:00Z",
        assigned_staff_count=2,
    )

    register = api.create_volunteer(
        f.volunteer_payload(full_name="Director Registered Rita", volunteer_type="FAMILY_MEMBER"),
        director,
    )
    validate_error(register, ApiErrorId.UNAUTHORIZED.value, 403)

    screening = api.volunteer_screening(
        volunteer["id"], {"event_type": "SUSPEND"}, director
    )
    validate_error(screening, ApiErrorId.UNAUTHORIZED.value, 403)

    assign = api.create_volunteer_assignment(
        f.assignment_payload(volunteer["id"], session["id"], role_type="COMPANION"), director
    )
    validate_error(assign, ApiErrorId.UNAUTHORIZED.value, 403)

    read_by_director = validate_success(api.get_volunteer(volunteer["id"], director), 200)
    assert read_by_director["status"] == "CLEARED", (
        f"The refused SUSPEND must leave the ledger untouched, saw {read_by_director['status']}"
    )


def test_attestation_by_compiling_user_returns_4xx(api, compliance, compliance_b):
    """The officer who compiled a survey packet may never attest that same packet.

    Segregation is per-user inside one role: compliance-A compiles the packet, is refused
    with a 403 when attesting its own compilation even with a perfectly formed body and a
    remediation note, and compliance-B then attests the very same packet successfully.

    PRD: "on the attest action, the acting `X-User-ID` must differ from the packet's
    stored `compiled_by_user_id`"

    Design: Corner/rbac/attestation_by_compiling_user_returns_4XX
    """
    packet = fx.open_packet(
        api, headers=compliance, window_start="2026-08-01", window_end="2026-08-01"
    )
    compiled = validate_success(
        api.compile_survey_packet(packet["id"], {}, compliance), 200
    )
    assert compiled["compiled_by_user_id"] == COMPLIANCE_USER_ID
    assert compiled["status"] == "COMPILED"

    self_attest = api.attest_survey_packet(
        packet["id"],
        {"action": "ATTEST", "remediation_note": "Self-attestation attempt"},
        compliance,
    )
    validate_error(self_attest, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)
    assert fx.read_packet(api, packet["id"], compliance)["status"] == "COMPILED", (
        "The refused self-attestation must leave the packet COMPILED"
    )

    attested = validate_success(
        api.attest_survey_packet(
            packet["id"],
            {"action": "ATTEST", "remediation_note": "Reviewed by second officer"},
            compliance_b,
        ),
        200,
    )
    assert attested["status"] == "ATTESTED"
    assert attested["attested_by_user_id"] == COMPLIANCE_B_USER_ID
    assert attested["compiled_by_user_id"] == COMPLIANCE_USER_ID


def test_gate_override_by_own_assessor_returns_4xx(api, therapist, therapist_b):
    """A therapist may not clear a review gate that rests on their own clinical judgement.

    therapist-A assesses the resident and authors the plan that is then revised, so the
    gate rests on therapist-A's assessment: therapist-A's own override is a 403, while
    peer therapist-B's override enrols the resident. The override is per-enrollment and
    never clears the resident's gate.

    PRD: "the acting `X-User-ID` must differ from the `assessed_by_user_id` recorded on
    the assessment that the resident's live activity plan cites as its
    `source_assessment_id`"

    Design: Corner/rbac/gate_override_by_own_assessor_returns_4XX
    """
    resident = fx.create_resident(api, full_name="Peer Review Pearl", room_number="710A")
    assessment = fx.file_assessment(
        api,
        resident["id"],
        headers=therapist,
        cognitive_level="MODERATE_IMPAIRMENT",
        functional_mobility="ASSIST_1",
        interest_domains=["COGNITIVE"],
        effective_date="2026-07-31",
    )
    assert assessment["assessed_by_user_id"] == THERAPIST_USER_ID
    plan = fx.active_plan(
        api, resident["id"], assessment["id"], targets=f.domain_targets(cognitive=2)
    )
    get_success_data(
        api.transition_activity_plan(
            plan["id"], {"action": "REVISE", "review_reason": "THERAPIST_REQUEST"}, therapist
        )
    )

    program, room = fx.calendar(
        api,
        program_kwargs={
            "name": "Peer Review Program",
            "domain": "COGNITIVE",
            "max_supervision_tier": "TIER_3",
        },
        room_kwargs={"name": "Peer Review Room", "capacity": 10},
    )
    session = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-09-23T10:00:00Z",
        ends_at="2026-09-23T11:00:00Z",
        assigned_staff_count=4,
    )

    self_override = api.create_enrollment(
        session["id"],
        f.enrollment_payload(
            resident["id"], gate_override_reason="I stand by my own assessment"
        ),
        therapist,
    )
    validate_error(self_override, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)

    peer_override = validate_success(
        api.create_enrollment(
            session["id"],
            f.enrollment_payload(
                resident["id"],
                gate_override_reason="Peer review completed; cleared for group work",
            ),
            therapist_b,
        ),
        201,
    )
    assert peer_override["status"] == "PLANNED"
    assert fx.read_session(api, session["id"])["enrolled_count"] == 1
    assert fx.read_resident(api, resident["id"])["enrollment_gate"] == "THERAPIST_REVIEW", (
        "An override is per-enrollment and never clears the resident's gate"
    )


def test_volunteer_role_foreign_assignment_read_unauthorized(api, coordinator):
    """A volunteer reading somebody else's assignment row gets 403, never 404.

    Two cleared volunteers are proposed onto the same session; volunteer A reads
    volunteer B's assignment and the ownership mismatch is an authorization failure that
    leaks nothing about the row's existence.

    PRD: "An ownership mismatch is an authorization failure evaluated inside the very
    same check as the role list: it returns `ERR_UNAUTHORIZED` with HTTP 403, and never a
    404 and never a 422."

    Design: Corner/rbac/volunteer_role_reaches_only_their_own_assignments_unauthorized
    """
    volunteer_a = fx.cleared_volunteer(api, full_name="Scoped Sandra")
    volunteer_b = fx.cleared_volunteer(api, full_name="Scoped Steven")
    program, room = fx.calendar(
        api,
        program_kwargs={
            "name": "Scoped Access Program",
            "domain": "CREATIVE",
            "max_supervision_tier": "TIER_2",
            "volunteer_eligible": True,
        },
        room_kwargs={"name": "Scoped Access Room", "capacity": 10},
    )
    session = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-09-24T10:00:00Z",
        ends_at="2026-09-24T12:00:00Z",
        assigned_staff_count=2,
    )
    assignment_b = fx.assign_volunteer(
        api, volunteer_b["id"], session["id"], role_type="GROUP_ASSISTANT"
    )

    foreign_read = api.get_volunteer_assignment(
        assignment_b["id"], make_volunteer_headers(volunteer_a["id"])
    )
    validate_error(foreign_read, ApiErrorId.UNAUTHORIZED.value, 403)

    assert fx.read_assignment(api, assignment_b["id"], coordinator)["status"] == "PROPOSED"


def test_volunteer_role_assignment_patch_scoped_to_own_row_and_withdrawal(api, coordinator):
    """A volunteer may only touch their own assignment and may only ever withdraw it.

    Volunteer A cannot withdraw volunteer B's assignment, cannot confirm even their own
    assignment, and can withdraw their own row with a supplied reason; volunteer B's row
    is untouched by any refusal and the withdrawal leaves no forward commitment.

    PRD: "A caller acting in the `Volunteer` role may only touch an assignment whose
    `volunteer_id` equals their own `X-User-ID`, and may only ever send `WITHDRAWN`."

    Design: Corner/rbac/volunteer_role_reaches_only_their_own_assignments_unauthorized
    """
    volunteer_a = fx.cleared_volunteer(api, full_name="Scoped Sandra")
    volunteer_b = fx.cleared_volunteer(api, full_name="Scoped Steven")
    program, room = fx.calendar(
        api,
        program_kwargs={
            "name": "Scoped Access Program",
            "domain": "CREATIVE",
            "max_supervision_tier": "TIER_2",
            "volunteer_eligible": True,
        },
        room_kwargs={"name": "Scoped Access Room", "capacity": 10},
    )
    session = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-09-24T10:00:00Z",
        ends_at="2026-09-24T12:00:00Z",
        assigned_staff_count=2,
    )
    assignment_a = fx.assign_volunteer(
        api, volunteer_a["id"], session["id"], role_type="PROGRAM_LEAD"
    )
    assignment_b = fx.assign_volunteer(
        api, volunteer_b["id"], session["id"], role_type="GROUP_ASSISTANT"
    )
    headers_a = make_volunteer_headers(volunteer_a["id"])

    foreign_write = api.update_volunteer_assignment(
        assignment_b["id"],
        {"status": "WITHDRAWN", "withdrawn_reason": "Not my shift to give up"},
        headers_a,
    )
    validate_error(foreign_write, ApiErrorId.UNAUTHORIZED.value, 403)

    self_confirm = api.update_volunteer_assignment(
        assignment_a["id"], {"status": "CONFIRMED"}, headers_a
    )
    validate_error(self_confirm, ApiErrorId.UNAUTHORIZED.value, 403)

    withdrawn = validate_success(
        api.update_volunteer_assignment(
            assignment_a["id"],
            {"status": "WITHDRAWN", "withdrawn_reason": "Family emergency"},
            headers_a,
        ),
        200,
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["withdrawn_reason"] == "Family emergency"
    assert fx.read_assignment(api, assignment_b["id"], coordinator)["status"] == "PROPOSED", (
        "Volunteer B's row must be untouched by any of the refusals"
    )
    assert fx.read_volunteer(api, volunteer_a["id"], coordinator)["scheduled_hours_week"] == 0.0


def test_council_representative_reaches_only_their_own_requests_unauthorized(api, director):
    """A council representative is bound to their own resident row on both write and read.

    Representative A may not file a request naming another resident, representative B may
    not read A's request, the representative may not disposition their own request, and
    the director may not file one at all: four 403s that write nothing, while A's own read
    of A's own request succeeds.

    PRD: "a representative may only file or read council requests they own"

    Design: Corner/rbac/council_representative_reaches_only_their_own_requests_unauthorized
    """
    resident_a = fx.create_resident(api, full_name="Council Chair Cora", room_number="711A")
    resident_b = fx.create_resident(api, full_name="Bystander Bram", room_number="711B")
    request_a = fx.council_request(
        api, resident_a["id"], requested_domain="SPIRITUAL", vote_count=6, note="More Sunday services"
    )
    headers_a = make_council_rep_headers(resident_a["id"])
    headers_b = make_council_rep_headers(resident_b["id"])

    foreign_file = api.create_council_request(
        f.council_request_payload(
            resident_b["id"],
            requested_domain="CREATIVE",
            vote_count=6,
            note="Filed on somebody else's behalf",
        ),
        headers_a,
    )
    validate_error(foreign_file, ApiErrorId.UNAUTHORIZED.value, 403)

    foreign_read = api.get_council_request(request_a["id"], headers_b)
    validate_error(foreign_read, ApiErrorId.UNAUTHORIZED.value, 403)

    self_review = api.review_council_request(
        request_a["id"], {"decision": "ADOPTED", "decision_note": "Self-approved"}, headers_a
    )
    validate_error(self_review, ApiErrorId.UNAUTHORIZED.value, 403)

    director_file = api.create_council_request(
        f.council_request_payload(
            resident_b["id"],
            requested_domain="CREATIVE",
            vote_count=6,
            note="Filed by the right resident",
        ),
        director,
    )
    validate_error(director_file, ApiErrorId.UNAUTHORIZED.value, 403)

    own_read = validate_success(api.get_council_request(request_a["id"], headers_a), 200)
    assert own_read["status"] == "SUBMITTED"

    _rows, meta = validate_paginated(api.list_council_requests(director))
    assert meta["total_count"] == 1, (
        f"All four refusals must have written nothing, saw {meta['total_count']} requests"
    )
