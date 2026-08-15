"""Brand customers and co-manufacturing agreements."""
from flask import Blueprint, request

import serialize
from db import STORES, base_record, touch
from errors import (
    not_found, invalid_request, invalid_enum, invalid_state, terminal_locked,
    unprocessable,
    ERR_CUSTOMER_NOT_FOUND, ERR_AGREEMENT_NOT_FOUND, ERR_CUSTOMER_SUSPENDED,
    ERR_STALE_VERSION,
)
from middleware import require_roles, rep_list_scope, rep_owns_customer
from response import ok_object, list_response
from services import calc
from util import (
    get_body, require, opt, check_str, check_int, check_enum, check_array,
    parse_dt,
)

bp = Blueprint("commercial", __name__)

READ_ROLES = ("PlantAdmin", "FormulationScientist", "QualityManager",
              "ProductionPlanner", "LabTechnician")
AGREEMENT_READ_ROLES = ("PlantAdmin", "ProductionPlanner", "QualityManager",
                        "BrandCustomerRep")

CUSTOMER_STATUS = ["ACTIVE", "SUSPENDED"]
AGREEMENT_STATUS = ["NEGOTIATION", "ACTIVE", "SUSPENDED", "TERMINATED"]
PRICING_MODES = ["MARGINAL", "AVERAGE"]
FINAL_TIER_UPTO = 999999999


def _sorted(name):
    return sorted(STORES[name].values(), key=lambda r: r["_seq"])


def _get_customer(cid):
    rec = STORES["customers"].get(cid)
    if rec is None:
        raise not_found(ERR_CUSTOMER_NOT_FOUND, f"Brand customer {cid} does not exist")
    return rec


def _get_agreement(aid):
    rec = STORES["agreements"].get(aid)
    if rec is None:
        raise not_found(ERR_AGREEMENT_NOT_FOUND,
                        f"Manufacturing agreement {aid} does not exist")
    return rec


# ---------------- customers ----------------

@bp.post("/mfg/customers")
def create_customer():
    require_roles("PlantAdmin")
    body = get_body(request)
    rec = base_record()
    rec.update({
        "name": check_str(require(body, "name"), "name"),
        "contact_email": check_str(require(body, "contact_email"), "contact_email"),
        "status": check_enum(opt(body, "status", "ACTIVE"), "status", CUSTOMER_STATUS),
    })
    STORES["customers"][rec["id"]] = rec
    return ok_object(serialize.customer(rec), 201)


@bp.get("/mfg/customers")
def list_customers():
    require_roles(*READ_ROLES)
    items = _sorted("customers")
    st = request.args.get("status")
    if st is not None:
        check_enum(st, "status", CUSTOMER_STATUS)
        items = [c for c in items if c["status"] == st]
    return list_response([serialize.customer(c) for c in items])


@bp.get("/mfg/customers/<cid>")
def get_customer(cid):
    require_roles(*READ_ROLES)
    return ok_object(serialize.customer(_get_customer(cid)))


# ---------------- agreements ----------------

def _validate_tier_breaks(v):
    check_array(v, "tier_breaks", min_len=1)
    tiers = []
    prev = None
    for i, entry in enumerate(v):
        if not isinstance(entry, dict):
            raise invalid_request(f"tier_breaks[{i}] must be an object")
        upto = check_int(require(entry, "upto_cases"), "tier_breaks.upto_cases")
        if upto <= 0:
            raise invalid_request("tier_breaks.upto_cases must be > 0")
        rate = check_int(require(entry, "rate_cents_per_case"),
                         "tier_breaks.rate_cents_per_case")
        if rate < 0:
            raise invalid_request("tier_breaks.rate_cents_per_case must be >= 0")
        if prev is not None and upto <= prev:
            raise invalid_request("tier_breaks must be sorted ascending by upto_cases")
        prev = upto
        tiers.append({"upto_cases": upto, "rate_cents_per_case": rate})
    if tiers[-1]["upto_cases"] != FINAL_TIER_UPTO:
        raise invalid_request(
            "tier_breaks final tier must have upto_cases == 999999999")
    return tiers


@bp.post("/mfg/agreements")
def create_agreement():
    require_roles("PlantAdmin")
    body = get_body(request)
    customer = None
    if "customer_id" in body and body["customer_id"] is not None:
        customer = STORES["customers"].get(body["customer_id"])
        if customer is None:
            raise not_found(ERR_CUSTOMER_NOT_FOUND,
                            f"Brand customer {body['customer_id']} does not exist")
    if customer is None:
        raise invalid_request("Missing required field 'customer_id'")
    # Stage 6 shape checks
    pricing_raw = require(body, "pricing_mode")
    check_str(pricing_raw, "pricing_mode")
    moq = check_int(require(body, "moq_cases_per_run"), "moq_cases_per_run")
    if moq <= 0:
        raise invalid_request("Field 'moq_cases_per_run' must be > 0")
    committed = check_int(require(body, "committed_cases_per_quarter"),
                          "committed_cases_per_quarter")
    if committed <= 0:
        raise invalid_request("Field 'committed_cases_per_quarter' must be > 0")
    tiers = _validate_tier_breaks(require(body, "tier_breaks"))
    quarter_start = parse_dt(require(body, "quarter_start"), "quarter_start")
    # Stage 7 enum membership
    pricing_mode = check_enum(pricing_raw, "pricing_mode", PRICING_MODES)
    if customer["status"] != "ACTIVE":
        raise unprocessable(ERR_CUSTOMER_SUSPENDED,
                            "SUSPENDED customers cannot create agreements")
    rec = base_record()
    rec.update({
        "customer_id": customer["id"],
        "pricing_mode": pricing_mode,
        "moq_cases_per_run": moq,
        "committed_cases_per_quarter": committed,
        "tier_breaks": tiers,
        "quarter_start_dt": quarter_start,
        "status": "NEGOTIATION",
    })
    STORES["agreements"][rec["id"]] = rec
    return ok_object(serialize.agreement(rec), 201)


@bp.get("/mfg/agreements")
def list_agreements():
    uid, role = require_roles(*AGREEMENT_READ_ROLES)
    scoped_cid = rep_list_scope(uid, role)
    items = _sorted("agreements")
    if scoped_cid is not None:
        items = [a for a in items if a["customer_id"] == scoped_cid]
    cid = request.args.get("customer_id")
    if cid is not None:
        items = [a for a in items if a["customer_id"] == cid]
    st = request.args.get("status")
    if st is not None:
        check_enum(st, "status", AGREEMENT_STATUS)
        items = [a for a in items if a["status"] == st]
    return list_response([serialize.agreement(a) for a in items])


@bp.get("/mfg/agreements/<aid>")
def get_agreement(aid):
    uid, role = require_roles(*AGREEMENT_READ_ROLES)
    rec = _get_agreement(aid)
    rep_owns_customer(uid, role, rec["customer_id"])
    return ok_object(serialize.agreement(rec))


def _agreement_action(aid, allowed_from, target, require_customer_active=False):
    require_roles("PlantAdmin")
    rec = _get_agreement(aid)
    if rec["status"] == "TERMINATED":
        raise terminal_locked("Agreement is TERMINATED (terminal)")
    if rec["status"] not in allowed_from:
        raise invalid_state(
            f"Agreement in status {rec['status']} cannot transition to {target}")
    if require_customer_active:
        customer = _get_customer(rec["customer_id"])
        if customer["status"] != "ACTIVE":
            raise unprocessable(ERR_CUSTOMER_SUSPENDED,
                                "Agreement's customer is not ACTIVE")
    rec["status"] = target
    touch(rec)
    return ok_object(serialize.agreement(rec))


@bp.post("/mfg/agreements/<aid>/activate")
def activate_agreement(aid):
    return _agreement_action(aid, ("NEGOTIATION",), "ACTIVE", True)


@bp.post("/mfg/agreements/<aid>/suspend")
def suspend_agreement(aid):
    return _agreement_action(aid, ("ACTIVE",), "SUSPENDED")


@bp.post("/mfg/agreements/<aid>/resume")
def resume_agreement(aid):
    return _agreement_action(aid, ("SUSPENDED",), "ACTIVE", True)


@bp.post("/mfg/agreements/<aid>/terminate")
def terminate_agreement(aid):
    return _agreement_action(aid, ("ACTIVE", "SUSPENDED"), "TERMINATED")


@bp.get("/mfg/agreements/<aid>/quote")
def quote_agreement(aid):
    uid, role = require_roles("PlantAdmin", "ProductionPlanner", "BrandCustomerRep")
    rec = _get_agreement(aid)
    rep_owns_customer(uid, role, rec["customer_id"])
    raw = request.args.get("cases")
    if raw is None:
        raise invalid_request("Missing required query parameter 'cases'")
    try:
        cases = int(raw)
    except (TypeError, ValueError):
        raise invalid_request("Parameter 'cases' must be an integer")
    if cases <= 0:
        raise invalid_request("Parameter 'cases' must be > 0")
    total, per_case = calc.agreement_quote(rec, cases)
    return ok_object({"cases": cases, "total_cents": total,
                      "per_case_cents": per_case})
