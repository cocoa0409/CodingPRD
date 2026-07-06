"""Ledger append-only surface, balance calculations, admin adjustments."""
import pytest

from test_helpers import (
    validate_success, validate_paginated, get_success_data,
    TEST_USERS, make_member_headers,
    ApiErrorId,
    create_member, seed_balance,
    setup_scheduled_exchange,
)


def test_ledger_entries_endpoint_supports_read_only_list(api):
    """PRD §2.6: "The ledger is a strict append-only log: once a LedgerEntry is
    posted, its delta_minutes, posted_at, entry_kind, memo, member_id,
    exchange_id, and redemption_id are immutable. Corrections take the form
    of a compensating entry, never a rewrite."

    Design: Corner/entities/immutability_ledger_entry_no_update_endpoint
    """
    resp = api.list_ledger_entries(headers=TEST_USERS["admin_headers"])
    data, meta = validate_paginated(resp)
    assert isinstance(data, list)
    assert meta["total_count"] == len(data) if meta["total_count"] <= 10 else True


def test_chronological_balance_sums_two_admin_adjustments(api):
    """PRD §2.6: "the entries are sorted with posted_at ascending as the primary
    key and LedgerEntry.created_at ascending as the secondary key — the entry
    id is never used as a tiebreak — and the running total starts at zero and
    adds each entry's delta_minutes in that order."

    Design: Corner/calculations/chronological_balance_after_admin_adjust
    """
    m = create_member(email_prefix="chb")
    seed_balance(m["id"], 180, memo="seed A")
    seed_balance(m["id"], -30, memo="adj B")
    resp = api.get_member(m["id"], headers=TEST_USERS["admin_headers"])
    data = validate_success(resp)
    assert data["chronological_balance_minutes"] == 150


def test_forward_looking_deducts_pending_scheduled_debit(api):
    """PRD §2.6: "The forward-looking balance, exposed as
    forward_looking_balance_minutes, is the chronological balance minus the
    sum of Exchange.committed_minutes across every exchange where
    requester_member_id equals the member and status is either SCHEDULED or
    DELIVERED"

    Design: Difficulty/dual_variant_calc/forward_looking_vs_chronological_balance_on_member
    """
    ctx = setup_scheduled_exchange(
        committed_minutes=90,
        scheduled_start="2026-03-01T10:00:00Z",
        earliest="2026-03-01T10:00:00Z",
        latest="2026-03-02T18:00:00Z",
        requester_seed=240,
        clock="2026-03-01T09:00:00Z",
    )
    resp = api.get_member(
        ctx["requester"]["id"],
        headers=make_member_headers(ctx["requester"]["id"]),
    )
    data = validate_success(resp)
    assert data["chronological_balance_minutes"] == 240
    assert data["forward_looking_balance_minutes"] == 150
    assert data["chronological_balance_minutes"] - data["forward_looking_balance_minutes"] == 90


def test_forward_looking_and_chronological_diverge_only_on_pending(api):
    """PRD §2.6: "the chronological variant — the plain chronological balance
    with no pending subtraction — is what impact reporting, historical audits,
    and dispute reconstruction consume, because it treats the ledger as final
    at each posted_at; the forward-looking variant — the chronological balance
    minus pending SCHEDULED and DELIVERED obligations — is what gates
    redemption authorisation and the exchange-creation ceiling, so that a
    member cannot double-commit hours they have already promised to another
    exchange."

    Design: Difficulty/dual_variant_calc/forward_looking_vs_chronological_balance_on_member
    """
    m = create_member(email_prefix="var")
    seed_balance(m["id"], 240, memo="seed for chrono")
    resp = api.get_member(m["id"], headers=make_member_headers(m["id"]))
    data = validate_success(resp)
    # No pending exchanges → the two variants agree.
    assert data["chronological_balance_minutes"] == 240
    assert data["forward_looking_balance_minutes"] == 240


def test_ledger_entries_pagination_with_member_filter(api):
    """PRD §2.3: "The default limit is 10, the minimum accepted value is 1,
    and the maximum is 100; the default offset is 0."
    PRD §2.3: "total_count is the size of the filtered result set before the
    window is applied, and has_more is true whenever offset + limit is
    smaller than total_count."

    Design: Corner/cross_cutting_complexity_layers/pagination_filtering_ledger_entries
    """
    m = create_member(email_prefix="pg")
    for _ in range(5):
        seed_balance(m["id"], 15, memo="e")
    resp = api.list_ledger_entries(
        headers=make_member_headers(m["id"]),
        params={"member_id": m["id"], "limit": 2, "offset": 1},
    )
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 5
    assert len(data) == 2
    assert meta["has_more"] is True
