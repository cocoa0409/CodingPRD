"""Vendor accuracy audits: dual accuracy variants, pooled rounding, period
overlap, fail threshold, the re-screen sweep, and rescreen dispatch rules."""
from test_helpers import (
    ApiErrorId,
    create_audit_payload,
    create_candidate_payload,
    create_order_payload,
    create_report_payload,
    finding,
    get_success_data,
    get_vendor_record,
    list_orders_filtered,
    make_candidate_headers,
    make_vendor_agent_headers,
    setup_screening_config,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

HR = TEST_USERS["hr_admin_headers"]
HM = TEST_USERS["hiring_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
AUD = TEST_USERS["auditor_headers"]

ADVERSE_FINDINGS = [finding()]


class TestAccuracyDualVariant:
    def _setup_two_audits(self, api):
        """Audit A (FINALIZED): sample 100, 1 mismatch. Audit B (DRAFT): sample
        50, 3 mismatches, adjacent period."""
        vendor = get_success_data(
            api.create_vendor(
                {"name": "V-DV2", "base_tat_business_hours": 40,
                 "max_concurrent_orders": 5, "surcharge_cents": 0},
                HR,
            )
        )
        audit_a = get_success_data(
            api.create_audit(
                create_audit_payload(
                    vendor["id"],
                    period_start="2026-01-01T00:00:00Z",
                    period_end="2026-02-01T00:00:00Z",
                    sample_size=100,
                    mismatches_found=1,
                ),
                AUD,
            )
        )
        get_success_data(api.finalize_audit(audit_a["id"], AUD))
        audit_b = get_success_data(
            api.create_audit(
                create_audit_payload(
                    vendor["id"],
                    period_start="2026-02-01T00:00:00Z",
                    period_end="2026-03-01T00:00:00Z",
                    sample_size=50,
                    mismatches_found=3,
                ),
                AUD,
            )
        )
        return vendor, audit_a, audit_b

    def test_finalized_and_including_draft_variants_diverge(self, api):
        """PRD section "Accuracy Audits and the Re-Screen Sweep": "The finalized
        variant, `accuracy_bps_finalized`, pools only `FINALIZED` audits ... The
        provisional variant, `accuracy_bps_including_draft`, pools `DRAFT` and
        `FINALIZED` audits together and diverges from the finalized variant
        whenever a draft audit exists" and "Both variants apply one formula:
        10000 times one minus the ratio of summed `mismatches_found` to summed
        `sample_size` across the variant's audit set, rounded half-up exactly
        once after pooling"."

        Design: Difficulty/dual_variant_calc/vendor_accuracy_finalized_vs_including_draft
        """
        vendor, _a, _b = self._setup_two_audits(api)
        vendor = get_vendor_record(vendor["id"], AUD)
        # Finalized only: 10000 * (1 - 1/100) = 9900.
        assert vendor["accuracy_bps_finalized"] == 9900
        # Including the draft: 10000 * (1 - 4/150) -> 9733.
        assert vendor["accuracy_bps_including_draft"] == 9733

    def test_draft_audit_excluded_from_finalized_variant(self, api):
        """PRD section "Accuracy Audits and the Re-Screen Sweep": "At creation
        the audit's `mismatch_rate_bps` is computed: the mismatch count divided
        by the sample size, scaled by 10000 basis points, rounded half-up." and
        "The finalized variant, `accuracy_bps_finalized`, pools only `FINALIZED`
        audits; it is the default view and the only input to probation and
        decertification decisions."

        Design: Difficulty/dual_variant_calc/vendor_accuracy_finalized_vs_including_draft
        """
        vendor, _a, audit_b = self._setup_two_audits(api)
        audit_b = get_success_data(api.get_audit(audit_b["id"], AUD))
        assert audit_b["status"] == "DRAFT"
        # 3/50 * 10000 = 600 bps on the draft audit itself...
        assert audit_b["mismatch_rate_bps"] == 600
        # ...yet the finalized variant ignores it.
        vendor = get_vendor_record(vendor["id"], AUD)
        assert vendor["accuracy_bps_finalized"] == 9900
        assert vendor["status"] == "ACTIVE"


class TestPooledRounding:
    def _setup_pooled(self, api):
        """Audit A (FINALIZED): sample 6, 1 mismatch. Audit B (FINALIZED):
        sample 4, 0 mismatches."""
        vendor = get_success_data(
            api.create_vendor(
                {"name": "V-CF2", "base_tat_business_hours": 40,
                 "max_concurrent_orders": 5, "surcharge_cents": 0},
                HR,
            )
        )
        audit_a = get_success_data(
            api.create_audit(
                create_audit_payload(
                    vendor["id"],
                    period_start="2026-01-01T00:00:00Z",
                    period_end="2026-02-01T00:00:00Z",
                    sample_size=6,
                    mismatches_found=1,
                ),
                AUD,
            )
        )
        get_success_data(api.finalize_audit(audit_a["id"], AUD))
        audit_b = get_success_data(
            api.create_audit(
                create_audit_payload(
                    vendor["id"],
                    period_start="2026-02-01T00:00:00Z",
                    period_end="2026-03-01T00:00:00Z",
                    sample_size=4,
                    mismatches_found=0,
                ),
                AUD,
            )
        )
        get_success_data(api.finalize_audit(audit_b["id"], AUD))
        return vendor, audit_a, audit_b

    def test_accuracy_pooled_then_rounded(self, api):
        """PRD section "Monetary Values, Precision, and Rounding": "Vendor
        accuracy is expressed as integer basis points with a single round-half-up
        applied after pooling; intermediate rounding of per-audit values before
        pooling is forbidden because it produces different results."

        Design: Difficulty/combinatorial_formula/accuracy_pooled_then_rounded_not_per_audit_average
        """
        vendor, _a, _b = self._setup_pooled(api)
        vendor = get_vendor_record(vendor["id"], AUD)
        # Pooled: round_half_up(10000 * (1 - 1/10)) = 9000. The forbidden
        # per-audit-rounded average would be (8333 + 10000) / 2 = 9167.
        assert vendor["accuracy_bps_finalized"] == 9000
        assert vendor["accuracy_bps_finalized"] != 9167

    def test_single_failing_audit_triggers_probation(self, api):
        """PRD section "Accuracy Audits and the Re-Screen Sweep": "Failure is
        strictly threshold-based: a `mismatch_rate_bps` strictly greater than
        200 fails; exactly 200 passes. A failing audit against an `ACTIVE`
        vendor moves the vendor to `PROBATION`"."

        Design: Difficulty/combinatorial_formula/accuracy_pooled_then_rounded_not_per_audit_average
        """
        vendor, audit_a, _b = self._setup_pooled(api)
        # Audit A alone: round_half_up(1/6 * 10000) = 1667 bps > 200 -> failed.
        audit_a = get_success_data(api.get_audit(audit_a["id"], AUD))
        assert audit_a["mismatch_rate_bps"] == 1667
        vendor = get_vendor_record(vendor["id"], AUD)
        assert vendor["status"] == "PROBATION"


class TestAuditShapeAndOverlap:
    def test_audit_shape_validation(self, api):
        """PRD section "Validation Ordering": "Fifth, request shape: required
        fields present, enum members valid, and structural constraints such as
        `mismatches_found` not exceeding `sample_size`, `period_end` strictly
        after `period_start`" — all rejected as `ERR_INVALID_REQUEST` (HTTP
        400).

        Design: Corner/validations/audit_shape_validation
        """
        vendor = get_success_data(
            api.create_vendor(
                {"name": "V-VL6", "base_tat_business_hours": 40,
                 "max_concurrent_orders": 5},
                HR,
            )
        )
        resp1 = api.create_audit(
            create_audit_payload(vendor["id"], sample_size=5, mismatches_found=6),
            AUD,
        )
        validate_error(resp1, ApiErrorId.ERR_INVALID_REQUEST)

        resp2 = api.create_audit(
            create_audit_payload(
                vendor["id"],
                period_start="2026-02-01T00:00:00Z",
                period_end="2026-01-01T00:00:00Z",
            ),
            AUD,
        )
        validate_error(resp2, ApiErrorId.ERR_INVALID_REQUEST)

    def test_overlapping_period_rejected(self, api):
        """PRD section "Accuracy Audits and the Re-Screen Sweep": "Two audits
        for the same vendor may not overlap: a new half-open interval intersects
        an existing one whenever the new start falls before the existing end and
        the new end falls after the existing start, and any such intersection is
        rejected with `ERR_AUDIT_PERIOD_OVERLAP`"."

        Design: Difficulty/resource_temporal_overlap/audit_period_half_open_adjacency
        """
        vendor = get_success_data(
            api.create_vendor(
                {"name": "V-TO1", "base_tat_business_hours": 40,
                 "max_concurrent_orders": 5},
                HR,
            )
        )
        get_success_data(
            api.create_audit(
                create_audit_payload(
                    vendor["id"],
                    period_start="2026-01-01T00:00:00Z",
                    period_end="2026-02-01T00:00:00Z",
                    sample_size=50,
                    mismatches_found=1,
                ),
                AUD,
            )
        )
        resp = api.create_audit(
            create_audit_payload(
                vendor["id"],
                period_start="2026-01-15T00:00:00Z",
                period_end="2026-02-15T00:00:00Z",
            ),
            AUD,
        )
        validate_error(resp, ApiErrorId.ERR_AUDIT_PERIOD_OVERLAP)

    def test_adjacent_period_accepted_and_other_vendor_unaffected(self, api):
        """PRD section "Accuracy Audits and the Re-Screen Sweep": "pure
        adjacency, where one audit's end equals the next's start, is allowed."
        and "Two audits for the same vendor may not overlap"."

        Design: Difficulty/resource_temporal_overlap/audit_period_half_open_adjacency
        """
        vendor = get_success_data(
            api.create_vendor(
                {"name": "V-TO1B", "base_tat_business_hours": 40,
                 "max_concurrent_orders": 5},
                HR,
            )
        )
        other = get_success_data(
            api.create_vendor(
                {"name": "V-TO1C", "base_tat_business_hours": 40,
                 "max_concurrent_orders": 5},
                HR,
            )
        )
        get_success_data(
            api.create_audit(
                create_audit_payload(
                    vendor["id"],
                    period_start="2026-01-01T00:00:00Z",
                    period_end="2026-02-01T00:00:00Z",
                    sample_size=50,
                    mismatches_found=1,
                ),
                AUD,
            )
        )
        # Adjacency: new start == existing end.
        adjacent = validate_success(
            api.create_audit(
                create_audit_payload(
                    vendor["id"],
                    period_start="2026-02-01T00:00:00Z",
                    period_end="2026-03-01T00:00:00Z",
                ),
                AUD,
            ),
            expected_status=201,
        )
        assert adjacent["status"] == "DRAFT"

        # Overlap is evaluated only against audits of the SAME vendor.
        other_vendor = validate_success(
            api.create_audit(
                create_audit_payload(
                    other["id"],
                    period_start="2026-01-15T00:00:00Z",
                    period_end="2026-02-15T00:00:00Z",
                ),
                AUD,
            ),
            expected_status=201,
        )
        assert other_vendor["vendor_id"] == other["id"]


class TestFailThresholdBoundary:
    def test_exactly_200bps_passes(self, api):
        """PRD section "Accuracy Audits and the Re-Screen Sweep": "Failure is
        strictly threshold-based: a `mismatch_rate_bps` strictly greater than
        200 fails; exactly 200 passes." and "The audit's `rescreen_order_ids`
        collects the created order ids in creation order, defaulting to an empty
        array when the sweep selects nothing or the audit passes."

        Design: Difficulty/boundary_precision_check/audit_fail_threshold_exact_200bps
        """
        vendor = get_success_data(
            api.create_vendor(
                {"name": "V-BP3", "base_tat_business_hours": 40,
                 "max_concurrent_orders": 5},
                HR,
            )
        )
        audit = get_success_data(
            api.create_audit(
                create_audit_payload(
                    vendor["id"], sample_size=50, mismatches_found=1
                ),
                AUD,
            )
        )
        # 1/50 * 10000 = exactly 200 bps: passes (not strictly greater).
        assert audit["mismatch_rate_bps"] == 200
        finalized = validate_success(api.finalize_audit(audit["id"], AUD))
        assert finalized["status"] == "FINALIZED"
        assert finalized["rescreen_order_ids"] == []
        vendor = get_vendor_record(vendor["id"], AUD)
        assert vendor["status"] == "ACTIVE"

    def test_300bps_fails_and_moves_vendor_to_probation(self, api):
        """PRD section "Accuracy Audits and the Re-Screen Sweep": "A failing
        audit against an `ACTIVE` vendor moves the vendor to `PROBATION`" and
        "Both variants apply one formula: 10000 times one minus the ratio of
        summed `mismatches_found` to summed `sample_size` across the variant's
        audit set, rounded half-up exactly once after pooling"."

        Design: Difficulty/boundary_precision_check/audit_fail_threshold_exact_200bps
        """
        vendor = get_success_data(
            api.create_vendor(
                {"name": "V-BP3B", "base_tat_business_hours": 40,
                 "max_concurrent_orders": 5},
                HR,
            )
        )
        passing = get_success_data(
            api.create_audit(
                create_audit_payload(
                    vendor["id"], sample_size=50, mismatches_found=1
                ),
                AUD,
            )
        )
        get_success_data(api.finalize_audit(passing["id"], AUD))
        failing = get_success_data(
            api.create_audit(
                create_audit_payload(
                    vendor["id"],
                    period_start="2026-02-01T00:00:00Z",
                    period_end="2026-03-01T00:00:00Z",
                    sample_size=100,
                    mismatches_found=3,
                ),
                AUD,
            )
        )
        # 3/100 * 10000 = 300 bps > 200: fails.
        assert failing["mismatch_rate_bps"] == 300
        validate_success(api.finalize_audit(failing["id"], AUD))
        vendor = get_vendor_record(vendor["id"], AUD)
        assert vendor["status"] == "PROBATION"
        # Pooled over both finalized audits: 10000 * (1 - 4/150) -> 9733.
        assert vendor["accuracy_bps_finalized"] == 9733


class TestRescreenSweep:
    def _setup_sweep_scenario(self, api):
        """Three orders on one vendor, delivered at the window start, window
        end, and just past the window; then a failing July audit."""
        ctx = setup_screening_config(
            tag="TO2", vendor_overrides={"max_concurrent_orders": 10}
        )
        candidates = []
        orders = []
        get_success_data(api.set_clock("2026-06-29T10:00:00Z"))
        for name, email in (
            ("To A", "to2a@x.com"), ("To B", "to2b@x.com"), ("To C", "to2c@x.com")
        ):
            cand = get_success_data(
                api.create_candidate(
                    create_candidate_payload(full_name=name, email=email), HR
                )
            )
            order = get_success_data(
                api.create_order(
                    create_order_payload(cand["id"], ctx["position"]["id"]), HM
                )
            )
            get_success_data(
                api.capture_consent(
                    order["id"],
                    {
                        "disclosure_form_id": "DISC-1",
                        "contains_extraneous_terms": False,
                        "authorization_signed_at": "2026-06-29T09:00:00Z",
                    },
                    make_candidate_headers(cand["id"]),
                )
            )
            get_success_data(
                api.dispatch_order(order["id"], ctx["vendor"]["id"], HM)
            )
            candidates.append(cand)
            orders.append(order)
        reports = []
        for delivered_at, order in zip(
            ("2026-07-01T00:00:00Z", "2026-07-31T23:59:59Z", "2026-08-01T00:00:00Z"),
            orders,
        ):
            get_success_data(api.set_clock(delivered_at))
            reports.append(
                get_success_data(
                    api.create_report(
                        create_report_payload(
                            order["id"], findings=list(ADVERSE_FINDINGS)
                        ),
                        make_vendor_agent_headers(ctx["vendor"]["id"]),
                    )
                )
            )
        audit = get_success_data(
            api.create_audit(
                create_audit_payload(
                    ctx["vendor"]["id"],
                    period_start="2026-07-01T00:00:00Z",
                    period_end="2026-07-31T23:59:59Z",
                    sample_size=10,
                    mismatches_found=1,
                ),
                AUD,
            )
        )
        return ctx, candidates, orders, reports, audit

    def test_sweep_window_is_closed_on_both_ends(self, api):
        """PRD section "Accuracy Audits and the Re-Screen Sweep": "The sweep
        selects every report by this vendor whose status is `DELIVERED`, whose
        `delivered_at` falls within the closed interval from `period_start`
        through `period_end` inclusive on both ends, whose order's fulfillment
        is `REPORT_RECEIVED`, and whose order's `recommended_outcome` is
        `IA_REQUIRED` or `ADVERSE_ELIGIBLE`." and "The audit's
        `rescreen_order_ids` collects the created order ids in creation order"."

        Design: Difficulty/resource_temporal_overlap/rescreen_sweep_closed_interval_inclusion
        """
        ctx, _cands, orders, reports, audit = self._setup_sweep_scenario(api)
        finalized = validate_success(api.finalize_audit(audit["id"], AUD))

        rs1, _ = list_orders_filtered(AUD, rescreen_of_order_id=orders[0]["id"])
        rs2, _ = list_orders_filtered(AUD, rescreen_of_order_id=orders[1]["id"])
        rs3, _ = list_orders_filtered(AUD, rescreen_of_order_id=orders[2]["id"])
        assert len(rs1) == 1
        assert len(rs2) == 1
        # 2026-08-01T00:00:00Z is past the closed window: no rescreen.
        assert rs3 == []
        # delivered_at ascending: boundary report (07-01) before 07-31 report.
        assert finalized["rescreen_order_ids"] == [rs1[0]["id"], rs2[0]["id"]]

    def test_sweep_creates_rescreen_orders_and_probates_vendor(self, api):
        """PRD section "Accuracy Audits and the Re-Screen Sweep": "the sweep
        creates a new screening order: `order_type` `RESCREEN`,
        `rescreen_of_order_id` pointing at the original order, `candidate_id`
        and `position_id` copied, fulfillment starting at `CONSENT_CAPTURED`"
        and "A failing audit against an `ACTIVE` vendor moves the vendor to
        `PROBATION`"."

        Design: Difficulty/resource_temporal_overlap/rescreen_sweep_closed_interval_inclusion
        """
        ctx, candidates, orders, _reports, audit = self._setup_sweep_scenario(api)
        validate_success(api.finalize_audit(audit["id"], AUD))

        rs1, _ = list_orders_filtered(AUD, rescreen_of_order_id=orders[0]["id"])
        rescreen = rs1[0]
        assert rescreen["order_type"] == "RESCREEN"
        assert rescreen["rescreen_of_order_id"] == orders[0]["id"]
        assert rescreen["candidate_id"] == candidates[0]["id"]
        assert rescreen["position_id"] == ctx["position"]["id"]
        assert rescreen["fulfillment_status"] == "CONSENT_CAPTURED"

        vendor = get_vendor_record(ctx["vendor"]["id"], AUD)
        assert vendor["status"] == "PROBATION"


class TestRescreenDispatchVendorGuard:
    def test_rescreen_order_cannot_dispatch_to_audited_vendor(self, api):
        """PRD section "Dispatch, the SLA Clock, and Vendor Capacity":
        "Rescreening orders carry one further guard: the target vendor must
        differ from the original order's vendor, because sending the re-screen
        back to the audited vendor defeats the audit's purpose; violations are
        rejected with `ERR_RESCREEN_SAME_VENDOR` (HTTP 422)." and "For a
        `RESCREEN` order, no new consent record is ever created — consent is
        inherited"."

        Design: Corner/validations/rescreen_order_cannot_dispatch_to_audited_vendor
        """
        ctx = setup_screening_config(tag="VL12")
        vendor2 = get_success_data(
            api.create_vendor(
                {"name": "V-VL12-B", "base_tat_business_hours": 40,
                 "max_concurrent_orders": 5},
                HR,
            )
        )
        candidate = get_success_data(
            api.create_candidate(
                create_candidate_payload(full_name="Vl Twelve", email="vl12@x.com"),
                HR,
            )
        )
        get_success_data(api.set_clock("2026-07-14T09:00:00Z"))
        order = get_success_data(
            api.create_order(
                create_order_payload(candidate["id"], ctx["position"]["id"]), HM
            )
        )
        get_success_data(
            api.capture_consent(
                order["id"],
                {
                    "disclosure_form_id": "DISC-1",
                    "contains_extraneous_terms": False,
                    "authorization_signed_at": "2026-07-14T09:00:00Z",
                },
                make_candidate_headers(candidate["id"]),
            )
        )
        get_success_data(api.dispatch_order(order["id"], ctx["vendor"]["id"], HM))
        get_success_data(api.set_clock("2026-07-15T10:00:00Z"))
        get_success_data(
            api.create_report(
                create_report_payload(order["id"], findings=list(ADVERSE_FINDINGS)),
                make_vendor_agent_headers(ctx["vendor"]["id"]),
            )
        )
        audit = get_success_data(
            api.create_audit(
                create_audit_payload(
                    ctx["vendor"]["id"],
                    period_start="2026-07-01T00:00:00Z",
                    period_end="2026-07-31T23:59:59Z",
                    sample_size=10,
                    mismatches_found=1,
                ),
                AUD,
            )
        )
        get_success_data(api.finalize_audit(audit["id"], AUD))
        rescreen_list, _ = list_orders_filtered(AUD, rescreen_of_order_id=order["id"])
        assert len(rescreen_list) == 1
        rescreen = rescreen_list[0]

        # Isolate the rescreen-vendor guard from the vendor-status gate:
        # reinstate the audited (now PROBATION) vendor first.
        get_success_data(api.reinstate_vendor(ctx["vendor"]["id"], CO))

        resp = api.dispatch_order(rescreen["id"], ctx["vendor"]["id"], HM)
        validate_error(resp, ApiErrorId.ERR_RESCREEN_SAME_VENDOR)

        # Dispatch to a different vendor succeeds: consent is inherited from the
        # original order, so no new consent record is needed.
        dispatched = validate_success(
            api.dispatch_order(rescreen["id"], vendor2["id"], HM)
        )
        assert dispatched["fulfillment_status"] == "DISPATCHED"
        assert dispatched["vendor_id"] == vendor2["id"]
        rescreen_now, _ = list_orders_filtered(
            AUD, rescreen_of_order_id=order["id"]
        )
        assert [o["id"] for o in rescreen_now] == [rescreen["id"]]


class TestAuditListingPagination:
    def test_list_pagination_defaults_and_envelope(self, api):
        """PRD section "Pagination": "List endpoints accept two query
        parameters: `limit`, the maximum number of items returned, defaulting to
        10 with a minimum of 1 and a maximum of 100; and `offset`, the number of
        items skipped, defaulting to 0." and "The `meta` envelope of a list
        response carries `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/list_pagination_defaults_and_envelope
        """
        vendor = get_success_data(
            api.create_vendor(
                {"name": "V-EP1", "base_tat_business_hours": 40,
                 "max_concurrent_orders": 5},
                HR,
            )
        )
        # Eleven audits over adjacent monthly periods in 2025.
        months = [
            ("2025-01-01T00:00:00Z", "2025-02-01T00:00:00Z"),
            ("2025-02-01T00:00:00Z", "2025-03-01T00:00:00Z"),
            ("2025-03-01T00:00:00Z", "2025-04-01T00:00:00Z"),
            ("2025-04-01T00:00:00Z", "2025-05-01T00:00:00Z"),
            ("2025-05-01T00:00:00Z", "2025-06-01T00:00:00Z"),
            ("2025-06-01T00:00:00Z", "2025-07-01T00:00:00Z"),
            ("2025-07-01T00:00:00Z", "2025-08-01T00:00:00Z"),
            ("2025-08-01T00:00:00Z", "2025-09-01T00:00:00Z"),
            ("2025-09-01T00:00:00Z", "2025-10-01T00:00:00Z"),
            ("2025-10-01T00:00:00Z", "2025-11-01T00:00:00Z"),
            ("2025-11-01T00:00:00Z", "2025-12-01T00:00:00Z"),
        ]
        for start, end in months:
            get_success_data(
                api.create_audit(
                    create_audit_payload(
                        vendor["id"], period_start=start, period_end=end,
                        sample_size=10, mismatches_found=0,
                    ),
                    AUD,
                )
            )

        page1, meta1 = validate_paginated(
            api.list_audits(AUD, params={"vendor_id": vendor["id"]})
        )
        assert len(page1) == 10
        assert meta1["total_count"] == 11
        assert meta1["has_more"] is True
        assert meta1["limit"] == 10
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_audits(AUD, params={"vendor_id": vendor["id"], "offset": 10})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 11
        assert meta2["has_more"] is False
