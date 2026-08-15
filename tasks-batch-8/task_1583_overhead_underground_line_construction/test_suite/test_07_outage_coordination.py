"""Outage coordination: the sixty-minute clearance buffer, the change-request
renegotiation cycle, and decision authorization."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_outage,
    assert_outage_request,
    get_success_data,
    request_outage,
    setup_approved_outage,
    setup_mobilized_scenario,
    validate_error,
    validate_success,
)

PM = TEST_USERS["contractor_pm_headers"]
DISPATCHER = TEST_USERS["utility_dispatcher_headers"]
INSPECTOR = TEST_USERS["utility_inspector_headers"]


def _buffer_scenario(api):
    """Mobilized outage-dependent package with o1 APPROVED on circuit CKT-9 for
    2026-08-10T10:00:00Z..2026-08-10T12:00:00Z, plus two pending requests:
    o2 starting 30 minutes after o1 ends, o3 starting exactly 60 minutes after."""
    scenario = setup_mobilized_scenario(
        requires_outage=True,
        contract_overrides={"contract_number": "C-901"},
        bid_item_overrides={"item_code": "OH-RECLOSER",
                            "description": "Recloser install",
                            "unit_price": 400.00, "estimated_quantity": 12},
        wp_overrides={"name": "Recloser program", "location": "CKT-9 corridor"})
    wp_id = scenario["work_package"]["id"]
    o1 = setup_approved_outage(wp_id, "CKT-9",
                               "2026-08-10T10:00:00Z", "2026-08-10T12:00:00Z")
    o2 = request_outage(wp_id, "CKT-9",
                        "2026-08-10T12:30:00Z", "2026-08-10T14:00:00Z")
    o3 = request_outage(wp_id, "CKT-9",
                        "2026-08-10T13:00:00Z", "2026-08-10T15:00:00Z")
    return scenario, o1, o2, o3


class TestClearanceBuffer:
    def test_outage_approval_inside_sixty_minute_buffer_rejected(self, api):
        """PRD §3.6: "Approval runs a clearance check on the circuit: for every
        other outage request on the same `circuit_id` standing in `APPROVED` or
        `IN_EFFECT`, the new window must either begin at least sixty minutes
        after the other window ends or end at least sixty minutes before the
        other window begins. A gap of exactly one hour satisfies the buffer;
        anything tighter is rejected with `ERR_OUTAGE_WINDOW_CONFLICT`."
        o2 begins only 30 minutes after o1's window ends.

        Design: Difficulty/resource_temporal_overlap/outage_window_sixty_minute_buffer
        """
        scenario, o1, o2, o3 = _buffer_scenario(api)
        resp = api.decide_outage_request(o2["id"], {"decision": "APPROVED"},
                                         DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_OUTAGE_WINDOW_CONFLICT)
        o2_after = validate_success(api.get_outage_request(o2["id"], PM))
        assert o2_after["status"] == "REQUESTED", (
            "The rejected approval leaves the outage REQUESTED")

    def test_outage_approval_at_exactly_sixty_minutes_allowed(self, api):
        """PRD §3.6: "Approval runs a clearance check on the circuit: for every
        other outage request on the same `circuit_id` standing in `APPROVED` or
        `IN_EFFECT`, the new window must either begin at least sixty minutes
        after the other window ends or end at least sixty minutes before the
        other window begins. A gap of exactly one hour satisfies the buffer;
        anything tighter is rejected with `ERR_OUTAGE_WINDOW_CONFLICT`."
        o3 begins exactly 60 minutes after o1's window ends: boundary inclusive.

        Design: Difficulty/resource_temporal_overlap/outage_window_sixty_minute_buffer
        """
        scenario, o1, o2, o3 = _buffer_scenario(api)
        resp = api.decide_outage_request(o3["id"], {"decision": "APPROVED"},
                                         DISPATCHER)
        approved = validate_success(resp, 200)
        assert_outage_request(approved)
        assert approved["status"] == "APPROVED", (
            "A gap of exactly one hour satisfies the buffer")


class TestChangeRequestCycle:
    def test_outage_request_change_cycle_adopts_new_window(self, api):
        """PRD §3.6: "The project manager may propose a new window for an
        `APPROVED` request, again with a `window_start` strictly before the
        `window_end` under the same date-range rule; the request moves to
        `CHANGE_REQUESTED` and the proposal is stored in
        `requested_window_start` and `requested_window_end` without disturbing
        the operative window. Re-approval from `CHANGE_REQUESTED` applies the
        same sixty-minute clearance check to the proposed window, then adopts
        it: `window_start` and `window_end` are overwritten from the requested
        values and both requested fields are cleared to null."

        Design: Corner/state_machines/outage_request_change_cycle_adopts_new_window
        """
        scenario = setup_mobilized_scenario(
            requires_outage=True,
            contract_overrides={"contract_number": "CS-5"},
            wp_overrides={"name": "WP oc", "location": "L5"})
        wp_id = scenario["work_package"]["id"]
        outage = setup_approved_outage(wp_id, "CKT-2",
                                       "2026-08-10T08:00:00Z",
                                       "2026-08-10T12:00:00Z")

        changed = get_success_data(api.request_change_outage_request(
            outage["id"],
            {"window_start": "2026-08-11T09:00:00Z",
             "window_end": "2026-08-11T13:00:00Z"},
            PM))
        assert changed["status"] == "CHANGE_REQUESTED"
        assert changed["requested_window_start"] == "2026-08-11T09:00:00Z", (
            "The proposal is stored without disturbing the operative window")
        assert changed["window_start"] == "2026-08-10T08:00:00Z", (
            "The operative window still holds the approved values")

        reapproved = approve_outage(outage["id"])
        assert reapproved["status"] == "APPROVED"
        assert reapproved["window_start"] == "2026-08-11T09:00:00Z", (
            "Re-approval adopts the requested window start")
        assert reapproved["window_end"] == "2026-08-11T13:00:00Z", (
            "Re-approval adopts the requested window end")
        assert reapproved["requested_window_start"] is None
        assert reapproved["requested_window_end"] is None, (
            "Both requested fields are cleared to null on adoption")


class TestOutageRbac:
    def test_utility_inspector_cannot_decide_outage(self, api):
        """PRD §2.1: "A request whose role is authenticated but not listed among
        the roles permitted for the target endpoint is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "| POST | `/outage-requests/{outage_request_id}/decide` |
        Utility decision: approve (runs the sixty-minute buffer check; adopts
        the requested window when `CHANGE_REQUESTED`) or deny |
        UTILITY_DISPATCHER |"

        Design: Corner/rbac/utility_inspector_cannot_decide_outage
        """
        scenario = setup_mobilized_scenario(
            requires_outage=True,
            contract_overrides={"contract_number": "CR-1"},
            wp_overrides={"name": "WP rbac", "location": "L24"})
        outage = request_outage(scenario["work_package"]["id"], "CKT-R",
                                "2026-08-10T08:00:00Z", "2026-08-10T12:00:00Z")

        resp = api.decide_outage_request(outage["id"], {"decision": "APPROVED"},
                                         INSPECTOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        outage_after = validate_success(api.get_outage_request(outage["id"], PM))
        assert outage_after["status"] == "REQUESTED", (
            "The forbidden decision leaves the outage REQUESTED")
