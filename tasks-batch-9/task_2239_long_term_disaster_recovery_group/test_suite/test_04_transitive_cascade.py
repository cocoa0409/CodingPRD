"""One write, three or four records downstream.

Each scenario fires a single request and then checks the whole chain it dragged
behind it, including the records that a shallow implementation would leave stale.
"""

from typing import Any, Dict

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    approve_disbursement,
    assert_bed_night_identity,
    assert_case_money_invariants,
    assert_construction_project,
    assert_disbursement,
    assert_funding_commitment,
    assert_funding_source_conservation,
    assert_housing_assignment,
    assert_lodging_site,
    assert_member_organization,
    assert_pledge_capacity_identity,
    assert_recovery_case,
    assert_version_bumped,
    assert_version_unchanged,
    assert_volunteer_deployment,
    create_case,
    create_deployment,
    create_funding_source,
    create_housing_assignment,
    create_lodging_site,
    create_project,
    create_survivor,
    decide,
    deliberate,
    document_and_verify_damage,
    funding_commitment_payload,
    log_follow_up,
    make_member_org_delegate_headers,
    open_session,
    pay_disbursement,
    permit_project,
    pledge,
    present,
    presentation_version,
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
    setup_awarded_case,
    setup_permitted_project_with_group,
    transition_deployment,
    transition_project,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["ltrg_admin_headers"]
BUILDER = TEST_USERS["construction_manager_headers"]
COORDINATOR = TEST_USERS["volunteer_coordinator_headers"]
CASE_MANAGER = TEST_USERS["case_manager_headers"]

UNRESTRICTED_POOL = {
    "label": "General donations 2026",
    "source_type": "INDIVIDUAL_DONATION",
    "restriction_code": "UNRESTRICTED",
    "total_cents": 2_000_000,
    "admin_retention_allowed": True,
}


def _setup_part_funded_award() -> Dict[str, Any]:
    """A 6000000 need met by a 2000000 pledge and a 900000 bridge authorization."""
    return setup_awarded_case(
        damage=[("STRUCTURE", 6_000_000)],
        orgs=[{"org_name": "Grace Fellowship Relief", "annual_pledge_cap_cents": 5_000_000}],
        pledges=[(0, 2_000_000, "STRUCTURE_REPAIR")],
        funding_sources=[UNRESTRICTED_POOL],
    )


def test_award_confirms_every_pledge_standing_on_the_presentation(api):
    """PRD §3.5: "First, every commitment on this presentation whose status is
    `PLEDGED` moves `PLEDGED → CONFIRMED`, each incrementing its own `version`."

    Design: Difficulty/transitive_cascade/award_cascades_commitment_to_case_ledger_to_funding_status_to_case_status
    """
    scenario = _setup_part_funded_award()
    pledged = scenario["commitments"][0]

    confirmed = validate_success(api.get_funding_commitment(pledged["id"], ADMIN))

    assert_funding_commitment(confirmed)
    assert pledged["status"] == "PLEDGED"
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["pledged_cents"] == 2_000_000
    assert_version_bumped(pledged, confirmed)


def test_award_recomputes_the_case_ledger_and_drives_both_case_axes(api):
    """PRD §3.5: "Second, because those commitments are now confirmed and the bridge
    has been authorized, the case's `reference_unmet_cents` is set to the determined
    need and its `total_committed_cents` and `residual_unmet_cents` are recomputed."

    Design: Difficulty/transitive_cascade/award_cascades_commitment_to_case_ledger_to_funding_status_to_case_status
    """
    scenario = _setup_part_funded_award()

    case = read_case(scenario["case"]["id"])

    assert_recovery_case(case)
    assert case["reference_unmet_cents"] == 6_000_000
    # 2000000 of confirmed pledge plus 900000 of authorized bridge.
    assert case["total_committed_cents"] == 2_900_000
    assert case["residual_unmet_cents"] == 3_100_000
    assert_case_money_invariants(case)
    assert case["funding_status"] == "PARTIALLY_COMMITTED"
    assert case["case_status"] == "ACTIVE_RECOVERY"
    assert scenario["presentation"]["bridge_authorized_cents"] == 900_000
    assert scenario["presentation"]["shortfall_cents"] == 3_100_000


def test_confirmation_alone_flips_no_organization_between_active_and_capped(api):
    """PRD §3.5: "note that because `committed_cents` spans both `PLEDGED` and
    `CONFIRMED`, these values do not actually change here, so no organization flips
    between `ACTIVE` and `CAPPED` on confirmation alone."

    Design: Difficulty/transitive_cascade/award_cascades_commitment_to_case_ledger_to_funding_status_to_case_status
    """
    scenario = _setup_part_funded_award()

    org = read_member_org(scenario["member_orgs"][0]["id"])

    assert_member_organization(org)
    assert org["committed_cents"] == 2_000_000
    assert org["disbursed_cents"] == 0
    assert org["remaining_pledge_capacity_cents"] == 3_000_000
    assert org["status"] == "ACTIVE"
    assert_pledge_capacity_identity(org)


def _read_project(project_id: str):
    return api_client.get_construction_project(project_id, BUILDER)


def _closure_review(case_id: str, review_note: str):
    """Open the closure runway as the case's own case manager."""
    return api_client.closure_review_case(case_id, {"review_note": review_note}, CASE_MANAGER)


def _setup_case_awaiting_closure_after_payment() -> Dict[str, Any]:
    """A fully paid case sitting in CLOSURE_PENDING with its phase closed out.

    The whole 1000000 determined need is pledged, paid through a grant that holds
    exactly the net plus its retention, and the phase is walked to CLOSED_OUT so the
    closure review's three criteria all hold.
    """
    scenario = setup_awarded_case(
        damage=[("STRUCTURE", 1_000_000)],
        orgs=[{"org_name": "Northside Nazarene Fund", "annual_pledge_cap_cents": 2_000_000}],
        pledges=[(0, 1_000_000, "STRUCTURE_REPAIR")],
    )
    scenario["source"] = create_funding_source(
        label="Rebuild grant 2026",
        source_type="FOUNDATION_GRANT",
        restriction_code="STRUCTURE_REPAIR_ONLY",
        total_cents=1_035_000,
        expires_on="2026-12-31",
        admin_retention_allowed=True,
    )
    project = create_project(scenario["case"]["id"], required_trade_hours={"FRAMING": 120})
    permit_project(project["id"], "PB-3309")
    row = request_disbursement(
        scenario["case"]["id"],
        "STRUCTURE_REPAIR",
        1_000_000,
        project_id=project["id"],
        commitment_id=scenario["commitments"][0]["id"],
    )
    approve_disbursement(row["id"], "Approved for rebuild")
    scenario["disbursement"] = pay_disbursement(row["id"], "CHK-3309")
    transition_project(project["id"], "START")
    transition_project(project["id"], "PUNCHLIST")
    transition_project(project["id"], "CLOSE_OUT")
    scenario["project"] = validate_success(_read_project(project["id"]))
    log_follow_up(
        scenario["case"]["id"], contact_type="CLOSURE_REVIEW", contacted_on="2026-09-01"
    )
    scenario["case"] = validate_success(
        _closure_review(scenario["case"]["id"], "All repairs complete and paid")
    )
    return scenario


def test_reversal_restores_the_drawn_funding_source_and_reopens_it(api):
    """PRD §3.6: "First, for every allocation line the funding source's
    `disbursed_cents` decreases by the line's net and its `admin_retained_cents`
    decreases by the line's retention. Second, because those decrements raised
    `available_cents` above 0, any such source moves `EXHAUSTED → OPEN`."

    Design: Difficulty/transitive_cascade/reverse_cascades_funding_source_restore_ledger_and_rewinds_closure_pending
    """
    scenario = _setup_case_awaiting_closure_after_payment()
    before = read_funding_source(scenario["source"]["id"])
    assert before["status"] == "EXHAUSTED"
    assert before["disbursed_cents"] == 1_000_000
    assert before["admin_retained_cents"] == 35_000

    reversed_row = validate_success(
        api.reverse_disbursement(
            scenario["disbursement"]["id"],
            {"reversal_reason": "Contractor withdrew before mobilisation; funds returned."},
            ADMIN,
        )
    )

    assert reversed_row["status"] == "REVERSED"
    after = read_funding_source(scenario["source"]["id"])
    assert after["total_cents"] == 1_035_000
    assert after["available_cents"] == 1_035_000
    assert after["committed_cents"] == 0
    assert after["disbursed_cents"] == 0
    assert after["admin_retained_cents"] == 0
    assert after["status"] == "OPEN"
    assert_funding_source_conservation(after)


def test_reversal_rewinds_funding_status_and_pulls_the_case_off_the_closure_runway(api):
    """PRD §3.9: "A case may also be pulled back off the closure runway without any
    operator action at all: reversing a paid disbursement or rescinding a confirmed
    pledge moves a `CLOSURE_PENDING` case back to `ACTIVE_RECOVERY`, because the
    criterion that `funding_status` be `SATISFIED` no longer holds."

    Design: Difficulty/transitive_cascade/reverse_cascades_funding_source_restore_ledger_and_rewinds_closure_pending
    """
    scenario = _setup_case_awaiting_closure_after_payment()
    assert scenario["case"]["case_status"] == "CLOSURE_PENDING"
    assert scenario["case"]["funding_status"] == "SATISFIED"

    validate_success(
        api.reverse_disbursement(
            scenario["disbursement"]["id"],
            {"reversal_reason": "Contractor withdrew before mobilisation; funds returned."},
            ADMIN,
        )
    )

    case = read_case(scenario["case"]["id"])
    assert case["total_net_disbursed_cents"] == 0
    assert case["total_committed_cents"] == 1_000_000
    assert case["funding_status"] == "FULLY_COMMITTED"
    assert case["case_status"] == "ACTIVE_RECOVERY"
    assert_case_money_invariants(case)


def test_reversal_returns_the_commitment_to_confirmed_and_keeps_the_rows_figures(api):
    """PRD §3.6: "When the row names a `commitment_id`, that commitment moves
    `DISBURSED → CONFIRMED`, restoring the organization's `committed_cents`. The row
    moves `PAID → REVERSED`, stores its `reversal_reason` and increments its
    `version`."

    Design: Difficulty/transitive_cascade/reverse_cascades_funding_source_restore_ledger_and_rewinds_closure_pending
    """
    scenario = _setup_case_awaiting_closure_after_payment()
    commitment_id = scenario["commitments"][0]["id"]
    disbursed = validate_success(api.get_funding_commitment(commitment_id, ADMIN))
    assert disbursed["status"] == "DISBURSED"

    reversed_row = validate_success(
        api.reverse_disbursement(
            scenario["disbursement"]["id"],
            {"reversal_reason": "Contractor withdrew before mobilisation; funds returned."},
            ADMIN,
        )
    )

    assert_disbursement(reversed_row)
    assert reversed_row["status"] == "REVERSED"
    assert reversed_row["reversal_reason"] == (
        "Contractor withdrew before mobilisation; funds returned."
    )
    # The reversal is a compensating action, not an erasure of the record.
    assert reversed_row["net_cents"] == 1_000_000
    assert reversed_row["admin_retained_cents"] == 35_000
    assert reversed_row["gross_cents"] == 1_035_000
    restored = validate_success(api.get_funding_commitment(commitment_id, ADMIN))
    assert restored["status"] == "CONFIRMED"
    org = read_member_org(scenario["member_orgs"][0]["id"])
    assert org["committed_cents"] == 1_000_000
    assert org["disbursed_cents"] == 0
    assert_pledge_capacity_identity(org)


def _setup_started_project_with_housed_crew() -> Dict[str, Any]:
    """A running phase with one confirmed crew filling a twelve-bed site.

    The site's capacity is exactly the crew's headcount, so the site is FULL until the
    suspension cascade reaches it.
    """
    scenario = setup_permitted_project_with_group(
        project_overrides={
            "required_trade_hours": {"FRAMING": 300, "ROOFING": 150, "GENERAL_LABOR": 300},
            "estimated_material_cents": 900_000,
            "critical_trades": ["FRAMING"],
        },
        group_overrides={
            "group_name": "Cedar Hill Work Team",
            "home_organization": "Cedar Hill Methodist",
            "member_count": 12,
            "skill_profile": {"FRAMING": 5, "ROOFING": 2, "GENERAL_LABOR": 12},
            "requires_housing": True,
        },
        permit_number="PB-3310",
    )
    site = create_lodging_site(site_name="Cedar Hill Bunkhouse", bed_capacity=12)
    assignment = create_housing_assignment(
        scenario["group"]["id"], site["id"], "2026-09-07", "2026-09-12"
    )
    deployment = create_deployment(
        scenario["group"]["id"], scenario["project"]["id"], "2026-09-07", "2026-09-11"
    )
    transition_deployment(deployment["id"], "CONFIRM")
    transition_project(scenario["project"]["id"], "START")
    scenario["site"] = site
    scenario["assignment"] = assignment
    scenario["deployment"] = deployment
    return scenario


def test_suspending_a_phase_cancels_live_crews_and_releases_the_beds_they_held(api):
    """PRD §3.7: "First, every volunteer deployment on this project whose status is
    `REQUESTED` or `CONFIRMED` moves to `CANCELLED` with `cancellation_reason` recorded
    as `PROJECT_SUSPENDED`. Second, because those deployments were cancelled, each
    affected volunteer group's housing assignments whose `status` is `ACTIVE` and whose
    night interval intersects the cancelled deployment's window move `ACTIVE →
    RELEASED` with `release_reason` recorded as `DEPLOYMENT_CANCELLED`."

    Design: Difficulty/transitive_cascade/project_suspend_cascades_deployment_housing_lodging_and_counters
    """
    scenario = _setup_started_project_with_housed_crew()

    suspended = validate_success(
        api.transition_construction_project(
            scenario["project"]["id"],
            {"action": "SUSPEND", "reason": "Permit revision required by building department."},
            BUILDER,
        )
    )

    assert_construction_project(suspended)
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == "Permit revision required by building department."
    deployment = validate_success(
        api.get_volunteer_deployment(scenario["deployment"]["id"], COORDINATOR)
    )
    assert_volunteer_deployment(deployment)
    assert deployment["status"] == "CANCELLED"
    assert deployment["cancellation_reason"] == "PROJECT_SUSPENDED"
    assignment = validate_success(
        api.get_housing_assignment(scenario["assignment"]["id"], COORDINATOR)
    )
    assert_housing_assignment(assignment)
    assert assignment["status"] == "RELEASED"
    assert assignment["release_reason"] == "DEPLOYMENT_CANCELLED"
    assert assignment["released_at"] is not None


def test_suspension_recomputes_the_lodging_peak_and_both_deployment_counters(api):
    """PRD §3.7: "Third, because those assignments were released, each affected lodging
    site's `peak_committed_beds` and `available_beds` are recomputed and any site whose
    recomputed peak has fallen below its `bed_capacity` moves `FULL → OPEN`. The
    project's `confirmed_deployment_count` and each affected group's
    `active_deployment_count` are recomputed."

    Design: Difficulty/transitive_cascade/project_suspend_cascades_deployment_housing_lodging_and_counters
    """
    scenario = _setup_started_project_with_housed_crew()
    before_site = validate_success(api.get_lodging_site(scenario["site"]["id"], COORDINATOR))
    assert before_site["peak_committed_beds"] == 12
    assert before_site["status"] == "FULL"

    validate_success(
        api.transition_construction_project(
            scenario["project"]["id"],
            {"action": "SUSPEND", "reason": "Permit revision required by building department."},
            BUILDER,
        )
    )

    site = validate_success(api.get_lodging_site(scenario["site"]["id"], COORDINATOR))
    assert_lodging_site(site)
    assert site["peak_committed_beds"] == 0
    assert site["available_beds"] == 12
    assert site["status"] == "OPEN"
    assert_bed_night_identity(site)
    group = validate_success(api.get_volunteer_group(scenario["group"]["id"], COORDINATOR))
    assert group["active_deployment_count"] == 0
    project = validate_success(
        api.get_construction_project(scenario["project"]["id"], BUILDER)
    )
    assert project["confirmed_deployment_count"] == 0


def test_resuming_a_phase_restores_neither_the_crew_nor_the_beds(api):
    """PRD §3.7: "`RESUME` moves the phase `SUSPENDED → IN_PROGRESS` and clears
    `suspension_reason`. It does **not** restore the cancelled deployments or the
    released housing assignments; the coordinator must rebook."

    Design: Difficulty/transitive_cascade/project_suspend_cascades_deployment_housing_lodging_and_counters
    """
    scenario = _setup_started_project_with_housed_crew()
    validate_success(
        api.transition_construction_project(
            scenario["project"]["id"],
            {"action": "SUSPEND", "reason": "Permit revision required by building department."},
            BUILDER,
        )
    )

    resumed = validate_success(
        api.transition_construction_project(
            scenario["project"]["id"], {"action": "RESUME"}, BUILDER
        )
    )

    assert resumed["status"] == "IN_PROGRESS"
    assert resumed["suspension_reason"] is None
    deployment = validate_success(
        api.get_volunteer_deployment(scenario["deployment"]["id"], COORDINATOR)
    )
    assert deployment["status"] == "CANCELLED"
    assignment = validate_success(
        api.get_housing_assignment(scenario["assignment"]["id"], COORDINATOR)
    )
    assert assignment["status"] == "RELEASED"
    site = validate_success(api.get_lodging_site(scenario["site"]["id"], COORDINATOR))
    assert site["peak_committed_beds"] == 0
    assert site["status"] == "OPEN"
    assert resumed["confirmed_deployment_count"] == 0


def _setup_two_households_before_one_capped_organization() -> Dict[str, Any]:
    """Two cases of one survivor at one meeting, the second still open to pledges.

    The organization's whole 1500000 annual cap goes to the first household, which is
    then deferred so the chair can hear the second. Every other gate on a pledge to the
    second household holds: the meeting is open, the presentation is deliberating, the
    organization is in attendance, and its version is read fresh.
    """
    set_clock()
    survivor = create_survivor(household_name="Ostrowski Household", household_size=4)
    cases = []
    assessments = []
    for disaster_code in ("DR-4801", "DR-4802"):
        case = create_case(survivor["id"], disaster_code=disaster_code)
        document_and_verify_damage(case["id"], "STRUCTURE", 2_000_000)
        cases.append(case)
        assessments.append(run_assessment(case["id"]))
    org = seat_member_org(
        org_name="Rotary Recovery Fund",
        org_type="CIVIC_CLUB",
        annual_pledge_cap_cents=1_500_000,
    )
    session = schedule_session(session_label="UNT 2026-09-11", quorum_min_member_orgs=1)
    open_session(session["id"], [org["id"]])
    presentations = [
        queue_presentation(case["id"], session["id"], assessment["id"])
        for case, assessment in zip(cases, assessments)
    ]
    present(presentations[0]["id"])
    deliberate(presentations[0]["id"])
    commitment = pledge(presentations[0]["id"], org["id"], 1_500_000)
    decide(presentations[0]["id"], "DEFER", "Hold A while B is heard")
    present(presentations[1]["id"])
    deliberate(presentations[1]["id"])
    return {
        "survivor": survivor,
        "cases": cases,
        "member_org": org,
        "session": session,
        "presentations": [read_presentation(p["id"]) for p in presentations],
        "commitment": commitment,
    }


def test_a_pledge_on_one_presentation_caps_the_organization_itself(api):
    """PRD §3.4: "Creating it recomputes the organization's `committed_cents` and
    `remaining_pledge_capacity_cents`, and if remaining capacity has reached 0 the
    organization moves `ACTIVE → CAPPED`, which stops it pledging on any other
    presentation until capacity returns."

    Design: Difficulty/transitive_cascade/pledge_caps_org_and_locks_it_out_of_a_second_case_in_the_same_session
    """
    scenario = _setup_two_households_before_one_capped_organization()

    assert scenario["commitment"]["status"] == "PLEDGED"
    assert scenario["commitment"]["pledged_cents"] == 1_500_000
    org = read_member_org(scenario["member_org"]["id"])
    assert_member_organization(org)
    assert org["committed_cents"] == 1_500_000
    assert org["disbursed_cents"] == 0
    assert org["remaining_pledge_capacity_cents"] == 0
    assert_pledge_capacity_identity(org)
    assert org["status"] == "CAPPED"


def test_the_capped_status_locks_the_organization_out_of_the_second_household(api):
    """PRD §3.4: "The pledging organization's `status` must be exactly `ACTIVE` — a
    `CAPPED`, `SUSPENDED` or `WITHDRAWN` organization may not pledge, and the attempt is
    refused with `ERR_MEMBER_ORG_NOT_ACTIVE`."

    Design: Difficulty/transitive_cascade/pledge_caps_org_and_locks_it_out_of_a_second_case_in_the_same_session
    """
    scenario = _setup_two_households_before_one_capped_organization()
    org_id = scenario["member_org"]["id"]
    second = scenario["presentations"][1]
    assert second["status"] == "DELIBERATING"

    response = api_client.create_funding_commitment(
        funding_commitment_payload(
            second["id"], org_id, 100_000, presentation_version(second["id"])
        ),
        make_member_org_delegate_headers(org_id),
    )

    # The status gate fires ahead of the fiscal check on remaining capacity.
    validate_error(response, ApiErrorId.ERR_MEMBER_ORG_NOT_ACTIVE.value, 409)
    after_presentation = read_presentation(second["id"])
    assert after_presentation["pledged_total_cents"] == 0
    assert_version_unchanged(second, after_presentation)
    org = read_member_org(org_id)
    assert org["committed_cents"] == 1_500_000
    assert org["remaining_pledge_capacity_cents"] == 0
    assert org["status"] == "CAPPED"
