"""Discharge permit and waste sample endpoints."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

from db import store, get_clock, format_ts
from errors import (
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_PERMIT_NOT_EXCEEDED,
    ERR_PERMIT_WINDOW_OVERLAP,
    ERR_SAMPLE_MONTH_REGRESSION,
    ERR_SAMPLE_OUTSIDE_PERMIT_WINDOW,
    raise_err,
)
from helpers import (
    body_json,
    check_number,
    check_string,
    get_or_404,
    is_number,
    paginate,
    parse_date,
    parse_iso8601,
    parse_pagination,
    stamp_event,
    stamp_new,
    touch,
)
from middleware import require_roles, STAFF_ROLES
from response import success_list, success_object
from serializers import permit_view, sample_view
from services.cascades import exceedance_cascade

bp = Blueprint("permits", __name__)

ANALYTES = {"NICKEL", "ZINC", "COPPER", "CHROME", "CYANIDE"}


def _round3(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


@bp.route("/discharge-permits", methods=["POST"])
def create_permit():
    user_id, role = require_roles({"EHSOfficer", "ShopManager"})
    data = body_json()
    outfall_code = check_string(data, "outfall_code", required=True)
    effective_from = data.get("effective_from")
    effective_to = data.get("effective_to")
    d_from = parse_date(effective_from, field="effective_from")
    d_to = parse_date(effective_to, field="effective_to")
    if d_to < d_from:
        raise_err(ERR_INVALID_REQUEST, "effective_to must be >= effective_from")

    limits = data.get("limits")
    if not isinstance(limits, list) or len(limits) < 1:
        raise_err(ERR_INVALID_REQUEST, "limits must be a non-empty array")
    seen = set()
    parsed_limits = []
    for entry in limits:
        if not isinstance(entry, dict):
            raise_err(ERR_INVALID_REQUEST, "each limit must be an object")
        analyte = entry.get("analyte_code")
        if analyte not in ANALYTES:
            raise_err(ERR_INVALID_REQUEST, "analyte_code must be one of NICKEL, ZINC, COPPER, CHROME, CYANIDE")
        if analyte in seen:
            raise_err(ERR_INVALID_REQUEST, "duplicate analyte_code within a permit")
        seen.add(analyte)
        max_conc = entry.get("max_concentration_mg_l")
        if not is_number(max_conc) or not (max_conc > 0):
            raise_err(ERR_INVALID_REQUEST, "max_concentration_mg_l must be a number > 0")
        mass_cap = entry.get("monthly_mass_cap_g")
        if not is_number(mass_cap) or not (mass_cap > 0):
            raise_err(ERR_INVALID_REQUEST, "monthly_mass_cap_g must be a number > 0")
        parsed_limits.append({
            "analyte_code": analyte,
            "max_concentration_mg_l": max_conc,
            "monthly_mass_cap_g": mass_cap,
        })

    # Tier 9: closed-closed window overlap per outfall (sharing a boundary IS overlap)
    for p in store.permits.values():
        if p["outfall_code"] != outfall_code:
            continue
        p_from = parse_date(p["effective_from"])
        p_to = parse_date(p["effective_to"])
        if d_from <= p_to and p_from <= d_to:
            raise_err(ERR_PERMIT_WINDOW_OVERLAP, "permit window overlaps an existing permit for this outfall")

    permit = stamp_new({
        "outfall_code": outfall_code,
        "effective_from": d_from.strftime("%Y-%m-%d"),
        "effective_to": d_to.strftime("%Y-%m-%d"),
        "limits": parsed_limits,
        "current_month": None,
        "cumulative_mass_g": {},
        "last_sampled_at": None,
        "exceedance_active": False,
        "status": "ACTIVE",
    })
    store.permits[permit["id"]] = permit
    return success_object(permit_view(permit), status=201)


@bp.route("/discharge-permits/<permit_id>", methods=["GET"])
def get_permit(permit_id):
    user_id, role = require_roles(STAFF_ROLES)
    permit = get_or_404(store.permits, permit_id)
    return success_object(permit_view(permit))


@bp.route("/discharge-permits/<permit_id>/samples", methods=["POST"])
def create_sample(permit_id):
    user_id, role = require_roles({"EHSOfficer", "ShopManager"})
    permit = get_or_404(store.permits, permit_id)
    data = body_json()

    # Tier 5: schema
    flow_liters = check_number(data, "flow_liters", required=True, gt=0)
    readings = data.get("readings")
    if not isinstance(readings, list) or len(readings) < 1:
        raise_err(ERR_INVALID_REQUEST, "readings must be a non-empty array")
    permit_analytes = {l["analyte_code"] for l in permit["limits"]}
    seen = set()
    parsed_readings = []
    for entry in readings:
        if not isinstance(entry, dict):
            raise_err(ERR_INVALID_REQUEST, "each reading must be an object")
        analyte = entry.get("analyte_code")
        if analyte not in ANALYTES or analyte not in permit_analytes:
            raise_err(ERR_INVALID_REQUEST, "reading analyte must exist in the permit's limits")
        if analyte in seen:
            raise_err(ERR_INVALID_REQUEST, "duplicate analyte within one sample")
        seen.add(analyte)
        conc = entry.get("concentration_mg_l")
        if not is_number(conc) or not (conc >= 0):
            raise_err(ERR_INVALID_REQUEST, "concentration_mg_l must be a number >= 0")
        parsed_readings.append({"analyte_code": analyte, "concentration_mg_l": conc})

    sampled_at_raw = data.get("sampled_at")
    if sampled_at_raw is None:
        sampled_dt = get_clock()
        sampled_at = format_ts(sampled_dt)
    else:
        sampled_dt = parse_iso8601(sampled_at_raw, field="sampled_at")
        sampled_at = format_ts(sampled_dt)

    # Tier 9: temporal — permit window containment (closed interval on dates)
    sample_date = sampled_dt.date()
    if sample_date < parse_date(permit["effective_from"]) or sample_date > parse_date(permit["effective_to"]):
        raise_err(ERR_SAMPLE_OUTSIDE_PERMIT_WINDOW, "sampled_at is outside the permit window")

    # Month bucketing
    sample_month = sampled_dt.strftime("%Y-%m")
    current_month = permit["current_month"]
    if current_month is not None and sample_month < current_month:
        raise_err(ERR_SAMPLE_MONTH_REGRESSION, "sample month is earlier than the permit's current month")

    # Mass accounting: round each per-analyte mass to 3 decimals FIRST
    masses_g = {}
    for r in parsed_readings:
        mass = _round3(Decimal(str(r["concentration_mg_l"])) * Decimal(str(flow_liters)) / Decimal("1000"))
        masses_g[r["analyte_code"]] = mass

    if current_month is None or sample_month > current_month:
        # RESET
        permit["current_month"] = sample_month
        permit["cumulative_mass_g"] = dict(masses_g)
    else:
        cumulative = dict(permit["cumulative_mass_g"])
        for analyte, mass in masses_g.items():
            prev = Decimal(str(cumulative.get(analyte, Decimal("0"))))
            cumulative[analyte] = prev + mass
        permit["cumulative_mass_g"] = cumulative

    permit["last_sampled_at"] = sampled_at

    # Exceedance: instantaneous (strict) or cumulative (strict); equality compliant
    exceeded_analytes = set()
    limits_by_analyte = {l["analyte_code"]: l for l in permit["limits"]}
    is_exceedance = False
    for r in parsed_readings:
        limit = limits_by_analyte[r["analyte_code"]]
        if Decimal(str(r["concentration_mg_l"])) > Decimal(str(limit["max_concentration_mg_l"])):
            is_exceedance = True
            exceeded_analytes.add(r["analyte_code"])
    for analyte, mass in masses_g.items():
        limit = limits_by_analyte[analyte]
        cum = Decimal(str(permit["cumulative_mass_g"].get(analyte, Decimal("0"))))
        if cum > Decimal(str(limit["monthly_mass_cap_g"])):
            is_exceedance = True
            exceeded_analytes.add(analyte)

    sample = stamp_event({
        "permit_id": permit["id"],
        "sampled_at": sampled_at,
        "flow_liters": flow_liters,
        "readings": parsed_readings,
        "masses_g": masses_g,
        "is_exceedance": is_exceedance,
    })
    store.samples[sample["id"]] = sample
    touch(permit)

    if is_exceedance:
        exceedance_cascade(permit, exceeded_analytes)

    return success_object(sample_view(sample), status=201)


@bp.route("/discharge-permits/<permit_id>/samples", methods=["GET"])
def list_samples(permit_id):
    user_id, role = require_roles(STAFF_ROLES)
    permit = get_or_404(store.permits, permit_id)
    limit, offset = parse_pagination()
    items = [s for s in store.samples.values() if s["permit_id"] == permit["id"]]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([sample_view(s) for s in page], limit, offset, total)


@bp.route("/discharge-permits/<permit_id>/clear-exceedance", methods=["POST"])
def clear_exceedance(permit_id):
    user_id, role = require_roles({"EHSOfficer", "ShopManager"})
    permit = get_or_404(store.permits, permit_id)
    if permit["status"] != "EXCEEDED":
        raise_err(ERR_PERMIT_NOT_EXCEEDED, "clear-exceedance requires permit EXCEEDED")
    permit["status"] = "ACTIVE"
    permit["exceedance_active"] = False
    touch(permit)
    return success_object(permit_view(permit))
