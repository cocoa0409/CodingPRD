"""TraitAgreement endpoints with OCC on grower version and the hold cascade."""

import db
from errors import (
    ApiError,
    ERR_INVALID_STATE_TRANSITION,
    ERR_STALE_GROWER_VERSION,
    ERR_AGREEMENT_EXPIRED,
    ERR_GROWER_NOT_ACTIVE,
)
from middleware import authenticate, check_grower_ownership
from response import success_obj, success_list
from routes import make_blueprint
from services import hold_cascade
from util import body_json, check_shape, pagination_params, paginate, apply_filters, require_fk, exist_body_fks, dt_of

bp = make_blueprint("agreements")

ALL_ROLES = ["DealerAdmin", "SalesRep", "Agronomist", "Grower", "ClaimsAdjuster"]
SUSPENSION_REASONS = ["STEWARDSHIP_VIOLATION", "PAPERWORK"]


@bp.post("/trait-agreements")
def create_agreement():
    authenticate(["DealerAdmin", "SalesRep"])
    body = body_json()
    exist_body_fks(body, {
        "grower_id": ("growers", "grower"),
        "trait_package_id": ("trait_packages", "trait package"),
    })
    check_shape(body, {
        "grower_id": {"type": "string", "required": True},
        "trait_package_id": {"type": "string", "required": True},
        "effective_from": {"type": "datetime", "required": True},
        "effective_to": {"type": "datetime", "required": True},
        "expected_grower_version": {"type": "integer", "required": True},
    })
    grower = db.get("growers", body["grower_id"])
    if body["expected_grower_version"] != grower["version"]:
        raise ApiError(ERR_STALE_GROWER_VERSION, 412, "grower version has advanced")
    agreement = db.new_entity("trait_agreements", {
        "grower_id": body["grower_id"],
        "trait_package_id": body["trait_package_id"],
        "effective_from": body["effective_from"],
        "effective_to": body["effective_to"],
        "status": "PENDING_SIGNATURE",
        "supersedes_agreement_id": None,
        "suspension_reason": None,
        "signed_at": None,
    })
    db.touch(grower)  # successful create increments the grower's version
    return success_obj(db.public(agreement), 201)


@bp.get("/trait-agreements/<aid>")
def get_agreement(aid):
    uid, role = authenticate(ALL_ROLES)
    agreement = require_fk("trait_agreements", aid, "trait agreement")
    check_grower_ownership(uid, role, agreement["grower_id"])
    return success_obj(db.public(agreement), 200)


@bp.get("/trait-agreements")
def list_agreements():
    uid, role = authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    items = db.all_of("trait_agreements")
    if role == "Grower":
        items = [a for a in items if a["grower_id"] == uid]
    items = apply_filters(items, ["grower_id", "trait_package_id", "supersedes_agreement_id", "status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(a) for a in page], limit, offset, total, has_more)


@bp.post("/trait-agreements/<aid>/sign")
def sign_agreement(aid):
    uid, role = authenticate(["DealerAdmin", "Grower"])
    agreement = require_fk("trait_agreements", aid, "trait agreement")
    check_grower_ownership(uid, role, agreement["grower_id"])
    if agreement["status"] != "PENDING_SIGNATURE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only a PENDING_SIGNATURE agreement can be signed")
    pkg = db.get("trait_packages", agreement["trait_package_id"])
    if pkg is None or pkg["status"] != "LISTED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "trait package is not LISTED")
    clock = db.now()
    if not (dt_of(agreement, "effective_from") <= clock <= dt_of(agreement, "effective_to")):
        raise ApiError(ERR_AGREEMENT_EXPIRED, 409, "logical clock is outside the agreement window")
    grower = db.get("growers", agreement["grower_id"])
    if grower is None or grower["status"] != "ACTIVE":
        raise ApiError(ERR_GROWER_NOT_ACTIVE, 409, "grower account is not ACTIVE")
    # Supersede the prior ACTIVE agreement for the same (grower, package).
    prior = None
    for other in db.all_of("trait_agreements"):
        if (
            other["id"] != agreement["id"]
            and other["grower_id"] == agreement["grower_id"]
            and other["trait_package_id"] == agreement["trait_package_id"]
            and other["status"] == "ACTIVE"
        ):
            other["status"] = "SUPERSEDED"
            db.touch(other)
            prior = other
    agreement["supersedes_agreement_id"] = prior["id"] if prior else None
    agreement["status"] = "ACTIVE"
    agreement["signed_at"] = db.fmt_ts(clock)
    db.touch(agreement)
    return success_obj(db.public(agreement), 200)


@bp.post("/trait-agreements/<aid>/suspend")
def suspend_agreement(aid):
    authenticate(["DealerAdmin"])
    agreement = require_fk("trait_agreements", aid, "trait agreement")
    body = body_json()
    check_shape(body, {"reason": {"type": "enum", "required": True, "values": SUSPENSION_REASONS}})
    if agreement["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only an ACTIVE agreement can be suspended")
    agreement["status"] = "SUSPENDED"
    agreement["suspension_reason"] = body["reason"]
    db.touch(agreement)
    hold_cascade(agreement)
    return success_obj(db.public(agreement), 200)


@bp.post("/trait-agreements/<aid>/reinstate")
def reinstate_agreement(aid):
    authenticate(["DealerAdmin"])
    agreement = require_fk("trait_agreements", aid, "trait agreement")
    if agreement["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only a SUSPENDED agreement can be reinstated")
    if not (db.now() <= dt_of(agreement, "effective_to")):
        raise ApiError(ERR_AGREEMENT_EXPIRED, 409, "agreement window has passed")
    agreement["status"] = "ACTIVE"
    agreement["suspension_reason"] = None
    db.touch(agreement)
    return success_obj(db.public(agreement), 200)


@bp.post("/trait-agreements/<aid>/revoke")
def revoke_agreement(aid):
    authenticate(["DealerAdmin"])
    agreement = require_fk("trait_agreements", aid, "trait agreement")
    if agreement["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only an ACTIVE or SUSPENDED agreement can be revoked")
    was_active = agreement["status"] == "ACTIVE"
    agreement["status"] = "REVOKED"
    db.touch(agreement)
    if was_active:
        hold_cascade(agreement)
    return success_obj(db.public(agreement), 200)
