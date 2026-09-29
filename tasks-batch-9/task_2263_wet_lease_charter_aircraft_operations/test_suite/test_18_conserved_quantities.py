"""Quantities defined as functions of other rows, and their compensating operations.

Voiding an issued invoice must walk back every effect of issuing it, and cancelling a
scheduled leg must walk back every effect of scheduling it.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    approve_invoice,
    assert_gross_charge_composition,
    cancel_leg_payload,
    close_month,
    file_reliability_report,
    fly_leg,
    get_success_data,
    issue_invoice,
    make_billing_admin_headers,
    prepare_invoice,
    schedule_leg,
    set_clock,
    setup_active_lease,
    validate_success,
    void_invoice_payload,
)

OPS = TEST_USERS["lessor_ops_headers"]
BILLING = TEST_USERS["billing_admin_headers"]

PREPARER = make_billing_admin_headers("billing-clerk-01")
APPROVER = make_billing_admin_headers("billing-supervisor-02")


def _issued_final_month(api):
    """One 100-minute revenue leg flown, 2026-09 closed and its FINAL invoice ISSUED."""
    scenario = setup_active_lease(api)
    leg = fly_leg(api, scenario, "2026-09-10T06:00:00Z", "2026-09-10T07:40:00Z")
    period = close_month(api, scenario["period"]["id"])
    file_reliability_report(api, scenario, period_month="2026-09")
    period = get_success_data(api.get_utilization_period(period["id"], BILLING))
    invoice = prepare_invoice(
        api, period, due_on="2026-10-15", variant="FINAL", headers=PREPARER
    )
    invoice = approve_invoice(api, invoice["id"], headers=APPROVER)
    invoice = issue_invoice(api, invoice["id"], headers=APPROVER)
    return scenario, leg, period, invoice


def _scheduled_leg_inside_the_duty_window(api):
    """One SCHEDULED 330-minute leg, with the clock advanced a day past its off-blocks."""
    scenario = setup_active_lease(api)
    leg = schedule_leg(api, scenario, "2026-09-03T06:00:00Z", "2026-09-03T11:30:00Z")
    set_clock(api, "2026-09-04T00:00:00Z")
    return scenario, leg


class TestLesseeReceivableAndCreditedBlockTime:
    def test_issuing_the_final_invoice_charges_the_receivable_and_settles_the_month(
        self, api
    ):
        """PRD §2.9: `Lessee.outstanding_balance_usd_cents` equals the sum of `amount_cents` over every `SettlementInvoice` whose `status` is `ISSUED` and whose lease belongs to that lessee.
        PRD §3.9: Issue moves the invoice from `APPROVED` to `ISSUED`, records `due_on`, adds `amount_cents` to the lessee's `outstanding_balance_usd_cents`, and — when the invoice's `variant` is `FINAL` — drives the period from `PENDING_SETTLEMENT` to `SETTLED`.
        PRD §3.9: That settlement moves every `COMPLETED` leg of the month from `UNBILLED` or `PROVISIONALLY_BILLED` to `FINALIZED`, adds the period's `credited_block_minutes` to the lease's `lifetime_credited_block_minutes`, and increments the period's `version`.
        PRD §3.9: `amount_cents` is frozen at preparation time: the period's `provisional_charge_cents` when `variant` is `PROVISIONAL`, and its `final_charge_cents` otherwise.

        Design: Difficulty/compensating_invariant/outstanding_balance_restored_when_issued_invoice_voided
        """
        scenario, leg, period, invoice = _issued_final_month(api)

        assert invoice["status"] == "ISSUED", (
            f"the invoice must be ISSUED before the void, got {invoice['status']}"
        )
        assert invoice["amount_cents"] == 2400000, (
            "the FINAL invoice must freeze the month's final charge of 2400000 cents, got "
            f"{invoice['amount_cents']}"
        )

        lessee = get_success_data(api.get_lessee(scenario["lessee"]["id"], BILLING))
        assert lessee["outstanding_balance_usd_cents"] == 2400000, (
            "issuing must add the invoice amount to the receivable, expected 2400000, "
            f"got {lessee['outstanding_balance_usd_cents']}"
        )

        settled = get_success_data(api.get_utilization_period(period["id"], BILLING))
        assert settled["status"] == "SETTLED", (
            f"issuing a FINAL invoice must settle the month, got {settled['status']}"
        )

        billed_leg = get_success_data(api.get_flight_leg(leg["id"], OPS))
        assert billed_leg["billing_state"] == "FINALIZED", (
            "settlement must move the completed leg to FINALIZED, got "
            f"{billed_leg['billing_state']}"
        )

        lease = get_success_data(api.get_lease(scenario["lease"]["id"], OPS))
        assert lease["lifetime_credited_block_minutes"] == 100, (
            "settlement must add the period's 100 credited block minutes to the lease "
            f"total, got {lease['lifetime_credited_block_minutes']}"
        )

    def test_voiding_the_issued_invoice_restores_every_quantity_it_moved(self, api):
        """PRD §2.9: The balance is maintained incrementally: issuing an invoice adds its `amount_cents`, and voiding an already-issued invoice subtracts the same `amount_cents`, restoring the pre-issue figure exactly.
        PRD §2.9: `LeaseAgreement.lifetime_credited_block_minutes` accumulates the `credited_block_minutes` of the lease's settled months: a period settling adds its figure, and a settled period returning to await settlement because its invoice was voided subtracts the same figure.
        PRD §3.9: Voiding is admissible from `PREPARED`, from `APPROVED` or from `ISSUED`, always records the supplied `void_reason`, and always lands in the terminal `VOID`.
        PRD §3.9: Voiding an `ISSUED` invoice subtracts its `amount_cents` from the lessee's `outstanding_balance_usd_cents`, restoring the pre-issue figure exactly, and — when the invoice's `variant` is `FINAL` — drives the period from `SETTLED` back to `PENDING_SETTLEMENT` so a corrected invoice can be prepared.
        PRD §3.9: That reversion returns every leg of the month from `FINALIZED` to `PROVISIONALLY_BILLED` if it had been provisionally invoiced and to `UNBILLED` if it had not, subtracts the period's `credited_block_minutes` from the lease's `lifetime_credited_block_minutes`, and increments the period's `version`.

        Design: Difficulty/compensating_invariant/outstanding_balance_restored_when_issued_invoice_voided
        """
        scenario, leg, period, invoice = _issued_final_month(api)

        voided = validate_success(
            api.void_settlement_invoice(
                invoice["id"],
                void_invoice_payload("LESSEE_RECONCILIATION_AGREED"),
                APPROVER,
            )
        )
        assert voided["status"] == "VOID", (
            f"voiding must land the invoice in VOID, got {voided['status']}"
        )
        assert voided["void_reason"] == "LESSEE_RECONCILIATION_AGREED", (
            "voiding must record the supplied reason, got "
            f"{voided['void_reason']}"
        )
        assert voided["amount_cents"] == 2400000, (
            "the voided amount stays frozen for audit, expected 2400000, got "
            f"{voided['amount_cents']}"
        )

        lessee = get_success_data(api.get_lessee(scenario["lessee"]["id"], BILLING))
        assert lessee["outstanding_balance_usd_cents"] == 0, (
            "voiding the only issued invoice must restore the receivable to 0, got "
            f"{lessee['outstanding_balance_usd_cents']}"
        )

        reverted = get_success_data(api.get_utilization_period(period["id"], BILLING))
        assert reverted["status"] == "PENDING_SETTLEMENT", (
            "voiding a FINAL invoice must return the month to PENDING_SETTLEMENT, got "
            f"{reverted['status']}"
        )
        assert reverted["final_charge_cents"] == 2400000, (
            "the void must not rewrite the closed month's final charge, expected "
            f"2400000, got {reverted['final_charge_cents']}"
        )

        unbilled_leg = get_success_data(api.get_flight_leg(leg["id"], OPS))
        assert unbilled_leg["billing_state"] == "UNBILLED", (
            "a leg that was never provisionally invoiced must revert to UNBILLED, got "
            f"{unbilled_leg['billing_state']}"
        )
        assert unbilled_leg["status"] == "COMPLETED", (
            "the financial reversion must not touch the operational dimension, expected "
            f"COMPLETED, got {unbilled_leg['status']}"
        )

        lease = get_success_data(api.get_lease(scenario["lease"]["id"], OPS))
        assert lease["lifetime_credited_block_minutes"] == 0, (
            "the void must subtract the period's credited block minutes from the lease "
            f"total, expected 0, got {lease['lifetime_credited_block_minutes']}"
        )


class TestRollingCrewExposure:
    def test_scheduling_the_leg_loads_both_pilots_rolling_exposure(self, api):
        """PRD §3.4: `rolling_duty_minutes_7d` is the sum, over the crew member's legs whose `status` is `SCHEDULED`, `DISPATCHED` or `COMPLETED` and whose `scheduled_out` falls within the last seven days — that is, at or after the instant 168 hours before the clock and strictly before the clock — of each leg's scheduled block minutes plus a fixed pre- and post-flight duty allowance of 105 minutes.
        PRD §3.4: `rolling_block_minutes_28d` is the sum of the scheduled block minutes alone, over the same status filter, for legs whose `scheduled_out` falls within the last twenty-eight days — at or after the instant 672 hours before the clock and strictly before it.
        PRD §3.4: A crew member counts a leg whether they are its `captain_id` or its `first_officer_id`.
        PRD §3.1: Reading a crew member back recomputes both exposure figures against the current logical clock before returning them.

        Design: Difficulty/compensating_invariant/crew_duty_exposure_restored_when_scheduled_leg_cancelled
        """
        scenario, leg = _scheduled_leg_inside_the_duty_window(api)

        assert leg["scheduled_block_minutes"] == 330, (
            "06:00Z to 11:30Z is 330 scheduled block minutes, got "
            f"{leg['scheduled_block_minutes']}"
        )

        for role in ("captain", "first_officer"):
            crew = get_success_data(api.get_crew_member(scenario[role]["id"], OPS))
            assert crew["rolling_duty_minutes_7d"] == 435, (
                f"the {role}'s seven-day duty must be 330 block minutes plus the "
                f"105-minute allowance, expected 435, got {crew['rolling_duty_minutes_7d']}"
            )
            assert crew["rolling_block_minutes_28d"] == 330, (
                f"the {role}'s twenty-eight-day block exposure must be 330, got "
                f"{crew['rolling_block_minutes_28d']}"
            )

    def test_cancelling_the_leg_releases_both_pilots_and_restores_the_full_shortfall(
        self, api
    ):
        """PRD §2.9: Because cancelled and diverted legs are excluded from the aggregate, cancelling a leg is an exact compensation for having scheduled it.
        PRD §3.6: A `SCHEDULED` leg cancelled by the lessee moves to `CANCELLED_LESSEE`; cancelled by the lessor it moves to `CANCELLED_LESSOR`.
        PRD §3.6: Either way `cancelling_party` and `cancel_reason` are recorded, `billing_state` is set to `CREDITED`, the rolling exposures of both `captain_id` and `first_officer_id` are recomputed — releasing the cancelled leg's duty and block contribution — and the lease's `OPEN` period is recomputed under the `PROVISIONAL` variant.
        PRD §3.8: Cancelled and diverted legs contribute nothing at all, so no lessee-cancellation credit ever appears in a provisional figure.
        PRD §3.8: When `credited_hours` is strictly less than `mgh_effective_hours`, `shortfall_hours` is their difference rounded half up to four decimal places and `overrun_hours` is 0.
        PRD §3.8: Separately, the lessor-cancelled hours of the month are the sum of `scheduled_block_minutes` over every leg of the month whose `status` is `CANCELLED_LESSOR`, divided by 60 and rounded half up to four decimal places; `lessor_attributable_shortfall_hours` is the lesser of `shortfall_hours` and that figure.
        PRD §3.8: `base_charge_cents` is `mgh_effective_hours` multiplied by the lease's `block_hour_rate_usd_cents`, rounded half up to whole cents.
        PRD §3.8: `gross_charge_cents` is `base_charge_cents` less `shortfall_credit_cents` plus `overrun_charge_cents`.
        PRD §3.8: Under the `PROVISIONAL` variant that net figure is written to `provisional_charge_cents`; under the `FINAL` variant it is written to `final_charge_cents`.

        Design: Difficulty/compensating_invariant/crew_duty_exposure_restored_when_scheduled_leg_cancelled
        """
        scenario, leg = _scheduled_leg_inside_the_duty_window(api)

        cancelled = validate_success(
            api.cancel_flight_leg(
                leg["id"], cancel_leg_payload("LESSEE", "COMMERCIAL"), OPS
            )
        )
        assert cancelled["status"] == "CANCELLED_LESSEE", (
            "a lessee cancellation of a SCHEDULED leg must land in CANCELLED_LESSEE, got "
            f"{cancelled['status']}"
        )
        assert cancelled["cancelling_party"] == "LESSEE", (
            f"the cancelling party must be recorded, got {cancelled['cancelling_party']}"
        )
        assert cancelled["billing_state"] == "CREDITED", (
            f"cancellation must set billing_state to CREDITED, got {cancelled['billing_state']}"
        )

        for role in ("captain", "first_officer"):
            crew = get_success_data(api.get_crew_member(scenario[role]["id"], OPS))
            assert crew["rolling_duty_minutes_7d"] == 0, (
                f"cancelling must release the {role}'s duty contribution entirely, "
                f"expected 0, got {crew['rolling_duty_minutes_7d']}"
            )
            assert crew["rolling_block_minutes_28d"] == 0, (
                f"cancelling must release the {role}'s block contribution entirely, "
                f"expected 0, got {crew['rolling_block_minutes_28d']}"
            )

        period = get_success_data(
            api.get_utilization_period(scenario["period"]["id"], BILLING)
        )
        assert period["credited_block_minutes"] == 0, (
            "a cancelled leg contributes nothing, so credited_block_minutes must be 0, "
            f"got {period['credited_block_minutes']}"
        )
        assert float(period["shortfall_hours"]) == pytest.approx(5.0000, abs=0.0001), (
            "the whole prorated guarantee must fall into shortfall, expected 5.0000, got "
            f"{period['shortfall_hours']}"
        )
        assert float(period["lessor_attributable_shortfall_hours"]) == pytest.approx(
            0.0000, abs=0.0001
        ), (
            "a lessee cancellation is not lessor-attributable, expected 0.0000, got "
            f"{period['lessor_attributable_shortfall_hours']}"
        )
        assert period["shortfall_credit_cents"] == 0, (
            "no lessor-attributable shortfall means no credit, expected 0 cents, got "
            f"{period['shortfall_credit_cents']}"
        )
        assert period["base_charge_cents"] == 2400000, (
            "5.0000 guaranteed hours at 480000 cents is 2400000 cents, got "
            f"{period['base_charge_cents']}"
        )
        assert period["gross_charge_cents"] == 2400000, (
            "the gross charge stays at the guarantee base, expected 2400000, got "
            f"{period['gross_charge_cents']}"
        )
        assert period["provisional_charge_cents"] == 2400000, (
            "the provisional net charge stays at the guarantee base, expected 2400000, "
            f"got {period['provisional_charge_cents']}"
        )
        assert_gross_charge_composition(period)
