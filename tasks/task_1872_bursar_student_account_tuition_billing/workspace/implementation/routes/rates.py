from flask import Blueprint

from db import store, base_fields
from dates import req_date, parse_date
from errors import (err, ERR_INVALID_REQUEST, ERR_TERM_NOT_FOUND,
                    ERR_RATE_WINDOW_OVERLAP)
from middleware import auth_context, require_roles
from response import success, json_body, req_str, req_int, req_enum, list_response
from serialize import ser_rate

bp = Blueprint("rates", __name__)

RESIDENCIES = ("IN_STATE", "OUT_OF_STATE", "INTERNATIONAL")
LEVELS = ("UNDERGRADUATE", "GRADUATE")


@bp.post("/bursar/tuition-rates")
def create_rate():
    _, role = auth_context()
    require_roles(role, "RegistrarStaff")
    body = json_body()
    term_id = req_str(body, "term_id")
    residency = req_enum(body, "residency", RESIDENCIES)
    level = req_enum(body, "level", LEVELS)
    per_credit = req_int(body, "per_credit_rate_cents")
    threshold = req_int(body, "full_time_threshold_credits")
    flat = req_int(body, "flat_rate_cents")
    max_flat = req_int(body, "max_flat_credits")
    overload = req_int(body, "overload_rate_cents")
    eff_from = req_date(body, "effective_from")
    eff_to = req_date(body, "effective_to")

    # Existence of the body-supplied term id.
    if term_id not in store.terms:
        raise err(ERR_TERM_NOT_FOUND, "Term not found")

    # Field constraints: all rates positive except overload (may be zero);
    # max_flat_credits at least the full-time threshold.
    if per_credit <= 0 or threshold <= 0 or flat <= 0 or overload < 0:
        raise err(ERR_INVALID_REQUEST, "Rate amounts must be positive (overload may be zero)")
    if max_flat < threshold:
        raise err(ERR_INVALID_REQUEST,
                  "max_flat_credits must be at least full_time_threshold_credits")
    # CLOSED effective window: end must not precede start.
    if eff_to < eff_from:
        raise err(ERR_INVALID_REQUEST, "effective_to must not precede effective_from")

    # Overlap: same (term, residency, level), CLOSED intervals; touching
    # endpoints already count as overlap.
    for r in store.rates.values():
        if (r["term_id"] == term_id and r["residency"] == residency
                and r["level"] == level):
            if eff_from <= parse_date(r["effective_to"]) and \
                    parse_date(r["effective_from"]) <= eff_to:
                raise err(ERR_RATE_WINDOW_OVERLAP,
                          "Rate window overlaps an existing rate for this term/residency/level")

    r = base_fields()
    r.update({
        "term_id": term_id, "residency": residency, "level": level,
        "per_credit_rate_cents": per_credit,
        "full_time_threshold_credits": threshold,
        "flat_rate_cents": flat, "max_flat_credits": max_flat,
        "overload_rate_cents": overload,
        "effective_from": eff_from.isoformat(), "effective_to": eff_to.isoformat(),
    })
    store.rates[r["id"]] = r
    return success(ser_rate(r), status=201)


@bp.get("/bursar/terms/<tid>/tuition-rates")
def list_rates(tid):
    _, role = auth_context()
    require_roles(role, "Student", "RegistrarStaff", "BursarStaff", "BursarManager")
    if tid not in store.terms:
        raise err(ERR_TERM_NOT_FOUND, "Term not found")
    rows = [r for r in store.rates.values() if r["term_id"] == tid]
    rows.sort(key=lambda r: r["_seq"])
    return list_response(rows, ser_rate)
