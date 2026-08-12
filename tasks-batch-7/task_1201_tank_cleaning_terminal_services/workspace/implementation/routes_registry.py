"""Configuration-plane resources: terminals, products, tanks, contractors,
safety events, inspectors, and the test-driving logical clock."""

from flask import Blueprint

from core import (
    db, ApiError, ALL_ROLES, auth, require_role, body_json, need, req_int,
    req_num, req_str, req_enum, req_dt, as_num, as_enum, get_or_404, create_entity,
    touch, ser, ok, paginate, sorted_all, apply_filters,
    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_FOUND,
    ERR_CONTRACTOR_NOT_QUALIFIED,
)
import calc
from services import refresh_contractor_score, contractor_score, sweep_clock

bp = Blueprint("registry", __name__)

SCORE_VARIANTS = {"ROLLING_12MO", "LIFETIME"}
PRODUCT_FAMILIES = {"GASOLINE", "DISTILLATE", "JET", "CRUDE", "CHEMICAL", "VEGOIL"}
VISCOSITY_CLASSES = {"LOW", "MEDIUM", "HIGH"}
SAFETY_KINDS = {"INCIDENT", "VIOLATION", "NEAR_MISS", "TRAINING_CREDIT"}
CERT_LEVELS = {"API653", "API650", "BOTH"}


# -------------------------------------------------------------- terminals ---


@bp.post("/terminals")
def create_terminal():
    auth_user, role = auth()
    require_role(role, {"TerminalAdmin"})
    b = body_json()
    name = req_str(b, "name")
    capacity = req_int(b, "wastewater_daily_capacity_liters")
    threshold = as_num(b.get("safety_score_threshold", 85.0), "safety_score_threshold")
    variant = as_enum(b.get("score_variant", "ROLLING_12MO"), "score_variant",
                      SCORE_VARIANTS)
    tolerance = as_num(b.get("mass_balance_tolerance_pct", 2.0),
                       "mass_balance_tolerance_pct")
    t = create_entity({
        "name": name,
        "wastewater_daily_capacity_liters": capacity,
        "safety_score_threshold": threshold,
        "score_variant": variant,
        "mass_balance_tolerance_pct": tolerance,
    })
    db.terminals[t["id"]] = t
    return ok(ser(t), 201)


@bp.get("/terminals/<terminalId>")
def get_terminal(terminalId):
    auth()
    return ok(ser(get_or_404(db.terminals, terminalId, "terminal")), 200)


@bp.get("/terminals")
def list_terminals():
    auth()
    page, pg = paginate(sorted_all(db.terminals))
    return ok([ser(e) for e in page], 200, pg)


# --------------------------------------------------------------- products ---


@bp.post("/products")
def create_product():
    auth_user, role = auth()
    require_role(role, {"TerminalAdmin"})
    b = body_json()
    p = create_entity({
        "code": req_str(b, "code"),
        "family": req_enum(b, "family", PRODUCT_FAMILIES),
        "viscosity_class": req_enum(b, "viscosity_class", VISCOSITY_CLASSES),
        "compatibility_group": req_str(b, "compatibility_group"),
        "flash_point_c": req_num(b, "flash_point_c"),
    })
    db.products[p["id"]] = p
    return ok(ser(p), 201)


@bp.get("/products/<productId>")
def get_product(productId):
    auth()
    return ok(ser(get_or_404(db.products, productId, "product")), 200)


@bp.get("/products")
def list_products():
    auth()
    page, pg = paginate(sorted_all(db.products))
    return ok([ser(e) for e in page], 200, pg)


# ------------------------------------------------------------------ tanks ---


@bp.post("/tanks")
def create_tank():
    auth_user, role = auth()
    require_role(role, {"TerminalAdmin"})
    b = body_json()
    terminal_id = req_str(b, "terminal_id")
    tank_number = req_str(b, "tank_number")
    capacity_m3 = req_int(b, "capacity_m3")
    current_product_id = req_str(b, "current_product_id")
    get_or_404(db.terminals, terminal_id, "terminal")
    get_or_404(db.products, current_product_id, "product")
    t = create_entity({
        "terminal_id": terminal_id,
        "tank_number": tank_number,
        "capacity_m3": capacity_m3,
        "current_product_id": current_product_id,
        "status": "IN_SERVICE",
    })
    db.tanks[t["id"]] = t
    return ok(ser(t), 201)


@bp.get("/tanks/<tankId>")
def get_tank(tankId):
    auth()
    return ok(ser(get_or_404(db.tanks, tankId, "tank")), 200)


@bp.get("/tanks")
def list_tanks():
    auth()
    items = apply_filters(sorted_all(db.tanks), [
        ("terminal_id", "terminal_id"),
        ("current_product_id", "current_product_id"),
        ("status", "status"),
    ])
    page, pg = paginate(items)
    return ok([ser(e) for e in page], 200, pg)


# ------------------------------------------------------------- contractors ---


@bp.post("/contractors")
def create_contractor():
    auth_user, role = auth()
    require_role(role, {"TerminalAdmin"})
    b = body_json()
    c = create_entity({
        "company_name": req_str(b, "company_name"),
        "status": "APPLICANT",
        "safety_score": 100.00,
    })
    db.contractors[c["id"]] = c
    return ok(ser(c), 201)


@bp.get("/contractors/<contractorId>")
def get_contractor(contractorId):
    auth()
    return ok(ser(get_or_404(db.contractors, contractorId, "contractor")), 200)


@bp.get("/contractors")
def list_contractors():
    auth()
    items = apply_filters(sorted_all(db.contractors), [("status", "status")])
    page, pg = paginate(items)
    return ok([ser(e) for e in page], 200, pg)


def _terminal_from_body(b):
    terminal_id = req_str(b, "terminal_id")
    return get_or_404(db.terminals, terminal_id, "terminal")


def _score_gate(contractor, terminal):
    """Inclusive threshold: a score exactly equal passes. The contractor's
    score is computed under that terminal's variant (PRD §3.2) and the
    computed value becomes the contractor's carried safety_score."""
    score = contractor_score(contractor["id"], terminal["score_variant"])
    if score < calc.Decimal(str(terminal["safety_score_threshold"])):
        raise ApiError(ERR_CONTRACTOR_NOT_QUALIFIED, 409,
                       "contractor safety score is below the terminal threshold")
    contractor["safety_score"] = float(score)
    return score


@bp.post("/contractors/<contractorId>/qualify")
def qualify_contractor(contractorId):
    auth_user, role = auth()
    require_role(role, {"TerminalAdmin"})
    c = get_or_404(db.contractors, contractorId, "contractor")
    b = body_json()
    terminal = _terminal_from_body(b)
    if c["status"] != "APPLICANT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only an APPLICANT contractor can be qualified")
    _score_gate(c, terminal)
    c["status"] = "QUALIFIED"
    touch(c)
    return ok(ser(c), 200)


@bp.post("/contractors/<contractorId>/suspend")
def suspend_contractor(contractorId):
    auth_user, role = auth()
    require_role(role, {"TerminalAdmin"})
    c = get_or_404(db.contractors, contractorId, "contractor")
    if c["status"] != "QUALIFIED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a QUALIFIED contractor can be suspended")
    c["status"] = "SUSPENDED"
    touch(c)
    return ok(ser(c), 200)


@bp.post("/contractors/<contractorId>/reinstate")
def reinstate_contractor(contractorId):
    auth_user, role = auth()
    require_role(role, {"TerminalAdmin"})
    c = get_or_404(db.contractors, contractorId, "contractor")
    b = body_json()
    terminal = _terminal_from_body(b)
    if c["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a SUSPENDED contractor can be reinstated")
    _score_gate(c, terminal)
    c["status"] = "QUALIFIED"
    touch(c)
    return ok(ser(c), 200)


@bp.post("/contractors/<contractorId>/bar")
def bar_contractor(contractorId):
    auth_user, role = auth()
    require_role(role, {"TerminalAdmin"})
    c = get_or_404(db.contractors, contractorId, "contractor")
    if c["status"] not in ("APPLICANT", "QUALIFIED", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "contractor cannot be barred from its current state")
    c["status"] = "BARRED"
    touch(c)
    return ok(ser(c), 200)


# ----------------------------------------------------------- safety events ---


@bp.post("/safety-events")
def create_safety_event():
    auth_user, role = auth()
    require_role(role, {"EHSOfficer"})
    b = body_json()
    contractor_id = req_str(b, "contractor_id")
    kind = req_enum(b, "kind", SAFETY_KINDS)
    weight = req_int(b, "severity_weight")
    occurred_at = req_dt(b, "occurred_at")
    contractor = get_or_404(db.contractors, contractor_id, "contractor")
    if weight < 1 or weight > 10:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "severity_weight must be between 1 and 10 inclusive")
    ev = create_entity({
        "contractor_id": contractor_id,
        "kind": kind,
        "severity_weight": weight,
        "occurred_at": occurred_at,
    }, common=False)  # append-only: id + created_at only, no updated_at/version
    db.safety_events[ev["id"]] = ev
    refresh_contractor_score(contractor)
    return ok(ser(ev), 201)


@bp.get("/safety-events/<eventId>")
def get_safety_event(eventId):
    auth()
    return ok(ser(get_or_404(db.safety_events, eventId, "safety event")), 200)


@bp.get("/safety-events")
def list_safety_events():
    auth()
    items = apply_filters(sorted_all(db.safety_events),
                          [("contractor_id", "contractor_id")])
    page, pg = paginate(items)
    return ok([ser(e) for e in page], 200, pg)


# -------------------------------------------------------------- inspectors ---


@bp.post("/inspectors")
def create_inspector():
    auth_user, role = auth()
    require_role(role, {"TerminalAdmin"})
    b = body_json()
    i = create_entity({
        "name": req_str(b, "name"),
        "certification_level": req_enum(b, "certification_level", CERT_LEVELS),
    })
    db.inspectors[i["id"]] = i
    return ok(ser(i), 201)


@bp.get("/inspectors/<inspectorId>")
def get_inspector(inspectorId):
    auth()
    return ok(ser(get_or_404(db.inspectors, inspectorId, "inspector")), 200)


@bp.get("/inspectors")
def list_inspectors():
    auth()
    page, pg = paginate(sorted_all(db.inspectors))
    return ok([ser(e) for e in page], 200, pg)


# ------------------------------------------------------------ logical clock ---


@bp.post("/_clock/set_current_utc")
def set_clock():
    auth_user, role = auth()
    require_role(role, {"TerminalAdmin"})
    b = body_json()
    to = req_dt(b, "to_iso8601")
    db.clock = to
    sweep_clock()
    from core import iso
    return ok({"current_utc": iso(db.clock)}, 200)
