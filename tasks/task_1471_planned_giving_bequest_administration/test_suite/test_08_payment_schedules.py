"""Annuity payment schedules: generation shape, clock sweeps, servicing gates,
rounding order, and obligation-mass conservation."""
from test_helpers import (
    AGE98_BOOKED_DEDUCTION_CENTS,
    AGE98_GIFT_CENTS,
    AGE98_MONTHLY_PAYMENT_CENTS,
    AGE98_PAYMENT_COUNT,
    AGE98_TOTAL_SCHEDULED_CENTS,
    ApiErrorId,
    assert_annuity_payment,
    assert_obligation_conservation,
    list_payments,
    make_active_agreement,
    make_active_rate_table,
    make_donor,
    make_funded_agreement,
    set_clock,
    validate_error,
    validate_success,
)


def _monthly_crat_active():
    """Age-98 MONTHLY CRT_ANNUITY (gift 1665017, 600bps) walked to ACTIVE:
    24 payments of 8325 each. Returns (donor, agreement, payments)."""
    donor = make_donor(full_name="Monthly CRAT", date_of_birth="1928-01-01T00:00:00Z")
    make_active_rate_table()
    agreement, payments = make_active_agreement(
        donor["id"],
        vehicle_type="CRT_ANNUITY",
        gift_amount_cents=AGE98_GIFT_CENTS,
        payout_rate_bps=600,
        payment_frequency="MONTHLY",
        annuitant_1_age=98,
    )
    return donor, agreement, payments


def _quarterly_crat_active():
    """Age-80 QUARTERLY CRT_ANNUITY (gift 10000000, 500bps) walked to ACTIVE:
    80 payments of 125000 each. Returns (donor, agreement, payments)."""
    donor = make_donor(full_name="Quarterly CRAT", date_of_birth="1946-06-01T00:00:00Z")
    make_active_rate_table()
    agreement, payments = make_active_agreement(
        donor["id"],
        vehicle_type="CRT_ANNUITY",
        gift_amount_cents=10000000,
        payout_rate_bps=500,
        payment_frequency="QUARTERLY",
        annuitant_1_age=80,
    )
    return donor, agreement, payments


class TestScheduleGeneration:
    def test_schedule_generation_structure(self, api, gift_admin_headers):
        """PRD §3.6: "The schedule's length in payments is the frequency divisor
        multiplied by the remaining contract years, where the frequency divisor
        is 1 for `ANNUAL`, 2 for `SEMIANNUAL`, 4 for `QUARTERLY`, and 12 for
        `MONTHLY`, and the remaining years are 100 minus the oldest annuitant's
        age, floored at a minimum of 1. The first payment's `due_date` falls
        exactly one frequency period after the funding date, each subsequent
        payment advances by one period, and payments are indexed by
        `period_index` starting at 1."

        Design: Corner/endpoints/schedule_generation_structure
        """
        donor = make_donor(full_name="Schedule Shape", date_of_birth="1928-01-01T00:00:00Z")
        make_active_rate_table()
        agreement = make_funded_agreement(
            donor["id"],
            vehicle_type="CRT_ANNUITY",
            gift_amount_cents=AGE98_GIFT_CENTS,
            payout_rate_bps=600,
            payment_frequency="MONTHLY",
            annuitant_1_age=98,
        )
        resp = api.generate_payment_schedule(agreement["id"], gift_admin_headers)
        payments = validate_success(resp, 201)
        # N = 12 * max(1, 100 - 98) = 24 monthly payments.
        assert len(payments) == AGE98_PAYMENT_COUNT
        first, last = payments[0], payments[-1]
        for payment in payments:
            assert_annuity_payment(payment)
            assert payment["status"] == "SCHEDULED"
        assert first["period_index"] == 1
        assert first["due_date"].startswith("2026-09-01")
        assert last["period_index"] == AGE98_PAYMENT_COUNT
        assert last["due_date"].startswith("2028-08-01")

        after = validate_success(api.get_gift_agreement(agreement["id"], gift_admin_headers))
        assert after["status"] == "ACTIVE"


class TestPerPaymentRoundingOrder:
    def test_each_payment_independently_rounded(self, api, gift_admin_headers):
        """PRD §2.6: "In annuity payment schedules, each payment's `amount_cents`
        is independently rounded from the annual annuity, and there is **no
        cumulative true-up** on any payment — the sum of a schedule's payments
        may therefore differ from the annual annuity multiplied by the number
        of years by a few cents."
        PRD §3.6: "The agreement's `total_scheduled_cents` becomes the sum of
        all created payment amounts, and its `version` increments."

        Design: Difficulty/combinatorial_formula/payment_schedule_per_period_rounding_mode_b
        """
        _donor, agreement, payments = _monthly_crat_active()
        assert len(payments) == AGE98_PAYMENT_COUNT
        for payment in payments:
            # round_half_up(99901 / 12) = 8325 on every line.
            assert payment["amount_cents"] == AGE98_MONTHLY_PAYMENT_CENTS
        total = sum(p["amount_cents"] for p in payments)
        assert total == AGE98_TOTAL_SCHEDULED_CENTS

        after = validate_success(api.get_gift_agreement(agreement["id"], gift_admin_headers))
        # Sum of rounded lines (24 * 8325 = 199800), not round(2 * 99901) =
        # 199802 — the two rounding orders drift by 2 cents.
        assert after["total_scheduled_cents"] == AGE98_TOTAL_SCHEDULED_CENTS
        assert after["total_scheduled_cents"] != 2 * 99901

    def test_booked_deduction_at_execute_and_active_status(self, api, gift_admin_headers):
        """PRD §3.3: "The present value of the annuity obligation is the annual
        annuity multiplied by that factor, rounded half-up to whole cents. The
        charitable deduction is `gift_amount_cents` minus that present value,
        floored at zero".
        PRD §3.6: "Once an agreement is `FUNDED`, a `GiftAdministrator`
        generates its payment schedule — a transition to `ACTIVE`".

        Design: Difficulty/combinatorial_formula/payment_schedule_per_period_rounding_mode_b
        """
        _donor, agreement, _payments = _monthly_crat_active()
        after = validate_success(api.get_gift_agreement(agreement["id"], gift_admin_headers))
        # annual 99901 at age 98 (n=2, 5%): pv = 185757, deduction = 1479260.
        assert after["booked_deduction_cents"] == AGE98_BOOKED_DEDUCTION_CENTS
        assert after["status"] == "ACTIVE"
        all_payments, meta = list_payments(agreement["id"])
        assert meta["total_count"] == AGE98_PAYMENT_COUNT
        assert len(all_payments) == AGE98_PAYMENT_COUNT


class TestClockSweeps:
    def test_payment_auto_due_via_clock_sweep(self, api, gift_admin_headers):
        """PRD §2.4: "First, every annuity payment in `SCHEDULED` status whose
        `due_date` is at or before the current clock time flips to `DUE`".
        PRD §2.4: "At server startup, before any client call, the logical clock
        reads exactly `2026-08-01T00:00:00Z`."

        Design: Corner/state_machines/payment_auto_due_via_clock_sweep
        """
        _donor, agreement, _payments = _monthly_crat_active()
        # Payment 1 falls due 2026-09-01; the startup clock is 2026-08-01.
        _due, meta = list_payments(agreement["id"], status="DUE")
        assert meta["total_count"] == 0

        set_clock("2026-09-01T00:00:00Z")
        due, meta = list_payments(agreement["id"], status="DUE")
        assert meta["total_count"] == 1
        assert due[0]["status"] == "DUE"
        assert due[0]["due_date"].startswith("2026-09-01")

    def test_payment_defer_due_cycle_via_clock(self, api, gift_admin_headers):
        """PRD §3.6: "Deferral (`DEFER`) moves a `DUE` payment to `DEFERRED`
        with a `defer_until` instant that must lie strictly in the future of
        the logical clock, else `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §2.4: "every payment in `DEFERRED` status whose `defer_until` is at
        or before the current clock time flips back to `DUE`."

        Design: Corner/state_machines/payment_defer_due_cycle_via_clock
        """
        _donor, agreement, _payments = _monthly_crat_active()
        set_clock("2026-09-01T00:00:00Z")
        due, _meta = list_payments(agreement["id"], status="DUE")
        payment_id = due[0]["id"]

        deferred = validate_success(
            api.transition_annuity_payment(
                payment_id,
                {"action": "DEFER", "defer_until": "2026-12-01T00:00:00Z"},
                gift_admin_headers,
            )
        )
        assert deferred["status"] == "DEFERRED"

        # Before the deferral boundary the payment stays DEFERRED.
        set_clock("2026-11-15T00:00:00Z")
        still, meta = list_payments(agreement["id"], status="DEFERRED")
        assert meta["total_count"] == 1
        assert still[0]["id"] == payment_id

        # At the boundary (inclusive) the sweep returns it to DUE.
        set_clock("2026-12-01T00:00:00Z")
        back = validate_success(api.get_annuity_payment(payment_id, gift_admin_headers))
        assert back["status"] == "DUE"
        assert back["amount_cents"] == AGE98_MONTHLY_PAYMENT_CENTS

    def test_scheduled_defer_past_rejected(self, api, gift_admin_headers):
        """PRD §3.6: "Deferral (`DEFER`) moves a `DUE` payment to `DEFERRED`
        with a `defer_until` instant that must lie strictly in the future of
        the logical clock, else `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/cross_cutting_complexity_layers/scheduled_defer_past_rejected
        """
        _donor, agreement, _payments = _monthly_crat_active()
        set_clock("2026-09-01T00:00:00Z")
        due, _meta = list_payments(agreement["id"], status="DUE")
        payment_id = due[0]["id"]

        resp = api.transition_annuity_payment(
            payment_id,
            {"action": "DEFER", "defer_until": "2026-08-15T00:00:00Z"},
            gift_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400
        after = validate_success(api.get_annuity_payment(payment_id, gift_admin_headers))
        assert after["status"] == "DUE"

    def test_pay_non_due_payment_rejected(self, api, gift_admin_headers):
        """PRD §3.6: "Disbursing a payment (`PAY`, by a `GiftAdministrator`)
        requires the payment to be `DUE` — otherwise `ERR_PAYMENT_NOT_DUE`
        (HTTP 409)".
        PRD §2.4: "At server startup, before any client call, the logical clock
        reads exactly `2026-08-01T00:00:00Z`."

        Design: Corner/validations/pay_non_due_payment_rejected
        """
        _donor, agreement, _payments = _monthly_crat_active()
        # Startup clock 2026-08-01 < first due date 2026-09-01: still SCHEDULED.
        scheduled, _meta = list_payments(agreement["id"], status="SCHEDULED")
        payment_id = scheduled[0]["id"]
        assert scheduled[0]["status"] == "SCHEDULED"

        resp = api.transition_annuity_payment(
            payment_id, {"action": "PAY"}, gift_admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_NOT_DUE)
        assert resp.status_code == 409


class TestSuspendResumeCycle:
    def _suspended_with_due_payment(self, api, compliance_headers):
        _donor, agreement, _payments = _quarterly_crat_active()
        # First quarterly payment falls due 2026-11-01.
        set_clock("2026-11-01T00:00:00Z")
        due, _meta = list_payments(agreement["id"], status="DUE")
        payment_id = due[0]["id"]
        validate_success(
            api.transition_gift_agreement(
                agreement["id"], {"action": "SUSPEND"}, compliance_headers
            )
        )
        return agreement["id"], payment_id

    def test_pay_blocked_while_agreement_suspended(
        self, api, compliance_headers, gift_admin_headers
    ):
        """PRD §3.3: "Once `ACTIVE`, a `ComplianceOfficer` may `SUSPEND` the
        agreement — which blocks all payment disbursements on its payments with
        `ERR_AGREEMENT_SUSPENDED` (HTTP 409) for the duration — and later
        `RESUME` it back to `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/agreement_suspend_resume_cycle
        """
        agreement_id, payment_id = self._suspended_with_due_payment(
            api, compliance_headers
        )
        resp = api.transition_annuity_payment(
            payment_id, {"action": "PAY"}, gift_admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_SUSPENDED)
        assert resp.status_code == 409
        after = validate_success(api.get_annuity_payment(payment_id, gift_admin_headers))
        assert after["status"] == "DUE"

    def test_resume_restores_payment_and_completes_cycle(
        self, api, compliance_headers, gift_admin_headers
    ):
        """PRD §3.3: "Once `ACTIVE`, a `ComplianceOfficer` may `SUSPEND` the
        agreement — which blocks all payment disbursements on its payments with
        `ERR_AGREEMENT_SUSPENDED` (HTTP 409) for the duration — and later
        `RESUME` it back to `ACTIVE`."
        PRD §3.6: "Payment stamps `paid_at` from the logical clock, recomputes
        the parent agreement's `total_paid_cents` as the sum of `amount_cents`
        over its `PAID` payments, and increments both the payment's and the
        agreement's `version`."

        Design: Difficulty/non_linear_state_machine/agreement_suspend_resume_cycle
        """
        agreement_id, payment_id = self._suspended_with_due_payment(
            api, compliance_headers
        )
        validate_success(
            api.transition_gift_agreement(
                agreement_id, {"action": "RESUME"}, compliance_headers
            )
        )
        paid = validate_success(
            api.transition_annuity_payment(
                payment_id, {"action": "PAY"}, gift_admin_headers
            )
        )
        assert paid["status"] == "PAID"
        agreement = validate_success(api.get_gift_agreement(agreement_id, gift_admin_headers))
        # Full cycle ACTIVE -> SUSPENDED -> ACTIVE traversed.
        assert agreement["status"] == "ACTIVE"
        assert agreement["total_paid_cents"] == 125000


class TestPayGatedBySuspension:
    def _suspended_with_two_due(self, api, compliance_headers):
        _donor, agreement, _payments = _quarterly_crat_active()
        # Payments 1 (2026-11-01) and 2 (2027-02-01) both DUE.
        set_clock("2027-02-01T00:00:00Z")
        due, _meta = list_payments(agreement["id"], status="DUE")
        validate_success(
            api.transition_gift_agreement(
                agreement["id"], {"action": "SUSPEND"}, compliance_headers
            )
        )
        return agreement["id"], due[0]["id"], due[1]["id"]

    def test_pay_rejected_but_defer_allowed_under_suspension(
        self, api, compliance_headers, gift_admin_headers
    ):
        """PRD §3.6: "Disbursing a payment (`PAY`, by a `GiftAdministrator`)
        requires the payment to be `DUE` — otherwise `ERR_PAYMENT_NOT_DUE`
        (HTTP 409) — and the parent agreement to be `ACTIVE`: a `SUSPENDED`
        parent yields `ERR_AGREEMENT_SUSPENDED`, and any other parent status
        yields `ERR_INVALID_STATE`."
        PRD §3.6: "Deferral (`DEFER`) moves a `DUE` payment to `DEFERRED` with
        a `defer_until` instant that must lie strictly in the future of the
        logical clock, else `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Difficulty/cross_entity_state_dependency/payment_pay_gated_by_agreement_suspension
        """
        agreement_id, pay_id, defer_id = self._suspended_with_two_due(
            api, compliance_headers
        )
        resp = api.transition_annuity_payment(
            pay_id, {"action": "PAY"}, gift_admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_SUSPENDED)
        assert resp.status_code == 409

        # The suspension gate is PAY-specific: DEFER on a sibling DUE payment
        # carries no parent-agreement precondition in its own rule.
        deferred = validate_success(
            api.transition_annuity_payment(
                defer_id,
                {"action": "DEFER", "defer_until": "2027-03-01T00:00:00Z"},
                gift_admin_headers,
            )
        )
        assert deferred["status"] == "DEFERRED"

    def test_resume_restores_pay(self, api, compliance_headers, gift_admin_headers):
        """PRD §3.3: "Once `ACTIVE`, a `ComplianceOfficer` may `SUSPEND` the
        agreement — which blocks all payment disbursements on its payments with
        `ERR_AGREEMENT_SUSPENDED` (HTTP 409) for the duration — and later
        `RESUME` it back to `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/payment_pay_gated_by_agreement_suspension
        """
        agreement_id, pay_id, _defer_id = self._suspended_with_two_due(
            api, compliance_headers
        )
        resp = api.transition_annuity_payment(
            pay_id, {"action": "PAY"}, gift_admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_SUSPENDED)
        validate_success(
            api.transition_gift_agreement(
                agreement_id, {"action": "RESUME"}, compliance_headers
            )
        )
        paid = validate_success(
            api.transition_annuity_payment(pay_id, {"action": "PAY"}, gift_admin_headers)
        )
        assert paid["status"] == "PAID"


class TestObligationConservation:
    def _paid_and_lapsed(self, api, gift_admin_headers):
        _donor, agreement, _payments = _monthly_crat_active()
        set_clock("2026-09-01T00:00:00Z")
        due, _meta = list_payments(agreement["id"], status="DUE")
        validate_success(
            api.transition_annuity_payment(due[0]["id"], {"action": "PAY"}, gift_admin_headers)
        )
        scheduled, _meta = list_payments(agreement["id"], status="SCHEDULED")
        lapsed = validate_success(
            api.transition_annuity_payment(
                scheduled[0]["id"], {"action": "LAPSE"}, gift_admin_headers
            )
        )
        after = validate_success(api.get_gift_agreement(agreement["id"], gift_admin_headers))
        return agreement["id"], lapsed, after

    def test_pay_and_lapse_reallocate_obligation_mass(self, api, gift_admin_headers):
        """PRD §3.6: "Payment stamps `paid_at` from the logical clock,
        recomputes the parent agreement's `total_paid_cents` as the sum of
        `amount_cents` over its `PAID` payments".
        PRD §3.6: "Every lapse recomputes the parent agreement's
        `liability_released_cents` (the sum of `amount_cents` over its `LAPSED`
        payments) and increments both versions. Alongside `total_paid_cents`
        and `liability_released_cents`, the agreement continuously reports
        `total_scheduled_cents` as the sum over **all** of its payments
        regardless of status."

        Design: Difficulty/compensating_invariant/annuity_obligation_pay_lapse_conservation
        """
        agreement_id, _lapsed, after = self._paid_and_lapsed(api, gift_admin_headers)
        assert after["total_paid_cents"] == AGE98_MONTHLY_PAYMENT_CENTS
        assert after["liability_released_cents"] == AGE98_MONTHLY_PAYMENT_CENTS
        # total_scheduled is the sum over ALL payments and is unchanged by
        # PAY/LAPSE: 8325 paid + 8325 released + 22 * 8325 open == 199800.
        assert after["total_scheduled_cents"] == AGE98_TOTAL_SCHEDULED_CENTS
        remaining_open = 22 * AGE98_MONTHLY_PAYMENT_CENTS
        assert_obligation_conservation(after, remaining_open)

    def test_status_census_after_pay_and_lapse(self, api, gift_admin_headers):
        """PRD §3.6: "Lapsing is available from `SCHEDULED`, `DUE`, or
        `DEFERRED`, either directly — where `lapse_reason` is `MANUAL` — or
        through the cascades of §3.1 and §3.3, which stamp `DONOR_DEATH`,
        `TERMINATION`, or `MATURITY` according to the triggering event."

        Design: Difficulty/compensating_invariant/annuity_obligation_pay_lapse_conservation
        """
        agreement_id, lapsed, _after = self._paid_and_lapsed(api, gift_admin_headers)
        assert lapsed["status"] == "LAPSED"
        assert lapsed["lapse_reason"] == "MANUAL"

        _paid, meta_paid = list_payments(agreement_id, status="PAID")
        _lapsed_rows, meta_lapsed = list_payments(agreement_id, status="LAPSED")
        _sched, meta_sched = list_payments(agreement_id, status="SCHEDULED")
        assert meta_paid["total_count"] == 1
        assert meta_lapsed["total_count"] == 1
        assert meta_sched["total_count"] == 22
        assert (
            meta_paid["total_count"] + meta_lapsed["total_count"] + meta_sched["total_count"]
            == AGE98_PAYMENT_COUNT
        )
