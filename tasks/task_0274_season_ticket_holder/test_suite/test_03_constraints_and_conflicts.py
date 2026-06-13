"""Validation conflicts, temporal/aggregate resource overlap, cross-entity state
dependencies, and the eligibility/capacity/uniqueness corners
(PRD §2.8, §2.9, §3.3, §3.4, §3.9, §3.10, §3.12).

Validation precedence is the explicit category order of PRD §2.8: "Business-state,
ownership, referential, temporal, capacity, eligibility, uniqueness, and
concurrency checks follow".
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_active_subscription,
    setup_active_subscription_with_payment_plan,
    setup_pending_subscription,
    setup_zone_at_capacity,
    create_section,
    create_seat,
    create_account,
    create_season_plan,
    create_subscription,
    create_seat_assignment,
    create_parking_zone,
    add_parking_pass,
    make_account_holder_headers,
    TEST_USERS,
)
from test_helpers.constants import SEASON_START, SEASON_END, SEASON_ADJACENT_START, SEASON_ADJACENT_END

_BOX = TEST_USERS["box_office_headers"]
_FIN = TEST_USERS["finance_headers"]


# =========================================================================
# Priority-pair conflict: state (priority earlier) beats OCC concurrency
# =========================================================================
def test_relocate_on_pending_with_stale_version_reports_invalid_state(api):
    """PRD §2.8: "Business-state, ownership, referential, temporal, capacity,
    eligibility, uniqueness, and concurrency checks follow, in the order their
    owning rules are introduced across §2.6 and §3, each carrying its own dedicated
    error as those sections describe."
    PRD §3.5: "Beginning a relocation is legal only while the subscription is
    `ACTIVE`."

    On relocate-begin against a PENDING subscription with a wrong
    expected_subscription_version, the business-state category precedes the
    concurrency category in §2.8's enumeration, so ERR_INVALID_STATE is reported.

    Design: Difficulty/priority_pair_validation_conflict/relocate_state_vs_occ_fiscal_state_wins
    """
    section = create_section(name="P5a Sec")
    seat = create_seat(section["id"], seat_number=1)
    plan = create_season_plan(plan_type="FULL", price_multiplier_bps=10000)
    account = create_account(full_name="P5a Holder")
    sub = create_subscription(account["id"], plan["id"])
    create_seat_assignment(sub["id"], seat["id"])
    # Subscription is still PENDING (never activated); pass a deliberately stale version.
    stale_version = sub["version"] + 99
    resp = api.relocate_subscription(sub["id"], {"expected_subscription_version": stale_version}, _BOX)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_relocate_on_pending_with_stale_version_does_not_transition(api):
    """PRD §3.5: "Beginning a relocation is legal only while the subscription is
    `ACTIVE`."
    PRD §2.9: "the request is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    The rejected begin leaves the subscription in PENDING (no transition occurs).

    Design: Difficulty/priority_pair_validation_conflict/relocate_state_vs_occ_fiscal_state_wins
    """
    section = create_section(name="P5a2 Sec")
    seat = create_seat(section["id"], seat_number=1)
    plan = create_season_plan(plan_type="FULL", price_multiplier_bps=10000)
    account = create_account(full_name="P5a2 Holder")
    sub = create_subscription(account["id"], plan["id"])
    create_seat_assignment(sub["id"], seat["id"])
    api.relocate_subscription(sub["id"], {"expected_subscription_version": sub["version"] + 99}, _BOX)
    after = validate_success(api.get_subscription(sub["id"], _BOX))
    assert after["status"] == "PENDING", after["status"]


# =========================================================================
# Priority-pair conflict: referential (section mismatch) beats temporal (window)
# =========================================================================
def test_relocate_confirm_section_mismatch_reported_over_window_conflict(api):
    """PRD §2.8: "Business-state, ownership, referential, temporal, capacity,
    eligibility, uniqueness, and concurrency checks follow, in the order their
    owning rules are introduced across §2.6 and §3, each carrying its own dedicated
    error as those sections describe."
    PRD §3.5: "if a target sits in a different section or a different window than the
    released seats, the confirm is rejected with `ERR_SECTION_MISMATCH` (HTTP 422)."

    A relocation target in a DIFFERENT section that is also already SOLD on an
    overlapping window triggers both referential (§3.5) and temporal (§3.4) checks;
    referential precedes temporal in §2.8's category order, so ERR_SECTION_MISMATCH.

    Design: Difficulty/priority_pair_validation_conflict/relocate_confirm_section_mismatch_vs_seat_window_referential_wins
    """
    s1 = create_section(name="Sec S1")
    s2 = create_section(name="Sec S2")
    seat_s1 = create_seat(s1["id"], row_label="A", seat_number=1)
    seat_s2 = create_seat(s2["id"], row_label="A", seat_number=1)
    plan = create_season_plan(plan_type="FULL", price_multiplier_bps=10000)
    mover_acc = create_account(full_name="Mover")
    occ_acc = create_account(full_name="Occupant")
    mover_sub = create_subscription(mover_acc["id"], plan["id"])
    occ_sub = create_subscription(occ_acc["id"], plan["id"])
    create_seat_assignment(mover_sub["id"], seat_s1["id"])
    create_seat_assignment(occ_sub["id"], seat_s2["id"])  # seat_s2 now SOLD on same window
    mover_active = validate_success(api.activate_subscription(mover_sub["id"], _BOX))
    validate_success(api.activate_subscription(occ_sub["id"], _BOX))
    validate_success(
        api.relocate_subscription(mover_sub["id"], {"expected_subscription_version": mover_active["version"]}, _BOX)
    )
    resp = api.relocate_confirm(mover_sub["id"], {"target_seat_ids": [seat_s2["id"]]}, _BOX)
    validate_error(resp, ApiErrorId.ERR_SECTION_MISMATCH.value)


def test_relocate_confirm_different_section_target_rejected(api):
    """PRD §3.5: "a relocation target seat must belong to the same `Section` as the
    seats being released and share the same season window; if a target sits in a
    different section or a different window than the released seats, the confirm is
    rejected with `ERR_SECTION_MISMATCH` (HTTP 422)."

    A target seat in a different section (AVAILABLE, same window) is rejected with
    ERR_SECTION_MISMATCH.

    Design: Difficulty/priority_pair_validation_conflict/relocate_confirm_section_mismatch_vs_seat_window_referential_wins
    """
    s1 = create_section(name="Sec S1b")
    s2 = create_section(name="Sec S2b")
    seat_s1 = create_seat(s1["id"], row_label="A", seat_number=1)
    seat_s2 = create_seat(s2["id"], row_label="A", seat_number=1)  # AVAILABLE, same window
    plan = create_season_plan(plan_type="FULL", price_multiplier_bps=10000)
    mover_acc = create_account(full_name="Mover2")
    mover_sub = create_subscription(mover_acc["id"], plan["id"])
    create_seat_assignment(mover_sub["id"], seat_s1["id"])
    mover_active = validate_success(api.activate_subscription(mover_sub["id"], _BOX))
    validate_success(
        api.relocate_subscription(mover_sub["id"], {"expected_subscription_version": mover_active["version"]}, _BOX)
    )
    resp = api.relocate_confirm(mover_sub["id"], {"target_seat_ids": [seat_s2["id"]]}, _BOX)
    validate_error(resp, ApiErrorId.ERR_SECTION_MISMATCH.value)


# =========================================================================
# Boundary precision: loyalty tier at the SILVER boundary (499 vs 500)
# =========================================================================
def test_loyalty_tier_below_silver_boundary_is_bronze(api):
    """PRD §3.2: "An account sits at `BRONZE` while its points are below 500, at
    `SILVER` once its points are at least 500 but still below 1000, and at `GOLD`
    once its points reach 1000 or more."

    priority_points==499 -> BRONZE (boundary X-1).

    Design: Difficulty/boundary_precision_check/loyalty_tier_silver_boundary_at_500_points
    """
    acc = create_account(full_name="Below")
    granted = validate_success(api.grant_points(acc["id"], {"priority_points": 499}, _BOX))
    assert granted["loyalty_tier"] == "BRONZE", granted["loyalty_tier"]
    fetched = validate_success(api.get_account(acc["id"], _BOX))
    assert fetched["loyalty_tier"] == "BRONZE", fetched["loyalty_tier"]


def test_loyalty_tier_at_silver_boundary_is_silver(api):
    """PRD §3.2: "at `SILVER` once its points are at least 500 but still below 1000."

    priority_points==500 -> SILVER (boundary X, inclusive).

    Design: Difficulty/boundary_precision_check/loyalty_tier_silver_boundary_at_500_points
    """
    acc = create_account(full_name="AtBound")
    granted = validate_success(api.grant_points(acc["id"], {"priority_points": 500}, _BOX))
    assert granted["loyalty_tier"] == "SILVER", granted["loyalty_tier"]
    fetched = validate_success(api.get_account(acc["id"], _BOX))
    assert fetched["loyalty_tier"] == "SILVER", fetched["loyalty_tier"]


# =========================================================================
# Boundary / aggregate capacity: ParkingZone capacity = 1 and = 2
# =========================================================================
def test_parking_zone_capacity_one_accepts_first_rejects_second(api):
    """PRD §3.12: "A pass may not be added when its target zone is already at
    capacity — that is, when the zone's `active_pass_count` is greater than or equal
    to its `capacity` — and such an attempt is rejected with `ERR_PARKING_ZONE_FULL`
    (HTTP 409)."

    capacity=1: first add-on succeeds (count 0->1), second rejected; count stays 1.

    Design: Difficulty/boundary_precision_check/parking_zone_capacity_empty_slot_boundary
    """
    zone, passes, filled, spare = setup_zone_at_capacity(capacity=1)
    assert zone["active_pass_count"] == 1, zone["active_pass_count"]
    resp = api.create_parking_addon(
        {"subscription_id": spare["subscription"]["id"], "parking_zone_id": zone["id"]}, _BOX
    )
    validate_error(resp, ApiErrorId.ERR_PARKING_ZONE_FULL.value)
    after = validate_success(api.get_parking_zone(zone["id"], _BOX))
    assert after["active_pass_count"] == 1, after["active_pass_count"]


def test_parking_zone_capacity_one_accepts_first_pass(api):
    """PRD §3.12: "At add time the pass snapshots the zone's `price_cents` into its
    own `price_cents`, begins with `status` of `ACTIVE`, and increments the zone's
    `active_pass_count`."
    PRD §3.12: "A new zone reports `active_pass_count` of 0."

    The first add-on into a capacity=1 zone succeeds, taking active_pass_count from
    0 to 1 (the empty-slot boundary, X-1 below capacity).

    Design: Difficulty/boundary_precision_check/parking_zone_capacity_empty_slot_boundary
    """
    from test_helpers import setup_active_subscription, create_parking_zone, add_parking_pass
    zone = create_parking_zone(capacity=1, name="Lot Empty")
    fresh = validate_success(api.get_parking_zone(zone["id"], _BOX))
    assert fresh["active_pass_count"] == 0, fresh["active_pass_count"]
    ctx = setup_active_subscription(section_name="Empty Slot Sec")
    add_parking_pass(ctx["subscription"]["id"], zone["id"])
    after = validate_success(api.get_parking_zone(zone["id"], _BOX))
    assert after["active_pass_count"] == 1, after["active_pass_count"]


def test_parking_zone_capacity_two_accepts_second_pass(api):
    """PRD §3.12: "At add time the pass snapshots the zone's `price_cents` into its
    own `price_cents`, begins with `status` of `ACTIVE`, and increments the zone's
    `active_pass_count`."
    PRD §3.12: "A pass may not be added when its target zone is already at capacity —
    that is, when the zone's `active_pass_count` is greater than or equal to its
    `capacity`."

    Into a capacity=2 zone the second pass still succeeds (count 1->2, the boundary
    that fills the zone but does not yet breach it), confirming aggregate counting.

    Design: Difficulty/resource_temporal_overlap/parking_zone_aggregate_capacity_conflict
    """
    from test_helpers import setup_active_subscription, create_parking_zone, add_parking_pass
    zone = create_parking_zone(capacity=2, name="Lot TwoFill")
    ctx1 = setup_active_subscription(section_name="Two Fill Sec 1")
    ctx2 = setup_active_subscription(section_name="Two Fill Sec 2")
    add_parking_pass(ctx1["subscription"]["id"], zone["id"])
    add_parking_pass(ctx2["subscription"]["id"], zone["id"])
    after = validate_success(api.get_parking_zone(zone["id"], _BOX))
    assert after["active_pass_count"] == 2, after["active_pass_count"]


def test_parking_zone_capacity_two_rejects_third(api):
    """PRD §3.12: "the maximum number of concurrently `ACTIVE` passes the zone may
    hold ... A pass may not be added when its target zone is already at capacity —
    that is, when the zone's `active_pass_count` is greater than or equal to its
    `capacity` — and such an attempt is rejected with `ERR_PARKING_ZONE_FULL`."

    capacity=2 with 2 ACTIVE passes rejects a third; count stays 2 (aggregate
    n-way capacity counting, not pairwise interval exclusion).

    Design: Difficulty/resource_temporal_overlap/parking_zone_aggregate_capacity_conflict
    """
    zone, passes, filled, spare = setup_zone_at_capacity(capacity=2)
    assert zone["active_pass_count"] == 2, zone["active_pass_count"]
    resp = api.create_parking_addon(
        {"subscription_id": spare["subscription"]["id"], "parking_zone_id": zone["id"]}, _BOX
    )
    validate_error(resp, ApiErrorId.ERR_PARKING_ZONE_FULL.value)
    after = validate_success(api.get_parking_zone(zone["id"], _BOX))
    assert after["active_pass_count"] == 2, after["active_pass_count"]


# =========================================================================
# Resource temporal overlap: closed-interval seat-window adjacency
# =========================================================================
def test_seat_window_adjacency_is_a_conflict(api):
    """PRD §3.4: "A seat may not be assigned if it already backs another `ASSIGNED`
    `SeatAssignment` whose subscription's season window overlaps the new one;
    because the interval is closed, two windows that merely share an endpoint date
    count as a collision."

    Window [2026-10-01, 2027-04-01] is ASSIGNED; an assignment for the adjacent
    window [2027-04-01, 2027-09-01] sharing the 2027-04-01 endpoint is rejected.

    Design: Difficulty/resource_temporal_overlap/seat_closed_interval_window_adjacency_conflict
    """
    section = create_section(name="Window Sec")
    seat_w1 = create_seat(section["id"], row_label="R", seat_number=7,
                          season_start_date=SEASON_START, season_end_date=SEASON_END)
    seat_w2 = create_seat(section["id"], row_label="R", seat_number=7,
                          season_start_date=SEASON_ADJACENT_START, season_end_date=SEASON_ADJACENT_END)
    plan = create_season_plan(plan_type="FULL", price_multiplier_bps=10000)
    acc_a = create_account(full_name="Holder A8")
    acc_b = create_account(full_name="Holder B8")
    sub_a = create_subscription(acc_a["id"], plan["id"])
    sub_b = create_subscription(acc_b["id"], plan["id"])
    create_seat_assignment(sub_a["id"], seat_w1["id"])
    resp = api.create_seat_assignment({"subscription_id": sub_b["id"], "seat_id": seat_w2["id"]}, _BOX)
    validate_error(resp, ApiErrorId.ERR_SEAT_WINDOW_CONFLICT.value)


def test_seat_window_overlap_same_window_conflict(api):
    """PRD §3.4: "A seat may not be assigned if it already backs another `ASSIGNED`
    `SeatAssignment` whose subscription's season window overlaps the new one."

    The same physical location reused across two seat rows with the identical
    window collides when both are assigned.

    Design: Difficulty/resource_temporal_overlap/seat_closed_interval_window_adjacency_conflict
    """
    section = create_section(name="Window Sec2")
    seat_w1 = create_seat(section["id"], row_label="R", seat_number=8,
                          season_start_date=SEASON_START, season_end_date=SEASON_END)
    seat_w2 = create_seat(section["id"], row_label="R", seat_number=8,
                          season_start_date=SEASON_START, season_end_date=SEASON_END)
    plan = create_season_plan(plan_type="FULL", price_multiplier_bps=10000)
    acc_a = create_account(full_name="Holder A9")
    acc_b = create_account(full_name="Holder B9")
    sub_a = create_subscription(acc_a["id"], plan["id"])
    sub_b = create_subscription(acc_b["id"], plan["id"])
    create_seat_assignment(sub_a["id"], seat_w1["id"])
    resp = api.create_seat_assignment({"subscription_id": sub_b["id"], "seat_id": seat_w2["id"]}, _BOX)
    validate_error(resp, ApiErrorId.ERR_SEAT_WINDOW_CONFLICT.value)


# =========================================================================
# Cross-entity state dependency: activate requires Account ACTIVE
# =========================================================================
def test_activate_blocked_when_account_suspended(api):
    """PRD §3.3: "Activation, performed by a box office agent, is legal only while
    the subscription is `PENDING`, requires the holder `Account` to be `ACTIVE`, and
    requires at least one `SeatAssignment` in `ASSIGNED` status to exist for it."
    PRD §3.2: "a suspended account cannot have a subscription activated or a renewal
    accepted against it, as those flows require the holder account to be `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/activate_requires_account_not_suspended
    """
    ctx = setup_pending_subscription()
    validate_success(api.suspend_account(ctx["account"]["id"], _BOX))
    resp = api.activate_subscription(ctx["subscription"]["id"], _BOX)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_activate_blocked_when_account_suspended_leaves_pending(api):
    """PRD §3.2: "a suspended account cannot have a subscription activated or a
    renewal accepted against it, as those flows require the holder account to be
    `ACTIVE`."
    PRD §3.3: "activation moves the subscription to `ACTIVE`."

    The rejected activation leaves the subscription in PENDING.

    Design: Difficulty/cross_entity_state_dependency/activate_requires_account_not_suspended
    """
    ctx = setup_pending_subscription(section_name="Susp Sec")
    validate_success(api.suspend_account(ctx["account"]["id"], _BOX))
    api.activate_subscription(ctx["subscription"]["id"], _BOX)
    after = validate_success(api.get_subscription(ctx["subscription"]["id"], _BOX))
    assert after["status"] == "PENDING", after["status"]


# =========================================================================
# Corner — validations: eligibility / uniqueness / range
# =========================================================================
def test_resale_missing_listing_price_rejected(api):
    """PRD §3.9: "The `listing_price_cents` field must be present for a `RESALE` and
    must be omitted for a `FORWARD`; supplying it on a forward or omitting it on a
    resale, like targeting an assignment that is not `ASSIGNED` or whose
    subscription is not `ACTIVE`, is rejected with `ERR_TRANSFER_NOT_ELIGIBLE`
    (HTTP 409)."

    Design: Corner/validations/resale_transfer_missing_listing_price_rejected
    """
    ctx = setup_active_subscription()
    holder_headers = make_account_holder_headers(ctx["account"]["id"])
    resp = api.create_ticket_transfer(
        {"seat_assignment_id": ctx["assignment"]["id"], "transfer_type": "RESALE"}, holder_headers
    )
    validate_error(resp, ApiErrorId.ERR_TRANSFER_NOT_ELIGIBLE.value)


def test_second_active_payment_plan_rejected(api):
    """PRD §3.10: "At most one `ACTIVE` payment plan may exist per subscription; a
    second attempt while one is still active is rejected with `ERR_PAYMENT_PLAN_EXISTS`
    (HTTP 409)."

    Design: Corner/validations/second_active_payment_plan_rejected
    """
    ctx = setup_active_subscription_with_payment_plan(installment_count=4, base_price_cents=200000)
    resp = api.create_payment_plan(
        {"subscription_id": ctx["subscription"]["id"], "installment_count": 6}, _FIN
    )
    validate_error(resp, ApiErrorId.ERR_PAYMENT_PLAN_EXISTS.value)


def test_payment_plan_installment_count_below_min_rejected(api):
    """PRD §3.10: "created against a `subscription_id` with an `installment_count`
    that must be at least 2 and at most 12."
    PRD §2.8: "that every integer falls inside its declared range; any violation
    yields `ERR_INVALID_REQUEST` (HTTP 422)."

    installment_count=1 is below the minimum of 2.

    Design: Corner/validations/payment_plan_installment_count_below_min_rejected
    """
    ctx = setup_active_subscription(base_price_cents=200000)
    resp = api.create_payment_plan(
        {"subscription_id": ctx["subscription"]["id"], "installment_count": 1}, _FIN
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
