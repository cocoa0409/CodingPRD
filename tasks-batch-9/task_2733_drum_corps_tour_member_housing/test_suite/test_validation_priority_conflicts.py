"""Requests that break two rules at once and must name the higher one.

The global validation ladder decides which of two live violations surfaces. Both
pairs here are constructed so that the losing rule is demonstrably armed: the same
request shape against a slightly different subject reports the lower rule instead.
"""

from test_helpers import (
    ApiErrorId,
    BUSINESS_MANAGER_HEADERS,
    MEMBERSHIP_COORDINATOR_HEADERS,
    assert_facility_agreement,
    assert_payment_plan,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
)


# ------------------------- plan state (rung 31) versus tender size (rung 53)
def _one_closed_plan_and_one_open_plan(api, season_id):
    plans = {}
    for key, dob, section in (("a", "2005-03-04", "BRASS"), ("b", "2004-07-19", "PERCUSSION")):
        built = fx.financed_member(
            api,
            season_id,
            first_due_date="2027-01-15",
            tuition_amount_cents=399900,
            payment_plan_type="STANDARD_3",
            date_of_birth=dob,
            section=section,
        )
        plans[key] = {"member": built["member"], "plan": built["plan"]}

    fx.set_clock(api, "2027-05-10T00:00:00Z")
    fx.withdraw_member(api, plans["a"]["member"]["id"], "2027-05-10", reason="family move")

    assert_payment_plan(
        fx.get_plan(api, plans["a"]["plan"]["id"]),
        status="CLOSED_WITH_BALANCE",
        outstanding_cents=399900,
    )
    assert_payment_plan(fx.get_plan(api, plans["b"]["plan"]["id"]), status="ACTIVE")
    return plans


def _oversized_ach(api, plan_id):
    return api.create_tuition_payment(
        f.tuition_payment_payload(plan_id, 900000, "2027-05-10", method="ACH"),
        BUSINESS_MANAGER_HEADERS,
    )


def test_a_closed_plan_reports_its_state_before_weighing_the_tender(api):
    """900000 cents against a closed plan is a state problem, not a size problem.

    PRD: "The target plan's `status` must be `ACTIVE` or `DELINQUENT`; a `SETTLED`,
    `SUPERSEDED` or `CLOSED_WITH_BALANCE` plan accepts nothing further and reports
    `ERR_PLAN_NOT_ACCEPTING_PAYMENTS`."

    Design: Difficulty/priority_pair_validation_conflict/closed_plan_state_error_outranks_oversized_payment_fiscal_error
    """
    season = fx.create_season(api)
    plans = _one_closed_plan_and_one_open_plan(api, season["id"])

    response = _oversized_ach(api, plans["a"]["plan"]["id"])
    validate_error(response, ApiErrorId.PLAN_NOT_ACCEPTING_PAYMENTS, 409)

    assert fx.get_plan(api, plans["a"]["plan"]["id"])["principal_paid_cents"] == 0
    assert fx.get_season(api, season["id"])["tuition_collected_cents"] == 0
    payments, _meta = validate_paginated(
        api.list_tuition_payments(BUSINESS_MANAGER_HEADERS)
    )
    assert payments == []


def test_the_same_tender_on_an_open_plan_reports_the_fiscal_rule(api):
    """The losing rule is armed: an open plan refuses the identical amount on size.

    PRD: "And the tendered amount may not exceed the plan's total outstanding
    obligation — the accrued late fees less the late fees already paid, plus the
    financed total less the principal already paid — or the posting is refused with
    `ERR_PAYMENT_EXCEEDS_BALANCE`, because the ledger never holds unallocated
    money."

    Design: Difficulty/priority_pair_validation_conflict/closed_plan_state_error_outranks_oversized_payment_fiscal_error
    """
    season = fx.create_season(api)
    plans = _one_closed_plan_and_one_open_plan(api, season["id"])

    response = _oversized_ach(api, plans["b"]["plan"]["id"])
    validate_error(response, ApiErrorId.PAYMENT_EXCEEDS_BALANCE, 409)

    assert fx.get_plan(api, plans["b"]["plan"]["id"])["principal_paid_cents"] == 0
    assert fx.get_season(api, season["id"])["tuition_collected_cents"] == 0
    payments, _meta = validate_paginated(
        api.list_tuition_payments(BUSINESS_MANAGER_HEADERS)
    )
    assert payments == []


# ------------------- minor mix (rung 31) versus space capacity (rung 53)
def _space_holding_two_adults(api, season_id):
    school = fx.create_school(api, name="Rockford High School", city="Rockford",
                              state_code="IL", sleeping_space_count=30,
                              capacity_per_space=2, rehearsal_field_count=2,
                              has_air_conditioning=True)
    built = fx.signed_agreement_with_school(
        api, season_id, school=school, nightly_rate_cents=450,
        minimum_billable_beds=0, start_date="2027-05-10", end_date="2027-06-05",
    )
    agreement = built["agreement"]

    occupants = []
    for dob, section in (("2005-03-04", "BRASS"), ("2004-07-19", "PERCUSSION")):
        member = fx.contracted_member(api, season_id, date_of_birth=dob,
                                      section=section)["member"]
        assignment = fx.house_member(api, agreement["id"], member["id"], 1,
                                     "2027-05-10", "2027-05-20")
        occupants.append({"member": member, "assignment": assignment})

    minor = fx.contracted_member(api, season_id, date_of_birth="2010-09-01",
                                 section="COLOR_GUARD")["member"]
    newcomer = fx.contracted_member(api, season_id, date_of_birth="2003-11-02",
                                    section="BRASS")["member"]
    assert minor["is_minor"] is True
    assert newcomer["is_minor"] is False
    for occupant in occupants:
        assert occupant["member"]["is_minor"] is False

    return {
        "school": school,
        "agreement": fx.get_agreement(api, agreement["id"]),
        "occupants": occupants,
        "minor": minor,
        "newcomer": newcomer,
    }


def _bunk_request(api, agreement_id, member_id, version):
    return api.create_housing_assignment(
        f.housing_assignment_payload(agreement_id, member_id, 1, "2027-05-12",
                                     "2027-05-18", version),
        MEMBERSHIP_COORDINATOR_HEADERS,
    )


def test_a_minor_joining_two_adults_reports_the_mix_not_the_capacity(api):
    """The mix is decided first even though the effective capacity is also blown.

    PRD: "Because the minor-mix check outranks the capacity check, an assignment
    that is simultaneously a minor/adult mix and over capacity always reports the
    mix."

    Design: Difficulty/priority_pair_validation_conflict/minor_room_mix_outranks_sleeping_space_capacity
    """
    season = fx.create_season(api)
    built = _space_holding_two_adults(api, season["id"])
    version = built["agreement"]["version"]

    response = _bunk_request(api, built["agreement"]["id"], built["minor"]["id"], version)
    validate_error(response, ApiErrorId.MINOR_ROOM_MIX, 409)

    assert_facility_agreement(
        fx.get_agreement(api, built["agreement"]["id"]),
        version=version,
        occupied_bed_nights=20,
        billable_cents=9000,
    )
    assert fx.get_school(api, built["school"]["id"])["reserved_bed_nights"] == 20


def test_a_third_adult_on_the_same_space_reports_the_capacity_rule(api):
    """The losing rule is armed: without a mix, the same bunk fails on capacity.

    PRD: "the space's effective capacity is `capacity_per_space` reduced by exactly
    one bunk whenever a minor occupies the space on an overlapping night — that
    single reserved bunk is the chaperone's — and the size of the overlap set plus
    the candidate must not exceed that effective capacity, or the assignment is
    refused with `ERR_SPACE_CAPACITY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/minor_room_mix_outranks_sleeping_space_capacity
    """
    season = fx.create_season(api)
    built = _space_holding_two_adults(api, season["id"])
    version = built["agreement"]["version"]

    response = _bunk_request(api, built["agreement"]["id"], built["newcomer"]["id"],
                             version)
    validate_error(response, ApiErrorId.SPACE_CAPACITY_EXCEEDED, 409)

    assert_facility_agreement(
        fx.get_agreement(api, built["agreement"]["id"]),
        version=version,
        occupied_bed_nights=20,
        billable_cents=9000,
    )
    assert fx.get_school(api, built["school"]["id"])["reserved_bed_nights"] == 20
    active, _meta = validate_paginated(
        api.list_housing_assignments(MEMBERSHIP_COORDINATOR_HEADERS,
                                     params={"status": "ACTIVE"})
    )
    assert sorted(row["id"] for row in active) == sorted(
        occupant["assignment"]["id"] for occupant in built["occupants"]
    )
