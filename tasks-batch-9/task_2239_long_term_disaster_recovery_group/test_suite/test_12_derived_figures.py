"""Arithmetic the coalition depends on: ceilings, weighted scores and the drawing order.

Every figure here is chosen so that only the declared formula reproduces it — a plausible
shortcut (capping the sum, summing documented costs, weighting every trade equally,
drawing from the largest source first) lands on a different number.
"""

from test_helpers import (
    ADMIN,
    BUILDER,
    CASE_MANAGER,
    COORDINATOR,
    INTAKE,
    ApiErrorId,
    assert_case_presentation,
    assert_damage_item,
    assert_disbursement,
    assert_funding_source,
    assert_skill_fit_report,
    assert_survivor,
    assert_unmet_need_assessment,
    assert_volunteer_deployment,
    case_presentation_payload,
    create_case,
    create_deployment,
    create_funding_source,
    create_group,
    create_project,
    create_survivor,
    decide,
    document_damage,
    open_session,
    permit_project,
    pledge,
    present_and_deliberate,
    queue_presentation,
    read_case,
    read_funding_source,
    record_assistance,
    request_disbursement,
    run_assessment,
    schedule_session,
    seat_member_org,
    set_clock,
    survivor_payload,
    validate_error,
    validate_paginated,
    validate_success,
    verify_damage,
)


def test_each_ruined_item_is_capped_before_the_case_total_is_taken(api):
    """PRD §3.2: "Structural damage is capped at $120,000 per item; a roof at $35,000; HVAC
    at $12,000; plumbing at $9,000; electrical at $9,000; contents at $15,000; and
    accessibility work at $25,000. The cap is applied to each item individually, before any
    summation."

    Design: Corner/calculations/corner_verified_damage_total_caps_each_item_before_summing
    """
    set_clock()
    survivor = create_survivor(
        household_name="Petrov Household",
        primary_contact_phone="555-0221",
        household_size=3,
        income_band="LOW",
        head_of_household_age=44,
    )
    case = create_case(survivor["id"])
    structure = document_damage(
        case["id"],
        category="STRUCTURE",
        item_description="Total structural rebuild",
        documented_cost_cents=13_000_000,
        photo_count=12,
    )
    verify_damage(structure["id"], verified_cost_cents=13_000_000)
    contents = document_damage(
        case["id"],
        category="CONTENTS",
        item_description="Whole-house contents",
        documented_cost_cents=2_000_000,
        photo_count=9,
        is_habitability_critical=False,
    )

    verified_contents = validate_success(
        api.verify_damage_item(
            contents["id"],
            {"verification_status": "VERIFIED", "verified_cost_cents": 2_000_000},
            BUILDER,
        )
    )

    assert_damage_item(verified_contents)
    assert verified_contents["capped_cost_cents"] == 1_500_000
    refreshed = read_case(case["id"])
    # 12000000 + 1500000, not the 15000000 raw sum and not a single 12000000 ceiling
    # laid over the whole total.
    assert refreshed["verified_damage_total_cents"] == 13_500_000


def test_rejected_and_uninspected_damage_contributes_nothing(api):
    """PRD §3.2: "`verified_damage_total_cents` becomes the sum, over every damage item on
    the case whose `verification_status` is `VERIFIED`, of the smaller of that item's
    `verified_cost_cents` and its category ceiling. Items that are `UNVERIFIED` or
    `REJECTED` contribute nothing."

    Design: Corner/calculations/corner_verified_damage_total_ignores_rejected_and_unverified_items
    """
    set_clock()
    survivor = create_survivor(
        household_name="Quintero Household",
        primary_contact_phone="555-0222",
        household_size=2,
        income_band="LOW",
        head_of_household_age=39,
    )
    case = create_case(survivor["id"])
    accepted = document_damage(
        case["id"],
        category="ROOF",
        item_description="Shingle patch",
        documented_cost_cents=500_000,
        photo_count=3,
    )
    disputed = document_damage(
        case["id"],
        category="CONTENTS",
        item_description="Claimed antiques",
        documented_cost_cents=800_000,
        photo_count=1,
        is_habitability_critical=False,
    )
    untouched = document_damage(
        case["id"],
        category="PLUMBING",
        item_description="Supply line",
        documented_cost_cents=900_000,
        photo_count=2,
    )
    verify_damage(accepted["id"], verified_cost_cents=500_000)

    rejected = validate_success(
        api.verify_damage_item(
            disputed["id"],
            {"verification_status": "REJECTED", "verified_cost_cents": 800_000},
            BUILDER,
        )
    )

    assert_damage_item(rejected)
    assert rejected["verification_status"] == "REJECTED"
    assert rejected["capped_cost_cents"] == 0
    refreshed = read_case(case["id"])
    # Summing documented costs over every row instead would report 2200000.
    assert refreshed["verified_damage_total_cents"] == 500_000
    pending, meta = validate_paginated(
        api.list_damage_items(
            case["id"], CASE_MANAGER, params={"verification_status": "UNVERIFIED"}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in pending] == [untouched["id"]]


def test_the_vulnerability_score_adds_every_term_that_applies(api):
    """PRD §3.1: "The five terms are added and the total is then capped at 100, so
    `priority_score` never exceeds 100."

    Design: Corner/calculations/corner_priority_score_sums_every_weighted_component
    """
    set_clock()

    created = validate_success(
        api.create_survivor(
            survivor_payload(
                household_name="Rasmussen Household",
                primary_contact_phone="555-0223",
                household_size=4,
                income_band="VLI",
                head_of_household_age=58,
                has_member_with_disability=True,
                is_uninsured=True,
                consent_on_file=True,
                follow_up_opt_in=True,
            ),
            INTAKE,
        ),
        201,
    )

    assert_survivor(created)
    # 30 for VLI + 12 for three extra members + 15 for the disability + 0 because 58 is
    # under the elder threshold + 15 for being uninsured.
    assert created["priority_score"] == 72


def test_a_very_large_household_stops_earning_points_at_the_cap(api):
    """PRD §3.1: "The household-size term contributes 4 points for each household member
    beyond the first, so a household of one contributes nothing, and the term is capped at
    20 points, which is reached at a household of six or more."

    Design: Corner/calculations/corner_household_size_points_stop_at_their_cap
    """
    set_clock()

    created = validate_success(
        api.create_survivor(
            survivor_payload(
                household_name="Sandoval Household",
                primary_contact_phone="555-0224",
                household_size=12,
                income_band="MODERATE",
                head_of_household_age=41,
                has_member_with_disability=False,
                is_uninsured=False,
                consent_on_file=True,
                follow_up_opt_in=True,
            ),
            INTAKE,
        ),
        201,
    )

    assert_survivor(created)
    # 10 for MODERATE plus the household term stopped at 20; an uncapped 4 * 11 would
    # report 54, and 30 is nowhere near the 100 ceiling that could otherwise explain it.
    assert created["priority_score"] == 30
    stored = validate_success(api.get_survivor(created["id"], INTAKE))
    assert stored["priority_score"] == 30


def test_the_pooled_triage_figure_may_be_computed_but_never_presented(api):
    """PRD §3.4: "The pinned snapshot's `variant` must be `PURPOSE_MATCHED`, since a
    `POOLED` figure may not be presented, and a `POOLED` pin is refused with
    `ERR_ASSESSMENT_VARIANT_NOT_ELIGIBLE`."

    Design: Corner/calculations/corner_pooled_variant_may_be_computed_but_not_presented
    """
    set_clock()
    survivor = create_survivor(
        household_name="Tanaka Household",
        primary_contact_phone="555-0225",
        household_size=2,
        income_band="LOW",
        head_of_household_age=47,
    )
    case = create_case(survivor["id"], temporary_housing_need_cents=100_000)
    item = document_damage(
        case["id"],
        category="STRUCTURE",
        item_description="Framing repair",
        documented_cost_cents=800_000,
        photo_count=5,
    )
    verify_damage(item["id"], verified_cost_cents=800_000)
    record_assistance(
        case["id"],
        source_type="FEMA_IA",
        purpose_code="TEMPORARY_HOUSING",
        awarded_cents=300_000,
        received_on="2026-08-10",
        documentation_status="DOCUMENTED",
    )
    org = seat_member_org(
        org_name="Alpha Relief",
        org_type="FAITH_BASED",
        contact_email="a@alpha.example",
        annual_pledge_cap_cents=3_000_000,
    )
    session = schedule_session(session_label="UNT variant gate", quorum_min_member_orgs=1)
    open_session(session["id"], [org["id"]])

    pooled = validate_success(
        api.create_assessment(case["id"], {"variant": "POOLED"}, CASE_MANAGER), 201
    )
    refused = api.create_case_presentation(
        case_presentation_payload(
            case["id"],
            session["id"],
            pooled["id"],
            narrative="Attempting to present the pooled figure.",
        ),
        CASE_MANAGER,
    )

    assert_unmet_need_assessment(pooled)
    # 900000 of need against a single 300000 pooled offset.
    assert pooled["unmet_need_total_cents"] == 600_000
    validate_error(refused, ApiErrorId.ERR_ASSESSMENT_VARIANT_NOT_ELIGIBLE.value, 422)
    assert read_case(case["id"])["case_status"] == "ASSESSED"
    purpose_matched = run_assessment(case["id"], "PURPOSE_MATCHED")
    # The housing offset cannot spill into the structure bucket, so 800000 survives.
    assert purpose_matched["unmet_need_total_cents"] == 800_000
    accepted = validate_success(
        api.create_case_presentation(
            case_presentation_payload(
                case["id"],
                session["id"],
                purpose_matched["id"],
                narrative="Presenting the purpose-matched figure.",
            ),
            CASE_MANAGER,
        ),
        201,
    )
    assert_case_presentation(accepted)
    assert accepted["status"] == "QUEUED"


def test_the_restricted_grant_is_drained_before_the_flexible_pool(api):
    """PRD §3.6: "The pool is then ordered by `restriction_specificity` descending, so
    restricted money is spent before unrestricted money and the flexible unrestricted
    balance is preserved for the cases that need it most; then by `expires_on` ascending
    with sources having no expiry ordered last, so money nearest to lapsing is used first;
    then by `created_at` ascending as the tie-break."

    Design: Corner/calculations/corner_waterfall_exhausts_the_restricted_source_before_the_unrestricted_one
    """
    set_clock()
    survivor = create_survivor(
        household_name="Uribe Household",
        primary_contact_phone="555-0226",
        household_size=3,
        income_band="VLI",
        head_of_household_age=50,
    )
    case = create_case(survivor["id"])
    item = document_damage(
        case["id"],
        category="STRUCTURE",
        item_description="Sill and joists",
        documented_cost_cents=1_500_000,
        photo_count=7,
    )
    verify_damage(item["id"], verified_cost_cents=1_500_000)
    assessment = run_assessment(case["id"])
    org = seat_member_org(
        org_name="Uribe Table Partner",
        org_type="NONPROFIT",
        contact_email="u@partner.example",
        annual_pledge_cap_cents=3_000_000,
    )
    restricted = create_funding_source(
        label="Rebuild-only grant",
        source_type="FOUNDATION_GRANT",
        restriction_code="STRUCTURE_REPAIR_ONLY",
        total_cents=400_000,
        admin_retention_allowed=False,
    )
    unrestricted = create_funding_source(
        label="General donations",
        source_type="INDIVIDUAL_DONATION",
        restriction_code="UNRESTRICTED",
        total_cents=2_000_000,
        admin_retention_allowed=True,
    )
    session = schedule_session(session_label="UNT waterfall", quorum_min_member_orgs=1)
    open_session(session["id"], [org["id"]])
    presentation = queue_presentation(case["id"], session["id"], assessment["id"])
    present_and_deliberate(presentation["id"])
    pledge(presentation["id"], org["id"], 900_000)
    awarded = decide(
        presentation["id"], "AWARD", decision_note="Awarded with a TIER_B bridge."
    )
    assert awarded["bridge_tier"] == "TIER_B"
    assert awarded["bridge_authorized_cents"] == 450_000
    assert awarded["awarded_cents"] == 1_350_000
    assert read_case(case["id"])["total_committed_cents"] == 1_350_000
    project = create_project(
        case["id"], required_trade_hours={"GENERAL_LABOR": 120}, estimated_material_cents=900_000
    )
    permit_project(project["id"], permit_number="PB-4026")
    requested = request_disbursement(
        case["id"],
        "STRUCTURE_REPAIR",
        900_000,
        payee_name="Harbor Builders LLC",
        project_id=project["id"],
    )

    approved = validate_success(
        api.approve_disbursement(
            requested["id"], {"approval_note": "Cleared for payment."}, ADMIN
        )
    )

    assert_disbursement(approved)
    assert approved["status"] == "APPROVED"
    assert approved["net_cents"] == 900_000
    assert approved["admin_retained_cents"] == 17_500
    assert approved["gross_cents"] == 917_500
    lines = approved["allocation_lines"]
    assert [line["funding_source_id"] for line in lines] == [
        restricted["id"],
        unrestricted["id"],
    ]
    assert lines[0]["net_cents"] == 400_000
    assert lines[0]["retention_cents"] == 0
    assert lines[0]["gross_cents"] == 400_000
    assert lines[1]["net_cents"] == 500_000
    assert lines[1]["retention_cents"] == 17_500
    assert lines[1]["gross_cents"] == 517_500
    drained = read_funding_source(restricted["id"])
    assert_funding_source(drained)
    assert drained["committed_cents"] == 400_000
    assert drained["available_cents"] == 0
    assert drained["status"] == "EXHAUSTED"


def test_a_critical_trade_counts_triple_in_the_crew_match(api):
    """PRD §3.8: "The trades considered are exactly the keys of the project's
    `required_trade_hours`. Each trade carries a weight of 3 when it appears in the
    project's `critical_trades` and 1 otherwise."

    Design: Corner/calculations/corner_skill_fit_applies_the_critical_trade_weight
    """
    set_clock()
    survivor = create_survivor(
        household_name="Vasquez Household",
        primary_contact_phone="555-0227",
        household_size=2,
        income_band="LOW",
        head_of_household_age=42,
    )
    case = create_case(survivor["id"])
    project = create_project(
        case["id"],
        required_trade_hours={"ROOFING": 60, "GENERAL_LABOR": 60},
        critical_trades=["ROOFING"],
        estimated_material_cents=300_000,
    )
    permit_project(project["id"], permit_number="PB-4027")
    group = create_group(
        group_name="Group Romeo",
        home_organization="Romeo Chapel",
        member_count=3,
        skill_profile={"ROOFING": 1, "GENERAL_LABOR": 2},
    )

    preview = validate_success(
        api.get_skill_fit(
            project["id"],
            COORDINATOR,
            params={
                "group_id": group["id"],
                "variant": "COVERAGE_WEIGHTED",
                "arrival_date": "2026-09-07",
                "departure_date": "2026-09-11",
            },
        )
    )

    assert_skill_fit_report(preview)
    assert preview["day_count"] == 5
    # One roofer covers 30 of the 60 roofing hours and two labourers cover all 60 labour
    # hours; weighting roofing at 3 gives 150 of 240, where equal weights would give 7500.
    assert preview["weighted_covered"] == 150
    assert preview["weighted_required"] == 240
    assert preview["score_bps"] == 6250
    assert preview["meets_minimum"] is True
    deployment = create_deployment(
        group["id"], project["id"], "2026-09-07", "2026-09-11"
    )
    assert_volunteer_deployment(deployment)
    assert deployment["skill_fit_score_bps"] == 6250
    assert deployment["status"] == "REQUESTED"
