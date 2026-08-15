"""Exchange pool cascades, selector, cross-entity dependencies (queue A rule 4, 7, 8, 9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    CSR,
    SHOP_MANAGER,
    TECHNICIAN,
    api_client,
    core_return_exchange,
    create_customer,
    create_exchange_agreement,
    create_lease,
    create_part,
    create_unit,
    fulfill_exchange,
    get_customer,
    get_exchange_agreement,
    get_unit,
    get_work_order,
    lease_agreement_payload,
    make_customer_headers,
    return_lease,
    set_clock,
    setup_exchange_fulfilled,
    setup_lease_active,
    setup_work_order_closed,
    setup_work_order_released,
    setup_work_order_test_passed,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Difficulty queue A — core-return settlement cascade (depth 4)
# ---------------------------------------------------------------------------

def test_core_return_settlement_chain_depth4_unit_and_invoice(api):
    """PRD §3.7: "The first hop inducts the core: its ownership flips from
    `CUSTOMER` to `SHOP`, `core_received_at` is stamped with the clock, and
    a `CORE_IN` traceability event is appended. ... A non-BER core moves to
    custody `IN_POOL` and its condition improves `UNSERVICEABLE →
    SERVICEABLE` ... With settlement computed, an invoice with `source_type`
    `EXCHANGE` is created in `ISSUED` status with `total_cents` equal to
    `settlement_total_cents`."

    Design: Difficulty/transitive_cascade/core_return_settlement_chain_depth4
    """
    customer, part, pool_unit, core_unit, agreement = setup_exchange_fulfilled()
    set_clock("2026-08-05T00:00:00Z")

    settled = core_return_exchange(agreement["id"], core_unit["id"],
                                   core_teardown_estimate_cents=1000000)
    assert settled["status"] == "CLOSED"
    # NON_BER, on time -> admin fee only
    assert settled["core_charge_cents"] == 0
    assert settled["late_fee_cents"] == 0
    assert settled["settlement_total_cents"] == 25000

    core_after = get_unit(core_unit["id"])
    assert core_after["ownership"] == "SHOP"
    assert core_after["custody_status"] == "IN_POOL"
    assert core_after["condition_status"] == "SERVICEABLE"

    invoices, _ = validate_paginated(api.list_invoices(
        SHOP_MANAGER, params={"exchange_agreement_id": agreement["id"]}))
    assert len(invoices) == 1
    inv = invoices[0]
    assert inv["source_type"] == "EXCHANGE"
    assert inv["status"] == "ISSUED"
    assert inv["total_cents"] == 25000


def test_core_return_settlement_chain_depth4_exposure_and_trace(api):
    """PRD §3.7: "The third hop adds `settlement_total_cents` to the
    customer's `current_exposure_cents`, re-deriving `credit_hold`. The
    fourth hop moves the agreement to `CLOSED`." PRD §2.10: "When an
    invoice is `ISSUED`, its `total_cents` is added to
    `current_exposure_cents`". PRD §2.11: traceability events append in
    chronological order beginning at BIRTH.

    Design: Difficulty/transitive_cascade/core_return_settlement_chain_depth4
    """
    customer, part, pool_unit, core_unit, agreement = setup_exchange_fulfilled()
    set_clock("2026-08-05T00:00:00Z")
    settled = core_return_exchange(agreement["id"], core_unit["id"],
                                   core_teardown_estimate_cents=1000000)

    cust_after = get_customer(customer["id"])
    assert cust_after["current_exposure_cents"] == 25000

    records, _ = validate_paginated(
        api.list_unit_traceability(core_unit["id"], SHOP_MANAGER))
    event_types = [r["event_type"] for r in records]
    assert event_types[0] == "BIRTH"
    assert event_types[-1] == "CORE_IN"


# ---------------------------------------------------------------------------
# Difficulty queue A — warranty accept cascade (depth 3)
# ---------------------------------------------------------------------------

def _setup_accepted_claim_with_parts():
    """Original work order with parts (base 2575000), claim at 200 cycles
    accepted -> FULL credit."""
    from test_helpers import (
        create_customer, create_part, create_unit, create_work_order,
        submit_quote, approve_quote, create_parts_requisition,
        issue_received_requisition, complete_repair, create_test_cell,
        book_cell, set_clock, record_test_results, release_work_order,
        generate_invoice, close_work_order, create_warranty_claim,
        review_warranty_claim, TECHNICIAN, CSR,
    )
    from test_helpers import api_client as _api
    customer = create_customer()
    part = create_part()
    unit = create_unit(part["id"], ownership="CUSTOMER",
                       owner_customer_id=customer["id"])
    wo = create_work_order(customer["id"], unit["id"], work_scope="OVERHAUL")
    _api.teardown_complete(wo["id"], TECHNICIAN)
    quoted = submit_quote(wo["id"], scrap_option_ack=False)
    approve_quote(wo["id"], customer["id"], quoted["version"])
    req = create_parts_requisition(wo["id"], part_number="BRG-32-99",
                                    quantity=2, requested_source="OEM")
    issue_received_requisition(req["id"], 250000)
    complete_repair(wo["id"], technician_user_id="tech-1")
    cell = create_test_cell()
    book_cell(cell["id"], wo["id"],
              start_time="2026-08-02T01:00:00Z", end_time="2026-08-02T05:00:00Z")
    set_clock("2026-08-02T02:00:00Z")
    record_test_results(wo["id"], result="PASS", inspector_user_id="insp-9")
    release_work_order(wo["id"], inspector_user_id="insp-9")
    generate_invoice(wo["id"])
    close_work_order(wo["id"])
    claim = create_warranty_claim(wo["id"], customer["id"],
                                  claim_cycles_used=200, claim_months_used=10,
                                  failure_description="Bearing spalling")
    accepted = review_warranty_claim(claim["id"], "ACCEPT")
    return customer, part, unit, wo, claim, accepted


def test_warranty_accept_rework_chain_depth3_credit_computed(api):
    """PRD §3.9: "The base is the original work-order invoice's
    `labor_cents` plus its `parts_cents`. The `credit_variant` is `FULL`
    when twice `claim_cycles_used` is at most `warranty_cycle_limit` ...
    and `credit_cents` then equals the base".

    Design: Difficulty/transitive_cascade/warranty_accept_rework_chain_depth3
    """
    customer, part, unit, wo, claim, accepted = _setup_accepted_claim_with_parts()
    assert accepted["status"] == "ACCEPTED"
    assert accepted["credit_cents"] == 2575000  # labor 2000000 + parts 575000


def test_warranty_accept_rework_chain_depth3_rework_spawned(api):
    """PRD §3.9: "a rework work order is auto-created with `customer_id`
    set to the claimant, `unit_id` set to the claim's unit, `work_scope`
    set to `WARRANTY_REWORK`, and `labor_estimate_cents` equal to the
    original work order's labor, starting directly in `REPAIR_IN_PROGRESS`"
    and "the unit's custody moves to `IN_SHOP`, its condition moves to
    `UNSERVICEABLE`, and a `WARRANTY_INDUCT` traceability event is appended."

    Design: Difficulty/transitive_cascade/warranty_accept_rework_chain_depth3
    """
    customer, part, unit, wo, claim, accepted = _setup_accepted_claim_with_parts()
    rework_wo_id = accepted["rework_work_order_id"]
    assert rework_wo_id

    rework = get_work_order(rework_wo_id)
    assert rework["status"] == "REPAIR_IN_PROGRESS"
    assert rework["work_scope"] == "WARRANTY_REWORK"

    unit_after = get_unit(unit["id"])
    assert unit_after["custody_status"] == "IN_SHOP"
    assert unit_after["condition_status"] == "UNSERVICEABLE"

    records, _ = validate_paginated(api.list_unit_traceability(unit["id"], SHOP_MANAGER))
    assert records[-1]["event_type"] == "WARRANTY_INDUCT"


# ---------------------------------------------------------------------------
# Corner — exchange / selector / pool
# ---------------------------------------------------------------------------

def test_fulfill_empty_pool_returns_pool_empty(api):
    """PRD §3.7: "an empty eligible set rejects fulfillment with
    `ERR_POOL_EMPTY` (HTTP 422), there being no deferred queue."

    Design: Corner/calculations/fulfill_empty_pool_returns_pool_empty
    """
    customer = create_customer()
    part = create_part()
    agreement = create_exchange_agreement(customer["id"], part["id"])
    res = api.fulfill_exchange(agreement["id"], CSR)
    validate_error(res, ApiErrorId.ERR_POOL_EMPTY.value, expected_status=422)

    after = get_exchange_agreement(agreement["id"])
    assert after["status"] == "OPEN"


def test_pool_selector_lowest_cycles_then_created_at_tiebreak(api):
    """PRD §3.7: "candidates rank by `cycles_since_overhaul` ascending with
    ties broken by `created_at` ascending — never by id".

    Design: Corner/calculations/pool_selector_lowest_cycles_then_created_at_tiebreak
    """
    customer = create_customer()
    part = create_part()
    # Three pool units; SN-B and SN-C tie at 50 cycles (B created first).
    u_a = create_unit(part["id"], serial_number="SN-A", ownership="SHOP",
                      condition_status="SERVICEABLE", custody_status="IN_POOL",
                      total_cycles=9000, cycles_since_overhaul=200,
                      manufactured_at="2011-01-01")
    u_b = create_unit(part["id"], serial_number="SN-B", ownership="SHOP",
                      condition_status="SERVICEABLE", custody_status="IN_POOL",
                      total_cycles=5000, cycles_since_overhaul=50,
                      manufactured_at="2013-01-01")
    set_clock("2026-08-01T00:00:01Z")
    u_c = create_unit(part["id"], serial_number="SN-C", ownership="SHOP",
                      condition_status="SERVICEABLE", custody_status="IN_POOL",
                      total_cycles=6000, cycles_since_overhaul=50,
                      manufactured_at="2012-01-01")
    ex1 = create_exchange_agreement(customer["id"], part["id"])
    ex2 = create_exchange_agreement(customer["id"], part["id"])
    ex3 = create_exchange_agreement(customer["id"], part["id"])

    f1 = fulfill_exchange(ex1["id"])
    assert f1["pool_unit_id"] == u_b["id"]
    f2 = fulfill_exchange(ex2["id"])
    assert f2["pool_unit_id"] == u_c["id"]
    f3 = fulfill_exchange(ex3["id"])
    assert f3["pool_unit_id"] == u_a["id"]


def test_exchange_defaulted_by_clock_sweep(api):
    """PRD §3.7: "whenever the logical clock is set (§2.5), every
    `FULFILLED` agreement whose `core_due_date` plus 5 grace days falls
    before the current date moves to `DEFAULTED`. The settlement follows
    the same pinned order with the missing-core branch: `core_charge_cents`
    is the full `replacement_value_cents`; the late-fee cap of
    `replacement_value_cents` minus that charge is zero, so `late_fee_cents`
    collapses to 0; and `settlement_total_cents` is $250.00 plus
    `replacement_value_cents`. An `EXCHANGE` invoice is created `ISSUED`,
    the customer's exposure rises by the settlement, and the pool unit's
    ownership flips from `SHOP` to `CUSTOMER` — the customer keeps the pool
    unit."

    Design: Corner/state_machines/exchange_defaulted_by_clock_sweep
    """
    customer = create_customer()
    part = create_part()
    pool_unit = create_unit(part["id"], serial_number="SN-P1", ownership="SHOP",
                            condition_status="SERVICEABLE", custody_status="IN_POOL",
                            total_cycles=3000, cycles_since_overhaul=50,
                            manufactured_at="2014-03-01")
    agreement = create_exchange_agreement(customer["id"], part["id"])
    fulfilled = fulfill_exchange(agreement["id"])
    # core_due_date = date(2026-08-01) + 15 days = 2026-08-16.
    assert fulfilled["core_due_date"] == "2026-08-16"

    sweep = set_clock("2026-08-22T00:00:00Z")
    assert agreement["id"] in sweep["defaulted_exchange_agreement_ids"]

    after = get_exchange_agreement(agreement["id"])
    assert after["status"] == "DEFAULTED"
    assert after["core_charge_cents"] == 10000000
    assert after["late_fee_cents"] == 0
    assert after["settlement_total_cents"] == 10025000

    invoices, _ = validate_paginated(api.list_invoices(
        SHOP_MANAGER, params={"exchange_agreement_id": agreement["id"]}))
    assert len(invoices) == 1
    assert invoices[0]["total_cents"] == 10025000
    assert invoices[0]["status"] == "ISSUED"

    pool_after = get_unit(pool_unit["id"])
    assert pool_after["ownership"] == "CUSTOMER"


def test_exchange_core_return_before_fulfill_rejected(api):
    """PRD §3.7: "Core return is a `Technician` action ... The checks, in
    order: the agreement must be `FULFILLED` (`ERR_EXCHANGE_INVALID_STATE`)".

    Design: Corner/errors/exchange_core_return_before_fulfill_rejected
    """
    customer = create_customer()
    part = create_part()
    core_unit = create_unit(part["id"], serial_number="SN-C1",
                            ownership="CUSTOMER", owner_customer_id=customer["id"],
                            total_cycles=7000, cycles_since_overhaul=900,
                            manufactured_at="2012-05-01")
    agreement = create_exchange_agreement(customer["id"], part["id"])

    res = api.core_return_exchange(
        agreement["id"],
        {"core_unit_id": core_unit["id"], "core_teardown_estimate_cents": 100000},
        TECHNICIAN)
    validate_error(res, ApiErrorId.ERR_EXCHANGE_INVALID_STATE.value, expected_status=409)


# ---------------------------------------------------------------------------
# Difficulty queue A — pool depth conserved invariant
# ---------------------------------------------------------------------------

def _pool_depth(part_id):
    data, _ = validate_paginated(api_client.list_units(
        SHOP_MANAGER,
        params={"part_id": part_id, "ownership": "SHOP",
                "custody_status": "IN_POOL", "condition_status": "SERVICEABLE",
                "limit": 100}))
    return len(data)


def _open_exchange_obligations(part_id):
    data, _ = validate_paginated(api_client.list_exchange_agreements(
        SHOP_MANAGER, params={"part_id": part_id, "status": "FULFILLED", "limit": 100}))
    return len(data)


def test_pool_depth_plus_open_exchange_obligations_conserved_at_fulfill(api):
    """PRD §3.7: fulfill "moves the selected unit's custody `IN_POOL →
    SHIPPED`" while the agreement becomes `FULFILLED`. The eligible pool
    set loses one unit exactly when the obligation appears.

    Design: Difficulty/compensating_invariant/pool_depth_plus_open_exchange_obligations_conserved
    """
    customer = create_customer()
    part = create_part()
    pool_unit = create_unit(part["id"], serial_number="SN-P1", ownership="SHOP",
                            condition_status="SERVICEABLE", custody_status="IN_POOL",
                            total_cycles=3000, cycles_since_overhaul=50,
                            manufactured_at="2014-03-01")
    core_unit = create_unit(part["id"], serial_number="SN-C1", ownership="CUSTOMER",
                            owner_customer_id=customer["id"],
                            condition_status="UNSERVICEABLE", custody_status="OFF_SITE",
                            total_cycles=7000, cycles_since_overhaul=900,
                            manufactured_at="2012-05-01")
    agreement = create_exchange_agreement(customer["id"], part["id"])

    # Before fulfill: pool depth 1 + obligations 0 == 1
    assert _pool_depth(part["id"]) + _open_exchange_obligations(part["id"]) == 1

    fulfilled = fulfill_exchange(agreement["id"])
    assert fulfilled["pool_unit_id"] == pool_unit["id"]
    assert fulfilled["core_due_date"] == "2026-08-16"

    # After fulfill: pool depth 0 + obligations 1 == 1
    assert _pool_depth(part["id"]) + _open_exchange_obligations(part["id"]) == 1


def test_pool_depth_plus_open_exchange_obligations_conserved_at_core_return(api):
    """PRD §3.7: "A non-BER core moves to custody `IN_POOL` and its
    condition improves `UNSERVICEABLE → SERVICEABLE`" and "The fourth hop
    moves the agreement to `CLOSED`" — the compensating core return
    replenishes the pool exactly when the obligation closes.

    Design: Difficulty/compensating_invariant/pool_depth_plus_open_exchange_obligations_conserved
    """
    customer = create_customer()
    part = create_part()
    pool_unit = create_unit(part["id"], serial_number="SN-P1", ownership="SHOP",
                            condition_status="SERVICEABLE", custody_status="IN_POOL",
                            total_cycles=3000, cycles_since_overhaul=50,
                            manufactured_at="2014-03-01")
    core_unit = create_unit(part["id"], serial_number="SN-C1", ownership="CUSTOMER",
                            owner_customer_id=customer["id"],
                            condition_status="UNSERVICEABLE", custody_status="OFF_SITE",
                            total_cycles=7000, cycles_since_overhaul=900,
                            manufactured_at="2012-05-01")
    agreement = create_exchange_agreement(customer["id"], part["id"])
    fulfill_exchange(agreement["id"])
    set_clock("2026-08-05T00:00:00Z")
    core_return_exchange(agreement["id"], core_unit["id"],
                         core_teardown_estimate_cents=1000000)

    # After core return: pool depth 1 + obligations 0 == 1
    assert _pool_depth(part["id"]) + _open_exchange_obligations(part["id"]) == 1


# ---------------------------------------------------------------------------
# Cross-entity state dependencies (queue A rule 7)
# ---------------------------------------------------------------------------

def test_test_results_require_covering_booking(api):
    """PRD §3.5: "a `BOOKED` booking for this work order must cover the
    current clock — its `start_time` at or before the clock and the clock
    before its `end_time` — otherwise `ERR_NO_ACTIVE_TEST_BOOKING` (HTTP
    409)."

    Design: Difficulty/cross_entity_state_dependency/test_results_require_covering_booking
    """
    from test_helpers import setup_work_order_ready_for_test, create_test_cell, book_cell
    customer, part, unit, wo = setup_work_order_ready_for_test()
    cell = create_test_cell()
    # Booking exists but its window is 10:00-14:00 while the clock reads 08:00.
    book_cell(cell["id"], wo["id"],
              start_time="2026-08-03T10:00:00Z", end_time="2026-08-03T14:00:00Z")
    set_clock("2026-08-03T08:00:00Z")

    from test_helpers import make_inspector_headers
    res = api.record_test_results(
        wo["id"], {"result": "PASS", "atp_reference": "ATP-X"},
        make_inspector_headers("insp-9"))
    validate_error(res, ApiErrorId.ERR_NO_ACTIVE_TEST_BOOKING.value, expected_status=409)

    after = get_work_order(wo["id"])
    assert after["status"] == "READY_FOR_TEST"
    assert after["test_attempt_count"] == 0


def test_test_results_no_booking_at_all_also_rejected(api):
    """PRD §3.5: "a `BOOKED` booking for this work order must cover the
    current clock ... otherwise `ERR_NO_ACTIVE_TEST_BOOKING` (HTTP 409)" —
    no booking whatsoever also fails the rule.

    Design: Difficulty/cross_entity_state_dependency/test_results_require_covering_booking
    """
    from test_helpers import setup_work_order_ready_for_test, make_inspector_headers
    customer, part, unit, wo = setup_work_order_ready_for_test()
    set_clock("2026-08-03T08:00:00Z")
    res = api.record_test_results(
        wo["id"], {"result": "PASS", "atp_reference": "ATP-X"},
        make_inspector_headers("insp-9"))
    validate_error(res, ApiErrorId.ERR_NO_ACTIVE_TEST_BOOKING.value, expected_status=409)


def test_warranty_claim_requires_closed_original_work_order(api):
    """PRD §3.9: "the original work order must be `CLOSED`, otherwise
    `ERR_WARRANTY_REQUIRES_CLOSED_WO` (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/warranty_claim_requires_closed_original_work_order
    """
    # Drive to RELEASED but not CLOSED (no invoice generated, no close).
    customer, part, unit, wo, cell, booking = setup_work_order_released()
    res = api.create_warranty_claim(
        {"original_work_order_id": wo["id"], "claim_cycles_used": 100,
         "claim_months_used": 5, "failure_description": "Premature claim"},
        make_customer_headers(customer["id"]))
    validate_error(res, ApiErrorId.ERR_WARRANTY_REQUIRES_CLOSED_WO.value,
                   expected_status=409)

    claims, meta = validate_paginated(api.list_warranty_claims(
        SHOP_MANAGER, params={"original_work_order_id": wo["id"]}))
    assert meta["total_count"] == 0


def test_warranty_claim_rejected_before_released_too(api):
    """PRD §3.9: "the original work order must be `CLOSED`, otherwise
    `ERR_WARRANTY_REQUIRES_CLOSED_WO` (HTTP 409)" — a work order still in
    an earlier pipeline state fails the same gate.

    Design: Difficulty/cross_entity_state_dependency/warranty_claim_requires_closed_original_work_order
    """
    from test_helpers import setup_work_order_in_repair
    customer, part, unit, wo = setup_work_order_in_repair()
    res = api.create_warranty_claim(
        {"original_work_order_id": wo["id"], "claim_cycles_used": 100,
         "claim_months_used": 5, "failure_description": "Way too early"},
        make_customer_headers(customer["id"]))
    validate_error(res, ApiErrorId.ERR_WARRANTY_REQUIRES_CLOSED_WO.value,
                   expected_status=409)
