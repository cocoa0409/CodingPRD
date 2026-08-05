"""FK reverse-reachability: each parent-scoped child collection returns its children."""
from test_helpers import (
    validate_paginated,
    TEST_USERS,
    open_account, add_meter, add_reading, collect_deposit,
    setup_account_with_water_bill, request_adjustment,
    moratorium_window_payload,
)

BS = TEST_USERS["billing_specialist_headers"]
MT = TEST_USERS["meter_tech_headers"]
CO = TEST_USERS["collections_officer_headers"]


def test_list_meters_for_account(api):
    """PRD §3.2: "Meters for an account are reverse-reachable through the account".

    Design: Corner/endpoints/list_meters_for_account_reverse_reachability
    """
    account = open_account(api, account_holder_name="List Liz")
    add_meter(api, account["id"], "WATER")
    add_meter(api, account["id"], "SEWER")
    meters, meta = validate_paginated(api.list_meters(account["id"], BS))
    assert len(meters) == 2
    assert all(m["account_id"] == account["id"] for m in meters)


def test_list_readings_for_meter(api):
    """PRD §3.2: "Readings for a meter are reverse-reachable through that meter."

    Design: Corner/endpoints/list_readings_for_meter_reverse_reachability
    """
    account = open_account(api, account_holder_name="Read Rae")
    meter = add_meter(api, account["id"], "WATER")
    add_reading(api, meter["id"], 5000, "ACTUAL", "2026-04-15T00:00:00Z")
    add_reading(api, meter["id"], 9500, "ACTUAL", "2026-05-15T00:00:00Z")
    readings, _ = validate_paginated(api.list_readings(meter["id"], MT))
    assert len(readings) == 2
    assert all(r["meter_id"] == meter["id"] for r in readings)


def test_list_adjustments_for_bill(api):
    """PRD §3.8: "Adjustments for a bill are reverse-reachable through the bill."

    Design: Corner/endpoints/list_adjustments_for_bill_reverse_reachability
    """
    ctx = setup_account_with_water_bill(api, reading_value=9500)
    request_adjustment(api, ctx["bill"]["id"], "cw_9", adjustment_type="GOODWILL", goodwill_amount_cents=250)
    adjustments, _ = validate_paginated(api.list_adjustments(ctx["bill"]["id"], BS))
    assert len(adjustments) == 1
    assert adjustments[0]["bill_id"] == ctx["bill"]["id"]


def test_list_bills_for_account(api):
    """PRD §3.3: reverse-reachability — the bill records its `account_id` (PRD §2.8: "The
    `Account` is the aggregate root.").

    Design: Corner/endpoints/list_bills_for_account_reverse_reachability
    """
    ctx = setup_account_with_water_bill(api, reading_value=9500)
    bills, _ = validate_paginated(api.list_bills(ctx["account"]["id"], BS))
    assert len(bills) == 1
    assert bills[0]["account_id"] == ctx["account"]["id"]


def test_list_deposits_for_account(api):
    """PRD §3.9: "Deposits for an account are reverse-reachable through the account."

    Design: Corner/endpoints/list_payments_deposits_arrangements_plans_liens_shutoffs_moratoria
    """
    account = open_account(api, account_holder_name="Coll Cole")
    collect_deposit(api, account["id"], 5000, "NEW_SERVICE")
    deposits, _ = validate_paginated(api.list_deposits(account["id"], BS))
    assert len(deposits) == 1
    assert deposits[0]["account_id"] == account["id"]


def test_list_moratorium_windows_for_account(api):
    """PRD §3.6: "Account-scoped windows for an account are reverse-reachable through the
    account".

    Design: Corner/endpoints/list_moratorium_windows_for_account_reverse_reachability
    """
    account = open_account(api, account_holder_name="Mora Moe")
    from test_helpers import get_success_data
    get_success_data(api.create_moratorium_window(
        moratorium_window_payload("ACCOUNT", "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z", "MEDICAL",
                                  account_id=account["id"]), CO))
    windows, _ = validate_paginated(api.list_account_moratorium_windows(account["id"], CO))
    assert len(windows) == 1
    assert windows[0]["account_id"] == account["id"]
