"""Emergency remediation order endpoints (PRD 3.8).

Opening and resolving an order are the only two mutating operations the PRD
permits against a project whose ``operational_posture`` is ``FROZEN``, so neither
handler runs the frozen gate.
"""

from decimal import Decimal as D

from flask import Blueprint

import clock
import db
import enums
import middleware as mw
import response
from errors import ApiError
from services import calc, derive, lookup, serialize

bp = Blueprint("remediation", __name__)

REVIEWER = "RegulatoryReviewer"

OPENABLE_PROJECT_STATUSES = ("INJECTION_AUTHORIZED", "INJECTION_ACTIVE", "PISC")
FREEZING_SEVERITIES = ("MAJOR", "CRITICAL")


def _draw_instrument(project):
    """The project's ALLOCATED instrument with the largest emergency bucket."""
    candidates = [i for i in db.instruments_of(project["id"]) if i["status"] == "ALLOCATED"]
    if not candidates:
        return None
    best = candidates[0]
    for instrument in candidates[1:]:
        if instrument["allocated_emergency_usd"] > best["allocated_emergency_usd"]:
            best = instrument
    return best


@bp.post("/ccs/remediation-orders")
@mw.require(REVIEWER)
def open_order():
    payload = mw.body()
    project_id = mw.req_str(payload, "project_id")
    trigger_type = mw.req_enum(payload, "trigger_type", enums.REMEDIATION_TRIGGER)
    severity = mw.req_enum(payload, "severity", enums.REMEDIATION_SEVERITY)
    narrative = mw.req_str(payload, "narrative")

    project = lookup.project(project_id)

    if project["status"] not in OPENABLE_PROJECT_STATUSES:
        raise ApiError(
            "ERR_INVALID_PROJECT_STATE",
            "an order may only be opened while the project is authorized, active or in PISC",
        )

    instrument = _draw_instrument(project)
    draw = calc.reserve_draw(
        severity,
        instrument["allocated_emergency_usd"] if instrument is not None else D("0"),
        project["required_financial_assurance_usd"],
    )

    row = db.base_fields()
    row.update(
        {
            "project_id": project["id"],
            "trigger_type": trigger_type,
            "severity": severity,
            "narrative": narrative,
            "reserve_draw_usd": draw,
            "status": "OPEN",
            "opened_at": clock.now_iso(),
            "resolved_at": None,
        }
    )
    db.remediation_orders[row["id"]] = row

    derive.recompute_open_remediation_count(project)

    if severity in FREEZING_SEVERITIES:
        project["operational_posture"] = "FROZEN"
        derive.suspension_cascade(project)

    if severity == "CRITICAL" and instrument is not None and draw > 0:
        instrument["drawn_usd"] = draw
        instrument["allocated_emergency_usd"] = calc.q2(
            D(instrument["allocated_emergency_usd"]) - draw
        )
        instrument["status"] = "DRAWN"
        db.touch(instrument)
        derive.recompute_allocated_assurance(project, posture=False)

    db.touch(project)
    return response.object_response(serialize.order(row), 201)


@bp.post("/ccs/remediation-orders/<order_id>/resolve")
@mw.require(REVIEWER)
def resolve_order(order_id):
    payload = mw.body()
    mw.req_str(payload, "remediation_summary")

    order = lookup.order(order_id)
    project = db.projects.get(order["project_id"])

    if order["status"] != "OPEN":
        raise ApiError("ERR_INVALID_CLAIM_STATE", "only an OPEN order may be resolved")

    order["status"] = "RESOLVED"
    order["resolved_at"] = clock.now_iso()
    db.touch(order)

    derive.recompute_open_remediation_count(project)

    if project["open_remediation_count"] == 0:
        project["operational_posture"] = (
            "OPEN" if project["assurance_coverage_status"] == "FUNDED" else "RESTRICTED"
        )
        derive.restore_cascade(project)

    db.touch(project)
    return response.object_response(serialize.order(order))
