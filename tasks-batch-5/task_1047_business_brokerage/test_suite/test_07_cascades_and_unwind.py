"""Transitive cascades on acceptance and deal-withdrawal, plus escrow-cash conservation."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_broker_headers, make_seller_headers,
)
from test_helpers import fixtures as fx


# ---------------------------------------------------------------------------
# Design: Difficulty/transitive_cascade/loi_accept_withdraws_rival_deals_and_lois
# ---------------------------------------------------------------------------
class TestAcceptanceCascade:
    def _accept_winner(self, api):
        s = fx.setup_two_rival_qualified_deals(api)
        validate_success(api.accept_loi(s["loi_a"]["id"], make_seller_headers(s["seller"]["id"])))
        return s

    def test_accept_advances_winning_deal_and_listing(self, api):
        """PRD §3.6: "When the seller accepts, the offer becomes `ACCEPTED` and the deal advances
        from `QUALIFIED` to `UNDER_LOI`."
        PRD §3.6: "The listing advances from `ACTIVE` to `UNDER_LOI`, and that listing transition
        in turn withdraws the competition: every **other** deal on the same listing whose status
        is `PROSPECT` or `QUALIFIED` is automatically driven to `WITHDRAWN`."

        Design: Difficulty/transitive_cascade/loi_accept_withdraws_rival_deals_and_lois
        """
        s = self._accept_winner(api)
        broker_hdr = make_broker_headers(s["broker"]["id"])
        deal_a = validate_success(api.get_deal(s["deal_a"]["id"], broker_hdr))
        listing = validate_success(api.get_listing(s["listing"]["id"], broker_hdr))
        assert deal_a["status"] == "UNDER_LOI"
        assert listing["status"] == "UNDER_LOI"

    def test_accept_withdraws_rival_deal_and_releases_buyer_capital(self, api):
        """PRD §3.6: "every **other** deal on the same listing whose status is `PROSPECT` or
        `QUALIFIED` is automatically driven to `WITHDRAWN`."
        PRD §3.10: "any non-terminal offer on the deal is driven to `WITHDRAWN`, which releases
        that offer's earnest from the buyer's `committed_capital_cents`."

        Design: Difficulty/transitive_cascade/loi_accept_withdraws_rival_deals_and_lois
        """
        s = self._accept_winner(api)
        broker_hdr = make_broker_headers(s["broker"]["id"])
        deal_b = validate_success(api.get_deal(s["deal_b"]["id"], broker_hdr))
        assert deal_b["status"] == "WITHDRAWN"

        lois_b, _meta = _paginate(api.list_lois(s["deal_b"]["id"], broker_hdr))
        loi_b = next(r for r in lois_b if r["id"] == s["loi_b"]["id"])
        assert loi_b["status"] == "WITHDRAWN"

        buyer_b = fx.get_buyer(api, s["buyer_b"]["id"])
        assert buyer_b["committed_capital_cents"] == 0
        assert buyer_b["available_capital_cents"] == 30_000_000


def _paginate(resp):
    from test_helpers import validate_paginated
    return validate_paginated(resp)


# ---------------------------------------------------------------------------
# Design: Difficulty/transitive_cascade/deal_withdraw_cancels_escrow_and_refunds_buyer
# ---------------------------------------------------------------------------
class TestDealWithdrawFromEscrow:
    def _withdraw_from_escrow(self, api, buyer_proof=30_000_000):
        s = fx.setup_deal_escrow_funded(api, buyer_proof_of_funds_cents=buyer_proof)
        validate_success(
            api.withdraw_deal(
                s["deal"]["id"], make_broker_headers(s["broker"]["id"]),
                {"reason": "Buyer walked at closing table"},
            )
        )
        return s

    def test_withdraw_cancels_escrow_and_refunds_buyer(self, api):
        """PRD §3.10: "the escrow account is cancelled — an `OPENED` or `FUNDED` account moves to
        `CANCELLED`, its held `balance_cents` is released back to the buyer, that released amount
        is subtracted from the buyer's `escrowed_cents`, and the account's `balance_cents` is
        reset to zero."

        Design: Difficulty/transitive_cascade/deal_withdraw_cancels_escrow_and_refunds_buyer
        """
        s = self._withdraw_from_escrow(api)
        broker_hdr = make_broker_headers(s["broker"]["id"])
        deal = validate_success(api.get_deal(s["deal"]["id"], broker_hdr))
        escrow, _meta = _paginate(api.list_escrow(s["deal"]["id"], broker_hdr))
        acct = next(r for r in escrow if r["id"] == s["escrow"]["id"])
        assert deal["status"] == "WITHDRAWN"
        assert acct["status"] == "CANCELLED"
        assert acct["balance_cents"] == 0
        buyer = fx.get_buyer(api, s["buyer"]["id"])
        assert buyer["escrowed_cents"] == 0

    def test_withdraw_from_escrow_reopens_listing(self, api):
        """PRD §3.10: "The accepted offer is driven to `WITHDRAWN` (releasing its
        `committed_capital_cents`), the listing is re-opened from `IN_ESCROW` back to `ACTIVE`,
        and the deal becomes `WITHDRAWN`."

        Design: Difficulty/transitive_cascade/deal_withdraw_cancels_escrow_and_refunds_buyer
        """
        s = self._withdraw_from_escrow(api)
        listing = fx.get_listing(api, s["broker"]["id"], s["listing"]["id"])
        assert listing["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Design: Difficulty/compensating_invariant/escrow_cash_conserved_across_deposit_cancel
# ---------------------------------------------------------------------------
class TestEscrowCashConservation:
    def test_deposit_raises_escrowed_cash(self, api):
        """PRD §3.8: "On success the amount is added to the account's `balance_cents`, the same
        amount is added to the buyer's `escrowed_cents`, and the account moves from `OPENED` to
        `FUNDED`."
        PRD §2.8: "the system derives a read-only `available_capital_cents`, defined as
        `proof_of_funds_cents` minus `committed_capital_cents` minus `escrowed_cents`."

        Design: Difficulty/compensating_invariant/escrow_cash_conserved_across_deposit_cancel
        """
        s = fx.setup_deal_escrow_funded(api, buyer_proof_of_funds_cents=50_000_000)
        buyer = fx.get_buyer(api, s["buyer"]["id"])
        # earnest 5_000_000 still committed (accepted LOI) + escrowed 5_000_000 deposit.
        assert buyer["escrowed_cents"] == 5_000_000
        assert buyer["available_capital_cents"] == 40_000_000

    def test_deal_withdraw_refunds_escrowed_cash(self, api):
        """PRD §3.10: "Through every one of these unwind paths the conservation invariants hold: no
        earnest remains committed and no escrowed cash remains held once the commitment that gave
        rise to it has ended."

        Design: Difficulty/compensating_invariant/escrow_cash_conserved_across_deposit_cancel
        """
        s = fx.setup_deal_escrow_funded(api, buyer_proof_of_funds_cents=50_000_000)
        validate_success(
            api.withdraw_deal(
                s["deal"]["id"], make_broker_headers(s["broker"]["id"]),
                {"reason": "Financing collapsed post-funding"},
            )
        )
        buyer = fx.get_buyer(api, s["buyer"]["id"])
        assert buyer["escrowed_cents"] == 0
        assert buyer["available_capital_cents"] == 50_000_000
        escrow, _meta = _paginate(api.list_escrow(s["deal"]["id"], make_broker_headers(s["broker"]["id"])))
        acct = next(r for r in escrow if r["id"] == s["escrow"]["id"])
        assert acct["status"] == "CANCELLED"


def test_open_diligence_with_empty_data_room_rejected(api):
    """PRD §3.6: "**opening diligence** advances the deal from `UNDER_LOI` to `DUE_DILIGENCE`, but
    only if the listing's data room holds at least one document; an empty data room blocks the
    transition with `ERR_DATA_ROOM_EMPTY`."

    Design: Corner/state_machines/open_diligence_empty_data_room_returns_error
    """
    s = fx.setup_deal_under_loi(api)  # UNDER_LOI, no documents uploaded
    resp = api.open_diligence(s["deal"]["id"], make_broker_headers(s["broker"]["id"]))
    validate_error(resp, ApiErrorId.ERR_DATA_ROOM_EMPTY.value)
