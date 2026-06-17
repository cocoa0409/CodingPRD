"""Validation-priority conflicts, boundary precision, cross-entity dependencies,
temporal overlaps, and the zone-slot compensating invariant.

Difficulty queue (A): priority_pair_validation_conflict, boundary_precision_check,
cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, assert_zone,
    create_festival_with_zone_and_stage, create_festival, create_zone, create_stage,
    open_sales, go_live, weather_hold, gate_enter, gate_exit,
    setup_live_festival_with_active_wristband, setup_approved_application,
    setup_application_under_review, create_vendor, submit_application,
    create_parking_lot, sell_ticket, sell_parking_addon, get_lot_version,
    schedule_performance, pay_fee, confirm_application, make_vendor_headers,
    TEST_USERS,
)

_DIRECTOR = TEST_USERS["director_headers"]
_BOXOFFICE = TEST_USERS["boxoffice_headers"]
_VENDOR_MANAGER = TEST_USERS["vendor_manager_headers"]
_GATE = TEST_USERS["gate_attendant_headers"]


# ─── priority_pair_validation_conflict / suspended_state_beats_already_inside_safety ──

def test_suspended_entry_beats_already_inside_guard(api):
    """PRD §3.11: "The festival-posture gate comes seventh, failing with
    `ERR_FESTIVAL_POSTURE`; the more specific suspended-entry check is eighth, failing
    with `ERR_FESTIVAL_SUSPENDED`. ... The gate double-entry guard is tenth, failing
    with `ERR_ALREADY_INSIDE`."

    A wristband already INSIDE, scanned ENTER while the festival is SUSPENDED, violates
    both the eighth (suspended) and tenth (already-inside) checks; the higher-priority
    eighth check wins, returning ERR_FESTIVAL_SUSPENDED (409).

    Design: Difficulty/priority_pair_validation_conflict/suspended_state_beats_already_inside_safety
    """
    festival, ticket, wristband = setup_live_festival_with_active_wristband(
        start_date="2026-08-01", end_date="2026-08-02", name="Conflict F",
        rfid_uid="RF-CFL-1", max_reentries=2)
    validate_success(gate_enter(festival["id"], wristband["id"]), 201)
    weather_hold(festival["id"])
    res = gate_enter(festival["id"], wristband["id"])
    validate_error(res, "ERR_FESTIVAL_SUSPENDED", expected_status=409)


def test_suspended_entry_rejected_even_for_inside_wristband(api):
    """PRD §2.9: "a gate entry attempted while the posture is `SUSPENDED` is rejected
    with `ERR_FESTIVAL_SUSPENDED`, while exit scans continue to be accepted."

    The suspended-entry rejection fires regardless of the wristband's presence — an
    already-inside wristband's ENTER is still answered with ERR_FESTIVAL_SUSPENDED, not
    the lower-priority already-inside error.

    Design: Difficulty/priority_pair_validation_conflict/suspended_state_beats_already_inside_safety
    """
    festival, ticket, wristband = setup_live_festival_with_active_wristband(
        start_date="2026-08-01", end_date="2026-08-02", name="Conflict2 F",
        rfid_uid="RF-CFL-2", max_reentries=2)
    validate_success(gate_enter(festival["id"], wristband["id"]), 201)
    weather_hold(festival["id"])
    res = gate_enter(festival["id"], wristband["id"])
    err = validate_error(res, "ERR_FESTIVAL_SUSPENDED", expected_status=409)
    assert err["error_id"] == "ERR_FESTIVAL_SUSPENDED"


# ─── priority_pair_validation_conflict / zone_full_constraint_beats_stale_zone_occ ──

def _setup_full_zone_with_pending_second_application(api):
    """Zone slot_capacity 1; AP1 approved (fills zone, bumps version); AP2 UNDER_REVIEW.
    Returns (zone_v0, app2_id) where zone_v0 is the pre-AP1 stale zone version."""
    festival, zone, stage = create_festival_with_zone_and_stage(start_date="2026-08-01",
                                                                end_date="2026-08-02",
                                                                zone_code="A", zone_slot_capacity=1)
    zone = validate_success(api.get_zone(zone["id"], _DIRECTOR), 200)
    zone_v0 = zone["version"]
    v1, app1 = setup_application_under_review(festival["id"], zone, vendor_name="V1 Co")
    v2, app2 = setup_application_under_review(festival["id"], zone, vendor_name="V2 Co")
    validate_success(api.approve_application(app1["id"], {"expected_zone_version": zone_v0},
                                             _VENDOR_MANAGER), 200)
    return zone, zone_v0, app2["id"]


def test_stale_zone_version_beats_zone_full(api):
    """PRD §3.11: "The optimistic-concurrency version check is ninth, failing with
    `ERR_STALE_ZONE_VERSION` or `ERR_STALE_LOT_VERSION`. ... The duplicate-RFID check
    is fifteenth (`ERR_DUPLICATE_RFID`), the zone-full check sixteenth (`ERR_ZONE_FULL`)."

    Approving a second application against a zone that is BOTH full and whose version
    the caller observed stale violates the ninth (OCC) and sixteenth (zone-full) checks;
    the higher-priority ninth check wins, returning ERR_STALE_ZONE_VERSION (412).

    Design: Difficulty/priority_pair_validation_conflict/zone_full_constraint_beats_stale_zone_occ
    """
    zone, zone_v0, app2_id = _setup_full_zone_with_pending_second_application(api)
    res = api.approve_application(app2_id, {"expected_zone_version": zone_v0}, _VENDOR_MANAGER)
    validate_error(res, "ERR_STALE_ZONE_VERSION", expected_status=412)


def test_stale_zone_version_returns_412_status(api):
    """PRD §2.6: "if another approval has advanced the zone's version since the caller
    last read it, the approval is rejected with `ERR_STALE_ZONE_VERSION` and an HTTP
    status of 412."

    Re-confirms the OCC outcome carries HTTP 412 even when the zone is simultaneously
    full, so the stale-version path pre-empts the zone-full 409.

    Design: Difficulty/priority_pair_validation_conflict/zone_full_constraint_beats_stale_zone_occ
    """
    zone, zone_v0, app2_id = _setup_full_zone_with_pending_second_application(api)
    res = api.approve_application(app2_id, {"expected_zone_version": zone_v0}, _VENDOR_MANAGER)
    assert res.status_code == 412
    validate_error(res, "ERR_STALE_ZONE_VERSION")


# ─── boundary_precision_check / reentry_cap_exact_boundary_third_enter ───

def test_reentry_cap_third_enter_rejected(api):
    """PRD §3.7: "An entry that would push `reentry_used` to or beyond `max_reentries`
    is rejected with `ERR_REENTRY_LIMIT`."

    With max_reentries 1: ENTER, EXIT, re-ENTER (reentry_used 0->1), EXIT; the next
    ENTER would push reentry_used to 2 (>= cap 1) and is rejected with ERR_REENTRY_LIMIT.

    Design: Difficulty/boundary_precision_check/reentry_cap_exact_boundary_third_enter
    """
    festival, ticket, wristband = setup_live_festival_with_active_wristband(
        start_date="2026-08-01", end_date="2026-08-02", name="Reentry F",
        rfid_uid="RF-RE-1", max_reentries=1)
    validate_success(gate_enter(festival["id"], wristband["id"]), 201)
    validate_success(gate_exit(festival["id"], wristband["id"]), 201)
    validate_success(gate_enter(festival["id"], wristband["id"]), 201)
    validate_success(gate_exit(festival["id"], wristband["id"]), 201)
    res = gate_enter(festival["id"], wristband["id"])
    validate_error(res, "ERR_REENTRY_LIMIT", expected_status=409)


def test_first_reentry_within_cap_admitted(api):
    """PRD §3.7: "The first entry on a wristband is always allowed, but each subsequent
    entry is a re-entry; an entry is permitted only when the wristband has not yet been
    inside (its `entry_count` is still 0) or when the re-entries already used remain
    below the festival's `max_reentries` cap."

    The boundary just below the cap: with max_reentries 1, after ENTER+EXIT the first
    re-entry (reentry_used 0 -> 1) is still admitted, distinguishing the allowed step
    from the rejected one above.

    Design: Difficulty/boundary_precision_check/reentry_cap_exact_boundary_third_enter
    """
    festival, ticket, wristband = setup_live_festival_with_active_wristband(
        start_date="2026-08-01", end_date="2026-08-02", name="ReentryOk F",
        rfid_uid="RF-RE-2", max_reentries=1)
    validate_success(gate_enter(festival["id"], wristband["id"]), 201)
    validate_success(gate_exit(festival["id"], wristband["id"]), 201)
    res = gate_enter(festival["id"], wristband["id"])
    event = validate_success(res, 201)
    assert event["outcome"] == "ADMITTED"
    after = validate_success(api.get_wristband(wristband["id"], _GATE), 200)
    assert after["reentry_used"] == 1


# ─── boundary_precision_check / parking_capacity_full_zero_remaining_boundary ──

def _setup_parking_lot_full(api, name, capacity=1):
    """ON_SALE festival, parking lot of given capacity, T1 bought one pass (sold_count 1).
    Returns (lot_id, t2_id) where t2 has no pass yet."""
    festival, zone, stage = create_festival_with_zone_and_stage(start_date="2026-08-01",
                                                                end_date="2026-08-02", name=name,
                                                                zone_code="A", zone_slot_capacity=1)
    lot = create_parking_lot(festival["id"], capacity=capacity, price_per_pass=25.00)
    open_sales(festival["id"])
    t1 = sell_ticket(festival["id"], purchaser_email="t1@x.com")
    t2 = sell_ticket(festival["id"], purchaser_email="t2@x.com")
    sell_parking_addon(t1["id"], lot["id"], lot["version"])
    return lot["id"], t2["id"]


def test_parking_capacity_full_zero_remaining_rejected(api):
    """PRD §3.4: "A parking sale requires the lot to have a free pass — that is, the
    lot's `sold_count` must be strictly below its `capacity` — and on success increments
    the lot's `sold_count` and advances the lot's `version` ... When the relevant pool
    is full, the sale is rejected with `ERR_CAPACITY_FULL`."

    A capacity-1 lot whose only pass is already sold (sold_count 1, zero remaining)
    rejects the next parking sale with ERR_CAPACITY_FULL.

    Design: Difficulty/boundary_precision_check/parking_capacity_full_zero_remaining_boundary
    """
    lot_id, t2_id = _setup_parking_lot_full(api, "ParkFull F", capacity=1)
    fresh_version = get_lot_version(lot_id)
    from test_helpers import create_parking_addon_payload
    res = api.create_addon(t2_id, create_parking_addon_payload(lot_id, fresh_version), _BOXOFFICE)
    validate_error(res, "ERR_CAPACITY_FULL", expected_status=409)


def test_parking_sale_succeeds_when_pass_remains(api):
    """PRD §3.4: "A parking sale requires the lot to have a free pass — that is, the
    lot's `sold_count` must be strictly below its `capacity` — and on success increments
    the lot's `sold_count` and advances the lot's `version`."

    The allowed side of the boundary: a capacity-2 lot with one pass sold (sold_count 1
    < capacity 2) admits a second sale, distinguishing the free-pass case from the
    full-pool rejection above.

    Design: Difficulty/boundary_precision_check/parking_capacity_full_zero_remaining_boundary
    """
    festival, zone, stage = create_festival_with_zone_and_stage(start_date="2026-08-01",
                                                                end_date="2026-08-02",
                                                                name="ParkOk F", zone_code="A")
    lot = create_parking_lot(festival["id"], capacity=2, price_per_pass=25.00)
    open_sales(festival["id"])
    t1 = sell_ticket(festival["id"], purchaser_email="po1@x.com")
    t2 = sell_ticket(festival["id"], purchaser_email="po2@x.com")
    sell_parking_addon(t1["id"], lot["id"], lot["version"])
    fresh_version = get_lot_version(lot["id"])
    from test_helpers import create_parking_addon_payload
    res = api.create_addon(t2["id"], create_parking_addon_payload(lot["id"], fresh_version),
                           _BOXOFFICE)
    addon = validate_success(res, 201)
    assert addon["status"] == "SOLD"


# ─── cross_entity_state_dependency / approve_application_depends_on_zone_capacity ──

def test_approve_rejected_when_zone_full(api):
    """PRD §3.8: "Approval is the pivotal step: it requires that the target zone have a
    free slot — its `allocated_count` strictly below its `slot_capacity`, otherwise
    rejected with `ERR_ZONE_FULL`."

    With a freshly-read zone version (so the OCC check passes) but the zone already at
    capacity (allocated_count == slot_capacity), approving a second application is
    rejected with ERR_ZONE_FULL — the transition fails on the cross-entity Zone
    capacity even though the application is in the correct UNDER_REVIEW from-state.

    Design: Difficulty/cross_entity_state_dependency/approve_application_depends_on_zone_capacity
    """
    festival, zone, stage = create_festival_with_zone_and_stage(start_date="2026-08-01",
                                                                end_date="2026-08-02",
                                                                zone_code="A", zone_slot_capacity=1)
    zone = validate_success(api.get_zone(zone["id"], _DIRECTOR), 200)
    zone_v0 = zone["version"]
    v1, app1 = setup_application_under_review(festival["id"], zone, vendor_name="CV1")
    v2, app2 = setup_application_under_review(festival["id"], zone, vendor_name="CV2")
    validate_success(api.approve_application(app1["id"], {"expected_zone_version": zone_v0},
                                             _VENDOR_MANAGER), 200)
    fresh_zone = validate_success(api.get_zone(zone["id"], _VENDOR_MANAGER), 200)
    res = api.approve_application(app2["id"], {"expected_zone_version": fresh_zone["version"]},
                                  _VENDOR_MANAGER)
    validate_error(res, "ERR_ZONE_FULL", expected_status=409)


def test_approve_succeeds_when_zone_has_free_slot(api):
    """PRD §3.8: "Approval is the pivotal step: it requires that the target zone have a
    free slot — its `allocated_count` strictly below its `slot_capacity`."

    The complementary success side of the cross-entity dependency: with slot_capacity 2
    and one slot already allocated, a second approval still finds a free slot and
    advances the application to APPROVED.

    Design: Difficulty/cross_entity_state_dependency/approve_application_depends_on_zone_capacity
    """
    festival, zone, stage = create_festival_with_zone_and_stage(start_date="2026-08-01",
                                                                end_date="2026-08-02",
                                                                zone_code="A", zone_slot_capacity=2)
    zone = validate_success(api.get_zone(zone["id"], _DIRECTOR), 200)
    zone_v0 = zone["version"]
    v1, app1 = setup_application_under_review(festival["id"], zone, vendor_name="CW1")
    v2, app2 = setup_application_under_review(festival["id"], zone, vendor_name="CW2")
    validate_success(api.approve_application(app1["id"], {"expected_zone_version": zone_v0},
                                             _VENDOR_MANAGER), 200)
    fresh_zone = validate_success(api.get_zone(zone["id"], _VENDOR_MANAGER), 200)
    res = api.approve_application(app2["id"], {"expected_zone_version": fresh_zone["version"]},
                                  _VENDOR_MANAGER)
    approved = validate_success(res, 200)
    assert approved["status"] == "APPROVED"


# ─── resource_temporal_overlap / stage_buffered_overlap_within_changeover ───

def test_stage_conflict_within_changeover_buffer(api):
    """PRD §3.3: "the new performance must not collide with any other scheduled
    performance on the same stage once the stage's changeover buffer is taken into
    account. Treating each interval as half-open from its start up to but not including
    its end, the new performance conflicts with an existing scheduled one on the same
    stage when the new start is earlier than the existing end plus the changeover buffer
    and, simultaneously, the new end plus the changeover buffer is later than the
    existing start; such a collision is rejected with `ERR_STAGE_CONFLICT`."

    Stage changeover 30min, existing 18:00-19:00: a new set starting 19:15 collides
    because 19:15 < 19:00 + 30min buffer -> ERR_STAGE_CONFLICT.

    Design: Difficulty/resource_temporal_overlap/stage_buffered_overlap_within_changeover
    """
    festival = create_festival(start_date="2026-08-01", end_date="2026-08-02", name="StageOv F")
    create_zone(festival["id"], code="A", slot_capacity=1)
    stage = create_stage(festival["id"], name="Main", changeover_minutes=30)
    schedule_performance(stage["id"], "Nova", "2026-08-01T18:00:00Z", "2026-08-01T19:00:00Z")
    from test_helpers import create_performance_payload
    res = api.create_performance(stage["id"], create_performance_payload(
        "Pulse", "2026-08-01T19:15:00Z", "2026-08-01T20:00:00Z"), _DIRECTOR)
    validate_error(res, "ERR_STAGE_CONFLICT", expected_status=409)


def test_stage_slot_allowed_at_buffer_end(api):
    """PRD §3.3: "the new performance conflicts with an existing scheduled one on the
    same stage when the new start is earlier than the existing end plus the changeover
    buffer and, simultaneously, the new end plus the changeover buffer is later than the
    existing start."

    With changeover 30min and existing 18:00-19:00, a new set starting exactly at
    19:30 (== existing end + buffer) is NOT earlier than the buffered end, so it is
    accepted — the open boundary of the buffered conflict.

    Design: Difficulty/resource_temporal_overlap/stage_buffered_overlap_within_changeover
    """
    festival = create_festival(start_date="2026-08-01", end_date="2026-08-02", name="StageOk F")
    create_zone(festival["id"], code="A", slot_capacity=1)
    stage = create_stage(festival["id"], name="Main", changeover_minutes=30)
    schedule_performance(stage["id"], "Nova", "2026-08-01T18:00:00Z", "2026-08-01T19:00:00Z")
    from test_helpers import create_performance_payload
    res = api.create_performance(stage["id"], create_performance_payload(
        "Pulse", "2026-08-01T19:30:00Z", "2026-08-01T20:30:00Z"), _DIRECTOR)
    perf = validate_success(res, 201)
    assert perf["status"] == "SCHEDULED"


# ─── resource_temporal_overlap / artist_unbuffered_overlap_across_stages ───

def test_artist_double_booked_across_stages(api):
    """PRD §3.3: "the same artist must not be double-booked anywhere in the festival
    across all stages, evaluated with no buffer at all: treating intervals as half-open,
    the new performance conflicts with an existing scheduled performance of the same
    `artist_name` in the same festival when the new start is earlier than the existing
    end and the new end is later than the existing start. ... An artist overlap is
    rejected with `ERR_ARTIST_DOUBLE_BOOKED`."

    Artist 'Nova' booked 18:00-19:00 on stage S1 conflicts with an 18:30-19:30 booking
    on a different stage S2 (overlap, festival-wide, no buffer) -> ERR_ARTIST_DOUBLE_BOOKED.

    Design: Difficulty/resource_temporal_overlap/artist_unbuffered_overlap_across_stages
    """
    festival = create_festival(start_date="2026-08-01", end_date="2026-08-02", name="ArtistOv F")
    create_zone(festival["id"], code="A", slot_capacity=1)
    s1 = create_stage(festival["id"], name="S1", changeover_minutes=30)
    s2 = create_stage(festival["id"], name="S2", changeover_minutes=30)
    schedule_performance(s1["id"], "Nova", "2026-08-01T18:00:00Z", "2026-08-01T19:00:00Z")
    from test_helpers import create_performance_payload
    res = api.create_performance(s2["id"], create_performance_payload(
        "Nova", "2026-08-01T18:30:00Z", "2026-08-01T19:30:00Z"), _DIRECTOR)
    validate_error(res, "ERR_ARTIST_DOUBLE_BOOKED", expected_status=409)


def test_artist_exact_adjacency_allowed_across_stages(api):
    """PRD §3.3: "Exact adjacency — where one set ends at the precise instant the next
    begins — is allowed and does not constitute a conflict."

    Artist 'Nova' 18:00-19:00 on S1 followed by 'Nova' 19:00-20:00 on S2 is exact
    adjacency with no buffer for the artist rule, so the second booking is accepted —
    distinct interval geometry from the buffered stage rule.

    Design: Difficulty/resource_temporal_overlap/artist_unbuffered_overlap_across_stages
    """
    festival = create_festival(start_date="2026-08-01", end_date="2026-08-02", name="ArtistOk F")
    create_zone(festival["id"], code="A", slot_capacity=1)
    s1 = create_stage(festival["id"], name="S1", changeover_minutes=30)
    s2 = create_stage(festival["id"], name="S2", changeover_minutes=30)
    schedule_performance(s1["id"], "Nova", "2026-08-01T18:00:00Z", "2026-08-01T19:00:00Z")
    from test_helpers import create_performance_payload
    res = api.create_performance(s2["id"], create_performance_payload(
        "Nova", "2026-08-01T19:00:00Z", "2026-08-01T20:00:00Z"), _DIRECTOR)
    perf = validate_success(res, 201)
    assert perf["status"] == "SCHEDULED"


# ─── compensating_invariant / zone_slot_conserved_approve_then_withdraw ───

def test_zone_slot_conserved_after_approve_then_withdraw(api):
    """PRD §3.8: "Alternatively the owning vendor may withdraw the application from
    `APPROVED` to the terminal `WITHDRAWN`, permitted only when `fee_paid` is 0;
    withdrawal is a compensation that decrements the zone's `allocated_count` by one and
    advances the zone's `version`, releasing the slot."

    Approve raises the zone's allocated_count 0->1; the compensating withdraw returns it
    1->0, leaving the conserved booth-slot count at 0 with no leakage and the
    application terminal at WITHDRAWN.

    Design: Difficulty/compensating_invariant/zone_slot_conserved_approve_then_withdraw
    """
    festival, zone, stage = create_festival_with_zone_and_stage(start_date="2026-08-01",
                                                                end_date="2026-08-02",
                                                                zone_code="A", zone_slot_capacity=1)
    zone = validate_success(api.get_zone(zone["id"], _DIRECTOR), 200)
    vendor, app = setup_approved_application(festival["id"], zone, booth_tier="STANDARD",
                                             day_count=2, vendor_name="SInv Co")
    res = api.withdraw_application(app["id"], make_vendor_headers(vendor["id"]))
    withdrawn = validate_success(res, 200)
    assert withdrawn["status"] == "WITHDRAWN"
    zone_after = validate_success(api.get_zone(zone["id"], _VENDOR_MANAGER), 200)
    assert_zone(zone_after)
    assert zone_after["allocated_count"] == 0, (
        f"expected allocated_count 0, got {zone_after['allocated_count']}")


def test_zone_allocated_count_one_after_approve(api):
    """PRD §2.8: "A zone tracks `allocated_count`, the number of vendor applications
    against it whose `status` is `APPROVED` or `CONFIRMED` — this is the conserved
    quantity behind the booth-slot capacity check."

    The pre-compensation state of the invariant: after a single approval the zone's
    allocated_count is exactly 1, the value the withdraw must later return to 0.

    Design: Difficulty/compensating_invariant/zone_slot_conserved_approve_then_withdraw
    """
    festival, zone, stage = create_festival_with_zone_and_stage(start_date="2026-08-01",
                                                                end_date="2026-08-02",
                                                                zone_code="A", zone_slot_capacity=1)
    zone = validate_success(api.get_zone(zone["id"], _DIRECTOR), 200)
    vendor, app = setup_approved_application(festival["id"], zone, booth_tier="STANDARD",
                                             day_count=2, vendor_name="SInv2 Co")
    zone_after = validate_success(api.get_zone(zone["id"], _VENDOR_MANAGER), 200)
    assert zone_after["allocated_count"] == 1
