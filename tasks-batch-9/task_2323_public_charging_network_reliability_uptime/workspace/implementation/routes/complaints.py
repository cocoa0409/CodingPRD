"""Driver complaints and session refunds: two independent dimensions
(PRD §3.9)."""
from flask import Blueprint

import calc
import clock
import db
import lookup
import serialize
import validation
from errors import err
from middleware import endpoint, current_user_id, require_role_for_leg
from response import array_response, object_response, paginate

bp = Blueprint("complaints", __name__)

COMPLAINT_TYPES = ("PAYMENT_DECLINED", "PRICE_MISMATCH", "SESSION_FAILED",
                   "CHARGER_OFFLINE", "BLOCKED_STALL")
DISPOSITIONS = ("LINK_OUTAGE", "NO_FAULT")
REFUND_BASES = ("ENERGY_PRORATED", "FULL_SESSION_GOODWILL")
REFUND_DECISIONS = ("APPROVE", "DENY")
LEDGER_ACTIONS = ("SETTLE", "REVERSE")
TERMINAL_INTAKE_STATES = ("CLOSED", "DISMISSED")
REFUND_IN_FLIGHT_STATES = ("REQUESTED", "APPROVED")


def _no_refund_position(complaint):
    complaint["refund_amount_cents"] = 0
    complaint["retained_amount_cents"] = complaint["session_charged_cents"]


@bp.post("/customer-complaints")
@endpoint("CustomerSupportAgent")
def take_complaint():
    body = validation.json_body()

    raw_station_id = validation.fk(body, "station_id")
    station = lookup.station(raw_station_id) if raw_station_id is not None else None
    raw_port_id = validation.fk(body, "port_id")
    port = lookup.port(raw_port_id) if raw_port_id is not None else None

    validation.as_string(body, "station_id")
    validation.as_string(body, "port_id")
    complaint_type = validation.as_enum(body, "complaint_type", COMPLAINT_TYPES)
    session_started_at = validation.as_datetime(body, "session_started_at")
    session_ended_at = validation.as_datetime(body, "session_ended_at")
    session_energy_kwh = validation.as_number(body, "session_energy_kwh",
                                              minimum=0, places=3)
    session_price_per_kwh_cents = validation.as_int(body, "session_price_per_kwh_cents",
                                                    minimum=0)
    session_charged_cents = validation.as_int(body, "session_charged_cents", minimum=0)
    session_idle_fee_cents = validation.as_int(body, "session_idle_fee_cents",
                                               required=False, default=0, minimum=0)

    if port["station_id"] != station["id"]:
        raise err("ERR_COMPLAINT_PORT_MISMATCH",
                  "The dispenser does not belong to the station named.")

    if not session_ended_at > session_started_at:
        raise err("ERR_SESSION_WINDOW_INVALID",
                  "session_ended_at must be strictly after session_started_at.")

    if session_charged_cents < session_idle_fee_cents:
        raise err("ERR_SESSION_CHARGE_INVALID",
                  "session_charged_cents may not be smaller than the idle-fee component.")

    row = db.base_record()
    row.update({
        "station_id": station["id"],
        "port_id": port["id"],
        "linked_outage_event_id": None,
        "complaint_type": complaint_type,
        "session_started_at": session_started_at,
        "session_ended_at": session_ended_at,
        "session_energy_kwh": session_energy_kwh,
        "session_price_per_kwh_cents": session_price_per_kwh_cents,
        "session_idle_fee_cents": session_idle_fee_cents,
        "session_charged_cents": session_charged_cents,
        "state": "INTAKE",
        "refund_state": "NONE",
        "refund_basis": None,
        "refund_amount_cents": None,
        "retained_amount_cents": None,
        "refund_requested_by_user_id": None,
        "refund_settled_at": None,
    })
    db.complaints[row["id"]] = row
    db.mark_fresh(row)
    return object_response(serialize.customer_complaint(row), 201)


@bp.get("/customer-complaints")
@endpoint()
def list_complaints():
    limit, offset = validation.pagination()
    rows = db.sort_rows(list(db.complaints.values()))
    rows = validation.apply_filters(rows, validation.filters(
        "station_id", "port_id", "linked_outage_event_id", "state", "refund_state"))
    page, total = paginate(rows, limit, offset)
    return array_response([serialize.customer_complaint(r) for r in page],
                          limit, offset, total)


@bp.get("/customer-complaints/<complaint_id>")
@endpoint()
def get_complaint(complaint_id):
    return object_response(serialize.customer_complaint(lookup.complaint(complaint_id)))


@bp.post("/customer-complaints/<complaint_id>/triage")
@endpoint("CustomerSupportAgent")
def triage(complaint_id):
    complaint = lookup.complaint(complaint_id)
    body = validation.json_body()

    raw_outage_id = validation.fk(body, "linked_outage_event_id")
    outage = lookup.outage(raw_outage_id) if raw_outage_id is not None else None

    disposition = validation.as_enum(body, "disposition", DISPOSITIONS)

    if complaint["state"] != "INTAKE":
        raise err("ERR_INVALID_STATE", "Only an INTAKE complaint may be triaged.")

    if disposition == "LINK_OUTAGE":
        if outage is None:
            raise err("ERR_COMPLAINT_OUTAGE_MISMATCH",
                      "LINK_OUTAGE requires a linked_outage_event_id.")
        if outage["port_id"] != complaint["port_id"]:
            raise err("ERR_COMPLAINT_OUTAGE_MISMATCH",
                      "The outage was not reported on the dispenser the complaint names.")
        complaint["linked_outage_event_id"] = outage["id"]
        complaint["state"] = "TRIAGED"
    else:  # NO_FAULT
        if complaint["refund_state"] != "NONE":
            raise err("ERR_INVALID_STATE",
                      "A complaint with refund activity may not be dismissed.")
        complaint["state"] = "DISMISSED"

    db.touch(complaint)
    return object_response(serialize.customer_complaint(complaint))


@bp.post("/customer-complaints/<complaint_id>/close")
@endpoint("CustomerSupportAgent")
def close_complaint(complaint_id):
    complaint = lookup.complaint(complaint_id)

    if complaint["state"] in TERMINAL_INTAKE_STATES:
        raise err("ERR_ALREADY_TERMINAL",
                  "The complaint's intake dimension is already terminal.")
    if complaint["state"] != "TRIAGED":
        raise err("ERR_INVALID_STATE", "Only a TRIAGED complaint may be closed.")
    if complaint["refund_state"] in REFUND_IN_FLIGHT_STATES:
        raise err("ERR_REFUND_IN_FLIGHT",
                  "A complaint with a refund in flight may not be closed.")

    complaint["state"] = "CLOSED"
    db.touch(complaint)
    return object_response(serialize.customer_complaint(complaint))


@bp.post("/customer-complaints/<complaint_id>/refund-requests")
@endpoint("CustomerSupportAgent")
def request_refund(complaint_id):
    complaint = lookup.complaint(complaint_id)
    body = validation.json_body()
    basis = validation.as_enum(body, "refund_basis", REFUND_BASES)

    if complaint["refund_state"] != "NONE":
        raise err("ERR_INVALID_STATE",
                  "A refund has already been filed on this complaint.")
    if complaint["state"] != "TRIAGED":
        raise err("ERR_INVALID_STATE",
                  "The complaint must be TRIAGED before a refund may be filed.")

    if basis == "FULL_SESSION_GOODWILL":
        outage = (db.outages.get(complaint["linked_outage_event_id"])
                  if complaint["linked_outage_event_id"] else None)
        if outage is None:
            raise err("ERR_REFUND_BASIS_NOT_ELIGIBLE",
                      "A goodwill refund requires a linked outage event.")
        if outage["fault_class"] != "CRITICAL":
            raise err("ERR_REFUND_BASIS_NOT_ELIGIBLE",
                      "A goodwill refund requires a CRITICAL linked outage.")
        if not calc.outage_overlaps_session(outage, complaint):
            raise err("ERR_REFUND_BASIS_NOT_ELIGIBLE",
                      "The outage window does not overlap the disputed session.")

    refund = calc.session_refund_amount(complaint, basis)
    complaint["refund_basis"] = basis
    complaint["refund_amount_cents"] = refund
    complaint["retained_amount_cents"] = complaint["session_charged_cents"] - refund
    complaint["refund_requested_by_user_id"] = current_user_id()
    complaint["refund_state"] = "REQUESTED"
    db.touch(complaint)
    return object_response(serialize.customer_complaint(complaint))


@bp.post("/customer-complaints/<complaint_id>/refund-decisions")
@endpoint("ComplianceAuditor")
def decide_refund(complaint_id):
    complaint = lookup.complaint(complaint_id)
    body = validation.json_body()
    decision = validation.as_enum(body, "decision", REFUND_DECISIONS)

    if complaint["refund_state"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Only a REQUESTED refund may be decided.")

    if decision == "APPROVE":
        if (complaint["refund_amount_cents"] or 0) > complaint["session_charged_cents"]:
            raise err("ERR_REFUND_EXCEEDS_SESSION_CHARGE",
                      "The refund may not exceed what the driver was charged.")
        complaint["refund_state"] = "APPROVED"
    else:  # DENY
        _no_refund_position(complaint)
        complaint["refund_state"] = "DENIED"

    db.touch(complaint)
    return object_response(serialize.customer_complaint(complaint))


@bp.post("/customer-complaints/<complaint_id>/refund-ledger-actions")
@endpoint("CustomerSupportAgent", "ComplianceAuditor")
def refund_ledger_action(complaint_id):
    complaint = lookup.complaint(complaint_id)
    body = validation.json_body()
    action = validation.as_enum(body, "action", LEDGER_ACTIONS)

    require_role_for_leg("CustomerSupportAgent" if action == "SETTLE"
                         else "ComplianceAuditor")

    if action == "SETTLE":
        if complaint["refund_state"] != "APPROVED":
            raise err("ERR_INVALID_STATE", "Only an APPROVED refund may be settled.")
        complaint["refund_state"] = "SETTLED"
        complaint["refund_settled_at"] = clock.now()
    else:  # REVERSE
        if complaint["refund_state"] != "SETTLED":
            raise err("ERR_INVALID_STATE", "Only a SETTLED refund may be reversed.")
        complaint["refund_state"] = "REVERSED"
        complaint["refund_settled_at"] = None
        _no_refund_position(complaint)

    db.touch(complaint)
    return object_response(serialize.customer_complaint(complaint))
