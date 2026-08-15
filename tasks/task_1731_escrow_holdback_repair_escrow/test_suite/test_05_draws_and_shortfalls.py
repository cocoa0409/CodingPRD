"""Draw requests: creation gates, approval, reservation, shortfall, payment."""
from test_helpers import (
    ApiErrorId,
    PARTIES,
    TEST_USERS,
    approve_draw,
    create_approved_draw,
    create_draft_holdback,
    create_draw,
    create_verified_draw,
    deposit_pledge,
    expire_holdback,
    get_holdback,
    list_draws,
    list_ledger,
    list_pledges,
    make_buyer_headers,
    pay_draw,
    select_bid,
    set_logical_clock,
    setup_active_holdback,
    setup_engagement,
    setup_escrow_file,
    submit_bid,
    validate_error,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]


class TestDrawCreationGates:
    def test_draw_create_on_draft_holdback_rejected(self, api):
        """PRD §3.5: "The holdback must be `ACTIVE` (`ERR_HOLDBACK_NOT_ACTIVE`)."

        A draw on a DRAFT holdback is rejected at the domain state gate.

        Design: Difficulty/cross_entity_state_dependency/draw_create_requires_active_holdback
        """
        set_logical_clock()
        file = setup_escrow_file()
        hb = create_draft_holdback(file["id"])

        resp = api.create_draw_request(
            {"holdback_id": hb["id"], "amount_cents": 1000,
             "description": "Premature draw", "is_final": False},
            TEST_USERS["contr_1_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_HOLDBACK_NOT_ACTIVE)

    def test_draw_create_requires_selected_contractor_then_succeeds(self, api):
        """PRD §3.5: "Contractor identity is enforced through the selection: when no bid has been selected yet there is no engagement to check against, the ownership check is skipped, and the request fails later at the state gate with `ERR_NO_SELECTED_CONTRACTOR`; once a bid is selected, a caller other than the selected contractor is rejected with `ERR_NOT_FILE_PARTY`."

        ACTIVE without a selection rejects; after selection the engaged
        contractor's draw enters SUBMITTED.

        Design: Difficulty/cross_entity_state_dependency/draw_create_requires_active_holdback
        """
        ctx = setup_active_holdback()
        hb, file = ctx["holdback"], ctx["file"]

        mid = api.create_draw_request(
            {"holdback_id": hb["id"], "amount_cents": 1000,
             "description": "No contractor yet", "is_final": False},
            TEST_USERS["contr_1_headers"],
        )
        validate_error(mid, ApiErrorId.ERR_NO_SELECTED_CONTRACTOR)

        bid = submit_bid(hb["id"])
        select_bid(bid["id"], file)

        ok = validate_success(
            api.create_draw_request(
                {"holdback_id": hb["id"], "amount_cents": 1000,
                 "description": "Now valid", "is_final": False},
                TEST_USERS["contr_1_headers"]),
            201,
        )
        assert ok["status"] == "SUBMITTED"

    def test_second_open_draw_rejected(self, api):
        """PRD §3.5: "Only one `SUBMITTED` draw may exist at a time on a holdback (`ERR_DRAW_ALREADY_OPEN`)."

        Design: Corner/validations/second_open_draw_rejected
        """
        ctx = setup_engagement()
        hb_id = ctx["holdback"]["id"]
        first = create_draw(hb_id, 50000, description="Stage 1")

        resp = api.create_draw_request(
            {"holdback_id": hb_id, "amount_cents": 40000,
             "description": "Stage 2 premature", "is_final": False},
            TEST_USERS["contr_1_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DRAW_ALREADY_OPEN)

        draws = {d["id"]: d for d in list_draws(hb_id)}
        assert draws[first["id"]]["status"] == "SUBMITTED"


class TestNetVsGrossShortfallCap:
    def _setup_two_draws(self, api, second_amount=90000, overrun="BUYER"):
        """ACTIVE 230000 holdback; draw1 150000 APPROVED-unpaid; draw2 ready."""
        ctx = setup_engagement(overrun_responsibility=overrun)
        hb_id = ctx["holdback"]["id"]
        create_approved_draw(ctx, 150000, description="Stage 1 tear-off",
                             scheduled_start="2026-08-20T10:00:00Z",
                             scheduled_end="2026-08-20T11:00:00Z")
        pair2 = create_verified_draw(ctx, second_amount, description="Stage 2 materials",
                                     scheduled_start="2026-08-21T10:00:00Z",
                                     scheduled_end="2026-08-21T11:00:00Z")
        return ctx, pair2["draw"]

    def test_net_cap_creates_pledge_when_gross_would_not(self, api):
        """PRD §3.5: "When judging how much cash a draw can safely call on, the system's authoritative measure is the net payable cap: `trust_balance_cents` minus the amounts reserved for the other `APPROVED`-but-unpaid draws, excluding the draw under consideration."
        PRD §3.5: "The gross reading that ignores approved-unpaid commitments is a rejected reading — it overcommits cash — and the two diverge exactly when at least one other approved-unpaid draw exists."
        PRD §3.5: "When positive, pledges are created per the holdback's `overrun_responsibility`: `BUYER` creates one pledge assigned to the buyer for the full excess"

        Approving 90000 while 150000 is APPROVED-unpaid against a 230000
        holdback yields projected excess 10000 and a single BUYER pledge; the
        rejected GROSS reading (90000 <= 230000) would create none.

        Design: Difficulty/dual_variant_calc/draw_shortfall_net_vs_gross_cap
        """
        ctx, draw2 = self._setup_two_draws(api, 90000, overrun="BUYER")
        approve_draw(draw2["id"])

        pledges = list_pledges(ctx["holdback"]["id"])
        assert len(pledges) == 1
        assert pledges[0]["amount_cents"] == 10000, (
            "NET: (0 disbursed + 240000 reserved) - 230000 funded == 10000"
        )
        assert pledges[0]["payer_role"] == "BUYER"
        assert pledges[0]["status"] == "PLEDGED"

    def test_reserved_tracks_both_approved_draws(self, api):
        """PRD §2.7: "Second, the holdback's `reserved_cents` always equals the sum of the `amount_cents` of its draw requests currently in `APPROVED` (approved-but-unpaid) state."
        PRD §3.5: "Approval stamps `approved_at` and adds the draw's amount to the holdback's `reserved_cents`, the running total of approved-but-unpaid commitments."

        After both approvals reserved_cents == 240000 and both draws read
        APPROVED.

        Design: Difficulty/dual_variant_calc/draw_shortfall_net_vs_gross_cap
        """
        ctx, draw2 = self._setup_two_draws(api, 90000, overrun="BUYER")
        approved2 = approve_draw(draw2["id"])
        assert approved2["status"] == "APPROVED"
        assert approved2["approved_at"] is not None

        hb = get_holdback(ctx["holdback"]["id"])
        assert hb["reserved_cents"] == 240000
        draws = list_draws(ctx["holdback"]["id"])
        approved_sum = sum(d["amount_cents"] for d in draws if d["status"] == "APPROVED")
        assert approved_sum == hb["reserved_cents"]


class TestShortfallThresholdBoundary:
    def _setup_single_draw(self, api, amount, address):
        ctx = setup_engagement(file_overrides={"property_address": address},
                               bid_amount_cents=240000)
        pair = create_verified_draw(ctx, amount, description="Boundary draw",
                                    is_final=True)
        return ctx, pair["draw"]

    def test_exact_fit_creates_no_pledge(self, api):
        """PRD §3.5: "Only a projected excess strictly greater than zero creates obligations; a projected excess of exactly zero creates none."

        Approving a draw of exactly 230000 against a 230000 holdback is an
        exact fit: the approval succeeds and no pledge exists.

        Design: Difficulty/boundary_precision_check/shortfall_threshold_exact_fit_vs_one_cent
        """
        ctx, draw = self._setup_single_draw(api, 230000, "1 Harbor Way")
        approved = approve_draw(draw["id"])
        assert approved["status"] == "APPROVED"
        pledges = list_pledges(ctx["holdback"]["id"])
        assert pledges == [], "excess == 0 is not > 0; exact fit creates no pledge"

    def test_one_cent_over_creates_one_cent_pledge(self, api):
        """PRD §3.5: "Only a projected excess strictly greater than zero creates obligations; a projected excess of exactly zero creates none."
        PRD §3.5: "`BUYER` creates one pledge assigned to the buyer for the full excess"

        One cent over (230001 against 230000) creates a pledge of exactly one
        cent; the approval itself still succeeds.

        Design: Difficulty/boundary_precision_check/shortfall_threshold_exact_fit_vs_one_cent
        """
        ctx, draw = self._setup_single_draw(api, 230001, "2 Cedar Ln")
        approved = approve_draw(draw["id"])
        assert approved["status"] == "APPROVED"
        pledges = list_pledges(ctx["holdback"]["id"])
        assert len(pledges) == 1
        assert pledges[0]["amount_cents"] == 1
        assert pledges[0]["payer_role"] == "BUYER"
        assert pledges[0]["status"] == "PLEDGED"


class TestShortfallPledgeCascade:
    def _setup_split_shortfall(self, api):
        """SPLIT_EQUAL overrun; draw1 150000 APPROVED; draw2 90001 verifiable."""
        ctx = setup_engagement(overrun_responsibility="SPLIT_EQUAL")
        create_approved_draw(ctx, 150000, description="Stage 1",
                             scheduled_start="2026-08-20T10:00:00Z",
                             scheduled_end="2026-08-20T11:00:00Z")
        pair2 = create_verified_draw(ctx, 90001, description="Stage 2",
                                     scheduled_start="2026-08-21T10:00:00Z",
                                     scheduled_end="2026-08-21T11:00:00Z")
        return ctx, pair2["draw"]

    def test_split_pledge_rounding_order(self, api):
        """PRD §2.6: "In the shortfall-pledge split, the buyer's pledge is the half rounded half-up first, and the seller's pledge is the residual (the total minus the buyer's pledge)."
        PRD §3.5: "`SPLIT_EQUAL` creates two — the buyer's pledge is half the excess rounded half-up to whole cents (the buyer's side is rounded first), and the seller's pledge is the residual, the excess minus the buyer's pledge."

        Excess 10001 splits into buyer 5001 (rounded first) and seller 5000.

        Design: Difficulty/transitive_cascade/draw_approve_shortfall_pledge_cascade
        """
        ctx, draw2 = self._setup_split_shortfall(api)
        approve_draw(draw2["id"])

        pledges = list_pledges(ctx["holdback"]["id"])
        assert len(pledges) == 2
        by_role = {p["payer_role"]: p for p in pledges}
        assert by_role["BUYER"]["amount_cents"] == 5001
        assert by_role["SELLER"]["amount_cents"] == 5000
        assert by_role["BUYER"]["payer_user_id"] == PARTIES["buyer"]
        assert by_role["SELLER"]["payer_user_id"] == PARTIES["seller"]
        assert all(p["status"] == "PLEDGED" for p in pledges)

    def test_pledged_pledge_blocks_payment(self, api):
        """PRD §3.5: "must have no `PLEDGED` shortfall pledge outstanding — unfunded pledges block payment with `ERR_SHORTFALL_UNFUNDED` until every pledge is deposited."

        With both pledges PLEDGED, paying even the earlier approved draw fails,
        and reserved_cents reflects both approvals (240001).

        Design: Difficulty/transitive_cascade/draw_approve_shortfall_pledge_cascade
        """
        ctx, draw2 = self._setup_split_shortfall(api)
        draw1 = [d for d in list_draws(ctx["holdback"]["id"])
                 if d["amount_cents"] == 150000][0]
        approve_draw(draw2["id"])

        resp = api.pay_draw_request(draw1["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_SHORTFALL_UNFUNDED)

        hb = get_holdback(ctx["holdback"]["id"])
        assert hb["reserved_cents"] == 240001
        draws = {d["id"]: d for d in list_draws(ctx["holdback"]["id"])}
        assert draws[draw1["id"]]["status"] == "APPROVED"


class TestPayGates:
    def test_pay_submitted_draw_rejected(self, api):
        """PRD §3.5: "The draw must be `APPROVED`: paying a `SUBMITTED` draw fails with `ERR_DRAW_NOT_APPROVED`, while paying one already `PAID` or `CANCELLED` is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/pay_submitted_draw_rejected
        """
        ctx = setup_engagement()
        draw = create_draw(ctx["holdback"]["id"], 50000, description="Stage 1")

        resp = api.pay_draw_request(draw["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_DRAW_NOT_APPROVED)

        draws = {d["id"]: d for d in list_draws(ctx["holdback"]["id"])}
        assert draws[draw["id"]]["status"] == "SUBMITTED"
        entries = list_ledger(ctx["holdback"]["id"])
        assert len(entries) == 1 and entries[0]["entry_type"] == "FUNDING", (
            "no ledger entry appended by the rejected pay"
        )

    def test_double_pay_rejected(self, api):
        """PRD §3.5: "The draw must be `APPROVED`: paying a `SUBMITTED` draw fails with `ERR_DRAW_NOT_APPROVED`, while paying one already `PAID` or `CANCELLED` is `ERR_INVALID_STATE`."
        PRD §3.5: "Payment appends a `DRAW_DEBIT` entry for the negative amount, reduces `trust_balance_cents` by the amount, grows `total_disbursed_cents` by the amount, releases the reservation by reducing `reserved_cents` by the amount, stamps `paid_at`, and moves the draw to `PAID`."

        Design: Corner/state_machines/double_pay_rejected
        """
        ctx = setup_engagement()
        pair = create_approved_draw(ctx, 50000, description="Stage 1")
        paid = pay_draw(pair["draw"]["id"])
        assert paid["status"] == "PAID"
        assert paid["paid_at"] is not None

        again = api.pay_draw_request(pair["draw"]["id"], OFFICER)
        validate_error(again, ApiErrorId.ERR_INVALID_STATE)

        entries = list_ledger(ctx["holdback"]["id"])
        debits = [e for e in entries if e["entry_type"] == "DRAW_DEBIT"]
        assert len(debits) == 1 and debits[0]["amount_cents"] == -50000
        assert get_holdback(ctx["holdback"]["id"])["trust_balance_cents"] == 180000

    def test_pay_state_gate_wins_over_fiscal_gate(self, api):
        """PRD §2.9: "When several checks could fail on the same request, the server evaluates them in a fixed order and returns the error of the first check that fails; later checks are never evaluated once an earlier one has fired."
        PRD §2.9: "Domain state gates, evaluated in this fixed internal order: `ERR_HOLDBACK_NOT_ACTIVE` first (required by bid creation, bid selection, draw creation, draw approval, draw payment, inspection scheduling, extension creation, and extension decision)"
        PRD §2.9: "Shortfall coverage on draw payment: no pledge of the holdback may remain `PLEDGED` — otherwise `ERR_SHORTFALL_UNFUNDED` (HTTP 409)."

        Paying an APPROVED draw on an EXPIRED holdback with a PLEDGED pledge
        outstanding reports the state gate, not the fiscal gate.

        Design: Difficulty/priority_pair_validation_conflict/pay_state_gate_before_fiscal_gate
        """
        ctx = setup_engagement()
        pair1 = create_approved_draw(ctx, 150000, description="Stage 1",
                                     scheduled_start="2026-08-20T10:00:00Z",
                                     scheduled_end="2026-08-20T11:00:00Z")
        pair2 = create_verified_draw(ctx, 90000, description="Stage 2",
                                     scheduled_start="2026-08-21T10:00:00Z",
                                     scheduled_end="2026-08-21T11:00:00Z")
        approve_draw(pair2["draw"]["id"])
        pledges = list_pledges(ctx["holdback"]["id"])
        assert len(pledges) == 1 and pledges[0]["status"] == "PLEDGED"

        set_logical_clock("2026-09-16T00:00:00Z")
        expire_holdback(ctx["holdback"]["id"])

        resp = api.pay_draw_request(pair1["draw"]["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_HOLDBACK_NOT_ACTIVE)

    def test_approved_draw_survives_expiry_with_pledge_intact(self, api):
        """PRD §3.8: "Expiration moves the holdback from `ACTIVE` to `EXPIRED` and cancels everything still open beneath it in one sweep: every `SUBMITTED` draw request becomes `CANCELLED`, every `PLANNED` inspection becomes `CANCELLED`, and every `PENDING` extension request becomes `CANCELLED`."

        The sweep cancels only SUBMITTED draws; an APPROVED draw and its
        PLEDGED pledge survive expiry unchanged.

        Design: Difficulty/priority_pair_validation_conflict/pay_state_gate_before_fiscal_gate
        """
        ctx = setup_engagement()
        pair1 = create_approved_draw(ctx, 150000, description="Stage 1",
                                     scheduled_start="2026-08-20T10:00:00Z",
                                     scheduled_end="2026-08-20T11:00:00Z")
        pair2 = create_verified_draw(ctx, 90000, description="Stage 2",
                                     scheduled_start="2026-08-21T10:00:00Z",
                                     scheduled_end="2026-08-21T11:00:00Z")
        approve_draw(pair2["draw"]["id"])

        set_logical_clock("2026-09-16T00:00:00Z")
        expired = expire_holdback(ctx["holdback"]["id"])
        assert expired["status"] == "EXPIRED"

        draws = {d["id"]: d for d in list_draws(ctx["holdback"]["id"])}
        assert draws[pair1["draw"]["id"]]["status"] == "APPROVED", (
            "approved draws are commitments and survive expiry"
        )
        pledges = list_pledges(ctx["holdback"]["id"])
        assert len(pledges) == 1 and pledges[0]["status"] == "PLEDGED"
        assert pledges[0]["amount_cents"] == 10000


class TestPledgeDeposit:
    def test_pledge_double_deposit_rejected(self, api):
        """PRD §3.5: "When the pledged funds arrive, an `EscrowOfficer` records the deposit: the pledge moves from `PLEDGED` to `DEPOSITED` (depositing one already deposited is `ERR_INVALID_STATE`), a `SHORTFALL_DEPOSIT` entry for the positive amount is appended, `trust_balance_cents` and `total_shortfall_deposited_cents` each grow by that amount, and `deposited_at` is stamped."

        A 240000 draw against a 230000 holdback pledges 10000; one deposit
        lands, the second is rejected, and the ledger shows a single
        SHORTFALL_DEPOSIT.

        Design: Corner/state_machines/pledge_double_deposit_rejected
        """
        ctx = setup_engagement(bid_amount_cents=240000)
        pair = create_verified_draw(ctx, 240000, description="Full bill",
                                    is_final=True)
        approve_draw(pair["draw"]["id"])

        pledges = list_pledges(ctx["holdback"]["id"])
        assert len(pledges) == 1 and pledges[0]["amount_cents"] == 10000
        deposited = deposit_pledge(pledges[0]["id"])
        assert deposited["status"] == "DEPOSITED"
        assert deposited["deposited_at"] is not None

        again = api.deposit_shortfall_pledge(pledges[0]["id"], OFFICER)
        validate_error(again, ApiErrorId.ERR_INVALID_STATE)

        entries = list_ledger(ctx["holdback"]["id"])
        deposits = [e for e in entries if e["entry_type"] == "SHORTFALL_DEPOSIT"]
        assert len(deposits) == 1 and deposits[0]["amount_cents"] == 10000
        hb = get_holdback(ctx["holdback"]["id"])
        assert hb["trust_balance_cents"] == 240000
        assert hb["total_shortfall_deposited_cents"] == 10000
