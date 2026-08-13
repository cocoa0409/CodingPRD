"""Ongoing monitoring: metrics, readings, breach events, and the consecutive-breach
auto-finding cascade (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    add_metric,
    assert_instant_equal,
    assert_reading,
    create_approved_model,
    create_approved_model_with_metric,
    create_model,
    create_suspended_tier1_model,
    get_model,
    record_reading,
    setup_metric_with_breaches,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

OWNER_A = TEST_USERS["model_owner_a_headers"]
OFFICER = TEST_USERS["risk_officer_headers"]


class TestMetricCreation:
    def test_metric_creation_initial_state(self, api):
        """PRD §3.7: "A new metric starts `ACTIVE` with `consecutive_breach_count`
        zero."
        PRD §3.1: "Every child record later created under the model — documentation,
        change requests, engagements, findings, metrics, vendor assessments — carries a
        system-assigned `model_id` pointing back to it."

        Design: Corner/entities/metric_creation_initial_state
        """
        model, _metric, ctx = create_approved_model_with_metric(name="Met M", declared_complexity="LOW",
                                                                usage_scope="SINGLE_DESK",
                                                                exposure_amount=100,
                                                                assessed_complexity="LOW")
        metric = add_metric(model["id"], "auc", "BELOW_IS_BREACH", 0.7, owner_headers=ctx["owner_headers"])
        assert metric["status"] == "ACTIVE"
        assert metric["consecutive_breach_count"] == 0
        assert metric["model_id"] == model["id"]

    def test_metric_creation_on_registered_model_returns_not_approved_for_use(self, api):
        """PRD §3.7: "Registration on a retired model fails with
        `ERR_MODEL_ALREADY_RETIRED`; on a live model that is not `APPROVED_FOR_USE` it
        fails with `ERR_MODEL_NOT_APPROVED_FOR_USE`."

        Design: Corner/state_machines/metric_creation_on_registered_model_returns_not_approved_for_use
        """
        model = create_model(name="NoMet M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        err = validate_error(
            api.create_metric(model["id"],
                              {"metric_name": "psi", "direction": "ABOVE_IS_BREACH",
                               "threshold_value": 0.25},
                              OWNER_A),
            ApiErrorId.ERR_MODEL_NOT_APPROVED_FOR_USE,
        )
        assert err["error_id"] == "ERR_MODEL_NOT_APPROVED_FOR_USE"


class TestReadings:
    def test_metric_reading_immutable_no_version_field(self, api):
        """PRD §2.4: "The single exception is the metric reading: readings are an
        append-only event log and carry only `id` and `created_at`; both `updated_at`
        and `version` are absent, because a recorded reading is never modified."

        Design: Corner/entities/metric_reading_immutable_no_version_field
        """
        model, metric, ctx = create_approved_model_with_metric(name="Imm M", declared_complexity="LOW",
                                                               usage_scope="SINGLE_DESK",
                                                               exposure_amount=100,
                                                               assessed_complexity="LOW")
        reading = validate_success(
            api.record_reading(metric["id"], {"value": 0.10, "observed_at": "2026-08-02T00:00:00Z"},
                               ctx["owner_headers"]),
            expected_status=201,
        )
        assert_reading(reading)
        assert reading["is_breach"] is False

    def test_reading_out_of_order_rejected(self, api):
        """PRD §3.7: "Two admission gates apply in pipeline order: the metric must be
        `ACTIVE` — readings on a `PAUSED` or `DECOMMISSIONED` metric fail with
        `ERR_METRIC_NOT_ACTIVE` — and readings must arrive in chronological order,
        meaning `observed_at` must not precede the `observed_at` of the metric's most
        recent reading (equal timestamps are acceptable), failing with
        `ERR_READING_OUT_OF_ORDER` otherwise."

        Design: Corner/validations/reading_out_of_order_rejected
        """
        model, metric, ctx = create_approved_model_with_metric(name="Order M", declared_complexity="LOW",
                                                               usage_scope="SINGLE_DESK",
                                                               exposure_amount=100,
                                                               assessed_complexity="LOW")
        record_reading(metric["id"], 0.10, "2026-08-05T00:00:00Z", owner_headers=ctx["owner_headers"])
        err = validate_error(
            api.record_reading(metric["id"], {"value": 0.11, "observed_at": "2026-08-04T23:59:59Z"},
                               ctx["owner_headers"]),
            ApiErrorId.ERR_READING_OUT_OF_ORDER,
        )
        assert err["error_id"] == "ERR_READING_OUT_OF_ORDER"
        ok = validate_success(
            api.record_reading(metric["id"], {"value": 0.12, "observed_at": "2026-08-05T00:00:00Z"},
                               ctx["owner_headers"]),
            expected_status=201,
        )
        assert ok["id"], "an equal-timestamp reading is allowed"
        readings, _ = validate_paginated(api.list_readings(metric["id"], OWNER_A))
        assert len(readings) == 2

    def test_reading_on_paused_metric_returns_metric_not_active(self, api):
        """PRD §3.7: "Two admission gates apply in pipeline order: the metric must be
        `ACTIVE` — readings on a `PAUSED` or `DECOMMISSIONED` metric fail with
        `ERR_METRIC_NOT_ACTIVE`".
        PRD §3.8: "Suspension pauses the model's monitoring: every `ACTIVE` metric
        transitions to `PAUSED`, and a paused metric admits no new readings."

        Design: Corner/state_machines/reading_on_paused_metric_returns_metric_not_active
        """
        scenario = create_suspended_tier1_model(severity="CRITICAL",
                                                finding_time="2026-08-02T00:00:00Z",
                                                sweep_to="2026-08-24T00:00:00Z",
                                                metric_names=("psi",))
        metric = scenario["metrics"]["psi"]
        assert get_model(scenario["model"]["id"])["status"] == "SUSPENDED"
        err = validate_error(
            api.record_reading(metric["id"], {"value": 0.30, "observed_at": "2026-08-24T00:00:00Z"},
                               scenario["owner_headers"]),
            ApiErrorId.ERR_METRIC_NOT_ACTIVE,
        )
        assert err["error_id"] == "ERR_METRIC_NOT_ACTIVE"
        metric_after = validate_success(api.get_metric(metric["id"], OWNER_A))
        assert metric_after["consecutive_breach_count"] == 0, "no reading was recorded"
        readings, _ = validate_paginated(api.list_readings(metric["id"], OWNER_A))
        assert readings == []


class TestThresholdBoundary:
    def test_reading_equal_to_threshold_is_not_breach(self, api):
        """PRD §3.7: "Breach evaluation happens at recording time with strict
        comparisons. For a metric whose `direction` is `ABOVE_IS_BREACH`, a reading
        breaches when its `value` is strictly greater than `threshold_value`; for
        `BELOW_IS_BREACH`, when `value` is strictly less than `threshold_value`.
        Equality is never a breach under either direction."

        Design: Difficulty/boundary_precision_check/reading_exactly_at_threshold_is_not_a_breach
        """
        model, metric, ctx = create_approved_model_with_metric(name="Boundary M", declared_complexity="LOW",
                                                               usage_scope="SINGLE_DESK",
                                                               exposure_amount=100,
                                                               assessed_complexity="LOW")
        reading = validate_success(
            api.record_reading(metric["id"], {"value": 0.25, "observed_at": "2026-08-02T00:00:00Z"},
                               ctx["owner_headers"]),
            expected_status=201,
        )
        assert reading["is_breach"] is False, "equality is NOT a breach under strict >"
        events, _ = validate_paginated(api.list_breach_events(metric["id"], OWNER_A))
        assert events == [], "no breach event for an exactly-at-threshold reading"
        metric_after = validate_success(api.get_metric(metric["id"], OWNER_A))
        assert metric_after["consecutive_breach_count"] == 0

    def test_reading_just_above_threshold_is_breach(self, api):
        """PRD §3.7: "For a metric whose `direction` is `ABOVE_IS_BREACH`, a reading
        breaches when its `value` is strictly greater than `threshold_value`".
        PRD §3.7: "A breaching reading increments the metric's
        `consecutive_breach_count` by one and opens a `BreachEvent` in `OPEN` status".

        0.250001 > 0.25 breaches right after an exactly-at-threshold non-breach.

        Design: Difficulty/boundary_precision_check/reading_exactly_at_threshold_is_not_a_breach
        """
        model, metric, ctx = create_approved_model_with_metric(name="Boundary M", declared_complexity="LOW",
                                                               usage_scope="SINGLE_DESK",
                                                               exposure_amount=100,
                                                               assessed_complexity="LOW")
        record_reading(metric["id"], 0.25, "2026-08-02T00:00:00Z", owner_headers=ctx["owner_headers"])
        reading = validate_success(
            api.record_reading(metric["id"], {"value": 0.250001, "observed_at": "2026-08-03T00:00:00Z"},
                               ctx["owner_headers"]),
            expected_status=201,
        )
        assert reading["is_breach"] is True, "0.250001 > 0.25"
        metric_after = validate_success(api.get_metric(metric["id"], OWNER_A))
        assert metric_after["consecutive_breach_count"] == 1


class TestBreachEvents:
    def test_breach_event_created_with_snapshot_fields(self, api):
        """PRD §3.7: "A breaching reading increments the metric's
        `consecutive_breach_count` by one and opens a `BreachEvent` in `OPEN` status,
        which snapshots the metric's `metric_name`, the breaching `breach_value`, and
        the `reading_id` of the causing reading for traceability."

        Design: Corner/entities/breach_event_created_with_snapshot_fields
        """
        model, metric, ctx = create_approved_model_with_metric(name="BE M", declared_complexity="LOW",
                                                               usage_scope="SINGLE_DESK",
                                                               exposure_amount=100,
                                                               assessed_complexity="LOW")
        reading = record_reading(metric["id"], 0.30, "2026-08-02T00:00:00Z",
                                 owner_headers=ctx["owner_headers"])
        events, _ = validate_paginated(api.list_breach_events(metric["id"], OWNER_A))
        assert len(events) == 1
        row = events[0]
        assert row["status"] == "OPEN"
        assert row["metric_name"] == "psi", "metric_name is a snapshot of the metric's name"
        assert float(row["breach_value"]) == 0.30
        assert row["reading_id"] == reading["id"]
        assert row["metric_id"] == metric["id"]

    def test_breach_events_filtered_by_status(self, api):
        """PRD §3.7: "The metric list and the breach-event list can each be filtered by
        `status`, and the readings list of a metric is returned in chronological
        observation order."

        Design: Corner/endpoints/breach_events_filtered_by_status
        """
        model, metric, ctx = create_approved_model_with_metric(name="BEF M", declared_complexity="LOW",
                                                               usage_scope="SINGLE_DESK",
                                                               exposure_amount=100,
                                                               assessed_complexity="LOW")
        record_reading(metric["id"], 0.30, "2026-08-02T00:00:00Z", owner_headers=ctx["owner_headers"])
        record_reading(metric["id"], 0.31, "2026-08-03T00:00:00Z", owner_headers=ctx["owner_headers"])
        events, _ = validate_paginated(api.list_breach_events(metric["id"], OWNER_A))
        assert len(events) == 2
        resolved = validate_success(api.resolve_breach_event(events[0]["id"], ctx["owner_headers"]))
        assert resolved["status"] == "RESOLVED"

        open_rows, _ = validate_paginated(api.list_breach_events(metric["id"], OWNER_A,
                                                                 params={"status": "OPEN"}))
        assert len(open_rows) == 1
        resolved_rows, _ = validate_paginated(api.list_breach_events(metric["id"], OWNER_A,
                                                                     params={"status": "RESOLVED"}))
        assert len(resolved_rows) == 1 and resolved_rows[0]["id"] == events[0]["id"]

    def test_breach_event_resolve_twice_returns_already_resolved(self, api):
        """PRD §3.7: "Breach events remain `OPEN` until the model's owner resolves
        them; resolving one that is already `RESOLVED` fails with
        `ERR_BREACH_EVENT_ALREADY_RESOLVED`, and resolution by anyone but the owner
        fails with `ERR_NOT_MODEL_OWNER`."

        Design: Corner/state_machines/breach_event_resolve_twice_returns_already_resolved
        """
        model, metric, ctx = create_approved_model_with_metric(name="BRes M", declared_complexity="LOW",
                                                               usage_scope="SINGLE_DESK",
                                                               exposure_amount=100,
                                                               assessed_complexity="LOW")
        record_reading(metric["id"], 0.30, "2026-08-02T00:00:00Z", owner_headers=ctx["owner_headers"])
        events, _ = validate_paginated(api.list_breach_events(metric["id"], OWNER_A))
        be_id = events[0]["id"]
        validate_success(api.resolve_breach_event(be_id, ctx["owner_headers"]))
        err = validate_error(api.resolve_breach_event(be_id, ctx["owner_headers"]),
                             ApiErrorId.ERR_BREACH_EVENT_ALREADY_RESOLVED)
        assert err["error_id"] == "ERR_BREACH_EVENT_ALREADY_RESOLVED"


class TestConsecutiveBreachCascade:
    def test_consecutive_breach_counter_resets_on_non_breach(self, api):
        """PRD §3.7: "A non-breaching reading resets `consecutive_breach_count` to
        zero."
        PRD §3.7: "The model's `monitoring_posture` is derived from breach events
        alone: it is `BREACHED` while at least one `OPEN` breach event exists on any
        metric of the model, and returns to `NORMAL` only when none remain".

        Two breaches then a non-breach: counter resets 2 -> 0, no auto-finding ever
        fires, and the two OPEN breach events keep the posture BREACHED.

        Design: Corner/calculations/consecutive_breach_counter_resets_on_non_breach
        """
        model, metric, ctx = create_approved_model_with_metric(name="Reset M", declared_complexity="LOW",
                                                               usage_scope="SINGLE_DESK",
                                                               exposure_amount=100,
                                                               assessed_complexity="LOW")
        record_reading(metric["id"], 0.30, "2026-08-02T00:00:00Z", owner_headers=ctx["owner_headers"])
        record_reading(metric["id"], 0.31, "2026-08-03T00:00:00Z", owner_headers=ctx["owner_headers"])
        reading = validate_success(
            api.record_reading(metric["id"], {"value": 0.10, "observed_at": "2026-08-04T00:00:00Z"},
                               ctx["owner_headers"]),
            expected_status=201,
        )
        assert reading["is_breach"] is False, "0.10 < 0.25 with ABOVE_IS_BREACH"
        metric_after = validate_success(api.get_metric(metric["id"], OWNER_A))
        assert metric_after["consecutive_breach_count"] == 0, "reset from 2"
        findings, _ = validate_paginated(api.list_findings(model["id"], OFFICER))
        assert findings == [], "no auto-finding ever fired"
        assert get_model(model["id"])["monitoring_posture"] == "BREACHED"

    def test_fourth_consecutive_breach_no_second_auto_finding(self, api):
        """PRD §3.7: "A fourth or further consecutive breach opens another
        `BreachEvent` but does not auto-raise another finding — the auto-raise fires
        only on the transition to exactly three."

        Design: Corner/calculations/fourth_consecutive_breach_no_second_auto_finding
        """
        model, metric, ctx = setup_metric_with_breaches(3, name="Fourth M", declared_complexity="LOW",
                                                        usage_scope="SINGLE_DESK", exposure_amount=100,
                                                        assessed_complexity="LOW")
        reading = validate_success(
            api.record_reading(metric["id"], {"value": 0.33, "observed_at": "2026-08-05T00:00:00Z"},
                               ctx["owner_headers"]),
            expected_status=201,
        )
        assert reading["is_breach"] is True
        metric_after = validate_success(api.get_metric(metric["id"], OWNER_A))
        assert metric_after["consecutive_breach_count"] == 4
        events, _ = validate_paginated(api.list_breach_events(metric["id"], OWNER_A))
        assert len(events) == 4
        assert all(e["status"] == "OPEN" for e in events)
        findings, _ = validate_paginated(api.list_findings(model["id"], OFFICER))
        assert len(findings) == 1, "the auto-raise fired once, at count 3"

    def test_third_breach_autoraises_monitoring_finding(self, api):
        """PRD §3.7: "The third consecutive breach is the escalation point: when
        `consecutive_breach_count` reaches exactly three, the system auto-raises a
        finding on the metric's model — severity `HIGH`, `source` `MONITORING`,
        `raised_by_user_id` the literal string 'system', and a `title` of the form
        "AUTO: 3 consecutive breaches on " followed by the metric's `metric_name`."

        Design: Difficulty/transitive_cascade/third_consecutive_breach_autoraises_finding_recomputes_risk
        """
        model, metric, ctx = setup_metric_with_breaches(2, name="Breach M", declared_complexity="HIGH",
                                                        usage_scope="SINGLE_DESK", exposure_amount=100,
                                                        assessed_complexity="HIGH")
        validate_success(
            api.record_reading(metric["id"], {"value": 0.32, "observed_at": "2026-08-04T00:00:00Z"},
                               ctx["owner_headers"]),
            expected_status=201,
        )
        metric_after = validate_success(api.get_metric(metric["id"], OWNER_A))
        assert metric_after["consecutive_breach_count"] == 3
        assert get_model(model["id"])["monitoring_posture"] == "BREACHED"
        findings, _ = validate_paginated(api.list_findings(model["id"], OFFICER))
        assert len(findings) == 1
        auto = findings[0]
        assert auto["source"] == "MONITORING"
        assert auto["severity"] == "HIGH"
        assert auto["status"] == "OPEN"
        assert auto["raised_by_user_id"] == "system"
        assert auto["title"] == "AUTO: 3 consecutive breaches on psi"

    def test_auto_finding_deadline_and_risk_recompute(self, api):
        """PRD §3.7: "That finding flows through the standard machinery of §3.6,
        including the five-day monitoring urgency deduction in its deadline and the
        model risk recomputation."
        PRD §3.6: "Raising a finding increments the model's `open_findings_count` —
        defined as the number of findings on the model whose status is `OPEN`,
        `OVERDUE`, or `ESCALATED` — by one and recomputes the model's `risk_score` and
        `risk_tier`, since the findings penalty of §3.1 has grown."

        TIER_1 model at 85 after validation (assessed HIGH); the auto-finding is
        created at the 2026-08-01 logical default, so its deadline is
        round(30*1.0) - 5 = 25 days -> 2026-08-26, and risk recomputes to 85 + 5 = 90.

        Design: Difficulty/transitive_cascade/third_consecutive_breach_autoraises_finding_recomputes_risk
        """
        model, metric, ctx = setup_metric_with_breaches(3, name="Breach M", declared_complexity="HIGH",
                                                        usage_scope="SINGLE_DESK", exposure_amount=100,
                                                        assessed_complexity="HIGH")
        findings, _ = validate_paginated(api.list_findings(model["id"], OFFICER))
        assert len(findings) == 1
        assert_instant_equal(findings[0]["remediation_due_at"], "2026-08-26T00:00:00Z",
                             "auto-finding deadline")
        data = get_model(model["id"])
        assert data["open_findings_count"] == 1
        assert data["risk_score"] == 90, f"expected 85 + 5 = 90, got {data['risk_score']}"


class TestMonitoringPosture:
    def test_derived_monitoring_posture_reconciliation(self, api):
        """PRD §3.7: "The model's `monitoring_posture` is derived from breach events
        alone: it is `BREACHED` while at least one `OPEN` breach event exists on any
        metric of the model, and returns to `NORMAL` only when none remain — which is
        why every breach and every resolution recomputes it."

        Design: Corner/cross_cutting_complexity_layers/derived_monitoring_posture_reconciliation
        """
        model, metric, ctx = create_approved_model_with_metric(name="Posture M", declared_complexity="LOW",
                                                               usage_scope="SINGLE_DESK",
                                                               exposure_amount=100,
                                                               assessed_complexity="LOW")
        assert model["monitoring_posture"] == "NORMAL"
        record_reading(metric["id"], 0.30, "2026-08-02T00:00:00Z", owner_headers=ctx["owner_headers"])
        assert get_model(model["id"])["monitoring_posture"] == "BREACHED"
        events, _ = validate_paginated(api.list_breach_events(metric["id"], OWNER_A))
        validate_success(api.resolve_breach_event(events[0]["id"], ctx["owner_headers"]))
        assert get_model(model["id"])["monitoring_posture"] == "NORMAL"
