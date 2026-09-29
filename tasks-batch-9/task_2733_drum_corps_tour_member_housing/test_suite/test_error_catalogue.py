"""Error identifiers reachable only from a specific corner of the domain.

Each test triggers a family of codes that no other route can raise and then
proves the refusal was inert, because a rejected write must leave every derived
counter exactly where it stood.
"""

from test_helpers import (
    ApiErrorId,
    AgreementStatus,
    AuditionDecision,
    BUSINESS_MANAGER_HEADERS,
    ContractStatus,
    Duty,
    HousingStatus,
    MEMBERSHIP_COORDINATOR_HEADERS,
    MembershipStatus,
    PaymentMethod,
    PaymentPlanType,
    PaymentStatus,
    ScreeningDecision,
    SECOND_BUSINESS_MANAGER_HEADERS,
    ScreeningStatus,
    Section,
    SettlementState,
    SettlementStatus,
    StaffAssignmentStatus,
    StopStatus,
    TOUR_MANAGER_HEADERS,
    VOLUNTEER_SCREENER_HEADERS,
    VolunteerRoleType,
    assert_all_nulls,
    assert_facility_agreement,
    assert_housing_assignment,
    assert_member,
    assert_member_contract,
    assert_payment_plan,
    assert_show_settlement,
    assert_staff_assignment,
    assert_tour_stop,
    assert_tuition_payment,
    assert_volunteer,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_email_contract_and_rate_constraints_each_report_their_own_code(api):
    """Season-scoped emails, one live contract, and an inclusive nightly cap.

    PRD: "An email address may repeat across seasons but must be unique among the members of any one season; a collision is refused with `ERR_DUPLICATE_EMAIL`."

    Design: Corner/errors/membership_and_fiscal_constraint_errors_are_each_triggerable
    """
    season_one = fx.create_season(api)
    season_two = fx.create_season(
        api,
        name="2028 Tour",
        year=2028,
        tuition_base_cents=419900,
        spring_training_start_date="2028-05-10",
        spring_training_end_date="2028-06-05",
        tour_departure_date="2028-06-12",
    )
    school = fx.create_school(api)
    member = fx.create_member(api, season_one["id"], email="avery@corps.test")
    fx.offer_member(api, member["id"], 90)
    contract = fx.issue_contract(api, member["id"])
    fx.create_volunteer(api, VolunteerRoleType.COOK, email="rosa@corps.test")

    validate_error(
        api.create_member(
            f.member_payload(
                season_one["id"],
                full_name="Avery Twin",
                email="avery@corps.test",
                section=Section.PERCUSSION,
            ),
            MEMBERSHIP_COORDINATOR_HEADERS,
        ),
        ApiErrorId.DUPLICATE_EMAIL,
        409,
    )
    twin = fx.create_member(api, season_two["id"], email="avery@corps.test")
    assert_member(twin, season_id=season_two["id"], email="avery@corps.test")

    validate_error(
        api.create_volunteer(
            f.volunteer_payload(VolunteerRoleType.CHAPERONE, email="rosa@corps.test"),
            VOLUNTEER_SCREENER_HEADERS,
        ),
        ApiErrorId.DUPLICATE_EMAIL,
        409,
    )
    validate_error(
        api.create_member_contract(
            f.member_contract_payload(
                member["id"], payment_plan_type=PaymentPlanType.EXTENDED_6
            ),
            MEMBERSHIP_COORDINATOR_HEADERS,
        ),
        ApiErrorId.CONTRACT_ALREADY_EXISTS,
        409,
    )
    assert_member_contract(
        fx.get_contract(api, contract["id"]),
        status=ContractStatus.ISSUED,
        payment_plan_type=PaymentPlanType.STANDARD_3,
    )

    validate_error(
        api.create_facility_agreement(
            f.facility_agreement_payload(
                school["id"], season_one["id"], nightly_rate_cents=1501
            ),
            TOUR_MANAGER_HEADERS,
        ),
        ApiErrorId.RATE_ABOVE_CAP,
        409,
    )
    agreement = fx.draft_agreement(
        api, school["id"], season_one["id"], nightly_rate_cents=1500
    )
    fx.submit_agreement(api, agreement["id"])
    validate_error(
        api.counter_facility_agreement(
            agreement["id"], f.counter_payload(1501), TOUR_MANAGER_HEADERS
        ),
        ApiErrorId.RATE_ABOVE_CAP,
        409,
    )
    countered = fx.get_agreement(api, agreement["id"])
    assert_facility_agreement(
        countered,
        status=AgreementStatus.SUBMITTED,
        counter_round=0,
        nightly_rate_cents=1500,
    )
    assert_all_nulls(countered, "countered_nightly_rate_cents")


def test_space_bounds_and_double_occupancy_report_distinct_housing_codes(api):
    """A one-based bounded index, then an overlap caught across spaces.

    PRD: "And the member may not already hold an active stay whose dates overlap the requested ones — in any space, under any agreement — or the request reports `ERR_MEMBER_ALREADY_HOUSED`."

    Design: Corner/errors/housing_constraint_errors_are_each_triggerable
    """
    season = fx.create_season(api)
    built = fx.housed_member(
        api,
        season["id"],
        "2027-05-10",
        "2027-05-20",
        space_index=1,
        nightly_rate_cents=500,
        school_overrides={"sleeping_space_count": 30, "capacity_per_space": 12},
    )
    member_id = built["member"]["id"]
    agreement_id = built["agreement"]["id"]
    agreement_version = built["agreement"]["version"]

    for space_index in (31, 0):
        validate_error(
            api.create_housing_assignment(
                f.housing_assignment_payload(
                    agreement_id,
                    member_id,
                    space_index,
                    "2027-05-25",
                    "2027-05-30",
                    agreement_version,
                ),
                MEMBERSHIP_COORDINATOR_HEADERS,
            ),
            ApiErrorId.SPACE_INDEX_OUT_OF_RANGE,
            409,
        )

    validate_error(
        api.create_housing_assignment(
            f.housing_assignment_payload(
                agreement_id,
                member_id,
                2,
                "2027-05-15",
                "2027-05-25",
                agreement_version,
            ),
            MEMBERSHIP_COORDINATOR_HEADERS,
        ),
        ApiErrorId.MEMBER_ALREADY_HOUSED,
        409,
    )

    assert_housing_assignment(
        fx.get_housing(api, built["assignment"]["id"]),
        status=HousingStatus.ACTIVE,
        space_index=1,
        nights=10,
        occupant_is_minor=False,
    )
    assert_facility_agreement(
        fx.get_agreement(api, agreement_id),
        version=agreement_version,
        occupied_bed_nights=10,
    )


def test_truck_shortfall_and_impossible_drive_report_distinct_route_codes(api):
    """An overloaded convoy, a drive one minute short, and the exact boundary.

    PRD: "The fleet must be adequate: `truck_count` must be at least the computed `trucks_required`, or the confirmation reports `ERR_INSUFFICIENT_TRUCKS`."

    Design: Corner/errors/route_confirmation_errors_are_each_triggerable
    """
    season = fx.create_season(api)
    origin = fx.create_rehearsal_stop(
        api,
        season["id"],
        venue_name="Origin",
        city="Rockford",
        state_code="IL",
        arrive_at="2027-06-18T06:00:00Z",
        depart_at="2027-06-18T18:00:00Z",
        travel_miles_from_previous=0,
        truck_count=1,
        rehearsal_minutes=120,
        heat_index_f=80,
    )
    fx.confirm_stop(api, origin["id"])

    overloaded = fx.create_rehearsal_stop(
        api,
        season["id"],
        previous_stop_id=origin["id"],
        venue_name="Overloaded",
        city="Dubuque",
        state_code="IA",
        arrive_at="2027-06-19T10:00:00Z",
        depart_at="2027-06-19T20:00:00Z",
        travel_miles_from_previous=100,
        uniform_trunks=40,
        instrument_cases=95,
        prop_units=10,
        truck_count=1,
        rehearsal_minutes=120,
        heat_index_f=80,
    )
    assert_tour_stop(
        overloaded,
        total_load_cuft=2670,
        total_load_lbs=18825,
        trucks_required=2,
        required_travel_minutes=134,
        status=StopStatus.PLANNED,
    )
    validate_error(
        api.confirm_tour_stop(overloaded["id"], TOUR_MANAGER_HEADERS),
        ApiErrorId.INSUFFICIENT_TRUCKS,
        409,
    )
    assert_tour_stop(fx.get_stop(api, overloaded["id"]), status=StopStatus.PLANNED, version=1)

    long_haul = dict(
        previous_stop_id=origin["id"],
        depart_at="2027-06-19T18:00:00Z",
        travel_miles_from_previous=420,
        truck_count=2,
        rehearsal_minutes=120,
        heat_index_f=80,
    )
    early = fx.create_rehearsal_stop(
        api,
        season["id"],
        venue_name="One Minute Early",
        city="Indianapolis",
        state_code="IN",
        arrive_at="2027-06-19T04:19:00Z",
        **long_haul,
    )
    feasible = fx.create_rehearsal_stop(
        api,
        season["id"],
        venue_name="Exactly Feasible",
        city="Columbus",
        state_code="OH",
        arrive_at="2027-06-19T04:20:00Z",
        **long_haul,
    )
    assert_tour_stop(early, required_travel_minutes=620, trucks_required=2)
    validate_error(
        api.confirm_tour_stop(early["id"], TOUR_MANAGER_HEADERS),
        ApiErrorId.TRAVEL_TIME_INFEASIBLE,
        409,
    )
    assert_tour_stop(fx.get_stop(api, early["id"]), status=StopStatus.PLANNED, version=1)

    confirmed = validate_success(api.confirm_tour_stop(feasible["id"], TOUR_MANAGER_HEADERS))
    assert_tour_stop(
        confirmed,
        status=StopStatus.CONFIRMED,
        trucks_required=2,
        truck_count=2,
        required_travel_minutes=620,
        version=2,
    )


def test_each_link_of_the_membership_to_money_chain_reports_its_own_state_code(api):
    """A second decision, an early reissue, an unexecuted plan and a mismatch.

    PRD: "The referenced contract must have `status` `EXECUTED`, or the request is refused with `ERR_CONTRACT_NOT_EXECUTED`, and the supplied `member_id` must be the very member the contract names, or the request is refused with `ERR_CONTRACT_MEMBER_MISMATCH`."

    Design: Corner/errors/membership_chain_state_errors_are_each_triggerable
    """
    season = fx.create_season(api)
    member_a = fx.create_member(api, season["id"], full_name="Avery Nakamura")
    fx.offer_member(api, member_a["id"], 90)
    contract_a = fx.issue_contract(api, member_a["id"])
    built_b = fx.contracted_member(api, season["id"], signature_name="Blair Osei")
    member_a = fx.get_member(api, member_a["id"])

    validate_error(
        api.record_audition_decision(
            member_a["id"],
            f.audition_decision_payload(decision=AuditionDecision.DECLINE, audition_score=55),
            MEMBERSHIP_COORDINATOR_HEADERS,
        ),
        ApiErrorId.INVALID_MEMBER_STATE,
        409,
    )
    assert_member(
        fx.get_member(api, member_a["id"]),
        membership_status=MembershipStatus.OFFERED,
        audition_score=90,
    )

    validate_error(
        api.reissue_member_contract(
            contract_a["id"],
            f.reissue_payload(tuition_amount_cents=349900),
            MEMBERSHIP_COORDINATOR_HEADERS,
        ),
        ApiErrorId.INVALID_CONTRACT_STATE,
        409,
    )
    assert_member_contract(
        fx.get_contract(api, contract_a["id"]),
        status=ContractStatus.ISSUED,
        tuition_amount_cents=399900,
        revision_round=0,
    )

    fx.sign_contract(api, contract_a["id"], member_a["id"], "Avery Nakamura")
    validate_error(
        api.create_payment_plan(
            f.payment_plan_payload(
                member_a["id"], contract_a["id"], "2027-01-15", member_a["version"]
            ),
            BUSINESS_MANAGER_HEADERS,
        ),
        ApiErrorId.CONTRACT_NOT_EXECUTED,
        409,
    )
    validate_error(
        api.create_payment_plan(
            f.payment_plan_payload(
                member_a["id"],
                built_b["contract"]["id"],
                "2027-01-15",
                member_a["version"],
            ),
            BUSINESS_MANAGER_HEADERS,
        ),
        ApiErrorId.CONTRACT_MEMBER_MISMATCH,
        409,
    )

    plans, meta = validate_paginated(api.list_payment_plans(BUSINESS_MANAGER_HEADERS))
    assert plans == [], "not one refused request may leave a plan behind"
    assert meta["total_count"] == 0
    assert_member(fx.get_member(api, member_a["id"]), tuition_charged_cents=0)


def test_repeating_a_step_on_four_entities_reports_four_distinct_state_codes(api):
    """A second reversal, a second release, a second decision and a skipped accept.

    PRD: "A reversal is permitted only while the payment is `POSTED` and only while its plan's `status` is anything other than `SUPERSEDED`; otherwise it reports `ERR_INVALID_PAYMENT_STATE`."

    Design: Corner/errors/payment_housing_screening_and_staffing_state_errors_are_each_triggerable
    """
    season = fx.create_season(api)
    built = fx.financed_member(api, season["id"], "2027-01-15")
    payment = fx.post_payment(api, built["plan"]["id"], 50000, "2026-08-01", PaymentMethod.ACH)
    fx.reverse_payment(api, payment["id"], reversal_reason="bank returned the item")

    housed = fx.housed_member(
        api,
        season["id"],
        "2027-05-10",
        "2027-05-20",
        member=built["member"],
        nightly_rate_cents=500,
    )
    fx.release_housing(api, housed["assignment"]["id"])

    volunteer = fx.create_volunteer(api, VolunteerRoleType.COOK, full_name="Rosa Cook")
    fx.clear_volunteer(api, volunteer["id"], "2026-08-01")

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
    shift = fx.propose_shift(
        api,
        volunteer["id"],
        stop["id"],
        Duty.COOK,
        "2027-06-19T09:00:00Z",
        "2027-06-19T19:00:00Z",
    )

    validate_error(
        api.reverse_tuition_payment(
            payment["id"], f.reversal_payload(reversal_reason="again"), BUSINESS_MANAGER_HEADERS
        ),
        ApiErrorId.INVALID_PAYMENT_STATE,
        409,
    )
    assert_tuition_payment(
        fx.get_payment(api, payment["id"]),
        status=PaymentStatus.REVERSED,
        reversal_reason="bank returned the item",
    )
    assert_payment_plan(fx.get_plan(api, built["plan"]["id"]), principal_paid_cents=0)

    validate_error(
        api.release_housing_assignment(
            housed["assignment"]["id"], MEMBERSHIP_COORDINATOR_HEADERS
        ),
        ApiErrorId.INVALID_HOUSING_STATE,
        409,
    )
    assert_facility_agreement(
        fx.get_agreement(api, housed["agreement"]["id"]), occupied_bed_nights=0
    )
    assert fx.get_school(api, housed["school"]["id"])["reserved_bed_nights"] == 0

    validate_error(
        api.record_screening_decision(
            volunteer["id"],
            f.screening_decision_payload("2026-08-01", ScreeningDecision.REJECT),
            VOLUNTEER_SCREENER_HEADERS,
        ),
        ApiErrorId.INVALID_SCREENING_STATE,
        409,
    )
    assert_volunteer(
        fx.get_volunteer(api, volunteer["id"]),
        screening_status=ScreeningStatus.CLEARED,
        screening_expires_on="2027-08-01",
        assignment_count=0,
    )

    validate_error(
        api.approve_staff_assignment(shift["id"], TOUR_MANAGER_HEADERS),
        ApiErrorId.INVALID_STAFF_ASSIGNMENT_STATE,
        409,
    )
    assert_staff_assignment(
        fx.get_shift(api, shift["id"]), status=StaffAssignmentStatus.PROPOSED
    )
    assert_volunteer(fx.get_volunteer(api, volunteer["id"]), assignment_count=0)

    closing_season = fx.get_season(api, season["id"])
    assert closing_season["tuition_collected_cents"] == 0
    assert closing_season["housing_cost_cents"] == 0


def test_a_second_finalization_is_refused_and_replays_nothing(api):
    """FINALIZED is terminal, so the second payload never touches the money.

    PRD: "Finalization requires the settlement to be `DRAFT`, or it reports `ERR_INVALID_SETTLEMENT_STATE`; requires the parent stop still to be `COMPLETED` and a `SHOW`, or it reports `ERR_STOP_NOT_COMPLETED`; and requires the finalizing `X-User-ID` to differ from `prepared_by_user_id`, or it reports `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/errors/finalizing_an_already_finalized_settlement_is_refused
    """
    season = fx.create_season(api)
    built = fx.draft_settlement_on_show(
        api,
        season["id"],
        100000,
        500000,
        3,
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
    fx.finalize_settlement(api, settlement_id, 2)

    validate_error(
        api.finalize_show_settlement(
            settlement_id,
            f.finalize_payload(1, [f.sanction_line(10000, "2027-06-22T08:00:00Z")]),
            SECOND_BUSINESS_MANAGER_HEADERS,
        ),
        ApiErrorId.INVALID_SETTLEMENT_STATE,
        409,
    )

    assert_show_settlement(
        fx.get_settlement(api, settlement_id),
        status=SettlementStatus.FINALIZED,
        final_placement=2,
        final_prize_cents=110000,
        final_gross_cents=210000,
        final_circuit_fee_cents=8400,
        sanctions_charged_cents=0,
        final_net_cents=201600,
        remittance_line_count=0,
    )
    assert_tour_stop(
        fx.get_stop(api, built["stop"]["id"]),
        status=StopStatus.COMPLETED,
        settlement_state=SettlementState.SETTLED,
    )
    assert fx.get_season(api, season["id"])["tour_revenue_cents"] == 201600
