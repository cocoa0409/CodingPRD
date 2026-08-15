"""PSA termination paths: diligence refunds, buyer-default forfeitures, the
lapsed termination right, and entity-backed ownership on buyer termination."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_asset,
    make_buyer_headers,
    pipeline_to_binding,
    pipeline_to_dd_active,
    pipeline_through_offers,
    register_qualified_bidder,
    place_bid,
    set_clock,
    close_offers,
    shortlist_bid,
    select_bid,
    create_psa,
    execute_psa,
    list_psa_deposits,
    post_deposit,
    validate_error,
    validate_success,
)

DM = TEST_USERS["dm_headers"]
CO = TEST_USERS["co_headers"]


class TestDiligenceRefund:
    def test_buyer_dd_termination_refunds_all_posted(self, api):
        """PRD: "A diligence termination refunds everything: all `POSTED`
        deposits cascade to `REFUNDED`, and all still-unpaid `DUE` or
        `DELINQUENT` deposits move to `REFUNDED`"
        PRD: "Cash is conserved across a termination: the sum of the
        `amount_cents` of deposits that ever reached `POSTED` equals the sum now
        `REFUNDED` plus the sum now `FORFEITED`, cent for cent"

        Design: Difficulty/compensating_invariant/deposit_cash_conservation_across_refund
        """
        ws = pipeline_to_dd_active()  # both deposits POSTED: 150M + 100M
        terminated = validate_success(
            api.terminate_psa(ws["psa"]["id"], "BUYER_DD", ws["buyer_headers"]))
        assert terminated["status"] == "TERMINATED"
        assert terminated["termination_reason"] == "BUYER_DD"

        deposits = validate_success(api.list_psa_deposits(ws["psa"]["id"], CO))
        assert deposits[0]["status"] == "REFUNDED"
        assert deposits[1]["status"] == "REFUNDED"
        refunded_sum = sum(d["amount_cents"] for d in deposits
                           if d["status"] == "REFUNDED")
        forfeited_sum = sum(d["amount_cents"] for d in deposits
                            if d["status"] == "FORFEITED")
        assert refunded_sum == 250_000_000, "every posted cent is refunded"
        assert forfeited_sum == 0
        assert refunded_sum + forfeited_sum == 250_000_000, \
            "conserved against the previously POSTED total"

    def test_buyer_dd_termination_leaves_forfeiture_ledger_untouched(self, api):
        """PRD: "A post followed by a refunding termination leaves the buyer
        whole and `forfeited_deposits_cents` unchanged"
        PRD: "in every case the deal dimension unwinds to `IDLE`."

        Design: Difficulty/compensating_invariant/deposit_cash_conservation_across_refund
        """
        ws = pipeline_to_dd_active()
        validate_success(
            api.terminate_psa(ws["psa"]["id"], "BUYER_DD", ws["buyer_headers"]))
        asset = get_asset(ws["asset"]["id"])
        assert asset["forfeited_deposits_cents"] == 0
        assert asset["deal_status"] == "IDLE"


class TestBuyerDefaultForfeit:
    def test_buyer_default_termination_forfeits_deposits(self, api):
        """PRD: "Under `BUYER_DEFAULT`, all `POSTED` deposits are `FORFEITED`
        and the asset's `forfeited_deposits_cents` grows by exactly the
        forfeited sum"

        Design: Difficulty/transitive_cascade/buyer_default_termination_cascade
        """
        ws = pipeline_to_binding()  # both deposits POSTED: 150M + 100M
        terminated = validate_success(
            api.terminate_psa(ws["psa"]["id"], "BUYER_DEFAULT", DM))
        assert terminated["status"] == "TERMINATED"
        assert terminated["termination_reason"] == "BUYER_DEFAULT"

        deposits = validate_success(api.list_psa_deposits(ws["psa"]["id"], CO))
        assert deposits[0]["status"] == "FORFEITED"
        assert deposits[1]["status"] == "FORFEITED"

    def test_buyer_default_termination_credits_forfeiture_ledger(self, api):
        """PRD: "a post followed by a `BUYER_DEFAULT` termination moves the same
        cents into `forfeited_deposits_cents` with zero refunded."
        PRD: "in every case the deal dimension unwinds to `IDLE`."

        Design: Difficulty/transitive_cascade/buyer_default_termination_cascade
        """
        ws = pipeline_to_binding()
        validate_success(api.terminate_psa(ws["psa"]["id"], "BUYER_DEFAULT", DM))
        asset = get_asset(ws["asset"]["id"])
        assert asset["forfeited_deposits_cents"] == 250_000_000
        assert asset["deal_status"] == "IDLE"


class TestBuyerTerminationRight:
    def test_psa_buyer_dd_terminate_blocked_after_lapse(self, api):
        """PRD: "a buyer may use only `BUYER_DD`, and only while the agreement
        is `DD_ACTIVE` — once the right has lapsed, the attempt is
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/psa_buyer_dd_terminate_blocked_after_lapse
        """
        ws = pipeline_to_binding()  # DD lapsed; agreement BINDING
        validate_error(
            api.terminate_psa(ws["psa"]["id"], "BUYER_DD", ws["buyer_headers"]),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        psa = validate_success(api.get_psa(ws["psa"]["id"], DM))
        assert psa["status"] == "BINDING"
        deposits = validate_success(api.list_psa_deposits(ws["psa"]["id"], CO))
        assert deposits[0]["status"] == "POSTED", \
            "no refund cascade fired on the rejected termination"

    def test_buyer_terminate_non_owner_forbidden(self, api):
        """PRD: "When `X-User-Role` is `Buyer`, `X-User-ID` is the `id` of the
        acting `Bidder`; ownership checks on any resource that references a
        `Bidder` compare the resource's foreign-key field — a bid's
        `bidder_id`, or a purchase agreement's `buyer_bidder_id` — to
        `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD: "the buyer caller's `X-User-ID` must equal `buyer_bidder_id`
        (`ERR_FORBIDDEN_ROLE`)"

        Design: Corner/state_machines/buyer_terminate_non_owner_forbidden
        """
        # Build the deal with bidder B1, then a second bidder B2 attempts the
        # buyer termination — the role is allowed on the endpoint but the
        # identity does not match the agreement's buyer_bidder_id.
        ws = pipeline_through_offers()
        b1 = register_qualified_bidder(ws["asset"]["id"], 1_500_000_000, "BuyerCo")
        b2 = register_qualified_bidder(ws["asset"]["id"], 1_500_000_000, "OtherCo")
        bid = place_bid(ws["asset"]["id"], b1["id"], 5_000_000_000, 150_000_000)
        set_clock("2026-09-16T00:00:00Z")
        close_offers(ws["asset"]["id"])
        shortlist_bid(bid["id"])
        select_bid(bid["id"])
        psa = create_psa(ws["asset"]["id"], bid["id"])
        psa = execute_psa(psa["id"], "2026-10-30T00:00:00Z")
        deposits = list_psa_deposits(psa["id"])
        post_deposit(deposits[0]["id"])
        psa = validate_success(api.open_dd(psa["id"], DM))
        assert psa["status"] == "DD_ACTIVE"

        validate_error(
            api.terminate_psa(psa["id"], "BUYER_DD", make_buyer_headers(b2["id"])),
            ApiErrorId.ERR_FORBIDDEN_ROLE)
        still = validate_success(api.get_psa(psa["id"], DM))
        assert still["status"] == "DD_ACTIVE"
