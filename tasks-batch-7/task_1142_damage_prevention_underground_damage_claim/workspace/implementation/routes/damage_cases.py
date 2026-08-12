"""DamageCase endpoints, evidence items, timeline events."""

from datetime import timedelta

from flask import Blueprint, request

import clock
from db import db
from errors import (err_case_not_closable, err_evidence_inadmissible,
                    err_invalid_state, err_not_found, err_outside_window,
                    err_timeline_empty)
from middleware import require_roles
from serializers import case_out, evidence_out, timeline_event_out
from services.core import EVENT_KIND_ORDER, STALE_MARKS_DAYS, touch
from util import (get_pagination, new_id, paginate, parse_body, parse_dt,
                  require_enum, require_string, success_envelope)

bp = Blueprint("damage_cases", __name__)

ALL_ROLES = ("IntakeCoordinator", "DamageInvestigator", "ClaimsAdjuster",
             "RecoveryManager", "Excavator", "Locator")


# ---------------- DamageCase ----------------

@bp.route("/damage-recovery/damage-cases", methods=["POST"])
def create_case():
    require_roles("IntakeCoordinator")
    body = parse_body(required_fields=["excavator_id", "dig_site_address", "facility_type", "severity", "occurred_at"])
    excavator_id = require_string(body["excavator_id"], "excavator_id")
    exc = db.excavators.get(excavator_id)
    if exc is None:
        raise err_not_found("excavator not found")
    facility_type = require_enum(body["facility_type"], ("GAS", "ELECTRIC", "TELECOM", "WATER"), "facility_type")
    severity = require_enum(body["severity"], ("MINOR", "MAJOR", "CRITICAL"), "severity")
    occurred_at = parse_dt(body["occurred_at"], "occurred_at")
    address = require_string(body["dig_site_address"], "dig_site_address")
    locate_ticket_id = body.get("locate_ticket_id")
    if locate_ticket_id is not None:
        ticket = db.locate_tickets.get(locate_ticket_id)
        if ticket is None:
            raise err_not_found("locate ticket not found")
    now = clock.get_current_utc()
    cid = new_id()
    case = {
        "id": cid,
        "excavator_id": excavator_id,
        "locate_ticket_id": locate_ticket_id,
        "case_number": db.next_case_number(),
        "dig_site_address": address,
        "facility_type": facility_type,
        "severity": severity,
        "occurred_at": occurred_at,
        "investigation_status": "REPORTED",
        "recovery_status": "UNBILLED",
        "investigator_user_id": None,
        "subtotal_cents": 0,
        "total_invoiced_cents": 0,
        "total_recovered_cents": 0,
        "evidence_count": 0,
        "reconstruction_flags": [],
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_insert_seq(),
    }
    db.damage_cases[cid] = case
    return success_envelope(case_out(case), "object", 201)


@bp.route("/damage-recovery/damage-cases/<cid>", methods=["GET"])
def get_case(cid):
    require_roles(*ALL_ROLES)
    case = db.damage_cases.get(cid)
    if case is None:
        raise err_not_found("damage case not found")
    return success_envelope(case_out(case), "object", 200)


@bp.route("/damage-recovery/damage-cases", methods=["GET"])
def list_cases():
    require_roles(*ALL_ROLES)
    limit, offset = get_pagination()
    items = list(db.damage_cases.values())
    excavator_id = request.args.get("excavator_id")
    ticket_id = request.args.get("locate_ticket_id")
    inv_status = request.args.get("investigation_status")
    rec_status = request.args.get("recovery_status")
    severity = request.args.get("severity")
    if excavator_id is not None:
        items = [c for c in items if c["excavator_id"] == excavator_id]
    if ticket_id is not None:
        items = [c for c in items if c["locate_ticket_id"] == ticket_id]
    if inv_status is not None:
        items = [c for c in items if c["investigation_status"] == inv_status]
    if rec_status is not None:
        items = [c for c in items if c["recovery_status"] == rec_status]
    if severity is not None:
        items = [c for c in items if c["severity"] == severity]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    page, meta = paginate(items, limit, offset)
    return success_envelope([case_out(c) for c in page], "array", 200, meta)


@bp.route("/damage-recovery/damage-cases/<cid>/link-ticket", methods=["POST"])
def link_ticket(cid):
    require_roles("IntakeCoordinator", "DamageInvestigator")
    case = db.damage_cases.get(cid)
    if case is None:
        raise err_not_found("damage case not found")
    body = parse_body(required_fields=["locate_ticket_id"])
    ticket = db.locate_tickets.get(body["locate_ticket_id"])
    if ticket is None:
        raise err_not_found("locate ticket not found")
    if ticket["status"] != "COMPLETED":
        raise err_invalid_state("ticket must be COMPLETED")
    if not (ticket["work_start_at"] <= case["occurred_at"] < ticket["work_end_at"]):
        raise err_outside_window()
    case["locate_ticket_id"] = ticket["id"]
    touch(case)
    return success_envelope(case_out(case), "object", 200)


@bp.route("/damage-recovery/damage-cases/<cid>/begin-investigation", methods=["POST"])
def begin_investigation(cid):
    user_id, _ = require_roles("DamageInvestigator")
    case = db.damage_cases.get(cid)
    if case is None:
        raise err_not_found("damage case not found")
    if case["investigation_status"] not in ("REPORTED", "DOCUMENTING"):
        raise err_invalid_state("case is not in REPORTED or DOCUMENTING")
    case["investigation_status"] = "INVESTIGATING"
    case["investigator_user_id"] = user_id
    touch(case)
    return success_envelope(case_out(case), "object", 200)


@bp.route("/damage-recovery/damage-cases/<cid>/reconstruct-timeline", methods=["POST"])
def reconstruct_timeline(cid):
    require_roles("DamageInvestigator")
    case = db.damage_cases.get(cid)
    if case is None:
        raise err_not_found("damage case not found")

    # delete prior events
    for eid in [eid for eid, e in db.timeline_events.items() if e["damage_case_id"] == cid]:
        del db.timeline_events[eid]

    ticket = db.locate_tickets.get(case["locate_ticket_id"]) if case["locate_ticket_id"] else None
    responses = []
    if ticket is not None:
        responses = [r for r in db.locate_responses.values() if r["locate_ticket_id"] == ticket["id"]]
    evidence = [e for e in db.evidence_items.values() if e["damage_case_id"] == cid]

    if ticket is None and not responses and not evidence:
        raise err_timeline_empty()

    now = clock.get_current_utc()
    flags = set()
    built = []  # (event_at, source_created_at, kind_order, dict)

    if ticket is not None:
        built.append((ticket["created_at"], ticket["created_at"], EVENT_KIND_ORDER["TICKET_SUBMITTED"], {
            "event_kind": "TICKET_SUBMITTED",
            "event_at": ticket["created_at"],
            "source_ref_id": ticket["id"],
            "flag": "NONE",
        }))
        for r in responses:
            flag = "NONE"
            ea = r["marks_completed_at"]
            if ea > ticket["work_start_at"]:
                flag = "LATE_MARK"
            elif ea < case["occurred_at"] - timedelta(days=STALE_MARKS_DAYS):
                flag = "STALE_MARKS"
            if ea > case["occurred_at"]:
                flag = "POST_DAMAGE_MARK"
            if flag != "NONE":
                flags.add(flag)
            built.append((ea, r["created_at"], EVENT_KIND_ORDER["RESPONSE_SUBMITTED"], {
                "event_kind": "RESPONSE_SUBMITTED",
                "event_at": ea,
                "source_ref_id": r["id"],
                "flag": flag,
            }))
    else:
        flags.add("NO_TICKET")

    for e in evidence:
        built.append((e["captured_at"], e["created_at"], EVENT_KIND_ORDER["EVIDENCE_CAPTURED"], {
            "event_kind": "EVIDENCE_CAPTURED",
            "event_at": e["captured_at"],
            "source_ref_id": e["id"],
            "flag": "NONE",
        }))

    built.append((case["occurred_at"], case["created_at"], EVENT_KIND_ORDER["DAMAGE_OCCURRED"], {
        "event_kind": "DAMAGE_OCCURRED",
        "event_at": case["occurred_at"],
        "source_ref_id": case["id"],
        "flag": "NONE",
    }))

    built.sort(key=lambda t: (t[0], t[1], t[2]))
    for event_at, _src_created, _kind, payload in built:
        eid = new_id()
        db.timeline_events[eid] = {
            "id": eid,
            "damage_case_id": cid,
            "event_kind": payload["event_kind"],
            "event_at": payload["event_at"],
            "source_ref_id": payload["source_ref_id"],
            "flag": payload["flag"],
            "created_at": now,
            "_seq": db.next_insert_seq(),
        }

    # flags unioned onto the case; deterministic order
    flag_order = ["NO_TICKET", "LATE_MARK", "STALE_MARKS", "POST_DAMAGE_MARK"]
    case["reconstruction_flags"] = [f for f in flag_order if f in flags]
    touch(case)

    return success_envelope({
        "created_event_count": len(built),
        "reconstruction_flags": list(case["reconstruction_flags"]),
    }, "object", 200)


@bp.route("/damage-recovery/damage-cases/<cid>/close", methods=["POST"])
def close_case(cid):
    require_roles("RecoveryManager")
    case = db.damage_cases.get(cid)
    if case is None:
        raise err_not_found("damage case not found")
    if case["investigation_status"] != "FAULT_FINAL" or case["recovery_status"] != "RECOVERED":
        raise err_case_not_closable()
    for r in db.regulatory_reports.values():
        if r["damage_case_id"] == cid and r["report_type"] == "INCIDENT" and r["status"] == "DRAFT":
            raise err_case_not_closable("a DRAFT incident report exists for this case")
    case["investigation_status"] = "CLOSED"
    touch(case)
    return success_envelope(case_out(case), "object", 200)


# ---------------- EvidenceItem ----------------

@bp.route("/damage-recovery/evidence-items", methods=["POST"])
def create_evidence():
    require_roles("IntakeCoordinator", "DamageInvestigator")
    body = parse_body(required_fields=["damage_case_id", "evidence_type", "captured_at", "description"])
    case = db.damage_cases.get(body["damage_case_id"])
    if case is None:
        raise err_not_found("damage case not found")
    evidence_type = require_enum(body["evidence_type"], ("PHOTO", "MEASUREMENT", "WITNESS_STATEMENT", "SKETCH"), "evidence_type")
    captured_at = parse_dt(body["captured_at"], "captured_at")
    description = require_string(body["description"], "description")
    if case["investigation_status"] == "CLOSED":
        raise err_invalid_state("case is CLOSED")
    if captured_at > case["occurred_at"] + timedelta(hours=72):
        raise err_evidence_inadmissible()
    now = clock.get_current_utc()
    eid = new_id()
    item = {
        "id": eid,
        "damage_case_id": case["id"],
        "evidence_type": evidence_type,
        "captured_at": captured_at,
        "description": description,
        "created_at": now,
        "_seq": db.next_insert_seq(),
    }
    db.evidence_items[eid] = item
    if case["investigation_status"] == "REPORTED":
        case["investigation_status"] = "DOCUMENTING"
    case["evidence_count"] += 1
    touch(case)
    return success_envelope(evidence_out(item), "object", 201)


@bp.route("/damage-recovery/evidence-items/<eid>", methods=["GET"])
def get_evidence(eid):
    require_roles(*ALL_ROLES)
    e = db.evidence_items.get(eid)
    if e is None:
        raise err_not_found("evidence item not found")
    return success_envelope(evidence_out(e), "object", 200)


@bp.route("/damage-recovery/evidence-items", methods=["GET"])
def list_evidence():
    require_roles(*ALL_ROLES)
    limit, offset = get_pagination()
    items = list(db.evidence_items.values())
    case_id = request.args.get("damage_case_id")
    etype = request.args.get("evidence_type")
    if case_id is not None:
        items = [e for e in items if e["damage_case_id"] == case_id]
    if etype is not None:
        items = [e for e in items if e["evidence_type"] == etype]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    page, meta = paginate(items, limit, offset)
    return success_envelope([evidence_out(e) for e in page], "array", 200, meta)


# ---------------- TimelineEvent ----------------

@bp.route("/damage-recovery/timeline-events/<eid>", methods=["GET"])
def get_timeline_event(eid):
    require_roles(*ALL_ROLES)
    e = db.timeline_events.get(eid)
    if e is None:
        raise err_not_found("timeline event not found")
    return success_envelope(timeline_event_out(e), "object", 200)


@bp.route("/damage-recovery/timeline-events", methods=["GET"])
def list_timeline_events():
    require_roles(*ALL_ROLES)
    limit, offset = get_pagination()
    items = list(db.timeline_events.values())
    case_id = request.args.get("damage_case_id")
    kind = request.args.get("event_kind")
    if case_id is not None:
        items = [e for e in items if e["damage_case_id"] == case_id]
    if kind is not None:
        items = [e for e in items if e["event_kind"] == kind]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    page, meta = paginate(items, limit, offset)
    return success_envelope([timeline_event_out(e) for e in page], "array", 200, meta)
