"""Transfer statements: deliver/accept/reject/redeliver cycle, OCC guard,
supersession, position capacity, and lot restoration.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    validate_error_is_one_of, ApiErrorId, TEST_USERS,
    setup_book, make_lot, make_security,
    make_transfer_statement, deliver_statement, lot_payload_entry,
    get_account_version,
)

TAX_OPS = TEST_USERS["tax_ops_headers"]


def _inbound_book(tin="TIN-TS-1", cusip="999999999"):
    return setup_book(tin=tin, cusip=cusip, ticker="TSX")


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / transfer_statement_reject_redeliver_cycle
# ---------------------------------------------------------------------------

def _inbound_statement(s):
    return make_transfer_statement(
        s["firm"]["id"], s["account"]["id"], s["security"]["id"],
        direction="INBOUND", quantity=10,
        lots_payload=[lot_payload_entry("2024-11-01T00:00:00Z", 10, 10000)],
    )


def test_redeliver_returns_rejected_statement_to_pending(api):
    """PRD §3.7: "A rejected statement is not dead. `TaxOps` can redeliver it,
    moving it back to `PENDING`, where its `lots_payload` may be edited before
    another delivery attempt."

    Design: Difficulty/non_linear_state_machine/transfer_statement_reject_redeliver_cycle
    """
    s = _inbound_book()
    ts = _inbound_statement(s)
    deliver_statement(s["firm"]["id"], s["account"]["id"], ts["id"])
    rejected = validate_success(api.reject_transfer_statement(s["firm"]["id"], ts["id"], TAX_OPS))
    assert rejected["status"] == "REJECTED"
    redelivered = validate_success(api.redeliver_transfer_statement(s["firm"]["id"], ts["id"], TAX_OPS))
    assert redelivered["status"] == "PENDING", "REJECTED -> PENDING closes the cycle"


def test_statement_visits_delivered_twice_then_accepted(api):
    """PRD §3.7: "Acceptance moves a `DELIVERED` statement to `ACCEPTED`. For
    an inbound receipt, acceptance materializes one new tax lot per payload
    entry: each arrives with `acquisition_kind` `TRANSFER_IN`, its
    `original_cost_basis_cents` taken from the payload entry."

    Design: Difficulty/non_linear_state_machine/transfer_statement_reject_redeliver_cycle
    """
    s = _inbound_book()
    ts = _inbound_statement(s)
    deliver_statement(s["firm"]["id"], s["account"]["id"], ts["id"])
    validate_success(api.reject_transfer_statement(s["firm"]["id"], ts["id"], TAX_OPS))
    validate_success(api.redeliver_transfer_statement(s["firm"]["id"], ts["id"], TAX_OPS))
    second = deliver_statement(s["firm"]["id"], s["account"]["id"], ts["id"])
    assert second["status"] == "DELIVERED", "statement visits DELIVERED twice (cyclic machine)"
    accepted = validate_success(api.accept_transfer_statement(s["firm"]["id"], ts["id"], TAX_OPS))
    assert accepted["status"] == "ACCEPTED"
    lots, _meta = validate_paginated(api.list_tax_lots(s["firm"]["id"], s["account"]["id"], TAX_OPS))
    assert len(lots) == 1
    assert lots[0]["acquisition_kind"] == "TRANSFER_IN"
    assert lots[0]["original_cost_basis_cents"] == 10000


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / outbound_transfer_aggregate_capacity_overlap
# ---------------------------------------------------------------------------

def _capacity_scenario():
    """One lot of 100 sh; TS1 (60 sh) delivered; TS2 (50 sh) pending."""
    s = setup_book(tin="TIN-OV-2", cusip="111111123", ticker="CAP")
    make_lot(s["firm"]["id"], s["account"]["id"], s["security"]["id"], quantity=100, basis=100000)
    ts1 = make_transfer_statement(
        s["firm"]["id"], s["account"]["id"], s["security"]["id"],
        direction="OUTBOUND", quantity=60, counterparty="Broker X",
        lots_payload=[lot_payload_entry("2025-01-05T00:00:00Z", 60, 60000)],
    )
    ts2 = make_transfer_statement(
        s["firm"]["id"], s["account"]["id"], s["security"]["id"],
        direction="OUTBOUND", quantity=50, counterparty="Broker Y", transfer_date="2025-04-02T00:00:00Z",
        lots_payload=[lot_payload_entry("2025-01-05T00:00:00Z", 50, 50000)],
    )
    deliver_statement(s["firm"]["id"], s["account"]["id"], ts1["id"])
    return s, ts1, ts2


def test_second_delivery_exceeding_remaining_position_rejected(api):
    """PRD §3.7: "for an outbound statement the source account must hold at
    least the statement's `quantity` across its open and partially disposed
    lots on that security, or the delivery fails with
    `ERR_TRANSFER_INSUFFICIENT_POSITION` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/outbound_transfer_aggregate_capacity_overlap
    """
    s, _ts1, ts2 = _capacity_scenario()
    version = get_account_version(s["firm"]["id"], s["account"]["id"])
    resp = api.deliver_transfer_statement(s["firm"]["id"], ts2["id"], {"expected_account_version": version}, TAX_OPS)
    validate_error(resp, ApiErrorId.ERR_TRANSFER_INSUFFICIENT_POSITION)


def test_rejected_second_delivery_stays_pending(api):
    """PRD §3.7: "for an outbound statement the source account must hold at
    least the statement's `quantity` across its open and partially disposed
    lots on that security, or the delivery fails with
    `ERR_TRANSFER_INSUFFICIENT_POSITION` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/outbound_transfer_aggregate_capacity_overlap
    """
    s, _ts1, ts2 = _capacity_scenario()
    version = get_account_version(s["firm"]["id"], s["account"]["id"])
    validate_error(
        api.deliver_transfer_statement(s["firm"]["id"], ts2["id"], {"expected_account_version": version}, TAX_OPS),
        ApiErrorId.ERR_TRANSFER_INSUFFICIENT_POSITION,
    )
    ts2_after = validate_success(api.get_transfer_statement(s["firm"]["id"], ts2["id"], TAX_OPS))
    assert ts2_after["status"] == "PENDING", "failed delivery leaves the statement unchanged"


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / outbound_transfer_deliver_reject_position_restored
# ---------------------------------------------------------------------------

def _outbound_60_of_100():
    s = setup_book(tin="TIN-INV-3", cusip="111111126", ticker="POS")
    lot = make_lot(s["firm"]["id"], s["account"]["id"], s["security"]["id"], quantity=100, basis=100000)
    ts = make_transfer_statement(
        s["firm"]["id"], s["account"]["id"], s["security"]["id"],
        direction="OUTBOUND", quantity=60, counterparty="Broker X",
        lots_payload=[lot_payload_entry("2025-01-05T00:00:00Z", 60, 60000)],
    )
    return s, lot, ts


def test_outbound_deliver_consumes_source_lots(api):
    """PRD §3.7: "Delivering an outbound statement consumes the source lots in
    the order dictated by the account's `default_disposal_method`, flipping
    them to `PARTIALLY_DISPOSED` or `FULLY_DISPOSED` as shares run out."

    Design: Difficulty/compensating_invariant/outbound_transfer_deliver_reject_position_restored
    """
    s, lot, ts = _outbound_60_of_100()
    deliver_statement(s["firm"]["id"], s["account"]["id"], ts["id"])
    lot_after = validate_success(api.get_tax_lot(s["firm"]["id"], lot["id"], TAX_OPS))
    assert lot_after["quantity_remaining"] == 40, "forward action consumed 60 of 100"
    assert lot_after["lot_status"] == "PARTIALLY_DISPOSED"


def test_outbound_reject_restores_position_exactly(api):
    """PRD §3.7: "Rejection instead moves a delivered statement to `REJECTED`:
    for an outbound delivery the consumed source lots are restored —
    `quantity_remaining` and `lot_status` roll back."

    Design: Difficulty/compensating_invariant/outbound_transfer_deliver_reject_position_restored
    """
    s, lot, ts = _outbound_60_of_100()
    deliver_statement(s["firm"]["id"], s["account"]["id"], ts["id"])
    validate_success(api.reject_transfer_statement(s["firm"]["id"], ts["id"], TAX_OPS))
    lot_after = validate_success(api.get_tax_lot(s["firm"]["id"], lot["id"], TAX_OPS))
    assert lot_after["quantity_remaining"] == 100, "compensating action restored the full position"
    assert lot_after["adjusted_cost_basis_cents"] == 100000, "basis restored exactly — no drift"
    assert lot_after["lot_status"] == "OPEN", "rolled back from PARTIALLY_DISPOSED"


# ---------------------------------------------------------------------------
# Corner: state_machines / inbound_accept_materializes_transfer_in_lots
# ---------------------------------------------------------------------------

def test_inbound_accept_materializes_transfer_in_lots(api):
    """PRD §3.7: "For an inbound receipt, acceptance materializes one new tax
    lot per payload entry: each arrives with `acquisition_kind` `TRANSFER_IN`,
    its `original_cost_basis_cents` taken from the payload entry, its
    `adjusted_cost_basis_cents` initialized to that same value, and its
    `holding_period_start` set to the entry's `acquisition_date`."

    Design: Corner/state_machines/inbound_accept_materializes_transfer_in_lots
    """
    s = _inbound_book(tin="TIN-SM-14", cusip="272727272")
    ts = make_transfer_statement(
        s["firm"]["id"], s["account"]["id"], s["security"]["id"],
        direction="INBOUND", quantity=30, counterparty="Old Broker",
        lots_payload=[
            lot_payload_entry("2024-01-05T00:00:00Z", 20, 20000),
            lot_payload_entry("2024-06-05T00:00:00Z", 10, 12000),
        ],
    )
    deliver_statement(s["firm"]["id"], s["account"]["id"], ts["id"])
    accepted = validate_success(api.accept_transfer_statement(s["firm"]["id"], ts["id"], TAX_OPS))
    assert accepted["status"] == "ACCEPTED"
    lots, _meta = validate_paginated(api.list_tax_lots(s["firm"]["id"], s["account"]["id"], TAX_OPS))
    assert len(lots) == 2, "one lot per lots_payload entry"
    assert all(l["acquisition_kind"] == "TRANSFER_IN" for l in lots)
    detail = sorted((l["quantity"], l["original_cost_basis_cents"], l["adjusted_cost_basis_cents"]) for l in lots)
    assert detail == [(10, 12000, 12000), (20, 20000, 20000)]


# ---------------------------------------------------------------------------
# Corner: state_machines / redeliver after supersession
# ---------------------------------------------------------------------------

def test_redeliver_after_replacement_delivered_rejected(api):
    """PRD §3.7: "A rejected statement is not dead. `TaxOps` can redeliver it,
    moving it back to `PENDING`, where its `lots_payload` may be edited before
    another delivery attempt — unless a replacement statement referencing it
    has already reached `DELIVERED`, in which case redelivery fails with
    `ERR_TRANSFER_ALREADY_SUPERSEDED` (HTTP 409)."

    Design: Corner/state_machines/transfer_statement_redeliver_after_replacement_superseded_rejected
    """
    s = setup_book(tin="TIN-SM-11", cusip="242424242", ticker="SMB")
    make_lot(s["firm"]["id"], s["account"]["id"], s["security"]["id"], quantity=100, basis=100000)
    ts1 = make_transfer_statement(
        s["firm"]["id"], s["account"]["id"], s["security"]["id"],
        direction="OUTBOUND", quantity=60, counterparty="Broker X",
        lots_payload=[lot_payload_entry("2025-01-05T00:00:00Z", 60, 60000)],
    )
    deliver_statement(s["firm"]["id"], s["account"]["id"], ts1["id"])
    # Replacement is registered while TS1 is still DELIVERED (creation gate).
    ts2 = make_transfer_statement(
        s["firm"]["id"], s["account"]["id"], s["security"]["id"],
        direction="OUTBOUND", quantity=60, counterparty="Broker X",
        lots_payload=[lot_payload_entry("2025-01-05T00:00:00Z", 60, 60000)],
        replaces_statement_id=ts1["id"],
    )
    validate_success(api.reject_transfer_statement(s["firm"]["id"], ts1["id"], TAX_OPS))
    deliver_statement(s["firm"]["id"], s["account"]["id"], ts2["id"])
    resp = api.redeliver_transfer_statement(s["firm"]["id"], ts1["id"], TAX_OPS)
    # The supersession guard fires whether the earlier statement is read as
    # still REJECTED (ERR_TRANSFER_ALREADY_SUPERSEDED) or as having flipped to
    # SUPERSEDED when the replacement delivered (state-check rejection).
    validate_error_is_one_of(resp, [ApiErrorId.ERR_TRANSFER_ALREADY_SUPERSEDED, ApiErrorId.ERR_INVALID_STATE_TRANSITION])


# ---------------------------------------------------------------------------
# Corner: validations / missing lot detail, supersede target not delivered
# ---------------------------------------------------------------------------

def test_transfer_deliver_missing_lot_detail_rejected(api):
    """PRD §3.7: "The payload must be non-empty, or the delivery fails with
    `ERR_TRANSFER_MISSING_LOT_DETAIL` (HTTP 422)."

    Design: Corner/validations/transfer_deliver_missing_lot_detail_rejected
    """
    s = _inbound_book(tin="TIN-V-7", cusip="505050505")
    ts = make_transfer_statement(
        s["firm"]["id"], s["account"]["id"], s["security"]["id"],
        direction="INBOUND", quantity=10, counterparty="Old Broker",
    )
    version = get_account_version(s["firm"]["id"], s["account"]["id"])
    resp = api.deliver_transfer_statement(s["firm"]["id"], ts["id"], {"expected_account_version": version}, TAX_OPS)
    validate_error(resp, ApiErrorId.ERR_TRANSFER_MISSING_LOT_DETAIL)


def test_transfer_supersede_target_not_delivered_rejected(api):
    """PRD §3.7: "A statement may also carry `replaces_statement_id`, naming an
    earlier statement it supersedes; the referenced statement must exist and
    currently be `DELIVERED`, or creation fails with
    `ERR_SUPERSEDE_TARGET_INVALID` (HTTP 422)."

    Design: Corner/validations/transfer_supersede_target_not_delivered_rejected
    """
    s = _inbound_book(tin="TIN-V-8", cusip="515151515")
    ts1 = make_transfer_statement(
        s["firm"]["id"], s["account"]["id"], s["security"]["id"],
        direction="OUTBOUND", quantity=10, counterparty="Broker X",
        lots_payload=[lot_payload_entry("2025-01-05T00:00:00Z", 10, 10000)],
    )
    payload = {
        "direction": "OUTBOUND", "counterparty_firm_name": "Broker X",
        "security_id": s["security"]["id"], "quantity": 10,
        "transfer_date": "2025-04-02T00:00:00Z",
        "lots_payload": [lot_payload_entry("2025-01-05T00:00:00Z", 10, 10000)],
        "replaces_statement_id": ts1["id"],
    }
    resp = api.create_transfer_statement(s["firm"]["id"], s["account"]["id"], payload, TAX_OPS)
    validate_error(resp, ApiErrorId.ERR_SUPERSEDE_TARGET_INVALID)


# ---------------------------------------------------------------------------
# Corner: errors / error_stale_account_version_triggered
# ---------------------------------------------------------------------------

def test_transfer_deliver_stale_account_version_rejected(api):
    """PRD §2.8: "Delivering a transfer statement —
    `POST /firms/{firmId}/transfer_statements/{stmtId}/deliver` — requires
    `expected_account_version`, matched against the current `version` of the
    account whose lots the delivery will consume. A mismatch is rejected with
    `ERR_STALE_ACCOUNT_VERSION` (HTTP 412)."
    PRD §2.4: "`version` (integer): a mutation counter that increments by one
    on every change to the resource, cascades included."

    Design: Corner/errors/error_stale_account_version_triggered
    """
    s = setup_book(tin="TIN-ER-1", cusip="595959595", ticker="STV")
    make_lot(s["firm"]["id"], s["account"]["id"], s["security"]["id"], quantity=100, basis=100000)
    ts = make_transfer_statement(
        s["firm"]["id"], s["account"]["id"], s["security"]["id"],
        direction="OUTBOUND", quantity=10, counterparty="Broker X",
        lots_payload=[lot_payload_entry("2025-01-05T00:00:00Z", 10, 10000)],
    )
    stale_version = s["account"]["version"]
    # Mutate the account twice (restrict then reopen) so its version advances.
    validate_success(api.restrict_account(s["firm"]["id"], s["account"]["id"], TAX_OPS))
    validate_success(api.reopen_account(s["firm"]["id"], s["account"]["id"], TAX_OPS))
    resp = api.deliver_transfer_statement(
        s["firm"]["id"], ts["id"], {"expected_account_version": stale_version}, TAX_OPS
    )
    validate_error(resp, ApiErrorId.ERR_STALE_ACCOUNT_VERSION)
