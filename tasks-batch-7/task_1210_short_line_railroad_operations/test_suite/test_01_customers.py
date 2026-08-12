"""Customer master data: creation defaults, required fields, reads, pagination,
credit-status visibility, and role denial (PRD §2.1, §2.3, §2.6, §3.1)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_customer,
    create_customer,
    create_customer_payload,
    is_valid_uuid,
    make_customer_rep_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCustomerCreation:
    def test_customer_creation_defaults_applied(self, api, system_admin_headers):
        """PRD §3.1: "Every commercial relationship begins with a **Customer**
        record — the legal shipper — created by a `SystemAdmin` with a `name`, a
        `billing_email` for invoice delivery, and an optional `demurrage_free_days`
        count that defaults to 2 when omitted. Each customer carries a
        system-managed `credit_status` that starts at `GOOD`; a `SystemAdmin`
        amendment may move it to `SUSPENDED` or back, and may also revise
        `demurrage_free_days`, with either change incrementing the customer's
        `version`."

        Design: Corner/entities/customer_creation_defaults_applied
        """
        resp = api.create_customer(
            create_customer_payload(name="Default Co", billing_email="d@default.example"),
            system_admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_customer(data)
        assert is_valid_uuid(data["id"])
        assert data["demurrage_free_days"] == 2, (
            f"omitted demurrage_free_days must default to 2, got {data['demurrage_free_days']}"
        )
        assert data["credit_status"] == "GOOD", (
            f"new customer credit_status must start at GOOD, got {data['credit_status']}"
        )

    def test_customer_missing_required_name_rejected(self, api, system_admin_headers):
        """PRD §2.9: "Immediately after the headers, and still ahead of any
        business rule, syntactic body validation rejects malformed payloads,
        missing required fields, invalid enum values, and invalid types with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/customer_missing_required_name_rejected
        """
        resp = api.create_customer({"billing_email": "no-name@x.example"}, system_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestCustomerReads:
    def test_customer_get_nonexistent_returns_not_found(self, api, system_admin_headers):
        """PRD §2.6: "Path identifiers are validated left to right: in a nested
        path, the parent identifier is resolved first, and the request is rejected
        with `ERR_RESOURCE_NOT_FOUND` (HTTP 404) at the first identifier that does
        not correspond to an existing resource — a milestone request under a
        nonexistent project fails on the project before the milestone is ever
        considered."

        Design: Corner/entities/customer_get_nonexistent_returns_not_found
        """
        resp = api.get_customer(NON_EXISTENT_UUID, system_admin_headers)
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND)

    def test_customer_list_pagination_limit_offset(self, api, system_admin_headers):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
        parameter skips a number of items from the start of the result set and
        defaults to 0. Unless otherwise specified, every list endpoint returns
        resources sorted by `created_at` in ascending order. The `meta` object of
        a list response carries four pagination fields: `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/entities/customer_list_pagination_limit_offset
        """
        for name, email in (("Alpha Co", "a@x.example"), ("Beta Co", "b@x.example"), ("Gamma Co", "g@x.example")):
            create_customer(name=name, billing_email=email)

        page1, meta1 = validate_paginated(api.list_customers(system_admin_headers, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2, f"limit=2 must return 2 rows, got {len(page1)}"
        assert meta1["total_count"] == 3, f"total_count must be 3, got {meta1['total_count']}"
        assert meta1["has_more"] is True, "first page of 3 with limit 2 must have has_more true"

        page2, meta2 = validate_paginated(api.list_customers(system_admin_headers, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1, f"offset=2 with 3 rows must return the final row only, got {len(page2)}"
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False, "last page must have has_more false"

    def test_immediate_read_after_write_visibility(self, api, system_admin_headers):
        """PRD §3.1: "Each customer carries a system-managed `credit_status` that
        starts at `GOOD`; a `SystemAdmin` amendment may move it to `SUSPENDED` or
        back, and may also revise `demurrage_free_days`, with either change
        incrementing the customer's `version`."
        PRD §2.5: "`version` is an integer that increments by exactly one on every
        mutation of the resource — including mutations performed by system
        cascades rather than by a direct client write — and anchors the optimistic
        concurrency rules of §2.8."

        Design: Corner/consistency_model/immediate_read_after_write_visibility
        """
        customer = create_customer(name="Visible Co", billing_email="v@x.example")
        v0 = customer["version"]
        patch = api.update_customer(customer["id"], {"credit_status": "SUSPENDED"}, system_admin_headers)
        validate_success(patch, expected_status=200)

        reread = validate_success(api.get_customer(customer["id"], system_admin_headers))
        assert reread["credit_status"] == "SUSPENDED", (
            f"PATCH must be visible on the very next GET, got {reread['credit_status']}"
        )
        assert reread["version"] == v0 + 1, (
            f"one mutation must increment version by exactly one: {v0} -> {reread['version']}"
        )


class TestCustomerRbac:
    def test_customer_rep_cannot_create_customers(self, api, system_admin_headers):
        """PRD §2.1: "Authorization is per-endpoint: a caller whose role is not in
        the endpoint's authorized list, or whose entity-backed identity does not
        match the targeted resource, is rejected with `ERR_FORBIDDEN_ROLE` (HTTP
        403)."
        PRD §4: "| POST | `/rail/customers` | Create a shipper customer | SystemAdmin |"

        Design: Corner/rbac/customer_rep_cannot_create_customers
        """
        actor = create_customer(name="Actor Co", billing_email="act@x.example")
        resp = api.create_customer(
            create_customer_payload(name="Sneaky Co", billing_email="s@x.example"),
            make_customer_rep_headers(actor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
