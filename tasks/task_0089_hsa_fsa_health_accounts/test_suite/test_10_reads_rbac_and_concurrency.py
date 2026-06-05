"""Filtered reads, RBAC gates, optimistic-concurrency on account writes, and immediate
consistency of derived balances.

Translates Corner/endpoints, Corner/rbac, Corner/cross_cutting_complexity_layers, and
Corner/consistency_model instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, TEST_USERS,
    setup_active_hsa, setup_active_fsa, file_claim, post_contribution,
    set_clock, create_plan_year, create_participant, create_and_activate_fsa,
    make_participant_headers, ApiErrorId,
)

ADMIN = TEST_USERS["plan_admin_headers"]


# --- Filtered reads ---

def test_list_claims_filtered_by_account(api):
    """PRD §3.9: "Claims can be listed and filtered by `account_id`, by `participant_id`, or
    by `status`."

    Two claims on one account: GET /claims?account_id=<id> returns exactly those two.

    Design: Corner/endpoints/list_claims_filtered_by_account
    """
    py, p, acc = setup_active_fsa(account_type="HEALTH_FSA", elected_amount_cents=200000)
    file_claim(acc["id"], p["id"], service_date="2026-04-01",
               expense_category="MEDICAL", claimed_amount_cents=20000, substantiated=True)
    file_claim(acc["id"], p["id"], service_date="2026-04-02",
               expense_category="DENTAL", claimed_amount_cents=30000, substantiated=True)
    rows, meta = validate_paginated(api.list_claims(ADMIN, params={"account_id": acc["id"]}))
    assert meta["total_count"] == 2
    assert len(rows) == 2
    assert all(c["account_id"] == acc["id"] for c in rows)


def test_account_ledger_entries_readable(api):
    """PRD §2.5: "Every movement of money is recorded as an immutable `LedgerEntry` so the
    account history is reconstructable for IRS audit."
    PRD §3.3: "A successful contribution post appends a `CONTRIBUTION` `LedgerEntry`".

    After one 100000 contribution the audit trail filtered on CONTRIBUTION has exactly one
    entry of magnitude 100000.

    Design: Corner/endpoints/account_ledger_entries_readable
    """
    py, p, acc = setup_active_hsa(elected_amount_cents=437500)
    post_contribution(acc["id"], 100000, acc["version"], source="PAYROLL")
    rows, _ = validate_paginated(api.get_account_ledger_entries(
        acc["id"], ADMIN, params={"entry_type": "CONTRIBUTION"}))
    assert len(rows) == 1
    assert rows[0]["entry_type"] == "CONTRIBUTION"
    assert rows[0]["amount_cents"] == 100000


# --- RBAC ---

def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or `X-User-Role` is not one of the recognized
    role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/unauthenticated_missing_role_header
    """
    no_role_headers = {"X-User-ID": "someone", "Content-Type": "application/json"}
    resp = api.list_participants(no_role_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_participant_cannot_adjudicate(api):
    """PRD §2.1: "When the headers are well-formed but the acting role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP
    403)."

    A Participant calling the Adjudicator-only adjudicate endpoint is forbidden.

    Design: Corner/rbac/participant_cannot_adjudicate
    """
    py, p, acc = setup_active_fsa(
        account_type="HEALTH_FSA", elected_amount_cents=100000,
        auto_adjudication_threshold_cents=1000000)
    claim = file_claim(acc["id"], p["id"], service_date="2026-04-01",
                       expense_category="MEDICAL", claimed_amount_cents=20000,
                       substantiated=True)
    resp = api.adjudicate_claim(claim["id"], {"decision": "APPROVE"},
                                make_participant_headers(p["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    after = validate_success(api.get_claim(claim["id"], ADMIN))
    assert after["status"] == "SUBMITTED"


def test_participant_cannot_submit_claim_for_other_owner(api):
    """PRD §2.1: "A `Participant` who acts on a claim or account they do not own is rejected
    with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD §3.4: "When a `Participant` files a claim, ownership is enforced: the claim's account
    must belong to that participant, or the request is rejected with
    `ERR_NOT_RESOURCE_OWNER`."

    P2 filing against P1's account is rejected.

    Design: Corner/rbac/participant_cannot_submit_claim_for_other_owner
    """
    set_clock("2026-06-01T00:00:00Z")
    py = create_plan_year()
    p1 = create_participant(email="p1@x.com")
    p2 = create_participant(email="p2@x.com", birth_date="1991-01-01")
    acc = create_and_activate_fsa(p1["id"], py["id"], account_type="HEALTH_FSA",
                                  elected_amount_cents=100000)
    resp = api.create_claim(
        {"account_id": acc["id"], "service_date": "2026-04-01",
         "expense_category": "MEDICAL", "claimed_amount_cents": 20000,
         "substantiated": True},
        make_participant_headers(p2["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


# --- Optimistic concurrency ---

def test_stale_expected_account_version_on_contribution_rejected(api):
    """PRD §2.9: "if the poster's `expected_account_version` does not equal the live
    `version`, the post is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412)".

    A second contribution reusing the pre-first-contribution version (now stale) is rejected;
    contributed_cents reflects only the first contribution.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_account_version_on_contribution
    """
    py, p, acc = setup_active_hsa(elected_amount_cents=437500)
    stale_version = acc["version"]
    post_contribution(acc["id"], 50000, stale_version, source="PAYROLL")  # advances version
    resp = api.create_contribution(
        acc["id"],
        {"amount_cents": 50000, "source": "EMPLOYER", "posted_at": "2026-03-01T00:00:00Z",
         "expected_account_version": stale_version},
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_ACCOUNT_VERSION.value)
    after = validate_success(api.get_account(acc["id"], ADMIN))
    assert after["contributed_cents"] == 50000, "stale second contribution not applied"


def test_account_version_increments_once_per_mutation(api):
    """PRD §2.4: "a `version` integer that starts at 1 and increments by one on every
    mutation to the resource."
    PRD §3.2: "On activation the server runs the available-balance computation to seed the
    account's spendable balance and increments the account's `version` by one."

    version == 1 at create, 2 after activate, 3 after one contribution.

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_every_write
    """
    set_clock("2026-06-01T00:00:00Z")
    py = create_plan_year()
    p = create_participant(email="vi@x.com", hdhp_covered=True)
    created = validate_success(api.create_account(
        {"participant_id": p["id"], "plan_year_id": py["id"], "account_type": "HSA",
         "coverage_tier": "SELF_ONLY", "elected_amount_cents": 437500}, ADMIN),
        expected_status=201)
    assert created["version"] == 1
    activated = validate_success(api.activate_account(created["id"], ADMIN))
    assert activated["version"] == 2
    post_contribution(created["id"], 10000, activated["version"], source="PAYROLL")
    after = validate_success(api.get_account(created["id"], ADMIN))
    assert after["version"] == 3


# --- Immediate consistency ---

def test_contribution_balance_visible_on_immediate_read(api):
    """PRD §2.4: "Wherever a derived field on an `Account` (such as `available_balance_cents`)
    is recomputed, that recomputation is itself a mutation of the `Account`".
    PRD §3.3: "recomputes the account's `contributed_cents` and `available_balance_cents` via
    the available-balance rule".

    A 70000 contribution is reflected in available_balance_cents on the very next GET.

    Design: Corner/consistency_model/immediate_contribution_balance_visible_on_read
    """
    py, p, acc = setup_active_hsa(elected_amount_cents=437500)
    post_contribution(acc["id"], 70000, acc["version"], source="PAYROLL")
    after = validate_success(api.get_account(acc["id"], ADMIN))
    assert after["available_balance_cents"] == 70000
