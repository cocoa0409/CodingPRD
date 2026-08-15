"""Coverage requirement variants, cost-recovery fee calculation, payments,
adjustments, and the delinquency cascade."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_invoice_balance_invariant,
    assert_notice_day_invariant,
    create_deployment_for_notice,
    create_em_enrollment_payload,
    create_em_trip_payload,
    drive_deployment_to_closed,
    find_invoice_for_vessel,
    make_coverage_plan,
    make_fishery,
    make_observer,
    make_program_coordinator_headers,
    make_vessel_operator_headers,
    publish_plan,
    run_selection,
    setup_closed_deployment_scenario,
    setup_delinquent_operator_scenario,
    setup_issued_invoice_scenario,
    setup_notice_scenario,
    setup_two_vessel_billed_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
COORD = TEST_USERS["program_coordinator_headers"]


def _provisional_final_plan(api):
    """Fishery target 0.30; plan projected 1000/300; published; one (empty
    pool) selection run executed; ready to close."""
    fishery = make_fishery(
        code="BSAI-PLK", coverage_target_pct=0.30, priority_gear="TRAWL"
    )
    plan = make_coverage_plan(
        fishery,
        projected_fleet_effort_days=1000,
        projected_em_effort_days=300,
    )
    published = publish_plan(plan["id"])
    run_selection(plan["id"], notice_response_deadline="2026-09-20T00:00:00Z")
    return fishery, plan, published


def _setup_two_single_day_invoice(api):
    """One vessel with TWO 1-day CLOSED deployments under one notice, invoice
    generated (DRAFT).

    PRD §3.4 requires the return to fall strictly after the departure, so each
    single-day deployment departs at 00:00 and returns at 12:00 on the same
    calendar day — the inclusive day count is 1."""
    bundle = setup_notice_scenario(
        length_ft=50, gear_type="TRAWL", priority_gear="TRAWL"
    )
    obs2 = make_observer()
    notice = bundle["notice"]
    d1 = create_deployment_for_notice(
        notice["id"], bundle["observer"]["id"],
        "2026-09-10T00:00:00Z", "2026-09-10T12:00:00Z",
    )
    drive_deployment_to_closed(
        d1["id"], bundle["observer"]["id"], bundle["debriefer"]["id"],
        "2026-09-10T00:00:00Z", haul_date="2026-09-10T00:00:00Z",
    )
    d2 = create_deployment_for_notice(
        notice["id"], obs2["id"],
        "2026-09-12T00:00:00Z", "2026-09-12T12:00:00Z",
    )
    drive_deployment_to_closed(
        d2["id"], obs2["id"], bundle["debriefer"]["id"],
        "2026-09-12T00:00:00Z", haul_date="2026-09-12T00:00:00Z",
    )
    validate_success(api.generate_invoices(bundle["plan"]["id"], {}, COORD), 201)
    invoice = find_invoice_for_vessel(bundle["plan"]["id"], bundle["vessel"]["id"])
    return bundle, invoice


class TestCoverageRequirementVariants:
    def test_provisional_and_final_values(self, api, coordinator_headers):
        """PRD §3.2: "Publication runs the coverage calculation in its
        provisional variant, in four pinned steps that must be applied in this
        order: first, the electronic-monitoring credit is capped at the
        whole-day floor of forty percent of the effort-day figure; second, the
        credited EM days are the lesser of the plan's EM-day figure and that
        cap; third, the covered base is the effort-day figure minus the
        credited EM days, never below zero; fourth, the requirement is the
        covered base multiplied by the fishery's current `coverage_target_pct`,
        rounded up to a whole day." and "Closing re-runs the same four-step
        calculation in its final variant, substituting
        `actual_fleet_effort_days` and the accumulated `actual_em_sea_days` for
        the projections, and stores the outcome as
        `final_required_observer_sea_days`"

        Design: Difficulty/dual_variant_calc/coverage_requirement_provisional_vs_final_diverge_on_actuals
        """
        fishery, plan, published = _provisional_final_plan(api)
        # PROVISIONAL: em_cap floor(1000*0.40)=400, credited min(300,400)=300,
        # base 700, requirement ceil(700*0.30)=210.
        assert published["required_observer_sea_days"] == 210
        assert published["status"] == "PUBLISHED"

        closed = validate_success(
            api.close_coverage_plan(
                plan["id"], {"actual_fleet_effort_days": 1200}, coordinator_headers
            )
        )
        # FINAL: em_cap floor(1200*0.40)=480, credited min(0,480)=0, base 1200,
        # requirement ceil(1200*0.30)=360.
        assert closed["status"] == "CLOSED"
        assert closed["final_required_observer_sea_days"] == 360

    def test_variants_diverge_and_attainment_computed(self, api, coordinator_headers):
        """PRD §3.2: "for the same plan, the provisional and final figures
        diverge whenever actuals departed from projections." and "Attainment is
        then recorded as `coverage_attainment_pct`: the plan's
        `actual_observer_sea_days` divided by
        `final_required_observer_sea_days`, rounded half-up to four decimal
        places — and zero when both figures are zero."

        Design: Difficulty/dual_variant_calc/coverage_requirement_provisional_vs_final_diverge_on_actuals
        """
        fishery, plan, published = _provisional_final_plan(api)
        closed = validate_success(
            api.close_coverage_plan(
                plan["id"], {"actual_fleet_effort_days": 1200}, coordinator_headers
            )
        )
        assert closed["required_observer_sea_days"] == 210
        assert closed["final_required_observer_sea_days"] == 360
        assert (
            closed["final_required_observer_sea_days"]
            != closed["required_observer_sea_days"]
        ), "variants must diverge when actuals depart from projections"
        # 0 actual observer days over a 360-day final requirement.
        assert closed["coverage_attainment_pct"] == pytest.approx(0.0, abs=1e-9)


class TestCostRecoveryFeeVariants:
    def test_standard_and_small_vessel_amounts(self, api, coordinator_headers):
        """PRD §3.9: "Pricing is cumulative per vessel. The vessel's billable
        deployments are ordered by `scheduled_departure_date` ascending, ties
        broken by the deployment's `created_at` ascending, and a running day
        index walks every billed day of every deployment in that order: days
        whose running index falls within the first 20 are priced at the tier-1
        rate of 39900 cents per day, and every day from the twenty-first onward
        at the tier-2 rate of 49900 cents per day." and "The line subtotal is
        the tier-1 days at the tier-1 rate plus the tier-2 days at the tier-2
        rate, multiplied by the fee-variant factor — 1 for the `STANDARD`
        variant, one half for the `SMALL_VESSEL` variant that applies when the
        vessel's `length_ft` is under 40 feet. The line total is the line
        subtotal inflated by a 3.7 percent surcharge, rounded half-up to whole
        cents."

        Design: Difficulty/dual_variant_calc/cost_recovery_fee_standard_vs_small_vessel_variant
        """
        bundle = setup_two_vessel_billed_scenario()
        inv_a = bundle["invoice_a"]
        inv_b = bundle["invoice_b"]
        # Vessel A (50 ft, STANDARD): round_half_up(10*39900*1*1.037).
        assert inv_a["fee_variant"] == "STANDARD"
        assert inv_a["amount_due_cents"] == 413763
        assert inv_a["sea_days_billed"] == 10
        # Vessel B (30 ft, SMALL_VESSEL): round_half_up(10*39900*0.5*1.037).
        assert inv_b["fee_variant"] == "SMALL_VESSEL"
        assert inv_b["amount_due_cents"] == 206882
        assert inv_b["sea_days_billed"] == 10

    def test_variants_diverge_on_identical_day_pattern(self, api, coordinator_headers):
        """PRD §3.9: "The line subtotal is the tier-1 days at the tier-1 rate
        plus the tier-2 days at the tier-2 rate, multiplied by the fee-variant
        factor — 1 for the `STANDARD` variant, one half for the `SMALL_VESSEL`
        variant that applies when the vessel's `length_ft` is under 40 feet."

        Design: Difficulty/dual_variant_calc/cost_recovery_fee_standard_vs_small_vessel_variant
        """
        bundle = setup_two_vessel_billed_scenario()
        assert len(bundle["generation"]["created_invoice_ids"]) == 2
        assert bundle["generation"]["skipped_vessel_ids"] == []
        inv_a = bundle["invoice_a"]
        inv_b = bundle["invoice_b"]
        assert inv_a["vessel_id"] == bundle["vessel_a"]["id"]
        assert inv_b["vessel_id"] == bundle["vessel_b"]["id"]
        assert inv_a["amount_due_cents"] != inv_b["amount_due_cents"], (
            "the variant factor must produce different totals for identical "
            "10-day patterns"
        )
        assert inv_a["amount_due_cents"] == 413763
        assert inv_b["amount_due_cents"] == 206882


class TestInvoiceLineRoundingOrder:
    def test_per_line_rounding(self, api, coordinator_headers):
        """PRD §3.9: "The line total is the line subtotal inflated by a 3.7
        percent surcharge, rounded half-up to whole cents. Rounding order is
        pinned: each line is rounded to cents first, and `amount_due_cents` is
        the sum of the already-rounded line totals — summing subtotals first
        and rounding once produces different cents and is non-conformant."

        Design: Difficulty/combinatorial_formula/invoice_line_rounding_order_per_line_then_sum
        """
        bundle, invoice = _setup_two_single_day_invoice(api)
        lines = invoice["line_items"]
        assert len(lines) == 2, "one line per CLOSED deployment"
        for line in lines:
            # 1*39900*1.037 == 41376.3 -> round_half_up -> 41376.
            assert line["days"] == 1
            assert line["tier1_days"] == 1
            assert line["tier2_days"] == 0
            assert line["line_subtotal_cents"] == 39900
            assert line["line_total_cents"] == 41376

    def test_sum_of_rounded_lines_not_rounded_sum(self, api, coordinator_headers):
        """PRD §3.9: "Rounding order is pinned: each line is rounded to cents
        first, and `amount_due_cents` is the sum of the already-rounded line
        totals — summing subtotals first and rounding once produces different
        cents and is non-conformant."

        Design: Difficulty/combinatorial_formula/invoice_line_rounding_order_per_line_then_sum
        """
        bundle, invoice = _setup_two_single_day_invoice(api)
        # Pinned order: 41376 + 41376 == 82752. The non-conformant
        # sum-then-round order would yield round_half_up(2*39900*1.037)=82753.
        assert invoice["amount_due_cents"] == 82752
        assert invoice["amount_due_cents"] != 82753
        assert invoice["sea_days_billed"] == 2
        assert_invoice_balance_invariant(invoice)


class TestRevenueCap:
    def test_cap_binds_when_declared_revenue_low(self, api, coordinator_headers):
        """PRD §3.9: "One cap protects small earners. When the vessel carries a
        `declared_annual_revenue_cents` value, the amount due is capped at the
        whole-cent floor of one half of one percent of that declared revenue;
        if the cap binds, `amount_due_cents` is replaced by the cap and
        `fee_cap_applied` is set true, otherwise it stays false."

        Design: Corner/endpoints/revenue_cap_applied_when_declared_revenue_binds
        """
        bundle = setup_closed_deployment_scenario(
            length_ft=30, gear_type="LONGLINE", priority_gear="LONGLINE",
            declared_annual_revenue_cents=20000000,
        )
        validate_success(api.generate_invoices(bundle["plan"]["id"], {}, COORD), 201)
        invoice = find_invoice_for_vessel(bundle["plan"]["id"], bundle["vessel"]["id"])
        assert invoice["fee_variant"] == "SMALL_VESSEL"
        # Uncapped 206882; cap floor(20000000 * 0.005) == 100000 binds.
        assert invoice["amount_due_cents"] == 100000
        assert invoice["fee_cap_applied"] is True
        assert invoice["sea_days_billed"] == 10
        assert_invoice_balance_invariant(invoice)


class TestInvoiceGenerationSkip:
    def test_vessel_with_open_invoice_is_skipped(self, api, coordinator_headers):
        """PRD §3.9: "Generation collects the plan's `CLOSED` deployments
        (linked through their notices' `coverage_plan_id`), groups them by
        vessel, and produces one **invoice** per vessel with at least one such
        deployment; a vessel that already has a non-terminal invoice for the
        same plan is skipped. The response reports `created_invoice_ids` for
        the invoices minted and `skipped_vessel_ids` for the vessels passed
        over."

        Design: Corner/endpoints/invoice_generate_skips_vessel_with_existing_open_invoice
        """
        bundle = setup_two_vessel_billed_scenario()
        inv_a = bundle["invoice_a"]
        inv_b = bundle["invoice_b"]
        validate_success(api.issue_invoice(inv_a["id"], {}, COORD))
        issued_b = validate_success(api.issue_invoice(inv_b["id"], {}, COORD))
        paid = validate_success(
            api.create_payment(
                inv_b["id"],
                {"amount_cents": issued_b["amount_outstanding_cents"]},
                make_vessel_operator_headers(bundle["operator"]["id"]),
            ),
            201,
        )
        assert paid["status"] == "PAID"

        second = validate_success(
            api.generate_invoices(bundle["plan"]["id"], {}, COORD), 201
        )
        # Vessel A's invoice is ISSUED (non-terminal) -> skipped; vessel B's
        # is PAID (terminal) -> the skip rule does not name it.
        assert set(second["skipped_vessel_ids"]) == {bundle["vessel_a"]["id"]}
        inv_a_now = validate_success(api.get_invoice(inv_a["id"], coordinator_headers))
        assert inv_a_now["status"] == "ISSUED"
        assert inv_a_now["amount_due_cents"] == 413763


class TestPaymentRules:
    def test_payment_not_positive_and_exceeds_outstanding(self, api, coordinator_headers):
        """PRD §3.9: "A payment must be a positive integer number of cents
        (`ERR_PAYMENT_NOT_POSITIVE`), must not exceed the current
        `amount_outstanding_cents` (`ERR_PAYMENT_EXCEEDS_OUTSTANDING`), and is
        accepted only while the invoice is in `ISSUED`, `PARTIALLY_PAID`, or
        `OVERDUE` — against any other status, `ERR_INVOICE_NOT_ISSUED`."

        Design: Corner/errors/err_payment_not_positive_and_exceeds_outstanding
        """
        bundle = setup_issued_invoice_scenario()
        invoice = bundle["invoice"]
        assert invoice["amount_outstanding_cents"] == 413763
        op = make_vessel_operator_headers(bundle["operator"]["id"])

        zero = api.create_payment(invoice["id"], {"amount_cents": 0}, op)
        validate_error(zero, ApiErrorId.ERR_PAYMENT_NOT_POSITIVE, 422)
        too_much = api.create_payment(invoice["id"], {"amount_cents": 413764}, op)
        validate_error(too_much, ApiErrorId.ERR_PAYMENT_EXCEEDS_OUTSTANDING, 422)

        current = validate_success(api.get_invoice(invoice["id"], coordinator_headers))
        assert current["amount_paid_cents"] == 0
        assert current["status"] == "ISSUED"

    def test_payment_on_draft_state_error_beats_fiscal_error(self, api, coordinator_headers):
        """PRD §2.11: "Incoming writes are checked in a fixed priority order so
        that a request with several problems always surfaces the same error.
        Lower numbers win:" with "6. **State-machine legality** — the target
        resource is in a from-state that permits the transition
        (`ERR_INVALID_STATE` and the domain state errors
        `ERR_NOTICE_NOT_ACCEPTED`, `ERR_PLAN_NOT_PUBLISHED`,
        `ERR_PLAN_HAS_OPEN_DEPLOYMENTS`, `ERR_INVOICE_NOT_ISSUED`,
        `ERR_SAFETY_CHECK_REQUIRED`, `ERR_DEBRIEFER_NOT_ASSIGNED`,
        `ERR_REVIEWER_NOT_ASSIGNED`, `ERR_EM_REVIEW_MIN_NOT_MET`,
        `ERR_SAMPLES_NOT_RESOLVED`)." outranking "11. **Fiscal and allocation
        rules** — sea-day allocation, payment bounds, adjustment floors
        (`ERR_SEA_DAY_ALLOCATION_EXCEEDED`, `ERR_PAYMENT_NOT_POSITIVE`,
        `ERR_PAYMENT_EXCEEDS_OUTSTANDING`, `ERR_ADJUSTMENT_WOULD_UNDERFLOW`)."

        Design: Difficulty/priority_pair_validation_conflict/invoice_payment_state_error_beats_fiscal_error
        """
        bundle = setup_issued_invoice_scenario(issue=False)
        invoice = bundle["invoice"]
        assert invoice["status"] == "DRAFT"
        assert invoice["amount_due_cents"] == 413763
        # Violates both the state gate (DRAFT is not payable) and the fiscal
        # bound (999999 > outstanding); the state gate must win.
        resp = api.create_payment(
            invoice["id"],
            {"amount_cents": 999999},
            make_vessel_operator_headers(bundle["operator"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_ISSUED, 409)

    def test_payment_on_draft_rejected_even_at_exact_amount(self, api, coordinator_headers):
        """PRD §3.9: "A payment must be a positive integer number of cents
        (`ERR_PAYMENT_NOT_POSITIVE`), must not exceed the current
        `amount_outstanding_cents` (`ERR_PAYMENT_EXCEEDS_OUTSTANDING`), and is
        accepted only while the invoice is in `ISSUED`, `PARTIALLY_PAID`, or
        `OVERDUE` — against any other status, `ERR_INVOICE_NOT_ISSUED`."

        Design: Difficulty/priority_pair_validation_conflict/invoice_payment_state_error_beats_fiscal_error
        """
        bundle = setup_issued_invoice_scenario(issue=False)
        invoice = bundle["invoice"]
        assert invoice["status"] == "DRAFT"
        # Exactly the outstanding amount on a DRAFT invoice: still a state
        # violation, never a fiscal one.
        resp = api.create_payment(
            invoice["id"],
            {"amount_cents": 413763},
            make_vessel_operator_headers(bundle["operator"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_ISSUED, 409)
        current = validate_success(api.get_invoice(invoice["id"], coordinator_headers))
        assert current["amount_paid_cents"] == 0


class TestAdjustmentAndOverlapGuards:
    def test_adjustment_underflow_and_em_trip_overlap(self, api, coordinator_headers):
        """PRD §3.9: "And the adjustment may not drive
        `amount_outstanding_cents` below zero, else
        `ERR_ADJUSTMENT_WOULD_UNDERFLOW`." PRD §3.8: "The new trip's closed
        date interval must not intersect any other trip of the vessel in
        `DECLARED`, `FOOTAGE_SUBMITTED`, `IN_REVIEW`, or `REVIEWED`, nor any
        deployment of the vessel in `SCHEDULED`, `SAFETY_HOLD`,
        `READY_TO_DEPLOY`, or `AT_SEA` — touching dates count as overlap — else
        `ERR_EM_TRIP_OVERLAP`."

        Design: Corner/errors/err_adjustment_would_underflow_and_em_trip_overlap
        """
        bundle = setup_issued_invoice_scenario()
        invoice = bundle["invoice"]
        op = make_vessel_operator_headers(bundle["operator"]["id"])
        # Switch the vessel to electronic monitoring and declare a trip.
        enrollment = validate_success(
            api.create_em_enrollment(
                create_em_enrollment_payload(vessel_id=bundle["vessel"]["id"]), op
            ),
            201,
        )
        validate_success(api.approve_em_enrollment(enrollment["id"], {}, ADMIN))
        validate_success(api.activate_em_enrollment(enrollment["id"], {}, COORD))
        trip = validate_success(
            api.create_em_trip(
                create_em_trip_payload(vessel_id=bundle["vessel"]["id"]), op
            ),
            201,
        )

        underflow = api.create_adjustment(
            invoice["id"],
            {
                "adjustment_cents": -413764,
                "reason": "Over-aggressive credit",
                "expected_invoice_version": invoice["version"],
            },
            ADMIN,
        )
        validate_error(underflow, ApiErrorId.ERR_ADJUSTMENT_WOULD_UNDERFLOW, 422)

        # [2026-10-08, 2026-10-12] touches the existing trip's closed interval
        # [2026-10-01, 2026-10-08] at 2026-10-08.
        overlap = api.create_em_trip(
            create_em_trip_payload(
                vessel_id=bundle["vessel"]["id"],
                departure_date="2026-10-08T00:00:00Z",
                return_date="2026-10-12T00:00:00Z",
            ),
            op,
        )
        validate_error(overlap, ApiErrorId.ERR_EM_TRIP_OVERLAP, 409)

        current = validate_success(api.get_invoice(invoice["id"], coordinator_headers))
        assert current["amount_adjusted_cents"] == 0
        trips, meta = validate_paginated(
            api.list_em_trips(coordinator_headers, params={"vessel_id": bundle["vessel"]["id"]})
        )
        assert meta["total_count"] == 1

    def test_adjustment_by_issuing_user_forbidden(self, api, admin_headers, coordinator_headers):
        """PRD §3.9: "Segregation of duties forbids the issuer from adjusting
        their own invoice: the caller's `X-User-ID` must differ from the
        invoice's `issued_by_user_id`, else `ERR_INVOICE_ADJUSTMENT_FORBIDDEN`."

        Design: Corner/rbac/invoice_adjustment_by_issuing_user_forbidden
        """
        bundle = setup_issued_invoice_scenario(issue=False)
        invoice = bundle["invoice"]
        # Issue with an opaque coordinator id that collides with the admin's
        # user id, so the same user then attempts the adjustment.
        issuer = make_program_coordinator_headers("admin-user-1")
        issued = validate_success(api.issue_invoice(invoice["id"], {}, issuer))
        assert issued["issued_by_user_id"] == "admin-user-1"
        resp = api.create_adjustment(
            invoice["id"],
            {
                "adjustment_cents": -1000,
                "reason": "Issuer attempting own adjustment",
                "expected_invoice_version": issued["version"],
            },
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVOICE_ADJUSTMENT_FORBIDDEN, 403)
        current = validate_success(api.get_invoice(invoice["id"], coordinator_headers))
        assert current["amount_adjusted_cents"] == 0
        assert current["status"] == "ISSUED"


class TestInvoiceAdjustmentOCC:
    def test_stale_invoice_version_rejected(self, api, admin_headers, coordinator_headers):
        """PRD §2.8: "Posting an invoice adjustment requires
        `expected_invoice_version`, matched against the invoice's current
        `version`; a mismatch — a payment or an earlier adjustment has moved
        the outstanding balance the client based its arithmetic on — is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_invoice_adjustment_stale_version
        """
        bundle = setup_issued_invoice_scenario()
        invoice = bundle["invoice"]
        v0 = invoice["version"]
        # A first adjustment bumps the invoice version.
        first = validate_success(
            api.create_adjustment(
                invoice["id"],
                {
                    "adjustment_cents": 1000,
                    "reason": "Surcharge correction upward",
                    "expected_invoice_version": v0,
                },
                admin_headers,
            ),
            201,
        )
        v1 = first["version"]
        assert v1 != v0
        stale = api.create_adjustment(
            invoice["id"],
            {
                "adjustment_cents": 2000,
                "reason": "Stale-basis correction",
                "expected_invoice_version": v0,
            },
            admin_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)
        fresh = validate_success(
            api.create_adjustment(
                invoice["id"],
                {
                    "adjustment_cents": 2000,
                    "reason": "Fresh-basis correction",
                    "expected_invoice_version": v1,
                },
                admin_headers,
            ),
            201,
        )
        assert fresh["amount_outstanding_cents"] == 413763 + 1000 + 2000
        assert_invoice_balance_invariant(fresh)


class TestInvoiceOutstandingInvariant:
    def test_forward_adjustment(self, api, admin_headers, coordinator_headers):
        """PRD §3.9: "Adjustments are permitted in `ISSUED`, `OVERDUE`, and
        `DISPUTED`; each adds to `amount_adjusted_cents`, recomputes the
        outstanding balance, and increments `version` without changing the
        invoice's status." and "Every invoice tracks `amount_paid_cents` (zero
        at birth), `amount_adjusted_cents` (zero at birth), and the derived
        `amount_outstanding_cents` — the amount due plus adjustments minus
        payments — which must never go negative."

        Design: Difficulty/compensating_invariant/invoice_outstanding_invariant_compensating_adjustments
        """
        bundle = setup_issued_invoice_scenario()
        invoice = bundle["invoice"]
        adjusted = validate_success(
            api.create_adjustment(
                invoice["id"],
                {
                    "adjustment_cents": 5000,
                    "reason": "Surcharge correction upward",
                    "expected_invoice_version": invoice["version"],
                },
                admin_headers,
            ),
            201,
        )
        assert adjusted["status"] == "ISSUED"
        assert adjusted["amount_adjusted_cents"] == 5000
        assert adjusted["amount_outstanding_cents"] == 418763
        assert adjusted["amount_due_cents"] == 413763
        assert_invoice_balance_invariant(adjusted)

    def test_compensating_adjustment_restores_balance(self, api, admin_headers, coordinator_headers):
        """PRD §3.9: "Adjustments are permitted in `ISSUED`, `OVERDUE`, and
        `DISPUTED`; each adds to `amount_adjusted_cents`, recomputes the
        outstanding balance, and increments `version` without changing the
        invoice's status." and "Every invoice tracks `amount_paid_cents` (zero
        at birth), `amount_adjusted_cents` (zero at birth), and the derived
        `amount_outstanding_cents` — the amount due plus adjustments minus
        payments — which must never go negative."

        Design: Difficulty/compensating_invariant/invoice_outstanding_invariant_compensating_adjustments
        """
        bundle = setup_issued_invoice_scenario()
        invoice = bundle["invoice"]
        forward = validate_success(
            api.create_adjustment(
                invoice["id"],
                {
                    "adjustment_cents": 5000,
                    "reason": "Surcharge correction upward",
                    "expected_invoice_version": invoice["version"],
                },
                admin_headers,
            ),
            201,
        )
        restored = validate_success(
            api.create_adjustment(
                invoice["id"],
                {
                    "adjustment_cents": -5000,
                    "reason": "Compensating reversal",
                    "expected_invoice_version": forward["version"],
                },
                admin_headers,
            ),
            201,
        )
        assert restored["status"] == "ISSUED"
        assert restored["amount_adjusted_cents"] == 0
        assert restored["amount_outstanding_cents"] == 413763
        assert restored["amount_due_cents"] == 413763
        assert_invoice_balance_invariant(restored)


class TestDelinquencyCascade:
    def test_cascade_statuses_and_counters(self, api, coordinator_headers):
        """PRD §2.10: "When the operations checkpoint moves an invoice to
        `OVERDUE`, the cascade walks outward: the invoice's operator has
        `payment_standing` set to `DELINQUENT`; every vessel of that operator
        in `ACTIVE` status is suspended (`ACTIVE` → `SUSPENDED`); and every
        deployment of such a vessel still in `SCHEDULED`, `SAFETY_HOLD`, or
        `READY_TO_DEPLOY` is cancelled, releasing its reserved sea days back to
        its notice per §2.9." PRD §2.7: "The response tallies the sweep's work
        in five counters: `expired_notice_count`, `overdue_invoice_count`,
        `delinquent_operator_count`, `suspended_vessel_count`, and
        `cancelled_deployment_count`."

        Design: Difficulty/transitive_cascade/overdue_invoice_delinquency_cascade_depth4
        """
        bundle = setup_delinquent_operator_scenario(with_open_deployment=True)
        ops = bundle["ops_result"]
        assert ops["overdue_invoice_count"] == 1
        assert ops["delinquent_operator_count"] == 1
        assert ops["suspended_vessel_count"] == 1
        assert ops["cancelled_deployment_count"] == 1

        invoice = validate_success(api.get_invoice(bundle["invoice"]["id"], coordinator_headers))
        assert invoice["status"] == "OVERDUE"
        operator = validate_success(
            api.get_vessel_operator(bundle["operator"]["id"], coordinator_headers)
        )
        assert operator["payment_standing"] == "DELINQUENT"
        vessel = validate_success(api.get_vessel(bundle["vessel"]["id"], coordinator_headers))
        assert vessel["status"] == "SUSPENDED"
        deployment2 = validate_success(
            api.get_deployment(bundle["deployment2"]["id"], coordinator_headers)
        )
        assert deployment2["status"] == "CANCELLED"

    def test_cascade_releases_reserved_days(self, api, coordinator_headers):
        """PRD §2.10: "When the operations checkpoint moves an invoice to
        `OVERDUE`, the cascade walks outward: the invoice's operator has
        `payment_standing` set to `DELINQUENT`; every vessel of that operator
        in `ACTIVE` status is suspended (`ACTIVE` → `SUSPENDED`); and every
        deployment of such a vessel still in `SCHEDULED`, `SAFETY_HOLD`, or
        `READY_TO_DEPLOY` is cancelled, releasing its reserved sea days back to
        its notice per §2.9." PRD §2.9: "Cancelling a deployment releases its
        reservation wholesale: `reserved_sea_days` drops by `planned_sea_days` and
        `remaining_sea_days` rises by the same."

        Design: Difficulty/transitive_cascade/overdue_invoice_delinquency_cascade_depth4
        """
        bundle = setup_delinquent_operator_scenario(with_open_deployment=True)
        notice = validate_success(
            api.get_selection_notice(bundle["notice"]["id"], coordinator_headers)
        )
        # D1 consumed 10; the cancelled D2's 10 reserved days are released.
        assert notice["reserved_sea_days"] == 0
        assert notice["consumed_sea_days"] == 10
        assert notice["remaining_sea_days"] == 20
        assert notice["allocated_sea_days"] == 30
        assert_notice_day_invariant(notice)
        deployment1 = validate_success(
            api.get_deployment(bundle["deployment"]["id"], coordinator_headers)
        )
        assert deployment1["status"] == "CLOSED", (
            "the completed deployment is untouched by the cascade"
        )
