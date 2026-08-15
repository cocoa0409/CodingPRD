"""Reconciliation: close-sales spawn, counts OCC, variance, approve gates, dispute cycle."""
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
    make_reconciling_fair,
    make_accepted_reconciliation,
    enter_counts_and_submit,
    approve_reconciliation_as_other,
    make_organizer_headers,
    make_publisher_rep_headers,
    TEST_USERS,
)

ORG = TEST_USERS["organizer_headers"]
CASHIER = TEST_USERS["cashier_headers"]


class TestCloseSalesSpawn:
    def test_close_sales_spawns_reconciliation_snapshot(self, api):
        """PRD §3.7: "a `Reconciliation` is spawned for the fair in `OPEN`
        status, stamped with `created_by_user_id` equal to the acting
        organizer's `X-User-ID` — the segregation-of-duties anchor — and with
        `provisional_lines` initialized from the stock counters as they stand."
        PRD §3.7: "Each provisional line covers one `DELIVERED` stock line of
        the fair and pairs `stock_line_id` with `expected_on_hand`: the copies
        the books say should remain, computed as `qty_delivered` minus
        `qty_sold`, minus `qty_damaged`, minus `qty_returned_shipped`, minus
        `qty_held_preorder`."

        Design: Corner/endpoints/close_sales_spawns_reconciliation_snapshot
        """
        school = make_school()
        pub = make_publisher()
        fair, agr, lines = make_fair_open(school["id"], pub["id"])
        line = lines[0]
        validate_success(api.close_sales(fair["id"], make_organizer_headers("org_lead_1")))
        after_fair = validate_success(api.get_fair(fair["id"], ORG))
        assert after_fair["status"] == "RECONCILING"

        resp = api.list_reconciliations(ORG, params={"fair_id": fair["id"]})
        data = validate_success(resp)
        assert isinstance(data, list) and len(data) == 1
        recon = data[0]
        assert recon["status"] == "OPEN"
        assert recon["created_by_user_id"] == "org_lead_1"
        prov = {p["stock_line_id"]: p["expected_on_hand"] for p in recon["provisional_lines"]}
        assert prov[line["id"]] == 10

    def test_close_sales_sweeps_allocated_preorders(self, api):
        """PRD §3.7: "every preorder still `ALLOCATED` is swept to `CANCELLED`
        with its hold released"

        Design: Corner/endpoints/close_sales_spawns_reconciliation_snapshot
        """
        school = make_school()
        pub = make_publisher()
        from test_helpers import make_fair_stocking, make_delivered_stock_line, create_preorder_payload
        fair, agr = make_fair_stocking(school["id"], pub["id"])
        line = make_delivered_stock_line(fair["id"], agr["id"], qty_committed=10)
        po = validate_success(api_client.create_preorder(
            create_preorder_payload(fair_id=fair["id"], stock_line_id=line["id"],
                                    customer_name="Ann", qty=2), CASHIER,
        ), expected_status=201)
        validate_success(api.open_fair(fair["id"], ORG))
        mid = validate_success(api.get_preorder(po["id"], ORG))
        assert mid["status"] == "ALLOCATED"

        validate_success(api.close_sales(fair["id"], make_organizer_headers("org_lead_1")))
        after_po = validate_success(api.get_preorder(po["id"], ORG))
        assert after_po["status"] == "CANCELLED"
        after_line = validate_success(api.get_stock_line(line["id"], ORG))
        assert after_line["qty_held_preorder"] == 0


class TestVarianceAndApprove:
    def test_reconciliation_provisional_vs_final_variance(self, api):
        """PRD §3.7: "the counted `qty_on_hand` minus its `expected_on_hand` —
        and `total_abs_variance` as the sum of the absolute per-line variances"
        PRD §3.7: "The books-versus-shelf delta is the whole point: identical
        physical stock can yield a nonzero variance whenever unrecorded shrink
        exists, and that variance drives the review branch."

        Design: Difficulty/dual_variant_calc/reconciliation_provisional_vs_final_variance
        """
        # One line delivered 10, one tendered sale of qty 2
        school = make_school()
        pub = make_publisher()
        fair, agr, lines = make_fair_open(school["id"], pub["id"])
        line = lines[0]
        sale = validate_success(api.create_sale(
            create_sale_payload(fair_id=fair["id"],
                                lines=[{"stock_line_id": line["id"], "qty": 2}]),
            CASHIER,
        ), expected_status=201)
        validate_success(api.tender_sale(sale["id"], {"tendered_amount_cents": 2000}, CASHIER))
        validate_success(api.close_sales(fair["id"], make_organizer_headers("org_lead_1")))
        recon_resp = api.list_reconciliations(ORG, params={"fair_id": fair["id"]})
        recon = validate_success(recon_resp)[0]
        recon_id = recon["id"]
        v = recon["version"]

        # Provisional expected_on_hand == 8 (10 - 2)
        prov = {p["stock_line_id"]: p["expected_on_hand"] for p in recon["provisional_lines"]}
        assert prov[line["id"]] == 8

        # Physical count 7 -> variance -1
        resp = api.post_counts(
            recon_id,
            {"lines": [{"stock_line_id": line["id"], "qty_on_hand": 7}],
             "expected_reconciliation_version": v},
            ORG,
        )
        data = validate_success(resp)
        var_lines = {vl["stock_line_id"]: vl for vl in data["variance_lines"]}
        # variance field name: the PRD says "per line, the counted qty_on_hand minus
        # its expected_on_hand". We read whichever key the implementation exposes.
        vl = var_lines[line["id"]]
        variance_val = vl.get("variance", vl.get("variance_qty"))
        assert variance_val == -1
        assert data["total_abs_variance"] == 1

    def test_reconciliation_provisional_expected_from_counters(self, api):
        """PRD §3.7: "Each provisional line covers one `DELIVERED` stock line of
        the fair and pairs `stock_line_id` with `expected_on_hand`: the copies
        the books say should remain, computed as `qty_delivered` minus
        `qty_sold`, minus `qty_damaged`, minus `qty_returned_shipped`, minus
        `qty_held_preorder`."

        Design: Difficulty/dual_variant_calc/reconciliation_provisional_vs_final_variance
        """
        school = make_school()
        pub = make_publisher()
        fair, agr, lines = make_fair_open(school["id"], pub["id"])
        line = lines[0]
        sale = validate_success(api.create_sale(
            create_sale_payload(fair_id=fair["id"],
                                lines=[{"stock_line_id": line["id"], "qty": 2}]),
            CASHIER,
        ), expected_status=201)
        validate_success(api.tender_sale(sale["id"], {"tendered_amount_cents": 2000}, CASHIER))
        validate_success(api.close_sales(fair["id"], make_organizer_headers("org_lead_1")))
        recon = validate_success(api.list_reconciliations(ORG, params={"fair_id": fair["id"]}))[0]
        prov = {p["stock_line_id"]: p["expected_on_hand"] for p in recon["provisional_lines"]}
        # provisional (system-derived) == 8, distinct from any physical count
        assert prov[line["id"]] == 8

    def test_variance_beyond_tolerance_blocks_approve_until_damage_absorbs(self, api):
        """PRD §3.7: "Only then, the tolerance gate: `total_abs_variance` must
        not exceed the shrink tolerance of two units
        (`ERR_VARIANCE_BEYOND_TOLERANCE`, HTTP 409)."
        PRD §3.3: "Recording damage during `RECONCILING` is the sanctioned
        shrink-absorption path — the reconciliation's expected-on-hand figures
        are recomputed from current counters, so a write-off posted
        mid-reconciliation moves the books into agreement with the shelf."

        Design: Corner/errors/variance_beyond_tolerance_blocks_approve_until_damage_absorbs
        """
        school = make_school()
        pub = make_publisher()
        fair, agr, lines = make_fair_open(school["id"], pub["id"])
        line = lines[0]
        validate_success(api.close_sales(fair["id"], make_organizer_headers("org_lead_1")))
        recon = validate_success(api.list_reconciliations(ORG, params={"fair_id": fair["id"]}))[0]
        recon_id = recon["id"]

        # Count 7 against expected 10 -> variance 3 > tolerance 2
        validate_success(api.post_counts(
            recon_id,
            {"lines": [{"stock_line_id": line["id"], "qty_on_hand": 7}],
             "expected_reconciliation_version": recon["version"]},
            ORG,
        ))
        validate_success(api.submit_review(recon_id, ORG))
        resp = api.approve_reconciliation(recon_id, make_organizer_headers("org_lead_2"))
        validate_error(resp, ApiErrorId.ERR_VARIANCE_BEYOND_TOLERANCE)

        # Absorb the shrink via damage during RECONCILING, then recount
        validate_success(api.damage_stock_line(line["id"], {"qty": 3}, ORG))
        recon_now = validate_success(api.get_reconciliation(recon_id, ORG))
        validate_success(api.post_counts(
            recon_id,
            {"lines": [{"stock_line_id": line["id"], "qty_on_hand": 7}],
             "expected_reconciliation_version": recon_now["version"]},
            ORG,
        ))
        validate_success(api.submit_review(recon_id, ORG))
        approved = validate_success(api.approve_reconciliation(
            recon_id, make_organizer_headers("org_lead_2")
        ))
        assert approved["status"] == "APPROVED"
        assert approved["remittance_cents"] == 0

    def test_counts_incomplete_blocks_submit_review(self, api):
        """PRD §3.7: "Submitting for review moves the reconciliation `OPEN` →
        `VARIANCE_REVIEW` and requires `counted_lines` to cover every
        `DELIVERED` stock line of the fair (`ERR_COUNTS_INCOMPLETE`, HTTP 409)"

        Design: Corner/errors/counts_incomplete_blocks_submit_review
        """
        school = make_school()
        pub = make_publisher()
        fair, agr, lines = make_fair_open(
            school["id"], pub["id"],
            line_specs=[
                {"isbn": "9780000000001", "title": "Alpha", "qty_committed": 5},
                {"isbn": "9780000000002", "title": "Beta", "qty_committed": 7},
            ],
        )
        line_a, line_b = lines
        validate_success(api.close_sales(fair["id"], make_organizer_headers("org_lead_1")))
        recon = validate_success(api.list_reconciliations(ORG, params={"fair_id": fair["id"]}))[0]
        recon_id = recon["id"]
        validate_success(api.post_counts(
            recon_id,
            {"lines": [{"stock_line_id": line_a["id"], "qty_on_hand": 5}],
             "expected_reconciliation_version": recon["version"]},
            ORG,
        ))
        resp = api.submit_review(recon_id, ORG)
        validate_error(resp, ApiErrorId.ERR_COUNTS_INCOMPLETE)
        after = validate_success(api.get_reconciliation(recon_id, ORG))
        assert after["status"] == "OPEN"

    def test_segregation_of_duties_blocks_creator_approve(self, api):
        """PRD §3.7: "First, segregation of duties: the approving organizer's
        `X-User-ID` must differ from the reconciliation's `created_by_user_id`
        (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403)."

        Design: Corner/errors/segregation_of_duties_blocks_creator_approve
        """
        ctx = make_reconciling_fair(make_school()["id"], make_publisher()["id"])
        recon_id = ctx["reconciliation"]["id"]
        line = ctx["lines"][0]
        recon_now = validate_success(api.get_reconciliation(recon_id, ORG))
        enter_counts_and_submit(recon_id, {line["id"]: recon_now["provisional_lines"][0]["expected_on_hand"]})
        # Same organizer id that closed sales tries to approve
        resp = api.approve_reconciliation(recon_id, make_organizer_headers("org_lead_1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        # A different organizer id approves successfully
        ok = validate_success(api.approve_reconciliation(
            recon_id, make_organizer_headers("org_lead_2")
        ))
        assert ok["status"] == "APPROVED"

    def test_recounts_are_occ_guarded(self, api):
        """PRD §2.6: "Posting physical counts to a reconciliation requires
        `expected_reconciliation_version` against the `Reconciliation`'s current
        `version`, again with `ERR_STALE_VERSION` (HTTP 412)"

        Design: Difficulty/non_linear_state_machine/reconciliation_dispute_recount_cycle
        """
        ctx = make_reconciling_fair(make_school()["id"], make_publisher()["id"])
        recon_id = ctx["reconciliation"]["id"]
        line = ctx["lines"][0]
        v = ctx["reconciliation"]["version"]
        # First counts call bumps version
        validate_success(api.post_counts(
            recon_id,
            {"lines": [{"stock_line_id": line["id"], "qty_on_hand": 10}],
             "expected_reconciliation_version": v},
            ORG,
        ))
        # Replaying with the same stale version is rejected
        resp = api.post_counts(
            recon_id,
            {"lines": [{"stock_line_id": line["id"], "qty_on_hand": 9}],
             "expected_reconciliation_version": v},
            ORG,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_reconciliation_dispute_recount_cycle(self, api):
        """PRD §3.7: "the publisher of the fair's accepted agreement rules on
        it: accept (`SUBMITTED` → `ACCEPTED`, terminal) or dispute (`SUBMITTED`
        → `DISPUTED`), the latter recording the payload `reason` into
        `dispute_reason`. A dispute is recovered by recounting, which reopens
        the reconciliation to `OPEN` as described above"

        Design: Difficulty/non_linear_state_machine/reconciliation_dispute_recount_cycle
        """
        school = make_school()
        pub = make_publisher()
        ctx = make_accepted_reconciliation(school["id"], pub["id"])
        recon_id = ctx["reconciliation"]["id"]
        line = ctx["lines"][0]

        # Roll back to SUBMITTED is not possible; rebuild through the dispute branch.
        # Start over from an APPROVED state: submit then dispute.
        # (make_accepted_reconciliation already accepted; build a second fair for the cycle.)
        # Second fair must live on a distinct venue calendar: both fairs would
        # otherwise hold overlapping slots on the default GYM venue_key, which
        # PRD section 2.8 forbids.
        ctx2 = make_reconciling_fair(
            school["id"], pub["id"], fair_overrides={"venue_key": "CAFETERIA"}
        )
        recon2 = ctx2["reconciliation"]
        recon2_id = recon2["id"]
        line2 = ctx2["lines"][0]
        recon_now = validate_success(api.get_reconciliation(recon2_id, ORG))
        expected = {p["stock_line_id"]: p["expected_on_hand"] for p in recon_now["provisional_lines"]}
        enter_counts_and_submit(recon2_id, expected)
        approve_reconciliation_as_other(recon2_id)
        validate_success(api.submit_reconciliation(recon2_id, ORG))
        disputed = validate_success(api.dispute_reconciliation(
            recon2_id, {"reason": "physical recount requested"},
            make_publisher_rep_headers(pub["id"]),
        ))
        assert disputed["status"] == "DISPUTED"
        assert disputed["dispute_reason"] == "physical recount requested"
        v_after_dispute = disputed["version"]

        # Recount from DISPUTED returns to OPEN and clears the reason
        recount = validate_success(api.post_counts(
            recon2_id,
            {"lines": [{"stock_line_id": line2["id"], "qty_on_hand": expected[line2["id"]]}],
             "expected_reconciliation_version": v_after_dispute},
            ORG,
        ))
        assert recount["status"] == "OPEN"
        assert recount["dispute_reason"] is None

        # Second pass completes to ACCEPTED
        validate_success(api.submit_review(recon2_id, ORG))
        approve_reconciliation_as_other(recon2_id)
        validate_success(api.submit_reconciliation(recon2_id, ORG))
        accepted = validate_success(api.accept_reconciliation(
            recon2_id, make_publisher_rep_headers(pub["id"])
        ))
        assert accepted["status"] == "ACCEPTED"


class TestRemittance:
    def test_remittance_per_line_rounding_beats_sum_then_round(self, api):
        """PRD §3.7: "for each `FRONTLIST` line in `DELIVERED` ... the line's
        remittance is `qty_sold` times `list_price_cents` scaled by one minus
        the accepted agreement's `discount_pct`, rounded half-up **per line
        first**, and `remittance_cents` is the sum of those rounded line
        amounts ... The per-line-then-sum order is pinned: three lines of one
        sold copy each at a 999-cent list price under a 0.45 discount remit
        1,647 cents, where rounding only after summation would wrongly yield
        1,648."

        Design: Difficulty/combinatorial_formula/remittance_per_line_rounding_beats_sum_then_round
        """
        from test_helpers import (
            make_fair_stocking,
            make_delivered_stock_line,
            create_agreement_payload,
            make_publisher_rep_headers,
        )
        school = make_school()
        pub = make_publisher()
        # Build the chain manually so the ACCEPTED agreement uses discount 0.45.
        from test_helpers import make_fair_scheduled
        fair = make_fair_scheduled(school["id"])
        agr = validate_success(api.create_agreement(
            create_agreement_payload(
                fair_id=fair["id"], publisher_party_id=pub["id"], discount_pct=0.45
            ), ORG,
        ), expected_status=201)
        validate_success(api.accept_agreement(agr["id"], make_publisher_rep_headers(pub["id"])))
        validate_success(api.open_stocking(fair["id"], ORG))
        line_a = make_delivered_stock_line(fair["id"], agr["id"],
                                           isbn="9780000000001", title="Alpha",
                                           list_price_cents=999, qty_committed=5, qty_delivered=5)
        line_b = make_delivered_stock_line(fair["id"], agr["id"],
                                           isbn="9780000000002", title="Beta",
                                           list_price_cents=999, qty_committed=5, qty_delivered=5)
        line_c = make_delivered_stock_line(fair["id"], agr["id"],
                                           isbn="9780000000003", title="Gamma",
                                           list_price_cents=999, qty_committed=5, qty_delivered=5)
        validate_success(api.open_fair(fair["id"], ORG))
        sale = validate_success(api.create_sale(
            create_sale_payload(
                fair_id=fair["id"],
                lines=[
                    {"stock_line_id": line_a["id"], "qty": 1},
                    {"stock_line_id": line_b["id"], "qty": 1},
                    {"stock_line_id": line_c["id"], "qty": 1},
                ],
            ), CASHIER,
        ), expected_status=201)
        validate_success(api.tender_sale(sale["id"], {"tendered_amount_cents": 2997}, CASHIER))
        validate_success(api.close_sales(fair["id"], make_organizer_headers("org_lead_1")))
        recon = validate_success(api.list_reconciliations(ORG, params={"fair_id": fair["id"]}))[0]
        recon_id = recon["id"]
        validate_success(api.post_counts(
            recon_id,
            {"lines": [
                {"stock_line_id": line_a["id"], "qty_on_hand": 4},
                {"stock_line_id": line_b["id"], "qty_on_hand": 4},
                {"stock_line_id": line_c["id"], "qty_on_hand": 4},
            ], "expected_reconciliation_version": recon["version"]},
            ORG,
        ))
        validate_success(api.submit_review(recon_id, ORG))
        approved = validate_success(api.approve_reconciliation(
            recon_id, make_organizer_headers("org_lead_2")
        ))
        # Per-line: round_half_up(1 * 999 * 0.55) = round_half_up(549.45) = 549; 3 * 549 = 1647.
        assert approved["remittance_cents"] == 1647
        assert approved["remittance_cents"] != 1648
        after_fair = validate_success(api.get_fair(fair["id"], ORG))
        assert after_fair["publisher_remittance_cents"] == 1647

    def test_remittance_locks_and_freezes_lines_at_approve(self, api):
        """PRD §3.7: "Approval moves the reconciliation to `APPROVED` and locks
        the publisher remittance ... all of which simultaneously transition to
        `RECONCILED`, freezing their counters ... The locked amount lands on the
        fair as `publisher_remittance_cents`."

        Design: Difficulty/combinatorial_formula/remittance_per_line_rounding_beats_sum_then_round
        """
        school = make_school()
        pub = make_publisher()
        ctx = make_reconciling_fair(school["id"], pub["id"])
        recon_id = ctx["reconciliation"]["id"]
        line = ctx["lines"][0]
        enter_counts_and_submit(recon_id, {line["id"]: 10})
        approved = approve_reconciliation_as_other(recon_id)
        # Nothing sold: remittance 0
        assert approved["remittance_cents"] == 0
        line_after = validate_success(api.get_stock_line(line["id"], ORG))
        assert line_after["status"] == "RECONCILED"
        fair_after = validate_success(api.get_fair(ctx["fair"]["id"], ORG))
        assert fair_after["publisher_remittance_cents"] == 0
