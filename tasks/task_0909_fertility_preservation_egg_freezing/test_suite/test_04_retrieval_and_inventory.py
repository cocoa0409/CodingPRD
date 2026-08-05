"""Retrieval, the cryopreservation cascade, tank-capacity boundary, and room-overlap
temporal semantics.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    retrieve_payload,
)
from test_helpers import fixtures as fx

COORD = TEST_USERS["coordinator_headers"]


# --------------------------------------------------------------- Difficulty: retrieval cascade depth-3
def test_retrieval_fills_tank_slots_and_sets_is_full(api):
    """PRD §2.7: "A StorageTank's used_slots is the count of `CryoSpecimen` rows assigned to
    that tank whose `status` is either `STORED` or `RESERVED`. The tank's `is_full` is true
    exactly when `used_slots` is greater than or equal to `capacity_slots`."

    Design: Difficulty/transitive_cascade/retrieval_complete_cascade_depth3
    """
    b = fx.setup_retrieved_cycle(mature_oocyte_count=2, tank_capacity=2, with_subscription=True)
    tank = validate_success(api.get_storage_tank(b["tank_id"], COORD), 200)
    assert tank["used_slots"] == 2, f"two specimens must occupy two slots, got {tank['used_slots']}"
    assert tank["is_full"] is True, "a capacity-2 tank holding two specimens is full"


def test_retrieval_increments_subscription_specimen_count(api):
    """PRD §3.4: "If the patient has a StorageSubscription, its specimen_count increases by the
    newly created specimens and its annual_fee_cents is recomputed via the storage-renewal-fee
    rule (§3.5)."

    Design: Difficulty/transitive_cascade/retrieval_complete_cascade_depth3
    """
    b = fx.setup_retrieved_cycle(mature_oocyte_count=2, tank_capacity=2, with_subscription=True)
    sub = validate_success(api.get_storage_subscription(b["subscription_id"], COORD), 200)
    assert sub["specimen_count"] == 2, f"subscription must count both specimens, got {sub['specimen_count']}"


# --------------------------------------------------------------- Difficulty: tank capacity boundary
def test_retrieve_over_tank_capacity_rejected(api):
    """PRD §3.4: "if the tank's current used_slots plus the number of specimens to be created
    would exceed the tank's capacity_slots, the request is rejected with ERR_TANK_AT_CAPACITY;
    storage is permitted exactly up to and including the tank's capacity."

    Design: Difficulty/boundary_precision_check/tank_capacity_at_boundary
    """
    b = fx.setup_triggered_cycle(num_visits=3)
    room_id = fx.create_room("OR-Cap")
    tank_id = fx.create_tank(2, "Tank-Cap")
    phys = fx.make_physician_headers(b["phys_id"])
    # Storing 3 specimens into a capacity-2 tank exceeds capacity.
    resp = api.retrieve_cycle(
        b["cycle_id"], retrieve_payload(room_id, tank_id, mature_oocyte_count=3,
                                        oocytes_retrieved=9), phys)
    validate_error(resp, ApiErrorId.ERR_TANK_AT_CAPACITY.value, 409)


def test_retrieve_exactly_at_tank_capacity_succeeds(api):
    """PRD §3.4: "storage is permitted exactly up to and including the tank's capacity."
    PRD §2.7: "The tank's is_full is true exactly when used_slots is greater than or equal to
    capacity_slots."

    Design: Difficulty/boundary_precision_check/tank_capacity_at_boundary
    """
    b = fx.setup_triggered_cycle(num_visits=3)
    room_id = fx.create_room("OR-Cap2")
    tank_id = fx.create_tank(3, "Tank-Cap2")
    phys = fx.make_physician_headers(b["phys_id"])
    data = validate_success(
        api.retrieve_cycle(b["cycle_id"], retrieve_payload(room_id, tank_id, mature_oocyte_count=3,
                                                           oocytes_retrieved=9), phys), 200)
    assert data["status"] == "COMPLETED", "retrieval up to capacity must succeed"
    tank = validate_success(api.get_storage_tank(tank_id, COORD), 200)
    assert tank["used_slots"] == 3 and tank["is_full"] is True, "tank filled exactly to capacity"


# --------------------------------------------------------------- Difficulty: room half-open adjacency
def test_adjacent_retrieval_after_existing_allowed(api):
    """PRD §3.4: "treating the window as half-open with no buffer so that adjacent windows
    sharing only an endpoint do not conflict, the request is rejected with ERR_ROOM_UNAVAILABLE."
    PRD §2.6: "back-to-back retrievals that merely touch at an endpoint are allowed."

    Design: Difficulty/resource_temporal_overlap/room_retrieval_adjacent_allowed
    """
    b = fx.setup_two_retrieval_cycles(first_start="2026-05-10T08:00:00Z",
                                      first_end="2026-05-10T09:00:00Z")
    phys = fx.make_physician_headers(b["phys_id"])
    # Second retrieval 09:00-10:00 touches the first's end (09:00) only.
    data = validate_success(
        api.retrieve_cycle(b["cycle2_id"],
                           retrieve_payload(b["room_id"], b["tank_id"], mature_oocyte_count=2,
                                            oocytes_retrieved=5,
                                            retrieval_start="2026-05-10T09:00:00Z",
                                            retrieval_end="2026-05-10T10:00:00Z"), phys), 200)
    assert data["status"] == "COMPLETED", "adjacent-after retrieval must be accepted"
    assert data["retrieval_room_id"] == b["room_id"], "the booked room must be recorded"


def test_adjacent_retrieval_before_existing_allowed(api):
    """PRD §3.4: "treating the window as half-open with no buffer so that adjacent windows
    sharing only an endpoint do not conflict." PRD §2.6: "back-to-back retrievals that merely
    touch at an endpoint are allowed."

    Design: Difficulty/resource_temporal_overlap/room_retrieval_adjacent_allowed
    """
    b = fx.setup_two_retrieval_cycles(first_start="2026-05-10T08:00:00Z",
                                      first_end="2026-05-10T09:00:00Z")
    phys = fx.make_physician_headers(b["phys_id"])
    # Second retrieval 07:00-08:00 touches the first's start (08:00) only.
    data = validate_success(
        api.retrieve_cycle(b["cycle2_id"],
                           retrieve_payload(b["room_id"], b["tank_id"], mature_oocyte_count=2,
                                            oocytes_retrieved=5,
                                            retrieval_start="2026-05-10T07:00:00Z",
                                            retrieval_end="2026-05-10T08:00:00Z"), phys), 200)
    assert data["status"] == "COMPLETED", "adjacent-before retrieval must be accepted"


# --------------------------------------------------------------- Corner: overlapping room booking
def test_overlapping_retrieval_same_room_rejected(api):
    """PRD §3.4: "if the requested [retrieval_start, retrieval_end) window overlaps another
    retrieval already booked on the same room ... the request is rejected with
    ERR_ROOM_UNAVAILABLE."

    Design: Corner/errors/overlapping_retrieval_same_room_returns_room_unavailable
    """
    b = fx.setup_two_retrieval_cycles(first_start="2026-05-10T08:00:00Z",
                                      first_end="2026-05-10T09:00:00Z")
    phys = fx.make_physician_headers(b["phys_id"])
    # Second retrieval 08:30-09:30 genuinely overlaps the first 08:00-09:00 booking.
    resp = api.retrieve_cycle(
        b["cycle2_id"], retrieve_payload(b["room_id"], b["tank_id"], mature_oocyte_count=2,
                                         oocytes_retrieved=5,
                                         retrieval_start="2026-05-10T08:30:00Z",
                                         retrieval_end="2026-05-10T09:30:00Z"), phys)
    validate_error(resp, ApiErrorId.ERR_ROOM_UNAVAILABLE.value, 409)
