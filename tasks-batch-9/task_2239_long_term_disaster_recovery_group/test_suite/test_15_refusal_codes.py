"""Refusals the coalition must be able to tell apart.

The point of each test is the *identity* of the refusal: which of several plausible codes
comes back, and that the refused write left the record where it was.
"""

from test_helpers import (
    ADMIN,
    BUILDER,
    CASE_MANAGER,
    CHAIR,
    COORDINATOR,
    NON_EXISTENT_UUID,
    OFFICER,
    ApiErrorId,
    assert_construction_project,
    assert_funding_source,
    assert_recovery_case,
    assert_table_session,
    case_presentation_payload,
    create_case,
    create_funding_source,
    create_group,
    create_lodging_site,
    create_project,
    create_survivor,
    damage_item_payload,
    decide,
    document_damage,
    housing_assignment_payload,
    log_follow_up,
    make_member_org_delegate_headers,
    open_session,
    permit_project,
    pledge,
    present_and_deliberate,
    queue_presentation,
    read_case,
    read_funding_source,
    read_member_org,
    read_presentation,
    request_disbursement,
    run_assessment,
    schedule_session,
    seat_member_org,
    set_clock,
    transition_project,
    validate_error,
    validate_success,
    verify_damage,
    volunteer_deployment_payload,
)


def test_every_missing_record_answers_in_its_own_name(api):
    """PRD §2.11: "The response names the first identifier that failed to resolve, using the
    code for that entity kind: `ERR_SURVIVOR_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
    `ERR_DAMAGE_ITEM_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_PRESENTATION_NOT_FOUND`,
    `ERR_COMMITMENT_NOT_FOUND`, `ERR_MEMBER_ORG_NOT_FOUND`, `ERR_FUNDING_SOURCE_NOT_FOUND`,
    `ERR_DISBURSEMENT_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`,
    `ERR_VOLUNTEER_GROUP_NOT_FOUND`, `ERR_DEPLOYMENT_NOT_FOUND`,
    `ERR_LODGING_SITE_NOT_FOUND` or `ERR_HOUSING_ASSIGNMENT_NOT_FOUND`, each with HTTP
    404."

    Design: Corner/errors/corner_each_missing_resource_reports_its_own_not_found_code
    """
    set_clock()
    survivor = create_survivor(
        household_name="Lombardi Household",
        primary_contact_phone="555-0251",
        household_size=2,
        income_band="LOW",
        head_of_household_age=45,
    )
    case = create_case(survivor["id"])
    session = schedule_session(session_label="UNT not-found probe")

    probes = [
        (api.get_recovery_case(NON_EXISTENT_UUID, CASE_MANAGER), ApiErrorId.ERR_CASE_NOT_FOUND),
        (
            api.verify_damage_item(
                NON_EXISTENT_UUID,
                {"verification_status": "VERIFIED", "verified_cost_cents": 100},
                BUILDER,
            ),
            ApiErrorId.ERR_DAMAGE_ITEM_NOT_FOUND,
        ),
        (
            api.get_member_organization(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_MEMBER_ORG_NOT_FOUND,
        ),
        (api.get_table_session(NON_EXISTENT_UUID, CHAIR), ApiErrorId.ERR_SESSION_NOT_FOUND),
        (
            api.get_case_presentation(NON_EXISTENT_UUID, CHAIR),
            ApiErrorId.ERR_PRESENTATION_NOT_FOUND,
        ),
        (
            api.get_funding_commitment(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_COMMITMENT_NOT_FOUND,
        ),
        (
            api.get_funding_source(NON_EXISTENT_UUID, OFFICER),
            ApiErrorId.ERR_FUNDING_SOURCE_NOT_FOUND,
        ),
        (
            api.get_disbursement(NON_EXISTENT_UUID, OFFICER),
            ApiErrorId.ERR_DISBURSEMENT_NOT_FOUND,
        ),
        (
            api.get_construction_project(NON_EXISTENT_UUID, BUILDER),
            ApiErrorId.ERR_PROJECT_NOT_FOUND,
        ),
        (
            api.get_volunteer_deployment(NON_EXISTENT_UUID, COORDINATOR),
            ApiErrorId.ERR_DEPLOYMENT_NOT_FOUND,
        ),
        (
            api.get_housing_assignment(NON_EXISTENT_UUID, COORDINATOR),
            ApiErrorId.ERR_HOUSING_ASSIGNMENT_NOT_FOUND,
        ),
        # A body reference, not a path parameter: the case and session both resolve.
        (
            api.create_case_presentation(
                case_presentation_payload(
                    case["id"],
                    session["id"],
                    NON_EXISTENT_UUID,
                    narrative="Unknown determination probe.",
                ),
                CASE_MANAGER,
            ),
            ApiErrorId.ERR_ASSESSMENT_NOT_FOUND,
        ),
    ]

    for response, error_id in probes:
        validate_error(response, error_id.value, 404)


def test_a_withdrawn_household_takes_no_further_casework(api):
    """PRD §3.9: "Both legs set `case_status` to `INACTIVE`, store the `withdrawn_reason`,
    decrement the survivor's `open_case_count` and increment the case's `version`."

    Design: Corner/errors/corner_withdrawn_case_goes_inactive_and_accepts_no_further_casework
    """
    set_clock()
    survivor = create_survivor(
        household_name="Marchetti Household",
        primary_contact_phone="555-0252",
        household_size=2,
        income_band="LOW",
        head_of_household_age=48,
    )
    case = create_case(survivor["id"], primary_residence_status="RENTER")

    withdrawn = validate_success(
        api.close_case(
            case["id"],
            {"withdrawn_reason": "Household relocated out of state and withdrew."},
            ADMIN,
        )
    )

    assert_recovery_case(withdrawn)
    assert withdrawn["case_status"] == "INACTIVE"
    assert withdrawn["withdrawn_reason"] == "Household relocated out of state and withdrew."
    late_claim = api.create_damage_item(
        case["id"],
        damage_item_payload(
            category="CONTENTS",
            item_description="Late claim",
            documented_cost_cents=200_000,
            photo_count=1,
            is_habitability_critical=False,
        ),
        CASE_MANAGER,
    )
    validate_error(late_claim, ApiErrorId.ERR_CASE_NOT_ASSESSABLE.value, 409)
    household = validate_success(api.get_survivor(survivor["id"], CASE_MANAGER))
    assert household["open_case_count"] == 0


def test_closure_review_reports_the_state_before_the_criteria(api):
    """PRD §2.11: "**Declared source state** — the target record is in a state from which
    the requested transition is declared, answering with the code for that entity kind:
    `ERR_CASE_INVALID_STATE`, `ERR_PRESENTATION_INVALID_STATE`,
    `ERR_COMMITMENT_INVALID_STATE`, `ERR_DISBURSEMENT_INVALID_STATE`,
    `ERR_PROJECT_INVALID_TRANSITION`, `ERR_DEPLOYMENT_INVALID_TRANSITION`,
    `ERR_HOUSING_ALREADY_RELEASED` or `ERR_DAMAGE_ITEM_ALREADY_VERIFIED`, each with HTTP
    409."

    Design: Corner/errors/corner_closure_review_from_the_wrong_case_state_is_refused
    """
    set_clock()
    survivor = create_survivor(
        household_name="Nakagawa Household",
        primary_contact_phone="555-0253",
        household_size=2,
        income_band="LOW",
        head_of_household_age=51,
    )
    case = create_case(survivor["id"])

    premature = api.closure_review_case(
        case["id"], {"review_note": "Premature closure attempt."}, CASE_MANAGER
    )

    # The state gate outranks the closure criteria, so this is 409 rather than the
    # criteria refusal.
    validate_error(premature, ApiErrorId.ERR_CASE_INVALID_STATE.value, 409)
    untouched = read_case(case["id"])
    assert untouched["case_status"] == "INTAKE"
    assert untouched["version"] == 1


def test_closure_review_needs_every_criterion_at_once(api):
    """PRD §3.9: "Three criteria must hold: the case's `funding_status` must be
    `SATISFIED`; every construction project on the case must have `status` `CLOSED_OUT` or
    `CANCELLED`; and at least one follow-up contact must exist on the case."

    Design: Corner/errors/corner_closure_review_with_money_still_outstanding_is_refused
    """
    set_clock()
    survivor = create_survivor(
        household_name="Okonkwo Household",
        primary_contact_phone="555-0254",
        household_size=5,
        income_band="ELI",
        head_of_household_age=57,
        has_member_with_disability=True,
        is_uninsured=True,
    )
    case = create_case(survivor["id"])
    item = document_damage(
        case["id"],
        category="STRUCTURE",
        item_description="Substantial rebuild",
        documented_cost_cents=4_000_000,
        photo_count=15,
    )
    verify_damage(item["id"], verified_cost_cents=4_000_000)
    assessment = run_assessment(case["id"])
    org = seat_member_org(
        org_name="Closure Table Org",
        org_type="NONPROFIT",
        contact_email="c@table.example",
        annual_pledge_cap_cents=3_000_000,
    )
    create_funding_source(
        label="Bridge pool for the closure-criteria case",
        source_type="INDIVIDUAL_DONATION",
        restriction_code="UNRESTRICTED",
        total_cents=1_000_000,
    )
    session = schedule_session(session_label="UNT closure criteria")
    open_session(session["id"], [org["id"]])
    presentation = queue_presentation(
        case["id"], session["id"], assessment["id"], narrative="Substantial rebuild request."
    )
    present_and_deliberate(presentation["id"])
    pledge(presentation["id"], org["id"], 500_000)
    awarded = decide(
        presentation["id"], "AWARD", decision_note="Partial award; more sources needed."
    )
    assert awarded["bridge_tier"] == "TIER_C"
    assert awarded["bridge_authorized_cents"] == 600_000
    assert awarded["awarded_cents"] == 1_100_000
    in_recovery = read_case(case["id"])
    assert in_recovery["case_status"] == "ACTIVE_RECOVERY"
    assert in_recovery["funding_status"] == "PARTIALLY_COMMITTED"

    outstanding = api.closure_review_case(
        case["id"], {"review_note": "Attempting closure with money outstanding."}, CASE_MANAGER
    )

    validate_error(outstanding, ApiErrorId.ERR_CLOSURE_CRITERIA_NOT_MET.value, 409)
    log_follow_up(
        case["id"],
        contact_type="CLOSURE_REVIEW",
        contacted_on="2026-09-01",
        outcome="REACHED",
        notes="Discussed remaining unmet need.",
    )
    # A logged contact satisfies one criterion, but the money is still short.
    still_outstanding = api.closure_review_case(
        case["id"],
        {"review_note": "Second attempt after logging a follow-up."},
        CASE_MANAGER,
    )
    validate_error(still_outstanding, ApiErrorId.ERR_CLOSURE_CRITERIA_NOT_MET.value, 409)
    assert read_case(case["id"])["case_status"] == "ACTIVE_RECOVERY"


def test_an_adjourned_meeting_takes_no_new_agenda_items(api):
    """PRD §3.4: "The target session's `status` must be `SCHEDULED` or `IN_SESSION`, or
    `ERR_SESSION_NOT_ACCEPTING_QUEUE` results."

    Design: Corner/errors/corner_queueing_into_an_adjourned_session_is_refused
    """
    set_clock()
    survivor = create_survivor(
        household_name="Palladino Household",
        primary_contact_phone="555-0255",
        household_size=2,
        income_band="LOW",
        head_of_household_age=43,
    )
    case = create_case(survivor["id"])
    item = document_damage(
        case["id"],
        category="STRUCTURE",
        item_description="Siding",
        documented_cost_cents=600_000,
        photo_count=3,
    )
    verify_damage(item["id"], verified_cost_cents=600_000)
    assessment = run_assessment(case["id"])
    org = seat_member_org(
        org_name="Adjourned Table Org",
        org_type="FAITH_BASED",
        contact_email="a@adj.example",
        annual_pledge_cap_cents=3_000_000,
    )
    closed_meeting = schedule_session(
        session_label="UNT adjourned session", scheduled_for="2026-09-10T15:00:00Z"
    )
    later_meeting = schedule_session(
        session_label="UNT scheduled session", scheduled_for="2026-09-24T15:00:00Z"
    )
    open_session(closed_meeting["id"], [org["id"]])
    validate_success(
        api.adjourn_table_session(
            closed_meeting["id"], {"minutes_note": "No agenda items."}, CHAIR
        )
    )

    too_late = api.create_case_presentation(
        case_presentation_payload(
            case["id"],
            closed_meeting["id"],
            assessment["id"],
            narrative="Queueing into the adjourned session.",
        ),
        CASE_MANAGER,
    )

    validate_error(too_late, ApiErrorId.ERR_SESSION_NOT_ACCEPTING_QUEUE.value, 409)
    # A meeting that has not opened yet is still an acceptable destination.
    queued = validate_success(
        api.create_case_presentation(
            case_presentation_payload(
                case["id"],
                later_meeting["id"],
                assessment["id"],
                narrative="Queueing into the scheduled session.",
            ),
            CASE_MANAGER,
        ),
        201,
    )
    assert queued["status"] == "QUEUED"
    assert queued["queue_position"] == 1
    assert read_case(case["id"])["case_status"] == "PRESENTED"


def test_the_chair_may_not_adjourn_over_a_case_being_discussed(api):
    """PRD §3.5: "Moving a session `IN_SESSION → ADJOURNED` requires that no presentation
    in that session is `PRESENTING` or `DELIBERATING`; an attempt while one is mid-flight is
    refused with `ERR_SESSION_HAS_ACTIVE_PRESENTATION`."

    Design: Corner/errors/corner_adjourning_mid_deliberation_is_refused
    """
    set_clock()
    survivor = create_survivor(
        household_name="Quintana Household",
        primary_contact_phone="555-0256",
        household_size=3,
        income_band="VLI",
        head_of_household_age=47,
    )
    case = create_case(survivor["id"])
    item = document_damage(
        case["id"],
        category="STRUCTURE",
        item_description="Deck",
        documented_cost_cents=600_000,
        photo_count=3,
    )
    verify_damage(item["id"], verified_cost_cents=600_000)
    assessment = run_assessment(case["id"])
    org = seat_member_org(
        org_name="Mid-Deliberation Org",
        org_type="CIVIC_CLUB",
        contact_email="m@mid.example",
        annual_pledge_cap_cents=3_000_000,
    )
    session = schedule_session(session_label="UNT mid-deliberation adjourn")
    open_session(session["id"], [org["id"]])
    presentation = queue_presentation(
        case["id"], session["id"], assessment["id"], narrative="Deck repair request."
    )
    present_and_deliberate(presentation["id"])

    mid_flight = api.adjourn_table_session(
        session["id"], {"minutes_note": "Attempting to adjourn mid-deliberation."}, CHAIR
    )

    validate_error(mid_flight, ApiErrorId.ERR_SESSION_HAS_ACTIVE_PRESENTATION.value, 409)
    assert validate_success(api.get_table_session(session["id"], CHAIR))["status"] == "IN_SESSION"
    denied = decide(presentation["id"], "DENY", decision_note="Referred elsewhere.")
    assert denied["status"] == "DENIED"
    adjourned = validate_success(
        api.adjourn_table_session(
            session["id"], {"minutes_note": "Adjourning after the decision."}, CHAIR
        )
    )
    assert_table_session(adjourned)
    assert adjourned["status"] == "ADJOURNED"
    assert adjourned["queued_count"] == 0


def test_a_pledge_can_only_be_withdrawn_once(api):
    """PRD §3.4: "Rescinding a `PLEDGED` commitment moves it `PLEDGED → RESCINDED`,
    recomputes the organization's `committed_cents` and `remaining_pledge_capacity_cents`,
    and recomputes the presentation's `pledged_total_cents`."

    Design: Corner/errors/corner_rescinding_an_already_rescinded_pledge_is_refused
    """
    set_clock()
    survivor = create_survivor(
        household_name="Rossi Household",
        primary_contact_phone="555-0257",
        household_size=3,
        income_band="VLI",
        head_of_household_age=50,
    )
    case = create_case(survivor["id"])
    item = document_damage(
        case["id"],
        category="STRUCTURE",
        item_description="Chimney",
        documented_cost_cents=900_000,
        photo_count=3,
    )
    verify_damage(item["id"], verified_cost_cents=900_000)
    assessment = run_assessment(case["id"])
    org = seat_member_org(
        org_name="Rescission Org",
        org_type="NONPROFIT",
        contact_email="r@resc.example",
        annual_pledge_cap_cents=3_000_000,
    )
    session = schedule_session(session_label="UNT rescission")
    open_session(session["id"], [org["id"]])
    presentation = queue_presentation(
        case["id"], session["id"], assessment["id"], narrative="Chimney rebuild request."
    )
    present_and_deliberate(presentation["id"])
    commitment = pledge(presentation["id"], org["id"], 400_000)
    delegate_headers = make_member_org_delegate_headers(org["id"])

    rescinded = validate_success(
        api.rescind_funding_commitment(
            commitment["id"], {"rescission_reason": "Board reversed the pledge."}, delegate_headers
        )
    )

    assert rescinded["status"] == "RESCINDED"
    duplicate = api.rescind_funding_commitment(
        commitment["id"], {"rescission_reason": "Duplicate rescission attempt."}, delegate_headers
    )
    validate_error(duplicate, ApiErrorId.ERR_COMMITMENT_INVALID_STATE.value, 409)
    # The capacity is restored once, never twice.
    restored = read_member_org(org["id"])
    assert restored["committed_cents"] == 0
    assert restored["remaining_pledge_capacity_cents"] == 3_000_000
    assert restored["status"] == "ACTIVE"
    assert read_presentation(presentation["id"])["pledged_total_cents"] == 0


def test_the_hosting_lifecycle_refuses_each_step_out_of_turn(api):
    """PRD §3.8: "Third, the project must be accepting volunteers: its `status` must be
    `PERMITTED` or `IN_PROGRESS`, or `ERR_PROJECT_NOT_ACCEPTING_VOLUNTEERS` results — a
    `SCOPED`, `SUSPENDED`, `PUNCHLIST`, `CLOSED_OUT` or `CANCELLED` phase takes no crews."

    Design: Corner/errors/corner_volunteer_and_housing_lifecycle_errors_are_all_reachable
    """
    set_clock()
    survivor = create_survivor(
        household_name="Suzuki Household",
        primary_contact_phone="555-0258",
        household_size=2,
        income_band="LOW",
        head_of_household_age=44,
    )
    case = create_case(survivor["id"])
    unpermitted = create_project(
        case["id"],
        required_trade_hours={"GENERAL_LABOR": 180},
        estimated_material_cents=200_000,
    )
    permitted = create_project(
        case["id"],
        required_trade_hours={"GENERAL_LABOR": 180},
        estimated_material_cents=200_000,
    )
    permit_project(permitted["id"], permit_number="PB-4058")
    group = create_group(
        group_name="Group Victor",
        home_organization="Victor Lutheran",
        member_count=6,
        skill_profile={"GENERAL_LABOR": 6},
        requires_housing=True,
    )
    site = create_lodging_site(site_name="Fellowship Hall", bed_capacity=10)

    too_early = api.create_volunteer_deployment(
        volunteer_deployment_payload(
            group["id"], unpermitted["id"], "2026-09-07", "2026-09-11"
        ),
        COORDINATOR,
    )

    validate_error(too_early, ApiErrorId.ERR_PROJECT_NOT_ACCEPTING_VOLUNTEERS.value, 409)
    booked = validate_success(
        api.create_volunteer_deployment(
            volunteer_deployment_payload(
                group["id"], permitted["id"], "2026-09-07", "2026-09-11"
            ),
            COORDINATOR,
        ),
        201,
    )
    assert booked["status"] == "REQUESTED"
    assert booked["skill_fit_score_bps"] == 10000
    skipped_confirmation = api.transition_volunteer_deployment(
        booked["id"], {"action": "COMPLETE", "hours_logged": 180}, COORDINATOR
    )
    validate_error(
        skipped_confirmation, ApiErrorId.ERR_DEPLOYMENT_INVALID_TRANSITION.value, 409
    )
    assert (
        validate_success(api.get_volunteer_deployment(booked["id"], COORDINATOR))["status"]
        == "REQUESTED"
    )
    stay = validate_success(
        api.create_housing_assignment(
            housing_assignment_payload(
                group["id"], site["id"], "2026-09-07", "2026-09-12"
            ),
            COORDINATOR,
        ),
        201,
    )
    released = validate_success(
        api.release_housing_assignment(
            stay["id"], {"release_reason": "Group found other lodging."}, COORDINATOR
        )
    )
    assert released["status"] == "RELEASED"
    second_release = api.release_housing_assignment(
        stay["id"], {"release_reason": "Duplicate release attempt."}, COORDINATOR
    )
    validate_error(second_release, ApiErrorId.ERR_HOUSING_ALREADY_RELEASED.value, 409)


def test_the_next_phase_waits_for_the_one_before_it_to_finish(api):
    """PRD §3.7: "It requires two things beyond the source state: the predecessor chain must
    be clear — `predecessor_project_id` is null, or the predecessor's `status` is
    `CLOSED_OUT`, otherwise `ERR_PREDECESSOR_NOT_COMPLETE` results — and the owning case must
    not have wound down, so its `case_status` may not be `CLOSURE_PENDING`, `CLOSED` or
    `INACTIVE`."

    Design: Corner/errors/corner_successor_project_cannot_be_permitted_before_its_predecessor_closes
    """
    set_clock()
    survivor = create_survivor(
        household_name="Tremblay Household",
        primary_contact_phone="555-0259",
        household_size=2,
        income_band="LOW",
        head_of_household_age=46,
    )
    case = create_case(survivor["id"])
    first_phase = create_project(
        case["id"],
        required_trade_hours={"GENERAL_LABOR": 60},
        estimated_material_cents=100_000,
    )
    second_phase = create_project(
        case["id"],
        scope_code="STRUCTURE_REBUILD",
        required_trade_hours={"GENERAL_LABOR": 120},
        estimated_material_cents=400_000,
        predecessor_project_id=first_phase["id"],
    )
    transition_project(first_phase["id"], "PERMIT", permit_number="PB-4059-A")
    transition_project(first_phase["id"], "START")

    too_soon = api.transition_construction_project(
        second_phase["id"], {"action": "PERMIT", "permit_number": "PB-4059-B"}, BUILDER
    )

    # Work has begun on the first phase but it is not finished, which is not enough.
    validate_error(too_soon, ApiErrorId.ERR_PREDECESSOR_NOT_COMPLETE.value, 409)
    assert (
        validate_success(api.get_construction_project(second_phase["id"], BUILDER))["status"]
        == "SCOPED"
    )
    transition_project(first_phase["id"], "PUNCHLIST")
    transition_project(first_phase["id"], "CLOSE_OUT")
    permitted = validate_success(
        api.transition_construction_project(
            second_phase["id"], {"action": "PERMIT", "permit_number": "PB-4059-B"}, BUILDER
        )
    )
    assert_construction_project(permitted)
    assert permitted["status"] == "PERMITTED"
    assert permitted["permit_number"] == "PB-4059-B"


def test_another_households_determination_may_not_be_pinned(api):
    """PRD §3.4: "The pinned snapshot must belong to the same case, or
    `ERR_ASSESSMENT_CASE_MISMATCH` results."

    Design: Corner/errors/corner_assessment_from_another_case_cannot_be_pinned
    """
    set_clock()
    first_survivor = create_survivor(
        household_name="Ueda Household",
        primary_contact_phone="555-0260",
        household_size=2,
        income_band="LOW",
        head_of_household_age=45,
    )
    second_survivor = create_survivor(
        household_name="Varga Household",
        primary_contact_phone="555-0261",
        household_size=2,
        income_band="LOW",
        head_of_household_age=47,
    )
    assessments = []
    cases = []
    for survivor, description in (
        (first_survivor, "Repair A"),
        (second_survivor, "Repair B"),
    ):
        case = create_case(survivor["id"])
        item = document_damage(
            case["id"],
            category="STRUCTURE",
            item_description=description,
            documented_cost_cents=700_000,
            photo_count=3,
        )
        verify_damage(item["id"], verified_cost_cents=700_000)
        cases.append(case)
        assessments.append(run_assessment(case["id"]))
    org = seat_member_org(
        org_name="Mismatch Table Org",
        org_type="FAITH_BASED",
        contact_email="m@mis.example",
        annual_pledge_cap_cents=3_000_000,
    )
    session = schedule_session(session_label="UNT case mismatch")
    open_session(session["id"], [org["id"]])

    cross_case = api.create_case_presentation(
        case_presentation_payload(
            cases[0]["id"],
            session["id"],
            assessments[1]["id"],
            narrative="Pinning the other case's determination.",
        ),
        CASE_MANAGER,
    )

    validate_error(cross_case, ApiErrorId.ERR_ASSESSMENT_CASE_MISMATCH.value, 422)
    own = validate_success(
        api.create_case_presentation(
            case_presentation_payload(
                cases[0]["id"],
                session["id"],
                assessments[0]["id"],
                narrative="Pinning this case's own determination.",
            ),
            CASE_MANAGER,
        ),
        201,
    )
    assert own["status"] == "QUEUED"
    assert own["assessment_id"] == assessments[0]["id"]


def test_approval_checks_the_restriction_before_the_ceiling(api):
    """PRD §3.6: "It requires the row to be in `DOB_CLEARED`, requires the approver to differ
    from `requested_by_user_id` per §2.7, and then applies four further gates in the order
    given in §2.11." Restriction match is listed at rung 32 of that ladder and disbursement
    within commitment at rung 38, so the restriction refusal is the one reported when both
    would fail.

    Design: Corner/errors/corner_approval_money_gates_report_restriction_before_commitment
    """
    set_clock()
    survivor = create_survivor(
        household_name="Wisniewski Household",
        primary_contact_phone="555-0262",
        household_size=3,
        income_band="VLI",
        head_of_household_age=52,
    )
    case = create_case(survivor["id"])
    beam = document_damage(
        case["id"],
        category="STRUCTURE",
        item_description="Beam replacement",
        documented_cost_cents=1_000_000,
        photo_count=5,
    )
    verify_damage(beam["id"], verified_cost_cents=1_000_000)
    beds = document_damage(
        case["id"],
        category="CONTENTS",
        item_description="Beds and bedding",
        documented_cost_cents=400_000,
        photo_count=4,
        is_habitability_critical=False,
    )
    verify_damage(beds["id"], verified_cost_cents=400_000)
    source = create_funding_source(
        label="Structure-only grant",
        source_type="FOUNDATION_GRANT",
        restriction_code="STRUCTURE_REPAIR_ONLY",
        total_cents=1_000_000,
    )
    project = create_project(
        case["id"],
        required_trade_hours={"GENERAL_LABOR": 100},
        estimated_material_cents=300_000,
    )
    permit_project(project["id"], permit_number="PB-4061")
    contents_request = request_disbursement(
        case["id"], "CONTENTS_REPLACEMENT", 400_000, payee_name="Sleepwell Bedding"
    )
    structure_request = request_disbursement(
        case["id"],
        "STRUCTURE_REPAIR",
        300_000,
        payee_name="Beamworks LLC",
        project_id=project["id"],
    )
    for requested in (contents_request, structure_request):
        assert requested["status"] == "DOB_CLEARED"
        assert requested["dob_exposure_cents"] == 0

    wrong_purpose = api.approve_disbursement(
        contents_request["id"], {"approval_note": "Contents request."}, ADMIN
    )
    over_ceiling = api.approve_disbursement(
        structure_request["id"], {"approval_note": "Structure request."}, ADMIN
    )

    # No source can legally cover contents money, so the restriction gate speaks first.
    validate_error(wrong_purpose, ApiErrorId.ERR_RESTRICTION_MISMATCH.value, 422)
    # The structure request clears the restriction gate and falls to the next one, because
    # the table never awarded this case anything.
    validate_error(over_ceiling, ApiErrorId.ERR_DISBURSEMENT_EXCEEDS_COMMITMENT.value, 422)
    untouched = read_funding_source(source["id"])
    assert_funding_source(untouched)
    assert untouched["committed_cents"] == 0
    assert untouched["available_cents"] == 1_000_000
