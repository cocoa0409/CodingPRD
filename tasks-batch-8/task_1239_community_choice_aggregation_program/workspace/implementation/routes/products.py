"""Product and RateSchedule endpoints (PRD §3.4)."""

from flask import Blueprint, g, request

from auth import require_roles
from envelope import ok_object, paginate
from errors import (ApiError, ERR_FISCAL_GATE, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_NO_DEFAULT_PRODUCT,
                    ERR_REFERENCED_NOT_FOUND, ERR_REFERENTIAL_STATE,
                    ERR_SEGREGATION_OF_DUTIES, ERR_UNIQUENESS_CONFLICT)
from serializers import ser_product, ser_schedule
from services import compute_margin_bps, get_or_404
from store import STORE
from util import as_enum, as_number, as_str, fmt_dt, get_body, parse_dt

bp = Blueprint("products", __name__)

ELECTION_KEYS = {"DEFAULT", "OPT_UP_100", "OPT_DOWN_ECONOMY"}


def _present(body, field):
    if field not in body or body[field] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Missing required field '{field}'")
    return body[field]


@bp.post("/cca/products")
@require_roles("RateAnalyst")
def create_product():
    body = get_body(request)
    # Uniqueness (priority 11) before field validity (priority 16).
    code = body.get("product_code")
    ekey = body.get("election_key")
    if isinstance(code, str):
        for p in STORE.products.values():
            if p["product_code"] == code:
                raise ApiError(ERR_UNIQUENESS_CONFLICT, 409,
                               f"product_code '{code}' already exists")
    if isinstance(ekey, str):
        for p in STORE.products.values():
            if p["election_key"] == ekey:
                raise ApiError(ERR_UNIQUENESS_CONFLICT, 409,
                               f"election_key '{ekey}' already exists for this authority")
    code = as_str(_present(body, "product_code"), "product_code")
    ekey = as_enum(_present(body, "election_key"), "election_key", ELECTION_KEYS)
    pct = as_number(_present(body, "renewable_pct"), "renewable_pct")
    if not (0 <= float(pct) <= 1.0):
        raise ApiError(ERR_INVALID_REQUEST, 400, "renewable_pct must lie between 0 and 1.0")
    rec = STORE.new_record()
    rec.update({
        "product_code": code,
        "election_key": ekey,
        "renewable_pct": pct,
        "status": "DRAFT",
        "is_default": False,
    })
    STORE.products[rec["id"]] = rec
    return ok_object(ser_product(rec), status=201)


@bp.get("/cca/products")
@require_roles("RateAnalyst", "BoardDirector", "CustomerService", "ProgramOperator")
def list_products():
    items = list(STORE.products.values())
    st = request.args.get("status")
    if st is not None:
        items = [p for p in items if p["status"] == st]
    ek = request.args.get("election_key")
    if ek is not None:
        items = [p for p in items if p["election_key"] == ek]
    items.sort(key=lambda p: (p["_created_dt"], p["_seq"]))
    return paginate(items, ser_product)


@bp.get("/cca/products/<pid>")
@require_roles("RateAnalyst", "BoardDirector", "CustomerService")
def get_product(pid):
    return ok_object(ser_product(get_or_404(STORE.products, pid, "Product")))


@bp.post("/cca/products/<pid>/adopt")
@require_roles("BoardDirector")
def adopt_product(pid):
    prod = get_or_404(STORE.products, pid, "Product")
    if prod["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"Product in status {prod['status']} cannot be adopted")
    has_adopted_schedule = any(
        s["product_id"] == prod["id"] and s["status"] == "ADOPTED"
        for s in STORE.schedules.values())
    if not has_adopted_schedule:
        raise ApiError(ERR_REFERENTIAL_STATE, 422,
                       "Product adoption requires at least one ADOPTED rate schedule")
    if prod["election_key"] == "DEFAULT":
        for p in STORE.products.values():
            if (p["id"] != prod["id"] and p["election_key"] == "DEFAULT"
                    and p["status"] == "ADOPTED"):
                raise ApiError(ERR_UNIQUENESS_CONFLICT, 409,
                               "Another ADOPTED default product already exists")
    prod["status"] = "ADOPTED"
    if prod["election_key"] == "DEFAULT":
        prod["is_default"] = True
    STORE.touch(prod)
    return ok_object(ser_product(prod))


@bp.post("/cca/products/<pid>/retire")
@require_roles("BoardDirector")
def retire_product(pid):
    prod = get_or_404(STORE.products, pid, "Product")
    if prod["status"] != "ADOPTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"Product in status {prod['status']} cannot be retired")
    for a in STORE.accounts.values():
        if (a["product_election"] == prod["election_key"]
                and a["enrollment_state"] == "ENROLLED"):
            raise ApiError(ERR_REFERENTIAL_STATE, 422,
                           "Enrolled accounts currently take this product's election")
    if prod["is_default"]:
        other = any(p["id"] != prod["id"] and p["election_key"] == "DEFAULT"
                    and p["status"] == "ADOPTED" for p in STORE.products.values())
        if not other:
            raise ApiError(ERR_NO_DEFAULT_PRODUCT, 422,
                           "Retiring the default product requires another ADOPTED default product")
    prod["status"] = "RETIRED"
    prod["is_default"] = False
    STORE.touch(prod)
    return ok_object(ser_product(prod))


@bp.get("/cca/products/<pid>/rate-schedules")
@require_roles("RateAnalyst", "BoardDirector", "CustomerService")
def product_schedules(pid):
    prod = get_or_404(STORE.products, pid, "Product")
    items = [s for s in STORE.schedules.values() if s["product_id"] == prod["id"]]
    items.sort(key=lambda s: (s["_created_dt"], s["_seq"]))
    return paginate(items, ser_schedule)


# --- rate schedules -----------------------------------------------------------

def _validate_rates(body, current=None):
    """Validate the rate/window fields present in body; merge onto current."""
    merged = dict(current) if current else {}
    out = {}
    if "period_start" in body and body["period_start"] is not None:
        out["_period_start"] = parse_dt(body["period_start"], "period_start")
        out["period_start"] = fmt_dt(out["_period_start"])
    if "period_end" in body and body["period_end"] is not None:
        out["_period_end"] = parse_dt(body["period_end"], "period_end")
        out["period_end"] = fmt_dt(out["_period_end"])
    for f in ("energy_rate_cents_per_kwh", "pcia_rate_cents_per_kwh",
              "incumbent_benchmark_rate_cents_per_kwh"):
        if f in body and body[f] is not None:
            out[f] = as_number(body[f], f)
    merged.update(out)
    if "_period_start" in merged and "_period_end" in merged:
        if merged["_period_end"] <= merged["_period_start"]:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "period_end must be strictly after period_start")
    if "energy_rate_cents_per_kwh" in merged and float(merged["energy_rate_cents_per_kwh"]) <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "energy_rate_cents_per_kwh must be > 0")
    if "pcia_rate_cents_per_kwh" in merged and float(merged["pcia_rate_cents_per_kwh"]) < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "pcia_rate_cents_per_kwh must be >= 0")
    if ("incumbent_benchmark_rate_cents_per_kwh" in merged
            and float(merged["incumbent_benchmark_rate_cents_per_kwh"]) <= 0):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "incumbent_benchmark_rate_cents_per_kwh must be > 0")
    return out


@bp.post("/cca/rate-schedules")
@require_roles("RateAnalyst")
def create_schedule():
    body = get_body(request)
    product_id = body.get("product_id")
    if product_id is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing required field 'product_id'")
    if product_id not in STORE.products:
        raise ApiError(ERR_REFERENCED_NOT_FOUND, 404, f"Product '{product_id}' not found")
    for f in ("period_start", "period_end", "energy_rate_cents_per_kwh",
              "pcia_rate_cents_per_kwh", "incumbent_benchmark_rate_cents_per_kwh"):
        _present(body, f)
    vals = _validate_rates(body)
    margin = compute_margin_bps(vals["energy_rate_cents_per_kwh"],
                                vals["incumbent_benchmark_rate_cents_per_kwh"])
    rec = STORE.new_record()
    rec.update({
        "product_id": product_id,
        "period_start": vals["period_start"],
        "_period_start": vals["_period_start"],
        "period_end": vals["period_end"],
        "_period_end": vals["_period_end"],
        "energy_rate_cents_per_kwh": vals["energy_rate_cents_per_kwh"],
        "pcia_rate_cents_per_kwh": vals["pcia_rate_cents_per_kwh"],
        "incumbent_benchmark_rate_cents_per_kwh": vals["incumbent_benchmark_rate_cents_per_kwh"],
        "comparison_margin_bps": margin,
        "status": "DRAFT",
        "adopted_by": None,
        "proposed_by": None,
    })
    STORE.schedules[rec["id"]] = rec
    return ok_object(ser_schedule(rec), status=201)


@bp.get("/cca/rate-schedules")
@require_roles("RateAnalyst", "BoardDirector", "CustomerService")
def list_schedules():
    items = list(STORE.schedules.values())
    pid = request.args.get("product_id")
    if pid is not None:
        items = [s for s in items if s["product_id"] == pid]
    st = request.args.get("status")
    if st is not None:
        items = [s for s in items if s["status"] == st]
    items.sort(key=lambda s: (s["_created_dt"], s["_seq"]))
    return paginate(items, ser_schedule)


@bp.get("/cca/rate-schedules/<sid>")
@require_roles("RateAnalyst", "BoardDirector", "CustomerService")
def get_schedule(sid):
    return ok_object(ser_schedule(get_or_404(STORE.schedules, sid, "RateSchedule")))


@bp.put("/cca/rate-schedules/<sid>")
@require_roles("RateAnalyst")
def update_schedule(sid):
    sched = get_or_404(STORE.schedules, sid, "RateSchedule")
    if sched["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"RateSchedule in status {sched['status']} cannot be updated")
    body = get_body(request)
    vals = _validate_rates(body, current=sched)
    sched.update(vals)
    sched["comparison_margin_bps"] = compute_margin_bps(
        sched["energy_rate_cents_per_kwh"], sched["incumbent_benchmark_rate_cents_per_kwh"])
    STORE.touch(sched)
    return ok_object(ser_schedule(sched))


@bp.post("/cca/rate-schedules/<sid>/propose")
@require_roles("RateAnalyst")
def propose_schedule(sid):
    sched = get_or_404(STORE.schedules, sid, "RateSchedule")
    if sched["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"RateSchedule in status {sched['status']} cannot be proposed")
    if sched["_period_end"] <= sched["_period_start"]:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "period_end must be strictly after period_start")
    prod = STORE.products.get(sched["product_id"])
    if prod is None or prod["status"] not in ("DRAFT", "ADOPTED"):
        raise ApiError(ERR_REFERENTIAL_STATE, 422,
                       "Parent product must be DRAFT or ADOPTED to propose a schedule")
    sched["proposed_by"] = g.user_id
    sched["comparison_margin_bps"] = compute_margin_bps(
        sched["energy_rate_cents_per_kwh"], sched["incumbent_benchmark_rate_cents_per_kwh"])
    sched["status"] = "PROPOSED"
    STORE.touch(sched)
    return ok_object(ser_schedule(sched))


@bp.post("/cca/rate-schedules/<sid>/adopt")
@require_roles("BoardDirector")
def adopt_schedule(sid):
    sched = get_or_404(STORE.schedules, sid, "RateSchedule")
    if sched["status"] != "PROPOSED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"RateSchedule in status {sched['status']} cannot be adopted")
    if g.user_id == sched["proposed_by"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 422,
                       "The adopting BoardDirector must differ from the proposing RateAnalyst")
    for other in STORE.schedules.values():
        if (other["id"] != sched["id"] and other["product_id"] == sched["product_id"]
                and other["status"] == "ADOPTED"
                and other["_period_start"] < sched["_period_end"]
                and sched["_period_start"] < other["_period_end"]):
            # A window fully contained in the new one is superseded, not a conflict.
            contained = (sched["_period_start"] <= other["_period_start"]
                         and other["_period_end"] <= sched["_period_end"])
            if not contained:
                raise ApiError(ERR_UNIQUENESS_CONFLICT, 409,
                               "An ADOPTED schedule for this product already overlaps this window")
    auth = STORE.authority()
    if auth is not None and auth["rate_setting_policy"] == "DISCOUNT_TO_INCUMBENT":
        if sched["comparison_margin_bps"] < auth["discount_floor_bps"]:
            raise ApiError(ERR_FISCAL_GATE, 422,
                           "comparison_margin_bps is below the authority's discount_floor_bps")
    sched["adopted_by"] = g.user_id
    sched["status"] = "ADOPTED"
    STORE.touch(sched)
    # Cascade hop 1: fully contained ADOPTED schedules for this product -> SUPERSEDED.
    superseded = False
    for other in STORE.schedules.values():
        if (other["id"] != sched["id"] and other["product_id"] == sched["product_id"]
                and other["status"] == "ADOPTED"
                and sched["_period_start"] <= other["_period_start"]
                and other["_period_end"] <= sched["_period_end"]):
            other["status"] = "SUPERSEDED"
            STORE.touch(other)
            superseded = True
    # Cascade hop 2: supersession refreshes the parent product.
    if superseded:
        prod = STORE.products.get(sched["product_id"])
        if prod is not None:
            STORE.touch(prod)
    return ok_object(ser_schedule(sched))


@bp.post("/cca/rate-schedules/<sid>/reject")
@require_roles("BoardDirector")
def reject_schedule(sid):
    sched = get_or_404(STORE.schedules, sid, "RateSchedule")
    if sched["status"] != "PROPOSED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"RateSchedule in status {sched['status']} cannot be rejected")
    if g.user_id == sched["proposed_by"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 422,
                       "The rejecting BoardDirector must differ from the proposing RateAnalyst")
    sched["status"] = "REJECTED"
    STORE.touch(sched)
    return ok_object(ser_schedule(sched))
