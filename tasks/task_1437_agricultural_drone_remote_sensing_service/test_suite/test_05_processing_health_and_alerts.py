"""Imagery processing, anomaly scoring boundaries, field health computation,
and deliverable access expiry (PRD sections 3.6 and 2.7)."""
from test_helpers import (
    ApiErrorId,
    ENGINE,
    api_client,
    create_mission,
    create_mission_completed,
    get_field,
    list_field_alerts,
    make_grower_headers,
    make_pilot_headers,
    process_ndvi_deliverable,
    process_plant_count_deliverable,
    set_clock,
    setup_ops,
    validate_error,
    validate_success,
)


class TestHealthScoreDualBasis:

    def test_health_score_uses_ndvi_base(self):
        """PRD section 3.6: "The base comes from the field's most recently
        created deliverable that is `READY` or `DELIVERED`: for an `NDVI`
        product the base is the mean index multiplied by 100 and rounded to a
        whole number".

        Design: Difficulty/dual_variant_calc/field_health_score_ndvi_vs_plant_count_basis
        """
        ctx = setup_ops()
        mission = create_mission_completed(
            ctx["field"]["id"], ctx["pilot"]["id"],
            acres_planned=50, acres_flown=50)
        process_ndvi_deliverable(mission["id"], 0.720, 0)
        field = get_field(ctx["field"]["id"])
        # round(0.720 * 100) = 72, no alerts outstanding.
        assert field["health_score"] == 72, \
            f"NDVI base must be round(ndvi_mean*100)=72, got {field['health_score']}"

    def test_health_score_uses_plant_count_base(self):
        """PRD section 3.6: "for a `PLANT_COUNT` product it is the reported
        stand divided by the 30,000-plants-per-acre target, multiplied by 100,
        rounded to a whole number, and capped at 100."

        Design: Difficulty/dual_variant_calc/field_health_score_ndvi_vs_plant_count_basis
        """
        ctx = setup_ops()
        mission = create_mission_completed(
            ctx["field"]["id"], ctx["pilot"]["id"],
            acres_planned=50, acres_flown=50,
            deliverable_kinds=["PLANT_COUNT"])
        process_plant_count_deliverable(mission["id"], 24000)
        field = get_field(ctx["field"]["id"])
        # min(100, round(24000/30000*100)) = 80; stand >= 20000 so no alert.
        assert field["health_score"] == 80, \
            f"PLANT_COUNT base must be min(100, round(24000/30000*100))=80, " \
            f"got {field['health_score']}"


class TestHealthScoreClamp:

    def test_health_score_floors_at_zero_when_penalty_exceeds_base(self):
        """PRD section 3.6: "The final score is the base minus the penalty,
        floored at 0 and capped at 100."
        PRD section 2.7: "A field's health score is an integer that can never
        fall below 0 nor rise above 100, regardless of what the underlying
        computation yields."

        Design: Difficulty/combinatorial_formula/field_health_score_nested_min_max
        """
        ctx = setup_ops(field_overrides={"legal_acres": 200})
        mission = create_mission_completed(
            ctx["field"]["id"], ctx["pilot"]["id"],
            acres_planned=100, acres_flown=100)
        # anomaly_count = round_half_up(30000*100/1000) = 3000 -> HIGH alert.
        deliverable = process_ndvi_deliverable(mission["id"], 0.050, 30000)
        assert deliverable["anomaly_count"] == 3000
        alerts = list_field_alerts(ctx["field"]["id"])
        assert len(alerts) == 1 and alerts[0]["severity"] == "HIGH"
        field = get_field(ctx["field"]["id"])
        # base = round(0.050*100) = 5; penalty 12; max(0, 5-12) = 0.
        assert field["health_score"] == 0, \
            f"penalty overshoot must clamp at 0, got {field['health_score']}"

    def test_health_score_caps_at_one_hundred(self):
        """PRD section 3.6: "for a `PLANT_COUNT` product it is the reported
        stand divided by the 30,000-plants-per-acre target, multiplied by 100,
        rounded to a whole number, and capped at 100."
        PRD section 2.7: "A field's health score is an integer that can never
        fall below 0 nor rise above 100, regardless of what the underlying
        computation yields."

        Design: Difficulty/combinatorial_formula/field_health_score_nested_min_max
        """
        ctx = setup_ops()
        mission = create_mission_completed(
            ctx["field"]["id"], ctx["pilot"]["id"],
            acres_planned=50, acres_flown=50,
            deliverable_kinds=["PLANT_COUNT"])
        # 60000/30000*100 = 200 -> capped at 100.
        process_plant_count_deliverable(mission["id"], 60000)
        field = get_field(ctx["field"]["id"])
        assert field["health_score"] == 100, \
            f"base overshoot must clamp at 100, got {field['health_score']}"


class TestCompletionToHealthCascade:

    def test_complete_then_process_cascades_to_alert_and_health(self):
        """PRD section 3.5: "The mission moves to `COMPLETED`; the field's
        `surveyed_acres` is rewritten with the mission's actual `acres_flown`;
        the grower's `acres_included_ytd` grows by those same acres".
        PRD section 3.6: "Whenever the count is positive, a `ScoutingAlert` is
        created against the field, referencing the `deliverable_id` that
        raised it, carrying the derived `severity`, born `OPEN`".
        PRD section 3.6: "10 up through 49 raises `MEDIUM`; and 50 or more
        raises `HIGH`."

        Design: Difficulty/transitive_cascade/mission_complete_cascades_depth3
        """
        ctx = setup_ops()
        mission = create_mission_completed(
            ctx["field"]["id"], ctx["pilot"]["id"],
            acres_planned=100, acres_flown=100)
        assert get_field(ctx["field"]["id"])["surveyed_acres"] == 100
        # anomaly_count = round_half_up(2000*100/1000) = 200 -> HIGH.
        deliverable = process_ndvi_deliverable(mission["id"], 0.500, 2000)
        assert deliverable["status"] == "READY"
        assert deliverable["anomaly_count"] == 200
        alerts = list_field_alerts(ctx["field"]["id"])
        assert len(alerts) == 1, f"expected one alert, got {len(alerts)}"
        assert alerts[0]["severity"] == "HIGH"
        assert alerts[0]["status"] == "OPEN"
        assert alerts[0]["deliverable_id"] == deliverable["id"]
        field = get_field(ctx["field"]["id"])
        # base = round(0.500*100) = 50; HIGH weight 12 -> max(0, 50-12) = 38.
        assert field["health_score"] == 38, \
            f"health must be base 50 minus HIGH penalty 12, got {field['health_score']}"


class TestAnomalyCountBoundary:

    def test_zero_anomalies_raise_no_alert(self):
        """PRD section 3.6: "Severity ladders off the result with inclusive
        boundaries: zero anomalies raise no alert at all; a count from 1 up
        through 9 raises a `LOW` alert; 10 up through 49 raises `MEDIUM`; and
        50 or more raises `HIGH`."

        Design: Difficulty/boundary_precision_check/anomaly_count_zero_vs_one_alert_creation
        """
        ctx = setup_ops()
        mission = create_mission_completed(
            ctx["field"]["id"], ctx["pilot"]["id"],
            acres_planned=10, acres_flown=10)
        deliverable = process_ndvi_deliverable(mission["id"], 0.700, 0)
        assert deliverable["anomaly_count"] == 0
        alerts = list_field_alerts(ctx["field"]["id"])
        assert alerts == [], f"zero anomalies must raise no alert, got {alerts}"

    def test_one_anomaly_raises_low_alert(self):
        """PRD section 3.6: "For an `NDVI` deliverable, cells whose index
        value falls below 0.400 count as stressed — the payload reports their
        number directly — and the `anomaly_count` is that cell count
        multiplied by the mission's `acres_flown` and divided by one thousand,
        rounded half-up to a whole number."
        PRD section 3.6: "a count from 1 up through 9 raises a `LOW` alert".

        Design: Difficulty/boundary_precision_check/anomaly_count_zero_vs_one_alert_creation
        """
        ctx = setup_ops()
        mission = create_mission_completed(
            ctx["field"]["id"], ctx["pilot"]["id"],
            acres_planned=10, acres_flown=10)
        # round_half_up(100*10/1000) = 1 -> LOW.
        deliverable = process_ndvi_deliverable(mission["id"], 0.690, 100)
        assert deliverable["anomaly_count"] == 1
        alerts = list_field_alerts(ctx["field"]["id"])
        assert len(alerts) == 1, f"expected exactly one alert, got {len(alerts)}"
        assert alerts[0]["severity"] == "LOW"


class TestSeverityThresholdBoundary:

    def test_severity_low_at_9_medium_at_10(self):
        """PRD section 3.6: "Severity ladders off the result with inclusive
        boundaries: zero anomalies raise no alert at all; a count from 1 up
        through 9 raises a `LOW` alert; 10 up through 49 raises `MEDIUM`; and
        50 or more raises `HIGH`."

        Design: Corner/calculations/severity_threshold_medium_at_exactly_10
        """
        ctx = setup_ops()
        m9 = create_mission_completed(
            ctx["field"]["id"], ctx["pilot"]["id"],
            start="2026-06-02T08:00:00Z", end="2026-06-02T10:00:00Z",
            launch_time="2026-06-02T08:30:00Z",
            acres_planned=10, acres_flown=10)
        # round_half_up(900*10/1000) = 9 -> LOW
        d9 = process_ndvi_deliverable(m9["id"], 0.500, 900)
        assert d9["anomaly_count"] == 9
        m10 = create_mission_completed(
            ctx["field"]["id"], ctx["pilot"]["id"],
            start="2026-06-03T08:00:00Z", end="2026-06-03T10:00:00Z",
            launch_time="2026-06-03T08:30:00Z",
            acres_planned=10, acres_flown=10)
        # round_half_up(1000*10/1000) = 10 -> MEDIUM (inclusive lower bound)
        d10 = process_ndvi_deliverable(m10["id"], 0.500, 1000)
        assert d10["anomaly_count"] == 10
        alerts = list_field_alerts(ctx["field"]["id"])
        by_deliverable = {a["deliverable_id"]: a for a in alerts}
        assert by_deliverable[d9["id"]]["severity"] == "LOW", \
            "anomaly_count 9 must be LOW"
        assert by_deliverable[d10["id"]]["severity"] == "MEDIUM", \
            "anomaly_count 10 must be MEDIUM"


class TestProcessingInputValidation:

    def test_ndvi_mean_above_one_rejected(self):
        """PRD section 3.6: "For an `NDVI` deliverable the payload's
        `ndvi_mean` is required and must lie between 0.000 and 1.000
        inclusive, expressed to three decimal places; for a `PLANT_COUNT`
        deliverable the payload's `plant_count_per_acre` is required and must
        be greater than zero. Inputs that fail their kind's shape are rejected
        as `ERR_DELIV_INPUT_INVALID`."

        Design: Corner/calculations/ndvi_mean_boundary_precision_3_decimal
        """
        ctx = setup_ops()
        mission = create_mission_completed(
            ctx["field"]["id"], ctx["pilot"]["id"],
            acres_planned=10, acres_flown=10)
        resp_list = api_client.list_mission_deliverables(mission["id"], ENGINE)
        deliverable = validate_success(resp_list)[0]
        resp = api_client.process_deliverable(
            deliverable["id"],
            {"ndvi_mean": 1.001, "cells_below_threshold": 0}, ENGINE)
        validate_error(resp, ApiErrorId.ERR_DELIV_INPUT_INVALID)


class TestProcessingRoleGate:

    def test_remote_pilot_cannot_process_deliverable(self):
        """PRD section 2.1: "a role attempting an operation outside its grant
        is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD section 4: POST /ag-drone/deliverables/{id}/process is authorized
        for ProcessingEngine only.

        Design: Corner/roles/remote_pilot_cannot_process_deliverable
        """
        ctx = setup_ops()
        mission = create_mission_completed(
            ctx["field"]["id"], ctx["pilot"]["id"],
            acres_planned=10, acres_flown=10)
        resp_list = api_client.list_mission_deliverables(mission["id"], ENGINE)
        deliverable = validate_success(resp_list)[0]
        resp = api_client.process_deliverable(
            deliverable["id"],
            {"ndvi_mean": 0.5, "cells_below_threshold": 0},
            make_pilot_headers(ctx["pilot"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestDeliverableAccessExpiry:

    def test_deliverable_grower_get_after_expiry_returns_gone(self):
        """PRD section 3.6: "Access then remains time-boxed: once the logical
        clock reaches `accessible_until`, or once the sweep has moved the
        deliverable to `EXPIRED`, a grower's read of it is refused with
        `ERR_DELIV_EXPIRED` (HTTP 410)."

        Design: Corner/endpoints/deliverable_grower_get_after_expiry_returns_gone
        """
        ctx = setup_ops(plan_overrides={"storage_retention_days": 1})
        mission = create_mission_completed(
            ctx["field"]["id"], ctx["pilot"]["id"],
            acres_planned=10, acres_flown=10)
        process_ndvi_deliverable(mission["id"], 0.700, 0)
        resp_list = api_client.list_mission_deliverables(mission["id"], ENGINE)
        deliverable = validate_success(resp_list)[0]
        # Advance the clock well past accessible_until (retention was 1 day).
        set_clock("2026-06-05T12:00:00Z")
        resp = api_client.get_deliverable(
            deliverable["id"], make_grower_headers(ctx["grower"]["id"]))
        validate_error(resp, ApiErrorId.ERR_DELIV_EXPIRED)
