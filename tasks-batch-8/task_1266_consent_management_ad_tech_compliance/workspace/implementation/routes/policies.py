"""Jurisdiction policies: DRAFT -> ACTIVE -> RETIRED, retention amendment."""

from flask import Blueprint, request

from db import store, touch
from errors import (
    ApiError,
    ERR_POLICY_NOT_FOUND,
    ERR_PROPERTY_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_POLICY_INVALID_TRANSITION,
    ERR_POLICY_WINDOW_OVERLAP,
)
from middleware import require_role
from response import ok, ok_list, parse_pagination, paginate
from services.validation import (
    check_frozen,
    get_json_body,
    new_entity,
    not_found,
    opt_datetime,
    req_bool,
    req_datetime,
    req_enum,
    req_int,
    req_str,
    run_lazy_effects,
    windows_overlap,
)

bp = Blueprint("policies", __name__)

BANNER_REGIMES = ("OPT_IN_REQUIRED", "OPT_OUT_ALLOWED", "NOTICE_ONLY")
POLICY_STATUSES = ("DRAFT", "ACTIVE", "RETIRED")


@bp.post("/v1/jurisdiction-policies")
def create_policy():
    require_role("PrivacyAdmin")
    body = get_json_body()
    property_id = req_str(body, "property_id")
    jurisdiction_code = req_str(body, "jurisdiction_code")
    banner_regime = req_enum(body, "banner_regime", BANNER_REGIMES)
    min_consent_age = req_int(body, "min_consent_age", minimum=0)
    retention_days = req_int(body, "retention_days", minimum=1)
    gpc_honored = req_bool(body, "gpc_honored")
    effective_from = req_datetime(body, "effective_from")
    effective_to = opt_datetime(body, "effective_to")
    # Existence (rung 3). Policy creation is NOT frozen-gated (only
    # activation/retirement/amendment are, per PRD §2.6).
    if property_id not in store["properties"]:
        not_found("properties", ERR_PROPERTY_NOT_FOUND)
    policy = new_entity(
        {
            "property_id": property_id,
            "jurisdiction_code": jurisdiction_code,
            "banner_regime": banner_regime,
            "min_consent_age": min_consent_age,
            "retention_days": retention_days,
            "gpc_honored": gpc_honored,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "status": "DRAFT",
        }
    )
    store["jurisdiction_policies"][policy["id"]] = policy
    return ok(policy, 201)


@bp.get("/v1/jurisdiction-policies")
def list_policies():
    require_role("Any")
    limit, offset = parse_pagination(request.args)
    items = list(store["jurisdiction_policies"].values())
    property_id = request.args.get("property_id")
    status = request.args.get("status")
    if property_id is not None:
        items = [p for p in items if p.get("property_id") == property_id]
    if status is not None:
        items = [p for p in items if p.get("status") == status]
    page, total = paginate(items, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.get("/v1/jurisdiction-policies/<id>")
def get_policy(id):
    require_role("Any")
    policy = store["jurisdiction_policies"].get(id)
    if policy is None:
        not_found("jurisdiction_policies", ERR_POLICY_NOT_FOUND)
    return ok(policy)


@bp.put("/v1/jurisdiction-policies/<id>")
def update_policy(id):
    require_role("PrivacyAdmin")
    policy = store["jurisdiction_policies"].get(id)
    if policy is None:
        not_found("jurisdiction_policies", ERR_POLICY_NOT_FOUND)
    body = get_json_body()
    has_status = "status" in body
    has_retention = "retention_days" in body
    if not has_status and not has_retention:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "Provide status and/or retention_days",
            400,
        )
    new_status = None
    if has_status:
        new_status = req_enum(body, "status", POLICY_STATUSES)
    new_retention = None
    if has_retention:
        new_retention = req_int(body, "retention_days", minimum=1)

    # Rung 5: posture gate applies to every policy PUT (activation,
    # retirement, retention amendment).
    run_lazy_effects()
    check_frozen(policy["property_id"])

    # Rung 6: transition preconditions. RETIRED is terminal.
    if new_status is not None:
        current = policy["status"]
        allowed = (current == "DRAFT" and new_status == "ACTIVE") or (
            current == "ACTIVE" and new_status == "RETIRED"
        )
        if not allowed:
            raise ApiError(
                ERR_POLICY_INVALID_TRANSITION,
                f"Policy status transition {current} -> {new_status} is not allowed",
                409,
            )
    elif policy["status"] == "RETIRED":
        # Retention-only amendment on a terminal policy.
        raise ApiError(
            ERR_POLICY_INVALID_TRANSITION,
            "RETIRED policies can no longer be amended",
            409,
        )

    # Rung 13: half-open window overlap against other ACTIVE policies of the
    # same (property, jurisdiction). Adjacency is explicitly permitted.
    if new_status == "ACTIVE":
        for other in store["jurisdiction_policies"].values():
            if (
                other["id"] != policy["id"]
                and other.get("property_id") == policy["property_id"]
                and other.get("jurisdiction_code") == policy["jurisdiction_code"]
                and other.get("status") == "ACTIVE"
                and windows_overlap(
                    policy["effective_from"],
                    policy.get("effective_to"),
                    other["effective_from"],
                    other.get("effective_to"),
                )
            ):
                raise ApiError(
                    ERR_POLICY_WINDOW_OVERLAP,
                    "ACTIVE policy window overlaps another ACTIVE policy of the same property and jurisdiction",
                    409,
                )

    if new_status is not None:
        policy["status"] = new_status
    if new_retention is not None:
        policy["retention_days"] = new_retention
    touch(policy)
    return ok(policy)
