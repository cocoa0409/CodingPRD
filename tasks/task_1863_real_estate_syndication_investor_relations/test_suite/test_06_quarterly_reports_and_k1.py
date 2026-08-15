"""Quarterly reports: distributable-cash formula, future-period guard,
slot uniqueness, distribution locking; and the dual-variant K-1 allocation."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_distribution,
    create_quarterly_report_payload,
    get_k1_package,
    get_quarterly_report,
    make_calculated_distribution,
    make_k1_package,
    make_open_offering,
    make_active_syndication,
    make_published_report,
    set_clock,
    setup_funded_offering,
    validate_error,
    validate_success,
)

SPONSOR = TEST_USERS["sponsor_operator_headers"]


class TestDistributableCash:
    def test_quarterly_distributable_cash_formula(self, api):
        """PRD §3.5: "Publication stamps `published_at` and computes the
        quarter's `distributable_cash_cents`: the `noi_cents` minus a reserve
        withholding of ten percent of NOI and a debt-service withholding of
        thirty percent of NOI, each withholding rounded half-up to a whole cent
        before subtraction, and the result floored at zero."
        NOI 10,000,000 -> 10,000,000 - 1,000,000 - 3,000,000 = 6,000,000.

        Design: Corner/calculations/quarterly_distributable_cash_formula
        """
        syn = make_active_syndication(syndication_name="CalcSyn")
        off = make_open_offering(syn["id"], offering_name="Calc Off")
        report = validate_success(api.create_quarterly_report(
            syn["id"], off["id"],
            create_quarterly_report_payload(report_year=2026, report_quarter=1,
                                            noi_cents=10_000_000,
                                            occupancy_pct=0.95),
            SPONSOR), 201)
        published = validate_success(api.publish_quarterly_report(
            syn["id"], off["id"], report["id"], SPONSOR))
        assert published["status"] == "PUBLISHED"
        assert published["distributable_cash_cents"] == 6_000_000, (
            f"distributable_cash_cents must be 6000000, "
            f"got {published['distributable_cash_cents']}")
        assert published["published_at"], "published_at must be stamped"


class TestFutureReportPeriod:
    def test_future_quarterly_report_rejected(self, api, sponsor_operator_headers):
        """PRD §3.5: "Neither at creation nor at publish time may the report's
        year and quarter lie in the future relative to the current logical time
        — a future period is rejected with `ERR_FUTURE_REPORT_PERIOD`."
        With the logical clock at 2026-04-15, Q4 2026 lies in the future.

        Design: Corner/validations/future_quarterly_report_rejected
        """
        syn = make_active_syndication(syndication_name="FpSyn")
        off = make_open_offering(syn["id"], offering_name="Fp Off")
        set_clock("2026-04-15T00:00:00Z")
        resp = api.create_quarterly_report(
            syn["id"], off["id"],
            create_quarterly_report_payload(report_year=2026, report_quarter=4,
                                            noi_cents=1_000_000,
                                            occupancy_pct=0.95),
            sponsor_operator_headers)
        validate_error(resp, ApiErrorId.ERR_FUTURE_REPORT_PERIOD, 422)


class TestReportSlotUniqueness:
    def test_duplicate_quarterly_report_slot_rejected(self, api):
        """PRD §3.5: "Publishing additionally requires the offering to be
        `OPEN`, `CLOSED_TO_NEW_SUBSCRIPTIONS`, or `FINAL_CLOSE`
        (`ERR_OFFERING_NOT_PUBLISHABLE`), and forbids a second `PUBLISHED`
        report for the same offering, year, and quarter
        (`ERR_DUPLICATE_QUARTERLY_REPORT`)."

        Design: Difficulty/resource_temporal_overlap/quarterly_report_slot_uniqueness_per_period
        """
        syn = make_active_syndication(syndication_name="QsSyn")
        off = make_open_offering(syn["id"], offering_name="Qs Off")
        first = make_published_report(syn["id"], off["id"], report_year=2026,
                                      report_quarter=1, noi_cents=5_000_000)
        assert first["status"] == "PUBLISHED"
        second = validate_success(api.create_quarterly_report(
            syn["id"], off["id"],
            create_quarterly_report_payload(report_year=2026, report_quarter=1,
                                            noi_cents=6_000_000,
                                            occupancy_pct=0.96),
            SPONSOR), 201)
        resp = api.publish_quarterly_report(syn["id"], off["id"], second["id"],
                                            SPONSOR)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_QUARTERLY_REPORT, 409)
        assert get_quarterly_report(syn["id"], off["id"],
                                    second["id"])["status"] == "DRAFT"

    def test_adjacent_period_report_publishes(self, api):
        """PRD §3.5: the prohibition is on "a second `PUBLISHED` report for the
        same offering, year, and quarter (`ERR_DUPLICATE_QUARTERLY_REPORT`)" —
        a different (year, quarter) slot is a different period and publishes
        freely alongside.

        Design: Difficulty/resource_temporal_overlap/quarterly_report_slot_uniqueness_per_period
        """
        syn = make_active_syndication(syndication_name="QsSyn2")
        off = make_open_offering(syn["id"], offering_name="Qs Off 2")
        first = make_published_report(syn["id"], off["id"], report_year=2026,
                                      report_quarter=1, noi_cents=5_000_000)
        assert first["status"] == "PUBLISHED"
        other = make_published_report(syn["id"], off["id"], report_year=2025,
                                      report_quarter=4, noi_cents=6_000_000)
        assert other["status"] == "PUBLISHED", (
            "a different (year, quarter) slot must publish alongside")


class TestReportLockedByDistribution:
    def test_report_locked_by_approved_distribution(self, api):
        """PRD §3.5: "A published report can be amended, moving it to
        `AMENDED`, but only while no distribution referencing it has reached
        `APPROVED` or `PAID` — a locked report rejects the amendment with
        `ERR_REPORT_LOCKED_BY_DISTRIBUTION`."

        Design: Corner/errors/error_report_locked_by_distribution
        """
        ctx = setup_funded_offering([5_000_000])
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        report = make_published_report(syn_id, off_id, report_year=2026,
                                       report_quarter=1, noi_cents=10_000_000)
        dist = make_calculated_distribution(
            syn_id, off_id, "QUARTERLY_OPERATING", 1_000_000,
            quarterly_report_id=report["id"])
        approve_distribution(syn_id, off_id, dist["id"])

        resp = api.amend_quarterly_report(syn_id, off_id, report["id"], SPONSOR)
        validate_error(resp, ApiErrorId.ERR_REPORT_LOCKED_BY_DISTRIBUTION, 409)


class TestK1DualVariant:
    def _k1_setup(self):
        """Three FUNDED subscriptions ($30K/$30K/$40K) and a PUBLISHED Q1-2026
        report with noi_cents=100001; K-1 package for tax year 2026 in
        PREPARATION. Subscriptions are funded at 2026-01-01; the clock then
        advances to 2026-05-01 so the Q1 period is unambiguously past before
        publication."""
        ctx = setup_funded_offering([3_000_000, 3_000_000, 4_000_000],
                                    fund_at="2026-01-01T00:00:00Z")
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        set_clock("2026-05-01T00:00:00Z")
        make_published_report(syn_id, off_id, report_year=2026, report_quarter=1,
                              noi_cents=100_001)
        pkg = make_k1_package(syn_id, off_id, tax_year=2026)
        return ctx, pkg

    def test_k1_provisional_map_no_reconciliation(self, api):
        """PRD §3.7: "The offering's NOI for the year is the sum of `noi_cents`
        across all quarterly reports on the offering that are `PUBLISHED` or
        `AMENDED` and whose `report_year` equals the package's `tax_year`. Each
        `FUNDED` subscription — ordered by `funded_at` ascending, ties broken
        by `created_at` — receives a provisional share equal to that annual NOI
        multiplied by the subscription's `funded_cents` and divided by the
        total `funded_cents` across all funded subscriptions snapshotted at
        year-end, rounded half-up to a whole cent per line. The provisional map
        runs no reconciliation pass: the per-line rounding means the mapped
        values may drift a few cents from the annual NOI, and that drift is
        accepted because the numbers are for review only."
        NOI 100,001 over funded 3M/3M/4M of 10M -> 30,000 / 30,000 / 40,000
        (sum 100,000 drifts 1c below the NOI, unreconciled).

        Design: Difficulty/dual_variant_calc/k1_provisional_vs_final_reconciliation
        """
        ctx, pkg = self._k1_setup()
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        sub_a, sub_b, sub_c = ctx["subs"]

        reviewed = validate_success(api.submit_k1_for_review(
            syn_id, off_id, pkg["id"], SPONSOR))
        assert reviewed["status"] == "PARTNER_REVIEW"
        draft = reviewed["draft_k1_cents_by_subscription"]
        assert draft[sub_a["id"]] == 30_000
        assert draft[sub_b["id"]] == 30_000
        assert draft[sub_c["id"]] == 40_000
        assert sum(draft.values()) == 100_000, (
            "provisional map runs no reconciliation pass; the 1c drift stands")

    def test_k1_final_map_reconciles_to_noi(self, api):
        """PRD §3.7: "Finalization moves the package from `PARTNER_REVIEW` to
        `FINALIZED` and computes `final_k1_cents_by_subscription` from exactly
        the same inputs — same annual NOI, same funded positions at year-end —
        but with one difference: after each line is rounded half-up
        individually, a largest-remainder reconciliation forces the final map
        to sum exactly to the annual NOI. The signed difference between the
        annual NOI and the sum of the rounded lines is allocated to the single
        line belonging to the subscription with the largest `funded_cents`,
        ties broken by the earliest subscription `created_at`. The draft map is
        left untouched at finalization, frozen so the delta between provisional
        and final remains auditable".

        Design: Difficulty/dual_variant_calc/k1_provisional_vs_final_reconciliation
        """
        ctx, pkg = self._k1_setup()
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        sub_a, sub_b, sub_c = ctx["subs"]
        reviewed = validate_success(api.submit_k1_for_review(
            syn_id, off_id, pkg["id"], SPONSOR))
        draft_before = dict(reviewed["draft_k1_cents_by_subscription"])

        finalized = validate_success(api.finalize_k1_package(
            syn_id, off_id, pkg["id"], SPONSOR))
        assert finalized["status"] == "FINALIZED"
        final = finalized["final_k1_cents_by_subscription"]
        assert final[sub_a["id"]] == 30_000
        assert final[sub_b["id"]] == 30_000
        # +1c reconciliation lands on C, the largest funded position.
        assert final[sub_c["id"]] == 40_001, (
            f"largest-remainder +1c must land on the largest line (C): "
            f"got {final[sub_c['id']]}")
        assert sum(final.values()) == 100_001, (
            "final map must sum exactly to the annual NOI")
        # The draft map is frozen for the delta audit.
        after = get_k1_package(syn_id, off_id, pkg["id"])
        assert after["draft_k1_cents_by_subscription"] == draft_before
