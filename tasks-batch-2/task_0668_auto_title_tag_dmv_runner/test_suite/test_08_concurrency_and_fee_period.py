"""Optimistic-concurrency (OCC) stale-version rejections and the fee-period reset.

Queue B (Corner) — cross_cutting_complexity_layers section.
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_schedule_and_account, create_transaction,
    create_transaction_verified_and_quoted, submit_transaction, create_planned_trip,
    publish_fee_schedule, create_account, inject_ytd_count, set_clock, TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["fee_analyst_headers"]
DISPATCHER = TEST_USERS["runner_dispatcher_headers"]


def test_occ_leg_attach_stale_trip_version_rejected(api):
    """PRD §2.5: "attaching a leg to a runner trip requires expected_runnertrip_version,
    which must carry the client's last observed version of the target RunnerTrip; if a
    prior leg attach has advanced the trip's version since the dispatcher last read it,
    the attach is rejected with ERR_STALE_VERSION (HTTP 412), so two attaches cannot both
    believe they took the last free capacity slot."

    Design: Corner/cross_cutting_complexity_layers/occ_leg_attach_stale_trip_version_returns_412
    """
    schedule, account = setup_schedule_and_account(account_type="RETAIL", state_code="CA")
    txnA, _qa = create_transaction_verified_and_quoted(account["id"], "REGISTRATION", vin="1HGCM82633A004352")
    subA = submit_transaction(txnA["id"])
    txnB, _qb = create_transaction_verified_and_quoted(account["id"], "REGISTRATION", vin="2HGCM82633A004353")
    subB = submit_transaction(txnB["id"])

    trip = create_planned_trip(capacity=5)
    stale_version = trip["version"]
    # First attach legitimately advances the trip version.
    validate_success(api.attach_leg(trip["id"], {
        "submission_id": subA["id"], "expected_runnertrip_version": stale_version}, DISPATCHER), 201)

    # Second attach carrying the now-stale pre-attach version is rejected.
    res = api.attach_leg(trip["id"], {
        "submission_id": subB["id"], "expected_runnertrip_version": stale_version}, DISPATCHER)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


def test_occ_quote_supersede_stale_transaction_version_rejected(api):
    """PRD §2.5: "generating a new fee quote requires expected_transaction_version, which
    must carry the client's last observed version of the target Transaction; if another
    writer has advanced the transaction's version since the analyst last read it ... the
    quote is rejected with ERR_STALE_VERSION (HTTP 412)"

    Design: Corner/cross_cutting_complexity_layers/occ_quote_supersede_stale_transaction_returns_412
    """
    schedule, account = setup_schedule_and_account(account_type="RETAIL", state_code="CA")
    txn = create_transaction(account["id"], "REGISTRATION", declared_price_cents=0)
    stale_version = txn["version"]
    # First quote legitimately advances the transaction version.
    validate_success(api.quote_transaction(
        txn["id"], {"expected_transaction_version": stale_version}, ANALYST), 200)

    # Second quote carrying the stale create-time version is rejected.
    res = api.quote_transaction(
        txn["id"], {"expected_transaction_version": stale_version}, ANALYST)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


def test_fee_period_advance_resets_ytd_count(api):
    """PRD §3.1: "advancing the fee period is the volume-discount reset event: it sets
    every account's ytd_completed_count back to zero and bumps each account's version."

    Design: Corner/cross_cutting_complexity_layers/fee_period_advance_resets_ytd_count
    """
    set_clock()
    publish_fee_schedule(state_code="CA", registration_fee_cents=8500)
    fleet = create_account(account_type="FLEET", state_code="CA",
                           credit_terms=True, credit_limit_cents=100000000)
    inject_ytd_count(fleet["id"], 20)  # would be the 1250 bps tier
    validate_success(api.advance_fee_period(ADMIN), 200)

    account_after = validate_success(api.get_account(fleet["id"], ADMIN), 200)
    assert account_after["ytd_completed_count"] == 0

    txn = create_transaction(fleet["id"], "REGISTRATION", declared_price_cents=0)
    quote = validate_success(api.quote_transaction(
        txn["id"], {"expected_transaction_version": txn["version"]}, ANALYST), 200)
    # No tier after reset -> base service fee 4500 (no discount).
    assert quote["service_fee_cents"] == 4500
