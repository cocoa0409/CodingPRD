"""Contract lifecycle: commit guards and the cancellation cascade."""
from test_helpers import (
    ApiErrorId,
    assert_customer_contract,
    create_active_season,
    create_committed_contract,
    create_contract,
    create_route_stop,
    create_season,
    get_assignment,
    get_contract,
    get_machine,
    get_stop,
    reserve_machine,
    validate_error,
    validate_success,
)


def test_contract_commit_from_committed_returns_invalid_state(api, grower_liaison_headers):
    """PRD section 3.2: "The contract must be in `DRAFT` (otherwise
    `ERR_CONTRACT_NOT_DRAFT`, HTTP 409), the parent season must be in `DRAFT`
    or `ACTIVE` (otherwise `ERR_SEASON_NOT_OPEN_FOR_COMMIT`, HTTP 409), and
    `committed_acres` must be greater than zero."

    Design: Corner/state_machines/contract_commit_from_committed_returns_invalid_state
    """
    season = create_season()
    contract = create_contract(season["id"])
    validate_success(api.commit_contract(contract["id"], grower_liaison_headers))
    resp = api.commit_contract(contract["id"], grower_liaison_headers)
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_DRAFT)


def test_cancel_contract_cascades_scheduled_stops(api, grower_liaison_headers):
    """PRD section 3.2: "Cancellation cascades: every stop of the contract
    still in `SCHEDULED` transitions to `SKIPPED`; each such stop's `RESERVED`
    machine assignments transition to `CANCELLED`, releasing each affected
    machine back to `AVAILABLE` if it is not allocated to any other active
    assignment; and the season's `committed_acres_total` is recomputed to
    exclude the cancelled contract."

    Design: Corner/endpoints/cancel_contract_cascades_scheduled_stops
    """
    ctx = create_active_season()
    machine = ctx["machine"]
    contract = create_committed_contract(ctx["season"]["id"])
    stop = create_route_stop(contract["id"], sequence_index=1)
    assignment = reserve_machine(stop["id"], machine["id"])

    resp = api.cancel_contract(contract["id"], grower_liaison_headers)
    cancelled = validate_success(resp)
    assert cancelled["status"] == "CANCELLED", (
        f"contract must be CANCELLED after cancel, got {cancelled['status']!r}"
    )

    stop_now = get_stop(stop["id"])
    assert stop_now["status"] == "SKIPPED", (
        f"scheduled stop must cascade to SKIPPED, got {stop_now['status']!r}"
    )
    assignment_now = get_assignment(assignment["id"])
    assert assignment_now["status"] == "CANCELLED", (
        f"reserved assignment must cascade to CANCELLED, got {assignment_now['status']!r}"
    )
    machine_now = get_machine(machine["id"])
    assert machine_now["status"] == "AVAILABLE", (
        f"unallocated machine must return to AVAILABLE, got {machine_now['status']!r}"
    )
    assert_customer_contract(get_contract(contract["id"]))
