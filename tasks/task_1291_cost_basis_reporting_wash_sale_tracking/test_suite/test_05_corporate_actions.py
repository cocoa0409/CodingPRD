"""Corporate actions: split/reverse-split/merger/spinoff basis reallocation,
cascades to accounts, and announcement-payload validation.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    setup_book, make_lot, make_security, make_firm,
    create_corporate_action_payload, get_account_version,
)

TAX_OPS = TEST_USERS["tax_ops_headers"]
FIRM_ADMIN = TEST_USERS["firm_admin_headers"]


def _derived_lots(api, firm_id, account_id):
    data, _meta = validate_paginated(
        api.list_tax_lots(firm_id, account_id, TAX_OPS, params={"acquisition_kind": "CORPORATE_ACTION_DERIVED"})
    )
    return data


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / spinoff_rounding_order_pinned
# ---------------------------------------------------------------------------

def _spinoff_scenario():
    s = setup_book(tin="TIN-SP-1", cusip="444444444", ticker="PAR")
    sec_s = make_security(s["firm"]["id"], cusip="555555555", ticker="SPN")
    lot = make_lot(s["firm"]["id"], s["account"]["id"], s["security"]["id"],
                   quantity=10, basis=10001)
    ca = validate_success(api_client_create_action(
        s, action_type="SPINOFF", merger_acquirer_security_id=sec_s["id"],
        merger_shares_per_source_share=1, spinoff_cost_allocation_pct=0.333,
    ), 201)
    return s, sec_s, lot, ca


def api_client_create_action(s, **kwargs):
    return api_client.create_corporate_action(
        s["firm"]["id"], s["security"]["id"],
        create_corporate_action_payload(**kwargs), TAX_OPS,
    )


def test_spinoff_supersedes_source_lot(api):
    """PRD §3.6: "Each source lot on the action's security in `OPEN` or
    `PARTIALLY_DISPOSED` is superseded: its `lot_status` becomes `SUPERSEDED`,
    its `superseded_by_action_id` points at the action, its `quantity_remaining`
    drops to zero, and one or more derived lots with `acquisition_kind`
    `CORPORATE_ACTION_DERIVED` take its place."

    Design: Difficulty/combinatorial_formula/spinoff_rounding_order_pinned
    """
    s, _sec_s, lot, ca = _spinoff_scenario()
    validate_success(api_client.apply_corporate_action(s["firm"]["id"], ca["id"], TAX_OPS))
    lot_after = validate_success(api_client.get_tax_lot(s["firm"]["id"], lot["id"], TAX_OPS))
    assert lot_after["lot_status"] == "SUPERSEDED"
    assert lot_after["superseded_by_action_id"] == ca["id"]


def test_spinoff_rounding_order_spun_off_first(api):
    """PRD §3.6: "The spun-off lot on the acquirer security holds the remaining
    shares multiplied by `merger_shares_per_source_share` and carries a basis
    equal to the source basis multiplied by `spinoff_cost_allocation_pct`,
    rounded half up to the nearest whole cent. The parent lot stays on the
    original security, keeps the full remaining share count, and carries the
    remainder of the basis. The two derived bases sum exactly to the source
    basis — a conservation invariant the system guarantees."

    Design: Difficulty/combinatorial_formula/spinoff_rounding_order_pinned
    """
    s, sec_s, lot, ca = _spinoff_scenario()
    validate_success(api_client.apply_corporate_action(s["firm"]["id"], ca["id"], TAX_OPS))
    derived = _derived_lots(api_client, s["firm"]["id"], s["account"]["id"])
    assert len(derived) == 2
    by_security = {d["security_id"]: d for d in derived}
    spun = by_security[sec_s["id"]]
    parent = by_security[s["security"]["id"]]
    # spun-off computed FIRST: round_half_up(10001 * 0.333) = 3330; parent = remainder
    assert spun["adjusted_cost_basis_cents"] == 3330
    assert parent["adjusted_cost_basis_cents"] == 6671
    assert spun["adjusted_cost_basis_cents"] + parent["adjusted_cost_basis_cents"] == 10001


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / corporate_action_apply_cascade_depth3
# ---------------------------------------------------------------------------

def _split_scenario(tin="TIN-CASC-2", cusip="111111113", qty=10, basis=10000):
    s = setup_book(tin=tin, cusip=cusip, ticker="SPL")
    lot = make_lot(s["firm"]["id"], s["account"]["id"], s["security"]["id"], quantity=qty, basis=basis)
    ca = validate_success(api_client_create_action(
        s, action_type="SPLIT", split_ratio_numerator=2, split_ratio_denominator=1,
    ), 201)
    return s, lot, ca


def test_split_supersedes_source_and_derives_doubled_lot(api):
    """PRD §3.6: "Under a `SPLIT`, the derived lot's share count is the
    remaining shares multiplied by the numerator and divided by the denominator
    — fractional shares are permitted. Both `original_cost_basis_cents` and
    `adjusted_cost_basis_cents` carry the source basis unchanged: total basis is
    conserved and only the per-share figure moves."
    PRD §3.6: "Every derived lot, whatever the action type, inherits the source
    lot's `acquisition_date` and `holding_period_start`: a corporate action
    never restarts a holding period."

    Design: Difficulty/transitive_cascade/corporate_action_apply_cascade_depth3
    """
    s, lot, ca = _split_scenario()
    validate_success(api_client.apply_corporate_action(s["firm"]["id"], ca["id"], TAX_OPS))
    lot_after = validate_success(api_client.get_tax_lot(s["firm"]["id"], lot["id"], TAX_OPS))
    assert lot_after["lot_status"] == "SUPERSEDED"
    assert lot_after["superseded_by_action_id"] == ca["id"]
    derived = _derived_lots(api_client, s["firm"]["id"], s["account"]["id"])
    assert len(derived) == 1
    assert derived[0]["quantity"] == 20, "split 2:1 doubles the shares"
    assert derived[0]["adjusted_cost_basis_cents"] == 10000, "total basis carried over unchanged"
    assert derived[0]["acquisition_date"].startswith("2025-01-05"), "holding period tacked, not reset"


def test_split_bubbles_account_version(api):
    """PRD §3.6: "Every account that held an affected lot has its `updated_at`
    refreshed and its `version` incremented."

    Design: Difficulty/transitive_cascade/corporate_action_apply_cascade_depth3
    """
    s, lot, ca = _split_scenario()
    v_pre = get_account_version(s["firm"]["id"], s["account"]["id"])
    validate_success(api_client.apply_corporate_action(s["firm"]["id"], ca["id"], TAX_OPS))
    v_post = get_account_version(s["firm"]["id"], s["account"]["id"])
    assert v_post == v_pre + 1, "derived-lot creation bubbled Account.version"


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / corporate_action_basis_conservation
# ---------------------------------------------------------------------------

def test_split_conserves_total_basis(api):
    """PRD §3.6: "Both `original_cost_basis_cents` and
    `adjusted_cost_basis_cents` carry the source basis unchanged: total basis
    is conserved and only the per-share figure moves."

    Design: Difficulty/compensating_invariant/corporate_action_basis_conservation
    """
    s, lot, ca = _split_scenario(tin="TIN-INV-1", cusip="111111124")
    validate_success(api_client.apply_corporate_action(s["firm"]["id"], ca["id"], TAX_OPS))
    derived = _derived_lots(api_client, s["firm"]["id"], s["account"]["id"])
    assert derived[0]["adjusted_cost_basis_cents"] == 10000
    assert derived[0]["quantity"] == 20


def test_split_superseded_source_excluded_from_live_basis(api):
    """PRD §3.6: "Each source lot on the action's security in `OPEN` or
    `PARTIALLY_DISPOSED` is superseded: its `lot_status` becomes `SUPERSEDED`,
    its `superseded_by_action_id` points at the action, its `quantity_remaining`
    drops to zero."

    Design: Difficulty/compensating_invariant/corporate_action_basis_conservation
    """
    s, lot, ca = _split_scenario(tin="TIN-INV-1", cusip="111111124")
    validate_success(api_client.apply_corporate_action(s["firm"]["id"], ca["id"], TAX_OPS))
    lot_after = validate_success(api_client.get_tax_lot(s["firm"]["id"], lot["id"], TAX_OPS))
    assert lot_after["lot_status"] == "SUPERSEDED"
    assert lot_after["quantity_remaining"] == 0
    live, _meta = validate_paginated(
        api_client.list_tax_lots(s["firm"]["id"], s["account"]["id"], TAX_OPS, params={"lot_status": "OPEN"})
    )
    live_basis = sum(l["adjusted_cost_basis_cents"] for l in live)
    assert live_basis == 10000, "live basis sum conserved across supersede+derive"


# ---------------------------------------------------------------------------
# Corner: calculations / reverse split cash-in-lieu, merger boot
# ---------------------------------------------------------------------------

def test_reverse_split_fractional_share_cash_in_lieu(api):
    """PRD §3.6: "Under a `REVERSE_SPLIT`, the derived share count is the same
    product rounded down to a whole share. The leftover fraction is paid out as
    cash in lieu, computed as the fractional part of that product multiplied by
    the source basis and divided by the remaining shares, rounded half up to
    the nearest whole cent. The derived lot's original and adjusted basis equal
    the source basis minus this cash-in-lieu amount."

    Design: Corner/calculations/reverse_split_fractional_share_cash_in_lieu
    """
    s = setup_book(tin="TIN-CALC-10", cusip="383838383", ticker="REV")
    lot = make_lot(s["firm"]["id"], s["account"]["id"], s["security"]["id"], quantity=12, basis=12000)
    ca = validate_success(api_client_create_action(
        s, action_type="REVERSE_SPLIT", split_ratio_numerator=1, split_ratio_denominator=5,
    ), 201)
    validate_success(api_client.apply_corporate_action(s["firm"]["id"], ca["id"], TAX_OPS))
    derived = _derived_lots(api_client, s["firm"]["id"], s["account"]["id"])
    assert len(derived) == 1
    # floor(12/5) = 2; fraction 0.4; cash_in_lieu = round_half_up(0.4 * 12000 / 12) = 400
    assert derived[0]["quantity"] == 2
    assert derived[0]["adjusted_cost_basis_cents"] == 11600, "12000 - 400 cash-in-lieu"
    lot_after = validate_success(api_client.get_tax_lot(s["firm"]["id"], lot["id"], TAX_OPS))
    assert lot_after["lot_status"] == "SUPERSEDED"


def test_merger_cash_boot_reduces_derived_basis(api):
    """PRD §3.6: "Under a `MERGER`, the derived lot lives on the acquirer
    security and holds the remaining shares multiplied by
    `merger_shares_per_source_share`, again possibly fractional. Its basis
    equals the source basis reduced by the cash boot — the remaining shares
    multiplied by `merger_cash_per_share_cents` — but never by more than the
    basis itself, so it cannot fall below zero."

    Design: Corner/calculations/merger_cash_boot_reduces_derived_basis
    """
    s = setup_book(tin="TIN-CALC-11", cusip="393939393", ticker="TGTC")
    acq_sec = make_security(s["firm"]["id"], cusip="404040404", ticker="ACQC")
    lot = make_lot(s["firm"]["id"], s["account"]["id"], s["security"]["id"], quantity=10, basis=10000)
    ca = validate_success(api_client_create_action(
        s, action_type="MERGER", merger_acquirer_security_id=acq_sec["id"],
        merger_cash_per_share_cents=200, merger_shares_per_source_share=1,
    ), 201)
    validate_success(api_client.apply_corporate_action(s["firm"]["id"], ca["id"], TAX_OPS))
    derived = _derived_lots(api_client, s["firm"]["id"], s["account"]["id"])
    assert len(derived) == 1
    # basis = 10000 - min(10 * 200, 10000) = 8000
    assert derived[0]["adjusted_cost_basis_cents"] == 8000
    assert derived[0]["security_id"] == acq_sec["id"], "derived lot lives on the acquirer security"
    lot_after = validate_success(api_client.get_tax_lot(s["firm"]["id"], lot["id"], TAX_OPS))
    assert lot_after["lot_status"] == "SUPERSEDED"


# ---------------------------------------------------------------------------
# Corner: state_machines / cancel-then-apply; validations / incomplete payload
# ---------------------------------------------------------------------------

def test_corporate_action_cancel_then_apply_rejected(api):
    """PRD §3.6: "An action still merely announced can instead be cancelled,
    moving it to `CANCELLED` with no lot impact; `EFFECTIVE` and `CANCELLED`
    are terminal."

    Design: Corner/state_machines/corporate_action_cancel_then_apply_rejected
    """
    s, lot, ca = _split_scenario(tin="TIN-SM-3", cusip="171717171")
    validate_success(api_client.cancel_corporate_action(s["firm"]["id"], ca["id"], TAX_OPS))
    resp = api_client.apply_corporate_action(s["firm"]["id"], ca["id"], TAX_OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    lot_after = validate_success(api_client.get_tax_lot(s["firm"]["id"], lot["id"], TAX_OPS))
    assert lot_after["lot_status"] == "OPEN", "cancelled action must not supersede lots"


def test_corporate_action_incomplete_payload_rejected(api):
    """PRD §3.6: "A split or reverse split requires a positive numerator and a
    positive denominator. ... An inconsistent payload fails with
    `ERR_INCOMPLETE_ACTION_PAYLOAD` (HTTP 422)."

    Design: Corner/validations/corporate_action_incomplete_payload_rejected
    """
    firm = make_firm("Firm V2")
    sec = make_security(firm["id"], cusip="464646464", ticker="ICP")
    resp = api_client.create_corporate_action(
        firm["id"], sec["id"],
        {"action_type": "SPLIT", "effective_date": "2025-03-01T00:00:00Z"},
        TAX_OPS,
    )
    validate_error(resp, ApiErrorId.ERR_INCOMPLETE_ACTION_PAYLOAD)
