"""Settlement lifecycle: generate guards, finalize gates, pay floor, void,
and the rebate-ledger compensating invariant."""
import pytest

from test_helpers import (
    ApiErrorId,
    complete_visit,
    create_container,
    create_customer,
    create_manifest,
    create_truck,
    dispatch_manifest,
    draw_and_grade_sample,
    generate_settlement,
    get_success_data,
    make_driver_headers,
    manifest_visits,
    publish_quote,
    set_clock,
    setup_completed_visit,
    setup_provisional_settlement,
    start_visit,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import BILL, DISP, FOPS, create_active_customer, create_contract


# ---------------------------------------------------------------------------
# Corner: generate with period not closed
# ---------------------------------------------------------------------------

def test_generate_period_not_closed_rejected(api, billing_headers):
    """PRD §3.7: "Generation requires that the period is closed — the logical
    clock date is on or after `period_end`, otherwise `ERR_PERIOD_NOT_CLOSED`"

    Design: Corner/validations/c_generate_period_not_closed_rejected
    """
    set_clock("2026-08-02T00:00:00Z")
    customer, _ = create_active_customer(name="Period House")
    set_clock("2026-08-15T00:00:00Z")
    resp = api.generate_settlement(
        {
            "customer_id": customer["id"],
            "period_start": "2026-08-01",
            "period_end": "2026-09-01",
        },
        billing_headers,
    )
    validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_CLOSED, expected_status=422)


def test_default_clock_period_not_closed_rejected(api, billing_headers):
    """PRD §2.4: "Before any such call, the clock's startup default is exactly
    2026-08-01T00:00:00Z; the server must not fall back to wall-clock time at
    any point."
    PRD §3.7: "Generation requires that the period is closed — the logical
    clock date is on or after `period_end`, otherwise `ERR_PERIOD_NOT_CLOSED`"

    Design: Corner/cross_cutting_layers/c_default_clock_period_not_closed_rejected
    """
    # No clock-set call at all: startup default 2026-08-01 applies.
    customer = create_customer(name="Clock House", address="48 Fry Way")
    create_contract(customer["id"], activate=True)
    resp = api.generate_settlement(
        {
            "customer_id": customer["id"],
            "period_start": "2026-08-01",
            "period_end": "2026-09-01",
        },
        billing_headers,
    )
    validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_CLOSED, expected_status=422)


# ---------------------------------------------------------------------------
# Corner: duplicate period rejected; regenerate after void succeeds
# ---------------------------------------------------------------------------

def test_duplicate_period_rejected(api, billing_headers):
    """PRD §3.7: "no other non-`VOID` settlement of the same customer overlaps
    the requested period, otherwise `ERR_DUPLICATE_PERIOD`"

    Design: Corner/validations/c_duplicate_period_rejected
    """
    ctx = setup_provisional_settlement(
        name="Dup House", truck_plate="T-C8",
        quote_weeks=(("2026-08-03", 100),),
    )
    resp = api.generate_settlement(
        {
            "customer_id": ctx["customer"]["id"],
            "period_start": "2026-08-01",
            "period_end": "2026-08-15",
        },
        billing_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PERIOD, expected_status=409)
    # Void the first settlement; the period becomes free again.
    get_success_data(
        api.void_settlement(ctx["settlement"]["id"], {"reason": "wrong cutoff"}, BILL)
    )
    regenerated = get_success_data(
        api.generate_settlement(
            {
                "customer_id": ctx["customer"]["id"],
                "period_start": "2026-08-01",
                "period_end": "2026-08-15",
            },
            billing_headers,
        )
    )
    assert regenerated["status"] == "PROVISIONAL"


# ---------------------------------------------------------------------------
# Corner: finalize gates — pending grade, missing in-period quote
# ---------------------------------------------------------------------------

def test_finalize_ungraded_sample_rejected(api, billing_headers):
    """PRD §3.7: "Finalization is gated by four preconditions: the period must
    be closed (`ERR_PERIOD_NOT_CLOSED`); every included pickup must have at
    least one sample in `GRADED` status (`ERR_GRADE_PENDING`); at least one
    `PUBLISHED` quote must exist with a `week_start` inside the period for the
    contract's `index_code` (`ERR_QUOTE_NOT_PUBLISHED`); and the customer's
    active-era contract used for pricing must be in `ACTIVE`, `AT_RISK`, or
    `RENEWAL_OFFERED` — a contract in `DRAFT` or any terminal state fails with
    `ERR_CONTRACT_NOT_ACTIVE`."

    Design: Corner/validations/c_finalize_ungraded_sample_rejected
    """
    ctx = setup_completed_visit(name="Grade House", truck_plate="T-C9")
    # Sample drawn and submitted but never graded.
    sample = get_success_data(
        api.create_sample(ctx["visit"]["id"], make_driver_headers("drv-1"))
    )
    get_success_data(api.submit_sample(sample["id"], make_driver_headers("drv-1")))
    publish_quote(week_start="2026-08-03", price=100)
    set_clock("2026-08-15T00:00:00Z")
    settlement = generate_settlement(ctx["customer"]["id"])
    resp = api.finalize_settlement(settlement["id"], billing_headers)
    validate_error(resp, ApiErrorId.ERR_GRADE_PENDING, expected_status=422)
    after = get_success_data(api.get_settlement(settlement["id"], billing_headers))
    assert after["status"] == "PROVISIONAL"


def test_finalize_without_in_period_quote_rejected(api, billing_headers):
    """PRD §3.7: "at least one `PUBLISHED` quote must exist with a `week_start`
    inside the period for the contract's `index_code`
    (`ERR_QUOTE_NOT_PUBLISHED`)"

    Only an out-of-period quote (w2026-07-27) exists; provisional pricing of
    the 2026-08-05 pickup still succeeds on it, but finalize fails.

    Design: Corner/validations/c_finalize_without_in_period_quote_rejected
    """
    ctx = setup_provisional_settlement(
        name="Quote House", truck_plate="T-C10",
        quote_weeks=(("2026-07-27", 100),),
        grade=(10.0, 1.0),
    )
    resp = api.finalize_settlement(ctx["settlement"]["id"], billing_headers)
    validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_PUBLISHED, expected_status=422)


# ---------------------------------------------------------------------------
# Corner: pay below minimum
# ---------------------------------------------------------------------------

def test_pay_below_minimum_rejected(api, billing_headers):
    """PRD §3.7: "Disbursement moves the settlement `FINALIZED` → `PAID` and
    enforces the payout floor: a settlement whose `final_total_cents` is below
    100 cents is rejected with `ERR_PAYOUT_BELOW_MINIMUM`."

    Final line: net 1.00 x rate 50 x grade factor 1.00 (lab 1.0/1.0 -> A) = 50.

    Design: Corner/validations/c_pay_below_minimum_rejected
    """
    ctx = setup_provisional_settlement(
        name="Tiny House", truck_plate="T-C13",
        pump_gallons=1.00, field_moisture_pct=0.0,
        quote_weeks=(("2026-08-03", 50),),
        grade=(1.0, 1.0),
    )
    finalized = get_success_data(
        api.finalize_settlement(ctx["settlement"]["id"], billing_headers)
    )
    assert finalized["final_total_cents"] == 50
    resp = api.pay_settlement(ctx["settlement"]["id"], billing_headers)
    validate_error(resp, ApiErrorId.ERR_PAYOUT_BELOW_MINIMUM, expected_status=422)
    after = get_success_data(api.get_settlement(ctx["settlement"]["id"], billing_headers))
    assert after["status"] == "FINALIZED"


# ---------------------------------------------------------------------------
# Difficulty: finalize requires the pricing contract in an active-era state
# ---------------------------------------------------------------------------

def _terminated_contract_settlement_setup(api):
    """Pickup completed 2026-07-05 with GRADED sample (lab 10.0/1.0 -> B);
    quotes w06-29 and w07-06 @100 published; contract terminated VOLUNTARY at
    clock 2026-08-20; settlement over [2026-07-01, 2026-08-01) generated after
    termination."""
    set_clock("2026-07-01T09:00:00Z")
    customer = create_customer(name="Term House", address="15 Fry Way")
    contract = create_contract(customer["id"], activate=True)
    container = create_container(customer["id"], capacity=300, fill_rate=100,
                                 lock_code="LKTE")
    truck = create_truck(plate="T-12", tank_capacity=500)
    manifest = create_manifest(truck["id"], [container["id"]],
                               service_date="2026-07-05")
    dispatch_manifest(manifest["id"], start_level=0)
    visit = manifest_visits(manifest["id"])[0]
    set_clock("2026-07-05T08:00:00Z")
    start_visit(visit["id"])
    complete_visit(visit["id"], pump_gallons=100.00, field_moisture_pct=5.0)
    draw_and_grade_sample(visit["id"], lab_moisture_pct=10.0, lab_impurity_pct=1.0)
    publish_quote(week_start="2026-06-29", price=100)
    publish_quote(week_start="2026-07-06", price=100)
    set_clock("2026-08-20T00:00:00Z")
    get_success_data(
        api.terminate_contract(contract["id"], {"reason": "VOLUNTARY"}, FOPS)
    )
    settlement = generate_settlement(
        customer["id"], period_start="2026-07-01", period_end="2026-08-01"
    )
    return customer, contract, settlement


def test_finalize_with_terminated_contract_rejected(api, billing_headers):
    """PRD §3.7: "the customer's active-era contract used for pricing must be
    in `ACTIVE`, `AT_RISK`, or `RENEWAL_OFFERED` — a contract in `DRAFT` or any
    terminal state fails with `ERR_CONTRACT_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/settlement_finalize_requires_contract_active
    """
    _, _, settlement = _terminated_contract_settlement_setup(api)
    resp = api.finalize_settlement(settlement["id"], billing_headers)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE, expected_status=409)


def test_finalize_rejection_leaves_settlement_provisional(api, billing_headers):
    """PRD §3.7: "Finalization moves the settlement `PROVISIONAL` → `FINALIZED`
    and recomputes every line under the final variant"
    PRD §3.7: "On success, `final_total_cents` is written and added to the
    customer's `rebate_balance_cents` per the ledger rule of §2.10."

    A rejected finalize performs no state move and posts nothing to the ledger.

    Design: Difficulty/cross_entity_state_dependency/settlement_finalize_requires_contract_active
    """
    _, _, settlement = _terminated_contract_settlement_setup(api)
    api.finalize_settlement(settlement["id"], billing_headers)
    after = get_success_data(api.get_settlement(settlement["id"], billing_headers))
    assert after["status"] == "PROVISIONAL"
    customer = get_success_data(api.get_customer(settlement["customer_id"], BILL))
    assert customer["rebate_balance_cents"] == 0, (
        "a rejected finalize must not post to the rebate ledger"
    )


# ---------------------------------------------------------------------------
# Corner: terminate with open settlements
# ---------------------------------------------------------------------------

def test_terminate_with_open_settlement_rejected(api, field_ops_headers):
    """PRD §3.2: "Open billing: termination while any settlement of the
    customer is in `PROVISIONAL` or `FINALIZED` status is rejected with
    `ERR_OPEN_SETTLEMENTS`."

    Design: Corner/validations/c_terminate_with_open_settlement_rejected
    """
    set_clock("2026-07-01T09:00:00Z")
    customer = create_customer(name="Open House", address="34 Fry Way")
    contract = create_contract(customer["id"], activate=True)
    container = create_container(customer["id"], capacity=300, fill_rate=100,
                                 lock_code="LKO")
    truck = create_truck(plate="T-C12", tank_capacity=500)
    manifest = create_manifest(truck["id"], [container["id"]],
                               service_date="2026-07-05")
    dispatch_manifest(manifest["id"], start_level=0)
    visit = manifest_visits(manifest["id"])[0]
    set_clock("2026-07-05T08:00:00Z")
    start_visit(visit["id"])
    complete_visit(visit["id"], pump_gallons=100.00, field_moisture_pct=5.0)
    publish_quote(week_start="2026-06-29", price=100)
    set_clock("2026-07-09T00:00:00Z")
    settlement = generate_settlement(
        customer["id"], period_start="2026-07-01", period_end="2026-07-08"
    )
    set_clock("2026-08-20T00:00:00Z")  # past the 14-day cooling-off
    resp = api.terminate_contract(contract["id"], {"reason": "VOLUNTARY"},
                                  field_ops_headers)
    validate_error(resp, ApiErrorId.ERR_OPEN_SETTLEMENTS, expected_status=422)
    get_success_data(
        api.void_settlement(settlement["id"], {"reason": "closing books"}, BILL)
    )
    terminated = get_success_data(
        api.terminate_contract(contract["id"], {"reason": "VOLUNTARY"},
                               field_ops_headers)
    )
    assert terminated["status"] == "TERMINATED_VOLUNTARY"


# ---------------------------------------------------------------------------
# Difficulty: priority pair — cooling-off beats open-settlements
# ---------------------------------------------------------------------------

def _cooling_off_priority_setup(api):
    """Contract activated 2026-07-01; pickup completed 2026-07-05; quote
    w06-29 @100; settlement over [07-01, 07-08) generated at clock 2026-07-09
    (day 8 of 14-day cooling-off AND settlement open)."""
    set_clock("2026-07-01T09:00:00Z")
    customer = create_customer(name="Cooling House", address="11 Fry Way")
    contract = create_contract(customer["id"], activate=True)
    container = create_container(customer["id"], capacity=300, fill_rate=100,
                                 lock_code="LKCO")
    truck = create_truck(plate="T-8", tank_capacity=500)
    manifest = create_manifest(truck["id"], [container["id"]],
                               service_date="2026-07-05")
    dispatch_manifest(manifest["id"], start_level=0)
    visit = manifest_visits(manifest["id"])[0]
    set_clock("2026-07-05T08:00:00Z")
    start_visit(visit["id"])
    complete_visit(visit["id"], pump_gallons=100.00, field_moisture_pct=5.0)
    publish_quote(week_start="2026-06-29", price=100)
    set_clock("2026-07-09T00:00:00Z")
    settlement = generate_settlement(
        customer["id"], period_start="2026-07-01", period_end="2026-07-08"
    )
    return customer, contract, settlement


def test_cooling_off_error_wins_over_open_settlements(api, field_ops_headers):
    """PRD §2.8: "tenth, temporal windows — pickup timing, period closure,
    cooling-off, and complaint reopen (`ERR_PICKUP_WINDOW_FUTURE`,
    `ERR_PERIOD_NOT_CLOSED`, `ERR_CONTRACT_IN_COOLING_OFF`,
    `ERR_COMPLAINT_REOPEN_WINDOW_EXPIRED`); eleventh, referential completeness
    — open settlements, pending grades, index coverage, unresolved theft
    (`ERR_OPEN_SETTLEMENTS`, `ERR_GRADE_PENDING`, `ERR_QUOTE_NOT_PUBLISHED`,
    `ERR_THEFT_UNRESOLVED`); and finally the fiscal payout floor
    (`ERR_PAYOUT_BELOW_MINIMUM`)."
    PRD §2.8: "Every request is validated against a fixed sequence of check
    categories, and a failure in an earlier category surfaces its error without
    evaluating later categories."

    Design: Difficulty/priority_pair_validation_conflict/cooling_off_vs_open_settlement_priority
    """
    _, contract, _ = _cooling_off_priority_setup(api)
    resp = api.terminate_contract(contract["id"], {"reason": "VOLUNTARY"},
                                  field_ops_headers)
    # Both guards fail here; the temporal category precedes the referential
    # category in PRD §2.8's fixed order.
    validate_error(resp, ApiErrorId.ERR_CONTRACT_IN_COOLING_OFF, expected_status=422)


def test_cooling_off_priority_leaves_contract_active(api, field_ops_headers):
    """PRD §3.2: "Cooling-off: termination is rejected with
    `ERR_CONTRACT_IN_COOLING_OFF` while the logical clock is earlier than 14
    days after `activated_at`; once at least 14 days have elapsed, the guard
    passes."

    Design: Difficulty/priority_pair_validation_conflict/cooling_off_vs_open_settlement_priority
    """
    _, contract, _ = _cooling_off_priority_setup(api)
    api.terminate_contract(contract["id"], {"reason": "VOLUNTARY"}, field_ops_headers)
    after = get_success_data(api.get_contract(contract["id"], field_ops_headers))
    assert after["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Difficulty: rebate ledger finalize/pay/void compensating invariant
# ---------------------------------------------------------------------------

def _ledger_setup(api):
    """S1: pickup 2026-08-05 pump 200.00 field 8.0, lab 16.0/1.0 (grade C);
    quotes w07-27 @140, w08-03 @100, w08-10 @110; period [08-01, 08-15)."""
    ctx = setup_provisional_settlement(
        name="Ledger House",
        container_capacity=1200,
        container_fill_rate=200,
        truck_plate="T-15",
        tank_capacity=2000,
        pump_gallons=200.00,
        field_moisture_pct=8.0,
        quote_weeks=(
            ("2026-07-27", 140),
            ("2026-08-03", 100),
            ("2026-08-10", 110),
        ),
        grade=(16.0, 1.0),
    )
    # A second, smaller container staged for the second settlement period.
    ctx["container2"] = create_container(
        ctx["customer"]["id"], capacity=300, fill_rate=100, lock_code="LKL2"
    )
    return ctx


def _ledger_second_settlement(api, ctx):
    """P2 on 2026-08-20 pump 100.00 field 5.0, lab 5.0/1.0 (grade B); quote
    w08-17 @80; period [08-15, 09-01)."""
    man2 = create_manifest(ctx["truck"]["id"], [ctx["container2"]["id"]],
                           service_date="2026-08-20")
    dispatch_manifest(man2["id"], start_level=0)
    v2 = manifest_visits(man2["id"])[0]
    set_clock("2026-08-20T08:00:00Z")
    start_visit(v2["id"])
    complete_visit(v2["id"], pump_gallons=100.00, field_moisture_pct=5.0)
    draw_and_grade_sample(v2["id"], lab_moisture_pct=5.0, lab_impurity_pct=1.0)
    publish_quote(week_start="2026-08-17", price=80)
    set_clock("2026-09-01T00:00:00Z")
    return generate_settlement(
        ctx["customer"]["id"], period_start="2026-08-15", period_end="2026-09-01"
    )


def test_finalize_posts_to_ledger_and_pay_disburses(api, field_ops_headers):
    """PRD §2.10: "The ledger mutates at exactly three points: finalizing a
    settlement adds its `final_total_cents` to the balance; paying a finalized
    settlement subtracts the same amount, moving it out of the open balance
    into a disbursement"
    PRD §3.7: "Payment stamps `paid_at` from the logical clock"

    S1 final: net 168.00 x rate 78.75 == 13230.

    Design: Difficulty/compensating_invariant/rebate_ledger_finalize_pay_void_invariant
    """
    ctx = _ledger_setup(api)
    get_success_data(api.finalize_settlement(ctx["settlement"]["id"], BILL))
    customer = get_success_data(api.get_customer(ctx["customer"]["id"], field_ops_headers))
    assert customer["rebate_balance_cents"] == 13230
    paid = get_success_data(api.pay_settlement(ctx["settlement"]["id"], BILL))
    assert paid["status"] == "PAID"
    assert paid["paid_at"], "paid_at must be stamped"
    customer = get_success_data(api.get_customer(ctx["customer"]["id"], field_ops_headers))
    assert customer["rebate_balance_cents"] == 0


def test_finalize_void_pair_leaves_ledger_unchanged(api, field_ops_headers):
    """PRD §2.10: "The compensating invariant follows directly: a
    finalize-then-void pair leaves the balance exactly as it was"
    PRD §2.10: "Each customer carries an open rebate ledger balance,
    `rebate_balance_cents`, defined as the sum of `final_total_cents` across
    that customer's settlements currently in `FINALIZED` status — settlements
    in `PROVISIONAL`, `PAID`, or `VOID` status never contribute."

    S2 final: net 95.00 x rate 72 (= 80 x 0.90 grade B) == 6840.

    Design: Difficulty/compensating_invariant/rebate_ledger_finalize_pay_void_invariant
    """
    ctx = _ledger_setup(api)
    get_success_data(api.finalize_settlement(ctx["settlement"]["id"], BILL))
    get_success_data(api.pay_settlement(ctx["settlement"]["id"], BILL))
    stl2 = _ledger_second_settlement(api, ctx)
    get_success_data(api.finalize_settlement(stl2["id"], BILL))
    customer = get_success_data(api.get_customer(ctx["customer"]["id"], field_ops_headers))
    assert customer["rebate_balance_cents"] == 6840
    get_success_data(
        api.void_settlement(stl2["id"], {"reason": "posted to wrong account"}, BILL)
    )
    after_void = get_success_data(api.get_settlement(stl2["id"], BILL))
    assert after_void["status"] == "VOID"
    customer = get_success_data(api.get_customer(ctx["customer"]["id"], field_ops_headers))
    assert customer["rebate_balance_cents"] == 0, (
        "finalize/void pair conserves the ledger"
    )
