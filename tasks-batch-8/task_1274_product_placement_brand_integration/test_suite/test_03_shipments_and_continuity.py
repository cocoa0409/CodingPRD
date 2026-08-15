"""Prop shipment lifecycle and continuity tracking (PRD §3.6)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_shipment,
    create_continuity_record,
    create_shipment,
    get_shipment,
    list_continuity_records,
    setup_active_contract,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["manager_headers"]


def _mgr():
    return MANAGER


def test_shipment_happy_path_walk(api):
    """PRD §3.6: "The legal steps are: `PENDING` → `DISPATCHED`, which requires
    the contract to be `ACTIVE`; `DISPATCHED` → `DELIVERED`; `DELIVERED` →
    `STAGED`". PRD §3.6: "Every advance increments the shipment's `version` by 1."

    Design: Corner/state_machines/shipment_happy_path_walk
    """
    ctx = setup_active_contract()
    shipment = create_shipment(ctx["contract"]["id"])
    v0 = shipment["version"]
    s1 = validate_success(api.advance_shipment(shipment["id"], {"to": "DISPATCHED"}, _mgr()))
    s2 = validate_success(api.advance_shipment(shipment["id"], {"to": "DELIVERED"}, _mgr()))
    s3 = validate_success(api.advance_shipment(shipment["id"], {"to": "STAGED"}, _mgr()))
    assert s1["status"] == "DISPATCHED", f"step 1: {s1['status']}"
    assert s2["status"] == "DELIVERED", f"step 2: {s2['status']}"
    assert s3["status"] == "STAGED", f"step 3: {s3['status']}"
    assert s1["version"] == v0 + 1, f"version after first advance: {s1['version']} != {v0 + 1}"
    assert s3["version"] == v0 + 3, f"version after third advance: {s3['version']} != {v0 + 3}"


def test_shipment_skip_stage_returns_invalid_state(api):
    """PRD §3.6: "Naming a target that does not correspond to a legal step from
    the current state is rejected with `ERR_INVALID_STATE`".

    Design: Corner/state_machines/shipment_skip_stage_returns_invalid_state
    """
    ctx = setup_active_contract()
    shipment = create_shipment(ctx["contract"]["id"])
    resp = api.advance_shipment(shipment["id"], {"to": "DELIVERED"}, _mgr())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_shipment(shipment["id"])
    assert after["status"] == "PENDING", f"shipment must stay PENDING, got {after['status']}"


def test_shipment_reship_cycle(api):
    """PRD §3.6: "`RETURN_REQUESTED` → `DISPATCHED`, the defective-prop
    reshipment cycle, which again requires the contract to be `ACTIVE`".

    Design: Corner/state_machines/shipment_reship_cycle
    """
    ctx = setup_active_contract()
    shipment = create_shipment(ctx["contract"]["id"])
    advance_shipment(shipment["id"], "DISPATCHED")
    advance_shipment(shipment["id"], "DELIVERED")
    s1 = validate_success(api.advance_shipment(shipment["id"], {"to": "RETURN_REQUESTED"}, _mgr()))
    s2 = validate_success(api.advance_shipment(shipment["id"], {"to": "DISPATCHED"}, _mgr()))
    s3 = validate_success(api.advance_shipment(shipment["id"], {"to": "DELIVERED"}, _mgr()))
    assert s1["status"] == "RETURN_REQUESTED", f"step 1: {s1['status']}"
    assert s2["status"] == "DISPATCHED", f"reshipment: {s2['status']}"
    assert s3["status"] == "DELIVERED", f"cycle must revisit DELIVERED, got {s3['status']}"


def test_terminate_cascade_voids_continuity_via_shipment(api):
    """PRD §3.5: "Terminating an `ACTIVE` contract does all of that and
    additionally runs the logistics cascade: every shipment of the contract in
    `PENDING`, `DISPATCHED`, `DELIVERED`, or `STAGED` is moved to
    `RETURN_REQUESTED`, and each shipment entering `RETURN_REQUESTED` voids its
    continuity records, flipping them from `LOGGED` to `VOID`."
    PRD §3.5: "the opportunity returns from `RESERVED` to `IDENTIFIED`".

    Design: Difficulty/transitive_cascade/terminate_cascade_voids_continuity
    """
    ctx = setup_active_contract()
    shipment = create_shipment(ctx["contract"]["id"])
    advance_shipment(shipment["id"], "DISPATCHED")
    advance_shipment(shipment["id"], "DELIVERED")
    advance_shipment(shipment["id"], "STAGED")
    record = create_continuity_record(ctx["contract"]["id"], shipment["id"])
    assert record["status"] == "LOGGED"

    resp = api.terminate_contract(ctx["contract"]["id"], _mgr())
    contract = validate_success(resp)
    assert contract["status"] == "TERMINATED", f"contract: {contract['status']}"

    shipment_after = get_shipment(shipment["id"])
    assert shipment_after["status"] == "RETURN_REQUESTED", (
        f"cascade link 1: shipment must be RETURN_REQUESTED, got {shipment_after['status']}"
    )
    records = list_continuity_records(ctx["contract"]["id"])
    by_id = {r["id"]: r for r in records}
    assert by_id[record["id"]]["status"] == "VOID", (
        f"cascade link 2: continuity record must be VOID, got {by_id[record['id']]['status']}"
    )

    from test_helpers import get_opportunity

    opp_after = get_opportunity(ctx["opportunity"]["id"])
    assert opp_after["status"] == "IDENTIFIED", (
        f"opportunity must be released back to IDENTIFIED, got {opp_after['status']}"
    )


def test_terminate_from_staged_voids_only_via_return_requested(api):
    """PRD §3.6: "Whenever a shipment enters `RETURN_REQUESTED` — whether
    advanced there from `DELIVERED` or `STAGED`, or driven there by the
    contract-termination cascade — its continuity records are voided from
    `LOGGED` to `VOID`."

    Design: Difficulty/transitive_cascade/terminate_cascade_voids_continuity
    """
    ctx = setup_active_contract()
    shipment = create_shipment(ctx["contract"]["id"])
    advance_shipment(shipment["id"], "DISPATCHED")
    advance_shipment(shipment["id"], "DELIVERED")
    advance_shipment(shipment["id"], "STAGED")
    record = create_continuity_record(
        ctx["contract"]["id"], shipment["id"], note="set dressing note"
    )
    api.terminate_contract(ctx["contract"]["id"], _mgr())
    records = list_continuity_records(ctx["contract"]["id"])
    by_id = {r["id"]: r for r in records}
    assert by_id[record["id"]]["status"] == "VOID", (
        "the termination cascade must void the record via the shipment transition"
    )
