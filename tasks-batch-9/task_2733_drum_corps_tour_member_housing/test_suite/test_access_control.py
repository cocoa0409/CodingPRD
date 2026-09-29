"""Role, ownership and four-eyes enforcement.

The five staff roles are peers rather than a hierarchy, the two entity-backed
roles are keyed on identity rather than role, and two separate rules forbid one
user from holding both halves of a two-step approval.
"""

from test_helpers import (
    ApiErrorId,
    BUSINESS_MANAGER_HEADERS,
    BUSINESS_MANAGER_ID,
    CORPS_DIRECTOR_HEADERS,
    ContractStatus,
    Duty,
    MEMBERSHIP_COORDINATOR_HEADERS,
    SECOND_BUSINESS_MANAGER_HEADERS,
    SECOND_BUSINESS_MANAGER_ID,
    SCREENER_AS_TOUR_MANAGER_HEADERS,
    SettlementStatus,
    StaffAssignmentStatus,
    TOUR_MANAGER_HEADERS,
    TOUR_MANAGER_ID,
    VOLUNTEER_SCREENER_HEADERS,
    VolunteerRoleType,
    assert_all_nulls,
    assert_member_contract,
    assert_show_settlement,
    assert_staff_assignment,
    assert_volunteer,
    factories as f,
    fixtures as fx,
    make_member_headers,
    make_volunteer_headers,
    validate_error,
    validate_paginated,
)

_PHANTOM_AGREEMENT_ID = "44444444-4444-4444-8444-444444444444"
_PHANTOM_MEMBER_ID = "55555555-5555-4555-8555-555555555555"


def test_no_staff_role_may_reach_into_another_roles_exclusive_write(api):
    """Seniority buys nothing: the role list is the whole authority.

    PRD: "The acting role appears in the called endpoint's authorized-role list — otherwise `ERR_UNAUTHORIZED`. Applies to every endpoint."

    Design: Corner/rbac/peer_role_exclusive_operations_are_forbidden_to_other_roles
    """
    season = fx.create_season(api)
    school = fx.create_school(api, name="Rockford High School", city="Rockford", state_code="IL")

    validate_error(
        api.create_member(f.member_payload(season["id"], full_name="Wrong Role"), TOUR_MANAGER_HEADERS),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    validate_error(
        api.create_tour_stop(
            f.rehearsal_stop_payload(season["id"], venue_name="Wrong Role Stop"),
            MEMBERSHIP_COORDINATOR_HEADERS,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    validate_error(
        api.create_host_school(
            f.host_school_payload(name="Wrong Role School", city="Peoria"),
            BUSINESS_MANAGER_HEADERS,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    validate_error(
        api.run_billing_cycle(season["id"], VOLUNTEER_SCREENER_HEADERS),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    validate_error(
        api.create_housing_assignment(
            f.housing_assignment_payload(
                _PHANTOM_AGREEMENT_ID,
                _PHANTOM_MEMBER_ID,
                1,
                "2027-05-10",
                "2027-05-20",
                school["version"],
            ),
            CORPS_DIRECTOR_HEADERS,
        ),
        ApiErrorId.UNAUTHORIZED,
        403,
    )

    assert fx.get_season(api, season["id"])["billing_epoch"] == 0
    members, member_meta = validate_paginated(
        api.list_members(MEMBERSHIP_COORDINATOR_HEADERS, {"season_id": season["id"]})
    )
    assert members == [] and member_meta["total_count"] == 0
    stops, stop_meta = validate_paginated(
        api.list_tour_stops(TOUR_MANAGER_HEADERS, {"season_id": season["id"]})
    )
    assert stops == [] and stop_meta["total_count"] == 0
    housing, housing_meta = validate_paginated(
        api.list_housing_assignments(MEMBERSHIP_COORDINATOR_HEADERS)
    )
    assert housing == [] and housing_meta["total_count"] == 0
    schools, school_meta = validate_paginated(api.list_host_schools(TOUR_MANAGER_HEADERS))
    assert [s["id"] for s in schools] == [school["id"]]
    assert school_meta["total_count"] == 1


def test_the_right_role_with_the_wrong_identity_is_an_ownership_failure(api):
    """Members sign their own contracts and volunteers accept their own shifts.

    PRD: "Like the revision request, signing is reserved to the owning member and compares `X-User-ID` against the contract's `member_id`, reporting `ERR_NOT_RESOURCE_OWNER` otherwise."

    Design: Corner/rbac/entity_backed_roles_cannot_act_on_another_owners_resource
    """
    season = fx.create_season(api)
    member_a = fx.offered_member(api, season["id"], 90, full_name="Avery Nakamura")
    member_b = fx.offered_member(api, season["id"], 92, full_name="Blair Osei")
    contract_a = fx.issue_contract(api, member_a["id"])

    stop = fx.create_rehearsal_stop(
        api,
        season["id"],
        venue_name="Rockford High School",
        city="Rockford",
        state_code="IL",
        arrive_at="2027-06-19T08:00:00Z",
        depart_at="2027-06-19T20:00:00Z",
        truck_count=1,
        rehearsal_minutes=120,
    )
    volunteer_x = fx.create_volunteer(api, VolunteerRoleType.COOK, full_name="Rosa Cook")
    volunteer_y = fx.create_volunteer(api, VolunteerRoleType.COOK, full_name="Yuri Cook")
    shift_x = fx.propose_shift(
        api, volunteer_x["id"], stop["id"], Duty.COOK,
        "2027-06-19T08:00:00Z", "2027-06-19T14:00:00Z",
    )
    shift_y = fx.propose_shift(
        api, volunteer_y["id"], stop["id"], Duty.COOK,
        "2027-06-19T14:00:00Z", "2027-06-19T20:00:00Z",
    )

    validate_error(
        api.sign_member_contract(
            contract_a["id"],
            f.signature_payload("Blair Osei"),
            make_member_headers(member_b["id"]),
        ),
        ApiErrorId.NOT_RESOURCE_OWNER,
        403,
    )
    validate_error(
        api.request_contract_revision(
            contract_a["id"],
            f.revision_request_payload(revision_note="not my contract"),
            make_member_headers(member_b["id"]),
        ),
        ApiErrorId.NOT_RESOURCE_OWNER,
        403,
    )
    refused_contract = fx.get_contract(api, contract_a["id"])
    assert_member_contract(refused_contract, status=ContractStatus.ISSUED, version=1)
    assert_all_nulls(refused_contract, "revision_note", "signature_name", "signed_at")

    validate_error(
        api.accept_staff_assignment(shift_x["id"], make_volunteer_headers(volunteer_y["id"])),
        ApiErrorId.NOT_RESOURCE_OWNER,
        403,
    )
    assert_staff_assignment(
        fx.get_shift(api, shift_x["id"]), status=StaffAssignmentStatus.PROPOSED, version=1
    )

    signed = fx.sign_contract(api, contract_a["id"], member_a["id"], "Avery Nakamura")
    assert_member_contract(
        signed, status=ContractStatus.SIGNED_BY_MEMBER, signature_name="Avery Nakamura", version=2
    )
    assert signed["signed_at"] is not None, "signing stamps the logical-clock instant"

    accepted = fx.accept_shift(api, shift_x["id"], volunteer_x["id"])
    assert_staff_assignment(accepted, status=StaffAssignmentStatus.ACCEPTED, version=2)
    assert_staff_assignment(
        fx.get_shift(api, shift_y["id"]), status=StaffAssignmentStatus.PROPOSED
    )


def test_one_user_may_not_hold_both_halves_of_a_two_step_approval(api):
    """Four eyes on a settlement and four eyes on a shift, keyed on the actor.

    PRD: "Rung 37 enforces segregation of duties on shift approval and settlement finalization, reporting `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/segregation_of_duties_blocks_one_user_holding_both_steps
    """
    season = fx.create_season(api)
    rehearsal_stop = fx.create_rehearsal_stop(
        api,
        season["id"],
        venue_name="Rockford High School",
        city="Rockford",
        state_code="IL",
        arrive_at="2027-06-19T08:00:00Z",
        depart_at="2027-06-19T20:00:00Z",
        truck_count=1,
        rehearsal_minutes=120,
    )
    volunteer = fx.create_volunteer(api, VolunteerRoleType.COOK, full_name="Rosa Cook")
    fx.clear_volunteer(api, volunteer["id"], "2026-08-01")
    shift = fx.propose_shift(
        api, volunteer["id"], rehearsal_stop["id"], Duty.COOK,
        "2027-06-19T09:00:00Z", "2027-06-19T19:00:00Z",
    )
    fx.accept_shift(api, shift["id"], volunteer["id"])

    built = fx.draft_settlement_on_show(
        api,
        season["id"],
        100000,
        500000,
        3,
        preparer_headers=BUSINESS_MANAGER_HEADERS,
        venue_name="Rockford Stadium",
        city="Rockford",
        state_code="IL",
        arrive_at="2027-06-20T08:00:00Z",
        depart_at="2027-06-20T23:00:00Z",
        show_start_at="2027-06-20T19:00:00Z",
        truck_count=1,
    )
    settlement_id = built["settlement"]["id"]
    fx.set_clock(api, "2027-06-22T09:00:00Z")

    validate_error(
        api.finalize_show_settlement(
            settlement_id, f.finalize_payload(2), BUSINESS_MANAGER_HEADERS
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES,
        403,
    )
    still_draft = fx.get_settlement(api, settlement_id)
    assert_show_settlement(
        still_draft, status=SettlementStatus.DRAFT, prepared_by_user_id=BUSINESS_MANAGER_ID
    )
    assert_all_nulls(still_draft, "final_net_cents", "finalized_by_user_id")

    validate_error(
        api.approve_staff_assignment(shift["id"], SCREENER_AS_TOUR_MANAGER_HEADERS),
        ApiErrorId.SEGREGATION_OF_DUTIES,
        403,
    )
    assert_staff_assignment(
        fx.get_shift(api, shift["id"]), status=StaffAssignmentStatus.ACCEPTED
    )
    assert_volunteer(fx.get_volunteer(api, volunteer["id"]), assignment_count=0)

    finalized = fx.finalize_settlement(
        api, settlement_id, 2, headers=SECOND_BUSINESS_MANAGER_HEADERS
    )
    assert_show_settlement(
        finalized,
        status=SettlementStatus.FINALIZED,
        finalized_by_user_id=SECOND_BUSINESS_MANAGER_ID,
        prepared_by_user_id=BUSINESS_MANAGER_ID,
        final_net_cents=201600,
    )

    approved = fx.approve_shift(api, shift["id"], TOUR_MANAGER_HEADERS)
    assert_staff_assignment(
        approved, status=StaffAssignmentStatus.APPROVED, approved_by_user_id=TOUR_MANAGER_ID
    )
    assert_volunteer(fx.get_volunteer(api, volunteer["id"]), assignment_count=1)


def test_read_access_is_granted_per_collection_and_not_globally(api):
    """The same reader is welcome on one list and refused on another.

    PRD: "| GET | `/volunteers` | List volunteers, filterable by role type and screening posture | CorpsDirector, TourManager, VolunteerScreener |"

    Design: Corner/rbac/shared_reads_work_for_listed_roles_and_are_forbidden_otherwise
    """
    season = fx.create_season(api)
    member = fx.create_member(api, season["id"], full_name="Avery Nakamura")
    volunteer = fx.create_volunteer(api, VolunteerRoleType.COOK, full_name="Rosa Cook")

    for headers in (CORPS_DIRECTOR_HEADERS, TOUR_MANAGER_HEADERS, BUSINESS_MANAGER_HEADERS):
        members, meta = validate_paginated(
            api.list_members(headers, {"season_id": season["id"]})
        )
        assert [m["id"] for m in members] == [member["id"]]
        assert meta["total_count"] == 1

    validate_error(
        api.list_volunteers(MEMBERSHIP_COORDINATOR_HEADERS, {"role_type": VolunteerRoleType.COOK}),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
    volunteers, volunteer_meta = validate_paginated(
        api.list_volunteers(VOLUNTEER_SCREENER_HEADERS, {"role_type": VolunteerRoleType.COOK})
    )
    assert [v["id"] for v in volunteers] == [volunteer["id"]]
    assert volunteer_meta["total_count"] == 1

    validate_error(
        api.list_payment_plans(TOUR_MANAGER_HEADERS, {"member_id": member["id"]}),
        ApiErrorId.UNAUTHORIZED,
        403,
    )
