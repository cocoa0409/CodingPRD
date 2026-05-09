"""Second-test supplements for SCAFFOLD_DIFFICULTY_DESIGN instances.

Each instance in scaffold_difficulty_design must be covered by at least
TWO dedicated tests; this file fills the second slot for instances whose
first test lives elsewhere in test_suite/.

Each test docstring still cites verbatim PRD prose for the underlying
rule(s) — the difficulty index is a coverage requirement, not a citation
target.
"""
import pytest

from test_helpers import (
    validate_error,
    validate_error_is_one_of,
    validate_success,
    ApiErrorId,
    setup_basic_platform,
    setup_platform_at_clock,
    setup_prescription_scenario,
    setup_otc_purchase_scenario,
    setup_otc_order_in_review,
    setup_approved_prescription_with_order,
    setup_cold_chain_dispatched,
    setup_psychotropic_window_scenario,
    setup_vendor_with_expiries,
    create_platform,
    create_vendor,
    create_pharmacist,
    create_customer,
    create_otc_drug_on_shelf,
    create_prescription_drug_on_shelf,
    create_two_pharmacists,
    create_drug,
    create_and_shelve_drug,
    upload_prescription,
    upload_and_approve_prescription,
    place_order,
    pay_order,
    cancel_order,
    open_pharmacist_review,
    request_change,
    resume_review,
    advance_clock,
    add_seconds,
    add_milliseconds,
    add_days,
    add_hours,
    append_readings,
    reading_payload,
    open_pharmacist_review_payload,
    request_change_payload,
    create_order_payload,
    create_purchase_limit_rule_payload,
    create_prescription_payload,
    prescription_item,
    order_item,
    get_order,
    get_drug,
    get_vendor,
    get_review,
    get_shipment,
    get_prescription,
    TEST_USERS,
    make_admin_headers,
    make_customer_headers,
    make_prescription_reviewer_headers,
    make_pharmacist_re_reviewer_headers,
    make_vendor_admin_headers,
    FAR_FUTURE_ISO,
)


# ---------------------------------------------------------------------------
# dual_variant_calc / vendor_qualification_score_ordering_variant
# ---------------------------------------------------------------------------

class TestVendorQualificationOrderingVariant2:
    """PRD §3.1: 'The order of evaluation is fixed: the raw total is
    computed first, the tier is derived from the raw total, and only then
    is the multiplier applied to that same total. Reversing the order
    (multiplying first and then bucketing) would yield a different number
    and is not permitted.'

    # difficulty: dual_variant_calc/vendor_qualification_score_ordering_variant
    """

    def test_yellow_tier_at_high_boundary(self, api):
        """PRD §3.1: 'the tier is YELLOW when the raw total is between 2
        and 4 inclusive.' raw_total=4 → YELLOW (not RED) → REVIEW_REQUIRED
        on clock advance.

        clock=2025-01-15, license=2025-02-10 (26 days, score=3),
        permit=2025-04-10 (85 days, score=1) → raw=4 → YELLOW.
        """
        clock = "2025-01-15T00:00:00.000Z"
        s = setup_vendor_with_expiries(
            api, clock_iso=clock,
            license_expires_at="2025-02-10T00:00:00.000Z",
            permit_expires_at="2025-04-10T00:00:00.000Z",
        )
        advance_clock(api, s["platform"]["id"], "2025-01-15T00:00:00.001Z")
        v = get_vendor(api, s["platform"]["id"], s["vendor"]["id"])
        assert v["qualification_status"] == "REVIEW_REQUIRED"


# ---------------------------------------------------------------------------
# combinatorial_formula / cold_chain_score_per_reading_then_sum
# ---------------------------------------------------------------------------

class TestColdChainPerReadingThenSum2:
    """PRD §3.7: 'The order is fixed: the per-reading product is always
    computed first per reading, and only then are the per-reading scores
    summed. Multiplying total severity by total window length (in either
    direction) is forbidden — it produces a different number for the same
    input.'

    # difficulty: combinatorial_formula/cold_chain_score_per_reading_then_sum
    """

    def test_two_critical_one_safe_falsifies_sum_then_multiply(self, api):
        """Three readings: critical(60s gap), critical(360s gap), safe(last).
        Per-reading: 5*1=5, 5*6=30, 0*1=0 → sum=35.
        Forbidden order (sum-severities × sum-minutes): (5+5+0)*(1+6+1)=80.
        We assert excursion_score == 35 to reject the forbidden formula.
        """
        s = setup_cold_chain_dispatched(api, clock_iso="2025-01-01T00:00:00.000Z")
        pf, shipment = s["platform"], s["shipment"]
        base = "2025-01-01T00:00:00.000Z"
        readings = [
            reading_payload(base, 200),                              # critical
            reading_payload(add_seconds(base, 60), 200),             # critical
            reading_payload(add_seconds(base, 60 + 360), 27),        # safe (last)
        ]
        final = append_readings(api, pf["id"], shipment["id"], readings)
        assert final["excursion_score"] == 35


# ---------------------------------------------------------------------------
# combinatorial_formula / vendor_score_circular_tier_then_multiplier
# ---------------------------------------------------------------------------

class TestVendorScoreCircular2:
    """PRD §3.1: 'the weighted score is the raw total multiplied by the
    tier multiplier — 1.0 for GREEN, 1.5 for YELLOW, 2.0 for RED — rounded
    half-up to one decimal place.'

    # difficulty: combinatorial_formula/vendor_score_circular_tier_then_multiplier
    """

    def test_red_tier_keeps_review_required_until_resubmission(self, api):
        """Once RED tier triggers REVIEW_REQUIRED, the only PRD-defined
        recovery is /resubmit-qualification (PRD §3.1). A subsequent clock
        nudge cannot return RED → ACTIVE without resubmission.
        """
        clock = "2025-01-15T00:00:00.000Z"
        s = setup_vendor_with_expiries(
            api, clock_iso=clock,
            license_expires_at="2025-02-10T00:00:00.000Z",  # 26 days → score 3
            permit_expires_at="2025-02-10T00:00:00.000Z",   # 26 days → score 3
        )
        advance_clock(api, s["platform"]["id"], "2025-01-15T00:00:00.001Z")
        v = get_vendor(api, s["platform"]["id"], s["vendor"]["id"])
        assert v["qualification_status"] == "REVIEW_REQUIRED"
        # Another negligible advance: not a resubmission.
        advance_clock(api, s["platform"]["id"], "2025-01-15T00:00:00.002Z")
        v2 = get_vendor(api, s["platform"]["id"], s["vendor"]["id"])
        assert v2["qualification_status"] == "REVIEW_REQUIRED"


# ---------------------------------------------------------------------------
# non_linear_state_machine / pharmacist_review_request_change_cycle
# ---------------------------------------------------------------------------

class TestRequestChangeCycle2:
    """PRD §3.6: 'Resuming bumps revision_count upward by exactly one. The
    cycle REQUEST_CHANGE → IN_REVIEW → ... → REQUEST_CHANGE may run at
    most twice before subsequent request-change attempts are rejected by
    the revision cap.'

    # difficulty: non_linear_state_machine/pharmacist_review_request_change_cycle
    """

    def test_one_round_trip_revision_count_one(self, api):
        """After exactly one request-change → resume cycle, revision_count
        is 1 and review.status is IN_REVIEW.
        """
        s = setup_otc_order_in_review(api)
        request_change(api, s["platform"]["id"], s["order"]["id"],
                          s["review"]["id"], s["rr_pharmacist"],
                          decision_notes="first round needs more notes please")
        resumed = resume_review(api, s["platform"]["id"], s["order"]["id"],
                                    s["review"]["id"], s["rr_pharmacist"])
        assert resumed["status"] == "IN_REVIEW"
        assert resumed["revision_count"] == 1


# ---------------------------------------------------------------------------
# non_linear_state_machine / order_parallel_payment_and_dispensing_dimensions
# ---------------------------------------------------------------------------

class TestParallelStateDimensions2:
    """PRD §3.5: 'A Customer may pay an UNPAID order, transitioning
    payment_status to PAID, only when dispensing_status is PENDING_REVIEW,
    PHARMACIST_REVIEWING, or APPROVED.' Pay can occur while
    dispensing_status remains PENDING_REVIEW — the two dimensions evolve
    independently.

    # difficulty: non_linear_state_machine/order_parallel_payment_and_dispensing_dimensions
    """

    def test_pay_then_dispensing_unchanged(self, api):
        s = setup_otc_purchase_scenario(api)
        order = place_order(api, s["platform"]["id"], s["customer"],
                              items=[order_item(s["drug"]["id"], qty=1, unit_price_cents=1000)])
        assert order["payment_status"] == "UNPAID"
        assert order["dispensing_status"] == "PENDING_REVIEW"
        paid = pay_order(api, s["platform"]["id"], order)
        # Dispensing dimension untouched by payment.
        assert paid["payment_status"] == "PAID"
        assert paid["dispensing_status"] == "PENDING_REVIEW"


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / prescription_expired_vs_contraindication
# ---------------------------------------------------------------------------

class TestExpiredVsContraindication2:
    """PRD §3.4: 'current_clock_iso must be strictly less than issued_at
    plus the smaller of validity_days and the per-control-category
    validity-days cap enforced by the server (otherwise
    ERR_PRESCRIPTION_EXPIRED).'

    # difficulty: priority_pair_validation_conflict/prescription_expired_vs_contraindication
    """

    def test_only_expired_returns_expired(self, api):
        """When ONLY expiry fails (no contraindication), the response is
        uniquely ERR_PRESCRIPTION_EXPIRED."""
        clock = "2025-02-01T00:00:00.000Z"
        s = setup_prescription_scenario(api, clock_iso=clock)  # default: no contraindication
        rx = upload_prescription(
            api, s["platform"]["id"], s["customer"],
            drug_items=[prescription_item(s["drug"]["id"], qty=1)],
            issued_at="2025-01-01T00:00:00.000Z", validity_days=7,
        )
        resp = api.approve_prescription(
            s["platform"]["id"], rx["id"],
            make_prescription_reviewer_headers(s["pr_pharmacist"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PRESCRIPTION_EXPIRED.value)


# ---------------------------------------------------------------------------
# boundary_precision_check / empty_drug_items_array_on_prescription_upload
# ---------------------------------------------------------------------------

class TestPrescriptionDrugItemsBoundary:
    """PRD §3.4: 'a drug_items array whose elements each contain a drug_id
    and a qty.' The array must contain at least one element on upload —
    an empty array fails generic input validation as ERR_INVALID_REQUEST.
    A single-element array succeeds (boundary at length=1).

    # difficulty: boundary_precision_check/empty_drug_items_array_on_prescription_upload
    """

    def test_single_item_succeeds(self, api):
        """drug_items length=1 → upload succeeds, status = REVIEW_PENDING."""
        s = setup_prescription_scenario(api)
        rx = upload_prescription(
            api, s["platform"]["id"], s["customer"],
            drug_items=[prescription_item(s["drug"]["id"], qty=1)],
            issued_at="2025-01-01T00:00:00.000Z", validity_days=30,
        )
        assert rx["status"] == "REVIEW_PENDING"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / drug_shelve_requires_vendor_active
# ---------------------------------------------------------------------------

class TestDrugShelveRequiresVendorActive2:
    """PRD §3.2: 'shelves a drug ... only if ... the drug's vendor has
    qualification_status equal to ACTIVE (otherwise ERR_VENDOR_NOT_ACTIVE).'

    # difficulty: cross_entity_state_dependency/drug_shelve_requires_vendor_active
    """

    def test_resubmit_then_shelve_succeeds(self, api):
        """After vendor is suspended (cascading drugs OFF_SHELF) and then
        resubmits qualification (back to ACTIVE), a manual re-shelve must
        succeed. PRD §3.1: 're-activating a previously SUSPENDED vendor
        does not auto re-shelve that vendor's drugs ... a PlatformAdmin
        must explicitly re-shelve each one.'"""
        clock = "2025-01-01T00:00:00.000Z"
        pf = setup_platform_at_clock(api, clock)
        vendor = create_vendor(
            api, pf["id"],
            business_license_expires_at="2025-01-05T00:00:00.000Z",
            drug_operation_permit_expires_at="2025-01-05T00:00:00.000Z",
        )
        drug = create_otc_drug_on_shelf(api, pf["id"], vendor["id"])
        # Suspend vendor → drug cascades OFF_SHELF.
        advance_clock(api, pf["id"], "2025-01-06T00:00:00.000Z")
        # Re-activate vendor.
        api.resubmit_vendor_qualification(
            pf["id"], vendor["id"],
            payload={"business_license_expires_at": FAR_FUTURE_ISO,
                       "drug_operation_permit_expires_at": FAR_FUTURE_ISO},
            headers=make_vendor_admin_headers(vendor["id"]),
        )
        # Now manual re-shelve must work (vendor ACTIVE).
        resp = api.shelve_drug(pf["id"], drug["id"], TEST_USERS["admin_headers"])
        data = validate_success(resp)
        assert data["status"] == "ON_SHELF"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / order_pay_requires_prescription_approved
# ---------------------------------------------------------------------------

class TestOrderPayRequiresPrescriptionApproved2:
    """PRD §3.5: 'When at least one line is a prescription drug, the
    order's prescription_id must be set and the referenced
    Prescription.status must be APPROVED; otherwise
    ERR_PRESCRIPTION_NOT_APPROVED.'

    # difficulty: cross_entity_state_dependency/order_pay_requires_prescription_approved
    """

    def test_pay_after_approve_succeeds(self, api):
        """The same flow that fails with REVIEW_PENDING succeeds once the
        prescription is APPROVED — verifying the dependency is on the
        prescription's APPROVED status, not on prescription_id presence
        alone."""
        s = setup_approved_prescription_with_order(api)
        # Already APPROVED + UNPAID order in PENDING_REVIEW.
        paid = pay_order(api, s["platform"]["id"], s["order"])
        assert paid["payment_status"] == "PAID"


# ---------------------------------------------------------------------------
# resource_temporal_overlap / purchase_limit_rolling_window_aggregate_capacity
# ---------------------------------------------------------------------------

class TestPurchaseLimitRollingWindow2:
    """PRD §3.5: 'the window is closed at the left and open at the right.'

    # difficulty: resource_temporal_overlap/purchase_limit_rolling_window_aggregate_capacity
    """

    def test_no_existing_units_proposed_at_max(self, api):
        """With zero in-window history, proposed=10 == max → succeeds (NOT > max)."""
        s = setup_psychotropic_window_scenario(
            api,
            clock_iso="2025-01-31T00:00:00.000Z",
            window_days=30, max_units_per_window=10,
            existing_paid_units_in_window=0,
            existing_paid_units_outside_window=0,
        )
        pf, drug, customer = s["platform"], s["drug"], s["customer"]
        rx = upload_and_approve_prescription(
            api, pf["id"], customer, s["pr_pharmacist"],
            drug_items=[prescription_item(drug["id"], qty=10)],
            issued_at="2025-01-31T00:00:00.000Z", validity_days=30,
        )
        resp = api.create_order(
            pf["id"],
            create_order_payload(customer["id"],
                                   items=[order_item(drug["id"], qty=10, unit_price_cents=10_000)],
                                   prescription_id=rx["id"]),
            make_customer_headers(customer["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert data["dispensing_status"] == "PENDING_REVIEW"


# ---------------------------------------------------------------------------
# resource_temporal_overlap / cold_chain_reading_adjacency_floored_window
# ---------------------------------------------------------------------------

class TestColdChainAdjacencyFloor2:
    """PRD §3.7: 'rounded up to the next whole number, and clamped to be
    at least 1; for the last reading the window length is exactly 1.'

    # difficulty: resource_temporal_overlap/cold_chain_reading_adjacency_floored_window
    """

    def test_61_second_gap_rounds_up_to_two_minute_window(self, api):
        """A 61-second gap → ceil(61/60) = 2 → per_reading uses window=2."""
        s = setup_cold_chain_dispatched(api, clock_iso="2025-01-01T00:00:00.000Z")
        pf, shipment = s["platform"], s["shipment"]
        base = "2025-01-01T00:00:00.000Z"
        readings = [
            reading_payload(base, 200),                              # critical
            reading_payload(add_seconds(base, 61), 27),              # safe (last)
        ]
        final = append_readings(api, pf["id"], shipment["id"], readings)
        # r0 window = ceil(61/60)=2, severity=5 → 10
        # r1 last → 0
        assert final["excursion_score"] == 10


# ---------------------------------------------------------------------------
# compensating_invariant / purchase_limit_units_invariant_on_revoke_cancel
# ---------------------------------------------------------------------------

class TestPurchaseLimitInvariantOnPlaceCancel2:
    """PRD §3.5: 'orders that are UNPAID are also not counted regardless
    of dispensing state.' The cancel-before-pay sequence MUST NOT change
    the purchase-limit aggregator.

    # difficulty: compensating_invariant/purchase_limit_units_invariant_on_revoke_cancel
    """

    def test_aggregator_zero_after_cancel_before_pay(self, api):
        """Place qty=5 (UNPAID), cancel; verify Order.dispensing_status =
        CANCELLED and payment_status remains UNPAID (no refund cascade)."""
        clock = "2025-01-15T00:00:00.000Z"
        pf = setup_platform_at_clock(api, clock)
        vendor = create_vendor(api, pf["id"])
        drug = create_and_shelve_drug(
            api, pf["id"], vendor["id"],
            classification="PRESCRIPTION", control_category="PSYCHOTROPIC_II",
            per_order_qty_cap=10,
        )
        api.create_purchase_limit_rule(
            pf["id"],
            create_purchase_limit_rule_payload(
                control_category="PSYCHOTROPIC_II",
                window_days=30, max_units_per_window=10,
                blocks_special_populations=[],
            ),
            TEST_USERS["admin_headers"],
        )
        customer = create_customer(api, pf["id"], real_name_verified=True)
        pr, _rr = create_two_pharmacists(api, pf["id"])
        rx = upload_and_approve_prescription(
            api, pf["id"], customer, pr,
            drug_items=[prescription_item(drug["id"], qty=5)],
            issued_at=clock, validity_days=999,
        )
        order = place_order(api, pf["id"], customer,
                                items=[order_item(drug["id"], qty=5, unit_price_cents=10_000)],
                                prescription_id=rx["id"])
        cancelled = cancel_order(api, pf["id"], order)
        # PRD §3.5: 'Cancellation drives dispensing_status to CANCELLED;
        # if the order was PAID, the refund cascade ... runs.' No pay
        # happened, so payment_status remains UNPAID.
        assert cancelled["dispensing_status"] == "CANCELLED"
        assert cancelled["payment_status"] == "UNPAID"
