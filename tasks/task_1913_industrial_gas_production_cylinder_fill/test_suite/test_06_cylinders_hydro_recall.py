"""Cylinder compliance: hydro boundaries, lifecycle loop, fleet conservation,
lot recall cascade, and quarantine release (PRD §3.2, §3.3, §3.5)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_test_cylinder,
    create_test_customer,
    create_test_fill_lot,
    create_test_rental,
    get_cylinder,
    get_customer,
    get_fill_lot,
    get_rental,
    return_test_rental,
    set_logical_clock,
    setup_planned_lot,
    setup_released_lot,
    validate_error,
    validate_paginated,
    validate_success,
)

OP = TEST_USERS["production_operator_headers"]
QM = TEST_USERS["quality_manager_headers"]
BC = TEST_USERS["billing_clerk_headers"]


# --- Difficulty: boundary_precision_check / hydro_due_today_still_fillable ---

def _setup_hydro_boundary():
    """Two O2 cylinders due 2026-08-10; a PLANNED lot awaiting assignment."""
    ctx = setup_planned_lot(
        num_cylinders=0,
        cylinder_overrides={"last_hydro_date": "2025-08-10"},
    )
    c1 = create_test_cylinder(serial_number="SN-BP1-A", last_hydro_date="2025-08-10")
    c2 = create_test_cylinder(serial_number="SN-BP1-B", last_hydro_date="2025-08-10")
    return ctx, c1, c2


def test_assign_allowed_when_hydro_due_exactly_today(api):
    """PRD §3.2: "A cylinder due exactly today is `DUE_SOON` and remains fillable
    and rentable; only `OVERDUE` blocks, and the gate applies at exactly two
    moments — assignment into a fill lot and rental checkout — where an overdue
    cylinder is rejected with `ERR_HYDRO_RETEST_OVERDUE`."
    PRD §3.2: "The `hydro_status` is then `OVERDUE` when the clock date is
    strictly after the due date, `DUE_SOON` when the due date is today or up to
    30 days in the future, and `COMPLIANT` when it is more than 30 days away."

    Design: Difficulty/boundary_precision_check/hydro_due_today_still_fillable
    """
    ctx, c1, c2 = _setup_hydro_boundary()
    set_logical_clock("2026-08-10T00:00:00Z")
    res = api.assign_cylinder_to_lot(ctx["lot"]["id"], {"cylinder_id": c1["id"]}, OP)
    assigned = validate_success(res, 201)
    assert assigned["status"] == "RESERVED"
    after = get_cylinder(c1["id"])
    assert after["hydro_due_date"] == "2026-08-10"
    assert after["hydro_status"] == "DUE_SOON", "days_to_due == 0 is still fillable"


def test_assign_rejected_one_day_after_hydro_due(api):
    """PRD §3.2: "The `hydro_status` is then `OVERDUE` when the clock date is
    strictly after the due date, `DUE_SOON` when the due date is today or up to
    30 days in the future, and `COMPLIANT` when it is more than 30 days away."
    PRD §3.3: "Assignment is refused with `ERR_FILL_LOT_INVALID_STATE` when the
    lot is not `PLANNED`, with `ERR_CYLINDER_NOT_AVAILABLE` when the cylinder is
    not `IN_STOCK`, with `ERR_HYDRO_RETEST_OVERDUE` when the cylinder is
    hydro-overdue at the clock date, and with `ERR_PRODUCT_SERVICE_MISMATCH` when
    the cylinder's `service_gas` differs from the lot's `product_code`."

    Design: Difficulty/boundary_precision_check/hydro_due_today_still_fillable
    """
    ctx, c1, c2 = _setup_hydro_boundary()
    set_logical_clock("2026-08-11T00:00:00Z")
    overdue = get_cylinder(c2["id"])
    assert overdue["hydro_status"] == "OVERDUE", "2026-08-11 is strictly past the due date"
    res = api.assign_cylinder_to_lot(ctx["lot"]["id"], {"cylinder_id": c2["id"]}, OP)
    validate_error(res, ApiErrorId.ERR_HYDRO_RETEST_OVERDUE.value)
    assert get_cylinder(c2["id"])["status"] == "IN_STOCK"


# --- Difficulty: non_linear_state_machine / cylinder_full_lifecycle_loop ---

def test_cylinder_loop_reenters_reserved_after_return(api):
    """PRD §3.5: "an `OK` return sends it to `IN_STOCK`" (from: "the cylinder's
    disposition depends on the path: an `OK` return sends it to `IN_STOCK`, a
    `DAMAGED` return sends it to `QUARANTINED`, and the return of a `RECALL_HOLD`
    rental sends it to `QUARANTINED` regardless of the declared condition.")
    PRD §3.3: "A successful assignment moves the cylinder from `IN_STOCK` to
    `RESERVED`, sets its `current_fill_lot_id` to the lot, recomputes the lot's
    `draw_estimate_liters`, and increments both the cylinder's and the lot's
    `version`."

    Design: Difficulty/non_linear_state_machine/cylinder_full_lifecycle_loop
    """
    ctx = setup_released_lot(num_cylinders=1)
    cyl = ctx["cylinders"][0]
    customer = create_test_customer(account_name="C-NL2", credit_limit_cents=100000)
    rental = create_test_rental(customer["id"], cyl["id"], daily_rate_cents=1000,
                                planned_days=3)
    assert get_cylinder(cyl["id"])["status"] == "ON_RENT"

    returned = return_test_rental(rental["id"])
    assert returned["status"] == "RETURNED"
    back = get_cylinder(cyl["id"])
    assert back["status"] == "IN_STOCK", "the cylinder completes ON_RENT -> IN_STOCK"

    lot2 = create_test_fill_lot(ctx["tank"]["id"])
    res = api.assign_cylinder_to_lot(lot2["id"], {"cylinder_id": cyl["id"]}, OP)
    reassigned = validate_success(res, 201)
    assert reassigned["status"] == "RESERVED", "the loop re-enters RESERVED"
    assert reassigned["current_fill_lot_id"] == lot2["id"]


def test_cylinder_provenance_last_fill_lot_retained(api):
    """PRD §3.4: "its `last_fill_lot_id` stamped with the lot's identity as
    permanent provenance — that provenance is set at release and never cleared,
    and it is what recall targeting later reads."
    PRD §3.5: "Days out is the whole-day count from `out_date` to the end date
    with the end date exclusive; the overdue day count is the whole days from
    `due_date` to the end date, never below zero."

    Design: Difficulty/non_linear_state_machine/cylinder_full_lifecycle_loop
    """
    ctx = setup_released_lot(num_cylinders=1)
    cyl, lot1 = ctx["cylinders"][0], ctx["lot"]
    customer = create_test_customer(account_name="C-NL2B", credit_limit_cents=100000)
    rental = create_test_rental(customer["id"], cyl["id"], daily_rate_cents=1000,
                                planned_days=3)
    set_logical_clock("2026-08-04T00:00:00Z")
    returned = return_test_rental(rental["id"])
    assert returned["final_charge_cents"] == 3000, "3 days out x 1000, due today"

    lot2 = create_test_fill_lot(ctx["tank"]["id"])
    validate_success(
        api.assign_cylinder_to_lot(lot2["id"], {"cylinder_id": cyl["id"]}, OP), 201
    )
    after = get_cylinder(cyl["id"])
    assert after["current_fill_lot_id"] == lot2["id"]
    assert after["last_fill_lot_id"] == lot1["id"], (
        "provenance survives the second reservation until the second lot releases"
    )


# --- Difficulty: transitive_cascade / fill_lot_recall_chain_depth4 ---

def _setup_recall_scenario():
    """Released lot with 3 cylinders: c1 rented to customer A, c2 rented to
    customer B, c3 FILLED and unrented."""
    ctx = setup_released_lot(num_cylinders=3)
    cust_a = create_test_customer(account_name="C-TC1-A", credit_limit_cents=100000)
    cust_b = create_test_customer(account_name="C-TC1-B", credit_limit_cents=100000)
    r1 = create_test_rental(cust_a["id"], ctx["cylinders"][0]["id"],
                            daily_rate_cents=1000, planned_days=5)
    r2 = create_test_rental(cust_b["id"], ctx["cylinders"][1]["id"],
                            daily_rate_cents=1000, planned_days=5)
    return ctx, cust_a, cust_b, r1, r2


def test_recall_quarantines_filled_and_rented_cylinders(api):
    """PRD §3.3: "Recall is terminal — the lot lands in `RECALLED` — and fires a
    four-link cascade: every cylinder whose `last_fill_lot_id` equals the
    recalled lot and whose status is `FILLED` or `ON_RENT` moves to
    `QUARANTINED`; every rental in `ACTIVE` or `OVERDUE` whose cylinder was just
    quarantined moves to `RECALL_HOLD`; and every customer account owning a
    rental that just entered `RECALL_HOLD` has its `recall_flag` set to true."

    Design: Difficulty/transitive_cascade/fill_lot_recall_chain_depth4
    """
    ctx, cust_a, cust_b, r1, r2 = _setup_recall_scenario()
    recalled = validate_success(api.recall_fill_lot(ctx["lot"]["id"], QM), 200)
    assert recalled["status"] == "RECALLED"
    for cyl in ctx["cylinders"]:
        after = get_cylinder(cyl["id"])
        assert after["status"] == "QUARANTINED", (
            "both ON_RENT cylinders and the FILLED-but-unrented one are swept"
        )


def test_recall_holds_rentals_and_flags_customers(api):
    """PRD §3.3: "every rental in `ACTIVE` or `OVERDUE` whose cylinder was just
    quarantined moves to `RECALL_HOLD`; and every customer account owning a
    rental that just entered `RECALL_HOLD` has its `recall_flag` set to true."

    Design: Difficulty/transitive_cascade/fill_lot_recall_chain_depth4
    """
    ctx, cust_a, cust_b, r1, r2 = _setup_recall_scenario()
    validate_success(api.recall_fill_lot(ctx["lot"]["id"], QM), 200)
    for rental in (r1, r2):
        assert get_rental(rental["id"])["status"] == "RECALL_HOLD"
    for customer in (cust_a, cust_b):
        assert get_customer(customer["id"])["recall_flag"] is True


# --- Difficulty: priority_pair_validation_conflict / assign_conflict_state_beats_safety ---

def _setup_on_rent_overdue_cylinder():
    """Cylinder filled and rented while hydro-compliant (due 2026-08-15); clock
    advanced to 2026-08-20 so it is simultaneously ON_RENT and hydro OVERDUE."""
    ctx = setup_released_lot(
        num_cylinders=1, cylinder_overrides={"last_hydro_date": "2025-08-15"}
    )
    cyl = ctx["cylinders"][0]
    customer = create_test_customer(account_name="C-PP1", credit_limit_cents=100000)
    create_test_rental(customer["id"], cyl["id"], daily_rate_cents=1000,
                       planned_days=10)
    set_logical_clock("2026-08-20T00:00:00Z")
    probe = get_cylinder(cyl["id"])
    assert probe["status"] == "ON_RENT"
    assert probe["hydro_status"] == "OVERDUE", "due 2026-08-15 < clock 2026-08-20"
    lot2 = create_test_fill_lot(ctx["tank"]["id"])
    return ctx, cyl, lot2


def test_assign_conflict_state_beats_safety_error(api):
    """PRD §2.8: "When several checks could reject the same request, the
    rejection reported is the earliest applicable check in the order below — a
    state-gate failure, for instance, masks a hydro-compliance failure that would
    also have fired." (State gates are check 5; hydrostatic compliance is
    check 6.)
    PRD §3.3: "Assignment is refused with ... `ERR_CYLINDER_NOT_AVAILABLE` when
    the cylinder is not `IN_STOCK`, with `ERR_HYDRO_RETEST_OVERDUE` when the
    cylinder is hydro-overdue at the clock date"

    Design: Difficulty/priority_pair_validation_conflict/assign_conflict_state_beats_safety
    """
    ctx, cyl, lot2 = _setup_on_rent_overdue_cylinder()
    res = api.assign_cylinder_to_lot(lot2["id"], {"cylinder_id": cyl["id"]}, OP)
    # Both conditions hold; the earlier state gate must be reported.
    validate_error(res, ApiErrorId.ERR_CYLINDER_NOT_AVAILABLE.value)


def test_assign_conflict_leaves_cylinder_and_lot_unchanged(api):
    """PRD §2.8: "When several checks could reject the same request, the
    rejection reported is the earliest applicable check in the order below"
    PRD §3.3: "The estimate is recomputed on every assignment into the lot and on
    every release out of it." — a rejected assignment is neither, so the lot's
    estimate stays at zero.

    Design: Difficulty/priority_pair_validation_conflict/assign_conflict_state_beats_safety
    """
    ctx, cyl, lot2 = _setup_on_rent_overdue_cylinder()
    res = api.assign_cylinder_to_lot(lot2["id"], {"cylinder_id": cyl["id"]}, OP)
    validate_error(res, ApiErrorId.ERR_CYLINDER_NOT_AVAILABLE.value)
    cyl_after = get_cylinder(cyl["id"])
    assert cyl_after["status"] == "ON_RENT"
    assert cyl_after["current_fill_lot_id"] is None
    lot_after = get_fill_lot(lot2["id"])
    assert lot_after["status"] == "PLANNED"
    assert lot_after["draw_estimate_liters"] == pytest.approx(0.0, abs=0.01)


# --- Difficulty: compensating_invariant / fleet_count_conserved_across_checkout_return ---

def _fleet_counts(api):
    data, meta = validate_paginated(api.list_cylinders(BC, params={"limit": 100}))
    counts = {}
    for cyl in data:
        counts[cyl["status"]] = counts.get(cyl["status"], 0) + 1
    non_terminal = sum(
        n for status, n in counts.items() if status not in ("LOST", "RETIRED")
    )
    return counts, non_terminal


def test_checkout_and_return_change_status_multiset(api):
    """PRD §3.5: "On success the rental starts `ACTIVE`, the cylinder moves from
    `FILLED` to `ON_RENT` with a `version` increment"
    PRD §3.5: "the cylinder's disposition depends on the path: an `OK` return
    sends it to `IN_STOCK`, a `DAMAGED` return sends it to `QUARANTINED`, and the
    return of a `RECALL_HOLD` rental sends it to `QUARANTINED` regardless of the
    declared condition."

    Design: Difficulty/compensating_invariant/fleet_count_conserved_across_checkout_return
    """
    ctx = setup_released_lot(num_cylinders=2)
    create_test_cylinder(serial_number="SN-CI3-C", size_code="SMALL")
    customer = create_test_customer(account_name="C-CI3", credit_limit_cents=100000)

    before, total_before = _fleet_counts(api)
    assert before.get("FILLED") == 2 and before.get("IN_STOCK") == 1
    assert total_before == 3

    rental = create_test_rental(customer["id"], ctx["cylinders"][0]["id"],
                                daily_rate_cents=1000, planned_days=3)
    mid, total_mid = _fleet_counts(api)
    assert mid.get("FILLED") == 1 and mid.get("ON_RENT") == 1
    assert mid.get("IN_STOCK") == 1

    return_test_rental(rental["id"])
    after, total_after = _fleet_counts(api)
    assert after.get("FILLED") == 1 and after.get("IN_STOCK") == 2
    assert "LOST" not in after and "RETIRED" not in after


def test_non_terminal_fleet_count_conserved(api):
    """PRD §3.2: "a `QualityManager` may decommission an in-plant cylinder with a
    `disposition` of `LOST` or `RETIRED`, permitted only from `IN_STOCK` or
    `QUARANTINED`; both dispositions are terminal states for the asset." — the
    checkout/return pair never routes through those terminal states, so the
    non-terminal count is conserved at 3.

    Design: Difficulty/compensating_invariant/fleet_count_conserved_across_checkout_return
    """
    ctx = setup_released_lot(num_cylinders=2)
    create_test_cylinder(serial_number="SN-CI3-D", size_code="SMALL")
    customer = create_test_customer(account_name="C-CI3B", credit_limit_cents=100000)

    _, total0 = _fleet_counts(api)
    rental = create_test_rental(customer["id"], ctx["cylinders"][0]["id"],
                                daily_rate_cents=1000, planned_days=3)
    _, total1 = _fleet_counts(api)
    return_test_rental(rental["id"])
    _, total2 = _fleet_counts(api)
    assert total0 == total1 == total2 == 3, (
        "count(status NOT IN {LOST, RETIRED}) is invariant across the pair"
    )


# --- Corner: calculations / hydro_interval_differs_by_gas ---

def test_hydro_interval_differs_by_gas(api):
    """PRD §3.2: "The `hydro_due_date` is computed by adding the retest interval
    for the cylinder's `service_gas` to its `last_hydro_date` — 6 months for
    `CO2`, 12 months for every other gas — with the day clamped to the target
    month's last day when the computed day does not exist in that month."
    PRD §3.2: "The `hydro_status` is then `OVERDUE` when the clock date is
    strictly after the due date, `DUE_SOON` when the due date is today or up to
    30 days in the future, and `COMPLIANT` when it is more than 30 days away."

    Design: Corner/calculations/hydro_interval_differs_by_gas
    """
    co2 = create_test_cylinder(serial_number="SN-CA5-A", service_gas="CO2",
                               last_hydro_date="2026-02-01")
    assert co2["hydro_due_date"] == "2026-08-01"
    assert co2["hydro_status"] == "DUE_SOON", "due exactly today at the default clock"

    o2 = create_test_cylinder(serial_number="SN-CA5-B", service_gas="O2",
                              last_hydro_date="2026-02-01")
    assert o2["hydro_due_date"] == "2027-02-01"
    assert o2["hydro_status"] == "COMPLIANT"


# --- Corner: state_machines / quarantine_release_returns_cylinder_to_stock ---

def test_quarantine_release_returns_cylinder_to_stock(api):
    """PRD §3.2: "A passed retest sets `last_hydro_date` to the test date,
    recomputes `hydro_due_date`, and leaves a quarantined cylinder in
    `QUARANTINED` — release is a separate quality action — while a failed retest
    drives the cylinder into `QUARANTINED`; either way the cylinder's `version`
    increments."
    PRD §3.2: "A `QualityManager` may release a quarantined cylinder back to
    `IN_STOCK`, but only when its `current_fill_lot_id` is null or references a
    lot in `VENTED` or `RECALLED` state; otherwise the release is rejected with
    `ERR_CYLINDER_NOT_AVAILABLE`. A successful release clears
    `current_fill_lot_id` and increments `version`."

    Design: Corner/state_machines/quarantine_release_returns_cylinder_to_stock
    """
    cyl = create_test_cylinder(serial_number="SN-SM6-A")
    failed = validate_success(
        api.record_hydro_retest(cyl["id"],
                                {"test_date": "2026-08-01", "result": "FAIL"}, OP),
        200,
    )
    assert failed["status"] == "QUARANTINED"

    released = validate_success(api.release_quarantine(cyl["id"], QM), 200)
    assert released["status"] == "IN_STOCK"
    assert released["current_fill_lot_id"] is None
