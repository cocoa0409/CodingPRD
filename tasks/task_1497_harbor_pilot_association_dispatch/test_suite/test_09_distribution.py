"""Revenue distribution: pool arithmetic, share rounding, void compensation
(PRD §2.6, §3.8)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    assert_distribution_run,
    create_main_tariff, place_order, dispatch, register_boat,
    register_endorsed_pilot, launch, board, complete, set_clock,
    get_assignment_fresh, invoice_of_assignment,
    make_distribution_run_payload, setup_completed_scenario,
    setup_two_pilots,
)

FINANCE = TEST_USERS["finance_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def _finalize(api, invoice_id):
    return validate_success(api.finalize_invoice(invoice_id, FINANCE), 200)


def _completed_job(vessel_name, gt, draft_dm, order_type, eta,
                   win_start, win_end, share_units=1):
    """One full job through completion at the current clock. Returns (order, asg)."""
    order = place_order(vessel_name=vessel_name, gt=gt, draft_dm=draft_dm,
                        order_type=order_type, eta=eta)
    asg = dispatch(order["id"], win_start, win_end)
    asg = complete(board(launch(asg)), 0, 0)
    return order, asg


class TestShareRounding:
    def _two_pilot_pool(self, api):
        """PA (3 units) completes a 950000-cent job (gt 82500, draft 90);
        PB (1 unit) completes a 488750-cent job (gt 30000, draft 120 with
        surcharge). Both invoices finalized in the 2026-08-20 window."""
        create_main_tariff()
        pa = register_endorsed_pilot("Pilot A", "LIC-A", share_units=3)
        pb = register_endorsed_pilot("Pilot B", "LIC-B", share_units=1)
        register_boat("Boat A")
        register_boat("Boat B")
        _oa, aa = _completed_job("MV Alpha", 82500, 90, "ARRIVAL",
                                 "2026-08-10T00:00:00Z",
                                 "2026-08-11T10:00:00Z", "2026-08-11T12:00:00Z")
        assert aa["pilot_id"] == pa["id"]
        _ob, ab = _completed_job("MV Beta", 30000, 120, "DEPARTURE",
                                 "2026-08-10T00:00:00Z",
                                 "2026-08-12T10:00:00Z", "2026-08-12T12:00:00Z")
        assert ab["pilot_id"] == pb["id"]
        ia = invoice_of_assignment(aa["id"])
        ib = invoice_of_assignment(ab["id"])
        assert ia["total_cents"] == 950000
        assert ib["total_cents"] == 488750
        set_clock("2026-08-20T10:00:00Z")
        _finalize(api, ia["id"])
        _finalize(api, ib["id"])
        return pa, pb, ia, ib

    def test_distribution_pool_gross_levy_net(self, api):
        """PRD §3.8: "The run's `gross_pool_cents` is the sum of the pool's
        `total_cents`. The association levy is then computed with a pinned
        anti-circular order: the levy percentage is keyed on the gross pool
        before any deduction — 0.10 when the gross reaches 10000000 cents,
        otherwise 0.08 — and `levy_cents` is the gross multiplied by that
        percentage, rounded half-up. The `net_pool_cents` is the gross minus
        the levy."

        gross 1438750 < 10000000 -> levy 8% = 115100; net 1323650.

        Design: Difficulty/combinatorial_formula/revenue_share_per_share_rounding_then_remainder
        """
        self._two_pilot_pool(api)
        run = validate_success(api.create_distribution_run(
            make_distribution_run_payload("2026-08-20T00:00:00Z",
                                          "2026-08-21T00:00:00Z"), FINANCE), 201)
        assert_distribution_run(run)
        assert run["gross_pool_cents"] == 1438750
        assert run["levy_cents"] == 115100
        assert run["net_pool_cents"] == 1323650

    def test_per_share_rounding_then_remainder_reconciliation(self, api):
        """PRD §3.8: "Each pilot's raw share is the net pool multiplied by
        their `share_units` and divided by the total units across eligible
        pilots; per §2.6 each share is rounded half-up to integer cents first".
        "a negative remainder removes one cent per pass walking pilots by
        `created_at` descending."

        Net 1323650 over units 3:1 -> raw 992737.5 / 330912.5; both round up
        (sum 1323651, remainder -1) and the cent is removed from the
        latest-created pilot: PA 992738, PB 330912.

        Design: Difficulty/combinatorial_formula/revenue_share_per_share_rounding_then_remainder
        """
        pa, pb, _ia, _ib = self._two_pilot_pool(api)
        run = validate_success(api.create_distribution_run(
            make_distribution_run_payload("2026-08-20T00:00:00Z",
                                          "2026-08-21T00:00:00Z"), FINANCE), 201)
        shares = {s["pilot_id"]: s["share_cents"] for s in run["shares"]}
        assert shares[pa["id"]] == 992738
        assert shares[pb["id"]] == 330912
        assert sum(shares.values()) + run["levy_cents"] == run["gross_pool_cents"], \
            "exact cent conservation"


class TestVoidCompensation:
    def test_distribution_run_computes_conserved_pool_arithmetic(self, api):
        """PRD §3.8: "the levy percentage is keyed on the gross pool before any
        deduction — 0.10 when the gross reaches 10000000 cents, otherwise 0.08
        — and `levy_cents` is the gross multiplied by that percentage, rounded
        half-up. The `net_pool_cents` is the gross minus the levy."
        PRD §3.8: "The invariant after reconciliation is exact: the gross pool
        equals the levy plus the sum of all shares."

        Single-pilot pool of 950000: levy 76000, net 874000, sole share 874000.

        Design: Difficulty/compensating_invariant/distribution_create_then_void_conserves_invoice_fiscal_state
        """
        ctx = setup_completed_scenario(gt=82500, draft_dm=90)
        _finalize(api, ctx["invoice"]["id"])
        run = validate_success(api.create_distribution_run(
            make_distribution_run_payload("2026-08-01T00:00:00Z",
                                          "2026-08-02T00:00:00Z"), FINANCE), 201)
        assert run["status"] == "COMPUTED"
        assert run["gross_pool_cents"] == 950000
        assert run["levy_cents"] == 76000
        assert run["net_pool_cents"] == 874000
        assert len(run["shares"]) == 1
        assert run["shares"][0]["share_cents"] == 874000
        assert run["levy_cents"] + run["shares"][0]["share_cents"] == 950000
        assert ctx["invoice"]["id"] in run["invoice_ids"]

    def test_void_run_leaves_invoice_and_billing_untouched(self, api):
        """PRD §3.8: "Voiding a `COMPUTED` run instead moves the run to `VOID`
        with no invoice or assignment mutation — the swept invoices remain
        `FINALIZED`, releasing the run's reservation so a later window can pick
        them up."

        Design: Difficulty/compensating_invariant/distribution_create_then_void_conserves_invoice_fiscal_state
        """
        ctx = setup_completed_scenario(gt=82500, draft_dm=90)
        _finalize(api, ctx["invoice"]["id"])
        run = validate_success(api.create_distribution_run(
            make_distribution_run_payload("2026-08-01T00:00:00Z",
                                          "2026-08-02T00:00:00Z"), FINANCE), 201)
        voided = validate_success(api.void_distribution_run(run["id"], FINANCE), 200)
        assert voided["status"] == "VOID"

        invoice = validate_success(api.get_invoice(ctx["invoice"]["id"], FINANCE), 200)
        assert invoice["status"] == "FINALIZED", "not DISTRIBUTED after the void"
        assignment = get_assignment_fresh(ctx["assignment"]["id"])
        assert assignment["billing_status"] == "INVOICED", "not SETTLED after the void"


class TestPoolAndWindowRules:
    def test_error_empty_distribution_pool(self, api, finance_headers):
        """PRD §3.8: "The pool is every `FINALIZED` invoice whose
        `finalized_at` falls in the window; an empty pool rejects the run with
        `ERR_EMPTY_DISTRIBUTION_POOL`."

        No invoices exist at all.

        Design: Corner/errors/error_empty_distribution_pool
        """
        res = api.create_distribution_run(
            make_distribution_run_payload("2026-08-01T00:00:00Z",
                                          "2026-08-02T00:00:00Z"), finance_headers)
        validate_error(res, ApiErrorId.ERR_EMPTY_DISTRIBUTION_POOL)

    def test_error_period_overlap_and_adjacency_allowed(self, api, finance_headers):
        """PRD §3.8: "The window must not overlap any existing run in
        `COMPUTED` or `SETTLED` status — adjacency is allowed, so a new
        `period_start` equal to an existing run's `period_end` passes —
        otherwise `ERR_PERIOD_OVERLAP` (HTTP 409)."

        [08-01T12:00, 08-03) overlaps the existing [08-01, 08-02) run; the
        adjacent [08-02, 08-03) passes the overlap check and fails only on the
        empty pool.

        Design: Corner/errors/error_period_overlap_and_adjacency_allowed
        """
        ctx = setup_completed_scenario()
        _finalize(api, ctx["invoice"]["id"])  # finalized_at = default clock, in [08-01, 08-02)
        validate_success(api.create_distribution_run(
            make_distribution_run_payload("2026-08-01T00:00:00Z",
                                          "2026-08-02T00:00:00Z"), finance_headers), 201)

        res_overlap = api.create_distribution_run(
            make_distribution_run_payload("2026-08-01T12:00:00Z",
                                          "2026-08-03T00:00:00Z"), finance_headers)
        validate_error(res_overlap, ApiErrorId.ERR_PERIOD_OVERLAP)

        res_adjacent = api.create_distribution_run(
            make_distribution_run_payload("2026-08-02T00:00:00Z",
                                          "2026-08-03T00:00:00Z"), finance_headers)
        validate_error(res_adjacent, ApiErrorId.ERR_EMPTY_DISTRIBUTION_POOL)
