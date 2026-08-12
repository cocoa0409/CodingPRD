"""Appraisers, Brokers, ApprovalTiers."""
import db
import domain
from domain import appraiser_json, broker_json, tier_json, sort_entities, ROLE_RANK
from envelope import success
from errors import ApiError
from routes.common import (require_roles, body, req_str, req_num, opt_num, opt_str,
                           req_enum, req_str_list, paginate, get_or_404)
from routes.properties import ALL_ROLES, request_arg

TIER_ROLES = ("OREOSpecialist", "CreditOfficer", "OREOCommittee")


# ---- Appraisers ----

def create_appraiser():
    require_roles("OREOAdmin")
    d = body()
    a = domain.base_entity()
    a.update({
        "name": req_str(d, "name"),
        "license_number": req_str(d, "license_number"),
        "coverage_states": req_str_list(d, "coverage_states"),
        "fee_flat": req_num(d, "fee_flat"),
    })
    db.appraisers[a["id"]] = a
    return success(appraiser_json(a), 201)


def list_appraisers():
    require_roles(*ALL_ROLES)
    return paginate(sort_entities(list(db.appraisers.values())), appraiser_json)


def get_appraiser(entity_id):
    require_roles(*ALL_ROLES)
    return success(appraiser_json(get_or_404(db.appraisers, entity_id, "Appraiser")))


# ---- Brokers ----

def create_broker():
    require_roles("OREOAdmin")
    d = body()
    b = domain.base_entity()
    b.update({
        "name": req_str(d, "name"),
        "license_number": req_str(d, "license_number"),
        "coverage_states": req_str_list(d, "coverage_states"),
        "status": "ACTIVE",
    })
    db.brokers[b["id"]] = b
    return success(broker_json(b), 201)


def list_brokers():
    require_roles(*ALL_ROLES)
    status = request_arg("status")
    state_code = request_arg("state_code")
    items = [b for b in db.brokers.values()
             if (status is None or b["status"] == status)
             and (state_code is None or state_code in b["coverage_states"])]
    return paginate(sort_entities(items), broker_json)


def get_broker(entity_id):
    require_roles(*ALL_ROLES)
    return success(broker_json(get_or_404(db.brokers, entity_id, "Broker")))


def patch_broker(entity_id):
    require_roles("OREOAdmin")
    b = get_or_404(db.brokers, entity_id, "Broker")
    d = body()
    name = opt_str(d, "name")
    if name is not None:
        b["name"] = name
    if "coverage_states" in d and d["coverage_states"] is not None:
        b["coverage_states"] = req_str_list(d, "coverage_states")
    if "status" in d and d["status"] is not None:
        new_status = req_enum(d, "status", ("ACTIVE", "SUSPENDED"))
        if new_status != b["status"]:
            # Broker state machine: ACTIVE <-> SUSPENDED.
            b["status"] = new_status
    domain.bump(b)
    return success(broker_json(b), 200)


# ---- Approval tiers ----

def create_tier():
    require_roles("OREOAdmin")
    d = body()
    name = req_str(d, "name")
    min_np = req_num(d, "min_net_proceeds")
    max_np = opt_num(d, "max_net_proceeds")  # null = unbounded
    required_role = req_enum(d, "required_role", TIER_ROLES)
    if max_np is not None and max_np <= min_np:
        raise ApiError("ERR_VALIDATION", 400, "max_net_proceeds must be greater than min_net_proceeds")
    # Half-open [min, max) intervals must not overlap; adjacency allowed.
    for t in db.tiers.values():
        other_hi = t["max_net_proceeds"]
        lo_ok = (min_np < other_hi) if other_hi is not None else True
        hi_ok = (t["min_net_proceeds"] < max_np) if max_np is not None else True
        if lo_ok and hi_ok:
            raise ApiError("ERR_TIER_OVERLAP", 409, "Approval tier interval overlaps an existing tier")
    t = domain.base_entity()
    t.update({
        "name": name,
        "min_net_proceeds": min_np,
        "max_net_proceeds": max_np,
        "required_role": required_role,
        "required_rank": ROLE_RANK[required_role],
    })
    db.tiers[t["id"]] = t
    return success(tier_json(t), 201)


def list_tiers():
    require_roles(*ALL_ROLES)
    return paginate(sort_entities(list(db.tiers.values())), tier_json)
