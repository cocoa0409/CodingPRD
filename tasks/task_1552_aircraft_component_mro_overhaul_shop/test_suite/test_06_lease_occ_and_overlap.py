"""Lease semantics, OCC stale-version checks, temporal overlap (queue A rule 8; queue B)."""
import pytest

from test_helpers import (
    ApiErrorId,
    CSR,
    SHOP_MANAGER,
    api_client,
    create_customer,
    create_lease,
    create_part,
    create_unit,
    fulfill_exchange,
    get_lease,
    get_unit,
    lease_agreement_payload,
    return_lease,
    set_clock,
    setup_lease_active,
    setup_work_order_in_repair,
    submit_quote,
    book_cell,
    complete_repair,
    create_test_cell,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Queue A — lease day-closed boundary
# ---------------------------------------------------------------------------

def test_lease_day_closed_boundary_day_conflicts_rejected(api):
    """PRD §3.8: "the lease's day-closed interval — the inclusive day range
    from `start_date` through `end_date` — must not share any day with an
    `ACTIVE` lease on the same unit, and a shared boundary day is a
    conflict, otherwise `ERR_LEASE_PERIOD_OVERLAP` (HTTP 409)".

    Design: Difficulty/resource_temporal_overlap/lease_day_closed_boundary_day_conflicts
    """
    customer, part, unit, lease1 = setup_lease_active(
        lease_overrides={"start_date": "2026-08-10", "end_date": "2026-08-14"})
    unit_now = get_unit(unit["id"])
    v2 = unit_now["version"]

    # Shared boundary day 2026-08-14 conflicts.
    res = api.create_lease_agreement(
        lease_agreement_payload(customer["id"], unit["id"], v2,
                                start_date="2026-08-14", end_date="2026-08-20"),
        CSR)
    validate_error(res, ApiErrorId.ERR_LEASE_PERIOD_OVERLAP.value, expected_status=409)


def test_lease_day_closed_boundary_day_after_is_free(api):
    """PRD §3.8: "the lease's day-closed interval — the inclusive day range
    from `start_date` through `end_date` — must not share any day with an
    `ACTIVE` lease on the same unit, and a shared boundary day is a
    conflict". A lease starting the day after the existing end_date shares
    no day and is legal. PRD §2.7: lease creation requires
    `expected_unit_version` — rejected leases do not bump it.

    Design: Difficulty/resource_temporal_overlap/lease_day_closed_boundary_day_conflicts
    """
    customer, part, unit, lease1 = setup_lease_active(
        lease_overrides={"start_date": "2026-08-10", "end_date": "2026-08-14"})
    unit_after_l1 = get_unit(unit["id"])
    v2 = unit_after_l1["version"]

    # Rejected create must NOT bump the unit version.
    res = api.create_lease_agreement(
        lease_agreement_payload(customer["id"], unit["id"], v2,
                                start_date="2026-08-14", end_date="2026-08-20"),
        CSR)
    validate_error(res, ApiErrorId.ERR_LEASE_PERIOD_OVERLAP.value, expected_status=409)

    # Retry with the same version on the free day succeeds.
    res2 = api.create_lease_agreement(
        lease_agreement_payload(customer["id"], unit["id"], v2,
                                start_date="2026-08-15", end_date="2026-08-20"),
        CSR)
    lease2 = validate_success(res2, 201)
    assert lease2["status"] == "ACTIVE"

    leases, meta = validate_paginated(api.list_lease_agreements(
        SHOP_MANAGER, params={"unit_id": unit["id"]}))
    assert meta["total_count"] == 2


# ---------------------------------------------------------------------------
# Queue A — cell half-open adjacency
# ---------------------------------------------------------------------------

def _setup_ready_for_test_with_booking():
    """Work order READY_FOR_TEST; cell CELL-A; booking [10:00, 14:00)."""
    customer, part, unit, wo = setup_work_order_in_repair()
    complete_repair(wo["id"], technician_user_id="tech-1")
    cell = create_test_cell(name="CELL-A")
    book_cell(cell["id"], wo["id"],
              start_time="2026-08-03T10:00:00Z", end_time="2026-08-03T14:00:00Z")
    return customer, part, unit, wo, cell


def test_test_cell_half_open_adjacency_allowed(api):
    """PRD §3.5: "The window is half-open: `start_time` is inclusive and
    `end_time` is exclusive, so two windows that merely touch are adjacent,
    not overlapping." PRD §3.5: "the window must not overlap any existing
    `BOOKED` window on the same cell — adjacency is allowed — otherwise
    `ERR_TEST_CELL_OVERLAP` (HTTP 409)".

    Design: Difficulty/resource_temporal_overlap/test_cell_half_open_adjacency_allowed_overlap_rejected
    """
    customer, part, unit, wo, cell = _setup_ready_for_test_with_booking()
    # Adjacent: starts exactly when B1 ends (14:00 == 14:00) -> allowed.
    res = api.create_booking(
        cell["id"],
        {"work_order_id": wo["id"],
         "start_time": "2026-08-03T14:00:00Z", "end_time": "2026-08-03T18:00:00Z"},
        CSR)
    booking2 = validate_success(res, 201)
    # 4h * 100000 cents/h = 400000
    assert booking2["fee_cents"] == 400000
    assert booking2["status"] == "BOOKED"


def test_test_cell_half_open_overlap_rejected(api):
    """PRD §3.5: "the window must not overlap any existing `BOOKED` window
    on the same cell — adjacency is allowed — otherwise
    `ERR_TEST_CELL_OVERLAP` (HTTP 409)" — a window shifted into the existing
    10:00-14:00 slot overlaps and is rejected.

    Design: Difficulty/resource_temporal_overlap/test_cell_half_open_adjacency_allowed_overlap_rejected
    """
    customer, part, unit, wo, cell = _setup_ready_for_test_with_booking()
    res = api.create_booking(
        cell["id"],
        {"work_order_id": wo["id"],
         "start_time": "2026-08-03T13:00:00Z", "end_time": "2026-08-03T15:00:00Z"},
        CSR)
    validate_error(res, ApiErrorId.ERR_TEST_CELL_OVERLAP.value, expected_status=409)


# ---------------------------------------------------------------------------
# Queue B — complexity_layers OCC
# ---------------------------------------------------------------------------

def test_occ_stale_quote_approval_returns_412(api):
    """PRD §2.7: "Approving a quote requires the request to carry
    `expected_work_order_version`, the client asserting the work order
    `version` it last observed. If that value does not match the work
    order's current `version` — for example because a re-quote has
    superseded the quoted amounts and advanced the version — the request
    is rejected with `ERR_STALE_VERSION` (HTTP 412)." PRD §3.3: "Re-quoting
    is a self-loop from `QUOTE_SUBMITTED` back to `QUOTE_SUBMITTED` ...
    Because the re-quote again increments `version` by 1, any
    `expected_work_order_version` captured before it no longer matches".

    Design: Corner/complexity_layers/occ_stale_quote_approval_returns_412
    """
    from test_helpers import (
        create_work_order, create_unit, create_customer, create_part,
        make_customer_headers, TECHNICIAN,
    )
    customer = create_customer()
    part = create_part()
    unit = create_unit(part["id"], ownership="CUSTOMER",
                       owner_customer_id=customer["id"])
    wo = create_work_order(customer["id"], unit["id"], work_scope="OVERHAUL")
    api_client.teardown_complete(wo["id"], TECHNICIAN)
    q1 = submit_quote(wo["id"], labor_estimate_cents=2000000,
                      parts_estimate_cents=1000000, scrap_option_ack=False)
    v1 = q1["version"]
    q2 = submit_quote(wo["id"], labor_estimate_cents=2100000,
                      parts_estimate_cents=1000000, scrap_option_ack=False)
    v2 = q2["version"]
    assert v2 == v1 + 1

    # Stale approval: rejected 412 even though the WO is still QUOTE_SUBMITTED.
    res = api.approve_quote(wo["id"],
                            {"expected_work_order_version": v1},
                            make_customer_headers(customer["id"]))
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)

    # Retry with the fresh version: succeeds; the superseding quote is the one approved.
    res2 = api.approve_quote(wo["id"],
                             {"expected_work_order_version": v2},
                             make_customer_headers(customer["id"]))
    approved = validate_success(res2, 200)
    assert approved["status"] == "REPAIR_IN_PROGRESS"
    assert approved["labor_charge_cents"] == 2100000


def test_occ_stale_lease_create_returns_412(api):
    """PRD §2.7: "Creating a lease agreement requires the request to carry
    `expected_unit_version`, the client asserting the component unit
    `version` it last observed. If that value does not match the unit's
    current `version`, the creation is rejected with `ERR_STALE_VERSION`
    (HTTP 412). A prior lease creation legitimately moved the unit to
    `ON_LEASE`, and forward-dated non-overlapping leases remain legal, so
    no state precondition catches the stale writer — only the version check
    does."

    Design: Corner/complexity_layers/occ_stale_lease_create_returns_412
    """
    customer = create_customer()
    part = create_part()
    unit = create_unit(part["id"], serial_number="SN-L1", ownership="SHOP",
                       condition_status="SERVICEABLE", custody_status="IN_POOL",
                       total_cycles=3000, cycles_since_overhaul=50,
                       manufactured_at="2014-03-01")
    v1 = unit["version"]
    lease1 = create_lease(customer["id"], unit["id"], v1,
                          start_date="2026-08-10", end_date="2026-08-14")
    assert lease1["status"] == "ACTIVE"

    # Second create with stale version — forward-dated non-overlapping.
    res = api.create_lease_agreement(
        lease_agreement_payload(customer["id"], unit["id"], v1,
                                start_date="2026-08-20", end_date="2026-08-25"),
        CSR)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)

    # The lease create bumped the unit version by 1 (PRD §3.8).
    unit_after = get_unit(unit["id"])
    assert unit_after["version"] == v1 + 1

    # Retry with the fresh version succeeds.
    res2 = api.create_lease_agreement(
        lease_agreement_payload(customer["id"], unit["id"], unit_after["version"],
                                start_date="2026-08-20", end_date="2026-08-25"),
        CSR)
    lease2 = validate_success(res2, 201)
    assert lease2["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Queue B — lease corners
# ---------------------------------------------------------------------------

def test_lease_return_before_start_rejected(api):
    """PRD §3.8: "Return is a `CustomerServiceRep` action requiring the
    agreement to be `ACTIVE` and the current date to be on or after
    `start_date`; either failure is `ERR_LEASE_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/lease_return_before_start_rejected
    """
    # Lease starts 2026-08-10 but clock still defaults to 2026-08-01.
    customer, part, unit, lease = setup_lease_active(
        lease_overrides={"start_date": "2026-08-10", "end_date": "2026-08-14"})
    res = api.return_lease(lease["id"], CSR)
    validate_error(res, ApiErrorId.ERR_LEASE_INVALID_STATE.value, expected_status=409)

    after = get_lease(lease["id"])
    assert after["status"] == "ACTIVE"


def test_lease_overage_billed_at_1_5x(api):
    """PRD §3.8: "`billed_days` is the inclusive day count from `start_date`
    through the earlier of the return date and `end_date`; `overage_days` is
    the number of whole days by which the return date falls after
    `end_date`, never below zero — a return exactly on `end_date` has zero
    overage days. The base charge is `billed_days` multiplied by
    `daily_rate_cents`; the overage charge is `overage_days` multiplied by
    `daily_rate_cents` multiplied by 1.5, rounded half up to whole cents;
    and `total_charge_cents` is the base plus the overage." Also: "Return
    then moves the unit's custody `ON_LEASE → IN_POOL`, appends a
    `LEASE_RETURN` traceability event, creates an invoice with `source_type`
    `LEASE` in `ISSUED` status whose `total_cents` equals
    `total_charge_cents`".

    Design: Corner/calculations/lease_overage_billed_at_1_5x
    """
    customer, part, unit, lease = setup_lease_active(
        lease_overrides={"start_date": "2026-08-10", "end_date": "2026-08-14",
                         "daily_rate_cents": 100000})
    set_clock("2026-08-16T00:00:00Z")
    returned = return_lease(lease["id"])
    # billed_days = inclusive 10..14 = 5; overage = 16-14 = 2 days
    # base = 500000; overage charge = round_half_up(2 * 100000 * 1.5) = 300000
    assert returned["billed_days"] == 5
    assert returned["overage_days"] == 2
    assert returned["total_charge_cents"] == 800000
    assert returned["status"] == "RETURNED"

    invoices, _ = validate_paginated(api.list_invoices(
        SHOP_MANAGER, params={"lease_agreement_id": lease["id"]}))
    assert len(invoices) == 1
    assert invoices[0]["source_type"] == "LEASE"
    assert invoices[0]["total_cents"] == 800000

    unit_after = get_unit(unit["id"])
    assert unit_after["custody_status"] == "IN_POOL"


def test_lease_on_customer_unit_not_leasable(api):
    """PRD §3.8: "the unit must be leasable — `SHOP`-owned, `SERVICEABLE`,
    in custody `IN_POOL` or `ON_LEASE`, with `end_date` on or after
    `start_date` — otherwise `ERR_UNIT_NOT_LEASABLE` (HTTP 422)."

    Design: Corner/validations/lease_on_customer_unit_not_leasable
    """
    customer = create_customer()
    part = create_part()
    unit = create_unit(part["id"], serial_number="SN-U1", ownership="CUSTOMER",
                       owner_customer_id=customer["id"],
                       condition_status="SERVICEABLE", custody_status="OFF_SITE")
    res = api.create_lease_agreement(
        lease_agreement_payload(customer["id"], unit["id"], unit["version"],
                                start_date="2026-08-10", end_date="2026-08-14"),
        CSR)
    validate_error(res, ApiErrorId.ERR_UNIT_NOT_LEASABLE.value, expected_status=422)

    leases, meta = validate_paginated(api.list_lease_agreements(
        SHOP_MANAGER, params={"unit_id": unit["id"]}))
    assert meta["total_count"] == 0
