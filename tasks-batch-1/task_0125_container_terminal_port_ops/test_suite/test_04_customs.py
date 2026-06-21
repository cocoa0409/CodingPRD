"""Customs holds and clearances: the parallel customs dimension, place/release,
the conserve-active-hold-count invariant, idempotency, and invalid-state guards.

Difficulty instances: non_linear_state_machine (parallel customs/handling),
compensating_invariant (hold place-then-release conserves active-hold count).
Corner instances: customs-clear-from-HELD invalid state, release idempotency.
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
YARD = TEST_USERS["yard_planner_headers"]
CUSTOMS = TEST_USERS["customs_officer_headers"]


# --------------------------------------------------------------------------- #
# Parallel customs / handling dimensions — non_linear_state_machine
# --------------------------------------------------------------------------- #
def test_hold_advances_customs_only_handling_unchanged(api):
    """PRD §3.3: "Every container carries two **independent** status dimensions that
    evolve on their own tracks."
    PRD §3.5: "A `CustomsOfficer` **places a hold** on a container, which both
    records a new customs hold and drives the container's `customs_status` from
    `PENDING` to `HELD`."

    Design: Difficulty/non_linear_state_machine/container_parallel_customs_handling_dimensions
    """
    _, _, container, _ = fx.setup_grounded_container()
    fx.place_hold(container["id"], reason="INSPECTION")
    after = validate_success(api.get_container(container["id"], YARD), 200)
    assert after["handling_status"] == "GROUNDED"
    assert after["customs_status"] == "HELD"


def test_ground_advances_handling_only_customs_pending(api):
    """PRD §3.3: "The physical `handling_status` begins at `ON_VESSEL` and proceeds
    to `GROUNDED` and then to the terminal `GATED_OUT`. The regulatory
    `customs_status` begins at `PENDING`".

    Design: Difficulty/non_linear_state_machine/container_parallel_customs_handling_dimensions
    """
    _, vessel, window = fx.provision_berthed_window()
    container = fx.declare_container(vessel["id"], window["id"], container_number="PARA5000050")
    slot = fx.create_yard_slot(block="A5")
    grounded = fx.ground_container(container["id"], slot["id"])
    assert grounded["handling_status"] == "GROUNDED"
    assert grounded["customs_status"] == "PENDING"


# --------------------------------------------------------------------------- #
# Conserve active-hold count — compensating_invariant
# --------------------------------------------------------------------------- #
def test_hold_release_clears_container_and_stamps_hold(api):
    """PRD §3.5: "On success the hold's `status` becomes `RELEASED`, its
    `released_at` is stamped to the current clock instant, and the container's
    `customs_status` becomes `CLEARED`."

    Design: Difficulty/compensating_invariant/customs_hold_release_conserves_active_hold_count
    """
    fx.set_clock("2026-02-01T00:00:00.000Z")
    berth = fx.provision_berth(code="B-19", length_m=400, draft_m=16.0)
    vessel = fx.provision_vessel(imo_number="1000020", name="Comp V2", loa_m=300, draft_m=14.0)
    window = fx.create_scheduled_window(berth["id"], vessel["id"])
    fx.berth_window(window)
    container = fx.declare_container(vessel["id"], window["id"], container_number="COMP190190")
    slot = fx.create_yard_slot(block="H")
    fx.ground_container(container["id"], slot["id"])
    hold = fx.place_hold(container["id"], reason="DOCUMENTATION")

    released = validate_success(api.release_customs_hold(hold["id"], CUSTOMS), 200)
    assert released["status"] == "RELEASED"
    assert released["released_at"] == "2026-02-01T00:00:00.000Z"
    after = validate_success(api.get_container(container["id"], YARD), 200)
    assert after["customs_status"] == "CLEARED"


def test_hold_then_release_conserves_active_hold_count(api):
    """PRD §3.5: "**Releasing a hold** drives the container from `HELD` to
    `CLEARED`. ... On success the hold's `status` becomes `RELEASED`, its
    `released_at` is stamped to the current clock instant, and the container's
    `customs_status` becomes `CLEARED`."

    Design: Difficulty/compensating_invariant/customs_hold_release_conserves_active_hold_count
    """
    _, _, container, _ = fx.setup_grounded_container()
    hold = fx.place_hold(container["id"], reason="DUTY_UNPAID")
    fx.get_success_data(api.release_customs_hold(hold["id"], CUSTOMS))
    data, _meta = validate_paginated(api.list_container_customs_holds(container["id"], CUSTOMS))
    active = [h for h in data if h["status"] == "ACTIVE"]
    assert len(active) == 0
    after = validate_success(api.get_container(container["id"], YARD), 200)
    assert after["customs_status"] == "CLEARED"


# --------------------------------------------------------------------------- #
# Invalid-state guards
# --------------------------------------------------------------------------- #
def test_customs_clear_from_held_returns_invalid_state(api):
    """PRD §3.5: "[direct clearance] requires the container to be in `customs_status`
    `PENDING` and to not be `GATED_OUT`; otherwise `ERR_INVALID_STATE` applies."

    Design: Corner/state_machines/customs_clear_from_held_direct_returns_invalid_state
    """
    _, vessel, window = fx.provision_berthed_window()
    container = fx.declare_container(vessel["id"], window["id"], container_number="CLRH360360")
    cont_v = container["version"]
    fx.place_hold(container["id"], reason="INSPECTION")  # now HELD
    resp = api.customs_clear_container(
        container["id"], {"expected_container_version": cont_v}, CUSTOMS
    )
    # Container is HELD, so direct-clear's PENDING precondition fails.
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_release_already_released_hold_returns_invalid_state(api):
    """PRD §3.5: "[Releasing a hold] requires the hold to be `ACTIVE` and the
    container's `customs_status` to be `HELD`, otherwise `ERR_INVALID_STATE`."

    Design: Corner/state_machines/customs_release_idempotency_second_release_fails
    """
    _, vessel, window = fx.provision_berthed_window()
    container = fx.declare_container(vessel["id"], window["id"], container_number="IDEM330330")
    hold = fx.place_hold(container["id"], reason="INSPECTION")
    fx.get_success_data(api.release_customs_hold(hold["id"], CUSTOMS))
    resp = api.release_customs_hold(hold["id"], CUSTOMS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
