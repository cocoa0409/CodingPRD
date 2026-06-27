"""Replenishment dispatch, recall, vault conservation, OCC, and scheduling conflicts.

Covers queue-A difficulty instances (priority_pair_validation_conflict, resource_temporal_overlap,
compensating_invariant vault leg) and queue-B corner instances (validations dispatch errors,
endpoints recall, errors OCC, cross_cutting derived balance).
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    assert_vault_conservation,
    TEST_USERS,
    provision_network, create_cassette, schedule_order, schedule_and_dispatch_order,
    confirm_load_order, read_vault, read_order,
)

VAULT = TEST_USERS["vault_controller_headers"]


def _dispatch(api, order_id, version):
    return api.dispatch_order(order_id, {"expected_vault_version": version}, headers=VAULT)


# ============================================================================
# priority_pair_validation_conflict (queue A)
# ============================================================================

def test_dispatch_route_paused_beats_vault_insufficient(api):
    """PRD §3.4: "the fulfilling route must be `ACTIVE`, or the dispatch is rejected with
    `ERR_ROUTE_PAUSED`; the `order_amount_cents` must be an exact whole-number multiple of the
    target machine's `note_denomination_cents`, or it is rejected with `ERR_AMOUNT_NOT_DENOMINATED`;
    this order's service window must not collide with another order's window on the same route, or
    it is rejected with `ERR_ROUTE_WINDOW_CONFLICT`; it must not collide with another order on the
    same machine inside the service buffer, or it is rejected with `ERR_ATM_SERVICE_LOCKOUT`; the
    drawing vault's on-hand `balance_cents` must be at least the `order_amount_cents`, or it is
    rejected with `ERR_VAULT_INSUFFICIENT`"

    Design: Difficulty/priority_pair_validation_conflict/dispatch_route_paused_beats_vault_insufficient
    """
    # Vault provisioned 100c; order 500000c (> balance) on a PAUSED route.
    net = provision_network(provisioned_cents=100)
    order = schedule_order(net["atm"]["id"], net["route"]["id"], order_amount_cents=500_000)
    validate_success(api.pause_route(net["route"]["id"], headers=VAULT))
    resp = _dispatch(api, order["id"], net["vault"]["version"])
    validate_error(resp, ApiErrorId.ERR_ROUTE_PAUSED, expected_status=409)


def test_dispatch_invalid_state_beats_vault_insufficient(api):
    """PRD §2.6: "Among those, any attempt to drive an entity through a transition that is not
    defined from its current state — settling a run that is already `SETTLED`, acknowledging a
    ticket that is not `OPEN`, approving a disclosure that is not `DRAFT`, and the like — is
    rejected with `ERR_INVALID_STATE`, the generic guard that backs every state machine described
    below."

    Design: Difficulty/priority_pair_validation_conflict/dispatch_invalid_state_beats_vault_insufficient
    """
    # Vault 250000; dispatch a 200000 order (vault now 50000); re-dispatch the DISPATCHED order.
    net = provision_network(provisioned_cents=250_000)
    order = schedule_order(net["atm"]["id"], net["route"]["id"], order_amount_cents=200_000)
    validate_success(_dispatch(api, order["id"], net["vault"]["version"]))
    # Re-dispatch: order is already DISPATCHED, transition undefined -> ERR_INVALID_STATE.
    resp = _dispatch(api, order["id"], net["vault"]["version"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


# ============================================================================
# resource_temporal_overlap (queue A)
# ============================================================================

def test_route_window_halfopen_overlap_rejected_adjacent_allowed(api):
    """PRD §3.5: "Two half-open intervals overlap when this order's start is strictly before the
    other's end and the other's start is strictly before this order's end. Intervals that merely
    touch — where one order's start equals another's end — do not overlap and are permitted; there
    is no buffer on the route. A violation is rejected with `ERR_ROUTE_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/route_window_halfopen_overlap_rejected_adjacent_allowed
    """
    net = provision_network(provisioned_cents=100_000_000)
    route_id = net["route"]["id"]
    loc_id = net["location"]["id"]
    from test_helpers import create_atm
    atm_a = net["atm"]
    atm_b = create_atm(loc_id, serial_no="SN-RWB", surcharge_cents=100)
    atm_c = create_atm(loc_id, serial_no="SN-RWC", surcharge_cents=100)

    ro_a = schedule_order(atm_a["id"], route_id, order_amount_cents=200_000,
                          service_window_start="2026-01-05T09:00:00Z",
                          service_window_end="2026-01-05T10:00:00Z")
    v = read_vault(net["vault"]["id"])
    validate_success(_dispatch(api, ro_a["id"], v["version"]))

    # Overlapping [09:30,10:30) on the same route -> conflict.
    ro_b = schedule_order(atm_b["id"], route_id, order_amount_cents=200_000,
                          service_window_start="2026-01-05T09:30:00Z",
                          service_window_end="2026-01-05T10:30:00Z")
    # Adjacent [10:00,11:00) (starts exactly when ro_a ends) -> allowed.
    ro_c = schedule_order(atm_c["id"], route_id, order_amount_cents=200_000,
                          service_window_start="2026-01-05T10:00:00Z",
                          service_window_end="2026-01-05T11:00:00Z")

    v_now = read_vault(net["vault"]["id"])["version"]
    resp_b = _dispatch(api, ro_b["id"], v_now)
    validate_error(resp_b, ApiErrorId.ERR_ROUTE_WINDOW_CONFLICT, expected_status=409)

    resp_c = _dispatch(api, ro_c["id"], v_now)
    data_c = validate_success(resp_c)
    assert data_c["status"] == "DISPATCHED"


def test_atm_lockout_closed_buffer_overlap_rejected(api):
    """PRD §3.5: "It treats each order's window as a closed interval — including both endpoints —
    and expands that interval by thirty minutes on each side."
    PRD §3.5: "Because of the thirty-minute buffer on each side, two orders whose windows merely
    touch end-to-start do collide, and only a gap strictly greater than thirty minutes between them
    is allowed."
    PRD §3.5: "A violation is rejected with `ERR_ATM_SERVICE_LOCKOUT`."

    Design: Difficulty/resource_temporal_overlap/atm_lockout_closed_buffer_overlap_rejected
    """
    net = provision_network(provisioned_cents=100_000_000)
    atm_id = net["atm"]["id"]
    route_id = net["route"]["id"]
    ro_1 = schedule_order(atm_id, route_id, order_amount_cents=200_000,
                          service_window_start="2026-01-05T09:00:00Z",
                          service_window_end="2026-01-05T10:00:00Z")
    validate_success(_dispatch(api, ro_1["id"], net["vault"]["version"]))
    # Adjacent [10:00,11:00) on the SAME ATM -> 30-min buffer makes adjacency collide.
    ro_2 = schedule_order(atm_id, route_id, order_amount_cents=200_000,
                          service_window_start="2026-01-05T10:00:00Z",
                          service_window_end="2026-01-05T11:00:00Z")
    v_now = read_vault(net["vault"]["id"])["version"]
    resp = _dispatch(api, ro_2["id"], v_now)
    validate_error(resp, ApiErrorId.ERR_ATM_SERVICE_LOCKOUT, expected_status=409)


# ============================================================================
# compensating_invariant — vault conservation (queue A)
# ============================================================================

def test_vault_conservation_dispatch_then_recall(api):
    """PRD §2.7: "At all times the sum of the vault's on-hand `balance_cents`, its
    `in_transit_cents`, and its `in_machine_cents` equals `provisioned_cents`."
    PRD §3.7: "A recall from `DISPATCHED` is the consequential one: it restores conservation by
    crediting the vault's `balance_cents` by `order_amount_cents` and reducing its
    `in_transit_cents` by the same amount"

    Design: Difficulty/compensating_invariant/vault_conservation_dispatch_then_recall
    """
    net = provision_network(provisioned_cents=10_000_000)
    order = schedule_and_dispatch_order(net["atm"]["id"], net["route"]["id"], net["vault"]["id"],
                                        order_amount_cents=200_000)
    resp = api.recall_order(order["id"], headers=VAULT)
    recalled = validate_success(resp)
    assert recalled["status"] == "RECALLED"
    vault = read_vault(net["vault"]["id"])
    assert vault["balance_cents"] == 10_000_000
    assert vault["in_transit_cents"] == 0
    assert vault["in_machine_cents"] == 0
    assert_vault_conservation(vault)


# ============================================================================
# validations / endpoints / errors (queue B)
# ============================================================================

def test_vault_insufficient_dispatch_rejected(api):
    """PRD §3.5: "The **vault sufficiency** check is the fiscal guard: at dispatch the drawing
    vault's on-hand `balance_cents` must be greater than or equal to the `order_amount_cents`,
    otherwise the dispatch is rejected with `ERR_VAULT_INSUFFICIENT` and no cash moves."

    Design: Corner/validations/vault_insufficient_dispatch_rejected
    """
    net = provision_network(provisioned_cents=100_000)
    order = schedule_order(net["atm"]["id"], net["route"]["id"], order_amount_cents=200_000)
    resp = _dispatch(api, order["id"], net["vault"]["version"])
    validate_error(resp, ApiErrorId.ERR_VAULT_INSUFFICIENT, expected_status=422)


def test_dispatch_amount_not_denominated_rejected(api):
    """PRD §3.4: "the `order_amount_cents` must be an exact whole-number multiple of the target
    machine's `note_denomination_cents`, or it is rejected with `ERR_AMOUNT_NOT_DENOMINATED`"

    Design: Corner/validations/dispatch_amount_not_denominated_rejected
    """
    net = provision_network(provisioned_cents=100_000_000, note_denomination_cents=2000)
    order = schedule_order(net["atm"]["id"], net["route"]["id"], order_amount_cents=199_999)
    resp = _dispatch(api, order["id"], net["vault"]["version"])
    validate_error(resp, ApiErrorId.ERR_AMOUNT_NOT_DENOMINATED, expected_status=422)


def test_recall_scheduled_order_no_vault_change(api):
    """PRD §3.7: "A recall from `SCHEDULED` simply moves the order to its terminal `RECALLED`
    status; because no vault cash was ever debited for a scheduled order, no vault adjustment is
    needed"

    Design: Corner/endpoints/recall_scheduled_order_no_vault_change
    """
    net = provision_network(provisioned_cents=1_000_000)
    order = schedule_order(net["atm"]["id"], net["route"]["id"], order_amount_cents=200_000)
    resp = api.recall_order(order["id"], headers=VAULT)
    recalled = validate_success(resp)
    assert recalled["status"] == "RECALLED"
    vault = read_vault(net["vault"]["id"])
    assert vault["balance_cents"] == 1_000_000


def test_stale_vault_version_dispatch_returns_412(api):
    """PRD §2.8: "Before the dispatch debits anything, the server compares `expected_vault_version`
    against the vault's current `version`."
    PRD §2.8: "If they do not match — because some other dispatch or some recall compensation has
    advanced the vault's `version` since the client's last read, changing the on-hand balance out
    from under it — the request is rejected with `ERR_STALE_VERSION` and an HTTP 412 status, and no
    cash moves."

    Design: Corner/errors/stale_vault_version_dispatch_returns_412
    """
    from test_helpers import create_atm
    net = provision_network(provisioned_cents=100_000_000)
    atm2 = create_atm(net["location"]["id"], serial_no="SN-OCC-STALE", surcharge_cents=100)
    v_ver0 = net["vault"]["version"]
    ro1 = schedule_order(net["atm"]["id"], net["route"]["id"], order_amount_cents=200_000,
                         service_window_start="2026-01-05T08:00:00Z",
                         service_window_end="2026-01-05T10:00:00Z")
    ro2 = schedule_order(atm2["id"], net["route"]["id"], order_amount_cents=200_000,
                         service_window_start="2026-01-06T08:00:00Z",
                         service_window_end="2026-01-06T10:00:00Z")
    validate_success(_dispatch(api, ro1["id"], v_ver0))  # bumps version
    # Re-using the now-stale v_ver0 must fail with 412.
    resp = _dispatch(api, ro2["id"], v_ver0)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def test_dispatch_with_fresh_version_succeeds(api):
    """PRD §2.8: "A dispatch request must carry `expected_vault_version`, the value of the target
    vault's `version` that the client last observed when it read the vault. Before the dispatch
    debits anything, the server compares `expected_vault_version` against the vault's current
    `version`."

    Design: Corner/errors/confirm_load_correct_version_not_required_but_dispatch_fresh_succeeds
    """
    from test_helpers import create_atm
    net = provision_network(provisioned_cents=100_000_000)
    atm2 = create_atm(net["location"]["id"], serial_no="SN-OCC-OK", surcharge_cents=100)
    ro1 = schedule_order(net["atm"]["id"], net["route"]["id"], order_amount_cents=200_000,
                         service_window_start="2026-01-05T08:00:00Z",
                         service_window_end="2026-01-05T10:00:00Z")
    ro2 = schedule_order(atm2["id"], net["route"]["id"], order_amount_cents=200_000,
                         service_window_start="2026-01-06T08:00:00Z",
                         service_window_end="2026-01-06T10:00:00Z")
    validate_success(_dispatch(api, ro1["id"], net["vault"]["version"]))
    v_fresh = read_vault(net["vault"]["id"])["version"]
    resp = _dispatch(api, ro2["id"], v_fresh)
    data = validate_success(resp)
    assert data["status"] == "DISPATCHED"


def test_derived_vault_balance_recomputed_after_confirm_load(api):
    """PRD §3.6: "On success the cash leaves the in-transit bucket and enters the machine: the
    vault's `in_transit_cents` is reduced by `order_amount_cents` and its `in_machine_cents` is
    increased by the same amount."

    Design: Corner/cross_cutting_complexity_layers/derived_vault_balance_recomputed_after_confirm_load
    """
    net = provision_network(provisioned_cents=10_000_000)
    create_cassette(net["atm"]["id"], position="C1")
    order = schedule_and_dispatch_order(net["atm"]["id"], net["route"]["id"], net["vault"]["id"],
                                        order_amount_cents=200_000)
    confirm_load_order(order["id"])
    vault = read_vault(net["vault"]["id"])
    assert vault["balance_cents"] == 9_800_000
    assert vault["in_transit_cents"] == 0
    assert vault["in_machine_cents"] == 200_000
    assert_vault_conservation(vault)
