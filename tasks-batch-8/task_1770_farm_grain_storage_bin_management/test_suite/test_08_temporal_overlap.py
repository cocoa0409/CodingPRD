"""Difficulty Rule 8: resource temporal overlap.

Covers:
- loadout_window_half_open_adjacency (Bin resource, half-open semantics)
- applicator_interval_closed_touching (Applicator resource, closed semantics)
"""
import pytest

from test_helpers import (
    get_success_data, validate_error, validate_success,
    ApiErrorId,
    TEST_USERS, make_applicator_headers,
    create_bin, create_lot, create_contract, create_applicator,
    setup_bin_lot_contract_loadout,
    get_contract,
)
from test_helpers.api_client import api_client
from test_helpers.factories import create_loadout_payload, create_fumigation_payload

SM = TEST_USERS["site_manager_headers"]
FO = TEST_USERS["farm_owner_headers"]


# ============================================================
# Instance: loadout_window_half_open_adjacency
# ============================================================

def _setup_bin_with_first_loadout(bin_name="BIN-O"):
    """Bin with one SCHEDULED loadout occupying [08-10 08:00, 12:00)."""
    b, lot, con, lo1 = setup_bin_lot_contract_loadout(
        bin_name=bin_name, capacity_bu=8000.00, original_bu=5000.00,
        fill_moisture_pct=15.0, contracted_bu=2000.00, planned_bu=100.00,
        scheduled_start="2026-08-10T08:00:00Z",
        scheduled_end="2026-08-10T12:00:00Z",
    )
    return b, lot, con, lo1


def test_loadout_window_touching_endpoint_accepted(api):
    """PRD section 3.5: "The window must not collide with another live
    load-out on the same bin: overlap uses half-open semantics over
    load-outs whose transport is `SCHEDULED`, `HELD`, or `DISPATCHED`, so a
    conflict exists when the new start falls before an existing window's end
    and the new end falls after that window's start, while windows that
    merely touch end-to-start are permitted".

    A new window starting exactly at the existing window's end is accepted.

    Design: Difficulty/resource_temporal_overlap/loadout_window_half_open_adjacency
    """
    b, lot, con, lo1 = _setup_bin_with_first_loadout()
    con_now = get_contract(con["id"])
    resp = api_client.create_loadout(create_loadout_payload(
        con["id"], b["id"], con_now["version"], planned_bu=100.00,
        scheduled_start="2026-08-10T12:00:00Z",
        scheduled_end="2026-08-10T16:00:00Z",
    ), SM)
    assert resp.status_code == 201


def test_loadout_window_one_minute_overlap_rejected(api):
    """PRD section 3.5: "a conflict exists when the new start falls before
    an existing window's end and the new end falls after that window's
    start, while windows that merely touch end-to-start are permitted; a
    conflict is rejected with `ERR_WINDOW_OVERLAP`."

    A window starting at 11:59:59 (one second before 12:00:00 end) overlaps
    and is rejected.

    Design: Difficulty/resource_temporal_overlap/loadout_window_half_open_adjacency
    """
    b, lot, con, lo1 = _setup_bin_with_first_loadout("BIN-O2")
    con_now = get_contract(con["id"])
    resp = api_client.create_loadout(create_loadout_payload(
        con["id"], b["id"], con_now["version"], planned_bu=100.00,
        scheduled_start="2026-08-10T11:59:59Z",
        scheduled_end="2026-08-10T13:00:00Z",
    ), SM)
    validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP, expected_status=409)


# ============================================================
# Instance: applicator_interval_closed_touching
# ============================================================

def _setup_applicator_with_first_fumigation():
    b1 = create_bin(name="BIN-Q1")
    b2 = create_bin(name="BIN-Q2")
    app = create_applicator()
    hdrs = make_applicator_headers(app["id"])
    get_success_data(api_client.create_fumigation(create_fumigation_payload(
        b1["id"], app["id"],
        application_start="2026-08-01T08:00:00Z",
        application_end="2026-08-01T12:00:00Z",
    ), hdrs))
    return b1, b2, app, hdrs


def test_applicator_touching_interval_conflicts(api):
    """PRD section 3.3: "an applicator cannot be in two places at once:
    occupancy intervals are closed, so a new record conflicts with any
    existing record of the same applicator whenever the new start falls at
    or before the existing record's end and the existing record's start
    falls at or before the new end. Touching endpoints conflict; an
    application beginning at the exact instant another of the applicator's
    applications ends is rejected with `ERR_APPLICATOR_DOUBLE_BOOKED`."

    [12:00:00, 14:00:00] touching [08:00:00, 12:00:00] -> conflict.

    Design: Difficulty/resource_temporal_overlap/applicator_interval_closed_touching
    """
    _, b2, app, hdrs = _setup_applicator_with_first_fumigation()
    resp = api_client.create_fumigation(create_fumigation_payload(
        b2["id"], app["id"],
        application_start="2026-08-01T12:00:00Z",
        application_end="2026-08-01T14:00:00Z",
    ), hdrs)
    validate_error(resp, ApiErrorId.ERR_APPLICATOR_DOUBLE_BOOKED,
                   expected_status=409)


def test_applicator_one_second_gap_accepted(api):
    """PRD section 3.3: "occupancy intervals are closed, so a new record
    conflicts with any existing record of the same applicator whenever the
    new start falls at or before the existing record's end and the existing
    record's start falls at or before the new end."

    [12:00:01, 14:00:00] starts strictly after [08:00:00, 12:00:00] ends,
    so no conflict.

    Design: Difficulty/resource_temporal_overlap/applicator_interval_closed_touching
    """
    _, b2, app, hdrs = _setup_applicator_with_first_fumigation()
    resp = api_client.create_fumigation(create_fumigation_payload(
        b2["id"], app["id"],
        application_start="2026-08-01T12:00:01Z",
        application_end="2026-08-01T14:00:00Z",
    ), hdrs)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE"
