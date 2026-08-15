"""Difficulty Rule 5: priority-pair validation conflicts.

Covers:
- state_beats_safety_on_dispatch (ERR_LOADOUT_STATE over ERR_BIN_POSTURE_BLOCKED)
- safety_beats_fiscal_on_loadout_create (ERR_BIN_POSTURE_BLOCKED over ERR_CONTRACT_REMAINING_EXCEEDED)
"""
import pytest

from test_helpers import (
    get_success_data, validate_error,
    ApiErrorId,
    TEST_USERS, make_applicator_headers,
    setup_bin_lot_contract_loadout, setup_active_fumigation,
    create_contract, create_hotspot_reading,
)
from test_helpers.api_client import api_client
from test_helpers.factories import create_loadout_payload

SM = TEST_USERS["site_manager_headers"]
FO = TEST_USERS["farm_owner_headers"]


# ============================================================
# Instance: state_beats_safety_on_dispatch
# ============================================================

def test_dispatch_held_loadout_yields_loadout_state_not_posture_blocked(api):
    """PRD section 2.9: "On any endpoint that enforces several rules,
    failures surface in a fixed precedence order so that the earliest
    applicable rejection is always the one returned."
    PRD section 3.6: "Dispatching is the first gated action: the load-out's
    transport must be `SCHEDULED` (otherwise `ERR_LOADOUT_STATE`), the bin's
    posture is re-checked and must be `SOUND` or `WATCH` (otherwise
    `ERR_BIN_POSTURE_BLOCKED`)".

    A HELD loadout on an ALERT bin violates both; the state-machine
    precondition fires first and ERR_LOADOUT_STATE is returned.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_dispatch
    """
    b, lot, con, lo = setup_bin_lot_contract_loadout(
        bin_name="BIN-D", original_bu=800.00, fill_moisture_pct=15.0,
        contracted_bu=2000.00, planned_bu=400.00,
    )
    create_hotspot_reading(b["id"], recorded_at="2026-08-05T10:00:00Z")
    # Sanity: loadout is HELD and bin is ALERT (both rules would fire)
    from test_helpers import get_loadout, get_bin
    assert get_loadout(lo["id"])["transport_status"] == "HELD"
    assert get_bin(b["id"])["posture"] == "ALERT"

    resp = api_client.dispatch_loadout(lo["id"], SM)
    validate_error(resp, ApiErrorId.ERR_LOADOUT_STATE, expected_status=409)


def test_dispatch_held_loadout_error_is_state_class_not_posture_class(api):
    """PRD section 3.6: "Dispatching is the first gated action: the
    load-out's transport must be `SCHEDULED` (otherwise
    `ERR_LOADOUT_STATE`)".

    Distinct second assertion under the same instance: the returned
    error_id is exactly ERR_LOADOUT_STATE (and not the posture error), so
    an implementer who swapped the two checks would fail.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_dispatch
    """
    b, lot, con, lo = setup_bin_lot_contract_loadout(
        bin_name="BIN-D2", original_bu=800.00, fill_moisture_pct=15.0,
        contracted_bu=2000.00, planned_bu=400.00,
    )
    create_hotspot_reading(b["id"], recorded_at="2026-08-05T10:00:00Z")
    resp = api_client.dispatch_loadout(lo["id"], SM)
    assert resp.status_code == 409
    err = resp.json()["data"]
    assert err["error_id"] == "ERR_LOADOUT_STATE"
    assert err["error_id"] != "ERR_BIN_POSTURE_BLOCKED"


# ============================================================
# Instance: safety_beats_fiscal_on_loadout_create
# ============================================================

def _setup_lockout_bin_with_small_contract(bin_name="BIN-G"):
    b, app, fum = setup_active_fumigation(
        bin_name=bin_name, product="PHOSPHINE",
        application_start="2026-08-01T00:00:00Z",
        application_end="2026-08-01T06:00:00Z",
    )
    con = create_contract(contracted_bu=100.00)
    return b, app, fum, con


def test_loadout_create_on_lockout_bin_with_overdraw_yields_posture_blocked(api):
    """PRD section 2.9: "then posture and safety checks; then temporal and
    window rules; then capacity, crop-consistency, and uniqueness
    constraints; then referential-state requirements on related resources;
    and finally fiscal coverage checks."
    PRD section 2.7: "Three operations are gated on posture: filling a new
    lot, scheduling a load-out, and dispatching a scheduled load-out each
    require the bin's posture to be `SOUND` or `WATCH`. Against a bin in
    `ALERT` or `FUMIGATION_LOCKOUT`, any of the three is rejected with
    `ERR_BIN_POSTURE_BLOCKED` (HTTP 409)."

    planned_bu 5000.00 > remaining 100.00 also violates the fiscal check,
    but the posture (safety) check fires first.

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_loadout_create
    """
    b, app, fum, con = _setup_lockout_bin_with_small_contract()
    resp = api_client.create_loadout(create_loadout_payload(
        con["id"], b["id"], con["version"], planned_bu=5000.00,
    ), SM)
    validate_error(resp, ApiErrorId.ERR_BIN_POSTURE_BLOCKED, expected_status=409)


def test_loadout_create_posture_error_is_not_remaining_exceeded(api):
    """PRD section 3.5: "And the contract must have room: `planned_bu` must
    not exceed `contracted_bu` minus `committed_bu` minus `delivered_bu`
    (otherwise `ERR_CONTRACT_REMAINING_EXCEEDED`)."

    When both posture and fiscal checks would fire, the returned error is
    ERR_BIN_POSTURE_BLOCKED — never ERR_CONTRACT_REMAINING_EXCEEDED.

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_loadout_create
    """
    b, app, fum, con = _setup_lockout_bin_with_small_contract("BIN-G2")
    resp = api_client.create_loadout(create_loadout_payload(
        con["id"], b["id"], con["version"], planned_bu=5000.00,
    ), SM)
    assert resp.status_code == 409
    err = resp.json()["data"]
    assert err["error_id"] == "ERR_BIN_POSTURE_BLOCKED"
    assert err["error_id"] != "ERR_CONTRACT_REMAINING_EXCEEDED"
