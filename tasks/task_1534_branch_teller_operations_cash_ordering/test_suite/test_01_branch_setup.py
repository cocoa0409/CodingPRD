"""Branch/teller/account onboarding: creation contract, defaults, 404s, pagination."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    is_valid_uuid, TEST_USERS, NON_EXISTENT_UUID,
    make_branch, make_teller, make_account, create_branch_payload,
)

MGR = TEST_USERS["manager_headers"]
AUD = TEST_USERS["auditor_headers"]


def test_branch_creation_returns_declared_fields(api):
    """PRD §3.1: "a `BranchManager` establishes the branch itself, supplying its
    `name` and three policy numbers that will govern everything that follows:
    `drawer_limit_cents`, the per-drawer cash cap enforced at the vault window;
    `vault_cash_cents`, the physical cash on hand at opening; and
    `over_short_investigation_threshold_cents`" and "A new branch is `OPEN`".

    Design: Corner/entities/branch_creation_returns_declared_fields
    """
    resp = api.create_branch(create_branch_payload(), MGR)
    data = validate_success(resp, 201)
    assert is_valid_uuid(data["id"])
    assert data["name"] == "Main St"
    assert data["drawer_limit_cents"] == 1_000_000
    assert data["vault_cash_cents"] == 50_000_000
    assert data["over_short_investigation_threshold_cents"] == 1_000
    assert data["status"] == "OPEN"
    assert data["version"] == 1


def test_teller_creation_defaults_active(api):
    """PRD §3.1: "Tellers join the branch when the manager records a
    `display_name`; each new teller starts `ACTIVE`."

    Design: Corner/entities/teller_creation_defaults_active
    """
    branch = make_branch(api)
    resp = api.create_teller(branch["id"], {"display_name": "T"}, MGR)
    data = validate_success(resp, 201)
    assert data["status"] == "ACTIVE"
    assert data["branch_id"] == branch["id"]


def test_get_nonexistent_branch_returns_not_found(api):
    """PRD §2.8: "a child identifier that exists but belongs to a different
    parent is reported as not found (`ERR_NOT_FOUND`, HTTP 404)."

    Design: Corner/entities/get_nonexistent_branch_returns_not_found
    """
    resp = api.get_branch(NON_EXISTENT_UUID, MGR)
    validate_error(resp, "ERR_NOT_FOUND", 404)


def test_branch_create_client_id_input_ignored(api):
    """PRD §2.4: "any client-supplied `id` in a creation payload is ignored."

    Design: Corner/entities/branch_create_client_id_input_ignored
    """
    payload = create_branch_payload()
    payload["id"] = "11111111-1111-1111-1111-111111111111"
    resp = api.create_branch(payload, MGR)
    data = validate_success(resp, 201)
    assert data["id"] != "11111111-1111-1111-1111-111111111111"
    assert is_valid_uuid(data["id"])


def test_branch_list_pagination_envelope(api):
    """PRD §2.3: "`limit` defaults to 10, must be at least 1, and may not
    exceed 100; `offset` defaults to 0. List responses report `limit`,
    `offset`, `total_count`, and `has_more` inside `meta`" and "All list
    endpoints return their resources ordered by `created_at` ascending".

    Design: Corner/entities/branch_list_pagination_envelope
    """
    b1 = make_branch(api, name="B1")
    b2 = make_branch(api, name="B2")
    b3 = make_branch(api, name="B3")
    page1, meta1 = validate_paginated(api.list_branches(AUD, {"limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert [b["name"] for b in page1] == ["B1", "B2"]
    page2, meta2 = validate_paginated(api.list_branches(AUD, {"limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["has_more"] is False
    assert page2[0]["name"] == "B3"
    assert page1[0]["id"] == b1["id"] and page1[1]["id"] == b2["id"] and page2[0]["id"] == b3["id"]

def test_close_account_with_balance_rejected(api):
    """PRD §3.1: "Closing an account is permitted only when its `balance_cents`
    is exactly zero and no hold on it is still `ACTIVE` — otherwise the attempt
    is refused with `ERR_ACCOUNT_NOT_SETTLED`."

    Design: Corner/errors/close_account_with_balance_rejected
    """
    branch = make_branch(api)
    acct = make_account(api, branch, balance_cents=10_000)
    resp = api.close_account(acct["id"], MGR)
    validate_error(resp, "ERR_ACCOUNT_NOT_SETTLED", 409)
