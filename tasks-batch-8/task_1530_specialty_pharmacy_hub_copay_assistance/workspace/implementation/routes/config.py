"""Drug programs, foundation pools, and the logical clock."""

from flask import Blueprint

from db import store, new_id, now_iso, set_logical_clock
from errors import ApiError, ERR_VALIDATION
from middleware import require_roles, get_auth
from response import success_object
from services.common import (
    body, req_string, req_bool, req_int, req_date, req_datetime,
    get_pool_or_404,
)
from services.calc import serialize_program, serialize_pool

bp = Blueprint("config", __name__)


@bp.post("/hub/drug-programs")
def create_drug_program():
    require_roles("HubAdmin")
    data = body()
    name = req_string(data, "name")
    manufacturer_name = req_string(data, "manufacturer_name")
    diagnosis_code = req_string(data, "diagnosis_code")
    requires_injection_training = req_bool(data, "requires_injection_training")
    requires_cold_chain = req_bool(data, "requires_cold_chain")
    max_transit_hours = req_int(data, "max_transit_hours")
    min_days_between_fills = req_int(data, "min_days_between_fills")
    copay_card_per_fill_cap_cents = req_int(data, "copay_card_per_fill_cap_cents")
    copay_card_annual_cap_cents = req_int(data, "copay_card_annual_cap_cents")
    default_days_supply = req_int(data, "default_days_supply")

    ts = now_iso()
    program = {
        "id": new_id(),
        "name": name,
        "manufacturer_name": manufacturer_name,
        "diagnosis_code": diagnosis_code,
        "requires_injection_training": requires_injection_training,
        "requires_cold_chain": requires_cold_chain,
        "max_transit_hours": max_transit_hours,
        "min_days_between_fills": min_days_between_fills,
        "copay_card_per_fill_cap_cents": copay_card_per_fill_cap_cents,
        "copay_card_annual_cap_cents": copay_card_annual_cap_cents,
        "default_days_supply": default_days_supply,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.drug_programs[program["id"]] = program
    return success_object(serialize_program(program), 201)


@bp.post("/hub/foundation-pools")
def create_foundation_pool():
    require_roles("HubAdmin")
    data = body()
    name = req_string(data, "name")
    diagnosis_code = req_string(data, "diagnosis_code")
    total_funding_cents = req_int(data, "total_funding_cents")
    grant_amount_cents = req_int(data, "grant_amount_cents")
    coverage_pct = req_int(data, "coverage_pct")
    if coverage_pct < 0 or coverage_pct > 100:
        raise ApiError(ERR_VALIDATION, "coverage_pct must be between 0 and 100.", 400)
    start_d = req_date(data, "start_date")
    end_d = req_date(data, "end_date")

    ts = now_iso()
    pool = {
        "id": new_id(),
        "name": name,
        "diagnosis_code": diagnosis_code,
        "total_funding_cents": total_funding_cents,
        "grant_amount_cents": grant_amount_cents,
        "coverage_pct": coverage_pct,
        "start_date": start_d.isoformat(),
        "end_date": end_d.isoformat(),
        "remaining_balance_cents": total_funding_cents,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.foundation_pools[pool["id"]] = pool
    return success_object(serialize_pool(pool), 201)


@bp.get("/hub/foundation-pools/<pool_id>")
def get_foundation_pool(pool_id):
    get_auth()
    pool = get_pool_or_404(pool_id)
    return success_object(serialize_pool(pool), 200)


@bp.get("/hub/foundation-pools/<pool_id>/copay-assistances")
def list_pool_assistances(pool_id):
    get_auth()
    pool = get_pool_or_404(pool_id)
    from services.common import pagination_params, paginate
    from services.calc import serialize_assistance
    limit, offset = pagination_params()
    items = [a for a in store.copay_assistances.values()
             if a["assistance_type"] == "FOUNDATION"
             and a["foundation_pool_id"] == pool["id"]]
    page, total = paginate(items, limit, offset)
    from response import success_array
    return success_array([serialize_assistance(a) for a in page],
                         limit, offset, total, 200)


@bp.post("/hub/_clock/set_current_utc")
def set_clock():
    require_roles("HubAdmin")
    data = body()
    target = req_datetime(data, "to_iso8601")
    new_clock = set_logical_clock(target.isoformat())
    # Report the resulting clock reading as current_utc (ISO8601 UTC).
    out = new_clock.strftime("%Y-%m-%dT%H:%M:%S.")
    out += f"{new_clock.microsecond // 1000:03d}Z"
    return success_object({"current_utc": out}, 200)
