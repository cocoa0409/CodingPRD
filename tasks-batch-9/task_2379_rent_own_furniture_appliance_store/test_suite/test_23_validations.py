"""Gates that read a jurisdiction's own configuration before they decide.

The disclosure requirement and the term cap both refuse a signing the shop would
otherwise be happy to take. A credit score is contraband in one state and routine
in the next. And an equity limit expressed as a strict inequality protects the
renter who is sitting exactly on it.
"""

from __future__ import annotations

from test_helpers import (
    CLOCK_EPOCH,
    COLLECTOR,
    MANAGER,
    NOV_06,
    NOV_27,
    NOV_28,
    NOV_28_1500,
    OFFICER,
    OFFICER_USER_ID,
    SALES,
    ST_PAUL_MAIN,
    W52_ADJUSTED_CASH_PRICE_CENTS,
    AccountFlag,
    Channel,
    CollectionsStage,
    Decision,
    ErrorId,
    InspectionStatus,
    Outcome,
    PaymentMethod,
    PaymentStatus,
    PossessionStatus,
    ResidualBasis,
    ReturnReason,
    TermType,
    UnitStatus,
    VerificationStatus,
    WindowStatus,
    assert_fields,
    assert_paid_pct,
    assert_pricing,
    assert_total_count,
    build_mn_floor,
    build_tx_floor,
    factories,
    failure,
    success,
)

ABOVE_THE_TEXAS_CAP = 79
AT_THE_TEXAS_CAP = 78
CAP_RENEWAL_RATE_CENTS = 3385
CAP_RENT_SUBTOTAL_CENTS = 264030
CAP_PROCESSING_FEE_CENTS = 5000
CAP_TOTAL_OF_PAYMENTS_CENTS = 269030
CAP_MONTHLY_EQUIVALENT_CENTS = 14668

BUREAU_SCORE = 700
EXPECTED_VERIFICATION_SCORE = 95

MN_RENEWAL_RATE_CENTS = 11000
MN_RENT_SUBTOTAL_CENTS = 264000
MN_TOTAL_OF_PAYMENTS_CENTS = 264000
MN_MONTHLY_EQUIVALENT_CENTS = 47667
TWELVE_PERIODS_CENTS = 132000
ELEVEN_PERIODS_CENTS = 121000
MN_LATE_FEE_TOTAL_CENTS = 1100
PROVISIONAL_RESIDUAL_CENTS = 96900

MORNING_START = "2026-08-01T09:00:00Z"
MORNING_END = "2026-08-01T11:00:00Z"
AFTERNOON_START = "2026-08-01T13:00:00Z"
AFTERNOON_END = "2026-08-01T15:00:00Z"


def test_the_disclosure_and_the_term_cap_both_gate_the_signing(world):
    """Two statutory refusals, then the identical signing at the cap itself succeeds.

    PRD: Where that jurisdiction requires the total-of-payments disclosure, `disclosure_acknowledged` must be true or the signing is refused with `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`, and a `renewal_count` above the jurisdiction's cap is refused with `ERR_TERM_EXCEEDS_STATE_CAP`.

    Design: Corner/validations/disclosure_and_term_cap_gate_agreement_creation
    """
    scenario = build_tx_floor(world)

    failure(
        scenario.api.create_agreement(
            factories.agreement_payload(
                scenario.customer_id,
                scenario.unit_id,
                TermType.WEEKLY,
                52,
                disclosure_acknowledged=False,
            ),
            SALES,
        ),
        ErrorId.DISCLOSURE_NOT_ACKNOWLEDGED,
    )
    failure(
        scenario.api.create_agreement(
            factories.agreement_payload(
                scenario.customer_id,
                scenario.unit_id,
                TermType.WEEKLY,
                ABOVE_THE_TEXAS_CAP,
            ),
            SALES,
        ),
        ErrorId.TERM_EXCEEDS_STATE_CAP,
    )

    assert scenario.read_unit()["status"] == UnitStatus.AVAILABLE, (
        "a refused signing must not reserve the goods"
    )
    assert_total_count(world.api.list_agreements(MANAGER), 0)

    agreement = world.sign(
        scenario.customer_id, scenario.unit_id, TermType.WEEKLY, AT_THE_TEXAS_CAP
    )
    assert_pricing(
        agreement,
        adjusted_cash_price_cents=W52_ADJUSTED_CASH_PRICE_CENTS,
        renewal_rate_cents=CAP_RENEWAL_RATE_CENTS,
        rent_subtotal_cents=CAP_RENT_SUBTOTAL_CENTS,
        processing_fee_cents=CAP_PROCESSING_FEE_CENTS,
        total_of_payments_cents=CAP_TOTAL_OF_PAYMENTS_CENTS,
        monthly_equivalent_rate_cents=CAP_MONTHLY_EQUIVALENT_CENTS,
    )
    assert_fields(
        agreement,
        renewal_count=AT_THE_TEXAS_CAP,
        state_code_snapshot="TX",
        payment_status=PaymentStatus.CURRENT,
        possession_status=PossessionStatus.PENDING_DELIVERY,
    )
    assert scenario.read_unit()["status"] == UnitStatus.RESERVED


def test_the_credit_inquiry_ban_follows_the_renters_own_jurisdiction(world):
    """The same request body is contraband in Texas and routine in Minnesota.

    PRD: A `credit_score` field exists in the request shape for exactly one reason: so that supplying it can be refused with `ERR_CREDIT_REPORT_PROHIBITED` in any jurisdiction whose `credit_inquiry_prohibited` flag is true.

    Design: Corner/validations/credit_inquiry_prohibition_is_state_conditional
    """
    world.set_clock(CLOCK_EPOCH)
    world.seed_tx_rule()
    world.seed_mn_rule()

    texan = world.onboard(
        factories.dana_reyes_payload(), factories.dana_reyes_references(), verify=False
    )
    minnesotan = world.onboard(
        factories.ivar_holm_payload(), factories.ivar_holm_references(), verify=False
    )

    with_a_bureau_file = factories.verify_payload(
        Decision.APPROVE, credit_score=BUREAU_SCORE
    )
    failure(
        world.api.verify_customer(texan["id"], with_a_bureau_file, OFFICER),
        ErrorId.CREDIT_REPORT_PROHIBITED,
    )
    assert_fields(
        world.get_customer(texan["id"]),
        verification_status=VerificationStatus.PENDING,
        verification_score=0,
        verified_by_user_id="",
    )

    permitted = world.api.verify_customer(minnesotan["id"], with_a_bureau_file, OFFICER)
    assert_fields(
        success(permitted),
        verification_status=VerificationStatus.VERIFIED,
        verified_by_user_id=OFFICER_USER_ID,
        verification_score=EXPECTED_VERIFICATION_SCORE,
    )

    without_it = world.verify_customer(texan["id"], Decision.APPROVE)
    assert_fields(
        without_it,
        verification_status=VerificationStatus.VERIFIED,
        verified_by_user_id=OFFICER_USER_ID,
        verification_score=EXPECTED_VERIFICATION_SCORE,
    )


def test_a_renter_sitting_exactly_on_the_equity_limit_is_protected(world):
    """Twelve periods paid is protected at 0.5000; eleven periods is repossessed.

    PRD: `paid_pct` is `rent_applied_cents` divided by `total_of_payments_cents`, rounded half up to four decimal places, and repossession is prohibited once `paid_pct` has reached the jurisdiction's `repossession_paid_pct_limit` — a customer sitting exactly at the limit is protected, and the refusal is `ERR_REPOSSESSION_EQUITY_PROTECTED`.

    Design: Corner/validations/repossession_equity_limit_protects_a_customer_exactly_at_the_state_limit
    """
    scenario = build_mn_floor(
        world,
        ST_PAUL_MAIN,
        serials=("SN-MN-0001", "SN-MN-0002"),
        customer_payload=factories.ivar_holm_payload(in_person_contact_consent=True),
    )
    protected = world.sign(
        scenario.customer_id, scenario.units[0]["id"], TermType.WEEKLY, 24
    )
    assert_pricing(
        protected,
        adjusted_cash_price_cents=W52_ADJUSTED_CASH_PRICE_CENTS,
        renewal_rate_cents=MN_RENEWAL_RATE_CENTS,
        rent_subtotal_cents=MN_RENT_SUBTOTAL_CENTS,
        processing_fee_cents=0,
        total_of_payments_cents=MN_TOTAL_OF_PAYMENTS_CENTS,
        monthly_equivalent_rate_cents=MN_MONTHLY_EQUIVALENT_CENTS,
    )
    world.deliver(
        protected["id"], scenario.crew_id, MORNING_START, MORNING_END
    )

    exposed = world.sign(
        scenario.customer_id, scenario.units[1]["id"], TermType.WEEKLY, 24
    )
    world.deliver(
        exposed["id"], scenario.crew_id, AFTERNOON_START, AFTERNOON_END
    )

    world.pay(protected["id"], TWELVE_PERIODS_CENTS, PaymentMethod.ACH)
    world.pay(exposed["id"], ELEVEN_PERIODS_CENTS, PaymentMethod.ACH)

    world.set_clock(NOV_06)
    arrears = world.day_close(scenario.store_id)
    assert_fields(
        arrears,
        agreements_scanned=2,
        late_fees_assessed=2,
        late_fee_total_cents=MN_LATE_FEE_TOTAL_CENTS,
        windows_opened=2,
        agreements_marked_adverse=2,
    )
    for agreement_id in (protected["id"], exposed["id"]):
        windows = world.windows(agreement_id)
        assert len(windows) == 1, (
            f"expected one reinstatement window, got {len(windows)}"
        )
        assert_fields(
            windows[0],
            status=WindowStatus.OPEN,
            window_days=21,
            expires_at=NOV_27,
            reinstatement_fee_cents=0,
        )

    world.set_clock(NOV_28)
    expiry = world.day_close(scenario.store_id)
    assert_fields(
        expiry,
        windows_expired=2,
        agreements_defaulted=2,
        late_fees_assessed=0,
    )

    world.set_clock(NOV_28_1500)
    for agreement_id in (protected["id"], exposed["id"]):
        world.log_contact(agreement_id, Channel.PHONE, Outcome.SPOKE_TO_CUSTOMER)

    at_the_limit = world.get_agreement(protected["id"])
    assert_fields(
        at_the_limit,
        payment_status=PaymentStatus.DEFAULTED,
        periods_paid=12,
        rent_applied_cents=TWELVE_PERIODS_CENTS,
    )
    assert_paid_pct(at_the_limit, 0.5000)

    below_the_limit = world.get_agreement(exposed["id"])
    assert_fields(
        below_the_limit, periods_paid=11, rent_applied_cents=ELEVEN_PERIODS_CENTS
    )
    assert_paid_pct(below_the_limit, 0.4583)

    failure(
        world.api.repossess_agreement(
            protected["id"], factories.repossess_payload(True), COLLECTOR
        ),
        ErrorId.REPOSSESSION_EQUITY_PROTECTED,
    )
    assert_fields(
        world.get_agreement(protected["id"]),
        possession_status=PossessionStatus.DELIVERED,
    )
    assert world.get_unit(scenario.units[0]["id"])["status"] == UnitStatus.ON_RENT

    repossessed = world.repossess(exposed["id"])
    assert_fields(
        repossessed,
        possession_status=PossessionStatus.REPOSSESSED,
        payment_status=PaymentStatus.CLOSED,
        collections_stage=CollectionsStage.ADVERSE,
    )
    assert_fields(
        world.get_unit(scenario.units[1]["id"]),
        status=UnitStatus.RETURNED_PENDING_GRADE,
        residual_value_cents=PROVISIONAL_RESIDUAL_CENTS,
        residual_valuation_basis=ResidualBasis.PROVISIONAL,
    )

    inspections = assert_total_count(
        world.api.list_return_inspections(MANAGER, {"agreement_id": exposed["id"]}), 1
    )
    assert_fields(
        inspections[0],
        status=InspectionStatus.PENDING,
        return_reason=ReturnReason.REPOSSESSION_RECOVERY,
        unit_id=scenario.units[1]["id"],
    )

    assert scenario.read_store()["units_on_rent_count"] == 1
    assert_fields(
        scenario.read_customer(),
        adverse_agreement_count=2,
        account_flag=AccountFlag.ADVERSE,
    )
