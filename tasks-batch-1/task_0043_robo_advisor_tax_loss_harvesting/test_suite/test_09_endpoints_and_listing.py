"""Filtered list endpoints.

Queue B (endpoints): list_tax_lots_filtered_by_account_and_status.
"""
from test_helpers import (
    validate_paginated,
    TEST_USERS,
    set_clock,
    create_model,
    create_security,
    create_active_account,
    open_tax_lot,
)

ADVISOR = TEST_USERS["advisor_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


def test_list_tax_lots_filtered_by_account_and_status(api):
    """PRD §4: "List tax lots (filter by account, security, harvest, status)".
    PRD §2.3: "Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_tax_lots_filtered_by_account_and_status
    """
    set_clock("2026-05-01T00:00:00.000Z")
    create_model(name="LF", targets=[{"asset_class": "US_EQUITY", "target_pct": 100}])
    sec = create_security("LF1", "US_EQUITY", 10000)
    acct = create_active_account("listlots@x.com")
    open_tax_lot(acct["id"], sec["id"], 2, 20000)
    open_tax_lot(acct["id"], sec["id"], 3, 30000)
    data, meta = validate_paginated(
        api.list_tax_lots(COMPLIANCE, params={"account_id": acct["id"], "status": "OPEN"})
    )
    assert meta["total_count"] == 2
    for lot in data:
        assert lot["account_id"] == acct["id"]
        assert lot["status"] == "OPEN"
