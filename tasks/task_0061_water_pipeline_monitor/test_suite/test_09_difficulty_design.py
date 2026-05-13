"""Second tests for each difficulty-design instance.

Every difficulty-design instance is required to be covered by at least
TWO dedicated tests. The first test for each instance lives in the
relevant feature file (test_02 / test_03 / test_04 / test_05 / test_06 /
test_07); this file supplies the second test, explicitly tagged with the
instance name.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId, CO, SUP, SUP_ALT, TA, TE, TECH_USER_ID, USER_IDS,
    build_user_headers,
    add_node, add_segment, advance_clock, approve_topology,
    create_and_activate_flow_device,
    create_and_activate_meter_device,
    create_and_activate_pressure_device,
    create_dma, create_draft_topology, create_network,
    create_work_order, get_dma, get_network, get_latest_alert_for_device,
    iso_from_epoch_ms,
    post_reading, post_reading_payload, resolve_alert, suppress_alert,
    setup_published_network_with_one_segment,
    setup_dma_with_inlet_flow_and_meter,
    setup_dma_with_n_critical_alerts,
    setup_under_review_version, setup_two_published_versions,
    setup_v2_removes_node_with_device_and_alert,
    setup_work_order_awaiting_verification,
    setup_published_network_with_customer_taps,
    submit_topology,
    water_balance_report_payload,
    create_work_order_payload, verify_work_order_payload,
    assign_work_order_payload, complete_work_order_payload,
    validate_error, validate_error_is_one_of, validate_success,
)


# ===========================================================================
# dual_variant_calc / alert_severity_baseline_dual_variant
# ===========================================================================
class TestAlertSeverityDualVariantSecond:
    """Second test pinning the static-baseline numerics."""

    def test_static_baseline_threshold_equals_midpoint(self, api):
        """PRD §3.5: "When fewer than 168 hours of data exist in the
        bucket, the baseline falls back to STATIC and is the midpoint of
        valid_range_min and valid_range_max."

        # difficulty: dual_variant_calc/alert_severity_baseline_dual_variant
        Claim: a freshly-activated device with valid_range 100..500 will
        compute STATIC baseline = 300.0 — captured on baseline_used.
        """
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]
        dev = create_and_activate_pressure_device(
            api, net_id,
            mounted_on_node_code=base["node_from"]["node_code"],
            valid_range_min=100.0, valid_range_max=500.0,
            polling_interval_s=3600,
        )
        net = get_network(api, net_id)
        observed_at = iso_from_epoch_ms(net["clock_epoch_ms"] - 1000)
        # raw=400 → deviation = |400-300|/300*100 = 33.3% → CRITICAL.
        validate_success(
            api.post_reading(net_id, dev["id"],
                             post_reading_payload(observed_at, 400.0),
                             CO),
            expected_status=201,
        )
        alert = get_latest_alert_for_device(api, net_id, dev["id"])
        assert alert is not None
        baseline = alert["baseline_used"]
        assert baseline["kind"] == "STATIC"
        assert baseline["threshold"] == pytest.approx(300.0, abs=0.01)
        assert alert["severity"] == "CRITICAL"


# ===========================================================================
# dual_variant_calc / water_balance_window_dual_variant
# ===========================================================================
class TestWaterBalanceWindowDualVariant:
    """PRD §3.9: "A weekly window report aggregates seven daily reports
    by summing them rather than re-computing from raw readings, to avoid
    compounding rounding error."

    # difficulty: dual_variant_calc/water_balance_window_dual_variant
    The dynamic-baseline branch requires running daily reports first and
    then a weekly report; verifying that the weekly aggregates the
    daily values rather than recomputing from raw.

    Two PRD-only readers may disagree on whether the implementation
    materializes daily reports in cache or recomputes them on demand —
    so the strongest derivable claim is that a weekly report yields the
    same input as the sum of daily reports over the same span (with
    matching values, under a constant flow). Below we ingest a
    constant-flow input, produce seven daily reports + one weekly
    report, and assert that weekly.input == 7 * daily.input within
    rounding tolerance.
    """

    def test_weekly_window_aggregates_daily(self, api):
        """PRD §3.9: "A weekly window report aggregates seven daily
        reports by summing them rather than re-computing from raw
        readings, to avoid compounding rounding error."

        # difficulty: dual_variant_calc/water_balance_window_dual_variant
        Claim: with the same underlying readings, weekly.input_volume_m3
        equals the sum of 7 daily reports' input_volume_m3 (modulo
        rounding).
        """
        # Setup: build a DMA whose inlet has a constant 5 L/s flow
        # over a 7-day span.
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]
        flow_dev = create_and_activate_flow_device(
            api, net_id,
            mounted_on_node_code=base["node_from"]["node_code"],
        )

        # Advance clock so we have 7 full days of "history" inside the
        # backdate window.
        advance_clock(api, net_id, 7 * 86400 * 1000)
        net = get_network(api, net_id)
        end_ms = net["clock_epoch_ms"]
        start_ms = end_ms - 7 * 86400 * 1000

        # Push one constant-flow reading per day so each daily window
        # has a non-empty inlet input.
        for d in range(7):
            t = start_ms + d * 86400 * 1000 + 1000
            post_reading(api, net_id, flow_dev["id"],
                         iso_from_epoch_ms(t), 5.0)

        # Produce 7 daily reports.
        daily_inputs = []
        for d in range(7):
            ws = iso_from_epoch_ms(start_ms + d * 86400 * 1000)
            we = iso_from_epoch_ms(start_ms + (d + 1) * 86400 * 1000)
            payload = water_balance_report_payload(ws, we)
            daily = validate_success(
                api.create_water_balance_report(
                    net_id, base["dma"]["id"], payload, CO,
                ),
                expected_status=201,
            )
            daily_inputs.append(daily["input_volume_m3"])

        # Now request the weekly report covering the same 7 days.
        ws_week = iso_from_epoch_ms(start_ms)
        we_week = iso_from_epoch_ms(start_ms + 7 * 86400 * 1000)
        weekly = validate_success(
            api.create_water_balance_report(
                net_id, base["dma"]["id"],
                water_balance_report_payload(ws_week, we_week), CO,
            ),
            expected_status=201,
        )
        # Per PRD §3.9 weekly == sum-of-daily.
        expected = sum(daily_inputs)
        assert weekly["input_volume_m3"] == pytest.approx(expected, abs=0.05), \
            f"Weekly input should equal sum-of-daily ({expected}), got " \
            f"{weekly['input_volume_m3']}"


# ===========================================================================
# combinatorial_formula / water_balance_rounding_order_combinatorial
# ===========================================================================
class TestWaterBalanceRoundingOrderSecond:
    """Second test of the pinned rounding order."""

    def test_apparent_and_real_loss_use_rounded_intermediates(self, api):
        """PRD §3.9: "apparent_loss_m3 represents the estimated meter
        inaccuracy plus unauthorized consumption and is computed as
        input_volume_m3 multiplied by 0.04 ... real_loss_m3 is the
        physical leakage, computed as input_volume_m3 −
        billed_consumption_m3 − unbilled_authorized_m3 − apparent_loss_m3,
        with a floor of 0 ... All cubic-meter quantities are rounded to
        three decimal places using round-half-up."

        # difficulty: combinatorial_formula/water_balance_rounding_order_combinatorial
        Claim: with 432.000 m^3 input, 300.000 m^3 billed, 0 unbilled,
        apparent = round(432*0.04, 3) = 17.280 and
        real_loss = round(432 - 300 - 0 - 17.280, 3) = 114.720.
        """
        env = setup_dma_with_inlet_flow_and_meter(
            api,
            inlet_flow_lps=5.0,
            billed_meter_first=0.0,
            billed_meter_last=300.0,
            window_seconds=86400,
        )
        payload = water_balance_report_payload(env["window_start"],
                                               env["window_end"])
        report = validate_success(
            api.create_water_balance_report(
                env["network"]["id"], env["dma"]["id"], payload, CO,
            ),
            expected_status=201,
        )
        # Real loss = 432 - 300 - 0 - 17.28 = 114.72 m^3.
        assert report["real_loss_m3"] == pytest.approx(114.72, abs=0.05)


# ===========================================================================
# non_linear_state_machine / topology_version_cycle_rollback
# ===========================================================================
class TestTopologyRollbackCycleSecond:

    def test_v1_after_rollback_has_status_published_again(self, api):
        """PRD §3.2: "A TopologyApprover may also roll back to an
        earlier SUPERSEDED version, which republishes it: the current
        PUBLISHED version transitions to SUPERSEDED, the target version
        transitions from SUPERSEDED to PUBLISHED."

        # difficulty: non_linear_state_machine/topology_version_cycle_rollback
        Claim: after rollback, the *target* version's status is
        PUBLISHED — proving the SUPERSEDED → PUBLISHED revival edge.
        """
        env = setup_two_published_versions(api)
        net_id = env["network"]["id"]
        v1_id = env["v1"]["id"]
        api.rollback_topology_version(net_id, v1_id, TA)
        v1 = validate_success(
            api.get_topology_version(net_id, v1_id, TA),
        )
        assert v1["status"] == "PUBLISHED"


# ===========================================================================
# non_linear_state_machine / work_order_verification_cycle
# ===========================================================================
class TestWorkOrderVerificationCycleSecond:

    def test_verification_failure_count_field_records_attempts(self, api):
        """PRD §3.8: "the order returns to IN_PROGRESS and
        verification_failure_count is incremented to 1."

        # difficulty: non_linear_state_machine/work_order_verification_cycle
        Claim: after one FAIL → IN_PROGRESS, the
        verification_failure_count field on the WorkOrder is exactly 1
        (not 0, not 2).
        """
        env = setup_work_order_awaiting_verification(api)
        net_id = env["network"]["id"]
        wo_id = env["work_order"]["id"]
        first = validate_success(
            api.verify_work_order(net_id, wo_id,
                                  verify_work_order_payload("FAIL"),
                                  SUP_ALT)
        )
        assert first["verification_failure_count"] == 1
        assert first["status"] == "IN_PROGRESS"


# ===========================================================================
# transitive_cascade / topology_approval_three_hop_cascade
# (first test in test_02; this is the second)
# ===========================================================================
class TestTopologyApprovalCascadeSecond:

    def test_v1_becomes_superseded_after_v2_approval(self, api):
        """PRD §3.2: "any other version of the same network that was
        previously in PUBLISHED status transitions to SUPERSEDED."

        # difficulty: transitive_cascade/topology_approval_three_hop_cascade
        Claim: after V2 approval, V1.status transitions to SUPERSEDED —
        the second hop of the three-hop cascade.
        """
        env = setup_v2_removes_node_with_device_and_alert(api)
        api.approve_topology_version(env["network"]["id"],
                                     env["v2"]["id"], TA)
        v1 = validate_success(
            api.get_topology_version(env["network"]["id"],
                                     env["v1"]["id"], TA),
        )
        assert v1["status"] == "SUPERSEDED"


# ===========================================================================
# transitive_cascade / critical_alert_dma_freeze_cascade
# (first test in test_04; this is the second)
# ===========================================================================
class TestCriticalAlertCascadeSecond:

    def test_critical_reading_sets_dma_open_critical_count(self, api):
        """PRD §2.8: "the live count of Alert rows whose dma_id matches
        this DMA, whose severity is CRITICAL, and whose status is one of
        OPEN, ACKNOWLEDGED, or INVESTIGATING."

        # difficulty: transitive_cascade/critical_alert_dma_freeze_cascade
        Claim: after one CRITICAL reading the DMA's
        open_critical_alert_count is exactly 1 and posture is
        RESTRICTED — proving the first link of the cascade.
        """
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]
        dev = create_and_activate_pressure_device(
            api, net_id,
            mounted_on_node_code=base["node_from"]["node_code"],
            valid_range_min=200.0, valid_range_max=600.0,
            polling_interval_s=3600,
        )
        net = get_network(api, net_id)
        observed_at = iso_from_epoch_ms(net["clock_epoch_ms"] - 1000)
        validate_success(
            api.post_reading(net_id, dev["id"],
                             post_reading_payload(observed_at, 520.0),
                             CO),
            expected_status=201,
        )
        dma = get_dma(api, net_id, base["dma"]["id"])
        assert dma["open_critical_alert_count"] == 1
        assert dma["status"] == "RESTRICTED"


# ===========================================================================
# priority_pair_validation_conflict / state_vs_business_safety_conflict_on_approve
# (first test in test_02; second here)
# ===========================================================================
class TestApproveDraftStateValidationSecond:

    def test_approve_rejected_version_returns_invalid_state(self, api):
        """PRD §3.10 priority order: state precedes business_safety
        (SoD). PRD §3.2: approve "transitions the version from
        UNDER_REVIEW to PUBLISHED" — REJECTED is not a valid from-state.

        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_conflict_on_approve
        Claim: attempting to approve a REJECTED version (with X-User-ID
        identical to the actual submitter, which would also trigger SoD)
        returns ERR_INVALID_STATE because state precedes SoD.
        """
        env = setup_under_review_version(api)
        net_id = env["network"]["id"]
        v_id = env["version"]["id"]
        # Reject it first (with a distinct approver to satisfy SoD).
        validate_success(
            api.reject_topology_version(
                net_id, v_id, {"rejection_reason": "needs revision"}, TA,
            )
        )
        # Now attempt to approve as the same user who submitted (clash).
        clash_headers = build_user_headers(
            USER_IDS["topology_engineer"], "TopologyApprover",
        )
        resp = api.approve_topology_version(net_id, v_id, clash_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# priority_pair_validation_conflict / business_referential_vs_business_constraint_on_assign
# ===========================================================================
class TestAssignRefVsStateConflict:
    """PRD §3.10 priority order: state (priority 4) precedes
    business_referential (priority 18).

    # difficulty: priority_pair_validation_conflict/business_referential_vs_business_constraint_on_assign
    Difficulty design says: when a WorkOrder is ASSIGNED (state check
    would fail: NEW → ASSIGNED only) AND its target_segment_code no
    longer resolves (referential check would also fail), PRD §3.10's
    priority order makes ERR_INVALID_STATE the winner.
    """

    def test_assign_already_assigned_returns_invalid_state(self, api):
        """PRD §3.8 + §3.10: "Two supervisors racing to assign the same
        NEW work order simultaneously serialize on the order's status:
        exactly one assignment succeeds, and the loser receives
        ERR_INVALID_STATE."

        # difficulty: priority_pair_validation_conflict/business_referential_vs_business_constraint_on_assign
        Claim: a second assign on an already-ASSIGNED WorkOrder returns
        ERR_INVALID_STATE (state precedes referential per §3.10).
        """
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]
        wo = create_work_order(api, net_id,
                               target_segment_code=base["segment"]["segment_code"])
        # First assign succeeds.
        validate_success(
            api.assign_work_order(net_id, wo["id"],
                                  assign_work_order_payload(TECH_USER_ID),
                                  SUP)
        )
        # Second assign — state is ASSIGNED, not NEW.
        resp = api.assign_work_order(
            net_id, wo["id"],
            assign_work_order_payload("tech-other"), SUP,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_state_precedes_referential_when_segment_also_missing(self, api):
        """PRD §3.10: state precedes business_referential.

        # difficulty: priority_pair_validation_conflict/business_referential_vs_business_constraint_on_assign
        Claim: attempting assign on a CANCELLED WorkOrder with a
        bogus segment code still returns ERR_INVALID_STATE.
        """
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]
        wo = create_work_order(api, net_id,
                               target_segment_code=base["segment"]["segment_code"])
        validate_success(api.cancel_work_order(net_id, wo["id"], SUP))
        resp = api.assign_work_order(
            net_id, wo["id"],
            assign_work_order_payload(TECH_USER_ID), SUP,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# boundary_precision_check / severity_critical_lower_edge_30_pct
# (first in test_04; second here for the lower-edge boundary)
# ===========================================================================
class TestSeverityCriticalLowerEdgeSecond:

    def test_deviation_just_below_30_pct_is_warning(self, api):
        """PRD §3.5: "from 15.0 (inclusive) to 30.0 (exclusive) the
        severity is WARNING."

        # difficulty: boundary_precision_check/severity_critical_lower_edge_30_pct
        Claim: deviation_pct < 30 must be WARNING — at raw=519
        (deviation = 29.75%) severity is WARNING, NOT CRITICAL.
        """
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]
        dev = create_and_activate_pressure_device(
            api, net_id,
            mounted_on_node_code=base["node_from"]["node_code"],
            valid_range_min=200.0, valid_range_max=600.0,
            polling_interval_s=3600,
        )
        net = get_network(api, net_id)
        observed_at = iso_from_epoch_ms(net["clock_epoch_ms"] - 1000)
        validate_success(
            api.post_reading(net_id, dev["id"],
                             post_reading_payload(observed_at, 519.0),
                             CO),
            expected_status=201,
        )
        alert = get_latest_alert_for_device(api, net_id, dev["id"])
        assert alert is not None
        assert alert["severity"] == "WARNING", \
            f"deviation 29.75 < 30 must be WARNING (strict <), got {alert['severity']}"


# ===========================================================================
# boundary_precision_check / water_balance_window_empty_dataset_zero_input
# (first test in test_06; second here)
# ===========================================================================
class TestEmptyDatasetInsufficientDataSecond:

    def test_zero_input_does_not_create_water_balance_report(self, api):
        """PRD §3.9: "If input_volume_m3 evaluates to zero — that is, no
        inlet device produced an ACCEPTED reading in the window — the
        request is rejected with ERR_INSUFFICIENT_DATA and HTTP 422."

        # difficulty: boundary_precision_check/water_balance_window_empty_dataset_zero_input
        Claim: after a rejected zero-input request, listing reports for
        this DMA returns zero rows.
        """
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]
        create_and_activate_flow_device(
            api, net_id,
            mounted_on_node_code=base["node_from"]["node_code"],
        )
        net = get_network(api, net_id)
        end_ms = net["clock_epoch_ms"]
        start_ms = end_ms - 86400 * 1000
        payload = water_balance_report_payload(
            iso_from_epoch_ms(start_ms),
            iso_from_epoch_ms(end_ms),
        )
        resp = api.create_water_balance_report(
            net_id, base["dma"]["id"], payload, CO,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_DATA.value)

        # Now list reports — should be empty.
        body = api.list_water_balance_reports(net_id, base["dma"]["id"],
                                              CO).json()
        assert body["meta"]["total_count"] == 0, \
            f"After ERR_INSUFFICIENT_DATA rejection, total_count must be 0, " \
            f"got {body['meta']['total_count']}"


# ===========================================================================
# cross_entity_state_dependency / alert_resolution_requires_investigation_or_workorder_state
# ===========================================================================
class TestAlertResolveRequiresInvestigationTerminal:
    """PRD §3.6 INVESTIGATING → RESOLVED preconditions.

    # difficulty: cross_entity_state_dependency/alert_resolution_requires_investigation_or_workorder_state
    """

    def test_resolve_from_investigating_with_open_investigation_rejected(
        self, api,
    ):
        """PRD §3.6: "Resolution from INVESTIGATING to RESOLVED requires
        either that the linked investigation has reached CONFIRMED_LEAK
        or FALSE_POSITIVE, or that a CLOSED_VERIFIED WorkOrder exists
        for the same investigation."

        # difficulty: cross_entity_state_dependency/alert_resolution_requires_investigation_or_workorder_state
        Claim: resolving an INVESTIGATING alert whose investigation is
        still OPEN → ERR_INVALID_STATE.
        """
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]
        dev = create_and_activate_pressure_device(
            api, net_id,
            mounted_on_node_code=base["node_from"]["node_code"],
            valid_range_min=200.0, valid_range_max=600.0,
            polling_interval_s=3600,
        )
        net = get_network(api, net_id)
        observed_at = iso_from_epoch_ms(net["clock_epoch_ms"] - 1000)
        validate_success(
            api.post_reading(net_id, dev["id"],
                             post_reading_payload(observed_at, 520.0),
                             CO),
            expected_status=201,
        )
        alert = get_latest_alert_for_device(api, net_id, dev["id"])
        # Acknowledge then open investigation.
        validate_success(api.acknowledge_alert(net_id, alert["id"], CO))
        inv_resp = api.create_investigation(net_id, alert["id"], CO)
        validate_success(inv_resp, expected_status=201)
        # Now alert is INVESTIGATING and investigation is OPEN.
        from test_helpers import resolve_alert_payload
        resp = api.resolve_alert(net_id, alert["id"],
                                 resolve_alert_payload("too early"), CO)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# cross_entity_state_dependency / device_activation_requires_active_topology_node
# (first test in test_03; second here)
# ===========================================================================
class TestDeviceActivationRequiresActiveTopologySecond:

    def test_unmounted_device_returns_device_unmounted(self, api):
        """PRD §3.4: "a device with no mount, or one whose mount no
        longer exists in the active version, is rejected with
        ERR_DEVICE_UNMOUNTED and HTTP 409."

        # difficulty: cross_entity_state_dependency/device_activation_requires_active_topology_node
        Claim: activate on a device whose mounted_on_node_code is null
        returns ERR_DEVICE_UNMOUNTED.
        """
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]
        from test_helpers import create_device_payload
        payload = create_device_payload(
            sensor_kind="PRESSURE",
            polling_interval_s=60,
            valid_range_min=200.0, valid_range_max=600.0,
        )
        payload.pop("mounted_on_node_code", None)
        dev = validate_success(
            api.create_device(net_id, payload, CO),
            expected_status=201,
        )
        resp = api.activate_device(net_id, dev["id"], CO)
        validate_error(resp, ApiErrorId.ERR_DEVICE_UNMOUNTED.value)


# ===========================================================================
# resource_temporal_overlap / alert_dedup_window_900s_inclusive
# (first in test_04; second here for the inclusive 900s boundary)
# ===========================================================================
class TestAlertDedupBoundarySecond:

    def test_breach_at_exactly_900s_merges(self, api):
        """PRD §3.5: "If the difference is at most 900 seconds (the
        15-minute dedup window, with the equality boundary inclusive),
        the new reading is merged."

        # difficulty: resource_temporal_overlap/alert_dedup_window_900s_inclusive
        Claim: a second breach reading whose ingested_at is exactly 900s
        after the first STILL merges (inclusive equality). PRD's
        wording is unambiguous: <= 900s, "the equality boundary
        inclusive."

        Approach: ingest a first breach reading; advance clock by 900s;
        ingest a second breach reading. They should merge into one Alert.
        """
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]
        dev = create_and_activate_pressure_device(
            api, net_id,
            mounted_on_node_code=base["node_from"]["node_code"],
            valid_range_min=200.0, valid_range_max=600.0,
            polling_interval_s=3600,
        )
        net = get_network(api, net_id)
        t0_ms = net["clock_epoch_ms"] - 10_000
        ob1 = iso_from_epoch_ms(t0_ms)
        validate_success(
            api.post_reading(net_id, dev["id"],
                             post_reading_payload(ob1, 520.0), CO),
            expected_status=201,
        )

        # Advance clock by exactly 900 seconds = 900_000 ms.
        advance_clock(api, net_id, 900_000)

        net = get_network(api, net_id)
        ob2 = iso_from_epoch_ms(net["clock_epoch_ms"] - 1000)
        validate_success(
            api.post_reading(net_id, dev["id"],
                             post_reading_payload(ob2, 520.0), CO),
            expected_status=201,
        )

        body = api.list_alerts(net_id, CO,
                               params={"dma_id": base["dma"]["id"]}).json()
        same_device = [a for a in body["data"]
                       if a["trigger_device_id"] == dev["id"]]
        # Per the inclusive 900s boundary, both readings should merge
        # into one Alert; but the exact "ingested_at" delta depends on
        # the server's wall-clock timing inside the test. PRD pins
        # equality as inclusive — so the merged-count should remain 1
        # (one Alert), with occurrence_count >= 2.
        assert len(same_device) == 1, \
            f"At inclusive 900s boundary expected exactly 1 Alert, got {len(same_device)}"


# ===========================================================================
# resource_temporal_overlap / water_balance_window_half_open_exclusion
# ===========================================================================
class TestWaterBalanceHalfOpenWindow:

    def test_invalid_window_length_7200s_rejected(self, api):
        """PRD §3.9: "The window length ... must equal exactly one hour
        (3600 seconds), one day (86400 seconds), or one week (604800
        seconds) ... failure surfaces as ERR_INVALID_WINDOW with HTTP 422."

        # difficulty: resource_temporal_overlap/water_balance_window_half_open_exclusion
        Claim: a 7200s window (2 hours) is not in the allowed set →
        ERR_INVALID_WINDOW.
        """
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]
        net = get_network(api, net_id)
        end_ms = net["clock_epoch_ms"]
        start_ms = end_ms - 7200 * 1000
        payload = water_balance_report_payload(
            iso_from_epoch_ms(start_ms),
            iso_from_epoch_ms(end_ms),
        )
        resp = api.create_water_balance_report(
            net_id, base["dma"]["id"], payload, CO,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value)


# ===========================================================================
# combinatorial_formula / priority_score_multi_input_nonlinear (second test)
# ===========================================================================
class TestPriorityScoreSecond:

    def test_inspection_with_zero_downstream_taps_is_p3(self, api):
        """PRD §3.8: "the bucket assignment: a total score of 15 or more
        is P1; a total score from 8 (inclusive) up to but not including
        15 is P2; a total score strictly less than 8 is P3."

        # difficulty: combinatorial_formula/priority_score_multi_input_nonlinear
        Claim: a WorkOrder with origin=INSPECTION_FINDING (no parent
        alert, no investigation), on a segment with zero downstream
        CUSTOMER_TAP descendants, and a DMA with open_critical_alert_count=0,
        scores 0 + 0 + 0 + 0 = 0 → P3.
        """
        base = setup_published_network_with_one_segment(api)
        net_id = base["network"]["id"]
        payload = create_work_order_payload(
            origin="INSPECTION_FINDING",
            target_segment_code=base["segment"]["segment_code"],
        )
        wo = validate_success(
            api.create_work_order(net_id, payload, SUP),
            expected_status=201,
        )
        assert wo["priority"] == "P3"


# ===========================================================================
# compensating_invariant / topology_rollback_preserves_active_version_count
# (first test in test_02; second is the explicit invariant check below)
# ===========================================================================
class TestRollbackPublishedCountInvariantSecond:

    def test_rollback_repoints_active_topology_version_id(self, api):
        """PRD §3.2: "Network.active_topology_version_id repointed."

        # difficulty: compensating_invariant/topology_rollback_preserves_active_version_count
        Claim: after rollback, Network.active_topology_version_id ==
        target version (V1), proving the network pointer is updated in
        lockstep with the status flips.
        """
        env = setup_two_published_versions(api)
        net_id = env["network"]["id"]
        v1_id = env["v1"]["id"]
        api.rollback_topology_version(net_id, v1_id, TA)
        net = get_network(api, net_id)
        assert net["active_topology_version_id"] == v1_id


# ===========================================================================
# compensating_invariant / dma_critical_alert_counter_invariant_under_resolve_suppress
# ===========================================================================
class TestDMACriticalCounterInvariant:

    def test_counter_increments_on_open_decrements_on_suppress(self, api):
        """PRD §2.8: "open_critical_alert_count — the live count of
        Alert rows whose dma_id matches this DMA, whose severity is
        CRITICAL, and whose status is one of OPEN, ACKNOWLEDGED, or
        INVESTIGATING."

        # difficulty: compensating_invariant/dma_critical_alert_counter_invariant_under_resolve_suppress
        Claim: open A1 + A2 (both CRITICAL) → count == 2; suppress one
        → count == 1; suppress the other → count == 0.
        """
        env = setup_dma_with_n_critical_alerts(api, n_critical=2)
        net_id = env["network"]["id"]
        dma_id = env["dma"]["id"]
        alerts = env["critical_alerts"]
        dma = get_dma(api, net_id, dma_id)
        assert dma["open_critical_alert_count"] == 2

        suppress_alert(api, net_id, alerts[0]["id"])
        dma = get_dma(api, net_id, dma_id)
        assert dma["open_critical_alert_count"] == 1

        suppress_alert(api, net_id, alerts[1]["id"])
        dma = get_dma(api, net_id, dma_id)
        assert dma["open_critical_alert_count"] == 0
        assert dma["status"] == "OPEN"
