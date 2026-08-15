"""Disposal posting: pinned evaluation order, dual-basis gain/loss, component
cascade, compliance gate, and the mid-month cutoff."""
from test_helpers import (
    ACCT,
    CTRL,
    ApiErrorId,
    book_entries,
    count_asset,
    create_and_post_disposal,
    create_and_post_run,
    create_approved_disposal,
    create_class,
    create_in_service_asset,
    create_inventory_run,
    entries_for_disposal,
    refresh_asset,
    setup_asset_with_posted_runs,
    tax_entries,
    validate_error,
    validate_paginated,
    validate_success,
)


def _sale_setup(api, tag="A-200"):
    """VEH class asset, 600000 cost, in service 2026-01-05, runs 2026-01/02
    posted; APPROVED SALE at 500000 effective 2026-03-20. Returns (asset, disp)."""
    cls = create_class(class_code="VEH", name="Vehicles", tax_method="MACRS_7YR")
    asset, _runs = setup_asset_with_posted_runs(
        ["2026-01", "2026-02"], asset_class_id=cls["id"], asset_tag=tag,
        description="Truck", acquisition_cost_cents=600000,
        in_service_date="2026-01-05",
    )
    disposal = create_approved_disposal(
        asset["id"], disposal_type="SALE", proceeds_cents=500000,
        effective_date="2026-03-20",
    )
    return asset, disposal


def test_sale_book_gain_loss_net_of_book_basis(api):
    """PRD §3.5: "**Step one — final-period depreciation:** if the asset is
    `IN_SERVICE` and the day-of-month of the `effective_date` is 15 or later, the
    effective period's `BOOK` and `TAX` entries are created with `source` equal
    to `DISPOSAL_FINAL`, the disposal's id recorded as their `disposal_id` (and
    `run_id` null), computed exactly per the §3.3 methods and applied to
    `accumulated_book_cents` and `accumulated_tax_cents`."
    PRD §3.5: "**Step two — book gain/loss:** `book_gain_loss_cents` is
    `proceeds_cents` minus the net book carrying amount, that is, minus
    (`acquisition_cost_cents` − `accumulated_book_cents` −
    `impairment_total_cents`)."

    Design: Difficulty/dual_variant_calc/book_vs_tax_disposal_gain_loss_divergence
    """
    asset, disposal = _sale_setup(api)
    posted = validate_success(api.post_disposal(disposal["id"], ACCT), 200)

    # Day 20 >= 15: March final BOOK entry of 10000 applied first.
    # book gain/loss = 500000 - (600000 - 30000 - 0) = -70000.
    assert posted["book_gain_loss_cents"] == -70000
    after = refresh_asset(asset["id"])
    assert after["accumulated_book_cents"] == 30000
    assert after["status"] == "DISPOSED"


def test_sale_tax_gain_loss_net_of_tax_basis(api):
    """PRD §3.5: "**Step three — tax gain/loss:** `tax_gain_loss_cents` is
    `proceeds_cents` minus the tax basis (`acquisition_cost_cents` −
    `accumulated_tax_cents`); impairment is ignored on the tax side, so the same
    disposal routinely produces two different gain/loss figures."
    PRD §3.5: "if the asset is `IN_SERVICE` and the day-of-month of the
    `effective_date` is 15 or later, the effective period's `BOOK` and `TAX`
    entries are created with `source` equal to `DISPOSAL_FINAL`"

    Design: Difficulty/dual_variant_calc/book_vs_tax_disposal_gain_loss_divergence
    """
    asset, disposal = _sale_setup(api)
    posted = validate_success(api.post_disposal(disposal["id"], ACCT), 200)

    # MACRS-7 year 1: 600000*0.1429 = 85740 annual, 7145/month; Jan+Feb+Mar final.
    assert posted["tax_gain_loss_cents"] == -78565, (
        "500000 - (600000 - 21435); impairment excluded from the tax basis"
    )
    after = refresh_asset(asset["id"])
    assert after["accumulated_tax_cents"] == 21435

    finals = entries_for_disposal(disposal["id"])
    assert len(finals) == 2
    by_ledger = {e["ledger"]: e for e in finals}
    assert by_ledger["BOOK"]["amount_cents"] == 10000
    assert by_ledger["TAX"]["amount_cents"] == 7145
    for entry in finals:
        assert entry["source"] == "DISPOSAL_FINAL"
        assert entry["disposal_id"] == disposal["id"]
        assert entry["period"] == "2026-03"
        assert entry["run_id"] is None


def test_parent_sale_posts_with_book_gain(api):
    """PRD §3.5: "**Step two — book gain/loss:** `book_gain_loss_cents` is
    `proceeds_cents` minus the net book carrying amount, that is, minus
    (`acquisition_cost_cents` − `accumulated_book_cents` −
    `impairment_total_cents`)."
    PRD §3.5: "The asset then transitions from `IN_SERVICE` or
    `FULLY_DEPRECIATED` to the terminal status `DISPOSED`."

    Design: Difficulty/transitive_cascade/disposal_post_component_cascade
    """
    cls = create_class()
    parent, component, disposal = _component_setup(api, cls)
    posted = validate_success(api.post_disposal(disposal["id"], ACCT), 200)

    # March final BOOK entry of 10000 applied: 700000 - (600000 - 30000) = 130000.
    assert posted["status"] == "POSTED"
    assert posted["book_gain_loss_cents"] == 130000
    assert refresh_asset(parent["id"])["status"] == "DISPOSED"
    assert refresh_asset(component["id"])["status"] == "DISPOSED"


def test_component_companion_scrap_disposal_cascade(api):
    """PRD §3.5: "When a primary asset is disposed by sale or scrap, every child
    asset whose `parent_asset_id` points at it and whose status is `IN_SERVICE`
    or `FULLY_DEPRECIATED` is itself disposed automatically: the system spawns a
    companion `SCRAP` disposal with zero proceeds, `auto_created` set to true,
    and immediate posting, each component computing its own final entries and its
    own book and tax gain/loss exactly as above."

    Design: Difficulty/transitive_cascade/disposal_post_component_cascade
    """
    cls = create_class()
    parent, component, disposal = _component_setup(api, cls)
    validate_success(api.post_disposal(disposal["id"], ACCT), 200)

    companions, meta = validate_paginated(
        api.list_disposals(CTRL, params={"asset_id": component["id"]})
    )
    assert meta["total_count"] == 1, "exactly one companion disposal"
    companion = companions[0]
    assert companion["disposal_type"] == "SCRAP"
    assert companion["auto_created"] is True
    assert companion["proceeds_cents"] == 0
    assert companion["status"] == "POSTED"
    # Feb run entry 12500 + March DISPOSAL_FINAL entry 12500.
    assert companion["book_gain_loss_cents"] == -275000, "0 - (300000 - 25000)"

    comp_after = refresh_asset(component["id"])
    assert comp_after["status"] == "DISPOSED"
    assert comp_after["accumulated_book_cents"] == 25000


def _component_setup(api, cls):
    """Parent 600000 SL/60 in service 2026-01-10 + run 2026-01; component 300000
    life 24 in service 2026-02-01 + run 2026-02; APPROVED SALE of the parent at
    700000 effective 2026-03-20."""
    parent = create_in_service_asset(
        cls["id"], asset_tag="A-500", description="Parent machine",
        acquisition_cost_cents=600000,
    )
    create_and_post_run("2026-01")
    component = create_in_service_asset(
        cls["id"], in_service_date="2026-02-01", asset_tag="A-500-C",
        description="Spindle overhaul", acquisition_cost_cents=300000,
        useful_life_months=24, parent_asset_id=parent["id"],
    )
    assert component["source"] == "COMPONENT_ADDITION"
    create_and_post_run("2026-02")
    disposal = create_approved_disposal(
        parent["id"], disposal_type="SALE", proceeds_cents=700000,
        effective_date="2026-03-20",
    )
    return parent, component, disposal


def _inventory_gate_setup(api):
    """In-service asset with a MISSING count (open inventory exception) and an
    APPROVED SALE whose effective period has since been closed by a posted run."""
    cls = create_class()
    asset, _runs = setup_asset_with_posted_runs(
        ["2026-01"], asset_class_id=cls["id"], asset_tag="A-600",
        description="Forklift", acquisition_cost_cents=600000,
    )
    inv = create_inventory_run(name="Q1 count", scope_type="ALL")
    line = count_asset(inv["id"], asset["id"], found=False)
    assert line["reconciliation_status"] == "MISSING"
    disposal = create_approved_disposal(
        asset["id"], disposal_type="SALE", proceeds_cents=100000,
        effective_date="2026-02-20",
    )
    create_and_post_run("2026-02")  # closes the disposal's effective period
    return asset, disposal


def test_inventory_exception_gate_reports_before_period_closed(api):
    """PRD §2.10: "When multiple validation rules could reject the same request,
    the server evaluates them in a fixed priority order so the returned error is
    deterministic."
    PRD §2.10: "**(5) compliance gate** — the open-inventory-exception gate on
    disposal posting (`ERR_ASSET_UNDER_INVENTORY_REVIEW`)"
    PRD §2.10: "**(7) temporal period rules** (`ERR_PERIOD_GAP`,
    `ERR_PERIOD_CLOSED`)"
    PRD §3.5: "for `SALE` and `TRANSFER`, the asset's `open_inventory_exception`
    flag must be false — an asset with an unresolved inventory exception may not
    leave the books or change hands, and the post is rejected with
    `ERR_ASSET_UNDER_INVENTORY_REVIEW` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/disposal_post_safety_error_beats_temporal_error
    """
    asset, disposal = _inventory_gate_setup(api)
    # Both the compliance gate (priority 5) and the closed-period rule
    # (priority 7) fail; the compliance gate must be reported.
    resp = api.post_disposal(disposal["id"], ACCT)
    validate_error(resp, ApiErrorId.ERR_ASSET_UNDER_INVENTORY_REVIEW, 409)


def test_blocked_post_leaves_disposal_approved_and_asset_in_service(api):
    """PRD §3.5: "the post is rejected with `ERR_ASSET_UNDER_INVENTORY_REVIEW`
    (HTTP 409)"
    PRD §3.5: "Posting is where the ledger moves, and it is restricted to
    `APPROVED` disposals (`ERR_INVALID_STATE` otherwise)."

    Design: Difficulty/priority_pair_validation_conflict/disposal_post_safety_error_beats_temporal_error
    """
    asset, disposal = _inventory_gate_setup(api)
    resp = api.post_disposal(disposal["id"], ACCT)
    validate_error(resp, ApiErrorId.ERR_ASSET_UNDER_INVENTORY_REVIEW, 409)

    d_after = validate_success(api.get_disposal(disposal["id"], ACCT), 200)
    assert d_after["status"] == "APPROVED"
    a_after = refresh_asset(asset["id"])
    assert a_after["status"] == "IN_SERVICE"


def test_accumulated_matches_entry_sums_on_both_ledgers(api):
    """PRD §3.2: "`accumulated_book_cents` is the sum of `amount_cents` over the
    asset's `BOOK` depreciation entries; `accumulated_tax_cents` is the same over
    its `TAX` entries"
    PRD §3.3: "Each created entry adds its `amount_cents` to the asset's
    `accumulated_book_cents` or `accumulated_tax_cents` (never negative amounts)
    and increments the asset's `version`."

    Design: Difficulty/compensating_invariant/depreciation_accumulated_equals_entry_sum
    """
    cls = create_class()
    asset, disposal = _fully_depreciated_scrap_setup(api, cls)

    book_sum = sum(e["amount_cents"] for e in book_entries(asset["id"]))
    tax_sum = sum(e["amount_cents"] for e in tax_entries(asset["id"]))
    after = refresh_asset(asset["id"])
    assert book_sum == 24000, "12000 + 12000"
    assert tax_sum == 800, "400 + 400 (24000*0.20/12 per month)"
    assert after["accumulated_book_cents"] == book_sum
    assert after["accumulated_tax_cents"] == tax_sum
    assert disposal["status"] == "POSTED"


def test_scrap_of_fully_depreciated_asset_posts_no_final_entries(api):
    """PRD §3.5: "**Step one — final-period depreciation:** if the asset is
    `IN_SERVICE` and the day-of-month of the `effective_date` is 15 or later, the
    effective period's `BOOK` and `TAX` entries are created with `source` equal
    to `DISPOSAL_FINAL`"
    PRD §3.5: "**Step two — book gain/loss:** `book_gain_loss_cents` is
    `proceeds_cents` minus the net book carrying amount, that is, minus
    (`acquisition_cost_cents` − `accumulated_book_cents` −
    `impairment_total_cents`)."
    PRD §3.5: "**Step three — tax gain/loss:** `tax_gain_loss_cents` is
    `proceeds_cents` minus the tax basis (`acquisition_cost_cents` −
    `accumulated_tax_cents`)"

    Design: Difficulty/compensating_invariant/depreciation_accumulated_equals_entry_sum
    """
    cls = create_class()
    asset, disposal = _fully_depreciated_scrap_setup(api, cls)

    # The asset was FULLY_DEPRECIATED, so the final-entry step is skipped even
    # though day 20 >= 15.
    assert entries_for_disposal(disposal["id"]) == []
    assert disposal["book_gain_loss_cents"] == 0, "0 - (24000 - 24000 - 0)"
    assert disposal["tax_gain_loss_cents"] == -23200, "0 - (24000 - 800)"


def _fully_depreciated_scrap_setup(api, cls):
    """24000-cost, 2-month-life asset driven to FULLY_DEPRECIATED by the 2026-01
    and 2026-02 runs, then SCRAP-posted effective 2026-03-20."""
    asset, _runs = setup_asset_with_posted_runs(
        ["2026-01", "2026-02"], asset_class_id=cls["id"], asset_tag="A-980",
        description="Short-lived tool", acquisition_cost_cents=24000,
        useful_life_months=2,
    )
    assert asset["status"] == "FULLY_DEPRECIATED"
    disposal = create_and_post_disposal(
        asset["id"], disposal_type="SCRAP", proceeds_cents=0,
        effective_date="2026-03-20",
    )
    return asset, disposal


def test_transfer_disposal_moves_cost_center_without_derecognition(api):
    """PRD §3.5: "A `TRANSFER` posting is deliberately quieter: the asset's
    `cost_center` is set to the disposal's `transfer_to_cost_center`, both
    gain/loss fields are set to zero, no final entries are created, the asset
    remains `IN_SERVICE` (a self-transition that records the move), and
    components are **not** cascaded — a transfer moves the primary asset's cost
    center only."

    Design: Corner/state_machines/transfer_disposal_moves_cost_center_without_derecognition
    """
    cls = create_class()
    asset, _runs = setup_asset_with_posted_runs(
        ["2026-01"], asset_class_id=cls["id"], asset_tag="T-1",
        description="Transfer me", acquisition_cost_cents=600000,
    )
    disposal = create_approved_disposal(
        asset["id"], disposal_type="TRANSFER", effective_date="2026-02-20",
        transfer_to_cost_center="CC9",
    )

    posted = validate_success(api.post_disposal(disposal["id"], ACCT), 200)
    assert posted["status"] == "POSTED"
    assert posted["book_gain_loss_cents"] == 0
    assert posted["tax_gain_loss_cents"] == 0

    after = refresh_asset(asset["id"])
    assert after["status"] == "IN_SERVICE"
    assert after["cost_center"] == "CC9"
    assert after["accumulated_book_cents"] == 10000

    assert entries_for_disposal(disposal["id"]) == [], (
        "no DISPOSAL_FINAL entries for TRANSFER"
    )


def test_mid_month_disposal_day_boundary(api):
    """PRD §3.5: "if the asset is `IN_SERVICE` and the day-of-month of the
    `effective_date` is 15 or later, the effective period's `BOOK` and `TAX`
    entries are created with `source` equal to `DISPOSAL_FINAL`, the disposal's
    id recorded as their `disposal_id` (and `run_id` null), computed exactly per
    the §3.3 methods and applied to `accumulated_book_cents` and
    `accumulated_tax_cents`."
    PRD §3.5: "If the day-of-month is before the 15th, no final entries are
    created — the mid-month convention treats the asset as disposed before the
    period's depreciation accrues."

    Design: Corner/calculations/mid_month_disposal_day_boundary
    """
    cls = create_class(class_code="VEH", name="Vehicles", tax_method="MACRS_7YR")
    d14_asset = create_in_service_asset(
        cls["id"], in_service_date="2026-01-05", asset_tag="D-14",
        description="Day 14 sale", acquisition_cost_cents=600000,
    )
    d15_asset = create_in_service_asset(
        cls["id"], in_service_date="2026-01-05", asset_tag="D-15",
        description="Day 15 sale", acquisition_cost_cents=600000,
    )
    create_and_post_run("2026-01")
    create_and_post_run("2026-02")

    d14 = create_approved_disposal(
        d14_asset["id"], disposal_type="SALE", proceeds_cents=580000,
        effective_date="2026-03-14",
    )
    d15 = create_approved_disposal(
        d15_asset["id"], disposal_type="SALE", proceeds_cents=570000,
        effective_date="2026-03-15",
    )

    posted14 = validate_success(api.post_disposal(d14["id"], ACCT), 200)
    posted15 = validate_success(api.post_disposal(d15["id"], ACCT), 200)

    # Day 14 < 15: no final entries; 580000 - (600000 - 20000) = 0.
    assert entries_for_disposal(d14["id"]) == []
    assert refresh_asset(d14_asset["id"])["accumulated_book_cents"] == 20000
    assert posted14["book_gain_loss_cents"] == 0

    # Day 15 >= 15: March final entries (BOOK 10000, TAX 7145) applied;
    # 570000 - (600000 - 30000) = 0.
    finals15 = entries_for_disposal(d15["id"])
    assert len(finals15) == 2
    by_ledger = {e["ledger"]: e["amount_cents"] for e in finals15}
    assert by_ledger["BOOK"] == 10000
    assert by_ledger["TAX"] == 7145
    assert all(e["period"] == "2026-03" for e in finals15)
    assert refresh_asset(d15_asset["id"])["accumulated_book_cents"] == 30000
    assert posted15["book_gain_loss_cents"] == 0
