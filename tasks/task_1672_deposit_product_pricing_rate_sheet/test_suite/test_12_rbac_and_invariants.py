"""Role-based access denials and the open-balance conservation invariant
(PRD §2.1, §2.5, §3.2, §3.5, §4)."""
from test_helpers import (
    ApiErrorId,
    create_draft_sheet,
    create_effective_sheet,
    create_funding_curve_payload,
    create_product,
    create_rate_sheet_payload,
    deploy_all,
    list_sheet_notices,
    open_account,
    promote_sheet_to_scheduled,
    send_all_notices,
    set_clock,
    single_tier,
    tier,
    validate_error,
    validate_success,
    validate_paginated,
)
from test_helpers import TEST_USERS

ANALYST = TEST_USERS["analyst_headers"]
BANKER = TEST_USERS["banker_headers"]
ADMIN = TEST_USERS["admin_headers"]

CONS_TIERS_V1 = [tier(0, 0, 1_000_000, 100), tier(1, 1_000_000, -1, 150)]
CONS_TIERS_V2 = [tier(0, 0, 1_000_000, 90), tier(1, 1_000_000, -1, 120)]


def test_rbac_role_denial_returns_forbidden(api, banker_headers, analyst_headers,
                                            treasury_headers):
    """PRD §2.1: "A request whose role is not permitted on the target endpoint
    is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: rate sheet creation is the `PricingAnalyst`'s, funding-curve
    publication the `TreasuryOfficer`'s, notice resolution the
    `ComplianceOfficer`'s, and the clock the `OperationsAdmin`'s.

    Design: Corner/rbac/rbac_role_denial_returns_forbidden
    """
    product = create_product(product_code="RB1")
    sheet = create_draft_sheet(product["id"], effective_date="2026-08-10",
                               tiers=single_tier(100))
    promote_sheet_to_scheduled(sheet["id"])
    notice_id = list_sheet_notices(sheet["id"])[0]["id"]

    # A BranchBanker cannot draft rate sheets.
    resp = api.create_rate_sheet(
        create_rate_sheet_payload(product["id"], market_code="US-EAST"),
        banker_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    # A PricingAnalyst cannot publish funding curves, resolve notices, or set
    # the clock.
    resp = api.create_funding_curve(
        create_funding_curve_payload(curve_date="2026-08-01"), analyst_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
    resp = api.resolve_disclosure_notice(notice_id, {"action": "SEND"}, analyst_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
    resp = api.set_clock({"to_iso8601": "2026-08-15T00:00:00Z"}, analyst_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    # The owning role succeeds.
    created = validate_success(api.create_funding_curve(
        create_funding_curve_payload(curve_date="2026-08-01"), treasury_headers), 201)
    assert created["curve_date"] == "2026-08-01"


def _conservation_scenario(api):
    """P-CONS: S1 EFFECTIVE 2026-08-15; A1 5,000,000 OPEN, A2 500,000 OPEN,
    A3 700,000 then CLOSED; S2 (90/120 bp) staged for 2026-09-01 with the
    clock on the activation date."""
    product = create_product(product_code="CONS")
    s1 = create_effective_sheet(product_id=product["id"],
                                effective_date="2026-08-15", tiers=CONS_TIERS_V1)["sheet"]
    a1 = open_account(product["id"], opening_balance_cents=5_000_000, customer_ref="CC1")
    a2 = open_account(product["id"], opening_balance_cents=500_000, customer_ref="CC2")
    a3 = open_account(product["id"], opening_balance_cents=700_000, customer_ref="CC3")
    validate_success(api.deposit_account_action(a3["id"], {"action": "CLOSE"}, BANKER))

    s2 = create_draft_sheet(product["id"], effective_date="2026-09-01",
                            tiers=CONS_TIERS_V2)
    promote_sheet_to_scheduled(s2["id"])
    deploy_all(s2["id"])
    send_all_notices(s2["id"])
    set_clock("2026-09-01")
    return product, s1, s2, a1, a2, a3


def _open_balance_sum(api, product_id) -> int:
    page, meta = validate_paginated(api.list_deposit_accounts(
        BANKER, params={"product_id": product_id, "market_code": "US-WEST",
                        "lifecycle": "OPEN", "limit": 100}))
    assert meta["has_more"] is False
    return sum(a["balance_cents"] for a in page)


def test_activation_cascade_conserves_open_balances(api, analyst_headers):
    """PRD §3.2: "accounts of variable-rate products (`term_months` equal to
    zero) are re-pointed — `sheet_id` set to the new sheet, `base_rate_bp` and
    `current_rate_bp` recomputed, version bumped" — repricing touches rates,
    not posted balances.
    PRD §3.5: "Closing does not post final interest automatically, and a
    `CLOSED` account drops out of the combined relationship balance (§3.7)."

    Design: Difficulty/compensating_invariant/rate_operations_conserve_total_open_balances
    """
    product, _, s2, a1, _, _ = _conservation_scenario(api)
    assert _open_balance_sum(api, product["id"]) == 5_500_000  # A3's 700,000 excluded

    validate_success(api.activate_rate_sheet(s2["id"], analyst_headers))

    a1_now = validate_success(api.get_deposit_account(a1["id"], BANKER))
    assert a1_now["current_rate_bp"] == 120        # repriced by the cascade
    assert a1_now["balance_cents"] == 5_000_000    # balance untouched
    assert _open_balance_sum(api, product["id"]) == 5_500_000


def test_compensating_balance_pair_conserves_total(api, analyst_headers,
                                                   banker_headers):
    """PRD §3.5: "A successful adjustment recomputes the account's tier base
    and current rate, refreshes `qualifying_balance_cents` on the customer's
    `ENROLLED` bundle enrollments, and bumps the account version."
    PRD §2.7: "Adjusting an account balance (`PATCH /deposit-accounts/{id}`)
    requires the non-optional field `expected_account_version`, carrying the
    account `version` the client last observed."

    Design: Difficulty/compensating_invariant/rate_operations_conserve_total_open_balances
    """
    product, _, s2, a1, _, _ = _conservation_scenario(api)
    validate_success(api.activate_rate_sheet(s2["id"], analyst_headers))

    # +1,000,000 then -1,000,000, each with the freshly observed version.
    current = validate_success(api.get_deposit_account(a1["id"], banker_headers))
    up = validate_success(api.patch_deposit_account(
        a1["id"], {"expected_account_version": current["version"],
                   "balance_cents": 6_000_000}, banker_headers))
    assert up["balance_cents"] == 6_000_000
    down = validate_success(api.patch_deposit_account(
        a1["id"], {"expected_account_version": up["version"],
                   "balance_cents": 5_000_000}, banker_headers))
    assert down["balance_cents"] == 5_000_000

    # The compensating pair leaves the conserved total exactly where it was.
    assert _open_balance_sum(api, product["id"]) == 5_500_000
