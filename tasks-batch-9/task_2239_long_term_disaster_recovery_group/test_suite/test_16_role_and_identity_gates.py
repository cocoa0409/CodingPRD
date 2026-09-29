"""Who may act, and in whose name.

Two questions are kept strictly apart here: whether the caller is recognized at all, and
whether the recognized caller is allowed on this endpoint. A third group of tests turns on
the acting user identity alone, with the role held constant.
"""

from test_helpers import (
    ADMIN,
    BUILDER,
    CASE_MANAGER,
    CHAIR,
    COORDINATOR,
    INTAKE,
    OFFICER,
    ApiErrorId,
    assert_case_presentation,
    assert_construction_project,
    assert_damage_item,
    assert_disbursement,
    assert_follow_up_contact,
    assert_funding_commitment,
    assert_funding_source,
    assert_housing_assignment,
    assert_lodging_site,
    assert_member_organization,
    assert_recovery_case,
    assert_survivor,
    assert_table_session,
    assert_unmet_need_assessment,
    assert_volunteer_deployment,
    assert_volunteer_group,
    assistance_record_payload,
    case_presentation_payload,
    case_version,
    construction_project_payload,
    create_case,
    create_survivor,
    damage_item_payload,
    disbursement_payload,
    document_damage,
    follow_up_payload,
    funding_commitment_payload,
    funding_source_payload,
    housing_assignment_payload,
    lodging_site_payload,
    make_admin_headers,
    make_case_manager_headers,
    make_chair_headers,
    make_member_org_delegate_headers,
    make_raw_headers,
    member_organization_payload,
    permit_project,
    read_case,
    recovery_case_payload,
    run_assessment,
    schedule_session,
    seat_member_org,
    set_clock,
    survivor_payload,
    table_session_payload,
    validate_error,
    validate_paginated,
    validate_success,
    verification_payload,
    verify_damage,
    volunteer_deployment_payload,
    volunteer_group_payload,
)


def test_an_unrecognized_caller_is_turned_away_before_anything_else(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the eight role
    names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers
    are well-formed but the declared role is not among the roles authorized for the requested
    endpoint, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/rbac/corner_requests_without_a_recognized_role_header_are_unauthenticated
    """
    set_clock()
    body = survivor_payload(
        household_name="Headerless Household",
        primary_contact_phone="555-0301",
        household_size=3,
        income_band="LOW",
        head_of_household_age=40,
    )

    no_headers = api.create_survivor(body, make_raw_headers())
    unknown_role = api.create_survivor(body, make_raw_headers("u_grants_1", "GrantWriter"))
    no_user_id = api.create_survivor(body, make_raw_headers(role="IntakeSpecialist"))

    validate_error(no_headers, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    # An unrecognized role name is an authentication failure, not a permission one.
    validate_error(unknown_role, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    validate_error(no_user_id, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    accepted = validate_success(api.create_survivor(body, INTAKE), 201)
    assert_survivor(accepted)
    assert accepted["priority_score"] == 28
    assert accepted["open_case_count"] == 0


def test_a_recognized_role_is_still_barred_from_another_roles_writes(api):
    """PRD §2.1: "Authentication is always evaluated before authorization, and both precede
    any inspection of the request body." The endpoint tables of §4 name the roles authorized
    on each write, and §2.11 places authorization at rung 2, ahead of resource existence at
    rungs 4 and 5 and optimistic concurrency at rung 20.

    Design: Corner/rbac/corner_each_role_is_refused_another_roles_exclusive_write
    """
    set_clock()
    survivor = create_survivor(
        household_name="Roleprobe Household",
        primary_contact_phone="555-0302",
        household_size=2,
        income_band="VLI",
        head_of_household_age=44,
    )
    case = create_case(survivor["id"], primary_residence_status="RENTER")
    item = document_damage(
        case["id"],
        category="CONTENTS",
        item_description="Kitchen contents",
        documented_cost_cents=300_000,
        photo_count=3,
        is_habitability_critical=False,
    )
    live_version = case_version(case["id"])
    unknown = "11111111-1111-4111-8111-111111111111"

    probes = [
        api.create_damage_item(
            case["id"],
            damage_item_payload(
                category="CONTENTS",
                item_description="Intake tries to document damage",
                documented_cost_cents=100_000,
                photo_count=1,
                is_habitability_critical=False,
            ),
            INTAKE,
        ),
        # Carries an id that resolves to nothing, and must still be a role refusal.
        api.present_case_presentation(unknown, {}, CASE_MANAGER),
        api.rescind_funding_commitment(
            unknown, {"rescission_reason": "Chair tries to rescind a delegate pledge."}, CHAIR
        ),
        api.create_disbursement(
            disbursement_payload(
                case["id"],
                100_000,
                live_version,
                payee_name="Delegate tries to request a payment",
            ),
            make_member_org_delegate_headers("u_org_1"),
        ),
        api.verify_damage_item(item["id"], verification_payload(verified_cost_cents=300_000), OFFICER),
        api.create_volunteer_group(
            volunteer_group_payload(
                group_name="Construction tries to register a group",
                home_organization="Somewhere Church",
                member_count=4,
                skill_profile={"GENERAL_LABOR": 4},
            ),
            BUILDER,
        ),
        api.create_funding_source(
            funding_source_payload(label="Coordinator tries to assemble funding"), COORDINATOR
        ),
        api.approve_disbursement(unknown, {"approval_note": "Officer tries to approve."}, OFFICER),
    ]

    for probe in probes:
        validate_error(probe, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value, 403)
    control = validate_success(
        api.create_damage_item(
            case["id"],
            damage_item_payload(
                category="CONTENTS",
                item_description="Case manager documents the second item",
                documented_cost_cents=100_000,
                photo_count=2,
                is_habitability_critical=False,
            ),
            CASE_MANAGER,
        ),
        201,
    )
    assert_damage_item(control)
    assert control["verification_status"] == "UNVERIFIED"
    documented, meta = validate_paginated(api.list_damage_items(case["id"], CASE_MANAGER))
    # Two items exist: the setup row and the control. The refused writes persisted nothing.
    assert meta["total_count"] == 2
    assert {row["id"] for row in documented} == {item["id"], control["id"]}


def test_the_casework_roles_each_own_their_own_step(api):
    """PRD §2.1: "A `CaseManager` owns a case: documenting damage, recording outside
    assistance, running determinations, queueing the case at the table, requeueing a deferred
    presentation, logging follow-up contacts, and driving closure review." Alongside it, "An
    `IntakeSpecialist` takes survivor intake and opens recovery cases." and "A
    `ConstructionManager` verifies documented damage costs by inspection and drives repair and
    rebuild phases through their lifecycle."

    Design: Corner/rbac/corner_intake_case_and_construction_roles_perform_their_own_exclusive_writes
    """
    set_clock()

    household = validate_success(
        api.create_survivor(
            survivor_payload(
                household_name="Alvarado Household",
                primary_contact_phone="555-0303",
                household_size=3,
                income_band="LOW",
                head_of_household_age=40,
            ),
            INTAKE,
        ),
        201,
    )
    case = validate_success(
        api.create_recovery_case(recovery_case_payload(household["id"]), INTAKE), 201
    )

    assert_survivor(household)
    assert household["priority_score"] == 28
    assert_recovery_case(case)
    assert case["case_status"] == "INTAKE"
    assert case["funding_status"] == "UNFUNDED"
    documented = validate_success(
        api.create_damage_item(
            case["id"],
            damage_item_payload(
                category="ROOF",
                item_description="Shingles and decking",
                documented_cost_cents=900_000,
                photo_count=6,
            ),
            CASE_MANAGER,
        ),
        201,
    )
    assert documented["verification_status"] == "UNVERIFIED"
    inspected = validate_success(
        api.verify_damage_item(
            documented["id"], verification_payload(verified_cost_cents=900_000), BUILDER
        )
    )
    assert inspected["verification_status"] == "VERIFIED"
    assert inspected["verified_cost_cents"] == 900_000
    assistance = validate_success(
        api.create_assistance_record(
            case["id"],
            assistance_record_payload(
                source_type="INSURANCE_SETTLEMENT",
                awarded_cents=200_000,
                received_on="2026-07-30",
            ),
            CASE_MANAGER,
        ),
        201,
    )
    assert assistance["documentation_status"] == "DOCUMENTED"
    determination = validate_success(
        api.create_assessment(case["id"], {"variant": "PURPOSE_MATCHED"}, CASE_MANAGER), 201
    )
    assert_unmet_need_assessment(determination)
    assert determination["verified_damage_total_cents"] == 900_000
    assert determination["total_documented_assistance_cents"] == 200_000
    assert determination["unmet_need_total_cents"] == 700_000
    project = validate_success(
        api.create_construction_project(
            construction_project_payload(
                case["id"],
                scope_code="ROOF_REPLACEMENT",
                required_trade_hours={"ROOFING": 120},
                estimated_material_cents=400_000,
            ),
            BUILDER,
        ),
        201,
    )
    assert_construction_project(project)
    assert project["status"] == "SCOPED"
    permitted = validate_success(
        api.transition_construction_project(
            project["id"], {"action": "PERMIT", "permit_number": "PB-4064"}, BUILDER
        )
    )
    assert permitted["status"] == "PERMITTED"
    contact = validate_success(
        api.create_follow_up(
            case["id"],
            follow_up_payload(
                contacted_on="2026-09-01", notes="Intake complete, determination run."
            ),
            CASE_MANAGER,
        ),
        201,
    )
    assert_follow_up_contact(contact)
    assert contact["contact_type"] == "CHECK_IN_30_DAY"
    assert contact["outcome"] == "REACHED"
    assessed = read_case(case["id"])
    assert assessed["case_status"] == "ASSESSED"
    assert assessed["verified_damage_total_cents"] == 900_000


def test_the_table_and_money_roles_each_own_their_own_step(api):
    """PRD §2.1: "An `UnmetNeedsChair` chairs the unmet needs table: scheduling and opening
    sessions, calling presentations, opening the pledge window, and recording the award,
    deferral or denial." Alongside it, "A `MemberOrgDelegate` speaks for one seated member
    organization, pledging and rescinding only on that organization's behalf." and "A
    `DisbursementOfficer` requests assistance payments, resolves duplication-of-benefits
    findings, pays approved payments and voids requests that were never approved."

    Design: Corner/rbac/corner_table_and_money_roles_perform_their_own_exclusive_writes
    """
    set_clock()
    survivor = create_survivor(
        household_name="Nakamura Household",
        primary_contact_phone="555-0304",
        household_size=4,
        income_band="ELI",
        head_of_household_age=66,
        is_uninsured=True,
    )
    case = create_case(survivor["id"])
    item = document_damage(
        case["id"],
        category="STRUCTURE",
        item_description="Load-bearing wall",
        documented_cost_cents=1_000_000,
        photo_count=8,
    )
    verify_damage(item["id"], verified_cost_cents=1_000_000)
    assessment = run_assessment(case["id"])
    project = validate_success(
        api.create_construction_project(
            construction_project_payload(
                case["id"],
                scope_code="STRUCTURE_REBUILD",
                required_trade_hours={"FRAMING": 160},
                estimated_material_cents=700_000,
            ),
            BUILDER,
        ),
        201,
    )
    permit_project(project["id"], permit_number="PB-4065")

    org = validate_success(
        api.create_member_organization(
            member_organization_payload(
                org_name="Coastal Interfaith Alliance",
                org_type="FAITH_BASED",
                contact_email="table@coastal.example",
                annual_pledge_cap_cents=3_000_000,
            ),
            ADMIN,
        ),
        201,
    )
    source = validate_success(
        api.create_funding_source(
            funding_source_payload(
                label="Rebuild grant M",
                source_type="FOUNDATION_GRANT",
                restriction_code="STRUCTURE_REPAIR_ONLY",
                total_cents=1_000_000,
                admin_retention_allowed=False,
            ),
            ADMIN,
        ),
        201,
    )

    assert_member_organization(org)
    assert org["status"] == "ACTIVE"
    assert org["remaining_pledge_capacity_cents"] == 3_000_000
    assert_funding_source(source)
    assert source["status"] == "OPEN"
    assert source["available_cents"] == 1_000_000
    session = validate_success(
        api.create_table_session(
            table_session_payload(session_label="UNT role coverage"), CHAIR
        ),
        201,
    )
    opened = validate_success(
        api.open_table_session(
            session["id"], {"attending_member_org_ids": [org["id"]]}, CHAIR
        )
    )
    assert_table_session(opened)
    assert opened["status"] == "IN_SESSION"
    presentation = validate_success(
        api.create_case_presentation(
            case_presentation_payload(
                case["id"],
                session["id"],
                assessment["id"],
                narrative="Load-bearing wall rebuild.",
            ),
            CASE_MANAGER,
        ),
        201,
    )
    assert_case_presentation(presentation)
    called = validate_success(api.present_case_presentation(presentation["id"], {}, CHAIR))
    assert called["status"] == "PRESENTING"
    window = validate_success(api.deliberate_case_presentation(presentation["id"], {}, CHAIR))
    assert window["status"] == "DELIBERATING"
    commitment = validate_success(
        api.create_funding_commitment(
            funding_commitment_payload(
                presentation["id"], org["id"], 1_000_000, window["version"]
            ),
            make_member_org_delegate_headers(org["id"]),
        ),
        201,
    )
    assert_funding_commitment(commitment)
    assert commitment["status"] == "PLEDGED"
    assert commitment["pledged_cents"] == 1_000_000
    assert commitment["pledged_by_user_id"] == org["id"]
    awarded = validate_success(
        api.decide_case_presentation(
            presentation["id"],
            {"decision": "AWARD", "decision_note": "Fully pledged by the alliance."},
            CHAIR,
        )
    )
    assert awarded["bridge_tier"] == "TIER_B"
    # The only source is restricted, so the unrestricted bridge pool is empty.
    assert awarded["bridge_authorized_cents"] == 0
    assert awarded["awarded_cents"] == 1_000_000
    assert awarded["shortfall_cents"] == 0
    assert awarded["decided_by_user_id"] == CHAIR["X-User-ID"]
    requested = validate_success(
        api.create_disbursement(
            disbursement_payload(
                case["id"],
                1_000_000,
                case_version(case["id"]),
                purpose_code="STRUCTURE_REPAIR",
                project_id=project["id"],
                commitment_id=commitment["id"],
                payee_name="Cedarline Framing LLC",
            ),
            OFFICER,
        ),
        201,
    )
    assert_disbursement(requested)
    assert requested["status"] == "DOB_CLEARED"
    assert requested["dob_exposure_cents"] == 0
    assert requested["requested_by_user_id"] == OFFICER["X-User-ID"]
    approved = validate_success(
        api.approve_disbursement(
            requested["id"], {"approval_note": "Approved by the administrator."}, ADMIN
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == ADMIN["X-User-ID"]
    assert [line["funding_source_id"] for line in approved["allocation_lines"]] == [source["id"]]
    assert approved["net_cents"] == 1_000_000
    assert approved["admin_retained_cents"] == 0
    assert approved["gross_cents"] == 1_000_000
    paid = validate_success(
        api.pay_disbursement(requested["id"], {"payment_reference": "CHK-6501"}, OFFICER)
    )
    assert paid["status"] == "PAID"
    settled = read_case(case["id"])
    assert settled["funding_status"] == "SATISFIED"
    assert settled["total_committed_cents"] == 1_000_000
    assert settled["total_net_disbursed_cents"] == 1_000_000
    assert settled["case_status"] == "ACTIVE_RECOVERY"


def test_the_volunteer_coordinator_owns_the_whole_hosting_chain(api):
    """PRD §2.1: "A `VolunteerCoordinator` registers volunteer groups and lodging sites,
    matches skills to project needs, deploys crews and hosts them."

    Design: Corner/rbac/corner_volunteer_coordinator_performs_its_own_exclusive_writes
    """
    set_clock()
    survivor = create_survivor(
        household_name="Delacroix Household",
        primary_contact_phone="555-0305",
        household_size=2,
        income_band="VLI",
        head_of_household_age=47,
    )
    case = create_case(survivor["id"])
    project = validate_success(
        api.create_construction_project(
            construction_project_payload(
                case["id"],
                required_trade_hours={"GENERAL_LABOR": 180},
                estimated_material_cents=250_000,
            ),
            BUILDER,
        ),
        201,
    )
    permit_project(project["id"], permit_number="PB-4066")

    group = validate_success(
        api.create_volunteer_group(
            volunteer_group_payload(
                group_name="Bayou Rebuild Crew",
                home_organization="Riverside Fellowship",
                member_count=6,
                skill_profile={"GENERAL_LABOR": 6},
                requires_housing=True,
            ),
            COORDINATOR,
        ),
        201,
    )
    site = validate_success(
        api.create_lodging_site(
            lodging_site_payload(site_name="Riverside Fellowship Hall", bed_capacity=10),
            COORDINATOR,
        ),
        201,
    )
    stay = validate_success(
        api.create_housing_assignment(
            housing_assignment_payload(group["id"], site["id"], "2026-09-07", "2026-09-11"),
            COORDINATOR,
        ),
        201,
    )
    booking = validate_success(
        api.create_volunteer_deployment(
            volunteer_deployment_payload(
                group["id"], project["id"], "2026-09-07", "2026-09-11"
            ),
            COORDINATOR,
        ),
        201,
    )

    assert_volunteer_group(group)
    assert group["member_count"] == 6
    assert group["active_deployment_count"] == 0
    assert_housing_assignment(stay)
    assert stay["status"] == "ACTIVE"
    assert stay["night_count"] == 4
    assert stay["beds_requested"] == 6
    assert_volunteer_deployment(booking)
    assert booking["status"] == "REQUESTED"
    assert booking["day_count"] == 5
    # Six labourers over five days cover all 180 required hours.
    assert booking["skill_fit_score_bps"] == 10000
    confirmed = validate_success(
        api.transition_volunteer_deployment(booking["id"], {"action": "CONFIRM"}, COORDINATOR)
    )
    assert confirmed["status"] == "CONFIRMED"
    released = validate_success(
        api.release_housing_assignment(
            stay["id"], {"release_reason": "Crew departed a night early."}, COORDINATOR
        )
    )
    assert released["status"] == "RELEASED"
    assert released["released_at"] is not None
    freed = validate_success(api.get_lodging_site(site["id"], COORDINATOR))
    assert_lodging_site(freed)
    assert freed["peak_committed_beds"] == 0
    assert freed["available_beds"] == 10
    assert freed["status"] == "OPEN"


def test_the_administrator_may_stand_in_for_every_other_role(api):
    """PRD §2.1: "`LTRGAdmin` is authorized on the entire write surface of the other seven
    roles, with one carve-out — segregation of duties still bars an `LTRGAdmin` from approving
    a disbursement they themselves requested."

    Design: Corner/rbac/corner_admin_may_stand_in_for_the_other_roles_exclusive_writes
    """
    set_clock()

    household = validate_success(
        api.create_survivor(
            survivor_payload(
                household_name="Adminpath Household",
                primary_contact_phone="555-0306",
                household_size=1,
                income_band="MODERATE",
                head_of_household_age=71,
                has_member_with_disability=True,
                follow_up_opt_in=False,
            ),
            ADMIN,
        ),
        201,
    )

    assert_survivor(household)
    # MODERATE 10, nothing for a single-member household, disability 15, elder 10 at 71.
    assert household["priority_score"] == 35
    case = validate_success(
        api.create_recovery_case(
            recovery_case_payload(
                household["id"],
                assigned_case_manager_user_id=ADMIN["X-User-ID"],
                primary_residence_status="MOBILE_HOME",
            ),
            ADMIN,
        ),
        201,
    )
    assert_recovery_case(case)
    item = validate_success(
        api.create_damage_item(
            case["id"],
            damage_item_payload(
                category="ACCESSIBILITY",
                item_description="Ramp and grab bars",
                documented_cost_cents=500_000,
                photo_count=4,
            ),
            ADMIN,
        ),
        201,
    )
    inspected = validate_success(
        api.verify_damage_item(
            item["id"], verification_payload(verified_cost_cents=500_000), ADMIN
        )
    )
    assert inspected["verification_status"] == "VERIFIED"
    determination = validate_success(
        api.create_assessment(case["id"], {"variant": "PURPOSE_MATCHED"}, ADMIN), 201
    )
    assert_unmet_need_assessment(determination)
    assert determination["unmet_need_total_cents"] == 500_000
    assert determination["bucket_need_cents"]["ACCESSIBILITY_MOD"] == 500_000
    crew = validate_success(
        api.create_volunteer_group(
            volunteer_group_payload(
                group_name="Admin-registered Crew",
                home_organization="LTRG Staff",
                member_count=3,
                skill_profile={"GENERAL_LABOR": 3},
            ),
            ADMIN,
        ),
        201,
    )
    assert_volunteer_group(crew)
    contact = validate_success(
        api.create_follow_up(
            case["id"],
            follow_up_payload(
                contact_type="ANNIVERSARY",
                contacted_on="2026-09-01",
                outcome="NO_ANSWER",
                notes="Left a voicemail.",
            ),
            ADMIN,
        ),
        201,
    )
    assert_follow_up_contact(contact)
    assert contact["contact_type"] == "ANNIVERSARY"
    assert contact["outcome"] == "NO_ANSWER"


def test_the_chair_may_not_decide_the_case_they_manage(api):
    """PRD §2.7: "First, at the table: the chair recording a decision on a presentation must
    not be the case's assigned case manager. The acting `X-User-ID` is compared against the
    `assigned_case_manager_user_id` of the presented case, and equality is refused. This
    applies to all three decision branches — award, deferral and denial alike."

    Design: Corner/rbac/corner_chair_may_not_decide_a_case_they_manage
    """
    set_clock()
    survivor = create_survivor(
        household_name="Petrosyan Household",
        primary_contact_phone="555-0307",
        household_size=3,
        income_band="VLI",
        head_of_household_age=49,
    )
    case = create_case(survivor["id"])
    item = document_damage(
        case["id"],
        category="STRUCTURE",
        item_description="Rear addition",
        documented_cost_cents=800_000,
        photo_count=5,
    )
    verify_damage(item["id"], verified_cost_cents=800_000)
    assessment = run_assessment(case["id"])
    org = seat_member_org(
        org_name="Segregation Table Org",
        org_type="CIVIC_CLUB",
        contact_email="sod@table.example",
        annual_pledge_cap_cents=1_000_000,
    )
    validate_success(
        api.create_funding_source(
            funding_source_payload(
                label="Bridge pool for the segregation case", total_cents=1_000_000
            ),
            ADMIN,
        ),
        201,
    )
    session = schedule_session(session_label="UNT segregation of duties")
    validate_success(
        api.open_table_session(
            session["id"], {"attending_member_org_ids": [org["id"]]}, CHAIR
        )
    )
    presentation = validate_success(
        api.create_case_presentation(
            case_presentation_payload(
                case["id"], session["id"], assessment["id"], narrative="Rear addition rebuild."
            ),
            CASE_MANAGER,
        ),
        201,
    )
    validate_success(api.present_case_presentation(presentation["id"], {}, CHAIR))
    validate_success(api.deliberate_case_presentation(presentation["id"], {}, CHAIR))
    decision = {"decision": "AWARD", "decision_note": "Case manager tries to chair their own case."}

    own_case = api.decide_case_presentation(
        presentation["id"], decision, make_chair_headers(CASE_MANAGER["X-User-ID"])
    )

    # The role is right; only the acting identity is wrong.
    validate_error(own_case, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    untouched = validate_success(api.get_case_presentation(presentation["id"], CHAIR))
    assert untouched["status"] == "DELIBERATING"
    assert untouched["awarded_cents"] == 0
    assert untouched["decided_by_user_id"] is None
    assert untouched["decided_at"] is None
    awarded = validate_success(
        api.decide_case_presentation(
            presentation["id"],
            {"decision": "AWARD", "decision_note": "Independent chair awards the bridge."},
            CHAIR,
        )
    )
    assert awarded["status"] == "AWARDED"
    assert awarded["bridge_tier"] == "TIER_B"
    # No pledges, so the whole award is the 30 percent bridge cap on 800000.
    assert awarded["bridge_authorized_cents"] == 240_000
    assert awarded["awarded_cents"] == 240_000
    assert awarded["shortfall_cents"] == 560_000
    assert awarded["decided_by_user_id"] == CHAIR["X-User-ID"]


def test_the_administrator_may_not_approve_their_own_request(api):
    """PRD §2.7: "Second, at the till: the administrator approving a disbursement must not be
    the officer who requested it. The acting `X-User-ID` is compared against the
    disbursement's `requested_by_user_id`, and equality is refused. This holds even for an
    `LTRGAdmin`, whose broad authority does not exempt them."

    Design: Corner/rbac/corner_administrator_may_not_approve_the_payment_they_requested
    """
    set_clock()
    survivor = create_survivor(
        household_name="Oyelaran Household",
        primary_contact_phone="555-0308",
        household_size=4,
        income_band="ELI",
        head_of_household_age=52,
        is_uninsured=True,
    )
    case = create_case(survivor["id"])
    item = document_damage(
        case["id"],
        category="STRUCTURE",
        item_description="Foundation piers",
        documented_cost_cents=1_000_000,
        photo_count=7,
    )
    verify_damage(item["id"], verified_cost_cents=1_000_000)
    assessment = run_assessment(case["id"])
    org = seat_member_org(
        org_name="Piers Fund Partner",
        org_type="FOUNDATION",
        contact_email="piers@fund.example",
        annual_pledge_cap_cents=2_000_000,
    )
    source = validate_success(
        api.create_funding_source(
            funding_source_payload(
                label="Foundation piers grant",
                source_type="FOUNDATION_GRANT",
                restriction_code="STRUCTURE_REPAIR_ONLY",
                total_cents=1_000_000,
                admin_retention_allowed=False,
            ),
            ADMIN,
        ),
        201,
    )
    session = schedule_session(session_label="UNT approver segregation")
    validate_success(
        api.open_table_session(
            session["id"], {"attending_member_org_ids": [org["id"]]}, CHAIR
        )
    )
    presentation = validate_success(
        api.create_case_presentation(
            case_presentation_payload(
                case["id"],
                session["id"],
                assessment["id"],
                narrative="Foundation pier replacement.",
            ),
            CASE_MANAGER,
        ),
        201,
    )
    validate_success(api.present_case_presentation(presentation["id"], {}, CHAIR))
    window = validate_success(api.deliberate_case_presentation(presentation["id"], {}, CHAIR))
    commitment = validate_success(
        api.create_funding_commitment(
            funding_commitment_payload(
                presentation["id"], org["id"], 1_000_000, window["version"]
            ),
            make_member_org_delegate_headers(org["id"]),
        ),
        201,
    )
    validate_success(
        api.decide_case_presentation(
            presentation["id"], {"decision": "AWARD", "decision_note": "Fully pledged."}, CHAIR
        )
    )
    project = validate_success(
        api.create_construction_project(
            construction_project_payload(
                case["id"],
                scope_code="STRUCTURE_REBUILD",
                required_trade_hours={"FRAMING": 140},
                estimated_material_cents=600_000,
            ),
            BUILDER,
        ),
        201,
    )
    permit_project(project["id"], permit_number="PB-4069")
    requested = validate_success(
        api.create_disbursement(
            disbursement_payload(
                case["id"],
                1_000_000,
                case_version(case["id"]),
                purpose_code="STRUCTURE_REPAIR",
                project_id=project["id"],
                commitment_id=commitment["id"],
                payee_name="Pierworks Foundations LLC",
            ),
            ADMIN,
        ),
        201,
    )
    assert requested["requested_by_user_id"] == ADMIN["X-User-ID"]
    assert requested["status"] == "DOB_CLEARED"

    self_approval = api.approve_disbursement(
        requested["id"], {"approval_note": "Requester tries to approve their own request."}, ADMIN
    )

    validate_error(self_approval, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    untouched = validate_success(api.get_disbursement(requested["id"], OFFICER))
    assert untouched["status"] == "DOB_CLEARED"
    assert untouched["allocation_lines"] == []
    assert untouched["net_cents"] == 0
    assert untouched["approved_by_user_id"] is None
    approved = validate_success(
        api.approve_disbursement(
            requested["id"],
            {"approval_note": "Second administrator approves."},
            make_admin_headers("u_admin_2"),
        )
    )
    assert_disbursement(approved)
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == "u_admin_2"
    assert approved["net_cents"] == 1_000_000
    assert approved["admin_retained_cents"] == 0
    assert approved["gross_cents"] == 1_000_000
    drawn = validate_success(api.get_funding_source(source["id"], make_admin_headers("u_admin_2")))
    assert drawn["committed_cents"] == 1_000_000
    assert drawn["available_cents"] == 0
    assert drawn["status"] == "EXHAUSTED"


def test_the_preparer_must_be_both_the_caller_and_the_assigned_manager(api):
    """PRD §2.7: "When a presentation is queued, the `prepared_by_user_id` in the request must
    equal both the acting `X-User-ID` and the case's `assigned_case_manager_user_id`; if
    either equality fails, the request is rejected with `ERR_CASE_MANAGER_MISMATCH` (HTTP
    403)."

    Design: Corner/rbac/corner_presentation_preparer_must_be_both_the_actor_and_the_assigned_case_manager
    """
    set_clock()
    survivor = create_survivor(
        household_name="Standin Household",
        primary_contact_phone="555-0309",
        household_size=2,
        income_band="LOW",
        head_of_household_age=38,
    )
    case = create_case(survivor["id"], primary_residence_status="RENTER")
    item = document_damage(
        case["id"],
        category="CONTENTS",
        item_description="Furniture and appliances",
        documented_cost_cents=700_000,
        photo_count=4,
        is_habitability_critical=False,
    )
    verify_damage(item["id"], verified_cost_cents=700_000)
    assessment = run_assessment(case["id"])
    session = schedule_session(session_label="UNT preparer identity")
    stand_in = make_case_manager_headers("u_cm_2")

    honest_stand_in = api.create_case_presentation(
        case_presentation_payload(
            case["id"],
            session["id"],
            assessment["id"],
            prepared_by_user_id="u_cm_2",
            narrative="Stand-in manager names themselves.",
        ),
        stand_in,
    )
    naming_a_colleague = api.create_case_presentation(
        case_presentation_payload(
            case["id"],
            session["id"],
            assessment["id"],
            prepared_by_user_id="u_cm_2",
            narrative="Assigned manager names a colleague.",
        ),
        CASE_MANAGER,
    )

    # Matches the caller but not the case's assigned manager.
    validate_error(honest_stand_in, ApiErrorId.ERR_CASE_MANAGER_MISMATCH.value, 403)
    # Matches neither half.
    validate_error(naming_a_colleague, ApiErrorId.ERR_CASE_MANAGER_MISMATCH.value, 403)
    queued = validate_success(
        api.create_case_presentation(
            case_presentation_payload(
                case["id"],
                session["id"],
                assessment["id"],
                narrative="Assigned manager names themselves.",
            ),
            CASE_MANAGER,
        ),
        201,
    )
    assert_case_presentation(queued)
    assert queued["status"] == "QUEUED"
    assert queued["queue_position"] == 1
    assert queued["prepared_by_user_id"] == CASE_MANAGER["X-User-ID"]
    assert queued["priority_score_snapshot"] == 24
    listed, meta = validate_paginated(
        api.list_case_presentations(CASE_MANAGER, params={"case_id": case["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in listed] == [queued["id"]]
