"""Floor-plan advances: credit limits, curtailments, interest, aging."""
from test_helpers import (
    ApiErrorId,
    assert_advance,
    assert_dealer_floorplan_invariants,
    create_advance,
    get_advance,
    get_dealer,
    record_payment,
    set_clock,
    setup_active_dealer,
    validate_error,
    validate_success,
)


class TestInterestAccrualAcrossBrackets:
    """An advance aged 200 days accrues across two daily-rate brackets after
    the 90-day free window."""

    def _setup_aged_advance(self, api):
        ctx = setup_active_dealer("DL-C1", name="Dealer C1",
                                  credit_limit_cents=2000000)
        # Created against the startup clock of 2026-08-01 (day 0).
        advance = create_advance(ctx["dealer"]["id"], "F-300", 1000000)
        # 2027-02-17 is 200 whole days after 2026-08-01.
        set_clock("2027-02-17T00:00:00Z")
        return ctx, advance

    def test_aging_audit_accrues_across_rate_brackets(self, api,
                                                      auditor_headers):
        """PRD section 3.4: "Beyond that, each billable day accrues at a daily rate applied to the **current** remaining principal — the `advance_cents` minus the `paid_curtailments_cents` as they stand at audit time, not any historical value. Days 91 through 180 accrue at a daily rate of 0.0002, days 181 through 270 at 0.0004, and day 271 onward at 0.0006. The accrued interest is the remaining principal multiplied by the sum across the three brackets of each bracket's rate times the number of days the advance has spent in that bracket, rounded half-up to a whole cent, and stored in `accrued_interest_cents`."

        Design: Difficulty/combinatorial_formula/floorplan_interest_age_bracket_accrual
        """
        ctx, advance = self._setup_aged_advance(api)

        audited = validate_success(
            api.audit_advance_aging(advance["id"], auditor_headers), 200)
        # 200 days of age: days 91..180 (90 days) at 0.0002 plus days
        # 181..200 (20 days) at 0.0004 -> 1000000 * (0.018 + 0.008).
        assert audited["accrued_interest_cents"] == 26000, (
            "expected 1000000 * (0.0002*90 + 0.0004*20) = 26000, got "
            f"{audited['accrued_interest_cents']}"
        )

    def test_aging_audit_marks_past_due_and_retains_utilization(
            self, api, auditor_headers, oem_admin_headers):
        """PRD section 3.4: "An advance in `OPEN` or `CURTAILED` whose age has passed 90 days moves to `PAST_DUE`. An advance in `OPEN`, `CURTAILED`, or `PAST_DUE` whose age has passed 270 days moves to `DEFAULTED` — a terminal state in which the remaining principal is written off: the dealer's `floorplan_utilization_cents` is reduced by that remaining principal and the same amount is added to the dealer's `default_loss_cents`."
        PRD section 3.4: "At any moment the utilization equals the sum, over all of the dealer's advances in `OPEN`, `CURTAILED`, or `PAST_DUE`, of each advance's principal minus its paid curtailments."

        Design: Difficulty/combinatorial_formula/floorplan_interest_age_bracket_accrual
        """
        ctx, advance = self._setup_aged_advance(api)

        audited = validate_success(
            api.audit_advance_aging(advance["id"], auditor_headers), 200)
        assert audited["status"] == "PAST_DUE", (
            "age 200 days is past 90 but not past 270, got "
            f"{audited['status']}"
        )

        dealer = validate_success(api.get_dealer(ctx["dealer"]["id"],
                                                 oem_admin_headers), 200)
        assert dealer["floorplan_utilization_cents"] == 1000000, (
            "a PAST_DUE advance still counts toward utilization"
        )
        assert dealer["default_loss_cents"] == 0
        assert_dealer_floorplan_invariants(dealer)


class TestUtilizationInvariant:
    """Utilization is conserved: it always equals the summed remaining
    principal of non-terminal advances."""

    def test_full_payoff_restores_utilization_to_pre_advance_value(
            self, api, oem_admin_headers):
        """PRD section 3.4: "A payment exactly equal to the remaining principal pays the advance off: it moves to `PAID_OFF` from any of those three states, `paid_curtailments_cents` is set equal to the full `advance_cents`, and the dealer's utilization is reduced by the remaining principal — the same end state the retail-sale payoff cascade of §3.3 produces."
        PRD section 3.1: "The dealer's available floor-plan credit is always derivable: `floorplan_available_cents` is the `credit_limit_cents` minus the current `floorplan_utilization_cents`."

        Design: Difficulty/compensating_invariant/floorplan_utilization_advance_payoff_invariant
        """
        ctx = setup_active_dealer("DL-R1", name="Dealer R1",
                                  credit_limit_cents=300000)
        dealer = ctx["dealer"]
        assert dealer["floorplan_utilization_cents"] == 0

        advance = create_advance(dealer["id"], "R-1", 120000)
        after_advance = get_dealer(dealer["id"])
        assert after_advance["floorplan_utilization_cents"] == 120000
        assert_dealer_floorplan_invariants(after_advance)

        paid = record_payment(advance["id"], 120000)
        assert paid["status"] == "PAID_OFF"
        assert paid["paid_curtailments_cents"] == 120000

        after_payoff = validate_success(api.get_dealer(dealer["id"],
                                                       oem_admin_headers),
                                        200)
        assert after_payoff["floorplan_utilization_cents"] == 0, (
            "the create + full-payoff pair must return utilization to its "
            "pre-action value"
        )
        assert after_payoff["floorplan_available_cents"] == 300000
        assert_dealer_floorplan_invariants(after_payoff)

    def test_partial_curtailment_leaves_remaining_principal_utilized(
            self, api, oem_admin_headers):
        """PRD section 3.4: "A partial payment adds the amount to `paid_curtailments_cents`, subtracts it from the dealer's `floorplan_utilization_cents`, and leaves the advance in (or moves it to) `CURTAILED`; this is true whether the advance was `OPEN`, already `CURTAILED`, or `PAST_DUE`."
        PRD section 3.4: "At any moment the utilization equals the sum, over all of the dealer's advances in `OPEN`, `CURTAILED`, or `PAST_DUE`, of each advance's principal minus its paid curtailments."

        Design: Difficulty/compensating_invariant/floorplan_utilization_advance_payoff_invariant
        """
        ctx = setup_active_dealer("DL-R2", name="Dealer R2",
                                  credit_limit_cents=300000)
        dealer = ctx["dealer"]

        advance = create_advance(dealer["id"], "R-2", 50000)
        curtailed = record_payment(advance["id"], 20000)
        assert curtailed["status"] == "CURTAILED"
        assert curtailed["paid_curtailments_cents"] == 20000

        dealer_after = validate_success(api.get_dealer(dealer["id"],
                                                       oem_admin_headers),
                                        200)
        assert dealer_after["floorplan_utilization_cents"] == 30000, (
            "50000 principal minus 20000 curtailment must remain utilized, "
            f"got {dealer_after['floorplan_utilization_cents']}"
        )
        assert dealer_after["floorplan_available_cents"] == 270000
        assert_dealer_floorplan_invariants(dealer_after)


class TestAdvanceCreationLimits:

    def test_duplicate_advance_serial_rejected(self, api, oem_admin_headers):
        """PRD section 3.4: "A serial may have only one live advance per dealer: a duplicate among non-terminal advances — those not yet `PAID_OFF` or `DEFAULTED` — is rejected with `ERR_DUPLICATE_ADVANCE_SERIAL`."

        Design: Corner/validations/duplicate_advance_serial_rejected
        """
        ctx = setup_active_dealer("DL-DA1", name="Dealer DA1")
        dealer = ctx["dealer"]
        create_advance(dealer["id"], "DA-1", 10000)

        resp = api.create_advance(
            {"dealer_id": dealer["id"], "unit_serial": "DA-1",
             "advance_cents": 5000},
            oem_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ADVANCE_SERIAL)

    def test_advance_over_available_credit_rejected(self, api,
                                                    oem_admin_headers):
        """PRD section 3.4: "The advance must also fit within the dealer's remaining credit: an `advance_cents` exceeding the dealer's current `floorplan_available_cents` is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`."

        Design: Corner/validations/advance_over_available_credit_rejected
        """
        ctx = setup_active_dealer("DL-FI1", name="Dealer FI1",
                                  credit_limit_cents=100000)
        dealer = ctx["dealer"]

        resp = api.create_advance(
            {"dealer_id": dealer["id"], "unit_serial": "FI-1",
             "advance_cents": 150000},
            oem_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
        assert resp.status_code == 402

        assert get_dealer(dealer["id"])["floorplan_utilization_cents"] == 0


class TestPaymentRules:

    def test_payment_exceeds_remaining_principal_rejected(
            self, api, oem_admin_headers):
        """PRD section 3.4: "The advance must be in `OPEN`, `CURTAILED`, or `PAST_DUE` (`ERR_ADVANCE_NOT_OPEN`), and the amount must not exceed the remaining principal — the `advance_cents` minus the `paid_curtailments_cents` — else `ERR_PAYMENT_EXCEEDS_BALANCE`."
        PRD section 3.4: "A payment exactly equal to the remaining principal pays the advance off: it moves to `PAID_OFF` from any of those three states, `paid_curtailments_cents` is set equal to the full `advance_cents`, and the dealer's utilization is reduced by the remaining principal — the same end state the retail-sale payoff cascade of §3.3 produces."

        Design: Corner/validations/payment_exceeds_remaining_principal_rejected
        """
        ctx = setup_active_dealer("DL-PM1", name="Dealer PM1",
                                  credit_limit_cents=100000)
        dealer = ctx["dealer"]
        advance = create_advance(dealer["id"], "PM-1", 50000)

        resp = api.record_advance_payment(advance["id"],
                                          {"amount_cents": 60000},
                                          oem_admin_headers)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE)

        paid = validate_success(
            api.record_advance_payment(advance["id"], {"amount_cents": 50000},
                                       oem_admin_headers), 200)
        assert_advance(paid)
        assert paid["status"] == "PAID_OFF"
        assert paid["paid_curtailments_cents"] == 50000
        assert get_dealer(dealer["id"])["floorplan_utilization_cents"] == 0

    def test_payment_on_paid_off_advance_rejected(self, api,
                                                  oem_admin_headers):
        """PRD section 3.4: "The advance must be in `OPEN`, `CURTAILED`, or `PAST_DUE` (`ERR_ADVANCE_NOT_OPEN`), and the amount must not exceed the remaining principal — the `advance_cents` minus the `paid_curtailments_cents` — else `ERR_PAYMENT_EXCEEDS_BALANCE`."

        Design: Corner/validations/payment_on_paid_off_advance_rejected
        """
        ctx = setup_active_dealer("DL-PO1", name="Dealer PO1",
                                  credit_limit_cents=100000)
        dealer = ctx["dealer"]
        advance = create_advance(dealer["id"], "PO-1", 40000)
        record_payment(advance["id"], 40000)
        assert get_advance(advance["id"])["status"] == "PAID_OFF"

        resp = api.record_advance_payment(advance["id"], {"amount_cents": 1},
                                          oem_admin_headers)
        validate_error(resp, ApiErrorId.ERR_ADVANCE_NOT_OPEN)

        assert get_advance(advance["id"])["status"] == "PAID_OFF"
