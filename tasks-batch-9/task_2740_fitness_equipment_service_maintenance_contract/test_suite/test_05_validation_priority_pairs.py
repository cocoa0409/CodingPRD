"""
Requests that violate two rules at once, and the rung that decides the answer.

Each pair below is set up twice. First the lower-priority defect is provoked on its
own, to prove that the rule really does fire and really does own that error id; then a
second request violates both rules together, and only the higher rung may answer.

* dispatching a tagged-out machine to a technician without the inspector credential is
  a safety violation — but a contract that is no longer ACTIVE is checked first;
* holding a part that belongs to another model while the parts allowance is exhausted
  is both a referential and a fiscal defect — and the referential one wins.

Every world below is built from scratch through declared endpoints, because the
server restarts with an empty database before each test.
"""

from test_helpers import (
    CONTRACT_ADMIN,
    ERR_CONTRACT_NOT_ACTIVE,
    ERR_PART_MODEL_MISMATCH,
    ERR_PARTS_ALLOWANCE_EXHAUSTED,
    ERR_SAFETY_CERTIFICATION_REQUIRED,
    SERVICE_COORDINATOR,
    arrive_call,
    assert_fields,
    assert_money,
    dispatch_call,
    dispatch_payload,
    get_success_data,
    inspector_headers,
    new_active_contract,
    new_club,
    new_equipment,
    new_model,
    new_part,
    new_technician,
    open_call,
    parts_hold_payload,
    read_call,
    read_contract,
    read_equipment,
    read_part,
    read_technician,
    rows_of,
    set_clock,
    suspend_payload,
    tag_out_payload,
    technician_headers,
    validate_error,
)

TREADMILL_MODEL = {
    "manufacturer": "Pacemaster",
    "model_code": "TM-900",
    "category": "TREADMILL",
    "model_year": 2019,
    "pm_interval_hours": 250,
    "expected_service_life_hours": 20000,
    "base_annual_service_cents": 120000,
}

GOLD_FULL_TERM = {
    "coverage_tier": "GOLD",
    "parts_inclusion": "FULL",
    "pm_visits_per_year": 4,
    "annual_base_cents": 250000,
    "initial_parts_allowance_cents": 500000,
    "term_start_date": "2026-01-01",
    "term_end_date": "2026-12-31",
}

DISPATCH_START = "2026-08-18T09:00:00Z"


def _tagged_out_machine_world(api):
    """
    A GOLD/FULL club with an OPEN MAJOR call on a machine an inspector has just tagged
    out. ``T1`` is an ordinary technician; ``T2`` holds the inspector credential.
    """
    set_clock(api, "2026-08-18T08:00:00Z")
    club = new_club(api, name="Northside Fitness", region_code="NW")
    model = new_model(api, **TREADMILL_MODEL)
    unit = new_equipment(
        api,
        club["id"],
        model["id"],
        serial_number="SN-PC-1",
        install_date="2024-03-01",
        initial_usage_hours=500,
    )
    contract = new_active_contract(api, club["id"], **GOLD_FULL_TERM)
    ordinary = new_technician(
        api,
        full_name="Dana Reyes",
        region_code="NW",
        skill_categories=["TREADMILL"],
    )
    inspector = new_technician(
        api,
        full_name="Ivo Marsh",
        region_code="NW",
        skill_categories=["TREADMILL"],
        is_safety_inspector=True,
    )
    call = open_call(
        api,
        contract["id"],
        unit["id"],
        severity="MAJOR",
        symptom_code="BELT_SLIP",
    )
    # A direct inspector lockout records INSPECTOR_TAG_OUT, one of the four declared
    # lockout reasons.
    get_success_data(
        api.tag_out_equipment(
            unit["id"],
            tag_out_payload("INSPECTOR_TAG_OUT"),
            inspector_headers(inspector["id"]),
        )
    )
    return {
        "club_id": club["id"],
        "contract_id": contract["id"],
        "equipment_id": unit["id"],
        "call_id": call["id"],
        "ordinary_technician_id": ordinary["id"],
        "inspector_id": inspector["id"],
    }


def _attempt_dispatch(api, world):
    """Ask for the tagged-out machine to be handed to the ordinary technician."""
    return api.dispatch_service_call(
        world["call_id"],
        dispatch_payload(DISPATCH_START, world["ordinary_technician_id"]),
        SERVICE_COORDINATOR,
    )


def _assert_dispatch_left_no_trace(api, world):
    """The refused dispatch may not have moved the call, the calendar or the machine."""
    call = read_call(api, world["call_id"])
    assert call["status"] == "OPEN", call["status"]
    assert call["assigned_technician_id"] is None, call["assigned_technician_id"]
    assignments = rows_of(
        api.list_technician_assignments(CONTRACT_ADMIN, service_call_id=world["call_id"])
    )
    assert assignments == [], assignments
    technician = read_technician(api, world["ordinary_technician_id"])
    assert technician["committed_minutes"] == 0, technician["committed_minutes"]
    unit = read_equipment(api, world["equipment_id"])
    assert_fields(
        unit,
        lifecycle_status="TAGGED_OUT",
        safety_lockout_reason="INSPECTOR_TAG_OUT",
    )


def test_dispatching_a_locked_out_machine_to_a_non_inspector_is_refused_on_its_own(api):
    """
    While the contract is still ACTIVE the only rule the request breaks is the safety
    credential gate, and it answers ERR_SAFETY_CERTIFICATION_REQUIRED with a 422.

    PRD 2.9: "(33) When the target machine is `TAGGED_OUT`, the technician chosen or
    routed for dispatch must have `is_safety_inspector` equal to `true`, otherwise
    `ERR_SAFETY_CERTIFICATION_REQUIRED` (422)."

    Design: Difficulty/priority_pair_validation_conflict/dispatch_contract_not_active_outranks_safety_certification_required
    """
    world = _tagged_out_machine_world(api)

    assert read_contract(api, world["contract_id"])["status"] == "ACTIVE"

    response = _attempt_dispatch(api, world)
    validate_error(response, ERR_SAFETY_CERTIFICATION_REQUIRED, 422)

    _assert_dispatch_left_no_trace(api, world)


def test_a_suspended_contract_outranks_the_missing_inspector_credential(api):
    """
    Suspending the contract adds a second defect to the very same request, and the
    state rung answers first: ERR_CONTRACT_NOT_ACTIVE with a 409, not the safety error.

    PRD 2.9: "FleetCare evaluates a request against a single, strictly ordered ladder of
    checks, and the **first** check that fails decides the response."

    Design: Difficulty/priority_pair_validation_conflict/dispatch_contract_not_active_outranks_safety_certification_required
    """
    world = _tagged_out_machine_world(api)

    get_success_data(
        api.suspend_contract(
            world["contract_id"],
            suspend_payload("Club payment dispute"),
            CONTRACT_ADMIN,
        )
    )
    assert read_contract(api, world["contract_id"])["status"] == "SUSPENDED"

    # The machine is still tagged out and the technician still holds no inspector
    # credential, so the safety rule is violated too — and must not be the one reported.
    response = _attempt_dispatch(api, world)
    validate_error(response, ERR_CONTRACT_NOT_ACTIVE, 409)

    _assert_dispatch_left_no_trace(api, world)


BIKE_MODEL = {
    "manufacturer": "Pacemaster",
    "model_code": "BK-200",
    "category": "BIKE",
    "model_year": 2022,
    "pm_interval_hours": 400,
    "expected_service_life_hours": 15000,
    "base_annual_service_cents": 60000,
}


def _exhausted_allowance_world(api):
    """
    A GOLD/FULL contract drafted with no parts allowance at all, an ON_SITE call on a
    treadmill, and two stocked parts: the treadmill's own belt and a bike crank.
    """
    set_clock(api, "2026-08-18T08:00:00Z")
    club = new_club(api, name="Northside Fitness", region_code="NW")
    treadmill_model = new_model(api, **TREADMILL_MODEL)
    bike_model = new_model(api, **BIKE_MODEL)
    unit = new_equipment(
        api,
        club["id"],
        treadmill_model["id"],
        serial_number="SN-PM-1",
        install_date="2024-03-01",
        initial_usage_hours=500,
    )
    contract = new_active_contract(
        api, club["id"], **dict(GOLD_FULL_TERM, initial_parts_allowance_cents=0)
    )
    technician = new_technician(
        api,
        full_name="Dana Reyes",
        region_code="NW",
        skill_categories=["TREADMILL"],
    )
    right_part = new_part(
        api,
        treadmill_model["id"],
        part_number="BELT-900",
        category="WEAR",
        unit_price_cents=12000,
        initial_on_hand_qty=5,
        initial_refurb_qty=0,
    )
    wrong_part = new_part(
        api,
        bike_model["id"],
        part_number="CRANK-200",
        category="STRUCTURAL",
        unit_price_cents=8000,
        initial_on_hand_qty=5,
        initial_refurb_qty=0,
    )
    call = open_call(
        api,
        contract["id"],
        unit["id"],
        severity="MINOR",
        symptom_code="BELT_NOISE",
    )
    dispatch_call(api, call["id"], "2026-08-18T08:00:00Z", technician["id"])
    arrive_call(api, call["id"], technician["id"])
    return {
        "contract_id": contract["id"],
        "equipment_id": unit["id"],
        "call_id": call["id"],
        "technician_id": technician["id"],
        "right_part_id": right_part["id"],
        "wrong_part_id": wrong_part["id"],
    }


def _attempt_hold(api, world, part_id):
    """Ask for one new unit of ``part_id`` against the ON_SITE call."""
    return api.place_parts_hold(
        world["call_id"],
        parts_hold_payload(part_id, 1, "NEW"),
        technician_headers(world["technician_id"]),
    )


def _assert_hold_left_no_trace(api, world):
    """A refused hold may not create an order, move stock or move the call."""
    orders = rows_of(api.list_part_orders(CONTRACT_ADMIN, service_call_id=world["call_id"]))
    assert orders == [], orders
    for label, part_id in (
        ("right", world["right_part_id"]),
        ("wrong", world["wrong_part_id"]),
    ):
        part = read_part(api, part_id)
        assert part["on_hand_qty"] == 5, f"{label}: {part['on_hand_qty']}"
        assert part["allocated_qty"] == 0, f"{label}: {part['allocated_qty']}"
    contract = read_contract(api, world["contract_id"])
    assert_money(
        contract["parts_allowance_remaining_cents"],
        0,
        "parts_allowance_remaining_cents",
    )
    call = read_call(api, world["call_id"])
    assert call["status"] == "ON_SITE", call["status"]
    assert call["parts_hold_count"] == 0, call["parts_hold_count"]


def test_holding_the_right_part_against_an_empty_allowance_is_refused_on_its_own(api):
    """
    The correct belt for this treadmill breaks only the fiscal rule, and it answers
    ERR_PARTS_ALLOWANCE_EXHAUSTED with a 409.

    PRD 3.7: "And when the requested part falls inside the contract's `parts_inclusion`
    coverage, `parts_allowance_remaining_cents` must be strictly greater than zero, or the
    answer is `ERR_PARTS_ALLOWANCE_EXHAUSTED`."

    Design: Difficulty/priority_pair_validation_conflict/parts_hold_model_mismatch_outranks_parts_allowance_exhausted
    """
    world = _exhausted_allowance_world(api)

    # Full parts inclusion covers every category, so the belt is a covered part and the
    # allowance gate applies to it.
    response = _attempt_hold(api, world, world["right_part_id"])
    validate_error(response, ERR_PARTS_ALLOWANCE_EXHAUSTED, 409)

    _assert_hold_left_no_trace(api, world)


def test_a_part_from_another_model_outranks_the_exhausted_allowance(api):
    """
    The bike crank breaks the referential rule and the fiscal rule at once, and the
    referential one answers: ERR_PART_MODEL_MISMATCH with a 422, not the 409.

    PRD 2.9: "A technician standing next to a broken treadmill should be told that the
    part does not fit the machine, or that the stock room is empty, before being told that
    the club has exhausted its parts allowance — the physical impossibility outranks the
    commercial one."

    Design: Difficulty/priority_pair_validation_conflict/parts_hold_model_mismatch_outranks_parts_allowance_exhausted
    """
    world = _exhausted_allowance_world(api)

    # The crank belongs to the bike model, and the allowance is still zero, so both rules
    # are violated by this one request.
    response = _attempt_hold(api, world, world["wrong_part_id"])
    validate_error(response, ERR_PART_MODEL_MISMATCH, 422)

    _assert_hold_left_no_trace(api, world)
