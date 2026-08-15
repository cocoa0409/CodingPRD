"""Settlement workflow: the HARVESTED gate and its precedence over OCC,
paid-terminal lockdown, dispute/resolve cascade, and contract-version OCC."""
from test_helpers import (
    ApiErrorId,
    create_draft_settlement,
    get_contract,
    setup_cutting_stop,
    setup_issued_settlement,
    setup_settling_season_with_draft_settlement,
    validate_error,
    validate_success,
)


def test_settlement_issue_requires_contract_harvested(api, billing_clerk_headers):
    """PRD section 3.8: "the parent contract must be in `HARVESTED`, meaning
    every one of its stops has reached `COMPLETED` or `SKIPPED` (otherwise
    `ERR_CONTRACT_NOT_HARVESTED`, HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/settlement_issue_requires_contract_harvested
    """
    ctx = setup_cutting_stop()
    settlement = create_draft_settlement(ctx["contract"]["id"])
    version = get_contract(ctx["contract"]["id"])["version"]

    resp = api.issue_settlement(
        settlement["id"], {"expected_contract_version": version}, billing_clerk_headers
    )
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_HARVESTED)

    contract_now = get_contract(ctx["contract"]["id"])
    assert contract_now["status"] == "IN_PROGRESS", (
        f"rejected issue must not move the contract, got {contract_now['status']!r}"
    )


def test_harvested_check_fires_before_stale_version(api, billing_clerk_headers):
    """PRD section 2.6: "When a billing clerk issues a settlement, the
    contract-must-be-harvested check (`ERR_CONTRACT_NOT_HARVESTED`) is
    evaluated before the optimistic-concurrency check (`ERR_STALE_VERSION`),
    so a premature issue attempt reports the contract state rather than a
    version mismatch."

    Design: Difficulty/cross_entity_state_dependency/settlement_issue_requires_contract_harvested
    """
    ctx = setup_cutting_stop()
    settlement = create_draft_settlement(ctx["contract"]["id"])
    stale_version = get_contract(ctx["contract"]["id"])["version"] + 5

    resp = api.issue_settlement(
        settlement["id"], {"expected_contract_version": stale_version}, billing_clerk_headers
    )
    validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_HARVESTED)


def test_terminal_settlement_paid_lockdown(api, billing_clerk_headers):
    """PRD section 3.8: "The clerk marks it paid (`ISSUED → PAID`; a
    settlement not in `ISSUED` yields `ERR_SETTLEMENT_NOT_ISSUED`, HTTP 409),
    which auto-transitions the parent contract `HARVESTED → SETTLED`."

    Design: Corner/state_machines/terminal_settlement_paid_lockdown
    """
    ctx = setup_issued_settlement()
    settlement_id = ctx["settlement"]["id"]
    validate_success(api.mark_settlement_paid(settlement_id, billing_clerk_headers))

    resp = api.mark_settlement_paid(settlement_id, billing_clerk_headers)
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOT_ISSUED)


def test_settlement_dispute_then_resolve_cascade_to_contract_settled(
    api, grower_liaison_headers, billing_clerk_headers
):
    """PRD section 3.8: "A disputed settlement is resolved by the clerk
    (`DISPUTED → RESOLVED`; any other state yields
    `ERR_SETTLEMENT_NOT_DISPUTED`, HTTP 409), and the resolution request must
    carry a `resolution_note`, a non-empty string. Resolution, like payment,
    auto-transitions the parent contract `HARVESTED → SETTLED`."

    Design: Corner/endpoints/settlement_dispute_then_resolve_cascade_to_contract_settled
    """
    ctx = setup_issued_settlement()
    settlement_id = ctx["settlement"]["id"]

    disputed = validate_success(api.dispute_settlement(settlement_id, grower_liaison_headers))
    assert disputed["status"] == "DISPUTED"

    resolved = validate_success(
        api.resolve_settlement(settlement_id, {"resolution_note": "adjusted"}, billing_clerk_headers)
    )
    assert resolved["status"] == "RESOLVED", (
        f"resolve must yield RESOLVED, got {resolved['status']!r}"
    )
    contract_now = get_contract(ctx["contract"]["id"])
    assert contract_now["status"] == "SETTLED", (
        f"resolution must settle the parent contract, got {contract_now['status']!r}"
    )


def test_occ_settlement_issue_stale_contract_version_rejected(api, billing_clerk_headers):
    """PRD section 2.7: "an issue-settlement request must carry
    `expected_contract_version`, a non-optional field holding the `version`
    of the parent customer contract as the client last observed it; a
    mismatch with the contract's current `version` is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_settlement_issue_stale_contract_version_rejected
    """
    ctx = setup_settling_season_with_draft_settlement()
    current_version = get_contract(ctx["contract"]["id"])["version"]

    resp = api.issue_settlement(
        ctx["settlement"]["id"],
        {"expected_contract_version": current_version - 1},
        billing_clerk_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_delivery_ticket_posting_bumps_contract_version(api, crew_boss_headers):
    """PRD section 3.7: "Posting a ticket also increments the parent
    contract's `version` by 1. This is the intended serialization point with
    settlement issuance: a ticket posted after a billing clerk last read the
    contract makes the clerk's `expected_contract_version` stale".
    PRD section 2.4: "Posting a delivery ticket, for example, increments the
    parent contract's `version` by 1 even though the ticket is a separate
    resource".

    Design: Corner/cross_cutting_complexity_layers/occ_settlement_issue_stale_contract_version_rejected
    """
    ctx = setup_cutting_stop()
    before = get_contract(ctx["contract"]["id"])["version"]

    validate_success(api.create_delivery_ticket(
        ctx["stop"]["id"],
        {"delivered_at": "2026-08-06T09:00:00Z", "gross_bushels": 800,
         "moisture_pct": 14.0, "used_our_trucks": False},
        crew_boss_headers,
    ), 201)

    after = get_contract(ctx["contract"]["id"])["version"]
    assert after == before + 1, (
        f"posting a ticket must increment contract.version by exactly 1: {before} -> {after}"
    )
