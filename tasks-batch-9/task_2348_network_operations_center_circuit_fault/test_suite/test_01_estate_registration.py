"""Registering the monitored estate: carriers, circuits and topology hops.

Everything else in the service hangs off these rows, so the contract defaults a
carrier is born with, the derived posture a circuit starts in, and the shape of
the path-segment junction are all pinned here before any alarm is ingested.
"""

from test_helpers import (
    ADMIN_HEADERS,
    CAPACITY_PLANNER_HEADERS,
    CLOCK_EPOCH,
    DEFAULT_CREDIT_PCT_CAP,
    DEFAULT_CREDIT_PCT_PER_BREACH_HOUR,
    DEFAULT_ESCALATION_TIER_COUNT,
    DEFAULT_MIN_CLAIM_AMOUNT_CENTS,
    DEFAULT_SLA_RESTORE_MINUTES_CRITICAL,
    DEFAULT_SLA_RESTORE_MINUTES_STANDARD,
    DEFAULT_TIER_ESCALATION_MIN_MINUTES,
    DEFAULT_WATCHLIST_EXPOSURE_THRESHOLD_CENTS,
    SHIFT_LEAD_HEADERS,
    UNKNOWN_UUID,
    ApiErrorId,
    advance_clock,
    assert_array_envelope,
    assert_carrier_ledger,
    assert_circuit_posture,
    assert_distinct_ids,
    assert_error_envelope,
    assert_instant,
    assert_object_envelope,
    assert_page,
    assert_path_posture,
    assert_request_id_shape,
    assert_versioned_record,
    carrier_payload,
    circuit_payload,
    create_carrier,
    create_circuit,
    create_device,
    create_path,
    get_success_data,
    path_segment_payload,
    read_circuit,
    read_path,
    read_segment,
    stamped,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCarrierRegistration:
    """A carrier is the contract, so its omitted parameters must be defaulted."""

    def test_carrier_registration_applies_every_contract_default(self, api):
        """A carrier created from name and code alone carries all eight defaults.

        PRD 3.1: "`escalation_tier_count` states how many carrier escalation tiers the contract offers and defaults to 3, with 1 as the floor and 3 as the ceiling."
        PRD 3.1: "`sla_restore_minutes_critical` defaults to 240 minutes — four hours — and is the restoration target that applies whenever the driving incident was classified `SEV1` or `SEV2`; `sla_restore_minutes_standard` defaults to 480 minutes and applies to `SEV3` and `SEV4`."
        PRD 3.1: "A freshly created carrier starts with `open_credit_exposure_cents` at 0, `committed_upgrade_mbps` at 0, `chronic_circuit_count` at 0 and `watchlist_state` `ACTIVE`; the alternative posture, `WATCHLIST`, is only ever reached by the derivations in Sections 3.6 and 3.8."

        Design: Corner/entities/corner_carrier_create_applies_every_sla_default
        """
        advance_clock(api, CLOCK_EPOCH)

        response = api.create_carrier(
            carrier_payload(name="Plainfield Telecom", carrier_code="PFT"),
            ADMIN_HEADERS,
        )
        carrier = validate_success(response, 201)["data"]

        assert carrier["name"] == "Plainfield Telecom", "the supplied name is stored"
        assert carrier["carrier_code"] == "PFT", "the supplied code is stored"
        assert carrier["escalation_tier_count"] == DEFAULT_ESCALATION_TIER_COUNT, (
            f"escalation_tier_count should default to {DEFAULT_ESCALATION_TIER_COUNT}, "
            f"got {carrier['escalation_tier_count']}"
        )
        assert (
            carrier["sla_restore_minutes_critical"]
            == DEFAULT_SLA_RESTORE_MINUTES_CRITICAL
        ), "the critical restoration target should default to 240 minutes"
        assert (
            carrier["sla_restore_minutes_standard"]
            == DEFAULT_SLA_RESTORE_MINUTES_STANDARD
        ), "the standard restoration target should default to 480 minutes"
        assert carrier["credit_pct_per_breach_hour"] == DEFAULT_CREDIT_PCT_PER_BREACH_HOUR, (
            "credit_pct_per_breach_hour should default to 5.0"
        )
        assert carrier["credit_pct_cap"] == DEFAULT_CREDIT_PCT_CAP, (
            "credit_pct_cap should default to 50.0"
        )
        assert carrier["min_claim_amount_cents"] == DEFAULT_MIN_CLAIM_AMOUNT_CENTS, (
            "min_claim_amount_cents should default to 5000 cents"
        )
        assert (
            carrier["tier_escalation_min_minutes"]
            == DEFAULT_TIER_ESCALATION_MIN_MINUTES
        ), "tier_escalation_min_minutes should default to 60 minutes"
        assert (
            carrier["watchlist_exposure_threshold_cents"]
            == DEFAULT_WATCHLIST_EXPOSURE_THRESHOLD_CENTS
        ), "watchlist_exposure_threshold_cents should default to 100000 cents"

        assert_carrier_ledger(
            carrier,
            exposure_cents=0,
            committed_mbps=0,
            watchlist_state="ACTIVE",
            chronic_circuit_count=0,
        )
        assert_versioned_record(carrier, expected_version=1, label="carrier")
        assert_instant(
            carrier["created_at"],
            stamped("2026-08-01", "00:00"),
            "carrier.created_at",
        )

    def test_reusing_a_carrier_code_is_refused(self, api):
        """A second carrier may not take a code an existing carrier already holds.

        PRD 3.1: "A `PlatformAdmin` registers one by supplying its legal `name` and a short operator code, `carrier_code`, which must be between 2 and 12 characters and is compared case-sensitively and exactly — `ATT` and `att` are two different codes, and reusing an existing code is refused with `ERR_CARRIER_CODE_DUPLICATE`."

        Design: Corner/validations/corner_duplicate_carrier_code_rejected
        """
        advance_clock(api, "2026-08-27T00:00:00Z")
        first = create_carrier(api, name="Plainfield Telecom", carrier_code="PFT")

        response = api.create_carrier(
            carrier_payload(name="Plainfield Telecom Holdings", carrier_code="PFT"),
            ADMIN_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_CARRIER_CODE_DUPLICATE)

        unchanged = get_success_data(api.get_carrier(first["id"], ADMIN_HEADERS))
        assert unchanged["name"] == "Plainfield Telecom", (
            "the refused create must not rename the carrier that holds the code"
        )
        assert_versioned_record(unchanged, expected_version=1, label="carrier")


class TestCircuitRegistration:
    """Circuit rows are mostly derived, so their birth values are a contract."""

    def test_circuit_registration_defaults_to_unmonitored_and_normal(self, api):
        """A circuit created without `monitoring_state` starts unmonitored and healthy.

        PRD 3.1: "`monitoring_state` may be supplied and defaults to `UNMONITORED`; the only other value accepted on input is `MONITORED`."
        PRD 3.1: "Every other circuit attribute is derived and starts at a known value: `operational_state` `UP`, `chronic_state` `NORMAL`, `capacity_state` `NORMAL`, `consecutive_high_readings` 0, `spof_flag` false, `fault_count_period` 0, and `last_incident_at` null until the circuit's first incident stamps it with that incident's detection instant."

        Design: Corner/entities/corner_circuit_create_defaults_unmonitored_and_normal
        """
        advance_clock(api, CLOCK_EPOCH)
        carrier = create_carrier(api)

        response = api.create_circuit(
            circuit_payload(
                carrier["id"],
                carrier_circuit_identifier="PFT-CKT-9001",
                site_a_code="CHI01",
                site_z_code="MSP01",
                bandwidth_mbps=500,
                mrc_cents=275000,
                monitoring_state=None,
            ),
            ADMIN_HEADERS,
        )
        circuit = validate_success(response, 201)["data"]

        assert_circuit_posture(
            circuit,
            monitoring_state="UNMONITORED",
            operational_state="UP",
            chronic_state="NORMAL",
            capacity_state="NORMAL",
            consecutive_high_readings=0,
            spof_flag=False,
            fault_count_period=0,
            bandwidth_mbps=500,
        )
        assert circuit["last_incident_at"] is None, (
            "a circuit that has never had an incident carries a null last_incident_at"
        )
        assert circuit["mrc_cents"] == 275000, "the monthly charge is stored as supplied"
        assert_versioned_record(circuit, expected_version=1, label="circuit")

    def test_circuit_without_a_monthly_charge_is_rejected(self, api):
        """`mrc_cents` is required, so a body omitting it is malformed.

        PRD 3.1: "A circuit is registered against a carrier by naming `carrier_id`, the carrier-assigned `carrier_circuit_identifier` quoted on trouble tickets, the two endpoint site codes `site_a_code` and `site_z_code`, the provisioned `bandwidth_mbps`, and `mrc_cents`, the monthly recurring charge in cents that forms the base of every credit computation and must be at least 1."
        PRD 2.7: "Violations are `ERR_INVALID_REQUEST` (400), and this check applies to every operation."

        Design: Corner/entities/corner_circuit_create_missing_mrc_cents_rejected
        """
        advance_clock(api, CLOCK_EPOCH)
        carrier = create_carrier(api)

        payload = circuit_payload(
            carrier["id"],
            carrier_circuit_identifier="PFT-CKT-9002",
            site_a_code="CHI01",
            site_z_code="MSP01",
            bandwidth_mbps=500,
            monitoring_state="MONITORED",
            mrc_cents=None,
        )
        assert "mrc_cents" not in payload, "the request must genuinely omit the charge"

        validate_error(
            api.create_circuit(payload, ADMIN_HEADERS),
            ApiErrorId.ERR_INVALID_REQUEST,
        )

        _, meta = validate_paginated(
            api.list_carrier_circuits(carrier["id"], ADMIN_HEADERS)
        )
        assert_page(meta, total_count=0)

    def test_reading_an_unknown_circuit_reports_circuit_not_found(self, api):
        """A path identifier that resolves to nothing is a typed 404, not an empty body.

        PRD 2.7: "A missing carrier, circuit, device, application path, path segment, alarm, incident, carrier ticket, credit claim, maintenance window, failover test, upgrade order or vendor review yields `ERR_CARRIER_NOT_FOUND`, `ERR_CIRCUIT_NOT_FOUND`, `ERR_DEVICE_NOT_FOUND`, `ERR_PATH_NOT_FOUND`, `ERR_SEGMENT_NOT_FOUND`, `ERR_ALARM_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, `ERR_TEST_NOT_FOUND`, `ERR_ORDER_NOT_FOUND` or `ERR_REVIEW_NOT_FOUND` respectively, all HTTP 404."

        Design: Corner/entities/corner_get_circuit_with_unknown_id_returns_not_found
        """
        advance_clock(api, CLOCK_EPOCH)
        create_carrier(api)

        response = api.get_circuit(UNKNOWN_UUID, ADMIN_HEADERS)
        validate_error(response, ApiErrorId.ERR_CIRCUIT_NOT_FOUND)

        data = assert_error_envelope(response)
        assert data["error_id"] == ApiErrorId.ERR_CIRCUIT_NOT_FOUND, (
            "the failure names the circuit it could not resolve"
        )
        assert_request_id_shape(response.json()["meta"])

    def test_carrier_circuit_listing_pages_and_filters(self, api):
        """Three circuits read two at a time report a stable total and a filterable set.

        PRD 2.3: "The four pagination fields `limit`, `offset`, `total_count` and `has_more` are reported in the `meta` object of every list response: `total_count` is the number of rows matching the filters before the page window is applied, and `has_more` is true when rows remain beyond the current window."
        PRD 3.1: "A carrier's circuits may be narrowed by `monitoring_state`, `operational_state`, `chronic_state` and `capacity_state`, so a shift lead can ask for every monitored circuit currently `DOWN`, or every circuit whose `capacity_state` is `UPGRADE_REQUIRED`."

        Design: Corner/entities/corner_carrier_circuits_listing_paginates_with_total_count
        """
        advance_clock(api, CLOCK_EPOCH)
        carrier = create_carrier(api)
        create_circuit(
            api,
            carrier["id"],
            carrier_circuit_identifier="PFT-CKT-9001",
            site_z_code="MSP01",
            monitoring_state="MONITORED",
        )
        create_circuit(
            api,
            carrier["id"],
            carrier_circuit_identifier="PFT-CKT-9002",
            site_z_code="DET01",
            monitoring_state="MONITORED",
        )
        create_circuit(
            api,
            carrier["id"],
            carrier_circuit_identifier="PFT-CKT-9003",
            site_z_code="STL01",
            bandwidth_mbps=100,
            mrc_cents=90000,
            monitoring_state=None,
        )

        first_response = api.list_carrier_circuits(
            carrier["id"], CAPACITY_PLANNER_HEADERS, params={"limit": 2, "offset": 0}
        )
        first_page, first_meta = validate_paginated(first_response)
        assert_array_envelope(first_response)
        assert len(first_page) == 2, f"the first page holds two rows, got {len(first_page)}"
        assert_page(first_meta, total_count=3, has_more=True, limit=2, offset=0)

        second_response = api.list_carrier_circuits(
            carrier["id"], CAPACITY_PLANNER_HEADERS, params={"limit": 2, "offset": 2}
        )
        second_page, second_meta = validate_paginated(second_response)
        assert_array_envelope(second_response)
        assert len(second_page) == 1, (
            f"the second page holds the remaining row, got {len(second_page)}"
        )
        assert_page(second_meta, total_count=3, has_more=False, limit=2, offset=2)
        assert_distinct_ids(first_page + second_page)

        filtered_response = api.list_carrier_circuits(
            carrier["id"], CAPACITY_PLANNER_HEADERS, params={"monitoring_state": "MONITORED"}
        )
        filtered, filtered_meta = validate_paginated(filtered_response)
        assert_array_envelope(filtered_response)
        assert_page(filtered_meta, total_count=2)
        for row in filtered:
            assert row["monitoring_state"] == "MONITORED", (
                f"the filter must only return monitored circuits, got {row['monitoring_state']}"
            )


class TestPathTopologyHops:
    """A hop is the junction row that binds an application path to the estate."""

    def test_hop_naming_an_unknown_circuit_is_a_not_found(self, api):
        """A body reference that resolves to nothing is a 404, not a shape complaint.

        PRD 2.8: "The same discipline applies to references supplied in a request body, and a body reference that resolves to nothing is a 404 rather than a 422: the client named a row that is not there."

        Design: Corner/entities/corner_path_segment_with_unknown_circuit_id_rejected
        """
        advance_clock(api, CLOCK_EPOCH)
        create_carrier(api)
        path = create_path(
            api,
            name="Branch VPN Path",
            service_tier="BRONZE",
            protection_scheme="UNPROTECTED",
        )

        validate_error(
            api.create_path_segment(
                path_segment_payload(path["id"], circuit_id=UNKNOWN_UUID),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_CIRCUIT_NOT_FOUND,
        )

        unchanged = read_path(api, path["id"])
        assert_path_posture(unchanged, posture="PROTECTED", active_leg_count=0)

    def test_hop_must_name_exactly_one_target(self, api):
        """Both targets or neither is refused; a device-only hop is accepted.

        PRD 3.2: "Each hop names its `application_path_id`, the `leg_group` it belongs to (`LEG_A` or `LEG_B`), its `sequence_index` within that leg, which must be at least 1, and exactly one target: either `circuit_id` or `device_id`."
        PRD 3.2: "Supplying both, or neither, is refused with `ERR_SEGMENT_TARGET_INVALID`."

        Design: Corner/validations/corner_path_segment_target_requires_exactly_one_target
        """
        advance_clock(api, "2026-08-25T00:00:00Z")
        carrier = create_carrier(api)
        circuit = create_circuit(
            api,
            carrier["id"],
            carrier_circuit_identifier="PFT-CKT-9001",
            monitoring_state="MONITORED",
        )
        device = create_device(
            api,
            hostname="chi01-rtr-1",
            site_code="CHI01",
            device_role="EDGE",
            primary_uplink_circuit_id=circuit["id"],
            monitoring_state="MONITORED",
        )
        path = create_path(
            api,
            name="Branch VPN Path",
            service_tier="BRONZE",
            protection_scheme="UNPROTECTED",
        )

        validate_error(
            api.create_path_segment(
                path_segment_payload(
                    path["id"], circuit_id=circuit["id"], device_id=device["id"]
                ),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_SEGMENT_TARGET_INVALID,
        )
        validate_error(
            api.create_path_segment(
                path_segment_payload(path["id"]),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_SEGMENT_TARGET_INVALID,
        )

        accepted = validate_success(
            api.create_path_segment(
                path_segment_payload(path["id"], device_id=device["id"]),
                ADMIN_HEADERS,
            ),
            201,
        )["data"]
        assert accepted["circuit_id"] is None, (
            "a device-targeted hop leaves circuit_id null"
        )
        assert accepted["device_id"] == device["id"], "the device target is recorded"
        assert accepted["segment_state"] == "ACTIVE", "every hop is created ACTIVE"

        assert_path_posture(
            read_path(api, path["id"]),
            active_leg_count=1,
            monitored_segment_count=1,
        )

    def test_one_circuit_may_be_a_hop_of_two_paths(self, api):
        """The junction is many-to-many and each parent path recounts on its own.

        PRD 3.2: "`monitored_segment_count` is the number of `ACTIVE` hops whose target has `monitoring_state` `MONITORED`, counted per hop rather than per leg."
        PRD 3.2: "Hops may be listed and narrowed by `application_path_id`, `circuit_id`, `device_id`, `leg_group` and `segment_state`."

        Design: Corner/entities/corner_path_segment_junction_links_path_to_circuit_graph
        """
        advance_clock(api, CLOCK_EPOCH)
        carrier = create_carrier(api)
        circuit = create_circuit(
            api,
            carrier["id"],
            carrier_circuit_identifier="PFT-CKT-9001",
            monitoring_state="MONITORED",
        )
        voice = create_path(
            api, name="Voice", service_tier="GOLD", protection_scheme="UNPROTECTED"
        )
        guest = create_path(
            api, name="Guest", service_tier="BRONZE", protection_scheme="UNPROTECTED"
        )

        voice_hop = validate_success(
            api.create_path_segment(
                path_segment_payload(voice["id"], circuit_id=circuit["id"]),
                ADMIN_HEADERS,
            ),
            201,
        )["data"]
        guest_hop = validate_success(
            api.create_path_segment(
                path_segment_payload(guest["id"], circuit_id=circuit["id"]),
                ADMIN_HEADERS,
            ),
            201,
        )["data"]

        for label, hop in (("voice", voice_hop), ("guest", guest_hop)):
            assert hop["segment_state"] == "ACTIVE", f"the {label} hop is created ACTIVE"
            assert hop["device_id"] is None, (
                f"the {label} hop targets a circuit, so device_id stays null"
            )

        listed_response = api.list_path_segments(
            SHIFT_LEAD_HEADERS, params={"circuit_id": circuit["id"]}
        )
        listed, meta = validate_paginated(listed_response)
        assert_page(meta, total_count=2)
        parents = {row["application_path_id"] for row in listed}
        assert parents == {voice["id"], guest["id"]}, (
            f"the circuit's hops span both application paths, got {parents}"
        )

        for path in (voice, guest):
            assert_path_posture(
                read_path(api, path["id"]),
                posture="PROTECTED",
                active_leg_count=1,
                healthy_leg_count=1,
                monitored_segment_count=1,
            )

        assert_object_envelope(api.get_path_segment(voice_hop["id"], SHIFT_LEAD_HEADERS))
        assert read_segment(api, guest_hop["id"])["segment_state"] == "ACTIVE", (
            "a hop remains readable on its own identifier"
        )
        assert read_circuit(api, circuit["id"])["spof_flag"] is False, (
            "a fully healthy path makes no circuit a single point of failure"
        )
