"""Biennial reports: grid-cell uniqueness, derived dates, amendment loop,
provisional-vs-final fee variants, late penalties, and cascade recomputation."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, create_biennial_report_payload, review_report_payload,
    create_site, create_manifest_chain, set_clock,
    create_biennial_report, get_biennial_report, submit_biennial_report,
    create_container, get_site, get_container, get_manifest,
    confirm_manifest_return, setup_site_stream_areas,
    ehs_headers, wc_headers, ca_headers,
    assert_biennial_report, assert_instant_equals,
)


class TestReportGrid:
    def test_biennial_report_grid_cell_collision(self, api):
        """PRD §3.9: "only one report may exist per site per odd-year grid cell; a
        second report for the same `site_id` and `report_year` is
        `ERR_REPORT_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/biennial_report_grid_cell_collision
        """
        site_a = create_site("Site A", "EPA-SITE-A")
        site_b = create_site("Site B", "EPA-SITE-B")
        rep_a27 = create_biennial_report(site_a["id"], 2027)
        res = api.create_biennial_report(
            create_biennial_report_payload(site_a["id"], 2027), ehs_headers())
        validate_error(res, ApiErrorId.ERR_REPORT_PERIOD_OVERLAP)
        # Abutting grid cells and the same cell on another site do not collide.
        rep_a25 = create_biennial_report(site_a["id"], 2025)
        rep_b27 = create_biennial_report(site_b["id"], 2027)
        assert rep_a25["id"] != rep_a27["id"]
        assert rep_b27["id"] != rep_a27["id"]

    def test_biennial_report_derived_period_and_due_dates(self, api):
        """PRD §3.9: "The report's period runs from January 1 of `report_year`
        (inclusive, `period_start`) to January 1 of the following year (exclusive,
        `period_end`), and the filing deadline `due_at` is March 1 of that
        following year."

        Design: Difficulty/resource_temporal_overlap/biennial_report_grid_cell_collision
        """
        site = create_site()
        report = create_biennial_report(site["id"], 2027)
        assert_biennial_report(report)
        assert_instant_equals(report["period_start"], "2027-01-01T00:00:00Z",
                              "period_start")
        assert_instant_equals(report["period_end"], "2028-01-01T00:00:00Z",
                              "period_end")
        assert_instant_equals(report["due_at"], "2028-03-01T00:00:00Z", "due_at")

    def test_report_year_even_returns_not_odd(self, api):
        """PRD §3.9: "The year must be an odd integer — an even year is rejected
        with `ERR_REPORT_YEAR_NOT_ODD`".

        Design: Corner/validations/report_year_even_returns_not_odd
        """
        site = create_site()
        res = api.create_biennial_report(
            create_biennial_report_payload(site["id"], 2026), ehs_headers())
        validate_error(res, ApiErrorId.ERR_REPORT_YEAR_NOT_ODD)

    def test_biennial_reports_listing_pagination(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items
        to return; it defaults to 10 when not provided, and accepts values from a
        minimum of 1 up to a maximum of 100. The `offset` parameter specifies how
        many items to skip and defaults to 0." and "List responses carry the
        pagination fields `limit`, `offset`, `total_count`, and `has_more` inside
        the `meta` object of the response envelope."

        Design: Corner/entities/biennial_reports_listing_pagination
        """
        site = create_site()
        create_biennial_report(site["id"], 2025)
        create_biennial_report(site["id"], 2027)
        page1, meta1 = validate_paginated(api.list_biennial_reports(
            ehs_headers(), params={"site_id": site["id"], "limit": 1, "offset": 0}))
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert len(page1) == 1
        page2, meta2 = validate_paginated(api.list_biennial_reports(
            ehs_headers(), params={"site_id": site["id"], "limit": 1, "offset": 1}))
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False
        assert len(page2) == 1
        assert page1[0]["id"] != page2[0]["id"]


class TestAmendmentLoop:
    def test_biennial_report_amendment_loop(self, api):
        """PRD §3.9: "`ACCEPT` moves the report to the terminal state `ACCEPTED`,
        while `REJECT` sends it back to `DRAFT` for amendment, clearing
        `submitted_at` and leaving the provisional fee to be re-derived on the
        next category flip or manifest return." PRD §2.9: "an entity already in a
        terminal state (`RETIRED`, `EMPTIED`, `VOIDED`, `RETURNED`, `ACCEPTED`, or
        `REJECTED`) rejects every further transition with `ERR_ALREADY_TERMINAL`."

        Design: Corner/state_machines/biennial_report_amendment_loop
        """
        site = create_site()
        report = create_biennial_report(site["id"], 2027)
        validate_success(api.submit_biennial_report(report["id"], ehs_headers()))
        rejected = validate_success(api.review_biennial_report(
            report["id"], review_report_payload("REJECT"), ca_headers("aud-2")))
        assert rejected["status"] == "DRAFT"
        assert rejected["submitted_at"] is None
        validate_success(api.submit_biennial_report(report["id"], ehs_headers()))
        accepted = validate_success(api.review_biennial_report(
            report["id"], review_report_payload("ACCEPT"), ca_headers("aud-2")))
        assert accepted["status"] == "ACCEPTED"
        res = api.review_biennial_report(
            report["id"], review_report_payload("REJECT"), ca_headers("aud-2"))
        validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL)


class TestProvisionalVsFinalFee:
    def _setup_in_transit_report(self):
        """Clock 2027-01-10; LQG site (one 1000 kg central container); one
        IN_TRANSIT manifest (1000 kg, tonnage 10500); DRAFT report 2027."""
        set_clock("2027-01-10T00:00:00Z")
        env = create_manifest_chain(
            quantity_kg=1000.0, quantity_gallons=10, tracking_number="MT-100",
            coverage_from="2025-01-01T00:00:00Z",
            coverage_to="2028-01-01T00:00:00Z", through="IN_TRANSIT")
        report = create_biennial_report(env["site"]["id"], 2027)
        return env, report

    def test_provisional_fee_counts_in_transit_manifest(self, api):
        """PRD §3.9: "At creation the report computes its provisional picture:
        `provisional_shipped_kg` is the sum of `total_quantity_kg` over the site's
        manifests whose `shipped_at` falls within the period and whose status is
        any of `IN_TRANSIT`, `DELIVERED`, `DISCREPANCY_RAISED`, `RETURNED`,
        `EXCEPTION_REQUIRED`, or `EXCEPTION_REPORT_FILED`. The provisional fee,
        `provisional_fee_cents`, is the category base amount plus the sum of
        `tonnage_fee_cents` over that same provisional manifest set, with no late
        penalty ever applied while the report is a draft. The category base is
        read from `category_snapshot`, which captures the site's
        `generator_category` at the moment the fee is computed: 250000 cents for
        `LQG`, 100000 cents for `SQG`, 25000 cents for `VSQG`."

        Design: Difficulty/dual_variant_calc/biennial_fee_provisional_vs_final
        """
        env, report = self._setup_in_transit_report()
        assert report["status"] == "DRAFT"
        assert report["category_snapshot"] == "LQG", "January 2027 total 1000.0 kg"
        assert report["provisional_shipped_kg"] == 1000.0
        assert report["provisional_fee_cents"] == 260500, (
            "250000 LQG base + 10500 tonnage")

    def test_final_fee_counts_returned_manifests_only(self, api):
        """PRD §3.9: "At that moment `final_shipped_kg` is computed as the sum of
        `total_quantity_kg` over in-period manifests in `RETURNED` status only,
        and `final_fee_cents` is the category base plus the tonnage sum over that
        returned-only set plus a late penalty when `submitted_at` is strictly
        after `due_at`." On identical site data the two variants diverge: the
        in-transit manifest feeds the provisional picture but not the final one.

        Design: Difficulty/dual_variant_calc/biennial_fee_provisional_vs_final
        """
        env, report = self._setup_in_transit_report()
        submitted = submit_biennial_report(report["id"])
        assert submitted["status"] == "SUBMITTED"
        assert submitted["final_shipped_kg"] == 0.0, "nothing RETURNED yet"
        assert submitted["final_fee_cents"] == 250000, "base only, no late penalty"
        assert submitted["is_late"] is False
        assert submitted["days_late"] == 0
        assert get_manifest(env["manifest"]["id"])["status"] == "IN_TRANSIT", (
            "report submission does not move the manifest")


class TestTieredBaseAndLatePenalty:
    def _setup_late_return(self, submit_day):
        """Manifest for 2000.0 kg shipped 2025-06-01 (LQG month), swept to
        exception and returned late; clock then sits at `submit_day`."""
        set_clock("2025-06-01T00:00:00Z")
        env = create_manifest_chain(
            quantity_kg=2000.0, quantity_gallons=40, tracking_number="MT-300",
            coverage_from="2025-01-01T00:00:00Z",
            coverage_to="2028-01-01T00:00:00Z", through="IN_TRANSIT")
        set_clock(submit_day)  # sweep: manifest -> EXCEPTION_REQUIRED
        returned = confirm_manifest_return(env["manifest"]["id"])
        assert returned["is_return_late"] is True
        assert returned["status"] == "RETURNED"
        report = create_biennial_report(env["site"]["id"], 2025)
        return env, report

    def test_biennial_fee_tiered_base_plus_capped_late(self, api):
        """PRD §3.9: "`final_fee_cents` is the category base plus the tonnage sum
        over that returned-only set plus a late penalty when `submitted_at` is
        strictly after `due_at`. The penalty is 5000 cents per whole day late,
        capped at 150000 cents; `is_late` records whether the deadline was missed
        and `days_late` counts the whole days between `due_at` and `submitted_at`
        (zero when not late)."

        Design: Difficulty/combinatorial_formula/biennial_fee_tiered_base_plus_capped_late
        """
        env, report = self._setup_late_return("2026-08-01T00:00:00Z")
        # The June-2025 LQG month has rolled away: the snapshot reads VSQG.
        assert report["category_snapshot"] == "VSQG"
        assert report["provisional_shipped_kg"] == 2000.0
        assert report["provisional_fee_cents"] == 46000, "25000 + 21000, no late branch"
        submitted = submit_biennial_report(report["id"])
        assert submitted["is_late"] is True
        assert submitted["days_late"] == 153, "2026-03-01 -> 2026-08-01"
        assert submitted["final_shipped_kg"] == 2000.0
        assert submitted["final_fee_cents"] == 196000, (
            "25000 + 21000 + min(150000, 5000*153)")
        assert get_manifest(env["manifest"]["id"])["is_return_late"] is True

    def test_biennial_fee_late_penalty_below_cap(self, api):
        """PRD §3.9: "The penalty is 5000 cents per whole day late, capped at
        150000 cents". Ten days late accrues 50000 cents — under the cap, so the
        penalty is not truncated.

        Design: Difficulty/combinatorial_formula/biennial_fee_tiered_base_plus_capped_late
        """
        _, report = self._setup_late_return("2026-03-11T00:00:00Z")
        assert report["provisional_fee_cents"] == 46000
        submitted = submit_biennial_report(report["id"])
        assert submitted["is_late"] is True
        assert submitted["days_late"] == 10, "2026-03-01 -> 2026-03-11"
        assert submitted["final_fee_cents"] == 96000, "25000 + 21000 + 50000"


class TestCategoryFlipReportRecompute:
    def _setup_draft_report(self):
        """Clock 2027-01-05; site + ACTIVE stream + central area + DRAFT report
        2027 at the VSQG base with no manifests."""
        set_clock("2027-01-05T00:00:00Z")
        env = setup_site_stream_areas()
        report = create_biennial_report(env["site"]["id"], 2027)
        assert report["provisional_fee_cents"] == 25000
        assert report["category_snapshot"] == "VSQG"
        return env, report

    def test_container_create_cascades_to_draft_report_fee(self, api):
        """PRD §2.7: "When a container is created or voided, three hops follow in
        order: the site's monthly generation total moves (hop 1); the category is
        re-evaluated and flips on a threshold crossing (hop 2); and every `DRAFT`
        BiennialReport belonging to that site recomputes its provisional fee
        against the new category and the current manifest set (hop 3)."

        Design: Difficulty/transitive_cascade/container_create_category_flip_report_recompute
        """
        env, report = self._setup_draft_report()
        container = create_container(env["stream"]["id"], env["central"]["id"],
                                     10, 1000.0, "wc-1")
        site = get_site(env["site"]["id"])
        assert site["current_month_generated_kg"] == 1000.0  # hop 1
        assert site["generator_category"] == "LQG"           # hop 2
        refreshed = get_biennial_report(report["id"])        # hop 3
        assert refreshed["category_snapshot"] == "LQG"
        assert refreshed["provisional_fee_cents"] == 250000
        assert get_container(container["id"])["deadline_days"] == 90, (
            "created after the flip: LQG allowance")

    def test_container_void_cascades_downward_to_draft_report_fee(self, api):
        """PRD §3.3: "Voiding is a compensating reversal through the same
        three-hop cascade as creation: the month's total is decremented by the
        container's `quantity_kg` (only when the container was created in the
        site's current month), the category is re-evaluated and flips downward on
        a threshold crossing, every `DRAFT` BiennialReport of the site recomputes
        its provisional fee".

        Design: Difficulty/transitive_cascade/container_create_category_flip_report_recompute
        """
        env, report = self._setup_draft_report()
        container = create_container(env["stream"]["id"], env["central"]["id"],
                                     10, 1000.0, "wc-1")
        assert get_biennial_report(report["id"])["provisional_fee_cents"] == 250000
        validate_success(api.void_container(container["id"], wc_headers("wc-1")))
        site = get_site(env["site"]["id"])
        assert site["current_month_generated_kg"] == 0.0
        assert site["generator_category"] == "VSQG"
        refreshed = get_biennial_report(report["id"])
        assert refreshed["category_snapshot"] == "VSQG"
        assert refreshed["provisional_fee_cents"] == 25000
