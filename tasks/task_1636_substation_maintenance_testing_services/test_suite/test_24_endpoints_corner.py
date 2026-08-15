"""Corner coverage — endpoints: response envelope shape, side effects, and
compensation behavior observable through the API."""
from test_helpers import (
    TEST_USERS,
    api_client,
    approve_outage_window,
    assert_money_equals,
    create_defect,
    create_certified_technician,
    create_outage_window,
    create_spare_reservation,
    create_spare_unit,
    create_work_order,
    schedule_work_order,
    set_clock,
    setup_asset,
    validate_error,
    validate_success,
)
from test_helpers import ApiErrorId

OPS = TEST_USERS["ops_manager_headers"]
COORD = TEST_USERS["coordinator_headers"]


class TestResponseEnvelope:
    def test_success_envelope_shape(self):
        """PRD §2.2: "All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body:".
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`".
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources".

        Design: Corner/endpoints/response_envelope_shape_on_success
        """
        resp = api_client.create_substation(
            {"name": "Sub Env", "code": "SUB-ENV", "region": "North"}, OPS
        )
        assert resp.status_code == 201
        body = resp.json()
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert body["response_type"] == "object"
        assert body["data"]["code"] == "SUB-ENV"


class TestScheduleSideEffects:
    def test_schedule_commits_hours_and_bumps_window_version(self):
        """PRD §3.6: "Success stamps the work order's `outage_window_id`,
        transitions `DRAFT → SCHEDULED`, adds `estimated_hours` into the
        window's `committed_hours`, and increments both the work order's and
        the window's `version`."
        PRD §3.2: "A successfully created window arrives in `REQUESTED` with
        `requested_by` stamped from the caller's `X-User-ID` and
        `duration_hours` computed as the difference between `end_ts` and
        `start_ts` expressed in hours at 2 decimal places rounded half-up."
        PRD §2.4: "`version` (an integer that increments by exactly 1 on every
        state transition and on every mutation the platform applies to that
        row)."

        Design: Corner/endpoints/schedule_side_effect_committed_hours
        """
        base = setup_asset("POWER_TRANSFORMER")
        tech, tech_headers = create_certified_technician("NETA_LEVEL_2")
        defect = create_defect(base["asset"]["id"], tech_headers, "C2", title="Fan")
        work_order = create_work_order(defect["id"], tech["id"], 4, title="Fix fan")
        window = create_outage_window(
            base["substation"]["id"], base["asset"]["id"],
            "2026-10-15T08:00:00Z", "2026-10-15T16:00:00Z", purpose="Hours probe",
        )
        approved = approve_outage_window(window["id"], "ops-mgr-1")
        window_version = approved["version"]
        scheduled = schedule_work_order(work_order["id"], window["id"], window_version)
        assert scheduled["status"] == "SCHEDULED"
        assert scheduled["outage_window_id"] == window["id"]
        current = validate_success(api_client.get_outage_window(window["id"], COORD))
        assert_money_equals(current["duration_hours"], "8.00")
        assert_money_equals(current["committed_hours"], "4.00")
        assert current["version"] == window_version + 1


class TestWorkOrderCancelCompensation:
    def test_cancel_returns_hours_and_reopens_defect(self):
        """PRD §3.6: "An `OperationsManager` may cancel a work order in `DRAFT`
        or `SCHEDULED`. Cancelling from `DRAFT` simply returns the defect
        `WORK_ORDERED → OPEN`. Cancelling from `SCHEDULED` additionally
        subtracts `estimated_hours` from the window's `committed_hours` and
        increments the window's `version`, in compensation for the schedule."

        Design: Corner/endpoints/workorder_cancel_compensates_window_hours
        """
        base = setup_asset("POWER_TRANSFORMER")
        tech, tech_headers = create_certified_technician("NETA_LEVEL_2")
        defect = create_defect(base["asset"]["id"], tech_headers, "C2", title="Pump")
        work_order = create_work_order(defect["id"], tech["id"], 5, title="Fix pump")
        window = create_outage_window(
            base["substation"]["id"], base["asset"]["id"],
            "2026-10-16T08:00:00Z", "2026-10-16T16:00:00Z", purpose="Compensation probe",
        )
        approved = approve_outage_window(window["id"], "ops-mgr-1")
        schedule_work_order(work_order["id"], window["id"], approved["version"])
        cancelled = validate_success(api_client.cancel_work_order(work_order["id"], OPS))
        assert cancelled["status"] == "CANCELLED"
        current = validate_success(api_client.get_outage_window(window["id"], OPS))
        assert_money_equals(current["committed_hours"], "0.00")
        defect_now = validate_success(api_client.get_defect(defect["id"], OPS))
        assert defect_now["status"] == "OPEN"


class TestDeployAndReturn:
    def test_deploy_then_return_drives_unit_status(self):
        """PRD §3.7: "Deploying the unit is gated on the logical clock lying
        within the reservation's half-open window — at or after `start_ts` and
        strictly before `end_ts`, otherwise `ERR_OUTSIDE_WINDOW` (HTTP 422) —
        and drives the unit `RESERVED → DEPLOYED`. Returning a deployed
        reservation transitions the reservation `ACTIVE → FULFILLED` and
        recomputes the unit status the same way: `AVAILABLE` when no other
        `ACTIVE` reservation remains, else `RESERVED`."

        Design: Corner/endpoints/deploy_and_return_drive_unit_status
        """
        unit = create_spare_unit(
            unit_type="MOBILE_SUBSTATION", rating_mva=30, voltage_class_kv=115,
            impedance_pct=8.0, home_location="Depot-1",
        )
        reservation = create_spare_reservation(
            "2026-08-05T08:00:00Z", "2026-08-05T18:00:00Z",
            spare_unit_id=unit["id"], unit_type="MOBILE_SUBSTATION", required_mva=25,
        )
        set_clock("2026-08-05T10:00:00Z")
        validate_success(api_client.deploy_spare_reservation(reservation["id"], COORD))
        unit_now = validate_success(api_client.get_spare_unit(unit["id"], OPS))
        assert unit_now["status"] == "DEPLOYED"
        returned = validate_success(api_client.return_spare_reservation(reservation["id"], COORD))
        assert returned["status"] == "FULFILLED"
        unit_now = validate_success(api_client.get_spare_unit(unit["id"], OPS))
        assert unit_now["status"] == "AVAILABLE"

    def test_deploy_before_window_start_rejected(self):
        """PRD §3.7: "Deploying the unit is gated on the logical clock lying
        within the reservation's half-open window — at or after `start_ts` and
        strictly before `end_ts`, otherwise `ERR_OUTSIDE_WINDOW` (HTTP 422) —
        and drives the unit `RESERVED → DEPLOYED`."
        PRD §2.7: "At server startup the clock reads exactly
        `2026-08-01T00:00:00Z` and never falls back to wall-clock time."

        Design: Corner/endpoints/deploy_before_window_start_rejected
        """
        unit = create_spare_unit(home_location="Yard-Q")
        reservation = create_spare_reservation(
            "2026-12-01T08:00:00Z", "2026-12-01T16:00:00Z", spare_unit_id=unit["id"]
        )
        # Clock is still at the 2026-08-01 startup default, before start_ts.
        resp = api_client.deploy_spare_reservation(reservation["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_WINDOW, 422)
