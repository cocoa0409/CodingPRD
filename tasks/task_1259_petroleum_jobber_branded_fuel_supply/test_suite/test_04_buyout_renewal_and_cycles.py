"""Buyout variants, renewal cycle + incentive, and fail/replan cycle (PRD §3.3, §3.6)."""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_success,
)

from test_helpers import (
    TEST_USERS,
    create_active_agreement,
    create_and_deliver_drop,
    create_and_reconcile_drop,
    create_drop,
    create_station,
    deliver_drop,
    dispatch_drop,
    schedule_drop,
    set_clock,
    setup_full_drop_fixture,
    void_invoice,
)

ADMIN = TEST_USERS["admin_headers"]
CREDIT = TEST_USERS["credit_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------------------
# Difficulty / dual_variant_calc / buyout_dual_method_divergence
# ---------------------------------------------------------------------------


def _buyout_fixture_loast_margin():
    """ACTIVE agreement with term 2026-01-01..2026-12-31, committed 1M,
    allowance 5M, margin 25, shortfall 20, LOST_MARGIN, fulfilled 0,
    clock 2026-06-30."""
    station = create_station(state_code="TX", state_excise_tc_per_gal=200,
                             credit_limit_cents=100_000_000)
    agreement = create_active_agreement(
        station["id"],
        term_start_date="2026-01-01",
        term_end_date="2026-12-31",
        committed_gallons=1_000_000,
        imaging_allowance_cents=5_000_000,
        margin_tc_per_gal=25,
        shortfall_penalty_tc_per_gal=20,
        buyout_method="LOST_MARGIN",
    )
    set_clock("2026-06-30T00:00:00Z")
    return agreement


def test_buyout_dual_method_divergence_base_variants(api):
    """PRD §3.3: "Under `UNAMORTIZED_DISCOUNT`, the base is the pro-rata
    unearned imaging allowance: `imaging_allowance_cents` multiplied by the
    remaining days — the larger of zero and the number of days from the
    current clock date to `term_end_date` — divided by the total term length
    in days from `term_start_date` to `term_end_date`, rounded half-up to
    integer cents; it ignores volume performance entirely. Under `LOST_MARGIN`,
    the base is the expected margin on the unfulfilled commitment: the
    unfulfilled gallons — the larger of zero and `committed_gallons` minus
    `fulfilled_gallons` — multiplied by `margin_tc_per_gal` and divided by
    ten, rounded half-up to integer cents; it ignores the allowance and the
    calendar."
    PRD §3.3: "...a `JobberAdmin` or `CreditManager` may read a computed
    buyout projection for the agreement, which returns the agreement's
    `method`, the method-selected `base_cents`, the `alternate_base_cents`
    computed under the other variant (so the divergence between the two
    methods is observable on one agreement), the `shortfall_penalty_cents`,
    and the `net_settlement_cents`."

    Design: Difficulty/dual_variant_calc/buyout_dual_method_divergence
    """
    agreement = _buyout_fixture_loast_margin()
    quote = validate_success(api.get_buyout_quote(agreement["id"], ADMIN))
    assert quote["base_cents"] == 2_500_000
    assert quote["alternate_base_cents"] == 2_527_473
    assert quote["base_cents"] != quote["alternate_base_cents"]


def test_buyout_dual_method_divergence_net_settlement(api):
    """PRD §3.3: "Second, the shortfall penalty: the same unfulfilled gallons
    multiplied by `shortfall_penalty_tc_per_gal` and divided by ten, rounded
    half-up to integer cents before any subtraction. Third, the net
    settlement: the base minus the penalty, floored at zero so the result is
    never negative."

    Design: Difficulty/dual_variant_calc/buyout_dual_method_divergence
    """
    agreement = _buyout_fixture_loast_margin()
    quote = validate_success(api.get_buyout_quote(agreement["id"], ADMIN))
    assert quote["shortfall_penalty_cents"] == 2_000_000
    assert quote["net_settlement_cents"] == 500_000


# ---------------------------------------------------------------------------
# Difficulty / combinatorial_formula / buyout_netting_order_floor
# ---------------------------------------------------------------------------


def test_buyout_netting_order_floor_terminal_state(api):
    """PRD §3.3: "Executing the buyout settles the economics and moves the
    agreement to the terminal `BOUGHT_OUT` state, recording the result in
    `buyout_settlement_cents`."
    PRD §3.3: "Third, the net settlement: the base minus the penalty, floored
    at zero so the result is never negative."

    Design: Difficulty/combinatorial_formula/buyout_netting_order_floor
    """
    station = create_station(state_code="TX", state_excise_tc_per_gal=200,
                             credit_limit_cents=100_000_000)
    agreement = create_active_agreement(
        station["id"],
        term_start_date="2026-01-01",
        term_end_date="2026-12-31",
        committed_gallons=1_000_000,
        imaging_allowance_cents=5_000_000,
        margin_tc_per_gal=25,
        shortfall_penalty_tc_per_gal=30,
        buyout_method="UNAMORTIZED_DISCOUNT",
    )
    set_clock("2026-06-30T00:00:00Z")
    get_success_data(api.initiate_buyout(agreement["id"], ADMIN))
    settled = validate_success(api.execute_buyout(agreement["id"], ADMIN))
    assert settled["status"] == "BOUGHT_OUT"
    assert settled["buyout_settlement_cents"] == 0


def test_buyout_netting_order_floor_quote_projection(api):
    """PRD §3.3: "Third, the net settlement: the base minus the penalty,
    floored at zero so the result is never negative."
    PRD §3.3: "...a `JobberAdmin` or `CreditManager` may read a computed
    buyout projection for the agreement, which returns the agreement's
    `method`, the method-selected `base_cents`, the `alternate_base_cents`
    computed under the other variant (so the divergence between the two
    methods is observable on one agreement), the `shortfall_penalty_cents`,
    and the `net_settlement_cents`."

    Design: Difficulty/combinatorial_formula/buyout_netting_order_floor
    """
    station = create_station(state_code="TX", state_excise_tc_per_gal=200,
                             credit_limit_cents=100_000_000)
    agreement = create_active_agreement(
        station["id"],
        term_start_date="2026-01-01",
        term_end_date="2026-12-31",
        committed_gallons=1_000_000,
        imaging_allowance_cents=5_000_000,
        margin_tc_per_gal=25,
        shortfall_penalty_tc_per_gal=30,
        buyout_method="UNAMORTIZED_DISCOUNT",
    )
    set_clock("2026-06-30T00:00:00Z")
    quote = validate_success(api.get_buyout_quote(agreement["id"], ADMIN))
    assert quote["base_cents"] == 2_527_473
    assert quote["shortfall_penalty_cents"] == 3_000_000
    assert quote["net_settlement_cents"] == 0


# ---------------------------------------------------------------------------
# Difficulty / non_linear_state_machine / agreement_renewal_cycle
# ---------------------------------------------------------------------------


def test_agreement_renewal_cycle_status_and_count(api):
    """PRD §3.3: "Completing the renewal requires three preconditions, in
    order: the agreement is `RENEWAL_PENDING` (else `ERR_INVALID_STATE`), the
    station's `compliance_status` is `COMPLIANT` (a station in `CURE_PERIOD`
    or `DEFAULT` blocks renewal with `ERR_CURE_PERIOD_ACTIVE`), and the
    station has no invoice in `OVERDUE` (else `ERR_OVERDUE_INVOICES_EXIST`).
    The renewal payload carries `new_term_start_date` and `new_term_end_date`,
    which replace the agreement's term, and may carry `new_committed_gallons`,
    which replaces `committed_gallons` when supplied."
    PRD §3.3: "Every completed renewal increments `renewal_count` by one."

    Design: Difficulty/non_linear_state_machine/agreement_renewal_cycle
    """
    station = create_station(state_code="TX", state_excise_tc_per_gal=200,
                             credit_limit_cents=100_000_000)
    agreement = create_active_agreement(
        station["id"],
        term_start_date="2026-01-01",
        term_end_date="2026-06-30",
        committed_gallons=1000,
        imaging_allowance_cents=100_000,
        margin_tc_per_gal=10,
        shortfall_penalty_tc_per_gal=10,
    )
    # First renewal cycle (window opens 2026-04-01).
    set_clock("2026-05-10T00:00:00Z")
    get_success_data(api.start_renewal(agreement["id"], ADMIN))
    renewed1 = validate_success(api.renew_supply_agreement(
        agreement["id"],
        {"new_term_start_date": "2026-07-01", "new_term_end_date": "2026-12-31"},
        ADMIN,
    ))
    assert renewed1["status"] == "ACTIVE"
    assert renewed1["renewal_count"] == 1
    # Second renewal cycle (window opens 2026-10-02).
    set_clock("2026-10-15T00:00:00Z")
    get_success_data(api.start_renewal(agreement["id"], ADMIN))
    renewed2 = validate_success(api.renew_supply_agreement(
        agreement["id"],
        {"new_term_start_date": "2027-01-01", "new_term_end_date": "2027-06-30"},
        ADMIN,
    ))
    assert renewed2["status"] == "ACTIVE"
    assert renewed2["renewal_count"] == 2


def test_agreement_renewal_cycle_zero_fulfillment_zero_credit(api):
    """PRD §3.3: "The system computes the fulfilment percentage over the
    ending term — one hundred times `fulfilled_gallons` divided by
    `committed_gallons`, rounded half-up to two decimal places — and when
    that percentage is at least 95.00 (exactly 95.00 qualifies), the station
    earns a `renewal_credit_cents` equal to one percent of
    `imaging_allowance_cents`, rounded half-up to integer cents; below the
    threshold the credit is 0."

    Design: Difficulty/non_linear_state_machine/agreement_renewal_cycle
    """
    station = create_station(state_code="TX", state_excise_tc_per_gal=200,
                             credit_limit_cents=100_000_000)
    agreement = create_active_agreement(
        station["id"],
        term_start_date="2026-01-01",
        term_end_date="2026-06-30",
        committed_gallons=1000,
        imaging_allowance_cents=100_000,
        margin_tc_per_gal=10,
        shortfall_penalty_tc_per_gal=10,
    )
    set_clock("2026-05-10T00:00:00Z")
    get_success_data(api.start_renewal(agreement["id"], ADMIN))
    renewed = validate_success(api.renew_supply_agreement(
        agreement["id"],
        {"new_term_start_date": "2026-07-01", "new_term_end_date": "2026-12-31"},
        ADMIN,
    ))
    # No reconciled drops -> fulfillment 0% -> below 95.00 -> no incentive.
    assert renewed["renewal_credit_cents"] == 0


# ---------------------------------------------------------------------------
# Difficulty / non_linear_state_machine / drop_fail_replan_cycle
# ---------------------------------------------------------------------------


def test_drop_fail_replan_cycle_reaches_delivered(api):
    """PRD §3.6: "Failing a delivery moves `EN_ROUTE` to `DELIVERY_FAILED`,
    recording the supplied `reason` in `failure_reason` and incrementing
    `failure_count` by one. A failed drop can be replanned back to `PLANNED`:
    the replan request carries `expected_drop_version` per §2.8 (stale values
    rejected with `ERR_STALE_VERSION`, HTTP 412) plus a fresh `window_start`,
    `window_end`, and `truck_id`, which replace the prior values."

    Design: Difficulty/non_linear_state_machine/drop_fail_replan_cycle
    """
    fixture = setup_full_drop_fixture()
    drop = create_drop(fixture, planned_gallons=1000)
    schedule_drop(drop["id"])
    dispatch_drop(drop["id"])
    get_success_data(api.fail_transport_drop(
        drop["id"], {"reason": "pump blocked"}, DISPATCH
    ))
    drop_now = get_success_data(api.get_transport_drop(drop["id"], DISPATCH))
    assert drop_now["status"] == "DELIVERY_FAILED"
    assert drop_now["failure_count"] == 1
    # Replan with the freshly observed version.
    replanned = validate_success(api.replan_transport_drop(
        drop["id"],
        {
            "expected_drop_version": drop_now["version"],
            "window_start": "2026-05-03T08:00:00Z",
            "window_end": "2026-05-03T12:00:00Z",
            "truck_id": fixture["truck"]["id"],
        },
        DISPATCH,
    ))
    assert replanned["status"] == "PLANNED"
    schedule_drop(drop["id"])
    dispatch_drop(drop["id"])
    delivered = validate_success(api.deliver_transport_drop(
        drop["id"], {"delivered_gallons": 1000}, DISPATCH
    ))
    assert delivered["status"] == "DELIVERED"
    assert delivered["failure_count"] == 1
    assert delivered["invoice_id"] is not None


def test_drop_fail_replan_cycle_replans_window_and_truck(api):
    """PRD §3.6: "A failed drop can be replanned back to `PLANNED`: the
    replan request carries `expected_drop_version` per §2.8 (stale values
    rejected with `ERR_STALE_VERSION`, HTTP 412) plus a fresh `window_start`,
    `window_end`, and `truck_id`, which replace the prior values."

    Design: Difficulty/non_linear_state_machine/drop_fail_replan_cycle
    """
    fixture = setup_full_drop_fixture()
    drop = create_drop(fixture, planned_gallons=1000)
    schedule_drop(drop["id"])
    dispatch_drop(drop["id"])
    failed = get_success_data(api.fail_transport_drop(
        drop["id"], {"reason": "pump blocked"}, DISPATCH
    ))
    replanned = validate_success(api.replan_transport_drop(
        drop["id"],
        {
            "expected_drop_version": failed["version"],
            "window_start": "2026-05-04T08:00:00Z",
            "window_end": "2026-05-04T12:00:00Z",
            "truck_id": fixture["truck"]["id"],
        },
        DISPATCH,
    ))
    assert replanned["status"] == "PLANNED"
    assert replanned["window_start"] == "2026-05-04T08:00:00Z"
    assert replanned["window_end"] == "2026-05-04T12:00:00Z"


# ---------------------------------------------------------------------------
# Difficulty / boundary_precision_check / fulfillment_exactly_95_renews_with_incentive
# ---------------------------------------------------------------------------


def _fulfillment_95_fixture():
    """Station with ACTIVE agreement term 2026-01-01..2026-07-31, committed
    20000, allowance 2000000. RECONCILED drops 10000 + 9000 = 19000 fulfilled
    (95.00% exactly). Both invoices voided so renew is not blocked by OVERDUE.
    Clock at 2026-06-01 (inside renewal window which opened 2026-05-02)."""
    set_clock("2026-01-02T00:00:00Z")
    fixture = setup_full_drop_fixture(
        state_code="TX",
        state_excise_tc_per_gal=200,
        credit_limit_cents=100_000_000,
        price_tc_per_gal=2000,
        price_effective_date="2026-01-02",
        tank_capacity=50_000,
        opening_physical=0,
        term_start_date="2026-01-01",
        term_end_date="2026-07-31",
        committed_gallons=20_000,
        imaging_allowance_cents=2_000_000,
    )
    # First drop: 10000 gal delivered at clock 2026-03-02.
    set_clock("2026-03-02T10:00:00Z")
    d1 = create_and_reconcile_drop(
        fixture, planned_gallons=10_000,
        window_start="2026-03-02T08:00:00Z", window_end="2026-03-02T12:00:00Z",
    )
    # Second drop: 9000 gal delivered at clock 2026-03-05.
    set_clock("2026-03-05T10:00:00Z")
    d2 = create_and_reconcile_drop(
        fixture, planned_gallons=9_000,
        window_start="2026-03-05T08:00:00Z", window_end="2026-03-05T12:00:00Z",
    )
    # Void both invoices so renewal is not blocked by OVERDUE once the clock
    # advances past their due dates.
    void_invoice(d1["invoice_id"])
    void_invoice(d2["invoice_id"])
    set_clock("2026-06-01T00:00:00Z")
    return fixture


def test_fulfillment_exactly_95_renews_with_incentive_credit(api):
    """PRD §3.3: "The system computes the fulfilment percentage over the
    ending term — one hundred times `fulfilled_gallons` divided by
    `committed_gallons`, rounded half-up to two decimal places — and when
    that percentage is at least 95.00 (exactly 95.00 qualifies), the station
    earns a `renewal_credit_cents` equal to one percent of
    `imaging_allowance_cents`, rounded half-up to integer cents; below the
    threshold the credit is 0."

    Design: Difficulty/boundary_precision_check/fulfillment_exactly_95_renews_with_incentive
    """
    fixture = _fulfillment_95_fixture()
    get_success_data(api.start_renewal(fixture["agreement"]["id"], ADMIN))
    renewed = validate_success(api.renew_supply_agreement(
        fixture["agreement"]["id"],
        {"new_term_start_date": "2026-08-01", "new_term_end_date": "2027-07-31"},
        ADMIN,
    ))
    assert renewed["status"] == "ACTIVE"
    assert renewed["renewal_count"] == 1
    assert renewed["renewal_credit_cents"] == 20_000


def test_fulfillment_exactly_95_resets_fulfilled_gallons(api):
    """PRD §3.2: "an agreement's `fulfilled_gallons` is computed on every
    read as the sum of `delivered_gallons` over the station's drops in
    `RECONCILED` status whose delivery clock-date falls within the
    agreement's term, both term dates inclusive."
    PRD §3.3: "The renewal payload carries `new_term_start_date` and
    `new_term_end_date`, which replace the agreement's term..."

    Design: Difficulty/boundary_precision_check/fulfillment_exactly_95_renews_with_incentive
    """
    fixture = _fulfillment_95_fixture()
    get_success_data(api.start_renewal(fixture["agreement"]["id"], ADMIN))
    renewed = validate_success(api.renew_supply_agreement(
        fixture["agreement"]["id"],
        {"new_term_start_date": "2026-08-01", "new_term_end_date": "2027-07-31"},
        ADMIN,
    ))
    # Old drops fall outside the new term [2026-08-01, 2027-07-31].
    assert renewed["fulfilled_gallons"] == 0
    assert renewed["term_start_date"] == "2026-08-01"
    assert renewed["term_end_date"] == "2027-07-31"


# ---------------------------------------------------------------------------
# Corner / state_machines / renew_blocked_by_overdue_invoice
# ---------------------------------------------------------------------------


def test_renew_blocked_by_overdue_invoice(api):
    """PRD §3.3: "Completing the renewal requires three preconditions, in
    order: the agreement is `RENEWAL_PENDING` (else `ERR_INVALID_STATE`), the
    station's `compliance_status` is `COMPLIANT` (a station in `CURE_PERIOD`
    or `DEFAULT` blocks renewal with `ERR_CURE_PERIOD_ACTIVE`), and the
    station has no invoice in `OVERDUE` (else `ERR_OVERDUE_INVOICES_EXIST`)."

    Design: Corner/validations/renew_blocked_by_overdue_invoice
    """
    fixture = setup_full_drop_fixture(
        term_start_date="2026-01-01",
        term_end_date="2026-06-30",
        credit_limit_cents=100_000_000,
    )
    # Deliver at clock 2026-05-10 -> invoice_date 2026-05-10, due 2026-05-20.
    set_clock("2026-05-10T10:00:00Z")
    create_and_deliver_drop(
        fixture, planned_gallons=1000,
        window_start="2026-05-10T08:00:00Z", window_end="2026-05-10T12:00:00Z",
    )
    # Advance past due_date so the invoice is OVERDUE.
    set_clock("2026-06-01T00:00:00Z")
    get_success_data(api.start_renewal(fixture["agreement"]["id"], ADMIN))
    resp = api.renew_supply_agreement(
        fixture["agreement"]["id"],
        {"new_term_start_date": "2026-07-01", "new_term_end_date": "2026-12-31"},
        ADMIN,
    )
    from test_helpers import ApiErrorId
    from prd_bench_local_runner.testing import validate_error
    validate_error(resp, ApiErrorId.ERR_OVERDUE_INVOICES_EXIST)
    agreement_now = get_success_data(api.get_supply_agreement(
        fixture["agreement"]["id"], ADMIN
    ))
    assert agreement_now["status"] == "RENEWAL_PENDING"


def test_renew_blocked_during_cure_period(api):
    """PRD §3.3: "Completing the renewal requires three preconditions, in
    order: the agreement is `RENEWAL_PENDING` (else `ERR_INVALID_STATE`), the
    station's `compliance_status` is `COMPLIANT` (a station in `CURE_PERIOD`
    or `DEFAULT` blocks renewal with `ERR_CURE_PERIOD_ACTIVE`), and the
    station has no invoice in `OVERDUE` (else `ERR_OVERDUE_INVOICES_EXIST`)."

    Design: Corner/validations/renew_blocked_during_cure_period
    """
    from test_helpers import ApiErrorId, record_audit
    from prd_bench_local_runner.testing import validate_error

    station = create_station(credit_limit_cents=500000)
    agreement = create_active_agreement(
        station["id"],
        term_start_date="2026-01-01",
        term_end_date="2026-06-30",
        committed_gallons=1000,
        imaging_allowance_cents=1000,
        margin_tc_per_gal=10,
        shortfall_penalty_tc_per_gal=10,
    )
    set_clock("2026-05-10T00:00:00Z")
    record_audit(station["id"], score=60, audit_date="2026-05-10")
    get_success_data(api.start_renewal(agreement["id"], ADMIN))
    resp = api.renew_supply_agreement(
        agreement["id"],
        {"new_term_start_date": "2026-07-01", "new_term_end_date": "2026-12-31"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_CURE_PERIOD_ACTIVE)
