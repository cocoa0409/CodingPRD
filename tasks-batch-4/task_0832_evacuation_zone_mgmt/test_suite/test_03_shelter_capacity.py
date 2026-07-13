"""Shelter capacity: combinatorial effective_capacity and the dual availability views."""
from test_helpers import (
    validate_success, assert_shelter, assert_shelter_bed_invariants,
    create_incident, create_shelter, create_staff_shift,
    setup_checkin_scenario, TEST_USERS,
)

SHELTER = TEST_USERS["shelter_headers"]


def test_shelter_staffed_capacity_now_from_shift(api):
    """PRD 2.7: "the staffed bed count `staffed_capacity_now` is the sum of `staffed_beds` across that shelter's `SCHEDULED` staff shifts whose window covers the clock — that is, shifts whose `start_utc` is at or before the current instant and whose `end_utc` is at or after it (both bounds inclusive)."

    Design: Difficulty/combinatorial_formula/shelter_effective_capacity_min_then_ada_ceil
    """
    inc = create_incident(name="Bay Quake", jurisdiction="Alameda", hazard_type="HAZMAT")
    shelter = create_shelter(inc["id"], name="Civic Center", physical_capacity=100,
                             ada_reserved_pct=0.10, power_backup=True)
    create_staff_shift(shelter["id"], staffed_beds=80)

    data = validate_success(api.get_shelter(shelter["id"], SHELTER))
    assert data["staffed_capacity_now"] == 80


def test_shelter_effective_capacity_min_then_ada_ceil(api):
    """PRD 2.7: "The general-population usable capacity `effective_capacity` is then derived by taking the smaller of the shelter's `physical_capacity` and its `staffed_capacity_now` as the base, computing the functional-needs reservation as the base multiplied by `ada_reserved_pct` rounded up to the next whole bed, and subtracting that reservation from the base; the result is floored at 0 so it is never negative."

    Design: Difficulty/combinatorial_formula/shelter_effective_capacity_min_then_ada_ceil
    """
    inc = create_incident(name="Bay Quake", jurisdiction="Alameda", hazard_type="HAZMAT")
    shelter = create_shelter(inc["id"], name="Civic Center", physical_capacity=100,
                             ada_reserved_pct=0.10, power_backup=True)
    create_staff_shift(shelter["id"], staffed_beds=80)

    data = validate_success(api.get_shelter(shelter["id"], SHELTER))
    assert_shelter(data)
    # base=min(100,80)=80, ada=ceil(80*0.10)=8, effective=72
    assert data["effective_capacity"] == 72


def test_shelter_provisional_available_subtracts_reserved(api):
    """PRD 2.7: "`provisional_available`, the planning view used when deciding whether a new reservation fits, is `effective_capacity` minus both `reserved_beds` and `occupied_beds`"

    Design: Difficulty/dual_variant_calc/shelter_provisional_vs_confirmed_available
    """
    ctx = setup_checkin_scenario(order_level="VOLUNTARY", physical_capacity=20, staffed_beds=20,
                                 ada_reserved_pct=0, party_size=3, open_shelter=False)

    data = validate_success(api.get_shelter(ctx["shelter"]["id"], SHELTER))
    assert data["reserved_beds"] == 3
    assert data["occupied_beds"] == 0
    # effective 20 - reserved 3 - occupied 0
    assert data["provisional_available"] == 17
    assert_shelter_bed_invariants(data)


def test_shelter_confirmed_available_ignores_reserved(api):
    """PRD 2.7: "`confirmed_available`, the physical-occupancy view, is `effective_capacity` minus `occupied_beds` only and ignores reservations."

    Design: Difficulty/dual_variant_calc/shelter_provisional_vs_confirmed_available
    """
    ctx = setup_checkin_scenario(order_level="VOLUNTARY", physical_capacity=20, staffed_beds=20,
                                 ada_reserved_pct=0, party_size=3, open_shelter=False)

    data = validate_success(api.get_shelter(ctx["shelter"]["id"], SHELTER))
    assert data["reserved_beds"] == 3
    assert data["occupied_beds"] == 0
    # effective 20 - occupied 0; RESERVED ignored
    assert data["confirmed_available"] == 20


def test_shelter_effective_capacity_zero_when_unstaffed(api):
    """PRD 2.7: "The general-population usable capacity `effective_capacity` is then derived by taking the smaller of the shelter's `physical_capacity` and its `staffed_capacity_now` as the base, computing the functional-needs reservation as the base multiplied by `ada_reserved_pct` rounded up to the next whole bed, and subtracting that reservation from the base; the result is floored at 0 so it is never negative."

    Design: Corner/entities/shelter_effective_capacity_zero_when_unstaffed
    """
    inc = create_incident()
    shelter = create_shelter(inc["id"], physical_capacity=50, power_backup=True)

    data = validate_success(api.get_shelter(shelter["id"], SHELTER))
    assert data["staffed_capacity_now"] == 0
    assert data["effective_capacity"] == 0
