"""Compensating invariants: add-then-void leaves the entry duty pool and the
export quantity/FOB pool with zero drift."""
from test_helpers import add_claim, add_claim_line, setup_draft_claim_with_line, setup_trade_scenario, TEST_USERS, validate_success

ANALYST = TEST_USERS["analyst_headers"]


def test_void_restores_the_entry_duty_pool_exactly(api):
    """PRD 3.3: "The entry's `drawback_eligible_duty_cents` is then the greater
    of zero or `duty_paid_cents` minus `non_drawbackable_cents`, and its
    `unclaimed_duty_cents` is the eligible duty minus the sum of
    `drawback_amount_cents` over all `ACTIVE` claim lines referencing it."
    PRD 3.4: "Voiding a line — permitted only while the parent claim is in
    `DRAFT`, and otherwise rejected with `ERR_INVALID_STATE` — flips the line to
    its terminal `VOID` status and runs the compensation cascade of §2.9 in
    reverse: the entry's unclaimed duty and matched quantity are restored, the
    shipment's pool and matched quantity are restored, and the claim's estimate
    is recomputed, again with version increments throughout."

    Design: Difficulty/compensating_invariant/entry_duty_pool_conserved_on_void
    """
    ctx = setup_draft_claim_with_line(matched_quantity=40)

    entry_mid = validate_success(api.get_import_entry(ctx["entry"]["id"], ANALYST))
    assert entry_mid["unclaimed_duty_cents"] == 49830
    # Conserved: ACTIVE line amount + unclaimed == eligible.
    assert 32670 + entry_mid["unclaimed_duty_cents"] == 82500
    assert entry_mid["drawback_eligible_duty_cents"] == 82500

    validate_success(
        api.void_claim_line(ctx["claim"]["id"], ctx["line"]["id"], ANALYST)
    )

    entry_after = validate_success(api.get_import_entry(ctx["entry"]["id"], ANALYST))
    assert entry_after["unclaimed_duty_cents"] == 82500, (
        f"compensating void must return the pool to exactly 82500; "
        f"got {entry_after['unclaimed_duty_cents']}"
    )
    assert entry_after["matched_quantity"] == 0
    assert entry_after["status"] == "UNMATCHED"

    line_after = validate_success(api.get_claim_line(ctx["line"]["id"], ANALYST))
    assert line_after["status"] == "VOID"
    claim_after = validate_success(api.get_claim(ctx["claim"]["id"], ANALYST))
    assert claim_after["estimate_cents"] == 0


def test_add_then_void_leaves_zero_drift_across_repeated_cycles(api):
    """PRD 2.9: "Whenever a claim line is voided — whether individually while
    the claim is still a draft, or wholesale because the claim was denied or
    cancelled — the system runs a compensation cascade that restores the matched
    pools: the import entry's consumed quantity and unclaimed-duty figure are
    restored, the export shipment's consumed quantity and remaining value pool
    are restored, and every resource the cascade touches has its `updated_at`
    refreshed and its `version` incremented."

    Design: Difficulty/compensating_invariant/entry_duty_pool_conserved_on_void
    """
    ctx = setup_trade_scenario()
    claim = add_claim(ctx["client"]["id"])

    for _ in range(3):
        line = add_claim_line(
            claim["id"], ctx["entry"]["id"], ctx["export"]["id"], matched_quantity=40
        )
        entry_mid = validate_success(api.get_import_entry(ctx["entry"]["id"], ANALYST))
        assert entry_mid["unclaimed_duty_cents"] == 49830
        validate_success(api.void_claim_line(claim["id"], line["id"], ANALYST))
        entry_after = validate_success(api.get_import_entry(ctx["entry"]["id"], ANALYST))
        assert entry_after["unclaimed_duty_cents"] == 82500, (
            "each forward/compensating pair must leave zero drift"
        )
        assert entry_after["matched_quantity"] == 0
        assert entry_after["status"] == "UNMATCHED"


def test_void_restores_export_quantity_and_fob_pool_exactly(api):
    """PRD 3.3: "Symmetrically, each shipment's `value_pool_remaining_cents` is
    its `fob_value_cents` minus the sum of `drawback_amount_cents` over `ACTIVE`
    lines referencing it."
    PRD 3.4: "Voiding a line — permitted only while the parent claim is in
    `DRAFT`, and otherwise rejected with `ERR_INVALID_STATE` — flips the line to
    its terminal `VOID` status and runs the compensation cascade of §2.9 in
    reverse: the entry's unclaimed duty and matched quantity are restored, the
    shipment's pool and matched quantity are restored, and the claim's estimate
    is recomputed, again with version increments throughout."

    Design: Difficulty/compensating_invariant/export_quantity_conserved_on_void
    """
    ctx = setup_draft_claim_with_line(matched_quantity=60)

    assert ctx["line"]["drawback_amount_cents"] == 49005, (
        "round_half_up(0.99 * 825 * 60) = 49005"
    )
    export_mid = validate_success(api.get_export_shipment(ctx["export"]["id"], ANALYST))
    assert export_mid["matched_quantity"] == 60
    assert export_mid["value_pool_remaining_cents"] == 430995, (
        f"480000 - 49005 = 430995; got {export_mid['value_pool_remaining_cents']}"
    )

    validate_success(
        api.void_claim_line(ctx["claim"]["id"], ctx["line"]["id"], ANALYST)
    )

    export_after = validate_success(api.get_export_shipment(ctx["export"]["id"], ANALYST))
    assert export_after["matched_quantity"] == 0
    assert export_after["value_pool_remaining_cents"] == 480000
    assert export_after["status"] == "UNMATCHED"


def test_export_match_band_tracks_consumption_and_restoration(api):
    """PRD 3.3: "Both resources track a system-maintained `matched_quantity`
    counting units consumed by `ACTIVE` claim lines, and both derive a `status`
    from the same bands: `UNMATCHED` when `matched_quantity` is zero,
    `PARTIALLY_MATCHED` when it is greater than zero but below the total
    quantity, and `MATCHED` once it reaches the entry's `line_quantity` or the
    shipment's `quantity` respectively."
    PRD 3.3: "These status transitions are system-driven side effects of line
    creation and voiding, never direct client operations: a line becoming
    `ACTIVE` with partial consumption moves the target from `UNMATCHED` to
    `PARTIALLY_MATCHED`, full consumption moves it to `MATCHED`, voiding a line
    from `MATCHED` drops it back to `PARTIALLY_MATCHED`, and voiding the last
    referencing line returns it to `UNMATCHED`."

    Design: Difficulty/compensating_invariant/export_quantity_conserved_on_void
    """
    ctx = setup_trade_scenario()
    claim = add_claim(ctx["client"]["id"])

    line = add_claim_line(
        claim["id"], ctx["entry"]["id"], ctx["export"]["id"], matched_quantity=60
    )
    export_mid = validate_success(api.get_export_shipment(ctx["export"]["id"], ANALYST))
    assert export_mid["status"] == "PARTIALLY_MATCHED"
    assert export_mid["matched_quantity"] == 60

    validate_success(api.void_claim_line(claim["id"], line["id"], ANALYST))
    export_after = validate_success(api.get_export_shipment(ctx["export"]["id"], ANALYST))
    assert export_after["status"] == "UNMATCHED"
    assert export_after["matched_quantity"] == 0
    assert export_after["value_pool_remaining_cents"] == 480000
