"""Grant lifecycle gate tests: validation precedence, boundary precision, cross-entity state
dependencies, segregation of duties, charity-vetted gates, minimum-grant, and payout boundaries.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    fixtures, factories,
)
from test_helpers.fixtures import (
    SPONSOR_ADMIN, COMPLIANCE, CONTRIB_ADMIN, advisor_headers, officer_headers,
)


# ===========================================================================
# Priority-pair: state (5) beats segregation_of_duties (7) on grant approve
# ===========================================================================
def test_approve_already_approved_grant_invalid_state_beats_sod(api):
    """PRD 3.10: "Then the generic state check: the target resource must be in a state that permits the requested transition (`ERR_INVALID_STATE`). Only after those structural checks do the business rules apply — the account-active gate (`ERR_ACCOUNT_NOT_ACTIVE`), segregation of duties (`ERR_SEGREGATION_OF_DUTIES`)"

    Design: Difficulty/priority_pair_validation_conflict/grant_approve_invalid_state_beats_segregation_of_duties
    """
    sponsor, charity, account = fixtures.setup_funded_account_with_vetted_charity(
        cash_amount_cents=1000000, advisor_user_id="adv-8")
    grant = fixtures.submit_grant(account["id"], charity["id"], 100000, "adv-8")
    validate_success(api.approve_grant(grant["id"], officer_headers("officer-4")))
    # Re-approve by the SAME user who recommended (adv-8): both state and SoD violated.
    validate_error(api.approve_grant(grant["id"], officer_headers("adv-8")),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_approve_rejected_grant_by_recommender_invalid_state_beats_sod(api):
    """PRD 3.10: "Then the generic state check: the target resource must be in a state that permits the requested transition (`ERR_INVALID_STATE`). Only after those structural checks do the business rules apply — the account-active gate (`ERR_ACCOUNT_NOT_ACTIVE`), segregation of duties (`ERR_SEGREGATION_OF_DUTIES`)"

    Design: Difficulty/priority_pair_validation_conflict/grant_approve_invalid_state_beats_segregation_of_duties
    """
    sponsor, charity, account = fixtures.setup_funded_account_with_vetted_charity(
        cash_amount_cents=1000000, advisor_user_id="adv-8b")
    grant = fixtures.submit_grant(account["id"], charity["id"], 100000, "adv-8b")
    # Reject the grant first (by a different officer), reaching a terminal state.
    validate_success(api.reject_grant(grant["id"], officer_headers("officer-4b")))
    # Approve attempt by the SAME user who recommended (adv-8b): state-invalid AND SoD-violated.
    validate_error(api.approve_grant(grant["id"], officer_headers("adv-8b")),
                   ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Priority-pair: charity_not_vetted (9) beats insufficient_grantable (23) on pay
# ===========================================================================
def test_pay_charity_not_vetted_beats_insufficient_grantable(api):
    """PRD 3.6: "the charity must still be `VETTED` — re-checked precisely because a watchlist or revoke decision may have intervened — failing with `ERR_CHARITY_NOT_VETTED`; and the sum of `cash_balance_cents` and `invested_value_cents` must still be at least the `amount_cents`, failing with `ERR_INSUFFICIENT_GRANTABLE_BALANCE`."
    PRD 3.10: "grantee eligibility (`ERR_INELIGIBLE_GRANTEE`), charity-vetted (`ERR_CHARITY_NOT_VETTED`), minimum-grant (`ERR_BELOW_MINIMUM_GRANT`), valuation-input presence (`ERR_VALUATION_INPUT_MISSING`) and whole-share quantity (`ERR_VALUATION_QUANTITY_INVALID`), pool-open (`ERR_POOL_CLOSED`), legacy-share total (`ERR_SHARE_BPS_NOT_100`), the interval-overlap rules (`ERR_NAV_PERIOD_OVERLAP`, `ERR_RECURRING_GRANT_OVERLAP`), the succession gates (`ERR_NO_CONFIRMED_SUCCESSION`, `ERR_PENDING_GRANTS_BLOCK_CLOSE`, `ERR_SUCCESSION_BENEFICIARY_NOT_VETTED`, `ERR_ACCOUNT_NOT_IN_WIND_DOWN`), the funding checks (`ERR_INSUFFICIENT_CASH`, `ERR_INSUFFICIENT_POOL_UNITS`, `ERR_INSUFFICIENT_GRANTABLE_BALANCE`)"

    Design: Difficulty/priority_pair_validation_conflict/grant_pay_charity_not_vetted_beats_insufficient_grantable
    """
    sponsor, charity, account = fixtures.setup_funded_account_with_vetted_charity(
        cash_amount_cents=100000, advisor_user_id="adv-9")
    grant = fixtures.create_scheduled_grant(
        account["id"], charity["id"], 100000, "adv-9", officer_user_id="officer-5")
    # Drain the account below the grant amount by paying a second smaller grant while the
    # charity is still VETTED (cash 100000 -> 50000 after a 50000 payout). The first grant is
    # now under-funded AND, after watchlisting, its charity is no longer VETTED — doubly invalid.
    drain = fixtures.create_scheduled_grant(
        account["id"], charity["id"], 50000, "adv-9", officer_user_id="officer-5b")
    validate_success(api.pay_grant(drain["id"], officer_headers("officer-5b")))
    get_success_data(api.vet_charity(
        charity["id"], factories.vet_decision_payload("WATCHLIST", vetting_note="under review"),
        COMPLIANCE))
    # Charity-not-vetted (priority 9) precedes insufficient-grantable (priority 23) at pay time.
    validate_error(api.pay_grant(grant["id"], officer_headers("officer-5")),
                   ApiErrorId.ERR_CHARITY_NOT_VETTED.value)


def test_pay_unvetted_charity_beats_insufficient_grantable_via_separate_drain(api):
    """PRD 3.6: "the charity must still be `VETTED` — re-checked precisely because a watchlist or revoke decision may have intervened — failing with `ERR_CHARITY_NOT_VETTED`; and the sum of `cash_balance_cents` and `invested_value_cents` must still be at least the `amount_cents`, failing with `ERR_INSUFFICIENT_GRANTABLE_BALANCE`."
    PRD 3.10: "grantee eligibility (`ERR_INELIGIBLE_GRANTEE`), charity-vetted (`ERR_CHARITY_NOT_VETTED`), minimum-grant (`ERR_BELOW_MINIMUM_GRANT`), valuation-input presence (`ERR_VALUATION_INPUT_MISSING`) and whole-share quantity (`ERR_VALUATION_QUANTITY_INVALID`), pool-open (`ERR_POOL_CLOSED`), legacy-share total (`ERR_SHARE_BPS_NOT_100`), the interval-overlap rules (`ERR_NAV_PERIOD_OVERLAP`, `ERR_RECURRING_GRANT_OVERLAP`), the succession gates (`ERR_NO_CONFIRMED_SUCCESSION`, `ERR_PENDING_GRANTS_BLOCK_CLOSE`, `ERR_SUCCESSION_BENEFICIARY_NOT_VETTED`, `ERR_ACCOUNT_NOT_IN_WIND_DOWN`), the funding checks (`ERR_INSUFFICIENT_CASH`, `ERR_INSUFFICIENT_POOL_UNITS`, `ERR_INSUFFICIENT_GRANTABLE_BALANCE`)"

    Design: Difficulty/priority_pair_validation_conflict/grant_pay_charity_not_vetted_beats_insufficient_grantable
    """
    sponsor, charity, account = fixtures.setup_funded_account_with_vetted_charity(
        cash_amount_cents=100000, advisor_user_id="adv-9b")
    grant = fixtures.create_scheduled_grant(
        account["id"], charity["id"], 100000, "adv-9b", officer_user_id="officer-5c")
    # Drain to 50000 via a second smaller paid grant while still VETTED, then REVOKE the charity.
    # The charity REVOKE also cascades any SCHEDULED grant to CANCELLED, so use a SEPARATE charity
    # for the drain grant to keep the under-test grant SCHEDULED while its own charity is revoked.
    drain_charity = fixtures.create_vetted_charity(sponsor["id"])
    drain = fixtures.create_scheduled_grant(
        account["id"], drain_charity["id"], 50000, "adv-9b", officer_user_id="officer-5d")
    validate_success(api.pay_grant(drain["id"], officer_headers("officer-5d")))
    get_success_data(api.vet_charity(
        charity["id"], factories.vet_decision_payload("WATCHLIST", vetting_note="hold"),
        COMPLIANCE))
    # Under-funded (50000 < 100000) AND charity not VETTED -> charity check (priority 9) wins.
    validate_error(api.pay_grant(grant["id"], officer_headers("officer-5c")),
                   ApiErrorId.ERR_CHARITY_NOT_VETTED.value)


# ===========================================================================
# Boundary precision: grant amount >= minimum_grant_cents
# ===========================================================================
def test_grant_amount_exactly_at_minimum_accepted(api):
    """PRD 3.5: "The grant amount must be at least the sponsor's `minimum_grant_cents`; a smaller amount is rejected with `ERR_BELOW_MINIMUM_GRANT`."

    Design: Difficulty/boundary_precision_check/grant_amount_exactly_at_minimum_grant_cents
    """
    sponsor, charity, account = fixtures.setup_funded_account_with_vetted_charity(
        cash_amount_cents=1000000, advisor_user_id="adv-10")
    version = fixtures.current_account_version(account["id"])
    grant = validate_success(api.create_grant(
        factories.create_grant_payload(account["id"], charity["id"], 5000, version),
        advisor_headers("adv-10")), expected_status=201)
    assert grant["status"] == "SUBMITTED"


def test_grant_amount_below_minimum_rejected(api):
    """PRD 3.5: "The grant amount must be at least the sponsor's `minimum_grant_cents`; a smaller amount is rejected with `ERR_BELOW_MINIMUM_GRANT`."

    Design: Difficulty/boundary_precision_check/grant_amount_exactly_at_minimum_grant_cents
    """
    sponsor, charity, account = fixtures.setup_funded_account_with_vetted_charity(
        cash_amount_cents=1000000, advisor_user_id="adv-10b")
    version = fixtures.current_account_version(account["id"])
    validate_error(api.create_grant(
        factories.create_grant_payload(account["id"], charity["id"], 4999, version),
        advisor_headers("adv-10b")),
        ApiErrorId.ERR_BELOW_MINIMUM_GRANT.value)


# ===========================================================================
# Boundary precision: grant pay zero redemption when cash covers amount
# ===========================================================================
def test_grant_pay_zero_redemption_when_cash_covers(api):
    """PRD 3.6: "First compute the shortfall: the amount needed is the grant's `amount_cents` minus the account's current `cash_balance_cents`. If that shortfall is zero or negative, no pool redemption is needed."

    Design: Difficulty/boundary_precision_check/grant_pay_zero_redemption_when_cash_covers_amount
    """
    sponsor = fixtures.create_sponsor()
    pool = fixtures.create_pool(sponsor["id"], nav_per_unit_cents=2500, fee_bps=50, risk_tier="CONSERVATIVE")
    charity = fixtures.create_vetted_charity(sponsor["id"])
    account = fixtures.create_account(sponsor["id"], "adv-11")
    fixtures.fund_account_with_cash(account["id"], 150000, "adv-11")
    fixtures.buy_into_pool(account["id"], pool["id"], 50000, "adv-11", target_pct_bps=5000)
    # cash now 100000, invested 50000
    grant = fixtures.create_scheduled_grant(
        account["id"], charity["id"], 100000, "adv-11", officer_user_id="officer-6")

    paid = validate_success(api.pay_grant(grant["id"], officer_headers("officer-6")))
    assert paid["status"] == "PAID"

    redeems = get_success_data(api.list_ledger_entries(
        SPONSOR_ADMIN, params={"donor_account_id": account["id"], "entry_type": "POOL_REDEEM"}))
    assert redeems == []  # need_cents == 0 -> nothing redeemed
    allocs = get_success_data(api.list_allocations(
        advisor_headers("adv-11"), params={"donor_account_id": account["id"]}))
    assert allocs[0]["units_micro"] == 20000000  # untouched
    acct = get_success_data(api.get_account(account["id"], SPONSOR_ADMIN))
    assert acct["cash_balance_cents"] == 0
    assert acct["invested_value_cents"] == 50000


def test_grant_pay_covered_by_cash_grant_status_paid(api):
    """PRD 3.6: "Once the cash balance covers the grant, the grant amount is subtracted from `cash_balance_cents`."

    Design: Difficulty/boundary_precision_check/grant_pay_zero_redemption_when_cash_covers_amount
    """
    sponsor = fixtures.create_sponsor()
    pool = fixtures.create_pool(sponsor["id"], nav_per_unit_cents=2500, fee_bps=50, risk_tier="CONSERVATIVE")
    charity = fixtures.create_vetted_charity(sponsor["id"])
    account = fixtures.create_account(sponsor["id"], "adv-11b")
    fixtures.fund_account_with_cash(account["id"], 150000, "adv-11b")
    fixtures.buy_into_pool(account["id"], pool["id"], 50000, "adv-11b", target_pct_bps=5000)
    grant = fixtures.create_scheduled_grant(
        account["id"], charity["id"], 100000, "adv-11b", officer_user_id="officer-6b")
    paid = validate_success(api.pay_grant(grant["id"], officer_headers("officer-6b")))
    assert paid["status"] == "PAID"


# ===========================================================================
# Cross-entity state dependency: grant approve blocked by WATCHLISTED charity
# ===========================================================================
def test_grant_approve_blocked_by_watchlisted_charity(api):
    """PRD 3.5: "Second, the recipient charity must currently be `VETTED`, or the request is rejected with `ERR_CHARITY_NOT_VETTED`."

    Design: Difficulty/cross_entity_state_dependency/grant_approve_blocked_by_watchlisted_charity
    """
    sponsor, charity, account = fixtures.setup_funded_account_with_vetted_charity(
        cash_amount_cents=1000000, advisor_user_id="adv-12")
    grant = fixtures.submit_grant(account["id"], charity["id"], 100000, "adv-12")
    get_success_data(api.vet_charity(
        charity["id"], factories.vet_decision_payload("WATCHLIST", vetting_note="hold"),
        COMPLIANCE))
    validate_error(api.approve_grant(grant["id"], officer_headers("officer-7")),
                   ApiErrorId.ERR_CHARITY_NOT_VETTED.value)
    refreshed = get_success_data(api.get_grant(grant["id"], SPONSOR_ADMIN))
    assert refreshed["status"] == "SUBMITTED"


def test_grant_approve_allowed_once_charity_revetted(api):
    """PRD 3.5: "Second, the recipient charity must currently be `VETTED`, or the request is rejected with `ERR_CHARITY_NOT_VETTED`."
    PRD 3.2: "An **APPROVE** decision moves a charity from `PENDING_VETTING` to `VETTED`, or from `WATCHLISTED` back to `VETTED`."

    Design: Difficulty/cross_entity_state_dependency/grant_approve_blocked_by_watchlisted_charity
    """
    sponsor, charity, account = fixtures.setup_funded_account_with_vetted_charity(
        cash_amount_cents=1000000, advisor_user_id="adv-12b")
    grant = fixtures.submit_grant(account["id"], charity["id"], 100000, "adv-12b")
    get_success_data(api.vet_charity(
        charity["id"], factories.vet_decision_payload("WATCHLIST", vetting_note="hold"),
        COMPLIANCE))
    # While WATCHLISTED, approval is blocked.
    validate_error(api.approve_grant(grant["id"], officer_headers("officer-7b")),
                   ApiErrorId.ERR_CHARITY_NOT_VETTED.value)
    # Re-vetting the charity back to VETTED lifts the cross-entity block; approval now succeeds.
    get_success_data(api.vet_charity(
        charity["id"], factories.vet_decision_payload("APPROVE"), COMPLIANCE))
    approved = validate_success(api.approve_grant(grant["id"], officer_headers("officer-7b")))
    assert approved["status"] == "APPROVED"


# ===========================================================================
# Cross-entity state dependency: contribution settle blocked by WIND_DOWN account
# ===========================================================================
def test_contribution_settle_blocked_by_wind_down_account(api):
    """PRD 3.3: "the target account must be in `status` `ACTIVE` — settling against an account that is not `ACTIVE` is rejected with `ERR_ACCOUNT_NOT_ACTIVE"

    Design: Difficulty/cross_entity_state_dependency/contribution_settle_blocked_by_wind_down_account
    """
    sponsor = fixtures.create_sponsor()
    ben = fixtures.create_vetted_charity(sponsor["id"])
    account = fixtures.create_account(sponsor["id"], "adv-13")
    contrib = get_success_data(api.create_contribution(
        factories.create_cash_contribution_payload(account["id"], 200000),
        advisor_headers("adv-13")))
    plan_beneficiaries = [{"charity_id": ben["id"], "share_bps": 10000}]
    fixtures.create_confirmed_legacy_plan(account["id"], plan_beneficiaries, "adv-13")
    get_success_data(api.wind_down_account(account["id"], SPONSOR_ADMIN))

    validate_error(api.settle_contribution(contrib["id"], CONTRIB_ADMIN),
                   ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE.value)
    refreshed = get_success_data(api.get_contribution(contrib["id"], CONTRIB_ADMIN))
    assert refreshed["status"] == "PENDING"
    receipts = get_success_data(api.list_receipts(
        CONTRIB_ADMIN, params={"contribution_id": contrib["id"]}))
    assert receipts == []


def test_contribution_settle_allowed_when_account_active(api):
    """PRD 3.3: "Before settling, three preconditions are checked: the target account must be in `status` `ACTIVE` — settling against an account that is not `ACTIVE` is rejected with `ERR_ACCOUNT_NOT_ACTIVE"
    PRD 3.3: "When those checks pass, the contribution's fair market value is computed and stamped into `fair_market_value_cents`, where it becomes irrevocable."

    Design: Difficulty/cross_entity_state_dependency/contribution_settle_blocked_by_wind_down_account
    """
    sponsor = fixtures.create_sponsor()
    account = fixtures.create_account(sponsor["id"], "adv-13b")  # account stays ACTIVE
    contrib = get_success_data(api.create_contribution(
        factories.create_cash_contribution_payload(account["id"], 200000),
        advisor_headers("adv-13b")))
    settled = validate_success(api.settle_contribution(contrib["id"], CONTRIB_ADMIN))
    assert settled["status"] == "SETTLED"
    assert settled["fair_market_value_cents"] == 200000


# ===========================================================================
# Corner: validations — grant/charity/contribution gates
# ===========================================================================
def test_settle_securities_quantity_not_divisible_rejected(api):
    """PRD 3.3: "for a securities gift the `quantity_milli` must represent whole shares, meaning it must be evenly divisible by 1000 — a `quantity_milli` not divisible by 1000 is rejected with `ERR_VALUATION_QUANTITY_INVALID`."

    Design: Corner/validations/settle_securities_quantity_not_divisible_rejected
    """
    sponsor = fixtures.create_sponsor()
    account = fixtures.create_account(sponsor["id"], "adv-v1")
    contrib = get_success_data(api.create_contribution(
        factories.create_securities_contribution_payload(
            account["id"], 100500, ticker="FRAC",
            high_price_cents=1000, low_price_cents=900, thinly_traded=False),
        advisor_headers("adv-v1")))
    validate_error(api.settle_contribution(contrib["id"], CONTRIB_ADMIN),
                   ApiErrorId.ERR_VALUATION_QUANTITY_INVALID.value)


def test_settle_securities_missing_pricing_rejected(api):
    """PRD 3.3: "a securities gift needs `high_price_cents` and `low_price_cents` (or `closing_price_cents` when `thinly_traded` is true)"
    PRD (cont.): "a missing required input is rejected with `ERR_VALUATION_INPUT_MISSING"

    Design: Corner/validations/settle_securities_missing_pricing_rejected
    """
    sponsor = fixtures.create_sponsor()
    account = fixtures.create_account(sponsor["id"], "adv-v2")
    contrib = get_success_data(api.create_contribution(
        factories.create_securities_contribution_payload(
            account["id"], 100000, ticker="NOPX", thinly_traded=False),
        advisor_headers("adv-v2")))
    validate_error(api.settle_contribution(contrib["id"], CONTRIB_ADMIN),
                   ApiErrorId.ERR_VALUATION_INPUT_MISSING.value)


def test_duplicate_charity_ein_rejected(api):
    """PRD 3.2: "A charity's `ein` must be unique among the non-`REVOKED` charities under the same sponsor; registering a charity whose EIN is already held by a non-revoked charity under that sponsor is rejected with `ERR_DUPLICATE_CHARITY_EIN`."

    Design: Corner/validations/duplicate_charity_ein_rejected
    """
    sponsor = fixtures.create_sponsor()
    fixtures.create_charity(sponsor["id"], legal_name="First", ein="23-9000003")
    validate_error(api.create_charity(
        factories.create_charity_payload(sponsor["id"], legal_name="Second", ein="23-9000003", ntee_code="A21"),
        COMPLIANCE),
        ApiErrorId.ERR_DUPLICATE_CHARITY_EIN.value)


def test_vet_private_foundation_ineligible(api):
    """PRD 3.2: "Approval is only permitted when the charity is not a private foundation: if `is_private_foundation` is true, approval is rejected with `ERR_INELIGIBLE_GRANTEE`, because private foundations are not eligible DAF grantees."

    Design: Corner/validations/vet_private_foundation_ineligible_grantee
    """
    sponsor = fixtures.create_sponsor()
    charity = fixtures.create_charity(sponsor["id"], legal_name="PF Org", ntee_code="T20", is_private_foundation=True)
    validate_error(api.vet_charity(
        charity["id"], factories.vet_decision_payload("APPROVE"), COMPLIANCE),
        ApiErrorId.ERR_INELIGIBLE_GRANTEE.value)
    refreshed = get_success_data(api.get_charity(charity["id"], COMPLIANCE))
    assert refreshed["status"] == "PENDING_VETTING"


def test_grant_reject_segregation_of_duties(api):
    """PRD 3.5: "Rejection is also subject to segregation of duties — the rejecting officer's `X-User-ID` must differ from `recommended_by_user_id`, failing with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/grant_reject_segregation_of_duties_rejected
    """
    sponsor, charity, account = fixtures.setup_funded_account_with_vetted_charity(
        cash_amount_cents=1000000, advisor_user_id="dual-user")
    grant = fixtures.submit_grant(account["id"], charity["id"], 100000, "dual-user")
    validate_error(api.reject_grant(grant["id"], officer_headers("dual-user")),
                   ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    refreshed = get_success_data(api.get_grant(grant["id"], SPONSOR_ADMIN))
    assert refreshed["status"] == "SUBMITTED"


def test_grant_schedule_insufficient_grantable(api):
    """PRD 3.6: "The account must have enough total value to cover the grant: the sum of `cash_balance_cents` and `invested_value_cents` must be at least the grant's `amount_cents`, or the request is rejected with `ERR_INSUFFICIENT_GRANTABLE_BALANCE`."

    Design: Corner/validations/grant_schedule_insufficient_grantable_rejected
    """
    sponsor, charity, account = fixtures.setup_funded_account_with_vetted_charity(
        cash_amount_cents=80000, advisor_user_id="adv-v10")
    grant = fixtures.create_approved_grant(
        account["id"], charity["id"], 100000, "adv-v10", officer_user_id="officer-v10")
    validate_error(api.schedule_grant(grant["id"], officer_headers("officer-v10")),
                   ApiErrorId.ERR_INSUFFICIENT_GRANTABLE_BALANCE.value)


# ===========================================================================
# Corner: RBAC segregation of duties on approve
# ===========================================================================
def test_segregation_grant_approve_same_recommender(api):
    """PRD 3.5: "First, segregation of duties: the approving officer's `X-User-ID` must differ from the grant's `recommended_by_user_id`, or the request is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/segregation_grant_approve_same_recommender
    """
    sponsor, charity, account = fixtures.setup_funded_account_with_vetted_charity(
        cash_amount_cents=1000000, advisor_user_id="shared-id")
    grant = fixtures.submit_grant(account["id"], charity["id"], 100000, "shared-id")
    validate_error(api.approve_grant(grant["id"], officer_headers("shared-id")),
                   ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    refreshed = get_success_data(api.get_grant(grant["id"], SPONSOR_ADMIN))
    assert refreshed["status"] == "SUBMITTED"
