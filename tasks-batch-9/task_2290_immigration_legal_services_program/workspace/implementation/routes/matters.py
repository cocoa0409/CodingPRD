"""Case matters: reads, facility attachment, the filing dimension, withdrawal."""

import datetime

from flask import Blueprint, request

import auth
import calc
import cascades
import response
import serialize
import store
import validation as v
from errors import ApiError
from routes.core import recompute_client

bp = Blueprint("matters", __name__)

TARGETS = ("EVIDENCE_GATHERING", "READY_TO_FILE", "FILED", "RFE_PENDING", "DECIDED",
           "APPEALED")
OUTCOMES = ("GRANTED", "DENIED", "ADMINISTRATIVELY_CLOSED", "WITHDRAWN", "TERMINATED",
            "REFERRED_TO_COURT")
COURT_FORUMS = ("EOIR_IMMIGRATION_COURT", "BIA")
EVENT_OPEN = ("SCHEDULED", "CONFIRMED")
BOOL_FILTERS = {"true": True, "false": False}


@bp.get("/case-matters")
@auth.requires("ProgramDirector", "IntakeScreener", "SupervisingAttorney",
               "CaseRepresentative", "GrantAnalyst")
def list_matters():
    rows = store.rows("matters")
    args = request.args
    for key in ("client_id", "intake_id", "cycle_id", "principal_matter_id",
                "facility_id", "representation_status", "filing_status"):
        if args.get(key):
            rows = [r for r in rows if r.get(key) == args[key]]
    for key in ("detained", "coverage_gap_flag"):
        if args.get(key) is not None and args.get(key) != "":
            wanted = BOOL_FILTERS.get(str(args[key]).lower())
            if wanted is None:
                v.bad("%s must be true or false." % key)
            rows = [r for r in rows if bool(r.get(key)) is wanted]
    page, meta = store.paginate(rows, args)
    return response.collection([serialize.matter(r) for r in page], meta)


@bp.get("/case-matters/<matter_id>")
@auth.requires("ProgramDirector", "IntakeScreener", "SupervisingAttorney",
               "CaseRepresentative", "GrantAnalyst", "ClientPortalUser", scoped=True)
def read_matter(matter_id):
    auth.scope_matter(matter_id)
    row = store.get("matters", matter_id)
    if row is None:
        raise ApiError("ERR_MATTER_NOT_FOUND")
    return response.ok(serialize.matter(row))


@bp.post("/case-matters/<matter_id>/set-facility")
@auth.requires("ProgramDirector", "SupervisingAttorney")
def set_facility(matter_id):
    row = store.get("matters", matter_id)
    if row is None:
        raise ApiError("ERR_MATTER_NOT_FOUND")
    payload = v.body()
    facility_id = v.as_id(payload, "facility_id", required=False, default=None)
    if facility_id is not None and store.get("facilities", facility_id) is None:
        raise ApiError("ERR_FACILITY_NOT_FOUND")
    detained = v.as_bool(payload, "detained", default=False)
    if detained and facility_id is None:
        raise ApiError("ERR_FACILITY_REQUIRED_FOR_DETAINED",
                       "facility_id is required when detained is true.")
    if row.get("filing_status") in ("FILED", "RFE_PENDING"):
        raise ApiError("ERR_FACILITY_CHANGE_AFTER_FILING",
                       "The facility may not change once the matter is filed.")
    row["detained"] = detained
    row["facility_id"] = facility_id
    calc.recompute_matter_deadlines(row)
    calc.recompute_matter_readiness(row, bump=False)
    row["readiness_gate_applied"] = calc.readiness_gate_name(detained)
    store.touch(row)
    return response.ok(serialize.matter(row))


def _matter_events(matter_id):
    return sorted(
        [e for e in store.db["events"].values() if e.get("matter_id") == matter_id],
        key=store.order_key,
    )


def _documented_decision(matter_id, decision_types):
    for row in sorted(store.db["decisions"].values(), key=store.order_key):
        if row.get("matter_id") != matter_id:
            continue
        if row.get("status") != "DOCUMENTED":
            continue
        if row.get("decision_type") in decision_types:
            return row
    return None


def _certified_declaration(matter_id):
    for row in sorted(store.db["declarations"].values(), key=store.order_key):
        if row.get("matter_id") == matter_id and row.get("status") == "CERTIFIED":
            return row
    return None


def _complete_filing_deadline_events(matter_id):
    for event in _matter_events(matter_id):
        if event.get("event_type") != "FILING_DEADLINE":
            continue
        if event.get("status") not in EVENT_OPEN:
            continue
        event["status"] = "COMPLETED"
        store.touch(event)


def _cancel_open_events(matter_id):
    for event in _matter_events(matter_id):
        if event.get("status") not in EVENT_OPEN:
            continue
        if event.get("event_type") == "FACILITY_VISIT":
            continue
        event["status"] = "CANCELLED"
        store.touch(event)


def _deadline_ok(matter):
    deadline = store.parse_date(matter.get("effective_filing_deadline_date"))
    return deadline is None or store.clock_date() <= deadline


def _authority_gate(matter, require_lead):
    forum = matter.get("forum")
    court = forum in COURT_FORUMS
    if not (require_lead or court):
        return
    lead = calc.active_lead(matter["id"])
    if lead is None:
        raise ApiError("ERR_LEAD_NOT_ASSIGNED",
                       "The matter has no ACTIVE LEAD assignment to authorize.")
    if not court:
        return
    rep = store.get("representatives", lead.get("representative_id"))
    if rep is None or not calc.rep_authorized_for_forum(rep, forum):
        raise ApiError("ERR_FORUM_NOT_AUTHORIZED",
                       "The lead representative is not authorized for %s." % forum)


@bp.post("/case-matters/<matter_id>/advance-filing")
@auth.requires("CaseRepresentative", "SupervisingAttorney", "ProgramDirector",
               scoped=True)
def advance_filing(matter_id):
    auth.scope_matter(matter_id)
    matter = store.get("matters", matter_id)
    if matter is None:
        raise ApiError("ERR_MATTER_NOT_FOUND")
    payload = v.body()
    target = v.as_enum(payload, "target_filing_status", TARGETS)
    outcome = v.as_enum(payload, "outcome", OUTCOMES, required=False, default=None)
    rfe_due = v.as_date(payload, "rfe_response_due_date", required=False, default=None)
    appeal_due = v.as_date(payload, "appeal_due_date", required=False, default=None)
    current = matter.get("filing_status")
    edge = (current, target)
    legal = {
        ("PRE_FILING", "EVIDENCE_GATHERING"),
        ("EVIDENCE_GATHERING", "READY_TO_FILE"),
        ("READY_TO_FILE", "EVIDENCE_GATHERING"),
        ("READY_TO_FILE", "FILED"),
        ("FILED", "RFE_PENDING"),
        ("RFE_PENDING", "FILED"),
        ("FILED", "DECIDED"),
        ("RFE_PENDING", "DECIDED"),
        ("DECIDED", "APPEALED"),
        ("APPEALED", "DECIDED"),
    }
    if edge not in legal:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "%s -> %s is not a legal filing edge." % (current, target))
    if matter.get("representation_status") == "WITHDRAWN_FROM":
        raise ApiError("ERR_MATTER_CLOSED", "The matter is closed.")

    require_lead = False
    if edge == ("PRE_FILING", "EVIDENCE_GATHERING"):
        if matter.get("representation_status") not in ("STAFFED", "SUPERVISED_STAFFED"):
            raise ApiError("ERR_LEAD_NOT_ASSIGNED",
                           "The matter must be staffed before evidence gathering.")
        if calc.required_evidence_total(matter["id"]) < 1:
            raise ApiError("ERR_BLOCKING_EVIDENCE_OUTSTANDING",
                           "At least one REQUIRED evidence item is needed.")
        require_lead = True
    elif edge == ("EVIDENCE_GATHERING", "READY_TO_FILE"):
        if _certified_declaration(matter["id"]) is None:
            raise ApiError("ERR_DECLARATION_NOT_CERTIFIED",
                           "A CERTIFIED declaration is required.")
        calc.recompute_matter_readiness(matter, bump=False)
        detained = bool(matter.get("detained"))
        matter["readiness_gate_applied"] = calc.readiness_gate_name(detained)
        if detained:
            if store.dec(matter["readiness_index_weighted"]) < calc.READINESS_WEIGHTED_THRESHOLD:
                raise ApiError("ERR_MATTER_NOT_READY",
                               "The weighted readiness gate is not met.")
        elif not matter.get("readiness_ready_strict"):
            raise ApiError("ERR_BLOCKING_EVIDENCE_OUTSTANDING",
                           "Required evidence items remain open.")
        require_lead = True
    elif edge == ("READY_TO_FILE", "FILED"):
        if _documented_decision(matter["id"],
                                ("FILE_AFFIRMATIVE", "PURSUE_RELIEF_IN_COURT")) is None:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "A DOCUMENTED filing decision is required.")
        if not _deadline_ok(matter):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "The effective filing deadline has passed.")
    elif edge == ("FILED", "RFE_PENDING"):
        if rfe_due is None:
            v.bad("rfe_response_due_date is required for RFE_PENDING.")
    elif edge == ("RFE_PENDING", "FILED"):
        calc.recompute_matter_readiness(matter, bump=False)
        if int(matter.get("evidence_blocking_count") or 0) != 0:
            raise ApiError("ERR_BLOCKING_EVIDENCE_OUTSTANDING",
                           "Blocking evidence remains outstanding.")
        if not _deadline_ok(matter):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "The effective filing deadline has passed.")
    elif target == "DECIDED":
        if outcome is None:
            v.bad("outcome is required for DECIDED.")
    elif target == "APPEALED":
        if matter.get("outcome") != "DENIED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Only a DENIED matter may be appealed.")
        if _documented_decision(matter["id"], ("APPEAL_DECISION",)) is None:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "A DOCUMENTED APPEAL_DECISION is required.")
        if appeal_due is None:
            v.bad("appeal_due_date is required for APPEALED.")

    _authority_gate(matter, require_lead)

    matter["filing_status"] = target
    if edge == ("FILED", "RFE_PENDING"):
        matter["statutory_deadline_date"] = rfe_due.isoformat()
        calc.recompute_matter_deadlines(matter)
        event = store.new_row({
            "matter_id": matter["id"],
            "facility_id": None,
            "assigned_representative_id": None,
            "continued_from_event_id": None,
            "event_type": "FILING_DEADLINE",
            "starts_at_utc": store.iso(datetime.datetime.combine(
                rfe_due, datetime.time(0, 0, 0))),
            "ends_at_utc": store.iso(datetime.datetime.combine(
                rfe_due, datetime.time(0, 0, 0))),
            "location_code": "MAIL",
            "travel_buffer_minutes": calc.travel_buffer("FILING_DEADLINE"),
            "status": "SCHEDULED",
            "reschedule_count": 0,
            "coverage_gap_flag": False,
            "client_conflict_waived": False,
        })
        store.insert("events", event)
    elif target == "FILED":
        _complete_filing_deadline_events(matter["id"])
    elif target == "DECIDED":
        matter["outcome"] = outcome
        matter["outcome_recorded_at_utc"] = store.clock_iso()
        if current in ("FILED", "RFE_PENDING"):
            _cancel_open_events(matter["id"])
    elif target == "APPEALED":
        matter["forum"] = "BIA"
        matter["statutory_deadline_date"] = appeal_due.isoformat()
        matter["outcome"] = None
        matter["outcome_recorded_at_utc"] = None
        calc.recompute_matter_deadlines(matter)
    else:
        calc.recompute_matter_readiness(matter, bump=False)
    store.touch(matter)
    return response.ok(serialize.matter(matter))


@bp.post("/case-matters/<matter_id>/withdraw-representation")
@auth.requires("SupervisingAttorney", "ProgramDirector")
def withdraw_representation(matter_id):
    matter = store.get("matters", matter_id)
    if matter is None:
        raise ApiError("ERR_MATTER_NOT_FOUND")
    payload = v.body()
    motion = v.as_bool(payload, "withdrawal_motion_filed", default=False)
    v.as_str(payload, "reason_code", required=False, min_len=1, max_len=40, default=None)
    if matter.get("representation_status") == "WITHDRAWN_FROM":
        raise ApiError("ERR_MATTER_CLOSED", "The matter is closed.")
    if matter.get("filing_status") == "FILED" and not motion:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "A filed matter requires withdrawal_motion_filed.")
    if _documented_decision(matter["id"], ("WITHDRAW_CASE",)) is None:
        raise ApiError("ERR_CONSENT_SCOPE_INSUFFICIENT",
                       "A DOCUMENTED WITHDRAW_CASE decision is required.")
    matter["representation_status"] = "WITHDRAWN_FROM"
    matter["closed_at_utc"] = store.clock_iso()
    if matter.get("filing_status") != "DECIDED":
        matter["filing_status"] = "CLOSED_NO_FILING"
    matter["coverage_gap_flag"] = False
    store.touch(matter)
    cascades.close_matter_assignments(matter, "MATTER_CLOSED")
    cycle = store.get("cycles", matter.get("cycle_id"))
    if cycle is not None:
        calc.recompute_cycle(cycle)
    client = store.get("clients", matter.get("client_id"))
    if client is not None:
        recompute_client(client)
    return response.ok(serialize.matter(matter))
