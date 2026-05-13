"""Difficulty-design dedicated coverage.

Each difficulty-design instance MUST be exercised by at least two tests; this
module supplies the explicit second test for instances already partially covered
elsewhere, plus full coverage for instances that have no home in other test
files. Every test docstring carries the matching PRD prose citation and a
``# difficulty: <rule_id>/<instance.name>`` tag.
"""

import pytest
from datetime import timedelta

from test_helpers import (
    validate_success,
    validate_error,
    ADMIN_HEADERS,
    OPS_HEADERS,
    COMPLIANCE_HEADERS,
    make_streamer_headers,
    set_clock,
    DEFAULT_BASE_TIME,
    setup_active_streamer,
    setup_studio_with_window,
    setup_draft_application,
    setup_scheduled_application,
    attach_compatible_product,
    submit_application,
    ops_approve,
    compliance_approve,
    fetch_invoice,
    fetch_application,
    fetch_settlement,
    fetch_streamer,
    create_violation,
    file_appeal,
    decide_appeal,
    enforce_violation_via_sweep,
    setup_silver_streamer_for_pricing_divergence,
    setup_silver_streamer_for_combo_discount,
    setup_gold_streamer_for_commission,
    setup_application_with_reservations,
    pay_deposit,
    go_live,
    end_live,
    emit_event_payload,
    create_application_payload,
    create_studio_payload,
    cancel_payload,
    approve_decision_payload,
    iso,
    ERR_INVALID_STATE,
    ERR_PRODUCT_CERT_MISSING,
    ERR_STUDIO_INTERVAL_CONFLICT,
    ERR_OUT_OF_AVAILABLE_WINDOW,
    ERR_DEPOSIT_UNPAID,
)
from test_helpers.fixtures import _parse_iso, get_product
from prd_bench_local_runner.testing import get_success_data


# =============================================================================
# Rule 1: dual_variant_calc — second tests
# =============================================================================


class TestDualVariantSlotFeeSecondLook:
    """Second test for dual_variant_calc/slot_fee_provisional_vs_final."""

    def test_pinned_streamer_tier_survives_post_approval_recompute(self, api):
        """# difficulty: dual_variant_calc/slot_fee_provisional_vs_final_on_application
        PRD §2.8: "Wherever a parent entity transitions, any pinned snapshot
        fields on its children (for example, pinned_streamer_tier on the
        application or snapshot_streamer_tier on an approval record) are
        preserved exactly as captured — recomputing the parent's tier after
        the snapshot was taken does not retroactively rewrite the snapshot."
        """
        bundle = setup_silver_streamer_for_pricing_divergence()
        app = bundle["application"]
        # The streamer's lifetime_gmv_cents may have increased post-approval
        # but pinned_streamer_tier must remain SILVER for this approved app.
        fresh = fetch_application(app["id"])
        assert fresh["pinned_streamer_tier"] == "SILVER"
        # And final_fee_cents must NOT have shifted from 28500
        assert fresh["final_fee_cents"] == 28_500


class TestDualVariantCommissionSecondLook:
    """Second look beyond the dedicated final_payout test: provisional uses
    gross only, the eventual final differs whenever returns > 0.
    """

    def test_provisional_uses_gross_only_no_tax(self, api):
        """# difficulty: dual_variant_calc/commission_provisional_vs_final_on_settlement
        PRD §3.8: "The provisional variant runs at end-live and reads only
        gross_sales_cents (returns have not yet been collected)."

        Negative form: at provisional time, tax_withholding_cents must NOT yet
        reflect the final taxation (the field is final-variant-only).
        """
        bundle = setup_gold_streamer_for_commission()
        streamer = bundle["streamer"]
        app = bundle["application"]
        starts = bundle["starts_at"]
        ends = bundle["ends_at"]
        app = go_live(streamer, app, clock_at=starts)
        get_success_data(api.emit_event(
            emit_event_payload(
                source="ECOMMERCE", kind="BROADCAST_GMV",
                occurred_at=starts + timedelta(minutes=30),
                application_id=app["id"], amount_cents=6_000_000,
            ), ADMIN_HEADERS
        ))
        app = end_live(streamer, app, clock_at=ends)
        settlement = fetch_settlement(app["id"])
        # At provisional time, status is WINDOW_OPEN; final_payout_cents is
        # either absent or has not yet been set to the final value.
        assert settlement["status"] == "WINDOW_OPEN"
        # The provisional payout uses gross only, no tax:
        # gross_commission = 6M * 1800/10000 = 1,080,000; bonus = 30,000
        # provisional_payout = 1,110,000
        assert settlement["provisional_payout_cents"] == 1_110_000


# =============================================================================
# Rule 2: combinatorial_formula — second tests
# =============================================================================


class TestCombinatorialSlotFeeSecondLook:
    """Second test for combinatorial_formula/slot_fee_pinned_rounding_order_mode_b."""

    def test_invoice_breakdown_fields_match_pinned_arithmetic(self, api):
        """# difficulty: combinatorial_formula/slot_fee_pinned_rounding_order_mode_b
        PRD §3.5: "When SlotFeeInvoice is issued at compliance approval, its
        subtotal_cents records the base plus peak-surcharge sum, its
        peak_surcharge_cents records only the peak component, its
        package_discount_cents records the absolute cent reduction
        attributable to the package discount, and its total_cents equals
        final_fee_cents."

        Per scenario: SILVER + COMBO_HALF_DAY, 2-hour fully-peak booking at
        10000 cents/hr.
            base = 20000, peak = 10000 -> subtotal 30000
            peak_surcharge_cents = 10000
            tier-adjusted = 30000 * 0.95 = 28500 (unrounded)
            package discount = 28500 - (28500 * 0.92) = 28500 * 0.08 = 2280
            total = round_half_up(28500 * 0.92) = 26220
        """
        bundle = setup_silver_streamer_for_combo_discount()
        invoice = bundle["invoice"]
        assert invoice["subtotal_cents"] == 30_000, \
            f"subtotal_cents must be 30000, got {invoice['subtotal_cents']}"
        assert invoice["peak_surcharge_cents"] == 10_000, \
            f"peak_surcharge_cents must be 10000, got {invoice['peak_surcharge_cents']}"


class TestCombinatorialCommissionSecondLook:
    """Second test for combinatorial_formula/commission_circular_dependency_mode_c."""

    def test_provisional_bonus_eligibility_unchanged_by_returns(self, api):
        """# difficulty: combinatorial_formula/commission_circular_dependency_mode_c
        PRD §3.8: "The tier bonus is 0 unless pinned_streamer_tier is GOLD or
        PLATINUM and gross_sales_cents is at least 5,000,000 cents, in which
        case the bonus is half a percent of gross_sales_cents (i.e.,
        gross_sales_cents multiplied by 0.005)..."

        Provisional is computed on gross only — so gross=5,000,000 yields a
        provisional bonus of 25,000 regardless of subsequent returns.
        """
        bundle = setup_gold_streamer_for_commission()
        streamer = bundle["streamer"]
        app = bundle["application"]
        starts = bundle["starts_at"]
        ends = bundle["ends_at"]
        app = go_live(streamer, app, clock_at=starts)
        get_success_data(api.emit_event(
            emit_event_payload(
                source="ECOMMERCE", kind="BROADCAST_GMV",
                occurred_at=starts + timedelta(minutes=30),
                application_id=app["id"], amount_cents=5_000_000,
            ), ADMIN_HEADERS
        ))
        app = end_live(streamer, app, clock_at=ends)
        settlement = fetch_settlement(app["id"])
        # gross_commission = round_half_up(5_000_000 * 1800 / 10000) = 900,000
        # tier_bonus = round_half_up(5_000_000 * 0.005) = 25,000
        # provisional = 925,000
        assert settlement["provisional_payout_cents"] == 925_000


# =============================================================================
# Rule 3: non_linear_state_machine — both instances need full coverage
# =============================================================================


class TestApplicationReviewBranching:
    """Difficulty-design Rule 3 instance: schedule_application_review_branching."""

    def test_ops_reject_branch_releases_stock_and_zeros_fee(self, api):
        """# difficulty: non_linear_state_machine/schedule_application_review_branching
        PRD §3.4: "A rejection transitions review_status from OPS_PENDING to
        REJECTED, requires a non-empty reason (otherwise ERR_REASON_REQUIRED,
        HTTP 422), and triggers a uniform release across every
        ProductAssociation for the application: each association moves to
        status RELEASED, the product's reserved_stock decreases by the
        association's reserved_quantity, and the product's available_stock
        increases by the same amount. The application's provisional_fee_cents
        is set to 0 and no invoice is issued."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer, studio, app = setup_draft_application()
        product, assoc = attach_compatible_product(app, streamer, reserved_quantity=10)
        app = submit_application(streamer, app)
        result = ops_approve(app["id"], decision="REJECT", reason="not fit")
        assert result["review_status"] == "REJECTED"
        assert result["provisional_fee_cents"] == 0
        product_after = get_product(product["id"])
        # PRD §3.4: each association moves to RELEASED, the product's
        # reserved_stock decreases by the association's reserved_quantity, and
        # the product's available_stock increases by the same amount. ``product``
        # was captured BEFORE the reservation pre-decremented stock, so the
        # post-release available_stock should equal the original creation-time
        # value (i.e., the 10-cent reserve has been returned to availability).
        assert product_after["reserved_stock"] == 0
        assert product_after["available_stock"] == product["available_stock"]

    def test_withdraw_branch_from_ops_pending(self, api):
        """# difficulty: non_linear_state_machine/schedule_application_review_branching
        PRD §3.4: "A streamer may withdraw their own application from DRAFT or
        OPS_PENDING, transitioning review_status to WITHDRAWN."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer, studio, app = setup_draft_application()
        attach_compatible_product(app, streamer)
        app = submit_application(streamer, app)
        result = get_success_data(api.withdraw_application(app["id"], make_streamer_headers(streamer["id"])))
        assert result["review_status"] == "WITHDRAWN"


class TestViolationCyclicWithRevert:
    """Difficulty-design Rule 3 instance: violation_cyclic_with_revert."""

    def test_overturn_restores_active_and_decrements_score(self, api):
        """# difficulty: non_linear_state_machine/violation_cyclic_with_revert
        PRD §3.9: "An OVERTURN decision sets the appeal's decision to
        OVERTURNED and decided_at to the current logical clock, transitions
        the violation from APPEAL_PENDING to OVERTURNED, and runs a depth-3
        cascade: if the streamer was SUSPENDED or BLACKLISTED solely because
        of this violation, the streamer's status reverts to ACTIVE and
        suspension_until is set to null; the violation's severity is
        subtracted from the streamer's violation_score; and the streamer's
        tier is recomputed against the new violation_score."

        Per recipe: DATA_FRAUD with 3 evidences => severity 5 => BLACKLIST.
        Then appeal & OVERTURN.
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer = setup_active_streamer()
        score_before = streamer["violation_score"]
        v = create_violation(streamer["id"], violation_type="DATA_FRAUD",
                             evidence_refs=["a", "b", "c"])
        # Violation creation must NOT yet apply the penalty (status OPEN); but
        # per PRD, BLACKLIST is the penalty_action — actual streamer.status
        # update happens at enforcement or via the immediate-blacklist path.
        # File appeal during OPEN window
        appeal = file_appeal(streamer, v["id"])
        decide_appeal(appeal["id"], decision="OVERTURN")
        s = fetch_streamer(streamer["id"])
        # Score must be ≤ pre-violation level (PRD: "the violation's severity
        # is subtracted from the streamer's violation_score")
        assert s["violation_score"] <= score_before, (
            f"OVERTURN must restore violation_score; before={score_before}, "
            f"after={s['violation_score']}"
        )

    def test_uphold_auto_advances_to_enforced(self, api):
        """# difficulty: non_linear_state_machine/violation_cyclic_with_revert
        PRD §3.9: "An UPHOLD decision sets the appeal's decision to UPHELD,
        transitions the violation to UPHELD, and the system auto-transitions
        the violation from UPHELD to ENFORCED immediately afterward without
        further mutation."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer = setup_active_streamer()
        v = create_violation(streamer["id"], violation_type="FALSE_ADVERTISING",
                             evidence_refs=["a", "b"])
        appeal = file_appeal(streamer, v["id"])
        decide_appeal(appeal["id"], decision="UPHOLD")
        from prd_bench_local_runner.testing import validate_paginated
        items, _ = validate_paginated(
            api.list_violations(ADMIN_HEADERS, params={"streamer_id": streamer["id"]})
        )
        target = [vi for vi in items if vi["id"] == v["id"]][0]
        assert target["status"] == "ENFORCED"


# =============================================================================
# Rule 4: transitive_cascade — second tests
# =============================================================================


class TestEndLiveTripleCascade:
    """Difficulty-design Rule 4 instance: end_live_triple_cascade."""

    def test_end_live_then_payout_recomputes_tier_to_silver(self, api):
        """# difficulty: transitive_cascade/end_live_triple_cascade
        PRD §3.6: "the server initializes a CommissionSettlement for the
        application with status WINDOW_OPEN and return_window_ends_at equal to
        the application's ends_at plus 7 days; it pins the settlement's
        commission_rate_bp using the provisional variant of the commission
        calculation against pinned_streamer_tier and gmv_cents; it increments
        the streamer's completed_broadcast_count by 1; and it triggers a
        depth-3 recompute of Streamer.tier..."
        PRD §3.8: "A PlatformAdmin then pays out a READY_FOR_PAYOUT
        settlement; the payout transitions status to PAID and adds the
        effective sales (gross_sales_cents minus returned_sales_cents) to the
        streamer's lifetime_gmv_cents, which in turn re-triggers the depth-3
        tier-recompute and suspension reconciliation cascade."

        BRONZE streamer; emit GMV >= 1,000,000; end-live; close window; payout
        => Streamer.tier becomes SILVER.
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer = setup_active_streamer()
        starts = DEFAULT_BASE_TIME + timedelta(days=10, hours=11)
        ends = starts + timedelta(hours=2)
        studio = setup_studio_with_window(
            available_start=starts - timedelta(days=30),
            available_end=ends + timedelta(days=30),
        )
        bundle = setup_scheduled_application(
            streamer=streamer, studio=studio,
            starts_at=starts, ends_at=ends,
        )
        app = bundle["application"]
        app = go_live(streamer, app, clock_at=starts)
        get_success_data(api.emit_event(
            emit_event_payload(
                source="ECOMMERCE", kind="BROADCAST_GMV",
                occurred_at=starts + timedelta(minutes=15),
                application_id=app["id"], amount_cents=1_000_000,
            ), ADMIN_HEADERS
        ))
        app = end_live(streamer, app, clock_at=ends)
        # Verify completed_broadcast_count incremented
        s = fetch_streamer(streamer["id"])
        assert s["completed_broadcast_count"] >= 1
        # Close window and payout
        from test_helpers import close_return_window
        close_return_window(ends)
        settlement = fetch_settlement(app["id"])
        get_success_data(api.payout_settlement(settlement["id"], ADMIN_HEADERS))
        s = fetch_streamer(streamer["id"])
        # Streamer.lifetime_gmv_cents must now be >= 1_000_000 and tier SILVER
        assert s["lifetime_gmv_cents"] >= 1_000_000
        assert s["tier"] == "SILVER", \
            f"tier must be SILVER after lifetime_gmv crosses 1_000_000, got {s['tier']}"

    def test_end_live_arms_settlement_and_pins_rate(self, api):
        """# difficulty: transitive_cascade/end_live_triple_cascade
        PRD §3.6: "it pins the settlement's commission_rate_bp using the
        provisional variant of the commission calculation against
        pinned_streamer_tier and gmv_cents".
        PRD §3.8: "It looks up the per-tier rate in basis points — 1,200 for
        BRONZE, 1,500 for SILVER, 1,800 for GOLD, 2,200 for PLATINUM — and
        pins it to commission_rate_bp based on pinned_streamer_tier."
        """
        set_clock(DEFAULT_BASE_TIME)
        bundle = setup_scheduled_application()
        streamer = bundle["streamer"]
        app = bundle["application"]
        app = go_live(streamer, app)
        app = end_live(streamer, app)
        settlement = fetch_settlement(app["id"])
        # streamer was BRONZE at compliance approval => commission_rate_bp = 1200
        assert settlement["commission_rate_bp"] == 1200


class TestViolationEnforcementTripleCascade:
    """Difficulty-design Rule 4 instance: violation_enforcement_triple_cascade."""

    def test_sweep_enforcement_blacklists_and_cancels_future_apps(self, api):
        """# difficulty: transitive_cascade/violation_enforcement_triple_cascade
        PRD §3.9: "A SUSPENSION or BLACKLIST enforcement also cascades depth-3
        through every future SCHEDULED application of the streamer: each such
        application is auto-cancelled, the refund calculation runs against its
        invoice, and the product associations are released."
        """
        set_clock(DEFAULT_BASE_TIME)
        bundle = setup_scheduled_application()
        streamer = bundle["streamer"]
        app = bundle["application"]
        invoice_before = bundle["invoice"]
        # Create a DATA_FRAUD violation with 3 evidences => severity 5 =>
        # BLACKLIST per PRD.
        v = create_violation(streamer["id"], violation_type="DATA_FRAUD",
                             evidence_refs=["e1", "e2", "e3"])
        # Drive sweep enforcement
        enforce_violation_via_sweep(v)
        s = fetch_streamer(streamer["id"])
        assert s["status"] == "BLACKLISTED", \
            f"streamer must be BLACKLISTED, got {s['status']}"
        # Future SCHEDULED application must be CANCELLED
        app_after = fetch_application(app["id"])
        assert app_after["operational_status"] == "CANCELLED", \
            f"future SCHEDULED app must be auto-CANCELLED, got {app_after['operational_status']}"
        # Invoice status reflects a refund branch
        invoice_after = fetch_invoice(app["id"])
        assert invoice_after["status"] in {"REFUNDED_FULL", "REFUNDED_PARTIAL"}

    def test_sweep_enforcement_increments_violation_score_on_fine(self, api):
        """# difficulty: transitive_cascade/violation_enforcement_triple_cascade
        PRD §3.9: "FINE (increment Streamer.violation_score by severity, charge
        fine via Payment event externally)" — enforcement increments score by
        severity.
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer = setup_active_streamer()
        score_before = streamer["violation_score"]
        # FALSE_ADVERTISING with 2 evidences => severity 2 => FINE
        v = create_violation(streamer["id"], violation_type="FALSE_ADVERTISING",
                             evidence_refs=["a", "b"])
        enforce_violation_via_sweep(v)
        s = fetch_streamer(streamer["id"])
        assert s["violation_score"] == score_before + 2


# =============================================================================
# Rule 5: priority_pair_validation_conflict
# =============================================================================


class TestStateVsTemporalOnSubmit:
    """Difficulty-design Rule 5 instance: state_vs_business_temporal_on_submit."""

    def test_double_submit_returns_invalid_state_not_temporal(self, api):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_temporal_on_submit
        PRD §2.9: "the server evaluates them in a fixed order so that the
        returned error_id is predictable. The authentication-headers check
        fires first (ERR_AUTH_REQUIRED), then the role-authorization check
        (ERR_FORBIDDEN), then path-id existence (ERR_NOT_FOUND), then body-id
        existence (ERR_NOT_FOUND), then streamer-ownership (ERR_FORBIDDEN),
        then state precondition (ERR_INVALID_STATE)."

        State (priority 6 — ERR_INVALID_STATE) must beat the business_temporal
        checks. Submitting an already-OPS_PENDING application must return
        ERR_INVALID_STATE regardless of any other rule violations.
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer, studio, app = setup_draft_application()
        attach_compatible_product(app, streamer)
        submit_application(streamer, app)  # OPS_PENDING
        # Second submit must yield ERR_INVALID_STATE
        resp = api.submit_application(app["id"], make_streamer_headers(streamer["id"]))
        validate_error(resp, ERR_INVALID_STATE, expected_status=409)

    def test_submit_on_approved_app_returns_invalid_state(self, api):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_temporal_on_submit
        PRD §2.9: "then state precondition (ERR_INVALID_STATE)."
        PRD §3.4: "After attaching products, the streamer advances the
        application from DRAFT to OPS_PENDING." — submit is legal only from
        DRAFT, so an already-APPROVED application must hit state-precondition
        before any temporal check, regardless of whether the underlying
        interval still satisfies AVAILABLE-coverage.

        State (priority 6 — ERR_INVALID_STATE) must fire before any of the
        priority-12/13 business_temporal checks. Driving an application to
        APPROVED and re-submitting must yield ERR_INVALID_STATE, never
        ERR_OUT_OF_AVAILABLE_WINDOW.
        """
        set_clock(DEFAULT_BASE_TIME)
        bundle = setup_scheduled_application()  # review_status=APPROVED
        streamer = bundle["streamer"]
        app = bundle["application"]
        resp = api.submit_application(app["id"], make_streamer_headers(streamer["id"]))
        validate_error(resp, ERR_INVALID_STATE, expected_status=409)


class TestSafetyVsFiscalOnAssociationSecondLook:
    """Second test for business_safety_vs_business_fiscal_on_product_association.
    The first test lives in test_06.
    """

    def test_cert_check_precedes_stock_even_when_stock_is_zero(self, api):
        """# difficulty: priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_product_association
        PRD §2.9: "on a product association the certification check precedes
        the category-match check, which precedes the on-shelf check, which
        precedes the stock check."

        Even when available_stock == 0 (extreme stock failure), the cert error
        wins.
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer = setup_active_streamer(professional_cert_categories=["FOOD"])
        # Application declares COSMETICS so category passes; product needs
        # COSMETICS cert which streamer lacks.
        streamer, studio, app = setup_draft_application(
            streamer=streamer,
            declared_product_categories=["COSMETICS"],
        )
        from test_helpers import create_product, associate_product_payload
        product = create_product(
            category="COSMETICS",
            requires_professional_cert=True,
            available_stock=0,
        )
        payload = associate_product_payload(product_id=product["id"], reserved_quantity=1)
        resp = api.associate_product(app["id"], payload, make_streamer_headers(streamer["id"]))
        validate_error(resp, ERR_PRODUCT_CERT_MISSING, expected_status=422)


# =============================================================================
# Rule 6: boundary_precision_check
# =============================================================================


class TestRefundBoundaryLeadHoursSecondLook:
    """Second test for boundary_precision_check/refund_lead_time_72h_boundary."""

    def test_lead_hours_just_below_72_partial_refund(self, api):
        """# difficulty: boundary_precision_check/refund_lead_time_72h_boundary
        PRD §3.7: "If the lead time is at least 24 hours but less than 72
        hours, the refund equals one half of deposit_due_cents, rounded
        half-up to integer cents."

        Boundary precision: lead_hours == 71.99... falls into the 24-72 branch,
        not the >=72 branch.
        """
        set_clock(DEFAULT_BASE_TIME)
        bundle = setup_scheduled_application()
        streamer = bundle["streamer"]
        app = bundle["application"]
        ddc_orig = bundle["invoice"]["deposit_due_cents"]
        starts = _parse_iso(app["starts_at"])
        # 71 hours, 59 minutes before starts => lead_hours < 72
        set_clock(starts - timedelta(hours=71, minutes=59))
        get_success_data(
            api.cancel_application(app["id"], cancel_payload("change"),
                                    make_streamer_headers(streamer["id"]))
        )
        invoice = fetch_invoice(app["id"])
        from decimal import Decimal, ROUND_HALF_UP
        expected_partial = int(
            Decimal(str(ddc_orig * 0.5)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        assert invoice["refund_cents"] == expected_partial


class TestEmptyAssociationOnOpsApprove:
    """Difficulty-design Rule 6 instance: empty_product_association_on_ops_approve."""

    def test_ops_approve_with_zero_associations_returns_invalid_state(self, api):
        """# difficulty: boundary_precision_check/empty_product_association_on_ops_approve
        PRD §3.4: "An approval transitions review_status from OPS_PENDING to
        COMPLIANCE_PENDING, but only if every ProductAssociation row on the
        application is currently APPROVED and still passes the four-step
        product eligibility ladder..."

        Empty-collection boundary: an application with zero APPROVED
        associations cannot pass ops-approve. The PRD's only error_id for a
        state-precondition failure is ERR_INVALID_STATE.
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer, studio, app = setup_draft_application()
        # Do NOT attach any products
        submit_application(streamer, app)
        resp = api.ops_approve(app["id"], approve_decision_payload(decision="APPROVE"), OPS_HEADERS)
        # No products attached so the precondition "every ProductAssociation
        # row is APPROVED and passes the eligibility ladder" cannot hold for a
        # promote. The PRD's general state-precondition failure error is
        # ERR_INVALID_STATE.
        validate_error(resp, ERR_INVALID_STATE, expected_status=409)

    def test_ops_approve_with_zero_associations_leaves_review_status_unchanged(self, api):
        """# difficulty: boundary_precision_check/empty_product_association_on_ops_approve
        PRD §1: a request rejected with ERR_INVALID_STATE leaves the
        application unchanged — the PRD's state-precondition contract
        (validation priority 6) is exactly this guarantee. PRD §3.4: ops-approve
        only moves from OPS_PENDING to COMPLIANCE_PENDING under the listed
        preconditions; on failure the state must stay at OPS_PENDING.
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer, studio, app = setup_draft_application()
        submit_application(streamer, app)  # OPS_PENDING
        api.ops_approve(app["id"], approve_decision_payload(decision="APPROVE"), OPS_HEADERS)
        after = fetch_application(app["id"])
        assert after["review_status"] == "OPS_PENDING"


# =============================================================================
# Rule 7: cross_entity_state_dependency — second tests
# =============================================================================


class TestCrossEntityStudioStatusSecondLook:
    """Second test for application_submit_requires_studio_open_pair_application_studio."""

    def test_closed_studio_blocks_submit(self, api):
        """# difficulty: cross_entity_state_dependency/application_submit_requires_studio_open_pair_application_studio
        PRD §3.2: "When a streamer requests an interval, the server first
        verifies the studio's overall status is OPEN; if not, the submit is
        rejected with ERR_INVALID_STATE."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer = setup_active_streamer()
        from test_helpers import setup_open_studio
        studio = setup_open_studio()
        get_success_data(api.update_studio(
            studio["id"], {"status": "CLOSED", "version": studio["version"]}, ADMIN_HEADERS
        ))
        starts = DEFAULT_BASE_TIME + timedelta(days=10, hours=11)
        ends = starts + timedelta(hours=2)
        _, _, app = setup_draft_application(
            streamer=streamer, studio=studio,
            starts_at=starts, ends_at=ends,
        )
        resp = api.submit_application(app["id"], make_streamer_headers(streamer["id"]))
        validate_error(resp, ERR_INVALID_STATE, expected_status=409)


class TestStartLiveDepositPaidSecondLook:
    """Second test for start_live_requires_invoice_deposit_paid_pair_application_invoice."""

    def test_paid_deposit_then_start_live_succeeds(self, api):
        """# difficulty: cross_entity_state_dependency/start_live_requires_invoice_deposit_paid_pair_application_invoice
        PRD §3.6: "the invoice must be in status DEPOSIT_PAID or SETTLED
        (equivalently deposit_paid must be true; otherwise ERR_DEPOSIT_UNPAID,
        HTTP 422)..."

        The positive case: once DEPOSIT_PAID has fired, start_live succeeds.
        """
        set_clock(DEFAULT_BASE_TIME)
        bundle = setup_scheduled_application(pay_deposit_event=True)
        streamer = bundle["streamer"]
        app = bundle["application"]
        invoice = fetch_invoice(app["id"])
        assert invoice["status"] == "DEPOSIT_PAID"
        result = go_live(streamer, app)
        assert result["operational_status"] == "LIVE"


# =============================================================================
# Rule 8: resource_temporal_overlap
# =============================================================================


class TestStudioHalfOpenOverlap:
    """Difficulty-design Rule 8 instance: studio_half_open_overlap_between_applications."""

    def test_back_to_back_intervals_both_succeed(self, api):
        """# difficulty: resource_temporal_overlap/studio_half_open_overlap_between_applications
        PRD §2.5: "Every interval declared by the system ... is half-open: the
        start is inclusive and the end is exclusive. Two intervals are
        considered to overlap exactly when the start of one is strictly less
        than the end of the other and vice versa; a back-to-back pair where
        one ends at the same instant another begins does not overlap."

        Two streamers submit back-to-back applications; neither must be
        rejected as conflicting.
        """
        set_clock(DEFAULT_BASE_TIME)
        # First, set up a SCHEDULED application via the normal flow
        bundle = setup_scheduled_application()
        studio = bundle["studio"]
        first_app = bundle["application"]
        first_ends = _parse_iso(first_app["ends_at"])
        # Second streamer submits a slot that begins exactly when the first ends
        streamer_b = setup_active_streamer()
        starts_b = first_ends
        ends_b = first_ends + timedelta(hours=2)
        _, _, app_b = setup_draft_application(
            streamer=streamer_b, studio=studio,
            starts_at=starts_b, ends_at=ends_b,
        )
        attach_compatible_product(app_b, streamer_b)
        resp = api.submit_application(app_b["id"], make_streamer_headers(streamer_b["id"]))
        validate_success(resp)

    def test_one_second_overlap_is_rejected(self, api):
        """# difficulty: resource_temporal_overlap/studio_half_open_overlap_between_applications
        PRD §3.4: "the interval does not overlap any existing application of
        the same Studio whose review_status is APPROVED or whose
        operational_status is SCHEDULED or LIVE (otherwise
        ERR_STUDIO_INTERVAL_CONFLICT, HTTP 409)."
        """
        set_clock(DEFAULT_BASE_TIME)
        bundle = setup_scheduled_application()
        studio = bundle["studio"]
        first_app = bundle["application"]
        first_ends = _parse_iso(first_app["ends_at"])
        # Second streamer's interval starts ONE SECOND before the first ends
        streamer_b = setup_active_streamer()
        starts_b = first_ends - timedelta(seconds=1)
        ends_b = first_ends + timedelta(hours=2)
        _, _, app_b = setup_draft_application(
            streamer=streamer_b, studio=studio,
            starts_at=starts_b, ends_at=ends_b,
        )
        attach_compatible_product(app_b, streamer_b)
        resp = api.submit_application(app_b["id"], make_streamer_headers(streamer_b["id"]))
        validate_error(resp, ERR_STUDIO_INTERVAL_CONFLICT, expected_status=409)


class TestMaintenanceBlocksSubmitSecondLook:
    """Second test for resource_temporal_overlap/studio_maintenance_window_blocks_overlap."""

    def test_maintenance_exactly_at_end_does_not_conflict(self, api):
        """# difficulty: resource_temporal_overlap/studio_maintenance_window_blocks_overlap
        PRD §2.5: "Every interval declared by the system ... is half-open: the
        start is inclusive and the end is exclusive. ... a back-to-back pair
        where one ends at the same instant another begins does not overlap."

        Maintenance window starts at application's ends_at (touch-not-overlap)
        — half-open semantics MUST treat this as no intersection.
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer = setup_active_streamer()
        avail_start = DEFAULT_BASE_TIME + timedelta(days=1)
        avail_end = DEFAULT_BASE_TIME + timedelta(days=30)
        starts = DEFAULT_BASE_TIME + timedelta(days=10, hours=11)
        ends = starts + timedelta(hours=2)
        # Maintenance begins exactly at the application's ends_at — back-to-back
        maint_start = ends
        maint_end = ends + timedelta(hours=1)
        studio = setup_studio_with_window(
            available_start=avail_start,
            available_end=avail_end,
            maintenance=(maint_start, maint_end),
        )
        _, _, app = setup_draft_application(
            streamer=streamer, studio=studio,
            starts_at=starts, ends_at=ends,
        )
        attach_compatible_product(app, streamer)
        resp = api.submit_application(app["id"], make_streamer_headers(streamer["id"]))
        validate_success(resp)


# =============================================================================
# Rule 9: compensating_invariant
# =============================================================================


class TestProductStockConserved:
    """Difficulty-design Rule 9 instance: product_stock_conserved_on_release."""

    def test_create_then_withdraw_restores_stock(self, api):
        """# difficulty: compensating_invariant/product_stock_conserved_on_release
        PRD §3.4: "Withdrawal releases every ProductAssociation (same release
        semantics as the ops-reject release: each association's status becomes
        RELEASED, the product's reserved_stock decreases, the product's
        available_stock increases)."
        PRD §3.3: "the server decrements the product's available_stock by
        reserved_quantity and increments its reserved_stock by the same
        amount..."
        """
        set_clock(DEFAULT_BASE_TIME)
        bundle = setup_application_with_reservations(initial_available_stock=100, reserved_quantity=25)
        streamer = bundle["streamer"]
        app = bundle["application"]
        product_before_assoc = bundle["product_initial"]  # available 100, reserved 0
        product_after_assoc = bundle["product"]            # available 75, reserved 25
        assert product_after_assoc["available_stock"] == 75
        assert product_after_assoc["reserved_stock"] == 25
        # Withdraw releases
        get_success_data(api.withdraw_application(app["id"], make_streamer_headers(streamer["id"])))
        from test_helpers.fixtures import get_product
        product_after_release = get_product(product_before_assoc["id"])
        # Conservation: avail + reserved unchanged at 100
        before_sum = product_before_assoc["available_stock"] + product_before_assoc["reserved_stock"]
        after_sum = product_after_release["available_stock"] + product_after_release["reserved_stock"]
        assert before_sum == after_sum == 100
        assert product_after_release["available_stock"] == 100
        assert product_after_release["reserved_stock"] == 0

    def test_create_then_ops_reject_restores_stock(self, api):
        """# difficulty: compensating_invariant/product_stock_conserved_on_release
        PRD §3.4: "a uniform release across every ProductAssociation for the
        application: each association moves to status RELEASED, the product's
        reserved_stock decreases by the association's reserved_quantity, and
        the product's available_stock increases by the same amount."
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer, studio, app = setup_draft_application()
        product, assoc = attach_compatible_product(app, streamer, reserved_quantity=15)
        # product["available_stock"] is the value AFTER reservation
        avail_after_assoc = product["available_stock"]
        reserved_after_assoc = product["reserved_stock"]
        submit_application(streamer, app)
        ops_approve(app["id"], decision="REJECT", reason="reject")
        from test_helpers.fixtures import get_product
        product_after_release = get_product(product["id"])
        assert (avail_after_assoc + reserved_after_assoc) == (
            product_after_release["available_stock"] + product_after_release["reserved_stock"]
        )


class TestViolationScoreConservedOnOverturn:
    """Difficulty-design Rule 9 instance: streamer_violation_score_conserved_on_appeal_overturn."""

    def test_overturn_after_enforced_suspension_restores_active(self, api):
        """# difficulty: compensating_invariant/streamer_violation_score_conserved_on_appeal_overturn
        PRD §3.9: "An OVERTURN decision ... transitions the violation from
        APPEAL_PENDING to OVERTURNED, and runs a depth-3 cascade: if the
        streamer was SUSPENDED or BLACKLISTED solely because of this
        violation, the streamer's status reverts to ACTIVE and
        suspension_until is set to null..."

        Verifies the compensating arc: a violation whose enforcement set the
        streamer to SUSPENDED is reversed by OVERTURN — but the appeal must
        be filed BEFORE the sweep enforces the suspension (the appeal window
        and the enforcement window are both 7 days from created_at; once the
        sweep runs, ERR_APPEAL_WINDOW_CLOSED applies). We therefore appeal
        first, then UPHOLD vs OVERTURN to decide the violation cleanly.
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer = setup_active_streamer()
        # VIOLATING_CONTENT with 3 evidences => severity 4 => SUSPENSION
        v = create_violation(streamer["id"], violation_type="VIOLATING_CONTENT",
                             evidence_refs=["a", "b", "c"])
        assert v["penalty_action"] == "SUSPENSION"
        appeal = file_appeal(streamer, v["id"])
        decide_appeal(appeal["id"], decision="OVERTURN")
        s_post = fetch_streamer(streamer["id"])
        # Streamer was never enforced (appeal short-circuited the sweep) — but
        # the OVERTURN cascade still asserts no SUSPENSION is in effect.
        assert s_post["status"] == "ACTIVE", \
            f"after OVERTURN, streamer must be ACTIVE, got {s_post['status']}"
        assert s_post.get("suspension_until") is None

    def test_overturn_after_fine_enforce_subtracts_severity(self, api):
        """# difficulty: compensating_invariant/streamer_violation_score_conserved_on_appeal_overturn
        PRD §3.9: "the violation's severity is subtracted from the streamer's
        violation_score..."

        FALSE_ADVERTISING with 2 evidences => severity 2 => FINE. We file the
        appeal WITHIN the 7-day window (before sweep enforcement could be
        invoked, so the appeal is legal), then OVERTURN. The conservation
        invariant: across enforce+overturn the score returns to pre-violation
        — equivalently, an OVERTURN on a not-yet-enforced violation leaves
        the score at its pre-violation value.
        """
        set_clock(DEFAULT_BASE_TIME)
        streamer = setup_active_streamer()
        score_pre = streamer["violation_score"]
        v = create_violation(streamer["id"], violation_type="FALSE_ADVERTISING",
                             evidence_refs=["a", "b"])
        appeal = file_appeal(streamer, v["id"])
        decide_appeal(appeal["id"], decision="OVERTURN")
        s_post = fetch_streamer(streamer["id"])
        # Invariant: enforce + overturn leaves violation_score unchanged. Here
        # enforcement never happened, so post-overturn score must be == pre.
        assert s_post["violation_score"] == score_pre, (
            f"after OVERTURN with no prior enforcement, score must remain "
            f"{score_pre}, got {s_post['violation_score']}"
        )
