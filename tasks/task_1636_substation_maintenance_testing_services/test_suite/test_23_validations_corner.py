"""Corner coverage — validations: auth, temporal gates, certification gate,
capacity, coordination margin, revalidation flag, decommission guards, and the
spare selector's empty pool."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_switching_step,
    api_client,
    approve_outage_window,
    create_accepted_test_event,
    create_asset,
    create_certified_technician,
    create_defect,
    create_outage_window,
    create_spare_reservation,
    create_spare_unit,
    create_test_event,
    create_verified_relay_setting,
    create_work_order,
    schedule_work_order,
    set_clock,
    setup_asset,
    setup_relay_domain,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

OPS = TEST_USERS["ops_manager_headers"]
COORD = TEST_USERS["coordinator_headers"]
SUP1 = TEST_USERS["supervisor_headers"]


class TestAuthentication:
    def test_missing_auth_headers_returns_401(self):
        """PRD §2.1: "Every request carries two authentication headers:
        `X-User-ID` and `X-User-Role`. A request missing either header, or
        carrying a role string the platform does not recognize, is rejected
        with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_401
        """
        resp = api_client.list_substations({})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestTemporalGates:
    def test_outage_start_in_past_rejected(self):
        """PRD §3.2: "The start must lie strictly in the future relative to the
        logical clock; otherwise the request is rejected with
        `ERR_INTERVAL_IN_PAST` (HTTP 422)."
        PRD §2.7: "At server startup the clock reads exactly
        `2026-08-01T00:00:00Z` and never falls back to wall-clock time."

        Design: Corner/validations/outage_start_in_past_rejected
        """
        base = setup_asset("POWER_TRANSFORMER")
        resp = api_client.create_outage_window(
            {
                "substation_id": base["substation"]["id"],
                "asset_id": base["asset"]["id"],
                "start_ts": "2026-07-01T08:00:00Z",
                "end_ts": "2026-07-01T16:00:00Z",
                "purpose": "Past window",
            },
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_INTERVAL_IN_PAST, 422)

    def test_zero_length_reservation_interval_rejected(self):
        """PRD §3.7: "The interval is half-open, `end_ts` strictly after
        `start_ts`, and `start_ts` strictly in the future (otherwise
        `ERR_INTERVAL_IN_PAST`, HTTP 422)."
        PRD §2.8: "then request-body schema and field-type checks (HTTP 400)"

        Design: Corner/validations/end_not_after_start_rejected
        """
        unit = create_spare_unit(home_location="Yard-Z")
        resp = api_client.create_spare_reservation(
            {
                "spare_unit_id": unit["id"],
                "unit_type": "SPARE_TRANSFORMER",
                "required_mva": 20,
                "required_voltage_kv": 115,
                "start_ts": "2026-11-01T14:00:00Z",
                "end_ts": "2026-11-01T14:00:00Z",  # equal: not strictly after
            },
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)


class TestCertificationGate:
    def test_neta_level_2_insufficient_for_relay_timing(self):
        """PRD §3.4: "The technician must hold the required certification:
        `NETA_LEVEL_3` or higher for a `RELAY_TIMING` submission,
        `NETA_LEVEL_2` or higher for any other test type; a technician without
        an `ACTIVE` certification at the required rank is rejected with
        `ERR_CERTIFICATION_REQUIRED` (HTTP 403)."

        Design: Corner/validations/cert_level_insufficient_for_relay_timing_rejected
        """
        base = setup_asset("RELAY")
        _, tech_headers = create_certified_technician("NETA_LEVEL_2")
        event = create_test_event(
            base["asset"]["id"], tech_headers, "RELAY_TIMING",
            value_primary=100, value_secondary=100, measured_at="2026-07-04T00:00:00Z",
        )
        resp = api_client.submit_test_event(event["id"], tech_headers)
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_REQUIRED, 403)


class TestOutageCapacity:
    def test_schedule_beyond_remaining_capacity_rejected(self):
        """PRD §3.6: "the work order's `estimated_hours` must fit within the
        window's remaining capacity — that is, `estimated_hours` is at most
        `duration_hours` minus `committed_hours`, otherwise
        `ERR_OUTAGE_CAPACITY_EXCEEDED` (HTTP 422)."
        PRD §3.6: "Success stamps the work order's `outage_window_id`,
        transitions `DRAFT → SCHEDULED`, adds `estimated_hours` into the
        window's `committed_hours`, and increments both the work order's and
        the window's `version`."

        Design: Corner/validations/outage_capacity_exceeded_rejected
        """
        base = setup_asset("POWER_TRANSFORMER")
        tech, tech_headers = create_certified_technician("NETA_LEVEL_2")
        defect1 = create_defect(base["asset"]["id"], tech_headers, "C2", title="D-one")
        defect2 = create_defect(base["asset"]["id"], tech_headers, "C2", title="D-two")
        wo1 = create_work_order(defect1["id"], tech["id"], 6, title="WO 6h")
        wo2 = create_work_order(defect2["id"], tech["id"], 3, title="WO 3h")
        window = create_outage_window(
            base["substation"]["id"], base["asset"]["id"],
            "2026-10-20T08:00:00Z", "2026-10-20T16:00:00Z", purpose="Capacity probe",
        )
        approved = approve_outage_window(window["id"], "ops-mgr-1")
        schedule_work_order(wo1["id"], window["id"], approved["version"])
        current = validate_success(api_client.get_outage_window(window["id"], COORD))
        assert abs(current["committed_hours"] - 6.00) < 1e-9
        # 3h does not fit into 8.00 - 6.00 = 2.00 remaining hours.
        resp = api_client.schedule_work_order(
            wo2["id"],
            {
                "outage_window_id": window["id"],
                "expected_outage_window_version": current["version"],
            },
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_OUTAGE_CAPACITY_EXCEEDED, 422)


class TestRelayCoordinationMargin:
    def test_insufficient_upstream_margin_rejected(self):
        """PRD §3.8: "The coordination margin is then checked: when the asset's
        `upstream_asset_id` is set and that upstream asset has an `ACTIVE`
        relay setting in the same `setting_group`, the upstream setting's
        `pickup_a` must be at least 1.3 times the activating setting's
        `pickup_a`; a shortfall is rejected with
        `ERR_RELAY_COORDINATION_VIOLATION` (HTTP 422)."

        Design: Corner/validations/relay_coordination_margin_violation_rejected
        """
        domain = setup_relay_domain()
        upstream = domain["asset"]
        downstream = create_asset(
            domain["substation"]["id"], "RELAY", upstream_asset_id=upstream["id"]
        )
        # Upstream relay carries an ACTIVE G1 setting with pickup 100.
        up_setting = create_verified_relay_setting(
            upstream["id"], domain["author_headers"], domain["verifier_headers"],
            pickup_a=100, time_dial=3.0,
        )
        up_asset = validate_success(api_client.get_asset(upstream["id"], OPS))
        validate_success(
            api_client.activate_relay_setting(
                up_setting["id"], {"expected_asset_version": up_asset["version"]},
                domain["verifier_headers"],
            )
        )
        # Downstream verified setting pickup 90: 100 < 1.3 * 90 = 117.
        down_setting = create_verified_relay_setting(
            downstream["id"], domain["author_headers"], domain["verifier_headers"],
            pickup_a=90, time_dial=2.0,
        )
        down_asset = validate_success(api_client.get_asset(downstream["id"], OPS))
        resp = api_client.activate_relay_setting(
            down_setting["id"], {"expected_asset_version": down_asset["version"]},
            domain["verifier_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_RELAY_COORDINATION_VIOLATION, 422)
        setting = validate_success(api_client.get_relay_setting(down_setting["id"], OPS))
        assert setting["status"] == "VERIFIED"


class TestRevalidationFlag:
    def test_flagged_window_blocks_begin_switching(self):
        """PRD §3.11: "The revalidation guard fires on both approval and
        begin-switching: while a window's `needs_revalidation` is true, both
        operations are rejected with `ERR_OUTAGE_NEEDS_REVALIDATION`
        (HTTP 409). The flag is set when the asset's `condition_score` falls
        strictly below the policy's `condition_escalation_threshold` while the
        window is `REQUESTED` or `APPROVED`, and clears when the score recovers
        to at or above that threshold."

        Design: Corner/validations/revalidation_flag_blocks_begin_switching_rejected
        """
        base = setup_asset("POWER_TRANSFORMER")
        window = create_outage_window(
            base["substation"]["id"], base["asset"]["id"],
            "2026-08-25T08:00:00Z", "2026-08-25T16:00:00Z", purpose="Flagged window",
        )
        add_switching_step(window["id"], 1, "Isolate")
        approve_outage_window(window["id"], "ops-mgr-1")
        # An ACCEPTED FAIL insulation test drops the score (30 base - 2
        # penalty = 28) below the escalation threshold 60.
        _, tech_headers = create_certified_technician("NETA_LEVEL_2")
        create_accepted_test_event(
            base["asset"]["id"], tech_headers, "INSULATION_RESISTANCE",
            value_primary=400, ambient_temp_c=40, measured_at="2026-07-25T00:00:00Z",
        )
        set_clock("2026-08-25T09:00:00Z")
        resp = api_client.begin_switching(window["id"], SUP1)
        validate_error(resp, ApiErrorId.ERR_OUTAGE_NEEDS_REVALIDATION, 409)
        current = validate_success(api_client.get_outage_window(window["id"], OPS))
        assert current["status"] == "APPROVED"


class TestOutageGatedTest:
    def test_submit_rejected_when_window_not_cleared(self):
        """PRD §3.4: "When `requires_outage` is true, the linked outage window
        must be in `CLEARED` — submitting against a window in any other state
        is rejected with `ERR_OUTAGE_NOT_CLEARED` (HTTP 409)."

        Design: Corner/validations/outage_gated_test_requires_cleared_window_rejected
        """
        base = setup_asset("POWER_TRANSFORMER")
        window = create_outage_window(
            base["substation"]["id"], base["asset"]["id"],
            "2026-10-25T08:00:00Z", "2026-10-25T16:00:00Z", purpose="Gated test",
        )
        approve_outage_window(window["id"], "ops-mgr-1")
        _, tech_headers = create_certified_technician("NETA_LEVEL_2")
        event = create_test_event(
            base["asset"]["id"], tech_headers, "INSULATION_RESISTANCE",
            value_primary=2000, ambient_temp_c=40, requires_outage=True,
            outage_window_id=window["id"], measured_at="2026-07-26T00:00:00Z",
        )
        # The linked window is APPROVED, not CLEARED.
        resp = api_client.submit_test_event(event["id"], tech_headers)
        validate_error(resp, ApiErrorId.ERR_OUTAGE_NOT_CLEARED, 409)


class TestDecommissionedAssetGuard:
    def test_new_test_event_on_decommissioned_asset_rejected(self):
        """PRD §3.11: "Once an asset is `DECOMMISSIONED`, three creation paths
        are closed against it: recording a test event, requesting an outage
        window, and drafting a relay setting — each is rejected with
        `ERR_ASSET_DECOMMISSIONED` (HTTP 422)."
        PRD §3.4: "Creating a test against a `DECOMMISSIONED` asset is rejected
        with `ERR_ASSET_DECOMMISSIONED` (HTTP 422)."

        Design: Corner/validations/decommissioned_asset_blocks_new_test_rejected
        """
        base = setup_asset("POWER_TRANSFORMER")
        decommissioned = validate_success(
            api_client.decommission_asset(base["asset"]["id"], OPS)
        )
        assert decommissioned["status"] == "DECOMMISSIONED"
        _, tech_headers = create_certified_technician("NETA_LEVEL_2")
        resp = api_client.create_test_event(
            {
                "asset_id": base["asset"]["id"],
                "test_type": "OIL_MOISTURE",
                "value_primary": 10,
                "measured_at": "2026-07-27T00:00:00Z",
            },
            tech_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ASSET_DECOMMISSIONED, 422)


class TestSpareSelectorPool:
    def test_selector_empty_pool_rejected(self):
        """PRD §3.7: "The eligible pool is every unit that is `AVAILABLE`,
        whose `unit_type` matches the request, whose `voltage_class_kv` exactly
        equals `required_voltage_kv`, whose `rating_mva` is at least the
        required capacity (for `MOBILE_SUBSTATION` requests the unit's rating
        is derated by a factor of 0.9 before this comparison — a mobile unit
        must have `rating_mva` at least 0.9 times `required_mva`; for
        `SPARE_TRANSFORMER` the factor is 1.0), and which has no `ACTIVE`
        reservation overlapping the requested half-open interval."
        PRD §3.7: "If the eligible pool is empty the request is rejected with
        `ERR_NO_COMPATIBLE_SPARE` (HTTP 422)."

        Design: Corner/validations/selector_empty_pool_rejected
        """
        create_spare_unit(
            unit_type="SPARE_TRANSFORMER", rating_mva=40, voltage_class_kv=115,
            impedance_pct=6.5, home_location="Yard-Y",
        )
        resp = api_client.create_spare_reservation(
            {
                "unit_type": "MOBILE_SUBSTATION",
                "required_mva": 20,
                "required_voltage_kv": 115,
                "start_ts": "2026-11-05T08:00:00Z",
                "end_ts": "2026-11-05T16:00:00Z",
            },
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_NO_COMPATIBLE_SPARE, 422)

    def test_explicit_unit_type_mismatch_rejected(self):
        """PRD §3.7: "When `spare_unit_id` is supplied explicitly, it must
        resolve and its unit's `unit_type` must match the requested
        `unit_type` — a mismatch is `ERR_VALIDATION` (HTTP 400)".

        Design: Corner/validations/explicit_unit_type_mismatch_rejected
        """
        unit = create_spare_unit(
            unit_type="SPARE_TRANSFORMER", rating_mva=40, voltage_class_kv=115,
            impedance_pct=6.5, home_location="Yard-X",
        )
        resp = api_client.create_spare_reservation(
            {
                "spare_unit_id": unit["id"],
                "unit_type": "MOBILE_SUBSTATION",
                "required_mva": 20,
                "required_voltage_kv": 115,
                "start_ts": "2026-11-06T08:00:00Z",
                "end_ts": "2026-11-06T16:00:00Z",
            },
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)


class TestSpareDecommissionGuard:
    def test_decommission_with_active_reservation_blocked_until_cancelled(self):
        """PRD §3.7: "An `OperationsManager` may decommission a spare unit
        while it is `AVAILABLE` and carries no `ACTIVE` reservations;
        attempting to decommission a unit with an `ACTIVE` reservation is
        rejected with `ERR_ACTIVE_RESERVATIONS` (HTTP 409). Decommissioning
        transitions the unit `AVAILABLE → DECOMMISSIONED`."

        Precedence ambiguity: when the unit is RESERVED because of the ACTIVE
        reservation, PRD §3.7 names ERR_ACTIVE_RESERVATIONS but PRD §2.8's
        priority list places the state-machine check (ERR_STATE_TRANSITION)
        ahead of the spare decommission guard. Both error ids are faithful
        PRD readings, so accept either.

        Design: Corner/validations/decommission_with_active_reservation_rejected
        """
        unit = create_spare_unit(home_location="Yard-W")
        reservation = create_spare_reservation(
            "2026-11-10T08:00:00Z", "2026-11-10T16:00:00Z", spare_unit_id=unit["id"]
        )
        resp = api_client.decommission_spare_unit(unit["id"], OPS)
        validate_error_is_one_of(
            resp,
            [ApiErrorId.ERR_ACTIVE_RESERVATIONS, ApiErrorId.ERR_STATE_TRANSITION],
        )
        assert resp.status_code == 409
        validate_success(api_client.cancel_spare_reservation(reservation["id"], COORD))
        decommissioned = validate_success(api_client.decommission_spare_unit(unit["id"], OPS))
        assert decommissioned["status"] == "DECOMMISSIONED"
