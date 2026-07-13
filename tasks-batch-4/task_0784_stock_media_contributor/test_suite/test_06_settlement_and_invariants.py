"""Settlement clearing, reversal compensation, and ledger conservation."""
from test_helpers import (
    validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    onboard_active_contributor, get_contributor,
    create_license_tier, create_accepted_asset, create_download,
    setup_accepted_asset_with_settled_download,
)

FINANCE = TEST_USERS["finance_headers"]


def test_settle_before_clearing_is_rejected(api):
    """PRD §3.5: "Settlement is permitted only when the download is still `PENDING` and the current
    logical clock has reached or passed the download's `available_at`; an attempt to settle before
    that instant is rejected with `ERR_NOT_YET_CLEARED`".

    Design: Corner/state_machines/corner_settle_before_clearing_blocked
    """
    create_license_tier(api, code="STANDARD", base_price_cents=1000)
    c = onboard_active_contributor(api, tax_id="US-5")
    asset = create_accepted_asset(api, c["id"])
    dl = create_download(api, asset["id"], "STANDARD")  # available_at 2026-03-31, clock still 2026-03-01
    validate_error(api.settle_download(dl["id"], FINANCE), ApiErrorId.ERR_NOT_YET_CLEARED.value)


def test_settled_balance_visible_immediately(api):
    """PRD §3.5: "On settlement the contributor's `lifetime_earnings_cents` and
    `available_balance_cents` each increase by the download's `royalty_amount_cents`".

    Design: Corner/consistency_model/corner_immediate_balance_visible_same_response
    """
    cid, _asset, _dl_id = setup_accepted_asset_with_settled_download(api)  # royalty 150
    contributor = get_contributor(api, cid)
    assert contributor["available_balance_cents"] == 150
    assert contributor["lifetime_earnings_cents"] == 150


def test_available_download_reverses_to_reversed(api):
    """PRD §3.5: "A download may be reversed as a chargeback, moving it to `REVERSED`."

    Design: Difficulty/non_linear_state_machine/download_available_then_reversed_branch
    """
    cid, _asset, dl_id = setup_accepted_asset_with_settled_download(api)
    reversed_dl = get_success_data(api.reverse_download(dl_id, {"reason": "chargeback"}, FINANCE))
    assert reversed_dl["earning_status"] == "REVERSED"


def test_reverse_available_download_debits_balances(api):
    """PRD §3.5: "Reversing an `AVAILABLE` download is the compensating action for its settlement
    credit: the contributor's `lifetime_earnings_cents` and `available_balance_cents` each decrease
    by that download's `royalty_amount_cents`".

    Design: Difficulty/non_linear_state_machine/download_available_then_reversed_branch
    """
    cid, _asset, dl_id = setup_accepted_asset_with_settled_download(api)
    get_success_data(api.reverse_download(dl_id, {"reason": "chargeback"}, FINANCE))
    contributor = get_contributor(api, cid)
    assert contributor["available_balance_cents"] == 0
    assert contributor["lifetime_earnings_cents"] == 0


def test_settle_then_reverse_conserves_lifetime_earnings(api):
    """PRD §2.7: "Every credit has a matching compensating debit, so a reversal always undoes
    exactly the amount its settlement credited."

    Design: Difficulty/compensating_invariant/settle_then_reverse_conserves_lifetime
    """
    cid, _asset, dl_id = setup_accepted_asset_with_settled_download(api)  # lifetime credited to 150
    get_success_data(api.reverse_download(dl_id, {"reason": "chargeback"}, FINANCE))
    assert get_contributor(api, cid)["lifetime_earnings_cents"] == 0, "credit +150 then debit -150 nets to 0"


def test_settle_then_reverse_conserves_available_balance(api):
    """PRD §3.5: "Reversing an `AVAILABLE` download is the compensating action for its settlement
    credit: the contributor's `lifetime_earnings_cents` and `available_balance_cents` each decrease
    by that download's `royalty_amount_cents`".

    Design: Difficulty/compensating_invariant/settle_then_reverse_conserves_lifetime
    """
    cid, _asset, dl_id = setup_accepted_asset_with_settled_download(api)
    reversed_dl = get_success_data(api.reverse_download(dl_id, {"reason": "chargeback"}, FINANCE))
    assert reversed_dl["earning_status"] == "REVERSED"
    assert get_contributor(api, cid)["available_balance_cents"] == 0
