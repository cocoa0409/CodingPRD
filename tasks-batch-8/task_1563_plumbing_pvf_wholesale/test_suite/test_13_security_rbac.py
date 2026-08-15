"""Authentication, role authorization, ownership scope, segregation of duties (PRD §2.1, §2.7)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    create_order_payload,
    create_picked_up_order,
    create_presented_sheet,
    create_product_payload,
    create_quote_payload,
    create_return_payload,
    create_submitted_return,
    make_account,
    make_branch,
    make_contractor_headers,
    make_counterrep_headers,
    make_manager_headers,
    make_product,
    make_stock,
    setup_branch_product_account,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["manager_headers"]
REP = TEST_USERS["counterrep_headers"]
SALES = TEST_USERS["sales_headers"]
WAREHOUSE = TEST_USERS["warehouse_headers"]


class TestAuthentication:
    def test_missing_auth_headers_unauthenticated(self, api, manager_headers):
        """PRD §2.1: "A request missing either header, or presenting a role
        outside this list, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_unauthenticated
        """
        make_branch()
        res = api.list_branches({})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_auth_priority_beats_existence_unauthenticated(self, api):
        """PRD §2.7: "Every request is validated against an ordered pipeline, and
        when several checks would fail on the same request, the check that sits
        earliest in this order determines the returned error" — step 1 is
        "Authentication — the `X-User-Role` and `X-User-ID` headers are present
        and the role is recognized; otherwise `ERR_UNAUTHENTICATED`.", ahead of
        path-identifier resolution.

        An unauthenticated GET on a non-existent order id returns 401, never
        leaking the 404.

        Design: Corner/validations/auth_priority_beats_existence_unauthenticated
        """
        res = api.get_order(NON_EXISTENT_UUID, {})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleDenial:
    def test_contractor_cannot_create_product(self, api, contractor_headers):
        """PRD §2.1: "A request whose role is not among the roles authorized for
        the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)." and
        "A `BranchManager` is the branch general manager and owns the catalog"
        — product creation is BranchManager-only (PRD §4).

        Design: Corner/rbac/contractor_cannot_create_product
        """
        account = make_account()
        res = api.create_product(
            create_product_payload(sku="P9", description="Sneaky", list_price_cents=100,
                                   cost_cents=50, cubes_per_unit=1),
            make_contractor_headers(account["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)
        _ = contractor_headers

    def test_warehouselead_cannot_create_quote(self, api, warehouse_headers):
        """PRD §2.1: "An `InsideSales` representative opens contractor accounts
        and owns quotes, selection sheets, takeoff kitting, and substitute
        proposals." Quote creation is InsideSales-only (PRD §4), so a
        WarehouseLead is rejected with `ERR_FORBIDDEN`.

        Design: Corner/rbac/warehouselead_cannot_create_quote
        """
        branch, product, account = setup_branch_product_account()
        res = api.create_quote(
            create_quote_payload(
                account["id"], branch["id"],
                [{"product_id": product["id"], "qty": 1, "unit_price_cents": 9000}],
            ),
            warehouse_headers,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)

    def test_counterrep_cannot_decide_return(self, api):
        """PRD §3.10: "The decision belongs to a `BranchManager`" — the decision
        endpoint is BranchManager-only (PRD §4), so a CounterRep is rejected
        with `ERR_FORBIDDEN` (HTTP 403) and the return stays SUBMITTED.

        Design: Corner/rbac/counterrep_cannot_decide_return
        """
        branch, product, account = setup_branch_product_account(stock=2)
        order, line_ids = create_picked_up_order(account["id"], branch["id"], [(product["id"], 1)])
        ret = create_submitted_return(order["id"], [{"order_line_id": line_ids[0], "qty": 1}],
                                      submitted_by="rep-1")

        res = api.decide_return(ret["id"], {"decision": "APPROVE"}, make_counterrep_headers("rep-2"))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)
        after = validate_success(api.get_return(ret["id"], REP))
        assert after["status"] == "SUBMITTED"


class TestSegregationOfDuties:
    def test_segregation_same_user_decision_rejected(self, api):
        """PRD §3.10: "The decision belongs to a `BranchManager`, and segregation
        of duties is hard: the decider's `X-User-ID` must differ from
        `submitted_by`, or the decision is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        The return was submitted by user rep-7; a BranchManager acting under
        the same X-User-ID may not decide it.

        Design: Corner/rbac/segregation_same_user_decision_rejected
        """
        branch, product, account = setup_branch_product_account(stock=2)
        order, line_ids = create_picked_up_order(account["id"], branch["id"], [(product["id"], 1)])
        ret = create_submitted_return(order["id"], [{"order_line_id": line_ids[0], "qty": 1}],
                                      submitted_by="rep-7")

        res = api.decide_return(ret["id"], {"decision": "APPROVE"}, make_manager_headers("rep-7"))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        after = validate_success(api.get_return(ret["id"], REP))
        assert after["status"] == "SUBMITTED"


class TestContractorOwnershipScope:
    def test_contractor_cannot_read_other_accounts_order(self, api):
        """PRD §2.1: "When `X-User-Role` is `Contractor`, `X-User-ID` is the `id` of the acting `ContractorAccount`; ownership checks on any account-scoped resource compare the resource's `account_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN`. This ownership rule governs awarding a quote, approving a selection sheet, deciding a proposed substitute, and every account-scoped read (the contractor's own account, quotes, sheets, orders, order lines, payments, and returns)."

        Design: Corner/rbac/contractor_cannot_read_other_accounts_order
        """
        branch = make_branch()
        account_a = make_account(company_name="A Co")
        account_b = make_account(company_name="B Co")
        order = validate_success(
            api.create_order(create_order_payload(account_a["id"], branch["id"]), REP), 201
        )

        own = validate_success(api.get_order(order["id"], make_contractor_headers(account_a["id"])))
        assert own["id"] == order["id"]

        res = api.get_order(order["id"], make_contractor_headers(account_b["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)
