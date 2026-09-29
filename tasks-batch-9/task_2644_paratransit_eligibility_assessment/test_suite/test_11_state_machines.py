"""Declared edges, initial states and terminal lockdowns of the state machines."""
from test_helpers import factories, validate_error, validate_paginated, validate_success
from test_helpers.api_errors import (
    ERR_APPEAL_STATE_INVALID,
    ERR_DETERMINATION_NOT_APPEALABLE,
    ERR_INVALID_ASSESSMENT_STATE,
    ERR_LOCAL_ELIGIBILITY_EXISTS,
    ERR_PROCEEDING_STATE_INVALID,
    ERR_VERIFICATION_PENDING,
    ERR_VISITOR_RECORD_INACTIVE,
)
from test_helpers.assertions import assert_slot_mirror, assert_vehicle_counters
from test_helpers.fixtures import (
    auto_referral,
    create_applicant,
    create_slot,
    create_vehicle,
    drafted_determination,
    heard_appeal_on_paper,
    ingest_trip_events,
    issued_determination,
    scheduled_assessment,
    set_clock,
    submitted_application,
    visitor_record,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    CLERK_HEADERS,
    CONDUCT_OFFICER_2_HEADERS,
    CONDUCT_OFFICER_HEADERS,
    EVALUATOR_HEADERS,
    REVIEWER_2_USER_ID,
    SPECIALIST_HEADERS,
    TRAINER_HEADERS,
    make_applicant_headers,
)


def test_a_no_show_reopens_the_slot_and_closes_the_reserved_booking(api):
    """One attendance call fires the widest cascade in the assessment stage.

    "Marking a rider `NO_SHOW` likewise requires that the current instant is at
    or after the slot's `starts_at`, and it triggers the widest cascade in this
    part of the system. The assessment's attendance dimension becomes `NO_SHOW`.
    The slot's `booked_count` decreases by one, and a slot that was `FULL`
    returns to `OPEN` as soon as its `booked_count` falls below its `capacity`.
    Every booking on this assessment still in `RESERVED` moves
    `RESERVED → NO_SHOW_CLOSED`, each releasing the vehicle counter it consumed.
    And the parent packet regresses from `ASSESSMENT_SCHEDULED` back to
    `ASSESSMENT_REQUIRED` so a replacement assessment can be booked"

    "The difference is that `applicant_delay_days` is left alone: agency fault is
    never charged to the rider, whereas a rider's own no-show is charged when the
    replacement is booked."

    Design: Corner/state_machines/no_show_attendance_reopens_the_slot_and_closes_the_reserved_booking
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Kwame Asante",
        date_of_birth="1955-03-03",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="POWER_WHEELCHAIR",
    )
    context = scheduled_assessment(
        api,
        applicant=rider,
        slot=create_slot(api, capacity=1, site_is_wheelchair_accessible=True),
        booking_overrides={"requires_wheelchair_position": True},
        functional_answers=factories.functional_answers(max_walk_distance_meters=60),
        claimed_conditions=["spinal cord injury"],
    )
    slot_id = context["slot"]["id"]
    assessment_id = context["assessment"]["id"]

    slot = validate_success(api.get_assessment_slot(slot_id, ADMIN_HEADERS))
    assert_slot_mirror(slot, booked_count=1, status="FULL")

    vehicle = create_vehicle(
        api, vehicle_number="V-7001", wheelchair_positions=2, ambulatory_seats=4
    )
    booking = validate_success(
        api.create_transportation_booking(
            factories.transportation_booking_payload(
                assessment_id,
                vehicle["id"],
                pickup_window_start="2026-08-05T08:00:00Z",
                pickup_window_end="2026-08-05T09:00:00Z",
                requires_wheelchair_position=True,
            ),
            CLERK_HEADERS,
        ),
        201,
    )
    assert booking["status"] == "RESERVED"
    assert_vehicle_counters(
        validate_success(api.get_vehicle(vehicle["id"], ADMIN_HEADERS)),
        wheelchair=1,
        ambulatory=0,
    )

    set_clock(api, "2026-08-05T09:30:00Z")
    assessment = validate_success(
        api.record_attendance(
            assessment_id, factories.attendance_payload("NO_SHOW"), EVALUATOR_HEADERS
        )
    )
    assert assessment["attendance_status"] == "NO_SHOW"
    assert assessment["attendance_recorded_at"] == "2026-08-05T09:30:00.000Z"
    assert assessment["scoring_status"] == "NOT_STARTED"

    assert_slot_mirror(
        validate_success(api.get_assessment_slot(slot_id, ADMIN_HEADERS)),
        booked_count=0,
        status="OPEN",
    )
    reread = validate_success(
        api.get_transportation_booking(booking["id"], CLERK_HEADERS)
    )
    assert reread["status"] == "NO_SHOW_CLOSED"
    assert_vehicle_counters(
        validate_success(api.get_vehicle(vehicle["id"], ADMIN_HEADERS)),
        wheelchair=0,
        ambulatory=0,
    )

    application = validate_success(
        api.get_application(context["application"]["id"], CLERK_HEADERS)
    )
    assert application["status"] == "ASSESSMENT_REQUIRED"
    assert application["applicant_delay_days"] == 0


def test_an_insufficient_answer_loops_the_packet_and_blocks_a_third_request(api):
    """The only cyclic edge on the packet costs statutory days and buys nothing.

    "The verification moves `REQUESTED → INSUFFICIENT`, `received_at` is stamped
    from the clock, and `wait_days` is computed by the same whole-day rule and
    added to the packet's `verification_excluded_days` exactly as on the accepted
    branch. The packet's `attests_permanent` is left untouched. Crucially, the
    packet stays in `PENDING_VERIFICATION` — this is a self-loop, not a
    regression — and `completeness_established_at` is not disturbed"

    "Only one request may be outstanding at a time: if any verification of this
    packet is still in `REQUESTED`, the new request is refused with
    `ERR_VERIFICATION_PENDING` (409)."

    Design: Corner/state_machines/insufficient_verification_holds_the_application_in_pending_verification
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Liora Stein",
        date_of_birth="1967-06-15",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="NONE",
    )
    context = submitted_application(
        api,
        applicant=rider,
        functional_answers=factories.functional_answers(
            can_board_bus_steps=True,
            can_navigate_unfamiliar_route=False,
            max_walk_distance_meters=350,
            uses_mobility_aid_outdoors=False,
            has_cognitive_impairment=True,
        ),
    )
    application_id = context["application"]["id"]
    first = validate_success(
        api.request_verification(
            application_id,
            factories.verification_request_payload(
                provider_name="Dr. O Kessler",
                provider_type="PSYCHOLOGIST",
                provider_license_number="PSY-2210",
            ),
            CLERK_HEADERS,
        ),
        201,
    )

    set_clock(api, "2026-08-04T00:00:00Z")
    answered = validate_success(
        api.receive_verification(
            application_id,
            first["id"],
            factories.verification_insufficient_payload(
                insufficiency_reason="no functional narrative attached"
            ),
            CLERK_HEADERS,
        )
    )
    assert answered["status"] == "INSUFFICIENT"
    assert answered["received_at"] == "2026-08-04T00:00:00.000Z"
    assert answered["wait_days"] == 3

    application = validate_success(api.get_application(application_id, CLERK_HEADERS))
    assert application["status"] == "PENDING_VERIFICATION"
    assert application["verification_excluded_days"] == 3
    assert application["attests_permanent"] is None
    assert application["completeness_established_at"] == "2026-08-01T00:00:00.000Z"

    replacement = validate_success(
        api.request_verification(
            application_id,
            factories.verification_request_payload(
                provider_name="Dr. P Nkemdirim",
                provider_type="PSYCHOLOGIST",
                provider_license_number="PSY-3310",
            ),
            CLERK_HEADERS,
        ),
        201,
    )
    assert replacement["status"] == "REQUESTED"
    assert replacement["wait_days"] == 0

    validate_error(
        api.request_verification(
            application_id,
            factories.verification_request_payload(
                provider_name="Dr. Q Duarte",
                provider_type="PHYSICIAN",
                provider_license_number="MD-90004",
            ),
            CLERK_HEADERS,
        ),
        ERR_VERIFICATION_PENDING,
        409,
    )

    _records, meta = validate_paginated(
        api.list_verifications(application_id, CLERK_HEADERS)
    )
    assert meta["total_count"] == 2
    assert (
        validate_success(api.get_application(application_id, CLERK_HEADERS))["status"]
        == "PENDING_VERIFICATION"
    )


def test_scoring_before_attendance_and_signing_before_scoring_are_both_refused(api):
    """The scoring dimension is guarded pairwise against the attendance dimension.

    "Scoring belongs to the `Evaluator` who conducted the assessment, and it is
    permitted only once the attendance dimension reads `ATTENDED`; attempting to
    score a `SCHEDULED`, `NO_SHOW` or `CANCELLED_BY_AGENCY` assessment is
    `ERR_INVALID_ASSESSMENT_STATE` (409)."

    "An `EligibilitySpecialist` signs off an assessment whose scoring dimension
    reads `SCORED`; a sign-off attempted while the assessment is still
    `NOT_STARTED`, or after it is already `SIGNED_OFF`, is
    `ERR_INVALID_ASSESSMENT_STATE` (409)."

    Design: Corner/state_machines/scores_posted_before_attendance_is_recorded_is_an_invalid_assessment_state
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Mira Sandoval",
        date_of_birth="1971-02-02",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="CANE",
    )
    context = scheduled_assessment(
        api,
        applicant=rider,
        slot=create_slot(api, site_name="East Depot Annex", capacity=2),
        claimed_conditions=["COPD"],
    )
    assessment_id = context["assessment"]["id"]
    application_id = context["application"]["id"]

    validate_error(
        api.record_scores(
            assessment_id,
            factories.scores_payload(
                board_alight_score=2,
                wayfinding_score=3,
                distance_meters_walked=250,
                heat_sensitivity_flag=False,
            ),
            EVALUATOR_HEADERS,
        ),
        ERR_INVALID_ASSESSMENT_STATE,
        409,
    )
    assessment = validate_success(api.get_assessment(assessment_id, EVALUATOR_HEADERS))
    assert assessment["scoring_status"] == "NOT_STARTED"
    assert assessment["recommended_category"] is None
    assert assessment["scored_by_user_id"] is None

    set_clock(api, "2026-08-05T09:30:00Z")
    attended = validate_success(
        api.record_attendance(
            assessment_id, factories.attendance_payload("ATTENDED"), EVALUATOR_HEADERS
        )
    )
    assert attended["attendance_status"] == "ATTENDED"
    assert attended["scoring_status"] == "NOT_STARTED"

    validate_error(
        api.sign_off_assessment(
            assessment_id, factories.sign_off_payload(), SPECIALIST_HEADERS
        ),
        ERR_INVALID_ASSESSMENT_STATE,
        409,
    )
    assessment = validate_success(api.get_assessment(assessment_id, EVALUATOR_HEADERS))
    assert assessment["signed_off_by_user_id"] is None
    assert assessment["scoring_status"] == "NOT_STARTED"

    application = validate_success(api.get_application(application_id, CLERK_HEADERS))
    assert application["status"] == "ASSESSMENT_SCHEDULED"


def test_a_drafted_determination_and_a_filed_appeal_carry_no_derived_data(api):
    """Both records are born with their schedule and remedy fields still null.

    "A successful draft creates the determination in `DRAFT`, copies
    `applicant_id` down from the parent packet so the grant is addressable by
    rider, records `determined_by_user_id` from the acting `X-User-ID` — the
    identity the appeal reviewer must later differ from — leaves `issued_at` and
    `expires_at` null, sets `under_appeal` false, `origin` to
    `SPECIALIST_DETERMINATION`, and `fixed_route_competency_confirmed` false."

    "A filed appeal starts in `FILED` with `filed_at` stamped from the logical
    clock, `filing_deadline_date` recorded as `effective_date` plus 60 days, and
    `reviewer_user_id`, `hearing_at`, `heard_at`, `decision_due_date`, `outcome`,
    `granted_category`, `decided_at` and `decision_note` all null, and
    `continued_service_extended` false."

    Design: Corner/state_machines/determination_and_appeal_are_born_in_their_declared_initial_states
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Nadia Oyelowo",
        date_of_birth="1958-04-04",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="WALKER",
    )
    context = drafted_determination(
        api,
        applicant=rider,
        functional_answers=factories.functional_answers(max_walk_distance_meters=150),
        claimed_conditions=["osteoarthritis"],
        score_overrides={
            "board_alight_score": 1,
            "wayfinding_score": 3,
            "distance_meters_walked": 150,
            "heat_sensitivity_flag": False,
        },
        slot=create_slot(api, capacity=2),
        draft_overrides={
            "category": "UNCONDITIONAL",
            "effective_date": "2026-08-06",
            "rationale": "cannot board fixed-route steps",
        },
    )
    draft = context["determination"]

    assert draft["status"] == "DRAFT"
    assert draft["origin"] == "SPECIALIST_DETERMINATION"
    assert draft["issued_at"] is None
    assert draft["expires_at"] is None
    assert draft["under_appeal"] is False
    assert draft["fixed_route_competency_confirmed"] is False
    assert draft["trip_condition_count"] == 0
    assert draft["determined_by_user_id"] == "spec-1"
    assert draft["category"] == "UNCONDITIONAL"
    assert draft["applicant_id"] == rider["id"]

    issued = validate_success(
        api.issue_determination(draft["id"], factories.issue_payload(), SPECIALIST_HEADERS)
    )
    assert issued["status"] == "ISSUED"
    assert issued["term_days"] == 1825
    assert issued["expires_at"] == "2031-08-05"

    appeal = validate_success(
        api.create_appeal(
            factories.appeal_payload(
                draft["id"],
                grounds="requests conditional rather than unconditional",
                request_hearing=True,
            ),
            make_applicant_headers(rider["id"]),
        ),
        201,
    )
    assert appeal["status"] == "FILED"
    assert appeal["reviewer_user_id"] is None
    assert appeal["hearing_at"] is None
    assert appeal["heard_at"] is None
    assert appeal["decided_at"] is None
    assert appeal["outcome"] is None
    assert appeal["granted_category"] is None
    assert appeal["decision_note"] is None
    assert appeal["decision_due_date"] is None
    assert appeal["continued_service_extended"] is False
    assert appeal["filing_deadline_date"] == "2026-10-05"

    determination = validate_success(
        api.get_determination(draft["id"], SPECIALIST_HEADERS)
    )
    assert determination["under_appeal"] is True
    reread = validate_success(api.get_applicant(rider["id"], CLERK_HEADERS))
    assert reread["continued_service_during_appeal"] is True


def test_a_decided_appeal_rejects_a_second_decision_a_hearing_and_a_reassignment(api):
    """DECIDED is terminal, and the upheld determination is not disturbed.

    "The decision is recorded by the assigned reviewer on an appeal in `HEARD`;
    from `FILED`, `REVIEWER_ASSIGNED`, `HEARING_SCHEDULED` or an
    already-`DECIDED` appeal it is `ERR_APPEAL_STATE_INVALID` (409)."

    "An `UPHELD` decision confirms the original determination. The appeal moves
    `HEARD → DECIDED` with `outcome` recorded and `decided_at` stamped from the
    clock. The contested determination's `under_appeal` returns to false and its
    own `status` is left exactly as it was — an upheld appeal does not vacate
    anything. The rider's `continued_service_during_appeal` returns to false"

    "Assigning the reviewer is an `AccessibilityOfficeAdmin` action on an appeal
    in `FILED`; from any other status it is `ERR_APPEAL_STATE_INVALID` (409)."

    Design: Corner/state_machines/appeal_decided_is_terminal_and_rejects_a_second_decision
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Otto Brennan",
        date_of_birth="1949-09-19",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="NONE",
    )
    context = heard_appeal_on_paper(
        api,
        applicant=rider,
        functional_answers=factories.functional_answers(max_walk_distance_meters=140),
        claimed_conditions=["neuropathy"],
        score_overrides={
            "board_alight_score": 1,
            "wayfinding_score": 4,
            "distance_meters_walked": 140,
            "heat_sensitivity_flag": False,
        },
        slot=create_slot(api, capacity=2),
        draft_overrides={
            "category": "UNCONDITIONAL",
            "effective_date": "2026-08-06",
            "rationale": "cannot board steps",
        },
        appeal_overrides={"grounds": "seeks conditional category"},
    )
    appeal = context["appeal"]
    determination_id = context["determination"]["id"]
    reviewer_headers = context["reviewer_headers"]

    assert appeal["status"] == "HEARD"
    assert appeal["heard_at"] == "2026-08-05T09:30:00.000Z"
    assert appeal["decision_due_date"] == "2026-09-04"
    assert appeal["hearing_at"] is None

    decided = validate_success(
        api.decide_appeal(
            appeal["id"],
            factories.appeal_decision_payload(
                "UPHELD", decision_note="assessment supports unconditional eligibility"
            ),
            reviewer_headers,
        )
    )
    assert decided["status"] == "DECIDED"
    assert decided["outcome"] == "UPHELD"
    assert decided["decided_at"] == "2026-08-05T09:30:00.000Z"

    validate_error(
        api.decide_appeal(
            appeal["id"],
            factories.appeal_decision_payload("OVERTURNED"),
            reviewer_headers,
        ),
        ERR_APPEAL_STATE_INVALID,
        409,
    )
    validate_error(
        api.open_appeal_hearing(
            appeal["id"], factories.paper_hearing_payload(), reviewer_headers
        ),
        ERR_APPEAL_STATE_INVALID,
        409,
    )
    validate_error(
        api.assign_appeal_reviewer(
            appeal["id"],
            factories.assign_reviewer_payload(REVIEWER_2_USER_ID),
            ADMIN_HEADERS,
        ),
        ERR_APPEAL_STATE_INVALID,
        409,
    )

    final = validate_success(api.get_appeal(appeal["id"], ADMIN_HEADERS))
    assert final["status"] == "DECIDED"
    assert final["outcome"] == "UPHELD"
    assert final["reviewer_user_id"] == "rev-1"

    determination = validate_success(
        api.get_determination(determination_id, SPECIALIST_HEADERS)
    )
    assert determination["status"] == "ISSUED"
    assert determination["under_appeal"] is False

    reread = validate_success(api.get_applicant(rider["id"], CLERK_HEADERS))
    assert reread["continued_service_during_appeal"] is False
    assert reread["eligibility_category"] == "UNCONDITIONAL"


def test_issuing_a_recertification_supersedes_and_closes_the_prior_grant(api):
    """Supersession, not expiry, is what ends the first grant's appealability.

    "It moves every *other* determination of the same rider that was in `ISSUED`
    to `SUPERSEDED`. It rewrites the rider's mirrors:
    `current_eligibility_status` becomes `ELIGIBLE`, or `INELIGIBLE` when the
    category is `INELIGIBLE`; `eligibility_category` becomes the issued category;
    and `active_determination_id` becomes this determination's `id`."

    "A determination that has been superseded is frozen for appeal purposes: its
    `under_appeal` value stays whatever it was, its own `status` is not otherwise
    disturbed, and no new appeal may be filed against it."

    "the determination must currently be in `ISSUED` — a `DRAFT`, `SUPERSEDED`,
    `VACATED` or `EXPIRED` determination is not appealable and yields
    `ERR_DETERMINATION_NOT_APPEALABLE` (409)"

    Design: Corner/state_machines/issuing_a_recertification_determination_supersedes_the_prior_issued_one
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Pilar Guzman",
        date_of_birth="1954-07-07",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="WALKER",
    )
    first = issued_determination(
        api,
        applicant=rider,
        functional_answers=factories.functional_answers(max_walk_distance_meters=130),
        claimed_conditions=["severe arthritis"],
        score_overrides={
            "board_alight_score": 1,
            "wayfinding_score": 3,
            "distance_meters_walked": 130,
            "heat_sensitivity_flag": False,
        },
        slot=create_slot(api, capacity=2),
        draft_overrides={
            "category": "UNCONDITIONAL",
            "effective_date": "2026-08-06",
            "rationale": "cannot board fixed-route steps",
        },
    )
    determination_one = first["determination"]
    assert determination_one["status"] == "ISSUED"
    assert determination_one["expires_at"] == "2031-08-05"
    assert first["application"]["status"] == "DETERMINED"

    set_clock(api, "2026-08-20T00:00:00Z")
    second = drafted_determination(
        api,
        applicant=rider,
        application_type="RECERTIFICATION",
        functional_answers=factories.functional_answers(
            can_navigate_unfamiliar_route=True, max_walk_distance_meters=300
        ),
        claimed_conditions=["arthritis, improved"],
        attests_permanent=False,
        slot=create_slot(
            api,
            evaluator_user_id="eval-2",
            starts_at="2026-08-25T09:00:00Z",
            ends_at="2026-08-25T10:00:00Z",
            capacity=2,
        ),
        attendance_at="2026-08-25T09:30:00Z",
        score_overrides={
            "board_alight_score": 3,
            "wayfinding_score": 3,
            "distance_meters_walked": 300,
            "heat_sensitivity_flag": True,
        },
        draft_overrides={
            "category": "CONDITIONAL",
            "effective_date": "2026-08-26",
            "rationale": "heat-sensitive; conditional on forecast",
            "trip_conditions": [
                factories.trip_condition_payload(
                    condition_type="HEAT_INDEX_ABOVE",
                    comparator="GTE",
                    threshold_value=90,
                    note="no service above heat index 90",
                )
            ],
        },
    )
    determination_two = second["determination"]

    issued = validate_success(
        api.issue_determination(
            determination_two["id"], factories.issue_payload(), SPECIALIST_HEADERS
        )
    )
    assert issued["status"] == "ISSUED"
    assert issued["term_days"] == 1095
    assert issued["expires_at"] == "2029-08-25"

    demoted = validate_success(
        api.get_determination(determination_one["id"], SPECIALIST_HEADERS)
    )
    assert demoted["status"] == "SUPERSEDED"
    assert demoted["expires_at"] == "2031-08-05"

    reread = validate_success(api.get_applicant(rider["id"], CLERK_HEADERS))
    assert reread["active_determination_id"] == determination_two["id"]
    assert reread["eligibility_category"] == "CONDITIONAL"
    assert reread["current_eligibility_status"] == "ELIGIBLE"

    _grants, grant_meta = validate_paginated(
        api.list_determinations(SPECIALIST_HEADERS, params={"applicant_id": rider["id"]})
    )
    assert grant_meta["total_count"] == 2

    referrals, referral_meta = validate_paginated(
        api.list_travel_training_referrals(
            TRAINER_HEADERS, params={"determination_id": determination_two["id"]}
        )
    )
    assert referral_meta["total_count"] == 1
    assert referrals[0]["status"] == "REFERRED"
    assert referrals[0]["referral_reason"] == "CONDITIONAL_ELIGIBILITY_AUTO"

    validate_error(
        api.create_appeal(
            factories.appeal_payload(
                determination_one["id"],
                grounds="still disagrees with the original category",
            ),
            make_applicant_headers(rider["id"]),
        ),
        ERR_DETERMINATION_NOT_APPEALABLE,
        409,
    )

    application_two = validate_success(
        api.get_application(second["application"]["id"], CLERK_HEADERS)
    )
    assert application_two["status"] == "DETERMINED"


def test_completing_training_at_exactly_eighty_flips_both_competency_mirrors(api):
    """A score of exactly 80 confirms competency and syncs rider and grant.

    "Completion is a `TravelTrainer` action on a referral in `ENROLLED`;
    attempting it on any other status is `ERR_REFERRAL_STATE_INVALID` (409). The
    trainer supplies `fixed_route_competency_score`, a whole number from 0 through
    100 — anything outside that range is `ERR_INVALID_REQUEST` — and the referral
    moves `ENROLLED → COMPLETED` with `completed_at` stamped from the logical
    clock. A score of at least 80 confirms fixed-route competency, and that
    confirmation cascades: the rider's `fixed_route_competency_confirmed` flips to
    true, and because the rider flag has flipped, the
    `fixed_route_competency_confirmed` mirror on the rider's determination that is
    still in `ISSUED` flips to true as well"

    "A decision of `ENROLLED` moves the referral `REFERRED → ENROLLED`, and it
    re-checks the category guard at that moment"

    Design: Corner/state_machines/completing_travel_training_at_eighty_syncs_the_competency_flag_to_both_rows
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Quinn Alvarez",
        date_of_birth="1975-05-25",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="NONE",
    )
    context = auto_referral(
        api,
        applicant=rider,
        conditions=[
            factories.boolean_trip_condition_payload(
                "COGNITIVE_UNFAMILIAR_ROUTE",
                note="eligible only for unfamiliar routes",
            )
        ],
        functional_answers=factories.functional_answers(
            can_board_bus_steps=True,
            can_navigate_unfamiliar_route=False,
            max_walk_distance_meters=500,
            uses_mobility_aid_outdoors=False,
            has_cognitive_impairment=True,
        ),
        claimed_conditions=["cognitive impairment"],
        slot=create_slot(api, capacity=2),
        score_overrides={
            "board_alight_score": 3,
            "wayfinding_score": 2,
            "distance_meters_walked": 500,
            "heat_sensitivity_flag": False,
        },
    )
    referral = context["referral"]
    determination_id = context["determination"]["id"]

    assert referral is not None
    assert referral["status"] == "REFERRED"
    assert referral["referral_reason"] == "CONDITIONAL_ELIGIBILITY_AUTO"
    assert referral["fixed_route_competency_score"] is None
    assert referral["completed_at"] is None

    enrolled = validate_success(
        api.respond_to_referral(
            referral["id"],
            factories.referral_response_payload("ENROLLED"),
            make_applicant_headers(rider["id"]),
        )
    )
    assert enrolled["status"] == "ENROLLED"

    completed = validate_success(
        api.complete_referral(
            referral["id"],
            factories.referral_completion_payload(fixed_route_competency_score=80),
            TRAINER_HEADERS,
        )
    )
    assert completed["status"] == "COMPLETED"
    assert completed["fixed_route_competency_score"] == 80
    assert completed["completed_at"] == "2026-08-05T09:30:00.000Z"

    reread = validate_success(api.get_applicant(rider["id"], CLERK_HEADERS))
    assert reread["fixed_route_competency_confirmed"] is True

    determination = validate_success(
        api.get_determination(determination_id, SPECIALIST_HEADERS)
    )
    assert determination["fixed_route_competency_confirmed"] is True
    assert determination["status"] == "ISSUED"

    _conditions, condition_meta = validate_paginated(
        api.list_trip_conditions(determination_id, SPECIALIST_HEADERS)
    )
    assert condition_meta["total_count"] == 1


def test_deciding_responding_and_rescinding_from_proposed_are_all_refused(api):
    """From PROPOSED the only declared trigger is send-notice.

    "A `ConductOfficer` sends the written notice on a proceeding in `PROPOSED`,
    moving it `PROPOSED → NOTICE_SENT`, stamping `notice_sent_at` from the logical
    clock, and setting `response_deadline_date` to the calendar date of
    `notice_sent_at` plus 14 days. Sending a notice from any other status is
    `ERR_PROCEEDING_STATE_INVALID` (409), and that same code guards every other
    transition in this workflow whose source status is wrong."

    "The proceeding must be in `RIDER_RESPONDED` or `RESPONSE_LAPSED`, else
    `ERR_PROCEEDING_STATE_INVALID` (409)."

    "A `ConductOfficer` or an `AccessibilityOfficeAdmin` may rescind a proceeding
    in `UPHELD_PENDING` or `ACTIVE`, moving it to `VOID`; from any other status it
    is `ERR_PROCEEDING_STATE_INVALID` (409)."

    Design: Corner/state_machines/deciding_a_suspension_from_proposed_is_a_proceeding_state_violation
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Rafe Donnelly",
        date_of_birth="1980-08-18",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="NONE",
    )
    ingest_trip_events(
        api,
        rider["id"],
        [("2026-07-10", "NO_SHOW"), ("2026-07-17", "NO_SHOW")],
    )
    reread = validate_success(api.get_applicant(rider["id"], CONDUCT_OFFICER_HEADERS))
    assert reread["no_show_points_event_basis"] == 4

    proceeding = validate_success(
        api.propose_suspension(
            rider["id"],
            factories.suspension_proposal_payload(
                reread["version"],
                review_window_end_date="2026-08-01",
                grounds_note="two no-shows in July",
            ),
            CONDUCT_OFFICER_HEADERS,
        ),
        201,
    )
    assert proceeding["status"] == "PROPOSED"
    assert proceeding["origin"] == "MANUAL"
    assert proceeding["proposed_by_user_id"] == "co-1"
    assert proceeding["notice_sent_at"] is None
    assert proceeding["response_deadline_date"] is None
    assert proceeding["duration_days"] == 0
    assert proceeding["days_served"] == 0
    assert proceeding["days_forgiven"] == 0

    validate_error(
        api.decide_suspension(
            proceeding["id"],
            factories.suspension_decision_payload(
                decision="UPHELD", suspension_start_date="2026-09-01"
            ),
            CONDUCT_OFFICER_2_HEADERS,
        ),
        ERR_PROCEEDING_STATE_INVALID,
        409,
    )
    validate_error(
        api.respond_to_suspension(
            proceeding["id"],
            factories.rider_response_payload(rider_response_note="I was hospitalised"),
            make_applicant_headers(rider["id"]),
        ),
        ERR_PROCEEDING_STATE_INVALID,
        409,
    )
    validate_error(
        api.rescind_suspension(
            proceeding["id"], factories.rescind_payload(), CONDUCT_OFFICER_HEADERS
        ),
        ERR_PROCEEDING_STATE_INVALID,
        409,
    )

    final = validate_success(
        api.get_suspension_proceeding(proceeding["id"], CONDUCT_OFFICER_HEADERS)
    )
    assert final["status"] == "PROPOSED"
    assert final["decision"] is None

    rider_now = validate_success(api.get_applicant(rider["id"], CLERK_HEADERS))
    assert rider_now["service_status"] == "ACTIVE"
    assert rider_now["prior_upheld_suspension_count"] == 0
    assert rider_now["suspension_days_ledger_total"] == 0


def test_issuing_a_local_grant_freezes_the_active_visitor_record(api):
    """The visitor cascade fires only on ACTIVE records and then locks them.

    "And it closes out visitor service: every visitor-eligibility record of this
    rider still in `ACTIVE` moves to `SUPERSEDED_BY_LOCAL`, because a local grant
    governs from its `effective_date` and visitor days stop accruing."

    "The record must be in `ACTIVE`: both `EXHAUSTED` and `SUPERSEDED_BY_LOCAL`
    records are frozen and reject new days with `ERR_VISITOR_RECORD_INACTIVE`
    (409)."

    "Only then is local eligibility considered: a rider who already holds a
    determination in `ISSUED` whose category is anything other than `INELIGIBLE`
    does not need visitor service and is refused with
    `ERR_LOCAL_ELIGIBILITY_EXISTS` (422)."

    Design: Corner/state_machines/issuing_a_local_determination_supersedes_the_active_visitor_record
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Sunniva Berg",
        date_of_birth="1961-01-11",
        residence_zone="OUT_OF_SERVICE_AREA",
        mobility_aid="CANE",
        home_agency_name="Fjord Transit",
    )
    visitor = visitor_record(
        api,
        applicant=rider,
        home_agency_name="Fjord Transit",
        home_agency_certification_provided=True,
        visit_start_date="2026-08-01",
    )
    record_id = visitor["visitor_record"]["id"]
    assert visitor["visitor_record"]["status"] == "ACTIVE"

    with_one_day = validate_success(
        api.record_visitor_service_day(
            record_id, factories.service_day_payload("2026-08-01"), CLERK_HEADERS
        )
    )
    assert with_one_day["days_used_365"] == 1
    assert with_one_day["days_remaining_365"] == 20
    assert with_one_day["status"] == "ACTIVE"
    assert with_one_day["service_dates"] == ["2026-08-01"]

    context = drafted_determination(
        api,
        applicant=rider,
        functional_answers=factories.functional_answers(max_walk_distance_meters=100),
        claimed_conditions=["balance disorder"],
        slot=create_slot(api, capacity=2),
        score_overrides={
            "board_alight_score": 1,
            "wayfinding_score": 3,
            "distance_meters_walked": 100,
            "heat_sensitivity_flag": False,
        },
        draft_overrides={
            "category": "UNCONDITIONAL",
            "effective_date": "2026-08-06",
            "rationale": "relocated into the service area",
        },
    )

    issued = validate_success(
        api.issue_determination(
            context["determination"]["id"], factories.issue_payload(), SPECIALIST_HEADERS
        )
    )
    assert issued["status"] == "ISSUED"

    frozen = validate_success(api.get_visitor_eligibility(record_id, CLERK_HEADERS))
    assert frozen["status"] == "SUPERSEDED_BY_LOCAL"
    assert frozen["service_dates"] == ["2026-08-01"]
    assert frozen["days_used_365"] == 1

    validate_error(
        api.record_visitor_service_day(
            record_id, factories.service_day_payload("2026-08-06"), CLERK_HEADERS
        ),
        ERR_VISITOR_RECORD_INACTIVE,
        409,
    )
    validate_error(
        api.create_visitor_eligibility(
            rider["id"],
            factories.visitor_eligibility_payload(
                home_agency_name="Fjord Transit",
                home_agency_certification_provided=True,
                visit_start_date="2026-08-07",
            ),
            CLERK_HEADERS,
        ),
        ERR_LOCAL_ELIGIBILITY_EXISTS,
        422,
    )

    reread = validate_success(api.get_applicant(rider["id"], CLERK_HEADERS))
    assert reread["current_eligibility_status"] == "ELIGIBLE"
    assert reread["eligibility_category"] == "UNCONDITIONAL"
