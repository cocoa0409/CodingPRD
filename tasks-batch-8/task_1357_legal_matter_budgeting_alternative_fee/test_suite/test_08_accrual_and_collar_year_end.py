"""Accrual reporting cycle and year-end collar true-up band arithmetic."""
from test_helpers import (
    TEST_USERS,
    advance_periods,
    api_client,
    apply_approved_write_down,
    assert_accrual_report,
    assert_collar_true_up,
    add_billed_entry,
    add_time_entry,
    latest_accrual_report,
    make_billing_partner_headers,
    run_true_up,
    setup_active_matter,
    setup_collar_matter_year_ended,
    setup_matter_with_accrual_report,
    submit_entry,
    validate_success,
)

CLIENT_CONTACT = TEST_USERS["client_contact_headers"]


class TestAccrualReporting:

    def test_accrual_report_dispute_resubmit_cycle(self):
        """PRD section 3.8: "From `SUBMITTED`, a `ClientContact`
        acknowledges the report — moving it to the terminal `ACKNOWLEDGED`
        state — or disputes it, moving it to `DISPUTED`. A disputed report
        returns to `SUBMITTED` when a `BillingPartner` resubmits it, at
        which point the two snapshot fields are recomputed from the matter's
        current state."

        Design: Difficulty/non_linear_state_machine/accrual_report_dispute_resubmit_cycle
        """
        ctx = setup_matter_with_accrual_report()
        firm_id = ctx["firm"]["id"]
        report_id = ctx["report"]["id"]
        partner = make_billing_partner_headers(ctx["partner"]["id"])

        submitted = validate_success(
            api_client.submit_accrual_report(firm_id, report_id, partner),
            200)
        assert submitted["status"] == "SUBMITTED"

        disputed = validate_success(
            api_client.dispute_accrual_report(firm_id, report_id,
                                              CLIENT_CONTACT), 200)
        assert disputed["status"] == "DISPUTED"

        resubmitted = validate_success(
            api_client.resubmit_accrual_report(firm_id, report_id, partner),
            200)
        assert resubmitted["status"] == "SUBMITTED", (
            "a disputed report must return to SUBMITTED on resubmit")

        acknowledged = validate_success(
            api_client.acknowledge_accrual_report(firm_id, report_id,
                                                  CLIENT_CONTACT), 200)
        assert_accrual_report(acknowledged)
        assert acknowledged["status"] == "ACKNOWLEDGED"

    def test_accrual_amounts_exclude_written_down(self):
        """PRD section 3.8: "`accrued_fees_cents` sums
        `billable_amount_cents` over entries in `APPROVED` or `BILLED` whose
        `period_index` equals the report's period — period attribution
        follows the entry's own `entry_date`. `unbilled_wip_cents` sums
        `billable_amount_cents` over entries in `DRAFT`, `SUBMITTED`, or
        `APPROVED` whose `period_index` is at or before the report's period,
        inclusive through the period's end. Entries in `WRITTEN_DOWN` are
        excluded from both figures, having already been realized net."

        Design: Corner/calculations/accrual_report_computation_excludes_written_down
        """
        ctx = setup_active_matter(
            client_overrides={"accrual_reporting_required": True},
            with_second_partner=True,
            phases=[{"task_code": "L110", "budget": 1000000}])
        firm_id = ctx["firm"]["id"]
        matter_id = ctx["matter"]["id"]
        p1 = ctx["partner"]["id"]
        p2 = ctx["partner2"]["id"]

        # Identical billed activity in two consecutive periods, so the
        # report's accrued figure is 50000 regardless of which of the two
        # periods the freshly regenerated report covers; the written-down
        # entries (20000 each) must be excluded from both figures.
        add_billed_entry(firm_id, matter_id, p1, 50000, p1,
                         entry_date="2026-08-05")
        wd_first = add_billed_entry(firm_id, matter_id, p1, 20000, p1,
                                    entry_date="2026-08-06")
        wip = add_time_entry(firm_id, matter_id, p1, 7000,
                             entry_date="2026-08-07")
        submit_entry(firm_id, wip["id"], p1)
        add_billed_entry(firm_id, matter_id, p1, 50000, p1,
                         entry_date="2026-09-03")
        wd_second = add_billed_entry(firm_id, matter_id, p1, 20000, p1,
                                     entry_date="2026-09-04")

        apply_approved_write_down(firm_id, matter_id, [wd_first["id"]],
                                  5000, p1, p2)
        apply_approved_write_down(firm_id, matter_id, [wd_second["id"]],
                                  5000, p1, p2)

        # Regenerate a fresh DRAFT accrual report via period advancement.
        advance_periods(firm_id, 1)
        report = latest_accrual_report(firm_id, matter_id)

        fetched = validate_success(
            api_client.get_accrual_report(
                report["id"], make_billing_partner_headers(p1)), 200)
        assert fetched["accrued_fees_cents"] == 50000, (
            f"accrued fees must count only the period's BILLED 50000; the "
            f"WRITTEN_DOWN 20000 is excluded — got "
            f"{fetched['accrued_fees_cents']}")
        assert fetched["unbilled_wip_cents"] == 7000, (
            f"unbilled WIP must count only the SUBMITTED 7000; WRITTEN_DOWN "
            f"entries are excluded — got {fetched['unbilled_wip_cents']}")


class TestCollarTrueUp:

    def test_collar_true_up_above_upper_bound(self):
        """PRD section 3.9: "when actual fees are strictly above
        `collar_upper_bound_cents`, the excess is the actual fees minus the
        upper bound, the firm rebates the same share of that excess rounded
        half-up to the nearest cent, `true_up_amount_cents` is that amount
        as a positive figure, and `direction` is `REBATE_TO_CLIENT`".
        PRD section 3.9: "`actual_year_fees_cents` is the sum of
        `billable_amount_cents` over the matter's `BILLED` entries in that
        fiscal year."

        Design: Difficulty/combinatorial_formula/collar_true_up_nested_band_arithmetic
        """
        ctx = setup_collar_matter_year_ended(
            billed_amounts=[250000], lb=100000, ub=200000, share_bp=5000)

        true_up = run_true_up(ctx["firm"]["id"], ctx["matter"]["id"],
                              ctx["partner"]["id"])
        assert_collar_true_up(true_up)
        assert true_up["actual_year_fees_cents"] == 250000
        # Excess = 250000 - 200000 = 50000; share 5000 bp = 50% -> 25000.
        assert true_up["true_up_amount_cents"] == 25000, (
            f"rebate must be 50% of the 50000 excess = 25000, got "
            f"{true_up['true_up_amount_cents']}")
        assert true_up["direction"] == "REBATE_TO_CLIENT"

    def test_collar_true_up_at_upper_bound_in_band(self):
        """PRD section 3.9: "and when actual fees sit between the bounds —
        exactly equal to either bound included — `true_up_amount_cents` is
        zero and `direction` is `IN_BAND`."

        Design: Difficulty/boundary_precision_check/collar_true_up_exact_band_boundary
        """
        ctx = setup_collar_matter_year_ended(
            billed_amounts=[200000], lb=100000, ub=200000, share_bp=5000)

        true_up = run_true_up(ctx["firm"]["id"], ctx["matter"]["id"],
                              ctx["partner"]["id"])
        assert true_up["actual_year_fees_cents"] == 200000
        assert true_up["true_up_amount_cents"] == 0, (
            f"actual exactly equal to the upper bound is IN_BAND with zero "
            f"true-up, got {true_up['true_up_amount_cents']}")
        assert true_up["direction"] == "IN_BAND"
