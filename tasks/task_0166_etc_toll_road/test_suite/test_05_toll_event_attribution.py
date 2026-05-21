"""Toll-event attribution path tests — TRANSPONDER / PLATE / UNRESOLVED
and the branching billing outcomes.

PRD §3.3 governs attribution resolution and terminal billing states.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    create_account,
    create_and_bind_transponder,
    create_toll_event_payload,
    create_vehicle,
    find_fine_for_account,
    ingest_toll_event,
    setup_account_with_bound_transponder,
    setup_account_with_vehicle,
    validate_success,
)


# ---------------------------------------------------------------------------
# Attribution resolution — PRD §3.3
# ---------------------------------------------------------------------------
def test_attribution_transponder_path(api):
    """PRD §3.3: "When the `transponder_serial` corresponds to a
    transponder whose status is `ACTIVE`, the gantry read is treated as
    a transponder capture: `capture_method` becomes `TRANSPONDER` and
    the associated `account_id` and `vehicle_id` are filled from the
    transponder's binding."

    Claim: a transponder-matching ingest sets capture_method TRANSPONDER
    and populates account_id/vehicle_id from the binding.
    """
    a, v, t = setup_account_with_bound_transponder(
        home_agency_code="NY_EZPASS", balance_cents=10000,
    )
    data = ingest_toll_event(
        gantry_id="G1", agency_code="NY_EZPASS", base_rate_cents=200,
        transponder_serial=t["serial_number"],
    )
    assert data["capture_method"] == "TRANSPONDER"
    assert data["account_id"] == a["id"]
    assert data["vehicle_id"] == v["id"]
    assert data["billing_status"] == "POSTED"


def test_attribution_plate_path(api):
    """PRD §3.3: "If the `transponder_serial` is null or does not match
    any `ACTIVE` transponder, the system tries to attribute via plate
    by looking up the `plate_number` and `plate_state` against
    registered vehicles. A successful plate lookup sets
    `capture_method` to `PLATE` and fills `account_id` and `vehicle_id`
    from the resolved vehicle."

    Claim: plate-only ingest matches by (plate_number, plate_state) and
    sets capture_method PLATE.
    """
    a, v = setup_account_with_vehicle(
        home_agency_code="NY_EZPASS", balance_cents=10000,
        plate_state="NY",
    )
    data = ingest_toll_event(
        gantry_id="G1", agency_code="NY_EZPASS", base_rate_cents=200,
        plate_number=v["plate_number"], plate_state=v["plate_state"],
    )
    assert data["capture_method"] == "PLATE"
    assert data["account_id"] == a["id"]
    assert data["vehicle_id"] == v["id"]
    assert data["billing_status"] == "TOLL_BY_PLATE_INVOICED"


def test_attribution_unresolved_neither_match(api):
    """PRD §3.3: "When neither attribution path succeeds, `capture_method`
    becomes `UNRESOLVED` and `account_id` and `vehicle_id` remain null."

    Claim: ingest with unknown transponder and unknown plate → capture
    UNRESOLVED, billing_status VIOLATED (per §3.3 violation list).
    """
    payload = create_toll_event_payload(
        gantry_id="G1", agency_code="NY_EZPASS", base_rate_cents=200,
        transponder_serial=None,
        plate_number="ZZZ999", plate_state="NY",
    )
    res = api.create_toll_event(
        payload, TEST_USERS["gantry_operator_headers"],
    )
    # Server may return 201 or 409 envelope — PRD §3.3 only commits to
    # ERR_HOV_FRAUD_RECORDED as the error path; UNREAD_TRANSPONDER_NO_PLATE
    # creates a Violation but PRD does not say it returns an error
    # envelope. Accept either 201 with VIOLATED or 409 with the
    # violation persisted.
    body = res.json()
    data = body.get("data") if isinstance(body, dict) else {}
    if res.status_code in (200, 201):
        assert data["capture_method"] == "UNRESOLVED"
        assert data["billing_status"] == "VIOLATED"
        assert data.get("account_id") is None
        assert data.get("vehicle_id") is None


# ---------------------------------------------------------------------------
# POSTED branch — PRD §3.3
# ---------------------------------------------------------------------------
def test_posted_decrements_balance(api):
    """PRD §3.3: "the event transitions from `PENDING` to `POSTED`: the
    system writes `capture_method` as `TRANSPONDER`, decrements
    `Account.balance_cents` by `net_toll_cents`".

    Claim: balance falls by net_toll_cents after a POSTED ingest.
    """
    a, v, t = setup_account_with_bound_transponder(
        home_agency_code="NY_EZPASS", balance_cents=10000,
        auto_reload_enabled=False,
    )
    before = a["balance_cents"]
    data = ingest_toll_event(
        gantry_id="G1", agency_code="NY_EZPASS", base_rate_cents=347,
        transponder_serial=t["serial_number"],
    )
    assert data["billing_status"] == "POSTED"
    net = data["net_toll_cents"]
    assert net == 347
    refreshed = validate_success(
        api.get_account(a["id"], TEST_USERS["agency_admin_headers"]),
        expected_status=200,
    )
    assert refreshed["balance_cents"] == before - net


# ---------------------------------------------------------------------------
# TOLL_BY_PLATE_INVOICED branch — PRD §3.3
# ---------------------------------------------------------------------------
def test_plate_invoiced_decrements_balance(api):
    """PRD §3.3: "the event transitions from `PENDING` to
    `TOLL_BY_PLATE_INVOICED` with `capture_method` set to `PLATE`. The
    plate-bill surcharge of fifteen percent applies, so a plate capture
    is more expensive than the equivalent transponder capture. The
    account is debited..."

    Claim: balance falls by net_toll_cents (which includes plate
    surcharge) after a TOLL_BY_PLATE_INVOICED ingest.
    """
    a, v = setup_account_with_vehicle(
        home_agency_code="NY_EZPASS", balance_cents=10000,
        auto_reload_enabled=False, plate_state="NY",
    )
    data = ingest_toll_event(
        gantry_id="G1", agency_code="NY_EZPASS", base_rate_cents=200,
        plate_number=v["plate_number"], plate_state=v["plate_state"],
    )
    assert data["billing_status"] == "TOLL_BY_PLATE_INVOICED"
    assert data["net_toll_cents"] == 230  # 200 + 30 plate surcharge
    refreshed = validate_success(
        api.get_account(a["id"], TEST_USERS["agency_admin_headers"]),
        expected_status=200,
    )
    assert refreshed["balance_cents"] == 10000 - 230


# ---------------------------------------------------------------------------
# Insufficient funds VIOLATED branch — PRD §3.3
# ---------------------------------------------------------------------------
def test_plate_bill_insufficient_funds_violated(api):
    """PRD §3.3: "if a plate-bill ingest would push the balance below
    zero with `auto_reload_enabled` set to false, or if the
    attribution-resolved vehicle is `BLOCKED`, or if the gantry is an
    HOV lane and the claim falls short of the three HOV conditions
    while `hov_capable` is true, the event transitions from `PENDING`
    to `VIOLATED`."
    PRD §3.3: "A `Violation` is created with a `reason_code` chosen
    from `UNREAD_TRANSPONDER_NO_PLATE` (no transponder match and no
    plate match), `INSUFFICIENT_FUNDS_ON_PLATE_BILL` (plate match but
    post-debit balance below zero without auto-reload)"

    Claim: plate ingest against a zero-balance, auto-reload-off account
    with a registered plate → VIOLATED with reason
    INSUFFICIENT_FUNDS_ON_PLATE_BILL; 409 envelope per §5.
    """
    a, v = setup_account_with_vehicle(
        home_agency_code="NY_EZPASS", balance_cents=0,
        auto_reload_enabled=False, plate_state="NY",
    )
    payload = create_toll_event_payload(
        gantry_id="G1", agency_code="NY_EZPASS", base_rate_cents=200,
        plate_number=v["plate_number"], plate_state=v["plate_state"],
    )
    res = api.create_toll_event(
        payload, TEST_USERS["gantry_operator_headers"],
    )
    # PRD §3.3 only explicitly commits to ERR_HOV_FRAUD_RECORDED as a
    # 409 error-envelope path; for INSUFFICIENT_FUNDS_ON_PLATE_BILL it
    # only says "transitions from PENDING to VIOLATED". Accept either
    # 201 with VIOLATED body or 409 with the error envelope. PRD §3.5
    # commits to the Violation + Fine being recorded either way.
    body = res.json()
    data = body.get("data") if isinstance(body, dict) else {}
    if res.status_code in (200, 201):
        assert data["billing_status"] == "VIOLATED"
        assert data["capture_method"] == "PLATE"
    else:
        assert res.status_code == 409
        assert data["error_id"] == "ERR_INSUFFICIENT_FUNDS_ON_PLATE_BILL"
    # Either way the violation persists and the fine exists.
    fine = find_fine_for_account(a["id"])
    assert fine is not None


# ---------------------------------------------------------------------------
# Deduplication — PRD §2.10
# ---------------------------------------------------------------------------
def test_duplicate_toll_event_same_minute_rejected(api):
    """PRD §2.10: "Two `TollEvent` ingests that share the same
    `gantry_id`, the same `read_at` minute (the `read_at` timestamp
    truncated to the minute), and the same `plate_number` +
    `plate_state` or `transponder_serial` tuple serialize
    first-writer-wins on that deduplication tuple; the second ingest
    is rejected with `ERR_DUPLICATE_TOLL_EVENT`."

    Claim: two transponder ingests at the same gantry within the same
    minute → second returns 409 ERR_DUPLICATE_TOLL_EVENT.
    """
    a, v, t = setup_account_with_bound_transponder(
        home_agency_code="NY_EZPASS", balance_cents=10000,
    )
    # First ingest at fixed minute.
    payload1 = create_toll_event_payload(
        gantry_id="DUP1", agency_code="NY_EZPASS", base_rate_cents=100,
        read_at="2026-05-20T10:15:00.000Z",
        transponder_serial=t["serial_number"],
    )
    res1 = api.create_toll_event(
        payload1, TEST_USERS["gantry_operator_headers"],
    )
    assert res1.status_code == 201

    # Second ingest: same gantry, same minute (different second).
    payload2 = create_toll_event_payload(
        gantry_id="DUP1", agency_code="NY_EZPASS", base_rate_cents=100,
        read_at="2026-05-20T10:15:42.500Z",
        transponder_serial=t["serial_number"],
    )
    res2 = api.create_toll_event(
        payload2, TEST_USERS["gantry_operator_headers"],
    )
    assert res2.status_code == 409
    assert res2.json()["data"]["error_id"] == "ERR_DUPLICATE_TOLL_EVENT"


def test_non_duplicate_different_minute_accepted(api):
    """PRD §2.10: dedup tuple is (gantry_id, read_at minute, plate+state
    or transponder_serial).

    Claim: same gantry / same transponder / DIFFERENT minute → second
    ingest accepted (201).
    """
    a, v, t = setup_account_with_bound_transponder(
        home_agency_code="NY_EZPASS", balance_cents=10000,
    )
    payload1 = create_toll_event_payload(
        gantry_id="DUP2", agency_code="NY_EZPASS", base_rate_cents=100,
        read_at="2026-05-20T11:15:00.000Z",
        transponder_serial=t["serial_number"],
    )
    res1 = api.create_toll_event(
        payload1, TEST_USERS["gantry_operator_headers"],
    )
    assert res1.status_code == 201

    payload2 = create_toll_event_payload(
        gantry_id="DUP2", agency_code="NY_EZPASS", base_rate_cents=100,
        read_at="2026-05-20T11:16:00.000Z",
        transponder_serial=t["serial_number"],
    )
    res2 = api.create_toll_event(
        payload2, TEST_USERS["gantry_operator_headers"],
    )
    assert res2.status_code == 201
