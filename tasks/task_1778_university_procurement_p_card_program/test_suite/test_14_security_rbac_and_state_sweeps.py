"""Authentication, role authorization, high-value gates, state-error sweeps."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    build_user_headers,
    create_competitive_requisition,
    create_declared_asset,
    create_department,
    create_grant,
    create_open_solicitation,
    create_pcard,
    create_surplus_asset_payload,
    create_vendor,
    get_success_data,
    make_cardholder_headers,
    post_debit,
    reconcile_txn,
    set_clock,
    submit_quote,
    validate_error,
    validate_paginated,
)
from test_helpers.fixtures import ADMIN, BUYER, DIRECTOR, SURPLUS_MANAGER

ADMIN_H = ADMIN
BUYER_H = BUYER
SM = SURPLUS_MANAGER


class TestAuthHeaderOrdering:
    def test_auth_header_missing_and_role_denied_ordering(self, api):
        """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one
        of the declared roles, the request is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
        PRD §2.1: "an attempt by a role outside that set is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §2.8: user context is rung 1 and role authorization rung 2 — "a
        failure on an earlier rung prevents any later rung from being evaluated".

        Design: Corner/validations/auth_header_missing_and_role_denied_ordering
        """
        create_department(name="Anthro")

        no_headers = api.create_vendor({"legal_name": "NoHead"}, headers={})
        validate_error(
            no_headers, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400
        )

        unknown_role = api.create_vendor(
            {"legal_name": "Wizard"}, build_user_headers("user-x", "Wizard")
        )
        validate_error(
            unknown_role,
            ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
        )

        wrong_role = api.create_vendor(
            {"legal_name": "WrongRole"}, TEST_USERS["ap_clerk_headers"]
        )
        validate_error(wrong_role, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

        vendors, meta = validate_paginated(api.list_vendors(ADMIN_H))
        assert meta["total_count"] == 0, "no vendor persisted from denied calls"


class TestRoleExclusiveDenials:
    def test_role_exclusive_denial_matrix(self, api):
        """PRD §2.8: role authorization (rung 2) precedes existence (rung 3) — "a
        failure on an earlier rung prevents any later rung from being evaluated".
        PRD §3.9: "when the estimated value is at least 5,000,000 cents (50,000
        dollars), only the `ProcurementDirector` may complete the sale — a
        `SurplusManager` attempting it receives
        `ERR_HIGH_VALUE_SALE_REQUIRES_DIRECTOR` rather than a generic role error".
        PRD §3.9: "the price must clear a floor of 2,500 cents or forty percent
        of `estimated_value_cents` rounded half up to whole cents, whichever is
        greater (otherwise `ERR_SALE_PRICE_BELOW_FLOOR`)".

        Design: Corner/rbac/role_exclusive_denial_matrix
        """
        set_clock("2026-08-01T00:00:00Z")
        dept = create_department(name="RBAC1")
        asset = create_declared_asset(
            department_id=dept["id"], asset_tag="AST-HV",
            description="MRI scanner", condition="GOOD",
            estimated_value_cents=5000000,
        )
        set_clock("2026-08-12T00:00:00Z")
        get_success_data(api.list_surplus_asset_for_sale(asset["id"], SM))
        card = create_pcard(department_id=dept["id"], cardholder_name="Ola")

        as_requester = api.create_vendor(
            {"legal_name": "AsRequester"}, TEST_USERS["requester_headers"]
        )
        validate_error(as_requester, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

        # Role check fires before existence: APClerk may never post receipts, so
        # even a nonexistent PO answers 403, never 404.
        clerk_receipt = api.create_receipt(
            NON_EXISTENT_UUID, {"lines": [{"line_no": 0, "quantity": 1}]},
            TEST_USERS["ap_clerk_headers"],
        )
        validate_error(clerk_receipt, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

        as_cardholder = api.create_surplus_asset(
            create_surplus_asset_payload(
                asset_tag="AST-X", department_id=dept["id"],
                estimated_value_cents=1000, condition="POOR",
            ),
            make_cardholder_headers(card["id"]),
        )
        validate_error(as_cardholder, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

        high_value = api.sell_surplus_asset(
            asset["id"], {"sale_price_cents": 3000000}, SM
        )
        validate_error(
            high_value, ApiErrorId.ERR_HIGH_VALUE_SALE_REQUIRES_DIRECTOR, 403
        )

        sold = get_success_data(
            api.sell_surplus_asset(
                asset["id"],
                {"sale_price_cents": 3000000, "buyer_name": "MedResale"},
                DIRECTOR,
            )
        )
        assert sold["status"] == "SOLD"


class TestStateErrorSweep:
    def test_state_error_sweep_misc_invalid_froms(self, api):
        """PRD §3.1: "calling either transition against a vendor in the wrong
        state is rejected with `ERR_VENDOR_STATE_INVALID`" and (grants) "a
        transition attempted from the wrong state is rejected with
        `ERR_GRANT_STATE_INVALID`".
        PRD §3.8: "A `POSTED` transaction — reconciling anything else is
        `ERR_TXN_NOT_RECONCILABLE`" and "resolution requires a `DISPUTED`
        transaction, else `ERR_TXN_NOT_DISPUTED`".
        PRD §3.9: "A `LISTED` asset may then be sold, donated, or scrapped."
        (§2.8 rung 6 names `ERR_SURPLUS_NOT_SELLABLE`).
        PRD §3.4: "Vendors quote through the buyer while the solicitation is
        `OPEN` — submitting against one that is not is rejected with
        `ERR_SOLICITATION_NOT_OPEN`".

        Design: Corner/errors/state_error_sweep_misc_invalid_froms
        """
        set_clock("2026-08-01T00:00:00Z")
        dept = create_department(name="Sweep")
        vendor = create_vendor(legal_name="SweepCo")
        grant = create_grant(grant_code="G-SW", allowed_categories=["SUPPLIES"])
        card = create_pcard(department_id=dept["id"], cardholder_name="Sid")
        cid = card["id"]
        t1 = post_debit(cid, 8000)
        reconcile_txn(t1["id"], cid, receipt_reference="rcpt-s")
        t2 = post_debit(cid, 9000)
        asset = create_declared_asset(
            department_id=dept["id"], asset_tag="AST-SW", description="shelf",
            condition="POOR", estimated_value_cents=10000,
        )
        req = create_competitive_requisition(
            total_cents=3000000, department_id=dept["id"], vendor_id=vendor["id"],
        )
        sol = create_open_solicitation(req["id"], deadline="2026-08-05T00:00:00Z")
        set_clock("2026-08-05T00:00:00Z")
        get_success_data(api.close_solicitation(sol["id"], BUYER_H))

        e1 = api.reinstate_vendor(vendor["id"], ADMIN_H)
        validate_error(e1, ApiErrorId.ERR_VENDOR_STATE_INVALID, 409)

        e2 = api.reinstate_grant(grant["id"], TEST_USERS["grant_officer_headers"])
        validate_error(e2, ApiErrorId.ERR_GRANT_STATE_INVALID, 409)

        e3 = api.reconcile_transaction(
            t1["id"],
            {"receipt_reference": "rcpt-again", "allocation_type": "GENERAL"},
            make_cardholder_headers(cid),
        )
        validate_error(e3, ApiErrorId.ERR_TXN_NOT_RECONCILABLE, 409)

        e4 = api.resolve_dispute(t2["id"], {"outcome": "MERCHANT_FAVOR"}, ADMIN_H)
        validate_error(e4, ApiErrorId.ERR_TXN_NOT_DISPUTED, 409)

        e5 = api.sell_surplus_asset(asset["id"], {"sale_price_cents": 9000}, SM)
        validate_error(e5, ApiErrorId.ERR_SURPLUS_NOT_SELLABLE, 409)

        e6 = api.create_quote(
            sol["id"], {"vendor_id": vendor["id"], "price_cents": 3000000},
            BUYER_H,
        )
        # The solicitation is CLOSED (state rung fires before the temporal rung).
        validate_error(e6, ApiErrorId.ERR_SOLICITATION_NOT_OPEN, 409)
