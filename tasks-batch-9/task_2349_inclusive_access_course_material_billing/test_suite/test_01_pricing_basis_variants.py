"""Two valid ways to compute the same figure: the tier basis behind a student's
price, and the method behind a publisher's invoice.
"""

from test_helpers import (
    ReconciliationRunStatus,
    ReconciliationStatus,
    assert_money,
    assert_ratio,
    fixtures,
    validate_success,
)


def _section_with_a_late_third_charge(api):
    """Two day-one charges freeze the basis at 2, then a third student is charged.

    The third student registers on 2026-09-01 — before the census date and on or
    before the add/drop deadline — so the census basis sees three enrollments
    while the frozen posting basis still sees two.
    """
    scenario = fixtures.setup_billed_section(api, setup_clock="2026-07-01T00:00:00Z")

    student3 = fixtures.create_student(api, "S-1003", "Cara Wu")
    fixtures.set_clock(api, "2026-09-01T09:00:00Z")
    enrollment3 = fixtures.create_enrollment(
        api, scenario["section_id"], student3["id"], "2026-09-01"
    )
    charge3 = fixtures.post_single_charge(api, enrollment3["id"])

    scenario["student3"] = student3
    scenario["enrollment3"] = enrollment3
    scenario["charge3"] = charge3
    return scenario


class TestTierBasisVariants:
    """The posting-snapshot basis prices students; the census basis only audits."""

    def test_billing_summary_exposes_posting_and_census_bases_side_by_side(self, api,
                                                                          program_admin):
        """PRD §3.5: "It returns the `section_id`, the `ia_status`, the frozen
        `billing_basis_enrollment_count`, `tier_basis_posting_count` (the
        production basis — the frozen count actually used for pricing),
        `tier_basis_census_count` (the audit basis — the number of enrollments on
        the section whose `enrolled_on` is on or before the term's `census_date`
        and which are either still `ENROLLED` or whose `dropped_on` is later than
        the census date), `gross_per_student_posting_cents` and
        `gross_per_student_census_cents` (the per-student price the three-step
        pricing rule yields under each of those two bases), `charge_count`,
        `posted_charge_count`, `refunded_charge_count`, `total_net_billed_cents`,
        `total_publisher_share_cents`, `provisioned_access_count`,
        `revoked_access_count` and `participation_rate`."

        Design: Difficulty/dual_variant_calc/dual_variant_tier_basis_posting_snapshot_versus_census_date
        """
        scenario = _section_with_a_late_third_charge(api)

        summary = validate_success(
            api.get_section_billing_summary(scenario["section_id"], program_admin)
        )

        assert summary["billing_basis_enrollment_count"] == 2
        assert summary["tier_basis_posting_count"] == 2
        assert summary["tier_basis_census_count"] == 3
        assert_money(summary["gross_per_student_posting_cents"], 9450)
        assert_money(summary["gross_per_student_census_cents"], 7875)
        assert (summary["gross_per_student_posting_cents"]
                - summary["gross_per_student_census_cents"]) == 1575
        assert summary["charge_count"] == 3
        assert_money(summary["total_net_billed_cents"], 28350)
        assert_money(summary["total_publisher_share_cents"], 24948)

    def test_late_charge_prices_against_the_frozen_basis_not_the_census_basis(self, api,
                                                                             bursar_officer):
        """PRD §3.5: "Step one establishes the tier basis, a single enrollment
        count called *n*: if the section's `billing_basis_enrollment_count` is
        already set, *n* is that frozen number; otherwise *n* is the section's
        live `enrolled_count` as observed in this request."

        Design: Difficulty/dual_variant_calc/dual_variant_tier_basis_posting_snapshot_versus_census_date
        """
        scenario = _section_with_a_late_third_charge(api)

        charge3 = validate_success(
            api.get_charge(scenario["charge3"]["id"], bursar_officer)
        )

        # Three students are enrolled, but the frozen basis of 2 keeps band [1,2].
        assert_money(charge3["gross_price_cents"], 9450)
        assert_ratio(charge3["proration_pct"], 1.0000)
        assert_money(charge3["billed_amount_cents"], 9450)


class TestReconciliationMethodVariants:
    """One granted opt-out makes the two invoice methods diverge by 680 cents."""

    @staticmethod
    def _two_charges_with_one_granted_opt_out(api):
        scenario = fixtures.setup_billed_section(api, setup_clock="2026-07-01T00:00:00Z")
        fixtures.set_clock(api, "2026-09-02T10:00:00Z")
        request = fixtures.file_opt_out(
            api, scenario["charge_ids"][0], scenario["student_ids"][0], "OWNS_COPY"
        )
        fixtures.grant_opt_out(api, request["id"])
        scenario["agreement"] = fixtures.read_agreement(api, scenario["agreement_id"])
        scenario["agreement_version"] = scenario["agreement"]["version"]
        return scenario

    def test_enrollment_snapshot_invoices_only_the_still_billed_head(self, api,
                                                                    program_admin):
        """PRD §3.8: "The included set is every in-scope charge whose
        `billing_status` is `POSTED`, `PARTIALLY_REFUNDED` or `REBILLED`.
        `billable_count` is the size of that set, and `gross_invoice_cents` is
        the sum of the included charges' `publisher_share_cents`, each already
        rounded to whole cents per §2.6."

        Design: Difficulty/dual_variant_calc/dual_variant_reconciliation_enrollment_snapshot_versus_access_days_weighted
        """
        scenario = self._two_charges_with_one_granted_opt_out(api)

        run_a = validate_success(
            api.create_reconciliation_run(
                {
                    "agreement_id": scenario["agreement_id"],
                    "term_id": scenario["term_id"],
                    "method": "ENROLLMENT_SNAPSHOT",
                    "publisher_reported_count": 1,
                    "publisher_reported_amount_cents": 8316,
                    "expected_agreement_version": scenario["agreement_version"],
                },
                program_admin,
            ),
            expected_status=201,
        )

        assert run_a["billable_count"] == 1
        assert run_a["opted_out_count"] == 1
        assert_money(run_a["gross_invoice_cents"], 8316)
        # 8316 sits below the 16500-cent rebate threshold, so no rebate applies.
        assert_money(run_a["rebate_cents"], 0)
        assert_money(run_a["settlement_amount_cents"], 8316)
        assert_money(run_a["variance_cents"], 0)

    def test_access_days_weighted_invoices_the_days_access_actually_existed(self, api,
                                                                           program_admin):
        """PRD §3.8: "The consequence is the whole reason two methods exist: over
        identical stored data, whenever any opt-out was granted mid-window,
        `ACCESS_DAYS_WEIGHTED` yields a strictly larger `gross_invoice_cents`
        than `ENROLLMENT_SNAPSHOT`, because the publisher is paid for the days
        access actually existed rather than for the final enrollment picture."

        Design: Difficulty/dual_variant_calc/dual_variant_reconciliation_enrollment_snapshot_versus_access_days_weighted
        """
        scenario = self._two_charges_with_one_granted_opt_out(api)

        run_a = validate_success(
            api.create_reconciliation_run(
                {
                    "agreement_id": scenario["agreement_id"],
                    "term_id": scenario["term_id"],
                    "method": "ENROLLMENT_SNAPSHOT",
                    "publisher_reported_count": 1,
                    "publisher_reported_amount_cents": 8316,
                    "expected_agreement_version": scenario["agreement_version"],
                },
                program_admin,
            ),
            expected_status=201,
        )
        refreshed = fixtures.read_agreement(api, scenario["agreement_id"])

        run_b = validate_success(
            api.create_reconciliation_run(
                {
                    "agreement_id": scenario["agreement_id"],
                    "term_id": scenario["term_id"],
                    "method": "ACCESS_DAYS_WEIGHTED",
                    "publisher_reported_count": 2,
                    "publisher_reported_amount_cents": 8996,
                    "supersedes_run_id": run_a["id"],
                    "expected_agreement_version": refreshed["version"],
                },
                program_admin,
            ),
            expected_status=201,
        )

        # The refunded charge still earned 9 of 110 access days: weight 0.0818
        # against a reconstructed share of 8316 contributes 680 cents.
        assert run_b["billable_count"] == 2
        assert run_b["opted_out_count"] == 1
        assert_money(run_b["gross_invoice_cents"], 8996)
        assert (run_b["gross_invoice_cents"] - run_a["gross_invoice_cents"]) == 680
        assert_money(run_b["variance_cents"], 0)
        assert run_b["count_variance"] == 0

        superseded = fixtures.read_run(api, run_a["id"])
        assert superseded["status"] == ReconciliationRunStatus.SUPERSEDED.value

        agreement = fixtures.read_agreement(api, scenario["agreement_id"])
        assert agreement["reconciliation_status"] == ReconciliationStatus.COMPUTED.value
