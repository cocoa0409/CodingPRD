"""Validation pipeline: authentication, authorization, uniqueness, foreign-key
resolution, posture gating, and the state-vs-safety priority ordering."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    ack_ticket,
    add_operator,
    add_pump,
    add_reading,
    create_spare,
    create_station,
    create_station_payload,
    dispatch_ticket,
    get_ticket,
    make_operator_headers,
    raise_ticket,
    reset_clock,
    setup_normal_station,
    setup_ranked_plan,
    setup_station_with_pumps,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestAuthentication:
    def test_unauthenticated_missing_role_header(self, api):
        """PRD §2.1: "If `X-User-Role` is missing, malformed, or does not name
        one of the declared roles, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unauthenticated_missing_role_header
        """
        headers = {"X-User-ID": "someone", "Content-Type": "application/json"}
        res = api.list_stations(headers)
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


class TestAuthorization:
    def test_unauthorized_role_denied(self, api, operator_headers):
        """PRD §2.1: "When both headers are present but the declared role is not
        permitted to invoke the endpoint (per the authorization column of §4),
        the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "POST | /lift-station-ops/stations | Create a LiftStation. |
        UtilityAdmin"

        Design: Corner/validations/unauthorized_role_denied
        """
        reset_clock()
        res = api.create_station(
            create_station_payload(station_code="LS-0300"), operator_headers,
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)

    def test_planner_cannot_approve_plan(self, api, capital_program_manager_headers):
        """PRD §4: "Approve the ranked plan (`RANKED` → `APPROVED`). OCC-guarded by
        `expected_plan_version`. | UtilityAdmin"
        PRD §2.1: "When both headers are present but the declared role is not
        permitted to invoke the endpoint (per the authorization column of §4),
        the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/planner_cannot_approve_plan
        """
        reset_clock()
        plan, _, _ = setup_ranked_plan(plan_year=2034)
        res = api.approve_capital_plan(plan["id"], plan["version"], capital_program_manager_headers)
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)

    def test_operator_cannot_create_capital_plan(self, api, operator_headers):
        """PRD §4: "Create a CapitalPlan for a `plan_year`. | CapitalProgramManager"
        PRD §2.1: "When both headers are present but the declared role is not
        permitted to invoke the endpoint (per the authorization column of §4),
        the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/operator_cannot_create_capital_plan
        """
        reset_clock()
        res = api.create_capital_plan(
            {"plan_year": 2035, "budget_total_usd": 1000}, operator_headers,
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)

    def test_compliance_officer_cannot_dispatch_alarm(self, api, compliance_officer_headers,
                                                      on_call_operator_headers):
        """PRD §4: "Dispatch the ticket; selects the callout winner. OCC-guarded by
        `expected_ticket_version`. | OnCallOperator"
        PRD §2.1: "When both headers are present but the declared role is not
        permitted to invoke the endpoint (per the authorization column of §4),
        the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/compliance_officer_cannot_dispatch_alarm
        """
        reset_clock()
        station = create_station()
        ticket = raise_ticket(station["id"])
        ack_ticket(ticket["id"])
        current = get_ticket(ticket["id"])
        res = api.dispatch_alarm_ticket(
            ticket["id"], current["version"], compliance_officer_headers,
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)

    def test_only_assigned_operator_can_arrive(self, api):
        """PRD §2.1: "actions such as arriving on-scene at a dispatched alarm,
        closing a confined-space permit, or issuing a permit as its named
        supervisor are only legal when the caller's `X-User-ID` equals the
        `Operator` `id` recorded on the resource."
        PRD §3.3: "arriving on scene (an `Operator` whose `X-User-ID` equals the
        ticket's `assigned_operator_id`) moves `DISPATCHED → ON_SCENE`"

        The PRD names no specific error identifier for an ownership failure, so
        either the authorization or the lifecycle-state rejection satisfies the
        contract.

        Design: Corner/rbac/only_assigned_operator_can_arrive
        """
        reset_clock()
        station = create_station(service_zone="Z1")
        op_a = add_operator(full_name="OpA", home_zone="Z1")
        op_b = add_operator(full_name="OpB", home_zone="Z9")
        ticket = raise_ticket(station["id"])
        ack_ticket(ticket["id"])
        dispatched = dispatch_ticket(ticket["id"])
        assert dispatched["assigned_operator_id"] == op_a["id"]
        res = api.arrive_alarm_ticket(ticket["id"], make_operator_headers(op_b["id"]))
        validate_error_is_one_of(
            res, [ApiErrorId.ERR_UNAUTHORIZED.value, ApiErrorId.ERR_INVALID_STATE.value],
        )


class TestUniquenessAndReferences:
    def test_duplicate_station_code_rejected(self, api, utility_admin_headers):
        """PRD §3.1: "The `station_code` must be unique across all stations and
        must match the pattern of the letters "LS-" followed by exactly four
        digits; a collision or a malformed code is rejected with
        `ERR_DUPLICATE_STATION_CODE` (HTTP 422)."

        Design: Corner/validations/duplicate_station_code_rejected
        """
        reset_clock()
        create_station(station_code="LS-0301")
        res = api.create_station(
            create_station_payload(
                station_code="LS-0301", service_zone="Z9", design_capacity_gpm=999,
                pump_count=4, has_backup_generator=True, wet_well_volume_gal=9000,
            ),
            utility_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_STATION_CODE)

    def test_duplicate_position_index_rejected(self, api, utility_admin_headers):
        """PRD §3.2: "The `position_index` must lie between 1 and the station's
        `pump_count` and must be unique within the station — a duplicate or
        out-of-range slot is rejected with `ERR_DUPLICATE_POSITION` (HTTP 422)."

        Design: Corner/validations/duplicate_position_index_rejected
        """
        reset_clock()
        station = create_station(station_code="LS-0302")
        add_pump(station["id"], 1, 100)
        res = api.create_pump(
            {"station_id": station["id"], "position_index": 1, "rated_gpm": 200,
             "status": "IN_SERVICE"},
            utility_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_POSITION)

    def test_fk_reference_not_found(self, api, utility_admin_headers):
        """PRD §2.8: "A body-provided foreign key such as `station_id`,
        `pump_id`, `plan_id`, `authorized_entrant_id`, `attendant_operator_id`,
        `entry_supervisor_id`, or `crew_lead_operator_id` that references a
        non-existent row is a different failure and produces
        `ERR_REFERENCE_NOT_FOUND` (HTTP 422)."

        Design: Corner/validations/fk_reference_not_found
        """
        reset_clock()
        res = api.create_pump(
            {"station_id": NON_EXISTENT_UUID, "position_index": 1, "rated_gpm": 100,
             "status": "IN_SERVICE"},
            utility_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_REFERENCE_NOT_FOUND)

    def test_zone_mismatch_on_spare_reserve(self, api, maintenance_planner_headers):
        """PRD §3.4: "A `MaintenancePlanner` reserves an `AVAILABLE` spare for a
        station by supplying the target `station_id`; the spare's
        `compatible_zone` must equal the station's `service_zone`, or the
        reservation is rejected with `ERR_ZONE_MISMATCH` (HTTP 422)."

        Design: Corner/validations/zone_mismatch_on_spare_reserve
        """
        reset_clock()
        station = create_station(station_code="LS-0303", service_zone="Z1")
        spare = create_spare(asset_tag="SP-0001", rated_gpm=200, compatible_zone="Z9")
        res = api.reserve_spare_pump(spare["id"], station["id"], maintenance_planner_headers)
        validate_error(res, ApiErrorId.ERR_ZONE_MISMATCH)

    def test_error_not_found_on_missing_pump(self, api, utility_admin_headers):
        """PRD §2.8: "path identifiers are resolved left to right, and the first
        identifier that does not resolve to an existing row produces
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/errors/error_not_found_on_missing_pump
        """
        reset_clock()
        res = api.get_pump(NON_EXISTENT_UUID, utility_admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)


class TestTemporalAndPostureValidation:
    def test_runtime_reading_out_of_order_rejected(self, api, utility_admin_headers):
        """PRD §3.2: "Readings for a pump must be chronological: a `recorded_at`
        earlier than the prior reading's `recorded_at` for the same pump is
        rejected with `ERR_READING_OUT_OF_ORDER` (HTTP 422)."

        Design: Corner/validations/runtime_reading_out_of_order_rejected
        """
        reset_clock()
        station = create_station(station_code="LS-0304")
        pump = add_pump(station["id"], 1, 100)
        add_reading(pump["id"], "2026-08-01T05:00:00Z", 1.0)
        res = api.create_runtime_reading(
            pump["id"],
            {"recorded_at": "2026-08-01T04:00:00Z", "run_hours_delta": 1.0,
             "starts_count": 1, "source": "SCADA"},
            utility_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_READING_OUT_OF_ORDER)

    def test_frozen_station_blocks_child_mutations(self, api, utility_admin_headers,
                                                   operations_supervisor_headers):
        """PRD §2.7: "Any mutation targeting a station's child resources — any
        action beneath a station in the URL hierarchy, and any child mutation
        that names a `station_id` — is rejected with `ERR_STATION_FROZEN` (HTTP
        409) while the station's `operational_posture` is `FROZEN`."
        PRD §3.12: "Recall from §2.7 that all child mutations at a frozen
        station are refused with `ERR_STATION_FROZEN`, and that non-critical
        child mutations at an emergency station are refused with
        `ERR_STATION_EMERGENCY`."

        Design: Corner/validations/frozen_station_blocks_child_mutations
        """
        reset_clock()
        station, pumps = setup_normal_station()
        res = api.freeze_station(station["id"], utility_admin_headers)
        frozen = validate_success(res, 200)
        assert frozen["operational_posture"] == "FROZEN"
        res = api.standby_pump(pumps[0]["id"], operations_supervisor_headers)
        validate_error(res, ApiErrorId.ERR_STATION_FROZEN)


class TestStateVsSafetyPriority:
    def test_invalid_state_wins_over_firm_capacity(self, api, operations_supervisor_headers):
        """PRD §2.8: "When several validation rules could reject the same
        request, the server evaluates them in a fixed order and surfaces only
        the first failure: authentication and role authorization first
        (`ERR_UNAUTHENTICATED` before `ERR_UNAUTHORIZED`); then path-existence
        (`ERR_NOT_FOUND`); then body foreign-key existence
        (`ERR_REFERENCE_NOT_FOUND`); then the target entity's lifecycle state
        (`ERR_INVALID_STATE`); then posture gating (`ERR_STATION_FROZEN` /
        `ERR_STATION_EMERGENCY`); then the business-safety rules in their
        declared sequence — firm-capacity preservation, segregation of duties,
        certification, gas test"

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_oos
        """
        reset_clock()
        station, pumps = setup_station_with_pumps(ratings=(150, 150))
        p2 = pumps[1]
        res = api.mark_pump_out_of_service(p2["id"], operations_supervisor_headers)
        validate_success(res, 200)
        res = api.mark_pump_out_of_service(p2["id"], operations_supervisor_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_firm_capacity_violation_on_last_in_service_pump(
        self, api, operations_supervisor_headers
    ):
        """PRD §3.4: "The same firm-capacity rule guards an
        `OperationsSupervisor` marking a pump out of service (`IN_SERVICE →
        OUT_OF_SERVICE`, which also auto-fires the `PUMP_OUT_OF_SERVICE` `MAJOR`
        alarm)."
        PRD §3.4: "it is refused at a frozen station, and it is refused with
        `ERR_FIRM_CAPACITY_VIOLATION` (HTTP 422) when it would leave the station
        without at least one remaining `IN_SERVICE` pump."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_oos
        """
        reset_clock()
        station, pumps = setup_station_with_pumps(ratings=(150, 150))
        res = api.mark_pump_out_of_service(pumps[1]["id"], operations_supervisor_headers)
        validate_success(res, 200)
        res = api.mark_pump_out_of_service(pumps[0]["id"], operations_supervisor_headers)
        validate_error(res, ApiErrorId.ERR_FIRM_CAPACITY_VIOLATION)
