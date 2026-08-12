"""OREOProperty endpoints, carrying costs, and the broker-recommendation selector."""
from decimal import Decimal

import db
import domain
from domain import (property_json, summary_json, cost_json, broker_json, basis_from,
                    charge_off, sort_entities, TERMINAL_LIFECYCLE)
from envelope import success
from errors import ApiError
from routes.common import (require_roles, body, req_str, req_enum, req_num, req_date,
                           opt_str, paginate, get_or_404)
from util import new_id, now_iso, q2, is_date_only

ALL_ROLES = ("OREOAdmin", "PropertyManager", "OREOSpecialist", "Appraiser", "ChiefAppraiser",
             "CreditOfficer", "OREOCommittee", "ComplianceOfficer", "Broker")
PROPERTY_TYPES = ("RESIDENTIAL", "COMMERCIAL", "INDUSTRIAL", "LAND")
COST_TYPES = ("TAXES", "INSURANCE", "MAINTENANCE", "UTILITIES", "HOA", "CAPITAL_IMPROVEMENT")


def create_property():
    require_roles("OREOAdmin")
    d = body()
    address = req_str(d, "address")
    state_code = req_str(d, "state_code")
    county = req_str(d, "county")
    property_type = req_enum(d, "property_type", PROPERTY_TYPES)
    acquisition_date = req_date(d, "acquisition_date")
    bpo_value = req_num(d, "bpo_value")
    foreclosure_debt = req_num(d, "foreclosure_debt")
    p = domain.base_entity()
    p.update({
        "address": address,
        "state_code": state_code,
        "county": county,
        "property_type": property_type,
        "acquisition_date": acquisition_date,
        "_acq_date_only": is_date_only(acquisition_date),
        "bpo_value": bpo_value,
        "foreclosure_debt": foreclosure_debt,
        # PROVISIONAL acquisition accounting variant at intake.
        "fair_value_at_acquisition": bpo_value,
        "acquisition_basis": basis_from(bpo_value),
        "lifecycle_status": "HELD",
    })
    db.properties[p["id"]] = p
    domain.ledger_append(p["id"], "ACQUISITION", p["acquisition_basis"],
                         "Property taken into OREO at provisional fair value")
    return success(property_json(p), 201)


def list_properties():
    require_roles(*ALL_ROLES)
    lifecycle = request_arg("lifecycle_status")
    appraisal = request_arg("appraisal_status")
    state_code = request_arg("state_code")
    items = []
    for p in db.properties.values():
        if lifecycle is not None and p["lifecycle_status"] != lifecycle:
            continue
        if state_code is not None and p["state_code"] != state_code:
            continue
        if appraisal is not None and domain.appraisal_status(p) != appraisal:
            continue
        items.append(p)
    return paginate(sort_entities(items), property_json)


def get_property(prop_id):
    require_roles(*ALL_ROLES)
    return success(property_json(get_or_404(db.properties, prop_id, "Property")))


def get_summary(prop_id):
    require_roles(*ALL_ROLES)
    return success(summary_json(get_or_404(db.properties, prop_id, "Property")))


def manual_charge_off(prop_id):
    require_roles("ComplianceOfficer")
    p = get_or_404(db.properties, prop_id, "Property")
    if p["lifecycle_status"] in TERMINAL_LIFECYCLE:
        raise ApiError("ERR_PROPERTY_ALREADY_TERMINAL", 409, "Property is already terminal")
    charge_off(p)
    return success(property_json(p), 200)


def broker_recommendation(prop_id):
    require_roles("OREOAdmin", "PropertyManager", "OREOSpecialist")
    p = get_or_404(db.properties, prop_id, "Property")
    pool = [b for b in db.brokers.values()
            if b["status"] == "ACTIVE" and p["state_code"] in b["coverage_states"]]
    if not pool:
        raise ApiError("ERR_NO_ELIGIBLE_BROKER", 422, "No eligible broker covers this property")
    scored = [(domain.broker_performance_score(b), b) for b in pool]
    scored.sort(key=lambda t: (t[0] is None,
                               -(t[0]) if t[0] is not None else Decimal(0),
                               t[1]["created_at"], t[1]["_seq"]))
    return paginate([b for (_, b) in scored], broker_json)


def request_arg(name):
    from flask import request
    v = request.args.get(name)
    return v if v not in (None, "") else None


# ---- Carrying costs ----

def create_cost():
    require_roles("PropertyManager")
    d = body()
    property_id = req_str(d, "property_id")
    cost_type = req_enum(d, "cost_type", COST_TYPES)
    amount = req_num(d, "amount")
    incurred_date = req_date(d, "incurred_date")
    description = opt_str(d, "description")
    p = get_or_404(db.properties, property_id, "Property")
    if p["lifecycle_status"] in TERMINAL_LIFECYCLE:
        raise ApiError("ERR_PROPERTY_ALREADY_TERMINAL", 409,
                       "Cannot post carrying costs to a terminal property")
    amt = q2(amount)  # pinned: round per entry at posting, then aggregate
    c = domain.append_only_entity()
    c.update({
        "property_id": property_id,
        "cost_type": cost_type,
        "amount": amt,
        "incurred_date": incurred_date,
        "description": description,
    })
    db.costs[c["id"]] = c
    domain.ledger_append(property_id, "CARRYING_COST", -amt, "Carrying cost: %s" % cost_type)
    domain.bump(p)
    return success(cost_json(c), 201)


def list_costs():
    require_roles(*ALL_ROLES)
    pid = request_arg("property_id")
    ctype = request_arg("cost_type")
    items = [c for c in db.costs.values()
             if (pid is None or c["property_id"] == pid)
             and (ctype is None or c["cost_type"] == ctype)]
    return paginate(sort_entities(items), cost_json)


def get_cost(cost_id):
    require_roles(*ALL_ROLES)
    return success(cost_json(get_or_404(db.costs, cost_id, "Carrying cost")))
