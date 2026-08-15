"""Completion reporting: dual variants, rounding order, k-anonymity
suppression, eligibility filtering, recognition tiers, OCC on publish, and
immediate read-after-write consistency (PRD §2.8, §2.10, §3.10)."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    REVIEWER,
    add_aid_record,
    add_report_senior,
    add_senior,
    add_school,
    create_event,
    enroll_school,
    find_row,
    fresh_senior,
    generate_report,
    get_campaign,
    get_checklist_for_senior,
    grant_consent,
    propose_link,
    publish_event,
    publish_report,
    setup_campaign_with_school,
    setup_dual_variant_scenario,
    setup_language_rate_scenario,
    setup_recognition_scenario,
    validate_error,
    validate_success,
)


class TestReportVariants:
    def test_submission_based_counts_intent_to_file(self, api):
        """PRD §3.10: "Completion depends on the variant: `SUBMISSION_BASED`
        counts a senior whose `fafsa_status` is `SUBMITTED`,
        `VERIFICATION_SELECTED`, or `COMPLETE` — intent to file is enough —
        while `PROCESSED_BASED` counts only `COMPLETE`, fully processed
        filings."
        PRD §3.10: "A senior counts as eligible for a report when all three
        hold: the senior's `match_status` is `MATCHED`; a `GRANTED` consent
        carrying the `DATA_SHARE` scope exists for the senior; and the senior's
        school is `ENROLLED`."

        Design: Difficulty/dual_variant_calc/completion_rate_submission_vs_processed_variants
        """
        campaign, _school = setup_dual_variant_scenario()
        report = generate_report(campaign, "SUBMISSION_BASED")
        assert report["eligible_count"] == 3
        assert report["completed_count"] == 3, (
            "COMPLETE + VERIFICATION_SELECTED + SUBMITTED all count as intent "
            "to file"
        )
        assert report["overall_rate"] == pytest.approx(100.0, abs=1e-9)

    def test_processed_based_counts_only_complete(self, api):
        """PRD §3.10: "`PROCESSED_BASED` counts only `COMPLETE`, fully
        processed filings" — on identical data the variants diverge: 3
        completions by submission, 1 by processing, and `overall_rate` is
        "derived from those totals by the same multiply-round-divide recipe".

        Design: Difficulty/dual_variant_calc/completion_rate_submission_vs_processed_variants
        """
        campaign, _school = setup_dual_variant_scenario()
        sub = generate_report(campaign, "SUBMISSION_BASED")
        proc = generate_report(campaign, "PROCESSED_BASED")
        assert proc["eligible_count"] == 3
        assert proc["completed_count"] == 1
        assert proc["overall_rate"] == pytest.approx(33.3, abs=0.01), (
            f"1/3 rounds half-up to 33.3, got {proc['overall_rate']}"
        )
        assert sub["completed_count"] != proc["completed_count"]


class TestReportRoundingOrder:
    def test_row_rates_round_half_up_to_one_decimal(self, api):
        """PRD §3.10: each surviving row carries "a `rate` computed as the
        row's completed count divided by its eligible count, multiplied by
        1000, rounded half-up, then divided by 10 — yielding a one-decimal
        percentage."

        Design: Difficulty/combinatorial_formula/report_rate_rounding_order_totals_not_row_average
        """
        campaign, _school = setup_language_rate_scenario()
        report = generate_report(campaign, "SUBMISSION_BASED")
        assert report["eligible_count"] == 11
        assert report["completed_count"] == 2

        en = find_row(report, "LANGUAGE", "en")
        assert en is not None and en["eligible_count"] == 5
        assert en["completed_count"] == 1
        assert en["rate"] == pytest.approx(20.0, abs=1e-9)

        es = find_row(report, "LANGUAGE", "es")
        assert es is not None and es["eligible_count"] == 6
        assert es["completed_count"] == 1
        assert es["rate"] == pytest.approx(16.7, abs=1e-9), (
            f"166.66... rounds half-up to 16.7, got {es['rate']}"
        )

    def test_overall_rate_comes_from_totals_not_row_average(self, api):
        """PRD §3.10: "The rounding order is pinned: the overall rate always
        comes from the totals, never from averaging the rounded row rates." —
        totals-first yields 18.2 (2/11); the rounded average of the rounded
        row rates would wrongly give 18.4.

        Design: Difficulty/combinatorial_formula/report_rate_rounding_order_totals_not_row_average
        """
        campaign, _school = setup_language_rate_scenario()
        report = generate_report(campaign, "SUBMISSION_BASED")
        assert report["overall_rate"] == pytest.approx(18.2, abs=1e-9), (
            f"2/11 -> 181.81 -> 18.2 from totals; got {report['overall_rate']}"
        )
        assert abs(report["overall_rate"] - 18.4) > 0.05, (
            "18.4 would mean the implementation averaged rounded row rates"
        )


class TestSubgroupSuppression:
    def _setup(self, api):
        campaign, school = setup_campaign_with_school(
            campaign_overrides={"min_subgroup_size": 2}
        )
        # LANGUAGE/en at exactly the floor (2); LANGUAGE/es one below (1).
        add_report_senior(
            campaign, school, student_ref="E1", full_name="En One",
            dob="2009-01-01", home_language="en", aid_status="STARTED",
        )
        add_report_senior(
            campaign, school, student_ref="E2", full_name="En Two",
            dob="2009-01-02", home_language="en", aid_status="STARTED",
        )
        add_report_senior(
            campaign, school, student_ref="E3", full_name="Es One",
            dob="2009-02-01", home_language="es", aid_status="STARTED",
        )
        return campaign

    def test_row_at_exact_floor_survives_and_row_below_is_suppressed(self, api):
        """PRD §3.10: "Privacy suppression is strict less-than: a row whose
        `eligible_count` is below the campaign's `min_subgroup_size` is omitted
        from `rows` entirely, while a row exactly at the floor survives."

        Design: Difficulty/boundary_precision_check/report_subgroup_exact_suppression_threshold
        """
        campaign = self._setup(api)
        report = generate_report(campaign, "SUBMISSION_BASED")
        en = find_row(report, "LANGUAGE", "en")
        assert en is not None and en["eligible_count"] == 2, (
            "2 == min_subgroup_size 2: the row at the floor must survive"
        )
        assert find_row(report, "LANGUAGE", "es") is None, (
            "1 < 2: the sub-floor row must be omitted from rows entirely"
        )

    def test_suppressed_students_still_count_in_totals(self, api):
        """PRD §3.10: "Campaign-wide totals are computed from unsuppressed data
        — suppressed students still count in the totals".

        Design: Difficulty/boundary_precision_check/report_subgroup_exact_suppression_threshold
        """
        campaign = self._setup(api)
        report = generate_report(campaign, "SUBMISSION_BASED")
        assert report["eligible_count"] == 3, (
            "the suppressed es senior must still count in campaign totals"
        )


class TestReportInputSet:
    def test_unmatched_unconsented_and_suspended_seniors_excluded(self, api):
        """PRD §3.10: "A senior counts as eligible for a report when all three
        hold: the senior's `match_status` is `MATCHED`; a `GRANTED` consent
        carrying the `DATA_SHARE` scope exists for the senior; and the senior's
        school is `ENROLLED`."

        Design: Corner/calculations/report_input_set_excludes_unmatched_unconsented_suspended
        """
        campaign, school_a = setup_campaign_with_school(
            campaign_overrides={"min_subgroup_size": 1, "name": "C27"},
            school_overrides={"name": "A HS"},
        )
        school_b = enroll_school(
            add_school(
                campaign, name="B HS", district_code="D02", school_code="SC0B"
            )
        )
        # (a) matched + DATA_SHARE: the only eligible senior.
        add_report_senior(
            campaign, school_a, student_ref="A", full_name="Ann A",
            dob="2009-01-01", aid_status="SUBMITTED", scopes=["DATA_SHARE"],
        )
        # (b) matched but consent without DATA_SHARE: ineligible.
        add_report_senior(
            campaign, school_a, student_ref="B", full_name="Bob B",
            dob="2009-01-02", aid_status="SUBMITTED", scopes=["STATUS_DETAIL"],
        )
        # (c) consented but UNMATCHED: ineligible.
        senior_c = add_senior(
            school_a, student_ref="C", full_name="Cat C", dob="2009-01-03"
        )
        grant_consent(school_a, senior_c["id"], ["DATA_SHARE"])
        # (d) matched + DATA_SHARE but school SUSPENDED: ineligible.
        add_report_senior(
            campaign, school_b, student_ref="D", full_name="Dan D",
            dob="2009-01-04", aid_status="SUBMITTED", scopes=["DATA_SHARE"],
        )
        api.suspend_school(school_b["id"], ADMIN)

        report = generate_report(campaign, "SUBMISSION_BASED")
        assert report["eligible_count"] == 1, (
            f"only senior (a) survives all three filters, got "
            f"{report['eligible_count']}"
        )
        assert report["completed_count"] == 1
        assert report["overall_rate"] == pytest.approx(100.0, abs=1e-9)


class TestRecognitionTiers:
    def test_top_of_distribution_takes_gold_with_inclusive_boundary(self, api):
        """PRD §3.10: "Third, the pool's rates are sorted ascending, and two
        cutoffs are read by nearest-rank: the gold cutoff is the value at the
        one-based index of the pool size multiplied by 0.70 rounded up, and the
        silver cutoff is the value at the one-based index of the pool size
        multiplied by 0.40 rounded up. Finally each ranked school takes `GOLD`
        when its rate is at least the gold cutoff, `SILVER` when at least the
        silver cutoff, and `BRONZE` otherwise — boundaries are inclusive, so a
        rate exactly equal to a cutoff takes the higher tier."

        Design: Difficulty/combinatorial_formula/recognition_tier_percentile_cutoff_self_reference
        """
        ctx = setup_recognition_scenario()
        report = generate_report(ctx["campaign"], "SUBMISSION_BASED")
        publish_report(ctx["campaign"]["id"], report["id"])

        # Ascending rates [25, 50, 75, 100], N=4: c70 = index ceil(2.8) = 3
        # -> 75.0.
        resp = api.get_school(ctx["schools"]["A"]["id"], ADMIN)
        assert validate_success(resp, 200)["recognition_tier"] == "GOLD"
        resp = api.get_school(ctx["schools"]["B"]["id"], ADMIN)
        assert validate_success(resp, 200)["recognition_tier"] == "GOLD", (
            "school B's 75.0 equals the gold cutoff 75.0 — the inclusive "
            "boundary takes the higher tier"
        )

    def test_silver_boundary_and_bronze_below(self, api):
        """PRD §3.10: "the silver cutoff is the value at the one-based index of
        the pool size multiplied by 0.40 rounded up" — with ascending rates
        [25, 50, 75, 100] that is index ceil(1.6) = 2 -> 50.0, and "boundaries
        are inclusive, so a rate exactly equal to a cutoff takes the higher
        tier."

        Design: Difficulty/combinatorial_formula/recognition_tier_percentile_cutoff_self_reference
        """
        ctx = setup_recognition_scenario()
        report = generate_report(ctx["campaign"], "SUBMISSION_BASED")
        publish_report(ctx["campaign"]["id"], report["id"])

        resp = api.get_school(ctx["schools"]["C"]["id"], ADMIN)
        assert validate_success(resp, 200)["recognition_tier"] == "SILVER", (
            "school C's 50.0 equals the silver cutoff 50.0 — SILVER"
        )
        resp = api.get_school(ctx["schools"]["D"]["id"], ADMIN)
        assert validate_success(resp, 200)["recognition_tier"] == "BRONZE", (
            "school D's 25.0 is below the silver cutoff — BRONZE"
        )


class TestReportPublishOcc:
    def test_stale_campaign_version_rejected_then_fresh_publish_succeeds(self, api):
        """PRD §2.8: "Publishing a completion report requires the client to
        send `expected_campaign_version` carrying the `version` of the campaign
        as last observed." — and "a mismatch between the supplied value and the
        campaign's current `version` is likewise rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.7: "On success, the campaign's `committed_budget_cents` rises by
        the estimate, and the campaign's `version` increments" — an intervening
        event publish is exactly such an increment.

        Design: Corner/complexity_layers/occ_report_publish_stale_campaign_version
        """
        campaign, school = setup_campaign_with_school()
        report = generate_report(campaign, "SUBMISSION_BASED")
        stale_version = get_campaign(campaign["id"])["version"]

        # An event publish advances Campaign.version past the captured value.
        event = create_event(school, title="E1")
        publish_event(school, event["id"])

        resp = api.publish_completion_report(report["id"], stale_version, ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412

        resp = api.get_completion_report(report["id"], ADMIN)
        assert validate_success(resp, 200)["status"] == "GENERATED", (
            "the 412 must not change the report"
        )

        fresh_version = get_campaign(campaign["id"])["version"]
        resp = api.publish_completion_report(report["id"], fresh_version, ADMIN)
        assert validate_success(resp, 200)["status"] == "PUBLISHED"


class TestImmediateConsistency:
    def test_confirm_effects_visible_immediately(self, api):
        """PRD §2.10: "Every such secondary mutation is a real mutation of the
        affected resource: its `updated_at` refreshes and its `version`
        increments." — computed counters and budget fields "are reconciled
        immediately and exactly at each triggering event — never lazily, never
        approximately".
        PRD §3.5: "the reviewer may confirm it, moving the link from
        `SUGGESTED` to `CONFIRMED` and firing the identical matched cascade".

        Design: Corner/consistency_model/immediate_read_after_write_consistency
        """
        campaign, school = setup_campaign_with_school()
        senior = add_senior(school)
        grant_consent(school, senior["id"], ["STATUS_DETAIL"])
        aid = add_aid_record(
            campaign,
            external_ref="E1",
            full_name="Ana Lee",
            dob="2009-03-04",
            school_code="SC99",
            district_code="D01",
            initial_status="SUBMITTED",
            effective_date="2027-01-10",
        )
        senior = fresh_senior(senior["id"])
        link = propose_link(senior["id"], aid["id"], expected_version=senior["version"])
        assert link["status"] == "SUGGESTED"

        resp = api.confirm_match_link(link["id"], REVIEWER)
        assert validate_success(resp, 200)["status"] == "CONFIRMED"

        # The very next reads observe the full cascade: no staleness window.
        senior = fresh_senior(senior["id"])
        assert senior["match_status"] == "MATCHED"
        assert senior["current_match_link_id"] == link["id"]
        checklist = get_checklist_for_senior(senior["id"])
        assert checklist["status"] == "GENERATED"
