"""Confirmation-time validation-priority conflicts and cross-entity state
dependencies. Covers difficulty rules priority_pair_validation_conflict,
cross_entity_state_dependency, and resource_temporal_overlap."""
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS,
    create_trail, create_unit, create_gear, create_guide, create_departure,
    register_member, register_signed_member, train_member,
    create_reservation, create_and_confirm_reservation,
    current_departure_version, assign_guide, lock_departure,
    read_reservation, read_departure,
    make_member_headers,
)

DISPATCH = TEST_USERS["dispatch_headers"]


# ===================================================================
# Rule priority_pair_validation_conflict
# ===================================================================

def test_waiver_unsigned_beats_departure_full_on_confirm(api):
    """PRD §3.4: "the confirmation-specific business gates fire in this exact sequence:
    the departure must still be open, then the waiver must be signed, then the rider
    must be old enough, then training must suffice for the unit class, then the unit
    must be capable for the trail, then the unit must not be double-booked, then the
    gear must not be double-booked, then there must be capacity remaining, and finally
    the optimistic-concurrency version must match."

    Design: Difficulty/priority_pair_validation_conflict/waiver_safety_beats_capacity_fiscal_on_confirm
    """
    trail = create_trail(name="Tiny", required_class="TRAIL", max_riders=1)
    unit_b = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    unit_a = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    dep = create_departure(trail["id"], starts_at="2026-12-24T09:00:00Z",
                           ends_at="2026-12-24T12:00:00Z", required_guide_class="TRAIL", capacity_riders=1)
    # Member B fills the single capacity slot.
    mem_b = register_signed_member()
    create_and_confirm_reservation(mem_b, dep["id"], unit_b["id"], expected_version=dep["version"])
    # Member A has an UNSIGNED waiver and a PENDING reservation on the same (now full) departure.
    mem_a = register_member()
    res_a = create_reservation(mem_a, dep["id"], unit_a["id"])
    dep_ver = current_departure_version(dep["id"])
    resp = api.confirm_reservation(res_a["id"], {"expected_tour_departure_version": dep_ver},
                                   make_member_headers(mem_a["id"]))
    validate_error(resp, "ERR_WAIVER_NOT_SIGNED", expected_status=409)


def test_departure_not_open_beats_unit_double_booked_on_confirm(api):
    """PRD §3.4: "the confirmation-specific business gates fire in this exact sequence:
    the departure must still be open, then the waiver must be signed, then the rider
    must be old enough, then training must suffice for the unit class, then the unit
    must be capable for the trail, then the unit must not be double-booked, then the
    gear must not be double-booked, then there must be capacity remaining, and finally
    the optimistic-concurrency version must match."

    Design: Difficulty/priority_pair_validation_conflict/departure_state_beats_unit_temporal_on_confirm
    """
    trail = create_trail(name="Ovl", required_class="TRAIL", max_riders=10)
    unit_filler = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    unit_shared = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    guide = create_guide(max_class="TRAIL")
    d1 = create_departure(trail["id"], starts_at="2026-12-26T09:00:00Z",
                          ends_at="2026-12-26T17:00:00Z", required_guide_class="TRAIL", capacity_riders=10)
    d2 = create_departure(trail["id"], starts_at="2026-12-26T12:00:00Z",
                          ends_at="2026-12-26T20:00:00Z", required_guide_class="TRAIL", capacity_riders=10)
    # unit_shared booked over overlapping D2 by member F.
    mem_f = register_signed_member()
    create_and_confirm_reservation(mem_f, d2["id"], unit_shared["id"], expected_version=d2["version"])
    # D1 gets a confirmed rider (filler unit) + guide, then locked.
    mem_g = register_signed_member()
    create_and_confirm_reservation(mem_g, d1["id"], unit_filler["id"], expected_version=d1["version"])
    assign_guide(d1["id"], guide["id"])
    locked = lock_departure(d1["id"])
    # Member A tries to confirm onto LOCKED D1 with the already-booked unit_shared.
    mem_a = register_signed_member()
    res_a = create_reservation(mem_a, d1["id"], unit_shared["id"])
    resp = api.confirm_reservation(res_a["id"], {"expected_tour_departure_version": locked["version"]},
                                   make_member_headers(mem_a["id"]))
    validate_error(resp, "ERR_DEPARTURE_NOT_OPEN", expected_status=409)


# ===================================================================
# Rule cross_entity_state_dependency
# ===================================================================

def test_lock_rejected_when_trail_closed(api):
    """PRD §3.3: "the departure's trail must not be `CLOSED`; locking against a closed
    trail is rejected with `ERR_TRAIL_CLOSED`."
    PRD §3.7: "A `CLOSED` condition gates the lock and depart transitions of a departure
    but does not by itself prevent new departures from being scheduled on the trail".

    Design: Difficulty/cross_entity_state_dependency/lock_requires_trail_not_closed_departure_to_trail
    """
    trail = create_trail(name="ClsLock", required_class="TRAIL", max_riders=10)
    get_success_data(api.post_closure(trail["id"], {"new_condition": "CLOSED", "reason": "storm"}, DISPATCH))
    unit = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    guide = create_guide(max_class="TRAIL")
    # Scheduling permitted on a closed trail; only lock/depart consult condition.
    dep = create_departure(trail["id"], starts_at="2027-01-02T09:00:00Z",
                           ends_at="2027-01-02T12:00:00Z", required_guide_class="TRAIL", capacity_riders=10)
    mem = register_signed_member()
    create_and_confirm_reservation(mem, dep["id"], unit["id"], expected_version=dep["version"])
    assign_guide(dep["id"], guide["id"])
    resp = api.lock_departure(dep["id"], DISPATCH)
    validate_error(resp, "ERR_TRAIL_CLOSED", expected_status=409)
    assert read_departure(dep["id"])["status"] == "SCHEDULED"


def test_confirm_mountain_unit_requires_advanced_training(api):
    """PRD §3.5: "The training gate applies only to mountain sleds: if the chosen unit's
    `unit_class` is `MOUNTAIN`, the member's `training_level` must be `ADVANCED`, failing
    which the confirm is rejected with `ERR_TRAINING_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/confirm_mountain_requires_member_training_reservation_to_member
    """
    trail = create_trail(name="MtnT", required_class="MOUNTAIN", max_riders=8)
    unit = create_unit(unit_class="MOUNTAIN", daily_rate_cents=12000, deposit_cents=40000, tank_capacity_liters=50)
    dep = create_departure(trail["id"], starts_at="2027-01-05T09:00:00Z",
                           ends_at="2027-01-05T15:00:00Z", required_guide_class="MOUNTAIN", capacity_riders=8)
    mem = register_signed_member()
    train_member(mem["id"], "BASIC")  # BASIC, not ADVANCED
    res = create_reservation(mem, dep["id"], unit["id"])
    resp = api.confirm_reservation(res["id"], {"expected_tour_departure_version": dep["version"]},
                                   make_member_headers(mem["id"]))
    validate_error(resp, "ERR_TRAINING_REQUIRED", expected_status=409)
    assert read_reservation(res["id"])["reservation_status"] == "PENDING"


# ===================================================================
# Rule resource_temporal_overlap
# ===================================================================

def test_unit_half_open_overlap_rejected(api):
    """PRD §3.5: "The unit gate rejects the confirm with `ERR_UNIT_DOUBLE_BOOKED` if the
    chosen unit has any other reservation in `CONFIRMED` or `CHECKED_OUT` whose departure
    window, taken as the half-open interval from `starts_at` up to but not including
    `ends_at`, overlaps this departure's window."

    Design: Difficulty/resource_temporal_overlap/unit_half_open_overlap_rejects_but_adjacent_ok
    """
    trail = create_trail(name="UnitOvl", required_class="TRAIL", max_riders=10)
    unit = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    d1 = create_departure(trail["id"], starts_at="2027-01-08T09:00:00Z",
                          ends_at="2027-01-08T17:00:00Z", required_guide_class="TRAIL", capacity_riders=10)
    d2 = create_departure(trail["id"], starts_at="2027-01-08T12:00:00Z",
                          ends_at="2027-01-08T20:00:00Z", required_guide_class="TRAIL", capacity_riders=10)
    m1 = register_signed_member()
    create_and_confirm_reservation(m1, d1["id"], unit["id"], expected_version=d1["version"])
    m2 = register_signed_member()
    res2 = create_reservation(m2, d2["id"], unit["id"])
    resp = api.confirm_reservation(res2["id"], {"expected_tour_departure_version": d2["version"]},
                                   make_member_headers(m2["id"]))
    validate_error(resp, "ERR_UNIT_DOUBLE_BOOKED", expected_status=409)


def test_unit_adjacent_window_accepted(api):
    """PRD §3.5: "The unit gate rejects the confirm with `ERR_UNIT_DOUBLE_BOOKED` if the
    chosen unit has any other reservation in `CONFIRMED` or `CHECKED_OUT` whose departure
    window, taken as the half-open interval from `starts_at` up to but not including
    `ends_at`, overlaps this departure's window."

    Design: Difficulty/resource_temporal_overlap/unit_half_open_overlap_rejects_but_adjacent_ok
    """
    # Half-open: D1 end == D3 start does NOT overlap, so the same unit is accepted.
    trail = create_trail(name="UnitAdj", required_class="TRAIL", max_riders=10)
    unit = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    d1 = create_departure(trail["id"], starts_at="2027-01-08T09:00:00Z",
                          ends_at="2027-01-08T17:00:00Z", required_guide_class="TRAIL", capacity_riders=10)
    d3 = create_departure(trail["id"], starts_at="2027-01-08T17:00:00Z",
                          ends_at="2027-01-09T01:00:00Z", required_guide_class="TRAIL", capacity_riders=10)
    m1 = register_signed_member()
    create_and_confirm_reservation(m1, d1["id"], unit["id"], expected_version=d1["version"])
    m3 = register_signed_member()
    confirmed3 = create_and_confirm_reservation(m3, d3["id"], unit["id"], expected_version=d3["version"])
    assert confirmed3["reservation_status"] == "CONFIRMED"


def test_gear_buffered_closed_overlap_rejects_adjacent(api):
    """PRD §3.5: "gear is checked against a closed interval that runs from `starts_at`
    to `ends_at` inclusive, padded by a turnaround buffer of 60 minutes on each side to
    allow for cleaning and drying between riders. The wider, inclusive, buffered window
    for gear is intentional and differs from the narrower half-open window used for units."

    Design: Difficulty/resource_temporal_overlap/gear_closed_buffered_overlap_rejects_adjacent_departure
    """
    trail = create_trail(name="GearOvl", required_class="TRAIL", max_riders=10)
    unit1 = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    unit2 = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    helmet = create_gear(kind="HELMET", size_code="M", replacement_cost_cents=12000)
    d1 = create_departure(trail["id"], starts_at="2027-01-10T09:00:00Z",
                          ends_at="2027-01-10T17:00:00Z", required_guide_class="TRAIL", capacity_riders=10)
    d3 = create_departure(trail["id"], starts_at="2027-01-10T17:00:00Z",
                          ends_at="2027-01-11T01:00:00Z", required_guide_class="TRAIL", capacity_riders=10)
    m1 = register_signed_member()
    create_and_confirm_reservation(m1, d1["id"], unit1["id"], helmet_id=helmet["id"], expected_version=d1["version"])
    m2 = register_signed_member()
    res2 = create_reservation(m2, d3["id"], unit2["id"], helmet_id=helmet["id"])
    # D1 buffered window [08:00,18:00] contains D3's 17:00 start -> rejected, unlike the unit case.
    resp = api.confirm_reservation(res2["id"], {"expected_tour_departure_version": d3["version"]},
                                   make_member_headers(m2["id"]))
    validate_error(resp, "ERR_GEAR_DOUBLE_BOOKED", expected_status=409)


# ===================================================================
# Second tests per instance (≥2 coverage)
# ===================================================================

def test_waiver_winner_leaves_reservation_pending(api):
    """PRD §3.5: "The waiver gate requires the member's `waiver_status` to be `SIGNED`;
    otherwise the confirm is rejected with `ERR_WAIVER_NOT_SIGNED`."
    PRD §3.4: "an earlier failure masks a later one and tests always see the first
    applicable rejection."

    Design: Difficulty/priority_pair_validation_conflict/waiver_safety_beats_capacity_fiscal_on_confirm
    """
    trail = create_trail(name="Tiny2", required_class="TRAIL", max_riders=1)
    unit_b = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    unit_a = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    dep = create_departure(trail["id"], starts_at="2026-12-24T09:00:00Z",
                           ends_at="2026-12-24T12:00:00Z", required_guide_class="TRAIL", capacity_riders=1)
    mem_b = register_signed_member()
    create_and_confirm_reservation(mem_b, dep["id"], unit_b["id"], expected_version=dep["version"])
    mem_a = register_member()  # UNSIGNED waiver
    res_a = create_reservation(mem_a, dep["id"], unit_a["id"])
    dep_ver = current_departure_version(dep["id"])
    resp = api.confirm_reservation(res_a["id"], {"expected_tour_departure_version": dep_ver},
                                   make_member_headers(mem_a["id"]))
    validate_error(resp, "ERR_WAIVER_NOT_SIGNED", expected_status=409)
    # The rejected reservation is untouched (still PENDING), confirming no side effect ran.
    assert read_reservation(res_a["id"])["reservation_status"] == "PENDING"


def test_departure_not_open_winner_leaves_reservation_pending(api):
    """PRD §3.5: "The departure-open gate requires the `TourDeparture` to still be
    `SCHEDULED` — not `LOCKED`, `DEPARTED`, `CANCELLED`, or `COMPLETED` — because a locked
    or departed tour no longer accepts riders; a confirm against a non-`SCHEDULED`
    departure is rejected with `ERR_DEPARTURE_NOT_OPEN`."

    Design: Difficulty/priority_pair_validation_conflict/departure_state_beats_unit_temporal_on_confirm
    """
    trail = create_trail(name="Ovl2", required_class="TRAIL", max_riders=10)
    unit_filler = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    unit_shared = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    guide = create_guide(max_class="TRAIL")
    d1 = create_departure(trail["id"], starts_at="2026-12-26T09:00:00Z",
                          ends_at="2026-12-26T17:00:00Z", required_guide_class="TRAIL", capacity_riders=10)
    d2 = create_departure(trail["id"], starts_at="2026-12-26T12:00:00Z",
                          ends_at="2026-12-26T20:00:00Z", required_guide_class="TRAIL", capacity_riders=10)
    mem_f = register_signed_member()
    create_and_confirm_reservation(mem_f, d2["id"], unit_shared["id"], expected_version=d2["version"])
    mem_g = register_signed_member()
    create_and_confirm_reservation(mem_g, d1["id"], unit_filler["id"], expected_version=d1["version"])
    assign_guide(d1["id"], guide["id"])
    locked = lock_departure(d1["id"])
    mem_a = register_signed_member()
    res_a = create_reservation(mem_a, d1["id"], unit_shared["id"])
    resp = api.confirm_reservation(res_a["id"], {"expected_tour_departure_version": locked["version"]},
                                   make_member_headers(mem_a["id"]))
    validate_error(resp, "ERR_DEPARTURE_NOT_OPEN", expected_status=409)
    assert read_reservation(res_a["id"])["reservation_status"] == "PENDING"


def test_lock_succeeds_after_trail_reopened(api):
    """PRD §3.3: "the departure's trail must not be `CLOSED`; locking against a closed
    trail is rejected with `ERR_TRAIL_CLOSED`."
    PRD §3.3: "Locking moves the departure from `SCHEDULED` to `LOCKED`".

    Design: Difficulty/cross_entity_state_dependency/lock_requires_trail_not_closed_departure_to_trail
    """
    from test_helpers import get_success_data
    trail = create_trail(name="ClsReopen", required_class="TRAIL", max_riders=10)
    get_success_data(api.post_closure(trail["id"], {"new_condition": "CLOSED", "reason": "storm"}, DISPATCH))
    unit = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    guide = create_guide(max_class="TRAIL")
    dep = create_departure(trail["id"], starts_at="2027-01-03T09:00:00Z",
                           ends_at="2027-01-03T12:00:00Z", required_guide_class="TRAIL", capacity_riders=10)
    mem = register_signed_member()
    create_and_confirm_reservation(mem, dep["id"], unit["id"], expected_version=dep["version"])
    assign_guide(dep["id"], guide["id"])
    # Lock fails while CLOSED ...
    validate_error(api.lock_departure(dep["id"], DISPATCH), "ERR_TRAIL_CLOSED", expected_status=409)
    # ... and succeeds once the trail is reopened, proving the gate is specifically CLOSED.
    get_success_data(api.post_closure(trail["id"], {"new_condition": "OPEN", "reason": "cleared"}, DISPATCH))
    locked = validate_success(api.lock_departure(dep["id"], DISPATCH), 200)
    assert locked["status"] == "LOCKED"


def test_confirm_mountain_unit_succeeds_with_advanced_training(api):
    """PRD §3.5: "if the chosen unit's `unit_class` is `MOUNTAIN`, the member's
    `training_level` must be `ADVANCED`, failing which the confirm is rejected with
    `ERR_TRAINING_REQUIRED`."
    PRD §3.1: "The significance of `ADVANCED` is that it is the prerequisite for riding
    any `MOUNTAIN`-class sled, enforced at confirmation time as described in §3.5."

    Design: Difficulty/cross_entity_state_dependency/confirm_mountain_requires_member_training_reservation_to_member
    """
    trail = create_trail(name="MtnT2", required_class="MOUNTAIN", max_riders=8)
    unit = create_unit(unit_class="MOUNTAIN", daily_rate_cents=12000, deposit_cents=40000, tank_capacity_liters=50)
    dep = create_departure(trail["id"], starts_at="2027-01-05T09:00:00Z",
                           ends_at="2027-01-05T15:00:00Z", required_guide_class="MOUNTAIN", capacity_riders=8)
    mem = register_signed_member()
    train_member(mem["id"], "BASIC")
    train_member(mem["id"], "ADVANCED")  # now eligible
    confirmed = create_and_confirm_reservation(mem, dep["id"], unit["id"], expected_version=dep["version"])
    assert confirmed["reservation_status"] == "CONFIRMED"


def test_gear_adjacent_window_rejected_unlike_unit(api):
    """PRD §3.5: "gear is checked against a closed interval that runs from `starts_at`
    to `ends_at` inclusive, padded by a turnaround buffer of 60 minutes on each side to
    allow for cleaning and drying between riders. The wider, inclusive, buffered window
    for gear is intentional and differs from the narrower half-open window used for units."

    Design: Difficulty/resource_temporal_overlap/gear_closed_buffered_overlap_rejects_adjacent_departure
    """
    # Same helmet, on two adjacent departures whose only contact is at 17:00 (D1 end = D3 start).
    # For units this is accepted (half-open); for gear the 60-min buffer makes it overlap.
    trail = create_trail(name="GearOvl2", required_class="TRAIL", max_riders=10)
    unit1 = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    unit2 = create_unit(unit_class="TRAIL", daily_rate_cents=5000, deposit_cents=25000, tank_capacity_liters=30)
    suit = create_gear(kind="SUIT", size_code="L", replacement_cost_cents=20000)
    d1 = create_departure(trail["id"], starts_at="2027-01-10T09:00:00Z",
                          ends_at="2027-01-10T17:00:00Z", required_guide_class="TRAIL", capacity_riders=10)
    d3 = create_departure(trail["id"], starts_at="2027-01-10T17:00:00Z",
                          ends_at="2027-01-11T01:00:00Z", required_guide_class="TRAIL", capacity_riders=10)
    m1 = register_signed_member()
    create_and_confirm_reservation(m1, d1["id"], unit1["id"], suit_id=suit["id"], expected_version=d1["version"])
    m2 = register_signed_member()
    res2 = create_reservation(m2, d3["id"], unit2["id"], suit_id=suit["id"])
    resp = api.confirm_reservation(res2["id"], {"expected_tour_departure_version": d3["version"]},
                                   make_member_headers(m2["id"]))
    validate_error(resp, "ERR_GEAR_DOUBLE_BOOKED", expected_status=409)
