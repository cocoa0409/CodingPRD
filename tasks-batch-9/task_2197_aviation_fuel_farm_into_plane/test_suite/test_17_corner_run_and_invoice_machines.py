"""Corner behaviour of the two closing machines: the reconciliation run's in-request variance hold,
its override gate and its immutable terminal state, and the invoice's bounded dispute loop."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    fixtures as fx, make_airline_rep_headers, make_billing_headers,
)

ACCOUNT = {"base_price_cents_per_liter": 62.00, "credit_limit_cents": 100_000_000,
           "tax_exempt": False}
PERMIT = {"max_daily_throughput_liters": 400000.0}


def _farm_with_one_ticket():
    """A farm whose ledger stands at 980,000.00 liters after a single 20,000 liter uplift."""
    env = fx.setup_fueling_order_with_uplift(
        meter_end_liters=20_000.0, temperature_c=15.0, requested_uplift_liters=20_000.0,
        max_authorized_liters=20_000.0, account_overrides=dict(ACCOUNT),
        permit_overrides=dict(PERMIT))
    assert fx.read_tank(env["tank"]["id"])["book_volume_liters"] == \
        pytest.approx(980000.00, abs=0.005)
    env["run"] = fx.open_reconciliation_run(env["farm"]["id"],
                                            period_start_utc="2026-08-10T00:00:00Z",
                                            period_end_utc="2026-08-10T07:00:00Z")
    fx.set_clock("2026-08-10T07:00:00Z")
    return env


def _measurement(tank_id, measured_volume_liters):
    return [{"storage_tank_id": tank_id, "measured_volume_liters": measured_volume_liters,
             "temperature_c": 15.0}]


def _run_status(api, farm_id):
    runs, _meta = validate_paginated(api.list_reconciliation_runs(farm_id, fx.OPERATOR))
    return [r["status"] for r in runs]


class TestReconciliationRunMachineCorners:
    def test_the_hold_is_visible_in_the_body_of_the_measuring_request(self, api):
        """PRD §3.9: "The run auto-transitions `MEASURED → VARIANCE_HOLD` on the same request that
        computed the variance when the governing percentage is **strictly greater than** 0.50 percent; a
        run sitting at exactly 0.5000 percent does not hold and posts clean."
        PRD §3.9: "`variance_pct_throughput_basis` uses the throughput denominator and is the
        **governing** figure; `variance_pct_opening_stock_basis` uses the derived opening stock and is
        advisory, reported for the auditor."
        PRD §3.9: "The per-tank variance is the corrected measured volume less the book volume, rounded
        half up to two decimals — a positive number is a gain, a negative number a loss — and the run's
        `variance_liters` is the sum of those per-tank variances, rounded half up to two decimals."

        Design: Corner/state_machines/variance_hold_is_entered_by_the_same_request_that_measured
        """
        env = _farm_with_one_ticket()

        measured = fx.measure_reconciliation_run(
            env["run"]["id"], _measurement(env["tank"]["id"], 979_000.0))

        assert measured["status"] == "VARIANCE_HOLD", \
            "the system hop lands inside the very request that measured"
        assert measured["variance_liters"] == pytest.approx(-1000.00, abs=0.005)
        assert measured["throughput_liters"] == pytest.approx(20000.00, abs=0.005)
        assert measured["variance_pct_throughput_basis"] == pytest.approx(5.0000, abs=0.00005)
        assert measured["variance_pct_opening_stock_basis"] == \
            pytest.approx(0.1000, abs=0.00005), \
            "the advisory basis sits far under tolerance while the governing basis breaches it"

    def test_a_held_run_posts_only_once_a_reason_is_given(self, api):
        """PRD §3.9: "From `MEASURED` it needs nothing further; from `VARIANCE_HOLD` it needs a non-empty
        `variance_override_reason` in the payload, and posting a held run without one is rejected with
        `ERR_VARIANCE_OVERRIDE_REQUIRED`."
        PRD §3.9: "Posting writes the signed per-tank variance into the ledger as that tank's
        `adjustment_liters`, with the effect that each measured tank's `book_volume_liters` afterwards
        equals its corrected measured volume exactly."
        PRD §3.9: "It stamps `posted_by_user_id` from the acting identifier, recomputes each tank's
        `available_volume_liters` and the farm's posture, and raises the run's `version`, each tank's
        `version` and the farm's `version` by one."

        Design: Corner/state_machines/post_from_variance_hold_without_an_override_reason
        """
        env = _farm_with_one_ticket()
        run_id, tank_id = env["run"]["id"], env["tank"]["id"]
        held = fx.measure_reconciliation_run(run_id, _measurement(tank_id, 979_000.0))
        assert held["status"] == "VARIANCE_HOLD"

        validate_error(api.post_reconciliation_run(run_id, fx.ADMIN),
                       ApiErrorId.ERR_VARIANCE_OVERRIDE_REQUIRED, 409)
        assert _run_status(api, env["farm"]["id"]) == ["VARIANCE_HOLD"]
        assert fx.read_tank(tank_id)["book_volume_liters"] == pytest.approx(980000.00,
                                                                           abs=0.005)

        posted = validate_success(api.post_reconciliation_run(
            run_id, fx.ADMIN, {"variance_override_reason": "gauge hatch reads low, retested"}))

        assert posted["status"] == "POSTED"
        assert posted["posted_by_user_id"] is not None
        assert fx.read_tank(tank_id)["book_volume_liters"] == pytest.approx(979000.00,
                                                                           abs=0.005), \
            "the ledger is dragged onto the corrected measured volume exactly"

    def test_a_posted_run_refuses_to_be_measured_or_posted_again(self, api):
        """PRD §3.9: "`POSTED` is terminal for a run."
        PRD §2.10: "the terminal-state guard (`ERR_ALREADY_TERMINAL`), which applies to every
        state-transition endpoint and fires when the target row already sits in a terminal state for its
        machine: a fuel receipt in `RELEASED` or `REJECTED`, a fuelling order in `COMPLETED`,
        `CANCELLED` or `ABORTED`, a fuel authorization in `REDEEMED`, `VOIDED` or `EXPIRED`, a spill
        incident in `CLOSED`, an invoice in `PAID` or `VOIDED`, or a reconciliation run in `POSTED`."
        PRD §3.9: "From `MEASURED` it needs nothing further; from `VARIANCE_HOLD` it needs a non-empty
        `variance_override_reason` in the payload, and posting a held run without one is rejected with
        `ERR_VARIANCE_OVERRIDE_REQUIRED`."

        Design: Corner/state_machines/posted_run_is_immutable
        """
        env = _farm_with_one_ticket()
        run_id, tank_id = env["run"]["id"], env["tank"]["id"]
        measurements = _measurement(tank_id, 979_950.0)
        measured = fx.measure_reconciliation_run(run_id, measurements)
        assert measured["status"] == "MEASURED", "a 50 litre loss on 20,000 is 0.2500 percent"
        assert measured["variance_pct_throughput_basis"] == pytest.approx(0.2500, abs=0.00005)

        posted = validate_success(api.post_reconciliation_run(run_id, fx.ADMIN))
        assert posted["status"] == "POSTED"
        assert fx.read_tank(tank_id)["book_volume_liters"] == pytest.approx(979950.00,
                                                                           abs=0.005)

        validate_error(api.measure_reconciliation_run(
            run_id, {"tank_measurements": measurements}, fx.OPERATOR),
            ApiErrorId.ERR_ALREADY_TERMINAL, 409)
        validate_error(api.post_reconciliation_run(
            run_id, fx.ADMIN, {"variance_override_reason": "one more time"}),
            ApiErrorId.ERR_ALREADY_TERMINAL, 409)

        assert _run_status(api, env["farm"]["id"]) == ["POSTED"]
        assert fx.read_tank(tank_id)["book_volume_liters"] == pytest.approx(979950.00,
                                                                           abs=0.005), \
            "the gain-loss adjustment lands on the ledger exactly once"


class TestInvoiceMachineCorners:
    @staticmethod
    def _issued():
        return fx.setup_issued_invoice(meter_end_liters=20_000.0,
                                       account_overrides=dict(ACCOUNT),
                                       permit_overrides=dict(PERMIT))

    def test_a_round_trip_through_dispute_reprices_nothing(self, api):
        """PRD §3.9: "The dispute raises only the invoice's `version`."
        PRD §3.9: "Resolution, `DISPUTED → ISSUED`, is a `BillingClerk` action refused when the acting
        identifier equals the invoice's `issued_by_user_id`; it raises `dispute_round` by one, stamps
        `dispute_resolved_by_user_id`, and raises the invoice's `version` by one, so the cycle
        `ISSUED → DISPUTED → ISSUED` is bounded at two rounds."
        PRD §3.9: "Issuance flips every swept ticket from `POSTED` to `BILLED` and freezes its
        `billed_line_cents`, recomputing the invoice totals one final time in the same four steps;
        stamps `issued_by_user_id` from the acting identifier; and recomputes both of the account's
        exposure figures, where the uncollected-ticket term is replaced by the invoiced-invoice term,
        which additionally carries the admin fee and the rebate."

        Design: Corner/state_machines/dispute_resolve_loop_returns_to_the_same_state
        """
        env = self._issued()
        invoice_id, ticket_id = env["invoice"]["id"], env["uplift"]["id"]
        before = fx.read_invoice(invoice_id)
        assert before["status"] == "ISSUED"
        assert before["dispute_round"] == 0
        assert fx.read_uplift(ticket_id)["status"] == "BILLED"

        disputed = validate_success(api.dispute_invoice(
            invoice_id, make_airline_rep_headers(env["account"]["id"])))
        assert disputed["status"] == "DISPUTED"
        assert disputed["dispute_round"] == 0, "the round only closes on resolution"

        resolved = validate_success(api.resolve_invoice_dispute(
            invoice_id, make_billing_headers("clerk-two")))

        assert resolved["status"] == "ISSUED"
        assert resolved["dispute_round"] == 1
        assert resolved["dispute_resolved_by_user_id"] == "clerk-two"
        assert resolved["subtotal_cents"] == before["subtotal_cents"]
        assert resolved["total_cents"] == before["total_cents"]
        ticket = fx.read_uplift(ticket_id)
        assert ticket["status"] == "BILLED"
        assert ticket["invoice_id"] == invoice_id, "the swept set survives the round trip intact"

    def test_a_disputed_invoice_takes_no_money_until_the_dispute_closes(self, api):
        """PRD §2.10: "`ERR_INVALID_INVOICE_STATE` on invoice issue, dispute, dispute resolution, void
        and payment"
        PRD §3.9: "Payments are recorded against an issued invoice with an `amount_cents` that must be
        strictly positive and must not push the cumulative `amount_paid_cents` above the invoice's
        `total_cents`; a violation of either bound is `ERR_PAYMENT_EXCEEDS_BALANCE`."
        PRD §3.9: "Once the cumulative paid amount reaches the total the invoice moves
        `ISSUED → PAID`, both exposure figures fall by the invoice total, and the invoice's and
        account's `version` each rise by one."

        Design: Corner/state_machines/payment_on_a_disputed_invoice
        """
        env = self._issued()
        invoice_id = env["invoice"]["id"]
        total = fx.read_invoice(invoice_id)["total_cents"]
        validate_success(api.dispute_invoice(
            invoice_id, make_airline_rep_headers(env["account"]["id"])))

        validate_error(api.create_payment(invoice_id, {"amount_cents": total}, fx.BILLING),
                       ApiErrorId.ERR_INVALID_INVOICE_STATE, 409)
        held = fx.read_invoice(invoice_id)
        assert held["status"] == "DISPUTED"
        assert held["amount_paid_cents"] == 0

        validate_success(api.resolve_invoice_dispute(invoice_id,
                                                    make_billing_headers("clerk-two")))
        validate_success(api.create_payment(invoice_id, {"amount_cents": total}, fx.BILLING),
                         201)

        settled = fx.read_invoice(invoice_id)
        assert settled["status"] == "PAID", "the money is only accepted once the dispute is closed"
        assert settled["amount_paid_cents"] == total

    def test_a_draft_has_nothing_to_dispute_yet(self, api):
        """PRD §3.9: "A draft opens with `status` `DRAFT`, `amount_paid_cents` zero, `dispute_round`
        zero, and `issued_by_user_id` and `dispute_resolved_by_user_id` null."
        PRD §3.9: "An `AirlineRep` owning the account may dispute an issued invoice,
        `ISSUED → DISPUTED`, provided the acting identifier is the invoice's `airline_account_id`, the
        invoice's `amount_paid_cents` is zero, and its `dispute_round` is at most 1 — so an invoice may
        be disputed at most twice, and a third attempt on an invoice already at a `dispute_round` of 2
        is rejected with `ERR_DISPUTE_LIMIT_REACHED`."
        PRD §2.10: "`ERR_INVALID_INVOICE_STATE` on invoice issue, dispute, dispute resolution, void and
        payment"

        Design: Corner/state_machines/draft_invoice_cannot_be_disputed_or_voided_into_paid
        """
        env = fx.setup_completed_order(meter_end_liters=20_000.0,
                                       account_overrides=dict(ACCOUNT),
                                       permit_overrides=dict(PERMIT))
        draft = fx.create_draft_invoice(env["account"]["id"])
        assert draft["status"] == "DRAFT"
        assert draft["issued_by_user_id"] is None

        validate_error(api.dispute_invoice(draft["id"],
                                          make_airline_rep_headers(env["account"]["id"])),
                       ApiErrorId.ERR_INVALID_INVOICE_STATE, 409)

        still_draft = fx.read_invoice(draft["id"])
        assert still_draft["status"] == "DRAFT"
        assert still_draft["dispute_round"] == 0
        assert fx.read_uplift(env["uplift"]["id"])["status"] == "POSTED", \
            "only issuance moves a draft forward"
