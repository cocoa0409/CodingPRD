"""Yard grounding: the ON_VESSEL -> GROUNDED transition, its cross-entity and
stacking-safety guards, slot occupancy, the GATE_IN EIR side effect, immediate
consistency, and the cross-entity-beats-slot-occupied precedence.

Difficulty instances: cross_entity_state_dependency (ground blocked until
berthed), priority_pair_validation_conflict (cross-entity beats slot-occupied).
Corner instances: GATE_IN EIR side effect, reefer-into-non-reefer, floating
stack, damaged-EIR-requires-note, slot-occupied, immediate consistency.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["terminal_admin_headers"]
BERTH = TEST_USERS["berth_planner_headers"]
YARD = TEST_USERS["yard_planner_headers"]
GATE = TEST_USERS["gate_operator_headers"]


# --------------------------------------------------------------------------- #
# Cross-entity dependency — ground blocked until window BERTHED
# --------------------------------------------------------------------------- #
def test_ground_blocked_until_window_berthed(api):
    """PRD §3.3: "The discharge berth window must be `BERTHED` — a container can
    only be grounded after its vessel has actually berthed — failing which the
    grounding is rejected with `ERR_CROSS_ENTITY_STATE`."

    Design: Difficulty/cross_entity_state_dependency/ground_blocked_until_berth_window_berthed
    """
    berth = fx.provision_berth(code="B-15", length_m=400, draft_m=16.0)
    vessel = fx.provision_vessel(imo_number="1000015", name="Sched V", loa_m=300, draft_m=14.0)
    window = fx.create_scheduled_window(berth["id"], vessel["id"])  # NOT berthed
    container = fx.declare_container(vessel["id"], window["id"], container_number="SCHD150150")
    slot = fx.create_yard_slot(block="F")
    resp = api.ground_container(
        container["id"], {"yard_slot_id": slot["id"], "condition": "SOUND"}, YARD
    )
    validate_error(resp, ApiErrorId.ERR_CROSS_ENTITY_STATE.value)
    after = validate_success(api.get_container(container["id"], YARD), 200)
    assert after["handling_status"] == "ON_VESSEL"


def test_ground_on_scheduled_window_leaves_container_on_vessel(api):
    """PRD §3.3: "The discharge berth window must be `BERTHED` ... failing which the
    grounding is rejected with `ERR_CROSS_ENTITY_STATE`."

    Design: Difficulty/cross_entity_state_dependency/ground_blocked_until_berth_window_berthed
    """
    berth = fx.provision_berth(code="B-15b", length_m=400, draft_m=16.0)
    vessel = fx.provision_vessel(imo_number="1000155", name="Sched Vb", loa_m=300, draft_m=14.0)
    window = fx.create_scheduled_window(berth["id"], vessel["id"])
    container = fx.declare_container(vessel["id"], window["id"])
    slot = fx.create_yard_slot(block="Fb")
    validate_error(
        api.ground_container(container["id"], {"yard_slot_id": slot["id"], "condition": "SOUND"}, YARD),
        ApiErrorId.ERR_CROSS_ENTITY_STATE.value,
    )
    # The slot must remain EMPTY since the ground was rejected.
    slot_after = validate_success(api.get_yard_slot(slot["id"], YARD), 200)
    assert slot_after["status"] == "EMPTY"


# --------------------------------------------------------------------------- #
# Priority pair — cross-entity-state beats slot-occupied
# --------------------------------------------------------------------------- #
def test_cross_entity_state_beats_slot_occupied_on_ground(api):
    """PRD §3.3: "The discharge berth window must be `BERTHED` ... failing which the
    grounding is rejected with `ERR_CROSS_ENTITY_STATE`. The target slot must
    currently be `EMPTY`; an occupied target yields `ERR_SLOT_OCCUPIED`."
    PRD §2.8: "Only then are state-machine preconditions and the deeper business
    rules of §3 evaluated."

    Design: Difficulty/priority_pair_validation_conflict/cross_entity_state_beats_slot_occupied_on_ground
    """
    # Occupier: a berthed window A with a container grounded into the shared slot.
    berth_a = fx.provision_berth(code="B-10", length_m=400, draft_m=16.0)
    vessel_a = fx.provision_vessel(imo_number="1000010", name="Occ V1", loa_m=300, draft_m=14.0)
    window_a = fx.create_scheduled_window(berth_a["id"], vessel_a["id"])
    fx.berth_window(window_a)
    occupier = fx.declare_container(vessel_a["id"], window_a["id"], container_number="OCCA000100")
    slot = fx.create_yard_slot(block="C")
    fx.ground_container(occupier["id"], slot["id"])

    # Newcomer: under a SCHEDULED (not berthed) window B, targeting the OCCUPIED slot.
    berth_b = fx.provision_berth(code="B-11", length_m=400, draft_m=16.0)
    vessel_b = fx.provision_vessel(imo_number="1000011", name="Occ V2", loa_m=300, draft_m=14.0)
    window_b = fx.create_scheduled_window(berth_b["id"], vessel_b["id"])
    newcomer = fx.declare_container(vessel_b["id"], window_b["id"], container_number="OCCB000101")

    resp = api.ground_container(
        newcomer["id"], {"yard_slot_id": slot["id"], "condition": "SOUND"}, YARD
    )
    validate_error(resp, ApiErrorId.ERR_CROSS_ENTITY_STATE.value)


def test_cross_entity_state_beats_slot_occupied_container_unchanged(api):
    """PRD §3.3: "The discharge berth window must be `BERTHED` ... failing which the
    grounding is rejected with `ERR_CROSS_ENTITY_STATE`. The target slot must
    currently be `EMPTY`; an occupied target yields `ERR_SLOT_OCCUPIED`."

    Design: Difficulty/priority_pair_validation_conflict/cross_entity_state_beats_slot_occupied_on_ground
    """
    berth_a = fx.provision_berth(code="B-10c", length_m=400, draft_m=16.0)
    vessel_a = fx.provision_vessel(imo_number="1000110", name="Occ V1c", loa_m=300, draft_m=14.0)
    window_a = fx.create_scheduled_window(berth_a["id"], vessel_a["id"])
    fx.berth_window(window_a)
    occupier = fx.declare_container(vessel_a["id"], window_a["id"])
    slot = fx.create_yard_slot(block="Cc")
    fx.ground_container(occupier["id"], slot["id"])

    berth_b = fx.provision_berth(code="B-11c", length_m=400, draft_m=16.0)
    vessel_b = fx.provision_vessel(imo_number="1000111", name="Occ V2c", loa_m=300, draft_m=14.0)
    window_b = fx.create_scheduled_window(berth_b["id"], vessel_b["id"])
    newcomer = fx.declare_container(vessel_b["id"], window_b["id"])

    validate_error(
        api.ground_container(newcomer["id"], {"yard_slot_id": slot["id"], "condition": "SOUND"}, YARD),
        ApiErrorId.ERR_CROSS_ENTITY_STATE.value,
    )
    after = validate_success(api.get_container(newcomer["id"], YARD), 200)
    assert after["handling_status"] == "ON_VESSEL"


# --------------------------------------------------------------------------- #
# Slot occupancy + stacking safety
# --------------------------------------------------------------------------- #
def test_slot_occupied_rejected(api):
    """PRD §3.3: "The target slot must currently be `EMPTY`; an occupied target
    yields `ERR_SLOT_OCCUPIED`."

    Design: Corner/validations/slot_occupied_returns_slot_occupied
    """
    _, vessel, window = fx.provision_berthed_window()
    c1 = fx.declare_container(vessel["id"], window["id"], container_number="OCC1510510")
    c2 = fx.declare_container(vessel["id"], window["id"], container_number="OCC2510511")
    slot = fx.create_yard_slot(block="Q")
    fx.ground_container(c1["id"], slot["id"])
    resp = api.ground_container(c2["id"], {"yard_slot_id": slot["id"], "condition": "SOUND"}, YARD)
    validate_error(resp, ApiErrorId.ERR_SLOT_OCCUPIED.value)


def test_reefer_into_non_reefer_slot_stacking_violation(api):
    """PRD §2.10: "a refrigerated container may only ground into a slot wired for
    reefer power". PRD §3.3: "if the container `is_reefer`, the target slot's
    `is_reefer_rack` must be true ... A stacking failure is rejected with
    `ERR_STACKING_VIOLATION`."

    Design: Corner/state_machines/reefer_into_non_reefer_slot_stacking_violation
    """
    _, vessel, window = fx.provision_berthed_window()
    container = fx.declare_container(
        vessel["id"], window["id"], container_number="RFRS400400", is_reefer=True, setpoint_c=-18.0
    )
    slot = fx.create_yard_slot(block="K", is_reefer_rack=False)
    resp = api.ground_container(container["id"], {"yard_slot_id": slot["id"], "condition": "SOUND"}, YARD)
    validate_error(resp, ApiErrorId.ERR_STACKING_VIOLATION.value)


def test_floating_stack_grounding_violation(api):
    """PRD §2.10: "a container may not ground into an above-ground slot whose
    supporting slot is not itself occupied (no floating stacks)". PRD §3.3: "the
    target slot must be either at `tier` 1 or else have the slot named by its
    `below_slot_id` already in `OCCUPIED` status, so that no stack floats. A
    stacking failure is rejected with `ERR_STACKING_VIOLATION`."

    Design: Corner/state_machines/floating_stack_grounding_violation
    """
    _, vessel, window = fx.provision_berthed_window()
    container = fx.declare_container(vessel["id"], window["id"], container_number="FLTS410410")
    slot1 = fx.create_yard_slot(block="L", bay=1, row=1, tier=1)
    slot2 = fx.create_yard_slot(block="L", bay=1, row=1, tier=2, below_slot_id=slot1["id"])
    resp = api.ground_container(container["id"], {"yard_slot_id": slot2["id"], "condition": "SOUND"}, YARD)
    validate_error(resp, ApiErrorId.ERR_STACKING_VIOLATION.value)


def test_damaged_ground_requires_damage_note(api):
    """PRD §3.4: "a sound crossing must leave `damage_note` null or omitted, and a
    damaged crossing must supply it (the mismatch is a §2.8 shape failure)."
    PRD §2.8: "A malformed body yields `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/state_machines/damaged_eir_requires_damage_note
    """
    _, vessel, window = fx.provision_berthed_window()
    container = fx.declare_container(vessel["id"], window["id"], container_number="DMGN420420")
    slot = fx.create_yard_slot(block="M")
    resp = api.ground_container(container["id"], {"yard_slot_id": slot["id"], "condition": "DAMAGED"}, YARD)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# --------------------------------------------------------------------------- #
# GATE_IN EIR side effect + immediate consistency
# --------------------------------------------------------------------------- #
def test_ground_creates_gate_in_eir(api):
    """PRD §3.3: "one equipment interchange receipt is created recording an inbound
    crossing — direction `GATE_IN`, the recorded `condition`, and no associated
    gate appointment."

    Design: Corner/state_machines/ground_creates_gate_in_eir_side_effect
    """
    _, vessel, window = fx.provision_berthed_window()
    container = fx.declare_container(vessel["id"], window["id"], container_number="EIRG350350")
    slot = fx.create_yard_slot(block="J")
    fx.ground_container(container["id"], slot["id"], condition="SOUND")
    data, _meta = validate_paginated(api.list_container_eirs(container["id"], GATE))
    assert len(data) == 1
    assert data[0]["direction"] == "GATE_IN"
    assert data[0]["condition"] == "SOUND"


def test_ground_side_effects_visible_immediately(api):
    """PRD §3.3: "On success the container's `yard_slot_id` is set to the target,
    `handling_status` becomes `GROUNDED`".

    Design: Corner/consistency_model/ground_side_effects_visible_in_same_response
    """
    _, vessel, window = fx.provision_berthed_window()
    container = fx.declare_container(vessel["id"], window["id"], container_number="IMMC900900")
    slot = fx.create_yard_slot(block="W")
    data = validate_success(
        api.ground_container(container["id"], {"yard_slot_id": slot["id"], "condition": "SOUND"}, YARD),
        200,
    )
    assert data["handling_status"] == "GROUNDED"
    assert data["yard_slot_id"] == slot["id"]


# --------------------------------------------------------------------------- #
# OCC stale on customs-clear (lives in grounding setup) — cross_cutting
# --------------------------------------------------------------------------- #
def test_customs_clear_stale_version_rejected(api):
    """PRD §2.7: "A request to clear a container that the customs desk believes is
    still pending must carry `expected_container_version` ... If the container's
    current `version` has advanced beyond that value ... the clear is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/customs_clear_stale_version_conflict
    """
    _, vessel, window = fx.provision_berthed_window()
    container = fx.declare_container(vessel["id"], window["id"], container_number="STLE810810")
    cont_v0 = container["version"]
    slot = fx.create_yard_slot(block="V")
    fx.ground_container(container["id"], slot["id"])  # advances container version
    resp = api.customs_clear_container(
        container["id"], {"expected_container_version": cont_v0}, TEST_USERS["customs_officer_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    after = validate_success(api.get_container(container["id"], YARD), 200)
    assert after["customs_status"] == "PENDING"
