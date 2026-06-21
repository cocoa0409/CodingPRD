"""Drift computation, the REBALANCE_DUE boundary, rebalancing, and lot-selection variants.

Queue A: boundary_precision_check/drift_at_exactly_threshold_triggers_rebalance_due,
dual_variant_calc/fifo_vs_hifo_partial_sell_realizes_different_gain,
resource_temporal_overlap/rebalance_quarter_uniqueness_overlap.
Queue B (calculations, validations, state_machines, cross_cutting_complexity_layers):
drift_recompute_on_price_update_clears_rebalance_due, rebalance_execute_when_not_due_rejected,
cancel_rebalance_from_planned_succeeds, price_update_cascade_recomputes_drift_for_all_holders,
drift_just_below_threshold_stays_active, occ_stale_version_on_rebalance_create_conflict.
"""
from test_helpers import (
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_rebalance_event_payload,
    set_clock,
    create_model,
    create_security,
    create_active_account,
    open_tax_lot,
    get_account,
    get_rebalance,
    setup_account_two_asset_model,
    setup_rebalance_due_account,
)

ADVISOR = TEST_USERS["advisor_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


def _open_rebalance(api, account_id, quarter, version):
    return get_success_data(
        api.create_rebalance_event(
            create_rebalance_event_payload(
                account_id=account_id, quarter_label=quarter, expected_account_version=version
            ),
            ADVISOR,
        )
    )


# ─── drift_at_exactly_threshold_triggers_rebalance_due ──────────────
def test_drift_exactly_at_threshold_triggers_rebalance_due(api):
    """PRD §2.7: "An account becomes `REBALANCE_DUE` exactly when its `max_drift_pct` is greater than or equal to the model's `drift_threshold_pct`. The boundary is inclusive: a drift equal to the threshold triggers the flag, a drift one point below it does not."

    Design: Difficulty/boundary_precision_check/drift_at_exactly_threshold_triggers_rebalance_due
    """
    s = setup_account_two_asset_model("2026-04-02T00:00:00.000Z", "drift5@x.com")
    # BOND 3.5sh @ 10000 = 35000; US 6.5sh @ 10000 = 65000; invested 100000.
    # US 65% (target 60) -> drift exactly 5 == threshold.
    open_tax_lot(s["account"]["id"], s["bond_sec"]["id"], 3.5, 35000)
    open_tax_lot(s["account"]["id"], s["us_sec"]["id"], 6.5, 65000)
    acct = get_account(s["account"]["id"])
    assert acct["max_drift_pct"] == 5
    assert acct["status"] == "REBALANCE_DUE"


def test_drift_one_below_threshold_stays_active(api):
    """PRD §2.7: "The boundary is inclusive: a drift equal to the threshold
    triggers the flag, a drift one point below it does not."

    Design: Difficulty/boundary_precision_check/drift_at_exactly_threshold_triggers_rebalance_due
    """
    s = setup_account_two_asset_model("2026-04-03T00:00:00.000Z", "drift4@x.com")
    # BOND 3.6sh = 36000; US 6.4sh = 64000; invested 100000. US 64% -> drift 4 < 5.
    open_tax_lot(s["account"]["id"], s["bond_sec"]["id"], 3.6, 36000)
    open_tax_lot(s["account"]["id"], s["us_sec"]["id"], 6.4, 64000)
    acct = get_account(s["account"]["id"])
    assert acct["max_drift_pct"] == 4
    assert acct["status"] == "ACTIVE"


# ─── fifo_vs_hifo_partial_sell_realizes_different_gain ──────────────
def _build_two_lot_account_and_rebalance(api, email, lot_selection):
    """50/50 model, two US_EQUITY lots in X (A 3sh/24000 first, B 3sh/36000 second)
    at price 10000. invested 60000 -> US 100% (drift 50) -> REBALANCE_DUE. A 2026-Q1
    rebalance must sell exactly 3 shares of X (down to 30000) to reach the 50000
    US_EQUITY target."""
    set_clock("2026-01-10T00:00:00.000Z")
    model = create_model(
        name=f"{lot_selection} model",
        min_risk_score=70,
        max_risk_score=100,
        targets=[
            {"asset_class": "US_EQUITY", "target_pct": 50},
            {"asset_class": "BOND", "target_pct": 50},
        ],
        drift_threshold_pct=5,
        lot_selection=lot_selection,
    )
    x = create_security(f"X{lot_selection}", "US_EQUITY", 10000)
    create_security(f"BX{lot_selection}", "BOND", 10000)
    acct = create_active_account(email, model_id=model["id"])
    open_tax_lot(acct["id"], x["id"], 3, 24000)  # lot A acquired first
    set_clock("2026-02-10T00:00:00.000Z")
    open_tax_lot(acct["id"], x["id"], 3, 36000)  # lot B acquired second
    acct_after = get_account(acct["id"])
    reb = _open_rebalance(api, acct["id"], "2026-Q1", acct_after["version"])
    get_success_data(api.execute_rebalance_event(reb["id"], ADVISOR))
    # Return the CLOSED X lots produced by the rebalance sell.
    closed, _meta = validate_paginated(
        api.list_tax_lots(
            ADVISOR, params={"account_id": acct["id"], "security_id": x["id"], "status": "CLOSED"}
        )
    )
    return acct["id"], x["id"], closed


def test_fifo_partial_sell_consumes_oldest_lot_realizes_gain(api):
    """PRD §3.6: "Under the default `FIFO` variant — in effect whenever `lot_selection` is unset or `FIFO` — the oldest lots are consumed first, ordered by `acquired_at` ascending and breaking ties by `created_at` ascending; in a rising market this typically realizes larger gains."

    Design: Difficulty/dual_variant_calc/fifo_vs_hifo_partial_sell_realizes_different_gain
    """
    _, _, closed_lots = _build_two_lot_account_and_rebalance(api, "fifo@x.com", "FIFO")
    assert len(closed_lots) == 1
    # FIFO consumes lot A (basis 24000): proceeds 30000 - 24000 = +6000.
    assert closed_lots[0]["realized_gain_cents"] == 6000


def test_hifo_partial_sell_consumes_highest_basis_lot_realizes_loss(api):
    """PRD §3.6: "Under the `HIFO` variant — in effect when `lot_selection` is `HIFO` — the lots with the highest per-share cost basis are consumed first, ordered by `cost_basis_cents` divided by `quantity` descending, breaking ties by `acquired_at` ascending and then `created_at` ascending; this minimizes the realized gain and maximizes the harvested loss. Because the two variants select different lots for the same partial sell, they realize different `realized_gain_cents` on identical holdings."

    Design: Difficulty/dual_variant_calc/fifo_vs_hifo_partial_sell_realizes_different_gain
    """
    _, _, closed_lots = _build_two_lot_account_and_rebalance(api, "hifo@x.com", "HIFO")
    assert len(closed_lots) == 1
    # HIFO consumes lot B (basis 36000): proceeds 30000 - 36000 = -6000.
    assert closed_lots[0]["realized_gain_cents"] == -6000


# ─── rebalance_quarter_uniqueness_overlap ───────────────────────────
def _execute_first_quarter_rebalance(api, email):
    s = setup_rebalance_due_account("2026-04-05T00:00:00.000Z", email)
    acct_id = s["account"]["id"]
    reb1 = _open_rebalance(api, acct_id, "2026-Q2", s["acct_version"])
    executed = get_success_data(api.execute_rebalance_event(reb1["id"], ADVISOR))
    return s, reb1, executed


def test_second_executed_rebalance_same_quarter_rejected(api):
    """PRD §3.6: "no already-`EXECUTED` rebalance for this account shares the same `quarter_label` — a repeated quarter is rejected with `ERR_QUARTER_ALREADY_REBALANCED`, since a `quarter_label` is unique per account among executed rebalances."

    Design: Difficulty/resource_temporal_overlap/rebalance_quarter_uniqueness_overlap
    """
    s, reb1, _ = _execute_first_quarter_rebalance(api, "tov2@x.com")
    acct_id = s["account"]["id"]
    # Re-skew drift so a second rebalance can be planned, then attempt the same quarter.
    open_tax_lot(acct_id, s["us_sec"]["id"], 5, 50000)
    acct_now = get_account(acct_id)
    reb2 = _open_rebalance(api, acct_id, "2026-Q2", acct_now["version"])
    res = api.execute_rebalance_event(reb2["id"], ADVISOR)
    validate_error(res, ApiErrorId.ERR_QUARTER_ALREADY_REBALANCED.value)


def test_first_quarter_rebalance_executed_second_remains_planned(api):
    """PRD §3.6: "a repeated quarter is rejected with `ERR_QUARTER_ALREADY_REBALANCED`, since a `quarter_label` is unique per account among executed rebalances." PRD §3.6: "A successful plan is recorded in `PLANNED` status with `trades_count` and `cash_consumed_cents` at zero."

    Design: Difficulty/resource_temporal_overlap/rebalance_quarter_uniqueness_overlap
    """
    s, reb1, executed1 = _execute_first_quarter_rebalance(api, "tov2b@x.com")
    acct_id = s["account"]["id"]
    assert executed1["status"] == "EXECUTED"
    open_tax_lot(acct_id, s["us_sec"]["id"], 5, 50000)
    acct_now = get_account(acct_id)
    reb2 = _open_rebalance(api, acct_id, "2026-Q2", acct_now["version"])
    api.execute_rebalance_event(reb2["id"], ADVISOR)
    reb2_after = get_rebalance(reb2["id"])
    assert reb2_after["status"] == "PLANNED"


# ─── Queue B corners ────────────────────────────────────────────────
def test_price_update_clears_rebalance_due(api):
    """PRD §3.1: "When the `price_cents` of a security is updated, every account holding `OPEN` lots in that security has its market values, `invested_value_cents`, and drift recomputed, and any such account may auto-transition between `ACTIVE` and `REBALANCE_DUE` according to the drift boundary of §2.7."

    Design: Corner/calculations/drift_recompute_on_price_update_clears_rebalance_due
    """
    s = setup_rebalance_due_account("2026-04-01T00:00:00.000Z", "pricedrift@x.com")
    assert s["account"]["status"] == "REBALANCE_DUE"
    # Reprice BOND so US 70000 of 116668 total ~= 60%, clearing drift.
    get_success_data(api.update_security_price(s["bond_sec"]["id"], {"price_cents": 15556}, ADVISOR))
    acct = get_account(s["account"]["id"])
    assert acct["max_drift_pct"] == 0
    assert acct["status"] == "ACTIVE"


def test_price_update_cascade_flips_active_to_rebalance_due(api):
    """PRD §3.1: "When the `price_cents` of a security is updated, every account holding `OPEN` lots in that security has its market values, `invested_value_cents`, and drift recomputed, and any such account may auto-transition between `ACTIVE` and `REBALANCE_DUE` according to the drift boundary of §2.7."

    Design: Corner/cross_cutting_complexity_layers/price_update_cascade_recomputes_drift_for_all_holders
    """
    s = setup_account_two_asset_model("2026-04-01T00:00:00.000Z", "pcasc@x.com")
    # At target: US 6sh = 60000, BOND 4sh = 40000 (60/40) -> ACTIVE.
    open_tax_lot(s["account"]["id"], s["us_sec"]["id"], 6, 60000)
    open_tax_lot(s["account"]["id"], s["bond_sec"]["id"], 4, 40000)
    assert get_account(s["account"]["id"])["status"] == "ACTIVE"
    # Double US price: US 120000 of 160000 = 75% -> drift 15.
    get_success_data(api.update_security_price(s["us_sec"]["id"], {"price_cents": 20000}, ADVISOR))
    acct = get_account(s["account"]["id"])
    assert acct["max_drift_pct"] == 15
    assert acct["status"] == "REBALANCE_DUE"


def test_drift_just_below_threshold_stays_active(api):
    """PRD §2.7: "The boundary is inclusive: a drift equal to the threshold
    triggers the flag, a drift one point below it does not."

    Design: Corner/cross_cutting_complexity_layers/drift_just_below_threshold_stays_active
    """
    s = setup_account_two_asset_model("2026-04-04T00:00:00.000Z", "below@x.com")
    open_tax_lot(s["account"]["id"], s["bond_sec"]["id"], 3.6, 36000)
    open_tax_lot(s["account"]["id"], s["us_sec"]["id"], 6.4, 64000)
    acct = get_account(s["account"]["id"])
    assert acct["max_drift_pct"] == 4
    assert acct["status"] == "ACTIVE"


def test_rebalance_execute_when_not_due_rejected(api):
    """PRD §3.6: "that the account's `status` be `REBALANCE_DUE` at execution time (an attempt while the account is not `REBALANCE_DUE` is rejected with `ERR_NOT_REBALANCE_DUE`)".

    Design: Corner/validations/rebalance_execute_when_not_due_rejected
    """
    set_clock("2026-05-01T00:00:00.000Z")
    create_model(
        name="NDUE", targets=[{"asset_class": "US_EQUITY", "target_pct": 100}], drift_threshold_pct=5
    )
    sec = create_security("ND1", "US_EQUITY", 10000)
    acct = create_active_account("notdue@x.com")
    open_tax_lot(acct["id"], sec["id"], 5, 50000)  # single-asset 100% -> drift 0, ACTIVE
    acct_now = get_account(acct["id"])
    assert acct_now["status"] == "ACTIVE"
    reb = _open_rebalance(api, acct["id"], "2026-Q2", acct_now["version"])
    res = api.execute_rebalance_event(reb["id"], ADVISOR)
    validate_error(res, ApiErrorId.ERR_NOT_REBALANCE_DUE.value)
    assert get_rebalance(reb["id"])["status"] == "PLANNED"


def test_cancel_planned_rebalance_succeeds(api):
    """PRD §3.6: "A planned rebalance that is no longer wanted may instead be cancelled by an advisor, which moves the event to `CANCELLED` with no ledger changes."

    Design: Corner/state_machines/cancel_rebalance_from_planned_succeeds
    """
    s = setup_rebalance_due_account("2026-07-10T00:00:00.000Z", "cancreb@x.com")
    reb = _open_rebalance(api, s["account"]["id"], "2026-Q3", s["acct_version"])
    cancelled = get_success_data(api.cancel_rebalance_event(reb["id"], ADVISOR))
    assert cancelled["status"] == "CANCELLED"
    assert get_account(s["account"]["id"])["status"] == "REBALANCE_DUE"


def test_stale_version_on_rebalance_create_rejected(api):
    """PRD §2.9: "A request to plan a rebalance event must likewise carry `expected_account_version` matching the account's current `version`; if a prior harvest or rebalance has changed the holdings the plan was computed against, the stale plan would buy or sell the wrong quantities and is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_rebalance_create_conflict
    """
    set_clock("2026-04-01T00:00:00.000Z")
    model = create_model(
        name="OCC6040",
        targets=[
            {"asset_class": "US_EQUITY", "target_pct": 60},
            {"asset_class": "BOND", "target_pct": 40},
        ],
        drift_threshold_pct=5,
    )
    us = create_security("OE", "US_EQUITY", 10000)
    bond = create_security("OB", "BOND", 10000)
    acct = create_active_account("occreb@x.com", model_id=model["id"])
    lot1 = open_tax_lot(acct["id"], us["id"], 7, 70000)
    stale_v = get_account(acct["id"])["version"]
    open_tax_lot(acct["id"], bond["id"], 3, 30000)  # bumps Account.version past stale_v
    res = api.create_rebalance_event(
        create_rebalance_event_payload(
            account_id=acct["id"], quarter_label="2026-Q2", expected_account_version=stale_v
        ),
        ADVISOR,
    )
    validate_error(res, ApiErrorId.ERR_STALE_ACCOUNT_VERSION.value)
