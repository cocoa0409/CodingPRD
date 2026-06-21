"""Listing endpoints — filtering, pagination defaults (PRD §2.3)."""
from test_helpers import (
    validate_paginated,
    TEST_USERS,
    set_clock,
    create_owner,
    create_account,
    open_n_accounts,
)


def test_list_accounts_filtered_by_owner_returns_only_that_owners_accounts(api):
    """PRD §4: "GET /ira/accounts | List accounts" — endpoint table.
    PRD §2.5: "Whenever a URL contains a templated id (for example a
    contribution, distribution, or conversion id, or a beneficiary-designation
    or RMD-schedule id), the path segments are resolved left-to-right."
    PRD §2.3: "The `meta` block on a list response carries four pagination
    fields: the echoed `limit`, the echoed `offset`, the `total_count` of rows
    matching the filter prior to pagination, and a boolean `has_more`
    indicating whether further rows remain past the current page."

    Design: Corner/endpoints/list_accounts_filtered_by_owner_returns_only_that_owners_accounts
    """
    set_clock("2026-06-01T00:00:00Z")
    cara = create_owner(
        full_name="Cara", date_of_birth="1981-09-09", tax_id_last4="2929"
    )
    dirk = create_owner(
        full_name="Dirk", date_of_birth="1981-10-10", tax_id_last4="3030"
    )
    open_n_accounts(cara["id"], 2, "TRADITIONAL")
    create_account(dirk["id"], "ROTH")

    res = api.list_accounts(
        TEST_USERS["plan_admin_headers"], params={"owner_id": cara["id"]}
    )
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2, (
        f"filter owner_id={cara['id']} must return Cara's 2 accounts; "
        f"got total_count={meta['total_count']}"
    )
    for row in data:
        assert row["owner_id"] == cara["id"], (
            f"every returned account must belong to filtered owner, "
            f"got owner_id={row['owner_id']!r}"
        )


def test_default_pagination_limits_list_size_and_signals_more(api):
    """PRD §2.3: "All list endpoints accept two query parameters, `limit` and
    `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of
    100; `offset` defaults to 0 and has no upper bound beyond what the
    underlying collection supports."
    PRD §2.3: "The `meta` block on a list response carries four pagination
    fields: the echoed `limit`, the echoed `offset`, the `total_count` of rows
    matching the filter prior to pagination, and a boolean `has_more`
    indicating whether further rows remain past the current page."

    Design: Corner/cross_cutting_layers/pagination_default_limit_caps_list_size
    """
    set_clock("2026-06-01T00:00:00Z")
    kit = create_owner(
        full_name="Kit", date_of_birth="1981-07-07", tax_id_last4="3737"
    )
    open_n_accounts(kit["id"], 12, "TRADITIONAL")

    res = api.list_accounts(
        TEST_USERS["plan_admin_headers"], params={"owner_id": kit["id"]}
    )
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 12, (
        f"total_count must reflect all 12 matching rows, got {meta['total_count']}"
    )
    assert meta["has_more"] is True, (
        f"has_more must be true when total_count (12) > default limit (10), "
        f"got {meta['has_more']!r}"
    )
    assert len(data) <= 10, (
        f"default-limit page must return at most 10 rows, got {len(data)}"
    )
