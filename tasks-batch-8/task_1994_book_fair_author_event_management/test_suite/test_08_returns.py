"""Return authorizations: gates, waterfall credit, snapshot staleness."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    create_return_authorization_payload,
    create_sale_payload,
    make_school,
    make_publisher,
    make_fair_open,
    make_reconciling_fair,
    make_accepted_reconciliation,
    make_organizer_headers,
    make_publisher_rep_headers,
    TEST_USERS,
)

ORG = TEST_USERS["organizer_headers"]
CASHIER = TEST_USERS["cashier_headers"]


def _approved_recon_fair():
    """Fair RECONCILING with one FRONTLIST line delivered 10 (no sales), recon APPROVED."""
    school = make_school()
    pub = make_publisher()
    ctx = make_reconciling_fair(school["id"], pub["id"])
    line = ctx["lines"][0]
    from test_helpers import enter_counts_and_submit, approve_reconciliation_as_other
    enter_counts_and_submit(ctx["reconciliation"]["id"], {line["id"]: 10})
    approve_reconciliation_as_other(ctx["reconciliation"]["id"])
    ctx["fair"] = validate_success(api_client.get_fair(ctx["fair"]["id"], ORG))
    ctx["reconciliation"] = validate_success(
        api_client.get_reconciliation(ctx["reconciliation"]["id"], ORG)
    )
    return school, pub, ctx


class TestReturnGates:
    def test_return_create_blocked_before_recon_approved(self, api):
        """PRD §3.8: "the fair's latest reconciliation must be `APPROVED`,
        `SUBMITTED`, or `ACCEPTED` (`ERR_RECONCILIATION_NOT_APPROVED`, HTTP
        409)"

        Design: Corner/errors/return_create_blocked_before_recon_approved
        """
        school = make_school()
        pub = make_publisher()
        ctx = make_reconciling_fair(school["id"], pub["id"])
        line = ctx["lines"][0]
        # Reconciliation is still OPEN (no counts entered)
        resp = api.create_return_authorization(
            create_return_authorization_payload(
                fair_id=ctx["fair"]["id"], agreement_id=ctx["agreement"]["id"],
                lines=[{"stock_line_id": line["id"], "qty": 2}],
            ), ORG,
        )
        validate_error(resp, ApiErrorId.ERR_RECONCILIATION_NOT_APPROVED)

    def test_firm_line_not_returnable(self, api):
        """PRD §3.8: "every referenced line must be `FRONTLIST` — `BACKLIST`
        lines are firm purchases and cannot be returned
        (`ERR_FIRM_SALE_NOT_RETURNABLE`, HTTP 409)."
        PRD §3.3: "`BACKLIST`, meaning a firm purchase whose cost accrues at
        delivery ... `firm_purchases_cents` grows by the per-line amount
        computed as `qty_delivered` times `list_price_cents` scaled by one minus
        the agreement's `discount_pct`, rounded half-up per line before being
        added."

        Design: Corner/errors/firm_line_not_returnable
        """
        school = make_school()
        pub = make_publisher()
        # One BACKLIST line, delivered 4
        ctx = make_reconciling_fair(
            school["id"], pub["id"],
            line_specs=[{"isbn": "9780000000009", "title": "Backlist Classic",
                         "line_type": "BACKLIST", "qty_committed": 4, "qty_delivered": 4}],
        )
        line = ctx["lines"][0]
        from test_helpers import enter_counts_and_submit, approve_reconciliation_as_other
        enter_counts_and_submit(ctx["reconciliation"]["id"], {line["id"]: 4})
        approve_reconciliation_as_other(ctx["reconciliation"]["id"])

        resp = api.create_return_authorization(
            create_return_authorization_payload(
                fair_id=ctx["fair"]["id"], agreement_id=ctx["agreement"]["id"],
                lines=[{"stock_line_id": line["id"], "qty": 1}],
            ), ORG,
        )
        validate_error(resp, ApiErrorId.ERR_FIRM_SALE_NOT_RETURNABLE)

        # BACKLIST firm cost accrued at deliver: round_half_up(4 * 1000 * 0.60) == 2400
        fair_after = validate_success(api.get_fair(ctx["fair"]["id"], ORG))
        assert fair_after["firm_purchases_cents"] == 2400

    def test_return_quantity_exceeds_on_hand(self, api):
        """PRD §3.8: "the cumulative quantity across this authorization and all
        of the fair's other `APPROVED`, `SHIPPED`, or `CREDITED` authorizations
        for that line may not exceed the line's `qty_delivered` minus `qty_sold`
        minus `qty_damaged` (`ERR_RETURN_QUANTITY_EXCEEDS_ON_HAND`, HTTP 409)."

        Design: Corner/errors/return_quantity_exceeds_on_hand
        """
        school, pub, ctx = _approved_recon_fair()
        line = ctx["lines"][0]
        ra1 = validate_success(api.create_return_authorization(
            create_return_authorization_payload(
                fair_id=ctx["fair"]["id"], agreement_id=ctx["agreement"]["id"],
                lines=[{"stock_line_id": line["id"], "qty": 4}],
            ), ORG,
        ), expected_status=201)
        validate_success(api.approve_return(ra1["id"], make_publisher_rep_headers(pub["id"])))
        ra2 = validate_success(api.create_return_authorization(
            create_return_authorization_payload(
                fair_id=ctx["fair"]["id"], agreement_id=ctx["agreement"]["id"],
                lines=[{"stock_line_id": line["id"], "qty": 8}],
            ), ORG,
        ), expected_status=201)
        resp = api.approve_return(ra2["id"], make_publisher_rep_headers(pub["id"]))
        validate_error(resp, ApiErrorId.ERR_RETURN_QUANTITY_EXCEEDS_ON_HAND)
        after = validate_success(api.get_return_authorization(ra2["id"], ORG))
        assert after["status"] == "REQUESTED"

    def test_return_quantity_exact_boundary_approved(self, api):
        """PRD §3.8: "the cumulative quantity across this authorization and all
        of the fair's other `APPROVED`, `SHIPPED`, or `CREDITED` authorizations
        for that line may not exceed the line's `qty_delivered` minus `qty_sold`
        minus `qty_damaged` (`ERR_RETURN_QUANTITY_EXCEEDS_ON_HAND`, HTTP 409)."

        Design: Corner/errors/return_quantity_exceeds_on_hand
        """
        school, pub, ctx = _approved_recon_fair()
        line = ctx["lines"][0]
        # qty_delivered 10, sold 0, damaged 0: cumulative exactly 10 passes
        ra = validate_success(api.create_return_authorization(
            create_return_authorization_payload(
                fair_id=ctx["fair"]["id"], agreement_id=ctx["agreement"]["id"],
                lines=[{"stock_line_id": line["id"], "qty": 10}],
            ), ORG,
        ), expected_status=201)
        ok = validate_success(api.approve_return(ra["id"], make_publisher_rep_headers(pub["id"])))
        assert ok["status"] == "APPROVED"


class TestReturnWaterfall:
    def test_return_credit_waterfall_cap_boundary(self, api):
        """PRD §3.8: "The per-line cap is the floor of `return_cap_pct` times
        `qty_delivered`; prior authorizations of the fair in `APPROVED`,
        `SHIPPED`, or `CREDITED` status consume cap first in their creation
        order; and within this authorization each line's copies are split so
        that the in-cap portion — the smaller of the line's `qty` and the cap
        remaining after prior consumption, floored at zero — is credited at
        `list_price_cents` scaled by one minus `discount_pct`, rounded half-up,
        while the over-cap remainder is credited at that same discounted base
        further scaled by one minus `restocking_fee_pct`, also rounded half-up;
        the two rounded components sum to the line's credit, and the line
        credits sum to `credit_cents`"
        PRD §3.8: "A cumulative quantity exactly equal to the cap is fully
        in-cap; only the first copy beyond the cap earns the reduced rate."

        Design: Difficulty/combinatorial_formula/return_credit_waterfall_cap_boundary
        """
        school = make_school()
        pub = make_publisher()
        # delivered 20, return_cap_pct 0.25 -> cap = floor(5) = 5; discount 0.40; restock 0.10
        ctx = make_reconciling_fair(
            school["id"], pub["id"],
            line_specs=[{"qty_committed": 20, "qty_delivered": 20}],
        )
        line = ctx["lines"][0]
        from test_helpers import enter_counts_and_submit, approve_reconciliation_as_other
        enter_counts_and_submit(ctx["reconciliation"]["id"], {line["id"]: 20})
        approve_reconciliation_as_other(ctx["reconciliation"]["id"])

        # RA1: qty 5 == cap -> fully in-cap: 5 * 1000 * 0.60 = 3000
        ra1 = validate_success(api.create_return_authorization(
            create_return_authorization_payload(
                fair_id=ctx["fair"]["id"], agreement_id=ctx["agreement"]["id"],
                lines=[{"stock_line_id": line["id"], "qty": 5}],
            ), ORG,
        ), expected_status=201)
        validate_success(api.approve_return(ra1["id"], make_publisher_rep_headers(pub["id"])))
        validate_success(api.ship_return(ra1["id"], ORG))
        credited1 = validate_success(api.confirm_credit_return(ra1["id"], ORG))
        assert credited1["credit_cents"] == 3000

        # RA2: qty 2, cap exhausted -> over-cap: 2 * round_half_up(1000*0.60*0.90)=2*540=1080
        ra2 = validate_success(api.create_return_authorization(
            create_return_authorization_payload(
                fair_id=ctx["fair"]["id"], agreement_id=ctx["agreement"]["id"],
                lines=[{"stock_line_id": line["id"], "qty": 2}],
            ), ORG,
        ), expected_status=201)
        validate_success(api.approve_return(ra2["id"], make_publisher_rep_headers(pub["id"])))
        validate_success(api.ship_return(ra2["id"], ORG))
        credited2 = validate_success(api.confirm_credit_return(ra2["id"], ORG))
        assert credited2["credit_cents"] == 1080

        line_after = validate_success(api.get_stock_line(line["id"], ORG))
        assert line_after["qty_returned_credited"] == 7
        fair_after = validate_success(api.get_fair(ctx["fair"]["id"], ORG))
        assert fair_after["return_credits_cents"] == 4080

    def test_return_credit_in_cap_at_exact_cap(self, api):
        """PRD §3.8: "A cumulative quantity exactly equal to the cap is fully
        in-cap; only the first copy beyond the cap earns the reduced rate."

        Design: Difficulty/combinatorial_formula/return_credit_waterfall_cap_boundary
        """
        school = make_school()
        pub = make_publisher()
        # cap = floor(0.25 * 20) = 5; qty 5 == cap -> fully in-cap
        ctx = make_reconciling_fair(
            school["id"], pub["id"],
            line_specs=[{"qty_committed": 20, "qty_delivered": 20}],
        )
        line = ctx["lines"][0]
        from test_helpers import enter_counts_and_submit, approve_reconciliation_as_other
        enter_counts_and_submit(ctx["reconciliation"]["id"], {line["id"]: 20})
        approve_reconciliation_as_other(ctx["reconciliation"]["id"])
        ra = validate_success(api.create_return_authorization(
            create_return_authorization_payload(
                fair_id=ctx["fair"]["id"], agreement_id=ctx["agreement"]["id"],
                lines=[{"stock_line_id": line["id"], "qty": 5}],
            ), ORG,
        ), expected_status=201)
        validate_success(api.approve_return(ra["id"], make_publisher_rep_headers(pub["id"])))
        validate_success(api.ship_return(ra["id"], ORG))
        credited = validate_success(api.confirm_credit_return(ra["id"], ORG))
        # Fully in-cap: 5 * 1000 * 0.60 = 3000, no restocking fee
        assert credited["credit_cents"] == 3000

    def test_return_credit_cascade_depth2_snapshot_staleness(self, api):
        """PRD §3.8: "Link two follows from the counter mutation: the fair's
        `return_credits_cents` grows by `credit_cents` — while any payout
        already `CALCULATED` is deliberately left stale, per the snapshot
        semantics of §2.11, until someone recalculates it."
        PRD §2.11: "a payout that has been calculated captures a **snapshot** of
        the fair's totals at calculation time, and later mutations — a newly
        credited return, a late damage write-off — do not refresh it."

        Design: Difficulty/transitive_cascade/return_credit_cascade_depth2_snapshot_staleness
        """
        school = make_school()
        pub = make_publisher()
        # FRONTLIST line list 1000 delivered 20; one TENDERED sale qty 10 (gross 10000)
        fair, agr, lines = make_fair_open(
            school["id"], pub["id"],
            line_specs=[{"qty_committed": 20, "qty_delivered": 20}],
        )
        line = lines[0]
        sale = validate_success(api.create_sale(
            create_sale_payload(fair_id=fair["id"],
                                lines=[{"stock_line_id": line["id"], "qty": 10}]),
            CASHIER,
        ), expected_status=201)
        validate_success(api.tender_sale(sale["id"], {"tendered_amount_cents": 10000}, CASHIER))
        validate_success(api.close_sales(fair["id"], make_organizer_headers("org_lead_1")))
        recon = validate_success(api.list_reconciliations(ORG, params={"fair_id": fair["id"]}))[0]
        recon_id = recon["id"]
        from test_helpers import enter_counts_and_submit, approve_reconciliation_as_other
        enter_counts_and_submit(recon_id, {line["id"]: 10})
        approve_reconciliation_as_other(recon_id)
        validate_success(api.submit_reconciliation(recon_id, ORG))
        validate_success(api.accept_reconciliation(recon_id, make_publisher_rep_headers(pub["id"])))

        # Payout CALCULATED: net = 10000 - 6000 = 4000; share = 0.20*4000 = 800
        payout = validate_success(api.create_payout({"fair_id": fair["id"]}, ORG), expected_status=201)
        calc = validate_success(api.calculate_payout(payout["id"], ORG))
        assert calc["cash_amount_cents"] == 800

        # Return qty 2, in-cap (cap 5), credit = 2 * 1000 * 0.60 = 1200
        ra = validate_success(api.create_return_authorization(
            create_return_authorization_payload(
                fair_id=fair["id"], agreement_id=agr["id"],
                lines=[{"stock_line_id": line["id"], "qty": 2}],
            ), ORG,
        ), expected_status=201)
        validate_success(api.approve_return(ra["id"], make_publisher_rep_headers(pub["id"])))
        validate_success(api.ship_return(ra["id"], ORG))
        credited = validate_success(api.confirm_credit_return(ra["id"], ORG))
        assert credited["credit_cents"] == 1200

        line_after = validate_success(api.get_stock_line(line["id"], ORG))
        assert line_after["qty_returned_credited"] == 2
        fair_after = validate_success(api.get_fair(fair["id"], ORG))
        assert fair_after["return_credits_cents"] == 1200
        # The CALCULATED payout is a snapshot: NOT refreshed by the credit
        payout_after = validate_success(api.get_payout(payout["id"], ORG))
        assert payout_after["cash_amount_cents"] == 800

    def test_return_credit_snapshot_refreshed_by_recalculate(self, api):
        """PRD §2.11: "a payout that has been calculated captures a **snapshot**
        of the fair's totals at calculation time, and later mutations — a newly
        credited return, a late damage write-off — do not refresh it. Revising
        the payout requires an explicit recalculation, which returns it to
        `DRAFT` and clears its computed amounts."

        Design: Difficulty/transitive_cascade/return_credit_cascade_depth2_snapshot_staleness
        """
        school = make_school()
        pub = make_publisher()
        fair, agr, lines = make_fair_open(
            school["id"], pub["id"],
            line_specs=[{"qty_committed": 20, "qty_delivered": 20}],
        )
        line = lines[0]
        sale = validate_success(api.create_sale(
            create_sale_payload(fair_id=fair["id"],
                                lines=[{"stock_line_id": line["id"], "qty": 10}]),
            CASHIER,
        ), expected_status=201)
        validate_success(api.tender_sale(sale["id"], {"tendered_amount_cents": 10000}, CASHIER))
        validate_success(api.close_sales(fair["id"], make_organizer_headers("org_lead_1")))
        recon = validate_success(api.list_reconciliations(ORG, params={"fair_id": fair["id"]}))[0]
        from test_helpers import enter_counts_and_submit, approve_reconciliation_as_other
        enter_counts_and_submit(recon["id"], {line["id"]: 10})
        approve_reconciliation_as_other(recon["id"])
        validate_success(api.submit_reconciliation(recon["id"], ORG))
        validate_success(api.accept_reconciliation(recon["id"], make_publisher_rep_headers(pub["id"])))

        payout = validate_success(api.create_payout({"fair_id": fair["id"]}, ORG), expected_status=201)
        calc1 = validate_success(api.calculate_payout(payout["id"], ORG))
        assert calc1["cash_amount_cents"] == 800

        # Credit a return of qty 2 (in-cap): fair.return_credits_cents += 1200
        ra = validate_success(api.create_return_authorization(
            create_return_authorization_payload(
                fair_id=fair["id"], agreement_id=agr["id"],
                lines=[{"stock_line_id": line["id"], "qty": 2}],
            ), ORG,
        ), expected_status=201)
        validate_success(api.approve_return(ra["id"], make_publisher_rep_headers(pub["id"])))
        validate_success(api.ship_return(ra["id"], ORG))
        validate_success(api.confirm_credit_return(ra["id"], ORG))

        # Snapshot unchanged
        stale = validate_success(api.get_payout(payout["id"], ORG))
        assert stale["cash_amount_cents"] == 800
        # Explicit recalculate clears and recomputes against the new basis:
        # net = 10000 - 6000 + 1200 = 5200; share = 0.20 * 5200 = 1040
        rec = validate_success(api.recalculate_payout(payout["id"], ORG))
        assert rec["status"] == "DRAFT"
        calc2 = validate_success(api.calculate_payout(payout["id"], ORG))
        assert calc2["net_revenue_cents"] == 5200
        assert calc2["share_cents"] == 1040
        assert calc2["cash_amount_cents"] == 1040
