"""Master-data lifecycle gates: installs, technician/account gates, AMI ingest.

Covers PRD section 3.1 (master data), section 3.4 (AMI ingestion), the
common-fields version contract of section 2.5, and route-reassign OCC (2.7).
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    ami_read_payload,
    assign_route_payload,
    create_billing_period,
    create_billing_period_payload,
    create_field_technician_payload,
    create_meter,
    create_meter_payload,
    create_route,
    create_route_payload,
    create_service_account_payload,
    get_account,
    get_meter,
    get_route_stops,
    get_stop,
    ingest_ami_read,
    install_meter_at_account,
    make_field_technician_headers,
    reassign_route_payload,
    set_logical_clock,
    setup_account_with_installed_meter,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["meter_ops_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


class TestMeterInstallGates:
    def test_install_rejected_when_account_occupied(self, api, meter_ops_admin_headers):
        """PRD section 3.1: "The target account must be `ACTIVE`
        (`ERR_ACCOUNT_NOT_ACTIVE`, HTTP 409) and must not already have another
        meter in service (`ERR_ACCOUNT_HAS_INSTALLED_METER`, HTTP 409)."

        Design: Corner/validations/install_rejected_when_account_occupied
        """
        account, m1 = setup_account_with_installed_meter(
            "C-0073", "C73", service_address="73 Occupy Rd"
        )
        m2 = create_meter("SN-OC-12", "HANDHELD")
        res = api.install_meter(m2["id"], {"service_account_id": account["id"]}, ADMIN)
        validate_error(res, ApiErrorId.ERR_ACCOUNT_HAS_INSTALLED_METER.value, 409)
        assert get_meter(m2["id"])["meter_status"] == "IN_STOCK"

    def test_meter_retire_terminal_rejects_install(self, api, meter_ops_admin_headers):
        """PRD section 3.1: "Retirement moves a meter from `IN_STOCK` or
        `REMOVED` to the terminal `RETIRED` state."
        PRD section 2.12: "Where a transition is not permitted from a
        resource's current state and no more specific rule names the failure,
        the request is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP
        409)."

        Design: Corner/state_machines/meter_retire_terminal_rejects_install
        """
        account = validate_success(
            api.create_service_account(
                create_service_account_payload(
                    account_number="C-0039",
                    service_address="39 Retire Rd",
                    billing_cycle_code="C39",
                ),
                meter_ops_admin_headers,
            ),
            201,
        )
        meter = create_meter("SN-RT-1", "HANDHELD")
        retired = validate_success(api.retire_meter(meter["id"], ADMIN), 200)
        assert retired["meter_status"] == "RETIRED"

        res = api.install_meter(meter["id"], {"service_account_id": account["id"]}, ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)
        assert get_meter(meter["id"])["meter_status"] == "RETIRED"


class TestTechnicianLifecycleGates:
    def test_technician_deactivate_blocked_by_open_work(
        self, api, meter_ops_admin_headers, dispatcher_headers
    ):
        """PRD section 3.1: "Deactivation moves `technician_status` from
        `ACTIVE` to `INACTIVE`, but only when the technician holds no open
        commitments: a route assigned or in progress under that technician, or
        a work order dispatched or in progress under them, blocks deactivation
        with `ERR_TECHNICIAN_HAS_OPEN_WORK` (HTTP 409)."

        Design: Corner/validations/technician_deactivate_blocked_by_open_work
        """
        tech = validate_success(
            api.create_field_technician(
                create_field_technician_payload(display_name="Busy Tech"),
                meter_ops_admin_headers,
            ),
            201,
        )
        period = create_billing_period(
            "C92", "2026-08-01", "2026-08-31", "2026-08-03", "2026-08-07", "2026-08-31"
        )
        route = create_route(period["id"], "2026-08-03", route_shift="AM")
        validate_success(
            api.assign_route(route["id"], assign_route_payload(tech["id"]), dispatcher_headers),
            200,
        )

        res = api.deactivate_field_technician(tech["id"], meter_ops_admin_headers)
        validate_error(res, ApiErrorId.ERR_TECHNICIAN_HAS_OPEN_WORK.value, 409)

        validate_success(api.unassign_route(route["id"], dispatcher_headers), 200)
        deactivated = validate_success(
            api.deactivate_field_technician(tech["id"], meter_ops_admin_headers), 200
        )
        assert deactivated["technician_status"] == "INACTIVE"

    def test_assign_inactive_technician_rejected(
        self, api, meter_ops_admin_headers, dispatcher_headers
    ):
        """PRD section 3.1: "An `INACTIVE` technician cannot receive new
        routes or work orders — assignment, reassignment, and dispatch all
        fail with `ERR_TECHNICIAN_NOT_ACTIVE` (HTTP 409) — though commitments
        already in flight are unaffected."

        Design: Corner/validations/assign_inactive_technician_rejected
        """
        tech = validate_success(
            api.create_field_technician(
                create_field_technician_payload(display_name="Idle Tech"),
                meter_ops_admin_headers,
            ),
            201,
        )
        validate_success(api.deactivate_field_technician(tech["id"], meter_ops_admin_headers), 200)

        period = create_billing_period(
            "C93", "2026-08-01", "2026-08-31", "2026-08-03", "2026-08-07", "2026-08-31"
        )
        route = create_route(period["id"], "2026-08-03", route_shift="AM")
        res = api.assign_route(route["id"], assign_route_payload(tech["id"]), dispatcher_headers)
        validate_error(res, ApiErrorId.ERR_TECHNICIAN_NOT_ACTIVE.value, 409)


class TestAccountLifecycle:
    def test_account_close_blocked_by_open_work(self, api, meter_ops_admin_headers):
        """PRD section 3.1: "Closing an account — permitted from either
        `ACTIVE` or `SUSPENDED` and restricted to `MeterOpsAdmin` — requires
        that no open work remain: open stops, unfinished work orders, or
        un-closed investigations cause rejection with
        `ERR_ACCOUNT_HAS_OPEN_WORK` (HTTP 409). `CLOSED` is terminal."
        PRD section 2.12: "Where a transition is not permitted from a
        resource's current state and no more specific rule names the failure,
        the request is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP
        409)."

        Design: Corner/validations/account_close_blocked_by_open_work
        """
        account_1, m1 = setup_account_with_installed_meter(
            "C-0094A", "C94", service_address="94A Close Rd"
        )
        account_2 = validate_success(
            api.create_service_account(
                create_service_account_payload(
                    account_number="C-0094B",
                    service_address="94B Close Rd",
                    billing_cycle_code="C95",
                ),
                meter_ops_admin_headers,
            ),
            201,
        )
        period = create_billing_period(
            "C94", "2026-08-01", "2026-08-31", "2026-08-03", "2026-08-07", "2026-08-31"
        )
        route = create_route(period["id"], "2026-08-03", route_shift="AM")
        stops = get_route_stops(route["id"])
        assert len(stops) == 1  # account_1's PENDING stop

        res = api.close_service_account(account_1["id"], meter_ops_admin_headers)
        validate_error(res, ApiErrorId.ERR_ACCOUNT_HAS_OPEN_WORK.value, 409)

        closed = validate_success(
            api.close_service_account(account_2["id"], meter_ops_admin_headers), 200
        )
        assert closed["account_status"] == "CLOSED"

        # CLOSED is terminal: reactivation is not a transition from CLOSED.
        res2 = api.reactivate_service_account(account_2["id"], meter_ops_admin_headers)
        validate_error(res2, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

    def test_account_suspend_cancels_pending_stops(self, api, meter_ops_admin_headers):
        """PRD section 3.1: "Suspending an account moves `account_status` from
        `ACTIVE` to `SUSPENDED` and immediately strands its field work: every
        route stop for the account still sitting in `PENDING` on a route in
        `DRAFT`, `ASSIGNED`, or `IN_PROGRESS` transitions to `CANCELLED`."

        Design: Corner/state_machines/account_suspend_cancels_pending_stops
        """
        account, m1 = setup_account_with_installed_meter(
            "C-0042", "C42", service_address="42 Suspend Rd"
        )
        period = create_billing_period(
            "C42", "2026-08-01", "2026-08-31", "2026-08-03", "2026-08-07", "2026-08-31"
        )
        route = create_route(period["id"], "2026-08-03", route_shift="AM")
        stops = get_route_stops(route["id"])
        assert len(stops) == 1

        suspended = validate_success(
            api.suspend_service_account(account["id"], meter_ops_admin_headers), 200
        )
        assert suspended["account_status"] == "SUSPENDED"
        assert get_stop(stops[0]["id"])["stop_status"] == "CANCELLED"

    def test_version_increments_on_every_mutation(self, api, meter_ops_admin_headers):
        """PRD section 2.5: "`version` (integer): a system-managed integer
        that increments with every modification to the resource, including
        modifications applied automatically by the system cascades described
        throughout this document."
        PRD section 2.5: "No resource type is exempt: all thirteen carry the
        full quartet, and any mutation — client-driven or cascaded — refreshes
        `updated_at` and increments `version` on each resource it touches."

        Design: Corner/complexity_layers/version_increments_on_every_mutation
        """
        account = validate_success(
            api.create_service_account(
                create_service_account_payload(
                    account_number="C-0132",
                    service_address="132 Ver Rd",
                    billing_cycle_code="CE4",
                ),
                meter_ops_admin_headers,
            ),
            201,
        )
        assert account["version"] == 1
        suspended = validate_success(
            api.suspend_service_account(account["id"], meter_ops_admin_headers), 200
        )
        assert suspended["version"] == 2
        reactivated = validate_success(
            api.reactivate_service_account(account["id"], meter_ops_admin_headers), 200
        )
        assert reactivated["version"] == 3


class TestAmiIngestion:
    def test_ami_ingest_on_handheld_meter_rejected(self, api, meter_ops_admin_headers):
        """PRD section 3.4: "The meter must be an `AMI` meter — ingestion
        against a `HANDHELD` meter fails with `ERR_METER_NOT_AMI` (HTTP 422) —
        and must be `IN_SERVICE`."

        Design: Corner/validations/ami_ingest_on_handheld_meter_rejected
        """
        account, m1 = setup_account_with_installed_meter(
            "C-0076", "C76", service_address="76 Ami Rd"
        )
        res = api.ingest_ami_read(
            m1["id"], ami_read_payload(100, "2026-08-02T10:00:00Z"), meter_ops_admin_headers
        )
        validate_error(res, ApiErrorId.ERR_METER_NOT_AMI.value, 422)

    def test_ami_ingest_rollback_rejected(self, api, meter_ops_admin_headers):
        """PRD section 2.9: "Meter registers move in one direction. Every
        `read_value`, `old_final_read_value`, and `reread_value` is a
        non-negative integer number of kWh, and any value presented below the
        account's `last_validated_read_value` (when that field is set) is
        rejected with `ERR_READ_ROLLBACK` (HTTP 422). This rollback screen
        applies uniformly to field read capture, AMI head-end ingestion,
        re-read completion, and meter-exchange completion."

        Design: Corner/validations/ami_ingest_rollback_rejected
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        account, m1 = setup_account_with_installed_meter(
            "C-0077", "C77", meter_type="AMI", service_address="77 Ami Rd"
        )
        ingest_ami_read(m1["id"], 100, "2026-08-01T10:00:00Z")
        assert get_account(account["id"])["last_validated_read_value"] == 100

        res = api.ingest_ami_read(
            m1["id"], ami_read_payload(50, "2026-08-02T10:00:00Z"), meter_ops_admin_headers
        )
        validate_error(res, ApiErrorId.ERR_READ_ROLLBACK.value, 422)
        assert get_account(account["id"])["last_validated_read_value"] == 100


class TestRouteReassignOcc:
    def test_occ_route_reassign_stale_version(self, api, meter_ops_admin_headers, dispatcher_headers):
        """PRD section 2.7: "Reassigning a route
        (`POST /routes/{id}/reassign`) requires `expected_route_version`
        matching the route's current `version`. Reassignment legitimately
        supersedes the current technician assignment while `ASSIGNED`, so a
        client holding a stale version would otherwise silently overwrite a
        newer assignment."
        PRD section 3.3: "the request must carry `expected_route_version`
        matching the route's current `version` (mismatches fail with
        `ERR_STALE_VERSION`, HTTP 412), the new technician must be `ACTIVE`
        and conflict-free, and the operation increments the route's `version`
        by one while remaining in `ASSIGNED`."

        Design: Corner/complexity_layers/occ_route_reassign_stale_version
        """
        tech_a = validate_success(
            api.create_field_technician(
                create_field_technician_payload(display_name="OCC A"), meter_ops_admin_headers
            ),
            201,
        )
        tech_b = validate_success(
            api.create_field_technician(
                create_field_technician_payload(display_name="OCC B"), meter_ops_admin_headers
            ),
            201,
        )
        period = create_billing_period(
            "CE1", "2026-08-01", "2026-08-31", "2026-08-03", "2026-08-07", "2026-08-31"
        )
        route = create_route(period["id"], "2026-08-03", route_shift="AM")
        validate_success(
            api.assign_route(route["id"], assign_route_payload(tech_a["id"]), dispatcher_headers),
            200,
        )
        current = validate_success(api.get_route(route["id"], dispatcher_headers), 200)
        observed_version = current["version"]

        reassigned = validate_success(
            api.reassign_route(
                route["id"],
                reassign_route_payload(tech_b["id"], observed_version),
                dispatcher_headers,
            ),
            200,
        )
        assert reassigned["technician_id"] == tech_b["id"]
        assert reassigned["version"] == observed_version + 1
        assert reassigned["route_status"] == "ASSIGNED"

        # Replaying the same expected version is now stale.
        stale = api.reassign_route(
            route["id"],
            reassign_route_payload(tech_a["id"], observed_version),
            dispatcher_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value, 412)
        after = validate_success(api.get_route(route["id"], dispatcher_headers), 200)
        assert after["technician_id"] == tech_b["id"]
