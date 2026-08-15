"""Role-based access control and entity-backed ownership (PRD §2.1, §2.9).

Covers role exclusivity (AgencyAdmin-only writes, Auditor read-only) and the
ownership scoping of the entity-backed Rep and PrincipalOps roles.
"""
from test_helpers import (
    ApiErrorId,
    checkout_sample,
    create_agreement,
    activate_agreement,
    create_customer,
    create_order,
    create_principal,
    create_rate_schedule,
    create_rep,
    create_sample_unit,
    get_order,
    make_order_line,
    make_principal_ops_headers,
    make_rep_headers,
    return_checkout,
    validate_error,
    validate_paginated,
)


class TestRoleExclusiveDenial:
    def test_rep_cannot_create_principal_forbidden(self, api):
        """PRD §2.1: "A caller whose role is not in an endpoint's allowed list is
        rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)." Principal creation is
        listed under AgencyAdmin only in PRD §4.

        Design: Corner/rbac/rep_cannot_create_principal_forbidden
        """
        rep = create_rep("R1", ["CA"])
        resp = api.create_principal(
            {"name": "PX", "annual_quota_cents": 10_000_000},
            make_rep_headers(rep["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)

    def test_principalops_cannot_settle_statement_forbidden(self, api):
        """PRD §2.1: "A `PrincipalOps` operator uploads commission statements and
        answers disputes for its own principal, but only an `AgencyAdmin` reconciles,
        accepts variances, raises disputes, and settles."

        Design: Corner/rbac/principalops_cannot_settle_statement_forbidden
        """
        principal = create_principal()
        headers = make_principal_ops_headers(principal["id"])
        stmt = api.create_statement(
            {
                "principal_id": principal["id"],
                "period_label": "2026-08",
                "lines": [{"line_id": "S1", "external_order_ref": "PO-1",
                           "amount_cents": 100}],
            },
            headers,
        )
        statement_id = stmt.json()["data"]["id"]
        resp = api.settle_statement(statement_id, headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)

    def test_auditor_is_read_only_forbidden(self, api, auditor_headers):
        """PRD §2.1: "`Auditor` is a read-only oversight role with access to every
        list and detail endpoint and no write capability at all."

        Design: Corner/rbac/auditor_is_read_only_forbidden
        """
        resp = api.create_customer(
            {"name": "C1", "spec_territory_code": "CA", "ship_to_territory_code": "WA"},
            auditor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)

        ok = api.list_customers(auditor_headers)
        _data, meta = validate_paginated(ok)
        assert meta["total_count"] == 0


class TestOwnershipScopeDenial:
    def test_principalops_wrong_principal_scope_forbidden(self, api):
        """PRD §2.1: "When `X-User-Role` is `PrincipalOps`, `X-User-ID` is the `id`
        of the `Principal` the operator serves; ownership checks on any
        principal-scoped resource compare the resource's principal reference to
        `X-User-ID`." and "An entity-backed caller who touches a resource it does not
        own is rejected with `ERR_FORBIDDEN_NOT_OWNER` (HTTP 403)."

        Design: Corner/rbac/principalops_wrong_principal_scope_forbidden
        """
        p1 = create_principal()
        p2 = create_principal(name="P2", annual_quota_cents=5_000_000)
        agreement = create_agreement(p1["id"], territory_codes=["CA"])
        activate_agreement(agreement["id"])
        create_rate_schedule(p1["id"], p1["version"])
        create_rep("R1", ["CA"])
        customer = create_customer(spec_territory_code="CA", ship_to_territory_code="CA")
        order = create_order(
            customer["id"], p1["id"], "PO-1",
            lines=[make_order_line(quantity=1, unit_price_cents=5000)],
        )

        resp = api.ship_order(order["id"], make_principal_ops_headers(p2["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_NOT_OWNER, expected_status=403)
        assert get_order(order["id"])["fulfillment_status"] == "PLACED"

    def test_rep_cannot_return_foreign_checkout(self, api):
        """PRD §3.8: "Return and purchase belong to the borrowing rep alone
        (`ERR_FORBIDDEN_NOT_OWNER`)."
        PRD §3.8: "a `SELLABLE` unit goes back to `IN_STOCK` with a `charge_cents`
        of zero"

        Design: Corner/rbac/rep_cannot_return_foreign_checkout
        """
        principal = create_principal()
        r1 = create_rep("R1", ["CA"])
        r2 = create_rep("R2", ["OR"])
        unit = create_sample_unit(principal["id"], serial_number="S-1", value_cents=80_000)
        checkout = checkout_sample(unit["id"], r1["id"])

        resp = api.return_sample_checkout(
            checkout["id"], {"condition_on_return": "SELLABLE"},
            make_rep_headers(r2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_NOT_OWNER, expected_status=403)

        returned = return_checkout(checkout["id"], r1["id"], "SELLABLE")
        assert returned["status"] == "RETURNED"
        assert returned["charge_cents"] == 0
