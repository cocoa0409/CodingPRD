"""Reference-data contract: scenarios, customers, accounts, transactions (PRD §2.4, §3.1, §3.2)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_customer,
    assert_scenario,
    assert_transaction,
    create_staff,
    create_account_payload,
    create_customer_payload,
    create_scenario_payload,
    create_transaction_payload,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_scenario_create_applies_defaults(api, admin_headers):
    """PRD §3.2: "Baseline weights default to 0.5 for amount, 0.3 for velocity,
    and 0.2 for geography; `stale_alert_days` defaults to 30. A new scenario
    begins in `DRAFT`."
    PRD §2.4: "an integer `version` that starts at 1 and increments by exactly 1
    on every mutation."

    Design: Corner/entities/scenario_create_defaults_applied
    """
    res = api.create_scenario(create_scenario_payload(
        scenario_code="VELOCITY-WIRE-1D", name="Wire velocity 1d",
        applies_to_txn_types=["WIRE_OUT"], direction_filter="DEBIT",
    ), admin_headers)
    scenario = validate_success(res, 201)
    assert_scenario(scenario)
    assert scenario["baseline_weight_amount"] == 0.5
    assert scenario["baseline_weight_velocity"] == 0.3
    assert scenario["baseline_weight_geo"] == 0.2
    assert scenario["stale_alert_days"] == 30
    assert scenario["status"] == "DRAFT"
    assert scenario["version"] == 1
    assert is_valid_uuid(scenario["id"])


def test_customer_create_missing_country_risk_returns_400(api, admin_headers):
    """PRD §3.1: "Onboarding a customer captures the legal `full_name`, the
    `country_code` of residence, and a `country_risk` of `LOW` or `HIGH`."
    PRD §2.10: "malformed-request checks (missing fields, bad enums,
    non-positive amounts, incoherent date windows, a QA review lacking exactly
    one target, or a duplicate active QA sample on the same target — all
    `ERR_INVALID_REQUEST`)".

    Design: Corner/entities/customer_create_missing_required_field_returns_400
    """
    res = api.create_customer(
        {"full_name": "Carl Customer", "country_code": "US"}, admin_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
    assert res.status_code == 400


def test_transaction_unknown_txn_type_returns_400(api, admin_headers):
    """PRD §3.1: "Each post records `amount_cents` (which must be greater than
    zero), a `txn_type` drawn from `CASH_DEPOSIT`, `WIRE_IN`, `WIRE_OUT`,
    `ACH_DEBIT`, or `CHECK_DEPOSIT`, a `direction` of `CREDIT` or `DEBIT`, the
    `counterparty_country`, a `posted_at` timestamp, and a `channel` of
    `BRANCH`, `ATM`, `ONLINE`, or `WIRE_DESK`."
    PRD §2.10: "malformed-request checks (missing fields, bad enums,
    non-positive amounts, incoherent date windows, a QA review lacking exactly
    one target, or a duplicate active QA sample on the same target — all
    `ERR_INVALID_REQUEST`)".

    Design: Corner/entities/transaction_invalid_enum_returns_400
    """
    staff = create_staff()
    customer = validate_success(api.create_customer(
        create_customer_payload(), admin_headers), 201)
    account = validate_success(api.create_account(
        customer["id"], create_account_payload(account_number="ACC-8001"),
        admin_headers), 201)

    res = api.post_transaction(account["id"], create_transaction_payload(
        amount_cents=1000, txn_type="CRYPTO", posted_at="2026-05-01T00:00:00Z",
    ), admin_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
    assert res.status_code == 400

    data, meta = validate_paginated(
        api.list_transactions(account["id"], admin_headers))
    assert data == [] and meta["total_count"] == 0, (
        "the rejected transaction must not be persisted"
    )
    _ = staff


def test_customer_create_ignores_client_supplied_id_and_version(api, admin_headers):
    """PRD §2.4: "Every persistent resource carries a server-minted `id`
    formatted as a UUID with no type prefix."
    PRD §2.4: "an integer `version` that starts at 1 and increments by exactly 1
    on every mutation."

    Design: Corner/entities/customer_create_extra_id_field_input_ignored
    """
    supplied_id = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
    res = api.create_customer(create_customer_payload(
        id=supplied_id, version=99,
    ), admin_headers)
    customer = validate_success(res, 201)
    assert_customer(customer)
    assert customer["id"] != supplied_id, "the server must mint its own UUID"
    assert customer["version"] == 1, "client-supplied version must be ignored"


def test_customer_create_ignores_client_supplied_risk_fields(api, admin_headers):
    """PRD §3.1: "Creation initializes `status` to `ACTIVE`, both risk scores to
    100, `risk_rating` to `LOW`, `sar_filings_365d` and `open_le_inquiry_count`
    to 0, and `any_account_exited` to false."

    Design: Corner/entities/customer_create_computed_risk_input_ignored
    """
    res = api.create_customer(create_customer_payload(
        risk_rating="PROHIBITED", risk_score_standard=9999,
    ), admin_headers)
    customer = validate_success(res, 201)
    assert_customer(customer)
    assert customer["risk_score_standard"] == 100
    assert customer["risk_score_enhanced"] == 100
    assert customer["risk_rating"] == "LOW"
    assert customer["sar_filings_365d"] == 0
    assert customer["open_le_inquiry_count"] == 0
    assert customer["any_account_exited"] is False
    assert customer["status"] == "ACTIVE"


def test_get_alert_unknown_id_returns_404(api, admin_headers):
    """PRD §2.10: "then existence of every referenced id (`ERR_NOT_FOUND`)".

    Design: Corner/entities/alert_get_not_found_returns_404
    """
    res = api.get_alert(NON_EXISTENT_UUID, admin_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)
    assert res.status_code == 404


def test_transaction_record_is_append_only(api, admin_headers):
    """PRD §2.4: "The exception is `Transaction`: transactions are immutable
    posted events, so a transaction carries only `id` and `created_at`; neither
    `updated_at` nor `version` exists on a `Transaction`."
    PRD §3.1: "Transactions are never edited or voided; corrections are made by
    posting new transactions."

    Design: Corner/entities/transaction_immutable_event_record
    """
    customer = validate_success(api.create_customer(
        create_customer_payload(), admin_headers), 201)
    account = validate_success(api.create_account(
        customer["id"], create_account_payload(account_number="ACC-8002"),
        admin_headers), 201)
    res = api.post_transaction(account["id"], create_transaction_payload(
        amount_cents=250000, txn_type="WIRE_OUT", direction="DEBIT",
        counterparty_country="GB", posted_at="2026-05-01T09:00:00Z",
        channel="WIRE_DESK",
    ), admin_headers)
    txn = validate_success(res, 201)
    assert_transaction(txn)
    assert is_valid_uuid(txn["id"])


def test_open_account_under_unknown_customer_returns_404(api, admin_headers):
    """PRD §2.10: "then existence of every referenced id (`ERR_NOT_FOUND`)".

    Design: Corner/entities/account_create_with_unknown_customer_returns_404
    """
    res = api.create_account(
        NON_EXISTENT_UUID,
        create_account_payload(account_number="ACC-8003"), admin_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)
    assert res.status_code == 404
