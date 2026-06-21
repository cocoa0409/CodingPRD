"""Lease endpoints: create, lifecycle, escalation, percentage rent, ledger, payments
(PRD §3.3, §3.4, §3.5, §3.9)."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    APIError, ERR_NOT_FOUND, ERR_FK_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_CAPACITY_EXCEEDED, ERR_PCT_RENT_ALREADY_RUN, ERR_VALIDATION,
)
from middleware import auth_required, ALL_ROLES, PROPERTY_MANAGER, ACCOUNTANT
from response import ok_object, ok_array
from routes._helpers import (
    get_body, require_fields, serialize, serialize_list, is_int, is_number,
    parse_pagination, paginate, order_by_created,
)
from services.common import new_common_fields, touch
from services.ledger import post_ledger_entry
from services.calculations import (
    compute_escalated_base, latest_sales_report, compute_percentage_rent,
    compute_total_recoverable_cents,
)

bp = Blueprint("leases", __name__)

ESCALATION_TYPES = {"FIXED_PCT", "CPI", "NONE"}


def _recompute_occupied(prop: dict):
    """Property.occupied_sqft = sum of leased_sqft over ACTIVE/HOLDOVER leases (PRD §2.6)."""
    total = 0
    for l in db.leases.values():
        if l["property_id"] == prop["id"] and l["status"] in ("ACTIVE", "HOLDOVER"):
            total += l["leased_sqft"]
    prop["occupied_sqft"] = total


@bp.post("/leases")
def create_lease():
    auth_required({PROPERTY_MANAGER})()
    body = get_body()
    require_fields(body, ["property_id", "tenant_id", "leased_sqft", "base_rent_cents_annual"])

    property_id = body["property_id"]
    tenant_id = body["tenant_id"]
    if db.properties.get(property_id) is None:
        raise APIError(ERR_FK_NOT_FOUND, 404, "property_id references a non-existent property")
    if db.tenants.get(tenant_id) is None:
        raise APIError(ERR_FK_NOT_FOUND, 404, "tenant_id references a non-existent tenant")

    leased_sqft = body["leased_sqft"]
    if not is_int(leased_sqft) or leased_sqft <= 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "leased_sqft must be a positive integer")

    base_rent = body["base_rent_cents_annual"]
    if not is_int(base_rent) or base_rent < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "base_rent_cents_annual must be a non-negative integer")

    escalation_type = body.get("escalation_type", "NONE")
    if escalation_type not in ESCALATION_TYPES:
        raise APIError(ERR_INVALID_REQUEST, 400, "escalation_type is out of range")

    escalation_rate = body.get("escalation_rate", 0.0)
    if not is_number(escalation_rate) or not (0 <= escalation_rate <= 1):
        raise APIError(ERR_INVALID_REQUEST, 400, "escalation_rate must be in [0, 1]")

    cpi_base_index = body.get("cpi_base_index", None)
    if cpi_base_index is not None and not is_number(cpi_base_index):
        raise APIError(ERR_INVALID_REQUEST, 400, "cpi_base_index must be a number or null")

    pct_rent_rate = body.get("pct_rent_rate", 0.0)
    if not is_number(pct_rent_rate) or not (0 <= pct_rent_rate <= 1):
        raise APIError(ERR_INVALID_REQUEST, 400, "pct_rent_rate must be in [0, 1]")

    pct_rent_breakpoint = body.get("pct_rent_breakpoint_cents", 0)
    if not is_int(pct_rent_breakpoint) or pct_rent_breakpoint < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "pct_rent_breakpoint_cents must be a non-negative integer")

    controllable_cap_pct = body.get("controllable_cap_pct", 0.0)
    if not is_number(controllable_cap_pct) or not (0 <= controllable_cap_pct <= 1):
        raise APIError(ERR_INVALID_REQUEST, 400, "controllable_cap_pct must be in [0, 1]")

    prior_year_capped_base = body.get("prior_year_capped_base_cents", 0)
    if not is_int(prior_year_capped_base) or prior_year_capped_base < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "prior_year_capped_base_cents must be a non-negative integer")

    ti_allowance = body.get("ti_allowance_cents", 0)
    if not is_int(ti_allowance) or ti_allowance < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "ti_allowance_cents must be a non-negative integer")

    estimated_cam = body.get("estimated_cam_cents_monthly", 0)
    if not is_int(estimated_cam) or estimated_cam < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "estimated_cam_cents_monthly must be a non-negative integer")

    lease = {
        **new_common_fields(),
        "property_id": property_id,
        "tenant_id": tenant_id,
        "leased_sqft": leased_sqft,
        "base_rent_cents_annual": base_rent,
        "escalation_type": escalation_type,
        "escalation_rate": escalation_rate,
        "cpi_base_index": cpi_base_index,
        "pct_rent_rate": pct_rent_rate,
        "pct_rent_breakpoint_cents": pct_rent_breakpoint,
        "controllable_cap_pct": controllable_cap_pct,
        "prior_year_capped_base_cents": prior_year_capped_base,
        "ti_allowance_cents": ti_allowance,
        "ti_drawn_cents": 0,
        "estimated_cam_cents_monthly": estimated_cam,
        "outstanding_balance_cents": 0,
        "status": "DRAFT",
    }
    db.leases[lease["id"]] = lease
    return ok_object(serialize(lease), http_status=201)


@bp.get("/leases/<lid>")
def get_lease(lid):
    auth_required(ALL_ROLES)()
    l = db.leases.get(lid)
    if l is None:
        raise APIError(ERR_NOT_FOUND, 404, "Lease not found")
    return ok_object(serialize(l))


@bp.post("/leases/<lid>/activate")
def activate_lease(lid):
    auth_required({PROPERTY_MANAGER})()
    lease = db.leases.get(lid)
    if lease is None:
        raise APIError(ERR_NOT_FOUND, 404, "Lease not found")

    # State guard first (priority 8), then business constraints (PRD §2.9).
    if lease["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "Lease must be DRAFT to activate")

    prop = db.properties.get(lease["property_id"])
    tenant = db.tenants.get(lease["tenant_id"])
    if prop is None or tenant is None:
        # Referenced property/tenant must still exist.
        raise APIError(ERR_FK_NOT_FOUND, 404, "Referenced property or tenant not found")

    # CPI escalation requires a non-null cpi_base_index.
    if lease["escalation_type"] == "CPI" and lease["cpi_base_index"] is None:
        raise APIError(ERR_INVALID_REQUEST, 400, "CPI lease requires a non-null cpi_base_index")

    # Capacity check: leased_sqft must not exceed remaining capacity.
    remaining = prop["total_rentable_sqft"] - prop["occupied_sqft"]
    if lease["leased_sqft"] > remaining:
        raise APIError(ERR_CAPACITY_EXCEEDED, 422, "leased_sqft exceeds the property's remaining capacity")

    lease["status"] = "ACTIVE"
    touch(lease)

    # Cascade: property occupied_sqft += leased_sqft (recompute), bump property version.
    _recompute_occupied(prop)
    touch(prop)

    # Post BASE_RENT ledger entry of +base_rent_cents_annual; recompute balance.
    post_ledger_entry(lease, "BASE_RENT", lease["base_rent_cents_annual"])
    touch(lease)

    return ok_object(serialize(lease))


@bp.post("/leases/<lid>/holdover")
def holdover_lease(lid):
    auth_required({PROPERTY_MANAGER})()
    lease = db.leases.get(lid)
    if lease is None:
        raise APIError(ERR_NOT_FOUND, 404, "Lease not found")
    if lease["status"] != "ACTIVE":
        raise APIError(ERR_INVALID_STATE, 409, "Lease must be ACTIVE to move to HOLDOVER")
    lease["status"] = "HOLDOVER"
    touch(lease)
    return ok_object(serialize(lease))


@bp.post("/leases/<lid>/terminate")
def terminate_lease(lid):
    auth_required({PROPERTY_MANAGER})()
    lease = db.leases.get(lid)
    if lease is None:
        raise APIError(ERR_NOT_FOUND, 404, "Lease not found")
    if lease["status"] not in ("ACTIVE", "HOLDOVER"):
        raise APIError(ERR_INVALID_STATE, 409, "Lease must be ACTIVE or HOLDOVER to terminate")

    # Blocked while any reconciliation for this lease is DRAFT/IN_REVIEW/DISPUTED.
    for r in db.reconciliations.values():
        if r["lease_id"] == lid and r["status"] in ("DRAFT", "IN_REVIEW", "DISPUTED"):
            raise APIError(ERR_INVALID_STATE, 409,
                           "Cannot terminate while an open reconciliation is pending")

    lease["status"] = "TERMINATED"
    touch(lease)

    prop = db.properties.get(lease["property_id"])
    if prop is not None:
        _recompute_occupied(prop)
        touch(prop)

    return ok_object(serialize(lease))


@bp.post("/leases/<lid>/escalate")
def escalate_lease(lid):
    auth_required({PROPERTY_MANAGER})()
    lease = db.leases.get(lid)
    if lease is None:
        raise APIError(ERR_NOT_FOUND, 404, "Lease not found")
    body = get_body()

    current_cpi_index = body.get("current_cpi_index", None)
    if lease["escalation_type"] == "CPI":
        if current_cpi_index is None:
            raise APIError(ERR_INVALID_REQUEST, 400, "current_cpi_index is required for a CPI lease")
        if not is_number(current_cpi_index):
            raise APIError(ERR_INVALID_REQUEST, 400, "current_cpi_index must be a number")
    elif current_cpi_index is not None and not is_number(current_cpi_index):
        raise APIError(ERR_INVALID_REQUEST, 400, "current_cpi_index must be a number")

    old_base = lease["base_rent_cents_annual"]
    new_base = compute_escalated_base(lease, current_cpi_index)
    delta = new_base - old_base
    lease["base_rent_cents_annual"] = new_base

    # Post BASE_RENT ledger entry for the delta; recompute balance; bump lease version.
    post_ledger_entry(lease, "BASE_RENT", delta)
    touch(lease)

    return ok_object(serialize(lease))


@bp.post("/leases/<lid>/percentage-rent-run")
def percentage_rent_run(lid):
    auth_required({PROPERTY_MANAGER, ACCOUNTANT})()
    lease = db.leases.get(lid)
    if lease is None:
        raise APIError(ERR_NOT_FOUND, 404, "Lease not found")
    body = get_body()
    require_fields(body, ["period_year"])
    period_year = body["period_year"]
    if not is_int(period_year) or period_year < 2000:
        raise APIError(ERR_INVALID_REQUEST, 400, "period_year must be an integer >= 2000")

    # A second run for an already-run (lease, period_year) is rejected.
    runs = lease.setdefault("_pct_rent_runs", [])
    if period_year in runs:
        raise APIError(ERR_PCT_RENT_ALREADY_RUN, 409,
                       "Percentage rent has already been run for this lease and year")

    report = latest_sales_report(lid, period_year)
    if report is None:
        # No SalesReport for this (lease, year). A SalesReport is neither a path
        # resource nor one of the five named body FKs, so PRD §2.9 reserves
        # neither ERR_NOT_FOUND (path resources) nor ERR_FK_NOT_FOUND for it.
        # An empty latest-report selector is a business-rule violation with no
        # more specific error, so it falls to the ERR_VALIDATION (422) fallback.
        raise APIError(ERR_VALIDATION, 422, "No sales report found for this lease and period")

    pct_rent = compute_percentage_rent(lease, report)
    post_ledger_entry(lease, "PCT_RENT", pct_rent)
    runs.append(period_year)
    touch(lease)

    return ok_object(serialize(lease))


@bp.get("/leases/<lid>/ledger")
def list_ledger(lid):
    auth_required(ALL_ROLES)()
    if db.leases.get(lid) is None:
        raise APIError(ERR_NOT_FOUND, 404, "Lease not found")
    limit, offset = parse_pagination()
    items = order_by_created([e for e in db.ledger_entries.values() if e["lease_id"] == lid])
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)


@bp.post("/leases/<lid>/payments")
def record_payment(lid):
    auth_required({PROPERTY_MANAGER, ACCOUNTANT})()
    lease = db.leases.get(lid)
    if lease is None:
        raise APIError(ERR_NOT_FOUND, 404, "Lease not found")
    body = get_body()
    require_fields(body, ["amount_cents"])
    amount_cents = body["amount_cents"]
    if not is_int(amount_cents) or amount_cents < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "amount_cents must be a non-negative integer")

    # PAYMENT ledger entry of -amount_cents; recompute balance; bump lease version.
    entry = post_ledger_entry(lease, "PAYMENT", -amount_cents)
    touch(lease)

    return ok_object(serialize(entry), http_status=201)
