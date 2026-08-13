"""Maintenance contracts, downtime events, publications, and the
test-driving logical clock (PRD §3.11, §3.12, §2.4)."""

from flask import Blueprint, request

from auth import authenticate, require_roles, is_entity_role, auth_id, check_create_ownership
from errors import fail
from helpers import (
    Body, validate_body, non_empty_str, is_int, dt_ok, date_ok, parse_dt, parse_date,
    contract_status, ser_contract, ser_downtime, ser_publication,
    system_cancel, system_reject, event_contains_now, downtime_conflicts,
)
from routes.instruments import get_instrument_or_404
from store import store, now
from util import new_entity, ok_object, parse_pagination, paginate, sort_default, touch, fmt_ts, fmt_clock

bp = Blueprint("ops", __name__)


def get_contract_or_404(cid):
    c = store.contracts.get(cid)
    if c is None:
        fail("ERR_NOT_FOUND", "Maintenance contract not found")
    return c


def get_downtime_or_404(did):
    ev = store.downtime_events.get(did)
    if ev is None:
        fail("ERR_NOT_FOUND", "Downtime event not found")
    return ev


def get_publication_or_404(pid):
    p = store.publications.get(pid)
    if p is None:
        fail("ERR_NOT_FOUND", "Publication not found")
    return p


# ---------------------------------------------------------------------------
# Maintenance contracts
# ---------------------------------------------------------------------------

@bp.route("/maintenance-contracts", methods=["POST"])
def create_contract():
    authenticate()
    require_roles("FacilityAdmin")
    body = Body(request.get_json(silent=True))
    instrument_id = body.get("instrument_id")
    # Priority 4 — FK existence
    if instrument_id is not None and instrument_id not in store.instruments:
        fail("ERR_NOT_FOUND", "instrument_id does not reference an existing instrument")
    cs = parse_date(body.get("coverage_start"))
    ce = parse_date(body.get("coverage_end"))
    # Priority 18 — non-terminated contract windows must not overlap
    # (half-open date semantics: touching boundaries allowed)
    if instrument_id is not None and cs is not None and ce is not None:
        for c in store.contracts.values():
            if c["instrument_id"] != instrument_id or c.get("_terminated"):
                continue
            if cs < c["_coverage_end"] and c["_coverage_start"] < ce:
                fail("ERR_CONTRACT_OVERLAP", "Coverage window overlaps another active contract")
    # Priority 21 — formats
    validate_body(
        body,
        allowed={"instrument_id", "vendor", "sla_response_hours", "coverage_start",
                 "coverage_end", "annual_cost_cents"},
        required={"instrument_id", "vendor", "sla_response_hours", "coverage_start",
                  "coverage_end", "annual_cost_cents"},
        checkers={
            "instrument_id": lambda v: isinstance(v, str),
            "vendor": non_empty_str,
            "sla_response_hours": lambda v: is_int(v) and v > 0,
            "coverage_start": date_ok,
            "coverage_end": date_ok,
            "annual_cost_cents": lambda v: is_int(v) and v > 0,
        },
    )
    if ce < cs:
        fail("ERR_INVALID_REQUEST", "coverage_end must be on or after coverage_start")
    contract = new_entity({
        "instrument_id": instrument_id,
        "vendor": body.get("vendor"),
        "sla_response_hours": body.get("sla_response_hours"),
        "coverage_start": body.get("coverage_start"),
        "coverage_end": body.get("coverage_end"),
        "annual_cost_cents": body.get("annual_cost_cents"),
        "_coverage_start": cs,
        "_coverage_end": ce,
        "_terminated": False,
    })
    store.contracts[contract["id"]] = contract
    return ok_object(ser_contract(contract), status=201)


@bp.route("/maintenance-contracts", methods=["GET"])
def list_contracts():
    authenticate()
    require_roles("FacilityAdmin", "CoreStaff", "FinanceOfficer")
    limit, offset = parse_pagination(request.args)
    items = list(store.contracts.values())
    instrument_id = request.args.get("instrument_id")
    if instrument_id is not None:
        items = [c for c in items if c["instrument_id"] == instrument_id]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if contract_status(c) == status]
    return paginate(sort_default(items), limit, offset, ser_contract)


@bp.route("/maintenance-contracts/<cid>", methods=["GET"])
def get_contract(cid):
    authenticate()
    require_roles("FacilityAdmin", "CoreStaff", "FinanceOfficer")
    return ok_object(ser_contract(get_contract_or_404(cid)))


@bp.route("/maintenance-contracts/<cid>/terminate", methods=["POST"])
def terminate_contract(cid):
    authenticate()
    require_roles("FacilityAdmin")
    c = get_contract_or_404(cid)
    body = Body(request.get_json(silent=True))
    if body.raw:
        for k in body.raw:
            if k not in ("reason",):
                fail("ERR_INVALID_REQUEST", "Unknown field in request body: %s" % k)
    if c.get("_terminated"):
        fail("ERR_INVALID_STATE", "Contract is already TERMINATED")
    c["_terminated"] = True
    touch(c)
    return ok_object(ser_contract(c))


# ---------------------------------------------------------------------------
# Downtime events
# ---------------------------------------------------------------------------

@bp.route("/downtime-events", methods=["POST"])
def create_downtime():
    authenticate()
    require_roles("CoreStaff", "FacilityAdmin")
    body = Body(request.get_json(silent=True))
    instrument_id = body.get("instrument_id")
    contract_id = body.get("maintenance_contract_id")
    # Priority 4 — FK existence
    if instrument_id is not None and instrument_id not in store.instruments:
        fail("ERR_NOT_FOUND", "instrument_id does not reference an existing instrument")
    if contract_id is not None and contract_id not in store.contracts:
        fail("ERR_NOT_FOUND", "maintenance_contract_id does not reference an existing contract")
    kind = body.get("kind")
    start_at = parse_dt(body.get("start_at"))
    end_at = parse_dt(body.get("end_at"))
    # Priority 20 — PREVENTIVE_MAINTENANCE needs an ACTIVE covering contract
    if kind == "PREVENTIVE_MAINTENANCE":
        contract = store.contracts.get(contract_id) if contract_id else None
        ok = False
        if contract is not None and contract_status(contract) == "ACTIVE" \
                and start_at is not None and end_at is not None:
            if contract["_coverage_start"] <= start_at.date() and end_at.date() <= contract["_coverage_end"]:
                ok = True
        if not ok:
            fail("ERR_CONTRACT_REQUIRED",
                 "PREVENTIVE_MAINTENANCE requires an ACTIVE contract covering the event window")
    # Priority 21 — formats
    validate_body(
        body,
        allowed={"instrument_id", "maintenance_contract_id", "kind", "start_at", "end_at", "notes"},
        required={"instrument_id", "kind", "start_at", "end_at"},
        checkers={
            "instrument_id": lambda v: isinstance(v, str),
            "maintenance_contract_id": lambda v: isinstance(v, str),
            "kind": lambda v: v in ("UNSCHEDULED_FAILURE", "PREVENTIVE_MAINTENANCE", "CALIBRATION"),
            "start_at": dt_ok,
            "end_at": dt_ok,
            "notes": lambda v: isinstance(v, str),
        },
    )
    if not (end_at > start_at):
        fail("ERR_INVALID_REQUEST", "end_at must be after start_at")
    ev = new_entity({
        "instrument_id": instrument_id,
        "maintenance_contract_id": contract_id,
        "kind": kind,
        "start_at": fmt_ts(start_at),
        "end_at": fmt_ts(end_at),
        "status": "REPORTED",
        "notes": body.get("notes"),
        "_start_at": start_at,
        "_end_at": end_at,
    })
    store.downtime_events[ev["id"]] = ev
    return ok_object(ser_downtime(ev), status=201)


@bp.route("/downtime-events", methods=["GET"])
def list_downtime():
    authenticate()
    require_roles("FacilityAdmin", "CoreStaff", "FinanceOfficer", "Researcher", "ExternalClient")
    limit, offset = parse_pagination(request.args)
    items = list(store.downtime_events.values())
    for param in ("instrument_id", "maintenance_contract_id"):
        v = request.args.get(param)
        if v is not None:
            items = [e for e in items if e.get(param) == v]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    return paginate(sort_default(items), limit, offset, ser_downtime)


@bp.route("/downtime-events/<did>", methods=["GET"])
def get_downtime(did):
    authenticate()
    require_roles("FacilityAdmin", "CoreStaff", "FinanceOfficer", "Researcher", "ExternalClient")
    return ok_object(ser_downtime(get_downtime_or_404(did)))


@bp.route("/downtime-events/<did>/confirm", methods=["POST"])
def confirm_downtime(did):
    authenticate()
    require_roles("CoreStaff", "FacilityAdmin")
    ev = get_downtime_or_404(did)
    body = Body(request.get_json(silent=True))
    if body.raw:
        for k in body.raw:
            fail("ERR_INVALID_REQUEST", "Unknown field in request body: %s" % k)
    if ev["status"] != "REPORTED":
        fail("ERR_INVALID_STATE", "Only a REPORTED downtime event can be confirmed")
    inst = store.instruments.get(ev["instrument_id"])
    if inst is not None and inst["status"] == "RETIRED":
        fail("ERR_INVALID_STATE", "Cannot confirm downtime on a RETIRED instrument")
    ev["status"] = "CONFIRMED"
    touch(ev)
    # Instrument flip only when the window contains the current logical time
    if inst is not None and event_contains_now(ev):
        new_status = "DOWN" if ev["kind"] == "UNSCHEDULED_FAILURE" else "MAINTENANCE"
        if inst["status"] != new_status:
            inst["status"] = new_status
            touch(inst)
    # Booking cascade under closed-interval semantics
    for b in list(store.bookings.values()):
        if b["instrument_id"] != ev["instrument_id"]:
            continue
        if b["status"] not in ("REQUESTED", "APPROVED"):
            continue
        if not downtime_conflicts(ev, b["_start_at"], b["_end_at"]):
            continue
        if b["status"] == "APPROVED":
            system_cancel(b, "DOWNTIME")
        else:
            system_reject(b)
    return ok_object(ser_downtime(ev))


@bp.route("/downtime-events/<did>/resolve", methods=["POST"])
def resolve_downtime(did):
    authenticate()
    require_roles("CoreStaff", "FacilityAdmin")
    ev = get_downtime_or_404(did)
    body = Body(request.get_json(silent=True))
    if body.raw:
        for k in body.raw:
            fail("ERR_INVALID_REQUEST", "Unknown field in request body: %s" % k)
    if ev["status"] != "CONFIRMED":
        fail("ERR_INVALID_STATE", "Only a CONFIRMED downtime event can be resolved")
    ev["status"] = "RESOLVED"
    touch(ev)
    # Instrument returns to AVAILABLE when no other CONFIRMED window covers now
    inst = store.instruments.get(ev["instrument_id"])
    if inst is not None and inst["status"] in ("DOWN", "MAINTENANCE"):
        blocked = False
        for other in store.downtime_events.values():
            if other["id"] == did:
                continue
            if other["instrument_id"] == inst["id"] and other["status"] == "CONFIRMED" \
                    and event_contains_now(other):
                blocked = True
                break
        if not blocked:
            inst["status"] = "AVAILABLE"
            touch(inst)
    return ok_object(ser_downtime(ev))


@bp.route("/downtime-events/<did>/cancel", methods=["POST"])
def cancel_downtime(did):
    authenticate()
    require_roles("CoreStaff", "FacilityAdmin")
    ev = get_downtime_or_404(did)
    body = Body(request.get_json(silent=True))
    if body.raw:
        for k in body.raw:
            fail("ERR_INVALID_REQUEST", "Unknown field in request body: %s" % k)
    if ev["status"] != "REPORTED":
        fail("ERR_INVALID_STATE", "Only a REPORTED downtime event can be cancelled")
    ev["status"] = "CANCELLED"
    touch(ev)
    return ok_object(ser_downtime(ev))


# ---------------------------------------------------------------------------
# Publications
# ---------------------------------------------------------------------------

@bp.route("/publications", methods=["POST"])
def create_publication():
    authenticate()
    require_roles("Researcher", "ExternalClient")
    body = Body(request.get_json(silent=True))
    # Priority 2 — entity-backed create ownership
    check_create_ownership(body)
    user_id = body.get("user_id")
    instrument_ids = body.get("instrument_ids")
    # Priority 4 — FK existence (every element of instrument_ids)
    if user_id is not None and user_id not in store.users:
        fail("ERR_NOT_FOUND", "user_id does not reference an existing user")
    if isinstance(instrument_ids, list):
        for iid in instrument_ids:
            if iid not in store.instruments:
                fail("ERR_NOT_FOUND", "instrument_ids references a missing instrument")
    # Priority 21 — formats
    validate_body(
        body,
        allowed={"user_id", "title", "journal", "published_at", "acknowledges_core",
                 "non_ack_reason", "instrument_ids"},
        required={"user_id", "title", "journal", "published_at", "acknowledges_core", "instrument_ids"},
        checkers={
            "user_id": lambda v: isinstance(v, str),
            "title": non_empty_str,
            "journal": non_empty_str,
            "published_at": date_ok,
            "acknowledges_core": lambda v: isinstance(v, bool),
            "non_ack_reason": lambda v: isinstance(v, str),
            "instrument_ids": lambda v: isinstance(v, list) and len(v) > 0
                          and all(isinstance(x, str) for x in v),
        },
    )
    # Priority 30 — acknowledgment reason required when not acknowledging
    if body.get("acknowledges_core") is False:
        reason = body.get("non_ack_reason")
        if not isinstance(reason, str) or len(reason.strip()) == 0:
            fail("ERR_ACK_REASON_REQUIRED", "non_ack_reason is required when acknowledges_core is false")
    pub = new_entity({
        "user_id": user_id,
        "title": body.get("title"),
        "journal": body.get("journal"),
        "published_at": body.get("published_at"),
        "acknowledges_core": body.get("acknowledges_core"),
        "non_ack_reason": body.get("non_ack_reason"),
        "instrument_ids": list(instrument_ids),
        "status": "REPORTED",
        "verified_by": None,
    })
    store.publications[pub["id"]] = pub
    return ok_object(ser_publication(pub), status=201)


@bp.route("/publications", methods=["GET"])
def list_publications():
    authenticate()
    require_roles("FacilityAdmin", "CoreStaff", "FinanceOfficer", "Researcher", "ExternalClient")
    limit, offset = parse_pagination(request.args)
    items = list(store.publications.values())
    if is_entity_role():
        items = [p for p in items if p["user_id"] == auth_id()]
    else:
        user_id = request.args.get("user_id")
        if user_id is not None:
            items = [p for p in items if p["user_id"] == user_id]
    instrument_id = request.args.get("instrument_id")
    if instrument_id is not None:
        items = [p for p in items if instrument_id in (p.get("instrument_ids") or [])]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return paginate(sort_default(items), limit, offset, ser_publication)


@bp.route("/publications/<pid>", methods=["GET"])
def get_publication(pid):
    authenticate()
    require_roles("FacilityAdmin", "CoreStaff", "FinanceOfficer", "Researcher", "ExternalClient")
    pub = get_publication_or_404(pid)
    if is_entity_role() and pub["user_id"] != auth_id():
        fail("ERR_FORBIDDEN", "Entity-backed callers may only access their own resources")
    return ok_object(ser_publication(pub))


@bp.route("/publications/<pid>/verify", methods=["POST"])
def verify_publication(pid):
    authenticate()
    require_roles("CoreStaff")
    pub = get_publication_or_404(pid)
    body = Body(request.get_json(silent=True))
    if body.raw:
        for k in body.raw:
            fail("ERR_INVALID_REQUEST", "Unknown field in request body: %s" % k)
    if pub["status"] != "REPORTED":
        fail("ERR_INVALID_STATE", "Only a REPORTED publication can be verified")
    # Priority 29 — evidence: a VALIDATED usage log by the same user on a
    # listed instrument
    evidence = False
    for u in store.usage_logs.values():
        if u["status"] == "VALIDATED" and u["user_id"] == pub["user_id"] \
                and u["instrument_id"] in (pub.get("instrument_ids") or []):
            evidence = True
            break
    if not evidence:
        fail("ERR_PUBLICATION_EVIDENCE_MISSING",
             "No VALIDATED usage log by this user on any listed instrument")
    pub["status"] = "VERIFIED"
    pub["verified_by"] = auth_id()
    touch(pub)
    return ok_object(ser_publication(pub))


@bp.route("/publications/<pid>/reject", methods=["POST"])
def reject_publication(pid):
    authenticate()
    require_roles("CoreStaff")
    pub = get_publication_or_404(pid)
    body = Body(request.get_json(silent=True))
    if body.raw:
        for k in body.raw:
            if k not in ("reason",):
                fail("ERR_INVALID_REQUEST", "Unknown field in request body: %s" % k)
    if pub["status"] != "REPORTED":
        fail("ERR_INVALID_STATE", "Only a REPORTED publication can be rejected")
    pub["status"] = "REJECTED"
    touch(pub)
    return ok_object(ser_publication(pub))


# ---------------------------------------------------------------------------
# Test-driving logical clock
# ---------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate()
    require_roles("FacilityAdmin")
    body = Body(request.get_json(silent=True))
    validate_body(
        body,
        allowed={"to_iso8601"},
        required={"to_iso8601"},
        checkers={"to_iso8601": dt_ok},
    )
    store.clock = parse_dt(body.get("to_iso8601"))
    return ok_object({"current_utc": fmt_clock(store.clock)})
