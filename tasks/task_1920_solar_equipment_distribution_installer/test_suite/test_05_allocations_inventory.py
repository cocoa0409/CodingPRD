"""Allocations: availability boundaries, release invariants, OCC on the lot,
and immediate same-transaction visibility."""
from test_helpers import (
    TEST_USERS,
    allocate_current_version,
    api_client,
    assert_lot_invariants,
    create_allocation_payload,
    get_lot,
    make_installer_rep_headers,
    setup_project_with_on_hand_lot,
    setup_shipped_project,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId

ADMIN = TEST_USERS["admin_headers"]
MANAGER = TEST_USERS["manager_headers"]


def test_qty_available_zero_rejects_further_allocation(api):
    """PRD section 3.6: "the availability check then requires the lot's
    `qty_available` to be at least the requested `qty_allocated`, failing with
    `ERR_INSUFFICIENT_QTY` otherwise". After all 5 units are allocated,
    `qty_available` stands at exactly 0 and a request for 1 more is rejected.

    Design: Difficulty/boundary_precision_check/qty_available_zero_rejects_allocation
    """
    ctx = setup_project_with_on_hand_lot(module_qty=5, lot_qty=5)
    inst_id = ctx["installer"]["id"]
    proj_id = ctx["project"]["id"]
    lot_id = ctx["lot"]["id"]

    allocate_current_version(proj_id, inst_id, lot_id, 5)
    lot = get_lot(lot_id)
    assert lot["qty_available"] == 0, "all 5 units allocated: boundary 0"
    assert_lot_invariants(lot)

    resp = api_client.create_allocation(
        proj_id,
        create_allocation_payload(lot_id, 1, lot["version"]),
        make_installer_rep_headers(inst_id),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_QTY)


def test_allocation_above_available_rejected(api):
    """PRD section 3.6: "the availability check then requires the lot's
    `qty_available` to be at least the requested `qty_allocated`, failing with
    `ERR_INSUFFICIENT_QTY` otherwise". Requesting 6 against 5 available fails;
    the comparison is `at least`, not a strict-greater allowance.

    Design: Difficulty/boundary_precision_check/qty_available_zero_rejects_allocation
    """
    ctx = setup_project_with_on_hand_lot(module_qty=5, lot_qty=5)
    inst_id = ctx["installer"]["id"]
    resp = api_client.create_allocation(
        ctx["project"]["id"],
        create_allocation_payload(ctx["lot"]["id"], 6, ctx["lot"]["version"]),
        make_installer_rep_headers(inst_id),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_QTY)


def test_allocate_then_release_restores_qty_available(api):
    """PRD section 3.3: "the derived `qty_available`, which is `qty_on_hand`
    minus `qty_allocated` minus `qty_quarantined` and is never negative".
    PRD section 3.6: "Releasing moves the allocation to `RELEASED`, stamps
    `released_at`, decreases the lot's `qty_allocated` by the released
    quantity so the units return to the available pool, recomputes the
    project's `allocated_value_cents`, and increments the lot's `version` by
    1."

    Design: Difficulty/compensating_invariant/allocation_create_then_release_preserves_lot_qty_available
    """
    ctx = setup_project_with_on_hand_lot(module_qty=5, lot_qty=10)
    inst_id = ctx["installer"]["id"]
    proj_id = ctx["project"]["id"]
    lot_id = ctx["lot"]["id"]

    assert ctx["lot"]["qty_available"] == 10

    allocation = allocate_current_version(proj_id, inst_id, lot_id, 4)
    lot = get_lot(lot_id)
    assert lot["qty_available"] == 6, (
        f"after allocating 4 of 10, qty_available must be 6, "
        f"got {lot['qty_available']}"
    )

    released = validate_success(
        api_client.release_allocation(
            allocation["id"], make_installer_rep_headers(inst_id)
        ),
        200,
    )
    assert released["status"] == "RELEASED"

    lot = get_lot(lot_id)
    assert lot["qty_available"] == 10, (
        f"release must restore qty_available to 10, got {lot['qty_available']}"
    )
    assert_lot_invariants(lot)


def test_release_stamps_released_at_and_increments_lot_version(api):
    """PRD section 3.6: "the lot's `qty_allocated` increases by the reserved
    quantity; the project's `allocated_value_cents` recomputes; if the design
    is locked and this is the project's first `OPEN` allocation, fulfillment
    moves `DESIGN` → `ALLOCATED`; the installer's `credit_hold` is
    re-evaluated; and the lot's `version` increments by 1."
    PRD section 3.6: "Releasing moves the allocation to `RELEASED`, stamps
    `released_at`, decreases the lot's `qty_allocated` by the released
    quantity so the units return to the available pool, recomputes the
    project's `allocated_value_cents`, and increments the lot's `version` by
    1."

    Design: Difficulty/compensating_invariant/allocation_create_then_release_preserves_lot_qty_available
    """
    ctx = setup_project_with_on_hand_lot(module_qty=5, lot_qty=10)
    inst_id = ctx["installer"]["id"]
    proj_id = ctx["project"]["id"]
    lot_id = ctx["lot"]["id"]
    version_before = ctx["lot"]["version"]

    allocation = allocate_current_version(proj_id, inst_id, lot_id, 4)
    released = validate_success(
        api_client.release_allocation(
            allocation["id"], make_installer_rep_headers(inst_id)
        ),
        200,
    )
    assert released["status"] == "RELEASED"
    assert released["released_at"] is not None

    lot = get_lot(lot_id)
    # create (+1) then release (+1) must move the lot version by exactly 2.
    assert lot["version"] == version_before + 2, (
        f"lot version must advance by 2 across create+release, "
        f"{version_before} -> {lot['version']}"
    )
    project = validate_success(api_client.get_project(proj_id, MANAGER), 200)
    assert project["allocated_value_cents"] == 0


def test_occ_allocation_create_with_stale_lot_version_rejected(api):
    """PRD section 2.8: "If the lot's current `version` does not match the
    supplied value — because another writer has since placed, released, or
    shipped an allocation against the same lot, each of which legitimately
    mutates the reserved quantity and therefore the client's observed
    availability — the create is rejected with `ERR_STALE_LOT_VERSION`
    (HTTP 412), preventing the client from reserving against a lot state it
    has not observed."

    Design: Corner/cross_cutting_layers/occ_allocation_create_with_stale_lot_version_rejected
    """
    ctx = setup_project_with_on_hand_lot(module_qty=5, lot_qty=10)
    inst_id = ctx["installer"]["id"]
    proj_id = ctx["project"]["id"]
    lot_id = ctx["lot"]["id"]
    observed_version = ctx["lot"]["version"]

    # First allocation advances the lot version beyond the observed value.
    allocate_current_version(proj_id, inst_id, lot_id, 1)

    resp = api_client.create_allocation(
        proj_id,
        create_allocation_payload(lot_id, 1, observed_version),
        make_installer_rep_headers(inst_id),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_LOT_VERSION)


def test_allocation_immediately_visible_in_project(api):
    """PRD section 2.7: "The system maintains a family of derived figures, and
    each is recomputed inside the same transaction as the event that could
    change it; there is no eventual-consistency window anywhere in the API."
    PRD section 3.6: "A project's `allocated_value_cents` is the sum, over its
    allocations in `OPEN` or `SHIPPED`, of each allocation's `qty_allocated`
    multiplied by its frozen `unit_cost_cents_at_allocation`."

    Design: Corner/consistency_model/allocation_immediately_visible_in_project
    """
    ctx = setup_project_with_on_hand_lot(module_qty=5, lot_qty=5)
    inst_id = ctx["installer"]["id"]
    proj_id = ctx["project"]["id"]

    allocation = allocate_current_version(proj_id, inst_id,
                                          ctx["lot"]["id"], 5)
    # 5 units x frozen 55000c final cost = 275000.
    assert allocation["unit_cost_cents_at_allocation"] == 55000

    project = validate_success(api_client.get_project(proj_id, MANAGER), 200)
    assert project["allocated_value_cents"] == 275000, (
        f"allocated_value_cents must reflect the allocation immediately, "
        f"got {project['allocated_value_cents']}"
    )
    assert project["fulfillment_status"] == "ALLOCATED"


def test_ship_on_released_allocation_returns_state_error(api):
    """PRD section 3.6: "Shipping is a `DistributionAdmin` action on an `OPEN`
    allocation — anything else fails with `ERR_ALLOCATION_NOT_OPEN`." A
    released allocation is no longer OPEN, so the state precondition surfaces
    the 409 state error regardless of any fiscal consideration.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_allocation_on_released_allocation_with_credit_exceeded
    """
    ctx = setup_project_with_on_hand_lot(module_qty=5, lot_qty=5)
    inst_id = ctx["installer"]["id"]
    proj_id = ctx["project"]["id"]

    allocation = allocate_current_version(proj_id, inst_id,
                                          ctx["lot"]["id"], 5)
    validate_success(
        api_client.release_allocation(
            allocation["id"], make_installer_rep_headers(inst_id)
        ),
        200,
    )
    resp = api_client.ship_allocation(allocation["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_ALLOCATION_NOT_OPEN)


def test_double_release_returns_state_error(api):
    """PRD section 3.6: "Release is the inverse gesture, open to an
    `InstallerRep` on their own projects and to a `ChannelManager`, and
    likewise requires an `OPEN` allocation (`ERR_ALLOCATION_NOT_OPEN`
    otherwise)." Releasing an already-RELEASED allocation reports the state
    error, never a fiscal one.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_allocation_on_released_allocation_with_credit_exceeded
    """
    ctx = setup_project_with_on_hand_lot(module_qty=5, lot_qty=5)
    inst_id = ctx["installer"]["id"]
    proj_id = ctx["project"]["id"]
    rep = make_installer_rep_headers(inst_id)

    allocation = allocate_current_version(proj_id, inst_id,
                                          ctx["lot"]["id"], 5)
    validate_success(api_client.release_allocation(allocation["id"], rep), 200)
    resp = api_client.release_allocation(allocation["id"], rep)
    validate_error(resp, ApiErrorId.ERR_ALLOCATION_NOT_OPEN)


def test_allocation_release_from_shipped_returns_invalid_state(api):
    """PRD section 3.6: "Release is the inverse gesture, open to an
    `InstallerRep` on their own projects and to a `ChannelManager`, and
    likewise requires an `OPEN` allocation (`ERR_ALLOCATION_NOT_OPEN`
    otherwise)." A SHIPPED allocation cannot be released.

    Design: Corner/state_machines/allocation_release_from_shipped_returns_invalid_state
    """
    ctx = setup_shipped_project(module_qty=5, lot_qty=5)
    inst_id = ctx["installer"]["id"]
    assert ctx["allocation"]["status"] == "SHIPPED"
    resp = api_client.release_allocation(
        ctx["allocation"]["id"], make_installer_rep_headers(inst_id)
    )
    validate_error(resp, ApiErrorId.ERR_ALLOCATION_NOT_OPEN)
