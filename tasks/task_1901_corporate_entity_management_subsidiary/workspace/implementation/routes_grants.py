"""Routes: SignatureAuthorityGrant create/verify/suspend/reinstate/revoke."""
from flask import Blueprint, request

import store
import services as svc
from errors import (
    ERR_INVALID_REQUEST, ERR_OFFICER_NOT_FOUND, ERR_GRANT_NOT_FOUND,
    ERR_ENTITY_NOT_FOUND, ERR_ENTITY_ALREADY_DISSOLVED, ERR_OFFICER_NOT_APPOINTED,
    ERR_REQUIRED_RESOLUTION_MISSING, ERR_DELEGATOR_GRANT_INVALID,
    ERR_GRANT_WINDOW_OVERLAP, ERR_DELEGATION_DEPTH_EXCEEDED,
    ERR_DELEGATOR_WINDOW_INSUFFICIENT, ERR_DELEGATION_LIMIT_EXCEEDED,
    ERR_GRANT_NOT_ACTIVE, ERR_GRANT_NOT_SUSPENDED, ERR_GRANT_ALREADY_TERMINAL,
    ERR_SEGREGATION_OF_DUTIES,
    raise_err,
)
from middleware import require_roles, get_body, ALL_ROLES
from response import ok_object, paginate, sort_records
from routes_entities import get_entity_or_404

bp = Blueprint("grants", __name__)

CS = ["CorporateSecretary"]
VERIFY_ROLES = ["CorporateSecretary", "FilingCoordinator", "AuthorizedOfficer",
                "ComplianceAuditor"]


@bp.route("/api/entities/<entityId>/signature-grants", methods=["POST"])
def create_grant(entityId):
    require_roles(CS)
    entity = get_entity_or_404(entityId)
    body = get_body()
    # Priority 3: body FK existence
    officer_id = body.get("officer_id")
    if officer_id is not None and officer_id not in store.officers:
        raise_err(ERR_OFFICER_NOT_FOUND)
    delegator_id = body.get("delegated_from_grant_id")
    if delegator_id is not None and delegator_id not in store.grants:
        raise_err(ERR_GRANT_NOT_FOUND)
    # Priority 4: schema
    if officer_id is None:
        raise_err(ERR_INVALID_REQUEST, "officer_id is required")
    scope = body.get("scope")
    if scope not in svc.GRANT_SCOPES:
        raise_err(ERR_INVALID_REQUEST, "scope is invalid")
    max_amount = body.get("max_amount_cents")
    if isinstance(max_amount, bool) or not isinstance(max_amount, int) or max_amount <= 0:
        raise_err(ERR_INVALID_REQUEST, "max_amount_cents must be an integer > 0")
    effective_date = body.get("effective_date")
    expiry_date = body.get("expiry_date")
    if not svc.is_valid_date(effective_date):
        raise_err(ERR_INVALID_REQUEST, "effective_date must be an ISO date")
    if not svc.is_valid_date(expiry_date):
        raise_err(ERR_INVALID_REQUEST, "expiry_date must be an ISO date")
    if svc.parse_date(expiry_date) <= svc.parse_date(effective_date):
        raise_err(ERR_INVALID_REQUEST, "expiry_date must be later than effective_date")
    # Priority 5: parent not DISSOLVED
    if entity["status"] == "DISSOLVED":
        raise_err(ERR_ENTITY_ALREADY_DISSOLVED)
    svc.lazy_eval_entity(entity, auto_deny=False)
    # Priority 7: referential checks
    appointed = any(a for a in svc.officer_appts_of(entity["id"])
                    if a["officer_id"] == officer_id and a["status"] == "APPOINTED")
    if not appointed:
        raise_err(ERR_OFFICER_NOT_APPOINTED,
                  "Officer does not hold an APPOINTED appointment at this entity")
    resolution = svc.find_authorizing_resolution(
        entity["id"], "GRANT_SIGNATURE_AUTHORITY",
        {"officer_id": officer_id, "scope": scope})
    if resolution is None:
        raise_err(ERR_REQUIRED_RESOLUTION_MISSING,
                  "No ADOPTED/EFFECTIVE GRANT_SIGNATURE_AUTHORITY resolution matches")
    delegator = None
    if delegator_id is not None:
        delegator = store.grants[delegator_id]
        if delegator["status"] != "ACTIVE" or delegator["entity_id"] != entity["id"]:
            raise_err(ERR_DELEGATOR_GRANT_INVALID,
                      "Delegator grant is not ACTIVE or does not match entity")
    # Priority 8: window overlap, delegation depth
    new_eff = svc.parse_date(effective_date)
    new_exp = svc.parse_date(expiry_date)
    for g in svc.grants_of(entity["id"]):
        if (g["officer_id"] == officer_id and g["scope"] == scope
                and g["status"] in ("ACTIVE", "SUSPENDED")):
            if new_eff < svc.parse_date(g["expiry_date"]) and svc.parse_date(g["effective_date"]) < new_exp:
                raise_err(ERR_GRANT_WINDOW_OVERLAP,
                          "Grant window overlaps an existing grant for this officer/scope")
    if delegator is not None and delegator.get("delegated_from_grant_id") is not None:
        raise_err(ERR_DELEGATION_DEPTH_EXCEEDED,
                  "Delegator must itself be a direct grant (depth <= 2)")
    # Priority 9: delegator window containment
    if delegator is not None:
        if (new_eff < svc.parse_date(delegator["effective_date"])
                or new_exp > svc.parse_date(delegator["expiry_date"])):
            raise_err(ERR_DELEGATOR_WINDOW_INSUFFICIENT,
                      "Delegated grant window is not contained in the delegator window")
    # Priority 10: delegation limit
    if delegator is not None and max_amount > delegator["max_amount_cents"]:
        raise_err(ERR_DELEGATION_LIMIT_EXCEEDED,
                  "Delegated max_amount_cents exceeds the delegator's limit")
    rec = store.new_record()
    rec.update({
        "entity_id": entity["id"],
        "officer_id": officer_id,
        "scope": scope,
        "max_amount_cents": max_amount,
        "effective_date": effective_date,
        "expiry_date": expiry_date,
        "delegated_from_grant_id": delegator_id,
        "source_resolution_id": resolution["id"],
        "suspended_by_user_id": None,
        "status": "ACTIVE",
    })
    store.grants[rec["id"]] = rec
    return ok_object(svc.serialize(rec), 201)


@bp.route("/api/signature-grants", methods=["GET"])
def list_grants():
    require_roles(ALL_ROLES)
    for g in list(store.grants.values()):
        svc.apply_grant_expiry(g)
    records = sort_records(list(store.grants.values()))
    for param, field in (("entity_id", "entity_id"), ("officer_id", "officer_id"),
                         ("scope", "scope"), ("status", "status"),
                         ("delegated_from_grant_id", "delegated_from_grant_id"),
                         ("source_resolution_id", "source_resolution_id")):
        v = request.args.get(param)
        if v is not None:
            records = [r for r in records if r[field] == v]
    return paginate([svc.serialize(r) for r in records], request.args)


def get_grant_or_404(grantId):
    rec = store.grants.get(grantId)
    if rec is None:
        raise_err(ERR_GRANT_NOT_FOUND)
    return rec


@bp.route("/api/signature-grants/verify", methods=["POST"])
def verify_grant():
    require_roles(VERIFY_ROLES)
    body = get_body()
    # Priority 3: body FK existence
    entity_id = body.get("entity_id")
    if entity_id is not None and entity_id not in store.entities:
        raise_err(ERR_ENTITY_NOT_FOUND)
    officer_id = body.get("officer_id")
    if officer_id is not None and officer_id not in store.officers:
        raise_err(ERR_OFFICER_NOT_FOUND)
    # Priority 4: schema
    if entity_id is None:
        raise_err(ERR_INVALID_REQUEST, "entity_id is required")
    if officer_id is None:
        raise_err(ERR_INVALID_REQUEST, "officer_id is required")
    scope = body.get("scope")
    if scope not in svc.GRANT_SCOPES:
        raise_err(ERR_INVALID_REQUEST, "scope is invalid")
    amount = body.get("amount_cents")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
        raise_err(ERR_INVALID_REQUEST, "amount_cents must be a non-negative integer")
    as_of = body.get("as_of_date")
    if not svc.is_valid_date(as_of):
        raise_err(ERR_INVALID_REQUEST, "as_of_date must be an ISO date")
    as_of_date = svc.parse_date(as_of)
    # Lazy EXPIRED evaluation against the logical clock
    for g in svc.grants_of(entity_id):
        svc.apply_grant_expiry(g)
    candidates = [g for g in svc.grants_of(entity_id)
                  if g["officer_id"] == officer_id and g["scope"] == scope
                  and g["status"] == "ACTIVE"
                  and svc.parse_date(g["effective_date"]) <= as_of_date
                  and as_of_date < svc.parse_date(g["expiry_date"])]
    if not candidates:
        return ok_object({"authorized": False, "effective_limit_cents": 0,
                          "matching_grant_id": None})
    candidates.sort(key=lambda g: g.get("_seq", 0))
    grant = candidates[0]
    delegator_id = grant.get("delegated_from_grant_id")
    if delegator_id is None:
        effective_limit = grant["max_amount_cents"]
    else:
        delegator = store.grants.get(delegator_id)
        if (delegator is None or delegator["status"] != "ACTIVE"
                or not (svc.parse_date(delegator["effective_date"]) <= as_of_date
                        < svc.parse_date(delegator["expiry_date"]))):
            return ok_object({"authorized": False, "effective_limit_cents": 0,
                              "matching_grant_id": grant["id"]})
        effective_limit = min(grant["max_amount_cents"], delegator["max_amount_cents"])
    authorized = effective_limit > 0 and amount <= effective_limit
    return ok_object({"authorized": authorized,
                      "effective_limit_cents": effective_limit,
                      "matching_grant_id": grant["id"]})


@bp.route("/api/signature-grants/<grantId>", methods=["GET"])
def get_grant(grantId):
    require_roles(ALL_ROLES)
    rec = get_grant_or_404(grantId)
    svc.apply_grant_expiry(rec)
    return ok_object(svc.serialize(rec))


@bp.route("/api/signature-grants/<grantId>/suspend", methods=["POST"])
def suspend_grant(grantId):
    user_id, _ = require_roles(["ComplianceAuditor", "CorporateSecretary"])
    rec = get_grant_or_404(grantId)
    get_body()
    svc.apply_grant_expiry(rec)
    if rec["status"] != "ACTIVE":
        raise_err(ERR_GRANT_NOT_ACTIVE, "suspend requires status == ACTIVE")
    rec["status"] = "SUSPENDED"
    rec["suspended_by_user_id"] = user_id
    store.touch(rec)
    return ok_object(svc.serialize(rec))


@bp.route("/api/signature-grants/<grantId>/reinstate", methods=["POST"])
def reinstate_grant(grantId):
    user_id, _ = require_roles(CS)
    rec = get_grant_or_404(grantId)
    get_body()
    svc.apply_grant_expiry(rec)
    if rec["status"] != "SUSPENDED":
        raise_err(ERR_GRANT_NOT_SUSPENDED, "reinstate requires status == SUSPENDED")
    if user_id == rec.get("suspended_by_user_id"):
        raise_err(ERR_SEGREGATION_OF_DUTIES, "Reinstater must differ from suspender")
    rec["status"] = "ACTIVE"
    rec["suspended_by_user_id"] = None
    store.touch(rec)
    return ok_object(svc.serialize(rec))


@bp.route("/api/signature-grants/<grantId>/revoke", methods=["POST"])
def revoke_grant_endpoint(grantId):
    require_roles(CS)
    rec = get_grant_or_404(grantId)
    body = get_body()
    svc.apply_grant_expiry(rec)
    if rec["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_err(ERR_GRANT_ALREADY_TERMINAL,
                  "revoke requires status IN {ACTIVE, SUSPENDED}")
    reason = body.get("reason") if isinstance(body.get("reason"), str) else None
    svc.revoke_grant(rec, reason=reason)
    return ok_object(svc.serialize(rec))
