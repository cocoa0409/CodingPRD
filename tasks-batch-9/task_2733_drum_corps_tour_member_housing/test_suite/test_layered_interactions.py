"""Layers that only show up when several mechanisms interact.

Optimistic concurrency where no state precondition could help, a strict date
threshold whose cascade is itself conditional, and filtered paging that has to
stay stable while the collection grows underneath it.
"""

from test_helpers import (
    ApiErrorId,
    BUSINESS_MANAGER_HEADERS,
    DietaryFlag,
    Duty,
    MEMBERSHIP_COORDINATOR_HEADERS,
    MembershipStatus,
    PlanStatus,
    ReleasedReason,
    ScreeningStatus,
    Section,
    StaffAssignmentStatus,
    TOUR_MANAGER_HEADERS,
    UsageType,
    VolunteerRoleType,
    assert_facility_agreement,
    assert_housing_assignment,
    assert_member,
    assert_payment_plan,
    assert_staff_assignment,
    assert_volunteer,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
)


def test_a_stale_member_view_cannot_silently_supersede_a_plan_it_never_saw(api):
    """The superseding write is legal, so only the version check can stop it.

    PRD: "Creating a second plan for the same member is legitimate under the product semantics — the new plan supersedes the prior one — so the state machine alone cannot reject a writer working from a stale view."

    Design: Corner/cross_cutting_complexity_layers/stale_member_version_rejects_the_superseding_payment_plan
    """
    season = fx.create_season(api)
    built = fx.contracted_member(api, season["id"], signature_name="Avery Nakamura")
    member_id = built["member"]["id"]
    contract_id = built["contract"]["id"]
    stale_version = fx.get_member(api, member_id)["version"]

    plan_one = fx.create_plan(api, member_id, contract_id, "2027-01-15", stale_version)
    refreshed_version = fx.get_member(api, member_id)["version"]
    assert refreshed_version == stale_version + 1, "an accepted plan advances the member"

    validate_error(
        api.create_payment_plan(
            f.payment_plan_payload(member_id, contract_id, "2027-02-15", stale_version),
            BUSINESS_MANAGER_HEADERS,
        ),
        ApiErrorId.STALE_MEMBER_VERSION,
        412,
    )
    assert_payment_plan(fx.get_plan(api, plan_one["id"]), status=PlanStatus.ACTIVE)
    plans, meta = validate_paginated(
        api.list_payment_plans(BUSINESS_MANAGER_HEADERS, {"member_id": member_id})
    )
    assert [p["id"] for p in plans] == [plan_one["id"]]
    assert meta["total_count"] == 1
    assert fx.get_member(api, member_id)["version"] == refreshed_version, (
        "a rejected write advances nothing"
    )

    plan_two = fx.create_plan(api, member_id, contract_id, "2027-02-15", refreshed_version)
    assert_payment_plan(plan_two, status=PlanStatus.ACTIVE, first_due_date="2027-02-15")
    assert_payment_plan(fx.get_plan(api, plan_one["id"]), status=PlanStatus.SUPERSEDED)
    assert fx.get_member(api, member_id)["version"] == refreshed_version + 1


def test_a_stale_agreement_view_cannot_add_a_second_occupant(api):
    """Occupancy leaves the agreement SIGNED, so only its version guards the beds.

    PRD: "Because every assignment and every release advances the agreement's `version`, a request carrying a pre-occupancy value is rejected with `ERR_STALE_AGREEMENT_VERSION` and HTTP 412 rather than overfilling a sleeping space the writer believed was empty."

    Design: Corner/cross_cutting_complexity_layers/stale_agreement_version_rejects_the_second_housing_assignment
    """
    season = fx.create_season(api)
    built = fx.signed_agreement_with_school(
        api,
        season["id"],
        UsageType.SPRING_TRAINING,
        school_overrides={
            "name": "Rockford High School",
            "city": "Rockford",
            "state_code": "IL",
            "sleeping_space_count": 30,
            "capacity_per_space": 12,
        },
        nightly_rate_cents=500,
        minimum_billable_beds=0,
    )
    agreement_id = built["agreement"]["id"]
    school_id = built["school"]["id"]
    member_a = fx.contracted_member(api, season["id"], full_name="Avery Nakamura")["member"]
    member_b = fx.contracted_member(api, season["id"], full_name="Blair Osei")["member"]
    stale_version = fx.get_agreement(api, agreement_id)["version"]

    housing_a = fx.house_member(
        api, agreement_id, member_a["id"], 5, "2027-05-10", "2027-05-20", stale_version
    )
    refreshed_version = fx.get_agreement(api, agreement_id)["version"]
    assert refreshed_version == stale_version + 1

    validate_error(
        api.create_housing_assignment(
            f.housing_assignment_payload(
                agreement_id, member_b["id"], 5, "2027-05-10", "2027-05-20", stale_version
            ),
            MEMBERSHIP_COORDINATOR_HEADERS,
        ),
        ApiErrorId.STALE_AGREEMENT_VERSION,
        412,
    )
    assert fx.get_agreement(api, agreement_id)["version"] == refreshed_version

    housing_b = fx.house_member(
        api, agreement_id, member_b["id"], 5, "2027-05-10", "2027-05-20", refreshed_version
    )
    assert_housing_assignment(housing_b, space_index=5, nights=10, occupant_is_minor=False)

    assignments, meta = validate_paginated(
        api.list_housing_assignments(
            MEMBERSHIP_COORDINATOR_HEADERS,
            {"facility_agreement_id": agreement_id, "space_index": 5},
        )
    )
    assert [a["id"] for a in assignments] == [housing_a["id"], housing_b["id"]]
    assert meta["total_count"] == 2
    assert_facility_agreement(
        fx.get_agreement(api, agreement_id),
        occupied_bed_nights=20,
        billable_bed_nights=20,
        billable_cents=10000,
        version=refreshed_version + 1,
    )
    assert fx.get_school(api, school_id)["reserved_bed_nights"] == 20


def test_the_expiry_sweep_waits_for_the_day_after_and_spares_finished_shifts(api):
    """A strict date comparison, then a release that skips the past.

    PRD: "A volunteer whose `screening_status` is `CLEARED` and whose `screening_expires_on` falls strictly before the logical-clock date moves `CLEARED → EXPIRED`, a terminal posture."

    Design: Corner/cross_cutting_complexity_layers/screening_expiry_threshold_releases_only_future_shifts
    """
    season = fx.create_season(api)
    volunteer = fx.create_volunteer(api, VolunteerRoleType.COOK, full_name="Rosa Cook")
    fx.clear_volunteer(api, volunteer["id"], "2026-08-01")

    june_stop = fx.create_rehearsal_stop(
        api,
        season["id"],
        venue_name="June Stop",
        city="Rockford",
        state_code="IL",
        arrive_at="2027-06-19T08:00:00Z",
        depart_at="2027-06-19T20:00:00Z",
        truck_count=1,
        rehearsal_minutes=120,
    )
    august_stop = fx.create_rehearsal_stop(
        api,
        season["id"],
        venue_name="August Stop",
        city="Peoria",
        state_code="IL",
        arrive_at="2027-08-20T08:00:00Z",
        depart_at="2027-08-20T20:00:00Z",
        truck_count=1,
        rehearsal_minutes=120,
    )
    june_shift = fx.propose_shift(
        api, volunteer["id"], june_stop["id"], Duty.COOK,
        "2027-06-19T09:00:00Z", "2027-06-19T19:00:00Z",
    )
    fx.accept_shift(api, june_shift["id"], volunteer["id"])
    fx.approve_shift(api, june_shift["id"], TOUR_MANAGER_HEADERS)
    august_shift = fx.propose_shift(
        api, volunteer["id"], august_stop["id"], Duty.COOK,
        "2027-08-20T09:00:00Z", "2027-08-20T19:00:00Z",
    )
    fx.accept_shift(api, august_shift["id"], volunteer["id"])
    fx.approve_shift(api, august_shift["id"], TOUR_MANAGER_HEADERS)

    fx.set_clock(api, "2027-08-01T12:00:00Z")
    on_expiry_date = fx.run_sweep(api, season["id"])
    assert on_expiry_date["billing_epoch"] == 1
    assert_volunteer(
        fx.get_volunteer(api, volunteer["id"]),
        screening_status=ScreeningStatus.CLEARED,
        screening_expires_on="2027-08-01",
        assignment_count=2,
    )

    fx.set_clock(api, "2027-08-02T00:00:00Z")
    after_expiry = fx.run_sweep(api, season["id"])
    assert after_expiry["billing_epoch"] == 2
    assert_volunteer(
        fx.get_volunteer(api, volunteer["id"]),
        screening_status=ScreeningStatus.EXPIRED,
        screening_expires_on="2027-08-01",
        assignment_count=1,
    )
    assert_staff_assignment(
        fx.get_shift(api, august_shift["id"]),
        status=StaffAssignmentStatus.RELEASED,
        released_reason=ReleasedReason.SCREENING_EXPIRED,
    )
    still_approved = fx.get_shift(api, june_shift["id"])
    assert_staff_assignment(still_approved, status=StaffAssignmentStatus.APPROVED)
    assert still_approved["released_reason"] is None, (
        "a shift that already ended is not rewritten by the expiry cascade"
    )


def test_two_member_filters_compose_and_offsets_survive_a_later_insertion(api):
    """Both filters bite, and the new row appends without shifting earlier windows.

    PRD: "Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending."

    Design: Corner/cross_cutting_complexity_layers/member_listing_filters_sort_and_offset_stay_consistent_under_mutation
    """
    season = fx.create_season(api)
    minor_one = fx.offered_member(
        api, season["id"], 80,
        full_name="Minor One", date_of_birth="2010-01-01", section=Section.BRASS,
    )
    minor_two = fx.offered_member(
        api, season["id"], 81,
        full_name="Minor Two", date_of_birth="2010-02-02",
        section=Section.PERCUSSION, dietary_flag=DietaryFlag.GLUTEN_FREE,
    )
    minor_three = fx.offered_member(
        api, season["id"], 82,
        full_name="Minor Three", date_of_birth="2010-03-03", section=Section.COLOR_GUARD,
    )
    adult_decoy = fx.offered_member(
        api, season["id"], 83, full_name="Adult Decoy", date_of_birth="2004-05-05",
    )
    declined_minor = fx.create_member(
        api, season["id"], full_name="Declined Minor", date_of_birth="2010-04-04"
    )
    fx.decline_member(api, declined_minor["id"], 40)

    assert_member(adult_decoy, is_minor=False, membership_status=MembershipStatus.OFFERED)
    assert_member(
        fx.get_member(api, declined_minor["id"]),
        is_minor=True,
        membership_status=MembershipStatus.DECLINED,
    )

    offered_minor_filter = {
        "season_id": season["id"],
        "membership_status": MembershipStatus.OFFERED,
        "is_minor": "true",
    }
    members, meta = validate_paginated(
        api.list_members(MEMBERSHIP_COORDINATOR_HEADERS, dict(offered_minor_filter))
    )
    assert [m["id"] for m in members] == [minor_one["id"], minor_two["id"], minor_three["id"]]
    assert meta["total_count"] == 3
    assert meta["has_more"] is False

    window, window_meta = validate_paginated(
        api.list_members(
            MEMBERSHIP_COORDINATOR_HEADERS,
            dict(offered_minor_filter, limit=1, offset=1),
        )
    )
    assert [m["id"] for m in window] == [minor_two["id"]]
    assert window_meta["total_count"] == 3
    assert window_meta["has_more"] is True

    minor_four = fx.offered_member(
        api, season["id"], 84,
        full_name="Minor Four", date_of_birth="2010-05-05",
        dietary_flag=DietaryFlag.VEGETARIAN,
    )
    tail, tail_meta = validate_paginated(
        api.list_members(
            MEMBERSHIP_COORDINATOR_HEADERS,
            dict(offered_minor_filter, limit=2, offset=2),
        )
    )
    assert [m["id"] for m in tail] == [minor_three["id"], minor_four["id"]]
    assert tail_meta["total_count"] == 4
    assert tail_meta["has_more"] is False
