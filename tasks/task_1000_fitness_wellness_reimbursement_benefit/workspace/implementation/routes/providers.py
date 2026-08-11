"""Provider endpoints: onboarding, lifecycle, contract amendment (OCC)."""
from flask import Blueprint, request

from db import STORE
from errors import (err, ERR_PROVIDER_NOT_FOUND, ERR_PROVIDER_NOT_ACTIVE,
                    ERR_PROVIDER_TERMINATED, ERR_STALE_VERSION,
                    ERR_INVALID_DATE_RANGE)
from middleware import require_roles
from response import success, paginate
from services.core import new_entity, touch, serialize, sort_created, terminate_provider_cascade
from util import (body_json, req, as_str, as_int, check_enum, parse_dt,
                  check_nonnegative)

bp = Blueprint("providers", __name__)

MODALITIES = ("GYM", "STUDIO", "APP", "POOL")
NETWORK_TIERS = ("IN_NETWORK", "PREFERRED", "OUT_OF_NETWORK")
READ_ROLES = ("BenefitsAdmin", "Auditor", "ClaimsReviewer", "Member", "ProviderOperator")


def get_provider(pid):
    p = STORE.providers.get(pid)
    if p is None:
        raise err(ERR_PROVIDER_NOT_FOUND, 404, "provider id does not resolve")
    return p


@bp.post("/api/providers")
def create_provider():
    require_roles("BenefitsAdmin")
    body = body_json()
    name = as_str(req(body, "name"), "name")
    modality = check_enum(req(body, "modality"), MODALITIES, "modality")
    network_tier = check_enum(req(body, "network_tier"), NETWORK_TIERS, "network_tier")
    cs_raw = req(body, "contract_start")
    ce_raw = req(body, "contract_end")
    rate = as_int(req(body, "visit_rate_cents"), "visit_rate_cents")
    check_nonnegative(rate, "visit_rate_cents")
    cs, ce = parse_dt(cs_raw), parse_dt(ce_raw)
    if ce <= cs:
        raise err(ERR_INVALID_DATE_RANGE, 400, "contract_end must be strictly after contract_start")
    p = new_entity()
    p.update({
        "name": name, "modality": modality, "network_tier": network_tier,
        "contract_start": cs_raw, "contract_end": ce_raw,
        "visit_rate_cents": rate,
        "status": "PENDING_ONBOARD",
        "_cs": cs, "_ce": ce,
        "_suspensions": [],   # list of (suspend_dt, reinstate_dt|None)
    })
    STORE.providers[p["id"]] = p
    return success(serialize(p), 201)


@bp.get("/api/providers/<pid>")
def read_provider(pid):
    require_roles(*READ_ROLES)
    return success(serialize(get_provider(pid)))


@bp.get("/api/providers")
def list_providers():
    require_roles(*READ_ROLES)
    items = sort_created(STORE.providers.values())
    network_tier = request.args.get("network_tier")
    status = request.args.get("status")
    if network_tier is not None:
        items = [p for p in items if p["network_tier"] == network_tier]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return paginate([serialize(p) for p in items])


def _provider_transition(pid, target, allowed_from):
    p = get_provider(pid)
    if p["status"] == "TERMINATED":
        raise err(ERR_PROVIDER_TERMINATED, 409, "provider TERMINATED")
    if p["status"] not in allowed_from:
        raise err(ERR_PROVIDER_NOT_ACTIVE, 409,
                  f"provider not in required state for transition to {target}")
    if target == "SUSPENDED":
        p["_suspensions"].append([STORE.clock, None])
    elif target == "ACTIVE" and p["status"] == "SUSPENDED":
        for s in p["_suspensions"]:
            if s[1] is None:
                s[1] = STORE.clock
    p["status"] = target
    touch(p)
    return p


@bp.post("/api/providers/<pid>/activate")
def activate_provider(pid):
    require_roles("BenefitsAdmin")
    return success(serialize(_provider_transition(pid, "ACTIVE", ("PENDING_ONBOARD",))))


@bp.post("/api/providers/<pid>/suspend")
def suspend_provider(pid):
    require_roles("BenefitsAdmin")
    return success(serialize(_provider_transition(pid, "SUSPENDED", ("ACTIVE",))))


@bp.post("/api/providers/<pid>/reinstate")
def reinstate_provider(pid):
    require_roles("BenefitsAdmin")
    return success(serialize(_provider_transition(pid, "ACTIVE", ("SUSPENDED",))))


@bp.post("/api/providers/<pid>/terminate")
def terminate_provider(pid):
    require_roles("BenefitsAdmin")
    p = get_provider(pid)
    if p["status"] == "TERMINATED":
        raise err(ERR_PROVIDER_TERMINATED, 409, "provider already TERMINATED")
    if p["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err(ERR_PROVIDER_NOT_ACTIVE, 409, "terminate requires ACTIVE or SUSPENDED")
    terminate_provider_cascade(p)
    p["status"] = "TERMINATED"
    touch(p)
    return success(serialize(p))


@bp.put("/api/providers/<pid>/contract")
def amend_contract(pid):
    require_roles("BenefitsAdmin")
    p = get_provider(pid)
    body = body_json()
    cs_raw = req(body, "contract_start")
    ce_raw = req(body, "contract_end")
    rate = as_int(req(body, "visit_rate_cents"), "visit_rate_cents")
    expected = as_int(req(body, "expected_provider_version"), "expected_provider_version")
    check_nonnegative(rate, "visit_rate_cents")
    cs, ce = parse_dt(cs_raw), parse_dt(ce_raw)
    if ce <= cs:
        raise err(ERR_INVALID_DATE_RANGE, 400, "contract_end must be strictly after contract_start")
    # state: amendment forbidden when TERMINATED
    if p["status"] == "TERMINATED":
        raise err(ERR_PROVIDER_TERMINATED, 409, "provider TERMINATED; contract amendment blocked")
    # OCC staleness
    if expected != p["version"]:
        raise err(ERR_STALE_VERSION, 412, "expected_provider_version does not match current version")
    p["contract_start"] = cs_raw
    p["contract_end"] = ce_raw
    p["visit_rate_cents"] = rate
    p["_cs"], p["_ce"] = cs, ce
    touch(p)
    return success(serialize(p))
