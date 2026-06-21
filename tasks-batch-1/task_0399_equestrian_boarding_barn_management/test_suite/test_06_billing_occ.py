"""Optimistic concurrency on invoice finalization.

Covers the stale-version rejection and the matching success path for
finalizing an invoice against the owner's version (PRD §2.10, §3.8).
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_owner_with_signed_waiver, create_stall, create_horse,
    create_draft_agreement, transition_agreement,
    open_invoice, get_owner, adjust_deposit, set_clock,
    setup_open_invoice_for_ended_boarding,
    TEST_USERS,
)

BM = TEST_USERS["barn_manager_headers"]


def test_finalize_with_stale_owner_version_rejected(api):
    """PRD §2.10: "If another writer has advanced the owner's version since the client
    last read it — for instance because a prior finalization already consumed deposit
    and marked lines invoiced — the stale request is rejected with
    `ERR_STALE_OWNER_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_owner_version_on_finalize
    """
    ctx = setup_open_invoice_for_ended_boarding(daily_rate_cents=4500)
    owner_id = ctx["owner"]["id"]
    inv_id = ctx["invoice"]["id"]
    stale = validate_success(api.get_owner(owner_id, BM), 200)["version"]
    adjust_deposit(owner_id, 1000)  # advances Owner.version past `stale`
    res = api.transition_invoice(
        inv_id, {"target_status": "FINALIZED", "expected_owner_version": stale}, BM
    )
    validate_error(res, "ERR_STALE_OWNER_VERSION", expected_status=412)
    invoices, _ = validate_paginated(api.list_owner_invoices(owner_id, BM))
    target = [i for i in invoices if i["id"] == inv_id][0]
    assert target["status"] == "OPEN"


def test_finalize_with_current_owner_version_succeeds(api):
    """PRD §3.8: "`expected_owner_version` must equal the owner's current `version`
    (else `ERR_STALE_OWNER_VERSION`, HTTP 412). On success the system computes the
    invoice totals by the rule of Section 3.9, then: ... it increases the owner's
    `account_balance_cents` by the `amount_due_cents`".

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_finalize_succeeds_and_bumps_version
    """
    ctx = setup_open_invoice_for_ended_boarding(daily_rate_cents=4500)
    owner_id = ctx["owner"]["id"]
    inv_id = ctx["invoice"]["id"]
    current = validate_success(api.get_owner(owner_id, BM), 200)["version"]
    finalized = validate_success(
        api.transition_invoice(
            inv_id, {"target_status": "FINALIZED", "expected_owner_version": current}, BM
        ),
        200,
    )
    assert finalized["status"] == "FINALIZED"
    assert finalized["amount_due_cents"] == 45000
    after = validate_success(api.get_owner(owner_id, BM), 200)
    assert after["account_balance_cents"] == 45000
