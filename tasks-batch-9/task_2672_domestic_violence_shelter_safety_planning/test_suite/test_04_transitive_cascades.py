"""Two multi-link cascades where each hop is caused by the hop before it: the exit
chain that frees a bed, promotes a waitlisted household and injures an advocate, and
the compromise chain that seals a survivor and unwinds her housing work.
"""

from test_helpers import (
    MODERATE_FACTORS,
    advance_clock,
    api_client,
    approve_screening,
    assert_bed_ledger_invariant,
    assert_component_scoring,
    assert_landlord_ledger_invariant,
    assert_screening_request,
    create_plan_component_payload,
    create_safety_plan_payload,
    client_version,
    exit_household,
    get_success_data,
    match_referral,
    read_client,
    read_partner,
    read_plan,
    read_shelter,
    read_staff,
    read_unit,
    record_wellness_check,
    report_compromise,
    reserve_bed,
    seed_checked_in_admission,
    seed_client_with_assessed_call,
    seed_hotline_advocate,
    seed_housing_specialist,
    seed_hotline_call,
    seed_landlord_partner,
    seed_risk_assessment,
    seed_screening_request,
    seed_shelter_scene,
    submit_referral,
    validate_success,
    waitlist_screening,
)

FAMILY_OF_THREE = {"household_size": 3, "minor_children_count": 2, "hmis_disclosure_consent": "DENIED"}

#: A same-day check contributing exactly 39.0 points, which leaves the member OPEN.
CHECK_AT_39_POINTS = {
    "checked_on_utc": "2026-08-12T08:00:00Z",
    "exposure_hours": 6.0,
    "distress_scale": 6,
    "debrief_completed": False,
}


def _exit_cascade_scene(with_waitlisted_request: bool = True):
    """A checked-in family in the only unit, plus a second advocate holding a waitlist row."""
    scene = seed_shelter_scene(unit_overrides={"unit_type": "FAMILY_SUITE", "bed_capacity": 4})
    second_advocate = seed_hotline_advocate("Bea Cole")
    scene, _client_a, _request_a, admission = seed_checked_in_admission(
        scene=scene,
        client_overrides=dict(FAMILY_OF_THREE, client_code="C-7001", legal_name="Alina Ford"),
        assessment_overrides=dict(MODERATE_FACTORS),
        admission_overrides={"entry_date": "2026-08-07", "planned_exit_date": "2026-08-12"},
        check_in_overrides={"school_enrollment_confirmed": True},
        entry_clock="2026-08-07T09:00:00Z",
    )
    waitlisted = None
    if with_waitlisted_request:
        client_b, call_b, _ra_b = seed_client_with_assessed_call(
            second_advocate,
            client_overrides={
                "client_code": "C-7002",
                "legal_name": "Mira Osei",
                "household_size": 2,
                "minor_children_count": 0,
                "hmis_disclosure_consent": "DENIED",
            },
            assessment_overrides=dict(MODERATE_FACTORS),
        )
        request_b = seed_screening_request(
            second_advocate,
            client_b["id"],
            call_b["id"],
            scene.shelter["id"],
            requested_entry_date="2026-08-10",
        )
        waitlisted = waitlist_screening(scene.manager, request_b["id"], second_advocate.id)
    clock = advance_clock("2026-08-12T09:00:00Z")
    assert clock["expired_screening_request_count"] == 0
    check = record_wellness_check(second_advocate.id, **CHECK_AT_39_POINTS)
    assert check["contribution_points"] == 39.0
    before = read_staff(second_advocate.id)
    assert before["secondary_trauma_index"] == 39.0
    assert before["wellness_posture"] == "OPEN"
    return scene, second_advocate, admission, waitlisted


def test_exit_frees_the_unit_and_promotes_the_only_eligible_waitlisted_request():
    """The freed beds are what make the waitlisted household eligible for promotion.

    PRD: "The promoted request moves `WAITLISTED` → `APPROVED` with
    `promoted_from_waitlist` set to true — which is how a reader tells a promotion apart
    from a manager's approval — `offered_shelter_unit_id` set to the freed unit,
    `decided_at` set to the clock reading, and `waitlist_position` cleared to null."

    Design: Difficulty/transitive_cascade/exit_frees_unit_then_promotes_waitlist_then_flips_advocate_posture
    """
    scene, second_advocate, admission, waitlisted = _exit_cascade_scene()
    assert waitlisted["waitlist_position"] == 1

    response = exit_household(
        scene, admission["id"], "2026-08-12", exit_destination="PERMANENT_HOUSING"
    )

    exited = validate_success(response, 200)
    assert exited["occupancy_status"] == "EXITED"
    assert exited["settled_stay_cost_cents"] == 59500
    assert read_shelter(scene.manager, scene.shelter["id"])["settled_revenue_cents"] == 59500
    unit = read_unit(scene.manager, scene.unit["id"])
    assert unit["occupied_beds"] == 0
    assert unit["available_beds"] == 4
    assert unit["status"] == "AVAILABLE"
    assert_bed_ledger_invariant(unit)
    promoted = get_success_data(
        api_client.list_screening_requests(
            scene.manager.headers,
            params={"assigned_advocate_id": second_advocate.id, "status": "APPROVED"},
        )
    )
    assert [row["id"] for row in promoted] == [waitlisted["id"]]
    assert_screening_request(promoted[0])
    assert promoted[0]["promoted_from_waitlist"] is True
    assert promoted[0]["status"] == "APPROVED"
    assert promoted[0]["offered_shelter_unit_id"] == scene.unit["id"]
    assert promoted[0]["waitlist_position"] is None
    assert read_shelter(scene.manager, scene.shelter["id"])["capacity_posture"] == "OPEN"


def test_promotion_adds_2_5_points_and_flips_the_promoted_advocate_to_restricted():
    """The last link is driven by the promotion's caseload, not by the exit itself.

    PRD: "The promoted request's advocate then has their `active_caseload_count`,
    `secondary_trauma_index` and `wellness_posture` re-derived, and because the promotion
    adds a counted screening it adds 2.5 points to that advocate's index: an advocate
    sitting at 39.0 lands at 41.5 and flips from `OPEN` to `RESTRICTED`."

    Design: Difficulty/transitive_cascade/exit_frees_unit_then_promotes_waitlist_then_flips_advocate_posture
    """
    scene, second_advocate, admission, _waitlisted = _exit_cascade_scene()

    response = exit_household(
        scene, admission["id"], "2026-08-12", exit_destination="PERMANENT_HOUSING"
    )

    validate_success(response, 200)
    after = read_staff(second_advocate.id)
    assert after["active_caseload_count"] == 1
    assert after["secondary_trauma_index"] == 41.5
    assert after["wellness_posture"] == "RESTRICTED"


def test_exit_with_no_eligible_waitlist_row_leaves_the_advocate_untouched():
    """With an empty eligible pool nothing is promoted and no advocate is injured.

    PRD: "If the eligible pool is empty, nothing is promoted, no error is raised, and the
    exit still succeeds with 200 OK."

    Design: Difficulty/transitive_cascade/exit_frees_unit_then_promotes_waitlist_then_flips_advocate_posture
    """
    scene, second_advocate, admission, waitlisted = _exit_cascade_scene(
        with_waitlisted_request=False
    )
    assert waitlisted is None

    response = exit_household(
        scene, admission["id"], "2026-08-12", exit_destination="PERMANENT_HOUSING"
    )

    validate_success(response, 200)
    after = read_staff(second_advocate.id)
    assert after["active_caseload_count"] == 0
    assert after["secondary_trauma_index"] == 39.0
    assert after["wellness_posture"] == "OPEN"


def _component_by_id(plan_id, headers, component_id):
    """Read one component back off its plan's component listing."""
    rows = get_success_data(
        api_client.list_plan_components(plan_id, headers, params={"limit": 100, "offset": 0})
    )
    match = [row for row in rows if row["id"] == component_id]
    assert match, f"component {component_id} missing from plan {plan_id}"
    return match[0]


def _compromise_cascade_scene(match_the_referral: bool = True):
    """A sealed-in-waiting survivor: ACTIVE plan of three components plus live housing work."""
    scene = seed_shelter_scene(unit_overrides={"unit_type": "FAMILY_SUITE", "bed_capacity": 4})
    specialist = seed_housing_specialist("Omar Diaz")
    advocate, manager = scene.advocate, scene.manager
    client, first_call, assessment = seed_client_with_assessed_call(
        advocate,
        client_overrides=dict(FAMILY_OF_THREE, client_code="C-8001", legal_name="Alina Ford"),
        assessment_overrides=dict(MODERATE_FACTORS),
        call_overrides={
            "presenting_concerns": "Wants a written plan before she tells her employer anything."
        },
    )
    get_success_data(
        api_client.dispose_hotline_call(
            first_call["id"], {"disposition": "SAFETY_PLAN_ONLY"}, advocate.headers
        )
    )
    plan = get_success_data(
        api_client.create_safety_plan(
            create_safety_plan_payload(
                client["id"], assessment["id"], client_version(client["id"], advocate.headers)
            ),
            advocate.headers,
        )
    )
    components = {}
    for component_type, target in (
        ("RELOCATION", "2026-08-09"),
        ("COMMUNICATION", "2026-08-15"),
        ("WORKPLACE_NOTIFICATION", "2026-08-18"),
    ):
        components[component_type] = get_success_data(
            api_client.create_plan_component(
                plan["id"],
                create_plan_component_payload(component_type, target_completion_date=target),
                advocate.headers,
            )
        )
    get_success_data(
        api_client.implement_plan_component(
            plan["id"], components["RELOCATION"]["id"], advocate.headers
        )
    )
    plan = get_success_data(api_client.activate_safety_plan(plan["id"], advocate.headers))
    assert plan["coverage_score"] == 4.58
    partner = seed_landlord_partner(
        specialist,
        name="Vista Rentals",
        units_pledged=4,
        accepts_subsidy_type="HOUSING_CHOICE_VOUCHER",
        base_incentive_cents=40000,
    )
    referral = submit_referral(
        specialist,
        client["id"],
        partner["id"],
        program_type="TRANSITIONAL_HOUSING",
        subsidy_type="HOUSING_CHOICE_VOUCHER",
    )
    if match_the_referral:
        referral = get_success_data(
            match_referral(
                specialist, referral["id"], partner["id"], monthly_rent_cents=138000
            )
        )
        assert referral["incentive_fee_cents"] == 40000
    second_call = seed_hotline_call(
        advocate, client["id"], presenting_concerns="Now asking for a shelter bed for tonight."
    )
    seed_risk_assessment(advocate, second_call["id"], **MODERATE_FACTORS)
    request = seed_screening_request(
        advocate,
        client["id"],
        second_call["id"],
        scene.shelter["id"],
        requested_entry_date="2026-08-07",
    )
    approve_screening(manager, request["id"], advocate.id)
    admission = get_success_data(
        reserve_bed(
            scene, request["id"], entry_date="2026-08-07", planned_exit_date="2026-08-14"
        )
    )
    advance_clock("2026-08-07T09:00:00Z")
    admission = get_success_data(
        api_client.check_in_admission(
            admission["id"], manager.headers, {"school_enrollment_confirmed": True}
        )
    )
    return scene, specialist, client, plan, components, partner, referral, admission


def test_compromise_seals_the_survivor_and_regrades_her_active_plan_conditionally():
    """The seal drives the plan under revision and re-grades only the components it must.

    PRD: "That second rewrite is deliberately conditional on the component type: `DRAFT`
    components of the other three domains stay at `DRAFT` and keep their factor of 0.350,
    because telling an employer where a survivor works is the one step that becomes
    actively dangerous the moment the location leaks."

    Design: Difficulty/transitive_cascade/compromise_seals_client_then_suspends_plan_then_rejects_referral_then_reverses_landlord_ledger
    """
    scene, _specialist, client, plan, components, _partner, _referral, admission = (
        _compromise_cascade_scene()
    )

    response = report_compromise(scene, admission["id"], compromise_source="SOCIAL_MEDIA")

    compromised = validate_success(response, 200)
    assert compromised["location_security_status"] == "COMPROMISED"
    assert compromised["occupancy_status"] == "CHECKED_IN"
    assert read_unit(scene.manager, scene.unit["id"])["occupied_beds"] == 3
    assert read_client(client["id"])["confidentiality_posture"] == "SEALED"
    suspended = read_plan(plan["id"], scene.advocate.headers)
    assert suspended["status"] == "UNDER_REVISION"
    assert suspended["revision_count"] == 0
    assert suspended["coverage_score"] == 1.41
    relocation = _component_by_id(
        plan["id"], scene.advocate.headers, components["RELOCATION"]["id"]
    )
    workplace = _component_by_id(
        plan["id"], scene.advocate.headers, components["WORKPLACE_NOTIFICATION"]["id"]
    )
    communication = _component_by_id(
        plan["id"], scene.advocate.headers, components["COMMUNICATION"]["id"]
    )
    assert_component_scoring(relocation, 30, 0.53, "REVIEW_REQUIRED")
    assert_component_scoring(workplace, 20, 0.0, "BLOCKED")
    assert_component_scoring(communication, 25, 0.88, "DRAFT")


def test_compromise_rejects_the_matched_referral_and_reverses_the_landlord_ledger():
    """The partner's ledger moves only because the referral was dragged out of MATCHED.

    PRD: "On every affected partner, `units_committed` drops by 1, `units_available` rises
    by 1, `incentive_accrued_cents` drops by the fee that was just cleared, and
    `engagement_score` and `incentive_tier` are re-derived from the new committed count."

    Design: Difficulty/transitive_cascade/compromise_seals_client_then_suspends_plan_then_rejects_referral_then_reverses_landlord_ledger
    """
    scene, specialist, _client, _plan, _components, partner, referral, admission = (
        _compromise_cascade_scene()
    )

    response = report_compromise(scene, admission["id"], compromise_source="SOCIAL_MEDIA")

    validate_success(response, 200)
    rejected = get_success_data(
        api_client.get_housing_referral(referral["id"], specialist.headers)
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "SAFETY_PLAN_SUSPENDED"
    assert rejected["incentive_fee_cents"] is None
    assert rejected["incentive_tier_applied"] is None
    # `withdraw_count` lives on the referral and counts only specialist-initiated
    # withdrawals, so the cascade rejection must leave it at 0.
    assert rejected["withdraw_count"] == 0
    after = read_partner(specialist, partner["id"])
    assert after["units_committed"] == 0
    assert after["units_available"] == 4
    assert after["incentive_accrued_cents"] == 0
    assert after["engagement_score"] == 0.0
    assert after["incentive_tier"] == "BASE"
    assert_landlord_ledger_invariant(after)


def test_compromise_of_a_submitted_only_referral_moves_no_partner_counter():
    """A referral that never locked a fee is rejected without touching the ledger.

    PRD: "A referral that was only `SUBMITTED` had no fee locked, so its rejection moves
    no partner counter at all."

    Design: Difficulty/transitive_cascade/compromise_seals_client_then_suspends_plan_then_rejects_referral_then_reverses_landlord_ledger
    """
    scene, specialist, _client, _plan, _components, partner, referral, admission = (
        _compromise_cascade_scene(match_the_referral=False)
    )
    assert referral["status"] == "SUBMITTED"

    response = report_compromise(scene, admission["id"], compromise_source="SOCIAL_MEDIA")

    validate_success(response, 200)
    rejected = get_success_data(
        api_client.get_housing_referral(referral["id"], specialist.headers)
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "SAFETY_PLAN_SUSPENDED"
    after = read_partner(specialist, partner["id"])
    assert after["units_committed"] == 0
    assert after["units_available"] == 4
    assert after["incentive_accrued_cents"] == 0
    assert after["engagement_score"] == 0.0
    assert after["incentive_tier"] == "BASE"
    assert_landlord_ledger_invariant(after)
