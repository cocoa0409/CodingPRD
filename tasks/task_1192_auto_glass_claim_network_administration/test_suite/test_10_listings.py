"""Reverse-reachability listings and pagination envelope."""
from test_helpers import (
    TEST_USERS, NON_EXISTENT_UUID, validate_error, validate_paginated,
    ApiErrorId,
    create_claim_payload,
    make_policyholder_headers,
    make_regulation, make_policyholder, make_policy,
    setup_invoice_submitted,
)

ADMIN = TEST_USERS["admin_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]


class TestReverseReachability:
    def test_reverse_reachability_list_endpoints(self, api):
        """PRD §3.3: "The disclosures recorded against a claim can be listed by
        any role."
        PRD §3.1: "A shop's work orders can be listed with an optional `status`
        filter."
        PRD §3.1: "every invoice line referencing a given entry remains
        reachable from the entry itself."
        PRD §3.5: "an invoice's lines remain listable from the invoice."
        PRD §3.7: "The rework work orders spawned by a warranty claim remain
        listable from it."

        Design: Corner/endpoints/reverse_reachability_list_endpoints
        """
        ctx = setup_invoice_submitted(
            claim_overrides={"estimated_repair_cost_cents": 95000})
        claim, wo, invoice = ctx["claim"], ctx["work_order"], ctx["invoice"]
        shop, part = ctx["shop"], ctx["part"]

        claim_wos, meta = validate_paginated(
            api.list_claim_work_orders(claim["id"], ADMIN))
        assert [w["id"] for w in claim_wos] == [wo["id"]]

        wo_invoices, meta = validate_paginated(
            api.list_work_order_invoices(wo["id"], ADMIN))
        assert [i["id"] for i in wo_invoices] == [invoice["id"]]

        inv_lines, meta = validate_paginated(
            api.list_invoice_line_items(invoice["id"], ADMIN))
        assert len(inv_lines) == 1
        assert inv_lines[0]["invoice_id"] == invoice["id"]

        part_lines, meta = validate_paginated(
            api.list_part_line_items(part["id"], ADMIN))
        assert len(part_lines) == 1

        shop_wos, meta = validate_paginated(
            api.list_shop_work_orders(shop["id"], ADMIN))
        assert [w["id"] for w in shop_wos] == [wo["id"]]

        disclosures, meta = validate_paginated(
            api.list_choice_disclosures(claim["id"], ADMIN))
        assert len(disclosures) == 1

        # Unresolvable parent id on a nested list surfaces the parent's 404.
        missing = api.list_warranty_work_orders(NON_EXISTENT_UUID, ADMIN)
        validate_error(missing, ApiErrorId.ERR_WARRANTY_CLAIM_NOT_FOUND)


class TestPagination:
    def test_pagination_defaults_and_envelope(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return. If not provided, it defaults to 10, with a minimum of
        1 and a maximum of 100. The `offset` parameter specifies the number of
        items to skip and defaults to 0."
        PRD §2.3: "Paginated list-based responses include the following fields
        in the `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/endpoints/pagination_defaults_and_envelope
        """
        make_regulation("FL")
        ph = make_policyholder(full_name="Page Test", email="pg@x.com")
        pol = make_policy(ph["id"])
        for i, cat in enumerate(("WINDSHIELD", "SIDE_GLASS", "REAR_GLASS")):
            resp = api.create_claim(
                create_claim_payload(pol["id"], part_category=cat,
                                     loss_date=f"2026-04-0{i + 1}",
                                     description=f"p{i + 1}",
                                     estimated_repair_cost_cents=80000),
                make_policyholder_headers(ph["id"]))
            assert resp.status_code == 201, f"Setup failed: {resp.text}"

        data, meta = validate_paginated(
            api.list_claims(ADJUSTER, params={"policyholder_id": ph["id"]}))
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert len(data) == 3
        assert meta["api_request_id"].startswith("req_")

        page, meta2 = validate_paginated(api.list_claims(
            ADJUSTER, params={"policyholder_id": ph["id"], "limit": 2,
                              "offset": 0}))
        assert len(page) == 2
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is True
