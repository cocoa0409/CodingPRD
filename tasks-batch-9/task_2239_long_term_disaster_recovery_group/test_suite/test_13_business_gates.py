"""Gates that only fire on the combination of facts, not on any single field.

Each test pairs a refused call with the nearly identical call that the coalition does
accept, so the assertion pins the gate itself rather than an unrelated precondition.
"""

from test_helpers import (
    ADMIN,
    CASE_MANAGER,
    CHAIR,
    COORDINATOR,
    ApiErrorId,
    assert_case_presentation,
    assert_funding_commitment,
    assert_member_organization,
    assert_recovery_case,
    assert_unmet_need_assessment,
    assert_version_unchanged,
    case_presentation_payload,
    create_case,
    create_funding_source,
    create_group,
    create_project,
    create_survivor,
    decide,
    deliberate,
    document_damage,
    funding_commitment_payload,
    make_member_org_delegate_headers,
    open_session,
    permit_project,
    pledge,
    present,
    present_and_deliberate,
    queue_presentation,
    read_case,
    read_member_org,
    read_presentation,
    record_assistance,
    run_assessment,
    schedule_session,
    seat_member_org,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    verify_damage,
    volunteer_deployment_payload,
)


def test_a_determination_needs_at_least_one_inspected_item(api):
    """PRD §3.3: "The case must have at least one damage item in `verification_status`
    `VERIFIED`, or the request is refused with `ERR_NO_VERIFIED_DAMAGE`."

    Design: Corner/validations/corner_assessment_without_any_verified_damage_item_is_refused
    """
    set_clock()
    survivor = create_survivor(
        household_name="Whitfield Household",
        primary_contact_phone="555-0231",
        household_size=2,
        income_band="LOW",
        head_of_household_age=45,
    )
    case = create_case(survivor["id"])
    item = document_damage(
        case["id"],
        category="ROOF",
        item_description="Ridge vent",
        documented_cost_cents=400_000,
        photo_count=2,
    )
    before = read_case(case["id"])

    premature = api.create_assessment(
        case["id"], {"variant": "PURPOSE_MATCHED"}, CASE_MANAGER
    )

    validate_error(premature, ApiErrorId.ERR_NO_VERIFIED_DAMAGE.value, 422)
    untouched = read_case(case["id"])
    assert_recovery_case(untouched)
    assert untouched["case_status"] == "INTAKE"
    assert untouched["verified_damage_total_cents"] == 0
    assert_version_unchanged(before, untouched)
    verify_damage(item["id"], verified_cost_cents=400_000)
    # The very same determination request is now legitimate.
    snapshot = validate_success(
        api.create_assessment(case["id"], {"variant": "PURPOSE_MATCHED"}, CASE_MANAGER), 201
    )
    assert_unmet_need_assessment(snapshot)
    assert snapshot["unmet_need_total_cents"] == 400_000
    assert read_case(case["id"])["case_status"] == "ASSESSED"


def test_an_organization_not_in_the_room_may_not_pledge(api):
    """PRD §3.4: "The organization must appear in the session's
    `attending_member_org_ids`, or `ERR_ORG_NOT_IN_SESSION` results — being seated at the
    coalition is not the same as being in the room."

    Design: Corner/validations/corner_pledge_from_an_org_absent_from_the_session_is_refused
    """
    set_clock()
    survivor = create_survivor(
        household_name="Ximenes Household",
        primary_contact_phone="555-0232",
        household_size=3,
        income_band="VLI",
        head_of_household_age=48,
    )
    case = create_case(survivor["id"])
    item = document_damage(
        case["id"],
        category="STRUCTURE",
        item_description="Wall repair",
        documented_cost_cents=800_000,
        photo_count=4,
    )
    verify_damage(item["id"], verified_cost_cents=800_000)
    assessment = run_assessment(case["id"])
    inside = seat_member_org(
        org_name="Inside Table Org",
        org_type="FAITH_BASED",
        contact_email="in@table.example",
        annual_pledge_cap_cents=3_000_000,
    )
    outside = seat_member_org(
        org_name="Outside Table Org",
        org_type="NONPROFIT",
        contact_email="out@table.example",
        annual_pledge_cap_cents=3_000_000,
    )
    session = schedule_session(session_label="UNT attendance gate", quorum_min_member_orgs=1)
    open_session(session["id"], [inside["id"]])
    presentation = queue_presentation(case["id"], session["id"], assessment["id"])
    window = present_and_deliberate(presentation["id"])

    absent = api.create_funding_commitment(
        funding_commitment_payload(
            presentation["id"], outside["id"], 300_000, window["version"]
        ),
        make_member_org_delegate_headers(outside["id"]),
    )

    validate_error(absent, ApiErrorId.ERR_ORG_NOT_IN_SESSION.value, 409)
    seated = validate_success(
        api.create_funding_commitment(
            funding_commitment_payload(
                presentation["id"], inside["id"], 300_000, window["version"]
            ),
            make_member_org_delegate_headers(inside["id"]),
        ),
        201,
    )
    assert_funding_commitment(seated)
    assert seated["status"] == "PLEDGED"
    assert seated["pledged_cents"] == 300_000
    untouched = read_member_org(outside["id"])
    assert_member_organization(untouched)
    assert untouched["committed_cents"] == 0
    assert untouched["remaining_pledge_capacity_cents"] == 3_000_000
    assert untouched["status"] == "ACTIVE"


def test_the_table_may_not_skip_the_head_of_the_queue(api):
    """PRD §3.4: "it requires the presentation to be at the head of the queue:
    `queue_position` must be exactly 1, and calling any other presentation is refused with
    `ERR_NOT_AT_QUEUE_HEAD`."

    Design: Corner/validations/corner_presenting_out_of_queue_order_is_refused
    """
    set_clock()
    first_survivor = create_survivor(
        household_name="Yamada Household",
        primary_contact_phone="555-0233",
        household_size=2,
        income_band="LOW",
        head_of_household_age=44,
    )
    second_survivor = create_survivor(
        household_name="Zeller Household",
        primary_contact_phone="555-0234",
        household_size=2,
        income_band="LOW",
        head_of_household_age=46,
    )
    presentations = []
    for survivor, description in (
        (first_survivor, "Repair A"),
        (second_survivor, "Repair B"),
    ):
        case = create_case(survivor["id"])
        item = document_damage(
            case["id"],
            category="STRUCTURE",
            item_description=description,
            documented_cost_cents=600_000,
            photo_count=3,
        )
        verify_damage(item["id"], verified_cost_cents=600_000)
        presentations.append((case, run_assessment(case["id"])))
    org = seat_member_org(
        org_name="Queue Table Org",
        org_type="FAITH_BASED",
        contact_email="q@table.example",
        annual_pledge_cap_cents=3_000_000,
    )
    session = schedule_session(session_label="UNT queue order", quorum_min_member_orgs=1)
    open_session(session["id"], [org["id"]])
    head = queue_presentation(
        presentations[0][0]["id"], session["id"], presentations[0][1]["id"], narrative="Case A."
    )
    behind = queue_presentation(
        presentations[1][0]["id"], session["id"], presentations[1][1]["id"], narrative="Case B."
    )
    assert head["queue_position"] == 1
    assert behind["queue_position"] == 2

    out_of_order = api.present_case_presentation(behind["id"], {}, CHAIR)

    validate_error(out_of_order, ApiErrorId.ERR_NOT_AT_QUEUE_HEAD.value, 409)
    assert read_presentation(behind["id"])["status"] == "QUEUED"
    called = validate_success(api.present_case_presentation(head["id"], {}, CHAIR))
    assert_case_presentation(called)
    assert called["status"] == "PRESENTING"


def test_a_determination_overtaken_by_a_later_inspection_may_not_be_pinned(api):
    """PRD §3.4: "Finally the pinned snapshot must not have been overtaken by later
    inspection work: its own `verified_damage_total_cents` must still equal the case's
    current `verified_damage_total_cents`, and a mismatch is refused with
    `ERR_ASSESSMENT_STALE`."

    Design: Corner/validations/corner_assessment_overtaken_by_a_later_inspection_cannot_be_presented
    """
    set_clock()
    survivor = create_survivor(
        household_name="Abadi Household",
        primary_contact_phone="555-0235",
        household_size=3,
        income_band="VLI",
        head_of_household_age=53,
    )
    case = create_case(survivor["id"])
    subfloor = document_damage(
        case["id"],
        category="STRUCTURE",
        item_description="Subfloor",
        documented_cost_cents=600_000,
        photo_count=4,
    )
    verify_damage(subfloor["id"], verified_cost_cents=600_000)
    superseded = run_assessment(case["id"])
    condenser = document_damage(
        case["id"],
        category="HVAC",
        item_description="Condenser",
        documented_cost_cents=300_000,
        photo_count=2,
        is_habitability_critical=False,
    )
    verify_damage(condenser["id"], verified_cost_cents=300_000)
    org = seat_member_org(
        org_name="Stale Check Org",
        org_type="NONPROFIT",
        contact_email="s@table.example",
        annual_pledge_cap_cents=3_000_000,
    )
    session = schedule_session(session_label="UNT staleness gate", quorum_min_member_orgs=1)
    open_session(session["id"], [org["id"]])
    assert superseded["verified_damage_total_cents"] == 600_000
    assert superseded["unmet_need_total_cents"] == 600_000
    assert read_case(case["id"])["verified_damage_total_cents"] == 900_000

    stale = api.create_case_presentation(
        case_presentation_payload(
            case["id"],
            session["id"],
            superseded["id"],
            narrative="Pinning the superseded determination.",
        ),
        CASE_MANAGER,
    )

    validate_error(stale, ApiErrorId.ERR_ASSESSMENT_STALE.value, 409)
    current = run_assessment(case["id"])
    assert current["verified_damage_total_cents"] == 900_000
    assert current["unmet_need_total_cents"] == 900_000
    accepted = validate_success(
        api.create_case_presentation(
            case_presentation_payload(
                case["id"],
                session["id"],
                current["id"],
                narrative="Pinning the current determination.",
            ),
            CASE_MANAGER,
        ),
        201,
    )
    assert_case_presentation(accepted)
    assert accepted["status"] == "QUEUED"


def test_two_lawful_pledges_may_still_overshoot_the_determined_need(api):
    """PRD §3.5: "Two fiscal gates guard the branch: the pledged total may not exceed the
    determined need, or `ERR_AWARD_EXCEEDS_UNMET_NEED` results; and the computed
    `awarded_cents` must be strictly greater than 0, or `ERR_AWARD_ZERO` results — the
    table may not record an award of nothing."

    Design: Corner/validations/corner_two_individually_legal_pledges_together_exceed_the_unmet_need
    """
    set_clock()
    survivor = create_survivor(
        household_name="Bergstrom Household",
        primary_contact_phone="555-0236",
        household_size=4,
        income_band="VLI",
        head_of_household_age=40,
    )
    case = create_case(survivor["id"])
    item = document_damage(
        case["id"],
        category="STRUCTURE",
        item_description="Rear wall",
        documented_cost_cents=1_000_000,
        photo_count=5,
    )
    verify_damage(item["id"], verified_cost_cents=1_000_000)
    assessment = run_assessment(case["id"])
    first_org = seat_member_org(
        org_name="Aggregate Org One",
        org_type="FAITH_BASED",
        contact_email="one@agg.example",
        annual_pledge_cap_cents=3_000_000,
    )
    second_org = seat_member_org(
        org_name="Aggregate Org Two",
        org_type="NONPROFIT",
        contact_email="two@agg.example",
        annual_pledge_cap_cents=3_000_000,
    )
    create_funding_source(
        label="Bridge pool for the aggregate ceiling case",
        source_type="INDIVIDUAL_DONATION",
        restriction_code="UNRESTRICTED",
        total_cents=1_000_000,
    )
    session = schedule_session(
        session_label="UNT aggregate ceiling", quorum_min_member_orgs=2
    )
    open_session(session["id"], [first_org["id"], second_org["id"]])
    presentation = queue_presentation(case["id"], session["id"], assessment["id"])
    present_and_deliberate(presentation["id"])
    pledge(presentation["id"], first_org["id"], 600_000)
    second_pledge = pledge(presentation["id"], second_org["id"], 600_000)
    assert read_presentation(presentation["id"])["pledged_total_cents"] == 1_200_000

    overshoot = api.decide_case_presentation(
        presentation["id"],
        {"decision": "AWARD", "decision_note": "Attempting to award over the unmet need."},
        CHAIR,
    )

    validate_error(overshoot, ApiErrorId.ERR_AWARD_EXCEEDS_UNMET_NEED.value, 422)
    held = read_presentation(presentation["id"])
    assert held["status"] == "DELIBERATING"
    assert held["awarded_cents"] == 0
    rescinded = validate_success(
        api.rescind_funding_commitment(
            second_pledge["id"],
            {"rescission_reason": "Org Two withdraws to keep the award inside the unmet need."},
            make_member_org_delegate_headers(second_org["id"]),
        )
    )
    assert rescinded["status"] == "RESCINDED"
    assert read_presentation(presentation["id"])["pledged_total_cents"] == 600_000
    awarded = decide(
        presentation["id"], "AWARD", decision_note="Awarding within the unmet need."
    )
    assert awarded["status"] == "AWARDED"
    assert awarded["bridge_tier"] == "TIER_B"
    assert awarded["bridge_authorized_cents"] == 300_000
    assert awarded["awarded_cents"] == 900_000
    assert awarded["shortfall_cents"] == 100_000


def test_a_crew_may_not_be_booked_into_the_past(api):
    """PRD §3.8: "First, the dates must be sane: `departure_date` must fall on or after
    `arrival_date`, and `arrival_date` must fall on or after the logical clock's current
    date; a violation is refused with `ERR_INVALID_DATE_RANGE`."

    Design: Corner/validations/corner_deployment_arrival_before_the_logical_clock_is_refused
    """
    set_clock()
    survivor = create_survivor(
        household_name="Castellano Household",
        primary_contact_phone="555-0237",
        household_size=2,
        income_band="LOW",
        head_of_household_age=43,
    )
    case = create_case(survivor["id"])
    project = create_project(
        case["id"],
        required_trade_hours={"GENERAL_LABOR": 180},
        estimated_material_cents=200_000,
    )
    permit_project(project["id"], permit_number="PB-4036")
    group = create_group(
        group_name="Group Sierra",
        home_organization="Sierra Chapel",
        member_count=6,
        skill_profile={"GENERAL_LABOR": 6},
    )

    # The window is internally well ordered but both ends sit before the logical clock.
    past = api.create_volunteer_deployment(
        volunteer_deployment_payload(
            group["id"], project["id"], "2026-08-25", "2026-08-29"
        ),
        COORDINATOR,
    )

    validate_error(past, ApiErrorId.ERR_INVALID_DATE_RANGE.value, 422)
    future = validate_success(
        api.create_volunteer_deployment(
            volunteer_deployment_payload(
                group["id"], project["id"], "2026-09-07", "2026-09-11"
            ),
            COORDINATOR,
        ),
        201,
    )
    assert future["skill_fit_score_bps"] == 10000
    assert future["status"] == "REQUESTED"
    booked, meta = validate_paginated(
        api.list_volunteer_deployments(COORDINATOR, params={"group_id": group["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in booked] == [future["id"]]


def test_the_table_may_not_record_an_award_of_nothing(api):
    """PRD §3.5: "the computed `awarded_cents` must be strictly greater than 0, or
    `ERR_AWARD_ZERO` results — the table may not record an award of nothing."

    Design: Corner/validations/corner_award_computing_to_zero_is_refused
    """
    set_clock()
    survivor = create_survivor(
        household_name="Delacroix Household",
        primary_contact_phone="555-0238",
        household_size=2,
        income_band="LOW",
        head_of_household_age=47,
    )
    case = create_case(survivor["id"])
    item = document_damage(
        case["id"],
        category="STRUCTURE",
        item_description="Porch rebuild",
        documented_cost_cents=500_000,
        photo_count=3,
    )
    verify_damage(item["id"], verified_cost_cents=500_000)
    record_assistance(
        case["id"],
        source_type="INSURANCE_SETTLEMENT",
        purpose_code="STRUCTURE_REPAIR",
        awarded_cents=500_000,
        received_on="2026-08-12",
        documentation_status="DOCUMENTED",
    )
    assessment = run_assessment(case["id"])
    org = seat_member_org(
        org_name="Zero Award Org",
        org_type="NONPROFIT",
        contact_email="z@table.example",
        annual_pledge_cap_cents=3_000_000,
    )
    session = schedule_session(session_label="UNT zero award", quorum_min_member_orgs=1)
    open_session(session["id"], [org["id"]])
    presentation = queue_presentation(
        case["id"], session["id"], assessment["id"], narrative="Fully offset case."
    )
    present_and_deliberate(presentation["id"])
    assert assessment["unmet_need_total_cents"] == 0
    assert assessment["bucket_need_cents"]["STRUCTURE_REPAIR"] == 500_000
    assert assessment["bucket_offset_cents"]["STRUCTURE_REPAIR"] == 500_000

    empty_award = api.decide_case_presentation(
        presentation["id"],
        {"decision": "AWARD", "decision_note": "Attempting a zero award."},
        CHAIR,
    )

    validate_error(empty_award, ApiErrorId.ERR_AWARD_ZERO.value, 422)
    assert read_presentation(presentation["id"])["status"] == "DELIBERATING"
    denied = decide(
        presentation["id"], "DENY", decision_note="Nothing unmet; no assistance needed."
    )
    assert denied["status"] == "DENIED"
    rewound = read_case(case["id"])
    assert rewound["case_status"] == "ASSESSED"
    assert rewound["funding_status"] == "UNFUNDED"


def test_a_case_returns_to_the_queue_once_nothing_is_live(api):
    """PRD §3.4: "the case must have no other presentation in `QUEUED`, `PRESENTING` or
    `DELIBERATING` — a second live presentation is refused with
    `ERR_PRESENTATION_ALREADY_ACTIVE`."

    Design: Corner/validations/corner_case_may_be_queued_again_once_no_presentation_is_active
    """
    set_clock()
    survivor = create_survivor(
        household_name="Eberhardt Household",
        primary_contact_phone="555-0239",
        household_size=3,
        income_band="VLI",
        head_of_household_age=50,
    )
    case = create_case(survivor["id"])
    item = document_damage(
        case["id"],
        category="STRUCTURE",
        item_description="Garage wall",
        documented_cost_cents=700_000,
        photo_count=3,
    )
    verify_damage(item["id"], verified_cost_cents=700_000)
    assessment = run_assessment(case["id"])
    org = seat_member_org(
        org_name="Requeue Org",
        org_type="FAITH_BASED",
        contact_email="r@table.example",
        annual_pledge_cap_cents=3_000_000,
    )
    session = schedule_session(
        session_label="UNT single active presentation", quorum_min_member_orgs=1
    )
    open_session(session["id"], [org["id"]])
    live = queue_presentation(
        case["id"], session["id"], assessment["id"], narrative="First attempt."
    )

    duplicate = api.create_case_presentation(
        case_presentation_payload(
            case["id"],
            session["id"],
            assessment["id"],
            narrative="Duplicate while the first is queued.",
        ),
        CASE_MANAGER,
    )

    validate_error(duplicate, ApiErrorId.ERR_PRESENTATION_ALREADY_ACTIVE.value, 409)
    present(live["id"])
    deliberate(live["id"])
    denied = decide(live["id"], "DENY", decision_note="Table declines for now.")
    assert denied["status"] == "DENIED"
    assert read_case(case["id"])["case_status"] == "ASSESSED"
    second = validate_success(
        api.create_case_presentation(
            case_presentation_payload(
                case["id"],
                session["id"],
                assessment["id"],
                narrative="Second attempt after the denial.",
            ),
            CASE_MANAGER,
        ),
        201,
    )
    assert_case_presentation(second)
    assert second["id"] != live["id"]
    assert second["status"] == "QUEUED"
    assert second["queue_position"] == 1


def test_the_identity_check_binds_the_delegate_and_not_the_administrator(api):
    """PRD §2.1: "Concretely, a delegate creating a pledge must supply a `member_org_id`
    equal to their own `X-User-ID`, and a delegate rescinding a pledge must be the delegate
    of that pledge's `member_org_id`; a mismatch is rejected with
    `ERR_ORG_IDENTITY_MISMATCH` (HTTP 403)."

    Design: Corner/validations/corner_org_identity_check_applies_only_to_the_delegate_role
    """
    set_clock()
    survivor = create_survivor(
        household_name="Fontaine Household",
        primary_contact_phone="555-0240",
        household_size=3,
        income_band="VLI",
        head_of_household_age=52,
    )
    case = create_case(survivor["id"])
    item = document_damage(
        case["id"],
        category="STRUCTURE",
        item_description="Kitchen rebuild",
        documented_cost_cents=900_000,
        photo_count=4,
    )
    verify_damage(item["id"], verified_cost_cents=900_000)
    assessment = run_assessment(case["id"])
    first_org = seat_member_org(
        org_name="Identity Org One",
        org_type="FAITH_BASED",
        contact_email="one@id.example",
        annual_pledge_cap_cents=3_000_000,
    )
    second_org = seat_member_org(
        org_name="Identity Org Two",
        org_type="NONPROFIT",
        contact_email="two@id.example",
        annual_pledge_cap_cents=3_000_000,
    )
    session = schedule_session(session_label="UNT identity gate", quorum_min_member_orgs=2)
    open_session(session["id"], [first_org["id"], second_org["id"]])
    presentation = queue_presentation(
        case["id"], session["id"], assessment["id"], narrative="Kitchen rebuild request."
    )
    window = present_and_deliberate(presentation["id"])
    pledge_body = funding_commitment_payload(
        presentation["id"], second_org["id"], 200_000, window["version"]
    )

    impersonation = api.create_funding_commitment(
        pledge_body, make_member_org_delegate_headers(first_org["id"])
    )

    validate_error(impersonation, ApiErrorId.ERR_ORG_IDENTITY_MISMATCH.value, 403)
    on_behalf = validate_success(api.create_funding_commitment(pledge_body, ADMIN), 201)
    assert_funding_commitment(on_behalf)
    assert on_behalf["member_org_id"] == second_org["id"]
    assert on_behalf["status"] == "PLEDGED"
    assert on_behalf["pledged_by_user_id"] == ADMIN["X-User-ID"]
    credited = read_member_org(second_org["id"])
    assert credited["committed_cents"] == 200_000
    assert credited["remaining_pledge_capacity_cents"] == 2_800_000
    assert credited["status"] == "ACTIVE"
