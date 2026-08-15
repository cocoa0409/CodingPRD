"""Safety inspections: segregation of duties, PASS auto-scheduling, the FAIL
approval cascade, and lifecycle guards (PRD §3.7, §2.7)."""
from test_helpers import (
    ApiErrorId,
    approve_inspection,
    authorize_session_ok,
    complete_inspection,
    create_inspection,
    create_station,
    get_account,
    make_compliance_officer_headers,
    make_station_manager_headers,
    setup_fueling_ready,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSegregationOfDuties:
    def test_segregation_of_duties_same_user_rejected(self, api):
        """PRD §3.7: "A `ComplianceOfficer` then approves a COMPLETED
        inspection, else `ERR_INSPECTION_NOT_APPROVABLE` (HTTP 409), and the
        approver's `X-User-ID` must differ from `performed_by` — an operator
        may never approve their own inspection — or the approval is refused
        with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/validations/segregation_of_duties_same_user_rejected
        """
        station = create_station(station_name="SoD", station_code="ST-SOD")
        inspection = create_inspection(
            station["id"],
            inspection_type="PRESSURE_VESSEL",
            scheduled_for="2026-08-10T10:00:00Z",
        )
        complete_inspection(
            inspection["id"], "PASS_WITH_DEFICIENCIES", "sm-400",
            findings="minor gauge lag",
        )
        resp = api.approve_safety_inspection(
            inspection["id"], make_compliance_officer_headers("sm-400")
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
        after = validate_success(
            api.get_safety_inspection(
                inspection["id"], make_compliance_officer_headers("co-400")
            ),
            200,
        )
        assert after["status"] == "COMPLETED"


class TestPassAutoSchedule:
    def test_inspection_pass_approval_auto_creates_next_inspection(
        self, api, compliance_officer_headers
    ):
        """PRD §3.7: "An approved PASS or PASS_WITH_DEFICIENCIES instead
        auto-creates the station's next inspection of the same
        `inspection_type`, born SCHEDULED with `scheduled_for` set to the
        completed inspection's `completed_at` plus the interval for its type:
        365 days for ANNUAL_COMPREHENSIVE, 90 days for ODORIZATION_CHECK, and
        730 days for PRESSURE_VESSEL."

        Design: Corner/state_machines/inspection_pass_approval_auto_creates_next_inspection
        """
        station = create_station(station_name="Next", station_code="ST-NEXT")
        inspection = create_inspection(
            station["id"], scheduled_for="2026-08-05T10:00:00Z"
        )
        # Completed at the default logical clock 2026-08-01T00:00:00Z.
        complete_inspection(
            inspection["id"], "PASS", "sm-300", findings="odorant detected at threshold"
        )
        approved = approve_inspection(inspection["id"], "co-300")
        assert approved["status"] == "APPROVED"

        rows, meta = validate_paginated(
            api.list_safety_inspections(
                compliance_officer_headers,
                params={"station_id": station["id"], "status": "SCHEDULED"},
            )
        )
        assert meta["total_count"] == 1
        nxt = rows[0]
        assert nxt["id"] != inspection["id"]
        assert nxt["inspection_type"] == "ODORIZATION_CHECK"
        assert nxt["scheduled_for"].startswith("2026-10-30T00:00:00"), (
            f"completed_at 2026-08-01T00:00:00Z + 90 days, got {nxt['scheduled_for']}"
        )


class TestFailApprovalCascade:
    """Difficulty instance: inspection_fail_approval_cascade (two tests)."""

    def _setup_and_approve(self, api):
        env = setup_fueling_ready(station_name="India", station_code="ST-INDIA")
        session = authorize_session_ok(
            env["card"]["id"], env["dispenser"]["id"], "CR-I1", 20.0
        )
        assert get_account(env["account"]["id"])["outstanding_balance_cents"] == 5780
        inspection = create_inspection(
            env["station"]["id"], scheduled_for="2026-08-20T10:00:00Z"
        )
        complete_inspection(
            inspection["id"], "FAIL", "sm-100",
            findings="odorant not detectable at outlet",
        )
        approved = approve_inspection(inspection["id"], "co-100")
        return env, session, inspection, approved

    def test_fail_approval_suspends_station(self, api, compliance_officer_headers):
        """PRD §3.7: "An approved FAIL suspends the station — its status
        becomes SUSPENDED with `version` incrementing — and voids every
        AUTHORIZED fueling session there with `void_reason` INSPECTION_FAIL,
        releasing each private session's hold (balance down by
        `hold_amount_cents`, account `version` up by one per session)."

        Design: Difficulty/transitive_cascade/inspection_fail_approval_cascade
        """
        env, _session, _insp, approved = self._setup_and_approve(api)
        assert approved["status"] == "APPROVED"
        station = validate_success(
            api.get_station(env["station"]["id"], compliance_officer_headers), 200
        )
        assert station["status"] == "SUSPENDED"

    def test_fail_approval_voids_sessions_and_releases_holds(
        self, api, station_manager_headers
    ):
        """PRD §3.7: "An approved FAIL suspends the station — its status
        becomes SUSPENDED with `version` incrementing — and voids every
        AUTHORIZED fueling session there with `void_reason` INSPECTION_FAIL,
        releasing each private session's hold (balance down by
        `hold_amount_cents`, account `version` up by one per session)."

        Design: Difficulty/transitive_cascade/inspection_fail_approval_cascade
        """
        env, session, _insp, _approved = self._setup_and_approve(api)
        after = validate_success(
            api.get_fueling_session(session["id"], station_manager_headers), 200
        )
        assert after["status"] == "VOIDED"
        assert after["void_reason"] == "INSPECTION_FAIL"
        assert get_account(env["account"]["id"])["outstanding_balance_cents"] == 0, (
            "hold released by the void"
        )


class TestInspectionLifecycleGuards:
    def test_inspection_complete_twice_rejected(self, api, station_manager_headers):
        """PRD §3.7: "A `StationManager` completes an inspection that is
        SCHEDULED or OVERDUE — any other state draws
        `ERR_INSPECTION_NOT_COMPLETABLE` (HTTP 409) — supplying a `result` of
        PASS, PASS_WITH_DEFICIENCIES, or FAIL plus optional `findings` text;
        the system stamps `performed_by` with the caller's `X-User-ID` and
        `completed_at` with the logical now."

        Design: Corner/validations/inspection_complete_twice_rejected
        """
        station = create_station(station_name="IC2", station_code="ST-IC2")
        inspection = create_inspection(
            station["id"],
            inspection_type="ANNUAL_COMPREHENSIVE",
            scheduled_for="2026-08-10T10:00:00Z",
        )
        complete_inspection(inspection["id"], "PASS", "sm-600")
        approve_inspection(inspection["id"], "co-600")
        resp = api.complete_safety_inspection(
            inspection["id"], {"result": "FAIL"}, make_station_manager_headers("sm-600")
        )
        validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_COMPLETABLE, 409)
        after = validate_success(
            api.get_safety_inspection(inspection["id"], station_manager_headers), 200
        )
        assert after["status"] == "APPROVED"

    def test_inspection_approve_before_complete_rejected(self, api):
        """PRD §3.7: "A `ComplianceOfficer` then approves a COMPLETED
        inspection, else `ERR_INSPECTION_NOT_APPROVABLE` (HTTP 409), and the
        approver's `X-User-ID` must differ from `performed_by` — an operator
        may never approve their own inspection — or the approval is refused
        with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/validations/inspection_approve_before_complete_rejected
        """
        station = create_station(station_name="IA1", station_code="ST-IA1")
        inspection = create_inspection(
            station["id"], scheduled_for="2026-08-10T10:00:00Z"
        )
        resp = api.approve_safety_inspection(
            inspection["id"], make_compliance_officer_headers("co-700")
        )
        validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_APPROVABLE, 409)
