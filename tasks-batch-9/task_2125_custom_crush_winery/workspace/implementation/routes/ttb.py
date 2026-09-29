"""Bonded reporting: periods, reconciliation variants, filing and amendment."""

from decimal import Decimal

from flask import Blueprint

import domain
from auth import CLIENT_REP, COMPLIANCE_OFFICER, FACILITY_ADMIN, guard, scope
from envelope import respond
from errors import (
    ApiError,
    ERR_CLIENT_NOT_ACTIVE,
    ERR_INVALID_INTERVAL,
    ERR_PERIOD_NOT_CLOSED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_TTB_PERIOD_OVERLAP,
    ERR_TTB_VARIANCE_UNBALANCED,
)
from helpers import declared, run_list
from store import db, iso, new_entity, touch
from validation import v_datetime, v_enum, v_string

D = Decimal
bp = Blueprint("ttb", __name__)

REPORT_ACTIONS = {
    "PREPARE": [COMPLIANCE_OFFICER],
    "RECALL": [COMPLIANCE_OFFICER],
    "FILE": [COMPLIANCE_OFFICER],
    "AMEND": [COMPLIANCE_OFFICER],
}
VARIANTS = {"BONDED", "GROSS"}
BLOCKING_STATUSES = ("OPEN", "PREPARED", "FILED", "AMENDED")
READ_ROLES = [FACILITY_ADMIN, COMPLIANCE_OFFICER, CLIENT_REP]


@bp.route("/ttb-reports", methods=["POST"])
def create_report():
    ctx = guard([COMPLIANCE_OFFICER])
    body = ctx.body
    client_id = v_string(body, "client_id")
    start_raw, start_dt = v_datetime(body, "period_start")
    end_raw, end_dt = v_datetime(body, "period_end")

    domain.get_client(client_id)

    # Rung 62 -- no overlap with another live report for the same client.
    for existing in domain.client_reports(client_id):
        if existing["status"] not in BLOCKING_STATUSES:
            continue
        if start_dt < existing["_pe_dt"] and existing["_ps_dt"] < end_dt:
            raise ApiError(ERR_TTB_PERIOD_OVERLAP,
                           "The window overlaps another report for this client.")

    # Rung 65 -- interval sanity.
    if not (end_dt > start_dt):
        raise ApiError(ERR_INVALID_INTERVAL,
                       "period_end must be strictly after period_start.")

    report = new_entity({
        "client_id": client_id,
        "period_start": start_raw,
        "period_end": end_raw,
        "variant": "BONDED",
        "status": "OPEN",
        "prepared_by_user_id": None,
        "filed_by_user_id": None,
        "opening_gallons": D(0),
        "produced_gallons": D(0),
        "removed_taxpaid_gallons": D(0),
        "removed_in_bond_gallons": D(0),
        "loss_gallons": D(0),
        "closing_gallons": D(0),
        "variance_gallons": D(0),
        "amendment_count": 0,
        "filed_at": None,
        "_ps_dt": start_dt,
        "_pe_dt": end_dt,
    })
    db.reports[report["id"]] = report
    return respond(domain.serialize(report), 201)


@bp.route("/ttb-reports/<report_id>", methods=["GET"])
def read_report(report_id):
    ctx = guard(READ_ROLES, read_body=False)
    report = domain.get_report(report_id)
    scope(ctx, report["client_id"])
    return respond(domain.serialize(report))


@bp.route("/ttb-reports", methods=["GET"])
def list_reports():
    ctx = guard(READ_ROLES, read_body=False)
    return run_list(db.reports.values(), ctx, domain.serialize,
                    owner_fn=lambda r: r["client_id"],
                    filters=(("client_id", "client_id"), ("status", "status")))


@bp.route("/ttb-reports/<report_id>/transitions", methods=["POST"])
def report_transitions(report_id):
    ctx = guard([COMPLIANCE_OFFICER], REPORT_ACTIONS)
    body = ctx.body
    action = v_enum(body, "action", set(REPORT_ACTIONS))
    variant = None
    if action == "PREPARE":
        variant = v_enum(body, "variant", VARIANTS, required=False, default=None,
                         nullable=True)

    report = domain.get_report(report_id)
    client = db.clients.get(report["client_id"])

    if action == "PREPARE":
        declared(report["status"] in ("OPEN", "AMENDED"))
        # Rung 40 -- the client must still be on the books.
        if client is None or client["status"] not in ("ACTIVE", "SUSPENDED"):
            raise ApiError(ERR_CLIENT_NOT_ACTIVE,
                           "The reporting client is not ACTIVE or SUSPENDED.")
        if variant is not None:
            report["variant"] = variant
        domain.ttb_reconciliation(report)
        report["prepared_by_user_id"] = ctx.user_id
        report["status"] = "PREPARED"
    elif action == "RECALL":
        declared(report["status"] == "PREPARED")
        for field in ("opening_gallons", "produced_gallons",
                      "removed_taxpaid_gallons", "removed_in_bond_gallons",
                      "loss_gallons", "closing_gallons", "variance_gallons"):
            report[field] = D(0)
        report["prepared_by_user_id"] = None
        report["status"] = "OPEN"
    elif action == "FILE":
        declared(report["status"] == "PREPARED")
        # Rung 50 -- segregation of duties.
        if ctx.user_id == report["prepared_by_user_id"]:
            raise ApiError(ERR_SEGREGATION_OF_DUTIES,
                           "The filing officer must differ from the preparer.")
        # Rung 65 -- the period must be closed.
        if report["_pe_dt"] > db.now():
            raise ApiError(ERR_PERIOD_NOT_CLOSED,
                           "The reporting period has not closed yet.")
        # Rung 85 -- the books must balance exactly.
        if D(report["variance_gallons"]) != D(0):
            raise ApiError(ERR_TTB_VARIANCE_UNBALANCED,
                           "variance_gallons must be exactly 0.00 to file.")
        report["filed_by_user_id"] = ctx.user_id
        report["filed_at"] = iso(db.now())
        report["status"] = "FILED"
        touch(report)
        if client is not None:
            touch(client)
        return respond(domain.serialize(report))
    else:  # AMEND
        declared(report["status"] == "FILED")
        report["amendment_count"] = report["amendment_count"] + 1
        report["status"] = "AMENDED"
        touch(report)
        if client is not None:
            touch(client)
        return respond(domain.serialize(report))

    touch(report)
    return respond(domain.serialize(report))
