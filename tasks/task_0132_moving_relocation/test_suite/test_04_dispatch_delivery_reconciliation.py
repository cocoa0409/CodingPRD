"""Departure, delivery, and final-charge reconciliation: cross-entity bubble-up,
binding vs non-binding reconciliation, the round-per-component-then-sum order, the
deposit gate on departure, and the balance/deposit payment rules.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_deposit_paid_job, setup_scheduled_dispatch, setup_en_route_dispatch,
    setup_delivered_job, setup_booked_job, schedule_dispatch,
    make_customer_headers, TEST_USERS,
    register_customer, create_job,
    ITEMS_120CF, ITEMS_370CF, PACKING_LINES_38300,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_non_binding_final_charge_rounds_per_component_then_sums(api):
    """PRD §3.7: "For a `NON_BINDING` estimate the weight-driven components are
    recomputed at the measured `actual_weight_lbs` — the linehaul (or labor) plus
    the fuel surcharge are re-rated to the actual weight — while the non-weight
    components carried on the accepted estimate, namely its `packing_cents`,
    `valuation_premium_cents`, and `accessorial_cents`, are carried over
    unchanged."
    PRD §2.8: "each charge component is independently rounded half up to integer
    cents first, and only then are the components summed."

    A NON_BINDING long-haul job re-rated at actual 3100lb: linehaul 651000 and fuel
    55335 rounded independently, summed with carried packing/valuation/accessorial
    -> final_charge_cents 783067; job delivered.

    Design: Difficulty/combinatorial_formula/final_charge_round_per_component_then_sum
    """
    cust_id, job, estimate, dispatch = setup_en_route_dispatch(
        service_type="LONG_HAUL", items=ITEMS_370CF,
        binding_type="NON_BINDING", valuation_coverage="FULL_VALUE",
        packing_lines=PACKING_LINES_38300, crate_count=3, deposit_cents=100000,
        declared_value_cents=1600000, deductible_cents=50000,
        job_overrides={"origin_zip": "90001", "destination_zip": "10001",
                       "distance_miles": 900, "stair_flights": 2, "long_carry_units": 1})

    validate_success(api.complete_dispatch(dispatch["id"], {"actual_weight_lbs": 3100}, DISPATCHER), 200)
    job_after = get_success_data(api.get_move_job(job["id"], make_customer_headers(cust_id)))
    assert job_after["final_charge_cents"] == 783067
    assert job_after["job_status"] == "DELIVERED"


def test_complete_dispatch_delivers_job(api):
    """PRD §2.9: "completing it bubbles the job to `DELIVERED` and runs final
    reconciliation."
    PRD §3.7: "Completion advances the dispatch `EN_ROUTE → COMPLETED`, bubbles the
    job `IN_TRANSIT → DELIVERED`, and runs the final-charge reconciliation that
    writes the job's `final_charge_cents`."

    Second assertion on the round-per-component instance: completion advances the
    dispatch to COMPLETED while delivering the job.

    Design: Difficulty/combinatorial_formula/final_charge_round_per_component_then_sum
    """
    cust_id, job, estimate, dispatch = setup_en_route_dispatch(
        service_type="LONG_HAUL", items=ITEMS_370CF,
        binding_type="NON_BINDING", valuation_coverage="FULL_VALUE",
        packing_lines=PACKING_LINES_38300, crate_count=3, deposit_cents=100000,
        declared_value_cents=1600000, deductible_cents=50000,
        job_overrides={"origin_zip": "90001", "destination_zip": "10001",
                       "distance_miles": 900, "stair_flights": 2, "long_carry_units": 1})
    completed = validate_success(
        api.complete_dispatch(dispatch["id"], {"actual_weight_lbs": 3100}, DISPATCHER), 200)
    assert completed["status"] == "COMPLETED"


def test_complete_dispatch_recomputes_balance_due(api):
    """PRD §3.7: "After reconciliation the job's running gross is set to the
    reconciled `final_charge_cents` plus any storage or packing charges already
    booked into the gross baseline, and `balance_due_cents` is recomputed."
    PRD §3.7: "For a `BINDING` estimate the locked price holds and
    `final_charge_cents` equals the accepted estimate's `estimate_total_cents`
    exactly, with the actual weight ignored."

    Depth>=2 cascade from dispatch complete: BINDING final 666864, deposit 100000
    -> balance_due 566864, job DELIVERED.

    Design: Difficulty/transitive_cascade/complete_dispatch_delivers_job_and_recomputes_balance
    """
    cust_id, job, estimate, dispatch = setup_en_route_dispatch(
        service_type="LONG_HAUL", items=ITEMS_370CF,
        binding_type="BINDING", valuation_coverage="FULL_VALUE",
        packing_lines=PACKING_LINES_38300, crate_count=3, deposit_cents=100000,
        declared_value_cents=1600000, deductible_cents=50000,
        job_overrides={"origin_zip": "90001", "destination_zip": "10001",
                       "distance_miles": 900, "stair_flights": 2, "long_carry_units": 1})

    validate_success(api.complete_dispatch(dispatch["id"], {"actual_weight_lbs": 3100}, DISPATCHER), 200)
    job_after = get_success_data(api.get_move_job(job["id"], make_customer_headers(cust_id)))
    assert job_after["job_status"] == "DELIVERED"
    assert job_after["final_charge_cents"] == 666864
    assert job_after["balance_due_cents"] == 566864


def test_binding_final_charge_equals_estimate_total(api):
    """PRD §3.7: "For a `BINDING` estimate the locked price holds and
    `final_charge_cents` equals the accepted estimate's `estimate_total_cents`
    exactly, with the actual weight ignored."

    Second assertion on the dispatch-complete cascade instance: a BINDING job
    completed at actual 3100lb still reconciles to the locked 666864.

    Design: Difficulty/transitive_cascade/complete_dispatch_delivers_job_and_recomputes_balance
    """
    cust_id, job, estimate, dispatch = setup_en_route_dispatch(
        service_type="LONG_HAUL", items=ITEMS_370CF,
        binding_type="BINDING", valuation_coverage="FULL_VALUE",
        packing_lines=PACKING_LINES_38300, crate_count=3, deposit_cents=100000,
        declared_value_cents=1600000, deductible_cents=50000,
        job_overrides={"origin_zip": "90001", "destination_zip": "10001",
                       "distance_miles": 900, "stair_flights": 2, "long_carry_units": 1})
    validate_success(api.complete_dispatch(dispatch["id"], {"actual_weight_lbs": 3100}, DISPATCHER), 200)
    job_after = get_success_data(api.get_move_job(job["id"], make_customer_headers(cust_id)))
    assert job_after["final_charge_cents"] == 666864


def test_binding_final_charge_ignores_actual_weight(api):
    """PRD §3.7: "For a `BINDING` estimate the locked price holds and
    `final_charge_cents` equals the accepted estimate's `estimate_total_cents`
    exactly, with the actual weight ignored — unless both an addendum is present and
    the measured `actual_cubic_feet` exceeds the surveyed `total_cubic_feet` by more
    than a ten-percent tolerance."

    A BINDING job completed at actual 3100lb (above the estimate weight) with no
    addendum still has final_charge_cents 666864.

    Design: Corner/calculations/binding_final_charge_ignores_actual_weight
    """
    cust_id, job, estimate, dispatch = setup_en_route_dispatch(
        service_type="LONG_HAUL", items=ITEMS_370CF,
        binding_type="BINDING", valuation_coverage="FULL_VALUE",
        packing_lines=PACKING_LINES_38300, crate_count=3, deposit_cents=100000,
        declared_value_cents=1600000, deductible_cents=50000,
        job_overrides={"origin_zip": "90001", "destination_zip": "10001",
                       "distance_miles": 900, "stair_flights": 2, "long_carry_units": 1})
    validate_success(api.complete_dispatch(dispatch["id"], {"actual_weight_lbs": 3100}, DISPATCHER), 200)
    job_after = get_success_data(api.get_move_job(job["id"], make_customer_headers(cust_id)))
    assert job_after["final_charge_cents"] == 666864


def test_depart_blocked_until_deposit_paid(api):
    """PRD §3.7: "Departure requires the job to be `BOOKED` and its `payment_status`
    to be either `DEPOSIT_PAID` or `PAID_IN_FULL`; if the money dimension has not
    reached at least a deposit, departure is blocked with
    `ERR_DEPENDENT_STATE_BLOCK`."

    A SCHEDULED dispatch on a BOOKED but still-UNPAID job cannot depart.

    Design: Difficulty/cross_entity_state_dependency/depart_blocked_until_deposit_paid
    """
    cust_id, job, survey, estimate = setup_booked_job(service_type="LOCAL", items=ITEMS_120CF)
    # Schedule a dispatch without paying any deposit.
    dispatch = schedule_dispatch(job["id"])
    res = api.depart_dispatch(dispatch["id"], DISPATCHER)
    validate_error(res, "ERR_DEPENDENT_STATE_BLOCK", 409)


def test_depart_succeeds_after_deposit_paid(api):
    """PRD §3.7: "A valid departure advances the dispatch `SCHEDULED → EN_ROUTE` and
    bubbles the job from `BOOKED` to `IN_TRANSIT`."

    Second assertion on the depart deposit-gate instance (the positive path): once
    a deposit has been paid, departure advances the dispatch to EN_ROUTE and bubbles
    the job to IN_TRANSIT.

    Design: Difficulty/cross_entity_state_dependency/depart_blocked_until_deposit_paid
    """
    cust_id, job, estimate, dispatch = setup_scheduled_dispatch(
        service_type="LOCAL", items=ITEMS_120CF)
    departed = validate_success(api.depart_dispatch(dispatch["id"], DISPATCHER), 200)
    assert departed["status"] == "EN_ROUTE"
    job_after = get_success_data(api.get_move_job(job["id"], make_customer_headers(cust_id)))
    assert job_after["job_status"] == "IN_TRANSIT"


def test_complete_scheduled_dispatch_without_depart_rejected(api):
    """PRD §3.7: "The `Dispatcher` completes an `EN_ROUTE` dispatch, supplying the
    measured `actual_weight_lbs` and, where relevant to a binding reconciliation,
    an optional `actual_cubic_feet` and an optional `addendum_present` flag."
    PRD §3.12: "then whether the requested state transition is defined from the
    current state (`ERR_INVALID_STATE`)."

    Completing a SCHEDULED (never departed) dispatch returns ERR_INVALID_STATE.

    Design: Corner/state_machines/complete_scheduled_dispatch_without_depart_returns_invalid_state
    """
    cust_id, job, estimate, dispatch = setup_scheduled_dispatch(
        service_type="LOCAL", items=ITEMS_120CF)
    res = api.complete_dispatch(dispatch["id"], {"actual_weight_lbs": 840}, DISPATCHER)
    validate_error(res, "ERR_INVALID_STATE", 409)


def test_balance_payment_amount_mismatch_rejected(api):
    """PRD §3.5: "A balance payment may only be taken once the job has been
    `DELIVERED`, and its `amount_cents` must equal the job's current
    `balance_due_cents` exactly — no partial and no overpayment — or it is rejected
    with `ERR_PAYMENT_AMOUNT_MISMATCH`."

    A DELIVERED job with balance_due 566864 rejects a BALANCE payment of 500000.

    Design: Corner/validations/balance_payment_amount_mismatch_returns_422
    """
    cust_id, job, estimate, dispatch = setup_delivered_job(
        service_type="LONG_HAUL", items=ITEMS_370CF,
        binding_type="BINDING", valuation_coverage="FULL_VALUE",
        packing_lines=PACKING_LINES_38300, crate_count=3, deposit_cents=100000,
        actual_weight_lbs=3100, declared_value_cents=1600000, deductible_cents=50000,
        job_overrides={"origin_zip": "90001", "destination_zip": "10001",
                       "distance_miles": 900, "stair_flights": 2, "long_carry_units": 1})
    assert job["balance_due_cents"] == 566864
    res = api.create_payment(job["id"], {"kind": "BALANCE", "amount_cents": 500000},
                             make_customer_headers(cust_id))
    validate_error(res, "ERR_PAYMENT_AMOUNT_MISMATCH", 422)


def test_deposit_before_booked_rejected(api):
    """PRD §3.5: "A deposit may only be taken once the job is `BOOKED`; attempting a
    deposit before the job is booked is rejected with `ERR_DEPOSIT_BEFORE_BOOKED`."

    A DEPOSIT payment on a QUOTING job returns ERR_DEPOSIT_BEFORE_BOOKED.

    Design: Corner/validations/deposit_before_booked_returns_409
    """
    cust_id = register_customer()["id"]
    job = create_job(cust_id, "LOCAL")
    res = api.create_payment(job["id"], {"kind": "DEPOSIT", "amount_cents": 10000},
                             make_customer_headers(cust_id))
    validate_error(res, "ERR_DEPOSIT_BEFORE_BOOKED", 409)
