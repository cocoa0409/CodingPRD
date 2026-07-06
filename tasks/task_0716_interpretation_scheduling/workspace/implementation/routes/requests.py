from flask import Blueprint, request as flask_request

from db import db
from errors import err
from clock import parse_iso
from middleware import authenticate, require_role
from response import ok, ok_list
from helpers import get_body, paginate, sort_by_created, require_fields, check_enum
from services import constants as C
from services import calc
from services import engine

bp = Blueprint("requests", __name__)


def _windows_overlap_half_open(s1, e1, s2, e2):
    # half-open [s,e): overlap iff s1 < e2 and s2 < e1
    return s1 < e2 and s2 < e1


def _windows_overlap_closed(s1, e1, s2, e2):
    # closed [s,e]: overlap iff s1 <= e2 and s2 <= e1
    return s1 <= e2 and s2 <= e1


# ===================== Create / fetch / list =====================

@bp.post("/interpretation/requests")
def create_request():
    uid, role = authenticate()
    require_role(role, {"ClientAccount"})
    body = get_body()
    require_fields(body, ["client_id", "language_pair_id", "modality", "required_tier", "scheduling_mode"])
    # FK resolution
    client = db.clients.get(body["client_id"])
    if client is None:
        raise err("ERR_FK_NOT_FOUND", "client_id not found")
    if db.language_pairs.get(body["language_pair_id"]) is None:
        raise err("ERR_FK_NOT_FOUND", "language_pair_id not found")
    # well-formedness
    check_enum(body["modality"], C.MODALITIES, "modality")
    check_enum(body["required_tier"], C.CERT_TIERS, "required_tier")
    check_enum(body["scheduling_mode"], C.SCHEDULING_MODES, "scheduling_mode")
    mode = body["scheduling_mode"]
    ws = body.get("window_start")
    we = body.get("window_end")
    if mode == "ON_DEMAND":
        if ws is not None or we is not None:
            raise err("ERR_INVALID_REQUEST", "window fields must be omitted for ON_DEMAND")
    else:  # SCHEDULED
        if ws is None or we is None:
            raise err("ERR_INVALID_REQUEST", "window_start and window_end required for SCHEDULED")
        try:
            ws_dt = parse_iso(ws)
            we_dt = parse_iso(we)
        except Exception:
            raise err("ERR_INVALID_REQUEST", "Invalid window datetime")
        if not (we_dt > ws_dt):
            raise err("ERR_INVALID_WINDOW", "window_end must be strictly after window_start")
    # ownership: acting client must be the client_id
    if uid != body["client_id"]:
        raise err("ERR_NOT_OWNER", "Client may only file own requests")
    # suspension guard
    if client["status"] == "SUSPENDED":
        raise err("ERR_CLIENT_SUSPENDED", "Client account is suspended")
    # credit guard
    if client["outstanding_balance_cents"] > client["credit_limit_cents"]:
        raise err("ERR_CREDIT_LIMIT_EXCEEDED", "Client over credit limit")
    # client-window conflict (SCHEDULED, half-open)
    if mode == "SCHEDULED":
        for other in db.requests.values():
            if (other["client_id"] == body["client_id"]
                    and other["scheduling_mode"] == "SCHEDULED"
                    and other["status"] in ("OPEN", "ASSIGNED")):
                ows = parse_iso(other["window_start"])
                owe = parse_iso(other["window_end"])
                if _windows_overlap_half_open(ws_dt, we_dt, ows, owe):
                    raise err("ERR_CLIENT_WINDOW_CONFLICT", "Window overlaps an existing scheduled request")
    entity = db.base_fields()
    entity.update({
        "client_id": body["client_id"],
        "language_pair_id": body["language_pair_id"],
        "modality": body["modality"],
        "required_tier": body["required_tier"],
        "scheduling_mode": mode,
        "window_start": ws if mode == "SCHEDULED" else None,
        "window_end": we if mode == "SCHEDULED" else None,
        "status": "OPEN",
        "cancellation_fee_cents": 0,
    })
    db.requests[entity["id"]] = entity
    return ok(entity, 201)


@bp.get("/interpretation/requests/<rid>")
def get_request(rid):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "CoordinatorOps", "ClientAccount"})
    engine.sweep_expired_offers()
    r = db.requests.get(rid)
    if not r:
        raise err("ERR_RESOURCE_NOT_FOUND", "Request not found")
    return ok(r)


@bp.get("/interpretation/requests")
def list_requests():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "CoordinatorOps", "ClientAccount"})
    engine.sweep_expired_offers()
    rows = list(db.requests.values())
    cid = flask_request.args.get("client_id")
    lpid = flask_request.args.get("language_pair_id")
    status = flask_request.args.get("status")
    if cid is not None:
        rows = [r for r in rows if r["client_id"] == cid]
    if lpid is not None:
        rows = [r for r in rows if r["language_pair_id"] == lpid]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_by_created(rows)
    window, limit, offset, total = paginate(rows)
    return ok_list(window, limit, offset, total)


# ===================== Dispatch =====================

def _has_valid_cert(interp_id, tier):
    now = db.clock.now()
    for c in db.certifications.values():
        if (c["interpreter_id"] == interp_id and c["tier"] == tier
                and not c["revoked"] and now < parse_iso(c["expires_at"])):
            return True
    return False


def _services_language(interp_id, lpid):
    for j in db.interpreter_languages.values():
        if j["interpreter_id"] == interp_id and j["language_pair_id"] == lpid:
            return True
    return False


def _double_booked(interp_id, req):
    """True if interpreter holds another non-terminal SCHEDULED assignment whose
    request window overlaps req's window under CLOSED-interval semantics."""
    ws = parse_iso(req["window_start"])
    we = parse_iso(req["window_end"])
    for a in db.assignments.values():
        if a["interpreter_id"] != interp_id:
            continue
        if a["assignment_type"] != "SCHEDULED":
            continue
        if a["lifecycle_status"] not in ("OFFERED", "ACCEPTED", "IN_SESSION"):
            continue
        other_req = db.requests.get(a["request_id"])
        if not other_req or other_req["scheduling_mode"] != "SCHEDULED":
            continue
        if other_req["id"] == req["id"]:
            continue
        ows = parse_iso(other_req["window_start"])
        owe = parse_iso(other_req["window_end"])
        if _windows_overlap_closed(ws, we, ows, owe):
            return True
    return False


@bp.post("/interpretation/requests/<rid>/dispatch")
def dispatch_request(rid):
    _, role = authenticate()
    require_role(role, {"CoordinatorOps"})
    engine.sweep_expired_offers()
    req = db.requests.get(rid)
    if not req:
        raise err("ERR_RESOURCE_NOT_FOUND", "Request not found")
    body = get_body()
    require_fields(body, ["expected_request_version"])
    ev = body["expected_request_version"]
    if not isinstance(ev, int) or isinstance(ev, bool):
        raise err("ERR_INVALID_REQUEST", "expected_request_version must be an integer")
    # state
    if req["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Request is not OPEN")
    client = db.clients.get(req["client_id"])
    if client and client["status"] == "SUSPENDED":
        raise err("ERR_CLIENT_SUSPENDED", "Client account is suspended")
    # OCC
    if ev != req["version"]:
        raise err("ERR_STALE_REQUEST_VERSION", "Stale request version")

    # ---- eligibility filter ----
    base_qualified = []  # interpreters with cert+language (used for error discrimination)
    eligible = []
    for interp in db.interpreters.values():
        has_lang = _services_language(interp["id"], req["language_pair_id"])
        has_cert = _has_valid_cert(interp["id"], req["required_tier"])
        if has_lang and has_cert:
            base_qualified.append(interp)
        if interp["status"] != "AVAILABLE":
            continue
        if interp["active_load"] >= interp["max_concurrent_load"]:
            continue
        if not has_lang or not has_cert:
            continue
        eligible.append(interp)

    if req["scheduling_mode"] == "SCHEDULED":
        non_double = [i for i in eligible if not _double_booked(i["id"], req)]
        if eligible and not non_double:
            # the only obstacle is double booking
            raise err("ERR_INTERPRETER_DOUBLE_BOOKED", "Chosen interpreter is double-booked")
        eligible = non_double

    if not eligible:
        if not base_qualified:
            # no interpreter holds a valid required-tier cert for the language pair
            raise err("ERR_NO_QUALIFIED_INTERPRETER", "No interpreter with valid certification for the pair")
        # qualified interpreters exist but none currently eligible (capacity/availability):
        # ordinary empty-candidate-set -> UNFULFILLABLE
        req["status"] = "UNFULFILLABLE"
        db.touch(req)
        # Dispatch transitions an existing request to UNFULFILLABLE; no new
        # resource is minted, so per PRD §4 status rule this returns HTTP 200.
        return ok(req, 200)

    winner = _select_winner(eligible)
    assignment = db.base_fields()
    assignment.update({
        "request_id": req["id"],
        "interpreter_id": winner["id"],
        "lifecycle_status": "OFFERED",
        "billing_status": "UNBILLED",
        "offered_at": db.clock.now_iso(),
        "assignment_type": req["scheduling_mode"],
        "_was_accepted": False,
        "_accepted_at": None,
    })
    db.assignments[assignment["id"]] = assignment
    req["status"] = "ASSIGNED"
    db.touch(req)
    return ok(assignment, 201)


def _select_winner(candidates):
    scored = []
    for c in candidates:
        scored.append((calc.selection_score(c), c["active_load"], c["_seq"], c))
    # highest score; tie-break lowest active_load, then earliest created (_seq)
    scored.sort(key=lambda t: (-t[0], t[1], t[2]))
    return scored[0][3]


# ===================== Cancel =====================

@bp.post("/interpretation/requests/<rid>/cancel")
def cancel_request(rid):
    uid, role = authenticate()
    require_role(role, {"ClientAccount"})
    engine.sweep_expired_offers()
    req = db.requests.get(rid)
    if not req:
        raise err("ERR_RESOURCE_NOT_FOUND", "Request not found")
    if req["status"] not in ("OPEN", "ASSIGNED"):
        raise err("ERR_INVALID_STATE", "Request cannot be cancelled in its current state")
    if uid != req["client_id"]:
        raise err("ERR_NOT_OWNER", "Client does not own this request")

    # find outstanding assignment
    outstanding = None
    for a in db.assignments.values():
        if a["request_id"] == req["id"] and a["lifecycle_status"] in ("OFFERED", "ACCEPTED"):
            outstanding = a
            break

    # if ASSIGNED, the session beneath must not have reached ACTIVE
    if req["status"] == "ASSIGNED":
        for a in db.assignments.values():
            if a["request_id"] == req["id"]:
                for s in db.sessions.values():
                    if s["assignment_id"] == a["id"] and s["status"] not in ("CONNECTING",):
                        # any session that progressed beyond CONNECTING blocks cancel
                        if s["status"] in ("ACTIVE", "ENDED", "DISPUTED", "RECONCILED",
                                            "CLIENT_NO_SHOW", "INTERPRETER_NO_SHOW"):
                            raise err("ERR_INVALID_STATE", "Session already active")

    # compute fee
    plan = calc.find_active_rate_plan(req["client_id"], req["required_tier"], req["modality"])
    if req["scheduling_mode"] == "ON_DEMAND":
        fee = 0
    else:
        if plan is None:
            raise err("ERR_NO_RATE_PLAN", "No active rate plan for this request")
        fee = calc.cancellation_fee(req, plan)
    req["cancellation_fee_cents"] = fee

    # cascade assignment
    if outstanding is not None:
        outstanding["lifecycle_status"] = "CANCELLED"
        outstanding["billing_status"] = "BILLABLE" if fee > 0 else "WAIVED"
        db.touch(outstanding)
        interp = db.interpreters.get(outstanding["interpreter_id"])
        if interp:
            was_busy = interp["status"] == "BUSY"
            engine.recompute_active_load(interp)
            if was_busy and interp["active_load"] < interp["max_concurrent_load"]:
                interp["status"] = "AVAILABLE"
            db.touch(interp)

    req["status"] = "CANCELLED"
    db.touch(req)
    return ok(req)
