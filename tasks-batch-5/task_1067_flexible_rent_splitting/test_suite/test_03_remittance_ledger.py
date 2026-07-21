"""Remittance, reversal, ledger visibility, and cycle rescheduling (OCC + conservation)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_enrolled_renter, create_scheduled_cycle, create_remitted_cycle,
    get_installments, find_ledger_entry,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / remit_requires_property_active
# ---------------------------------------------------------------------------

def test_remit_pending_property_rejected(api):
    """PRD §3.5: "Remittance requires that the cycle's property be integrated: the
    property's `integration_status` must be `ACTIVE`, otherwise the request is rejected
    with `ERR_PROPERTY_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/remit_requires_property_active
    """
    enrolled = create_enrolled_renter(api, unit_label="Maple #14", integration_status="PENDING")
    ctx = create_scheduled_cycle(api, enrolled=enrolled)
    resp = api.remit_cycle(ctx["cycle"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_ACTIVE.value, 409)


def test_remit_suspended_property_rejected(api):
    """PRD §3.5: "Remittance requires that the cycle's property be integrated: the
    property's `integration_status` must be `ACTIVE`, otherwise the request is rejected
    with `ERR_PROPERTY_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/remit_requires_property_active
    """
    enrolled = create_enrolled_renter(api, unit_label="Maple #14b", integration_status="ACTIVE")
    ctx = create_scheduled_cycle(api, enrolled=enrolled)
    validate_success(api.set_property_integration(
        enrolled["property"]["id"], {"integration_status": "SUSPENDED"}, ADMIN))
    resp = api.remit_cycle(ctx["cycle"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_ACTIVE.value, 409)


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / remit_reverse_net_remitted_zero
# ---------------------------------------------------------------------------

def test_reverse_restores_net_remitted_zero(api):
    """PRD §2.7: "once a remittance is reversed, the compensating reversal restores
    `net_remitted_cents` to 0."
    PRD §3.5: "A `PlatformAdmin` reverses a `SENT` remittance — moving it `SENT → REVERSED`
    and the cycle `REMITTED → SCHEDULED`".

    Design: Difficulty/compensating_invariant/remit_reverse_net_remitted_zero
    """
    ctx = create_remitted_cycle(api, mode="SPLIT", split_count=2, unit_label="Maple #17")
    validate_success(api.reverse_remittance(ctx["remittance"]["id"], ADMIN))
    cycle = validate_success(api.get_billing_cycle(ctx["cycle"]["id"], ADMIN))
    assert cycle["net_remitted_cents"] == 0
    assert cycle["status"] == "SCHEDULED"


def test_reverse_marks_remittance_reversed(api):
    """PRD §3.5: "A `PlatformAdmin` reverses a `SENT` remittance — moving it
    `SENT → REVERSED` and the cycle `REMITTED → SCHEDULED` — but only when the cycle is
    still `REMITTED` and its `repaid_amount_cents` is exactly 0."

    Design: Difficulty/compensating_invariant/remit_reverse_net_remitted_zero
    """
    ctx = create_remitted_cycle(api, mode="SPLIT", split_count=2, unit_label="Maple #17b")
    data = validate_success(api.reverse_remittance(ctx["remittance"]["id"], ADMIN))
    assert data["status"] == "REVERSED"


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / reschedule_pair_scheduled_obligation_conserved
# ---------------------------------------------------------------------------

def test_reschedule_roundtrip_conserves_obligation(api):
    """PRD §3.4: "Rescheduling cancels the prior `SCHEDULED` installments and mints a fresh
    set by the same allocation rules, keeping the sum of non-`CANCELLED` installment amounts
    equal to `portion_cents`, and increments the cycle's `version` by one."

    Design: Difficulty/compensating_invariant/reschedule_pair_scheduled_obligation_conserved
    """
    ctx = create_scheduled_cycle(api, mode="SPLIT", split_count=2, unit_label="Maple #18")
    cyc_id = ctx["cycle"]["id"]
    v1 = ctx["cycle"]["version"]
    v2 = validate_success(api.reschedule_cycle(
        cyc_id, {"expected_cycle_version": v1, "mode": "SPLIT", "split_count": 4}, ADMIN))["version"]
    validate_success(api.reschedule_cycle(
        cyc_id, {"expected_cycle_version": v2, "mode": "SPLIT", "split_count": 2}, ADMIN))
    insts = get_installments(cyc_id, api)
    live = sum(i["amount_cents"] for i in insts if i["status"] != "CANCELLED")
    cycle = validate_success(api.get_billing_cycle(cyc_id, ADMIN))
    assert live == 100000
    assert cycle["portion_cents"] == 100000


def test_reschedule_roundtrip_bumps_version(api):
    """PRD §2.8: "On a successful reschedule the cycle's `version` increments by one."

    Design: Difficulty/compensating_invariant/reschedule_pair_scheduled_obligation_conserved
    """
    ctx = create_scheduled_cycle(api, mode="SPLIT", split_count=2, unit_label="Maple #18b")
    cyc_id = ctx["cycle"]["id"]
    v1 = ctx["cycle"]["version"]
    v2 = validate_success(api.reschedule_cycle(
        cyc_id, {"expected_cycle_version": v1, "mode": "SPLIT", "split_count": 4}, ADMIN))["version"]
    v3 = validate_success(api.reschedule_cycle(
        cyc_id, {"expected_cycle_version": v2, "mode": "SPLIT", "split_count": 2}, ADMIN))["version"]
    assert v3 == 3


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / installment_gap_buffer_reschedule
# ---------------------------------------------------------------------------

def test_reschedule_gap_too_short_rejected(api):
    """PRD §3.4: "When custom offsets are given, consecutive installment due dates must be
    at least 5 days apart; offsets closer than that are rejected with
    `ERR_INSTALLMENT_GAP_TOO_SHORT` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/installment_gap_buffer_reschedule
    """
    ctx = create_scheduled_cycle(api, mode="SPLIT", split_count=2, unit_label="Maple #16")
    v1 = ctx["cycle"]["version"]
    resp = api.reschedule_cycle(ctx["cycle"]["id"], {
        "expected_cycle_version": v1, "mode": "SPLIT", "split_count": 2,
        "due_offsets_days": [0, 3]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INSTALLMENT_GAP_TOO_SHORT.value, 422)


def test_reschedule_gap_exactly_min_allowed(api):
    """PRD §3.4: "When custom offsets are given, consecutive installment due dates must be
    at least 5 days apart; offsets closer than that are rejected with
    `ERR_INSTALLMENT_GAP_TOO_SHORT` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/installment_gap_buffer_reschedule
    """
    ctx = create_scheduled_cycle(api, mode="SPLIT", split_count=2, unit_label="Maple #16b")
    v1 = ctx["cycle"]["version"]
    resp = api.reschedule_cycle(ctx["cycle"]["id"], {
        "expected_cycle_version": v1, "mode": "SPLIT", "split_count": 2,
        "due_offsets_days": [0, 5]}, ADMIN)
    data = validate_success(resp, 200)
    assert data["version"] == v1 + 1


# ---------------------------------------------------------------------------
# Corner: cross_cutting / reschedule_stale_cycle_version_returns_412
# ---------------------------------------------------------------------------

def test_reschedule_stale_version_returns_412(api):
    """PRD §2.8: "If that value does not match the cycle's current `version` — because
    another writer has advanced the cycle since the client read it — the request is rejected
    with `ERR_STALE_CYCLE_VERSION` (HTTP 412), preventing the client from superseding a
    layout it has not seen."

    Design: Corner/cross_cutting/reschedule_stale_cycle_version_returns_412
    """
    ctx = create_scheduled_cycle(api, mode="SPLIT", split_count=2, unit_label="Oak #15")
    cyc_id = ctx["cycle"]["id"]
    v1 = ctx["cycle"]["version"]
    validate_success(api.reschedule_cycle(
        cyc_id, {"expected_cycle_version": v1, "mode": "SPLIT", "split_count": 3}, ADMIN))
    resp = api.reschedule_cycle(
        cyc_id, {"expected_cycle_version": v1, "mode": "SPLIT", "split_count": 4}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_CYCLE_VERSION.value, 412)


# ---------------------------------------------------------------------------
# Corner: consistency_model / remit_ledger_visible_same_request_immediate
# ---------------------------------------------------------------------------

def test_remit_ledger_visible_immediately(api):
    """PRD §3.5: "It appends a `REMITTANCE_ADVANCE` ledger entry of the full rent amount
    and a `FEE` ledger entry of the provisional flex fee, and recomputes `net_remitted_cents`
    to equal the full rent."

    Design: Corner/consistency_model/remit_ledger_visible_same_request_immediate
    """
    ctx = create_remitted_cycle(api, mode="SPLIT", split_count=2, unit_label="Oak #19")
    ledger = validate_success(api.list_cycle_ledger(ctx["cycle"]["id"], ADMIN))
    assert find_ledger_entry(ledger, "REMITTANCE_ADVANCE", 120000) is not None
    # LOW band membership 1500 + split (2-1)*500 = 2000
    assert find_ledger_entry(ledger, "FEE", 2000) is not None
    assert ctx["cycle"]["net_remitted_cents"] == 120000
