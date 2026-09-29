"""Invoice line rounding, the two billing modes, the discount/surcharge order,
and the conserved customer receivable ledger."""

import pytest

from test_helpers import (
    BILLING_CLERK,
    build_critical_world,
    build_standard_world,
    read_customer,
    read_invoice,
    read_plan,
    setup_closed_critical_job,
    setup_closed_standard_job,
    validate_paginated,
    validate_success,
)

CANONICAL_HOURLY_CLAIM = {"on_site_hours": 9.5, "travel_hours": 1.5, "travel_miles": 62.3}


def _create_invoice(api, plan_id, version, **overrides):
    payload = {"lift_plan_id": plan_id, "billing_mode": "HOURLY",
               "expected_lift_plan_version": version}
    payload.update(overrides)
    return validate_success(api.create_invoice(payload, BILLING_CLERK), 201)


class TestInvoiceLineRounding:
    """Difficulty rule: combinatorial_formula."""

    def test_each_line_is_rounded_to_whole_cents_before_the_lines_are_summed(self, api):
        """PRD 3.9: "`line_overtime_cents` is `overtime_hours` multiplied by that same
        rate and then by 1.5, rounded half up, and is likewise 0 under `LUMP_SUM`."
        PRD 3.9: "`line_travel_cents` is `travel_miles` multiplied by 285 cents per
        mile, rounded half up, and applies under both modes."
        PRD 3.9: "Each of those seven lines is **rounded to whole cents first, and
        only then are the seven rounded lines added together** to give
        `subtotal_cents`. Summing the unrounded lines and rounding once at the end
        produces a different answer and is wrong."

        Design: Difficulty/combinatorial_formula/invoice_subtotal_rounds_each_line_before_summing
        """
        world = build_standard_world()
        ctx = setup_closed_standard_job(world, plan_overrides={"job_reference": "JOB-6100"})
        assert ctx["plan"]["lift_class"] == "STANDARD"
        assert ctx["plan"]["standby_hours_billable"] == pytest.approx(3.25, abs=0.0001)

        invoice = _create_invoice(api, ctx["plan_id"], ctx["plan_version"],
                                  **CANONICAL_HOURLY_CLAIM)

        assert invoice["line_overtime_cents"] == 204_188
        assert invoice["line_standby_cents"] == 110_602
        assert invoice["line_travel_cents"] == 17_756
        assert invoice["subtotal_cents"] == 945_546, (
            "round-each-line-then-sum gives 945546; sum-then-round gives 945545"
        )
        assert invoice["subtotal_cents"] != 945_545

    def test_hourly_hours_split_at_the_eight_hour_regular_cap(self, api):
        """PRD 3.9: "Under `HOURLY`, the invoice's `billable_hours` is the sum of
        `on_site_hours` and `travel_hours`, or 4.0 hours if that sum is smaller — a
        four-hour minimum applies whether or not the crew was there four hours. Its
        `regular_hours` is the smaller of `billable_hours` and 8.0 hours, and its
        `overtime_hours` is whatever part of `billable_hours` exceeds 8.0 hours, or
        zero if none does."
        PRD 3.9: "`line_regular_cents` is `regular_hours` multiplied by the assigned
        crane's `hourly_rate_cents`, rounded half up, and is 0 under `LUMP_SUM`."
        PRD 3.9: "`line_mobdemob_cents` is the crane's `mob_demob_cents` under
        `HOURLY` and 0 under `LUMP_SUM`, because mobilization is inside the fixed
        price."

        Design: Difficulty/combinatorial_formula/invoice_subtotal_rounds_each_line_before_summing
        """
        world = build_standard_world()
        ctx = setup_closed_standard_job(world, plan_overrides={"job_reference": "JOB-6100"})
        invoice = _create_invoice(api, ctx["plan_id"], ctx["plan_version"],
                                  **CANONICAL_HOURLY_CLAIM)

        assert invoice["billable_hours"] == pytest.approx(11.0, abs=0.0001)
        assert invoice["regular_hours"] == pytest.approx(8.0, abs=0.0001)
        assert invoice["overtime_hours"] == pytest.approx(3.0, abs=0.0001)
        assert invoice["line_regular_cents"] == 363_000
        assert invoice["line_mobdemob_cents"] == 250_000


class TestDiscountAndSurchargeOrder:
    """Difficulty rule: combinatorial_formula."""

    def test_the_volume_tier_reads_the_pre_surcharge_subtotal(self, api):
        """PRD 3.9: "Step two selects `discount_pct` from a volume tier keyed on that
        **pre-surcharge** subtotal: a subtotal at or above 6,000,000 cents takes eight
        hundredths; failing that, one at or above 2,500,000 cents takes five
        hundredths; failing that, one at or above 1,000,000 cents takes two
        hundredths; anything below takes zero."
        PRD 3.9: "Keying the tier on the subtotal *after* the surcharge is wrong and
        changes the answer whenever the surcharge alone would carry the bill across a
        tier boundary."

        Design: Difficulty/combinatorial_formula/discount_tier_keyed_on_presurcharge_subtotal_not_on_gross_bill
        """
        world = build_standard_world()
        ctx = setup_closed_standard_job(world, plan_overrides={"job_reference": "JOB-6101"})
        invoice = _create_invoice(api, ctx["plan_id"], ctx["plan_version"],
                                  **CANONICAL_HOURLY_CLAIM)

        assert invoice["subtotal_cents"] == 945_546
        assert invoice["discount_pct"] == pytest.approx(0.00, abs=0.0001)
        assert invoice["discount_cents"] == 0

    def test_surcharge_applies_to_the_discounted_subtotal_and_fixes_the_total(self, api):
        """PRD 3.9: "Step four sets `fuel_surcharge_cents` to seven hundredths of the
        discounted subtotal — that is, of `subtotal_cents` less `discount_cents` —
        rounded half up to whole cents. Step five sets `total_cents` to
        `subtotal_cents`, less `discount_cents`, plus `fuel_surcharge_cents`."

        Design: Difficulty/combinatorial_formula/discount_tier_keyed_on_presurcharge_subtotal_not_on_gross_bill
        """
        world = build_standard_world()
        ctx = setup_closed_standard_job(world, plan_overrides={"job_reference": "JOB-6101"})
        invoice = _create_invoice(api, ctx["plan_id"], ctx["plan_version"],
                                  **CANONICAL_HOURLY_CLAIM)

        assert invoice["fuel_surcharge_cents"] == 66_188
        assert invoice["total_cents"] == 1_011_734
        assert invoice["total_cents"] != 991_499, (
            "991499 is the circular reading that keys the tier on subtotal + surcharge"
        )


class TestBillingModeDivergence:
    """Difficulty rule: dual_variant_calc."""

    def test_hourly_bill_for_the_canonical_closed_job(self, api):
        """PRD 3.9: "Under `HOURLY`, the invoice's `billable_hours` is the sum of
        `on_site_hours` and `travel_hours`, or 4.0 hours if that sum is smaller — a
        four-hour minimum applies whether or not the crew was there four hours."
        PRD 3.9: "The billable standby figure is the full `standby_hours_source` with
        **no** free allowance."
        PRD 3.8: "The merged total is the sum of the merged interval lengths in
        hours, rounded half up to four decimal places, and the plan's
        `standby_hours_billable` is that total rounded **up** to the next quarter of
        an hour."

        Design: Difficulty/dual_variant_calc/invoice_hourly_vs_lump_sum_diverge_on_identical_job
        """
        world = build_critical_world()
        ctx = setup_closed_critical_job(world, plan_overrides={"job_reference": "JOB-7781"})

        assert ctx["plan"]["standby_hours_billable"] == pytest.approx(3.25, abs=0.0001)

        invoice = _create_invoice(api, ctx["plan_id"], ctx["plan_version"],
                                  **CANONICAL_HOURLY_CLAIM)
        assert invoice["subtotal_cents"] == 945_546
        assert invoice["total_cents"] == 1_011_734
        assert invoice["line_mobdemob_cents"] == 250_000
        assert invoice["line_standby_cents"] == 110_602

    def test_lump_sum_bill_diverges_from_hourly_on_the_identical_job(self, api):
        """PRD 3.9: "Under `LUMP_SUM`, `billable_hours`, `regular_hours` and
        `overtime_hours` are all 0, and the billable standby figure is
        `standby_hours_source` reduced by a free allowance of 2.0 hours, floored at
        zero — the first two hours of standby are absorbed into the fixed price."
        PRD 3.9: "`line_mobdemob_cents` is the crane's `mob_demob_cents` under
        `HOURLY` and 0 under `LUMP_SUM`, because mobilization is inside the fixed
        price."
        PRD 3.9: "and — because the newest bill for a job retires the last unsent one
        — moves any prior invoice on the same plan still standing at `DRAFT` to
        `VOIDED`."

        Design: Difficulty/dual_variant_calc/invoice_hourly_vs_lump_sum_diverge_on_identical_job
        """
        world = build_critical_world()
        ctx = setup_closed_critical_job(world, plan_overrides={"job_reference": "JOB-7781"})

        hourly = _create_invoice(api, ctx["plan_id"], ctx["plan_version"],
                                 **CANONICAL_HOURLY_CLAIM)
        version_after_first = read_plan(ctx["plan_id"])["version"]
        lump = _create_invoice(api, ctx["plan_id"], version_after_first,
                               billing_mode="LUMP_SUM", lump_sum_cents=850_000,
                               **CANONICAL_HOURLY_CLAIM)

        assert lump["subtotal_cents"] == 910_295
        assert lump["total_cents"] == 974_016
        assert lump["line_mobdemob_cents"] == 0
        assert lump["line_standby_cents"] == 42_539
        assert lump["total_cents"] != hourly["total_cents"], (
            "the identical job must bill differently under the two modes"
        )
        assert read_invoice(hourly["id"])["status"] == "VOIDED"
        assert lump["status"] == "DRAFT"


class TestEmptyStandbySetAndMinimumHourFloor:
    """Difficulty rule: boundary_precision_check."""

    def test_a_job_with_no_closed_standby_bills_zero_standby(self, api):
        """PRD 3.8: "The plan's `standby_hours_billable` is recomputed from every
        closed standby event on the plan."
        PRD 3.9: "`line_standby_cents` is the mode-specific billable standby hours
        multiplied by the rate and then by seventy-five hundredths, rounded half up,
        and applies under both modes."

        Design: Difficulty/boundary_precision_check/empty_closed_standby_set_zeroes_standby_line_at_minimum_hour_floor
        """
        world = build_standard_world()
        ctx = setup_closed_standard_job(world, with_standby=False,
                                        plan_overrides={"job_reference": "JOB-6300"})

        assert ctx["plan"]["standby_hours_billable"] == pytest.approx(0.0, abs=0.0001)

        events, meta = validate_paginated(
            api.list_standby_events(BILLING_CLERK, params={"lift_plan_id": ctx["plan_id"]})
        )
        assert events == []
        assert meta["total_count"] == 0
        assert meta["has_more"] is False

        invoice = _create_invoice(api, ctx["plan_id"], ctx["plan_version"],
                                  on_site_hours=2.5, travel_hours=1.0, travel_miles=0.0)
        assert invoice["line_standby_cents"] == 0

    def test_short_portal_to_portal_claim_lands_on_the_four_hour_floor(self, api):
        """PRD 3.9: "Under `HOURLY`, the invoice's `billable_hours` is the sum of
        `on_site_hours` and `travel_hours`, or 4.0 hours if that sum is smaller — a
        four-hour minimum applies whether or not the crew was there four hours."
        PRD 3.9: "Step four sets `fuel_surcharge_cents` to seven hundredths of the
        discounted subtotal — that is, of `subtotal_cents` less `discount_cents` —
        rounded half up to whole cents."

        Design: Difficulty/boundary_precision_check/empty_closed_standby_set_zeroes_standby_line_at_minimum_hour_floor
        """
        world = build_standard_world()
        ctx = setup_closed_standard_job(world, with_standby=False,
                                        plan_overrides={"job_reference": "JOB-6300"})
        invoice = _create_invoice(api, ctx["plan_id"], ctx["plan_version"],
                                  on_site_hours=2.5, travel_hours=1.0, travel_miles=0.0)

        assert invoice["billable_hours"] == pytest.approx(4.0, abs=0.0001)
        assert invoice["regular_hours"] == pytest.approx(4.0, abs=0.0001)
        assert invoice["overtime_hours"] == pytest.approx(0.0, abs=0.0001)
        assert invoice["line_regular_cents"] == 181_500
        assert invoice["line_travel_cents"] == 0
        assert invoice["subtotal_cents"] == 431_500
        assert invoice["fuel_surcharge_cents"] == 30_205
        assert invoice["total_cents"] == 461_705


class TestReceivableConservation:
    """Difficulty rule: compensating_invariant."""

    @staticmethod
    def _closed_job_with_draft_invoice(api, world):
        ctx = setup_closed_standard_job(world, plan_overrides={"job_reference": "JOB-6600"})
        invoice = _create_invoice(api, ctx["plan_id"], ctx["plan_version"],
                                  **CANONICAL_HOURLY_CLAIM)
        ctx["invoice"] = invoice
        ctx["invoice_id"] = invoice["id"]
        return ctx

    def test_issuing_the_invoice_moves_the_open_receivable(self, api):
        """PRD 3.9: "`open_receivable_cents` is the sum of `total_cents` across every
        invoice belonging to that customer whose status is `ISSUED` **or**
        `DISPUTED`; drafts, paid invoices and voided invoices are excluded.
        `invoice_count` is the number of that customer's invoices in any status
        whatsoever."
        PRD 3.9: "Issuing moves a `DRAFT` — or a `DISPUTED` — invoice to `ISSUED`,
        and requires the owning customer's `credit_hold` to be false, or it is
        refused with `ERR_CUSTOMER_CREDIT_HOLD`."

        Design: Difficulty/compensating_invariant/customer_open_receivable_conserved_across_issue_then_void
        """
        world = build_standard_world()
        ctx = self._closed_job_with_draft_invoice(api, world)
        assert ctx["invoice"]["total_cents"] == 1_011_734

        before = read_customer(world["cust_id"])
        assert before["open_receivable_cents"] == 0
        assert before["invoice_count"] == 1

        issued = validate_success(api.issue_invoice(ctx["invoice_id"], BILLING_CLERK))
        assert issued["status"] == "ISSUED"
        assert read_customer(world["cust_id"])["open_receivable_cents"] == 1_011_734

    def test_voiding_the_issued_invoice_restores_the_pre_issue_receivable(self, api):
        """PRD 3.9: "Because a disputed invoice stays inside the open set, disputing
        changes nothing about the balance; because the ledger is recomputed rather
        than adjusted, issuing an invoice and then voiding it returns
        `open_receivable_cents` to exactly its pre-issue value while leaving
        `invoice_count` where it stood after the invoice was created."

        Design: Difficulty/compensating_invariant/customer_open_receivable_conserved_across_issue_then_void
        """
        world = build_standard_world()
        ctx = self._closed_job_with_draft_invoice(api, world)

        validate_success(api.issue_invoice(ctx["invoice_id"], BILLING_CLERK))
        voided = validate_success(api.void_invoice(
            ctx["invoice_id"], {"reason": "billed against the wrong purchase order"},
            BILLING_CLERK))
        assert voided["status"] == "VOIDED"

        after = read_customer(world["cust_id"])
        assert after["open_receivable_cents"] == 0, (
            "the recomputed ledger must return to exactly its pre-issue value"
        )
        assert after["invoice_count"] == 1, "voiding never removes an invoice from the count"
