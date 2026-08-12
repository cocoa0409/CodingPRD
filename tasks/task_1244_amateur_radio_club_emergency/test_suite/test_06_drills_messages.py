"""Drills and radiogram message handling (PRD §3.5): the RELAYED self-loop,
delivery gating, origination preconditions, and drill-creation RBAC."""
from test_helpers import (
    ApiErrorId,
    assert_drill_message,
    create_active_member,
    create_drill_message_payload,
    create_drill_payload,
    create_member,
    create_planned_drill,
    drill_message_transition,
    get_success_data,
    make_liaison_headers,
    make_member_headers,
    originate_message,
    set_clock,
    start_drill,
    validate_error,
)


def _drill_scenario():
    """EC member + ACTIVE member + a PLANNED drill (window covers the default
    logical clock)."""
    ec = create_member("W1EC")
    member = create_active_member("K1OPR")
    drill = create_planned_drill(ec["id"])
    return ec, member, drill


class TestRelaySelfLoop:
    def test_two_relays_increment_relay_count_and_delivery_succeeds(self, api, admin_headers):
        """PRD §3.5: "Relaying moves a message `ORIGINATED` → `RELAYED`, and
        each subsequent relay is a `RELAYED` → `RELAYED` self-loop — every
        entry into `RELAYED`, self-loops included, adds one to `relay_count`."

        Design: Difficulty/non_linear_state_machine/drill_message_relay_self_loop
        """
        ec, member, drill = _drill_scenario()
        start_drill(drill["id"], ec["id"])
        message = originate_message(drill["id"], member["id"])
        relayed_once = drill_message_transition(message["id"], "RELAYED", member["id"])
        assert relayed_once["relay_count"] == 1
        relayed_twice = drill_message_transition(message["id"], "RELAYED", member["id"])
        assert relayed_twice["relay_count"] == 2
        set_clock("2026-05-01T01:00:00Z")
        delivered = drill_message_transition(message["id"], "DELIVERED", member["id"])
        assert delivered["status"] == "DELIVERED"
        assert delivered["relay_count"] == 2

    def test_delivery_computes_handling_seconds(self, api, admin_headers):
        """PRD §3.5: "Delivery stamps `delivered_at` and computes
        `handling_seconds` as the whole-second difference between
        `delivered_at` and the message's `created_at`; both remain null until
        delivery."

        Design: Difficulty/non_linear_state_machine/drill_message_relay_self_loop
        """
        ec, member, drill = _drill_scenario()
        start_drill(drill["id"], ec["id"])
        message = originate_message(drill["id"], member["id"])
        drill_message_transition(message["id"], "RELAYED", member["id"])
        drill_message_transition(message["id"], "RELAYED", member["id"])
        # One hour after the message was originated at the default clock.
        set_clock("2026-05-01T01:00:00Z")
        delivered = drill_message_transition(message["id"], "DELIVERED", member["id"])
        assert_drill_message(delivered)
        assert delivered["handling_seconds"] == 3600


class TestDeliveryGating:
    def test_deliver_without_relay_rejected(self, api, admin_headers):
        """PRD §3.5: "Delivery (`RELAYED` → `DELIVERED`) is possible only for a
        message that has actually been relayed: a message that never left
        `ORIGINATED` — where `relay_count` is still zero — cannot be delivered
        and is rejected with `ERR_MESSAGE_NOT_RELAYED`."

        Design: Corner/state_machines/drill_message_deliver_without_relay_rejected
        """
        ec, member, drill = _drill_scenario()
        start_drill(drill["id"], ec["id"])
        message = originate_message(drill["id"], member["id"])
        resp = api.drill_message_set_status(
            message["id"], {"to": "DELIVERED"}, make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_MESSAGE_NOT_RELAYED)
        after = get_success_data(api.get_drill_message(message["id"], admin_headers))
        assert after["status"] == "ORIGINATED"
        assert after["relay_count"] == 0


class TestDrillPreconditions:
    def test_message_on_planned_drill_rejected(self, api, admin_headers):
        """PRD §3.5: "Origination requires the drill to be `IN_PROGRESS`
        (`ERR_DRILL_NOT_IN_PROGRESS`) and the caller's membership to be
        `ACTIVE` (`ERR_MEMBERSHIP_NOT_ACTIVE`)".

        Design: Corner/errors/message_on_planned_drill_rejected
        """
        ec, member, drill = _drill_scenario()
        assert drill["status"] == "PLANNED"
        resp = api.create_drill_message(
            create_drill_message_payload(drill["id"]),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_DRILL_NOT_IN_PROGRESS)


class TestDrillRbac:
    def test_exam_liaison_cannot_create_drill(self, api, admin_headers):
        """PRD §4: the drill-planning endpoint is listed with authorized role
        "EmergencyCoordinator" only, and §2.1: "A request whose role is not
        listed for the target endpoint, or that fails a declared ownership
        sub-check ... is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/exam_liaison_cannot_create_drill
        """
        liaison = create_member("W1LIA")
        resp = api.create_drill(create_drill_payload(),
                                make_liaison_headers(liaison["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
