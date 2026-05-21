"""Reload tests — manual reload range, auto-reload threshold (inclusive
boundary), per-minute serialization.

PRD §3.4 governs reloads; PRD §2.10 covers per-minute serialization.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_reload_event,
    create_reload_payload,
    get_account,
    ingest_toll_event,
    make_account_holder_headers,
    setup_account_with_bound_transponder,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Manual reload — PRD §3.4
# ---------------------------------------------------------------------------
def test_manual_reload_adds_to_balance(api):
    """PRD §3.4: "A successful manual reload adds the supplied amount
    to `balance_cents` and records a `ReloadEvent` with `kind` of
    `MANUAL`, `balance_before_cents` snapshotting the pre-credit
    balance, `balance_after_cents` snapshotting the post-credit
    balance, and `triggered_by_event_id` null."

    Claim: POST /accounts/{id}/reloads with amount=5000 increases
    balance by 5000 and creates a MANUAL ReloadEvent with the
    before/after snapshots.
    """
    a, v, t = setup_account_with_bound_transponder(
        home_agency_code="NY_EZPASS", balance_cents=0,
        auto_reload_enabled=False,
    )
    res = api.create_reload(
        a["id"], create_reload_payload(amount_cents=5000),
        make_account_holder_headers(a["id"]),
    )
    re_event = validate_success(res, expected_status=201)
    assert_reload_event(re_event)
    assert re_event["kind"] == "MANUAL"
    assert re_event["amount_cents"] == 5000
    assert re_event["balance_before_cents"] == 0
    assert re_event["balance_after_cents"] == 5000
    assert re_event.get("triggered_by_event_id") is None

    refreshed = get_account(a["id"])
    assert refreshed["balance_cents"] == 5000


@pytest.mark.parametrize("amount", [99, 50001])
def test_manual_reload_out_of_range_rejected(api, amount):
    """PRD §3.4: "`amount_cents`, which must be an integer between 100
    and 50000 inclusive; any value outside this range is rejected with
    `ERR_INVALID_RELOAD_AMOUNT`."

    Claim: amount_cents below 100 or above 50000 → 422
    ERR_INVALID_RELOAD_AMOUNT.
    """
    a, v, t = setup_account_with_bound_transponder(
        home_agency_code="NY_EZPASS", balance_cents=0,
        auto_reload_enabled=False,
    )
    res = api.create_reload(
        a["id"], create_reload_payload(amount_cents=amount),
        make_account_holder_headers(a["id"]),
    )
    validate_error(res, "ERR_INVALID_RELOAD_AMOUNT",
                   expected_status=422)


@pytest.mark.parametrize("amount", [100, 50000])
def test_manual_reload_inclusive_boundary_accepted(api, amount):
    """PRD §3.4: "between 100 and 50000 inclusive".

    Claim: the inclusive endpoints amount=100 and amount=50000 are
    accepted (201).
    """
    a, v, t = setup_account_with_bound_transponder(
        home_agency_code="NY_EZPASS", balance_cents=0,
        auto_reload_enabled=False,
    )
    res = api.create_reload(
        a["id"], create_reload_payload(amount_cents=amount),
        make_account_holder_headers(a["id"]),
    )
    data = validate_success(res, expected_status=201)
    assert data["amount_cents"] == amount


# ---------------------------------------------------------------------------
# Auto-reload — PRD §3.4
# ---------------------------------------------------------------------------
def test_auto_reload_triggers_when_post_debit_at_threshold(api):
    """PRD §3.4: "when `auto_reload_enabled` is true and the post-debit
    `balance_cents` is at or below `auto_reload_threshold_cents` (the
    comparison is inclusive — a balance exactly equal to the threshold
    triggers a reload), the system creates a `ReloadEvent` with `kind`
    of `AUTO`".

    Claim: A1 with threshold=2500 and pre-debit balance=3000, posting
    a 500-cent toll → post-debit balance=2500 (== threshold) → AUTO
    ReloadEvent created with amount=auto_reload_topup_cents=4000;
    Account.balance_cents = 2500 + 4000 = 6500.
    """
    a, v, t = setup_account_with_bound_transponder(
        home_agency_code="NY_EZPASS", balance_cents=3000,
        auto_reload_enabled=True,
        auto_reload_threshold_cents=2500,
        auto_reload_topup_cents=4000,
    )
    ingest_toll_event(
        gantry_id="G1", agency_code="NY_EZPASS", base_rate_cents=500,
        transponder_serial=t["serial_number"],
    )
    refreshed = get_account(a["id"])
    # Post-debit balance hits exactly the threshold → reload runs.
    assert refreshed["balance_cents"] == 6500

    # ReloadEvent list should include the AUTO entry.
    res = api.list_reloads(
        a["id"], make_account_holder_headers(a["id"]),
        params={"kind": "AUTO"},
    )
    data, meta = validate_paginated(res)
    assert any(
        r["kind"] == "AUTO" and r["amount_cents"] == 4000 for r in data
    )


def test_auto_reload_does_not_trigger_above_threshold(api):
    """PRD §3.4: "(the comparison is inclusive — a balance exactly
    equal to the threshold triggers a reload)".

    Claim: A2 with threshold=2500 and pre-debit balance=3001, posting a
    500-cent toll → post-debit balance=2501 (just above threshold) →
    no AUTO reload; Account.balance_cents = 2501.
    """
    a, v, t = setup_account_with_bound_transponder(
        home_agency_code="NY_EZPASS", balance_cents=3001,
        auto_reload_enabled=True,
        auto_reload_threshold_cents=2500,
        auto_reload_topup_cents=4000,
    )
    ingest_toll_event(
        gantry_id="G1", agency_code="NY_EZPASS", base_rate_cents=500,
        transponder_serial=t["serial_number"],
    )
    refreshed = get_account(a["id"])
    assert refreshed["balance_cents"] == 2501


def test_auto_reload_event_carries_triggered_by_event_id(api):
    """PRD §3.4: "An `AUTO` reload additionally carries the originating
    toll event's id in `triggered_by_event_id`; a `MANUAL` reload
    leaves that field null."

    Claim: AUTO ReloadEvent.triggered_by_event_id == the originating
    TollEvent.id.
    """
    a, v, t = setup_account_with_bound_transponder(
        home_agency_code="NY_EZPASS", balance_cents=1000,
        auto_reload_enabled=True,
        auto_reload_threshold_cents=1000,
        auto_reload_topup_cents=4000,
    )
    event = ingest_toll_event(
        gantry_id="G1", agency_code="NY_EZPASS", base_rate_cents=200,
        transponder_serial=t["serial_number"],
    )
    # Post-debit balance = 800 ≤ 1000 → AUTO reload fires.
    res = api.list_reloads(
        a["id"], make_account_holder_headers(a["id"]),
        params={"kind": "AUTO"},
    )
    data, meta = validate_paginated(res)
    autos = [r for r in data if r["kind"] == "AUTO"]
    assert len(autos) >= 1
    assert autos[0]["triggered_by_event_id"] == event["id"]
