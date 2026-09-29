"""Meal-count reconciliation and period closure."""
from flask import Blueprint

import serialize
from auth import authenticate
from db import base_row, db, touch
from errors import api_error
from response import created, ok
from routes.common import BS, DSM, PA, get_community, get_reconciliation
from services import calc, derive
from shape import body_json, opt_str, req_date, req_str

bp = Blueprint("reconciliations", __name__)


@bp.get("/reconciliations/<reconciliation_id>")
def read_reconciliation(reconciliation_id):
    authenticate([PA, DSM, BS])
    return ok(serialize.reconciliation(get_reconciliation(reconciliation_id)))


@bp.post("/reconciliations")
def create_reconciliation():
    authenticate([BS])
    body = body_json()
    community_id = req_str(body, "community_id")
    start_str, start_date = req_date(body, "period_start_date")
    end_str, end_date = req_date(body, "period_end_date")
    if end_date < start_date:
        raise api_error(
            "ERR_INVALID_REQUEST",
            "period_end_date must not precede period_start_date",
        )

    get_community(community_id)

    clash = derive.finalized_period_overlaps(community_id, start_str, end_str)
    if clash is not None:
        raise api_error(
            "ERR_PERIOD_CLOSED",
            "The period intersects FINALIZED reconciliation %s" % clash["id"],
        )

    figures = calc.meal_count_reconciliation(community_id, start_str, end_str)

    row = base_row()
    row.update({
        "community_id": community_id,
        "period_start_date": start_str,
        "period_end_date": end_str,
        "variance_note": None,
        "status": "RECONCILED",
        "finalized_by_user_id": None,
    })
    row.update(figures)
    db.reconciliations[row["id"]] = row
    return created(serialize.reconciliation(row))


@bp.post("/reconciliations/<reconciliation_id>/finalize")
def finalize_reconciliation(reconciliation_id):
    ctx = authenticate([BS])
    body = body_json()
    variance_note = opt_str(body, "variance_note")

    row = get_reconciliation(reconciliation_id)
    if row["status"] != "RECONCILED":
        raise api_error("ERR_INVALID_STATE", "Only a RECONCILED reconciliation may be finalized")

    fresh = calc.meal_count_reconciliation(
        row["community_id"], row["period_start_date"], row["period_end_date"]
    )
    for key in (
        "ticket_ledger_total_cents",
        "census_projection_total_cents",
        "net_billable_total_cents",
    ):
        if fresh[key] != row[key]:
            raise api_error(
                "ERR_RECONCILIATION_STALE",
                "%s has drifted from %s to %s since the reconciliation was created"
                % (key, row[key], fresh[key]),
            )

    community = db.communities.get(row["community_id"])
    tolerance = community["variance_tolerance_cents"] if community is not None else 0
    if abs(row["variance_cents"]) > tolerance:
        if variance_note is None or variance_note.strip() == "":
            raise api_error(
                "ERR_VARIANCE_UNRESOLVED",
                "A variance of %d exceeds the tolerance of %d and needs a variance_note"
                % (row["variance_cents"], tolerance),
            )

    if variance_note is not None:
        row["variance_note"] = variance_note
    row["status"] = "FINALIZED"
    row["finalized_by_user_id"] = ctx["user_id"]
    touch(row)

    venue_ids = set(
        v["id"] for v in db.venues.values() if v["community_id"] == row["community_id"]
    )
    for ticket in db.tickets.values():
        if ticket["venue_id"] not in venue_ids or ticket["status"] != "SERVED":
            continue
        if not (row["period_start_date"] <= ticket["service_date"] <= row["period_end_date"]):
            continue
        ticket["status"] = "BILLED"
        ticket["billed_reconciliation_id"] = row["id"]
        touch(ticket)

    return ok(serialize.reconciliation(row))
