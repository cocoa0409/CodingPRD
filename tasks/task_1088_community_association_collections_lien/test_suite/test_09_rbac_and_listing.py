"""Authentication, AssociationManager ownership scoping, and list/filter reachability."""
from test_helpers import (
    validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, ANON_HEADERS,
    make_association_manager_headers,
    fixtures,
)

AGENT = TEST_USERS["collections_agent_headers"]


def test_create_account_without_role_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting an `X-User-Role` that is not
    one of the recognized roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/create_account_missing_role_returns_unauthenticated
    """
    assoc = fixtures.create_association(api, name="Tarn HOA")
    resp = api.create_account(
        {"association_id": assoc["id"], "unit_number": "1", "owner_name": "Sia Tu"},
        ANON_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_association_manager_cross_scope_denied(api):
    """PRD §2.1: "an `AssociationManager` reading an association, an account (or its child
    assessments, payments, notices, plans, liens, referrals, and bankruptcy cases), an aging
    report, a payoff quote, or a remittance that does not belong to its own association is
    rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/association_manager_cross_scope_unauthorized
    """
    assoc1 = fixtures.create_association(api, name="A-One HOA")
    assoc2 = fixtures.create_association(api, name="A-Two HOA")
    acct1 = fixtures.create_account(api, assoc1["id"], unit_number="1", owner_name="Val Wu")
    # Manager acting as assoc2 reads acct1 (owned by assoc1)
    resp = api.get_account(acct1["id"], make_association_manager_headers(assoc2["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_accounts_list_pagination_and_filter(api):
    """PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`, `total_count`
    (the total number of records matching the filter, ignoring pagination), and `has_more`
    (true when records remain beyond the current page)."

    Design: Corner/endpoints/accounts_list_pagination_and_filter
    """
    assoc = fixtures.create_association(api, name="Zed HOA")
    for name in ("Ann A", "Ben B", "Cy C"):
        fixtures.create_account(api, assoc["id"], owner_name=name)
    data, meta = validate_paginated(
        api.list_accounts(AGENT, params={"association_id": assoc["id"], "limit": 2, "offset": 0}))
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True


def test_assessments_reverse_reachable_by_account(api):
    """PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`, `total_count`
    (the total number of records matching the filter, ignoring pagination), and `has_more`
    (true when records remain beyond the current page)."

    Design: Corner/endpoints/assessments_reverse_reachable_by_account
    """
    assoc = fixtures.create_association(api, name="Ada HOA")
    acct = fixtures.create_account(api, assoc["id"], owner_name="Deb D")
    fixtures.create_assessment(api, acct["id"], 10000, charge_type="REGULAR")
    fixtures.create_assessment(api, acct["id"], 2500, charge_type="LATE_FEE")
    data, meta = validate_paginated(
        api.list_assessments(make_association_manager_headers(assoc["id"]),
                             params={"account_id": acct["id"]}))
    assert len(data) == 2
