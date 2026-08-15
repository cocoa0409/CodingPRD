"""Contractor bidding, buyer selection, and the work order cascade."""
from test_helpers import (
    ApiErrorId,
    PARTIES,
    STANDARD,
    TEST_USERS,
    get_holdback,
    get_work_orders,
    list_ledger,
    make_buyer_headers,
    select_bid,
    set_logical_clock,
    setup_active_holdback,
    setup_engagement,
    submit_bid,
    validate_error,
    validate_paginated,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]


class TestProvisionalVsCommitment:
    def test_provisional_amount_funded_then_commitment_basis_set(self, api):
        """PRD §3.1: "This provisional, estimate-sized amount is the amount actually funded: creation immediately withholds the funds by appending a `FUNDING` entry for the positive holdback amount as the ledger's `seq` 1, so `trust_balance_cents` starts equal to `holdback_amount_cents`."
        PRD §3.3: "The holdback records the choice in `selected_bid_id` and computes its `commitment_basis_cents` from the selected bid's amount scaled by the contingency — the bid amount multiplied by one hundred plus `contingency_pct`, divided by one hundred, rounded half-up to whole cents."

        Estimate 200000 @15% funds 230000 at creation; selecting a 210000 bid
        sets the commitment basis to 241500 while the funded amount is unmoved.

        Design: Difficulty/dual_variant_calc/holdback_sizing_provisional_vs_commitment
        """
        set_logical_clock()
        ctx = setup_active_holdback(clock=None)
        hb = ctx["holdback"]
        assert hb["holdback_amount_cents"] == 230000
        assert hb["trust_balance_cents"] == 230000
        assert hb["commitment_basis_cents"] is None, "null before selection"
        entries = list_ledger(hb["id"])
        assert len(entries) == 1 and entries[0]["entry_type"] == "FUNDING"
        assert entries[0]["amount_cents"] == 230000

        bid = submit_bid(hb["id"], amount_cents=210000)
        select_bid(bid["id"], ctx["file"])

        after = get_holdback(hb["id"])
        assert after["holdback_amount_cents"] == 230000, (
            "PROVISIONAL funded amount is unchanged by selection"
        )
        assert after["commitment_basis_cents"] == 241500, (
            "COMMITMENT_BASIS = round_half_up(210000 * 115 / 100)"
        )
        assert after["selected_bid_id"] == bid["id"]
        # Selection appends no money movement.
        assert len(list_ledger(hb["id"])) == 1

    def test_commitment_basis_diverges_from_provisional(self, api):
        """PRD §3.3: "Where the selected bid differs from the original estimate, the commitment basis diverges from the funded provisional amount and exposes the underfunding gap."

        For identical agreement terms the two variants produce different amounts
        (230000 funded vs 241500 commitment) — an 11500-cent divergence.

        Design: Difficulty/dual_variant_calc/holdback_sizing_provisional_vs_commitment
        """
        ctx = setup_engagement()
        after = ctx["holdback"]
        assert after["holdback_amount_cents"] == 230000
        assert after["commitment_basis_cents"] == 241500
        assert after["commitment_basis_cents"] != after["holdback_amount_cents"]
        assert after["selected_bid_id"] == ctx["bid"]["id"]
        assert ctx["bid"]["status"] == "SELECTED"


class TestBidCardinalityAndSelection:
    def test_second_bid_same_contractor_rejected(self, api):
        """PRD §3.3: "Each contractor may hold at most one `SUBMITTED` bid per holdback — a repeat attempt fails with `ERR_BID_ALREADY_SUBMITTED`"

        Design: Corner/validations/second_bid_same_contractor_rejected
        """
        ctx = setup_active_holdback()
        hb = ctx["holdback"]
        submit_bid(hb["id"], contractor_user_id=PARTIES["contractor"],
                   amount_cents=210000, scope_text="Bid v1")

        resp = api.create_bid(
            {"holdback_id": hb["id"], "amount_cents": 199000, "scope_text": "Bid v2"},
            TEST_USERS["contr_1_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_BID_ALREADY_SUBMITTED)

    def test_bid_after_selection_rejected(self, api):
        """PRD §3.3: "once any bid of the holdback has been selected, further bid creation is closed off with `ERR_WORK_ORDER_EXISTS`."

        Design: Corner/validations/bid_after_selection_rejected
        """
        ctx = setup_engagement()

        resp = api.create_bid(
            {"holdback_id": ctx["holdback"]["id"], "amount_cents": 199000,
             "scope_text": "Late bid"},
            TEST_USERS["contr_2_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_WORK_ORDER_EXISTS)

    def test_select_rejected_bid_rejected(self, api):
        """PRD §3.3: "The chosen bid becomes `SELECTED`; every other `SUBMITTED` bid of the holdback becomes `REJECTED` by the system."
        PRD §3.3: "The holdback must be `ACTIVE` (`ERR_HOLDBACK_NOT_ACTIVE`), the chosen bid must still be `SUBMITTED` (`ERR_BID_NOT_SELECTABLE`), and no other bid of the holdback may already be `SELECTED` (`ERR_WORK_ORDER_EXISTS`)."

        Selecting bid A cascade-rejects bid B; selecting B afterwards fails.

        Design: Corner/state_machines/select_rejected_bid_rejected
        """
        ctx = setup_active_holdback()
        hb, file = ctx["holdback"], ctx["file"]
        bid_a = submit_bid(hb["id"], contractor_user_id=PARTIES["contractor"],
                           amount_cents=210000, scope_text="Bid A")
        bid_b = submit_bid(hb["id"], contractor_user_id=PARTIES["contractor_b"],
                           amount_cents=205000, scope_text="Bid B")

        select_bid(bid_a["id"], file)

        resp = api.select_bid(bid_b["id"], make_buyer_headers(file["buyer_user_id"]))
        validate_error(resp, ApiErrorId.ERR_BID_NOT_SELECTABLE)

        data, _meta = validate_paginated(api.list_bids(hb["id"], OFFICER))
        by_id = {b["id"]: b for b in data}
        assert by_id[bid_b["id"]]["status"] == "REJECTED", (
            "set by the selection cascade, not by this rejected call"
        )
        assert by_id[bid_a["id"]]["status"] == "SELECTED"

    def test_cascade_created_work_order_discoverable_via_list(self, api):
        """PRD §3.3: "A work order springs into existence in `IN_PROGRESS`, copying `contractor_user_id` and `agreed_amount_cents` from the selected bid, stamping `started_at` with its creation time, and starting with `failed_final_count` at 0 and `submitted_completion_at` null."
        PRD §3.3: "Exactly one work order ever exists per holdback, and its `completion_deadline_date` always mirrors the holdback's `effective_deadline_date`, including after extensions."

        Design: Corner/state_machines/cascade_created_work_order_discoverable_via_list
        """
        ctx = setup_engagement()
        orders = get_work_orders(ctx["holdback"]["id"])
        assert len(orders) == 1
        wo = orders[0]
        assert wo["status"] == "IN_PROGRESS"
        assert wo["contractor_user_id"] == PARTIES["contractor"]
        assert wo["agreed_amount_cents"] == STANDARD["bid_amount_cents"] == 210000
        assert wo["completion_deadline_date"] == STANDARD["work_deadline_date"]
        assert wo["failed_final_count"] == 0
        assert wo["submitted_completion_at"] is None
