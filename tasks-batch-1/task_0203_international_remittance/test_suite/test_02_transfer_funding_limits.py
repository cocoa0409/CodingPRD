"""Transfer funding, send-limit enforcement, and the fund-time cascade.

Covers the per-transfer / KYC-tier / rolling-window ceilings (all inclusive),
the depth-2 fund cascade onto corridor.reserved_minor and the ledger, and the
rolling-window aggregate-capacity overlap.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    setup_corridor, setup_sender, setup_recipient,
    create_locked_quote, create_transfer_from_quote,
    setup_created_transfer, ledger_entries_for, get_corridor, ledger_net,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
AGENT = TEST_USERS["remittance_agent_headers"]


def _fund_one(api, corridor_id, sender_id, recipient_id, principal):
    quote = create_locked_quote(corridor_id, sender_id, send_principal_minor=principal)
    transfer = create_transfer_from_quote(quote, recipient_id)
    return transfer


# ─── fund cascade depth-2 (reserved_minor + ledger) ─────────────────────────

def test_fund_increases_reserved_minor_by_principal(api):
    """PRD §3.4: "the transfer's `funding_status` becomes `FUNDED`, the corridor's
    `reserved_minor` is increased by `send_principal_minor`."

    Design: Difficulty/transitive_cascade/fund_cascade_depth2_reserved_and_ledger
    """
    corridor = setup_corridor(rolling_window_cap_minor=4000000)
    sender = setup_sender(kyc_tier="TIER1")
    recipient = setup_recipient(sender["id"])
    transfer = _fund_one(api, corridor["id"], sender["id"], recipient["id"], 50000)
    assert corridor["reserved_minor"] == 0
    funded = validate_success(api.fund_transfer(transfer["id"], AGENT), 200)
    assert funded["funding_status"] == "FUNDED", funded["funding_status"]
    after = get_corridor(corridor["id"])
    assert after["reserved_minor"] == 50000, after["reserved_minor"]


def test_fund_writes_sender_debit_and_fee_revenue_entries(api):
    """PRD §3.4: "two ledger entries are written: a `SENDER_DEBIT` whose
    `amount_minor` is the negative of the sum of `send_principal_minor` and
    `fee_minor` (the sender pays principal plus fee), and a `FEE_REVENUE` whose
    `amount_minor` is the positive `fee_minor`."

    Design: Difficulty/transitive_cascade/fund_cascade_depth2_reserved_and_ledger
    """
    corridor = setup_corridor(rolling_window_cap_minor=4000000)
    sender = setup_sender(kyc_tier="TIER1")
    recipient = setup_recipient(sender["id"])
    transfer = _fund_one(api, corridor["id"], sender["id"], recipient["id"], 50000)
    validate_success(api.fund_transfer(transfer["id"], AGENT), 200)
    entries = ledger_entries_for(transfer["id"])
    by_type = {e["entry_type"]: e for e in entries}
    assert len(entries) == 2, f"expected exactly 2 entries, got {len(entries)}"
    # P=50000, fee=799 -> SENDER_DEBIT -50799, FEE_REVENUE +799.
    assert by_type["SENDER_DEBIT"]["amount_minor"] == -50799, by_type["SENDER_DEBIT"]["amount_minor"]
    assert by_type["FEE_REVENUE"]["amount_minor"] == 799, by_type["FEE_REVENUE"]["amount_minor"]


# ─── rolling-window inclusive boundary (boundary precision) ─────────────────

def test_rolling_window_third_fund_at_exact_cap_passes(api):
    """PRD §3.4: "require the projected total to be at most the corridor's
    `rolling_window_cap_minor`, else `ERR_ROLLING_WINDOW_LIMIT`."
    PRD §3.4: "Three ceilings are then checked, all with inclusive boundaries (the
    limit value itself passes; one minor unit beyond it fails)."

    Design: Difficulty/boundary_precision_check/rolling_window_cap_inclusive_boundary_on_fund
    """
    corridor = setup_corridor(rolling_window_cap_minor=400000)
    sender = setup_sender(kyc_tier="TIER2")
    recipient = setup_recipient(sender["id"])
    # prior funded = 150000 + 150000 = 300000.
    for _ in range(2):
        t = _fund_one(api, corridor["id"], sender["id"], recipient["id"], 150000)
        validate_success(api.fund_transfer(t["id"], AGENT), 200)
    # third fund of exactly 100000 -> projected 400000 == cap (inclusive) -> PASS.
    t3 = _fund_one(api, corridor["id"], sender["id"], recipient["id"], 100000)
    funded = validate_success(api.fund_transfer(t3["id"], AGENT), 200)
    assert funded["funding_status"] == "FUNDED", funded["funding_status"]
    after = get_corridor(corridor["id"])
    assert after["reserved_minor"] == 400000, after["reserved_minor"]


def test_rolling_window_third_fund_one_minor_over_cap_rejected(api):
    """PRD §3.4: "require the projected total to be at most the corridor's
    `rolling_window_cap_minor`, else `ERR_ROLLING_WINDOW_LIMIT`."
    PRD §3.4: "Three ceilings are then checked, all with inclusive boundaries (the
    limit value itself passes; one minor unit beyond it fails)."

    Design: Difficulty/boundary_precision_check/rolling_window_cap_inclusive_boundary_on_fund
    """
    corridor = setup_corridor(rolling_window_cap_minor=400000)
    sender = setup_sender(kyc_tier="TIER2")
    recipient = setup_recipient(sender["id"])
    # prior funded = 300000.
    for _ in range(2):
        t = _fund_one(api, corridor["id"], sender["id"], recipient["id"], 150000)
        validate_success(api.fund_transfer(t["id"], AGENT), 200)
    # third fund of 100001 -> projected 400001 == cap + 1 (one minor over) -> rejected.
    t3 = _fund_one(api, corridor["id"], sender["id"], recipient["id"], 100001)
    res = api.fund_transfer(t3["id"], AGENT)
    validate_error(res, "ERR_ROLLING_WINDOW_LIMIT")
    after = get_corridor(corridor["id"])
    assert after["reserved_minor"] == 300000, after["reserved_minor"]


# ─── rolling-window aggregate overlap (resource temporal overlap) ───────────

def test_rolling_window_projected_one_over_cap_rejected(api):
    """PRD §3.4: "require the projected total to be at most the corridor's
    `rolling_window_cap_minor`, else `ERR_ROLLING_WINDOW_LIMIT`."

    Design: Difficulty/resource_temporal_overlap/rolling_window_capacity_overlap_aggregate_on_corridor
    """
    corridor = setup_corridor(rolling_window_cap_minor=400000)
    sender = setup_sender(kyc_tier="TIER2")
    recipient = setup_recipient(sender["id"])
    # prior funded = 300000; a third 150000 -> projected 450000 > 400000 -> rejected.
    for _ in range(2):
        t = _fund_one(api, corridor["id"], sender["id"], recipient["id"], 150000)
        validate_success(api.fund_transfer(t["id"], AGENT), 200)
    t3 = _fund_one(api, corridor["id"], sender["id"], recipient["id"], 150000)
    res = api.fund_transfer(t3["id"], AGENT)
    validate_error(res, "ERR_ROLLING_WINDOW_LIMIT")
    after_t = validate_success(api.get_transfer(t3["id"], AGENT), 200)
    assert after_t["funding_status"] == "UNFUNDED", after_t["funding_status"]
    after_c = get_corridor(corridor["id"])
    assert after_c["reserved_minor"] == 300000, after_c["reserved_minor"]


def test_rolling_window_aggregate_overlap_reserved_unchanged(api):
    """PRD §3.4: "sum `send_principal_minor` across this sender's other funded
    transfers on this corridor whose funding ledger debit was created strictly after
    that window start ... add this transfer's `send_principal_minor`, and require the
    projected total to be at most the corridor's `rolling_window_cap_minor`."

    Design: Difficulty/resource_temporal_overlap/rolling_window_capacity_overlap_aggregate_on_corridor
    """
    corridor = setup_corridor(rolling_window_cap_minor=400000)
    sender = setup_sender(kyc_tier="TIER2")
    recipient = setup_recipient(sender["id"])
    for _ in range(2):
        t = _fund_one(api, corridor["id"], sender["id"], recipient["id"], 150000)
        validate_success(api.fund_transfer(t["id"], AGENT), 200)
    t3 = _fund_one(api, corridor["id"], sender["id"], recipient["id"], 150000)
    validate_error(api.fund_transfer(t3["id"], AGENT), "ERR_ROLLING_WINDOW_LIMIT")
    # The rejected fund leaves the aggregate reservation at the prior 300000.
    after = get_corridor(corridor["id"])
    assert after["reserved_minor"] == 300000, after["reserved_minor"]


# ─── per-transfer limit (corner: calculations) ──────────────────────────────

def test_per_transfer_limit_one_over_max_rejected(api):
    """PRD §3.4: "First, the transfer's `send_principal_minor` must not exceed the
    corridor's `per_transfer_max_minor`, else `ERR_PER_TRANSFER_LIMIT`."

    Design: Corner/calculations/per_transfer_limit_boundary_above_max_rejected
    """
    corridor = setup_corridor(per_transfer_max_minor=500000, rolling_window_cap_minor=5000000)
    sender = setup_sender(kyc_tier="TIER2")
    recipient = setup_recipient(sender["id"])
    # 500001 > per_transfer_max 500000 -> ERR_PER_TRANSFER_LIMIT.
    t = _fund_one(api, corridor["id"], sender["id"], recipient["id"], 500001)
    res = api.fund_transfer(t["id"], AGENT)
    validate_error(res, "ERR_PER_TRANSFER_LIMIT")
    after = validate_success(api.get_transfer(t["id"], AGENT), 200)
    assert after["funding_status"] == "UNFUNDED", after["funding_status"]


# ─── KYC-tier ceiling (corner: calculations) ────────────────────────────────

def test_tier0_ceiling_one_over_50000_rejected(api):
    """PRD §3.4: "Second, `send_principal_minor` must not exceed the sender's
    KYC-tier ceiling, else `ERR_KYC_TIER_LIMIT`; the ceilings are 50000 minor units
    (five hundred of the major unit) for `TIER0`, 300000 (three thousand) for `TIER1`,
    and 1500000 (fifteen thousand) for `TIER2`."

    Design: Corner/calculations/kyc_tier_ceiling_boundary_tier0_rejects_above_50000
    """
    corridor = setup_corridor(per_transfer_max_minor=2000000, rolling_window_cap_minor=5000000)
    sender = setup_sender()  # default TIER0
    recipient = setup_recipient(sender["id"])
    # 50001 > TIER0 ceiling 50000 (still under per_transfer_max) -> ERR_KYC_TIER_LIMIT.
    t = _fund_one(api, corridor["id"], sender["id"], recipient["id"], 50001)
    res = api.fund_transfer(t["id"], AGENT)
    validate_error(res, "ERR_KYC_TIER_LIMIT")
