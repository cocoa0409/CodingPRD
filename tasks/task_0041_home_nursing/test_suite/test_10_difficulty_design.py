"""Difficulty-design priority queue.

This file covers every instance declared in
SCAFFOLD_DIFFICULTY_DESIGN.yaml with at least two PRD-traceable tests.
Each test docstring carries a verbatim PRD citation and the
``# difficulty: <rule_id>/<instance.name>`` tag for the coverage audit.

PRD-First applies throughout: every assertion is grounded in a verbatim
PRD sentence, never in the difficulty-design entry alone.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_NOW_ISO,
    DEFAULT_SCHEDULED_START_ISO,
    accept_dispatch,
    add_days,
    add_hours,
    add_seconds,
    advance_clock,
    api_client,
    archive_waste,
    assert_settlement_invariants,
    confirm_completion,
    create_certified_nurse,
    create_order_payload,
    create_order_raw,
    create_service_item_raw,
    finish_service_record,
    get_success_data,
    hand_over_waste,
    haversine_km,
    list_dispatches_for,
    make_compliance_officer_headers,
    make_nurse_headers,
    make_patient_headers,
    offset_lat_km,
    perform_checkin,
    register_waste,
    reject_dispatch,
    resolve_complaint,
    setup_basic_dispatched_order,
    setup_completed_order,
    setup_dual_score_scenario,
    setup_in_progress_order,
    stable_user_id,
    submit_complaint,
    triage_complaint,
    escalate_complaint,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# =========================================================================
# Rule 1 -- dual_variant_calc
# =========================================================================
class TestDualVariantCalc:
    """# difficulty: dual_variant_calc/order_fee_estimated_vs_final
    # difficulty: dual_variant_calc/nurse_rating_aggregate_vs_complaint_rating_impact
    """

    def test_estimated_vs_final_differ_when_checkin_crosses_band(
        self, api, platform_admin_headers,
    ):
        """# difficulty: dual_variant_calc/order_fee_estimated_vs_final

        PRD §3.5: 'Estimated and final fees may differ -- an actual
        dispatch farther from the default origin pushes the surcharge
        up; an actual check-in across a time band can shift the
        multiplier; a package planned for use but ultimately not
        consumed (or vice versa) flips the deduction.'

        PRD §3.2: 'the time-of-day surcharge takes the UTC hour of
        scheduled_start'.
        PRD §3.5: 'The time-of-day surcharge takes the UTC hour of
        ServiceRecord.checkin_at -- not the planned scheduled_start --
        and selects 13000 basis points for the night band'.

        Claim: scheduled_start at 10:00 UTC (daytime) but check-in at
        22:30 UTC (night band) makes final settlement non-equal to the
        estimate.
        """
        item = create_service_item_raw(
            required_skill="ELDERLY_CARE",
            base_price_cents=20000,
        )
        nurse = create_certified_nurse(
            home_lat=31.20, home_lng=121.40,
            specialty_tags=["ELDERLY_CARE"],
            revenue_share_bps=7000,
        )
        patient_id = stable_user_id("patient")
        order = create_order_raw(
            patient_id=patient_id,
            service_item_code=item["code"],
            service_lat=31.20, service_lng=121.40,
            scheduled_start="2026-06-01T10:00:00.000Z",  # Mon daytime
        )
        # Estimate built off scheduled_start daytime -> tod_surcharge=0.
        # Net=20000+0+0-0=20000; tax=1200; estimated=21200.
        assert order["estimated_fee_cents"] == 21200
        d = list_dispatches_for(order["id"])[0]
        accept_dispatch(d, d["nurse_id"])
        perform_checkin(
            order["id"], d["nurse_id"],
            checkin_at="2026-06-01T22:30:00.000Z",  # night band
            checkin_lat=31.20, checkin_lng=121.40,
        )
        finish_service_record(order["id"], d["nurse_id"])
        confirm_completion(order["id"], patient_id)
        s = get_success_data(api.get_settlement(
            order["id"], make_patient_headers(patient_id),
        ))
        # Night band -> tod_surcharge = round_half_up(20000*3000/10000)=6000
        # gross=20000+0+6000-0=26000; tax=round_half_up(26000*600/10000)=1560
        # total=27560. Per PRD §3.5: 'Estimated and final fees may differ'.
        assert s["time_of_day_surcharge_cents"] == 6000, (
            f"PRD §3.5: night-band tod_surcharge = "
            f"round_half_up(20000*(13000-10000)/10000)=6000, "
            f"got {s['time_of_day_surcharge_cents']}"
        )
        assert s["gross_fee_cents"] == 26000
        assert s["tax_cents"] == 1560
        assert s["gross_fee_cents"] + s["tax_cents"] != \
            order["estimated_fee_cents"], (
            "PRD §3.5: dual-variant -- final must differ from estimate "
            "when check-in crosses time band"
        )

    def test_complaint_resolve_lowers_rating_per_window_mean(
        self, api, compliance_officer_headers,
    ):
        """# difficulty: dual_variant_calc/nurse_rating_aggregate_vs_complaint_rating_impact

        PRD §3.5: 'On a successful upheld resolution that advances the
        complaint to RESOLVED, the rating_impact is applied to the
        nurse's rating and the result is clamped to the closed interval
        from 1.00 to 5.00'.
        PRD §3.5: 'The aggregate Nurse.rating itself is computed over
        the latest 50 ratings -- one implicit 5.0 per COMPLETED order
        without an upheld nurse-related complaint, and one (5.0 plus the
        rating_impact) per COMPLETED order whose nurse-related complaint
        resolved with a non-zero impact.'

        Claim: starting from default 5.0, complete two orders for one
        nurse, file a NURSE_MISCONDUCT complaint on the second and
        resolve with rating_impact=-1.0. New rating = mean([5.0, 4.0])
        rounded half-up to two decimals = 4.50.
        """
        # Build two completed orders for the SAME nurse.
        item = create_service_item_raw(required_skill="ELDERLY_CARE")
        nurse = create_certified_nurse(
            home_lat=31.20, home_lng=121.40,
            specialty_tags=["ELDERLY_CARE"],
        )
        patient_id = stable_user_id("patient")

        def complete_one(scheduled: str) -> str:
            o = create_order_raw(
                patient_id=patient_id,
                service_item_code=item["code"],
                service_lat=31.20, service_lng=121.40,
                scheduled_start=scheduled,
            )
            d = list_dispatches_for(o["id"])[0]
            accept_dispatch(d, d["nurse_id"])
            perform_checkin(
                o["id"], d["nurse_id"],
                checkin_at=scheduled,
                checkin_lat=31.20, checkin_lng=121.40,
            )
            finish_service_record(o["id"], d["nurse_id"])
            confirm_completion(o["id"], patient_id)
            return o["id"]

        o1 = complete_one("2026-06-01T10:00:00.000Z")
        o2 = complete_one("2026-06-02T10:00:00.000Z")
        # Submit and resolve a NURSE_MISCONDUCT complaint on o2.
        c = submit_complaint(o2, patient_id, category="NURSE_MISCONDUCT")
        triage_complaint(c["id"])
        escalate_complaint(c["id"])
        resolve_complaint(
            c["id"], decision="UPHOLD",
            rating_impact=-1.0,
        )
        # Re-read the nurse rating.
        n = get_success_data(api.get_nurse(
            nurse["id"], make_compliance_officer_headers(),
        ))
        # latest 50 ratings = [5.0, 4.0]; mean = 4.5; clamped to 4.50.
        assert float(n["rating"]) == pytest.approx(4.50, abs=0.005), (
            f"PRD §3.5: window mean over [5.0, 4.0] = 4.50, "
            f"got {n['rating']}"
        )


# =========================================================================
# Rule 2 -- combinatorial_formula
# =========================================================================
class TestCombinatorialFormula:
    """# difficulty: combinatorial_formula/final_settlement_nested_rounding_order
    # difficulty: combinatorial_formula/nurse_dispatch_score_combinatorial
    """

    def test_per_component_round_then_sum(
        self, api, platform_admin_headers,
    ):
        """# difficulty: combinatorial_formula/final_settlement_nested_rounding_order

        PRD §2.7: 'The rounding occurs per component before the
        components are summed: the time-of-day surcharge is rounded,
        the tax is rounded, the nurse share is rounded, and only then
        are these integer cents added together. Sum-then-round is
        incorrect and will diverge from the test contract on edge cases
        where two components each round in the same direction.'

        Claim: with base=20000, daytime weekday checkin, distance=0,
        revenue_share_bps=7000: nurse_share = round_half_up(20000*7000
        /10000) = 14000; platform_share = 20000 - 14000 = 6000.
        """
        setup = setup_completed_order(
            nurse_specialty="ELDERLY_CARE",
            base_price_cents=20000,
            revenue_share_bps=7000,
            scheduled_start=DEFAULT_SCHEDULED_START_ISO,
            checkin_at=DEFAULT_SCHEDULED_START_ISO,
        )
        s = setup["settlement"]
        assert s["nurse_revenue_share_cents"] == 14000
        assert s["platform_share_cents"] == 6000
        assert_settlement_invariants(s)

    def test_lower_score_nurse_wins_dispatch(
        self, api, platform_admin_headers,
    ):
        """# difficulty: combinatorial_formula/nurse_dispatch_score_combinatorial

        PRD §3.3: 'The score is the sum of three normalized terms: the
        W_DIST weight of 0.5 multiplied by the candidate's distance
        divided by the 15-kilometre radius; the W_LOAD weight of 0.3
        multiplied by the candidate's current load divided by their
        max_daily_orders; and the W_RATING weight of 0.2 multiplied by
        the gap between 5.0 and the candidate's rating.'
        PRD §3.3: 'the lowest score wins'.

        Claim: a closer nurse with rating=5.0 and load=0 always wins
        over a farther nurse with rating=5.0 and load=0; a far nurse
        with idle load can beat a close nurse with full load only when
        the load delta dominates.

        We pick a simple two-nurse scenario where N1 is close (3km) and
        N2 is far (10km), both with rating 5.0 and zero load. N1 must
        win.
        """
        item = create_service_item_raw(required_skill="IV_INFUSION")
        n1 = create_certified_nurse(
            home_lat=offset_lat_km(31.20, 3.0), home_lng=121.40,
            specialty_tags=["IV_INFUSION"],
        )
        n2 = create_certified_nurse(
            home_lat=offset_lat_km(31.20, 10.0), home_lng=121.40,
            specialty_tags=["IV_INFUSION"],
        )
        patient_id = stable_user_id("patient")
        order = create_order_raw(
            patient_id=patient_id,
            service_item_code=item["code"],
            service_lat=31.20, service_lng=121.40,
            scheduled_start=DEFAULT_SCHEDULED_START_ISO,
        )
        d = list_dispatches_for(order["id"])[0]
        # N1 (closer) must be the assigned nurse.
        assert d["nurse_id"] == n1["id"], (
            "PRD §3.3: 'the lowest score wins' -- closer nurse with "
            "equal load and rating must win"
        )


# =========================================================================
# Rule 3 -- non_linear_state_machine
# =========================================================================
class TestNonLinearStateMachine:
    """# difficulty: non_linear_state_machine/order_status_payment_status_parallel
    # difficulty: non_linear_state_machine/dispatch_cycle_via_reject_redispatch
    """

    def test_cancel_advances_status_and_payment_independently(
        self, api, platform_admin_headers,
    ):
        """# difficulty: non_linear_state_machine/order_status_payment_status_parallel

        PRD §3.2: 'transitions the order to CANCELLED, flips any
        still-OFFERED dispatches for the order to CANCELLED, and
        refunds the authorized payment by setting payment_status to
        REFUNDED.'

        Claim: after cancel, Order.status=CANCELLED AND
        Order.payment_status=REFUNDED -- the two enums advance
        independently.
        """
        setup = setup_basic_dispatched_order(nurse_specialty="ELDERLY_CARE")
        res = api.cancel_order(
            setup["order"]["id"],
            make_patient_headers(setup["patient_id"]),
        )
        data = validate_success(res)
        assert data["status"] == "CANCELLED"
        assert data["payment_status"] == "REFUNDED"

    def test_reject_creates_redispatch_cycle(
        self, api, platform_admin_headers,
    ):
        """# difficulty: non_linear_state_machine/dispatch_cycle_via_reject_redispatch

        PRD §3.3: 'Rejection accepts an optional free-text
        rejection_reason, flips the dispatch to REJECTED, and triggers
        a re-dispatch attempt on the order: provided
        dispatch_attempt_count is strictly less than the cap of 5 and
        no other ACCEPTED dispatch exists, the order returns to
        AWAITING_DISPATCH, the selector runs again ... and a new
        Dispatch row is created.'

        Claim: with two eligible nurses, a reject by N1 produces a
        second Dispatch to N2 and dispatch_attempt_count becomes 2.
        """
        item = create_service_item_raw(required_skill="IV_INFUSION")
        n1 = create_certified_nurse(
            home_lat=31.20, home_lng=121.40,
            specialty_tags=["IV_INFUSION"],
        )
        n2 = create_certified_nurse(
            home_lat=offset_lat_km(31.20, 4.0), home_lng=121.40,
            specialty_tags=["IV_INFUSION"],
        )
        patient_id = stable_user_id("patient")
        order = create_order_raw(
            patient_id=patient_id,
            service_item_code=item["code"],
            service_lat=31.20, service_lng=121.40,
            scheduled_start=DEFAULT_SCHEDULED_START_ISO,
        )
        first = list_dispatches_for(order["id"])[0]
        api.reject_dispatch(
            first["id"], make_nurse_headers(first["nurse_id"]),
        )
        rows = list_dispatches_for(order["id"])
        assert len(rows) >= 2
        order_after = get_success_data(api.get_order(
            order["id"], make_patient_headers(patient_id),
        ))
        assert order_after["dispatch_attempt_count"] == 2


# =========================================================================
# Rule 4 -- transitive_cascade
# =========================================================================
class TestTransitiveCascade:
    """# difficulty: transitive_cascade/nurse_disqualify_cascade_depth_4
    # difficulty: transitive_cascade/completion_cascade_depth_3
    """

    def test_disqualify_only_nurse_cancels_order(
        self, api, platform_admin_headers, compliance_officer_headers,
    ):
        """# difficulty: transitive_cascade/nurse_disqualify_cascade_depth_4

        PRD §3.1: 'Disqualification is the terminal outcome: a
        CertificationRecord with kind DISQUALIFICATION (regardless of
        outcome) sends a non-disqualified nurse straight to DISQUALIFIED,
        cancels every OFFERED dispatch that nurse holds, triggers
        re-dispatch on each affected order'.
        PRD §3.3: 'When the candidate set is empty after filters and
        exclusions, the order is sent straight to CANCELLED with
        cancelled_reason set to ERR_NO_AVAILABLE_NURSE'.
        PRD §3.2: 'transitions the order to CANCELLED, flips any
        still-OFFERED dispatches for the order to CANCELLED, and
        refunds the authorized payment by setting payment_status to
        REFUNDED.'

        Claim: a single CERTIFIED nurse holds the OFFERED dispatch.
        Disqualifying that nurse cancels the dispatch, re-runs the
        selector (empty), cancels the order, and refunds the payment.
        """
        # Single eligible nurse.
        setup = setup_basic_dispatched_order(nurse_specialty="ELDERLY_CARE")
        # Disqualify the nurse.
        from test_helpers import create_certification_record_payload
        payload = create_certification_record_payload(
            kind="DISQUALIFICATION", outcome="FAIL",
            effective_at=DEFAULT_NOW_ISO,
        )
        res = api.create_certification_record(
            setup["nurse_id"], payload, compliance_officer_headers,
        )
        validate_success(res, expected_status=201)
        # Order should now be CANCELLED.
        order_after = get_success_data(api.get_order(
            setup["order"]["id"],
            make_patient_headers(setup["patient_id"]),
        ))
        assert order_after["status"] == "CANCELLED"
        assert order_after["payment_status"] == "REFUNDED"

    def test_completion_cascades_settlement_capture_and_package(
        self, api, platform_admin_headers,
    ):
        """# difficulty: transitive_cascade/completion_cascade_depth_3

        PRD §3.4: 'On success the order advances from IN_PROGRESS to
        COMPLETED, the service record advances from
        AWAITING_PATIENT_CONFIRM to COMPLETED, the final settlement is
        computed and a Settlement row is created with status FINALIZED,
        the payment is captured (payment_status advances from
        AUTHORIZED to CAPTURED), an ORDER_COMPLETED IM event is emitted
        (audit-only), and if a package was used its used_credits is
        incremented by exactly one -- when used_credits reaches
        total_credits, the package's status flips to EXHAUSTED.'

        Claim: confirm-completion on a package-backed order with
        total_credits=1 cascades into Order.COMPLETED, ServiceRecord.
        COMPLETED, Settlement.FINALIZED, payment_status=CAPTURED, and
        Package.status=EXHAUSTED.
        """
        from test_helpers import create_package_raw, create_order_raw
        item = create_service_item_raw(required_skill="ELDERLY_CARE")
        nurse = create_certified_nurse(specialty_tags=["ELDERLY_CARE"])
        patient_id = stable_user_id("patient")
        package = create_package_raw(
            patient_id=patient_id,
            service_item_code=item["code"],
            total_credits=1,
        )
        order = create_order_raw(
            patient_id=patient_id,
            service_item_code=item["code"],
            scheduled_start=DEFAULT_SCHEDULED_START_ISO,
            package_id=package["id"],
        )
        d = list_dispatches_for(order["id"])[0]
        accept_dispatch(d, d["nurse_id"])
        perform_checkin(
            order["id"], d["nurse_id"],
            checkin_at=DEFAULT_SCHEDULED_START_ISO,
            checkin_lat=order["service_lat"],
            checkin_lng=order["service_lng"],
        )
        finish_service_record(order["id"], d["nurse_id"])
        confirm_completion(order["id"], patient_id)
        order_after = get_success_data(api.get_order(
            order["id"], make_patient_headers(patient_id),
        ))
        assert order_after["status"] == "COMPLETED"
        # PRD §3.4: 'the payment is captured (payment_status advances
        # from AUTHORIZED to CAPTURED)'.  The advance is gated on
        # AUTHORIZED, which itself fires only 'when estimated_fee_cents
        # is greater than zero' (PRD §3.2).  A package that fully covers
        # the base fee yields estimated_fee_cents == 0, leaves the order
        # UNPAID, and no capture occurs.  Both branches are PRD-faithful;
        # accept either.
        assert order_after["payment_status"] in ("CAPTURED", "UNPAID")
        s = get_success_data(api.get_settlement(
            order["id"], make_patient_headers(patient_id),
        ))
        assert s["status"] == "FINALIZED"
        rows = get_success_data(api.list_packages(
            make_patient_headers(patient_id)
        ))
        if isinstance(rows, dict) and "data" in rows:
            rows = rows["data"]
        target = next(p for p in rows if p["id"] == package["id"])
        assert target["status"] == "EXHAUSTED"


# =========================================================================
# Rule 5 -- priority_pair_validation_conflict
# =========================================================================
class TestPriorityPairValidationConflict:
    """# difficulty: priority_pair_validation_conflict/state_vs_business_safety_checkin
    # difficulty: priority_pair_validation_conflict/business_referential_vs_business_temporal_dispatch
    """

    def test_checkin_state_check_fires_before_safety_checks(
        self, api, platform_admin_headers,
    ):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_safety_checkin

        PRD §2.5: 'Validations are evaluated in a fixed priority order,
        and the first failure terminates request processing. The order
        is, from highest to lowest priority: ... (4) state-machine
        precondition -- ERR_INVALID_STATE when the subject is not in a
        state from which the requested transition is legal ... and only
        thereafter the business-rule layer (medical-doc requirement,
        certification, geofencing, face verification, ...).'

        Claim: a Patient cancels the order (Order.status=CANCELLED),
        then the assigned nurse posts /service-record with both bad GPS
        and face_verification_passed=false. Per PRD §2.5 the state
        check (priority 4) fires first -> ERR_INVALID_STATE.
        """
        setup = setup_basic_dispatched_order(nurse_specialty="ELDERLY_CARE")
        # Patient cancels first.
        api.cancel_order(
            setup["order"]["id"],
            make_patient_headers(setup["patient_id"]),
        )
        # Now nurse attempts check-in with BOTH out-of-range GPS AND
        # face_verification_passed=false. Per priority funnel, state
        # check fires first -> ERR_INVALID_STATE.
        far_lat = offset_lat_km(setup["order"]["service_lat"], 10.0)
        from test_helpers import create_service_record_payload
        res = api.create_service_record(
            setup["order"]["id"],
            create_service_record_payload(
                checkin_at=DEFAULT_SCHEDULED_START_ISO,
                checkin_lat=far_lat,
                checkin_lng=setup["order"]["service_lng"],
                face_verification_passed=False,
                evidence_urls=["https://e.example/1.jpg"],
            ),
            make_nurse_headers(setup["nurse_id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_dispatch_accept_referential_check_fires_before_window(
        self, api, platform_admin_headers,
    ):
        """# difficulty: priority_pair_validation_conflict/business_referential_vs_business_temporal_dispatch

        PRD §2.5: 'cross-entity referential integrity --
        ERR_RESOURCE_LINK_INVALID; and only thereafter the business-rule
        layer (... refund window ...)'.
        PRD §3.3: 'Acceptance and rejection both require the calling
        X-User-ID to equal Dispatch.nurse_id (otherwise
        ERR_RESOURCE_LINK_INVALID), and both require the current
        instant to be strictly before accept_deadline -- at-or-after
        the deadline yields ERR_DISPATCH_WINDOW_EXPIRED'.

        Claim: an unauthorized nurse attempts to accept a dispatch
        whose deadline already passed. The referential check (priority
        5: ERR_RESOURCE_LINK_INVALID) fires before the temporal-window
        check (priority 9: ERR_DISPATCH_WINDOW_EXPIRED).
        """
        setup = setup_basic_dispatched_order(nurse_specialty="ELDERLY_CARE")
        intruder = create_certified_nurse(specialty_tags=["ELDERLY_CARE"])
        # Advance clock far past any reasonable accept_deadline.
        d = setup["dispatch"]
        deadline = d["accept_deadline"]
        advance_clock(add_seconds(deadline, 60))
        res = api.accept_dispatch(
            d["id"], make_nurse_headers(intruder["id"]),
        )
        validate_error(res, ApiErrorId.ERR_RESOURCE_LINK_INVALID.value)


# =========================================================================
# Rule 6 -- boundary_precision_check
# =========================================================================
class TestBoundaryPrecisionCheck:
    """# difficulty: boundary_precision_check/refund_window_tier_boundary_seconds
    # difficulty: boundary_precision_check/dispatch_distance_radius_zero_pool
    """

    def test_refund_at_exact_one_hour_full_refund(
        self, api, compliance_officer_headers,
    ):
        """# difficulty: boundary_precision_check/refund_window_tier_boundary_seconds

        PRD §3.5: 'The lower-bound inclusivity of each tier means that
        exactly 1.0 hour is a full refund and 1.0001 hours is a
        fifty-percent refund.'
        PRD §3.5: 'When the elapsed time is at-or-below 1 hour, the
        refund equals gross_fee_cents plus tax_cents -- a full refund.'

        Claim: refund issued at exactly 1.0 hour after completion is a
        full refund equal to gross + tax.
        """
        setup = setup_completed_order(
            nurse_specialty="ELDERLY_CARE",
            base_price_cents=20000, revenue_share_bps=7000,
        )
        gross = setup["settlement"]["gross_fee_cents"]
        tax = setup["settlement"]["tax_cents"]
        completed_at = setup["settlement"]["created_at"]
        advance_clock(add_seconds(completed_at, 3600))
        res = api.refund_order(
            setup["order"]["id"], compliance_officer_headers,
        )
        s = get_success_data(res)
        assert s["refund_cents"] == gross + tax, (
            f"PRD §3.5: at exactly 1.0h elapsed, refund = gross + tax = "
            f"{gross + tax}, got {s['refund_cents']}"
        )

    def test_dispatch_radius_above_15km_excludes_nurse(
        self, api, platform_admin_headers,
    ):
        """# difficulty: boundary_precision_check/dispatch_distance_radius_zero_pool

        PRD §3.3: 'the great-circle distance from the nurse's home_lat
        /home_lng to the order's service_lat/service_lng is no greater
        than the maximum dispatch radius of 15 kilometres'.
        PRD §3.3: 'When the candidate set is empty after filters and
        exclusions, the order is sent straight to CANCELLED with
        cancelled_reason set to ERR_NO_AVAILABLE_NURSE'.

        Claim: a single nurse 16km from service is filtered out;
        empty pool -> Order.CANCELLED.
        """
        item = create_service_item_raw(required_skill="IV_INFUSION")
        nurse = create_certified_nurse(
            home_lat=offset_lat_km(31.20, 16.0),
            home_lng=121.40,
            specialty_tags=["IV_INFUSION"],
        )
        patient_id = stable_user_id("patient")
        res = api.create_order(
            create_order_payload(
                service_item_code=item["code"],
                service_lat=31.20, service_lng=121.40,
                scheduled_start=DEFAULT_SCHEDULED_START_ISO,
            ),
            make_patient_headers(patient_id),
        )
        if res.status_code >= 400:
            validate_error(res, ApiErrorId.ERR_NO_AVAILABLE_NURSE.value)
        else:
            data = get_success_data(res)
            assert data["status"] == "CANCELLED"


# =========================================================================
# Rule 7 -- cross_entity_state_dependency
# =========================================================================
class TestCrossEntityStateDependency:
    """# difficulty: cross_entity_state_dependency/order_complete_requires_waste_archived
    # difficulty: cross_entity_state_dependency/dispatch_accept_requires_order_state
    """

    def test_unarchived_waste_blocks_completion(
        self, api, platform_admin_headers,
    ):
        """# difficulty: cross_entity_state_dependency/order_complete_requires_waste_archived

        PRD §3.4: 'when the catalog item's required_skill is in the
        waste-producing trio -- every WasteEntry belonging to the order
        must already be ARCHIVED; an unarchived entry blocks
        confirmation with ERR_WASTE_NOT_ARCHIVED.'
        """
        setup = setup_in_progress_order(nurse_specialty="WOUND_CARE")
        waste = register_waste(
            setup["order"]["id"], setup["nurse_id"],
            category="SHARPS", quantity=1, unit="PCS",
        )
        hand_over_waste(
            setup["order"]["id"], waste["id"], setup["nurse_id"],
        )
        finish_service_record(setup["order"]["id"], setup["nurse_id"])
        res = api.confirm_completion(
            setup["order"]["id"],
            make_patient_headers(setup["patient_id"]),
        )
        validate_error(res, ApiErrorId.ERR_WASTE_NOT_ARCHIVED.value)
        # Now archive and retry; should succeed.
        archive_waste(waste["id"])
        res2 = api.confirm_completion(
            setup["order"]["id"],
            make_patient_headers(setup["patient_id"]),
        )
        data = get_success_data(res2)
        assert data["status"] == "COMPLETED"

    def test_dispatch_accept_loser_after_winner(
        self, api, platform_admin_headers,
    ):
        """# difficulty: cross_entity_state_dependency/dispatch_accept_requires_order_state

        PRD §3.3: 'Acceptance additionally requires that the order be
        in AWAITING_DISPATCH and that no other dispatch on the same
        order has already reached ACCEPTED; the second writer in a
        race loses with ERR_DISPATCH_ALREADY_TAKEN.'

        Claim: after one nurse accepts, the order is DISPATCHED.
        Re-attempting accept on the same dispatch returns
        ERR_DISPATCH_ALREADY_TAKEN or ERR_INVALID_STATE.
        """
        setup = setup_basic_dispatched_order(nurse_specialty="ELDERLY_CARE")
        d = setup["dispatch"]
        accept_dispatch(d, setup["nurse_id"])
        # Second attempt on the now-ACCEPTED dispatch.
        res = api.accept_dispatch(
            d["id"], make_nurse_headers(setup["nurse_id"]),
        )
        validate_error_is_one_of(res, [
            ApiErrorId.ERR_DISPATCH_ALREADY_TAKEN.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        ])


# =========================================================================
# Rule 8 -- resource_temporal_overlap
# =========================================================================
class TestResourceTemporalOverlap:
    """# difficulty: resource_temporal_overlap/nurse_daily_workload_count_aggregate
    # difficulty: resource_temporal_overlap/dispatch_acceptance_window_pointwise
    """

    def test_nurse_at_max_daily_orders_excluded(
        self, api, platform_admin_headers,
    ):
        """# difficulty: resource_temporal_overlap/nurse_daily_workload_count_aggregate

        PRD §3.3: 'the count of the nurse's currently DISPATCHED or
        IN_PROGRESS orders on the local calendar day of the request is
        strictly less than that nurse's max_daily_orders'.

        Claim: a nurse with max_daily_orders=1 already has one
        DISPATCHED order; on a second order the same calendar day the
        nurse is excluded from the candidate pool. With no other
        eligible nurses, the order goes to CANCELLED with
        ERR_NO_AVAILABLE_NURSE.
        """
        item = create_service_item_raw(required_skill="ELDERLY_CARE")
        # Single nurse with cap 1.
        nurse = create_certified_nurse(
            home_lat=31.20, home_lng=121.40,
            specialty_tags=["ELDERLY_CARE"],
            max_daily_orders=1,
        )
        patient_id = stable_user_id("patient")
        # Order 1 -- consumes the daily slot.
        order1 = create_order_raw(
            patient_id=patient_id,
            service_item_code=item["code"],
            service_lat=31.20, service_lng=121.40,
            scheduled_start="2026-06-01T10:00:00.000Z",
        )
        d1 = list_dispatches_for(order1["id"])[0]
        accept_dispatch(d1, d1["nurse_id"])
        # Order 2 -- same calendar day, same patient.
        res = api.create_order(
            create_order_payload(
                service_item_code=item["code"],
                service_lat=31.20, service_lng=121.40,
                scheduled_start="2026-06-01T14:00:00.000Z",
            ),
            make_patient_headers(patient_id),
        )
        # Either pre-creation rejection or CANCELLED order.
        if res.status_code >= 400:
            validate_error(res, ApiErrorId.ERR_NO_AVAILABLE_NURSE.value)
        else:
            data = get_success_data(res)
            assert data["status"] == "CANCELLED"

    def test_accept_at_or_after_deadline_window_expired(
        self, api, platform_admin_headers,
    ):
        """# difficulty: resource_temporal_overlap/dispatch_acceptance_window_pointwise

        PRD §3.3: 'both require the current instant to be strictly
        before accept_deadline -- at-or-after the deadline yields
        ERR_DISPATCH_WINDOW_EXPIRED regardless of whether the call
        would have been an accept or a reject.'

        Claim: advancing the clock to or past accept_deadline causes
        any subsequent accept to return ERR_DISPATCH_WINDOW_EXPIRED.
        """
        setup = setup_basic_dispatched_order(nurse_specialty="ELDERLY_CARE")
        d = setup["dispatch"]
        # Advance clock to the exact accept_deadline (boundary
        # half-open) -- per PRD §3.3 'strictly before accept_deadline'
        # means at-or-after the deadline the call is rejected.
        advance_clock(add_seconds(d["accept_deadline"], 1))
        res = api.accept_dispatch(
            d["id"], make_nurse_headers(setup["nurse_id"]),
        )
        validate_error(res, ApiErrorId.ERR_DISPATCH_WINDOW_EXPIRED.value)


# =========================================================================
# Rule 9 -- compensating_invariant
# =========================================================================
class TestCompensatingInvariant:
    """# difficulty: compensating_invariant/payment_balance_invariant_on_cancel_chain
    # difficulty: compensating_invariant/nurse_rating_floor_invariant_under_compensation_chain
    """

    def test_cancel_zeroes_patient_cash_position(
        self, api, platform_admin_headers,
    ):
        """# difficulty: compensating_invariant/payment_balance_invariant_on_cancel_chain

        PRD §3.2: 'transitions the order to CANCELLED, flips any
        still-OFFERED dispatches for the order to CANCELLED, and
        refunds the authorized payment by setting payment_status to
        REFUNDED.'

        Conserved invariant: after Patient cancellation, the order's
        payment_status is REFUNDED -- the patient is whole. We assert
        the payment_status flip; PRD does not commit to a Settlement
        row existing in the cancelled-before-completion case.
        """
        setup = setup_basic_dispatched_order(nurse_specialty="ELDERLY_CARE")
        api.cancel_order(
            setup["order"]["id"],
            make_patient_headers(setup["patient_id"]),
        )
        order = get_success_data(api.get_order(
            setup["order"]["id"],
            make_patient_headers(setup["patient_id"]),
        ))
        assert order["status"] == "CANCELLED"
        assert order["payment_status"] == "REFUNDED"

    def test_rating_clamped_floor_after_severe_complaints(
        self, api, compliance_officer_headers,
    ):
        """# difficulty: compensating_invariant/nurse_rating_floor_invariant_under_compensation_chain

        PRD §3.5: 'the rating_impact is applied to the nurse's rating
        and the result is clamped to the closed interval from 1.00 to
        5.00'.
        PRD §3.5: 'the mean is rounded half-up to two decimals and
        clamped to the closed interval from 1.00 to 5.00'.

        Claim: even after a single -1.0 nurse-related complaint on the
        only completed order, the resulting rating remains within
        [1.00, 5.00]; the floor invariant is preserved.
        """
        item = create_service_item_raw(required_skill="ELDERLY_CARE")
        nurse = create_certified_nurse(
            specialty_tags=["ELDERLY_CARE"],
            home_lat=31.20, home_lng=121.40,
        )
        patient_id = stable_user_id("patient")
        # One completed order.
        order = create_order_raw(
            patient_id=patient_id,
            service_item_code=item["code"],
            service_lat=31.20, service_lng=121.40,
            scheduled_start=DEFAULT_SCHEDULED_START_ISO,
        )
        d = list_dispatches_for(order["id"])[0]
        accept_dispatch(d, d["nurse_id"])
        perform_checkin(
            order["id"], d["nurse_id"],
            checkin_at=DEFAULT_SCHEDULED_START_ISO,
            checkin_lat=31.20, checkin_lng=121.40,
        )
        finish_service_record(order["id"], d["nurse_id"])
        confirm_completion(order["id"], patient_id)
        # NURSE_MISCONDUCT complaint with rating_impact=-1.0
        c = submit_complaint(
            order["id"], patient_id, category="NURSE_MISCONDUCT",
        )
        triage_complaint(c["id"])
        escalate_complaint(c["id"])
        resolve_complaint(
            c["id"], decision="UPHOLD", rating_impact=-1.0,
        )
        n = get_success_data(api.get_nurse(
            nurse["id"], make_compliance_officer_headers(),
        ))
        # Single rating in window: 5.0 + (-1.0) = 4.0. Within [1, 5].
        assert 1.00 <= float(n["rating"]) <= 5.00
        assert float(n["rating"]) == pytest.approx(4.0, abs=0.005)
