"""Mid-rental class changes: the upgrade cost split and the divergence between
the provisional estimate and the audited charge."""
import pytest

from test_helpers import (
    ADJUSTER,
    ApiErrorId,
    api_client,
    assert_class_change_record,
    assert_invoice,
    get_reservation_view,
    record_class_change,
    return_reservation,
    set_clock,
    setup_active_rental_scenario,
    setup_authorized_rental_scenario,
    submit_invoice,
    validate_success,
)


class TestUpgradeCostResponsibility:
    def _setup_upgrade(self):
        """Authorized STANDARD reservation; upgrade to PREMIUM effective
        2026-08-10 with no waiver (5 remaining days at the new rate)."""
        ctx = setup_authorized_rental_scenario()
        change = record_class_change(ctx["reservation"]["id"], "PREMIUM",
                                     "2026-08-10", upgrade_waiver=False)
        ctx["class_change"] = change
        return ctx

    def test_upgrade_customer_bears_full_differential(self, api):
        """PRD §3.5: "On an upgrade, the insurer's per-day share is the amount by
        which the capped new rate exceeds the capped old rate — each rate capped
        at the claim's `coverage_daily_limit_cents` before the comparison, and the
        difference floored at zero — while the customer's per-day share depends on
        the waiver: a waived upgrade (for example, when no comparable vehicle was
        available) sets `per_day_customer_cents` to zero, and an unwaived upgrade
        sets it to the amount by which the new rate exceeds the greater of the
        coverage daily limit and the old rate, floored at zero. Multiplying each
        per-day figure by the remaining days yields
        `customer_responsibility_cents` and `insurer_delta_cents`."

        Design: Difficulty/combinatorial_formula/class_change_upgrade_nested_minmax
        """
        ctx = self._setup_upgrade()
        change = ctx["class_change"]
        assert_class_change_record(change)
        assert change["from_class"] == "STANDARD"
        assert change["to_class"] == "PREMIUM"
        assert change["per_day_customer_cents"] == 3000, (
            f"Expected max(0, 9000 - max(6000, 6000)) == 3000, "
            f"got {change['per_day_customer_cents']}"
        )
        assert change["customer_responsibility_cents"] == 15000, (
            f"Expected 3000 x 5 remaining days == 15000, "
            f"got {change['customer_responsibility_cents']}"
        )
        assert change["insurer_delta_cents"] == 0, (
            f"The old rate already sits at the limit, so the insurer share "
            f"collapses to 0; got {change['insurer_delta_cents']}"
        )

    def test_upgrade_leaves_insurer_estimate_unchanged(self, api):
        """PRD §3.5: "The change then applies: the reservation's `vehicle_class`
        becomes the `to_class`, `daily_rate_cents` is re-read from the snapshot
        for the new class, the provisional estimate absorbs the insurer delta, and
        the claim's reserve is reduced by the insurer delta — a negative delta
        credits the reserve."

        Design: Difficulty/combinatorial_formula/class_change_upgrade_nested_minmax
        """
        ctx = self._setup_upgrade()
        reservation = get_reservation_view(ctx["reservation"]["id"])
        assert reservation["vehicle_class"] == "PREMIUM"
        assert reservation["daily_rate_cents"] == 9000
        assert reservation["estimated_charge_cents"] == 60000, (
            f"Insurer delta 0 must leave the provisional estimate at 60000, "
            f"got {reservation['estimated_charge_cents']}"
        )


class TestProvisionalVsAuditedDivergence:
    def _setup_divergence(self):
        """Active STANDARD rental downgraded to ECONOMY effective 2026-08-10,
        returned 2026-08-15, then billed for the full window."""
        ctx = setup_active_rental_scenario()
        record_class_change(ctx["reservation"]["id"], "ECONOMY", "2026-08-10")
        ctx["reservation"] = return_reservation(
            ctx["reservation"]["id"], ctx["partner"]["id"], "2026-08-15T10:00:00Z")
        ctx["invoice"] = submit_invoice(
            ctx["reservation"]["id"], ctx["partner"]["id"], "INV-A1",
            period_start="2026-08-05", period_end="2026-08-15",
            daily_rate_cents=4500, tax_cents=4200, fees_cents=3000)
        return ctx

    def test_provisional_estimate_diverges_from_audited_charge(self, api):
        """PRD §3.4: "This provisional estimate is deliberately uncapped by the
        coverage daily limit and excludes tax entirely: it is the desk's
        forward-looking authorization exposure, not the audit figure, and it
        diverges from the audited charge whenever the booked rate exceeds the
        limit or any tax is later billed."
        PRD §3.8: "`ADJUST_TO_AUTHORIZED` prices the invoice by the audited final
        algorithm above — clipping days to the authorized window, capping each day
        at the coverage limit, applying per-day tax rounding, and capping fees —
        and likewise moves the invoice to `AUTO_APPROVED`."

        Design: Difficulty/dual_variant_calc/reservation_provisional_vs_audited_diverge
        """
        ctx = self._setup_divergence()
        estimate = get_reservation_view(ctx["reservation"]["id"])["estimated_charge_cents"]
        assert estimate == 52500, (
            f"Provisional variant: 60000 - (6000-4500) x 5 == 52500, "
            f"got {estimate}"
        )

        resp = api.decide_invoice_audit(ctx["invoice"]["id"],
                                        {"decision": "ADJUST_TO_AUTHORIZED"},
                                        ADJUSTER)
        audited_invoice = validate_success(resp, 200)
        assert audited_invoice["status"] == "AUTO_APPROVED"
        assert audited_invoice["audited_payable_cents"] == 59200, (
            f"Audit variant: 5 x (6000+480) + 5 x (4500+360) + min(3000,2500) "
            f"== 59200, got {audited_invoice['audited_payable_cents']}"
        )
        assert audited_invoice["audited_payable_cents"] != estimate, (
            "The two valid algorithms must diverge for identical rental days"
        )

    def test_class_change_routes_invoice_to_manual_review(self, api):
        """PRD §3.8: "An invoice is auto-adjudicated to `AUTO_APPROVED` if and
        only if all five criteria hold: the billed period lies entirely within the
        reservation's authorized window from `pickup_date` to
        `authorized_return_date`; the billed `daily_rate_cents` equals the
        reservation's currently applicable rate; no class change record exists on
        the reservation; ..."
        PRD §3.8: "A manually routed invoice keeps `audited_payable_cents` null
        until an adjuster prices it."

        Design: Difficulty/dual_variant_calc/reservation_provisional_vs_audited_diverge
        """
        ctx = self._setup_divergence()
        invoice = ctx["invoice"]
        assert_invoice(invoice)
        assert invoice["status"] == "MANUAL_REVIEW", (
            "A class change record on the reservation must force MANUAL_REVIEW "
            f"even with an in-window period; got {invoice['status']}"
        )
        assert invoice["unauthorized_days"] == 0, (
            "The billed period lies entirely inside the authorized window"
        )
        assert invoice["audited_payable_cents"] is None, (
            "A manually routed invoice must carry no audited amount until priced"
        )
