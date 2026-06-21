"""Validation precedence, numeric/empty-set boundaries, cross-entity gates, intervals.

Queue A (Difficulty) translations: priority_pair_validation_conflict,
boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    TEST_USERS, make_tenant_headers,
    setup_auction_scheduled, setup_delinquent_past_90, setup_activated,
    set_clock, pay,
    create_facility, create_unit, create_tenant, create_lease, create_insurance_policy,
    api_client,
)

FM = TEST_USERS["facility_manager_headers"]
LIEN = TEST_USERS["lien_administrator_headers"]


# ─── priority_pair_validation_conflict / state (5) beats fiscal (11) ───

def test_redeem_sold_proceeding_returns_invalid_state(api):
    """PRD §3.9: "Redemption is defined while the proceeding is in `NOTICE_SENT`,
    `LIEN_FILED`, or `SCHEDULED` status."
    PRD §2.8: "For state-transition endpoints, the target resource being in a state from
    which the requested transition is not defined is checked fifth, giving
    `ERR_INVALID_STATE` (HTTP 409). Beyond these, the domain-specific business rules
    described in §3 apply."

    Design: Difficulty/priority_pair_validation_conflict/priority_state_beats_fiscal_on_redeem_terminal_lease
    """
    # Complete the sale first so the proceeding is SOLD (terminal). Balance is then 0,
    # but the state check (priority 5) precedes the fiscal balance check (priority 11).
    ctx = setup_auction_scheduled(climate=True, rate=10000,
                                  past_due_date="2026-07-02T00:00:00Z")
    validate_success(
        api.complete_sale(ctx["auction"]["id"], {"sale_proceeds_cents": 20000}, LIEN), 200)
    resp = api.redeem_auction(ctx["auction"]["id"], make_tenant_headers(ctx["tenant"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    a = validate_success(api.get_auction_proceeding(ctx["auction"]["id"], LIEN), 200)
    assert a["status"] == "SOLD"


def test_redeem_sold_proceeding_leaves_lease_auctioned(api):
    """PRD §3.8: "The lease moves `AUCTION_SCHEDULED → AUCTIONED`."
    PRD §3.9: "Redemption is defined while the proceeding is in `NOTICE_SENT`,
    `LIEN_FILED`, or `SCHEDULED` status."

    Design: Difficulty/priority_pair_validation_conflict/priority_state_beats_fiscal_on_redeem_terminal_lease
    """
    # After a SOLD proceeding, the failed redeem leaves the lease terminal (AUCTIONED),
    # confirming the state check (priority 5) blocks the transition rather than the
    # fiscal balance check (priority 11) admitting it.
    ctx = setup_auction_scheduled(climate=True, rate=10000,
                                  past_due_date="2026-07-02T00:00:00Z")
    validate_success(
        api.complete_sale(ctx["auction"]["id"], {"sale_proceeds_cents": 20000}, LIEN), 200)
    resp = api.redeem_auction(ctx["auction"]["id"], make_tenant_headers(ctx["tenant"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    lease = validate_success(api.get_lease(ctx["lease"]["id"], FM), 200)
    assert lease["status"] == "AUCTIONED"


def test_transfer_complete_to_occupied_unit_returns_unit_not_available(api):
    """PRD §3.10: "the destination unit must still be `AVAILABLE`, else the relevant state
    or availability error is raised."
    PRD §3.10: "The destination unit must be `AVAILABLE`; if it is not, the request is
    rejected with `ERR_UNIT_NOT_AVAILABLE`."

    Design: Difficulty/priority_pair_validation_conflict/priority_referential_beats_temporal_on_transfer_complete
    """
    # L1 on U1; transfer L1->U2 requested while U2 AVAILABLE; then L2 occupies U2.
    fac = create_facility(name="F10", state_code="TX", climate_premium_pct=0.20)
    u1 = create_unit(fac["id"], unit_number="U1", monthly_rate_cents=10000)
    u2 = create_unit(fac["id"], unit_number="U2", monthly_rate_cents=12000)
    ten1 = create_tenant(email="t10a@x.com", full_name="T Ten A", state_code="TX")
    ten2 = create_tenant(email="t10b@x.com", full_name="T Ten B", state_code="TX")
    set_clock("2026-04-01T00:00:00Z")
    l1 = create_lease(u1["id"], ten1["id"])
    l1 = validate_success(api.activate_lease(l1["id"], FM), 200)
    transfer = validate_success(api.create_transfer_order(
        {"lease_id": l1["id"], "to_unit_id": u2["id"],
         "expected_lease_version": l1["version"]}, FM), 201)
    l2 = create_lease(u2["id"], ten2["id"])
    validate_success(api.activate_lease(l2["id"], FM), 200)
    # U2 is now OCCUPIED -> completing the transfer fails ERR_UNIT_NOT_AVAILABLE.
    resp = api.complete_transfer(transfer["id"], FM)
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_AVAILABLE.value)
    to = validate_success(api.get_transfer_order(transfer["id"], FM), 200)
    assert to["status"] == "REQUESTED"


def test_transfer_complete_to_occupied_leaves_origin_lease_on_old_unit(api):
    """PRD §3.10: "The destination unit must be `AVAILABLE`; if it is not, the request is
    rejected with `ERR_UNIT_NOT_AVAILABLE`."
    PRD §3.10: "On completion ... The lease's `unit_id` is updated to the destination."

    Design: Difficulty/priority_pair_validation_conflict/priority_referential_beats_temporal_on_transfer_complete
    """
    # The rejected completion must NOT relocate L1: it stays bound to U1 (its old unit),
    # confirming the availability (referential) check blocks the move outright.
    fac = create_facility(name="F10b", state_code="TX", climate_premium_pct=0.20)
    u1 = create_unit(fac["id"], unit_number="U1", monthly_rate_cents=10000)
    u2 = create_unit(fac["id"], unit_number="U2", monthly_rate_cents=12000)
    ten1 = create_tenant(email="t10c@x.com", full_name="T Ten C", state_code="TX")
    ten2 = create_tenant(email="t10d@x.com", full_name="T Ten D", state_code="TX")
    set_clock("2026-04-01T00:00:00Z")
    l1 = create_lease(u1["id"], ten1["id"])
    l1 = validate_success(api.activate_lease(l1["id"], FM), 200)
    transfer = validate_success(api.create_transfer_order(
        {"lease_id": l1["id"], "to_unit_id": u2["id"],
         "expected_lease_version": l1["version"]}, FM), 201)
    l2 = create_lease(u2["id"], ten2["id"])
    validate_success(api.activate_lease(l2["id"], FM), 200)
    resp = api.complete_transfer(transfer["id"], FM)
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_AVAILABLE.value)
    lease = validate_success(api.get_lease(l1["id"], FM), 200)
    assert lease["unit_id"] == u1["id"], "L1 still on its old unit after the rejected move"


# ─── boundary_precision_check / days_past_due >= 90 opens auction ───

def test_auction_opens_at_exactly_90_days_past_due(api):
    """PRD §3.8: "Opening is permitted only when the lease is in `PRE_LIEN` status and its
    `days_past_due` is at least the facility's `lien_default_days` — the at-least-90-day
    default boundary; a lease that has not yet reached that day count is rejected with
    `ERR_WINDOW_NOT_ELAPSED` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/boundary_days_past_due_ge_90_opens_auction
    """
    # Invoice due 2026-04-01; clock 2026-06-30 == due + 90 days; billing-cycle -> PRE_LIEN.
    ctx = setup_delinquent_past_90(climate=True, rate=10000,
                                   past_due_date="2026-06-30T00:00:00Z")
    lease = validate_success(api.get_lease(ctx["lease"]["id"], LIEN), 200)
    assert lease["days_past_due"] == 90
    resp = api.create_auction_proceeding(
        {"lease_id": ctx["lease"]["id"], "expected_lease_version": lease["version"]}, LIEN)
    data = validate_success(resp, 201)
    assert data["status"] == "NOTICE_SENT"


def test_auction_open_below_90_days_rejected(api):
    """PRD §3.8: "a lease that has not yet reached that day count is rejected with
    `ERR_WINDOW_NOT_ELAPSED` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/boundary_days_past_due_ge_90_opens_auction
    """
    # Clock 2026-06-29 == due 2026-04-01 + 89 days -> below the 90-day boundary.
    ctx = setup_delinquent_past_90(climate=True, rate=10000,
                                   past_due_date="2026-06-29T00:00:00Z")
    lease = validate_success(api.get_lease(ctx["lease"]["id"], LIEN), 200)
    assert lease["days_past_due"] == 89
    resp = api.create_auction_proceeding(
        {"lease_id": ctx["lease"]["id"], "expected_lease_version": lease["version"]}, LIEN)
    validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_ELAPSED.value)


# ─── boundary_precision_check / empty unpaid set -> surplus = proceeds - admin ───

def test_surplus_full_proceeds_minus_admin_when_balance_cleared(api):
    """PRD §3.9: "The first bucket takes the smaller of the remaining proceeds and the
    outstanding rent, climate, and insurance remainders. The second bucket then takes the
    smaller of what now remains and the outstanding late fees. The third bucket then takes
    the smaller of what now remains and the lien administration cost of 15000 cents.
    Whatever proceeds remain after those three buckets are the tenant's `surplus_cents`."

    Design: Difficulty/boundary_precision_check/boundary_empty_unpaid_set_surplus_equals_full_proceeds
    """
    # Schedule auction, then pay every invoice to zero before the sale. Only the lien
    # admin bucket (15000) draws; surplus = 50000 - 15000 = 35000.
    ctx = setup_auction_scheduled(climate=True, rate=10000,
                                  past_due_date="2026-07-02T00:00:00Z")
    lease = validate_success(api.get_lease(ctx["lease"]["id"], FM), 200)
    pay(ctx["lease"]["id"], lease["balance_cents"], ctx["tenant"]["id"])
    # Lease was redeemed back to ACTIVE by clearing balance; re-confirm auction still
    # SCHEDULED would be wrong -- instead this clears the unpaid set. Complete the sale.
    sold = validate_success(
        api.complete_sale(ctx["auction"]["id"], {"sale_proceeds_cents": 50000}, LIEN), 200)
    assert sold["surplus_cents"] == 35000, "50000 - 15000 lien admin (buckets 1-2 empty)"


def test_surplus_plus_buckets_sum_to_proceeds(api):
    """PRD §3.9: "the four quantities — the three bucket payments and the surplus — always
    sum exactly to `sale_proceeds_cents`."

    Design: Difficulty/boundary_precision_check/boundary_empty_unpaid_set_surplus_equals_full_proceeds
    """
    ctx = setup_auction_scheduled(climate=True, rate=10000,
                                  past_due_date="2026-07-02T00:00:00Z")
    lease = validate_success(api.get_lease(ctx["lease"]["id"], FM), 200)
    pay(ctx["lease"]["id"], lease["balance_cents"], ctx["tenant"]["id"])
    sold = validate_success(
        api.complete_sale(ctx["auction"]["id"], {"sale_proceeds_cents": 50000}, LIEN), 200)
    # Buckets 1 and 2 empty (balance cleared), bucket 3 = 15000, surplus = 35000.
    assert sold["surplus_cents"] + 15000 == 50000


# ─── cross_entity_state_dependency / lease activate requires unit AVAILABLE ───

def test_activate_second_lease_on_occupied_unit_rejected(api):
    """PRD §3.3: "The bound unit's `status` must be `AVAILABLE` — if it is not, activation
    is rejected with `ERR_UNIT_NOT_AVAILABLE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/cross_lease_activate_requires_unit_available
    """
    fac = create_facility(name="F13", state_code="TX", climate_premium_pct=0.20)
    unit = create_unit(fac["id"], unit_number="A-13", monthly_rate_cents=10000)
    ten1 = create_tenant(email="t13a@x.com", full_name="T 13 A", state_code="TX")
    ten2 = create_tenant(email="t13b@x.com", full_name="T 13 B", state_code="TX")
    set_clock("2026-04-01T00:00:00Z")
    l1 = create_lease(unit["id"], ten1["id"], start_date="2026-04-01T00:00:00Z")
    # Non-overlapping later window so the lease create itself is accepted.
    l2 = create_lease(unit["id"], ten2["id"], start_date="2027-01-01T00:00:00Z")
    validate_success(api.activate_lease(l1["id"], FM), 200)
    occupied_unit = validate_success(api.get_unit(unit["id"], FM), 200)
    assert occupied_unit["status"] == "OCCUPIED"
    resp = api.activate_lease(l2["id"], FM)
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_AVAILABLE.value)
    l2_after = validate_success(api.get_lease(l2["id"], FM), 200)
    assert l2_after["status"] == "PENDING"


def test_rejected_activation_leaves_unit_bound_to_first_lease(api):
    """PRD §3.3: "The bound unit moves `AVAILABLE → OCCUPIED`, its `current_lease_id` is
    set to this lease."
    PRD §3.3: "The bound unit's `status` must be `AVAILABLE` — if it is not, activation is
    rejected with `ERR_UNIT_NOT_AVAILABLE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/cross_lease_activate_requires_unit_available
    """
    fac = create_facility(name="F13b", state_code="TX", climate_premium_pct=0.20)
    unit = create_unit(fac["id"], unit_number="A-13b", monthly_rate_cents=10000)
    ten1 = create_tenant(email="t13c@x.com", full_name="T 13 C", state_code="TX")
    ten2 = create_tenant(email="t13d@x.com", full_name="T 13 D", state_code="TX")
    set_clock("2026-04-01T00:00:00Z")
    l1 = create_lease(unit["id"], ten1["id"], start_date="2026-04-01T00:00:00Z")
    l2 = create_lease(unit["id"], ten2["id"], start_date="2027-01-01T00:00:00Z")
    l1 = validate_success(api.activate_lease(l1["id"], FM), 200)
    validate_error(api.activate_lease(l2["id"], FM), ApiErrorId.ERR_UNIT_NOT_AVAILABLE.value)
    # The unit's binding must still point at L1, not the rejected L2.
    unit_after = validate_success(api.get_unit(unit["id"], FM), 200)
    assert unit_after["current_lease_id"] == l1["id"]


# ─── cross_entity_state_dependency / auction open requires lease PRE_LIEN ───

def test_auction_open_on_active_lease_rejected(api):
    """PRD §3.8: "Opening is permitted only when the lease is in `PRE_LIEN` status."
    PRD §2.5: "For state-transition endpoints, the target resource being in a state from
    which the requested transition is not defined is checked fifth, giving
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/cross_auction_open_requires_lease_pre_lien
    """
    # ACTIVE lease: not PRE_LIEN, so the open is rejected on the status guard.
    ctx = setup_activated(unit_overrides={"climate_controlled": True,
                                          "monthly_rate_cents": 10000})
    lease = validate_success(api.get_lease(ctx["lease"]["id"], LIEN), 200)
    assert lease["status"] == "ACTIVE"
    resp = api.create_auction_proceeding(
        {"lease_id": ctx["lease"]["id"], "expected_lease_version": lease["version"]}, LIEN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_auction_open_on_active_lease_creates_no_proceeding(api):
    """PRD §3.8: "Opening is permitted only when the lease is in `PRE_LIEN` status."
    PRD §4: "GET `/auction-proceedings` ... List auction proceedings; filter by lease."

    Design: Difficulty/cross_entity_state_dependency/cross_auction_open_requires_lease_pre_lien
    """
    # The rejected open must not have created a proceeding for the ACTIVE lease.
    ctx = setup_activated(unit_overrides={"climate_controlled": True,
                                          "monthly_rate_cents": 10000})
    lease = validate_success(api.get_lease(ctx["lease"]["id"], LIEN), 200)
    validate_error(api.create_auction_proceeding(
        {"lease_id": ctx["lease"]["id"], "expected_lease_version": lease["version"]}, LIEN),
        ApiErrorId.ERR_INVALID_STATE.value)
    listing, _ = validate_paginated(
        api.list_auction_proceedings(LIEN, params={"lease_id": ctx["lease"]["id"]}))
    assert listing == [], "no proceeding should exist for the ACTIVE lease"


# ─── resource_temporal_overlap / unit occupancy closed interval ───

def test_unit_occupancy_overlap_rejected(api):
    """PRD §3.2: "A lease created against a unit whose closed occupancy interval
    `[start_date, end_date]` intersects the interval of an existing lease on that same
    unit is rejected with `ERR_UNIT_OCCUPANCY_OVERLAP` (HTTP 409); two leases may not
    occupy the same unit over intersecting closed date intervals."

    Design: Difficulty/resource_temporal_overlap/overlap_unit_occupancy_closed_interval_rejected
    """
    fac = create_facility(name="F15", state_code="TX", climate_premium_pct=0.20)
    unit = create_unit(fac["id"], unit_number="A-15", monthly_rate_cents=10000)
    ten1 = create_tenant(email="t15a@x.com", full_name="T 15 A", state_code="TX")
    ten2 = create_tenant(email="t15b@x.com", full_name="T 15 B", state_code="TX")
    set_clock("2026-04-01T00:00:00Z")
    l1 = create_lease(unit["id"], ten1["id"], start_date="2026-04-01T00:00:00Z")
    validate_success(api.activate_lease(l1["id"], FM), 200)
    # Second lease starting inside L1's open-ended occupancy -> overlap.
    resp = api.create_lease(
        {"unit_id": unit["id"], "tenant_id": ten2["id"],
         "start_date": "2026-05-01T00:00:00Z", "billing_day": 1,
         "insurance_required": False}, FM)
    validate_error(resp, ApiErrorId.ERR_UNIT_OCCUPANCY_OVERLAP.value)


def test_unit_occupancy_overlap_does_not_create_second_lease(api):
    """PRD §3.2: "A lease created against a unit whose closed occupancy interval
    `[start_date, end_date]` intersects the interval of an existing lease on that same
    unit is rejected with `ERR_UNIT_OCCUPANCY_OVERLAP` (HTTP 409)."
    PRD §4: "GET `/leases` ... List leases; filter by facility, unit, tenant, status."

    Design: Difficulty/resource_temporal_overlap/overlap_unit_occupancy_closed_interval_rejected
    """
    fac = create_facility(name="F15b", state_code="TX", climate_premium_pct=0.20)
    unit = create_unit(fac["id"], unit_number="A-15b", monthly_rate_cents=10000)
    ten1 = create_tenant(email="t15c@x.com", full_name="T 15 C", state_code="TX")
    ten2 = create_tenant(email="t15d@x.com", full_name="T 15 D", state_code="TX")
    set_clock("2026-04-01T00:00:00Z")
    l1 = create_lease(unit["id"], ten1["id"], start_date="2026-04-01T00:00:00Z")
    validate_success(api.activate_lease(l1["id"], FM), 200)
    validate_error(api.create_lease(
        {"unit_id": unit["id"], "tenant_id": ten2["id"],
         "start_date": "2026-05-01T00:00:00Z", "billing_day": 1,
         "insurance_required": False}, FM),
        ApiErrorId.ERR_UNIT_OCCUPANCY_OVERLAP.value)
    # Only the first lease exists on the unit.
    leases, _ = validate_paginated(api.list_leases(FM, params={"unit_id": unit["id"]}))
    assert [l["id"] for l in leases] == [l1["id"]], "rejected overlap must create no lease"


# ─── resource_temporal_overlap / insurance half-open adjacency allowed ───

def test_insurance_adjacency_at_prior_end_accepted(api):
    """PRD §3.7: "adjacency, where one interval's end equals the next interval's start, is
    permitted because the intervals do not overlap."
    PRD §3.7: "`coverage_end`, when set, marks the exclusive end of the half-open coverage
    interval `[coverage_start, coverage_end)`."

    Design: Difficulty/resource_temporal_overlap/overlap_insurance_coverage_half_open_adjacency_allowed
    """
    fac = create_facility(name="F16b", state_code="TX", climate_premium_pct=0.20)
    unit = create_unit(fac["id"], unit_number="A-16b", monthly_rate_cents=10000)
    ten = create_tenant(email="t16b@x.com", full_name="T 16 B", state_code="TX")
    set_clock("2026-04-01T00:00:00Z")
    lease = create_lease(unit["id"], ten["id"])
    p1 = create_insurance_policy(lease["id"], coverage_tier="BASIC",
                                 coverage_start="2026-04-01T00:00:00Z")
    set_clock("2026-07-01T00:00:00Z")
    validate_success(api.cancel_insurance_policy(p1["id"], FM), 200)
    # New policy starting exactly at the prior policy's coverage_end is adjacent -> allowed.
    resp = api.create_insurance_policy(
        {"lease_id": lease["id"], "coverage_tier": "STANDARD",
         "coverage_start": "2026-07-01T00:00:00Z"}, FM)
    validate_success(resp, 201)


def test_insurance_interior_overlap_rejected(api):
    """PRD §3.7: "A policy whose half-open coverage interval intersects an existing policy
    interval on the same lease is rejected with `ERR_COVERAGE_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/overlap_insurance_coverage_half_open_adjacency_allowed
    """
    fac = create_facility(name="F16", state_code="TX", climate_premium_pct=0.20)
    unit = create_unit(fac["id"], unit_number="A-16", monthly_rate_cents=10000)
    ten = create_tenant(email="t16@x.com", full_name="T 16", state_code="TX")
    set_clock("2026-04-01T00:00:00Z")
    lease = create_lease(unit["id"], ten["id"])
    # P1 [2026-04-01, ...). Cancel at 2026-07-01 -> coverage_end = 2026-07-01.
    p1 = create_insurance_policy(lease["id"], coverage_tier="BASIC",
                                 coverage_start="2026-04-01T00:00:00Z")
    set_clock("2026-07-01T00:00:00Z")
    validate_success(api.cancel_insurance_policy(p1["id"], FM), 200)
    create_insurance_policy(lease["id"], coverage_tier="STANDARD",
                            coverage_start="2026-07-01T00:00:00Z")
    # An interior-overlapping policy (starts inside P1's [04-01, 07-01)) is rejected.
    overlap_resp = api.create_insurance_policy(
        {"lease_id": lease["id"], "coverage_tier": "PREMIUM",
         "coverage_start": "2026-06-15T00:00:00Z"}, FM)
    validate_error(overlap_resp, ApiErrorId.ERR_COVERAGE_OVERLAP.value)
