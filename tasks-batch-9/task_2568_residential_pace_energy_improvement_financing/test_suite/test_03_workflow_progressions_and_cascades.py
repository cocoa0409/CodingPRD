"""Progressions that revisit a state without repeating its outcome, and multi-link cascades.

The cure cycle returns an application to the same status twice and then declines it
on an identical payload; the assessment's two status axes advance on independent
schedules; and an uphold or a roll run must complete every downstream link inside
the one call.
"""

from test_helpers import assertions as A
from test_helpers import factories, fixtures
from test_helpers.api_errors import ERR_TRANSFER_STATE_INVALID
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    COUNTY_OFFICER,
    PROGRAM_ADMIN,
    UNDERWRITING_ANALYST,
)


def _cure_round(client, world, reason_code, note):
    A.expect_ok(
        client.underwrite_application(
            world["application_id"],
            factories.underwrite_cure_payload([reason_code]),
            UNDERWRITING_ANALYST,
        )
    )
    return A.expect_ok(
        client.cure_application(
            world["application_id"], world["owner_headers"], factories.cure_payload(note)
        )
    )


def test_two_cure_rounds_return_to_under_review_without_resetting_the_counter(client):
    """UNDER_REVIEW is re-entered twice while cure_round_count only ever climbs.

    It requires a non-empty `cure_reason_codes` array in the request, whose members are
    drawn from `TAX_DELINQUENCY`, `MEASURE_SIR_FAIL`, `APPRAISAL_MISSING` and
    `LENDER_UNRESPONSIVE`; that array is stored on the application, `cure_round_count`
    is incremented by one, and `status` becomes `NEEDS_CURE`.

    Design: Difficulty/non_linear_state_machine/application_cure_cycle_then_exhausted_rounds_decline
    """
    world = fixtures.submitted_application(client)

    first = A.expect_ok(
        client.underwrite_application(
            world["application_id"],
            factories.underwrite_cure_payload(["APPRAISAL_MISSING"]),
            UNDERWRITING_ANALYST,
        )
    )
    A.assert_fields(
        first,
        status="NEEDS_CURE",
        cure_round_count=1,
        cure_reason_codes=["APPRAISAL_MISSING"],
    )

    returned = A.expect_ok(
        client.cure_application(
            world["application_id"],
            world["owner_headers"],
            factories.cure_payload("Appraisal uploaded"),
        )
    )
    A.assert_fields(
        returned, status="UNDER_REVIEW", cure_round_count=1, cure_reason_codes=[]
    )

    second = A.expect_ok(
        client.underwrite_application(
            world["application_id"],
            factories.underwrite_cure_payload(["LENDER_UNRESPONSIVE"]),
            UNDERWRITING_ANALYST,
        )
    )
    A.assert_fields(
        second,
        status="NEEDS_CURE",
        cure_round_count=2,
        cure_reason_codes=["LENDER_UNRESPONSIVE"],
    )

    second_return = A.expect_ok(
        client.cure_application(
            world["application_id"],
            world["owner_headers"],
            factories.cure_payload("Lender chased by phone"),
        )
    )
    A.assert_fields(second_return, status="UNDER_REVIEW", cure_round_count=2)


def test_the_third_cure_decision_declines_instead_of_repeating_needs_cure(client):
    """The identical CURE payload that twice yielded NEEDS_CURE now closes the file.

    The program grants at most two owner cure rounds: when a `CURE` decision arrives on
    an application whose `cure_round_count` already stands at 2, the application is
    instead moved to `DECLINED` with `decline_reason_code` set to
    `CURE_ROUNDS_EXHAUSTED`, the counter is left at 2, and every remaining `PROPOSED`
    measure is marked `INELIGIBLE`.

    Design: Difficulty/non_linear_state_machine/application_cure_cycle_then_exhausted_rounds_decline
    """
    world = fixtures.submitted_application(client)
    _cure_round(client, world, "APPRAISAL_MISSING", "Appraisal uploaded")
    _cure_round(client, world, "LENDER_UNRESPONSIVE", "Lender chased by phone")

    declined = A.expect_ok(
        client.underwrite_application(
            world["application_id"],
            factories.underwrite_cure_payload(["LENDER_UNRESPONSIVE"]),
            UNDERWRITING_ANALYST,
        )
    )
    A.assert_fields(
        declined,
        status="DECLINED",
        decline_reason_code="CURE_ROUNDS_EXHAUSTED",
        cure_round_count=2,
    )
    for measure_id in (world["solar_measure_id"], world["hvac_measure_id"]):
        A.assert_fields(fixtures.read_measure(client, measure_id), status="INELIGIBLE")

    # No mortgage holder is notified on this path.
    A.assert_fields(
        A.expect_ok(client.get_mortgage_lien(world["lien_id"], PROGRAM_ADMIN)),
        consent_response="NOT_NOTIFIED",
        consent_application_id=None,
        notified_at=None,
    )
    A.assert_fields(declined, consent_posture="NOT_STARTED", notified_lien_count=0)


def _referred_assessment(client):
    """Two delinquent years, so the lien axis has moved but the billing axis has not."""
    world = fixtures.assessed_project(client, first_tax_year=2027)
    fixtures.move_clock(client, "2027-10-01T00:00:00Z")
    A.expect_ok(
        client.run_county_roll(
            "06073", factories.roll_run_payload(2027, "2027-10-01"), COUNTY_OFFICER
        )
    )
    A.assert_fields(
        fixtures.read_assessment(client, world),
        billing_status="ON_ROLL",
        lien_status="SENIOR_RECORDED",
    )
    fixtures.move_clock(client, "2028-12-15T00:00:00Z")
    A.expect_ok(
        client.run_county_roll(
            "06073", factories.roll_run_payload(2028, "2028-12-15"), COUNTY_OFFICER
        )
    )
    world["installments"] = fixtures.schedule_of(client, world)
    return world


def test_the_lien_axis_moves_while_the_billing_axis_stays_on_roll(client):
    """A referral advances only the lien dimension; billing_status is untouched.

    The two assessment status axes are checked independently, otherwise
    `ERR_ASSESSMENT_STATE_INVALID` (409). A payoff quote and a prepayment both require
    `billing_status` of `ON_ROLL` **and** `lien_status` of `SENIOR_RECORDED`. An
    installment payment requires `billing_status` of `ON_ROLL` only, and is explicitly
    legal while `lien_status` is `LIEN_SALE_REFERRED`, because paying the delinquent
    installments is the only route back to `SENIOR_RECORDED`.

    Design: Difficulty/non_linear_state_machine/assessment_parallel_billing_and_lien_dimensions_advance_independently
    """
    world = _referred_assessment(client)
    A.assert_fields(
        fixtures.read_assessment(client, world),
        billing_status="ON_ROLL",
        lien_status="LIEN_SALE_REFERRED",
        delinquent_installment_count=2,
        accrued_penalty_cents=150770,
    )

    first = A.find_installment(world["installments"], 2027)
    A.expect_ok(
        client.pay_installment(
            world["assessment_id"],
            first["id"],
            factories.installment_payment_payload(549867),
            COUNTY_OFFICER,
        )
    )
    A.assert_fields(
        A.expect_ok(
            client.get_installment(world["assessment_id"], first["id"], COUNTY_OFFICER)
        ),
        status="PAID",
        paid_amount_cents=549867,
    )
    # One delinquent row remains, so the lien axis has not yet recovered.
    A.assert_fields(
        fixtures.read_assessment(client, world),
        lien_status="LIEN_SALE_REFERRED",
        delinquent_installment_count=1,
        billing_status="ON_ROLL",
        principal_balance_cents=4220219,
    )


def test_curing_the_last_delinquency_recovers_the_lien_axis_alone(client):
    """The lien axis closes its cycle while the billing axis is still mid-term.

    Curing the *last* remaining `DELINQUENT` installment moves the lien axis back from
    `LIEN_SALE_REFERRED` to `SENIOR_RECORDED`, sets `delinquent_installment_count` to 0
    and zeroes `accrued_penalty_cents`; the parcel's `tax_delinquency_count_36m` is
    pointedly **not** decremented, because the 36-month history is a permanent record
    and a cured parcel still carries its mark into the next underwrite.

    Design: Difficulty/non_linear_state_machine/assessment_parallel_billing_and_lien_dimensions_advance_independently
    """
    world = _referred_assessment(client)
    rows = world["installments"]
    A.expect_ok(
        client.pay_installment(
            world["assessment_id"],
            A.find_installment(rows, 2027)["id"],
            factories.installment_payment_payload(549867),
            COUNTY_OFFICER,
        )
    )
    A.expect_ok(
        client.pay_installment(
            world["assessment_id"],
            A.find_installment(rows, 2028)["id"],
            factories.installment_payment_payload(487785),
            COUNTY_OFFICER,
        )
    )

    assessment = fixtures.read_assessment(client, world)
    A.assert_fields(
        assessment,
        lien_status="SENIOR_RECORDED",
        delinquent_installment_count=0,
        accrued_penalty_cents=0,
    )
    # Never PAID_OFF: the balance is still positive, so the two axes ended apart.
    A.assert_fields(
        assessment, billing_status="ON_ROLL", principal_balance_cents=4118396
    )
    assert assessment["principal_balance_cents"] > 0

    A.assert_fields(
        fixtures.read_property(client, world), tax_delinquency_count_36m=1
    )


def _contractor_with_two_projects(client):
    """One released project on the first parcel, one draw still awaiting release on the second."""
    world = fixtures.solar_only_project(client)
    fixtures.second_parcel(client, world)
    owner2 = world["second_owner_headers"]

    app2 = A.expect_created(
        client.open_application(
            factories.application_payload(
                world["second_property_id"], world["contractor_id"], 20
            ),
            owner2,
        )
    )
    version = A.expect_ok(client.get_application(app2["id"], owner2))["version"]
    measure2 = A.expect_created(
        client.add_measure(
            app2["id"],
            factories.measure_payload(world["solar_product_id"], version, 1000000, 100000),
            owner2,
        )
    )
    A.expect_ok(client.submit_application(app2["id"], owner2))
    A.expect_ok(
        client.underwrite_application(
            app2["id"],
            factories.underwrite_proceed_payload("ASSESSED"),
            UNDERWRITING_ANALYST,
        )
    )
    A.expect_ok(
        client.record_consent_response(
            world["second_lien_id"],
            factories.consent_response_payload(),
            COMPLIANCE_OFFICER,
        )
    )
    A.expect_ok(client.approve_application(app2["id"], COMPLIANCE_OFFICER))
    approved_version = A.expect_ok(client.get_application(app2["id"], owner2))["version"]
    agreement2 = A.expect_created(
        client.issue_agreement(
            factories.agreement_payload(app2["id"], approved_version, 20, 800),
            UNDERWRITING_ANALYST,
        )
    )
    A.expect_ok(
        client.sign_agreement(
            agreement2["id"],
            factories.sign_agreement_payload(world["second_owner_full_name"]),
            owner2,
        )
    )
    certificate2 = A.expect_created(
        client.file_certificate(
            factories.certificate_payload(app2["id"], [measure2["id"]], 1000000),
            world["contractor_caller"],
        )
    )
    A.expect_ok(
        client.sign_certificate(
            certificate2["id"],
            factories.sign_certificate_payload(world["second_owner_full_name"]),
            owner2,
        )
    )
    A.expect_ok(
        client.verify_certificate(
            certificate2["id"],
            factories.verify_certificate_payload("APPROVE"),
            fixtures.FUNDING_OFFICER_VERIFIER,
        )
    )
    draw2 = A.expect_created(
        client.request_disbursement(
            factories.disbursement_payload(
                app2["id"], certificate2["id"], world["contractor_id"], 1000000
            ),
            fixtures.FUNDING_OFFICER_VERIFIER,
        )
    )
    world["second_application_id"] = app2["id"]
    world["second_agreement_id"] = agreement2["id"]
    world["second_certificate_id"] = certificate2["id"]
    world["second_disbursement_id"] = draw2["id"]
    return world


def test_a_severe_uphold_completes_all_four_cascade_links_in_one_call(client):
    """Adjudicating one complaint freezes a draw and an application on another parcel.

    An uphold therefore propagates through a four-link chain, and every link must
    complete inside the one call.

    Design: Difficulty/transitive_cascade/complaint_upheld_probation_hold_funding_cascade_depth4
    """
    world = _contractor_with_two_projects(client)
    fixtures.move_clock(client, "2026-08-20T00:00:00Z")
    fixtures.upheld_complaint(client, world, "2026-09-30", severity="SEVERE")

    # Link one: the complaint itself.
    A.assert_fields(
        fixtures.read_complaint(client, world),
        status="REMEDY_ORDERED",
        adjudicated_at="2026-08-20T00:00:00Z",
        remedy_deadline_on="2026-09-30",
    )
    # Link two: both score variants and the enrollment move.
    A.assert_fields(
        fixtures.read_contractor(client, world),
        workmanship_score=8000,
        lifetime_workmanship_score=8000,
        enrollment_status="PROBATION",
        suspension_reason="WORKMANSHIP_SCORE_BELOW_9000",
        upheld_open_remedy_count=1,
    )
    # Link three: the requested draw on the unrelated parcel.
    A.assert_fields(
        A.expect_ok(
            client.get_disbursement(world["second_disbursement_id"], PROGRAM_ADMIN)
        ),
        status="HELD",
        hold_reason="CONTRACTOR_PROBATION",
    )
    # Link four: that draw's application.
    A.assert_fields(
        A.expect_ok(
            client.get_application(world["second_application_id"], PROGRAM_ADMIN)
        ),
        status="FUNDING_HELD",
        funding_hold_reason="CONTRACTOR_PROBATION",
    )


def test_the_uphold_cascade_moves_states_and_never_touches_money(client):
    """The released draw, the funded application and both ledgers survive the cascade.

    **Link three** is that every disbursement of that contractor standing at `REQUESTED`
    moves to `HELD`, with `hold_reason` set to `CONTRACTOR_PROBATION` or
    `CONTRACTOR_SUSPENSION` according to where the contractor landed; a draw already
    `HELD` under probation keeps its held status but has its `hold_reason` upgraded to
    `CONTRACTOR_SUSPENSION`.

    Design: Difficulty/transitive_cascade/complaint_upheld_probation_hold_funding_cascade_depth4
    """
    world = _contractor_with_two_projects(client)
    committed_before = A.expect_ok(
        client.get_property(world["second_property_id"], PROGRAM_ADMIN)
    )["committed_pace_principal_cents"]
    assert committed_before == 1034500

    fixtures.move_clock(client, "2026-08-20T00:00:00Z")
    fixtures.upheld_complaint(client, world, "2026-09-30", severity="SEVERE")

    # The already-released draw is not clawed back by a hold.
    A.assert_fields(fixtures.read_disbursement(client, world), status="RELEASED")
    A.assert_fields(fixtures.read_application(client, world), status="FUNDED")
    A.assert_contractor_ledger(fixtures.read_contractor(client, world), 3000000, 0)
    A.assert_fields(
        A.expect_ok(client.get_property(world["second_property_id"], PROGRAM_ADMIN)),
        committed_pace_principal_cents=1034500,
    )


def _parcel_with_quote_and_live_application(client):
    """One assessed deal with a live payoff quote, plus a fresh application on the same parcel."""
    world = fixtures.assessed_project(client, first_tax_year=2027)
    fixtures.move_clock(client, "2027-10-01T00:00:00Z")
    A.expect_ok(
        client.run_county_roll(
            "06073", factories.roll_run_payload(2027, "2027-10-01"), COUNTY_OFFICER
        )
    )
    fixtures.payoff_quote(client, world, "2027-11-15")

    # The only measure is the 18-year heat pump, so the cost-weighted useful life is
    # 18 and "the requested term ... must not exceed the application's
    # weighted_useful_life_years".
    second_app = A.expect_created(
        client.open_application(
            factories.application_payload(
                world["property_id"], world["contractor_id"], 18
            ),
            world["owner_headers"],
        )
    )
    version = A.expect_ok(
        client.get_application(second_app["id"], world["owner_headers"])
    )["version"]
    A.expect_created(
        client.add_measure(
            second_app["id"],
            factories.measure_payload(world["hvac_product_id"], version, 1000000, 90000),
            world["owner_headers"],
        )
    )
    A.expect_ok(client.submit_application(second_app["id"], world["owner_headers"]))
    world["second_application_id"] = second_app["id"]
    return world


def test_a_referral_voids_the_quote_marks_the_parcel_and_cures_the_live_application(client):
    """Step four reaches a transfer, the parcel history and a neighbouring application.

    **Step four — cascade.** Each referral does three further things. Every transfer of
    that assessment standing at `QUOTED` moves to the terminal `VOID_STALE` and the
    assessment's `transfer_status` returns to `NONE`, which frees the quote window for a
    re-quote after the delinquency is cured. The parcel's `tax_delinquency_count_36m` is
    incremented by one.

    Design: Difficulty/transitive_cascade/roll_run_delinquency_referral_void_cure_cascade_depth4
    """
    world = _parcel_with_quote_and_live_application(client)
    assert fixtures.read_property(client, world)["tax_delinquency_count_36m"] == 0

    fixtures.move_clock(client, "2028-12-15T00:00:00Z")
    run = A.expect_ok(
        client.run_county_roll(
            "06073", factories.roll_run_payload(2028, "2028-12-15"), COUNTY_OFFICER
        )
    )
    A.assert_fields(
        run,
        county_code="06073",
        tax_year=2028,
        effective_date="2028-12-15",
        billed_installment_count=1,
        delinquent_installment_count=2,
        total_penalty_cents=150770,
        referred_assessment_ids=world["assessment_id"],
        voided_transfer_ids=world["transfer_id"],
        cured_application_ids=world["second_application_id"],
        incremented_property_ids=world["property_id"],
    )

    A.assert_fields(
        fixtures.read_assessment(client, world),
        lien_status="LIEN_SALE_REFERRED",
        billing_status="ON_ROLL",
        transfer_status="NONE",
        delinquent_installment_count=2,
        accrued_penalty_cents=150770,
    )
    A.assert_fields(
        fixtures.read_transfer(client, world),
        status="VOID_STALE",
        recorded_on=None,
        payoff_principal_cents=4314500,
    )
    A.assert_fields(fixtures.read_property(client, world), tax_delinquency_count_36m=1)
    A.assert_fields(
        A.expect_ok(
            client.get_application(world["second_application_id"], PROGRAM_ADMIN)
        ),
        status="NEEDS_CURE",
        cure_reason_codes=["TAX_DELINQUENCY"],
        cure_round_count=0,
    )


def test_the_referral_cascade_spares_terminal_records_and_locks_the_voided_quote(client):
    """A terminal application is never dragged into the cure, and the void is final.

    Two things distinguish this from an analyst's cure: `cure_round_count` is *not*
    incremented, because a system-initiated cure does not consume one of the owner's two
    rounds, and when the application was in `CONSENT_PENDING` its `consent_posture` is
    left exactly as it stood, so consents already collected survive the cure round.

    Design: Difficulty/transitive_cascade/roll_run_delinquency_referral_void_cure_cascade_depth4
    """
    world = _parcel_with_quote_and_live_application(client)
    fixtures.move_clock(client, "2028-12-15T00:00:00Z")
    A.expect_ok(
        client.run_county_roll(
            "06073", factories.roll_run_payload(2028, "2028-12-15"), COUNTY_OFFICER
        )
    )

    # The originating application was already terminal and stays there.
    A.assert_fields(fixtures.read_application(client, world), status="ASSESSED")
    A.assert_fields(fixtures.read_disbursement(client, world), status="RELEASED")
    A.assert_fields(fixtures.read_agreement(client, world), status="RECORDED")

    # The void is load-bearing: the closing can no longer be recorded on that quote.
    A.expect_error(
        client.record_transfer(world["transfer_id"], COUNTY_OFFICER),
        ERR_TRANSFER_STATE_INVALID,
    )
    A.assert_fields(fixtures.read_transfer(client, world), status="VOID_STALE")
    A.assert_fields(fixtures.read_assessment(client, world), transfer_status="NONE")
