"""Registry entities: brokers, investors, insureds, policies, state licenses."""

from flask import Blueprint

import cascade
from db import stamp, store, touch
from errors import (
    ApiError,
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_STATE_TRANSITION,
    ERR_LICENSE_WINDOW_OVERLAP,
    ERR_NOT_CASE_OWNER,
    ERR_POLICY_LOCKED_BY_ACTIVE_CASE,
)
from middleware import (
    READ_ALL,
    auth,
    get_body,
    lookup,
    opt,
    page_args,
    req,
    require_role,
    v_date,
    v_enum,
    v_int,
    v_str,
)
from response import ok, ok_list
from serialize import (
    ser_broker,
    ser_case,
    ser_disbursement,
    ser_insured,
    ser_investor,
    ser_license,
    ser_policy,
)

bp = Blueprint("registry", __name__)

POLICY_LOCK_STATES = {"UNDERWRITING", "MARKETED", "IN_CLOSING", "ACQUIRED"}
CASE_TERMINAL = cascade.CASE_TERMINAL


def _sorted(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def _list(items, serializer):
    limit, offset = page_args()
    items = _sorted(items)
    page = items[offset : offset + limit]
    return ok_list([serializer(e) for e in page], len(items), limit, offset)


# ---------------------------------------------------------------------------
# Brokers
# ---------------------------------------------------------------------------


@bp.post("/api/brokers")
def create_broker():
    uid, role = auth()
    require_role(role, ["PlatformAdmin"])
    body = get_body()
    broker = {
        "name": v_str(req(body, "name"), "name"),
        "license_number": v_str(req(body, "license_number"), "license_number"),
        "state_code": v_str(req(body, "state_code"), "state_code"),
        "status": "ACTIVE",
    }
    stamp(broker)
    store.brokers[broker["id"]] = broker
    return ok(ser_broker(broker), 201)


@bp.get("/api/brokers/<bid>")
def get_broker(bid):
    uid, role = auth()
    require_role(role, READ_ALL)
    return ok(ser_broker(lookup(store.brokers, bid, "Broker")))


@bp.get("/api/brokers/<bid>/cases")
def broker_cases(bid):
    uid, role = auth()
    require_role(role, READ_ALL)
    lookup(store.brokers, bid, "Broker")
    return _list([c for c in store.cases.values() if c["broker_id"] == bid], ser_case)


@bp.get("/api/brokers/<bid>/insureds")
def broker_insureds(bid):
    uid, role = auth()
    require_role(role, READ_ALL)
    lookup(store.brokers, bid, "Broker")
    return _list(
        [i for i in store.insureds.values() if i["created_by_broker_id"] == bid],
        ser_insured,
    )


@bp.get("/api/brokers/<bid>/disbursements")
def broker_disbursements(bid):
    uid, role = auth()
    require_role(role, READ_ALL)
    lookup(store.brokers, bid, "Broker")
    return _list(
        [d for d in store.disbursements.values() if d["payee_broker_id"] == bid],
        ser_disbursement,
    )


# ---------------------------------------------------------------------------
# Investors
# ---------------------------------------------------------------------------


@bp.post("/api/investors")
def create_investor():
    uid, role = auth()
    require_role(role, ["PlatformAdmin"])
    body = get_body()
    investor = {
        "name": v_str(req(body, "name"), "name"),
        "investor_type": v_enum(req(body, "investor_type"), "investor_type", ["INDIVIDUAL", "FUND"]),
        "status": "ACTIVE",
    }
    stamp(investor)
    store.investors[investor["id"]] = investor
    return ok(ser_investor(investor), 201)


@bp.get("/api/investors/<iid>")
def get_investor(iid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "PortfolioManager", "ComplianceOfficer", "FinanceOfficer", "Investor"])
    return ok(ser_investor(lookup(store.investors, iid, "Investor")))


# ---------------------------------------------------------------------------
# Insureds
# ---------------------------------------------------------------------------


@bp.post("/api/insureds")
def create_insured():
    uid, role = auth()
    require_role(role, ["Broker", "CaseManager"])
    body = get_body()
    insured = {
        "full_name": v_str(req(body, "full_name"), "full_name"),
        "date_of_birth": v_date(req(body, "date_of_birth"), "date_of_birth"),
        "state_code": v_str(req(body, "state_code"), "state_code"),
        "gender": v_enum(req(body, "gender"), "gender", ["M", "F"]),
        "smoker_status": v_enum(
            req(body, "smoker_status"), "smoker_status", ["TOBACCO", "NON_TOBACCO", "UNKNOWN"]
        ),
        "ssn_last4": v_str(req(body, "ssn_last4"), "ssn_last4"),
        "created_by_broker_id": uid if role == "Broker" else None,
        "status": "LIVING",
    }
    stamp(insured)
    store.insureds[insured["id"]] = insured
    return ok(ser_insured(insured), 201)


@bp.get("/api/insureds/<iid>")
def get_insured(iid):
    uid, role = auth()
    require_role(role, READ_ALL)
    return ok(ser_insured(lookup(store.insureds, iid, "Insured")))


@bp.get("/api/insureds/<iid>/policies")
def insured_policies(iid):
    uid, role = auth()
    require_role(role, READ_ALL)
    lookup(store.insureds, iid, "Insured")
    return _list([p for p in store.policies.values() if p["insured_id"] == iid], ser_policy)


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------

POLICY_TYPES = ["WHOLE_LIFE", "UNIVERSAL_LIFE", "VARIABLE", "TERM_CONVERTIBLE", "TERM_NONCONVERTIBLE"]


def _check_broker_owns_insured(uid, role, insured):
    if role == "Broker" and insured["created_by_broker_id"] != uid:
        raise ApiError(ERR_NOT_CASE_OWNER, 403, "Insured was not created by the calling broker")


@bp.post("/api/policies")
def create_policy():
    uid, role = auth()
    require_role(role, ["Broker", "CaseManager"])
    body = get_body()
    insured_id = v_str(req(body, "insured_id"), "insured_id")
    carrier_name = v_str(req(body, "carrier_name"), "carrier_name")
    policy_number = v_str(req(body, "policy_number"), "policy_number")
    face = v_int(req(body, "face_amount_cents"), "face_amount_cents", min_v=1)
    policy_type = v_enum(req(body, "policy_type"), "policy_type", POLICY_TYPES)
    issue_date = v_date(req(body, "issue_date"), "issue_date")
    annual_premium = v_int(req(body, "annual_premium_cents"), "annual_premium_cents", min_v=0)
    cash_value = v_int(opt(body, "cash_value_cents", 0), "cash_value_cents", min_v=0)
    policy_loan = v_int(opt(body, "policy_loan_cents", 0), "policy_loan_cents", min_v=0)
    insured = lookup(store.insureds, insured_id, "Insured")
    _check_broker_owns_insured(uid, role, insured)
    policy = {
        "insured_id": insured_id,
        "carrier_name": carrier_name,
        "policy_number": policy_number,
        "face_amount_cents": face,
        "policy_type": policy_type,
        "issue_date": issue_date,
        "annual_premium_cents": annual_premium,
        "cash_value_cents": cash_value,
        "policy_loan_cents": policy_loan,
        "status": "IN_FORCE",
    }
    stamp(policy)
    store.policies[policy["id"]] = policy
    return ok(ser_policy(policy), 201)


@bp.get("/api/policies/<pid>")
def get_policy(pid):
    uid, role = auth()
    require_role(role, READ_ALL)
    return ok(ser_policy(lookup(store.policies, pid, "Policy")))


@bp.patch("/api/policies/<pid>")
def patch_policy(pid):
    uid, role = auth()
    require_role(role, ["Broker", "CaseManager"])
    body = get_body()
    updates = {}
    for field in ("face_amount_cents", "annual_premium_cents", "cash_value_cents", "policy_loan_cents"):
        if field in body and body[field] is not None:
            updates[field] = v_int(body[field], field, min_v=0)
    policy = lookup(store.policies, pid, "Policy")
    insured = store.insureds.get(policy["insured_id"])
    if role == "Broker" and (insured is None or insured["created_by_broker_id"] != uid):
        raise ApiError(ERR_NOT_CASE_OWNER, 403, "Caller does not own the insured chain")
    for case in store.cases.values():
        if case["policy_id"] == pid and case["status"] in POLICY_LOCK_STATES:
            raise ApiError(
                ERR_POLICY_LOCKED_BY_ACTIVE_CASE,
                409,
                "Policy is locked by an active case",
            )
    policy.update(updates)
    touch(policy)
    return ok(ser_policy(policy))


@bp.get("/api/policies/<pid>/cases")
def policy_cases(pid):
    uid, role = auth()
    require_role(role, READ_ALL)
    lookup(store.policies, pid, "Policy")
    return _list([c for c in store.cases.values() if c["policy_id"] == pid], ser_case)


# ---------------------------------------------------------------------------
# State licenses
# ---------------------------------------------------------------------------


@bp.post("/api/licenses")
def create_license():
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "ComplianceOfficer"])
    body = get_body()
    state_code = v_str(req(body, "state_code"), "state_code")
    license_number = v_str(req(body, "license_number"), "license_number")
    effective = v_date(req(body, "effective_date"), "effective_date")
    expiry = v_date(req(body, "expiry_date"), "expiry_date")
    # Closed-interval windows for the same state must not touch or overlap.
    for lic in store.licenses.values():
        if lic["state_code"] != state_code:
            continue
        if effective <= lic["expiry_date"] and expiry >= lic["effective_date"]:
            raise ApiError(
                ERR_LICENSE_WINDOW_OVERLAP,
                409,
                "License window touches or overlaps an existing window for the state",
            )
    lic = {
        "state_code": state_code,
        "license_number": license_number,
        "effective_date": effective,
        "expiry_date": expiry,
        "status": "ACTIVE",
    }
    stamp(lic)
    store.licenses[lic["id"]] = lic
    return ok(ser_license(lic), 201)


@bp.get("/api/licenses")
def list_licenses():
    uid, role = auth()
    require_role(role, READ_ALL)
    state = __import__("flask").request.args.get("state_code")
    items = list(store.licenses.values())
    if state is not None:
        items = [l for l in items if l["state_code"] == state]
    return _list(items, ser_license)


@bp.get("/api/licenses/<lid>")
def get_license(lid):
    uid, role = auth()
    require_role(role, READ_ALL)
    return ok(ser_license(lookup(store.licenses, lid, "StateLicense")))


@bp.post("/api/licenses/<lid>/suspend")
def suspend_license(lid):
    uid, role = auth()
    require_role(role, ["ComplianceOfficer"])
    lic = lookup(store.licenses, lid, "StateLicense")
    if lic["status"] == "EXPIRED":
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "License is EXPIRED")
    if lic["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Only an ACTIVE license can be suspended")
    lic["status"] = "SUSPENDED"
    touch(lic)
    cascade.suspension_cascade(lic)
    return ok(ser_license(lic))


@bp.post("/api/licenses/<lid>/reinstate")
def reinstate_license(lid):
    uid, role = auth()
    require_role(role, ["ComplianceOfficer"])
    lic = lookup(store.licenses, lid, "StateLicense")
    if lic["status"] == "EXPIRED":
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "License is EXPIRED")
    if lic["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Only a SUSPENDED license can be reinstated")
    lic["status"] = "ACTIVE"
    touch(lic)
    cascade.reinstate_cascade(lic)
    return ok(ser_license(lic))
