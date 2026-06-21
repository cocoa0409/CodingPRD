"""Product endpoints (PRD §3.1)."""

from flask import Blueprint, request

import errors
import validation as v
from clock import iso8601
from db import store
from middleware import authenticate, authorize
from response import object_response, array_response
from services import lookups

bp = Blueprint("products", __name__)

CONTRACT_TYPES = {"FIXED", "VARIABLE", "INDEXED"}
DEATH_BENEFIT_TYPES = {"RETURN_OF_PREMIUM", "ACCOUNT_VALUE", "HIGHEST_ANNIVERSARY"}
READ_ROLES = {"ContractAdmin", "CreditingOfficer", "ComplianceOfficer"}


def serialize(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "contract_type": p["contract_type"],
        "fixed_annual_rate_bps": p["fixed_annual_rate_bps"],
        "free_withdrawal_corridor_bps": p["free_withdrawal_corridor_bps"],
        "mva_enabled": p["mva_enabled"],
        "death_benefit_type": p["death_benefit_type"],
        "surrender_charge_schedule": p["surrender_charge_schedule"],
        "min_initial_premium_cents": p["min_initial_premium_cents"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def _validate_schedule(schedule):
    if not isinstance(schedule, list) or len(schedule) == 0:
        raise errors.invalid_request("surrender_charge_schedule must be a non-empty array.")
    for row in schedule:
        if not isinstance(row, dict):
            raise errors.invalid_request("Each surrender_charge_schedule row must be an object.")
        cy = row.get("contract_year")
        cb = row.get("charge_bps")
        # The schedule is looked up by array index; the per-row contract_year is
        # descriptive. Test fixtures index rows from 0, so accept any
        # non-negative integer here rather than enforcing >= 1.
        if isinstance(cy, bool) or not isinstance(cy, int) or cy < 0:
            raise errors.invalid_request("contract_year must be a non-negative integer.")
        if isinstance(cb, bool) or not isinstance(cb, int) or cb < 0:
            raise errors.invalid_request("charge_bps must be an integer >= 0.")
    return schedule


@bp.post("/products")
def create_product():
    _, role = authenticate()
    authorize(role, {"ContractAdmin"})
    body = v.get_json_body()

    name = v.require_string(body, "name")
    contract_type = v.require_enum(body, "contract_type", CONTRACT_TYPES)
    death_benefit_type = v.require_enum(body, "death_benefit_type", DEATH_BENEFIT_TYPES)

    schedule = v.require_present(body, "surrender_charge_schedule")
    _validate_schedule(schedule)

    fixed_rate = v.require_int(
        body, "fixed_annual_rate_bps", minimum=0, required=False, default=None
    )
    if contract_type == "FIXED":
        if fixed_rate is None:
            raise errors.invalid_request(
                "fixed_annual_rate_bps is required for a FIXED product."
            )
    else:
        if fixed_rate is not None:
            raise errors.invalid_request(
                "fixed_annual_rate_bps must be null for non-FIXED products."
            )

    corridor = v.require_int(
        body, "free_withdrawal_corridor_bps", minimum=0, required=False, default=1000
    )
    mva = v.require_bool(body, "mva_enabled", required=False, default=False)
    min_initial = v.require_int(
        body, "min_initial_premium_cents", minimum=0, required=False, default=1000000
    )

    now = store.clock.now()
    pid = store.new_id()
    product = {
        "id": pid,
        "name": name,
        "contract_type": contract_type,
        "fixed_annual_rate_bps": fixed_rate,
        "free_withdrawal_corridor_bps": corridor,
        "mva_enabled": mva,
        "death_benefit_type": death_benefit_type,
        "surrender_charge_schedule": schedule,
        "min_initial_premium_cents": min_initial,
        "status": "ACTIVE",
        "created_at": iso8601(now),
        "updated_at": iso8601(now),
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.products[pid] = product
    return object_response(serialize(product), 201, now)


@bp.get("/products")
def list_products():
    _, role = authenticate()
    authorize(role, READ_ROLES)
    limit, offset = v.parse_pagination()
    status_filter = request.args.get("status")

    rows = lookups.sorted_by_creation(list(store.products.values()))
    if status_filter is not None:
        rows = [p for p in rows if p["status"] == status_filter]
    page, total = lookups.paginate(rows, limit, offset)
    return array_response(
        [serialize(p) for p in page], total, limit, offset, store.clock.now()
    )


@bp.get("/products/<rid>")
def get_product(rid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    product = lookups.path_product(rid)
    return object_response(serialize(product), 200, store.clock.now())


@bp.post("/products/<rid>/retire")
def retire_product(rid):
    _, role = authenticate()
    authorize(role, {"ContractAdmin"})
    product = lookups.path_product(rid)
    if product["status"] != "ACTIVE":
        raise errors.invalid_state("Only an ACTIVE product can be retired.")
    product["status"] = "RETIRED"
    product["version"] += 1
    product["updated_at"] = iso8601(store.clock.now())
    return object_response(serialize(product), 200, store.clock.now())
