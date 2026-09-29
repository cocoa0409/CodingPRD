"""Requests that fail two checks at once, where only the earlier one may be reported.

An oversized tender against a defaulted agreement is both a state conflict and a
fiscal violation; an in-person call at ten at night to a renter who never consented
to home visits is both a safety violation and an unusable channel.
"""

from __future__ import annotations

from test_helpers import (
    DAY_12,
    DAY_14_2200,
    DAY_15_1500,
    DAY_18,
    DULUTH_MAIN,
    MN_LATE_FEE_CENTS,
    AccountFlag,
    Channel,
    CollectionsStage,
    ErrorId,
    Outcome,
    PaymentMethod,
    PaymentStatus,
    PossessionStatus,
    TermType,
    WindowStatus,
    assert_fields,
    build_mn_floor,
    build_tx_floor,
    deliver_on,
    factories,
    failure,
    sign_on,
)
from test_helpers.test_users import COLLECTOR, SALES

ABSURD_TENDER_CENTS = 999999999

SECOND_DELIVERY_START = "2026-08-18T09:00:00Z"
SECOND_DELIVERY_END = "2026-08-18T11:00:00Z"


def _one_defaulted_and_one_current_agreement(world):
    """The same renter holding two sofas: one defaulted, one freshly delivered."""
    scenario = build_tx_floor(world, serials=("SN-TX-0001", "SN-TX-0002"))
    deliver_on(sign_on(scenario, unit_index=0))

    world.set_clock(DAY_12)
    world.day_close(scenario.store_id)
    world.set_clock(DAY_18)
    world.day_close(scenario.store_id)

    second = world.sign(scenario.customer_id, scenario.units[1]["id"])
    world.deliver(
        second["id"], scenario.crew_id, SECOND_DELIVERY_START, SECOND_DELIVERY_END
    )
    return scenario, second


def test_the_defaulted_state_conflict_is_reported_before_the_overpayment(world):
    """The earlier state check decides the response; the fiscal check never runs.

    PRD: Checks are evaluated in the sequence below and the **first** failing check determines the response; later checks never mask an earlier one, and a request that fails an early check must not exhibit any side effect of a later one.

    Design: Difficulty/priority_pair_validation_conflict/defaulted_state_409_outranks_overpayment_fiscal_422
    """
    scenario, second = _one_defaulted_and_one_current_agreement(world)

    defaulted = scenario.read_agreement()
    assert_fields(
        defaulted,
        payment_status=PaymentStatus.DEFAULTED,
        collections_stage=CollectionsStage.ADVERSE,
        late_fee_balance_cents=508,
    )
    assert world.get_agreement(second["id"])["payment_status"] == PaymentStatus.CURRENT

    response = scenario.api.post_renewal_payment(
        scenario.agreement_id,
        factories.payment_payload(ABSURD_TENDER_CENTS, PaymentMethod.CASH),
        SALES,
    )
    failure(response, ErrorId.AGREEMENT_DEFAULTED)

    assert world.payments(scenario.agreement_id) == [], (
        "a rejected payment must leave no row behind"
    )
    after = scenario.read_agreement()
    assert_fields(
        after,
        payment_status=PaymentStatus.DEFAULTED,
        late_fee_balance_cents=508,
        rent_applied_cents=0,
    )

    customer = scenario.read_customer()
    assert_fields(
        customer, adverse_agreement_count=1, account_flag=AccountFlag.ADVERSE
    )


def test_the_same_oversized_tender_reaches_the_fiscal_check_when_the_state_is_clean(world):
    """With no state conflict to report, the overpayment ceiling is what refuses it.

    PRD: Overpayment is refused: `amount_cents` may not exceed the part of `total_of_payments_cents` not yet covered by `rent_applied_cents`, plus whatever remains of `late_fee_balance_cents` and `reinstatement_fee_balance_cents` (`ERR_PAYMENT_EXCEEDS_BALANCE`).

    Design: Difficulty/priority_pair_validation_conflict/defaulted_state_409_outranks_overpayment_fiscal_422
    """
    scenario, second = _one_defaulted_and_one_current_agreement(world)

    response = scenario.api.post_renewal_payment(
        second["id"],
        factories.payment_payload(ABSURD_TENDER_CENTS, PaymentMethod.CASH),
        SALES,
    )
    failure(response, ErrorId.PAYMENT_EXCEEDS_BALANCE)

    assert world.payments(second["id"]) == [], (
        "a rejected payment must leave no row behind"
    )
    assert_fields(
        world.get_agreement(second["id"]),
        payment_status=PaymentStatus.CURRENT,
        possession_status=PossessionStatus.DELIVERED,
        periods_paid=0,
        rent_applied_cents=0,
    )


def _minnesota_delinquent_renter_without_home_visit_consent(world):
    """A Duluth renter, six days past a five-day grace period, who declined home visits."""
    scenario = build_mn_floor(
        world,
        DULUTH_MAIN,
        service_bay_capacity=2,
        serials=("SN-MN-0001",),
        customer_payload=factories.duluth_ivar_payload(),
        references=factories.duluth_ivar_references(),
    )
    deliver_on(sign_on(scenario, term_type=TermType.WEEKLY, renewal_count=24))
    world.set_clock(DAY_14_2200)
    world.day_close(scenario.store_id)
    return scenario


def test_quiet_hours_are_reported_before_an_unusable_contact_channel(world):
    """A ten-at-night house call is refused for the hour, not for the missing consent.

    PRD: **Quiet hours** come first: contact is permitted only when the clock's UTC hour is at or after the jurisdiction's `quiet_hours_end_utc_hour` and strictly before its `quiet_hours_start_utc_hour`, and a call inside the prohibited span is refused with `ERR_QUIET_HOURS_VIOLATION`.

    Design: Difficulty/priority_pair_validation_conflict/quiet_hours_safety_outranks_channel_availability_referential
    """
    scenario = _minnesota_delinquent_renter_without_home_visit_consent(world)

    delinquent = scenario.read_agreement()
    assert_fields(
        delinquent,
        payment_status=PaymentStatus.DELINQUENT,
        collections_stage=CollectionsStage.ADVERSE,
        late_fee_balance_cents=MN_LATE_FEE_CENTS,
        reinstatement_fee_balance_cents=0,
        collection_contact_count_7d=0,
    )
    assert scenario.read_customer()["in_person_contact_consent"] is False

    response = scenario.api.log_collection_contact(
        scenario.agreement_id,
        factories.collection_contact_payload(Channel.IN_PERSON, Outcome.NO_ANSWER),
        COLLECTOR,
    )
    failure(response, ErrorId.QUIET_HOURS_VIOLATION)

    assert world.contacts(scenario.agreement_id) == [], (
        "a refused contact must not be appended"
    )
    assert scenario.read_agreement()["collection_contact_count_7d"] == 0

    windows = world.windows(scenario.agreement_id)
    assert len(windows) == 1, f"expected exactly one window, got {len(windows)}"
    assert_fields(
        windows[0],
        status=WindowStatus.OPEN,
        window_days=7,
        reinstatement_fee_cents=0,
        expires_at="2026-08-21T22:00:00Z",
    )


def test_once_the_hour_is_lawful_the_channel_gate_is_what_refuses_the_call(world):
    """Inside business hours the same house call fails on the consent the renter withheld.

    PRD: **Channel usability** comes third: `PHONE` and `SMS` require a non-empty `phone` on the customer, `EMAIL` requires a non-empty `email`, and `IN_PERSON` requires `in_person_contact_consent` to be true, failing otherwise with `ERR_CONTACT_CHANNEL_UNAVAILABLE`.

    Design: Difficulty/priority_pair_validation_conflict/quiet_hours_safety_outranks_channel_availability_referential
    """
    scenario = _minnesota_delinquent_renter_without_home_visit_consent(world)
    failure(
        scenario.api.log_collection_contact(
            scenario.agreement_id,
            factories.collection_contact_payload(Channel.IN_PERSON, Outcome.NO_ANSWER),
            COLLECTOR,
        ),
        ErrorId.QUIET_HOURS_VIOLATION,
    )

    world.set_clock(DAY_15_1500)
    response = scenario.api.log_collection_contact(
        scenario.agreement_id,
        factories.collection_contact_payload(Channel.IN_PERSON, Outcome.NO_ANSWER),
        COLLECTOR,
    )
    failure(response, ErrorId.CONTACT_CHANNEL_UNAVAILABLE)

    assert world.contacts(scenario.agreement_id) == [], (
        "neither refusal may append a contact row"
    )
    assert_fields(
        scenario.read_agreement(),
        collection_contact_count_7d=0,
        payment_status=PaymentStatus.DELINQUENT,
        collections_stage=CollectionsStage.ADVERSE,
        late_fee_balance_cents=MN_LATE_FEE_CENTS,
    )
