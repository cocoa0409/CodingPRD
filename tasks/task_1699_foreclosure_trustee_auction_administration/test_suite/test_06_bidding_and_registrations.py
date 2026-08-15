"""Bidder qualification, minimum-bid increments, winner determination, and refunds."""
from test_helpers import (
    AUCT,
    ApiErrorId,
    add_bidding_instruction,
    create_bid_payload,
    conduct_sale_at,
    make_third_party_bidder_headers,
    qualify_bidder,
    register_and_qualify_bidder,
    register_bidder,
    setup_case_at_sale_scheduled,
    setup_closed_sale,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestBidRequiresQualifiedRegistration:
    def _conducted_with_pending_registration(self, api):
        # Registration happens while the sale is still SCHEDULED; the auction
        # is then opened on its scheduled day.
        ctx = setup_case_at_sale_scheduled("BEN-D2", venue_name="VEN-D2",
                                           loan_reference="LN-D2")
        add_bidding_instruction(ctx["case"]["id"], ctx["beneficiary"]["id"])
        reg = register_bidder(ctx["sale"]["id"], bidder_name="Bidder Z",
                              bidder_email="bz@bid.example",
                              deposit_cents=1_000_000)
        ctx["sale"] = conduct_sale_at(ctx["sale"]["id"])
        return ctx, reg

    def test_bid_from_pending_registration_rejected(self, api):
        """PRD §3.8: "Four checks then run in order: the sale must be `CONDUCTED` (`ERR_INVALID_SALE_STATE`); the registration must be `QUALIFIED` (`ERR_INVALID_REGISTRATION_STATE`); and the amount must meet the minimum next bid — a bid exactly at the minimum is accepted, and anything lower is rejected with `ERR_BID_TOO_LOW` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/bid_acceptance_requires_qualified_registration
        """
        ctx, reg = self._conducted_with_pending_registration(api)
        # 42210000 == opening 42000000 + increment max(50000, 210000): the
        # amount is valid; only the registration state blocks it.
        resp = api.place_bid(
            ctx["sale"]["id"],
            create_bid_payload(reg["id"], 42_210_000),
            make_third_party_bidder_headers(reg["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REGISTRATION_STATE, 409)

    def test_bid_at_exact_minimum_accepted_after_qualify(self, api):
        """PRD §3.8: "Four checks then run in order: the sale must be `CONDUCTED` (`ERR_INVALID_SALE_STATE`); the registration must be `QUALIFIED` (`ERR_INVALID_REGISTRATION_STATE`); and the amount must meet the minimum next bid — a bid exactly at the minimum is accepted, and anything lower is rejected with `ERR_BID_TOO_LOW` (HTTP 422). The minimum is computed from the bidding so far: the increment over a base amount is the greater of five hundred dollars (50000 cents) and one-half of one percent of that base rounded half-up to whole cents. When no bid has yet been placed on the sale, the base is the sale's `opening_bid_cents` and the first bid must be at least the opening bid plus the increment over it; thereafter the base is the current highest accepted bid, and each new bid must be at least that high bid plus the increment over it."

        Design: Difficulty/cross_entity_state_dependency/bid_acceptance_requires_qualified_registration
        """
        ctx, reg = self._conducted_with_pending_registration(api)
        qualify_bidder(reg["id"])
        bid = validate_success(
            api.place_bid(
                ctx["sale"]["id"],
                create_bid_payload(reg["id"], 42_210_000),
                make_third_party_bidder_headers(reg["id"]),
            ),
            201,
        )
        assert bid["amount_cents"] == 42_210_000, (
            "a bid exactly at the minimum (opening + increment) is accepted"
        )


class TestWinnerDeterminationAndIncrementFloor:
    def test_winner_highest_bid_and_increment_floor(self, api):
        """PRD §3.8: "Four checks then run in order: the sale must be `CONDUCTED` (`ERR_INVALID_SALE_STATE`); the registration must be `QUALIFIED` (`ERR_INVALID_REGISTRATION_STATE`); and the amount must meet the minimum next bid — a bid exactly at the minimum is accepted, and anything lower is rejected with `ERR_BID_TOO_LOW` (HTTP 422)."
        PRD §3.8: "When qualifying bids exist, the winner is the highest bid by `amount_cents`, with ties broken in favor of the earliest `placed_at`; record identifiers are never used for ordering. The sale then records `winner_type` of `THIRD_PARTY`, the winning amount in `winning_bid_cents`, and the winner's registration in `winning_bidder_registration_id`."
        PRD §3.8: "the winner's `QUALIFIED` registration becomes `DEPOSIT_APPLIED`, and every other `QUALIFIED` registration becomes `REFUND_PENDING`, awaiting refund."

        Design: Corner/calculations/winner_highest_bid_and_increment_floor
        """
        ctx = setup_case_at_sale_scheduled(
            "BEN-CAL1", venue_name="VEN-CAL1", loan_reference="LN-CAL1"
        )
        add_bidding_instruction(
            ctx["case"]["id"], ctx["beneficiary"]["id"],
            opening_bid_cents=42_000_000, max_bid_cents=44_000_000,
            strategy="UP_TO_MAX",
        )
        sale_id = ctx["sale"]["id"]
        reg1 = register_and_qualify_bidder(sale_id, bidder_name="Bidder One",
                                           bidder_email="b1@bid.example")
        reg2 = register_and_qualify_bidder(sale_id, bidder_name="Bidder Two",
                                           bidder_email="b2@bid.example")
        ctx["sale"] = conduct_sale_at(sale_id)
        validate_success(
            api.place_bid(sale_id, create_bid_payload(reg1["id"], 42_210_000),
                          make_third_party_bidder_headers(reg1["id"])),
            201,
        )
        # increment over 42210000 == max(50000, round(0.005*42210000)) == 211050
        # -> minimum 42421050; 42300000 is below it.
        resp = api.place_bid(
            sale_id, create_bid_payload(reg2["id"], 42_300_000),
            make_third_party_bidder_headers(reg2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BID_TOO_LOW, 422)
        bid2 = validate_success(
            api.place_bid(sale_id, create_bid_payload(reg2["id"], 42_421_050),
                          make_third_party_bidder_headers(reg2["id"])),
            201,
        )
        assert bid2["amount_cents"] == 42_421_050

        sale = validate_success(api.close_sale(sale_id, AUCT), 200)
        assert sale["winner_type"] == "THIRD_PARTY"
        assert sale["winning_bid_cents"] == 42_421_050
        assert sale["winning_bidder_registration_id"] == reg2["id"]

        reg1_after = validate_success(
            api.get_bidder_registration(reg1["id"], AUCT), 200
        )
        reg2_after = validate_success(
            api.get_bidder_registration(reg2["id"], AUCT), 200
        )
        assert reg1_after["status"] == "REFUND_PENDING"
        assert reg2_after["status"] == "DEPOSIT_APPLIED"


class TestRequiredDepositBranches:
    def test_required_deposit_floor_and_percentage_branches(self, api):
        """PRD §3.8: "To qualify, the registration must be `PENDING`, the sale must be in `SCHEDULED` or `CONDUCTED` status (`ERR_INVALID_SALE_STATE` otherwise), and the tendered `deposit_cents` must be at least the registration's `required_deposit_cents` — meeting the requirement exactly qualifies — with a shortfall rejected as `ERR_DEPOSIT_INSUFFICIENT` (HTTP 422); the sale-state check runs before the registration-state check, and the deposit test runs last. The required deposit is computed at review time: the opening reference is the `opening_bid_cents` of the case's `ACTIVE` bidding instruction if one exists, and otherwise the case's `unpaid_principal_balance_cents`; the `required_deposit_cents` is the greater of ten thousand dollars (1000000 cents) and one percent of the opening reference rounded half-up to whole cents."

        Design: Corner/calculations/required_deposit_floor_and_percentage_branches
        """
        # Case A: instruction opening 42000000 -> 1% is 420000, floor governs.
        ctx_a = setup_case_at_sale_scheduled(
            "BEN-CAL2", venue_name="VEN-CAL2", loan_reference="LN-CAL2"
        )
        add_bidding_instruction(ctx_a["case"]["id"], ctx_a["beneficiary"]["id"])
        sale_a = ctx_a["sale"]["id"]
        # Case B: principal 120000000, no instruction -> percentage branch.
        ctx_b = setup_case_at_sale_scheduled(
            "BEN-CAL3", venue_name="VEN-CAL3", loan_reference="LN-CAL3",
            unpaid_principal_balance_cents=120_000_000,
        )
        sale_b = ctx_b["sale"]["id"]

        reg_a_short = register_bidder(sale_a, bidder_name="Floor Short",
                                      bidder_email="fs@bid.example",
                                      deposit_cents=999_999)
        reg_a_exact = register_bidder(sale_a, bidder_name="Floor Exact",
                                      bidder_email="fe@bid.example",
                                      deposit_cents=1_000_000)
        reg_b_short = register_bidder(sale_b, bidder_name="Pct Short",
                                      bidder_email="ps@bid.example",
                                      deposit_cents=1_199_999)
        reg_b_exact = register_bidder(sale_b, bidder_name="Pct Exact",
                                      bidder_email="pe@bid.example",
                                      deposit_cents=1_200_000)

        validate_error(
            api.review_bidder_registration(
                reg_a_short["id"], {"decision": "QUALIFY"}, AUCT
            ),
            ApiErrorId.ERR_DEPOSIT_INSUFFICIENT,
            422,
        )
        a_exact = validate_success(
            api.review_bidder_registration(
                reg_a_exact["id"], {"decision": "QUALIFY"}, AUCT
            ),
            200,
        )
        assert a_exact["status"] == "QUALIFIED"
        assert a_exact["required_deposit_cents"] == 1_000_000, (
            "the 1000000-cent floor governs when 1% of the reference is smaller"
        )

        validate_error(
            api.review_bidder_registration(
                reg_b_short["id"], {"decision": "QUALIFY"}, AUCT
            ),
            ApiErrorId.ERR_DEPOSIT_INSUFFICIENT,
            422,
        )
        b_exact = validate_success(
            api.review_bidder_registration(
                reg_b_exact["id"], {"decision": "QUALIFY"}, AUCT
            ),
            200,
        )
        assert b_exact["status"] == "QUALIFIED"
        assert b_exact["required_deposit_cents"] == 1_200_000, (
            "with no instruction, 1% of the 120000000-cent principal governs"
        )


class TestRegistrationRefundsAndOwnership:
    def test_refund_before_refund_pending_rejected(self, api):
        """PRD §3.8: "Reviewing a registration that is not `PENDING` — or, for bids and refunds, one in the wrong status — surfaces `ERR_INVALID_REGISTRATION_STATE` (HTTP 409)."
        PRD §3.8: "Finally, an `Auctioneer` refunds a `REFUND_PENDING` registration, releasing the deposit and moving it to `REFUNDED`; no other field changes."

        Design: Corner/state_machines/refund_before_refund_pending_rejected
        """
        ctx = setup_case_at_sale_scheduled("BEN-S7", venue_name="VEN-S7",
                                           loan_reference="LN-S7")
        reg = register_and_qualify_bidder(
            ctx["sale"]["id"], bidder_name="Bidder S7",
            bidder_email="bs7@bid.example",
        )
        resp = api.refund_registration(reg["id"], AUCT)
        validate_error(resp, ApiErrorId.ERR_INVALID_REGISTRATION_STATE, 409)

    def test_bidder_cannot_place_others_bid_returns_403(self, api):
        """PRD §2.1: "A third-party bidder placing a bid must present a payload whose `bidder_registration_id` equals the caller's `X-User-ID`; a mismatch is rejected with `ERR_BIDDER_OWNERSHIP_MISMATCH` (HTTP 403)."

        Design: Corner/rbac/bidder_cannot_place_others_bid_returns_403
        """
        ctx = setup_case_at_sale_scheduled("BEN-RB2", venue_name="VEN-RB2",
                                           loan_reference="LN-RB2")
        add_bidding_instruction(ctx["case"]["id"], ctx["beneficiary"]["id"])
        sale_id = ctx["sale"]["id"]
        reg_a = register_and_qualify_bidder(sale_id, bidder_name="Bidder RA",
                                            bidder_email="ra@bid.example")
        reg_b = register_and_qualify_bidder(sale_id, bidder_name="Bidder RB",
                                            bidder_email="rb@bid.example")
        ctx["sale"] = conduct_sale_at(sale_id)
        resp = api.place_bid(
            sale_id,
            create_bid_payload(reg_b["id"], 42_210_000),
            make_third_party_bidder_headers(reg_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BIDDER_OWNERSHIP_MISMATCH, 403)
        _rows, meta = validate_paginated(api.list_bids(sale_id, AUCT))
        assert meta["total_count"] == 0, "no bid may be persisted by a mismatch"


class TestBidAfterClose:
    def test_bid_after_close_rejected_and_filtered_lists(self, api):
        """PRD §3.8: "Four checks then run in order: the sale must be `CONDUCTED` (`ERR_INVALID_SALE_STATE`); the registration must be `QUALIFIED` (`ERR_INVALID_REGISTRATION_STATE`); and the amount must meet the minimum next bid — a bid exactly at the minimum is accepted, and anything lower is rejected with `ERR_BID_TOO_LOW` (HTTP 422)."
        PRD §3.8: "Sales may be listed with optional `notice_of_trustee_sale_id`, `foreclosure_case_id`, and `status` filters, and read individually."

        Design: Corner/endpoints/bid_after_close_rejected_and_filtered_lists
        """
        ctx = setup_closed_sale("BEN-E3", venue_name="VEN-E3",
                                loan_reference="LN-E3",
                                bid_amount_cents=42_210_000,
                                bidder_email="be3@bid.example")
        resp = api.place_bid(
            ctx["sale"]["id"],
            create_bid_payload(ctx["registration"]["id"], 43_000_000),
            make_third_party_bidder_headers(ctx["registration"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_SALE_STATE, 409)
        rows, meta = validate_paginated(
            api.list_auction_sales(
                AUCT, params={"foreclosure_case_id": ctx["case"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == ctx["sale"]["id"]
