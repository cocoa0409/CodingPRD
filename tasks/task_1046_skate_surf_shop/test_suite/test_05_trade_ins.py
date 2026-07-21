"""Trade-ins: the cash-vs-store-credit buyout fork, the consignment sell branch,
and the appraisal authorization / existence guards.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS, get_success_data,
    create_member, create_appraised_tradein, create_listed_tradein,
    create_trade_in_payload,
)

SM = TEST_USERS["shop_manager_headers"]
ASSOC = TEST_USERS["associate_headers"]
NON_EXISTENT = "00000000-0000-4000-8000-000000000abc"


def test_tradein_cash_buyout_pays_50_percent(api):
    """PRD §3.6: "a `CASH` payout is 50 percent of `appraised_value_cents`, rounded
    half-up, and is paid physically with no change to the member's balance".

    Design: Difficulty/dual_variant_calc/tradein_cash_vs_store_credit_payout
    """
    member = create_member(api)
    ti, member = create_appraised_tradein(api, appraised_value_cents=10000, member=member)
    resp = api.buyout_trade_in(ti["id"], {"payout_method": "CASH"}, ASSOC)
    data = validate_success(resp, 200)
    assert data["payout_cents"] == 5000
    assert data["payout_method"] == "CASH"
    member_after = get_success_data(api.get_member(member["id"], SM))
    assert member_after["store_credit_cents"] == 0


def test_tradein_store_credit_buyout_pays_70_percent(api):
    """PRD §3.6: "a `STORE_CREDIT` payout is 70 percent of `appraised_value_cents`,
    rounded half-up, and is added to the member's `store_credit_cents` (so store
    credit is strictly more generous than cash for the same appraised value)."

    Design: Difficulty/dual_variant_calc/tradein_cash_vs_store_credit_payout
    """
    member = create_member(api)
    ti, member = create_appraised_tradein(api, appraised_value_cents=10000, member=member)
    resp = api.buyout_trade_in(ti["id"], {"payout_method": "STORE_CREDIT"}, ASSOC)
    data = validate_success(resp, 200)
    assert data["payout_cents"] == 7000
    member_after = get_success_data(api.get_member(member["id"], SM))
    assert member_after["store_credit_cents"] == 7000


def test_consignment_sell_pays_70_percent_of_list(api):
    """PRD §3.6: "Selling a `LISTED` item moves it to `SOLD`, computes `payout_cents`
    as 70 percent of `list_price_cents` (a 30 percent consignment fee), rounded
    half-up, records the `payout_method` as `CONSIGNMENT`, adds the payout to the
    member's `store_credit_cents`, and stamps `settled_at`."

    Design: Difficulty/non_linear_state_machine/tradein_consignment_branch_credits_store_credit
    """
    member = create_member(api)
    ti, member = create_listed_tradein(
        api, appraised_value_cents=10000, list_price_cents=20000, member=member)
    resp = api.sell_trade_in(ti["id"], ASSOC)
    data = validate_success(resp, 200)
    assert data["status"] == "SOLD"
    assert data["payout_cents"] == 14000
    assert data["payout_method"] == "CONSIGNMENT"


def test_consignment_sell_credits_store_credit(api):
    """PRD §3.6: "Selling a `LISTED` item moves it to `SOLD`, computes `payout_cents`
    as 70 percent of `list_price_cents` (a 30 percent consignment fee), rounded
    half-up, records the `payout_method` as `CONSIGNMENT`, adds the payout to the
    member's `store_credit_cents`, and stamps `settled_at`."

    Design: Difficulty/non_linear_state_machine/tradein_consignment_branch_credits_store_credit
    """
    member = create_member(api)
    ti, member = create_listed_tradein(
        api, appraised_value_cents=10000, list_price_cents=20000, member=member)
    api.sell_trade_in(ti["id"], ASSOC)
    member_after = get_success_data(api.get_member(member["id"], SM))
    assert member_after["store_credit_cents"] == 14000


def test_associate_cannot_appraise(api):
    """PRD §3.6: "Only a `ShopManager` may appraise a `RECEIVED` trade-in, supplying
    its `appraised_value_cents` (which is recorded and must be zero or greater) and
    stamping `appraised_at`, moving it to `APPRAISED`."

    Design: Corner/rbac/associate_cannot_appraise_tradein_returns_unauthorized
    """
    member = create_member(api)
    ti = get_success_data(api.create_trade_in(create_trade_in_payload(member["id"]), ASSOC))
    resp = api.appraise_trade_in(ti["id"], {"appraised_value_cents": 100}, ASSOC)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_appraise_nonexistent_tradein_not_found(api):
    """PRD §2.5: "3. **Existence** — the path identifier and every body foreign key
    resolve to an existing resource, checked left to right, otherwise the matching
    `ERR_<ENTITY>_NOT_FOUND` (404)."

    Design: Corner/validations/appraise_existence_before_state_nonexistent_tradein_returns_not_found
    """
    resp = api.appraise_trade_in(NON_EXISTENT, {"appraised_value_cents": 100}, SM)
    validate_error(resp, ApiErrorId.ERR_TRADEIN_NOT_FOUND.value)
