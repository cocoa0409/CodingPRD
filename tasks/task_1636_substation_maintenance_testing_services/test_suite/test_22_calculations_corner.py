"""Corner coverage — calculations: grading formulas, certification status
boundary, defect SLA dates, and score renormalization."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_accepted_test_event,
    create_certified_technician,
    create_defect,
    create_technician,
    create_test_event,
    grant_certification,
    make_technician_headers,
    setup_asset,
    submit_test_event,
    validate_error,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["ops_manager_headers"]


class TestInsulationTemperatureCorrection:
    def test_ambient_temperature_flips_grade(self):
        """PRD §3.4: "For `INSULATION_RESISTANCE`, the platform computes the
        temperature-corrected resistance by multiplying `value_primary` by 2
        raised to the power of one-tenth of the difference between
        `ambient_temp_c` and the 40-degree reference temperature — that is, the
        measured resistance doubles for every 10 degrees Celsius the ambient is
        above 40 and halves for every 10 degrees below. The corrected value is
        compared against the policy's `ir_min_mohm`: a corrected value at or
        above `ir_min_mohm` grades `PASS`; a corrected value strictly below
        `ir_min_mohm` but at or above half of `ir_min_mohm` grades `MARGINAL`;
        anything below half grades `FAIL`."

        Design: Corner/calculations/insulation_temperature_correction
        """
        base = setup_asset("POWER_TRANSFORMER")
        _, tech_headers = create_certified_technician("NETA_LEVEL_2")
        asset_id = base["asset"]["id"]
        # 800 Mohm at 60C corrects to 800 * 2^2 = 3200 >= 1000 -> PASS.
        hot = create_test_event(
            asset_id, tech_headers, "INSULATION_RESISTANCE",
            value_primary=800, ambient_temp_c=60, measured_at="2026-07-01T08:00:00Z",
        )
        # 300 Mohm at 20C corrects to 300 * 2^-2 = 75 < 500 -> FAIL.
        cold = create_test_event(
            asset_id, tech_headers, "INSULATION_RESISTANCE",
            value_primary=300, ambient_temp_c=20, measured_at="2026-07-01T09:00:00Z",
        )
        assert submit_test_event(hot["id"], tech_headers)["result"] == "PASS"
        assert submit_test_event(cold["id"], tech_headers)["result"] == "FAIL"


class TestRelayTimingDeviationBands:
    def test_strictly_greater_band_edges(self):
        """PRD §3.4: "For `RELAY_TIMING`, the deviation percent is the absolute
        difference between `value_primary` and `value_secondary`, divided by
        `value_secondary`, multiplied by 100. A deviation strictly greater than
        `relay_timing_fail_pct` grades `FAIL`; strictly greater than
        `relay_timing_warn_pct` but not greater than `relay_timing_fail_pct`
        grades `MARGINAL`; otherwise `PASS`. A deviation exactly equal to
        `relay_timing_warn_pct` is `PASS`; exactly equal to
        `relay_timing_fail_pct` is `MARGINAL`."

        Design: Corner/calculations/relay_timing_deviation_bands
        """
        base = setup_asset("RELAY")
        _, tech_headers = create_certified_technician("NETA_LEVEL_3")
        asset_id = base["asset"]["id"]
        cases = [(105, "PASS"), (110, "MARGINAL"), (111, "FAIL")]  # vs nominal 100 ms
        for measured_ms, expected in cases:
            event = create_test_event(
                asset_id, tech_headers, "RELAY_TIMING",
                value_primary=measured_ms, value_secondary=100,
                measured_at="2026-07-02T08:00:00Z",
            )
            submitted = submit_test_event(event["id"], tech_headers)
            assert submitted["result"] == expected, (
                f"deviation {abs(measured_ms - 100)}% should grade {expected}"
            )


class TestCertificationStatusExpiryBoundary:
    def test_cert_expiring_at_clock_is_expired_and_gates_submit(self):
        """PRD §3.9: "A certification's `status` is derived, never stored by
        the caller: `REVOKED` when `revoked_at` is set; otherwise `EXPIRED`
        when the logical clock has reached or passed `expires_at` — the
        boundary is inclusive, so a clock exactly equal to `expires_at` is
        `EXPIRED`; otherwise `ACTIVE`."
        PRD §3.9: "Submitting a `RELAY_TIMING` test event requires
        `NETA_LEVEL_3` or higher; submitting any other test type requires
        `NETA_LEVEL_2` or higher; verifying, rejecting, or activating a relay
        setting requires `NETA_LEVEL_4` exactly as the minimum rank."

        Design: Corner/calculations/certification_status_expiry_boundary
        """
        base = setup_asset("POWER_TRANSFORMER")
        tech = create_technician()
        # Expires exactly at the startup clock 2026-08-01T00:00:00Z.
        grant_certification(
            tech["id"], "NETA_LEVEL_2",
            issued_at="2024-08-01T00:00:00Z", expires_at="2026-08-01T00:00:00Z",
        )
        certs, _ = validate_paginated(api_client.list_certifications(tech["id"], OPS))
        assert certs[0]["status"] == "EXPIRED"

        tech_headers = make_technician_headers(tech["id"])
        event = create_test_event(
            base["asset"]["id"], tech_headers, "OIL_MOISTURE",
            value_primary=10, measured_at="2026-07-31T00:00:00Z",
        )
        resp = api_client.submit_test_event(event["id"], tech_headers)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_REQUIRED, 403)


class TestDefectSlaDueDates:
    def test_due_dates_match_severity_sla(self):
        """PRD §3.6: "The `due_date` is computed from severity: `C1` defects
        are due 30 days after creation, `C2` after 90 days, `C3` after 365
        days; the result is a whole ISO date."
        PRD §2.7: "At server startup the clock reads exactly
        `2026-08-01T00:00:00Z` and never falls back to wall-clock time."

        Design: Corner/calculations/defect_sla_due_dates
        """
        base = setup_asset(
            "CIRCUIT_BREAKER", voltage_kv=34.5, install_date="2019-01-01T00:00:00Z"
        )
        _, tech_headers = create_certified_technician("NETA_LEVEL_2")
        asset_id = base["asset"]["id"]
        expected = {"C1": "2026-08-31", "C2": "2026-10-30", "C3": "2027-08-01"}
        for severity, due in expected.items():
            defect = create_defect(asset_id, tech_headers, severity, title=f"D-{severity}")
            assert defect["due_date"] == due, (
                f"{severity} defect due {due} (created at the 2026-08-01 clock)"
            )


class TestConditionScoreRenormalization:
    def test_single_present_component_renormalizes_weights(self):
        """PRD §3.5: "The base score is the weighted average over present
        components only: each present component is multiplied by its policy
        weight (`w_insulation`, `w_oil`, `w_relay`), summed, and divided by the
        sum of the weights of the present components; the weights of absent
        disciplines are dropped entirely."
        PRD §3.4: "Second, when the accepted `result` is `MARGINAL` or `FAIL`,
        the platform auto-creates a `Defect` on the same asset with
        `test_event_id` pointing at the accepted event, a system-generated
        `title`, severity mapped from the result (`FAIL` becomes `C2`;
        `MARGINAL` becomes `C3` — any severity supplied by the caller on this
        path is ignored), and status `OPEN`."

        Design: Corner/calculations/condition_score_single_component_renormalization
        """
        base = setup_asset("RELAY")
        _, tech_headers = create_certified_technician("NETA_LEVEL_3")
        # One MARGINAL relay-timing test (110 vs 100 ms with warn 5 / fail 10).
        create_accepted_test_event(
            base["asset"]["id"], tech_headers, "RELAY_TIMING",
            value_primary=110, value_secondary=100, measured_at="2026-07-03T08:00:00Z",
        )
        forecast = validate_success(api_client.get_asset_forecast(base["asset"]["id"], OPS))
        # Only the relay component is present: 0.6*70/0.6 = 70.00; the accept
        # auto-created a C3 defect, subtracting 1 -> 69.00.
        assert forecast["condition_score"] == pytest.approx(69.00, abs=0.01)
        assert forecast["escalation_active"] is False  # 69.00 >= threshold 60
