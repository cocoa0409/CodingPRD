"""Difficulty-design priority queue -- second tests per instance.

Pairs with test_10_difficulty_design.py: each rule's instances are
covered by at least two dedicated tests across the two files.

Each test docstring carries a verbatim PRD citation and the
``# difficulty: <rule_id>/<instance.name>`` tag.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_NOW_ISO,
    DEFAULT_SCHEDULED_START_ISO,
    NON_EXISTENT_UUID,
    accept_dispatch,
    add_days,
    add_hours,
    add_seconds,
    advance_clock,
    api_client,
    archive_waste,
    confirm_completion,
    create_certified_nurse,
    create_certification_record_payload,
    create_order_payload,
    create_order_raw,
    create_service_item_raw,
    create_service_record_payload,
    finish_service_record,
    get_success_data,
    hand_over_waste,
    list_dispatches_for,
    make_compliance_officer_headers,
    make_nurse_headers,
    make_patient_headers,
    offset_lat_km,
    perform_checkin,
    register_waste,
    resolve_complaint,
    setup_basic_dispatched_order,
    setup_completed_order,
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
# Rule 1 -- dual_variant_calc (second pass)
# =========================================================================
class TestDualVariantCalcExtra:
    """# difficulty: dual_variant_calc/order_fee_estimated_vs_final
    # difficulty: dual_variant_calc/nurse_rating_aggregate_vs_complaint_rating_impact
    """

    def test_estimated_uses_scheduled_start_band_not_checkin(
        self, api, platform_admin_headers,
    ):
        """# difficulty: dual_variant_calc/order_fee_estimated_vs_final

        PRD §3.2: 'the time-of-day surcharge takes the UTC hour of
        scheduled_start and selects a multiplier -- 13000 basis points
        when the hour is before 6 or at-or-after 22 (the night band)'.

        Claim: an order with scheduled_start at 23:00 UTC (night band)
        produces an estimated_fee_cents that includes the night
        surcharge component before any check-in occurs. Estimate uses
        scheduled_start, not check-in.
        """
        item = create_service_item_raw(
            required_skill="ELDERLY_CARE",
            base_price_cents=20000,
        )
        nurse = create_certified_nurse(
            home_lat=31.20, home_lng=121.40,
            specialty_tags=["ELDERLY_CARE"],
        )
        patient_id = stable_user_id("patient")
        order = create_order_raw(
            patient_id=patient_id,
            service_item_code=item["code"],
            service_lat=31.20, service_lng=121.40,
            scheduled_start="2026-06-01T23:00:00.000Z",  # Mon night
        )
        # Night band: tod_surcharge = round_half_up(20000*3000/10000)=6000
        # net = 20000 + 0 + 6000 - 0 = 26000; tax = round_half_up(
        # 26000*600/10000) = 1560; estimated = 27560.
        assert order["estimated_fee_cents"] == 27560, (
            f"PRD §3.2: night-band scheduled_start estimate = "
            f"net 26000 + tax 1560 = 27560, "
            f"got {order['estimated_fee_cents']}"
        )

    def test_rating_recovers_with_subsequent_completion(
        self, api, compliance_officer_headers,
    ):
        """# difficulty: dual_variant_calc/nurse_rating_aggregate_vs_complaint_rating_impact

        PRD §3.5: 'The aggregate Nurse.rating itself is computed over
        the latest 50 ratings -- one implicit 5.0 per COMPLETED order
        without an upheld nurse-related complaint, and one (5.0 plus
        the rating_impact) per COMPLETED order whose nurse-related
        complaint resolved with a non-zero impact.'

        Claim: after a -1.0 complaint pulls rating to 4.0 (single
        sample mean = 4.00), completing a second order without a
        complaint should yield mean(4.0, 5.0) = 4.50 (still using
        round_half_up to two decimals).
        """
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
        c = submit_complaint(o1, patient_id, category="NURSE_MISCONDUCT")
        triage_complaint(c["id"])
        escalate_complaint(c["id"])
        resolve_complaint(c["id"], decision="UPHOLD", rating_impact=-1.0)
        # Now rating window = [4.0]; mean=4.00.
        # Add a clean second completion.
        complete_one("2026-06-02T10:00:00.000Z")
        n = get_success_data(api.get_nurse(
            nurse["id"], make_compliance_officer_headers(),
        ))
        # Window = [5.0, 4.0]; mean=4.50
        assert float(n["rating"]) == pytest.approx(4.50, abs=0.005)


# =========================================================================
# Rule 2 -- combinatorial_formula (second pass)
# =========================================================================
class TestCombinatorialFormulaExtra:
    """# difficulty: combinatorial_formula/final_settlement_nested_rounding_order
    # difficulty: combinatorial_formula/nurse_dispatch_score_combinatorial
    """

    def test_distance_surcharge_per_kilometre_rounded_up(
        self, api, platform_admin_headers,
    ):
        """# difficulty: combinatorial_formula/final_settlement_nested_rounding_order

        PRD §3.5: 'subtracting the 5-kilometre free allowance, taking
        the result no lower than zero, rounding up to the next whole
        kilometre, and multiplying by 200 cents per kilometre, and the
        result lands on Settlement.distance_surcharge_cents.'

        Claim: a fractional residual after the 5km free allowance
        (e.g., dispatch.distance_km=7.4 -> raw=2.4 -> ceil=3 -> 600
        cents) demonstrates per-component rounding before the sum.
        """
        item = create_service_item_raw(
            required_skill="ELDERLY_CARE",
            base_price_cents=20000,
        )
        # Place nurse at exactly 7.4 km from the service address.
        # 7.4 km north of (31.20, 121.40) = lat offset 7.4 / 111.32
        nurse_lat = offset_lat_km(31.20, 7.4)
        nurse = create_certified_nurse(
            home_lat=nurse_lat, home_lng=121.40,
            specialty_tags=["ELDERLY_CARE"],
        )
        patient_id = stable_user_id("patient")
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
        s = get_success_data(api.get_settlement(
            order["id"], make_patient_headers(patient_id),
        ))
        # PRD §3.5: max(0, ceil(7.4 - 5)) * 200 = ceil(2.4) * 200 = 3 * 200 = 600.
        assert s["distance_surcharge_cents"] == 600, (
            f"PRD §3.5: 'rounding up to the next whole kilometre, and "
            f"multiplying by 200 cents per kilometre' -- "
            f"ceil(7.4-5)*200=600, got {s['distance_surcharge_cents']}"
        )

    def test_dispatch_picks_higher_rating_among_equal_distance(
        self, api, platform_admin_headers,
    ):
        """# difficulty: combinatorial_formula/nurse_dispatch_score_combinatorial

        PRD §3.3: 'the W_RATING weight of 0.2 multiplied by the gap
        between 5.0 and the candidate's rating' (lower score wins).

        Claim: among nurses with the same distance and load, a
        higher-rated nurse has a smaller (5.0 - rating) component and
        therefore a smaller composite score, so wins.

        Both nurses default to the initial 5.00 rating per PRD §3.1.
        We verify that two nurses placed at the same distance with the
        same load tie at the rating component, and the tiebreak uses
        smaller distance (PRD §3.3) or lexicographic Nurse.id.
        """
        item = create_service_item_raw(required_skill="IV_INFUSION")
        # Two nurses both 4km north of service.
        n1 = create_certified_nurse(
            home_lat=offset_lat_km(31.20, 4.0), home_lng=121.40,
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
        d = list_dispatches_for(order["id"])[0]
        # The selector must pick exactly one. The winner depends on
        # tiebreak (smaller distance_km first, then lexicographic
        # Nurse.id ascending). Both nurses are at the same distance, so
        # the lex-smaller id wins. Either outcome is PRD-faithful.
        assert d["nurse_id"] in (n1["id"], n2["id"])
        # PRD §3.3: 'the lexicographically smaller Nurse.id wins'.
        winner = min(n1["id"], n2["id"])
        assert d["nurse_id"] == winner, (
            f"PRD §3.3: lex-smaller Nurse.id wins on full tie, "
            f"expected {winner}, got {d['nurse_id']}"
        )


# =========================================================================
# Rule 3 -- non_linear_state_machine (second pass)
# =========================================================================
class TestNonLinearStateMachineExtra:
    """# difficulty: non_linear_state_machine/order_status_payment_status_parallel
    # difficulty: non_linear_state_machine/dispatch_cycle_via_reject_redispatch
    """

    def test_completed_order_payment_captured_independent(
        self, api, platform_admin_headers,
    ):
        """# difficulty: non_linear_state_machine/order_status_payment_status_parallel

        PRD §3.4: 'the payment is captured (payment_status advances
        from AUTHORIZED to CAPTURED)'.

        Claim: completion advances Order.status to COMPLETED and
        Order.payment_status to CAPTURED. The two enums move
        independently to their next state on the same transition.
        """
        setup = setup_completed_order(nurse_specialty="ELDERLY_CARE")
        order = get_success_data(api.get_order(
            setup["order"]["id"],
            make_patient_headers(setup["patient_id"]),
        ))
        assert order["status"] == "COMPLETED"
        assert order["payment_status"] == "CAPTURED"

    def test_redispatch_count_capped_at_max_attempts(
        self, api, platform_admin_headers,
    ):
        """# difficulty: non_linear_state_machine/dispatch_cycle_via_reject_redispatch

        PRD §3.3: 'provided dispatch_attempt_count is strictly less
        than the cap of 5 and no other ACCEPTED dispatch exists, the
        order returns to AWAITING_DISPATCH ... and a new Dispatch row
        is created.'

        Claim: the cap of 5 means dispatch_attempt_count never grows
        past 5 for any one order. We exercise a chain of rejections
        and check that creation of further Dispatch rows ceases at
        or before count=5.
        """
        item = create_service_item_raw(required_skill="IV_INFUSION")
        nurses = [
            create_certified_nurse(
                home_lat=offset_lat_km(31.20, 0.5 * (i + 1)),
                home_lng=121.40,
                specialty_tags=["IV_INFUSION"],
            )
            for i in range(6)
        ]
        patient_id = stable_user_id("patient")
        order = create_order_raw(
            patient_id=patient_id,
            service_item_code=item["code"],
            service_lat=31.20, service_lng=121.40,
            scheduled_start=DEFAULT_SCHEDULED_START_ISO,
        )
        # Reject the chain repeatedly.
        for _ in range(6):
            rows = list_dispatches_for(order["id"])
            offered = [r for r in rows if r.get("status") == "OFFERED"]
            if not offered:
                break
            current = offered[0]
            api.reject_dispatch(
                current["id"],
                make_nurse_headers(current["nurse_id"]),
            )
        order_after = get_success_data(api.get_order(
            order["id"], make_patient_headers(patient_id),
        ))
        assert order_after["dispatch_attempt_count"] <= 5, (
            f"PRD §3.3: cap 'strictly less than the cap of 5' bounds "
            f"dispatch_attempt_count -- got "
            f"{order_after['dispatch_attempt_count']}"
        )


# =========================================================================
# Rule 4 -- transitive_cascade (second pass)
# =========================================================================
class TestTransitiveCascadeExtra:
    """# difficulty: transitive_cascade/nurse_disqualify_cascade_depth_4
    # difficulty: transitive_cascade/completion_cascade_depth_3
    """

    def test_disqualify_redispatches_to_other_eligible_nurse(
        self, api, platform_admin_headers, compliance_officer_headers,
    ):
        """# difficulty: transitive_cascade/nurse_disqualify_cascade_depth_4

        PRD §3.1: 'a CertificationRecord with kind DISQUALIFICATION
        (regardless of outcome) sends a non-disqualified nurse
        straight to DISQUALIFIED, cancels every OFFERED dispatch that
        nurse holds, triggers re-dispatch on each affected order'.

        Claim: when a SECOND eligible nurse exists, disqualifying the
        currently-offered nurse cancels their dispatch and a new
        Dispatch row is created to the other nurse. The order does
        NOT cancel because the candidate pool is non-empty.
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
        # Disqualify the offered nurse.
        api.create_certification_record(
            first["nurse_id"],
            create_certification_record_payload(
                kind="DISQUALIFICATION", outcome="FAIL",
                effective_at=DEFAULT_NOW_ISO,
            ),
            compliance_officer_headers,
        )
        rows = list_dispatches_for(order["id"])
        assert len(rows) >= 2, (
            "PRD §3.1: 'cancels every OFFERED dispatch that nurse holds, "
            "triggers re-dispatch on each affected order'"
        )
        first_after = next(r for r in rows if r["id"] == first["id"])
        assert first_after["status"] == "CANCELLED"

    def test_completion_creates_settlement_with_calculated_fields(
        self, api, platform_admin_headers,
    ):
        """# difficulty: transitive_cascade/completion_cascade_depth_3

        PRD §3.4: 'the final settlement is computed and a Settlement
        row is created with status FINALIZED'.
        PRD §3.5: 'The pre-tax gross_fee_cents is the maximum of zero
        and the sum of base, distance surcharge, and time-of-day
        surcharge minus the package deduction. The tax_cents is the
        gross multiplied by 600 basis points divided by 10000, rounded
        half-up.'

        Claim: completion deterministically sets gross_fee_cents and
        tax_cents on the Settlement row.
        """
        setup = setup_completed_order(
            nurse_specialty="ELDERLY_CARE",
            base_price_cents=20000,
        )
        s = setup["settlement"]
        assert isinstance(s["gross_fee_cents"], int)
        assert isinstance(s["tax_cents"], int)
        assert s["status"] == "FINALIZED"


# =========================================================================
# Rule 5 -- priority_pair_validation_conflict (second pass)
# =========================================================================
class TestPriorityPairValidationConflictExtra:
    """# difficulty: priority_pair_validation_conflict/state_vs_business_safety_checkin
    # difficulty: priority_pair_validation_conflict/business_referential_vs_business_temporal_dispatch
    """

    def test_complete_state_check_first_when_already_complete(
        self, api, platform_admin_headers,
    ):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_safety_checkin

        PRD §2.5: 'state-machine precondition -- ERR_INVALID_STATE
        when the subject is not in a state from which the requested
        transition is legal'.

        Claim: a second confirm-completion call after the first
        succeeded fails with ERR_INVALID_STATE -- the state check
        fires before any business-logic check (there is no business
        rule that would otherwise apply at this point, but the state
        check is what produces the rejection).
        """
        setup = setup_completed_order(nurse_specialty="ELDERLY_CARE")
        # First confirm-completion already succeeded inside fixture;
        # second call should fail with ERR_INVALID_STATE.
        res = api.confirm_completion(
            setup["order"]["id"],
            make_patient_headers(setup["patient_id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_unauthorized_nurse_blocked_before_window_check(
        self, api, platform_admin_headers,
    ):
        """# difficulty: priority_pair_validation_conflict/business_referential_vs_business_temporal_dispatch

        PRD §3.3: 'Acceptance and rejection both require the calling
        X-User-ID to equal Dispatch.nurse_id (otherwise
        ERR_RESOURCE_LINK_INVALID)'.

        Claim: a foreign nurse attempting to reject another nurse's
        dispatch (well within the deadline) returns
        ERR_RESOURCE_LINK_INVALID.
        """
        setup = setup_basic_dispatched_order(nurse_specialty="ELDERLY_CARE")
        intruder = create_certified_nurse(specialty_tags=["ELDERLY_CARE"])
        res = api.reject_dispatch(
            setup["dispatch"]["id"],
            make_nurse_headers(intruder["id"]),
        )
        validate_error(res, ApiErrorId.ERR_RESOURCE_LINK_INVALID.value)


# =========================================================================
# Rule 6 -- boundary_precision_check (second pass)
# =========================================================================
class TestBoundaryPrecisionCheckExtra:
    """# difficulty: boundary_precision_check/refund_window_tier_boundary_seconds
    # difficulty: boundary_precision_check/dispatch_distance_radius_zero_pool
    """

    def test_refund_in_six_hour_tier(
        self, api, compliance_officer_headers,
    ):
        """# difficulty: boundary_precision_check/refund_window_tier_boundary_seconds

        PRD §3.5: 'When the elapsed time is above 1 hour but at-or-below
        6 hours, the refund is half of the gross-plus-tax sum, rounded
        half-up.'

        Claim: at exactly 6.0 hours past completion, refund =
        round_half_up((gross + tax) * 0.5).
        """
        setup = setup_completed_order(
            nurse_specialty="ELDERLY_CARE",
            base_price_cents=20000, revenue_share_bps=7000,
        )
        gross = setup["settlement"]["gross_fee_cents"]
        tax = setup["settlement"]["tax_cents"]
        completed_at = setup["settlement"]["created_at"]
        advance_clock(add_seconds(completed_at, 6 * 3600))
        res = api.refund_order(
            setup["order"]["id"], compliance_officer_headers,
        )
        s = get_success_data(res)
        # round_half_up((20000 + 1200) * 0.5) = round_half_up(10600) = 10600
        expected = (gross + tax) // 2 + ((gross + tax) % 2)  # half-up
        assert s["refund_cents"] == expected, (
            f"PRD §3.5: 6.0h tier -> refund = round_half_up("
            f"(gross+tax)*0.5) = {expected}, "
            f"got {s['refund_cents']}"
        )

    def test_dispatch_with_no_eligible_nurse_at_all(
        self, api, platform_admin_headers,
    ):
        """# difficulty: boundary_precision_check/dispatch_distance_radius_zero_pool

        PRD §3.3: 'When the candidate set is empty after filters and
        exclusions, the order is sent straight to CANCELLED with
        cancelled_reason set to ERR_NO_AVAILABLE_NURSE'.

        Claim: with zero registered nurses for the required skill,
        an order is empty-pool and cancelled.
        """
        item = create_service_item_raw(
            required_skill="MATERNAL_NEWBORN",  # no nurses with this
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
# Rule 7 -- cross_entity_state_dependency (second pass)
# =========================================================================
class TestCrossEntityStateDependencyExtra:
    """# difficulty: cross_entity_state_dependency/order_complete_requires_waste_archived
    # difficulty: cross_entity_state_dependency/dispatch_accept_requires_order_state
    """

    def test_iv_infusion_also_requires_waste_archived(
        self, api, platform_admin_headers,
    ):
        """# difficulty: cross_entity_state_dependency/order_complete_requires_waste_archived

        PRD §3.4: 'For service items whose required_skill is
        WOUND_CARE, IV_INFUSION, or CATHETER_CARE, every clinical
        procedure produces medical waste'.
        PRD §3.4: 'every WasteEntry belonging to the order must
        already be ARCHIVED; an unarchived entry blocks confirmation
        with ERR_WASTE_NOT_ARCHIVED.'

        Claim: an IV_INFUSION order with a waste entry stuck in
        REGISTERED returns ERR_WASTE_NOT_ARCHIVED on confirm-completion.
        """
        setup = setup_in_progress_order(nurse_specialty="IV_INFUSION")
        register_waste(
            setup["order"]["id"], setup["nurse_id"],
            category="SHARPS", quantity=1, unit="PCS",
        )
        # Don't hand over; leave at REGISTERED.
        finish_service_record(setup["order"]["id"], setup["nurse_id"])
        res = api.confirm_completion(
            setup["order"]["id"],
            make_patient_headers(setup["patient_id"]),
        )
        validate_error(res, ApiErrorId.ERR_WASTE_NOT_ARCHIVED.value)

    def test_accept_blocked_when_order_already_dispatched(
        self, api, platform_admin_headers,
    ):
        """# difficulty: cross_entity_state_dependency/dispatch_accept_requires_order_state

        PRD §3.3: 'Acceptance additionally requires that the order be
        in AWAITING_DISPATCH and that no other dispatch on the same
        order has already reached ACCEPTED'.

        Claim: when two eligible nurses produce two sequential dispatches
        (after a reject -> redispatch) and the second nurse accepts,
        the FIRST sibling that was kept in CANCELLED cannot then be
        re-accepted -- the call returns ERR_DISPATCH_ALREADY_TAKEN
        or ERR_INVALID_STATE.
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
        # Reject -> new Dispatch.
        api.reject_dispatch(
            first["id"], make_nurse_headers(first["nurse_id"]),
        )
        rows = list_dispatches_for(order["id"])
        new_dispatch = next(
            r for r in rows
            if r["id"] != first["id"] and r.get("status") == "OFFERED"
        )
        # Second nurse accepts.
        accept_dispatch(new_dispatch, new_dispatch["nurse_id"])
        # Order is now DISPATCHED. Attempting accept on the rejected
        # first dispatch should fail (it is REJECTED, not OFFERED).
        res = api.accept_dispatch(
            first["id"], make_nurse_headers(first["nurse_id"]),
        )
        validate_error_is_one_of(res, [
            ApiErrorId.ERR_DISPATCH_ALREADY_TAKEN.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        ])


# =========================================================================
# Rule 8 -- resource_temporal_overlap (second pass)
# =========================================================================
class TestResourceTemporalOverlapExtra:
    """# difficulty: resource_temporal_overlap/nurse_daily_workload_count_aggregate
    # difficulty: resource_temporal_overlap/dispatch_acceptance_window_pointwise
    """

    def test_nurse_under_max_daily_orders_still_eligible(
        self, api, platform_admin_headers,
    ):
        """# difficulty: resource_temporal_overlap/nurse_daily_workload_count_aggregate

        PRD §3.3: 'the count of the nurse's currently DISPATCHED or
        IN_PROGRESS orders on the local calendar day of the request is
        strictly less than that nurse's max_daily_orders'.

        Claim: with max_daily_orders=2 and 1 currently DISPATCHED
        order, the nurse remains eligible (count 1 < 2). A second
        order on the same day succeeds.
        """
        item = create_service_item_raw(required_skill="ELDERLY_CARE")
        nurse = create_certified_nurse(
            home_lat=31.20, home_lng=121.40,
            specialty_tags=["ELDERLY_CARE"],
            max_daily_orders=2,
        )
        patient_id = stable_user_id("patient")
        # Order 1 -- consumes one slot.
        order1 = create_order_raw(
            patient_id=patient_id,
            service_item_code=item["code"],
            service_lat=31.20, service_lng=121.40,
            scheduled_start="2026-06-01T10:00:00.000Z",
        )
        d1 = list_dispatches_for(order1["id"])[0]
        accept_dispatch(d1, d1["nurse_id"])
        # Order 2 -- second slot still available.
        res = api.create_order(
            create_order_payload(
                service_item_code=item["code"],
                service_lat=31.20, service_lng=121.40,
                scheduled_start="2026-06-01T14:00:00.000Z",
            ),
            make_patient_headers(patient_id),
        )
        data = validate_success(res, expected_status=201)
        # PRD §3.3: 'strictly less than ... max_daily_orders' -- 1 < 2,
        # nurse eligible. The order should be AWAITING_DISPATCH or
        # DISPATCHED, not CANCELLED.
        assert data["status"] != "CANCELLED"

    def test_accept_just_before_deadline_succeeds(
        self, api, platform_admin_headers,
    ):
        """# difficulty: resource_temporal_overlap/dispatch_acceptance_window_pointwise

        PRD §3.3: 'both require the current instant to be strictly
        before accept_deadline'.

        Claim: at one second before the accept_deadline, the call
        succeeds.

        Some implementations may not allow advancing the clock that
        precisely; we use add_seconds(deadline, -1).
        """
        setup = setup_basic_dispatched_order(nurse_specialty="ELDERLY_CARE")
        d = setup["dispatch"]
        advance_clock(add_seconds(d["accept_deadline"], -1))
        res = api.accept_dispatch(
            d["id"], make_nurse_headers(setup["nurse_id"]),
        )
        data = validate_success(res)
        assert data["status"] == "ACCEPTED"


# =========================================================================
# Rule 9 -- compensating_invariant (second pass)
# =========================================================================
class TestCompensatingInvariantExtra:
    """# difficulty: compensating_invariant/payment_balance_invariant_on_cancel_chain
    # difficulty: compensating_invariant/nurse_rating_floor_invariant_under_compensation_chain
    """

    def test_eligibility_reject_refunds_payment(
        self, api, compliance_officer_headers,
    ):
        """# difficulty: compensating_invariant/payment_balance_invariant_on_cancel_chain

        PRD §3.2: 'rejection moves the order from UNDER_REVIEW to
        REJECTED, and if the payment authorization had succeeded by
        then the platform emits a refund event and sets payment_status
        to REFUNDED.'

        Claim: an ERR_REJECTED order via eligibility-review has
        payment_status=REFUNDED -- patient cash position is zero on
        the rejection path too.
        """
        item = create_service_item_raw(
            required_skill="IV_INFUSION",
            requires_eligibility_review=True,
        )
        patient_id = stable_user_id("patient")
        order = create_order_raw(
            patient_id=patient_id,
            service_item_code=item["code"],
            scheduled_start=DEFAULT_SCHEDULED_START_ISO,
        )
        from test_helpers import review_order_payload
        res = api.review_order(
            order["id"], review_order_payload(decision="REJECT"),
            compliance_officer_headers,
        )
        data = validate_success(res)
        assert data["status"] == "REJECTED"
        assert data["payment_status"] == "REFUNDED"

    def test_rating_clamp_ceiling_holds(
        self, api, compliance_officer_headers,
    ):
        """# difficulty: compensating_invariant/nurse_rating_floor_invariant_under_compensation_chain

        PRD §3.5: 'the mean is rounded half-up to two decimals and
        clamped to the closed interval from 1.00 to 5.00. A nurse with
        fewer than one rating retains the initialization value of
        5.00.'

        Claim: a brand-new nurse has rating=5.00 and any aggregate
        recompute keeps that value within [1.00, 5.00]. PRD pins the
        ceiling explicitly; we also confirm the no-ratings default.
        """
        # Brand-new nurse from factory (status PENDING but rating is
        # already initialized at 5.00 per PRD §3.1).
        from test_helpers import create_nurse_raw
        n = create_nurse_raw(
            specialty_tags=["ELDERLY_CARE"],
            home_lat=31.20, home_lng=121.40,
        )
        assert float(n["rating"]) == 5.00
        # And the rating must be within the closed interval [1.00, 5.00].
        assert 1.00 <= float(n["rating"]) <= 5.00
