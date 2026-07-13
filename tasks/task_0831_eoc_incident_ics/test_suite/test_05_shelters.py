"""Sheltering: projected-vs-strict capacity gating and the empty-to-close rule."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_activated_incident,
    create_open_shelter,
    adjust_occupancy,
)

OPS = TEST_USERS["operations_chief_headers"]


# ─── Difficulty: dual_variant_calc / shelter_strict_vs_projected_capacity ───
def test_check_in_gated_by_projected_availability(api):
    """PRD §3.5: "the sum of `current_occupancy` and `reserved_occupancy` must not exceed
    `capacity`, where exactly-equal is allowed (otherwise `ERR_SHELTER_CAPACITY_EXCEEDED`).
    Gating a new check-in or reservation therefore uses projected availability — `capacity`
    minus `current_occupancy` minus `reserved_occupancy`, which counts reservations against
    capacity."

    Design: Difficulty/dual_variant_calc/shelter_strict_vs_projected_capacity
    """
    inc = create_activated_incident(name="Coastal Storm", hazard_type="HURRICANE")
    sh = create_open_shelter(inc["id"], name="Central High", capacity=100)
    adjust_occupancy(sh["id"], check_in=30)
    adjust_occupancy(sh["id"], reserve=20)
    # projected_available = 100 - 30 - 20 = 50 < 60, even though strict = 70 would admit.
    validate_error(
        api.adjust_shelter_occupancy(sh["id"], {"check_in": 60}, OPS),
        ApiErrorId.ERR_SHELTER_CAPACITY_EXCEEDED.value,
    )


def test_rejected_check_in_leaves_occupancy_unchanged(api):
    """PRD §3.5: "the sum of `current_occupancy` and `reserved_occupancy` must not exceed
    `capacity`, where exactly-equal is allowed (otherwise `ERR_SHELTER_CAPACITY_EXCEEDED`).
    Gating a new check-in or reservation therefore uses projected availability — `capacity`
    minus `current_occupancy` minus `reserved_occupancy`, which counts reservations against
    capacity."

    Design: Difficulty/dual_variant_calc/shelter_strict_vs_projected_capacity
    """
    inc = create_activated_incident(name="Coastal Storm", hazard_type="HURRICANE")
    sh = create_open_shelter(inc["id"], name="Central High", capacity=100)
    adjust_occupancy(sh["id"], check_in=30)
    sh_after = adjust_occupancy(sh["id"], reserve=20)
    api.adjust_shelter_occupancy(sh["id"], {"check_in": 60}, OPS)
    from test_helpers import validate_paginated
    shelters, _ = validate_paginated(api.list_incident_shelters(inc["id"], OPS))
    target = next(s for s in shelters if s["id"] == sh["id"])
    assert target["current_occupancy"] == 30, f"current must stay 30, got {target['current_occupancy']}"
    assert target["reserved_occupancy"] == 20, f"reserved must stay 20, got {target['reserved_occupancy']}"


# ─── Corner: state_machines / shelter_close_with_occupants_rejected ───
def test_close_occupied_shelter_rejected(api):
    """PRD §3.5: "Closing a shelter advances it from `OPEN` to `CLOSED` and stamps
    `closed_at`, but only when it is truly empty: both `current_occupancy` and
    `reserved_occupancy` must be exactly zero. A close attempted with any current or reserved
    occupants is rejected with `ERR_SHELTER_OCCUPIED`."

    Design: Corner/state_machines/shelter_close_with_occupants_rejected
    """
    inc = create_activated_incident(name="Shelter Ctx", hazard_type="HURRICANE")
    sh = create_open_shelter(inc["id"], name="Gym A", capacity=50)
    adjust_occupancy(sh["id"], check_in=5)
    validate_error(
        api.transition_shelter(sh["id"], {"to_status": "CLOSED"}, OPS),
        ApiErrorId.ERR_SHELTER_OCCUPIED.value,
    )


# ─── Corner: state_machines / shelter_close_when_empty_succeeds ───
def test_close_empty_shelter_succeeds(api):
    """PRD §3.5: "Closing a shelter advances it from `OPEN` to `CLOSED` and stamps
    `closed_at`, but only when it is truly empty: both `current_occupancy` and
    `reserved_occupancy` must be exactly zero."

    Design: Corner/state_machines/shelter_close_when_empty_succeeds
    """
    inc = create_activated_incident(name="Empty Shelter Ctx", hazard_type="HURRICANE")
    sh = create_open_shelter(inc["id"], name="Gym B", capacity=50)
    closed = validate_success(api.transition_shelter(sh["id"], {"to_status": "CLOSED"}, OPS))
    assert closed["status"] == "CLOSED", f"expected CLOSED, got {closed['status']}"
    assert closed["closed_at"] is not None, "closed_at must be stamped"
