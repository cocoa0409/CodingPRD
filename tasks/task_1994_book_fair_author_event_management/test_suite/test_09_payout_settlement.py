"""Profit-share payout: tiered share math, CASH/SCRIP variants, revision loop."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    create_sale_payload,
    make_school,
    make_publisher,
    make_fair_open,
    make_accepted_reconciliation,
    make_school_coordinator_headers,
    TEST_USERS,
)

ORG = TEST_USERS["organizer_headers"]
CASHIER = TEST_USERS["cashier_headers"]


def _fair_with_accepted_recon(school, pub, sale_qty, qty_delivered, line_price=1000,
                              discount=0.40):
    """Fair through RECONCILING with one FRONTLIST line, one tendered sale of
    sale_qty, recon fully ACCEPTED with zero variance."""
    fair, agr, lines = make_fair_open(
        school["id"], pub["id"],
        line_specs=[{"qty_committed": qty_delivered, "qty_delivered": qty_delivered,
                     "list_price_cents": line_price}],
    )
    line = lines[0]
    if sale_qty > 0:
        sale = validate_success(api_client.create_sale(
            create_sale_payload(fair_id=fair["id"],
                                lines=[{"stock_line_id": line["id"], "qty": sale_qty}]),
            CASHIER,
        ), expected_status=201)
        validate_success(api_client.tender_sale(
            sale["id"], {"tendered_amount_cents": sale_qty * line_price}, CASHIER
        ))
    from test_helpers import make_organizer_headers
    validate_success(api_client.close_sales(fair["id"], make_organizer_headers("org_lead_1")))
    recon = validate_success(api_client.list_reconciliations(
        ORG, params={"fair_id": fair["id"]}
    ))[0]
    from test_helpers import enter_counts_and_submit, approve_reconciliation_as_other
    expected = qty_delivered - sale_qty
    enter_counts_and_submit(recon["id"], {line["id"]: expected})
    approve_reconciliation_as_other(recon["id"])
    validate_success(api_client.submit_reconciliation(recon["id"], ORG))
    validate_success(api_client.accept_reconciliation(
        recon["id"], __import__("test_helpers").make_publisher_rep_headers(pub["id"])
    ))
    return fair, agr, line


class TestBookingSettlement:
    def test_travel_cap_error_then_settle_math(self, api):
        """PRD §3.4: "The organizer records actual travel spend as
        `travel_actual_cents`, moving the booking `CONFIRMED` → `TRAVEL_BOOKED`;
        the recorded amount may not exceed the booking's `travel_cap_cents`
        (`ERR_TRAVEL_CAP_EXCEEDED`, HTTP 409)."
        PRD §3.9: "Settlement fixes `settled_total_cents` as the sum of
        `base_honorarium_cents`, the accrued `accrued_bonus_cents`, and the
        smaller of `travel_actual_cents` and `travel_cap_cents`, and moves the
        booking to `SETTLED`."

        Design: Corner/calculations/travel_cap_error_then_settle_math
        """
        from test_helpers import make_author, make_confirmed_booking
        school = make_school()
        pub = make_publisher()
        author = make_author()
        # Fair OPEN so settle is permitted (fair must be OPEN or RECONCILING)
        fair, agr, lines = make_fair_open(school["id"], pub["id"])
        booking = make_confirmed_booking(
            fair["id"], author["id"],
            base_honorarium_cents=10000, travel_cap_cents=2000,
        )
        # 2500 exceeds the 2000 cap
        resp = api.book_travel(booking["id"], {"travel_actual_cents": 2500}, ORG)
        validate_error(resp, ApiErrorId.ERR_TRAVEL_CAP_EXCEEDED)
        still = validate_success(api.get_booking(booking["id"], ORG))
        assert still["status"] == "CONFIRMED"
        # 1500 within cap succeeds
        validate_success(api.book_travel(booking["id"], {"travel_actual_cents": 1500}, ORG))
        settled = validate_success(api.settle_booking(booking["id"], ORG))
        # settled = 10000 + 0 bonus + min(1500, 2000) = 11500
        assert settled["settled_total_cents"] == 11500
        fair_after = validate_success(api.get_fair(fair["id"], ORG))
        assert fair_after["honorarium_total_cents"] == 11500


class TestPayoutVariants:
    def test_payout_cash_vs_scrip_variant_divergence(self, api):
        """PRD §3.9: "Step five computes both payout variants:
        `cash_amount_cents` equals `share_cents`, while `scrip_amount_cents` is
        `share_cents` uplifted by fifteen percent and rounded half-up — the
        scrip variant is never less than the cash one"

        Design: Difficulty/dual_variant_calc/payout_cash_vs_scrip_variant_divergence
        """
        school = make_school()
        pub = make_publisher()
        # gross 5000, remittance 3000 -> net 2000 -> share 400; cash 400; scrip round(400*1.15)=460
        fair, agr, line = _fair_with_accepted_recon(school, pub, sale_qty=5, qty_delivered=10)
        fair_now = validate_success(api.get_fair(fair["id"], ORG))
        assert fair_now["publisher_remittance_cents"] == 3000
        payout = validate_success(api.create_payout({"fair_id": fair["id"]}, ORG), expected_status=201)
        calc = validate_success(api.calculate_payout(payout["id"], ORG))
        assert calc["net_revenue_cents"] == 2000
        assert calc["share_cents"] == 400
        assert calc["cash_amount_cents"] == 400
        assert calc["scrip_amount_cents"] == 460
        assert calc["cash_amount_cents"] != calc["scrip_amount_cents"]

    def test_payout_scrip_uplift_single_final_rounding(self, api):
        """PRD §3.9: "Step five computes both payout variants:
        `cash_amount_cents` equals `share_cents`, while `scrip_amount_cents` is
        `share_cents` uplifted by fifteen percent and rounded half-up — the
        scrip variant is never less than the cash one, so a 40,000-cent share
        locks 40,000 cents cash against 46,000 cents scrip."
        PRD §2.7: "Under the **single-final-rounding** doctrine — used by the
        school profit share and the scrip uplift — the full computation is
        carried out unrounded and rounded half-up exactly once at the end."

        Design: Difficulty/dual_variant_calc/payout_cash_vs_scrip_variant_divergence
        """
        school = make_school()
        pub = make_publisher()
        # Net 200000 -> share 40000; cash 40000; scrip round_half_up(40000*1.15)=46000
        fair, agr, line = _fair_with_accepted_recon(
            school, pub, sale_qty=500, qty_delivered=600
        )
        payout = validate_success(api.create_payout({"fair_id": fair["id"]}, ORG), expected_status=201)
        calc = validate_success(api.calculate_payout(payout["id"], ORG))
        assert calc["cash_amount_cents"] == 40000
        assert calc["scrip_amount_cents"] == 46000

    def test_payout_tiered_share_marginal_boundary(self, api):
        """PRD §3.9: "otherwise the share is marginal — twenty percent of the
        first $2,000 of net revenue, plus twenty-five percent of the portion
        between $2,000 and $6,000, plus thirty percent of any portion beyond
        $6,000 — with the three tier amounts summed unrounded and rounded
        half-up exactly once into `share_cents`; per-tier rounding is
        prohibited."

        Design: Difficulty/combinatorial_formula/payout_tiered_share_marginal_boundary
        """
        school = make_school()
        pub = make_publisher()
        # gross 500000, remittance 300000 -> net 200000 == TIER1 cap exactly
        fair, agr, line = _fair_with_accepted_recon(
            school, pub, sale_qty=500, qty_delivered=600
        )
        fair_now = validate_success(api.get_fair(fair["id"], ORG))
        assert fair_now["publisher_remittance_cents"] == 300000
        payout = validate_success(api.create_payout({"fair_id": fair["id"]}, ORG), expected_status=201)
        calc = validate_success(api.calculate_payout(payout["id"], ORG))
        assert calc["net_revenue_cents"] == 200000
        # tier1 = 0.20 * 200000 = 40000; tier2 = 0.25 * max(0, min(200000,600000)-200000) = 0
        assert calc["share_cents"] == 40000
        assert calc["cash_amount_cents"] == 40000
        assert calc["scrip_amount_cents"] == 46000

    def test_payout_tier2_marginal_above_tier1(self, api):
        """PRD §3.9: "otherwise the share is marginal — twenty percent of the
        first $2,000 of net revenue, plus twenty-five percent of the portion
        between $2,000 and $6,000, plus thirty percent of any portion beyond
        $6,000 — with the three tier amounts summed unrounded and rounded
        half-up exactly once into `share_cents`; per-tier rounding is
        prohibited."

        Design: Difficulty/combinatorial_formula/payout_tiered_share_marginal_boundary
        """
        school = make_school()
        pub = make_publisher()
        # gross 500400, remit 300000 -> net 200400
        # tier1 = 0.20*200000 = 40000; tier2 = 0.25 * (200400-200000) = 100; share = 40100
        fair, agr, lines = make_fair_open(
            school["id"], pub["id"],
            line_specs=[{"qty_committed": 600, "qty_delivered": 600}],
        )
        line = lines[0]
        sale = validate_success(api.create_sale(
            create_sale_payload(fair_id=fair["id"],
                                lines=[{"stock_line_id": line["id"], "qty": 500}]),
            CASHIER,
        ), expected_status=201)
        validate_success(api.tender_sale(sale["id"], {"tendered_amount_cents": 500000}, CASHIER))
        # Second sale at the default list price of 1000 for 0.4 additional gross? No — use
        # a markdown-priced second line at 400 to push gross to 500400.
        sale2 = validate_success(api.create_sale(
            create_sale_payload(fair_id=fair["id"],
                                lines=[{"stock_line_id": line["id"], "qty": 1,
                                        "unit_price_cents": 800}]),
            CASHIER,
        ), expected_status=201)
        validate_success(api.tender_sale(sale2["id"], {"tendered_amount_cents": 800}, CASHIER))
        # gross now 500800; remit = round_half_up(501*1000*0.60) = 300600 -> net 200200
        from test_helpers import make_organizer_headers, make_publisher_rep_headers
        validate_success(api.close_sales(fair["id"], make_organizer_headers("org_lead_1")))
        recon = validate_success(api.list_reconciliations(ORG, params={"fair_id": fair["id"]}))[0]
        from test_helpers import enter_counts_and_submit, approve_reconciliation_as_other
        enter_counts_and_submit(recon["id"], {line["id"]: 600 - 501})
        approve_reconciliation_as_other(recon["id"])
        validate_success(api.submit_reconciliation(recon["id"], ORG))
        validate_success(api.accept_reconciliation(recon["id"], make_publisher_rep_headers(pub["id"])))
        payout = validate_success(api.create_payout({"fair_id": fair["id"]}, ORG), expected_status=201)
        calc = validate_success(api.calculate_payout(payout["id"], ORG))
        # net = 500800 - 300600 = 200200; share = 40000 + 0.25*200 = 40050
        assert calc["net_revenue_cents"] == 200200
        assert calc["share_cents"] == 40050

    def test_payout_zero_when_net_nonpositive(self, api):
        """PRD §3.9: "when net revenue is zero or negative, `share_cents` is
        zero"

        Design: Corner/calculations/payout_zero_when_net_nonpositive
        """
        school = make_school()
        pub = make_publisher()
        # No lines, no sales: net == 0
        fair, agr, lines = make_fair_open(school["id"], pub["id"], line_specs=[])
        from test_helpers import make_organizer_headers, make_publisher_rep_headers
        validate_success(api.close_sales(fair["id"], make_organizer_headers("org_lead_1")))
        recon = validate_success(api.list_reconciliations(ORG, params={"fair_id": fair["id"]}))[0]
        validate_success(api.post_counts(
            recon["id"], {"lines": [], "expected_reconciliation_version": recon["version"]}, ORG
        ))
        validate_success(api.submit_review(recon["id"], ORG))
        validate_success(api.approve_reconciliation(recon["id"], make_organizer_headers("org_lead_2")))
        validate_success(api.submit_reconciliation(recon["id"], ORG))
        validate_success(api.accept_reconciliation(recon["id"], make_publisher_rep_headers(pub["id"])))
        payout = validate_success(api.create_payout({"fair_id": fair["id"]}, ORG), expected_status=201)
        calc = validate_success(api.calculate_payout(payout["id"], ORG))
        assert calc["net_revenue_cents"] == 0
        assert calc["share_cents"] == 0
        assert calc["cash_amount_cents"] == 0
        assert calc["scrip_amount_cents"] == 0


class TestPayoutRevisionLoop:
    def test_payout_recalculate_revision_loop(self, api):
        """PRD §3.9: "the organizer's recalculation step (`CALCULATED` →
        `DRAFT`) clears all computed amounts and opens the revision loop
        explicitly."
        PRD §3.9: "the choice is locked: `final_amount_cents` becomes
        `cash_amount_cents` when `CASH` is chosen and `scrip_amount_cents` when
        `SCRIP` is chosen, and the payout moves to `APPROVED`."

        Design: Difficulty/non_linear_state_machine/payout_recalculate_revision_loop
        """
        school = make_school()
        pub = make_publisher()
        fair, agr, line = _fair_with_accepted_recon(school, pub, sale_qty=5, qty_delivered=10)
        payout = validate_success(api.create_payout({"fair_id": fair["id"]}, ORG), expected_status=201)
        calc1 = validate_success(api.calculate_payout(payout["id"], ORG))
        assert calc1["cash_amount_cents"] == 400

        rec = validate_success(api.recalculate_payout(payout["id"], ORG))
        assert rec["status"] == "DRAFT"
        assert rec["cash_amount_cents"] is None

        calc2 = validate_success(api.calculate_payout(payout["id"], ORG))
        assert calc2["cash_amount_cents"] == 400
        assert calc2["scrip_amount_cents"] == 460

        approved = validate_success(api.approve_payout(
            payout["id"], {"mode": "SCRIP"},
            make_school_coordinator_headers(school["id"]),
        ))
        assert approved["mode"] == "SCRIP"
        assert approved["final_amount_cents"] == 460

    def test_payout_approve_cash_variant(self, api):
        """PRD §3.9: "the choice is locked: `final_amount_cents` becomes
        `cash_amount_cents` when `CASH` is chosen and `scrip_amount_cents` when
        `SCRIP` is chosen, and the payout moves to `APPROVED`."

        Design: Difficulty/non_linear_state_machine/payout_recalculate_revision_loop
        """
        school = make_school()
        pub = make_publisher()
        fair, agr, line = _fair_with_accepted_recon(school, pub, sale_qty=5, qty_delivered=10)
        payout = validate_success(api.create_payout({"fair_id": fair["id"]}, ORG), expected_status=201)
        validate_success(api.calculate_payout(payout["id"], ORG))
        approved = validate_success(api.approve_payout(
            payout["id"], {"mode": "CASH"},
            make_school_coordinator_headers(school["id"]),
        ))
        assert approved["mode"] == "CASH"
        assert approved["final_amount_cents"] == 400


class TestFairCancelCascade:
    def test_fair_cancel_depth3_cascade(self, api):
        """PRD §3.1: "The cancellation cascades in a deliberate order: first
        every `HELD` or `CONFIRMED` venue slot of the fair is released; then
        every non-terminal author booking of the fair is cancelled, accruing the
        kill fee described in §3.4; each booking so cancelled cancels its own
        non-terminal signing sessions (`SCHEDULED`, `OPEN_FOR_SIGNING`, or
        `CLOSED_FOR_SIGNING` become `CANCELLED`) — an effect of the booking
        transition, not of the fair directly; each session so cancelled voids
        its own non-terminal tickets (`ISSUED` or `ADMITTED` become `VOIDED`) —
        an effect of the session transition; finally every preorder still
        `PLACED` or `ALLOCATED` is cancelled, releasing any held stock."
        PRD §3.4: "the schedule is zero from those states, one quarter of base
        from `CONFIRMED`, one half of base from `TRAVEL_BOOKED`"

        Design: Difficulty/transitive_cascade/fair_cancel_depth3_cascade
        """
        from test_helpers import (
            make_author, make_fair, make_confirmed_venue_slot,
            make_travel_booked_booking, make_session, create_ticket_payload,
        )
        school = make_school()
        author = make_author()
        fair = make_fair(school["id"])
        slot = make_confirmed_venue_slot(fair["id"], school["id"])
        booking = make_travel_booked_booking(
            fair["id"], author["id"], base_honorarium_cents=10000,
            travel_cap_cents=2000, travel_actual_cents=1500,
        )
        session = make_session(booking["id"], fair["id"], mode="TICKETED")
        t1 = validate_success(api.create_ticket(
            create_ticket_payload(session_id=session["id"], holder_name="Kid One"),
            TEST_USERS["linestaff_headers"],
        ), expected_status=201)
        t2 = validate_success(api.create_ticket(
            create_ticket_payload(session_id=session["id"], holder_name="Kid Two"),
            TEST_USERS["linestaff_headers"],
        ), expected_status=201)

        validate_success(api.cancel_fair(fair["id"], ORG, {"reason": "weather closure"}))

        fair_after = validate_success(api.get_fair(fair["id"], ORG))
        assert fair_after["status"] == "CANCELLED"
        assert fair_after["honorarium_total_cents"] == 5000

        slot_after = validate_success(api.get_venue_slot(slot["id"], ORG))
        assert slot_after["status"] == "RELEASED"

        booking_after = validate_success(api.get_booking(booking["id"], ORG))
        assert booking_after["status"] == "CANCELLED"
        assert booking_after["kill_fee_cents"] == 5000

        session_after = validate_success(api.get_session(session["id"], ORG))
        assert session_after["status"] == "CANCELLED"

        t1_after = validate_success(api.get_ticket(t1["id"], ORG))
        t2_after = validate_success(api.get_ticket(t2["id"], ORG))
        assert t1_after["status"] == "VOIDED"
        assert t2_after["status"] == "VOIDED"

    def test_fair_cancel_kill_fee_from_confirmed(self, api):
        """PRD §3.4: "the accrued `kill_fee_cents` is one quarter of
        `base_honorarium_cents` — rounded half-up — when cancelled from
        `CONFIRMED`, and one half of `base_honorarium_cents` — rounded half-up —
        when cancelled from `TRAVEL_BOOKED`."

        Design: Difficulty/transitive_cascade/fair_cancel_depth3_cascade
        """
        from test_helpers import make_author, make_fair, make_confirmed_booking
        school = make_school()
        author = make_author()
        fair = make_fair(school["id"])
        booking = make_confirmed_booking(
            fair["id"], author["id"], base_honorarium_cents=10000,
        )
        validate_success(api.cancel_fair(fair["id"], ORG, {}))
        booking_after = validate_success(api.get_booking(booking["id"], ORG))
        assert booking_after["status"] == "CANCELLED"
        # 25% of 10000 from CONFIRMED
        assert booking_after["kill_fee_cents"] == 2500
        fair_after = validate_success(api.get_fair(fair["id"], ORG))
        assert fair_after["honorarium_total_cents"] == 2500
