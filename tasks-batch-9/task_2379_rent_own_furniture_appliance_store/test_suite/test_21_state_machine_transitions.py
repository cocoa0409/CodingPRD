"""Where rows start, where they refuse to move twice, and where they lock shut.

A sweep repeated at one clock instant must find its own work already done, a
telephone call may only be recorded once, an owned term accepts nothing further,
and handing the goods back moves possession without touching the money.
"""

from __future__ import annotations

from test_helpers import (
    AUSTIN_MAIN,
    CLOCK_EPOCH,
    DAY_12,
    DAY_17,
    MANAGER,
    SALES,
    SALES_USER_ID,
    TX_LATE_FEE_CENTS,
    TX_REINSTATEMENT_FEE_CENTS,
    W52_RENEWAL_RATE_CENTS,
    WASHER_CASH_PRICE_CENTS,
    AccountFlag,
    Category,
    CheckStatus,
    CollectionsStage,
    ConditionGrade,
    DepreciationTier,
    ErrorId,
    InspectionStatus,
    IssueCode,
    LoyaltyTier,
    PaymentMethod,
    PaymentRowStatus,
    PaymentStatus,
    PossessionStatus,
    Relationship,
    ResidualBasis,
    RetiredReason,
    ReturnReason,
    ServiceType,
    TermType,
    UnitStatus,
    VerificationStatus,
    WindowStatus,
    assert_fields,
    assert_paid_pct,
    assert_pricing,
    assert_total_count,
    assert_tracked_row,
    build_tx_floor,
    deliver_on,
    factories,
    failure,
    sign_on,
)

M2_RENEWAL_RATE_CENTS = 29250
M2_RENT_SUBTOTAL_CENTS = 58500
M2_PROCESSING_FEE_CENTS = 2925
M2_TOTAL_OF_PAYMENTS_CENTS = 61425
M2_POINTS = 610  # 585 whole dollars of rent at the STANDARD multiplier plus the on-time bonus
LATE_TICKET_START = "2026-08-02T09:00:00Z"
LATE_TICKET_END = "2026-08-02T11:00:00Z"
PROVISIONAL_RESIDUAL_CENTS = 96900


def test_a_store_and_a_unit_are_born_in_their_declared_initial_state(world):
    """Neither the derived counters nor the capacity default may be administered.

    PRD: A new store starts with `units_on_rent_count` and `units_in_service_count` at 0 and `service_intake_open` at true.

    Design: Corner/state_machines/store_and_unit_start_in_their_declared_initial_state
    """
    world.set_clock(CLOCK_EPOCH)
    world.seed_tx_rule()

    store = world.open_store(AUSTIN_MAIN, "TX", None)
    assert_fields(
        store,
        name=AUSTIN_MAIN,
        state_code="TX",
        service_bay_capacity=1,
        units_on_rent_count=0,
        units_in_service_count=0,
        service_intake_open=True,
    )
    assert_tracked_row(store, expected_version=1)

    unit = world.add_sofa(store["id"], "SN-TX-0001")
    assert_fields(
        unit,
        store_id=store["id"],
        status=UnitStatus.AVAILABLE,
        condition_grade=ConditionGrade.NEW,
        rent_cycle_count=0,
        accumulated_rent_received_cents=0,
        residual_value_cents=0,
        residual_valuation_basis=ResidualBasis.NONE,
        retired_reason=RetiredReason.NONE,
        replaced_unit_id=None,
    )
    assert_tracked_row(unit, expected_version=1)


def test_a_reference_that_has_left_pending_cannot_be_telephoned_again(world):
    """The first call is recorded with its caller; the second is refused outright.

    PRD: `PENDING` may never be written back, and a reference whose `check_status` has already left `PENDING` cannot be checked twice — the second attempt is refused with `ERR_REFERENCE_ALREADY_CHECKED`.

    Design: Corner/state_machines/checking_a_reference_twice_is_rejected
    """
    world.set_clock(CLOCK_EPOCH)
    customer = world.create_customer(factories.dana_reyes_payload())
    reference = world.add_reference(
        customer["id"],
        factories.reference_payload("Ruth Vega", Relationship.FAMILY, "+15125550102"),
    )
    assert_fields(
        reference,
        check_status=CheckStatus.PENDING,
        checked_at=None,
        checked_by_user_id="",
    )

    checked = world.check_reference(
        reference["id"], CheckStatus.VERIFIED, as_user_id=SALES_USER_ID
    )
    assert_fields(
        checked,
        check_status=CheckStatus.VERIFIED,
        checked_at=CLOCK_EPOCH,
        checked_by_user_id=SALES_USER_ID,
    )

    failure(
        world.api.check_customer_reference(
            reference["id"], factories.check_payload(CheckStatus.UNREACHABLE), SALES
        ),
        ErrorId.REFERENCE_ALREADY_CHECKED,
    )

    rows = assert_total_count(
        world.api.list_customer_references(customer["id"], SALES), 1
    )
    assert_fields(
        rows[0],
        check_status=CheckStatus.VERIFIED,
        checked_by_user_id=SALES_USER_ID,
    )
    assert_fields(
        world.get_customer(customer["id"]),
        verified_reference_count=1,
        verification_status=VerificationStatus.PENDING,
    )


def test_a_second_day_close_at_the_same_instant_finds_its_work_already_done(world):
    """The scan count survives; every effect counter comes back at zero.

    PRD: A second day-close at the same clock value re-scans the same agreements and finds every effect already applied, so `agreements_scanned` still reports how many agreements were inspected while `late_fees_assessed`, `late_fee_total_cents`, `windows_opened`, `windows_expired`, `agreements_defaulted` and `agreements_marked_adverse` all come back 0 and no row changes.

    Design: Corner/state_machines/day_close_repeated_at_the_same_clock_instant_changes_nothing
    """
    scenario = deliver_on(sign_on(build_tx_floor(world)))
    world.set_clock(DAY_12)

    first = world.day_close(scenario.store_id)
    assert_fields(
        first,
        agreements_scanned=1,
        late_fees_assessed=1,
        late_fee_total_cents=TX_LATE_FEE_CENTS,
        windows_opened=1,
        windows_expired=0,
        agreements_defaulted=0,
        agreements_marked_adverse=1,
    )

    second = world.day_close(scenario.store_id)
    assert_fields(
        second,
        agreements_scanned=1,
        late_fees_assessed=0,
        late_fee_total_cents=0,
        windows_opened=0,
        windows_expired=0,
        agreements_defaulted=0,
        agreements_marked_adverse=0,
    )

    assert_fields(
        scenario.read_agreement(),
        payment_status=PaymentStatus.DELINQUENT,
        late_fee_assessed_cents=TX_LATE_FEE_CENTS,
        late_fee_balance_cents=TX_LATE_FEE_CENTS,
        late_fee_period_index_last=1,
        reinstatement_fee_balance_cents=TX_REINSTATEMENT_FEE_CENTS,
        collections_stage=CollectionsStage.ADVERSE,
    )

    windows = assert_total_count(
        world.api.list_reinstatement_windows(scenario.agreement_id, MANAGER), 1
    )
    assert_fields(
        windows[0],
        status=WindowStatus.OPEN,
        missed_period_index=1,
        window_days=5,
        opened_at=DAY_12,
        expires_at=DAY_17,
        reinstatement_fee_cents=TX_REINSTATEMENT_FEE_CENTS,
    )

    assert_fields(
        scenario.read_customer(),
        lifetime_delinquency_count=1,
        adverse_agreement_count=1,
        account_flag=AccountFlag.ADVERSE,
    )


def test_the_payment_that_completes_the_term_locks_the_agreement_down(world):
    """Ownership passes, the appliance is sold, and nothing further may be written.

    PRD: When the payment brings `periods_paid` up to `renewal_count` with no fee balance left and the goods are in `DELIVERED` possession, the term is complete: `payment_status` moves `CURRENT` → `CLOSED`, `possession_status` moves `DELIVERED` → `OWNED`, the unit becomes `SOLD`, and any unapplied remainder has already moved to the customer's `credit_balance_cents`.

    Design: Corner/state_machines/term_completing_payment_closes_the_agreement_and_locks_it_down
    """
    scenario = build_tx_floor(
        world, serials=("SN-TX-0002",), category=Category.APPLIANCE
    )
    sign_on(scenario, term_type=TermType.MONTHLY, renewal_count=2)
    assert_pricing(
        scenario.agreement,
        adjusted_cash_price_cents=WASHER_CASH_PRICE_CENTS,
        renewal_rate_cents=M2_RENEWAL_RATE_CENTS,
        rent_subtotal_cents=M2_RENT_SUBTOTAL_CENTS,
        processing_fee_cents=M2_PROCESSING_FEE_CENTS,
        total_of_payments_cents=M2_TOTAL_OF_PAYMENTS_CENTS,
        monthly_equivalent_rate_cents=M2_RENEWAL_RATE_CENTS,
    )
    deliver_on(
        scenario, service_type=ServiceType.DELIVERY_SETUP, setup_completed=True
    )
    assert_fields(
        scenario.read_agreement(), current_period_due_at="2026-08-31T00:00:00Z"
    )

    payment = world.pay(
        scenario.agreement_id, M2_TOTAL_OF_PAYMENTS_CENTS, PaymentMethod.ACH
    )
    assert_fields(
        payment,
        periods_advanced=2,
        allocation_late_fee_cents=0,
        allocation_reinstatement_fee_cents=0,
        allocation_rent_cents=M2_RENT_SUBTOTAL_CENTS,
        allocation_partial_credit_cents=0,
        allocation_customer_credit_cents=M2_PROCESSING_FEE_CENTS,
        partial_credit_before_cents=0,
        days_late=0,
        cured_delinquency=False,
        loyalty_points_awarded=M2_POINTS,
        status=PaymentRowStatus.POSTED,
    )

    agreement = scenario.read_agreement()
    assert_fields(
        agreement,
        payment_status=PaymentStatus.CLOSED,
        possession_status=PossessionStatus.OWNED,
        periods_paid=2,
        rent_applied_cents=M2_RENT_SUBTOTAL_CENTS,
        customer_credit_contributed_cents=M2_PROCESSING_FEE_CENTS,
    )
    assert_paid_pct(agreement, 0.9524)
    assert scenario.read_unit()["status"] == UnitStatus.SOLD
    assert scenario.read_store()["units_on_rent_count"] == 0
    assert_fields(
        scenario.read_customer(),
        credit_balance_cents=M2_PROCESSING_FEE_CENTS,
        loyalty_points_balance=M2_POINTS,
        loyalty_points_lifetime=M2_POINTS,
        loyalty_tier=LoyaltyTier.GOLD,
    )

    failure(
        world.api.post_renewal_payment(
            scenario.agreement_id,
            factories.payment_payload(100, PaymentMethod.CASH),
            MANAGER,
        ),
        ErrorId.AGREEMENT_CLOSED,
    )
    failure(
        world.api.create_service_ticket(
            scenario.agreement_id,
            factories.service_ticket_payload(
                IssueCode.MECHANICAL, LATE_TICKET_START, LATE_TICKET_END
            ),
            MANAGER,
        ),
        ErrorId.AGREEMENT_CLOSED,
    )
    assert_total_count(
        world.api.list_service_tickets(
            MANAGER, {"agreement_id": scenario.agreement_id}
        ),
        0,
    )


def test_a_voluntary_return_moves_possession_and_leaves_the_money_alone(world):
    """Possession freezes at pending inspection while the payment dimension stays current.

    PRD: The agreement moves `DELIVERED` → `RETURN_PENDING_INSPECTION` while the payment dimension is untouched.

    Design: Corner/state_machines/voluntary_return_freezes_possession_while_payment_stays_current
    """
    scenario = deliver_on(sign_on(build_tx_floor(world)))
    world.pay(scenario.agreement_id, W52_RENEWAL_RATE_CENTS, PaymentMethod.CASH)

    world.start_return(scenario.agreement_id, ReturnReason.VOLUNTARY_RETURN)
    inspections = world.inspections(agreement_id=scenario.agreement_id)
    assert len(inspections) == 1, (
        f"a return must open exactly one inspection, got {len(inspections)}"
    )
    assert_fields(
        inspections[0],
        agreement_id=scenario.agreement_id,
        unit_id=scenario.unit_id,
        status=InspectionStatus.PENDING,
        return_reason=ReturnReason.VOLUNTARY_RETURN,
        assessed_grade=None,
        depreciation_tier=DepreciationTier.TIER_1,
    )

    agreement = scenario.read_agreement()
    assert_fields(
        agreement,
        possession_status=PossessionStatus.RETURN_PENDING_INSPECTION,
        payment_status=PaymentStatus.CURRENT,
        collections_stage=CollectionsStage.NONE,
        periods_paid=1,
        rent_applied_cents=W52_RENEWAL_RATE_CENTS,
        current_period_due_at="2026-08-15T00:00:00Z",
    )
    assert_paid_pct(agreement, 0.0189)

    assert_fields(
        scenario.read_unit(),
        status=UnitStatus.RETURNED_PENDING_GRADE,
        condition_grade=ConditionGrade.NEW,
        rent_cycle_count=0,
        residual_value_cents=PROVISIONAL_RESIDUAL_CENTS,
        residual_valuation_basis=ResidualBasis.PROVISIONAL,
    )
    assert scenario.read_store()["units_on_rent_count"] == 0

    failure(
        world.api.post_renewal_payment(
            scenario.agreement_id,
            factories.payment_payload(W52_RENEWAL_RATE_CENTS, PaymentMethod.CASH),
            MANAGER,
        ),
        ErrorId.POSSESSION_STATE_INVALID,
    )
    assert scenario.read_agreement()["periods_paid"] == 1
