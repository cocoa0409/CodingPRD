"""TransportLeg state-mutation endpoints: arrive, report-break."""
from __future__ import annotations

from flask import Blueprint

from ..auth import ROLE_LAB_TECH, require_roles
from ..clock import now
from ..errors import (
    err_invalid_state,
    err_leg_already_arrived,
    err_time_order_invalid,
)
from ..helpers import parse_iso8601, require_json_object
from ..responses import ok
from ..services import calculations as calc
from ..services.audit import write_audit_event
from ..services.lookups import (
    get_lab_order,
    get_specimen,
    get_test_panel,
    get_transport_leg,
)
from ..services.serialize import transport_leg_view
from ..services.workflows import bump, issue_retest
from ..store import store

bp = Blueprint("transport_legs", __name__)


@bp.route("/transport-legs/<lid>/arrive", methods=["POST"])
@require_roles(ROLE_LAB_TECH)
def arrive_leg(lid, **_):
    body = require_json_object()
    arrived_at = parse_iso8601(body.get("arrived_at"), "arrived_at")

    with store().lock:
        leg = get_transport_leg(lid)
        # Already arrived (priority 5-special, separate error id per scaffold)
        if leg["status"] == "ARRIVED":
            raise err_leg_already_arrived()
        if leg["status"] != "DEPARTED":
            raise err_invalid_state(f"TransportLeg must be DEPARTED to arrive (was {leg['status']})")
        # Time order (priority 11)
        if arrived_at < leg["departed_at"]:
            raise err_time_order_invalid("arrived_at must be >= departed_at")

        leg["status"] = "ARRIVED"
        leg["arrived_at"] = arrived_at
        # TransportLeg has no version/updated_at — append-once-mutated-once row.

        # Cascade ONLY if final leg to LAB_MAIN
        if leg["to_location"] == calc.LAB_LOCATION_CODE:
            specimen = get_specimen(leg["specimen_id"])
            order = get_lab_order(specimen["lab_order_id"])
            panel = get_test_panel(order["panel_id"])
            exceeded = calc.specimen_stability_exceeded(
                specimen["collected_at"], arrived_at, panel["stability_minutes"]
            )
            if exceeded:
                specimen["status"] = "REJECTED"
                specimen["rejected_reason"] = "STABILITY_EXCEEDED"
                specimen["received_at"] = None
                bump(specimen)
                order["status"] = "REJECTED"
                bump(order)
                # Auto-issue retest
                issue_retest(order, reason="SPECIMEN_REJECTED")
                # Audit
                write_audit_event(
                    event_type="SPECIMEN_REJECTED",
                    lab_order_id=order["id"],
                    actor_id="system",
                    payload={"rejected_reason": "STABILITY_EXCEEDED"},
                )
                write_audit_event(
                    event_type="RETEST_ISSUED",
                    lab_order_id=order["id"],
                    actor_id="system",
                    payload={"reason": "SPECIMEN_REJECTED"},
                )
            else:
                specimen["received_at"] = arrived_at
                specimen["status"] = "RECEIVED"
                bump(specimen)
                order["status"] = "RECEIVED"
                bump(order)
    return ok(transport_leg_view(leg))


@bp.route("/transport-legs/<lid>/report-break", methods=["POST"])
@require_roles(ROLE_LAB_TECH)
def report_break(lid, **_):
    require_json_object()  # ignore body content
    with store().lock:
        leg = get_transport_leg(lid)
        if leg["status"] != "DEPARTED":
            raise err_invalid_state(f"TransportLeg must be DEPARTED to report break (was {leg['status']})")

        leg["status"] = "BROKEN"
        specimen = get_specimen(leg["specimen_id"])
        specimen["status"] = "REJECTED"
        specimen["rejected_reason"] = "CHAIN_BROKEN"
        bump(specimen)
        order = get_lab_order(specimen["lab_order_id"])
        order["status"] = "REJECTED"
        bump(order)
        issue_retest(order, reason="SPECIMEN_REJECTED")
        write_audit_event(
            event_type="SPECIMEN_REJECTED",
            lab_order_id=order["id"],
            actor_id="system",
            payload={"rejected_reason": "CHAIN_BROKEN"},
        )
        write_audit_event(
            event_type="RETEST_ISSUED",
            lab_order_id=order["id"],
            actor_id="system",
            payload={"reason": "SPECIMEN_REJECTED"},
        )
    return ok(transport_leg_view(leg))
