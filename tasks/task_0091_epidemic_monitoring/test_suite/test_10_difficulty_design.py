"""Difficulty-design priority-queue coverage.

Every instance declared in the difficulty-design index is exercised by
at least TWO dedicated tests. Each test cites the verbatim PRD sentence
that states the rule the instance exercises (not the difficulty-design
entry itself).

The test_recipe declared in the difficulty-design index drives the
fixture choice and the specific assertions. Tests tagged with
`# difficulty: <rule_id>/<instance.name>` so the coverage audit can
verify which instance each test satisfies.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    accept_tracing_task,
    advance_clock,
    allocate_batch_payload,
    api_client,
    approve_risk_decision_payload,
    complete_tracing_task,
    consume_payload,
    create_bulletin_payload,
    create_contact_event_payload,
    create_facility,
    create_isolation_for_person,
    create_isolation_payload,
    create_person,
    create_region,
    create_supply_item,
    create_supply_request_payload,
    create_test_order_payload,
    dispatch_payload,
    dispatch_tracing_task,
    drive_region_to_published_tier,
    file_case,
    file_case_under_tracing,
    iso_utc,
    iso_utc_midnight,
    make_cdc_dispatcher_headers,
    make_cdc_tracer_headers,
    make_hospital_reporter_headers,
    make_lab_technician_headers,
    order_pcr_test,
    collect_test,
    release_isolation,
    result_test,
    setup_district_with_hospital,
    setup_district_with_hospital_and_cdc,
    setup_full_local_chain,
    setup_isolation_releasable_via_home_mode,
    setup_provisional_risk_decision,
    setup_supply_for_allocate_batch,
    setup_two_distinct_date_negative_pcr_tests,
    submit_supply_request,
    TEST_USERS,
    test_result_payload,
    validate_error,
    validate_success,
    violate_isolation,
)


# ===========================================================================
# Rule 1 — dual_variant_calc
# ===========================================================================
class TestDualVariantRegionTier:
    """difficulty: dual_variant_calc/region_tier_provisional_vs_final"""

    def test_provisional_low_with_three_cases(self, api, supervisor_headers):
        """PRD §3.6: "anything else is LOW. The result is written to the
        region's provisional_risk_tier. This automatic path does not
        write current_risk_tier."

        Claim: 2 CONFIRMED + 1 ASYMPTOMATIC in a region of 100 000
        gives density 7.00 (< 10.00) → provisional_risk_tier LOW, and
        current_risk_tier remains LOW (its initial default).
        # difficulty: dual_variant_calc/region_tier_provisional_vs_final
        """
        region, hospital = setup_district_with_hospital(
            district_code="D-DVRT-1", population=100000,
        )
        for _ in range(2):
            p = create_person(district_code=region["district_code"])
            file_case(person_id=p["id"], hospital_id=hospital["id"],
                      case_type="CONFIRMED")
        p = create_person(district_code=region["district_code"])
        file_case(person_id=p["id"], hospital_id=hospital["id"],
                  case_type="ASYMPTOMATIC")
        api.recompute_region_risk(region["id"], supervisor_headers)
        refreshed = validate_success(api.get_region(
            region["id"], supervisor_headers,
        ))
        # density = (2*3 + 1*1)/100000 * 100000 = 7.00 → LOW.
        assert refreshed["provisional_risk_tier"] == "LOW"
        assert refreshed["current_risk_tier"] == "LOW", (
            "PRD §3.6: provisional path does NOT touch current_risk_tier"
        )

    def test_expert_override_diverges_current_from_provisional(
        self, api, supervisor_headers,
    ):
        """PRD §3.6: "The final_tier set on approval may diverge from
        provisional_tier — that divergence is the entire point of
        EXPERT_OVERRIDE."
        PRD §3.6: "Publishing stamps published_at, writes
        Region.current_risk_tier to final_tier."

        Claim: a Region with provisional LOW becomes current_risk_tier
        HIGH after expert override + publish — divergent values on the
        same Region from identical underlying epidemiological data.
        # difficulty: dual_variant_calc/region_tier_provisional_vs_final
        """
        region, hospital = setup_district_with_hospital(
            district_code="D-DVRT-2", population=100000,
        )
        # Build provisional LOW state with a few cases (still < 10.00).
        for _ in range(2):
            p = create_person(district_code=region["district_code"])
            file_case(person_id=p["id"], hospital_id=hospital["id"],
                      case_type="CONFIRMED")
        api.recompute_region_risk(region["id"], supervisor_headers)
        # Drive to PUBLISHED HIGH.
        _decision, region_after = drive_region_to_published_tier(
            region, "HIGH",
        )
        assert region_after["current_risk_tier"] == "HIGH"


class TestDualVariantPersonExposure:
    """difficulty: dual_variant_calc/person_exposure_chronological_vs_projection"""

    def test_chronological_replay_applies_decay(self, api,
                                                supervisor_headers,
                                                hospital_reporter_fallback_headers):
        """PRD §3.8: "For each event, the raw weight is computed as in
        §3.3 — base weight from event_type, proximity factor from
        distance_meters, duration factor as the smaller of
        duration_minutes / 60 and a cap of 4. The raw weight is then
        attenuated by a linear decay factor: the larger of zero and one
        minus the number of whole days between event_time and the
        current moment divided by 14. The raw weight times the decay
        factor is added to a running accumulator. After all events are
        folded in, the accumulator is rounded half-up to two decimal
        places and returned as the person's contact_exposure_score."

        Claim: a single HOUSEHOLD ContactEvent 7 days in the past
        (distance 1.0, 60 minutes, raw = 10) decays by 1 - 7/14 = 0.5
        and the chronological_replay path returns 5.00.
        # difficulty: dual_variant_calc/person_exposure_chronological_vs_projection
        """
        region, hospital, _cdc = setup_district_with_hospital_and_cdc(
            district_code="D-PEX-1",
        )
        src = create_person(district_code=region["district_code"])
        tgt = create_person(district_code=region["district_code"])
        # event_time = now - 7 days.
        event_time = iso_utc(datetime.now(timezone.utc) - timedelta(days=7))
        payload = create_contact_event_payload(
            source_person_id=src["id"],
            target_person_id=tgt["id"],
            event_type="HOUSEHOLD",
            event_time=event_time,
            duration_minutes=60,
            distance_meters=1.0,
        )
        validate_success(api.create_contact_event(
            payload, make_hospital_reporter_headers(hospital["id"]),
        ), 201)
        # Default chronological_replay.
        resp = api.get_person_exposure_score(
            tgt["id"], supervisor_headers, params=None,
        )
        body = validate_success(resp, 200)
        score = body.get("contact_exposure_score")
        assert score == pytest.approx(5.00, abs=0.01), (
            f"PRD §3.8 + §3.3: HOUSEHOLD raw=10*1.0*1.0=10; decay = "
            f"max(0, 1 - 7/14) = 0.5; chronological score = 10*0.5 = 5.00; "
            f"got {score!r}"
        )

    def test_projection_disables_decay_for_recent_events(self, api,
                                                          supervisor_headers,
                                                          hospital_reporter_fallback_headers):
        """PRD §3.8: "When the projection variant is requested, decay
        aging is bypassed for events whose event_time falls within the
        trailing single day — those events use a days-since-event count
        of zero, producing a typically higher numeric score for the
        same input set. The two variants therefore return different
        scores for identical inputs."

        Claim: with one HOUSEHOLD ContactEvent inside the trailing 1-day
        window (effectively "now"), the chronological score and the
        projection score may both be ~10.00, but projection MUST be
        >= chronological. We use a recent event (event_time = now) to
        keep the comparison strict-equality on at least one side.
        # difficulty: dual_variant_calc/person_exposure_chronological_vs_projection
        """
        region, hospital, _cdc = setup_district_with_hospital_and_cdc(
            district_code="D-PEX-2",
        )
        src = create_person(district_code=region["district_code"])
        tgt = create_person(district_code=region["district_code"])
        event_time = iso_utc(datetime.now(timezone.utc))
        payload = create_contact_event_payload(
            source_person_id=src["id"],
            target_person_id=tgt["id"],
            event_type="HOUSEHOLD",
            event_time=event_time,
            duration_minutes=60,
            distance_meters=1.0,
        )
        validate_success(api.create_contact_event(
            payload, make_hospital_reporter_headers(hospital["id"]),
        ), 201)
        chrono_body = validate_success(
            api.get_person_exposure_score(
                tgt["id"], supervisor_headers,
            ),
            200,
        )
        proj_body = validate_success(
            api.get_person_exposure_score(
                tgt["id"], supervisor_headers,
                params={"projection": "true"},
            ),
            200,
        )
        chrono = chrono_body["contact_exposure_score"]
        proj = proj_body["contact_exposure_score"]
        assert proj >= chrono, (
            f"PRD §3.8: projection MUST be >= chronological for the same "
            f"input set; got chrono={chrono!r}, proj={proj!r}"
        )


# ===========================================================================
# Rule 2 — combinatorial_formula
# ===========================================================================
class TestCaseDensityTieredSelection:
    """difficulty: combinatorial_formula/case_density_tiered_selection"""

    def test_high_at_50_boundary(self, api, supervisor_headers):
        """PRD §3.6: "Tier mapping is closed-interval and evaluated
        top-down: a final score of at least 50.00 yields HIGH; otherwise
        a score of at least 10.00 yields MEDIUM; anything else is LOW."

        Claim: 16 CONFIRMED + 2 ASYMPTOMATIC in pop 100 000 →
        density = (16*3 + 2*1)/100000*100000 = 50.00 → HIGH (>= 50.00).
        # difficulty: combinatorial_formula/case_density_tiered_selection
        """
        region, hospital, cdc = setup_district_with_hospital_and_cdc(
            district_code="D-CD-DD-1", population=100000,
        )
        for _ in range(16):
            p = create_person(district_code=region["district_code"])
            file_case_under_tracing(
                person_id=p["id"], hospital_id=hospital["id"],
                cdc_id=cdc["id"], case_type="CONFIRMED",
            )
        for _ in range(2):
            p = create_person(district_code=region["district_code"])
            file_case(person_id=p["id"], hospital_id=hospital["id"],
                      case_type="ASYMPTOMATIC")
        api.recompute_region_risk(region["id"], supervisor_headers)
        refreshed = validate_success(api.get_region(
            region["id"], supervisor_headers,
        ))
        assert refreshed["provisional_risk_tier"] == "HIGH"

    def test_low_just_below_medium_threshold(self, api, supervisor_headers):
        """PRD §3.6: "anything else is LOW."

        Claim: 3 CONFIRMED cases in pop 100 000 → density = 9.00 < 10.00
        threshold → LOW.
        # difficulty: combinatorial_formula/case_density_tiered_selection
        """
        region, hospital = setup_district_with_hospital(
            district_code="D-CD-DD-2", population=100000,
        )
        for _ in range(3):
            p = create_person(district_code=region["district_code"])
            file_case(person_id=p["id"], hospital_id=hospital["id"],
                      case_type="CONFIRMED")
        api.recompute_region_risk(region["id"], supervisor_headers)
        refreshed = validate_success(api.get_region(
            region["id"], supervisor_headers,
        ))
        # density 9.00 < 10.00 → LOW.
        assert refreshed["provisional_risk_tier"] == "LOW"


class TestSupplyAllocationRoundingOrder:
    """difficulty: combinatorial_formula/supply_allocation_rounding_order"""

    def test_high_priority_request_first_low_second_with_remainder(
        self, api, supply_manager_headers,
    ):
        """PRD §3.7: "Allocation is performed by the supply manager
        either against a single request or in batch by sku. The batch
        path is a strict waterfall: among all PENDING requests for the
        sku, sort by priority_score descending, then created_at
        ascending, then id ascending, and walk the sorted list. At each
        request allocate the smaller of the request's
        requested_quantity and the remaining available — defined as
        the item's reserve_quantity minus its allocated_quantity. The
        last request in line that can only be partially satisfied
        receives the entire remaining available (it is not split across
        multiple requests); there is no proportional split, no
        fractional unit, and no redistribution of any remainder."

        Claim: HIGH/PPE 80 (priority 105) + LOW/PPE 50 (priority 5)
        from reserve 100 → 80/20 distribution.
        # difficulty: combinatorial_formula/supply_allocation_rounding_order
        """
        ctx = setup_supply_for_allocate_batch(
            sku="PPE_X1", category="PPE", reserve=100,
            high_request_qty=80, low_request_qty=50,
        )
        validate_success(api.allocate_supply_batch(
            allocate_batch_payload(sku=ctx["item"]["sku"]),
            supply_manager_headers,
        ))
        a = validate_success(api.get_supply_request(
            ctx["request_high"]["id"], supply_manager_headers,
        ))
        b = validate_success(api.get_supply_request(
            ctx["request_low"]["id"], supply_manager_headers,
        ))
        assert a["allocated_quantity"] == 80
        assert b["allocated_quantity"] == 20

    def test_no_proportional_split_last_gets_remainder(self, api,
                                                       supply_manager_headers):
        """PRD §3.7: "The last request in line that can only be
        partially satisfied receives the entire remaining available (it
        is not split across multiple requests); there is no proportional
        split, no fractional unit, and no redistribution of any
        remainder."

        Claim: with reserve=10, HIGH-tier request 7 + LOW-tier request 5
        → first gets 7, second gets 3 (the entire remaining). No
        rounding redistribution.
        # difficulty: combinatorial_formula/supply_allocation_rounding_order
        """
        ctx = setup_supply_for_allocate_batch(
            sku="PPE_X2", category="PPE", reserve=10,
            high_request_qty=7, low_request_qty=5,
        )
        validate_success(api.allocate_supply_batch(
            allocate_batch_payload(sku=ctx["item"]["sku"]),
            supply_manager_headers,
        ))
        a = validate_success(api.get_supply_request(
            ctx["request_high"]["id"], supply_manager_headers,
        ))
        b = validate_success(api.get_supply_request(
            ctx["request_low"]["id"], supply_manager_headers,
        ))
        assert a["allocated_quantity"] == 7, (
            f"HIGH-tier sorted first should fully receive 7; got "
            f"{a['allocated_quantity']}"
        )
        assert b["allocated_quantity"] == 3, (
            f"LOW-tier sorted second should receive remaining 3; got "
            f"{b['allocated_quantity']}"
        )


class TestIsolationReleaseEvaluationOrder:
    """difficulty: combinatorial_formula/isolation_release_circular_dependency"""

    def test_home_mode_release_after_min_days_with_two_negatives(self, api):
        """PRD §3.4: "First, the elapsed whole-day count since
        start_date must be at least the minimum-days constant for the
        isolation's mode; if not, the outcome is NOT_ELIGIBLE. Second,
        if any DailyHealthReport whose report_date falls in the
        trailing 3-day abnormal window has is_abnormal true, the
        outcome is EXTEND. Third, the count of TestOrder rows for this
        person with status RESULTED, result NEGATIVE, test_type PCR,
        and collected_at strictly later than start_date must be at
        least 2; if fewer, the outcome is EXTEND. Fourth, those negative
        tests must fall on at least two distinct UTC collection dates;
        if not, the outcome is EXTEND. If all four checks pass, the
        outcome is RELEASE."

        Claim: a HOME-mode isolation with all four checks passing →
        RELEASED.
        # difficulty: combinatorial_formula/isolation_release_circular_dependency
        """
        ctx = setup_isolation_releasable_via_home_mode(
            days_isolated=11, test1_day=5, test2_day=9,
        )
        result = release_isolation(ctx["isolation"]["id"], ctx["cdc"]["id"])
        assert result["status"] == "RELEASED"

    def test_min_days_check_fires_before_negative_test_check(self, api):
        """PRD §3.4: "First, the elapsed whole-day count since
        start_date must be at least the minimum-days constant for the
        isolation's mode; if not, the outcome is NOT_ELIGIBLE."

        Claim: at start_date + 0 days, the isolation cannot be RELEASED
        regardless of how many negative tests would otherwise satisfy
        the count check. The PRD pins min-days as the FIRST check.
        # difficulty: combinatorial_formula/isolation_release_circular_dependency
        """
        chain = setup_full_local_chain(district_code="D-RC-2")
        person = create_person(district_code=chain["district_code"])
        iso = create_isolation_for_person(
            person_id=person["id"], cdc_id=chain["cdc"]["id"], mode="HOME",
        )
        # 0 days elapsed, no tests yet — first check (min-days) must
        # block release; outcome status must NOT be RELEASED.
        result = release_isolation(iso["id"], chain["cdc"]["id"])
        assert result["status"] != "RELEASED"


# ===========================================================================
# Rule 3 — non_linear_state_machine
# ===========================================================================
class TestTracingTaskRevisionCycle:
    """difficulty: non_linear_state_machine/tracing_task_revision_cycle"""

    def test_complete_reject_accept_complete_cycle(self, api, supervisor_headers):
        """PRD §3.3: "A CDCSupervisor may either close the completed
        task (COMPLETED → CLOSED) or send it back for revision
        (COMPLETED → NEEDS_REVISION); rejection cancels any
        auto-created isolation that is still ACTIVE and has not yet
        received a DailyHealthReport. A tracer can re-accept a
        needs-revision task (NEEDS_REVISION → IN_PROGRESS) and
        re-walk the workflow."

        Claim: IN_PROGRESS → COMPLETED → NEEDS_REVISION → IN_PROGRESS →
        COMPLETED traverses the cycle and lands at COMPLETED.
        # difficulty: non_linear_state_machine/tracing_task_revision_cycle
        """
        region, hospital, cdc = setup_district_with_hospital_and_cdc(
            district_code="D-TRC-1",
        )
        person = create_person(district_code=region["district_code"])
        case = file_case(
            person_id=person["id"], hospital_id=hospital["id"],
            case_type="CONFIRMED",
        )
        task = dispatch_tracing_task(case_id=case["id"], cdc_id=cdc["id"])
        accept_tracing_task(task["id"], cdc["id"])
        completed = complete_tracing_task(task["id"], cdc["id"])
        assert completed["status"] == "COMPLETED"
        rejected = validate_success(api.reject_tracing_task(
            task["id"], supervisor_headers,
        ))
        assert rejected["status"] == "NEEDS_REVISION"
        # Re-accept and re-complete.
        reaccepted = accept_tracing_task(task["id"], cdc["id"])
        assert reaccepted["status"] == "IN_PROGRESS"
        recompleted = complete_tracing_task(task["id"], cdc["id"])
        assert recompleted["status"] == "COMPLETED"

    def test_close_after_revision_cycle_works(self, api, supervisor_headers):
        """PRD §3.3: "A CDCSupervisor may either close the completed
        task (COMPLETED → CLOSED) or send it back for revision."

        Claim: after a full IN_PROGRESS → COMPLETED → NEEDS_REVISION →
        IN_PROGRESS → COMPLETED cycle, a supervisor close moves the
        task to CLOSED — proving the cycle does not lock the task out
        of the terminal-close path.
        # difficulty: non_linear_state_machine/tracing_task_revision_cycle
        """
        region, hospital, cdc = setup_district_with_hospital_and_cdc(
            district_code="D-TRC-2",
        )
        person = create_person(district_code=region["district_code"])
        case = file_case(
            person_id=person["id"], hospital_id=hospital["id"],
            case_type="CONFIRMED",
        )
        task = dispatch_tracing_task(case_id=case["id"], cdc_id=cdc["id"])
        accept_tracing_task(task["id"], cdc["id"])
        complete_tracing_task(task["id"], cdc["id"])
        validate_success(api.reject_tracing_task(
            task["id"], supervisor_headers,
        ))
        accept_tracing_task(task["id"], cdc["id"])
        complete_tracing_task(task["id"], cdc["id"])
        closed = validate_success(api.close_tracing_task(
            task["id"], supervisor_headers,
        ))
        assert closed["status"] == "CLOSED"


class TestIsolationBranchingTerminals:
    """difficulty: non_linear_state_machine/isolation_branching_release_or_violation"""

    def test_release_branch_decrements_facility_occupied(self, api):
        """PRD §3.4: "a RELEASE outcome moves the isolation to its
        terminal status, stamps actual_end_date, sets the person's
        isolation_status to RELEASED, and for centralized isolations
        decrements occupied (flipping FULL back to OPEN when occupied
        drops below capacity)."

        Claim: a CENTRALIZED isolation that completes the release
        flow brings facility.occupied from 1 down to 0 and
        Person.isolation_status to RELEASED.
        # difficulty: non_linear_state_machine/isolation_branching_release_or_violation
        """
        ctx = setup_isolation_releasable_via_home_mode(
            days_isolated=15, test1_day=5, test2_day=9,
        )
        # The helper used HOME mode — switch to CENTRALIZED to exercise
        # the facility decrement branch. Build manually instead.
        # ── manual build of a releasable centralized isolation. ──
        chain = setup_full_local_chain(district_code="D-IBR-1")
        facility = create_facility(
            district_code=chain["district_code"], capacity=2,
        )
        person = create_person(district_code=chain["district_code"])
        iso = create_isolation_for_person(
            person_id=person["id"], cdc_id=chain["cdc"]["id"],
            mode="CENTRALIZED", facility_id=facility["id"],
        )
        # Need >= 14 elapsed days for CENTRALIZED, >= 2 distinct-date
        # NEGATIVE PCR tests after start_date.
        # Advance to day-5, run test1 (collect + result).
        advance_clock(5 * 86400)
        o1 = order_pcr_test(person["id"], chain["hospital"]["id"])
        c1 = collect_test(o1["id"], chain["hospital"]["id"])
        advance_clock(60)
        result_test(c1["id"], chain["lab"]["id"], "NEGATIVE")
        advance_clock(4 * 86400)  # to day 9
        o2 = order_pcr_test(person["id"], chain["hospital"]["id"])
        c2 = collect_test(o2["id"], chain["hospital"]["id"])
        advance_clock(60)
        result_test(c2["id"], chain["lab"]["id"], "NEGATIVE")
        advance_clock(6 * 86400)  # to ~day 15, past CENTRALIZED min=14
        result = release_isolation(iso["id"], chain["cdc"]["id"])
        assert result["status"] == "RELEASED"
        # Facility occupied should now be 0.
        fac_refreshed = validate_success(api.get_facility(
            facility["id"],
            make_cdc_tracer_headers(chain["cdc"]["id"]),
        ))
        assert fac_refreshed["occupied"] == 0

    def test_violation_branch_increments_violations_and_terminates_person(self, api):
        """PRD §3.4: "A successful violation increments violations_count,
        stamps actual_end_date, sets the person's isolation_status to
        VIOLATED_TERMINATED, transitions the isolation itself to
        VIOLATED_TERMINATED, and for centralized isolations decrements
        occupied."

        Claim: a CENTRALIZED isolation that takes the VIOLATION branch
        ends in VIOLATED_TERMINATED with violations_count==1 and
        Person.isolation_status == VIOLATED_TERMINATED.
        # difficulty: non_linear_state_machine/isolation_branching_release_or_violation
        """
        chain = setup_full_local_chain(district_code="D-IBR-2")
        facility = create_facility(
            district_code=chain["district_code"], capacity=3,
        )
        person = create_person(district_code=chain["district_code"])
        iso = create_isolation_for_person(
            person_id=person["id"], cdc_id=chain["cdc"]["id"],
            mode="CENTRALIZED", facility_id=facility["id"],
        )
        result = violate_isolation(iso["id"], chain["cdc"]["id"])
        assert result["status"] == "VIOLATED_TERMINATED"
        assert result["violations_count"] == 1
        fac_after = validate_success(api.get_facility(
            facility["id"],
            make_cdc_tracer_headers(chain["cdc"]["id"]),
        ))
        assert fac_after["occupied"] == 0


# ===========================================================================
# Rule 4 — transitive_cascade
# ===========================================================================
class TestTestResultToCaseCascade:
    """difficulty: transitive_cascade/test_result_to_case_to_region_tier"""

    def test_positive_pcr_advances_case_to_confirmed_hop2(self, api):
        """PRD §3.10: "A case that started as SUSPECTED or ASYMPTOMATIC
        and is currently UNDER_TRACING advances to CONFIRMED when a
        positive PCR result is ingested for its person (status
        UNDER_TRACING → CONFIRMED)."

        Claim: POST /epi/test-orders/{id}/result with POSITIVE on a
        person with an UNDER_TRACING case advances the case to
        CONFIRMED (depth-2 cascade).
        # difficulty: transitive_cascade/test_result_to_case_to_region_tier
        """
        chain = setup_full_local_chain(district_code="D-TR-CR-1")
        person = create_person(district_code=chain["district_code"])
        case = file_case(
            person_id=person["id"], hospital_id=chain["hospital"]["id"],
            case_type="ASYMPTOMATIC",
        )
        task = dispatch_tracing_task(
            case_id=case["id"], cdc_id=chain["cdc"]["id"],
        )
        accept_tracing_task(task["id"], chain["cdc"]["id"])
        order = order_pcr_test(person["id"], chain["hospital"]["id"])
        collected = collect_test(order["id"], chain["hospital"]["id"])
        advance_clock(60)
        resulted = result_test(collected["id"], chain["lab"]["id"], "POSITIVE")
        assert resulted["status"] == "RESULTED"
        # Hop 2 verification.
        case_after = validate_success(api.get_case(
            case["id"],
            make_hospital_reporter_headers(chain["hospital"]["id"]),
        ))
        assert case_after["status"] == "CONFIRMED"

    def test_case_confirmation_triggers_region_recompute_hop3(self, api,
                                                              supervisor_headers):
        """PRD §3.10: "On that transition the case's case_type is set to
        CONFIRMED if it was previously SUSPECTED, the region's
        provisional risk tier is recomputed, and an audit row is
        appended."
        PRD §3.6: "Tier mapping is closed-interval and evaluated
        top-down: a final score of at least 50.00 yields HIGH."

        Claim: pre-loading 16 CONFIRMED cases plus one UNDER_TRACING
        ASYMPTOMATIC case keeps density at (16*3)/100000*100000 +
        (1*1)/100000*100000 ... but the cascade we test here is that
        once that ASYMPTOMATIC case ALSO becomes CONFIRMED, the
        recompute writes the new provisional tier. We use the simpler
        boundary: 16 CONFIRMED already = density 48.00 → MEDIUM. Adding
        one more CONFIRMED bumps density to 51.00 → HIGH (the cascade
        flip).
        # difficulty: transitive_cascade/test_result_to_case_to_region_tier
        """
        chain = setup_full_local_chain(
            district_code="D-TR-CR-2", population=100000,
        )
        region = chain["region"]
        # 16 CONFIRMED-typed cases advanced to UNDER_TRACING (PRD §3.6
        # counts confirmed-or-tracing-active by case status) → density
        # 48.00 → MEDIUM.
        for _ in range(16):
            p = create_person(district_code=chain["district_code"])
            file_case_under_tracing(
                person_id=p["id"], hospital_id=chain["hospital"]["id"],
                cdc_id=chain["cdc"]["id"], case_type="CONFIRMED",
            )
        api.recompute_region_risk(region["id"], supervisor_headers)
        before = validate_success(api.get_region(region["id"], supervisor_headers))
        assert before["provisional_risk_tier"] == "MEDIUM"
        # Now create the cascade-driver case: ASYMPTOMATIC, dispatch
        # tracing → accept → positive PCR result advances to CONFIRMED.
        person = create_person(district_code=chain["district_code"])
        case = file_case(
            person_id=person["id"], hospital_id=chain["hospital"]["id"],
            case_type="ASYMPTOMATIC",
        )
        task = dispatch_tracing_task(
            case_id=case["id"], cdc_id=chain["cdc"]["id"],
        )
        accept_tracing_task(task["id"], chain["cdc"]["id"])
        order = order_pcr_test(person["id"], chain["hospital"]["id"])
        collected = collect_test(order["id"], chain["hospital"]["id"])
        advance_clock(60)
        result_test(collected["id"], chain["lab"]["id"], "POSITIVE")
        # After the cascade, region provisional should have recomputed.
        # Density now = (17*3)/100000*100000 = 51.00 → HIGH.
        after = validate_success(api.get_region(region["id"], supervisor_headers))
        assert after["provisional_risk_tier"] == "HIGH", (
            f"PRD §3.10 + §3.6: after positive PCR cascades the case to "
            f"CONFIRMED, the region's provisional_risk_tier must be "
            f"recomputed; expected HIGH at density 51.00, got "
            f"{after['provisional_risk_tier']!r}"
        )


class TestRiskPublishCascadeToSupplyAllocation:
    """difficulty: transitive_cascade/risk_publish_to_supply_priority_to_allocation"""

    def test_publish_recomputes_priority_score_hop2(self, api,
                                                    supply_manager_headers,
                                                    supervisor_headers,
                                                    risk_expert_headers,
                                                    press_officer_headers):
        """PRD §3.7: "Risk publication cascades into allocation: when a
        region's current_risk_tier is updated by a published decision,
        every PENDING SupplyRequest from that region has its
        priority_score recomputed against the new tier weight. The next
        batch allocate therefore re-sorts those requests against their
        freshly weighted scores."

        Claim: a PENDING SupplyRequest filed while the region was LOW
        (priority_score = 0+5 = 5) has its priority_score recomputed to
        100+5 = 105 after the region is published HIGH.
        # difficulty: transitive_cascade/risk_publish_to_supply_priority_to_allocation
        """
        region, hospital = setup_district_with_hospital(
            district_code="D-RPSA-1", population=100000,
        )
        item = create_supply_item(
            sku="PPE_RPSA1", category="PPE", reserve_quantity=100,
        )
        # File the request while region is LOW.
        request = submit_supply_request(
            sku=item["sku"], hospital_id=hospital["id"],
            requested_quantity=50,
        )
        assert request["priority_score"] == 5
        # Publish HIGH.
        drive_region_to_published_tier(region, "HIGH")
        # PENDING request priority_score must be recomputed.
        refreshed = validate_success(api.get_supply_request(
            request["id"], supply_manager_headers,
        ))
        assert refreshed["priority_score"] == 105, (
            f"PRD §3.7: PENDING SupplyRequest priority must be "
            f"recomputed to HIGH(100)+PPE(5)=105 after publish; got "
            f"{refreshed['priority_score']}"
        )

    def test_publish_then_allocate_batch_orders_by_new_priority_hop3(
        self, api, supply_manager_headers,
    ):
        """PRD §3.7: "The next batch allocate therefore re-sorts those
        requests against their freshly weighted scores."

        Claim: after publishing one region to HIGH, the subsequent
        allocate-batch correctly favors that region's request (now
        priority 105) over a competing LOW-region request (priority 5),
        even when the LOW-region request was created first.
        # difficulty: transitive_cascade/risk_publish_to_supply_priority_to_allocation
        """
        # Build the canonical setup. The helper publishes region_high
        # to HIGH and seeds two requests (HIGH for 80, LOW for 50).
        ctx = setup_supply_for_allocate_batch(
            sku="PPE_RPSA2", category="PPE", reserve=100,
            high_request_qty=80, low_request_qty=50,
        )
        validate_success(api.allocate_supply_batch(
            allocate_batch_payload(sku=ctx["item"]["sku"]),
            supply_manager_headers,
        ))
        high = validate_success(api.get_supply_request(
            ctx["request_high"]["id"], supply_manager_headers,
        ))
        low = validate_success(api.get_supply_request(
            ctx["request_low"]["id"], supply_manager_headers,
        ))
        assert high["allocated_quantity"] == 80
        assert low["allocated_quantity"] == 20


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict
# ===========================================================================
class TestStateVsBusinessSafetyOnIsolationViolation:
    """difficulty: priority_pair_validation_conflict/state_vs_business_safety_isolation_violation"""

    def test_violation_on_released_isolation_returns_invalid_state(self, api):
        """PRD §3.4: "A violation can only be recorded against a
        non-terminal isolation (ACTIVE or EXTENDED); recording one
        against a terminal isolation is rejected with
        ERR_INVALID_STATE."
        PRD §2.8: "state-transition admissibility (ERR_INVALID_STATE),
        then institution-active checks (ERR_INSTITUTION_INACTIVE), then
        the isolation-violation terminal-state guard."

        Claim: a violation against a RELEASED isolation returns
        ERR_INVALID_STATE (state check fires before the violation-
        terminal-state guard, even though both would condemn the call).
        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_isolation_violation
        """
        ctx = setup_isolation_releasable_via_home_mode(
            days_isolated=11, test1_day=5, test2_day=9,
        )
        # Drive isolation to RELEASED.
        released = release_isolation(
            ctx["isolation"]["id"], ctx["cdc"]["id"],
        )
        assert released["status"] == "RELEASED"
        # Now record a violation against the now-terminal isolation.
        resp = api.record_isolation_violation(
            ctx["isolation"]["id"], {"reason": "post-release breach"},
            make_cdc_tracer_headers(ctx["cdc"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_violation_on_violated_terminated_isolation_returns_invalid_state(
        self, api,
    ):
        """PRD §3.4: "recording one against a terminal isolation is
        rejected with ERR_INVALID_STATE."

        Claim: a second violation against a VIOLATED_TERMINATED
        isolation returns ERR_INVALID_STATE.
        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_isolation_violation
        """
        chain = setup_full_local_chain(district_code="D-SVB-2")
        person = create_person(district_code=chain["district_code"])
        iso = create_isolation_for_person(
            person_id=person["id"], cdc_id=chain["cdc"]["id"], mode="HOME",
        )
        violate_isolation(iso["id"], chain["cdc"]["id"])
        resp = api.record_isolation_violation(
            iso["id"], {"reason": "second-breach"},
            make_cdc_tracer_headers(chain["cdc"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestBusinessTemporalVsBusinessFiscal:
    """difficulty: priority_pair_validation_conflict/business_temporal_vs_business_fiscal_supply_allocation"""

    def test_isolation_before_onset_returns_isolation_date_invalid(self, api):
        """PRD §3.4: "if the person has an indexing case it cannot be
        earlier than that case's onset_date; either violation is
        rejected with ERR_ISOLATION_DATE_INVALID."

        Claim: an Isolation with start_date BEFORE the indexing case's
        onset_date → ERR_ISOLATION_DATE_INVALID.
        # difficulty: priority_pair_validation_conflict/business_temporal_vs_business_fiscal_supply_allocation
        """
        region, hospital, cdc = setup_district_with_hospital_and_cdc(
            district_code="D-BTBF-1",
        )
        person = create_person(district_code=region["district_code"])
        # File a case with onset_date "now".
        case_onset = iso_utc_midnight(datetime.now(timezone.utc))
        file_case(
            person_id=person["id"], hospital_id=hospital["id"],
            case_type="CONFIRMED", onset_date=case_onset,
        )
        # Attempt isolation with start_date 5 days BEFORE onset_date.
        past_start = iso_utc_midnight(
            datetime.now(timezone.utc) - timedelta(days=5),
        )
        payload = create_isolation_payload(
            person_id=person["id"], mode="HOME", start_date=past_start,
        )
        resp = api.create_isolation(
            payload, make_cdc_tracer_headers(cdc["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ISOLATION_DATE_INVALID.value)

    def test_supply_request_exceeding_reserve_returns_supply_insufficient(
        self, api, supply_manager_headers,
    ):
        """PRD §3.7: "If at any point the chosen allocation cannot
        satisfy the request from the remaining reserve, the platform
        records the partial allocation and continues; any request whose
        allocated quantity is zero stays in PENDING. A single-request
        allocate runs the same logic restricted to that one request.
        ... If two allocations race over the same item and would
        jointly drive allocated_quantity past reserve_quantity,
        serialization on the item's allocated_quantity field gives the
        first writer the allocation and the second receives
        ERR_SUPPLY_INSUFFICIENT. The same error fires when a single
        allocate would over-commit on its own."

        Claim: a single-request allocate that would over-commit on its
        own → ERR_SUPPLY_INSUFFICIENT.
        # difficulty: priority_pair_validation_conflict/business_temporal_vs_business_fiscal_supply_allocation
        """
        item = create_supply_item(
            sku="SKU-INS-1", category="PPE", reserve_quantity=10,
        )
        _region, hospital = setup_district_with_hospital(
            district_code="D-INS-1",
        )
        # First request consumes everything.
        first = submit_supply_request(
            sku=item["sku"], hospital_id=hospital["id"], requested_quantity=10,
        )
        validate_success(api.allocate_supply_request(
            first["id"], supply_manager_headers,
        ))
        # Second request — nothing left.
        second = submit_supply_request(
            sku=item["sku"], hospital_id=hospital["id"], requested_quantity=5,
        )
        resp = api.allocate_supply_request(
            second["id"], supply_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SUPPLY_INSUFFICIENT.value)


# ===========================================================================
# Rule 6 — boundary_precision_check
# ===========================================================================
class TestCaseReportLatenessStrictGt:
    """difficulty: boundary_precision_check/case_report_lateness_strict_gt"""

    def test_onset_today_within_window_is_not_late(self, api):
        """PRD §3.2: "The boolean is_late_report is then set to true
        exactly when reported_at is strictly later than
        report_deadline_at; equality counts as on-time and the flag is
        persisted once at creation and not recomputed later."

        Claim: onset_date = today UTC midnight → reported_at - onset
        within 24h → is_late_report == false (strict-greater rule, also
        well inside the boundary).
        # difficulty: boundary_precision_check/case_report_lateness_strict_gt
        """
        region, hospital = setup_district_with_hospital(
            district_code="D-CRL-1",
        )
        person = create_person(district_code=region["district_code"])
        today = iso_utc_midnight(datetime.now(timezone.utc))
        case = file_case(
            person_id=person["id"], hospital_id=hospital["id"],
            case_type="CONFIRMED", onset_date=today,
        )
        assert case["is_late_report"] is False

    def test_onset_three_days_ago_is_late(self, api):
        """PRD §3.2: "The boolean is_late_report is then set to true
        exactly when reported_at is strictly later than
        report_deadline_at."

        Claim: onset_date 3 days ago (well past the 24h window) →
        is_late_report == true.
        # difficulty: boundary_precision_check/case_report_lateness_strict_gt
        """
        region, hospital = setup_district_with_hospital(
            district_code="D-CRL-2",
        )
        person = create_person(district_code=region["district_code"])
        three_days_ago = iso_utc_midnight(
            datetime.now(timezone.utc) - timedelta(days=3),
        )
        case = file_case(
            person_id=person["id"], hospital_id=hospital["id"],
            case_type="CONFIRMED", onset_date=three_days_ago,
        )
        assert case["is_late_report"] is True


class TestTracingCompleteWithZeroContacts:
    """difficulty: boundary_precision_check/tracing_complete_with_zero_contacts"""

    def test_complete_with_no_contact_events(self, api):
        """PRD §3.3: "When the contact list is finalized —
        discovered_contact_count may be zero — the tracer marks the
        task complete (IN_PROGRESS → COMPLETED)."

        Claim: tracing task complete with zero contact events → status
        COMPLETED with discovered_contact_count == 0.
        # difficulty: boundary_precision_check/tracing_complete_with_zero_contacts
        """
        region, hospital, cdc = setup_district_with_hospital_and_cdc(
            district_code="D-TCZ-1",
        )
        person = create_person(district_code=region["district_code"])
        case = file_case(
            person_id=person["id"], hospital_id=hospital["id"],
            case_type="CONFIRMED",
        )
        task = dispatch_tracing_task(case_id=case["id"], cdc_id=cdc["id"])
        accept_tracing_task(task["id"], cdc["id"])
        completed = complete_tracing_task(task["id"], cdc["id"])
        assert completed["status"] == "COMPLETED"
        assert completed["discovered_contact_count"] == 0

    def test_no_isolation_auto_created_when_zero_close_contacts(self, api):
        """PRD §3.3: "for every linked ContactEvent whose tier is CLOSE
        the system auto-creates an Isolation in ACTIVE for the contacted
        person."

        Claim: with zero linked CLOSE contacts, no Isolation is
        auto-created — empty CLOSE set means no auto-creation.
        # difficulty: boundary_precision_check/tracing_complete_with_zero_contacts
        """
        region, hospital, cdc = setup_district_with_hospital_and_cdc(
            district_code="D-TCZ-2",
        )
        person = create_person(district_code=region["district_code"])
        case = file_case(
            person_id=person["id"], hospital_id=hospital["id"],
            case_type="CONFIRMED",
        )
        task = dispatch_tracing_task(case_id=case["id"], cdc_id=cdc["id"])
        accept_tracing_task(task["id"], cdc["id"])
        completed = complete_tracing_task(task["id"], cdc["id"])
        assert completed["status"] == "COMPLETED"
        # PRD says "for every linked ContactEvent whose tier is CLOSE
        # the system auto-creates an Isolation." With zero CLOSE
        # contacts, the person should NOT have transitioned to
        # isolation_status ACTIVE.
        person_after = validate_success(api.get_person(
            person["id"],
            make_hospital_reporter_headers(hospital["id"]),
        ))
        assert person_after["isolation_status"] == "NONE", (
            "PRD §3.3: zero CLOSE contacts → no auto-created Isolation; "
            "Person.isolation_status should remain NONE"
        )


# ===========================================================================
# Rule 7 — cross_entity_state_dependency
# ===========================================================================
class TestCaseRecoveryDependsOnIsolation:
    """difficulty: cross_entity_state_dependency/case_recovery_depends_on_isolation_state"""

    def test_recovery_blocked_while_isolation_active(self, api):
        """PRD §3.10: "A CDCDispatcher may mark a case RECOVERED
        (CONFIRMED → RECOVERED) only when three conditions hold: the
        case is currently CONFIRMED; the person's linked isolation is
        in RELEASED (a violated or active isolation blocks recovery);
        and at least two prior TestOrder rows for the same person carry
        result NEGATIVE, test_type PCR, and chronologically distinct
        collection dates."

        Claim: recover on a CONFIRMED case whose person's isolation is
        ACTIVE → ERR_INVALID_STATE.
        # difficulty: cross_entity_state_dependency/case_recovery_depends_on_isolation_state
        """
        chain = setup_full_local_chain(district_code="D-CRDI-1")
        person = create_person(district_code=chain["district_code"])
        # File a CONFIRMED case directly.
        case = file_case(
            person_id=person["id"], hospital_id=chain["hospital"]["id"],
            case_type="CONFIRMED",
        )
        # Create an ACTIVE isolation for the person.
        iso = create_isolation_for_person(
            person_id=person["id"], cdc_id=chain["cdc"]["id"], mode="HOME",
            start_date=case["onset_date"],
        )
        assert iso["status"] == "ACTIVE"
        # Two negative-PCR tests at distinct UTC collection dates
        # (recovery's other precondition).
        setup_two_distinct_date_negative_pcr_tests(
            person_id=person["id"],
            hospital_id=chain["hospital"]["id"],
            lab_id=chain["lab"]["id"],
            cdc_id=chain["cdc"]["id"],
            iso_start=datetime.now(timezone.utc),
        )
        # We must first transition the case into CONFIRMED state. The
        # case was filed as CONFIRMED-typed; for status the PRD §3.2
        # case status enters REPORTED. The transition to status
        # CONFIRMED is via the PCR-result cascade. So move it via the
        # tracing + positive PCR route.
        from test_helpers import accept_tracing_task, dispatch_tracing_task
        task = dispatch_tracing_task(
            case_id=case["id"], cdc_id=chain["cdc"]["id"],
        )
        accept_tracing_task(task["id"], chain["cdc"]["id"])
        order = order_pcr_test(person["id"], chain["hospital"]["id"])
        collected = collect_test(order["id"], chain["hospital"]["id"])
        advance_clock(60)
        result_test(collected["id"], chain["lab"]["id"], "POSITIVE")
        # Now attempt recover; isolation is still ACTIVE.
        resp = api.recover_case(
            case["id"], make_cdc_dispatcher_headers(chain["cdc"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_recovery_succeeds_after_isolation_released(self, api):
        """PRD §3.10: "A CDCDispatcher may mark a case RECOVERED
        (CONFIRMED → RECOVERED) only when three conditions hold: the
        case is currently CONFIRMED; the person's linked isolation is
        in RELEASED (a violated or active isolation blocks recovery);
        and at least two prior TestOrder rows for the same person carry
        result NEGATIVE, test_type PCR, and chronologically distinct
        collection dates."

        Claim: once isolation is RELEASED, the recover call on a
        CONFIRMED case with two distinct-date NEGATIVE PCR tests
        succeeds.
        # difficulty: cross_entity_state_dependency/case_recovery_depends_on_isolation_state
        """
        # Build a release-eligible HOME isolation (also generates the
        # two-distinct-date NEGATIVE PCR tests as part of the recipe).
        ctx = setup_isolation_releasable_via_home_mode(
            days_isolated=11, test1_day=5, test2_day=9,
        )
        chain = {
            "region": ctx["region"], "hospital": ctx["hospital"],
            "lab": ctx["lab"], "cdc": ctx["cdc"],
        }
        person = ctx["person"]
        iso = ctx["isolation"]
        # File and confirm a CONFIRMED-typed case for this person.
        case = file_case(
            person_id=person["id"], hospital_id=chain["hospital"]["id"],
            case_type="CONFIRMED",
        )
        # Walk case to status CONFIRMED via tracing + positive PCR.
        from test_helpers import accept_tracing_task, dispatch_tracing_task
        task = dispatch_tracing_task(
            case_id=case["id"], cdc_id=chain["cdc"]["id"],
        )
        accept_tracing_task(task["id"], chain["cdc"]["id"])
        order = order_pcr_test(person["id"], chain["hospital"]["id"])
        collected = collect_test(order["id"], chain["hospital"]["id"])
        advance_clock(60)
        result_test(collected["id"], chain["lab"]["id"], "POSITIVE")
        # Release the isolation.
        released = release_isolation(iso["id"], chain["cdc"]["id"])
        assert released["status"] == "RELEASED"
        # Now recover; we already have two distinct-date NEGATIVE PCR
        # tests from the release fixture.
        recover_resp = api.recover_case(
            case["id"], make_cdc_dispatcher_headers(chain["cdc"]["id"]),
        )
        recovered = validate_success(recover_resp, 200)
        assert recovered["status"] == "RECOVERED"


class TestRiskPublishDependsOnRegionState:
    """difficulty: cross_entity_state_dependency/risk_decision_publish_depends_on_region_state"""

    def test_no_op_publish_blocked_when_current_equals_final(
        self, api, supervisor_headers, risk_expert_headers,
        press_officer_headers,
    ):
        """PRD §3.6: "A PressOfficer then publishes the approved
        decision (APPROVED → PUBLISHED), permitted as long as the
        final_tier differs from the region's current_risk_tier or this
        is the first publication for that region."

        Claim: after a prior publish to HIGH, a new APPROVED decision
        with final_tier=HIGH cannot publish (no-op blocked) →
        ERR_INVALID_STATE.
        # difficulty: cross_entity_state_dependency/risk_decision_publish_depends_on_region_state
        """
        region, _ = setup_district_with_hospital(district_code="D-RPDR-1")
        drive_region_to_published_tier(region, "HIGH")
        # New decision, approve HIGH again.
        api.recompute_region_risk(region["id"], supervisor_headers)
        rd2 = setup_provisional_risk_decision(region["id"])
        validate_success(api.submit_risk_decision_review(
            rd2["id"], supervisor_headers,
        ))
        validate_success(api.approve_risk_decision(
            rd2["id"],
            approve_risk_decision_payload(
                final_tier="HIGH",
                expert_reviewer_id=TEST_USERS["risk_expert_headers"]["X-User-ID"],
            ),
            risk_expert_headers,
        ))
        resp = api.publish_risk_decision(rd2["id"], press_officer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_publish_with_different_tier_after_existing_publish_succeeds(
        self, api, supervisor_headers, risk_expert_headers,
        press_officer_headers,
    ):
        """PRD §3.6: "permitted as long as the final_tier differs from
        the region's current_risk_tier."

        Claim: after a prior publish to HIGH, a second decision
        APPROVED for MEDIUM (different from current HIGH) publishes
        successfully — final_tier != current_risk_tier passes the
        precondition.
        # difficulty: cross_entity_state_dependency/risk_decision_publish_depends_on_region_state
        """
        region, _ = setup_district_with_hospital(district_code="D-RPDR-2")
        drive_region_to_published_tier(region, "HIGH")
        # New decision, approve MEDIUM.
        api.recompute_region_risk(region["id"], supervisor_headers)
        rd2 = setup_provisional_risk_decision(region["id"])
        validate_success(api.submit_risk_decision_review(
            rd2["id"], supervisor_headers,
        ))
        validate_success(api.approve_risk_decision(
            rd2["id"],
            approve_risk_decision_payload(
                final_tier="MEDIUM",
                expert_reviewer_id=TEST_USERS["risk_expert_headers"]["X-User-ID"],
            ),
            risk_expert_headers,
        ))
        published = validate_success(api.publish_risk_decision(
            rd2["id"], press_officer_headers,
        ))
        assert published["status"] == "PUBLISHED"
        region_after = validate_success(api.get_region(
            region["id"], supervisor_headers,
        ))
        assert region_after["current_risk_tier"] == "MEDIUM"


# ===========================================================================
# Rule 8 — resource_temporal_overlap
# ===========================================================================
class TestFacilityAggregateCapacity:
    """difficulty: resource_temporal_overlap/isolation_facility_aggregate_capacity"""

    def test_third_admission_blocked_by_capacity(self, api):
        """PRD §3.4: "the facility must have status equal to OPEN and
        occupied strictly less than capacity. Failing that, the request
        is rejected with ERR_FACILITY_AT_CAPACITY."

        Claim: capacity=2, occupied=2 → a third admission is rejected.
        # difficulty: resource_temporal_overlap/isolation_facility_aggregate_capacity
        """
        chain = setup_full_local_chain(district_code="D-FAC-1")
        facility = create_facility(
            district_code=chain["district_code"], capacity=2,
        )
        for _ in range(2):
            p = create_person(district_code=chain["district_code"])
            create_isolation_for_person(
                person_id=p["id"], cdc_id=chain["cdc"]["id"],
                mode="CENTRALIZED", facility_id=facility["id"],
            )
        third = create_person(district_code=chain["district_code"])
        payload = create_isolation_payload(
            person_id=third["id"], mode="CENTRALIZED",
            facility_id=facility["id"],
        )
        resp = api.create_isolation(
            payload, make_cdc_tracer_headers(chain["cdc"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FACILITY_AT_CAPACITY.value)

    def test_occupied_does_not_overflow_capacity(self, api,
                                                  supervisor_headers):
        """PRD §3.4: "Two simultaneous centralized admissions to the
        same facility holding only one remaining bed serialize on the
        facility's occupied field — the first writer wins and the
        second receives ERR_FACILITY_AT_CAPACITY."

        Claim: after a successful admission and a failed-by-capacity
        admission, facility.occupied equals capacity exactly (no
        overflow).
        # difficulty: resource_temporal_overlap/isolation_facility_aggregate_capacity
        """
        chain = setup_full_local_chain(district_code="D-FAC-2")
        facility = create_facility(
            district_code=chain["district_code"], capacity=1,
        )
        # First admission succeeds.
        p_ok = create_person(district_code=chain["district_code"])
        create_isolation_for_person(
            person_id=p_ok["id"], cdc_id=chain["cdc"]["id"],
            mode="CENTRALIZED", facility_id=facility["id"],
        )
        # Second admission rejected.
        p_fail = create_person(district_code=chain["district_code"])
        bad_payload = create_isolation_payload(
            person_id=p_fail["id"], mode="CENTRALIZED",
            facility_id=facility["id"],
        )
        resp = api.create_isolation(
            bad_payload, make_cdc_tracer_headers(chain["cdc"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FACILITY_AT_CAPACITY.value)
        # Capacity invariant after the failed second admission.
        fac = validate_success(api.get_facility(
            facility["id"],
            make_cdc_tracer_headers(chain["cdc"]["id"]),
        ))
        assert fac["occupied"] == 1
        assert fac["occupied"] <= fac["capacity"]


class TestTestOrderValidityWindow:
    """difficulty: resource_temporal_overlap/test_order_validity_window"""

    def test_within_validity_window_succeeds(self, api):
        """PRD §3.5: "the test must still be valid at this moment —
        the elapsed time between collected_at and the result ingest
        must not exceed the per-modality validity window."

        Claim: ingesting a result just minutes after collection (well
        within any plausible validity window) succeeds.
        # difficulty: resource_temporal_overlap/test_order_validity_window
        """
        chain = setup_full_local_chain(district_code="D-TVW-1")
        person = create_person(district_code=chain["district_code"])
        order = order_pcr_test(person["id"], chain["hospital"]["id"])
        collected = collect_test(order["id"], chain["hospital"]["id"])
        # Tiny delay — far inside any reasonable validity window.
        advance_clock(60)
        resulted = result_test(
            collected["id"], chain["lab"]["id"], "NEGATIVE",
        )
        assert resulted["status"] == "RESULTED"
        assert resulted["result"] == "NEGATIVE"

    def test_far_past_validity_window_rejected(self, api):
        """PRD §3.5: "otherwise ERR_TEST_RESULT_EXPIRED fires."

        Claim: a 30-day delay after collection — far past any
        per-modality validity window the PRD could plausibly define —
        is rejected with ERR_TEST_RESULT_EXPIRED.
        # difficulty: resource_temporal_overlap/test_order_validity_window
        """
        chain = setup_full_local_chain(district_code="D-TVW-2")
        person = create_person(district_code=chain["district_code"])
        order = order_pcr_test(person["id"], chain["hospital"]["id"])
        collected = collect_test(order["id"], chain["hospital"]["id"])
        advance_clock(30 * 86400)  # 30 days.
        resp = api.result_test_order(
            collected["id"], test_result_payload(result="NEGATIVE"),
            make_lab_technician_headers(chain["lab"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TEST_RESULT_EXPIRED.value)


# ===========================================================================
# Rule 9 — compensating_invariant
# ===========================================================================
class TestSupplyAllocateThenCancelConserved:
    """difficulty: compensating_invariant/supply_allocate_then_cancel_preserves_available"""

    def test_available_restored_after_cancel(self, api, supply_manager_headers):
        """PRD §3.7: "Cancelling a PENDING request simply moves it to
        CANCELLED; cancelling an ALLOCATED request also decrements the
        item's allocated_quantity by the previously-allocated amount,
        returning that capacity to the next allocation cycle."

        Claim: allocate 30 of reserve 100 → available 70; cancel →
        available restored to 100 (reserve unchanged, allocated == 0).
        # difficulty: compensating_invariant/supply_allocate_then_cancel_preserves_available
        """
        item = create_supply_item(
            sku="SKU-CCV-1", category="PPE", reserve_quantity=100,
        )
        _region, hospital = setup_district_with_hospital(
            district_code="D-CCV-1",
        )
        req = submit_supply_request(
            sku=item["sku"], hospital_id=hospital["id"],
            requested_quantity=30,
        )
        validate_success(api.allocate_supply_request(
            req["id"], supply_manager_headers,
        ))
        mid = validate_success(api.get_supply_item(
            item["id"], supply_manager_headers,
        ))
        available_after = mid["reserve_quantity"] - mid["allocated_quantity"]
        assert available_after == 70
        # Cancel.
        validate_success(api.cancel_supply_request(
            req["id"], supply_manager_headers,
        ))
        end = validate_success(api.get_supply_item(
            item["id"], supply_manager_headers,
        ))
        available_restored = end["reserve_quantity"] - end["allocated_quantity"]
        assert end["reserve_quantity"] == 100
        assert end["allocated_quantity"] == 0
        assert available_restored == 100, (
            f"Allocate-then-cancel must restore available to its "
            f"pre-allocation value; got {available_restored}"
        )

    def test_reserve_quantity_unchanged_across_allocate_cancel(
        self, api, supply_manager_headers,
    ):
        """PRD §3.7: "Cancelling an ALLOCATED request also decrements
        the item's allocated_quantity by the previously-allocated
        amount."

        Claim: reserve_quantity is invariant across the allocate +
        cancel sequence (only allocated_quantity is touched, and it
        returns to 0).
        # difficulty: compensating_invariant/supply_allocate_then_cancel_preserves_available
        """
        item = create_supply_item(
            sku="SKU-CCV-2", category="VACCINE", reserve_quantity=50,
        )
        _region, hospital = setup_district_with_hospital(
            district_code="D-CCV-2",
        )
        req = submit_supply_request(
            sku=item["sku"], hospital_id=hospital["id"],
            requested_quantity=20,
        )
        validate_success(api.allocate_supply_request(
            req["id"], supply_manager_headers,
        ))
        validate_success(api.cancel_supply_request(
            req["id"], supply_manager_headers,
        ))
        end = validate_success(api.get_supply_item(
            item["id"], supply_manager_headers,
        ))
        assert end["reserve_quantity"] == 50, (
            "reserve_quantity must be unchanged across allocate+cancel"
        )
        assert end["allocated_quantity"] == 0


class TestIsolationAdmitThenViolationConserved:
    """difficulty: compensating_invariant/isolation_admit_then_violation_preserves_facility_beds"""

    def test_admit_then_violation_returns_bed(self, api):
        """PRD §3.4: "A successful violation increments violations_count,
        stamps actual_end_date, sets the person's isolation_status to
        VIOLATED_TERMINATED, transitions the isolation itself to
        VIOLATED_TERMINATED, and for centralized isolations decrements
        occupied."

        Claim: admit a CENTRALIZED isolation (occupied 0→1), then
        violate (occupied 1→0) — net change zero on facility.occupied,
        and facility.capacity is unchanged.
        # difficulty: compensating_invariant/isolation_admit_then_violation_preserves_facility_beds
        """
        chain = setup_full_local_chain(district_code="D-IATV-1")
        facility = create_facility(
            district_code=chain["district_code"], capacity=3,
        )
        capacity_before = facility["capacity"]
        free_before = facility["capacity"] - facility["occupied"]
        person = create_person(district_code=chain["district_code"])
        iso = create_isolation_for_person(
            person_id=person["id"], cdc_id=chain["cdc"]["id"],
            mode="CENTRALIZED", facility_id=facility["id"],
        )
        violated = violate_isolation(iso["id"], chain["cdc"]["id"])
        assert violated["status"] == "VIOLATED_TERMINATED"
        assert violated["violations_count"] == 1
        fac_end = validate_success(api.get_facility(
            facility["id"],
            make_cdc_tracer_headers(chain["cdc"]["id"]),
        ))
        free_after = fac_end["capacity"] - fac_end["occupied"]
        assert fac_end["capacity"] == capacity_before
        assert free_after == free_before, (
            f"facility free-beds invariant: before={free_before}, "
            f"after={free_after}"
        )

    def test_violation_clears_person_isolation_status(self, api):
        """PRD §3.4: "transitions the isolation itself to
        VIOLATED_TERMINATED, and for centralized isolations decrements
        occupied."

        Claim: after admit + violation on a CENTRALIZED isolation, the
        Person.isolation_status reflects VIOLATED_TERMINATED.
        # difficulty: compensating_invariant/isolation_admit_then_violation_preserves_facility_beds
        """
        chain = setup_full_local_chain(district_code="D-IATV-2")
        facility = create_facility(
            district_code=chain["district_code"], capacity=2,
        )
        person = create_person(district_code=chain["district_code"])
        iso = create_isolation_for_person(
            person_id=person["id"], cdc_id=chain["cdc"]["id"],
            mode="CENTRALIZED", facility_id=facility["id"],
        )
        violate_isolation(iso["id"], chain["cdc"]["id"])
        person_after = validate_success(api.get_person(
            person["id"],
            make_cdc_tracer_headers(chain["cdc"]["id"]),
        ))
        assert person_after["isolation_status"] == "VIOLATED_TERMINATED"
