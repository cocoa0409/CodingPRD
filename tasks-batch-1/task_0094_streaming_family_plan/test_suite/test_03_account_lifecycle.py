"""Account lifecycle: the SUSPENDED<->ACTIVE revert loop, the close cascade
(stream-end -> minute-fold, download-delete), and terminal-state lockdown.

Translates Difficulty/non_linear_state_machine (suspend/reactivate),
Difficulty/transitive_cascade (close depth-3), and
Corner/state_machines (closed lockdown) instances.
"""
from test_helpers import (
    make_owner_headers,
    validate_success,
    validate_error,
    ApiErrorId,
)
import test_helpers as h


def test_account_suspend_then_reactivate_revert_loop(api):
    """PRD §3.2: "Reactivation is the revert leg of this loop: it is permitted
    only while the account is SUSPENDED, only when expected_account_version
    matches the current version, and only when wallet_credit_cents is at least one
    period of the current plan's monthly_fee_cents ... A successful reactivation
    debits wallet_credit_cents by the current plan's monthly_fee_cents, drives the
    account back from SUSPENDED to ACTIVE, and increments version by one."

    wallet 5000 - one 1000 period fee = 4000 after reactivate.

    Design: Difficulty/non_linear_state_machine/account_suspend_reactivate_revert_loop
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    account = h.create_account(plan["id"], owner_email="owner5@x.com", initial_credit_cents=5000)
    suspend = api.suspend_account(
        account["id"], {"expected_account_version": account["version"]},
        make_owner_headers(account["id"]),
    )
    suspended = validate_success(suspend, 200)
    assert suspended["status"] == "SUSPENDED"

    react = api.reactivate_account(
        account["id"], {"expected_account_version": suspended["version"]},
        make_owner_headers(account["id"]),
    )
    data = validate_success(react, 200)
    assert data["status"] == "ACTIVE"
    assert data["wallet_credit_cents"] == 4000


def test_account_close_depth3_cascade_folds_minutes_and_deletes_download(api):
    """PRD §3.2: "When closing from ACTIVE, the cascade additionally force-ends
    every ACTIVE StreamSession (folding minutes and driving active_stream_count to
    0) before the rest". PRD §3.2: "each forced end folds that session's
    minutes_watched into its profile's daily_watch_minutes_used exactly as a
    normal stop would". PRD §3.2: the close cascade "deletes every DOWNLOADING or
    READY Download owned by any of the account's profiles".
    PRD §3.6: same-day elapsed "is the current minute-of-day minus started_at_min"
    — 09:00->09:... here 10:00->10:30 folds 30 minutes.

    Design: Difficulty/transitive_cascade/account_close_depth3_cascade
    """
    plan = h.create_plan(monthly_fee_cents=1000)
    title = h.create_title(name="Long", maturity_rating="PG", runtime_minutes=120, license_size_mb=700)
    h.set_clock("2026-06-15T10:00:00Z", run_sweeps=False)
    account = h.create_account(plan["id"], owner_email="owner7@x.com", billing_anchor_day=15,
                               initial_credit_cents=50000)
    profile = h.create_profile(account["id"], display_name="Mom", kind="ADULT")
    device = h.create_device(account["id"], device_label="TV1", platform="TV", supports_hd=True)
    download = h.create_ready_download(profile["id"], device["id"], title["id"], quality="SD")
    session = h.start_stream(profile["id"], device["id"], title["id"])
    h.set_clock("2026-06-15T10:30:00Z", run_sweeps=False)

    # Device registration and stream start each mutate the Account (PRD §2.5:
    # counter sync increments version), so re-read the current version for the
    # OCC-guarded close.
    current = h.fetch_account(account["id"])
    close = api.close_account(
        account["id"], {"expected_account_version": current["version"]},
        make_owner_headers(account["id"]),
    )
    closed = validate_success(close, 200)
    assert closed["status"] == "CLOSED"
    assert closed["active_stream_count"] == 0

    prof = h.fetch_profile(account["id"], profile["id"])
    assert prof["daily_watch_minutes_used"] == 30

    dl_after = h.fetch_download(account["id"], download["id"])
    assert dl_after["status"] == "DELETED"


def test_closed_account_suspend_returns_invalid_state(api):
    """PRD §3.2: "A request to drive an account through a transition its current
    state does not define — closing an already-closed account, reactivating an
    active one — is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/closed_account_terminal_lockdown
    """
    s = h.create_closed_account(account_overrides={"owner_email": "closed@x.com",
                                                   "initial_credit_cents": 5000})
    account = s["account"]
    resp = api.suspend_account(
        account["id"], {"expected_account_version": account["version"]},
        make_owner_headers(account["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
