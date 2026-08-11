"""Role-based access denials and list/pagination behavior (PRD §2.1, §2.3, §4)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    acknowledge_alert,
    create_device_payload,
    create_order_payload,
    create_report_payload,
    list_open_gap_events,
    make_physician_headers,
    make_technician_headers,
    raise_alert,
    read_billing_period,
    record_gap_strikes,
    register_patient,
    register_physician,
    register_technician,
    setup_alert_scenario,
    setup_monitoring_episode,
    setup_ready_billing_period,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["enrollment_coordinator_headers"]
BILLING = TEST_USERS["billing_specialist_headers"]
INVENTORY = TEST_USERS["inventory_manager_headers"]
GATEWAY = TEST_USERS["device_gateway_headers"]
TECHNICIAN = TEST_USERS["monitoring_technician_headers"]


class TestRoleDenials:
    def test_billing_specialist_cannot_register_device(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        operation — or that fails an entity-backed ownership check — is
        rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "| POST | `/v1/devices` | Register a device into inventory |
        InventoryManager |"

        Design: Corner/validations/billing_specialist_cannot_register_device_forbidden
        """
        resp = api.create_device(create_device_payload(serial_number="EV-3001"), BILLING)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_coordinator_cannot_submit_billing(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        operation — or that fails an entity-backed ownership check — is
        rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "| POST | `/v1/billing-periods/{period_id}/submit` | Submit a
        READY billing period | BillingSpecialist |"

        Design: Corner/rbac/coordinator_cannot_submit_billing_forbidden
        """
        ctx = setup_ready_billing_period(prescribed_days=10)
        assert read_billing_period(ctx["bp_id"])["status"] == "READY"
        resp = api.submit_billing_period(ctx["bp_id"], COORD)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert read_billing_period(ctx["bp_id"])["status"] == "READY"

    def test_technician_cannot_finalize_report(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        operation — or that fails an entity-backed ownership check — is
        rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "| POST | `/v1/reports/{report_id}/finalize` | Finalize a DRAFT
        or AMENDED report | Physician |"

        Design: Corner/rbac/technician_cannot_finalize_report_forbidden
        """
        ctx = setup_monitoring_episode(prescribed_days=7)
        tech = register_technician()
        dr_headers = make_physician_headers(ctx["physician"]["id"])
        report = validate_success(
            api.create_report(
                ctx["episode_id"],
                create_report_payload(report_type="INTERIM", findings_summary="draft"),
                dr_headers,
            ),
            201,
        )
        resp = api.finalize_report(report["id"], make_technician_headers(tech["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert validate_success(api.get_report(report["id"], COORD))["status"] == "DRAFT"

    def test_non_ordering_physician_cannot_cancel_order(self, api):
        """PRD §3.2: "The ordering physician — and only that physician, by the
        ownership check of §2.1 — may cancel an order while it is still `OPEN`;
        an order already `IN_SERVICE` must first run its episode to a terminal
        state, and cancelling one is rejected with `ERR_INVALID_STATE`
        (HTTP 409)."
        PRD §2.1: "A request whose role is not permitted for the target
        operation — or that fails an entity-backed ownership check — is
        rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/non_ordering_physician_cannot_cancel_order
        """
        patient = register_patient()
        owner = register_physician()
        other = register_physician()
        order = validate_success(
            api.create_order(
                create_order_payload(patient["id"], monitor_type="HOLTER", prescribed_days=7),
                make_physician_headers(owner["id"]),
            ),
            201,
        )
        resp = api.cancel_order(order["id"], make_physician_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert validate_success(api.get_order(order["id"], COORD))["status"] == "OPEN"

    def test_inventory_manager_cannot_resolve_compliance_event(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        operation — or that fails an entity-backed ownership check — is
        rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "| POST | `/v1/compliance-events/{event_id}/resolve` | Record
        non-compliance follow-up resolution | EnrollmentCoordinator |"

        Design: Corner/rbac/inventory_manager_cannot_resolve_compliance_forbidden
        """
        ctx = setup_monitoring_episode(prescribed_days=10)
        event_ids = record_gap_strikes(ctx["episode_id"], 1, resolve_last=False)
        resp = api.resolve_compliance_event(
            event_ids[0], {"resolution_action": "CONTACTED_PATIENT"}, INVENTORY
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        still_open = list_open_gap_events(ctx["episode_id"])
        assert len(still_open) == 1 and still_open[0]["status"] == "OPEN"

    def test_gateway_cannot_read_business_resources(self, api):
        """PRD §2.1: "Every role except `DeviceGateway` may call every read
        endpoint in the API. `DeviceGateway` is a data-plane identity: beyond
        its two write capabilities it may read only the transmission listing of
        an episode."
        PRD §2.1: "A request whose role is not permitted for the target
        operation — or that fails an entity-backed ownership check — is
        rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/gateway_cannot_read_business_resources_forbidden
        """
        resp = api.list_alerts(GATEWAY)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestListingsAndPagination:
    def _setup_twelve_alerts(self):
        ctx = setup_monitoring_episode(prescribed_days=10, start_clock="2026-05-01T10:00:00Z")
        for _ in range(7):
            raise_alert(ctx["episode_id"], severity="ROUTINE", arrhythmia_type="AFIB")
        for _ in range(5):
            raise_alert(ctx["episode_id"], severity="URGENT", arrhythmia_type="VTACH")
        return ctx

    def test_alerts_list_pagination_defaults_and_filter(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10, with a minimum of 1 and a maximum of 100."
        PRD §2.3: "Paginated list responses carry the following fields in the
        `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."
        PRD §3.5: "Alerts themselves can be listed with filters on
        `episode_id`, `assigned_technician_id`, `status`, and `severity`, and
        read individually by `alert_id`."

        Design: Corner/endpoints/alerts_list_pagination_defaults_and_filter
        """
        ctx = self._setup_twelve_alerts()
        episode_id = ctx["episode_id"]

        page1, meta1 = validate_paginated(
            api.list_alerts(TECHNICIAN, params={"episode_id": episode_id})
        )
        assert len(page1) == 10, f"default limit is 10, got {len(page1)}"
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_alerts(TECHNICIAN, params={"episode_id": episode_id, "offset": 10})
        )
        assert len(page2) == 2
        assert meta2["has_more"] is False

        urgent, meta3 = validate_paginated(
            api.list_alerts(TECHNICIAN, params={"episode_id": episode_id, "severity": "URGENT"})
        )
        assert meta3["total_count"] == 5
        assert len(urgent) == 5
        assert all(a["severity"] == "URGENT" for a in urgent)

    def test_alerts_list_invalid_limit_rejected(self, api):
        """PRD §2.3: "A `limit` outside the range 1 to 100 is a
        field-validation failure rejected with `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/endpoints/alerts_list_invalid_limit_rejected
        """
        for bad_limit in (0, 101):
            resp = api.list_alerts(TECHNICIAN, params={"limit": bad_limit})
            validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_reverse_reachability_filtered_lists(self, api):
        """PRD §3.2: "The orders list can be filtered by `patient_id`,
        `ordering_physician_id`, and `status`."
        PRD §3.2: "Enrollments can be listed with filters on `order_id`,
        `device_id`, `episode_id`, and `status`, and read individually by
        `enrollment_id`."
        PRD §3.5: "Alerts themselves can be listed with filters on
        `episode_id`, `assigned_technician_id`, `status`, and `severity`, and
        read individually by `alert_id`."

        Design: Corner/endpoints/reverse_reachability_filtered_lists
        """
        ctx = setup_alert_scenario(severity="ROUTINE", alert_clock="2026-05-01T10:00:00Z")
        acknowledge_alert(ctx["alert"]["id"], ctx["technician"]["id"])

        orders, meta_o = validate_paginated(
            api.list_orders(COORD, params={"patient_id": ctx["patient"]["id"]})
        )
        assert meta_o["total_count"] == 1
        assert orders[0]["id"] == ctx["order"]["id"]

        enrollments, meta_e = validate_paginated(
            api.list_enrollments(COORD, params={"device_id": ctx["device"]["id"]})
        )
        assert meta_e["total_count"] == 1
        assert enrollments[0]["id"] == ctx["enrollment"]["id"]

        alerts, meta_a = validate_paginated(
            api.list_alerts(
                TECHNICIAN, params={"assigned_technician_id": ctx["technician"]["id"]}
            )
        )
        assert meta_a["total_count"] == 1
        assert alerts[0]["id"] == ctx["alert"]["id"]
