"""The portal user sees its own principal and nothing else, and writes nothing anywhere."""

import pytest

from test_helpers import (
    PRIMARY_CATEGORY,
    ApiErrorId,
    DeductionReasonCode,
    UPC_1,
    UPC_2,
    UPC_3,
    fixtures,
    get_success_data,
    make_principal_portal_headers,
    validate_error,
)
from test_helpers import factories as F

AMOUNT_CENTS = 60000
BUDGET_CENTS = 20000000
OWN_NAME = "Northwind Foods"


@pytest.fixture
def two_principals_one_of_them_the_caller(api):
    """NWF is the acting portal identity; SGF is the stranger whose rows must stay invisible."""
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    own = fixtures.create_principal(api, slotting_budget_cents=BUDGET_CENTS)
    other = fixtures.create_principal(
        api, name="Sunglow Frozen", code="SGF", slotting_budget_cents=BUDGET_CENTS
    )
    agreement = fixtures.create_agreement(api, own["id"], retailer["id"])
    own_item = fixtures.create_item(api, own["id"], upc=UPC_1)
    other_item = fixtures.create_item(
        api, other["id"], upc=UPC_2, description="Frozen Empanadas 10ct"
    )
    other_deduction = fixtures.create_deduction(
        api,
        retailer["id"],
        other["id"],
        reason_code=DeductionReasonCode.SHORTAGE,
        amount_cents=AMOUNT_CENTS,
        deduction_date="2026-08-01",
    )
    return {
        "retailer": retailer,
        "own": own,
        "other": other,
        "agreement": agreement,
        "own_item": own_item,
        "other_item": other_item,
        "other_deduction": other_deduction,
        "portal_headers": make_principal_portal_headers(own["id"]),
    }


def statement(api, scope, principal_id):
    return api.get_commission_statement(
        principal_id,
        scope["portal_headers"],
        {"retailer_id": scope["retailer"]["id"], "category_code": PRIMARY_CATEGORY},
    )


class TestPortalUserScopeAndReadOnlySurface:
    def test_the_portal_identity_resolves_to_its_own_principal_row(
        self, api, two_principals_one_of_them_the_caller
    ):
        """`X-User-ID` is the principal's own identifier, so the row is its own.

        PRD: "When `X-User-Role` is `PrincipalPortalUser`, `X-User-ID` is the `id` of the acting
        `Principal`; reading an item, a presentation, a deduction, or a slotting deal (through its
        presentation) that belongs to a different principal is rejected with
        `ERR_PRINCIPAL_SCOPE_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/portal_user_reads_are_scoped_to_its_own_principal_and_never_write
        """
        scope = two_principals_one_of_them_the_caller

        own_view = get_success_data(
            api.get_principal(scope["own"]["id"], scope["portal_headers"]), 200
        )

        assert own_view["id"] == scope["own"]["id"]
        assert own_view["code"] == "NWF"
        assert own_view["name"] == OWN_NAME

    def test_another_principals_row_and_item_and_deduction_are_all_invisible(
        self, api, two_principals_one_of_them_the_caller
    ):
        """Three different resource types, one ownership-scope band.

        PRD: "**Ownership scope.** A `RetailerBuyer` acting outside its own chain returns
        `ERR_RETAILER_SCOPE_FORBIDDEN` (403); a `PrincipalPortalUser` reading another principal's
        resource returns `ERR_PRINCIPAL_SCOPE_FORBIDDEN` (403)."

        Design: Corner/rbac/portal_user_reads_are_scoped_to_its_own_principal_and_never_write
        """
        scope = two_principals_one_of_them_the_caller

        validate_error(
            api.get_principal(scope["other"]["id"], scope["portal_headers"]),
            ApiErrorId.PRINCIPAL_SCOPE_FORBIDDEN,
            403,
        )
        validate_error(
            api.get_item(scope["other_item"]["id"], scope["portal_headers"]),
            ApiErrorId.PRINCIPAL_SCOPE_FORBIDDEN,
            403,
        )
        validate_error(
            api.get_deduction(scope["other_deduction"]["id"], scope["portal_headers"]),
            ApiErrorId.PRINCIPAL_SCOPE_FORBIDDEN,
            403,
        )

    def test_its_own_item_stays_readable_through_the_same_endpoint(
        self, api, two_principals_one_of_them_the_caller
    ):
        """The same path that was refused for the stranger's item succeeds for its own.

        PRD: "| GET | `/items/{itemId}` | Read one item including its catalog data and catalog state |
        BrokerAdmin, BrokerAccountManager, BrokerAuditManager, RetailerBuyer, PrincipalPortalUser |"

        Design: Corner/rbac/portal_user_reads_are_scoped_to_its_own_principal_and_never_write
        """
        scope = two_principals_one_of_them_the_caller
        validate_error(
            api.get_item(scope["other_item"]["id"], scope["portal_headers"]),
            ApiErrorId.PRINCIPAL_SCOPE_FORBIDDEN,
            403,
        )

        own_item = get_success_data(
            api.get_item(scope["own_item"]["id"], scope["portal_headers"]), 200
        )

        assert own_item["upc"] == UPC_1
        assert own_item["principal_id"] == scope["own"]["id"]

    def test_the_scope_check_covers_the_computed_commission_statement_too(
        self, api, two_principals_one_of_them_the_caller
    ):
        """The role is authorized for this read, and the ownership band still refuses it.

        PRD: "The commission statement is a computed read, available to `BrokerAdmin`,
        `BrokerAccountManager`, `BrokerAuditManager` and `PrincipalPortalUser` — but not to a
        `RetailerBuyer`."

        PRD: "**Ownership scope.** A `RetailerBuyer` acting outside its own chain returns
        `ERR_RETAILER_SCOPE_FORBIDDEN` (403); a `PrincipalPortalUser` reading another principal's
        resource returns `ERR_PRINCIPAL_SCOPE_FORBIDDEN` (403)."

        Design: Corner/rbac/portal_user_reads_are_scoped_to_its_own_principal_and_never_write
        """
        scope = two_principals_one_of_them_the_caller

        validate_error(
            statement(api, scope, scope["other"]["id"]),
            ApiErrorId.PRINCIPAL_SCOPE_FORBIDDEN,
            403,
        )

    def test_its_own_statement_is_well_formed_even_with_no_authorizations(
        self, api, two_principals_one_of_them_the_caller
    ):
        """No item holds shelf space yet, so the lines array is empty and both totals are sums of nothing.

        PRD: "The response echoes `principal_id`, `retailer_id`, `category_code`, the resolved
        `agreement_id` and the three rate terms `base_commission_bps`, `tier_threshold_cents` and
        `tier_commission_bps`, then carries a `lines` array and the two totals `total_shipped_cents` and
        `total_commission_cents`."

        PRD: "`total_commission_cents` is the sum of the already-rounded line values, and
        `total_shipped_cents` is the sum of the line shipped amounts."

        Design: Corner/rbac/portal_user_reads_are_scoped_to_its_own_principal_and_never_write
        """
        scope = two_principals_one_of_them_the_caller

        own_statement = get_success_data(statement(api, scope, scope["own"]["id"]), 200)

        assert own_statement["principal_id"] == scope["own"]["id"]
        assert own_statement["retailer_id"] == scope["retailer"]["id"]
        assert own_statement["category_code"] == PRIMARY_CATEGORY
        assert own_statement["agreement_id"] == scope["agreement"]["id"]
        assert own_statement["lines"] == []
        assert own_statement["total_shipped_cents"] == 0
        assert own_statement["total_commission_cents"] == 0

    def test_a_write_against_its_own_principal_is_still_a_role_rejection(
        self, api, two_principals_one_of_them_the_caller
    ):
        """The role band sits above the ownership band, so ownership is never even consulted.

        PRD: "This role holds no write capability anywhere on the business surface — every mutating
        operation other than setting the logical clock returns `ERR_ROLE_FORBIDDEN`."

        PRD: "`PrincipalPortalUser` — a manufacturer-side, read-only portal user."

        Design: Corner/rbac/portal_user_reads_are_scoped_to_its_own_principal_and_never_write
        """
        scope = two_principals_one_of_them_the_caller

        validate_error(
            api.patch_principal(
                scope["own"]["id"],
                F.principal_patch_payload(name="Northwind Foods Renamed"),
                scope["portal_headers"],
            ),
            ApiErrorId.ROLE_FORBIDDEN,
            403,
        )
        validate_error(
            api.create_item(
                F.item_payload(scope["own"]["id"], upc=UPC_3, description="Churro Bites 8ct"),
                scope["portal_headers"],
            ),
            ApiErrorId.ROLE_FORBIDDEN,
            403,
        )

    def test_neither_refused_write_moved_the_principal(
        self, api, two_principals_one_of_them_the_caller
    ):
        """A priority-2 rejection leaves the row at the version it was created with.

        PRD: "Mutable resources additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on
        every change to the resource, and `version`, an integer that is 1 when the resource is created
        and increases by exactly one on every mutation of that resource."

        Design: Corner/rbac/portal_user_reads_are_scoped_to_its_own_principal_and_never_write
        """
        scope = two_principals_one_of_them_the_caller
        validate_error(
            api.patch_principal(
                scope["own"]["id"],
                F.principal_patch_payload(name="Northwind Foods Renamed"),
                scope["portal_headers"],
            ),
            ApiErrorId.ROLE_FORBIDDEN,
            403,
        )

        unchanged = fixtures.get_principal(api, scope["own"]["id"])

        assert unchanged["name"] == OWN_NAME
        assert unchanged["version"] == 1

    def test_chain_rows_are_not_principal_scoped_and_stay_readable(
        self, api, two_principals_one_of_them_the_caller
    ):
        """Retailers belong to no principal, so the ownership band has nothing to compare.

        PRD: "| GET | `/retailers/{retailerId}` | Read one retail chain | BrokerAdmin,
        BrokerAccountManager, BrokerAuditManager, RetailerBuyer, PrincipalPortalUser |"

        Design: Corner/rbac/portal_user_reads_are_scoped_to_its_own_principal_and_never_write
        """
        scope = two_principals_one_of_them_the_caller

        chain = get_success_data(
            api.get_retailer(scope["retailer"]["id"], scope["portal_headers"]), 200
        )

        assert chain["name"] == scope["retailer"]["name"]
        assert chain["chain_code"] == scope["retailer"]["chain_code"]
