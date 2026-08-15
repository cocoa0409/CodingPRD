"""Shipment state machine: invalid transitions, terminal lockdown, idempotent
accept, the reconditioning cycle, and cancellation quota release."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_shipment,
    book_dispatch_deliver,
    book_shipment,
    dispatch_and_deliver,
    get_agreement,
    get_agreement_version,
    get_commitment,
    get_shipment,
    setup_booking_ready_chain,
    setup_dispatch_ready_chain,
    validate_error,
    validate_paginated,
    validate_success,
)

BROKER = TEST_USERS["broker_ops_headers"]


def test_accept_from_booked_returns_invalid_state(api):
    """PRD §3.5: "Accepting a load is declared only from `DELIVERED` (else
    `ERR_INVALID_STATE`)"
    PRD §3.4: "Its destination measurements (`destination_moisture_pct`,
    `destination_arsenic_ppm`) and all acceptance-time financial fields —
    `price_at_acceptance_cents_per_ton`, `moisture_deduction_pct`,
    `net_billable_tons`, `final_gross_revenue_cents`,
    `final_generator_share_cents`, `final_broker_share_cents`,
    `generator_net_payout_cents` — remain null until delivery and acceptance"
    PRD §3.8: "**Credit entries** are created only by the acceptance and
    voiding cascades — never directly"

    Design: Corner/state_machines/accept_from_booked_returns_invalid_state
    """
    chain = setup_booking_ready_chain(committed_agreement_tons=100,
                                      committed_commitment_tons=100)
    shipment = book_shipment(chain, gross_tons=10)

    resp = api.accept_shipment(shipment["id"], chain["offtaker_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    shipment_after = get_shipment(shipment["id"])
    assert shipment_after["status"] == "BOOKED"
    assert shipment_after["final_gross_revenue_cents"] is None, (
        "no settlement may run for a rejected accept"
    )
    entries, meta = validate_paginated(
        api.list_shipment_credit_entries(shipment["id"], BROKER)
    )
    assert meta["total_count"] == 0 and entries == [], (
        "no credit entry may be posted without acceptance"
    )


def test_dispatch_from_cancelled_returns_invalid_state(api):
    """PRD §3.6: "A Generator may cancel a load still in `BOOKED` status, moving
    it to terminal `CANCELLED`"
    PRD §2.10: "Eighth, state eligibility: the requested transition must be
    declared from the target resource's current state — attempting any action
    from a state where it is not defined, including any terminal state, yields
    `ERR_INVALID_STATE`"

    Design: Corner/state_machines/dispatch_from_cancelled_terminal_lockdown
    """
    chain = setup_dispatch_ready_chain(committed_agreement_tons=100,
                                       committed_commitment_tons=100)
    shipment = book_shipment(chain, gross_tons=10)
    cancelled = validate_success(
        api.cancel_shipment(shipment["id"], chain["generator_headers"]), 200
    )
    assert cancelled["status"] == "CANCELLED"

    resp = api.dispatch_shipment(shipment["id"], chain["generator_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    shipment_after = get_shipment(shipment["id"])
    assert shipment_after["status"] == "CANCELLED"


def test_second_accept_rejected_and_credit_posted_once(api):
    """PRD §3.5: "Accepting a load is declared only from `DELIVERED` (else
    `ERR_INVALID_STATE`)"
    PRD §3.5: "A sustainability credit entry is posted with `entry_type`
    `ACCRUAL`, crediting the agreement's generator, referencing this shipment,
    posted to the current logical month as its `period`, with `tons_credited`
    equal to `net_billable_tons` and `credits` equal to those net billable tons
    multiplied by 1.0 credit per ton, rounded half-up to two decimal places."

    Design: Corner/state_machines/second_accept_rejected_idempotency_attempt
    """
    chain = setup_dispatch_ready_chain(committed_agreement_tons=100,
                                       committed_commitment_tons=100)
    delivered = book_dispatch_deliver(chain, gross_tons=10)
    accepted = accept_shipment(chain, delivered["id"])
    assert accepted["status"] == "ACCEPTED"

    resp = api.accept_shipment(delivered["id"], chain["offtaker_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    entries, meta = validate_paginated(
        api.list_shipment_credit_entries(delivered["id"], BROKER)
    )
    assert meta["total_count"] == 1, "the ACCRUAL entry must be posted exactly once"
    assert entries[0]["entry_type"] == "ACCRUAL"
    assert entries[0]["credits"] == pytest.approx(10.0)


def test_reconditioning_cycle_restores_delivered_with_fresh_measurements(api):
    """PRD §3.6: "Reconditioning moves it from `REJECTED` to `RECONDITIONING`;
    redelivery then returns it from `RECONDITIONING` to `DELIVERED` with
    freshly supplied `destination_moisture_pct` and `destination_arsenic_ppm`
    measurements stamped over the old ones. The loop is genuinely cyclic — a
    redelivered load may be accepted or rejected again, and each rejection adds
    the full `gross_tons` to `cumulative_rejected_tons` once more."

    Design: Difficulty/non_linear_state_machine/shipment_reconditioning_cycle
    """
    chain = setup_dispatch_ready_chain(committed_agreement_tons=500,
                                       committed_commitment_tons=500)
    shipment = book_shipment(chain, gross_tons=20)
    dispatch_and_deliver(chain, shipment["id"], destination_moisture_pct=13.0)

    rejected = validate_success(
        api.reject_shipment(shipment["id"], {"reason": "too wet"}, chain["offtaker_headers"]),
        200,
    )
    assert rejected["status"] == "REJECTED"

    reconditioning = validate_success(
        api.recondition_shipment(shipment["id"], chain["generator_headers"]), 200
    )
    assert reconditioning["status"] == "RECONDITIONING"

    redelivered = validate_success(
        api.redeliver_shipment(
            shipment["id"],
            {"destination_moisture_pct": 9.0, "destination_arsenic_ppm": 3.0},
            chain["generator_headers"],
        ),
        200,
    )
    assert redelivered["status"] == "DELIVERED", (
        "redelivery returns the load to DELIVERED so it can be accepted again"
    )
    assert redelivered["destination_moisture_pct"] == pytest.approx(9.0), (
        "redelivery stamps fresh destination measurements over the old ones"
    )


def test_reconditioned_load_acceptance_settles_and_updates_counters(api):
    """PRD §3.6: "The loop is genuinely cyclic — a redelivered load may be
    accepted or rejected again, and each rejection adds the full `gross_tons`
    to `cumulative_rejected_tons` once more."
    PRD §3.5: "Second, `net_billable_tons` is the shipment's `gross_tons`
    multiplied by one minus that deduction percentage divided by one hundred,
    rounded half-up to three decimal places." and "Fourth,
    `final_gross_revenue_cents` is the rounded `net_billable_tons` — never the
    unrounded tonnage — multiplied by the acceptance price, rounded half-up to
    whole cents."
    PRD §3.5: "The agreement's `delivered_month_to_date_tons` increases by
    `net_billable_tons` (after rollover), its `fulfillment_status` is
    recomputed, and its `version` advances by one"

    Design: Difficulty/non_linear_state_machine/shipment_reconditioning_cycle
    """
    chain = setup_dispatch_ready_chain(committed_agreement_tons=500,
                                       committed_commitment_tons=500)
    shipment = book_shipment(chain, gross_tons=20)
    dispatch_and_deliver(chain, shipment["id"], destination_moisture_pct=13.0)
    validate_success(
        api.reject_shipment(shipment["id"], {"reason": "too wet"}, chain["offtaker_headers"]),
        200,
    )
    validate_success(api.recondition_shipment(shipment["id"], chain["generator_headers"]), 200)
    validate_success(
        api.redeliver_shipment(
            shipment["id"],
            {"destination_moisture_pct": 9.0, "destination_arsenic_ppm": 3.0},
            chain["generator_headers"],
        ),
        200,
    )

    accepted = accept_shipment(chain, shipment["id"])
    assert accepted["status"] == "ACCEPTED"
    # Redelivered at 9.0% against max_moisture_pct 10.0: no deduction.
    assert accepted["net_billable_tons"] == pytest.approx(20.0)
    assert accepted["final_gross_revenue_cents"] == 6000  # 20.0 t x 300 cents

    commitment_after = get_commitment(chain["commitment"]["id"])
    assert commitment_after["cumulative_rejected_tons"] == pytest.approx(20), (
        "the single rejection added the full 20 t gross"
    )
    assert commitment_after["status"] == "ACTIVE", (
        "20.0 t rejected against a 500 t commitment (tolerance 100.0) must not suspend"
    )

    agreement_after = get_agreement(chain["agreement"]["id"])
    assert agreement_after["delivered_month_to_date_tons"] == pytest.approx(20.0)


def test_cancel_releases_booked_tonnage_and_bumps_version(api):
    """PRD §3.6: "A Generator may cancel a load still in `BOOKED` status, moving
    it to terminal `CANCELLED`; the agreement's `booked_month_to_date_tons`
    decreases by the shipment's `gross_tons` after rollover, never dropping
    below zero, and the agreement's `version` advances by one."

    Design: Corner/state_machines/cancel_releases_booked_tonnage_and_bumps_version
    """
    chain = setup_booking_ready_chain(committed_agreement_tons=100,
                                      committed_commitment_tons=100)
    version_after_activation = get_agreement_version(chain["agreement"]["id"])
    shipment = book_shipment(chain, gross_tons=30)
    # Booking bumped the version once.
    assert get_agreement_version(chain["agreement"]["id"]) == version_after_activation + 1

    cancelled = validate_success(
        api.cancel_shipment(shipment["id"], chain["generator_headers"]), 200
    )
    assert cancelled["status"] == "CANCELLED"

    agreement_after = get_agreement(chain["agreement"]["id"])
    assert agreement_after["booked_month_to_date_tons"] == pytest.approx(
        0
    ), "cancellation must release the booked tonnage back to 0"
    assert (
        agreement_after["version"] == version_after_activation + 2
    ), "cancel advances the agreement version by exactly one more"
