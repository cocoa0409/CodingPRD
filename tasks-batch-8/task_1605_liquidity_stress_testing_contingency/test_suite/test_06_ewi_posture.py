"""EWI readings, band computation, cadence, and posture evaluation.

Difficulty instances: red_reading_cascades_to_posture_escalation_and_breach_escalation,
posture_multi_input_branch_with_hysteresis,
posture_amber_count_exactly_three_crosses_heightened,
metric_reading_minimum_cadence_buffer.
Corner instances: threshold_config_inverted_rejected,
posture_snapshot_history_lists_evaluations,
reading_on_missing_metric_returns_not_found.
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_posture_snapshot,
    create_ewi_metric_payload,
    make_analyst_headers,
    make_board_limit,
    make_committee_headers,
    make_metric,
    make_officer_headers,
    post_reading,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = make_analyst_headers("ta_1")
OFFICER = make_officer_headers("ro_1")
COMMITTEE = make_committee_headers("lc_1")


def _metric(api, code, cadence=0):
    return make_metric(code=code, name=code.lower(), min_reading_interval_hours=cadence)


class TestRedReadingCascade:
    def test_red_reading_escalates_posture_and_breach(self, api, analyst_headers, officer_headers):
        """PRD §3.6: "Whenever a posted reading makes a metric's `current_band`
        become `RED`, the system immediately evaluates posture and appends a
        snapshot with trigger `READING_AUTO`."
        PRD §3.6: "Entering `SEVERE` or `CRISIS` from a strictly lower level
        escalates every `OPEN` breach to `ESCALATED` automatically, leaving its
        `acknowledged_by_user_id` null."
        PRD §3.6: "for an `ABOVE_BREACHES` metric, a value strictly above
        `red_threshold` is `RED`".

        Design: Difficulty/transitive_cascade/red_reading_cascades_to_posture_escalation_and_breach_escalation
        """
        metric = _metric(api, "M")
        limit = make_board_limit(subject="EWI_METRIC", direction="ABOVE_BREACHES",
                                 limit_value=4000, severity="BOARD",
                                 ewi_metric_id=metric["id"])
        resp = api.post_metric_reading(
            metric["id"], {"observed_at": "2026-08-01T00:00:00Z", "value": 6000},
            analyst_headers,
        )
        reading = validate_success(resp, expected_status=201)
        assert reading["band"] == "RED", f"6000 > red 5000 must be RED, got {reading['band']}"

        dashboard = validate_success(api.get_ewi_dashboard(officer_headers))
        assert dashboard["posture_level"] == "SEVERE", (
            f"one RED metric must escalate posture to SEVERE, got {dashboard['posture_level']}"
        )
        assert dashboard["red_count"] == 1, f"red_count must be 1, got {dashboard['red_count']}"

        breaches, _meta = validate_paginated(api.list_limit_breaches(limit["id"], officer_headers))
        assert len(breaches) == 1
        breach = breaches[0]
        assert breach["status"] == "ESCALATED", (
            f"the fresh OPEN breach must be auto-escalated by the SEVERE entry, got {breach['status']}"
        )
        assert breach["detected_value"] == 6000
        assert breach.get("acknowledged_by_user_id") is None, (
            "auto-escalation leaves acknowledged_by_user_id null"
        )

    def test_red_reading_appends_reading_auto_snapshot(self, api, analyst_headers, officer_headers):
        """PRD §3.6: "Whenever a posted reading makes a metric's `current_band`
        become `RED`, the system immediately evaluates posture and appends a
        snapshot with trigger `READING_AUTO`."
        PRD §3.6: "Automatic evaluations only escalate: the new level is the
        higher of the current posture and the raw level, so the automatic path
        never de-escalates."

        Design: Difficulty/transitive_cascade/red_reading_cascades_to_posture_escalation_and_breach_escalation
        """
        metric = _metric(api, "M")
        post_reading(metric["id"], 6000)  # RED -> READING_AUTO snapshot
        snapshots, _meta = validate_paginated(api.list_posture_snapshots(officer_headers))
        assert len(snapshots) == 1, f"one auto snapshot must be appended, got {len(snapshots)}"
        snap = snapshots[0]
        assert_posture_snapshot(snap)
        assert snap["level"] == "SEVERE"
        assert snap["prior_level"] == "NORMAL"
        assert snap["trigger"] == "READING_AUTO"
        assert snap["red_count"] == 1


class TestPostureHysteresis:
    def test_red_branch_dominates_ambers(self, api, officer_headers):
        """PRD §3.6: "The raw level is `CRISIS` when at least two metrics are
        red; otherwise `SEVERE` when at least one is red; otherwise
        `HEIGHTENED` when at least three metrics are amber or at least two
        breaches are open; otherwise `NORMAL`."

        Design: Difficulty/combinatorial_formula/posture_multi_input_branch_with_hysteresis
        """
        m1 = _metric(api, "M1")
        m2 = _metric(api, "M2")
        m3 = _metric(api, "M3")
        post_reading(m1["id"], 6000)   # RED -> auto-escalates posture to SEVERE
        post_reading(m2["id"], 1500)   # AMBER
        post_reading(m3["id"], 1500)   # AMBER

        resp = api.run_posture_evaluation(officer_headers)
        snap = validate_success(resp, expected_status=201)
        assert_posture_snapshot(snap)
        # raw: red_count 1 -> SEVERE (red branch dominates amber_count 2 < 3).
        assert snap["level"] == "SEVERE", f"one red must yield SEVERE, got {snap['level']}"
        assert snap["red_count"] == 1
        assert snap["amber_count"] == 2
        # The READING_AUTO snapshot already escalated posture to SEVERE.
        assert snap["prior_level"] == "SEVERE", (
            f"the auto snapshot already escalated posture, got prior {snap['prior_level']}"
        )

    def test_deescalation_capped_at_one_ordinal_step(self, api, officer_headers, committee_headers):
        """PRD §3.6: "De-escalation below the current level is committee-only,
        so any other role attempting it is rejected with `ERR_FORBIDDEN`; it
        additionally requires `red_count` and `open_breach_count` both at zero
        (`ERR_DEESCALATION_BLOCKED` otherwise); and it moves exactly one
        ordinal step downward per evaluation, a hysteresis rule that prevents
        any single evaluation from dropping two levels at once."

        Design: Difficulty/combinatorial_formula/posture_multi_input_branch_with_hysteresis
        """
        m1 = _metric(api, "M1")
        post_reading(m1["id"], 6000)  # posture SEVERE via READING_AUTO
        # Correct the metric: band back to GREEN, so raw_level is NORMAL.
        post_reading(m1["id"], 500, observed_at="2026-08-02T00:00:00Z")

        resp = api.run_posture_evaluation(committee_headers)
        snap = validate_success(resp, expected_status=201)
        # Hysteresis: one step down from SEVERE lands on HEIGHTENED, not NORMAL.
        assert snap["level"] == "HEIGHTENED", (
            f"de-escalation is capped at one ordinal step, got {snap['level']}"
        )
        assert snap["prior_level"] == "SEVERE"


class TestAmberCountBoundary:
    def test_two_ambers_stay_normal(self, api, officer_headers):
        """PRD §3.6: "The raw level is `CRISIS` when at least two metrics are
        red; otherwise `SEVERE` when at least one is red; otherwise
        `HEIGHTENED` when at least three metrics are amber or at least two
        breaches are open; otherwise `NORMAL`."

        Design: Difficulty/boundary_precision_check/posture_amber_count_exactly_three_crosses_heightened
        """
        m1 = _metric(api, "M1")
        m2 = _metric(api, "M2")
        post_reading(m1["id"], 1500)  # AMBER
        post_reading(m2["id"], 1500)  # AMBER
        snap = validate_success(api.run_posture_evaluation(officer_headers), expected_status=201)
        assert snap["amber_count"] == 2
        assert snap["level"] == "NORMAL", f"2 < 3 ambers must leave posture NORMAL, got {snap['level']}"

    def test_three_ambers_cross_to_heightened(self, api, officer_headers):
        """PRD §3.6: "The raw level is `CRISIS` when at least two metrics are
        red; otherwise `SEVERE` when at least one is red; otherwise
        `HEIGHTENED` when at least three metrics are amber or at least two
        breaches are open; otherwise `NORMAL`."

        Design: Difficulty/boundary_precision_check/posture_amber_count_exactly_three_crosses_heightened
        """
        m1 = _metric(api, "M1")
        m2 = _metric(api, "M2")
        m3 = _metric(api, "M3")
        post_reading(m1["id"], 1500)
        post_reading(m2["id"], 1500)
        post_reading(m3["id"], 1500)  # third AMBER crosses the >= 3 breakpoint
        snap = validate_success(api.run_posture_evaluation(officer_headers), expected_status=201)
        assert snap["amber_count"] == 3
        assert snap["level"] == "HEIGHTENED", (
            f"3 ambers cross to HEIGHTENED, got {snap['level']}"
        )


class TestReadingCadence:
    def test_metric_reading_minimum_cadence_buffer(self, api, analyst_headers):
        """PRD §3.6: "Cadence is enforced whenever a previous reading exists:
        the new `observed_at` must be at least `last_reading_at` plus
        `min_reading_interval_hours` — exactly on that boundary is allowed —
        and anything earlier is rejected with `ERR_READING_TOO_FREQUENT`."

        Design: Difficulty/resource_temporal_overlap/metric_reading_minimum_cadence_buffer
        """
        metric = _metric(api, "M", cadence=24)
        first = post_reading(metric["id"], 100, observed_at="2026-08-01T00:00:00Z")
        assert first["band"] == "GREEN"

        # 12h later: inside the 24h buffer -> rejected.
        resp = api.post_metric_reading(
            metric["id"], {"observed_at": "2026-08-01T12:00:00Z", "value": 200},
            analyst_headers,
        )
        validate_error(resp, ApiErrorId.ERR_READING_TOO_FREQUENT)

        # Exactly +24h: on the boundary, allowed. The rejected reading did not
        # move last_reading_at, so this is measured from the first reading.
        third = post_reading(metric["id"], 200, observed_at="2026-08-02T00:00:00Z")
        assert third["band"] == "GREEN"

    def test_cadence_boundary_uses_last_accepted_reading(self, api, analyst_headers):
        """PRD §3.6: "the new `observed_at` must be at least `last_reading_at`
        plus `min_reading_interval_hours` — exactly on that boundary is allowed
        — and anything earlier is rejected with `ERR_READING_TOO_FREQUENT`."
        PRD §3.6: "The metric's `current_band` and `last_reading_at` then track
        the latest reading by `observed_at`".

        Design: Difficulty/resource_temporal_overlap/metric_reading_minimum_cadence_buffer
        """
        metric = _metric(api, "M", cadence=24)
        post_reading(metric["id"], 100, observed_at="2026-08-01T00:00:00Z")
        post_reading(metric["id"], 200, observed_at="2026-08-02T00:00:00Z")
        metric_now = validate_success(api.get_ewi_metric(metric["id"], analyst_headers))
        assert metric_now["last_reading_at"] == "2026-08-02T00:00:00Z", (
            f"last_reading_at tracks the latest reading, got {metric_now['last_reading_at']}"
        )
        # 23h after the second reading: still inside the buffer.
        resp = api.post_metric_reading(
            metric["id"], {"observed_at": "2026-08-02T23:00:00Z", "value": 300},
            analyst_headers,
        )
        validate_error(resp, ApiErrorId.ERR_READING_TOO_FREQUENT)
        # Exactly +24h after the second reading: allowed.
        third = post_reading(metric["id"], 300, observed_at="2026-08-03T00:00:00Z")
        assert third["band"] == "GREEN"


class TestMetricConfigValidation:
    def test_threshold_config_inverted_rejected(self, api, officer_headers):
        """PRD §3.6: "Threshold coherence depends on direction: `ABOVE_BREACHES`
        requires the red boundary strictly above the amber one, while
        `BELOW_BREACHES` requires red strictly below amber; an inconsistent
        pair is rejected with `ERR_THRESHOLD_CONFIG_INVALID` (HTTP 422)."

        Design: Corner/validations/threshold_config_inverted_rejected
        """
        resp = api.create_ewi_metric(
            create_ewi_metric_payload(
                code="BAD", name="bad", direction="ABOVE_BREACHES",
                amber_threshold=5000, red_threshold=4000,
            ),
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_THRESHOLD_CONFIG_INVALID)

    def test_reading_on_missing_metric_returns_not_found(self, api, analyst_headers):
        """PRD §2.8: "Endpoints nested under a parent path validate path
        identifiers strictly from left to right, and the first identifier that
        does not resolve to an existing resource yields `ERR_NOT_FOUND`
        (HTTP 404)".

        Design: Corner/validations/reading_on_missing_metric_returns_not_found
        """
        resp = api.post_metric_reading(
            NON_EXISTENT_UUID,
            {"observed_at": "2026-08-01T00:00:00Z", "value": 100},
            analyst_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestPostureHistory:
    def test_posture_snapshot_history_lists_evaluations(self, api, officer_headers):
        """PRD §2.3: "The posture snapshot history is the single exception: it
        is ordered by `snapshot_seq` ascending, so that evaluations replay in
        exactly the order they were appended."
        PRD §3.6: "Every evaluation, automatic or manual, appends a
        `PostureSnapshot` recording a monotone `snapshot_seq`, the new `level`,
        the `prior_level` (`NORMAL` when no prior snapshot exists), the three
        counts, the `trigger` (`READING_AUTO` or `MANUAL_EVALUATION`)".

        Design: Corner/state_machines/posture_snapshot_history_lists_evaluations
        """
        metric = _metric(api, "M")
        post_reading(metric["id"], 6000)  # RED -> READING_AUTO SEVERE snapshot
        manual = validate_success(api.run_posture_evaluation(officer_headers), expected_status=201)
        assert manual["level"] == "SEVERE"
        assert manual["prior_level"] == "SEVERE"
        assert manual["trigger"] == "MANUAL_EVALUATION"

        snapshots, _meta = validate_paginated(api.list_posture_snapshots(officer_headers))
        assert len(snapshots) == 2, f"two evaluations must produce two snapshots, got {len(snapshots)}"
        first, second = snapshots[0], snapshots[1]
        assert first["snapshot_seq"] < second["snapshot_seq"], (
            "history must replay in snapshot_seq ascending order"
        )
        assert first["trigger"] == "READING_AUTO"
        assert second["trigger"] == "MANUAL_EVALUATION"
