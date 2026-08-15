"""Response envelope, pagination, filters, role admission, ownership, and
the existence (404) surface."""
from test_helpers import (
    ADMIN,
    FEED,
    FINANCE,
    GATEWAY,
    OFFICER,
    SPM,
    ApiErrorId,
    create_active_carrier,
    create_carrier,
    create_config,
    list_vehicles_for,
    make_carrier_manager_headers,
    make_compliance_officer_headers,
    post_event,
    post_snapshot,
    set_clock,
    setup_bypass_ready,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

GHOST = "11111111-2222-4333-8444-555555555555"
GHOST_2 = "11111111-2222-4333-8444-555555555556"


class TestErrorEnvelope:
    def test_error_envelope_shape(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" with `response_type` "error" and `data`
        carrying `error_id` and `message`; "The `meta` object for error
        responses contains only `api_request_id` and
        `api_request_timestamp`."

        Design: Corner/errors/error_envelope_shape_on_error
        """
        resp = api.create_carrier({"legal_name": "No Dot"}, ADMIN)
        assert resp.status_code == 400
        body = resp.json()
        assert body["response_type"] == "error"
        assert set(body["meta"].keys()) == {"api_request_id",
                                            "api_request_timestamp"}
        data = body["data"]
        assert data["error_id"] == "ERR_INVALID_REQUEST"
        assert isinstance(data["message"], str) and data["message"].strip()


class TestListBehavior:
    def test_pagination_limit_offset_and_envelope(self, api):
        """PRD §2.3: "`limit` caps the page size: it defaults to 10, accepts
        a minimum of 1, and accepts a maximum of 100. `offset` skips that
        many records from the start of the result set and defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries `limit`,
        `offset`, `total_count`, and `has_more` alongside the request
        identifiers."

        Design: Corner/endpoints/pagination_limit_offset_and_envelope
        """
        fx = setup_bypass_ready()
        set_clock("2026-08-05T12:00:00Z")
        for hh in ("10:00:00", "10:30:00", "11:00:00"):
            post_event(fx["vehicle"]["id"], fx["station"]["id"],
                       f"2026-08-05T{hh}Z", measured_weight_lbs=90000,
                       credentials_presented=["IFTA", "IRP", "UCR"])

        page1, meta1 = validate_paginated(api.list_events(
            FINANCE, params={"carrier_id": fx["carrier"]["id"],
                             "limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2 and meta1["offset"] == 0

        page2, meta2 = validate_paginated(api.list_events(
            FINANCE, params={"carrier_id": fx["carrier"]["id"],
                             "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        default_body = api.list_events(
            FINANCE, params={"carrier_id": fx["carrier"]["id"]}).json()
        assert default_body["response_type"] == "array"
        assert default_body["meta"]["limit"] == 10
        assert default_body["meta"]["offset"] == 0
        assert isinstance(default_body["meta"]["api_request_id"], str)
        assert default_body["meta"]["api_request_id"]

    def test_filter_events_by_decision_and_carrier(self, api):
        """PRD §2.3: "Collections support exact-match filtering through query
        parameters named after the underlying fields: ... bypass events by
        `carrier_id`, `vehicle_id`, `station_id`, and `decision` ..."

        Design: Corner/endpoints/filter_by_decision_and_carrier
        """
        fx = setup_bypass_ready()
        set_clock("2026-08-05T12:00:00Z")
        granted = post_event(fx["vehicle"]["id"], fx["station"]["id"],
                             "2026-08-05T10:00:00Z", measured_weight_lbs=80000,
                             credentials_presented=["IFTA", "IRP", "UCR"])
        pulled = post_event(fx["vehicle"]["id"], fx["station"]["id"],
                            "2026-08-05T10:30:00Z", measured_weight_lbs=90000,
                            credentials_presented=["IFTA", "IRP", "UCR"])
        assert granted["decision"] == "BYPASS_GRANTED"
        assert pulled["decision"] == "PULL_IN"

        pull_ins, meta_p = validate_paginated(api.list_events(
            FINANCE, params={"carrier_id": fx["carrier"]["id"],
                             "decision": "PULL_IN"}))
        assert [e["id"] for e in pull_ins] == [pulled["id"]]
        assert meta_p["total_count"] == 1

        grants, meta_g = validate_paginated(api.list_events(
            FINANCE, params={"carrier_id": fx["carrier"]["id"],
                             "decision": "BYPASS_GRANTED"}))
        assert [e["id"] for e in grants] == [granted["id"]]
        assert meta_g["total_count"] == 1


class TestRoleAdmission:
    def test_forbidden_role_matrix(self, api):
        """PRD §2.1: "A request whose role is not admitted by the target
        endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)".
        PRD §2.10: rung "2. **Role admission.**" is screened before rung
        "4. **Existence.**"

        Design: Corner/rbac/forbidden_role_matrix_returns_403
        """
        carrier = create_carrier(dot_number="100001", legal_name="Acme Hauling")
        cm = make_carrier_manager_headers(carrier["id"])

        r1 = api.create_carrier({"dot_number": "100002", "legal_name": "Wrong"}, cm)
        validate_error(r1, ApiErrorId.ERR_FORBIDDEN_ROLE)

        r2 = api.create_config({"state_code": "NV"}, OFFICER)
        validate_error(r2, ApiErrorId.ERR_FORBIDDEN_ROLE)

        r3 = api.create_snapshot(
            {"carrier_id": carrier["id"], "iss_score": 30,
             "safety_rating": "SATISFACTORY", "source": "FMCSA_FEED",
             "effective_date": "2026-08-01",
             "expected_carrier_version": carrier["version"]},
            ADMIN)
        validate_error(r3, ApiErrorId.ERR_FORBIDDEN_ROLE)

        r4 = api.create_event(
            {"vehicle_id": GHOST, "station_id": GHOST_2,
             "approach_at": "2026-08-01T00:00:00Z"},
            cm)
        validate_error(r4, ApiErrorId.ERR_FORBIDDEN_ROLE)

        r5 = api.record_payment(GHOST, 100, OFFICER)
        validate_error(r5, ApiErrorId.ERR_FORBIDDEN_ROLE)

        r6 = api.set_clock("2026-08-02T00:00:00Z", FINANCE)
        validate_error(r6, ApiErrorId.ERR_FORBIDDEN_ROLE)

        r7 = api.adjudicate_dispute(GHOST, {"outcome": "UPHELD"}, cm)
        validate_error(r7, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_carrier_transition_role_split_by_target_state(self, api):
        """PRD §2.1: "the carrier lifecycle transition endpoint applies this
        rule per target state, so a `PlatformAdmin` asking for `ACTIVE`, or a
        `ComplianceOfficer` asking for `TERMINATED`, is refused at the role
        gate rather than at the state machine."
        PRD §3.1: "Termination is the exclusive, terminal act of a
        `PlatformAdmin`, available from `ENROLLED`, `ACTIVE`, or `SUSPENDED`"

        Design: Corner/rbac/carrier_transition_role_split_returns_403
        """
        set_clock()
        carrier = create_carrier(dot_number="100001", legal_name="Acme Hauling")
        post_snapshot(carrier["id"], iss_score=30,
                      expected_carrier_version=carrier["version"])

        x1 = api.transition_carrier(carrier["id"], "ACTIVE", ADMIN)
        validate_error(x1, ApiErrorId.ERR_FORBIDDEN_ROLE)

        x2 = api.transition_carrier(carrier["id"], "TERMINATED", OFFICER)
        validate_error(x2, ApiErrorId.ERR_FORBIDDEN_ROLE)

        x3 = api.transition_carrier(carrier["id"], "TERMINATED", ADMIN)
        data = validate_success(x3)
        assert data["status"] == "TERMINATED"


class TestOwnership:
    def test_ownership_mismatch_rejected(self, api):
        """PRD §2.1: "When `X-User-Role` is `CarrierManager`, `X-User-ID` is
        the `id` of the acting `Carrier`; ownership checks on any resource
        that references a `Carrier` compare the resource's carrier foreign
        key to `X-User-ID`."
        PRD §2.1: "A resolved reference whose carrier differs from
        `X-User-ID` is rejected with `ERR_CARRIER_OWNERSHIP_MISMATCH`
        (HTTP 403)."

        Design: Corner/validations/ownership_mismatch_returns_403
        """
        set_clock()
        carrier_a = create_active_carrier(dot_number="100001", legal_name="Carrier A")
        carrier_b = create_active_carrier(dot_number="100002", legal_name="Carrier B")
        cm_b = make_carrier_manager_headers(carrier_b["id"])
        resp = api.create_vehicle(
            {"carrier_id": carrier_a["id"], "vin": "VIN-0001",
             "plate_number": "P-1", "plate_state": "CA", "home_state_code": "CA",
             "gvwr_lbs": 80000},
            cm_b)
        validate_error(resp, ApiErrorId.ERR_CARRIER_OWNERSHIP_MISMATCH)
        assert list_vehicles_for(carrier_a["id"]) == [], \
            "no vehicle created for carrier A"


class TestExistenceSweep:
    def test_not_found_sweep_returns_resource_specific_404(self, api):
        """PRD §2.10: "Path- and body-referenced resources are verified left
        to right — carrier, state config, station, vehicle, credential,
        bypass event, dispute, override, subscription, invoice — and the
        first missing reference yields its `ERR_CARRIER_NOT_FOUND`,
        `ERR_STATE_PROGRAM_CONFIG_NOT_FOUND`, `ERR_STATION_NOT_FOUND`,
        `ERR_VEHICLE_NOT_FOUND`, `ERR_CREDENTIAL_NOT_FOUND`,
        `ERR_BYPASS_EVENT_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`,
        `ERR_OVERRIDE_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, or
        `ERR_INVOICE_NOT_FOUND`."
        PRD §2.1: "When the referenced resource does not exist, ownership is
        unresolvable and the existence check described in §2.10 produces the
        404 response instead."

        Design: Corner/errors/not_found_sweep_returns_404
        """
        set_clock()
        carrier = create_carrier(dot_number="100001", legal_name="Acme Hauling")
        config = create_config(state_code="CA")
        cm = make_carrier_manager_headers(carrier["id"])
        cm_ghost = make_carrier_manager_headers(GHOST)
        officer = make_compliance_officer_headers("officer-a")

        # Carrier references (path and body).
        validate_error(api.get_carrier(GHOST, ADMIN),
                       ApiErrorId.ERR_CARRIER_NOT_FOUND)
        validate_error(api.transition_carrier(GHOST, "ACTIVE", OFFICER),
                       ApiErrorId.ERR_CARRIER_NOT_FOUND)
        validate_error(
            api.get_roi_report(GHOST, FINANCE,
                               params={"period_year": 2026, "period_month": 8}),
            ApiErrorId.ERR_CARRIER_NOT_FOUND)
        validate_error(api.get_invoice_preview(GHOST, FINANCE),
                       ApiErrorId.ERR_CARRIER_NOT_FOUND)
        validate_error(api.close_billing_period(GHOST, 2026, 8, FINANCE),
                       ApiErrorId.ERR_CARRIER_NOT_FOUND)

        # Remaining single-resource path ids.
        validate_error(
            api.patch_config(GHOST,
                             {"iss_refusal_threshold": 80,
                              "expected_state_program_config_version":
                                  config["version"]},
                             SPM),
            ApiErrorId.ERR_STATE_PROGRAM_CONFIG_NOT_FOUND)
        validate_error(api.patch_station(GHOST, {"operational_status": "CLOSED_TEMP"},
                                         SPM),
                       ApiErrorId.ERR_STATION_NOT_FOUND)
        validate_error(api.patch_vehicle(GHOST, {"service_status": "OUT_OF_SERVICE"},
                                         cm),
                       ApiErrorId.ERR_VEHICLE_NOT_FOUND)
        validate_error(api.transition_credential(GHOST, "ACTIVE", cm),
                       ApiErrorId.ERR_CREDENTIAL_NOT_FOUND)
        validate_error(api.adjudicate_dispute(GHOST, {"outcome": "UPHELD"}, officer),
                       ApiErrorId.ERR_DISPUTE_NOT_FOUND)
        validate_error(api.appeal_dispute(GHOST, cm),
                       ApiErrorId.ERR_DISPUTE_NOT_FOUND)
        validate_error(api.decide_override(GHOST, "APPROVE", officer),
                       ApiErrorId.ERR_OVERRIDE_NOT_FOUND)
        validate_error(api.cancel_subscription(GHOST, cm),
                       ApiErrorId.ERR_SUBSCRIPTION_NOT_FOUND)
        validate_error(api.record_payment(GHOST, 100, FINANCE),
                       ApiErrorId.ERR_INVOICE_NOT_FOUND)

        # Body foreign keys. For the event POST both references are missing;
        # the PRD's rung-4 enumeration does not pin whether vehicle or
        # station is verified first on this endpoint, so either resource's
        # 404 satisfies the rule.
        ghost_event = api.create_event(
            {"vehicle_id": GHOST, "station_id": GHOST_2,
             "approach_at": "2026-08-01T00:00:00Z"},
            GATEWAY)
        assert ghost_event.status_code == 404
        validate_error_is_one_of(ghost_event, [
            ApiErrorId.ERR_VEHICLE_NOT_FOUND,
            ApiErrorId.ERR_STATION_NOT_FOUND])

        validate_error(
            api.create_dispute({"bypass_event_id": GHOST, "reason": "ghost event",
                                "claimed_credit_cents": 100}, cm),
            ApiErrorId.ERR_BYPASS_EVENT_NOT_FOUND)
        validate_error(
            api.create_subscription(
                {"carrier_id": GHOST, "vehicle_id": GHOST_2,
                 "service_start_date": "2026-08-01",
                 "service_end_date": "2026-12-31"}, cm_ghost),
            ApiErrorId.ERR_CARRIER_NOT_FOUND)
        validate_error(
            api.create_inspection(
                {"carrier_id": GHOST, "vehicle_id": GHOST_2,
                 "inspection_level": "LEVEL_1",
                 "inspected_at": "2026-08-01T09:00:00Z", "violations_found": 0},
                FEED),
            ApiErrorId.ERR_CARRIER_NOT_FOUND)
        validate_error(
            api.create_snapshot(
                {"carrier_id": GHOST, "iss_score": 30,
                 "safety_rating": "SATISFACTORY", "source": "FMCSA_FEED",
                 "effective_date": "2026-08-01",
                 "expected_carrier_version": carrier["version"]},
                FEED),
            ApiErrorId.ERR_CARRIER_NOT_FOUND)
        validate_error(
            api.create_override(
                {"carrier_id": GHOST, "reason": "ghost carrier",
                 "start_date": "2026-08-01", "end_date": "2026-09-01",
                 "expected_carrier_version": carrier["version"]}, cm_ghost),
            ApiErrorId.ERR_CARRIER_NOT_FOUND)
        validate_error(
            api.create_station(
                {"state_program_config_id": GHOST, "station_code": "GHOST-1",
                 "station_type": "FIXED_SCALE", "supported_channel": "BOTH"}, SPM),
            ApiErrorId.ERR_STATE_PROGRAM_CONFIG_NOT_FOUND)
        validate_error(
            api.create_credential(
                {"vehicle_id": GHOST, "device_type": "TRANSPONDER",
                 "device_serial": "SN-GHOST"}, cm),
            ApiErrorId.ERR_VEHICLE_NOT_FOUND)
        validate_error(
            api.create_vehicle(
                {"carrier_id": GHOST, "vin": "VIN-GHOST", "plate_number": "P-G",
                 "plate_state": "CA", "home_state_code": "CA", "gvwr_lbs": 80000},
                cm_ghost),
            ApiErrorId.ERR_CARRIER_NOT_FOUND)
