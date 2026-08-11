"""Warranty terms, claims, coverage variants, and the appeal loop
(PRD §2.1, §3.6, §3.9)."""
from test_helpers import (
    ApiErrorId, TEST_USERS, make_district_buyer_headers, validate_error,
    validate_success, add_accepted_po, build_accepted_award_context,
    build_verified_line_context, complete_task, create_task,
    file_warranty_claim, get_po_line, set_clock, ship_and_deliver, start_task,
)

SA = TEST_USERS["service_agent_headers"]
FC = TEST_USERS["fulfillment_coordinator_headers"]


class TestCoverageVariantDivergence:
    def test_standard_term_claim_past_base_end_rejected(self, api):
        """PRD §3.9: "the filing date must fall within the applicable term — on or
        before the base-term end for a non-enrolled district, or on or before the
        base-term end plus `extended_years` for an enrolled one — with a filing
        beyond the term rejected as `ERR_WARRANTY_EXPIRED`."

        Design: Difficulty/dual_variant_calc/warranty_standard_term_vs_extended_prorated_divergence
        """
        ctx = build_verified_line_context(
            line_qtys=(10,), pricing_mode="COOP_TIERED",
            extended_years=3, complete_clock="2026-07-08T10:00:00Z")
        # installed_at 2026-07-08 + 5y base term -> base_end 2031-07-08.
        set_clock("2032-08-12T09:00:00Z")  # 400 days past base_end
        resp = api.create_warranty_claim(
            {"po_line_id": ctx["lines"][0]["id"], "parts_cost_cents": 90000,
             "description": "frame weld cracked"},
            make_district_buyer_headers(ctx["district"]["id"]))
        validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED)

    def test_extended_prorated_claim_pays_prorated_coverage(self, api):
        """PRD §3.9: "the covered percentage is one minus the ratio of those
        started years to the award's `extended_years`, floored at zero; and
        `coverage_cents` is `parts_cost_cents` multiplied by that percentage,
        rounded half-up to whole cents."
        PRD §3.9: "past the base term, the standard variant would already have
        rejected the filing, while the extended variant pays a prorated amount."

        Design: Difficulty/dual_variant_calc/warranty_standard_term_vs_extended_prorated_divergence
        """
        ctx = build_verified_line_context(
            line_qtys=(10,), pricing_mode="COOP_TIERED",
            extended_warranty_enrolled=True, extended_years=3,
            complete_clock="2026-07-08T10:00:00Z")
        set_clock("2032-08-12T09:00:00Z")  # 400 days past base_end 2031-07-08
        claim = validate_success(api.create_warranty_claim(
            {"po_line_id": ctx["lines"][0]["id"], "parts_cost_cents": 90000,
             "description": "frame weld cracked"},
            make_district_buyer_headers(ctx["district"]["id"])), 201)
        assert claim["status"] == "FILED"

        validate_success(api.review_warranty_claim(claim["id"], SA))
        approved = validate_success(api.approve_warranty_claim(claim["id"], SA))
        assert approved["status"] == "APPROVED"
        # years_started = ceil(400/365) = 2; pct = 1 - 2/3; 90000 * 1/3 = 30000.
        assert approved["coverage_cents"] == 30000


class TestAppealCycle:
    def _denied_claim(self, api):
        ctx = build_verified_line_context(line_qtys=(5,))
        set_clock("2026-08-01T09:00:00Z")
        claim = file_warranty_claim(ctx["lines"][0]["id"], ctx["district"]["id"],
                                    parts_cost_cents=55000)
        validate_success(api.review_warranty_claim(claim["id"], SA))
        denied = validate_success(api.deny_warranty_claim(
            claim["id"], {"denial_reason": "normal wear"}, SA))
        assert denied["status"] == "DENIED"
        return ctx, claim

    def test_appeal_reinstates_review_then_approves(self, api):
        """PRD §3.9: "Review moves a claim from `FILED` to `UNDER_REVIEW` — and
        likewise from `APPEALED` back to `UNDER_REVIEW` when an appeal is being
        reconsidered."
        PRD §3.9: "Under the standard term — the district not enrolled — a claim
        approved within term is covered in full: `coverage_cents` equals
        `parts_cost_cents`."

        Design: Difficulty/non_linear_state_machine/warranty_appeal_cycle_reinstates_review_then_approves
        """
        ctx, claim = self._denied_claim(api)
        d_id = ctx["district"]["id"]

        appealed = validate_success(api.appeal_warranty_claim(
            claim["id"], {"appeal_note": "defect photos attached"},
            make_district_buyer_headers(d_id)))
        assert appealed["status"] == "APPEALED"
        assert appealed["appeal_count"] == 1

        review = validate_success(api.review_warranty_claim(claim["id"], SA))
        assert review["status"] == "UNDER_REVIEW"

        approved = validate_success(api.approve_warranty_claim(claim["id"], SA))
        assert approved["status"] == "APPROVED"
        assert approved["coverage_cents"] == 55000

        second = api.appeal_warranty_claim(
            claim["id"], {"appeal_note": "second appeal attempt"},
            make_district_buyer_headers(d_id))
        validate_error(second, ApiErrorId.ERR_INVALID_STATE)

    def test_second_appeal_after_loop_bound_spent_rejected(self, api):
        """PRD §3.9: "the move to `APPEALED` is permitted only while `appeal_count`
        is still 0 — a second appeal attempt is `ERR_INVALID_STATE` — and sets
        `appeal_count` to 1, after which `DENIED` is effectively terminal."

        Design: Difficulty/non_linear_state_machine/warranty_appeal_cycle_reinstates_review_then_approves
        """
        ctx, claim = self._denied_claim(api)
        d_id = ctx["district"]["id"]

        validate_success(api.appeal_warranty_claim(
            claim["id"], {"appeal_note": "defect photos attached"},
            make_district_buyer_headers(d_id)))
        validate_success(api.review_warranty_claim(claim["id"], SA))
        denied_again = validate_success(api.deny_warranty_claim(
            claim["id"], {"denial_reason": "still wear"}, SA))
        assert denied_again["status"] == "DENIED"
        assert denied_again["appeal_count"] == 1

        second = api.appeal_warranty_claim(
            claim["id"], {"appeal_note": "appeal the second denial"},
            make_district_buyer_headers(d_id))
        validate_error(second, ApiErrorId.ERR_INVALID_STATE)


class TestWarrantyTermBoundary:
    def _two_verified_lines(self, api):
        return build_verified_line_context(
            line_qtys=(5, 5), complete_clock="2026-07-08T10:00:00Z")

    def test_claim_on_exact_expiry_day_valid(self, api):
        """PRD §3.9: "the filing date must fall within the applicable term — on or
        before the base-term end for a non-enrolled district ... with a filing
        beyond the term rejected as `ERR_WARRANTY_EXPIRED`."
        PRD §3.9: "the base term runs for the award's `warranty_years` years from
        the installation date"

        Design: Difficulty/boundary_precision_check/warranty_claim_on_exact_expiry_day_valid_next_day_rejected
        """
        ctx = self._two_verified_lines(api)
        # installed_at 2026-07-08, warranty_years 5 -> base_end 2031-07-08.
        set_clock("2031-07-08T09:00:00Z")
        claim = validate_success(api.create_warranty_claim(
            {"po_line_id": ctx["lines"][0]["id"], "parts_cost_cents": 10000,
             "description": "exact-day claim"},
            make_district_buyer_headers(ctx["district"]["id"])), 201)
        assert claim["status"] == "FILED"

    def test_claim_one_day_past_expiry_rejected(self, api):
        """PRD §3.9: "on or before the base-term end for a non-enrolled district ...
        with a filing beyond the term rejected as `ERR_WARRANTY_EXPIRED`."

        Design: Difficulty/boundary_precision_check/warranty_claim_on_exact_expiry_day_valid_next_day_rejected
        """
        ctx = self._two_verified_lines(api)
        set_clock("2031-07-09T09:00:00Z")  # one day past base_end 2031-07-08
        resp = api.create_warranty_claim(
            {"po_line_id": ctx["lines"][1]["id"], "parts_cost_cents": 10000,
             "description": "one-day-late claim"},
            make_district_buyer_headers(ctx["district"]["id"]))
        validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED)


class TestLineVerifiedGate:
    def _delivered_not_verified(self, api):
        """PO line delivered (DELIVERED) but no install task completed."""
        ctx = build_accepted_award_context()
        po, lines = add_accepted_po(ctx, line_qtys=(5,))
        shipment = ship_and_deliver(ctx, po, lines)
        set_clock("2026-08-01T09:00:00Z")
        return ctx, po, lines, shipment

    def test_warranty_claim_requires_poline_verified(self, api):
        """PRD §3.9: "Filing enforces its gates in order: the line must be
        `VERIFIED` (`ERR_LINE_NOT_VERIFIED`)"

        Design: Difficulty/cross_entity_state_dependency/warranty_claim_requires_poline_verified
        """
        ctx, _po, lines, _shipment = self._delivered_not_verified(api)
        assert get_po_line(lines[0]["id"])["status"] == "DELIVERED"
        resp = api.create_warranty_claim(
            {"po_line_id": lines[0]["id"], "parts_cost_cents": 5000,
             "description": "premature claim"},
            make_district_buyer_headers(ctx["district"]["id"]))
        validate_error(resp, ApiErrorId.ERR_LINE_NOT_VERIFIED)

    def test_claim_succeeds_after_line_verified(self, api):
        """PRD §3.6: "every PO line on the shipment with `delivered_qty` greater
        than zero moves `DELIVERED` → `VERIFIED` with `installed_at` stamped from
        the logical clock"
        PRD §3.9: "A filed claim is `FILED` with `filed_date` stamped from the
        clock's date, `appeal_count` 0, and `coverage_cents` null."

        Design: Difficulty/cross_entity_state_dependency/warranty_claim_requires_poline_verified
        """
        ctx, _po, lines, shipment = self._delivered_not_verified(api)
        task = create_task(shipment["id"], ctx["crew"]["id"], ctx["site"]["id"],
                           start_date="2026-08-03", end_date="2026-08-04",
                           crew_count=1, room_label="W-12")
        start_task(task["id"], ctx["crew"]["id"])
        complete_task(task["id"], ctx["crew"]["id"])
        assert get_po_line(lines[0]["id"])["status"] == "VERIFIED"

        claim = validate_success(api.create_warranty_claim(
            {"po_line_id": lines[0]["id"], "parts_cost_cents": 5000,
             "description": "post-verification claim"},
            make_district_buyer_headers(ctx["district"]["id"])), 201)
        assert claim["status"] == "FILED"
        assert claim["appeal_count"] == 0
        assert claim["coverage_cents"] is None


class TestClaimAmountGuards:
    def test_claim_over_installed_value_returns_claim_exceeds_coverage(self, api):
        """PRD §3.9: "the claimed `parts_cost_cents` may not exceed the installed
        value of the line — its `delivered_qty` at verification multiplied by its
        `computed_unit_price_cents` — on pain of `ERR_CLAIM_EXCEEDS_COVERAGE`."

        Design: Corner/errors/claim_over_installed_value_returns_claim_exceeds_coverage
        """
        ctx = build_verified_line_context(line_qtys=(10,))
        set_clock("2026-08-01T09:00:00Z")
        resp = api.create_warranty_claim(
            {"po_line_id": ctx["lines"][0]["id"], "parts_cost_cents": 120000,
             "description": "overvalued claim"},
            make_district_buyer_headers(ctx["district"]["id"]))
        validate_error(resp, ApiErrorId.ERR_CLAIM_EXCEEDS_COVERAGE)

    def test_second_claim_on_open_line_returns_duplicate_claim(self, api):
        """PRD §3.9: "no second claim may exist on the same line while one is
        `FILED`, `UNDER_REVIEW`, `APPEALED`, or `APPROVED` (`ERR_DUPLICATE_CLAIM`)"

        Design: Corner/errors/second_claim_on_open_line_returns_duplicate_claim
        """
        ctx = build_verified_line_context(line_qtys=(10,))
        set_clock("2026-08-01T09:00:00Z")
        buyer = make_district_buyer_headers(ctx["district"]["id"])
        first = validate_success(api.create_warranty_claim(
            {"po_line_id": ctx["lines"][0]["id"], "parts_cost_cents": 5000,
             "description": "first claim"}, buyer), 201)
        assert first["status"] == "FILED"

        resp = api.create_warranty_claim(
            {"po_line_id": ctx["lines"][0]["id"], "parts_cost_cents": 6000,
             "description": "second claim while first open"}, buyer)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CLAIM)

    def test_warranty_approve_by_coordinator_returns_403(self, api):
        """PRD §2.1: "Each endpoint admits a defined set of roles; a well-formed
        request whose role is not on that endpoint's list is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §3.9: "Adjudication belongs to the `ServiceAgent`."

        Design: Corner/rbac/warranty_approve_by_coordinator_returns_403
        """
        ctx = build_verified_line_context(line_qtys=(10,))
        set_clock("2026-08-01T09:00:00Z")
        claim = file_warranty_claim(ctx["lines"][0]["id"], ctx["district"]["id"],
                                    parts_cost_cents=5000)
        validate_success(api.review_warranty_claim(claim["id"], SA))

        resp = api.approve_warranty_claim(claim["id"], FC)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
