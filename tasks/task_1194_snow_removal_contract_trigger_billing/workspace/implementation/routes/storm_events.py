"""StormEvent endpoints — report, verify, challenge, void, close-sweep, route-plan."""
from flask import Blueprint, request
from datetime import timedelta
import db
from middleware import require_roles, get_pagination, get_json_body
from response import success_object, success_created, success_list
from errors import *
from services.helpers import (
    recompute_contract_accumulators, _touch, evaluate_visit_billing,
    recompute_draft_invoices,
)

bp = Blueprint("storm_events", __name__)

ALLOWED_CREATE_FIELDS = {"region_code", "window_start", "window_end", "reported_accumulation_inches", "reported_source_name"}


@bp.route("/storm-events", methods=["POST"])
def create_storm_event():
    user_id, role = require_roles("OpsDispatcher")
    body = get_json_body()
    unknown = set(body.keys()) - ALLOWED_CREATE_FIELDS
    if unknown:
        raise ApiError(ERR_INVALID_REQUEST, f"Unknown fields: {', '.join(unknown)}", 400)

    region_code = body.get("region_code")
    window_start = body.get("window_start")
    window_end = body.get("window_end")
    accumulation = body.get("reported_accumulation_inches")
    source_name = body.get("reported_source_name")

    if not region_code:
        raise ApiError(ERR_INVALID_REQUEST, "region_code is required", 400)
    if not window_start or not window_end:
        raise ApiError(ERR_INVALID_REQUEST, "window_start and window_end are required", 400)
    ws = db._parse_iso(window_start)
    we = db._parse_iso(window_end)
    if not ws or not we:
        raise ApiError(ERR_INVALID_REQUEST, "Invalid window dates", 400)
    if we <= ws:
        raise ApiError(ERR_INVALID_REQUEST, "window_end must be > window_start", 400)
    if accumulation is None:
        raise ApiError(ERR_INVALID_REQUEST, "reported_accumulation_inches is required", 400)
    if not source_name:
        raise ApiError(ERR_INVALID_REQUEST, "reported_source_name is required", 400)

    event = {
        "id": db._new_id(),
        "region_code": region_code,
        "window_start": window_start,
        "window_end": window_end,
        "reported_accumulation_inches": accumulation,
        "reported_source_name": source_name,
        "status": "REPORTED",
        "verified_accumulation_inches": None,
        "verified_at": None,
        "verifying_observation_ids": [],
        "challenged_at": None,
        "challenged_by_client_id": None,
        "challenge_reason": None,
        "closed_at": None,
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
    }
    db.storm_events.create(event)
    return success_created(event)


def _get_event_or_404(id):
    e = db.storm_events.get(id)
    if not e:
        raise ApiError(ERR_NOT_FOUND, f"StormEvent {id} not found", 404)
    return e


@bp.route("/storm-events/<id>", methods=["GET"])
def get_storm_event(id):
    user_id, role = require_roles("PlatformAdmin", "OpsDispatcher", "ClientContact", "ClaimsAdjuster", "Subcontractor", "CrewLead")
    event = _get_event_or_404(id)
    return success_object(event)


@bp.route("/storm-events", methods=["GET"])
def list_storm_events():
    user_id, role = require_roles("PlatformAdmin", "OpsDispatcher", "ClientContact", "ClaimsAdjuster")
    limit, offset = get_pagination()
    all_events = db.storm_events.list_all()
    status = request.args.get("status")
    region_code = request.args.get("region_code")
    if status:
        all_events = [e for e in all_events if e.get("status") == status]
    if region_code:
        all_events = [e for e in all_events if e.get("region_code") == region_code]
    all_events = sorted(all_events, key=lambda e: e.get("created_at", ""))
    total = len(all_events)
    page = all_events[offset:offset + limit]
    return success_list(page, total, limit, offset)


@bp.route("/storm-events/<id>/verify", methods=["POST"])
def verify_storm_event(id):
    user_id, role = require_roles("OpsDispatcher")
    event = _get_event_or_404(id)
    if event["status"] == "CLOSED" or event["status"] == "VOIDED":
        raise ApiError(ERR_ALREADY_TERMINAL, f"Event is {event['status']} (terminal)", 409)
    if event["status"] not in ("REPORTED", "CHALLENGED"):
        raise ApiError(ERR_INVALID_STATE, f"Cannot verify from {event['status']}", 409)

    # Find eligible observations
    ws = db._parse_iso(event["window_start"])
    we = db._parse_iso(event["window_end"])
    grace_end = we + timedelta(hours=6)

    eligible = []
    for obs in db.observations.list_all():
        if obs.get("storm_event_id") != id:
            continue
        obs_at = db._parse_iso(obs.get("observed_at"))
        if obs_at and ws <= obs_at <= grace_end:
            eligible.append(obs)

    # Quorum check
    sources = set(o.get("source_name") for o in eligible)
    if len(sources) < 2:
        raise ApiError(ERR_VERIFICATION_QUORUM, "Fewer than 2 distinct observation sources", 422)

    # Re-verification requires fresh evidence
    if event["status"] == "CHALLENGED":
        challenged_at = db._parse_iso(event.get("challenged_at"))
        if challenged_at:
            has_new = False
            for obs in eligible:
                obs_created = db._parse_iso(obs.get("created_at"))
                if obs_created and obs_created > challenged_at:
                    has_new = True
                    break
            if not has_new:
                raise ApiError(ERR_NO_NEW_EVIDENCE, "No observation created after challenge", 409)

    # Select latest observation by (observed_at DESC, created_at DESC)
    eligible.sort(key=lambda o: (db._parse_iso(o["observed_at"]) or db._parse_iso(o["created_at"]), db._parse_iso(o["created_at"])), reverse=True)
    latest = eligible[0]

    event["verified_accumulation_inches"] = latest.get("accumulation_inches")
    event["verified_at"] = db.now_iso()
    event["verifying_observation_ids"] = [o["id"] for o in eligible]
    event["status"] = "VERIFIED"
    _touch(event)
    db.storm_events.update(id, event)

    # CASCADE L1: Re-evaluate all COMPLETED visits under this event.
    # PRD §3.7: tier allocation is chronological across the season, ordered by
    # actual_start_at and then by created_at — never by completion/insertion order.
    completed_visits = [
        v for v in db.visits.list_all()
        if v.get("storm_event_id") == id and v.get("execution_status") == "COMPLETED"
    ]
    completed_visits.sort(key=lambda v: (
        db._parse_iso(v.get("actual_start_at")) or db._parse_iso(v.get("created_at")),
        db._parse_iso(v.get("created_at")),
    ))
    affected_contracts = set()
    for v in completed_visits:
        evaluate_visit_billing(v, event)
        affected_contracts.add(v.get("contract_id"))

    # CASCADE L2: Recompute contract accumulators
    for cid in affected_contracts:
        if cid:
            recompute_contract_accumulators(cid)

    # CASCADE L3: DRAFT invoices covering this event recompute
    recompute_draft_invoices(storm_event_id=id)

    return success_object(event)


@bp.route("/storm-events/<id>/challenge", methods=["POST"])
def challenge_storm_event(id):
    user_id, role = require_roles("ClientContact")
    event = _get_event_or_404(id)
    if event["status"] != "VERIFIED":
        if event["status"] in ("CLOSED", "VOIDED"):
            raise ApiError(ERR_ALREADY_TERMINAL, f"Event is {event['status']} (terminal)", 409)
        raise ApiError(ERR_INVALID_STATE, f"Cannot challenge from {event['status']}", 409)

    body = get_json_body()
    reason = body.get("reason")
    if not reason:
        raise ApiError(ERR_INVALID_REQUEST, "reason is required", 400)

    # Check ownership: client must have >= 1 ContractSite whose Site.region_code matches
    has_site = False
    for cs in db.contract_sites.list_all():
        site = db.sites.get(cs.get("site_id"))
        if site and site.get("client_id") == user_id and site.get("region_code") == event.get("region_code"):
            has_site = True
            break
    if not has_site:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "No site in this region", 403)

    # Challenge window: clock <= verified_at + 48h
    clock = db.get_clock()
    verified_at = db._parse_iso(event.get("verified_at"))
    if verified_at:
        deadline = verified_at + timedelta(hours=48)
        if clock > deadline:
            raise ApiError(ERR_CHALLENGE_WINDOW_EXPIRED, "Challenge window expired", 422)

    event["status"] = "CHALLENGED"
    event["challenged_at"] = db.now_iso()
    event["challenged_by_client_id"] = user_id
    event["challenge_reason"] = reason
    _touch(event)
    db.storm_events.update(id, event)

    # Revert BILLABLE_CONFIRMED visits to PENDING
    affected_contracts = set()
    for v in db.visits.list_all():
        if v.get("storm_event_id") == id and v.get("billing_status") == "BILLABLE_CONFIRMED":
            v["billing_status"] = "PENDING"
            _touch(v)
            db.visits.update(v["id"], v)
            affected_contracts.add(v.get("contract_id"))

    for cid in affected_contracts:
        if cid:
            recompute_contract_accumulators(cid)

    recompute_draft_invoices(storm_event_id=id)

    return success_object(event)


@bp.route("/storm-events/<id>/void", methods=["POST"])
def void_storm_event(id):
    user_id, role = require_roles("PlatformAdmin")
    event = _get_event_or_404(id)
    if event["status"] in ("CLOSED", "VOIDED"):
        raise ApiError(ERR_ALREADY_TERMINAL, f"Event is {event['status']} (terminal)", 409)
    if event["status"] not in ("REPORTED", "CHALLENGED", "VERIFIED"):
        raise ApiError(ERR_INVALID_STATE, f"Cannot void from {event['status']}", 409)

    # VERIFIED: check no ISSUED-or-later invoice references this event
    if event["status"] == "VERIFIED":
        locked_statuses = {"ISSUED", "PARTIALLY_CREDITED", "PARTIALLY_PAID", "PAID"}
        for inv in db.invoices.list_all():
            if inv.get("storm_event_id") == id and inv.get("status") in locked_statuses:
                raise ApiError(ERR_EVENT_LOCKED_BY_INVOICE, "Event locked by issued invoice", 409)

    old_status = event["status"]
    event["status"] = "VOIDED"
    _touch(event)
    db.storm_events.update(id, event)

    affected_contracts = set()

    if old_status in ("REPORTED", "CHALLENGED"):
        # Cancel SCHEDULED/AWAITING_BACKUP visits, COMPLETED -> NON_BILLABLE
        for v in db.visits.list_all():
            if v.get("storm_event_id") != id:
                continue
            if v.get("execution_status") in ("SCHEDULED", "AWAITING_BACKUP"):
                v["execution_status"] = "CANCELLED"
                _touch(v)
                db.visits.update(v["id"], v)
                affected_contracts.add(v.get("contract_id"))
            elif v.get("execution_status") == "COMPLETED":
                v["billing_status"] = "NON_BILLABLE"
                _touch(v)
                db.visits.update(v["id"], v)
                affected_contracts.add(v.get("contract_id"))
    elif old_status == "VERIFIED":
        # BILLABLE_CONFIRMED -> NON_BILLABLE, DRAFT invoices -> VOIDED
        for v in db.visits.list_all():
            if v.get("storm_event_id") == id and v.get("billing_status") == "BILLABLE_CONFIRMED":
                v["billing_status"] = "NON_BILLABLE"
                _touch(v)
                db.visits.update(v["id"], v)
                affected_contracts.add(v.get("contract_id"))
        for inv in db.invoices.list_all():
            if inv.get("storm_event_id") == id and inv.get("status") == "DRAFT":
                inv["status"] = "VOIDED"
                _touch(inv)
                db.invoices.update(inv["id"], inv)
                affected_contracts.add(inv.get("contract_id"))

    for cid in affected_contracts:
        if cid:
            recompute_contract_accumulators(cid)

    return success_object(event)


@bp.route("/storm-events/<id>/close-sweep", methods=["POST"])
def close_sweep(id):
    user_id, role = require_roles("OpsDispatcher")
    event = _get_event_or_404(id)
    if event["status"] != "VERIFIED":
        if event["status"] in ("CLOSED", "VOIDED"):
            raise ApiError(ERR_ALREADY_TERMINAL, f"Event is {event['status']} (terminal)", 409)
        raise ApiError(ERR_INVALID_STATE, f"Cannot close-sweep from {event['status']}", 409)

    clock = db.get_clock()
    event["closed_at"] = db.now_iso()
    event["status"] = "CLOSED"
    _touch(event)
    db.storm_events.update(id, event)

    visits_marked_missed = 0
    affected_contracts = set()

    # Mark overdue SCHEDULED/AWAITING_BACKUP visits as MISSED
    for v in db.visits.list_all():
        if v.get("storm_event_id") != id:
            continue
        if v.get("execution_status") in ("SCHEDULED", "AWAITING_BACKUP"):
            deadline = db._parse_iso(v.get("sla_deadline_at"))
            if deadline and deadline < clock:
                v["execution_status"] = "MISSED"
                v["sla_miss"] = True
                v["billing_status"] = "NON_BILLABLE"
                _touch(v)
                db.visits.update(v["id"], v)
                visits_marked_missed += 1
                affected_contracts.add(v.get("contract_id"))

    for cid in affected_contracts:
        if cid:
            recompute_contract_accumulators(cid)

    # Expire contracts past season_end with no open work
    contracts_expired = 0
    open_statuses = {"SCHEDULED", "IN_PROGRESS", "AWAITING_BACKUP"}
    for c in db.contracts.list_all():
        if c.get("status") not in ("ACTIVE", "SUSPENDED"):
            continue
        se = db._parse_iso(c.get("season_end"))
        if not se or clock <= se:
            continue
        open_visits = [v for v in db.visits.list_all() if v.get("contract_id") == c["id"] and v.get("execution_status") in open_statuses]
        if not open_visits:
            c["status"] = "EXPIRED"
            _touch(c)
            db.contracts.update(c["id"], c)
            contracts_expired += 1

    return success_object({"visits_marked_missed": visits_marked_missed, "contracts_expired": contracts_expired})


@bp.route("/storm-events/<id>/route-plan", methods=["GET"])
def route_plan(id):
    user_id, role = require_roles("OpsDispatcher", "Subcontractor")
    event = _get_event_or_404(id)
    contract_id = request.args.get("contract_id")
    if not contract_id:
        raise ApiError(ERR_INVALID_REQUEST, "contract_id query parameter is required", 400)

    # Verify contract exists
    contract = db.contracts.get(contract_id)
    if not contract:
        raise ApiError(ERR_NOT_FOUND, f"Contract {contract_id} not found", 404)

    # Find visits for (event, contract) in active execution states
    active_statuses = {"SCHEDULED", "IN_PROGRESS", "AWAITING_BACKUP"}
    candidate_visits = [
        v for v in db.visits.list_all()
        if v.get("storm_event_id") == id
        and v.get("contract_id") == contract_id
        and v.get("execution_status") in active_statuses
    ]

    # Sort by contract_site priority_sequence
    def get_priority(v):
        cs = db.contract_sites.get(v.get("contract_site_id"))
        return cs.get("priority_sequence", 999999) if cs else 999999

    candidate_visits.sort(key=get_priority)

    entries = []
    for i, v in enumerate(candidate_visits):
        entries.append({
            "visit_id": v["id"],
            "contract_site_id": v.get("contract_site_id"),
            "site_id": v.get("site_id"),
            "route_order": i + 1,
            "execution_status": v.get("execution_status"),
            "scheduled_start": v.get("scheduled_start"),
            "scheduled_end": v.get("scheduled_end"),
        })

    limit, offset = get_pagination()
    total = len(entries)
    page = entries[offset:offset + limit]
    return success_list(page, total, limit, offset)
