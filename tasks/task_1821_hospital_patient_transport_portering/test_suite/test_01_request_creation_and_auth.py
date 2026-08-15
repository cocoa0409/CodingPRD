"""Transport-request creation, defaults, reads, queue-entry guards, and auth."""
from test_helpers import (
    DISP,
    ApiErrorId,
    add_transporter,
    assert_transporter,
    assert_transport_request,
    build_user_headers,
    close_request_ok,
    create_location,
    create_request_payload,
    create_transport_request,
    make_clinician_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRequestCreationDefaults:
    def test_request_creation_with_defaults(self, api):
        """PRD §3.3: "A fresh request lands in `QUEUED` with `sla_posture`
        `ON_TRACK`; the counters `escalation_count`, `decline_count`,
        `release_count`, and `offer_seq_count` all start at zero;
        `excluded_transporter_ids` starts empty; `assigned_transporter_id`,
        `assigned_equipment_id`, and `duplicate_of_id` start null; the computed
        fields `committed_eta_minutes` and `response_minutes` remain null until
        dispatch and arrival respectively; and the lifecycle timestamps
        `at_pickup_at`, `picked_up_at`, `completed_at`, and `closed_at` are null
        until their events occur."
        PRD §3.3: "The server stamps `requested_by` from the caller's `X-User-ID`."
        PRD §2.5: "Before any administrator action, the logical clock starts at
        exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time
        thereafter."

        Design: Corner/entities/request_creation_with_defaults
        """
        # The logical clock is never set: it must read the startup default.
        ward = create_location("W4", "Ward 4", "WARD", "Z1")
        img = create_location("IMG", "Imaging", "IMAGING", "Z2")

        payload = create_request_payload("P1", ward["id"], img["id"],
                                         "ROUTINE", "PORTER_ONLY")
        resp = api.create_request(payload, make_clinician_headers("clin-1"))
        data = validate_success(resp, 201)

        body = resp.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "api_request_id starts with req_ (PRD §2.2)")

        assert_transport_request(data)
        assert data["status"] == "QUEUED"
        assert data["sla_posture"] == "ON_TRACK"
        assert data["oxygen_required"] is False
        assert data["isolation_precaution"] == "NONE"
        assert data["escalation_count"] == 0
        assert data["decline_count"] == 0
        assert data["release_count"] == 0
        assert data["offer_seq_count"] == 0
        assert data["excluded_transporter_ids"] == []
        assert data["assigned_transporter_id"] is None
        assert data["assigned_equipment_id"] is None
        assert data["duplicate_of_id"] is None
        assert data["committed_eta_minutes"] is None
        assert data["response_minutes"] is None
        assert data["at_pickup_at"] is None
        assert data["picked_up_at"] is None
        assert data["completed_at"] is None
        assert data["closed_at"] is None
        assert data["cancel_reason"] is None
        assert data["requested_by"] == "clin-1"
        assert data["version"] == 1
        assert data["created_at"] == "2026-08-01T00:00:00.000Z", (
            "creation stamps the logical clock default with three fractional "
            "digits (PRD §2.4/§2.5)")

    def test_request_system_fields_input_ignored(self, api):
        """PRD §2.4: "The `id` is a server-minted UUID with no type prefix."
        PRD §2.5: "Before any administrator action, the logical clock starts at
        exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time
        thereafter."

        Design: Corner/entities/request_system_fields_input_ignored
        """
        ward = create_location("W4", "Ward 4", "WARD", "Z1")
        img = create_location("IMG", "Imaging", "IMAGING", "Z2")

        payload = create_request_payload(
            "P1", ward["id"], img["id"], "ROUTINE", "PORTER_ONLY",
            id="00000000-0000-4000-8000-000000000000",
            created_at="1999-01-01T00:00:00Z")
        resp = api.create_request(payload, make_clinician_headers("clin-1"))
        data = validate_success(resp, 201)

        assert data["id"] != "00000000-0000-4000-8000-000000000000", (
            "the server mints its own UUID")
        assert data["created_at"] == "2026-08-01T00:00:00.000Z", (
            "created_at comes from the logical clock, not the client payload")


class TestRequestCreationValidation:
    def test_request_missing_patient_ref_returns_400(self, api):
        """PRD §2.6: "required fields are present, enums are in range, and
        integer bounds hold (positive travel minutes, a valid adequacy window,
        shift end after shift start, and a `duplicate_of_id` present when the
        close action is SUPERSEDE), else `ERR_VALIDATION`."
        PRD §3.3: "A `RequestingClinician` opens a **Transport Request** by
        supplying the `patient_ref` (an opaque patient identifier used for
        duplicate and separation checks), the `origin_location_id` and
        `destination_location_id`, a `priority` of `ROUTINE`, `URGENT`, or
        `STAT`, and the `required_equipment` — `PORTER_ONLY`, `WHEELCHAIR`,
        `STRETCHER`, or `BARIATRIC_STRETCHER`."

        Design: Corner/entities/request_missing_patient_ref_returns_400
        """
        ward = create_location("W4", "Ward 4", "WARD", "Z1")
        img = create_location("IMG", "Imaging", "IMAGING", "Z2")

        payload = {
            "origin_location_id": ward["id"],
            "destination_location_id": img["id"],
            "priority": "ROUTINE",
            "required_equipment": "PORTER_ONLY",
        }
        resp = api.create_request(payload, make_clinician_headers("clin-1"))
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_request_invalid_priority_enum_returns_400(self, api):
        """PRD §2.6: "required fields are present, enums are in range, and
        integer bounds hold (positive travel minutes, a valid adequacy window,
        shift end after shift start, and a `duplicate_of_id` present when the
        close action is SUPERSEDE), else `ERR_VALIDATION`."
        PRD §3.3: "a `priority` of `ROUTINE`, `URGENT`, or `STAT`"

        Design: Corner/entities/request_invalid_priority_enum_returns_400
        """
        ward = create_location("W4", "Ward 4", "WARD", "Z1")
        img = create_location("IMG", "Imaging", "IMAGING", "Z2")

        payload = create_request_payload("P1", ward["id"], img["id"],
                                         "CRITICAL", "PORTER_ONLY")
        resp = api.create_request(payload, make_clinician_headers("clin-1"))
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestRequestReads:
    def test_request_get_missing_id_returns_404(self, api):
        """PRD §2.6: "path identifiers exist, validated left to right, and
        body-referenced identifiers (such as `transporter_id`,
        `duplicate_of_id`, and location or equipment foreign keys) exist, else
        `ERR_NOT_FOUND`."

        Design: Corner/entities/request_get_missing_id_returns_404
        """
        resp = api.get_request("11111111-2222-4333-8444-555555555555", DISP)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_request_list_pagination_defaults(self, api):
        """PRD §2.3: "`limit` defaults to 10, with a minimum of 1 and a maximum
        of 100; `offset` defaults to 0. Unless otherwise specified, list
        endpoints return resources sorted by `created_at` in ascending order.
        Paginated list responses carry `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/request_list_pagination_defaults
        """
        ward = create_location("W4", "Ward 4", "WARD", "Z1")
        img = create_location("IMG", "Imaging", "IMAGING", "Z2")
        set_clock("2026-08-01T00:00:00Z")
        r1 = create_transport_request("P1", ward["id"], img["id"],
                                      priority="ROUTINE")
        set_clock("2026-08-01T00:01:00Z")
        r2 = create_transport_request("P2", ward["id"], img["id"],
                                      priority="URGENT")

        page1, meta1 = validate_paginated(
            api.list_requests(DISP, params={"limit": 1, "offset": 0}))
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert page1[0]["id"] == r1["id"], "created_at ascending: oldest first"

        page2, meta2 = validate_paginated(
            api.list_requests(DISP, params={"limit": 1, "offset": 1}))
        assert len(page2) == 1
        assert page2[0]["id"] == r2["id"]
        assert meta2["has_more"] is False
        assert meta2["total_count"] == 2

    def test_request_list_filter_origin_location(self, api):
        """PRD §3.3: "the list filters by `status`, `priority`, `sla_posture`,
        `origin_location_id`, `destination_location_id`,
        `assigned_transporter_id`, `assigned_equipment_id`, and
        `duplicate_of_id`."

        Design: Corner/entities/request_list_filter_origin_location
        """
        hub = create_location("HUB", "Hub", "OTHER", "Z1")
        ward = create_location("W4", "Ward 4", "WARD", "Z1")
        img = create_location("IMG", "Imaging", "IMAGING", "Z2")
        r1 = create_transport_request("P1", ward["id"], img["id"])
        create_transport_request("P2", hub["id"], img["id"])

        data, meta = validate_paginated(
            api.list_requests(DISP, params={"origin_location_id": ward["id"]}))
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["id"] == r1["id"]

    def test_transporter_retrieval_returns_stored_fields(self, api):
        """PRD §3.2: "A supervisor registers each **Transporter** with a `name`
        and a `home_location_id`, and optionally a `certified_equipment` list
        (a subset of `WHEELCHAIR`, `STRETCHER`, and `BARIATRIC_STRETCHER`,
        defaulting to empty), an `oxygen_certified` flag (default false,
        required to escort oxygen trips), and an `isolation_certified` flag
        (default false, required for any trip under precautions). A new
        transporter starts `OFF_SHIFT` with `current_location_id` initialized
        to their home"

        Design: Corner/entities/transporter_retrieval_returns_stored_fields
        """
        hub = create_location("HUB", "Hub", "OTHER", "Z1")
        t1 = add_transporter("T One", hub["id"],
                             certified_equipment=["WHEELCHAIR"],
                             oxygen_certified=True)

        resp = api.get_transporter(t1["id"], DISP)
        data = validate_success(resp, 200)
        assert_transporter(data)
        assert data["name"] == "T One"
        assert data["certified_equipment"] == ["WHEELCHAIR"]
        assert data["oxygen_certified"] is True
        assert data["isolation_certified"] is False
        assert data["status"] == "OFF_SHIFT"
        assert data["current_location_id"] == hub["id"]


class TestAuthentication:
    def test_request_create_missing_auth_headers_returns_401(self, api):
        """PRD §2.1: "A request with missing headers or an unrecognized role is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/request_create_missing_auth_headers_returns_401
        """
        payload = {
            "patient_ref": "P1",
            "origin_location_id": "x",
            "destination_location_id": "y",
            "priority": "ROUTINE",
            "required_equipment": "PORTER_ONLY",
        }
        resp = api.create_request(payload, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_unknown_role_returns_401(self, api):
        """PRD §2.1: "The system recognizes exactly five roles:
        `RequestingClinician`, `TransportDispatcher`, `Transporter`,
        `HousekeepingStaff`, and `TransportSupervisor`. A request with missing
        headers or an unrecognized role is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/errors/unknown_role_returns_401
        """
        resp = api.list_requests(build_user_headers("wiz-1", "Wizard"))
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestQueueEntryGuards:
    def test_schedule_in_past_returns_422(self, api):
        """PRD §3.3: "A `scheduled_pickup_time` or `appointment_deadline`
        earlier than the current logical instant is rejected with
        `ERR_SCHEDULE_IN_PAST`."

        Design: Corner/validations/schedule_in_past_returns_422
        """
        set_clock("2026-08-01T00:00:00Z")
        ward = create_location("W4", "Ward 4", "WARD", "Z1")
        img = create_location("IMG", "Imaging", "IMAGING", "Z2")

        payload = create_request_payload(
            "P1", ward["id"], img["id"], "ROUTINE", "PORTER_ONLY",
            scheduled_pickup_time="2026-07-01T10:00:00Z")
        resp = api.create_request(payload, make_clinician_headers("clin-1"))
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_IN_PAST)

    def test_duplicate_active_request_returns_409(self, api):
        """PRD §3.3: "And if the same `patient_ref` already has a non-terminal
        request to the same `destination_location_id` — one in `QUEUED`,
        `ASSIGNED`, `AT_PICKUP`, or `IN_TRANSIT` — creation is rejected with
        `ERR_DUPLICATE_ACTIVE_REQUEST`."

        Design: Corner/validations/duplicate_active_request_returns_409
        """
        ward = create_location("W4", "Ward 4", "WARD", "Z1")
        img = create_location("IMG", "Imaging", "IMAGING", "Z2")
        create_transport_request("PX", ward["id"], img["id"], priority="ROUTINE")

        payload = create_request_payload("PX", ward["id"], img["id"],
                                         "URGENT", "PORTER_ONLY")
        resp = api.create_request(payload, make_clinician_headers("clin-1"))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_REQUEST)

    def test_patient_min_separation_conflict_and_exact_boundary(self, api):
        """PRD §3.3: "Two non-terminal requests for the same `patient_ref`
        whose `scheduled_pickup_time` values fall strictly less than 75
        minutes apart violate the patient minimum-separation rule and are
        rejected with `ERR_PATIENT_SCHEDULE_CONFLICT` — bookings exactly 75
        minutes apart are acceptable."

        Design: Difficulty/resource_temporal_overlap/patient_min_separation_boundary
        """
        ward = create_location("W4", "Ward 4", "WARD", "Z1")
        img = create_location("IMG", "Imaging", "IMAGING", "Z2")
        w5 = create_location("W5", "Ward 5", "WARD", "Z1")
        create_transport_request(
            "PX", ward["id"], img["id"],
            scheduled_pickup_time="2026-08-01T10:00:00Z")

        # 40 minutes apart: strictly less than 75 -> conflict.
        too_close = api.create_request(
            create_request_payload("PX", ward["id"], img["id"], "ROUTINE",
                                   "PORTER_ONLY",
                                   scheduled_pickup_time="2026-08-01T10:40:00Z"),
            make_clinician_headers("clin-1"))
        validate_error(too_close, ApiErrorId.ERR_PATIENT_SCHEDULE_CONFLICT)

        # Exactly 75 minutes apart (to a different destination): acceptable.
        ok = api.create_request(
            create_request_payload("PX", ward["id"], w5["id"], "ROUTINE",
                                   "PORTER_ONLY",
                                   scheduled_pickup_time="2026-08-01T11:15:00Z"),
            make_clinician_headers("clin-1"))
        created = validate_success(ok, 201)
        assert_transport_request(created)
        assert created["patient_ref"] == "PX"

    def test_patient_min_separation_ignores_terminal_requests(self, api):
        """PRD §3.3: "Two non-terminal requests for the same `patient_ref`
        whose `scheduled_pickup_time` values fall strictly less than 75
        minutes apart violate the patient minimum-separation rule and are
        rejected with `ERR_PATIENT_SCHEDULE_CONFLICT` — bookings exactly 75
        minutes apart are acceptable."
        PRD §3.5: "from `QUEUED`, `ASSIGNED`, or `AT_PICKUP` it proceeds — but
        a `RequestingClinician` may cancel only their own requests, meaning
        `requested_by` must equal the caller's `X-User-ID` (otherwise
        `ERR_FORBIDDEN_ROLE`), and only while the request is still `QUEUED`"

        Design: Difficulty/resource_temporal_overlap/patient_min_separation_boundary
        """
        ward = create_location("W4", "Ward 4", "WARD", "Z1")
        img = create_location("IMG", "Imaging", "IMAGING", "Z2")
        r1 = create_transport_request(
            "PX", ward["id"], img["id"],
            scheduled_pickup_time="2026-08-01T10:00:00Z")
        closed = close_request_ok(r1["id"], "CANCEL",
                                  make_clinician_headers("clin-1"),
                                  reason="ORDER_WITHDRAWN")
        assert closed["status"] == "CANCELLED"

        # The cancelled request is terminal, so a booking 40 minutes after its
        # scheduled pickup no longer conflicts.
        resp = api.create_request(
            create_request_payload("PX", ward["id"], img["id"], "ROUTINE",
                                   "PORTER_ONLY",
                                   scheduled_pickup_time="2026-08-01T10:40:00Z"),
            make_clinician_headers("clin-1"))
        created = validate_success(resp, 201)
        assert created["status"] == "QUEUED"
