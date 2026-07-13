"""Occupancy and tenant chargeback: the conserved occupancy share, the fully-closed
allocation interval with aggregate capacity, and the statement money lines whose
per-line rounding order decides the cents.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_lease,
    assert_lease_allocation,
    assert_space,
    assert_space_share_invariant,
    assert_statement,
    assert_statement_total_invariant,
    assert_work_order,
    allocation_payload,
    create_allocation,
    create_building,
    create_lease,
    create_space,
    create_statement,
    create_utility_reading,
    dispute_statement,
    issue_statement,
    read_lease,
    read_lease_version,
    read_space,
    read_statement,
    read_work_order,
    set_clock,
    setup_active_lease,
    setup_disputed_statement_with_extra_reading,
    setup_lease_over_two_spaces,
    setup_lease_with_collectable_work_order,
    statement_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

FM = TEST_USERS["facility_manager_headers"]
FC = TEST_USERS["finance_controller_headers"]
SA = TEST_USERS["sustainability_analyst_headers"]

MAY_START = "2026-05-01T00:00:00Z"
MAY_END = "2026-05-31T23:59:59Z"


# ---------------------------------------------------------------------------
# The conserved occupancy share
# ---------------------------------------------------------------------------
def test_allocating_a_share_reduces_free_share_and_sets_the_lease_area(api):
    """PRD §2.10: "The first is space occupancy. For any space, `allocated_share_pct`
    and `free_share_pct` always sum to exactly 100, after every allocation and after
    every release."
    PRD §3.9: "`allocated_share_pct` is the sum of `share_pct` across the space's
    `ACTIVE` allocations whose closed interval covers today's clock date, rounded half
    up to 2 decimal places; `free_share_pct` is 100 less that figure, likewise rounded;
    and `occupancy_status` is `OCCUPIED` when the allocated share is greater than zero
    and `VACANT` otherwise."
    PRD §3.9: "The lease's `allocated_area_sqm` is recomputed at the same time as the
    sum, over the lease's `ACTIVE` allocations, of each allocated space's `area_sqm`
    multiplied by that allocation's `share_pct` divided by 100, with the sum rounded half
    up to 2 decimal places at the end."

    Design: Difficulty/compensating_invariant/occupancy_share_conserved_across_allocation_create_and_release
    """
    set_clock("2026-05-15T09:00:00Z")
    building = create_building()
    space = create_space(building["id"], space_code="S1", area_sqm=200,
                         space_type="OFFICE")
    lease = create_lease(building["id"])

    allocation = validate_success(
        api.create_allocation(
            lease["id"],
            allocation_payload(space["id"], share_pct=40,
                               effective_from="2026-05-01T00:00:00Z",
                               effective_to="2027-04-30T23:59:59Z"),
            FC,
        ),
        201,
    )
    assert_lease_allocation(allocation)
    assert allocation["status"] == "ACTIVE"

    occupied = read_space(space["id"])
    assert_space(occupied)
    assert occupied["allocated_share_pct"] == pytest.approx(40, abs=0.01)
    assert occupied["free_share_pct"] == pytest.approx(60, abs=0.01)
    assert occupied["occupancy_status"] == "OCCUPIED"
    assert_space_share_invariant(occupied)

    leased = read_lease(lease["id"])
    assert_lease(leased)
    assert leased["allocated_area_sqm"] == pytest.approx(80.00, abs=0.01), (
        "200 sqm at a 40% share"
    )


def test_releasing_an_allocation_restores_the_free_share_exactly(api):
    """PRD §3.9: "Releasing an allocation is a soft delete: the row is retained but its
    `status` moves `ACTIVE → RELEASED`. A released allocation is excluded from every
    derived figure immediately, so a release restores the space's `free_share_pct` to
    exactly the value it had before the allocation was made."
    PRD §2.10: "The first is space occupancy. For any space, `allocated_share_pct` and
    `free_share_pct` always sum to exactly 100, after every allocation and after every
    release."

    Design: Difficulty/compensating_invariant/occupancy_share_conserved_across_allocation_create_and_release
    """
    set_clock("2026-05-15T09:00:00Z")
    building = create_building()
    space = create_space(building["id"], space_code="S1", area_sqm=200,
                         space_type="OFFICE")
    lease = create_lease(building["id"])
    allocation = create_allocation(
        lease["id"], space["id"], share_pct=40,
        effective_from="2026-05-01T00:00:00Z", effective_to="2027-04-30T23:59:59Z",
    )

    released = validate_success(api.release_allocation(allocation["id"], FC))
    assert released["status"] == "RELEASED", "the row is retained, not deleted"

    space_now = read_space(space["id"])
    assert space_now["allocated_share_pct"] == pytest.approx(0, abs=0.01)
    assert space_now["free_share_pct"] == pytest.approx(100, abs=0.01)
    assert space_now["occupancy_status"] == "VACANT"
    assert_space_share_invariant(space_now)

    assert read_lease(lease["id"])["allocated_area_sqm"] == pytest.approx(0, abs=0.01)


# ---------------------------------------------------------------------------
# The fully-closed allocation interval and aggregate capacity
# ---------------------------------------------------------------------------
def _space_with_sixty_percent_allocated():
    set_clock("2026-05-15T09:00:00Z")
    building = create_building()
    space = create_space(building["id"], space_code="S1", area_sqm=100,
                         space_type="OFFICE")
    lease_a = create_lease(building["id"], tenant_name="Alpha",
                           start_date="2026-05-01T00:00:00Z",
                           end_date="2026-05-31T23:59:59Z")
    lease_b = create_lease(building["id"], tenant_name="Bravo",
                           start_date="2026-05-31T00:00:00Z",
                           end_date="2026-06-30T23:59:59Z")
    create_allocation(lease_a["id"], space["id"], share_pct=60,
                      effective_from="2026-05-01T00:00:00Z",
                      effective_to="2026-05-31T23:59:59Z")
    return building, space, lease_a, lease_b


def test_touching_date_pushes_the_aggregate_share_over_one_hundred(api):
    """PRD §3.9: "Unlike a soft-service shift, this interval is **fully closed**: both
    endpoints belong to the interval, so an allocation that starts on exactly the day an
    existing allocation ends *does* cover a shared date, and both allocations are
    considered to be covering it."
    PRD §3.9: "The capacity rule is aggregate, not exclusive. Two leases may hold shares
    of the same space over the same dates, provided the shares fit: for every date inside
    the new allocation's closed interval, the sum of `share_pct` across the space's
    `ACTIVE` allocations whose own closed intervals cover that date, plus the new
    `share_pct`, must not exceed 100. If it would exceed 100 on any single date, the
    request is refused with `ERR_SPACE_SHARE_EXCEEDED` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/allocation_closed_interval_touching_date_aggregate_capacity
    """
    _, space, _, lease_b = _space_with_sixty_percent_allocated()

    response = api.create_allocation(
        lease_b["id"],
        allocation_payload(space["id"], share_pct=50,
                           effective_from="2026-05-31T00:00:00Z",
                           effective_to="2026-06-30T23:59:59Z"),
        FC,
    )
    validate_error(response, ApiErrorId.ERR_SPACE_SHARE_EXCEEDED.value)
    assert response.status_code == 422, (
        "on the shared date 2026-05-31 the closed intervals overlap: 60 + 50 = 110"
    )


def test_touching_date_at_exactly_one_hundred_percent_is_accepted(api):
    """PRD §3.9: "The capacity rule is aggregate, not exclusive. Two leases may hold
    shares of the same space over the same dates, provided the shares fit: for every date
    inside the new allocation's closed interval, the sum of `share_pct` across the space's
    `ACTIVE` allocations whose own closed intervals cover that date, plus the new
    `share_pct`, must not exceed 100. If it would exceed 100 on any single date, the
    request is refused with `ERR_SPACE_SHARE_EXCEEDED` (HTTP 422)."
    PRD §3.9: "`allocated_share_pct` is the sum of `share_pct` across the space's
    `ACTIVE` allocations whose closed interval covers today's clock date, rounded half up
    to 2 decimal places; `free_share_pct` is 100 less that figure, likewise rounded; and
    `occupancy_status` is `OCCUPIED` when the allocated share is greater than zero and
    `VACANT` otherwise."

    Design: Difficulty/resource_temporal_overlap/allocation_closed_interval_touching_date_aggregate_capacity
    """
    _, space, _, lease_b = _space_with_sixty_percent_allocated()

    allocation = validate_success(
        api.create_allocation(
            lease_b["id"],
            allocation_payload(space["id"], share_pct=40,
                               effective_from="2026-05-31T00:00:00Z",
                               effective_to="2026-06-30T23:59:59Z"),
            FC,
        ),
        201,
    )
    assert allocation["status"] == "ACTIVE", "60 + 40 lands exactly on the capacity edge"

    # The clock reads 2026-05-15, a date only the first allocation's interval covers.
    space_now = read_space(space["id"])
    assert space_now["allocated_share_pct"] == pytest.approx(60, abs=0.01)
    assert space_now["free_share_pct"] == pytest.approx(40, abs=0.01)
    assert space_now["occupancy_status"] == "OCCUPIED"


# ---------------------------------------------------------------------------
# Statement money lines: rounding order decides the cents
# ---------------------------------------------------------------------------
def test_utility_share_is_rounded_per_line_before_it_is_summed(api):
    """PRD §3.9: "`utility_share` is likewise computed **per allocation line and rounded
    per line, then summed**. First total the `cost` of the building's utility readings
    whose own inclusive `period_start`-to-`period_end` window is *fully contained* within
    the statement period, both ends inclusive — a reading that straddles the boundary is
    not counted at all, and all three meter types count towards this total. Then for each
    relevant allocation, take that total utility cost, multiply it by the allocation's
    allocated area (the space's `area_sqm` multiplied by the allocation's `share_pct`
    divided by 100) divided by the building's `gross_area_sqm`, and round the result half
    up to 2 decimal places. Sum those rounded line figures."
    PRD §2.9: "This matters most in the chargeback computation, where rounding happens per
    line and the lines are then summed — summing first and rounding once produces a
    different total whenever two lines carry a repeating fraction, and it is wrong."

    Design: Difficulty/combinatorial_formula/statement_round_per_line_then_sum_not_sum_then_round
    """
    ctx = setup_lease_over_two_spaces(clock="2026-05-15T09:00:00Z",
                                      gross_area_sqm=3000, space_area_sqm=100)
    create_utility_reading(ctx["building"]["id"], meter_type="ELECTRIC",
                           period_start=MAY_START, period_end=MAY_END,
                           consumption_kwh=4000, cost=1000.00)

    statement = create_statement(ctx["lease"]["id"], MAY_START, MAY_END)
    assert_statement(statement)

    # Each of the two allocation lines pro-rates 1000.00 over 100/3000 of the building:
    # round(33.3333..., 2) = 33.33 per line, summed to 66.66.
    # Summing first (66.6666...) and rounding once would give 66.67 — and is wrong.
    assert statement["utility_share"] == pytest.approx(66.66, abs=0.001)
    assert statement["utility_share"] != pytest.approx(66.67, abs=0.001)


def test_statement_total_is_the_sum_of_the_already_rounded_lines(api):
    """PRD §3.9: "`base_rent` is computed **per allocation line and rounded per line,
    then summed**. For each such allocation, take the allocated space's `area_sqm`,
    multiply by that allocation's `share_pct` divided by 100, multiply by the lease's
    `base_rate_per_sqm_month`, and round the result half up to 2 decimal places. Sum those
    rounded line figures."
    PRD §3.9: "`total_amount` is the sum of the three already-rounded figures —
    `base_rent` plus `utility_share` plus `om_share` — rounded half up to 2 decimal
    places. There is no further rounding pass over the underlying lines; summing the raw
    lines and rounding once at the end is a different number and it is wrong."

    Design: Difficulty/combinatorial_formula/statement_round_per_line_then_sum_not_sum_then_round
    """
    ctx = setup_lease_over_two_spaces(clock="2026-05-15T09:00:00Z",
                                      gross_area_sqm=3000, space_area_sqm=100)
    create_utility_reading(ctx["building"]["id"], meter_type="ELECTRIC",
                           period_start=MAY_START, period_end=MAY_END,
                           consumption_kwh=4000, cost=1000.00)

    statement = create_statement(ctx["lease"]["id"], MAY_START, MAY_END)

    # Two base-rent lines of round(100 sqm * 100% * 10.00, 2) = 1000.00 each.
    assert statement["base_rent"] == pytest.approx(2000.00, abs=0.01)
    assert statement["om_share"] == pytest.approx(0.00, abs=0.01), (
        "no closed chargeable work orders exist in the period"
    )
    assert statement["total_amount"] == pytest.approx(2066.66, abs=0.001)
    assert statement["status"] == "DRAFT"
    assert_statement_total_invariant(statement)


def test_reissue_from_disputed_recomputes_the_money_lines_from_current_data(api):
    """PRD §3.9: "Issuing again from `DISPUTED` moves it `DISPUTED → ISSUED`, re-stamps
    `issued_at`, retains the `dispute_reason`, and — crucially — recomputes `base_rent`,
    `utility_share`, `om_share`, and `total_amount` from scratch against current data, so
    a genuine correction upstream is reflected in the re-issued figures."

    Design: Difficulty/non_linear_state_machine/statement_issue_dispute_reissue_cycle_recomputes_totals
    """
    ctx = setup_disputed_statement_with_extra_reading()
    assert ctx["statement"]["status"] == "DISPUTED"
    assert ctx["statement"]["utility_share"] == pytest.approx(66.66, abs=0.001)

    reissued = validate_success(api.issue_statement(ctx["statement"]["id"], FC))
    assert_statement(reissued)

    # The utility total is now 1000.00 + 500.00 = 1500.00, so each of the two
    # allocation lines pro-rates round(1500.00 * 100/3000, 2) = 50.00.
    assert reissued["utility_share"] == pytest.approx(100.00, abs=0.01)
    assert reissued["base_rent"] == pytest.approx(2000.00, abs=0.01)
    assert reissued["total_amount"] == pytest.approx(2100.00, abs=0.01)
    assert_statement_total_invariant(reissued)


def test_reissue_from_disputed_returns_to_issued_and_retains_the_reason(api):
    """PRD §3.9: "A `TenantRep` — and only the one whose lease this is — may dispute an
    `ISSUED` statement by supplying a `dispute_reason`, moving it `ISSUED → DISPUTED` and
    recording the reason."
    PRD §3.9: "Issuing again from `DISPUTED` moves it `DISPUTED → ISSUED`, re-stamps
    `issued_at`, retains the `dispute_reason`, and — crucially — recomputes `base_rent`,
    `utility_share`, `om_share`, and `total_amount` from scratch against current data, so
    a genuine correction upstream is reflected in the re-issued figures."

    Design: Difficulty/non_linear_state_machine/statement_issue_dispute_reissue_cycle_recomputes_totals
    """
    ctx = setup_disputed_statement_with_extra_reading()
    assert ctx["statement"]["dispute_reason"] == "Utility pro-rata looks wrong"

    reissued = validate_success(api.issue_statement(ctx["statement"]["id"], FC))

    assert reissued["status"] == "ISSUED", "the ISSUED → DISPUTED → ISSUED cycle closed"
    assert reissued["dispute_reason"] == "Utility pro-rata looks wrong", (
        "the reason is retained across the re-issue"
    )
    assert reissued["issued_at"] is not None


# ---------------------------------------------------------------------------
# Statements depend on the lease's own state
# ---------------------------------------------------------------------------
def test_drafting_a_statement_against_a_draft_lease_is_refused(api):
    """PRD §3.9: "The lease must be `ACTIVE`, or the request is refused with
    `ERR_LEASE_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/statement_creation_depends_on_lease_status
    """
    set_clock("2026-05-15T09:00:00Z")
    building = create_building()
    space = create_space(building["id"], space_code="S1", area_sqm=100,
                         space_type="OFFICE")
    lease = create_lease(building["id"])
    create_allocation(lease["id"], space["id"], share_pct=100)
    draft_version = read_lease(lease["id"])["version"]
    assert read_lease(lease["id"])["status"] == "DRAFT"

    response = api.create_statement(
        lease["id"], statement_payload(MAY_START, MAY_END, draft_version), FC
    )
    validate_error(response, ApiErrorId.ERR_LEASE_NOT_ACTIVE.value)
    assert response.status_code == 409


def test_the_same_statement_succeeds_once_the_lease_is_activated(api):
    """PRD §3.9: "A `DRAFT` lease is activated by a `FinanceController` or
    `PlatformAdmin`, moving it `DRAFT → ACTIVE` and incrementing the lease's `version` by
    1."
    PRD §3.9: "`base_rent` is computed **per allocation line and rounded per line, then
    summed**. For each such allocation, take the allocated space's `area_sqm`, multiply by
    that allocation's `share_pct` divided by 100, multiply by the lease's
    `base_rate_per_sqm_month`, and round the result half up to 2 decimal places. Sum those
    rounded line figures."

    Design: Difficulty/cross_entity_state_dependency/statement_creation_depends_on_lease_status
    """
    ctx = setup_active_lease(clock="2026-05-15T09:00:00Z", gross_area_sqm=1000,
                             space_area_sqm=100, share_pct=100)
    assert ctx["lease"]["status"] == "ACTIVE"

    statement = validate_success(
        api.create_statement(
            ctx["lease"]["id"],
            statement_payload(MAY_START, MAY_END, read_lease_version(ctx["lease"]["id"])),
            FC,
        ),
        201,
    )
    assert_statement(statement)
    # One line: round(100 sqm * 100% * 10.00, 2) = 1000.00; nothing else to bill.
    assert statement["base_rent"] == pytest.approx(1000.00, abs=0.01)
    assert statement["total_amount"] == pytest.approx(1000.00, abs=0.01)


# ---------------------------------------------------------------------------
# What a statement collects, and what it may not
# ---------------------------------------------------------------------------
def test_om_share_is_pro_rated_by_the_leases_allocated_area(api):
    """PRD §3.9: "`om_share` is computed **per work order and rounded per work order,
    then summed**. Let the lease's share of the building be its `allocated_area_sqm`
    divided by the building's `gross_area_sqm`. The collectable orders are those of the
    same building whose `status` is `CLOSED`, whose `billing_status` is `PENDING`, whose
    `chargeable` flag is true, and whose `closed_at` falls within the statement period,
    both ends inclusive. For each such order, multiply its `billable_amount` by the
    lease's share, round the result half up to 2 decimal places, and sum those rounded
    figures. Orders that are `WAIVED`, already `INVOICED`, or already
    `SETTLED_CHARGEBACK` are never re-collected."
    PRD §3.9: "Every work order the statement collects moves its `billing_status`
    `PENDING → INVOICED` and records the statement's identifier in its `statement_id`."

    Design: Corner/calculations/statement_om_share_pro_rated_by_allocated_area
    """
    ctx = setup_lease_with_collectable_work_order(clock="2026-05-10T09:00:00Z")
    assert ctx["work_order"]["billable_amount"] == pytest.approx(200.00, abs=0.01)

    statement = create_statement(ctx["lease"]["id"], MAY_START, MAY_END)
    assert_statement(statement)

    # The lease holds 100 sqm of a 1000 sqm building, so its share is 0.10:
    # round(200.00 * 100/1000, 2) = 20.00.
    assert statement["om_share"] == pytest.approx(20.00, abs=0.01)
    assert statement["base_rent"] == pytest.approx(1000.00, abs=0.01)
    assert statement["utility_share"] == pytest.approx(0.00, abs=0.01)
    assert statement["total_amount"] == pytest.approx(1020.00, abs=0.01)

    collected = read_work_order(ctx["work_order"]["id"])
    assert_work_order(collected)
    assert collected["billing_status"] == "INVOICED"
    assert collected["statement_id"] == statement["id"]


def test_statement_period_spanning_two_calendar_months_is_refused(api):
    """PRD §3.9: "The `FinanceController` or `PlatformAdmin` supplies the `period_start`
    and `period_end`, which must be exactly the first and last instant of one and the same
    calendar month — anything else is refused with `ERR_STATEMENT_PERIOD_INVALID` (HTTP
    422) — plus the `expected_lease_version` that §2.7 requires."

    Design: Corner/validations/statement_period_not_a_calendar_month_rejected
    """
    ctx = setup_active_lease(clock="2026-05-15T09:00:00Z", gross_area_sqm=1000,
                             space_area_sqm=100, share_pct=100)

    response = api.create_statement(
        ctx["lease"]["id"],
        statement_payload(MAY_START, "2026-06-15T23:59:59Z",
                          read_lease_version(ctx["lease"]["id"])),
        FC,
    )
    validate_error(response, ApiErrorId.ERR_STATEMENT_PERIOD_INVALID.value)
    assert response.status_code == 422

    _, meta = validate_paginated(api.list_lease_statements(ctx["lease"]["id"], FC))
    assert meta["total_count"] == 0


def test_second_statement_for_an_issued_period_is_a_duplicate(api):
    """PRD §3.9: "If a statement for the same lease and the same `period_start` already
    exists with a status of `ISSUED`, `DISPUTED`, or `SETTLED`, the new statement is
    refused with `ERR_STATEMENT_PERIOD_DUPLICATE` (HTTP 409)."
    PRD §3.9: "Issuing a `DRAFT` statement moves it `DRAFT → ISSUED` and stamps
    `issued_at` from the logical clock; the lease must still be `ACTIVE` or the issue is
    refused with `ERR_LEASE_NOT_ACTIVE`."

    Design: Corner/validations/second_statement_for_issued_period_rejected_as_duplicate
    """
    ctx = setup_active_lease(clock="2026-05-15T09:00:00Z", gross_area_sqm=1000,
                             space_area_sqm=100, share_pct=100)
    first = create_statement(ctx["lease"]["id"], MAY_START, MAY_END)
    issue_statement(first["id"])

    response = api.create_statement(
        ctx["lease"]["id"],
        statement_payload(MAY_START, MAY_END, read_lease_version(ctx["lease"]["id"])),
        FC,
    )
    validate_error(response, ApiErrorId.ERR_STATEMENT_PERIOD_DUPLICATE.value)
    assert response.status_code == 409

    assert read_statement(first["id"])["status"] == "ISSUED"
    _, meta = validate_paginated(api.list_lease_statements(ctx["lease"]["id"], FC))
    assert meta["total_count"] == 1


def test_activating_a_lease_with_no_allocation_is_refused(api):
    """PRD §3.9: "A lease may only be activated if it is in `DRAFT` and it already holds
    at least one `ACTIVE` allocation; both an activation attempt on a non-`DRAFT` lease
    and an activation attempt on a `DRAFT` lease with no active allocation are refused
    with `ERR_LEASE_NOT_DRAFT` (HTTP 409)."

    Design: Corner/validations/lease_activate_without_allocation_rejected
    """
    building = create_building()
    lease = create_lease(building["id"])

    response = api.activate_lease(lease["id"], FC)
    validate_error(response, ApiErrorId.ERR_LEASE_NOT_DRAFT.value)
    assert response.status_code == 409

    reread = read_lease(lease["id"])
    assert reread["status"] == "DRAFT"
    assert reread["allocated_area_sqm"] == pytest.approx(0, abs=0.01)


def test_a_superseding_statement_voids_the_draft_and_recollects_its_orders(api):
    """PRD §3.9: "If the existing statement for that period is still in `DRAFT`, however,
    it is not an obstacle: it moves `DRAFT → VOID`, and every work order carrying that
    voided statement's identifier reverts its `billing_status` `INVOICED → PENDING` with
    its `statement_id` cleared, so that the superseding statement may collect those orders
    afresh."
    PRD §3.9: "Every work order the statement collects moves its `billing_status`
    `PENDING → INVOICED` and records the statement's identifier in its `statement_id`."

    Design: Corner/cross_cutting_layers/statement_supersede_voids_draft_and_returns_orders_to_pending
    """
    ctx = setup_lease_with_collectable_work_order(clock="2026-05-10T09:00:00Z")
    first = create_statement(ctx["lease"]["id"], MAY_START, MAY_END)
    assert read_work_order(ctx["work_order"]["id"])["statement_id"] == first["id"]

    second = create_statement(ctx["lease"]["id"], MAY_START, MAY_END)

    assert read_statement(first["id"])["status"] == "VOID"
    assert second["status"] == "DRAFT"
    assert second["om_share"] == pytest.approx(20.00, abs=0.01), (
        "the released order is re-collected, not lost"
    )
    assert second["total_amount"] == pytest.approx(1020.00, abs=0.01)

    order = read_work_order(ctx["work_order"]["id"])
    assert order["billing_status"] == "INVOICED"
    assert order["statement_id"] == second["id"], "never double-billed"

    _, meta = validate_paginated(
        api.list_work_orders(FC, params={"statement_id": first["id"]})
    )
    assert meta["total_count"] == 0
