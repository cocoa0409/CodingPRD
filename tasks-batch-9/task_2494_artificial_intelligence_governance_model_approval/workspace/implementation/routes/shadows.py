"""Shadow deployments: discovery, linking, grace and retirement."""
from flask import Blueprint

import clock
import constants
import db
import errors
import response
import validators as v
from errors import ApiError
from middleware import authorize
from services import calc, guards, queries

bp = Blueprint("shadows", __name__)


def _check_actionable(shadow):
    if shadow["status"] in ("RETIRED", "ENFORCED_BLOCK"):
        raise ApiError(
            errors.ERR_SHADOW_NOT_ACTIONABLE,
            "shadow deployment %s is %s" % (shadow["id"], shadow["status"]),
        )


def _recompute_grace_deadline(shadow):
    days = calc.grace_days_total(shadow["environment"], shadow["grace_days_granted"])
    shadow["grace_deadline_at"] = clock.plus_days(shadow["discovered_at"], days)


# --- 42. POST /shadow-deployments --------------------------------------
@bp.post("/shadow-deployments")
@authorize(constants.GOVERNANCE_OFFICER, constants.SECURITY_REVIEWER)
def record_shadow():
    body = v.get_body()
    guards.resolve_model_asset_fk(body)                              # step 7
    guards.resolve_use_case_fk(body, "claimed_use_case_id")
    model_asset_id = v.as_str(body, "model_asset_id", required=True)  # step 8
    claimed_use_case_id = v.as_str(body, "claimed_use_case_id")
    environment = v.as_enum(body, "environment", constants.ENVIRONMENTS, required=True)
    discovered_source = v.as_enum(
        body, "discovered_source", constants.DISCOVERED_SOURCES, required=True
    )
    discovered_at = v.as_datetime(body, "discovered_at", required=True)

    record = {
        "model_asset_id": model_asset_id,
        "claimed_use_case_id": claimed_use_case_id,
        "environment": environment,
        "discovered_source": discovered_source,
        "discovered_at": discovered_at,
        "status": "DISCOVERED",
        "grace_days_granted": 0,
        "grace_deadline_at": None,
        "retired_at": None,
        "updated_at": clock.now(),
        "version": 1,
    }
    _recompute_grace_deadline(record)
    db.insert(db.shadow_deployments, record)
    return response.object_response(record, 201)


# --- 43. GET /shadow-deployments --------------------------------------
@bp.get("/shadow-deployments")
@authorize(*constants.ALL_ROLES)
def list_shadows():
    model_asset_id = v.query_str("model_asset_id")
    claimed_use_case_id = v.query_str("claimed_use_case_id")
    status = v.query_str("status")
    environment = v.query_str("environment")
    limit, offset = v.pagination_params()
    records = db.all_of(db.shadow_deployments)
    if model_asset_id is not None:
        records = [r for r in records if r["model_asset_id"] == model_asset_id]
    if claimed_use_case_id is not None:
        records = [r for r in records if r["claimed_use_case_id"] == claimed_use_case_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if environment is not None:
        records = [r for r in records if r["environment"] == environment]
    page, pagination = response.paginate(records, limit, offset)
    return response.list_response(page, pagination)


# --- 44. GET /shadow-deployments/{id} ---------------------------------
@bp.get("/shadow-deployments/<shadow_id>")
@authorize(*constants.ALL_ROLES)
def read_shadow(shadow_id):
    return response.object_response(
        guards.get_record(db.shadow_deployments, shadow_id, "shadow deployment")
    )


# --- 45. POST /shadow-deployments/{id}/link --------------------------
@bp.post("/shadow-deployments/<shadow_id>/link")
@authorize(constants.GOVERNANCE_OFFICER)
def link_shadow(shadow_id):
    shadow = guards.get_record(                                      # step 6
        db.shadow_deployments, shadow_id, "shadow deployment"
    )
    body = v.get_body()
    use_case = guards.resolve_use_case_fk(body)                       # step 7
    use_case_id = v.as_str(body, "use_case_id", required=True)         # step 8
    _check_actionable(shadow)                                        # step 18

    pinned = [                                                       # step 33
        b
        for b in queries.bindings_of(use_case_id)
        if b["status"] == "PINNED" and b["model_asset_id"] == shadow["model_asset_id"]
    ]
    if use_case["status"] != "APPROVED" or not pinned:
        raise ApiError(
            errors.ERR_SHADOW_LINK_MISMATCH,
            "the link target must be an APPROVED use case holding a PINNED binding on "
            "the same model asset",
        )

    shadow["status"] = "LINKED"
    shadow["claimed_use_case_id"] = use_case_id
    db.touch(shadow)
    return response.object_response(shadow)


# --- 46. POST /shadow-deployments/{id}/grant-grace ------------------
@bp.post("/shadow-deployments/<shadow_id>/grant-grace")
@authorize(constants.GOVERNANCE_OFFICER)
def grant_grace(shadow_id):
    shadow = guards.get_record(                                      # step 6
        db.shadow_deployments, shadow_id, "shadow deployment"
    )
    body = v.get_body()                                              # step 8
    grace_days = v.as_int(body, "grace_days", required=True)
    _check_actionable(shadow)                                        # step 18
    if shadow["status"] != "DISCOVERED":
        raise ApiError(
            errors.ERR_SHADOW_NOT_ACTIONABLE,
            "granting grace is available only from DISCOVERED",
        )
    if clock.now() > shadow["grace_deadline_at"]:                     # step 38
        raise ApiError(
            errors.ERR_GRACE_PERIOD_ELAPSED,
            "the grace deadline %s has already elapsed"
            % clock.iso(shadow["grace_deadline_at"]),
        )
    if grace_days < 1 or grace_days > constants.MAX_GRACE_EXTENSION_DAYS:
        raise ApiError(                                              # step 39
            errors.ERR_GRACE_EXTENSION_EXCEEDED,
            "grace_days must be between 1 and %d" % constants.MAX_GRACE_EXTENSION_DAYS,
        )

    shadow["status"] = "GRACE_GRANTED"
    shadow["grace_days_granted"] = grace_days
    _recompute_grace_deadline(shadow)
    db.touch(shadow)
    return response.object_response(shadow)


# --- 47. POST /shadow-deployments/{id}/retire ----------------------
@bp.post("/shadow-deployments/<shadow_id>/retire")
@authorize(constants.GOVERNANCE_OFFICER)
def retire_shadow(shadow_id):
    shadow = guards.get_record(                                      # step 6
        db.shadow_deployments, shadow_id, "shadow deployment"
    )
    _check_actionable(shadow)                                        # step 18
    shadow["status"] = "RETIRED"
    shadow["retired_at"] = clock.now()
    db.touch(shadow)
    return response.object_response(shadow)
