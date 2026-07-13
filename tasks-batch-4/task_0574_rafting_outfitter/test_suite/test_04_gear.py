"""Gear fitting: PFD weight range, duplicate-type constraint, precedence, and the
serviceable-inventory conservation invariant."""
from test_helpers import validate_success, validate_error, validate_paginated
from test_helpers import TEST_USERS
from test_helpers.fixtures import (
    setup_open_trip, create_reservation, add_guest, create_gear_item, assign_gear,
)
from test_helpers.factories import create_gear_assignment_payload

MGR = TEST_USERS["outfitter_manager_headers"]
RESV = TEST_USERS["reservationist_headers"]


def _serviceable_pfd_count(api):
    """Client-side computation of serviceable PFD inventory: count of PFD GearItems in
    status AVAILABLE or ASSIGNED (excluding OUT_OF_SERVICE), read from the full list."""
    data, _ = validate_paginated(api.list_gear_items(RESV, params={"limit": 100}))
    return sum(1 for g in data if g["gear_type"] == "PFD" and g["status"] in ("AVAILABLE", "ASSIGNED"))


def _available_pfd_count(api):
    data, _ = validate_paginated(api.list_gear_items(RESV, params={"limit": 100}))
    return sum(1 for g in data if g["gear_type"] == "PFD" and g["status"] == "AVAILABLE")


# ── Priority: safety (weight) beats constraint (duplicate gear type) ──

def test_weight_out_of_range_beats_duplicate_gear_type(api):
    """PRD §2.6: "When more than one rule could reject a request, the checks are applied
    in a fixed order of precedence, and the first failing check determines the returned error."
    PRD §3.4: "the guest's `weight_lbs` must lie within the item's inclusive range from
    `min_weight_lbs` to `max_weight_lbs`, otherwise `ERR_WEIGHT_OUT_OF_RANGE`."
    PRD §3.4: "if the guest already holds an `ASSIGNED` gear assignment of the same
    `gear_type`, the new assignment is rejected with `ERR_DUPLICATE_GEAR_TYPE`."

    Design: Difficulty/priority_pair_validation_conflict/weight_safety_beats_duplicate_gear_constraint
    """
    trip, _, _ = setup_open_trip(api)
    pfd_a = create_gear_item(api, gear_type="PFD", size_label="XL", min_weight_lbs=100, max_weight_lbs=300)
    pfd_b = create_gear_item(api, gear_type="PFD", size_label="L", min_weight_lbs=100, max_weight_lbs=250)
    res = create_reservation(api, trip["id"], party_size=1, deposit_cents=3000)
    guest = add_guest(api, res["id"], full_name="Gil", age=45, weight_lbs=260)
    assign_gear(api, pfd_a["id"], guest["id"], trip["id"])  # accepted: 260 within 100-300
    # Second PFD (100-250) both duplicates the PFD type (P7) and excludes weight 260 (P5).
    resp = api.create_gear_assignment(
        create_gear_assignment_payload(pfd_b["id"], guest["id"], trip["id"]), RESV)
    validate_error(resp, "ERR_WEIGHT_OUT_OF_RANGE")


def test_weight_out_of_range_isolated(api):
    """PRD §3.4: "For weight-sensitive gear (a `PFD` or `WETSUIT`), the guest's
    `weight_lbs` must lie within the item's inclusive range from `min_weight_lbs` to
    `max_weight_lbs`, otherwise `ERR_WEIGHT_OUT_OF_RANGE`."

    Design: Difficulty/priority_pair_validation_conflict/weight_safety_beats_duplicate_gear_constraint
    """
    trip, _, _ = setup_open_trip(api)
    pfd = create_gear_item(api, gear_type="PFD", min_weight_lbs=100, max_weight_lbs=250)
    res = create_reservation(api, trip["id"], party_size=1, deposit_cents=3000)
    guest = add_guest(api, res["id"], full_name="Gil", age=45, weight_lbs=260)
    resp = api.create_gear_assignment(
        create_gear_assignment_payload(pfd["id"], guest["id"], trip["id"]), RESV)
    validate_error(resp, "ERR_WEIGHT_OUT_OF_RANGE")


# ── PFD weight range inclusive upper bound ──

def test_pfd_weight_equal_upper_bound_accepted(api):
    """PRD §3.4: "the guest's `weight_lbs` must lie within the item's inclusive range from
    `min_weight_lbs` to `max_weight_lbs`, otherwise `ERR_WEIGHT_OUT_OF_RANGE`."
    PRD §3.4: "on success the assignment begins in `status` `ASSIGNED` and the linked gear
    item moves from `AVAILABLE` to `ASSIGNED`."

    Design: Difficulty/boundary_precision_check/pfd_weight_range_inclusive_upper_bound_accepts
    """
    trip, _, _ = setup_open_trip(api)
    pfd = create_gear_item(api, gear_type="PFD", size_label="M", min_weight_lbs=100, max_weight_lbs=200)
    res = create_reservation(api, trip["id"], party_size=1, deposit_cents=3000)
    guest = add_guest(api, res["id"], full_name="Ivy", age=35, weight_lbs=200)
    gasg = validate_success(
        api.create_gear_assignment(create_gear_assignment_payload(pfd["id"], guest["id"], trip["id"]), RESV), 201)
    assert gasg["status"] == "ASSIGNED"
    item = validate_success(api.get_gear_item(pfd["id"], RESV), 200)
    assert item["status"] == "ASSIGNED"


def test_pfd_weight_above_upper_bound_rejected(api):
    """PRD §3.4: "For weight-sensitive gear (a `PFD` or `WETSUIT`), the guest's
    `weight_lbs` must lie within the item's inclusive range from `min_weight_lbs` to
    `max_weight_lbs`, otherwise `ERR_WEIGHT_OUT_OF_RANGE`."

    Design: Difficulty/boundary_precision_check/pfd_weight_range_inclusive_upper_bound_accepts
    """
    trip, _, _ = setup_open_trip(api)
    pfd = create_gear_item(api, gear_type="PFD", size_label="M", min_weight_lbs=100, max_weight_lbs=200)
    res = create_reservation(api, trip["id"], party_size=1, deposit_cents=3000)
    guest = add_guest(api, res["id"], full_name="Ivo", age=35, weight_lbs=201)
    resp = api.create_gear_assignment(
        create_gear_assignment_payload(pfd["id"], guest["id"], trip["id"]), RESV)
    validate_error(resp, "ERR_WEIGHT_OUT_OF_RANGE")


# ── Serviceable-inventory conservation across assign + release ──

def test_serviceable_pfd_count_conserved_across_assign_release(api):
    """PRD §3.4: "the serviceable inventory of any given `gear_type` — the count of items
    that are `AVAILABLE` plus the count that are `ASSIGNED`, excluding those
    `OUT_OF_SERVICE` — is invariant across an assign followed by its compensating release."
    PRD §3.4: "Releasing a gear assignment moves its `status` from `ASSIGNED` to
    `RELEASED` and returns the linked gear item's `status` to `AVAILABLE`."

    Design: Difficulty/compensating_invariant/gear_serviceable_count_conserved_across_assign_release
    """
    trip, _, _ = setup_open_trip(api)
    pfd = create_gear_item(api, gear_type="PFD", min_weight_lbs=100, max_weight_lbs=250)
    res = create_reservation(api, trip["id"], party_size=1, deposit_cents=3000)
    guest = add_guest(api, res["id"], full_name="Kim", age=30, weight_lbs=175)
    serviceable_before = _serviceable_pfd_count(api)
    gasg = assign_gear(api, pfd["id"], guest["id"], trip["id"])
    released = validate_success(api.release_gear_assignment(gasg["id"], RESV), 200)
    assert released["status"] == "RELEASED"
    item = validate_success(api.get_gear_item(pfd["id"], RESV), 200)
    assert item["status"] == "AVAILABLE"
    assert _serviceable_pfd_count(api) == serviceable_before == 1


def test_available_pfd_count_restored_after_release(api):
    """PRD §3.4: "on success the assignment begins in `status` `ASSIGNED` and the linked
    gear item moves from `AVAILABLE` to `ASSIGNED`."
    PRD §3.4: "Releasing a gear assignment moves its `status` from `ASSIGNED` to
    `RELEASED` and returns the linked gear item's `status` to `AVAILABLE`."

    Design: Difficulty/compensating_invariant/gear_serviceable_count_conserved_across_assign_release
    """
    trip, _, _ = setup_open_trip(api)
    pfd = create_gear_item(api, gear_type="PFD", min_weight_lbs=100, max_weight_lbs=250)
    res = create_reservation(api, trip["id"], party_size=1, deposit_cents=3000)
    guest = add_guest(api, res["id"], full_name="Kim", age=30, weight_lbs=175)
    assert _available_pfd_count(api) == 1
    gasg = assign_gear(api, pfd["id"], guest["id"], trip["id"])
    assert _available_pfd_count(api) == 0            # moved AVAILABLE -> ASSIGNED
    assert _serviceable_pfd_count(api) == 1          # still serviceable while ASSIGNED
    validate_success(api.release_gear_assignment(gasg["id"], RESV), 200)
    assert _available_pfd_count(api) == 1            # restored on release


# ── Retired gear cannot be assigned (corner) ──

def test_retired_gear_cannot_be_assigned(api):
    """PRD §3.4: "Creating the assignment requires the gear item to be `AVAILABLE`,
    otherwise `ERR_GEAR_UNAVAILABLE`."

    Design: Corner/state_machines/retired_gear_cannot_be_assigned
    """
    trip, _, _ = setup_open_trip(api, difficulty_class="CLASS_II", guide_class="CLASS_II")
    pfd = create_gear_item(api, gear_type="PFD", min_weight_lbs=100, max_weight_lbs=250)
    validate_success(api.retire_gear_item(pfd["id"], MGR), 200)
    res = create_reservation(api, trip["id"], party_size=1, deposit_cents=3000)
    guest = add_guest(api, res["id"], full_name="Bo", age=30, weight_lbs=175)
    resp = api.create_gear_assignment(
        create_gear_assignment_payload(pfd["id"], guest["id"], trip["id"]), RESV)
    validate_error(resp, "ERR_GEAR_UNAVAILABLE")
