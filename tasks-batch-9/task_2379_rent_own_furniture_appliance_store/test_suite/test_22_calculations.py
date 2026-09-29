"""Three sums whose answer turns on which rows are allowed into the tally.

The verification score admits only telephoned-and-verified references and never
more than three of them. A write-off grade refuses to run the decay formula at
all. The rolling contact window drops a contact made exactly seven days ago.
"""

from __future__ import annotations

from test_helpers import (
    CLOCK_EPOCH,
    COLLECTOR,
    COLLECTOR_USER_ID,
    DAY_12,
    DAY_12_1500,
    DAY_13_1500,
    DAY_14_1500,
    DAY_14_1600,
    DAY_19_1500,
    MANAGER,
    OFFICER,
    OFFICER_USER_ID,
    TECH_USER_ID,
    AccountFlag,
    Channel,
    CheckStatus,
    CollectionsStage,
    ConditionGrade,
    Decision,
    DepreciationTier,
    ErrorId,
    InspectionStatus,
    Outcome,
    PaymentStatus,
    PossessionStatus,
    Relationship,
    ResidualBasis,
    RetiredReason,
    UnitStatus,
    VerificationStatus,
    assert_fields,
    assert_ordered_by,
    assert_total_count,
    build_tx_floor,
    deliver_on,
    factories,
    failure,
    sign_on,
)

SCORE_WITH_TWO_VERIFIED_REFERENCES = 60
SCORE_WITH_FOUR_VERIFIED_REFERENCES = 70
SCORE_IF_THE_CAP_WERE_IGNORED = 80

DAMAGE_DEDUCTION_CENTS = 40000
MISSING_PARTS = 2
PROVISIONAL_RESIDUAL_CENTS = 96900


def test_only_verified_references_score_and_never_more_than_three_of_them(world):
    """An unreachable reference is worth nothing and a fourth verified one is worth nothing.

    PRD: Ten points are awarded for each `VERIFIED` reference, counting at most three of them, so this term contributes at most 30 points.

    Design: Corner/calculations/verification_score_counts_only_verified_references_and_caps_at_three
    """
    world.set_clock(CLOCK_EPOCH)
    world.seed_tx_rule()
    customer = world.create_customer(factories.ivy_chen_payload())

    for name, relationship, phone, result in (
        ("Ruth Vega", Relationship.FAMILY, "+15125550112", CheckStatus.VERIFIED),
        ("Sam Ortiz", Relationship.LANDLORD, "+15125550113", CheckStatus.VERIFIED),
        ("Cal Diaz", Relationship.PERSONAL, "+15125550114", CheckStatus.UNREACHABLE),
    ):
        reference = world.add_reference(
            customer["id"], factories.reference_payload(name, relationship, phone)
        )
        world.check_reference(reference["id"], result)

    failure(
        world.api.verify_customer(
            customer["id"], factories.verify_payload(Decision.APPROVE), OFFICER
        ),
        ErrorId.VERIFICATION_SCORE_TOO_LOW,
    )
    assert_fields(
        world.get_customer(customer["id"]),
        verification_status=VerificationStatus.PENDING,
        verified_by_user_id="",
    )

    rejected = world.verify_customer(customer["id"], Decision.REJECT)
    assert_fields(
        rejected,
        verification_status=VerificationStatus.REJECTED,
        verification_score=SCORE_WITH_TWO_VERIFIED_REFERENCES,
        verified_reference_count=2,
    )

    for name, phone in (("Nina Park", "+15125550115"), ("Omar Vale", "+15125550116")):
        extra = world.add_reference(
            customer["id"],
            factories.reference_payload(name, Relationship.PERSONAL, phone),
        )
        world.check_reference(extra["id"], CheckStatus.VERIFIED)
    assert world.get_customer(customer["id"])["verified_reference_count"] == 4

    approved = world.verify_customer(customer["id"], Decision.APPROVE)
    assert_fields(
        approved,
        verification_status=VerificationStatus.VERIFIED,
        verified_by_user_id=OFFICER_USER_ID,
        verification_score=SCORE_WITH_FOUR_VERIFIED_REFERENCES,
    )
    assert approved["verification_score"] != SCORE_IF_THE_CAP_WERE_IGNORED, (
        "the fourth verified reference must be dropped by the cap, not counted"
    )

    rows = assert_total_count(
        world.api.list_customer_references(customer["id"], OFFICER), 5
    )
    unreachable = [
        row for row in rows if row["check_status"] == CheckStatus.UNREACHABLE
    ]
    assert len(unreachable) == 1, (
        f"exactly one reference must have gone unreached, got {len(unreachable)}"
    )


def test_an_unrentable_grade_short_circuits_the_residual_to_a_write_off(world):
    """The decay formula never runs, so no deduction can push the residual negative.

    PRD: An `assessed_grade` of `UNRENTABLE` short-circuits the whole formula to a residual of 0.

    Design: Corner/calculations/unrentable_grade_short_circuits_the_residual_to_a_write_off
    """
    scenario = deliver_on(sign_on(build_tx_floor(world)))
    world.start_return(scenario.agreement_id)
    inspection = world.inspections(agreement_id=scenario.agreement_id)[0]
    assert_fields(
        inspection, status=InspectionStatus.PENDING, assessed_grade=None
    )
    assert scenario.read_unit()["residual_value_cents"] == PROVISIONAL_RESIDUAL_CENTS

    graded = world.grade(
        inspection["id"],
        ConditionGrade.UNRENTABLE,
        damage_deduction_cents=DAMAGE_DEDUCTION_CENTS,
        missing_parts_count=MISSING_PARTS,
    )
    assert_fields(
        graded,
        status=InspectionStatus.GRADED,
        assessed_grade=ConditionGrade.UNRENTABLE,
        damage_deduction_cents=DAMAGE_DEDUCTION_CENTS,
        missing_parts_count=MISSING_PARTS,
        final_residual_value_cents=0,
        re_rent_rate_cents=0,
        depreciation_tier=DepreciationTier.WRITE_OFF,
        graded_by_user_id=TECH_USER_ID,
    )

    # Unlike a GRADE_A/B/C grading, a write-off neither steps the grade nor
    # counts the cycle: the unit leaves the re-rent loop for good.
    assert_fields(
        scenario.read_unit(),
        status=UnitStatus.RETIRED,
        retired_reason=RetiredReason.UNRENTABLE_ON_GRADING,
        residual_value_cents=0,
        residual_valuation_basis=ResidualBasis.FINAL,
        condition_grade=ConditionGrade.NEW,
        rent_cycle_count=0,
    )
    assert_fields(
        scenario.read_agreement(),
        possession_status=PossessionStatus.RETURNED,
        payment_status=PaymentStatus.CLOSED,
    )


def test_a_contact_made_exactly_seven_days_ago_has_already_fallen_out(world):
    """Three calls block a fourth, then the oldest ages off the boundary exactly.

    PRD: **Frequency** comes second: the rolling count is the number of contacts already on **this** agreement whose `contacted_at` falls strictly after the instant seven days before the clock and at or before the clock itself — a half-open window, so a contact made exactly seven days ago has already fallen out — and contacts on the customer's other agreements never count.

    Design: Corner/calculations/collection_contact_window_lower_bound_is_exclusive
    """
    scenario = deliver_on(sign_on(build_tx_floor(world)))
    world.set_clock(DAY_12)
    world.day_close(scenario.store_id)

    for instant, channel, outcome, expected_rolling in (
        (DAY_12_1500, Channel.PHONE, Outcome.NO_ANSWER, 0),
        (DAY_13_1500, Channel.SMS, Outcome.LEFT_MESSAGE, 1),
        (DAY_14_1500, Channel.EMAIL, Outcome.SPOKE_TO_CUSTOMER, 2),
    ):
        world.set_clock(instant)
        logged = world.log_contact(scenario.agreement_id, channel, outcome)
        assert_fields(
            logged,
            agreement_id=scenario.agreement_id,
            channel=channel,
            outcome=outcome,
            contacted_at=instant,
            contacted_by_user_id=COLLECTOR_USER_ID,
            rolling_7d_count_at_contact=expected_rolling,
        )
    assert scenario.read_agreement()["collection_contact_count_7d"] == 3

    world.set_clock(DAY_14_1600)
    failure(
        world.api.log_collection_contact(
            scenario.agreement_id,
            factories.collection_contact_payload(Channel.PHONE, Outcome.NO_ANSWER),
            COLLECTOR,
        ),
        ErrorId.CONTACT_FREQUENCY_EXCEEDED,
    )

    world.set_clock(DAY_19_1500)
    accepted = world.log_contact(
        scenario.agreement_id, Channel.IN_PERSON, Outcome.PROMISE_TO_PAY
    )
    assert_fields(
        accepted,
        contacted_at=DAY_19_1500,
        rolling_7d_count_at_contact=2,
    )
    assert scenario.read_agreement()["collection_contact_count_7d"] == 3

    rows = assert_total_count(
        world.api.list_collection_contacts(scenario.agreement_id, MANAGER), 4
    )
    assert_ordered_by(rows, "contacted_at")
    assert_fields(
        scenario.read_agreement(), collections_stage=CollectionsStage.ADVERSE
    )
    assert_fields(scenario.read_customer(), account_flag=AccountFlag.ADVERSE)
