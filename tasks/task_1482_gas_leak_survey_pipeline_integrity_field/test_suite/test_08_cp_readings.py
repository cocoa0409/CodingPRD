"""Cathodic-protection readings, anomaly disposition, and posture derivation (PRD §2.8, §3.10)."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_leak,
    make_org,
    make_segment,
    setup_accepted_run,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_cp_reading_payload

CLEAN_READING = {"pipe_to_soil_potential_mv": -1000.0, "instant_off_potential_mv": -950.0}
ANOMALOUS_READING = {"pipe_to_soil_potential_mv": -700.0, "instant_off_potential_mv": -800.0}


def _post_cp(api, ctx, segment_id, reading, test_point="TP-1"):
    return api.create_cp_reading(
        create_cp_reading_payload(segment_id, test_point_id=test_point, **reading),
        ctx["ft_h"],
    )


class TestCpAnomalyLifecycle:
    def test_cp_anomaly_full_lifecycle(self, api):
        """PRD §3.10: "An anomalous reading is born with `anomaly_status` of
        `OPEN`"; "An `IntegrityAnalyst` acknowledges an `OPEN` anomaly
        (`OPEN → ACKNOWLEDGED`)"; "Resolution moves the anomaly to `RESOLVED`
        (terminal)".

        Design: Corner/state_machines/cp_anomaly_full_lifecycle
        """
        ctx = make_org()
        segment = make_segment(ctx, segment_code="SEG-CP")
        created = validate_success(_post_cp(api, ctx, segment["id"], ANOMALOUS_READING),
                                   expected_status=201)
        assert created["is_anomalous"] is True
        assert created["anomaly_status"] == "OPEN"

        acked = validate_success(api.acknowledge_cp_reading(created["id"], ctx["ia_h"]))
        assert acked["anomaly_status"] == "ACKNOWLEDGED"

        # Newer clean reading = cleanup evidence.
        validate_success(_post_cp(api, ctx, segment["id"], CLEAN_READING), expected_status=201)
        resolved = validate_success(api.resolve_cp_reading(created["id"], ctx["ia_h"]))
        assert resolved["anomaly_status"] == "RESOLVED"

    def test_cp_acknowledge_clean_reading_rejected(self, api):
        """PRD §3.10: "A clean reading keeps `anomaly_status` of `NONE`" and
        "any other state is rejected with `ERR_ANOMALY_NOT_OPEN`."

        Design: Corner/state_machines/cp_acknowledge_clean_reading_rejected
        """
        ctx = make_org()
        segment = make_segment(ctx, segment_code="SEG-CPC")
        clean = validate_success(_post_cp(api, ctx, segment["id"], CLEAN_READING),
                                 expected_status=201)
        assert clean["anomaly_status"] == "NONE"
        resp = api.acknowledge_cp_reading(clean["id"], ctx["ia_h"])
        validate_error(resp, ApiErrorId.ERR_ANOMALY_NOT_OPEN)

    def test_cp_resolve_from_open_rejected(self, api):
        """PRD §3.10: "Resolving requires `ACKNOWLEDGED`
        (`ERR_ANOMALY_NOT_ACKNOWLEDGED`)."

        Design: Corner/state_machines/cp_resolve_from_open_rejected
        """
        ctx = make_org()
        segment = make_segment(ctx, segment_code="SEG-CPO")
        anomalous = validate_success(_post_cp(api, ctx, segment["id"], ANOMALOUS_READING),
                                     expected_status=201)
        resp = api.resolve_cp_reading(anomalous["id"], ctx["ia_h"])
        validate_error(resp, ApiErrorId.ERR_ANOMALY_NOT_ACKNOWLEDGED)

    def test_cp_resolve_without_cleanup_reading_rejected(self, api):
        """PRD §3.10: "additionally requires a newer cathodic-protection reading
        on the same segment with `is_anomalous` false — the cleanup evidence —
        else `ERR_NO_CLEANUP_READING`."

        Design: Corner/state_machines/cp_resolve_without_cleanup_reading_rejected
        """
        ctx = make_org()
        segment = make_segment(ctx, segment_code="SEG-CPN")
        anomalous = validate_success(_post_cp(api, ctx, segment["id"], ANOMALOUS_READING),
                                     expected_status=201)
        get_success_data(api.acknowledge_cp_reading(anomalous["id"], ctx["ia_h"]))
        resp = api.resolve_cp_reading(anomalous["id"], ctx["ia_h"])
        validate_error(resp, ApiErrorId.ERR_NO_CLEANUP_READING)


class TestCpThresholdsAndPosture:
    def test_cp_anomaly_threshold_boundary(self, api):
        """PRD §3.10: "the reading is anomalous when the instant-off potential is
        greater (less negative) than -850 mV" — exactly -850 is not anomalous;
        -849 is.

        Design: Corner/calculations/cp_anomaly_threshold_boundary
        """
        ctx = make_org()
        segment = make_segment(ctx, segment_code="SEG-CPB")
        at_threshold = validate_success(_post_cp(
            api, ctx, segment["id"],
            {"pipe_to_soil_potential_mv": -900.0, "instant_off_potential_mv": -850.0},
            test_point="TP-A",
        ), expected_status=201)
        assert at_threshold["is_anomalous"] is False
        assert at_threshold["anomaly_status"] == "NONE"

        over_threshold = validate_success(_post_cp(
            api, ctx, segment["id"],
            {"pipe_to_soil_potential_mv": -900.0, "instant_off_potential_mv": -849.0},
            test_point="TP-B",
        ), expected_status=201)
        assert over_threshold["is_anomalous"] is True
        assert over_threshold["anomaly_status"] == "OPEN"

    def test_posture_threshold_with_g3_leaks(self, api):
        """PRD §2.8: "if it has three or more open Grade 3 leaks, posture is
        `ELEVATED`. In all remaining cases posture is `NORMAL`."

        Design: Corner/calculations/posture_threshold_with_g3_leaks
        """
        ctx = setup_accepted_run(
            route_code="R-P3",
            segment_overrides={
                "segment_code": "SEG-P3",
                "install_year": 2015,
                "material": "PLASTIC_PE",
                "diameter_inches": 2.0,
                "length_feet": 300.0,
                "operating_pressure_psi": 30.0,
                "pressure_class": "SERVICE",
            },
            distance_covered_feet=300.0,
        )
        segment, run = ctx["segments"][0], ctx["run"]
        g3 = {"concentration_ppm": 500.0, "bar_hole_reading_pct_lel": 1.0,
              "is_migration_evidence": False}
        make_leak(ctx, segment["id"], run["id"], distance_to_building_feet=200.0, **g3)
        make_leak(ctx, segment["id"], run["id"], distance_to_building_feet=210.0, **g3)

        seg = get_success_data(api.get_pipe_segment(segment["id"], ctx["ia_h"]))
        assert seg["open_grade3_count"] == 2
        assert seg["posture"] == "NORMAL"

        make_leak(ctx, segment["id"], run["id"], distance_to_building_feet=220.0, **g3)
        seg = get_success_data(api.get_pipe_segment(segment["id"], ctx["ia_h"]))
        assert seg["open_grade3_count"] == 3
        assert seg["posture"] == "ELEVATED"

    def test_immediate_visibility_of_writes_in_read(self, api):
        """PRD §3.10: "The server stamps `recorded_at` and computes `is_anomalous`"
        in the write response itself, and "recording it recomputes the segment's
        `posture` (per §2.8, an open anomaly alone raises posture to `ELEVATED`)" —
        visible on the immediately following read with no lag.

        Design: Corner/consistency_model/immediate_visibility_of_writes_in_read
        """
        ctx = make_org()
        segment = make_segment(ctx, segment_code="SEG-IM")
        created = validate_success(_post_cp(api, ctx, segment["id"], ANOMALOUS_READING),
                                   expected_status=201)
        assert created["is_anomalous"] is True
        assert created["anomaly_status"] == "OPEN"
        seg = get_success_data(api.get_pipe_segment(segment["id"], ctx["ia_h"]))
        assert seg["posture"] == "ELEVATED"
