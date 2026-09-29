"""Lifecycles that loop, refuse a further lap, and drag a second dimension with them.

A cross-connect route may be sent back for rework twice and no more, and every lap
must hand the patch-panel pool back exactly as it found it — so the third refusal
leaves an order that is still approvable and still holding precisely one port pair.
A remote-hands ticket carries two dimensions that are neither independent nor merged:
dispatch reads the authorization dimension, and a later revocation reaches across and
cancels an already dispatched execution.
"""

from datetime import datetime

from test_helpers import assertions as ax, constants as k, factories as f, fixtures as fx
from test_helpers import (
    ApiErrorId,
    ENGINEER_2,
    FACILITY_MANAGER,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


def _instant(value):
    """Parse an ISO 8601 UTC timestamp into an aware datetime for instant comparison."""
    assert value, f"expected an ISO 8601 UTC timestamp, got {value!r}"
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _request_changes(api, order_id, reason):
    """Send a proposed route back for rework, as a `FacilityManager`."""
    return api.request_route_changes(order_id, {"reason": reason}, FACILITY_MANAGER)


def _assert_port_free(api, port_id, label):
    port = fx.read_port(api, port_id)
    assert port["status"] == "FREE", (
        f"{label}.status: expected FREE after the pool was handed back, got {port['status']}"
    )
    assert port.get("assigned_order_id") is None, (
        f"{label}.assigned_order_id: expected no holder, got {port['assigned_order_id']!r}"
    )


def _assert_port_reserved_by(api, port_id, order_id, label):
    port = fx.read_port(api, port_id)
    assert port["status"] == "RESERVED", (
        f"{label}.status: expected RESERVED while the route is pinned, got {port['status']}"
    )
    assert port["assigned_order_id"] == order_id, (
        f"{label}.assigned_order_id: expected the holding order {order_id}, "
        f"got {port['assigned_order_id']!r}"
    )


class TestRouteRevisionCycle:
    """`ROUTE_PROPOSED` ⇄ `CHANGES_REQUESTED`, twice around and no further."""

    CONTRACT = {
        "billing_mode": "COMMITTED_ONLY",
        "committed_cabinet_count": 2,
        "power_commit_kw": 20.0,
        "cross_connect_cap": 4,
    }

    def _first_proposal(self, api):
        """A `ROUTE_PROPOSED` SMF order holding the first of two free port pairs."""
        scenario = fx.setup_routed_order(
            api, contract=self.CONTRACT, port_pairs=2, media_type="SMF"
        )
        return scenario

    def _two_laps(self, api):
        """The rework cycle traversed twice: the second pair is proposed and sent back,
        and the third proposal returns to the first pair."""
        scenario = self._first_proposal(api)
        order_id = scenario.order["id"]
        a, z = fx.a_ports(scenario), fx.z_ports(scenario)

        validate_success(_request_changes(api, order_id, "A-side panel is on the wrong busway"))
        fx.propose_route(api, order_id, a[1]["id"], z[1]["id"])
        validate_success(_request_changes(api, order_id, "Customer asked for the diverse Z-side port"))
        fx.propose_route(api, order_id, a[0]["id"], z[0]["id"])
        return scenario

    def test_change_request_hands_the_reserved_pair_back_and_raises_the_count(self, api):
        """PRD §3.5: "A `FacilityManager` or a `CustomerAdmin` who dislikes a proposed route sends it back with a `reason`, moving `ROUTE_PROPOSED` → `CHANGES_REQUESTED`."
        PRD §3.5: "The pool is conserved rather than leaked: `revision_count` rises by one, both currently reserved ports return to `FREE` with `assigned_order_id` cleared, and `a_end_port_id`, `z_end_port_id` and `path_hops` are cleared back to unset and an empty list."

        Design: Difficulty/non_linear_state_machine/route_revision_cycle_bounded_at_two_conserves_port_pool
        """
        scenario = self._first_proposal(api)
        order_id = scenario.order["id"]
        a, z = fx.a_ports(scenario), fx.z_ports(scenario)

        validate_success(_request_changes(api, order_id, "A-side panel is on the wrong busway"))

        order = fx.read_order(api, order_id)
        assert order["status"] == "CHANGES_REQUESTED", (
            f"order.status: expected CHANGES_REQUESTED, got {order['status']}"
        )
        assert order["revision_count"] == 1, (
            f"order.revision_count: expected 1 after one change request, got {order['revision_count']}"
        )
        assert order.get("a_end_port_id") is None, (
            f"order.a_end_port_id must be cleared back to unset, got {order['a_end_port_id']!r}"
        )
        assert order.get("z_end_port_id") is None, (
            f"order.z_end_port_id must be cleared back to unset, got {order['z_end_port_id']!r}"
        )
        assert order["path_hops"] == [], (
            f"order.path_hops must be cleared back to an empty list, got {order['path_hops']!r}"
        )
        _assert_port_free(api, a[0]["id"], "PP-A/1")
        _assert_port_free(api, z[0]["id"], "PP-Z/1")

    def test_second_lap_repins_the_freed_pool_onto_the_new_pair(self, api):
        """PRD §3.5: "Routing is exclusive to a `ProvisioningEngineer` and moves the order `SUBMITTED` → `ROUTE_PROPOSED` or, on a second attempt, `CHANGES_REQUESTED` → `ROUTE_PROPOSED`; both entry paths apply identical guards."
        PRD §3.5: "On acceptance both ports move `FREE` → `RESERVED` with `assigned_order_id` set to this order, the two port references and the hop list are pinned onto the order, `proposed_by_user_id` records the acting `X-User-ID`, and the order's `version` increments."

        Design: Difficulty/non_linear_state_machine/route_revision_cycle_bounded_at_two_conserves_port_pool
        """
        scenario = self._first_proposal(api)
        order_id = scenario.order["id"]
        a, z = fx.a_ports(scenario), fx.z_ports(scenario)

        validate_success(_request_changes(api, order_id, "A-side panel is on the wrong busway"))
        fx.propose_route(api, order_id, a[1]["id"], z[1]["id"])

        order = fx.read_order(api, order_id)
        assert order["status"] == "ROUTE_PROPOSED", (
            f"order.status: expected ROUTE_PROPOSED on the second lap, got {order['status']}"
        )
        assert order["a_end_port_id"] == a[1]["id"], (
            f"order.a_end_port_id: expected the newly proposed PP-A/2, got {order['a_end_port_id']!r}"
        )
        assert order["z_end_port_id"] == z[1]["id"], (
            f"order.z_end_port_id: expected the newly proposed PP-Z/2, got {order['z_end_port_id']!r}"
        )
        _assert_port_reserved_by(api, a[1]["id"], order_id, "PP-A/2")
        _assert_port_reserved_by(api, z[1]["id"], order_id, "PP-Z/2")
        _assert_port_free(api, a[0]["id"], "PP-A/1")
        _assert_port_free(api, z[0]["id"], "PP-Z/1")

    def test_third_change_request_is_refused_once_two_revisions_are_spent(self, api):
        """PRD §3.5: "The cycle `ROUTE_PROPOSED` → `CHANGES_REQUESTED` → `ROUTE_PROPOSED` may repeat only while `revision_count` is strictly below two; a third change request is refused with `ERR_REVISION_LIMIT_REACHED`, at which point the order must be approved or abandoned."
        PRD §2.5: "The order's `revision_count` is strictly below two, otherwise `ERR_REVISION_LIMIT_REACHED` (409)."

        Design: Difficulty/non_linear_state_machine/route_revision_cycle_bounded_at_two_conserves_port_pool
        """
        scenario = self._two_laps(api)
        order_id = scenario.order["id"]

        assert fx.read_order(api, order_id)["revision_count"] == 2, (
            "two laps of the rework cycle must leave revision_count at 2"
        )

        validate_error(
            _request_changes(api, order_id, "Third bite at the cherry"),
            ApiErrorId.ERR_REVISION_LIMIT_REACHED,
        )

        order = fx.read_order(api, order_id)
        assert order["status"] == "ROUTE_PROPOSED", (
            f"a refused change request leaves the order in ROUTE_PROPOSED, got {order['status']}"
        )
        assert order["revision_count"] == 2, (
            f"a refused change request must not raise revision_count, got {order['revision_count']}"
        )

    def test_order_refused_a_third_revision_is_still_approvable(self, api):
        """PRD §3.5: "Approval belongs to a `FacilityManager`."
        PRD §3.5: "The order must be in `ROUTE_PROPOSED`, its contract must be `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`) and not on credit hold (`ERR_CREDIT_HOLD_ACTIVE`), and both pinned ports must still be `RESERVED` with `assigned_order_id` naming this order, otherwise `ERR_PORT_UNAVAILABLE`."

        Design: Difficulty/non_linear_state_machine/route_revision_cycle_bounded_at_two_conserves_port_pool
        """
        scenario = self._two_laps(api)
        order_id = scenario.order["id"]

        validate_error(
            _request_changes(api, order_id, "Third bite at the cherry"),
            ApiErrorId.ERR_REVISION_LIMIT_REACHED,
        )
        fx.move_order(api, order_id, "APPROVED")

        order = fx.read_order(api, order_id)
        assert order["status"] == "APPROVED", (
            f"the refused revision left an approvable ROUTE_PROPOSED order, so approval must "
            f"succeed; got {order['status']}"
        )

    def test_only_the_last_proposed_pair_is_held_after_three_proposals(self, api):
        """PRD §3.5: "Over its life a port moves between `FREE`, `RESERVED` (pinned by a route proposal), `ASSIGNED` (physically patched) and `QUARANTINED` (reclaimed and cooling down), and `assigned_order_id` names the order holding it while it is reserved or assigned."
        PRD §3.5: "The pool is conserved rather than leaked: `revision_count` rises by one, both currently reserved ports return to `FREE` with `assigned_order_id` cleared, and `a_end_port_id`, `z_end_port_id` and `path_hops` are cleared back to unset and an empty list."
        PRD §3.5: "On acceptance both ports move `FREE` → `RESERVED` with `assigned_order_id` set to this order, the two port references and the hop list are pinned onto the order, `proposed_by_user_id` records the acting `X-User-ID`, and the order's `version` increments."

        Design: Difficulty/non_linear_state_machine/route_revision_cycle_bounded_at_two_conserves_port_pool
        """
        scenario = self._two_laps(api)
        order_id = scenario.order["id"]
        a, z = fx.a_ports(scenario), fx.z_ports(scenario)

        order = fx.read_order(api, order_id)
        assert order["a_end_port_id"] == a[0]["id"], (
            f"order.a_end_port_id: expected the third proposal's PP-A/1, got {order['a_end_port_id']!r}"
        )
        assert order["z_end_port_id"] == z[0]["id"], (
            f"order.z_end_port_id: expected the third proposal's PP-Z/1, got {order['z_end_port_id']!r}"
        )
        _assert_port_reserved_by(api, a[0]["id"], order_id, "PP-A/1")
        _assert_port_reserved_by(api, z[0]["id"], order_id, "PP-Z/1")
        _assert_port_free(api, a[1]["id"], "PP-A/2")
        _assert_port_free(api, z[1]["id"], "PP-Z/2")

        held = [
            port
            for port in (fx.read_port(api, p["id"]) for p in scenario.ports)
            if port.get("assigned_order_id") == order_id
        ]
        assert len(held) == 2, (
            f"exactly one port pair may be held after three proposals and two hand-backs, got "
            f"{len(held)}"
        )


class TestAuthorizationAndExecutionDimensions:
    """Two dimensions on one ticket row: one reads the other, then cancels it."""

    CONTRACT = {
        "billing_mode": "COMMITTED_ONLY",
        "committed_cabinet_count": 1,
        "power_commit_kw": 20.0,
        "remote_hands_included_minutes": 15,
    }
    HIGH_DEADLINE = "2026-08-01T02:00:00Z"
    SEGMENT = ("2026-08-01T09:00:00Z", "2026-08-01T09:20:00Z")

    def _pending_ticket(self, api):
        """A `HIGH`-severity ticket sitting at `PENDING_AUTHORIZATION` × `QUEUED`."""
        scenario = fx.setup_ticket_scenery(
            api, contract=self.CONTRACT, cabinet={"cabinet_code": "C01", "rated_power_kw": 20.0}
        )
        fx.raise_ticket(api, scenario, severity="HIGH", description="Swap a failed PSU")
        return scenario

    def _authorized_and_dispatched(self, api):
        scenario = self._pending_ticket(api)
        fx.authorize_ticket(api, scenario.ticket["id"], scenario.contacts[1]["id"])
        fx.dispatch_ticket(api, scenario.ticket["id"])
        return scenario

    def _revoked(self, api):
        scenario = self._authorized_and_dispatched(api)
        fx.authorize_ticket(
            api, scenario.ticket["id"], scenario.contacts[1]["id"], to_state="REVOKED"
        )
        return scenario

    def test_dispatch_is_refused_while_the_authorization_dimension_is_pending(self, api):
        """PRD §3.6: "It requires `authorization_state` to be `AUTHORIZED` — a ticket in `PENDING_AUTHORIZATION`, `DENIED` or `REVOKED` is refused with `ERR_TICKET_NOT_AUTHORIZED` even though its execution dimension is legitimately `QUEUED` — and requires the target cabinet to be `INSTALLED` or `ACTIVE`, otherwise `ERR_CABINET_NOT_OPERATIONAL`."
        PRD §3.6: "On success `dispatched_at` is stamped from the logical clock and `sla_breached` is set true only when `dispatched_at` is strictly later than `response_deadline_at`; a dispatch landing exactly on the deadline instant has met the commitment, not breached it."

        Design: Difficulty/non_linear_state_machine/revoke_authorization_cancels_dispatched_execution_dimension
        """
        scenario = self._pending_ticket(api)

        validate_error(
            api.dispatch_ticket(scenario.ticket["id"], ENGINEER_2),
            ApiErrorId.ERR_TICKET_NOT_AUTHORIZED,
        )

        ticket = fx.read_ticket(api, scenario.ticket["id"])
        assert ticket["authorization_state"] == "PENDING_AUTHORIZATION", (
            f"ticket.authorization_state: expected PENDING_AUTHORIZATION, "
            f"got {ticket['authorization_state']}"
        )
        assert ticket["execution_state"] == "QUEUED", (
            f"a refused dispatch leaves the execution dimension at QUEUED, "
            f"got {ticket['execution_state']}"
        )
        assert ticket.get("dispatched_at") is None, (
            f"ticket.dispatched_at is stamped only on a successful dispatch, "
            f"got {ticket['dispatched_at']!r}"
        )

    def test_authorization_advances_alone_and_derives_the_high_severity_deadline(self, api):
        """PRD §3.6: "Authorizing a `PENDING_AUTHORIZATION` ticket stamps `authorized_at` from the logical clock and derives `response_deadline_at` from it, leaving `execution_state` untouched because the dimensions are independent."
        PRD §3.6: "`response_deadline_at` is `authorized_at` advanced by 30 minutes for a `CRITICAL` ticket, by 120 minutes for a `HIGH` ticket, and by 480 minutes — eight hours — for a `STANDARD` ticket."

        Design: Difficulty/non_linear_state_machine/revoke_authorization_cancels_dispatched_execution_dimension
        """
        scenario = self._pending_ticket(api)

        fx.authorize_ticket(api, scenario.ticket["id"], scenario.contacts[1]["id"])

        ticket = fx.read_ticket(api, scenario.ticket["id"])
        assert ticket["authorization_state"] == "AUTHORIZED", (
            f"ticket.authorization_state: expected AUTHORIZED, got {ticket['authorization_state']}"
        )
        assert ticket["execution_state"] == "QUEUED", (
            f"authorization must leave the execution dimension untouched at QUEUED, "
            f"got {ticket['execution_state']}"
        )
        assert _instant(ticket["authorized_at"]) == _instant(k.DEFAULT_CLOCK), (
            f"ticket.authorized_at: expected the logical clock {k.DEFAULT_CLOCK}, "
            f"got {ticket['authorized_at']}"
        )
        assert _instant(ticket["response_deadline_at"]) == _instant(self.HIGH_DEADLINE), (
            f"ticket.response_deadline_at: expected {self.HIGH_DEADLINE} for a HIGH ticket "
            f"authorized at {k.DEFAULT_CLOCK}, got {ticket['response_deadline_at']}"
        )

    def test_dispatch_after_authorization_moves_only_the_execution_dimension(self, api):
        """PRD §3.6: "Dispatch is exclusive to a `ProvisioningEngineer`, takes no body fields, and moves `execution_state` from `QUEUED` to `DISPATCHED`."
        PRD §3.6: "On success `dispatched_at` is stamped from the logical clock and `sla_breached` is set true only when `dispatched_at` is strictly later than `response_deadline_at`; a dispatch landing exactly on the deadline instant has met the commitment, not breached it."

        Design: Difficulty/non_linear_state_machine/revoke_authorization_cancels_dispatched_execution_dimension
        """
        scenario = self._authorized_and_dispatched(api)

        ticket = fx.read_ticket(api, scenario.ticket["id"])
        assert ticket["execution_state"] == "DISPATCHED", (
            f"ticket.execution_state: expected DISPATCHED, got {ticket['execution_state']}"
        )
        assert ticket["authorization_state"] == "AUTHORIZED", (
            f"dispatch must leave the authorization dimension at AUTHORIZED, "
            f"got {ticket['authorization_state']}"
        )
        assert _instant(ticket["dispatched_at"]) == _instant(k.DEFAULT_CLOCK), (
            f"ticket.dispatched_at: expected the logical clock {k.DEFAULT_CLOCK}, "
            f"got {ticket['dispatched_at']}"
        )
        ax.assert_ticket_labor(ticket, sla_breached=False)

    def test_revocation_drags_the_dispatched_execution_dimension_to_cancelled(self, api):
        """PRD §3.6: "Revoking an already `AUTHORIZED` ticket is refused with `ERR_INVALID_STATE` once execution has reached `COMPLETED`; otherwise it forces `execution_state` to `CANCELLED` from whichever of `QUEUED`, `DISPATCHED` or `IN_PROGRESS` it currently holds."
        PRD §3.6: "`authorization_state` walks `PENDING_AUTHORIZATION` → `AUTHORIZED`, `PENDING_AUTHORIZATION` → `DENIED` or `AUTHORIZED` → `REVOKED`, while `execution_state` walks `QUEUED` → `DISPATCHED` → `COMPLETED`, with `CANCELLED` as its abandonment state and `IN_PROGRESS` as an intermediate execution value."

        Design: Difficulty/non_linear_state_machine/revoke_authorization_cancels_dispatched_execution_dimension
        """
        scenario = self._revoked(api)

        ticket = fx.read_ticket(api, scenario.ticket["id"])
        assert ticket["authorization_state"] == "REVOKED", (
            f"ticket.authorization_state: expected REVOKED, got {ticket['authorization_state']}"
        )
        assert ticket["execution_state"] == "CANCELLED", (
            f"revocation forces the execution dimension from DISPATCHED to CANCELLED, "
            f"got {ticket['execution_state']}"
        )

    def test_completion_is_impossible_once_authorization_has_been_revoked(self, api):
        """PRD §3.6: "Completion is also exclusive to a `ProvisioningEngineer`, requires the ticket to be `DISPATCHED` with `authorization_state` still `AUTHORIZED` (`ERR_TICKET_NOT_AUTHORIZED` otherwise), and carries `work_segments`, the labour actually performed."
        PRD §2.5: "This includes terminal-state lockdown — `TERMINATED`, `RELEASED`, `REMOVED`, `DECOMMISSIONED`, `ABORTED`, `CLOSED`, `CANCELLED` and `CHECKED_OUT` accept no further transitions — and the rejection of a replayed trigger."

        Design: Difficulty/non_linear_state_machine/revoke_authorization_cancels_dispatched_execution_dimension
        """
        scenario = self._revoked(api)

        validate_error_is_one_of(
            api.complete_ticket(
                scenario.ticket["id"],
                f.complete_ticket_payload(f.work_segment(*self.SEGMENT)),
                ENGINEER_2,
            ),
            [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_TICKET_NOT_AUTHORIZED],
        )

        ticket = fx.read_ticket(api, scenario.ticket["id"])
        assert ticket["execution_state"] == "CANCELLED", (
            f"a refused completion leaves the execution dimension at CANCELLED, "
            f"got {ticket['execution_state']}"
        )
        assert ticket.get("completed_at") is None, (
            f"ticket.completed_at is stamped only when execution_state becomes COMPLETED, "
            f"got {ticket['completed_at']!r}"
        )

    def test_revoked_ticket_consumes_no_bundled_minutes_and_no_money(self, api):
        """PRD §3.6: "The contract's `remote_hands_remaining_minutes` is reduced by `included_increments_applied` multiplied by 15."
        PRD §3.6: "When `labor_charge_usd` is greater than zero, an invoice line of `line_type` `REMOTE_HANDS` is appended carrying that amount, a `quantity` equal to `billable_increments` minus `included_increments_applied`, and `included_minutes_consumed` equal to the absorbed increments multiplied by 15."
        PRD §3.6: "The ticket's `completed_at` is stamped, `execution_state` becomes `COMPLETED`, the contract's `billed_total_usd` is refreshed, and both the ticket's and the contract's `version` increment."

        Design: Difficulty/non_linear_state_machine/revoke_authorization_cancels_dispatched_execution_dimension
        """
        scenario = self._revoked(api)

        validate_error_is_one_of(
            api.complete_ticket(
                scenario.ticket["id"],
                f.complete_ticket_payload(f.work_segment(*self.SEGMENT)),
                ENGINEER_2,
            ),
            [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_TICKET_NOT_AUTHORIZED],
        )

        lines = [
            line
            for line in fx.invoice_lines(api, scenario.contract_id)
            if line.get("contract_id") == scenario.contract_id
        ]
        assert lines == [], (
            f"a ticket that never completed appends no invoice line, got "
            f"{[line['line_type'] for line in lines]}"
        )
        contract = fx.read_contract(api, scenario.contract_id)
        ax.assert_contract_billing_rollup(
            contract, remote_hands_remaining_minutes=15, billed_total_usd=0.00
        )
