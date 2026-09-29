"""Lifecycle moves: the legal ones, the illegal ones and the cascades they drag along.

Each test drives a record to one particular state and then probes the single hop the
contract either permits or forbids from there.
"""

from test_helpers import (
    ADMIN,
    BUILDER,
    CASE_MANAGER,
    CHAIR,
    COORDINATOR,
    OFFICER,
    ApiErrorId,
    assert_bed_night_identity,
    assert_case_presentation,
    assert_clock_reading,
    assert_construction_project,
    assert_damage_item,
    assert_disbursement,
    assert_funding_source,
    assert_housing_assignment,
    assert_lodging_site,
    assert_table_session,
    assert_version_unchanged,
    create_case,
    create_funding_source,
    create_group,
    create_housing_assignment,
    create_lodging_site,
    create_project,
    create_survivor,
    document_damage,
    funding_commitment_payload,
    make_member_org_delegate_headers,
    open_session,
    queue_presentation,
    read_case,
    read_presentation,
    record_assistance,
    request_disbursement,
    run_assessment,
    schedule_session,
    seat_member_org,
    set_clock,
    transition_project,
    validate_error,
    validate_paginated,
    validate_success,
    verify_damage,
)


def test_a_newly_scoped_phase_starts_unpermitted(api):
    """PRD §3.7: "A new phase starts at `status` `SCOPED` with `permit_number` and
    `suspension_reason` null, `volunteer_hours_logged` at 0 and
    `confirmed_deployment_count` at 0."

    Design: Corner/state_machines/corner_project_initial_state_is_scoped
    """
    set_clock()
    survivor = create_survivor(
        household_name="Jansen Household",
        primary_contact_phone="555-0211",
        household_size=2,
        income_band="LOW",
        head_of_household_age=43,
    )
    case = create_case(survivor["id"])

    created = validate_success(
        api.create_construction_project(
            {
                "case_id": case["id"],
                "scope_code": "INTERIOR_REPAIR",
                "required_trade_hours": {"GENERAL_LABOR": 100},
                "estimated_material_cents": 250_000,
            },
            BUILDER,
        ),
        201,
    )

    assert_construction_project(created)
    assert created["status"] == "SCOPED"
    assert created["confirmed_deployment_count"] == 0
    assert created["permit_number"] is None
    assert created["predecessor_project_id"] is None
    assert created["version"] == 1


def test_opening_a_meeting_records_the_room(api):
    """PRD §3.4: "On success the server stores the attendance list and stamps
    `chaired_by_user_id` from the acting identity."

    Design: Corner/state_machines/corner_session_open_valid_transition_records_attendance
    """
    set_clock()
    alpha = seat_member_org(
        org_name="Alpha Relief",
        org_type="FAITH_BASED",
        contact_email="a@alpha.example",
        annual_pledge_cap_cents=3_000_000,
    )
    bravo = seat_member_org(
        org_name="Bravo Relief",
        org_type="NONPROFIT",
        contact_email="b@bravo.example",
        annual_pledge_cap_cents=3_000_000,
    )
    session = schedule_session(session_label="UNT open test", quorum_min_member_orgs=2)

    opened = validate_success(
        api.open_table_session(
            session["id"], {"attending_member_org_ids": [alpha["id"], bravo["id"]]}, CHAIR
        )
    )

    assert_table_session(opened)
    assert opened["status"] == "IN_SESSION"
    assert set(opened["attending_member_org_ids"]) == {alpha["id"], bravo["id"]}
    assert opened["chaired_by_user_id"] == CHAIR["X-User-ID"]
    assert opened["version"] == 2


def test_opening_a_meeting_one_organization_short_is_refused(api):
    """PRD §3.4: "The list must contain at least `quorum_min_member_orgs` entries or the
    request is refused with `ERR_QUORUM_NOT_MET`, and every id in it must resolve to a
    member organization whose `status` is either `ACTIVE` or `CAPPED` — a list naming a
    `SUSPENDED` or `WITHDRAWN` organization is refused with `ERR_MEMBER_ORG_NOT_ACTIVE`."

    Design: Corner/state_machines/corner_session_open_below_quorum_is_refused
    """
    set_clock()
    alpha = seat_member_org(
        org_name="Alpha Relief",
        org_type="FAITH_BASED",
        contact_email="a@alpha.example",
        annual_pledge_cap_cents=3_000_000,
    )
    bravo = seat_member_org(
        org_name="Bravo Relief",
        org_type="NONPROFIT",
        contact_email="b@bravo.example",
        annual_pledge_cap_cents=3_000_000,
    )
    session = schedule_session(session_label="UNT quorum test", quorum_min_member_orgs=2)

    short = api.open_table_session(
        session["id"], {"attending_member_org_ids": [alpha["id"]]}, CHAIR
    )

    validate_error(short, ApiErrorId.ERR_QUORUM_NOT_MET.value, 409)
    unopened = validate_success(api.get_table_session(session["id"], CHAIR))
    assert unopened["status"] == "SCHEDULED"
    assert unopened["attending_member_org_ids"] == []
    assert_version_unchanged(session, unopened)
    # The second organization is the only thing that changed; the call is otherwise identical.
    opened = validate_success(
        api.open_table_session(
            session["id"], {"attending_member_org_ids": [alpha["id"], bravo["id"]]}, CHAIR
        )
    )
    assert opened["status"] == "IN_SESSION"
    assert opened["version"] == 2


def test_opening_the_pledge_window_on_an_uncalled_case_is_refused(api):
    """PRD §3.4: "The chair then opens the pledge window by moving the presentation
    `PRESENTING → DELIBERATING`, which again requires the session to be `IN_SESSION`."

    Design: Corner/state_machines/corner_deliberate_from_queued_is_an_invalid_transition
    """
    set_clock()
    survivor = create_survivor(
        household_name="Kowalski Household",
        primary_contact_phone="555-0212",
        household_size=2,
        income_band="LOW",
        head_of_household_age=49,
    )
    case = create_case(survivor["id"])
    item = document_damage(
        case["id"],
        category="STRUCTURE",
        item_description="Window replacement",
        documented_cost_cents=700_000,
    )
    verify_damage(item["id"], verified_cost_cents=700_000)
    assessment = run_assessment(case["id"])
    alpha = seat_member_org(
        org_name="Alpha Relief",
        org_type="FAITH_BASED",
        contact_email="a@alpha.example",
        annual_pledge_cap_cents=3_000_000,
    )
    session = schedule_session(
        session_label="UNT invalid transition", quorum_min_member_orgs=1
    )
    open_session(session["id"], [alpha["id"]])
    presentation = queue_presentation(case["id"], session["id"], assessment["id"])

    response = api.deliberate_case_presentation(presentation["id"], {}, CHAIR)

    validate_error(response, ApiErrorId.ERR_PRESENTATION_INVALID_STATE.value, 409)
    after = read_presentation(presentation["id"])
    assert_case_presentation(after)
    assert after["status"] == "QUEUED"
    assert after["queue_position"] == 1
    assert_version_unchanged(presentation, after)
    # The window never opened, so a pledge sized against the very version the delegate
    # holds is still refused.
    pledge_attempt = api.create_funding_commitment(
        funding_commitment_payload(
            presentation["id"], alpha["id"], 100_000, presentation["version"]
        ),
        make_member_org_delegate_headers(alpha["id"]),
    )
    validate_error(
        pledge_attempt, ApiErrorId.ERR_PRESENTATION_NOT_ACCEPTING_PLEDGES.value, 409
    )


def test_a_closed_out_phase_accepts_no_further_action(api):
    """PRD §3.7: "Any action not declared from the project's current status is refused with
    `ERR_PROJECT_INVALID_TRANSITION`, and every accepted action increments the project's
    `version`."

    Design: Corner/state_machines/corner_closed_out_project_is_terminal_and_rejects_further_transitions
    """
    set_clock()
    survivor = create_survivor(
        household_name="Lindqvist Household",
        primary_contact_phone="555-0213",
        household_size=2,
        income_band="LOW",
        head_of_household_age=52,
    )
    case = create_case(survivor["id"])
    project = create_project(
        case["id"],
        required_trade_hours={"GENERAL_LABOR": 80},
        estimated_material_cents=150_000,
    )
    transition_project(project["id"], "PERMIT", permit_number="PB-4013")
    transition_project(project["id"], "START")
    transition_project(project["id"], "PUNCHLIST")
    closed_out = transition_project(project["id"], "CLOSE_OUT")
    assert closed_out["status"] == "CLOSED_OUT"

    resume = api.transition_construction_project(project["id"], {"action": "RESUME"}, BUILDER)
    cancel = api.transition_construction_project(
        project["id"],
        {"action": "CANCEL", "reason": "Attempt to cancel a completed project."},
        BUILDER,
    )

    validate_error(resume, ApiErrorId.ERR_PROJECT_INVALID_TRANSITION.value, 409)
    validate_error(cancel, ApiErrorId.ERR_PROJECT_INVALID_TRANSITION.value, 409)
    after = validate_success(api.get_construction_project(project["id"], BUILDER))
    assert after["status"] == "CLOSED_OUT"
    assert_version_unchanged(closed_out, after)


def test_a_second_inspection_of_the_same_damage_item_is_refused(api):
    """PRD §3.2: "Verification is a one-shot act: a second attempt on an item whose
    `verification_status` is no longer `UNVERIFIED` is refused with
    `ERR_DAMAGE_ITEM_ALREADY_VERIFIED`."

    Design: Corner/state_machines/corner_second_verification_of_the_same_damage_item_is_rejected
    """
    set_clock()
    survivor = create_survivor(
        household_name="Moreau Household",
        primary_contact_phone="555-0214",
        household_size=3,
        income_band="VLI",
        head_of_household_age=55,
    )
    case = create_case(survivor["id"])
    item = document_damage(
        case["id"],
        category="STRUCTURE",
        item_description="Roof deck",
        documented_cost_cents=1_000_000,
    )
    verify_damage(item["id"], verification_status="VERIFIED", verified_cost_cents=900_000)

    response = api.verify_damage_item(
        item["id"],
        {"verification_status": "VERIFIED", "verified_cost_cents": 1_500_000},
        BUILDER,
    )

    validate_error(response, ApiErrorId.ERR_DAMAGE_ITEM_ALREADY_VERIFIED.value, 409)
    items, meta = validate_paginated(api.list_damage_items(case["id"], CASE_MANAGER))
    assert meta["total_count"] == 1
    stored = items[0]
    assert_damage_item(stored)
    assert stored["verification_status"] == "VERIFIED"
    assert stored["verified_cost_cents"] == 900_000
    assert stored["documented_cost_cents"] == 1_000_000


def test_excluding_the_disputed_award_carries_the_request_back_to_cleared(api):
    """PRD §3.6: "On success each listed record has `is_excluded_from_dob` set to true and
    its `exclusion_note` recorded; the disbursement's `dob_resolution_note` is stored and
    its status returns to `REQUESTED`; and the duplication-of-benefits check is immediately
    re-run, forking the row on to `DOB_CLEARED` or straight back to `DOB_FLAGGED`."

    Design: Corner/state_machines/corner_dob_flagged_cycles_back_through_requested_to_cleared
    """
    set_clock()
    survivor = create_survivor(
        household_name="Nowak Household",
        primary_contact_phone="555-0215",
        household_size=3,
        income_band="VLI",
        head_of_household_age=51,
    )
    case = create_case(survivor["id"], primary_residence_status="RENTER")
    item = document_damage(
        case["id"],
        category="CONTENTS",
        item_description="Contents loss",
        documented_cost_cents=1_000_000,
        photo_count=6,
        is_habitability_critical=False,
    )
    verify_damage(item["id"], verified_cost_cents=1_000_000)
    record_assistance(
        case["id"],
        source_type="NONPROFIT_GRANT",
        purpose_code="CONTENTS_REPLACEMENT",
        awarded_cents=400_000,
        received_on="2026-08-01",
        documentation_status="DOCUMENTED",
    )
    insurance = record_assistance(
        case["id"],
        source_type="INSURANCE_SETTLEMENT",
        purpose_code="CONTENTS_REPLACEMENT",
        awarded_cents=500_000,
        received_on="2026-08-05",
        documentation_status="DOCUMENTED",
    )
    requested = request_disbursement(
        case["id"], "CONTENTS_REPLACEMENT", 500_000, payee_name="Valley Furniture Co"
    )
    # 900000 of documented contents money plus this 500000 request against a 1000000
    # contents need leaves 400000 of exposure, so the row forked to the flagged branch.
    assert requested["status"] == "DOB_FLAGGED"
    assert requested["dob_pool_cents"] == 900_000
    assert requested["dob_exposure_cents"] == 400_000

    resolved = validate_success(
        api.resolve_disbursement_dob(
            requested["id"],
            {
                "dob_resolution_note": (
                    "The 500000 insurance payment was for a different property and is excluded."
                ),
                "excluded_assistance_record_ids": [insurance["id"]],
            },
            OFFICER,
        )
    )

    assert_disbursement(resolved)
    assert resolved["status"] == "DOB_CLEARED"
    assert resolved["dob_pool_cents"] == 400_000
    assert resolved["dob_exposure_cents"] == 0
    stored = validate_success(api.get_disbursement(requested["id"], OFFICER))
    assert stored["status"] == "DOB_CLEARED"
    assert "different property" in stored["dob_resolution_note"]
    records, _ = validate_paginated(api.list_assistance_records(case["id"], CASE_MANAGER))
    excluded = [row for row in records if row["id"] == insurance["id"]][0]
    assert excluded["is_excluded_from_dob"] is True


def test_adjourning_defers_every_case_still_waiting_its_turn(api):
    """PRD §3.5: "A queued presentation whose `deferral_count` is still below 3 moves
    `QUEUED → DEFERRED` and its `deferral_count` increments by 1. Its commitments are left
    in `PLEDGED` so the pledges survive to the next meeting, no organization's
    `committed_cents` or `remaining_pledge_capacity_cents` changes, the case's
    `case_status` stays `PRESENTED`, and the session's `queued_count` decrements."

    Design: Corner/state_machines/corner_adjourn_cascades_queued_presentations_to_deferred
    """
    set_clock()
    survivor = create_survivor(
        household_name="Oyelaran Household",
        primary_contact_phone="555-0216",
        household_size=4,
        income_band="VLI",
        head_of_household_age=46,
    )
    first_case = create_case(survivor["id"], disaster_code="DR-4801")
    second_case = create_case(survivor["id"], disaster_code="DR-4802")
    for case, description in ((first_case, "Repair A"), (second_case, "Repair B")):
        item = document_damage(
            case["id"],
            category="STRUCTURE",
            item_description=description,
            documented_cost_cents=600_000,
        )
        verify_damage(item["id"], verified_cost_cents=600_000)
    first_assessment = run_assessment(first_case["id"])
    second_assessment = run_assessment(second_case["id"])
    alpha = seat_member_org(
        org_name="Alpha Relief",
        org_type="FAITH_BASED",
        contact_email="a@alpha.example",
        annual_pledge_cap_cents=3_000_000,
    )
    session = schedule_session(
        session_label="UNT adjourn cascade", quorum_min_member_orgs=1
    )
    open_session(session["id"], [alpha["id"]])
    queue_presentation(first_case["id"], session["id"], first_assessment["id"])
    queue_presentation(second_case["id"], session["id"], second_assessment["id"])

    adjourned = validate_success(
        api.adjourn_table_session(
            session["id"], {"minutes_note": "Out of time; both cases carried over."}, CHAIR
        )
    )

    assert_table_session(adjourned)
    assert adjourned["status"] == "ADJOURNED"
    assert adjourned["queued_count"] == 0
    presentations, meta = validate_paginated(
        api.list_case_presentations(CHAIR, params={"session_id": session["id"]})
    )
    assert meta["total_count"] == 2
    for row in presentations:
        assert_case_presentation(row)
        assert row["status"] == "DEFERRED"
        assert row["deferral_count"] == 1
    carried = read_case(first_case["id"])
    assert carried["case_status"] == "PRESENTED"
    assert carried["funding_status"] == "UNFUNDED"


def test_advancing_the_clock_expires_only_the_lapsed_grant(api):
    """PRD §2.4: "Setting the clock moves every funding source that is `OPEN` and whose
    `expires_on` falls strictly before the new current date into `EXPIRED`."

    Design: Corner/state_machines/corner_clock_advance_expires_only_sources_past_their_expiry_date
    """
    set_clock()
    early = create_funding_source(
        label="Early grant",
        source_type="FOUNDATION_GRANT",
        restriction_code="STRUCTURE_REPAIR_ONLY",
        total_cents=500_000,
        expires_on="2026-09-30",
    )
    late = create_funding_source(
        label="Late grant",
        source_type="FOUNDATION_GRANT",
        restriction_code="STRUCTURE_REPAIR_ONLY",
        total_cents=500_000,
        expires_on="2026-11-30",
    )
    open_ended = create_funding_source(
        label="Open-ended donations",
        source_type="INDIVIDUAL_DONATION",
        restriction_code="UNRESTRICTED",
        total_cents=500_000,
    )

    reading = validate_success(
        api.set_clock({"to_iso8601": "2026-10-15T00:00:00Z"}, ADMIN)
    )

    assert_clock_reading(reading)
    assert reading["current_utc"].startswith("2026-10-15T00:00:00")
    assert reading["expired_funding_source_ids"] == [early["id"]]
    expired, expired_meta = validate_paginated(
        api.list_funding_sources(OFFICER, params={"status": "EXPIRED"})
    )
    assert expired_meta["total_count"] == 1
    assert [row["id"] for row in expired] == [early["id"]]
    still_open, open_meta = validate_paginated(
        api.list_funding_sources(OFFICER, params={"status": "OPEN"})
    )
    assert open_meta["total_count"] == 2
    assert {row["id"] for row in still_open} == {late["id"], open_ended["id"]}
    for row in still_open:
        assert_funding_source(row)
        assert row["available_cents"] == 500_000


def test_releasing_one_crews_beds_re_derives_the_sites_worst_night(api):
    """PRD §3.8: "Releasing an assignment supplies a `release_reason`, moves it
    `ACTIVE → RELEASED`, stamps `released_at` from the logical clock, recomputes the site's
    `peak_committed_beds` and `available_beds`, moves the site `FULL → OPEN` when the
    recomputed peak falls below `bed_capacity`, and increments the site's `version`."

    Design: Corner/state_machines/corner_housing_release_syncs_lodging_site_ledger
    """
    set_clock()
    site = create_lodging_site(site_name="Riverside Camp", bed_capacity=18, has_showers=True)
    papa = create_group(
        group_name="Group Papa",
        home_organization="Papa Parish",
        member_count=12,
        skill_profile={"GENERAL_LABOR": 12},
        requires_housing=True,
    )
    quebec = create_group(
        group_name="Group Quebec",
        home_organization="Quebec Parish",
        member_count=6,
        skill_profile={"GENERAL_LABOR": 6},
        requires_housing=True,
    )
    papa_stay = create_housing_assignment(
        papa["id"], site["id"], "2026-09-07", "2026-09-10"
    )
    quebec_stay = create_housing_assignment(
        quebec["id"], site["id"], "2026-09-07", "2026-09-10"
    )
    full = validate_success(api.get_lodging_site(site["id"], COORDINATOR))
    assert full["peak_committed_beds"] == 18
    assert full["available_beds"] == 0
    assert full["status"] == "FULL"

    released = validate_success(
        api.release_housing_assignment(
            papa_stay["id"], {"release_reason": "Group Papa cancelled their travel."}, COORDINATOR
        )
    )

    assert_housing_assignment(released)
    assert released["status"] == "RELEASED"
    assert released["released_at"] is not None
    assert released["released_at"].startswith("2026-09-01")
    after = validate_success(api.get_lodging_site(site["id"], COORDINATOR))
    assert_lodging_site(after)
    assert after["peak_committed_beds"] == 6
    assert after["available_beds"] == 12
    assert after["status"] == "OPEN"
    assert_bed_night_identity(after)
    remaining, meta = validate_paginated(
        api.list_housing_assignments(
            COORDINATOR, params={"lodging_site_id": site["id"], "status": "ACTIVE"}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in remaining] == [quebec_stay["id"]]
