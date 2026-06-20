"""Endpoint side-effect and listing tests: clock, read voiding, and FK reverse-reachability
filtered lists / sub-resource collections."""
import pytest

from test_helpers import (
    validate_success, validate_paginated,
    fixtures as fx,
    TEST_USERS,
)

ADMIN = TEST_USERS["billing_admin_headers"]
CS = TEST_USERS["customer_service_headers"]
FT = TEST_USERS["field_tech_headers"]


def test_clock_set_updates_current_utc_and_heating_flag(api):
    """PRD 2.8: "A BillingAdmin may advance the clock and toggle the heating-season flag."
    PRD 2.8: "When current_utc is unset by the operator it begins at 2026-01-01T00:00:00.000Z
    and heating_season_active begins false."

    Design: Corner/endpoints/clock_set_updates_current_utc_and_heating_flag
    """
    fx.set_clock("2026-01-10T00:00:00.000Z", True)
    resp = api.get_clock(headers=ADMIN)
    data = validate_success(resp, 200)
    assert data["current_utc"] == "2026-01-10T00:00:00.000Z", f"got {data['current_utc']}"
    assert data["heating_season_active"] is True, f"got {data['heating_season_active']}"


def test_void_read_excludes_it_from_consumption(api):
    """PRD 3.4: "A read may later be voided by a BillingAdmin, setting its status to VOID;
    voided reads are excluded from all consumption math." PRD 3.4: "The prior index is the
    reading_index of the most recent non-voided read on the same meter whose read_date is
    strictly earlier than this read's read_date; when there is no earlier read, the prior
    index is the meter's install_index."

    Design: Corner/endpoints/void_meter_read_excludes_it_from_consumption
    """
    fx.set_clock("2026-02-15T00:00:00.000Z", False)
    rs = fx.create_rate_schedule(btu_factor=1.0)
    acct = fx.create_account(rs["id"])
    meter = fx.register_meter(acct["id"], install_index=1000)
    fx.set_meter(acct["id"], meter["id"], completed_index=1000)
    read1 = fx.post_read(meter["id"], 1100, "2026-02-10T00:00:00.000Z")
    voided = validate_success(api.void_read(meter["id"], read1["id"], headers=ADMIN), 200)
    assert voided["status"] == "VOID", f"got {voided['status']}"
    # Next read computes delta against install 1000 (1100 read is VOID) -> 150.
    read2 = fx.post_read(meter["id"], 1150, "2026-02-28T00:00:00.000Z")
    assert read2["ccf_consumed"] == 150, f"got {read2['ccf_consumed']}"


def test_list_meters_by_account(api):
    """PRD 4 (endpoint): "List meters for an account". PRD 2.3: "List results are ordered by
    created_at ascending."

    Design: Corner/endpoints/list_meters_by_account_fk_reverse_reachability
    """
    rs = fx.create_rate_schedule()
    acct = fx.create_account(rs["id"])
    fx.register_meter(acct["id"], install_index=1000)
    fx.register_meter(acct["id"], install_index=2000)
    resp = api.list_meters(acct["id"], headers=ADMIN)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"got {meta['total_count']}"
    assert all(m["account_id"] == acct["id"] for m in data)


def test_list_service_orders_filtered_by_meter(api):
    """PRD 4 (endpoint): "List service orders, filtered by account/meter".

    Design: Corner/endpoints/list_service_orders_filtered_by_meter_fk_reverse_reachability
    """
    fx.set_clock("2026-02-15T00:00:00.000Z", False)
    rs = fx.create_rate_schedule()
    acct = fx.create_account(rs["id"])
    meter = fx.register_meter(acct["id"], install_index=1000)
    order = fx.get_success_data(api.create_service_order(
        {"account_id": acct["id"], "order_type": "METER_SET", "premise_meter_id": meter["id"],
         "scheduled_date": "2026-02-01T00:00:00.000Z"}, headers=FT))
    resp = api.list_service_orders(headers=FT, params={"premise_meter_id": meter["id"]})
    data, meta = validate_paginated(resp)
    assert all(o["premise_meter_id"] == meter["id"] for o in data)
    assert any(o["id"] == order["id"] for o in data)


def test_list_payments_filtered_by_bill(api):
    """PRD 4 (endpoint): "List payments, filtered by account/bill".

    Design: Corner/endpoints/list_payments_filtered_by_bill_fk_reverse_reachability
    """
    rs, acct, meter, read, issued = fx.setup_issued_bill()
    fx.pay_off_bill(acct["id"], issued["id"], amount_cents=3000, posted_date="2026-03-01T00:00:00.000Z")
    resp = api.list_payments(headers=ADMIN, params={"bill_id": issued["id"]})
    data, meta = validate_paginated(resp)
    assert all(p["bill_id"] == issued["id"] for p in data)
    assert len(data) >= 1


def test_list_bills_filtered_by_account(api):
    """PRD 4 (endpoint): "List bills, filtered by account/read/correction".

    Design: Corner/endpoints/list_bills_filtered_by_account_fk_reverse_reachability
    """
    rs, acct, meter, read, draft = fx.setup_draft_bill()
    resp = api.list_bills(headers=ADMIN, params={"account_id": acct["id"]})
    data, meta = validate_paginated(resp)
    assert all(b["account_id"] == acct["id"] for b in data)
    assert any(b["id"] == draft["id"] for b in data)


def test_list_meter_reads_filtered_by_meter(api):
    """PRD 4 (endpoint): "List meter reads, filtered by meter/account/bill".

    Design: Corner/endpoints/list_meter_reads_filtered_by_meter_fk_reverse_reachability
    """
    rs, acct, meter = fx.setup_account_with_set_meter()
    read = fx.post_read(meter["id"], 1100, "2026-02-28T00:00:00.000Z")
    resp = api.list_meter_reads(headers=ADMIN, params={"premise_meter_id": meter["id"]})
    data, meta = validate_paginated(resp)
    assert all(r["premise_meter_id"] == meter["id"] for r in data)
    assert any(r["id"] == read["id"] for r in data)


def test_list_tickets_filtered_by_account(api):
    """PRD 4 (endpoint): "List emergency tickets, optionally filtered".

    Design: Corner/endpoints/list_tickets_filtered_by_account_fk_reverse_reachability
    """
    rs = fx.create_rate_schedule()
    acct = fx.create_account(rs["id"])
    meter = fx.register_meter(acct["id"], install_index=1000)
    ticket = fx.open_ticket(meter["id"], account_id=acct["id"], kind="ODOR", reported_indoors=False)
    resp = api.list_tickets(headers=FT, params={"account_id": acct["id"]})
    data, meta = validate_paginated(resp)
    assert all(t["account_id"] == acct["id"] for t in data)
    assert any(t["id"] == ticket["id"] for t in data)


def test_list_account_sub_resource_collections(api):
    """PRD 4 (endpoints): "List credits for an account", "List deposits for an account",
    "List budget plans for an account".

    Design: Corner/endpoints/list_budget_plans_low_income_credits_deposits_sub_resources
    """
    rs = fx.create_rate_schedule()
    acct = fx.create_account(rs["id"])
    fx.submit_low_income_credit(acct["id"], household_size=4, annual_income_cents=3000000)
    fx.get_success_data(api.create_deposit(acct["id"], {"reason": "NEW_SERVICE"}, headers=CS))
    credits, c_meta = validate_paginated(api.list_low_income_credits(acct["id"], headers=ADMIN))
    assert c_meta["total_count"] == 1
    assert all(c["account_id"] == acct["id"] for c in credits)
    deposits, d_meta = validate_paginated(api.list_deposits(acct["id"], headers=ADMIN))
    assert d_meta["total_count"] == 1
    assert all(d["account_id"] == acct["id"] for d in deposits)
    plans, p_meta = validate_paginated(api.list_budget_plans(acct["id"], headers=ADMIN))
    assert p_meta["total_count"] == 0
