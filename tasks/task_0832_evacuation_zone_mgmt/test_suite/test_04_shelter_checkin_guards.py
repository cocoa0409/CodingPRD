"""Check-in guard ordering, the inclusive FULL boundary, and capacity/power/state errors."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    setup_checkin_scenario, setup_open_shelter, reserve_and_check_in,
    create_registrant, create_assignment, TEST_USERS,
)

SHELTER = TEST_USERS["shelter_headers"]


def _setup_two_household_full_boundary(api):
    """Shelter effective_capacity=3, household A (party 2) CHECKED_IN, household B (party 1)
    RESERVED and ready to check in — occupied 2 + 1 == 3."""
    inc, zone, shelter = setup_open_shelter(order_level="MANDATORY", physical_capacity=5,
                                            staffed_beds=3, ada_reserved_pct=0)
    reserve_and_check_in(shelter["id"], zone["id"], party_size=2)
    reg_b = create_registrant(zone["id"], party_size=1, household_name="Bianchi")
    asg_b = create_assignment(reg_b["id"], shelter["id"], reg_b["version"])
    return shelter, asg_b


def test_checkin_at_exact_capacity_succeeds(api):
    """PRD 3.4: "a capacity rule requires that `occupied_beds` plus the assignment's `party_size` not exceed `effective_capacity` (else `ERR_SHELTER_CAPACITY_EXCEEDED`)."

    Design: Difficulty/boundary_precision_check/shelter_full_at_exact_effective_capacity
    """
    shelter, asg_b = _setup_two_household_full_boundary(api)
    # occupied 2 + party 1 == effective_capacity 3 -> within capacity
    data = validate_success(api.set_shelter_assignment_status(asg_b["id"], {"action": "CHECK_IN"}, SHELTER))
    assert data["status"] == "CHECKED_IN"


def test_shelter_full_at_exact_effective_capacity(api):
    """PRD 3.4: "The boundary is inclusive — full fires when occupied beds equal effective capacity, not only when they exceed it."

    Design: Difficulty/boundary_precision_check/shelter_full_at_exact_effective_capacity
    """
    shelter, asg_b = _setup_two_household_full_boundary(api)
    validate_success(api.set_shelter_assignment_status(asg_b["id"], {"action": "CHECK_IN"}, SHELTER))

    data = validate_success(api.get_shelter(shelter["id"], SHELTER))
    assert data["occupied_beds"] == 3
    assert data["status"] == "FULL"


def test_checkin_closed_shelter_returns_closed_over_capacity(api):
    """PRD 3.4: "the shelter must not be `CLOSED` (else `ERR_SHELTER_CLOSED`)"
    PRD 3.4: "These five checks are evaluated in that order, so a closed shelter surfaces as `ERR_SHELTER_CLOSED` before any capacity concern."

    Design: Difficulty/priority_pair_validation_conflict/checkin_shelter_closed_beats_capacity
    """
    ctx = setup_checkin_scenario(order_level="VOLUNTARY", physical_capacity=10, staffed_beds=0,
                                 ada_reserved_pct=0, party_size=2, open_shelter=False,
                                 close_shelter=True)
    # effective_capacity==0 (unstaffed) would also fail, but CLOSED wins.
    resp = api.set_shelter_assignment_status(ctx["assignment"]["id"], {"action": "CHECK_IN"}, SHELTER)
    validate_error(resp, ApiErrorId.ERR_SHELTER_CLOSED)


def test_checkin_closed_shelter_leaves_assignment_reserved(api):
    """PRD 3.4: "the shelter must not be `CLOSED` (else `ERR_SHELTER_CLOSED`)"

    Design: Difficulty/priority_pair_validation_conflict/checkin_shelter_closed_beats_capacity
    """
    ctx = setup_checkin_scenario(order_level="VOLUNTARY", physical_capacity=10, staffed_beds=0,
                                 ada_reserved_pct=0, party_size=2, open_shelter=False,
                                 close_shelter=True)
    api.set_shelter_assignment_status(ctx["assignment"]["id"], {"action": "CHECK_IN"}, SHELTER)

    data = validate_success(api.get_shelter_assignment(ctx["assignment"]["id"], SHELTER))
    assert data["status"] == "RESERVED"


def test_checkin_no_power_returns_power_capable_over_capacity(api):
    """PRD 3.4: "then a safety rule requires that if the household's `functional_needs` is `MEDICAL_ELECTRICITY` or `OXYGEN` the shelter's `power_backup` must be true (else `ERR_SHELTER_NOT_POWER_CAPABLE`), and finally a capacity rule requires that `occupied_beds` plus the assignment's `party_size` not exceed `effective_capacity` (else `ERR_SHELTER_CAPACITY_EXCEEDED`). These five checks are evaluated in that order"

    Design: Difficulty/priority_pair_validation_conflict/checkin_power_safety_beats_capacity
    """
    ctx = setup_checkin_scenario(order_level="MANDATORY", physical_capacity=5, staffed_beds=1,
                                 ada_reserved_pct=0, power_backup=False, party_size=2,
                                 functional_needs="OXYGEN", open_shelter=True)
    # effective_capacity==1, 0+2 also exceeds it, but the safety rule fires first.
    resp = api.set_shelter_assignment_status(ctx["assignment"]["id"], {"action": "CHECK_IN"}, SHELTER)
    validate_error(resp, ApiErrorId.ERR_SHELTER_NOT_POWER_CAPABLE)


def test_checkin_no_power_leaves_assignment_reserved(api):
    """PRD 3.4: "a safety rule requires that if the household's `functional_needs` is `MEDICAL_ELECTRICITY` or `OXYGEN` the shelter's `power_backup` must be true (else `ERR_SHELTER_NOT_POWER_CAPABLE`)"

    Design: Difficulty/priority_pair_validation_conflict/checkin_power_safety_beats_capacity
    """
    ctx = setup_checkin_scenario(order_level="MANDATORY", physical_capacity=5, staffed_beds=1,
                                 ada_reserved_pct=0, power_backup=False, party_size=2,
                                 functional_needs="OXYGEN", open_shelter=True)
    api.set_shelter_assignment_status(ctx["assignment"]["id"], {"action": "CHECK_IN"}, SHELTER)

    data = validate_success(api.get_shelter_assignment(ctx["assignment"]["id"], SHELTER))
    assert data["status"] == "RESERVED"


def test_shelter_capacity_exceeded_plain(api):
    """PRD 3.4: "a capacity rule requires that `occupied_beds` plus the assignment's `party_size` not exceed `effective_capacity` (else `ERR_SHELTER_CAPACITY_EXCEEDED`)."

    Design: Corner/validations/shelter_capacity_exceeded_plain
    """
    ctx = setup_checkin_scenario(order_level="MANDATORY", physical_capacity=5, staffed_beds=1,
                                 ada_reserved_pct=0, power_backup=True, party_size=2,
                                 functional_needs="NONE", open_shelter=True)
    # effective_capacity==1, occupied 0 + party 2 > 1; only the fiscal check fails.
    resp = api.set_shelter_assignment_status(ctx["assignment"]["id"], {"action": "CHECK_IN"}, SHELTER)
    validate_error(resp, ApiErrorId.ERR_SHELTER_CAPACITY_EXCEEDED)


def test_shelter_standby_checkin_returns_not_open(api):
    """PRD 3.4: "the shelter must be `OPEN` and not `STANDBY` (a `STANDBY` shelter yields `ERR_SHELTER_NOT_OPEN`)"

    Design: Corner/validations/shelter_standby_checkin_returns_not_open
    """
    ctx = setup_checkin_scenario(order_level="MANDATORY", physical_capacity=5, staffed_beds=5,
                                 ada_reserved_pct=0, power_backup=True, party_size=1,
                                 open_shelter=False)
    resp = api.set_shelter_assignment_status(ctx["assignment"]["id"], {"action": "CHECK_IN"}, SHELTER)
    validate_error(resp, ApiErrorId.ERR_SHELTER_NOT_OPEN)
