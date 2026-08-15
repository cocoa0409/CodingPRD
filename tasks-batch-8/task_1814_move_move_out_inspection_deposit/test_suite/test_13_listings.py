"""List endpoints: pagination envelope and deduction filtering by statement."""
import test_helpers as th
from test_helpers import (
    api_client,
    create_deduction_payload,
    create_jurisdiction,
    create_property,
    create_statement_for,
    create_tenancy,
    create_tenancy_payload,
    create_unit,
    get_success_data,
    get_statement,
    make_manager_admin_headers,
    make_property_manager_headers,
    setup_vacated_tenancy,
    validate_paginated,
    validate_success,
)

ADMIN = make_manager_admin_headers()
PM = make_property_manager_headers()


class TestTenanciesPagination:
    def test_pagination_envelope_and_unit_filter(self):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return; if not provided it defaults to 10, with a minimum of
        1 and a maximum of 100. The `offset` parameter specifies the number of
        items to skip and defaults to 0." and "Paginated list responses
        include the following fields in the `meta` object of the response
        envelope: `limit`, `offset`, `total_count`, and `has_more`."
        PRD §3.2: "The tenancy list can be filtered by `unit_id` and by
        `status`."

        Three tenancies: page 1 (limit 2) => total_count 3, has_more true, 2
        rows; offset 2 => 1 row, has_more false; unit_id filter narrows to 1.

        Design: Corner/endpoints/tenancies_list_pagination_envelope
        """
        jur = create_jurisdiction(interest_required=False, annual_interest_rate_bp=0)
        prop = create_property(jur["id"])
        unit_a = create_unit(prop["id"], unit_number="1A")
        unit_b = create_unit(prop["id"], unit_number="1B")
        unit_c = create_unit(prop["id"], unit_number="1C")
        ten_c = None
        for unit, name in ((unit_a, "T A"), (unit_b, "T B"), (unit_c, "T C")):
            ten = create_tenancy(unit["id"], tenant_display_name=name,
                                 lease_start_on="2026-09-01",
                                 lease_end_on="2027-09-01")
            if unit is unit_c:
                ten_c = ten

        page1, meta1 = validate_paginated(
            api_client.list_tenancies(PM, params={"limit": 2, "offset": 0}))
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert len(page1) == 2

        page2, meta2 = validate_paginated(
            api_client.list_tenancies(PM, params={"limit": 2, "offset": 2}))
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert len(page2) == 1

        filtered, meta3 = validate_paginated(
            api_client.list_tenancies(PM, params={"unit_id": unit_c["id"]}))
        assert meta3["total_count"] == 1
        assert len(filtered) == 1
        assert filtered[0]["id"] == ten_c["id"]


class TestDeductionsFilteredByStatement:
    def test_deductions_filtered_by_statement_after_issue(self):
        """PRD §3.5: "Every `DRAFT` deduction line of the tenancy is then
        swept to `BILLED` with its `statement_id` set to this statement".
        PRD §3.4: "The deduction list can be filtered by `tenancy_id`,
        `inspection_item_id`, `statement_id`, or `status`."

        GET /pm/deductions?statement_id= returns exactly the swept lines (2:
        paint 60,000c + cleaning 8,000c), both BILLED with statement_id set,
        summing to the statement's deduction_total 68,000c.

        Design: Corner/endpoints/deductions_filtered_by_statement_after_issue
        """
        ctx = setup_vacated_tenancy(keys_returned=2, fobs_returned=1)
        ten_id = ctx["tenancy"]["id"]
        get_success_data(api_client.create_deduction(
            create_deduction_payload(tenancy_id=ten_id, amount_cents=8_000), PM))
        stmt = create_statement_for(ten_id)
        api_client.set_clock({"to_iso8601": "2026-08-10T00:00:00Z"}, ADMIN)
        validate_success(api_client.issue_statement(stmt["id"], PM))
        stmt = get_statement(stmt["id"])
        assert stmt["deduction_total_cents"] == 68_000

        resp = api_client.list_deductions(PM, params={"statement_id": stmt["id"],
                                                      "limit": 100})
        rows, meta = validate_paginated(resp)
        assert meta["total_count"] == 2
        assert len(rows) == 2
        for row in rows:
            assert row["statement_id"] == stmt["id"]
            assert row["status"] == "BILLED"
        amounts = sorted(r["amount_cents"] for r in rows)
        assert amounts == [8_000, 60_000]
        assert sum(amounts) == stmt["deduction_total_cents"]

        billed, meta_b = validate_paginated(api_client.list_deductions(
            PM, params={"statement_id": stmt["id"], "status": "BILLED",
                        "limit": 100}))
        assert meta_b["total_count"] == 2
