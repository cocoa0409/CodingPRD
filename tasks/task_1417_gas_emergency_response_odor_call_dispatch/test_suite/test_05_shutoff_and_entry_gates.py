"""Shutoff lifecycle, entry-authorization gate, and shutoff RBAC
(PRD §3.6, §2.1)."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId,
    setup_territory_technician, intake_call, triage, dispatch, arrive,
    set_clock, get_incident, setup_on_scene_incident,
    TEST_USERS, make_technician_headers,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


def _setup_authorized_entry_required_shutoff():
    """P2 incident ON_SCENE, entry AWAITING_AUTHORIZATION, METER shutoff
    AUTHORIZED with entry_required=true (PRD §3.5/§3.6)."""
    terr, tech = setup_territory_technician()
    call, incident, disp = setup_on_scene_incident(
        terr["id"], tech["id"], priority="P2",
        address_line="51 Alder St", caller_name="Rosa", caller_phone="555-0117",
        location_context="METER_AREA", hissing_reported=True)
    inc_id = call["incident_id"]
    validate_success(api_client.set_entry_status(
        inc_id, {"to_status": "AWAITING_AUTHORIZATION"},
        make_technician_headers(tech["id"])))
    order = validate_success(api_client.create_shutoff_order(
        inc_id, {"scope": "METER", "entry_required": True, "reason": "meter leak"},
        make_technician_headers(tech["id"])), expected_status=201)
    validate_success(api_client.authorize_shutoff(order["id"], SUPERVISOR))
    return terr, tech, call, disp, order


class TestShutoffExecuteRequiresEntryAuthorization:
    def test_execute_blocked_while_entry_awaiting_authorization(self, api):
        """PRD §3.6: "When the order's `entry_required` flag is true, one more
        gate applies: the incident's `entry_status` must be `AUTHORIZED` or
        `FORCED`, or execution is rejected with `ERR_ENTRY_NOT_AUTHORIZED`
        (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/shutoff_execute_requires_entry_authorization
        """
        terr, tech, call, disp, order = _setup_authorized_entry_required_shutoff()
        resp = api_client.execute_shutoff(order["id"],
                                          make_technician_headers(tech["id"]))
        validate_error(resp, ApiErrorId.ERR_ENTRY_NOT_AUTHORIZED)

        current = validate_success(api_client.get_shutoff_order(order["id"],
                                                                SUPERVISOR))
        assert current["status"] == "AUTHORIZED"
        assert current["executed_at"] is None

    def test_customer_consent_unlocks_execution(self, api):
        """PRD §3.5: "A `CUSTOMER_CONSENT` method may be recorded by a
        `Dispatcher` or `Supervisor` and moves the dimension
        `AWAITING_AUTHORIZATION → AUTHORIZED`" and §3.6: "Successful execution
        stamps `executed_at` from the logical clock, records the executing
        technician's identity in `executed_by_technician_id`, and recomputes
        the incident's `gas_flow_stopped` — which is true exactly when any of
        the incident's shutoff orders stands in `EXECUTED` or `RESTORED`."

        Design: Difficulty/cross_entity_state_dependency/shutoff_execute_requires_entry_authorization
        """
        terr, tech, call, disp, order = _setup_authorized_entry_required_shutoff()
        inc_id = call["incident_id"]

        resp = api_client.execute_shutoff(order["id"],
                                          make_technician_headers(tech["id"]))
        validate_error(resp, ApiErrorId.ERR_ENTRY_NOT_AUTHORIZED)

        validate_success(api_client.create_entry_authorization(
            inc_id, {"method": "CUSTOMER_CONSENT", "authorized_by_name": "Rosa"},
            DISPATCHER), expected_status=201)
        incident = get_incident(inc_id)
        assert incident["entry_status"] == "AUTHORIZED"

        executed = validate_success(api_client.execute_shutoff(
            order["id"], make_technician_headers(tech["id"])))
        assert executed["status"] == "EXECUTED"
        assert executed["executed_at"] is not None
        assert executed["executed_by_technician_id"] == tech["id"]

        incident = get_incident(inc_id)
        assert incident["gas_flow_stopped"] is True


class TestShutoffAuthorizeRbac:
    def test_dispatcher_cannot_authorize_shutoff_returns_403(self, api):
        """PRD §2.1: "A request whose role is simply not permitted on the
        target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)." §3.6: "Only a `Supervisor` disposes of a request."

        Design: Corner/rbac/dispatcher_cannot_authorize_shutoff_returns_403
        """
        terr, tech = setup_territory_technician()
        call, incident, disp = setup_on_scene_incident(
            terr["id"], tech["id"], priority="P2",
            address_line="6 Shut St", caller_name="Z6", caller_phone="555-0230",
            location_context="OUTSIDE_STRUCTURE", hissing_reported=True)
        order = validate_success(api_client.create_shutoff_order(
            call["incident_id"],
            {"scope": "SERVICE_LINE", "entry_required": False,
             "reason": "service line leak"},
            make_technician_headers(tech["id"])), expected_status=201)
        assert order["status"] == "REQUESTED"

        resp = api_client.authorize_shutoff(order["id"], DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

        current = validate_success(api_client.get_shutoff_order(order["id"],
                                                                SUPERVISOR))
        assert current["status"] == "REQUESTED"
