"""Capabilities that stand slightly apart: crew and lodging records, computed reads and
the administrative actions that gate or retarget work already in flight.
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
    assert_disbursement,
    assert_dob_report,
    assert_follow_up_contact,
    assert_funding_commitment,
    assert_funding_source,
    assert_housing_assignment,
    assert_immutable_record,
    assert_lodging_site,
    assert_member_organization,
    assert_volunteer_group,
    create_case,
    create_funding_source,
    create_group,
    create_lodging_site,
    create_project,
    create_survivor,
    decide,
    document_damage,
    follow_up_payload,
    funding_commitment_payload,
    housing_assignment_payload,
    make_case_manager_headers,
    make_member_org_delegate_headers,
    open_session,
    present_and_deliberate,
    queue_presentation,
    read_funding_source,
    read_member_org,
    record_assistance,
    request_disbursement,
    run_assessment,
    schedule_session,
    seat_member_org,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    verify_damage,
    volunteer_group_payload,
)


def test_a_visiting_crew_round_trips_its_trade_roster(api):
    """PRD §3.8: "A `VolunteerCoordinator` registers a visiting group with a `group_name`,
    the sending `home_organization` — a congregation, employer or club — a `member_count` of
    at least 1 giving the number of volunteers travelling, and a `skill_profile` mapping
    trade code to the count of qualified members, drawn from the same trade vocabulary as a
    project's `required_trade_hours`."

    Design: Corner/endpoints/corner_volunteer_group_create_read_and_missing_id
    """
    set_clock()
    roster = {"ROOFING": 3, "DRYWALL": 4, "GENERAL_LABOR": 9}

    created = validate_success(
        api.create_volunteer_group(
            volunteer_group_payload(
                group_name="Group Tango",
                home_organization="Tango Baptist",
                member_count=9,
                skill_profile=roster,
                requires_housing=True,
                brings_own_tools=False,
            ),
            COORDINATOR,
        ),
        201,
    )

    assert_volunteer_group(created)
    assert created["member_count"] == 9
    assert created["skill_profile"] == roster
    assert created["requires_housing"] is True
    assert created["brings_own_tools"] is False
    assert created["version"] == 1
    stored = validate_success(api.get_volunteer_group(created["id"], BUILDER))
    assert stored == created
    missing = api.get_volunteer_group(NON_EXISTENT_UUID, COORDINATOR)
    validate_error(missing, ApiErrorId.ERR_VOLUNTEER_GROUP_NOT_FOUND.value, 404)


def test_hosting_a_crew_needs_a_site_that_exists(api):
    """PRD §3.8: "The server copies `beds_requested` from the group's `member_count` at
    creation and computes `night_count` as the number of days from check-in to check-out."

    Design: Corner/endpoints/corner_housing_assignment_links_a_group_to_a_site_and_both_must_exist
    """
    set_clock()
    site = create_lodging_site(
        site_name="Grange Hall", bed_capacity=10, has_showers=False
    )
    group = create_group(
        group_name="Group Uniform",
        home_organization="Uniform Methodist",
        member_count=4,
        skill_profile={"GENERAL_LABOR": 4},
        requires_housing=True,
        brings_own_tools=False,
    )

    unknown_site = api.create_housing_assignment(
        housing_assignment_payload(
            group["id"], NON_EXISTENT_UUID, "2026-09-07", "2026-09-10"
        ),
        COORDINATOR,
    )

    validate_error(unknown_site, ApiErrorId.ERR_LODGING_SITE_NOT_FOUND.value, 404)
    linked = validate_success(
        api.create_housing_assignment(
            housing_assignment_payload(
                group["id"], site["id"], "2026-09-07", "2026-09-10"
            ),
            COORDINATOR,
        ),
        201,
    )
    assert_housing_assignment(linked)
    assert linked["group_id"] == group["id"]
    assert linked["lodging_site_id"] == site["id"]
    assert linked["beds_requested"] == 4
    assert linked["night_count"] == 3
    assert linked["status"] == "ACTIVE"
    hosted, meta = validate_paginated(
        api.list_housing_assignments(COORDINATOR, params={"lodging_site_id": site["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in hosted] == [linked["id"]]
    ledger = validate_success(api.get_lodging_site(site["id"], COORDINATOR))
    assert_lodging_site(ledger)
    assert ledger["peak_committed_beds"] == 4
    assert ledger["available_beds"] == 6


def test_the_planning_read_and_the_real_request_see_the_same_household_money(api):
    """PRD §3.6: "It takes a `purpose_code` and an optional `requested_cents` to test
    against, and answers with `case_id`, `survivor_id`, `purpose_code`, `dob_pool_cents`,
    `prior_disbursed_cents`, `bucket_need_cents`, `dob_exposure_cents` and
    `sibling_case_ids`, the last being the ids of the non-`INACTIVE` cases that formed the
    pool."

    Design: Corner/endpoints/corner_dob_report_matches_the_disbursement_fork_across_sibling_cases
    """
    set_clock()
    survivor = create_survivor(
        household_name="Grieco Household",
        primary_contact_phone="555-0243",
        household_size=4,
        income_band="ELI",
        head_of_household_age=61,
    )
    target = create_case(survivor["id"], disaster_code="DR-4801")
    sibling = create_case(survivor["id"], disaster_code="DR-4802")
    item = document_damage(
        target["id"],
        category="STRUCTURE",
        item_description="Load-bearing wall",
        documented_cost_cents=1_000_000,
        photo_count=6,
    )
    verify_damage(item["id"], verified_cost_cents=1_000_000)
    record_assistance(
        target["id"],
        source_type="FEMA_IA",
        purpose_code="STRUCTURE_REPAIR",
        awarded_cents=300_000,
        received_on="2026-08-02",
        documentation_status="DOCUMENTED",
    )
    record_assistance(
        sibling["id"],
        source_type="NONPROFIT_GRANT",
        purpose_code="STRUCTURE_REPAIR",
        awarded_cents=500_000,
        received_on="2026-08-06",
        documentation_status="DOCUMENTED",
    )
    project = create_project(
        target["id"],
        required_trade_hours={"GENERAL_LABOR": 100},
        estimated_material_cents=300_000,
    )

    report = validate_success(
        api.get_dob_report(
            target["id"],
            OFFICER,
            params={"purpose_code": "STRUCTURE_REPAIR", "requested_cents": 300_000},
        )
    )

    assert_dob_report(report)
    # Both of the household's live cases feed the pool: 300000 here plus 500000 there.
    assert report["dob_pool_cents"] == 800_000
    assert report["prior_disbursed_cents"] == 0
    assert report["bucket_need_cents"] == 1_000_000
    assert report["dob_exposure_cents"] == 100_000
    assert set(report["sibling_case_ids"]) == {target["id"], sibling["id"]}
    requested = request_disbursement(
        target["id"],
        "STRUCTURE_REPAIR",
        300_000,
        payee_name="Ridgeline Contractors",
        project_id=project["id"],
    )
    assert_disbursement(requested)
    assert requested["status"] == "DOB_FLAGGED"
    assert requested["dob_pool_cents"] == 800_000
    assert requested["dob_exposure_cents"] == 100_000


def test_suspending_an_organization_silences_its_pledges_until_reinstatement(api):
    """PRD §3.4: "The pledging organization's `status` must be exactly `ACTIVE` — a
    `CAPPED`, `SUSPENDED` or `WITHDRAWN` organization may not pledge, and the attempt is
    refused with `ERR_MEMBER_ORG_NOT_ACTIVE`."

    Design: Corner/endpoints/corner_member_org_status_action_gates_and_ungates_pledging
    """
    set_clock()
    survivor = create_survivor(
        household_name="Hollander Household",
        primary_contact_phone="555-0244",
        household_size=3,
        income_band="VLI",
        head_of_household_age=49,
    )
    case = create_case(survivor["id"])
    item = document_damage(
        case["id"],
        category="STRUCTURE",
        item_description="Bathroom rebuild",
        documented_cost_cents=900_000,
        photo_count=4,
    )
    verify_damage(item["id"], verified_cost_cents=900_000)
    assessment = run_assessment(case["id"])
    org = seat_member_org(
        org_name="Suspendable Org",
        org_type="CIVIC_CLUB",
        contact_email="s@susp.example",
        annual_pledge_cap_cents=3_000_000,
    )
    session = schedule_session(session_label="UNT suspension gate", quorum_min_member_orgs=1)
    open_session(session["id"], [org["id"]])
    presentation = queue_presentation(
        case["id"], session["id"], assessment["id"], narrative="Bathroom rebuild request."
    )
    window = present_and_deliberate(presentation["id"])
    pledge_body = funding_commitment_payload(
        presentation["id"], org["id"], 400_000, window["version"]
    )
    delegate = make_member_org_delegate_headers(org["id"])

    suspended = validate_success(
        api.set_member_organization_status(
            org["id"], {"status": "SUSPENDED", "suspension_reason": "Audit pending."}, ADMIN
        )
    )

    assert_member_organization(suspended)
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == "Audit pending."
    # Suspension is administrative, not fiscal: the capacity is untouched.
    assert suspended["remaining_pledge_capacity_cents"] == 3_000_000
    silenced = api.create_funding_commitment(pledge_body, delegate)
    validate_error(silenced, ApiErrorId.ERR_MEMBER_ORG_NOT_ACTIVE.value, 409)
    reinstated = validate_success(
        api.set_member_organization_status(org["id"], {"status": "ACTIVE"}, ADMIN)
    )
    assert reinstated["status"] == "ACTIVE"
    accepted = validate_success(api.create_funding_commitment(pledge_body, delegate), 201)
    assert_funding_commitment(accepted)
    assert accepted["pledged_cents"] == 400_000
    credited = read_member_org(org["id"])
    assert credited["committed_cents"] == 400_000
    assert credited["remaining_pledge_capacity_cents"] == 2_600_000


def test_a_deferred_case_is_carried_onto_the_next_meeting(api):
    """PRD §3.5: "On success the presentation's `session_id` becomes the new session,
    `queue_position` is recomputed for every `QUEUED` presentation of both the old and the
    new session, `queued_count` increments on the new session and decrements on the old
    one, and the presentation's `version` increments."

    Design: Corner/endpoints/corner_requeue_moves_a_deferred_presentation_onto_another_session
    """
    set_clock()
    survivor = create_survivor(
        household_name="Ivarsson Household",
        primary_contact_phone="555-0245",
        household_size=2,
        income_band="LOW",
        head_of_household_age=44,
    )
    case = create_case(survivor["id"])
    item = document_damage(
        case["id"],
        category="STRUCTURE",
        item_description="Foundation pier",
        documented_cost_cents=800_000,
        photo_count=5,
    )
    verify_damage(item["id"], verified_cost_cents=800_000)
    assessment = run_assessment(case["id"])
    org = seat_member_org(
        org_name="Requeue Table Org",
        org_type="FAITH_BASED",
        contact_email="rq@table.example",
        annual_pledge_cap_cents=3_000_000,
    )
    first_session = schedule_session(
        session_label="UNT session one", scheduled_for="2026-09-10T15:00:00Z"
    )
    second_session = schedule_session(
        session_label="UNT session two", scheduled_for="2026-09-24T15:00:00Z"
    )
    open_session(first_session["id"], [org["id"]])
    presentation = queue_presentation(
        case["id"], first_session["id"], assessment["id"], narrative="Foundation repair."
    )
    present_and_deliberate(presentation["id"])
    deferred = decide(
        presentation["id"], "DEFER", decision_note="Awaiting a contractor bid."
    )
    assert deferred["status"] == "DEFERRED"
    assert deferred["deferral_count"] == 1

    requeued = validate_success(
        api.requeue_case_presentation(
            presentation["id"], {"new_session_id": second_session["id"]}, CASE_MANAGER
        )
    )

    assert requeued["session_id"] == second_session["id"]
    assert requeued["status"] == "QUEUED"
    assert requeued["queue_position"] == 1
    assert requeued["deferral_count"] == 1
    emptied = validate_success(api.get_table_session(first_session["id"], CHAIR))
    assert emptied["queued_count"] == 0
    carried, meta = validate_paginated(
        api.list_case_presentations(CHAIR, params={"session_id": second_session["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in carried] == [presentation["id"]]


def test_abandoning_an_unapproved_payment_reserves_nothing(api):
    """PRD §3.6: "Voiding is declared from two source states with identical effects:
    `DOB_FLAGGED → VOIDED` and `DOB_CLEARED → VOIDED`. No funding source or case money
    field changes, because nothing was ever reserved."

    Design: Corner/endpoints/corner_void_is_allowed_only_before_approval_and_touches_no_funding_source
    """
    set_clock()
    survivor = create_survivor(
        household_name="Jelinek Household",
        primary_contact_phone="555-0246",
        household_size=2,
        income_band="LOW",
        head_of_household_age=46,
    )
    case = create_case(survivor["id"])
    item = document_damage(
        case["id"],
        category="STRUCTURE",
        item_description="Stair rebuild",
        documented_cost_cents=1_000_000,
        photo_count=4,
    )
    verify_damage(item["id"], verified_cost_cents=1_000_000)
    source = create_funding_source(
        label="General fund",
        source_type="INDIVIDUAL_DONATION",
        restriction_code="UNRESTRICTED",
        total_cents=1_000_000,
    )
    project = create_project(
        case["id"],
        required_trade_hours={"GENERAL_LABOR": 120},
        estimated_material_cents=400_000,
    )
    requested = request_disbursement(
        case["id"],
        "STRUCTURE_REPAIR",
        400_000,
        payee_name="Stairworks Inc",
        project_id=project["id"],
    )
    assert requested["status"] == "DOB_CLEARED"
    assert requested["dob_exposure_cents"] == 0
    assert requested["allocation_lines"] == []

    voided = validate_success(
        api.void_disbursement(
            requested["id"], {"void_reason": "Contractor withdrew the invoice."}, OFFICER
        )
    )

    assert_disbursement(voided)
    assert voided["status"] == "VOIDED"
    untouched = read_funding_source(source["id"])
    assert_funding_source(untouched)
    assert untouched["committed_cents"] == 0
    assert untouched["disbursed_cents"] == 0
    assert untouched["available_cents"] == 1_000_000
    assert untouched["status"] == "OPEN"
    second_void = api.void_disbursement(
        requested["id"], {"void_reason": "Duplicate void attempt."}, OFFICER
    )
    validate_error(second_void, ApiErrorId.ERR_DISBURSEMENT_INVALID_STATE.value, 409)


def test_follow_up_contacts_are_stamped_by_their_caller_and_filterable(api):
    """PRD §3.9: "The server stamps `recorded_by_user_id` from the acting identity. Contact
    records are immutable once written and, per §2.4, carry only `id` and `created_at`. They
    can be listed for a case and filtered by `contact_type`."

    Design: Corner/endpoints/corner_follow_up_contacts_are_logged_and_filterable_by_type
    """
    set_clock()
    survivor = create_survivor(
        household_name="Kaminski Household",
        primary_contact_phone="555-0247",
        household_size=2,
        income_band="LOW",
        head_of_household_age=68,
    )
    case = create_case(survivor["id"])
    # A relief case manager covering the caseload, not the manager named on the case.
    covering = make_case_manager_headers("u_cm_9")

    check_in = validate_success(
        api.create_follow_up(
            case["id"],
            follow_up_payload(
                contact_type="CHECK_IN_30_DAY",
                contacted_on="2026-09-01",
                outcome="REACHED",
                notes="Household is stable in temporary housing.",
            ),
            covering,
        ),
        201,
    )
    review = validate_success(
        api.create_follow_up(
            case["id"],
            follow_up_payload(
                contact_type="CLOSURE_REVIEW",
                contacted_on="2026-09-01",
                outcome="REACHED",
                notes="Reviewed the closure checklist with the survivor.",
            ),
            covering,
        ),
        201,
    )

    for contact in (check_in, review):
        assert_follow_up_contact(contact)
        assert_immutable_record(contact)
        assert contact["recorded_by_user_id"] == "u_cm_9"
    filtered, filtered_meta = validate_paginated(
        api.list_follow_ups(
            case["id"], CASE_MANAGER, params={"contact_type": "CLOSURE_REVIEW"}
        )
    )
    assert filtered_meta["total_count"] == 1
    assert [row["id"] for row in filtered] == [review["id"]]
    everything, all_meta = validate_paginated(
        api.list_follow_ups(case["id"], CASE_MANAGER)
    )
    assert all_meta["total_count"] == 2
    assert {row["id"] for row in everything} == {check_in["id"], review["id"]}
