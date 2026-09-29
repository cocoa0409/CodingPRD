"""Compensating actions that must land the ledgers exactly where they began.

Reversing a payment and releasing a bed are both defined as the arithmetic
inverse of the write that preceded them, so an apply-then-unwind round trip has
to leave every aggregate — plan, member, season, agreement, school — untouched.
"""

from test_helpers import (
    assert_facility_agreement,
    assert_housing_assignment,
    assert_instant_equals,
    assert_member,
    assert_payment_plan,
    assert_tuition_payment,
    fixtures as fx,
)


def _delinquent_plan_then_cured(api, season_id):
    """One missed installment, one late fee, then a payment that cures both."""
    built = fx.financed_member(api, season_id, "2027-01-15",
                               payment_plan_type="EXTENDED_6",
                               full_name="Avery Nakamura",
                               date_of_birth="2005-03-04")
    fx.set_clock(api, "2027-02-20T00:00:00Z")
    fx.run_sweep(api, season_id)
    payment = fx.post_payment(api, built["plan"]["id"], 139134, "2027-02-20")
    return {"member": built["member"], "plan": built["plan"], "payment": payment}


def test_the_cure_payment_clears_the_fee_bucket_then_the_arrears(api):
    """The waterfall takes the late fee first and the cure lifts the delinquency.

    PRD: "Otherwise, if `arrears_cents` has reached 0 while something remains
    outstanding and the plan was `DELINQUENT`, the plan is cured and moves
    `DELINQUENT → ACTIVE`; curing never touches `delinquency_strikes`, which only
    ever increases."

    Design: Difficulty/compensating_invariant/payment_reversal_restores_plan_member_and_season_ledgers_and_delinquency
    """
    season = fx.create_season(api)
    built = _delinquent_plan_then_cured(api, season["id"])

    assert_tuition_payment(built["payment"], status="POSTED",
                           allocated_to_late_fee_cents=2500,
                           allocated_to_principal_cents=136634)
    assert_payment_plan(fx.get_plan(api, built["plan"]["id"]), status="ACTIVE",
                        delinquency_strikes=1, principal_paid_cents=136634,
                        late_fee_paid_cents=2500, arrears_cents=0,
                        outstanding_cents=273264)
    assert_member(fx.get_member(api, built["member"]["id"]),
                  tuition_paid_cents=136634, tuition_balance_cents=263266)

    season_now = fx.get_season(api, season["id"])
    assert season_now["tuition_collected_cents"] == 136634
    assert season_now["late_fee_collected_cents"] == 2500


def test_reversing_the_cure_reopens_the_arrears_and_the_delinquency(api):
    """The unwind is exact and the plan falls back into delinquency.

    PRD: "The unwind is exact: the plan's `principal_paid_cents` is reduced by
    that payment's `allocated_to_principal_cents` and its `late_fee_paid_cents` by
    that payment's `allocated_to_late_fee_cents`, the member's
    `tuition_paid_cents`, `tuition_balance_cents` and `refund_due_cents` are
    recomputed, and the season's `tuition_collected_cents` and
    `late_fee_collected_cents` return to their pre-payment values."

    Design: Difficulty/compensating_invariant/payment_reversal_restores_plan_member_and_season_ledgers_and_delinquency
    """
    season = fx.create_season(api)
    built = _delinquent_plan_then_cured(api, season["id"])

    reversed_payment = fx.reverse_payment(
        api, built["payment"]["id"],
        reversal_reason="ACH returned for insufficient funds",
    )
    assert_tuition_payment(reversed_payment, status="REVERSED",
                           reversal_reason="ACH returned for insufficient funds",
                           allocated_to_late_fee_cents=2500,
                           allocated_to_principal_cents=136634)
    assert_instant_equals(reversed_payment["reversed_at"], "2027-02-20T00:00:00Z",
                          "reversed_at")

    assert_payment_plan(fx.get_plan(api, built["plan"]["id"]), status="DELINQUENT",
                        delinquency_strikes=1, principal_paid_cents=0,
                        late_fee_paid_cents=0, late_fee_accrued_cents=2500,
                        arrears_cents=136634, outstanding_cents=412398)
    assert_member(fx.get_member(api, built["member"]["id"]),
                  tuition_paid_cents=0, tuition_balance_cents=399900,
                  refund_due_cents=0)

    season_now = fx.get_season(api, season["id"])
    assert season_now["tuition_collected_cents"] == 0
    assert season_now["late_fee_collected_cents"] == 0


def _one_stay_of_ten_nights(api, season_id):
    built = fx.signed_agreement_with_school(
        api, season_id, nightly_rate_cents=450, minimum_billable_beds=0,
        school_overrides={"name": "Rockford High School", "city": "Rockford",
                          "state_code": "IL"},
    )
    member = fx.contracted_member(api, season_id, full_name="Avery Nakamura",
                                  date_of_birth="2005-03-04")["member"]
    assignment = fx.house_member(api, built["agreement"]["id"], member["id"], 4,
                                 "2027-05-10", "2027-05-20")
    return {"school": built["school"], "agreement": built["agreement"],
            "member": member, "assignment": assignment}


def _housing_ledgers(api, built, season_id):
    return (
        fx.get_agreement(api, built["agreement"]["id"]),
        fx.get_school(api, built["school"]["id"])["reserved_bed_nights"],
        fx.get_season(api, season_id)["housing_cost_cents"],
    )


def test_releasing_the_stay_hands_every_bed_night_back(api):
    """The release runs the housing chain in reverse, down to zero.

    PRD: "Releasing a stay by hand sets `released_reason` to `MANUAL`, moves the
    assignment `ACTIVE → RELEASED`, and runs exactly the same recomputation in
    reverse: the agreement's occupancy drops by that stay's `nights`, its billing
    figures are re-derived, the school's `reserved_bed_nights` drops by the same
    nights, and the season's housing cost is re-summed."

    Design: Difficulty/compensating_invariant/housing_release_and_rebooking_restore_bed_night_ledgers_without_drift
    """
    season = fx.create_season(api)
    built = _one_stay_of_ten_nights(api, season["id"])
    agreement, reserved, housing_cost = _housing_ledgers(api, built, season["id"])
    assert_facility_agreement(agreement, occupied_bed_nights=10,
                              billable_bed_nights=10, billable_cents=4500)
    assert (reserved, housing_cost) == (10, 4500)

    released = fx.release_housing(api, built["assignment"]["id"])
    assert_housing_assignment(released, status="RELEASED", released_reason="MANUAL",
                              nights=10)

    agreement, reserved, housing_cost = _housing_ledgers(api, built, season["id"])
    assert_facility_agreement(agreement, occupied_bed_nights=0,
                              billable_bed_nights=0, billable_cents=0,
                              effective_nightly_rate_cents=450)
    assert (reserved, housing_cost) == (0, 0)


def test_rebooking_the_freed_bed_re_adds_those_nights_exactly_once(api):
    """A released bed is instantly re-assignable and does not double-count.

    PRD: "Released assignments free their beds immediately and are excluded from
    the overlap set and from every bed-night sum, which is what makes a released
    bed instantly re-assignable."

    Design: Difficulty/compensating_invariant/housing_release_and_rebooking_restore_bed_night_ledgers_without_drift
    """
    season = fx.create_season(api)
    built = _one_stay_of_ten_nights(api, season["id"])
    fx.release_housing(api, built["assignment"]["id"])

    rebooked = fx.house_member(api, built["agreement"]["id"], built["member"]["id"], 4,
                               "2027-05-10", "2027-05-20")
    assert_housing_assignment(rebooked, status="ACTIVE", nights=10, space_index=4)

    agreement, reserved, housing_cost = _housing_ledgers(api, built, season["id"])
    assert_facility_agreement(agreement, occupied_bed_nights=10,
                              billable_bed_nights=10, billable_cents=4500,
                              effective_nightly_rate_cents=450)
    assert (reserved, housing_cost) == (10, 4500)


def test_the_release_rebook_release_round_trip_leaves_no_drift(api):
    """Two full cycles end exactly where the first one began.

    PRD: "A release requires the assignment to be `ACTIVE`; a second release
    reports `ERR_INVALID_HOUSING_STATE`."

    Design: Difficulty/compensating_invariant/housing_release_and_rebooking_restore_bed_night_ledgers_without_drift
    """
    season = fx.create_season(api)
    built = _one_stay_of_ten_nights(api, season["id"])
    fx.release_housing(api, built["assignment"]["id"])
    rebooked = fx.house_member(api, built["agreement"]["id"], built["member"]["id"], 4,
                               "2027-05-10", "2027-05-20")

    released_again = fx.release_housing(api, rebooked["id"])
    assert_housing_assignment(released_again, status="RELEASED",
                              released_reason="MANUAL", nights=10)

    agreement, reserved, housing_cost = _housing_ledgers(api, built, season["id"])
    assert_facility_agreement(agreement, occupied_bed_nights=0,
                              billable_bed_nights=0, billable_cents=0,
                              effective_nightly_rate_cents=450)
    assert (reserved, housing_cost) == (0, 0)
