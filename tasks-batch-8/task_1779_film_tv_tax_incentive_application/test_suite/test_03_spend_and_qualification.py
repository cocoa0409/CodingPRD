"""Spend recording, vendor residency gates, qualified totals, and the credit
pipeline's system-sum computations."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_qualified_entries,
    add_spend_entry,
    approve_application,
    claim_application,
    create_application,
    create_production,
    create_spend_entry_payload,
    disqualify_entry,
    get_application,
    make_producer_headers,
    open_program,
    qualify_entry,
    register_company,
    register_vendor,
    register_verified_vendor,
    review_vendor,
    setup_approved_application,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
REVIEWER1 = TEST_USERS["reviewer1_headers"]


def _approved_with_vendor(api, estimated=250_000_000, **production_overrides):
    scenario = setup_approved_application(
        estimated_qualified_spend_cents=estimated, **production_overrides)
    vendor = register_verified_vendor(scenario.production, scenario.company)
    scenario.vendor = vendor
    return scenario


class TestSpendEntryCreateShape:
    def test_spend_entry_default_is_resident_labor_false(self, api):
        """PRD §3.4: "Recording a **SpendEntry** takes the `application_id`, the
        `vendor_id`, an `external_invoice_ref` identifying the vendor's invoice,
        a `category` of `ATL` (above the line) or `BTL` (below the line), the
        `spend_date` on which the cost was incurred, and a positive
        `amount_cents`; an optional `is_resident_labor` flag defaults to false,
        and an optional `amends_entry_id` supports correction by amendment."
        PRD §3.4: "Every other qualified entry's `effective_amount_cents` equals
        its `amount_cents`."

        Design: Corner/entities/spend_entry_default_is_resident_labor_false
        """
        scenario = _approved_with_vendor(api)
        entry = add_spend_entry(scenario.application, scenario.vendor,
                                scenario.company, category="BTL",
                                amount_cents=100_000_000)
        assert entry["is_resident_labor"] is False, (
            "omitting is_resident_labor defaults it to false")
        qualified = qualify_entry(entry)
        assert qualified["effective_amount_cents"] == 100_000_000, (
            "no resident uplift applies when the flag defaulted to false")

    def test_spend_entry_missing_required_amount_returns_invalid_request(self, api):
        """PRD §2.9: "13. **Request shape** — required fields present, enums
        valid, amounts positive, date ranges coherent, conditional fields
        present, and no unknown payload fields (`ERR_INVALID_REQUEST`)."
        PRD §3.4: "Recording a **SpendEntry** takes the `application_id`, the
        `vendor_id`, an `external_invoice_ref` identifying the vendor's invoice,
        a `category` of `ATL` (above the line) or `BTL` (below the line), the
        `spend_date` on which the cost was incurred, and a positive
        `amount_cents`"

        Design: Corner/entities/spend_entry_missing_required_amount_returns_invalid_request
        """
        scenario = _approved_with_vendor(api)
        payload = create_spend_entry_payload(
            scenario.application["id"], scenario.vendor["id"])
        del payload["amount_cents"]
        resp = api.create_spend_entry(
            payload, make_producer_headers(scenario.company["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_computed_field_input_rejected(self, api):
        """PRD §2.9: "13. **Request shape** — required fields present, enums
        valid, amounts positive, date ranges coherent, conditional fields
        present, and no unknown payload fields (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/computed_field_input_rejected
        """
        scenario = _approved_with_vendor(api)
        payload = create_spend_entry_payload(
            scenario.application["id"], scenario.vendor["id"],
            amount_cents=1000)
        payload["effective_amount_cents"] = 999999
        resp = api.create_spend_entry(
            payload, make_producer_headers(scenario.company["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestSpendEntryCoherence:
    def test_vendor_production_mismatch_rejected(self, api):
        """PRD §3.4: "Two coherence guards protect the ledger: the named vendor
        must belong to the same production as the application
        (`ERR_VENDOR_PRODUCTION_MISMATCH`)"

        Design: Corner/validations/vendor_production_mismatch_rejected
        """
        scenario = setup_approved_application()
        other_production = create_production(
            scenario.company, title="Okefenokee Nights", production_type="SERIES",
            total_budget_cents=200_000_000)
        foreign_vendor = register_vendor(other_production, scenario.company)

        resp = api.create_spend_entry(
            create_spend_entry_payload(scenario.application["id"],
                                       foreign_vendor["id"]),
            make_producer_headers(scenario.company["id"]))
        validate_error(resp, ApiErrorId.ERR_VENDOR_PRODUCTION_MISMATCH)
        data, _ = validate_paginated(api.list_spend_entries(
            REVIEWER1, params={"application_id": scenario.application["id"]}))
        assert data == [], "no entry may be persisted on a coherence failure"

    def test_duplicate_invoice_across_jurisdictions_rejected(self, api):
        """PRD §3.4: "the `external_invoice_ref` must not already appear on any
        non-`SUPERSEDED` spend entry of the same production — across all of that
        production's applications, in every jurisdiction
        (`ERR_DUPLICATE_SPEND_INVOICE`). This per-production invoice uniqueness
        is the structural double-count guard that makes multi-jurisdiction
        filing safe (§3.9)."

        Design: Corner/validations/duplicate_invoice_across_jurisdictions_rejected
        """
        program_ga = open_program()
        program_nm = open_program(
            jurisdiction_code="NM", program_name="NM Film Credit FY27",
            annual_cap_cents=50_000_000, minimum_qualified_spend_cents=5_000_000,
            elevated_tier_threshold_cents=100_000_000)
        company = register_company()
        production = create_production(company, title="Split State Shoot")
        app_ga = create_application(production, program_ga,
                                    estimated_qualified_spend_cents=150_000_000)
        app_nm = create_application(production, program_nm,
                                    estimated_qualified_spend_cents=100_000_000)
        for app in (app_ga, app_nm):
            submit_application(app, company)
            claim_application(app)
        app_ga = approve_application(app_ga)
        app_nm = approve_application(app_nm)
        vendor = register_verified_vendor(
            production, company, legal_name="Regional Grip Services")

        add_spend_entry(app_ga, vendor, company,
                        external_invoice_ref="INV-DUP-001",
                        amount_cents=1_000_000)
        resp = api.create_spend_entry(
            create_spend_entry_payload(app_nm["id"], vendor["id"],
                                       external_invoice_ref="INV-DUP-001",
                                       amount_cents=2_000_000,
                                       spend_date="2026-10-06T00:00:00Z"),
            make_producer_headers(company["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SPEND_INVOICE)
        data, _ = validate_paginated(api.list_spend_entries(
            REVIEWER1, params={"application_id": app_nm["id"]}))
        assert data == [], "the same invoice cannot feed two jurisdictions"

    def test_amendment_target_mismatch_rejected(self, api):
        """PRD §3.4: "When `amends_entry_id` is present on a new entry, the
        referenced entry must belong to the same application and stand in
        `PENDING_REVIEW`, `QUALIFIED`, or `DISQUALIFIED` — a missing,
        cross-application, or already-`SUPERSEDED` target is rejected with
        `ERR_AMENDMENT_TARGET_MISMATCH`. The target atomically becomes
        `SUPERSEDED`, which is terminal, and the new entry replaces it in
        `PENDING_REVIEW`."

        Design: Corner/validations/amendment_target_mismatch_rejected
        """
        scenario = _approved_with_vendor(api)
        e1 = add_spend_entry(scenario.application, scenario.vendor,
                             scenario.company, amount_cents=1_000_000)
        e2 = add_spend_entry(scenario.application, scenario.vendor,
                             scenario.company, amount_cents=1_500_000,
                             amends_entry_id=e1["id"])
        superseded = validate_success(
            api.get_spend_entry(e1["id"], REVIEWER1), 200)
        assert superseded["status"] == "SUPERSEDED"
        assert e2["status"] == "PENDING_REVIEW"

        resp = api.create_spend_entry(
            create_spend_entry_payload(scenario.application["id"],
                                       scenario.vendor["id"],
                                       amount_cents=1_600_000,
                                       amends_entry_id=e1["id"]),
            make_producer_headers(scenario.company["id"]))
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_TARGET_MISMATCH)


class TestVendorResidencyGate:
    def test_qualify_blocked_while_vendor_unverified(self, api):
        """PRD §3.4: "Qualifying an entry out of `PENDING_REVIEW` first requires
        the application to be `APPROVED` or `CREDIT_ISSUED`
        (`ERR_INVALID_STATE_TRANSITION`), then requires the vendor's
        `residency_status` to be `VERIFIED`
        (`ERR_VENDOR_RESIDENCY_NOT_VERIFIED`)"

        Design: Difficulty/cross_entity_state_dependency/spend_qualify_requires_vendor_verified
        """
        scenario = setup_approved_application()
        vendor = register_vendor(scenario.production, scenario.company)
        entry = add_spend_entry(scenario.application, vendor, scenario.company,
                                category="BTL", is_resident_labor=True,
                                spend_date="2026-10-12T00:00:00Z",
                                amount_cents=100_000_000)

        resp = api.review_spend_entry(entry["id"], {"decision": "QUALIFY"},
                                      REVIEWER1)
        validate_error(resp, ApiErrorId.ERR_VENDOR_RESIDENCY_NOT_VERIFIED)
        current = validate_success(api.get_spend_entry(entry["id"], REVIEWER1), 200)
        assert current["status"] == "PENDING_REVIEW"

    def test_qualify_unblocked_after_vendor_verified(self, api):
        """PRD §3.4: "Qualifying an entry out of `PENDING_REVIEW` first requires
        the application to be `APPROVED` or `CREDIT_ISSUED`
        (`ERR_INVALID_STATE_TRANSITION`), then requires the vendor's
        `residency_status` to be `VERIFIED`
        (`ERR_VENDOR_RESIDENCY_NOT_VERIFIED`)"
        PRD §3.4: "For a `BTL` entry flagged `is_resident_labor` whose vendor
        stood `VERIFIED` at review time, `effective_amount_cents` is the entry's
        `amount_cents` plus that amount multiplied by the program's
        `resident_uplift_pct`, with the uplift rounded half up to whole cents per
        entry before any summation."

        Design: Difficulty/cross_entity_state_dependency/spend_qualify_requires_vendor_verified
        """
        scenario = setup_approved_application()
        vendor = register_vendor(scenario.production, scenario.company)
        entry = add_spend_entry(scenario.application, vendor, scenario.company,
                                category="BTL", is_resident_labor=True,
                                spend_date="2026-10-12T00:00:00Z",
                                amount_cents=100_000_000)

        review_vendor(vendor, "VERIFIED")
        resp = api.review_spend_entry(entry["id"], {"decision": "QUALIFY"},
                                      REVIEWER1)
        qualified = validate_success(resp, 200)
        assert qualified["status"] == "QUALIFIED"
        assert qualified["effective_amount_cents"] == 102_500_000, (
            "the resident uplift applies once the vendor stands VERIFIED")
        application = get_application(scenario.application)
        assert application["btl_qualified_cents"] == 102_500_000


class TestVerificationWindow:
    def _setup_window_entries(self, api):
        """Vendor VERIFIED at the default clock (2026-08-01) with a 365-day
        validity window; entry X dated at the window start, entry Y dated at
        the exclusive window end."""
        scenario = _approved_with_vendor(api)
        entry_start = add_spend_entry(
            scenario.application, scenario.vendor, scenario.company,
            category="BTL", spend_date="2026-08-01T00:00:00Z",
            amount_cents=5_000_000)
        entry_end = add_spend_entry(
            scenario.application, scenario.vendor, scenario.company,
            category="BTL", spend_date="2027-08-01T00:00:00Z",
            amount_cents=5_000_000)
        return scenario, entry_start, entry_end

    def test_spend_date_at_window_start_qualifies(self, api):
        """PRD §3.4: "and finally requires the `spend_date` to fall inside the
        vendor's verification validity window — on or after the vendor's
        `verified_at` and strictly before the instant the program's
        `vendor_verification_validity_days` days after `verified_at` — evaluated
        against the application's program (`ERR_VERIFICATION_WINDOW_EXPIRED`)"

        Design: Difficulty/resource_temporal_overlap/vendor_verification_point_containment
        """
        scenario, entry_start, _entry_end = self._setup_window_entries(api)
        resp = api.review_spend_entry(entry_start["id"], {"decision": "QUALIFY"},
                                      REVIEWER1)
        qualified = validate_success(resp, 200)
        assert qualified["status"] == "QUALIFIED", (
            "spend_date == verified_at (window start) is inside the window")
        assert qualified["effective_amount_cents"] == 5_000_000

    def test_spend_date_at_window_end_rejected(self, api):
        """PRD §3.4: "and finally requires the `spend_date` to fall inside the
        vendor's verification validity window — on or after the vendor's
        `verified_at` and strictly before the instant the program's
        `vendor_verification_validity_days` days after `verified_at` — evaluated
        against the application's program (`ERR_VERIFICATION_WINDOW_EXPIRED`)"

        Design: Difficulty/resource_temporal_overlap/vendor_verification_point_containment
        """
        scenario, entry_start, entry_end = self._setup_window_entries(api)
        qualify_entry(entry_start)
        resp = api.review_spend_entry(entry_end["id"], {"decision": "QUALIFY"},
                                      REVIEWER1)
        validate_error(resp, ApiErrorId.ERR_VERIFICATION_WINDOW_EXPIRED)
        current = validate_success(api.get_spend_entry(entry_end["id"], REVIEWER1), 200)
        assert current["status"] == "PENDING_REVIEW", (
            "spend_date == verified_at + validity days is outside (exclusive end)")
        application = get_application(scenario.application)
        assert application["btl_qualified_cents"] == 5_000_000, (
            "only the in-window entry counts toward the totals")


class TestUpliftRoundingOrder:
    def _setup_two_resident_entries(self, api):
        scenario = _approved_with_vendor(
            api, estimated=20_000_000, title="Shorts Program",
            production_type="COMMERCIAL", total_budget_cents=50_000_000)
        e1 = add_spend_entry(scenario.application, scenario.vendor,
                             scenario.company, category="BTL",
                             is_resident_labor=True,
                             spend_date="2026-10-05T00:00:00Z", amount_cents=101)
        e2 = add_spend_entry(scenario.application, scenario.vendor,
                             scenario.company, category="BTL",
                             is_resident_labor=True,
                             spend_date="2026-10-06T00:00:00Z", amount_cents=101)
        return scenario, e1, e2

    def test_per_entry_effective_amount_rounds_half_up(self, api):
        """PRD §3.4: "For a `BTL` entry flagged `is_resident_labor` whose vendor
        stood `VERIFIED` at review time, `effective_amount_cents` is the entry's
        `amount_cents` plus that amount multiplied by the program's
        `resident_uplift_pct`, with the uplift rounded half up to whole cents per
        entry before any summation."

        Design: Difficulty/combinatorial_formula/per_entry_uplift_rounding_order
        """
        _scenario, e1, e2 = self._setup_two_resident_entries(api)
        q1 = qualify_entry(e1)
        q2 = qualify_entry(e2)
        assert q1["effective_amount_cents"] == 104, (
            "101 + round_half_up(101 * 0.025) = 101 + 3")
        assert q2["effective_amount_cents"] == 104

    def test_category_total_uses_per_entry_rounding_not_sum_then_round(self, api):
        """PRD §2.6: "First, the resident-labor uplift is rounded half up per
        spend entry before any summation; summing raw amounts first and rounding
        once at the category level is a different, non-conformant result."

        Design: Difficulty/combinatorial_formula/per_entry_uplift_rounding_order
        """
        scenario, e1, e2 = self._setup_two_resident_entries(api)
        qualify_entry(e1)
        qualify_entry(e2)
        application = get_application(scenario.application)
        assert application["btl_qualified_cents"] == 208, (
            "per-entry rounding yields 104 + 104 = 208, not the "
            "sum-then-round 207")
        assert application["capped_total_qualified_cents"] == 208


class TestTierThresholdStraddle:
    def _setup_straddle(self, api):
        """Two applications on one program: app A qualifies BTL 199,999,999
        (threshold-1), app B qualifies BTL 200,000,000 (threshold, inclusive)."""
        program = open_program()
        company = register_company()
        production_a = create_production(company, title="Atlantic Crossing")
        production_b = create_production(company, title="Okefenokee Nights")
        app_a = create_application(production_a, program)
        app_b = create_application(production_b, program)
        for app in (app_a, app_b):
            submit_application(app, company)
            claim_application(app)
        app_a = approve_application(app_a)
        app_b = approve_application(app_b)
        vendor_a = register_verified_vendor(production_a, company)
        vendor_b = register_verified_vendor(
            production_b, company, legal_name="Columbus Camera Rental")
        entry_a = add_spend_entry(app_a, vendor_a, company, category="BTL",
                                  amount_cents=199_999_999)
        entry_b = add_spend_entry(app_b, vendor_b, company, category="BTL",
                                  amount_cents=200_000_000)
        qualify_entry(entry_a)
        qualify_entry(entry_b)
        return app_a, app_b

    def test_one_cent_below_threshold_earns_standard_rate(self, api):
        """PRD §3.9: "select the tier on the post-cap total, where a capped total
        of at least the program's `elevated_tier_threshold_cents` — boundary
        inclusive — earns `base_rate_elevated` and anything below it earns
        `base_rate_standard`; and compute the credit as the capped total
        multiplied by the selected rate, rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/tiered_credit_rate_threshold_straddle
        """
        app_a, _app_b = self._setup_straddle(api)
        estimate = validate_success(api.get_credit_estimate(
            app_a["id"], REVIEWER1, params={"variant": "PROVISIONAL"}), 200)
        assert estimate["capped_total_qualified_cents"] == 199_999_999
        assert estimate["applied_rate"] == 0.25
        assert estimate["credit_cents"] == 50_000_000, (
            "round_half_up(199999999 * 0.25)")
        assert estimate["meets_minimum"] is True

    def test_exact_threshold_earns_elevated_rate(self, api):
        """PRD §3.9: "select the tier on the post-cap total, where a capped total
        of at least the program's `elevated_tier_threshold_cents` — boundary
        inclusive — earns `base_rate_elevated` and anything below it earns
        `base_rate_standard`; and compute the credit as the capped total
        multiplied by the selected rate, rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/tiered_credit_rate_threshold_straddle
        """
        _app_a, app_b = self._setup_straddle(api)
        estimate = validate_success(api.get_credit_estimate(
            app_b["id"], REVIEWER1, params={"variant": "PROVISIONAL"}), 200)
        assert estimate["capped_total_qualified_cents"] == 200_000_000
        assert estimate["applied_rate"] == 0.30, (
            "the tier boundary is inclusive")
        assert estimate["credit_cents"] == 60_000_000
        assert estimate["meets_minimum"] is True


class TestAtlCapPinnedOrder:
    def _setup_atl_heavy(self, api):
        """ATL 150,000,000 (non-labor) + BTL resident 50,000,000 (effective
        51,250,000): the ATL cap binds at floor(0.40 * 201,250,000)."""
        scenario = _approved_with_vendor(api, title="Star Vehicles")
        entries = add_qualified_entries(
            scenario.application, scenario.vendor, scenario.company,
            [
                {"category": "ATL", "amount_cents": 150_000_000,
                 "spend_date": "2026-10-05T00:00:00Z"},
                {"category": "BTL", "is_resident_labor": True,
                 "amount_cents": 50_000_000,
                 "spend_date": "2026-10-12T00:00:00Z"},
            ])
        scenario.entries = entries
        return scenario

    def test_atl_cap_applies_to_pre_cap_total_and_binds(self, api):
        """PRD §3.4: "First, the pre-cap total is the raw ATL sum plus the raw
        BTL sum. Second, the ATL cap in cents is the program's `atl_cap_pct`
        multiplied by that pre-cap total, rounded down to whole cents. Third, the
        capped ATL is the lesser of the raw ATL sum and the cap. Finally,
        `capped_total_qualified_cents` is the capped ATL plus the full BTL sum."

        Design: Difficulty/combinatorial_formula/atl_cap_pinned_evaluation_order
        """
        scenario = self._setup_atl_heavy(api)
        application = get_application(scenario.application)
        assert application["atl_qualified_cents"] == 150_000_000, (
            "the raw ATL sum is kept on the application")
        assert application["btl_qualified_cents"] == 51_250_000
        assert application["capped_total_qualified_cents"] == 131_750_000, (
            "min(150000000, floor(0.40 * 201250000)) + 51250000 "
            "= 80500000 + 51250000")

    def test_atl_cap_pulls_credit_below_elevated_tier(self, api):
        """PRD §3.4: "BTL is never capped, the cap base is always the raw sums —
        never the capped ATL — and rounding the cap half up instead of down is
        non-conformant."
        PRD §3.9: "select the tier on the post-cap total, where a capped total of
        at least the program's `elevated_tier_threshold_cents` — boundary
        inclusive — earns `base_rate_elevated` and anything below it earns
        `base_rate_standard`; and compute the credit as the capped total
        multiplied by the selected rate, rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/atl_cap_pinned_evaluation_order
        """
        scenario = self._setup_atl_heavy(api)
        estimate = validate_success(api.get_credit_estimate(
            scenario.application["id"], REVIEWER1,
            params={"variant": "PROVISIONAL"}), 200)
        assert estimate["capped_total_qualified_cents"] == 131_750_000
        assert estimate["applied_rate"] == 0.25, (
            "the capped total falls below the elevated tier")
        assert estimate["credit_cents"] == 32_937_500


class TestQualifiedInputSet:
    def test_provisional_totals_exclude_pending_disqualified_superseded(self, api):
        """PRD §3.4: "`atl_qualified_cents` is the sum of
        `effective_amount_cents` over the application's `QUALIFIED` `ATL`
        entries, and `btl_qualified_cents` the same sum over `BTL` entries;
        entries in any other status never contribute."

        Design: Corner/calculations/provisional_totals_exclude_pending_disqualified_superseded
        """
        scenario = _approved_with_vendor(api)
        app, vendor, company = (scenario.application, scenario.vendor,
                                scenario.company)
        e1 = add_spend_entry(app, vendor, company, category="BTL",
                             spend_date="2026-10-05T00:00:00Z",
                             amount_cents=10_000_000)
        e2 = add_spend_entry(app, vendor, company, category="BTL",
                             spend_date="2026-10-06T00:00:00Z",
                             amount_cents=20_000_000)
        e3 = add_spend_entry(app, vendor, company, category="BTL",
                             spend_date="2026-10-07T00:00:00Z",
                             amount_cents=30_000_000)
        e4 = add_spend_entry(app, vendor, company, category="BTL",
                             spend_date="2026-10-08T00:00:00Z",
                             amount_cents=40_000_000)
        qualify_entry(e1)
        disqualify_entry(e3, reason="missing invoice")
        e5 = add_spend_entry(app, vendor, company, category="BTL",
                             spend_date="2026-10-08T00:00:00Z",
                             amount_cents=50_000_000, amends_entry_id=e4["id"])
        qualify_entry(e5)

        application = get_application(app)
        assert application["btl_qualified_cents"] == 60_000_000, (
            "only the QUALIFIED non-superseded E1 (10M) and E5 (50M) count")
        assert application["capped_total_qualified_cents"] == 60_000_000
        assert application["provisional_credit_cents"] == 15_000_000

        e4_now = validate_success(api.get_spend_entry(e4["id"], REVIEWER1), 200)
        assert e4_now["status"] == "SUPERSEDED"
        e2_now = validate_success(api.get_spend_entry(e2["id"], REVIEWER1), 200)
        assert e2_now["status"] == "PENDING_REVIEW"
        e3_now = validate_success(api.get_spend_entry(e3["id"], REVIEWER1), 200)
        assert e3_now["status"] == "DISQUALIFIED"


class TestImmediateConsistency:
    def test_immediate_consistency_read_after_write(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.4: "Whenever the qualified set of an application changes — an
        entry created with a superseding amendment, a qualify or disqualify
        decision, the vendor-revocation cascade of §3.2, or an audit acceptance
        that refreshes figures (§3.5) — the application recomputes its totals."
        PRD §2.4: "The `version` field is an integer that increments by one on
        every mutation, including mutations performed by system cascades rather
        than direct client writes."

        Design: Corner/consistency_model/immediate_consistency_read_after_write
        """
        scenario = _approved_with_vendor(api)
        entry = add_spend_entry(scenario.application, scenario.vendor,
                                scenario.company, category="BTL",
                                is_resident_labor=True,
                                spend_date="2026-10-05T00:00:00Z",
                                amount_cents=100_000_000)
        before = get_application(scenario.application)

        resp = api.review_spend_entry(entry["id"], {"decision": "QUALIFY"},
                                      REVIEWER1)
        qualified = validate_success(resp, 200)
        assert qualified["status"] == "QUALIFIED", (
            "the mutation is visible in the review response itself")
        assert qualified["effective_amount_cents"] == 102_500_000

        after = get_application(scenario.application)
        assert after["btl_qualified_cents"] == 102_500_000, (
            "a follow-up read reflects the recomputed totals with no lag")
        assert after["version"] > before["version"], (
            "the recompute advanced the application's version")


class TestSpendReviewRbac:
    def test_admin_cannot_review_spend_forbidden(self, api):
        """PRD §2.1: "A request whose role is not on the target endpoint's
        authorized list is rejected with `ERR_FORBIDDEN_FOR_ROLE`."
        PRD §4: "| POST | `/api/spend-entries/{entryId}/review` | Reviewer
        qualifies or disqualifies a spend entry; fires the totals recompute
        cascade | FilmOfficeReviewer |"

        Design: Corner/rbac/admin_cannot_review_spend_forbidden
        """
        scenario = _approved_with_vendor(api)
        entry = add_spend_entry(scenario.application, scenario.vendor,
                                scenario.company, category="BTL",
                                amount_cents=1_000_000)
        resp = api.review_spend_entry(entry["id"], {"decision": "QUALIFY"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        current = validate_success(api.get_spend_entry(entry["id"], REVIEWER1), 200)
        assert current["status"] == "PENDING_REVIEW"


class TestQualifyDisqualifyRoundTrip:
    def _setup_round_trip(self, api):
        """ATL 40M + BTL 60M already qualified; a third BTL resident 100M entry
        pending. Pre-pair totals: atl 40M, btl 60M, capped 100M, prov 25M."""
        scenario = _approved_with_vendor(api)
        app, vendor, company = (scenario.application, scenario.vendor,
                                scenario.company)
        e_atl = add_spend_entry(app, vendor, company, category="ATL",
                                spend_date="2026-10-05T00:00:00Z",
                                amount_cents=40_000_000)
        e_btl = add_spend_entry(app, vendor, company, category="BTL",
                                spend_date="2026-10-19T00:00:00Z",
                                amount_cents=60_000_000)
        e3 = add_spend_entry(app, vendor, company, category="BTL",
                             is_resident_labor=True,
                             spend_date="2026-10-12T00:00:00Z",
                             amount_cents=100_000_000)
        qualify_entry(e_atl)
        qualify_entry(e_btl)
        return scenario, e3

    def test_qualify_then_disqualify_restores_totals(self, api):
        """PRD §3.4: "Disqualifying a previously `QUALIFIED` entry returns its
        effective amount to zero."
        PRD §3.4: "`atl_qualified_cents` is the sum of `effective_amount_cents`
        over the application's `QUALIFIED` `ATL` entries, and
        `btl_qualified_cents` the same sum over `BTL` entries; entries in any
        other status never contribute."

        Design: Difficulty/compensating_invariant/qualify_disqualify_round_trip_conserves_totals
        """
        scenario, e3 = self._setup_round_trip(api)
        pre = get_application(scenario.application)
        assert (pre["atl_qualified_cents"], pre["btl_qualified_cents"],
                pre["capped_total_qualified_cents"],
                pre["provisional_credit_cents"]) == (
                    40_000_000, 60_000_000, 100_000_000, 25_000_000)

        qualify_entry(e3)
        disqualify_entry(e3, reason="invoice voided by vendor")
        post = get_application(scenario.application)
        assert (post["atl_qualified_cents"], post["btl_qualified_cents"],
                post["capped_total_qualified_cents"],
                post["provisional_credit_cents"]) == (
                    pre["atl_qualified_cents"], pre["btl_qualified_cents"],
                    pre["capped_total_qualified_cents"],
                    pre["provisional_credit_cents"]), (
                        "the compensating pair returns the totals to the "
                        "pre-pair snapshot with zero drift")

    def test_qualify_mid_pair_recomputes_totals(self, api):
        """PRD §3.4: "Whenever the qualified set of an application changes — an
        entry created with a superseding amendment, a qualify or disqualify
        decision, the vendor-revocation cascade of §3.2, or an audit acceptance
        that refreshes figures (§3.5) — the application recomputes its totals."
        PRD §3.4: "From there, `provisional_credit_cents` refreshes as the
        PROVISIONAL credit variant over the system-qualified sums (§3.9), landing
        at zero when the capped total falls below the program minimum"

        Design: Difficulty/compensating_invariant/qualify_disqualify_round_trip_conserves_totals
        """
        scenario, e3 = self._setup_round_trip(api)
        qualify_entry(e3)
        mid = get_application(scenario.application)
        assert mid["btl_qualified_cents"] == 162_500_000, (
            "60000000 + (100000000 + round_half_up(100000000 * 0.025))")
        assert mid["capped_total_qualified_cents"] == 202_500_000
        assert mid["provisional_credit_cents"] == 60_750_000, (
            "202500000 crosses the elevated tier: round(202500000 * 0.30)")
