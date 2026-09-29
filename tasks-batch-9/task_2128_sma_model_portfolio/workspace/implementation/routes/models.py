"""ModelVersion + SponsorDistribution routes, including CASCADE-A (PRD 3.2-3.3)."""

from datetime import timedelta

from flask import Blueprint, g

from core import (
    ApiError, READ_ROLES, ROLE_COMPLIANCE_OFFICER, ROLE_PORTFOLIO_MANAGER,
    ROLE_SPONSOR_OPERATOR, arg, body_json, clock, db, lookup, new_row, ok,
    paged, qfilter, require_roles, serialize, sponsor_scope, touch, v_dt,
    v_int, v_str,
)
from calc import half_open_collides, dispersion_report
from entities import (
    DISPERSION_BASES, DISTRIBUTION_STATUSES, MODEL_VERSION_STATUSES,
    recompute_block_membership,
)

bp = Blueprint("models", __name__)

TOTAL_BPS = 10000


# ------------------------------------------------------------ ModelVersion --
@bp.post("/sma/model-versions")
@require_roles(ROLE_PORTFOLIO_MANAGER)
def create_model_version():
    body = body_json()
    model_id = body.get("model_id")
    if isinstance(model_id, str):
        model = lookup(db.models, model_id, "ERR_MODEL_NOT_FOUND")
    else:
        v_str(body, "model_id")
        model = None

    row = new_row(
        model_id=model["id"],
        version_number=model["version_count"] + 1,
        status="DRAFT",
        sleeves=[],
        sleeve_count=0,
        total_target_weight_bps=0,
        submitted_by_user_id=None,
        approved_by_user_id=None,
        rejection_note=None,
        published_at=None,
        superseded_at=None,
        distribution_count=0,
    )
    db.model_versions[row["id"]] = row
    model["version_count"] += 1
    touch(model)
    return ok(serialize(row), 201)


@bp.get("/sma/model-versions/<model_version_id>")
@require_roles(*READ_ROLES)
def get_model_version(model_version_id):
    row = lookup(db.model_versions, model_version_id, "ERR_MODEL_VERSION_NOT_FOUND")
    return ok(serialize(row))


@bp.get("/sma/model-versions")
@require_roles(*READ_ROLES)
def list_model_versions():
    rows = qfilter(db.model_versions.values(),
                   model_id=arg("model_id"), status=arg("status"))
    return paged(rows)


@bp.post("/sma/model-versions/<model_version_id>/sleeves")
@require_roles(ROLE_PORTFOLIO_MANAGER)
def replace_sleeves(model_version_id):
    version = lookup(db.model_versions, model_version_id, "ERR_MODEL_VERSION_NOT_FOUND")
    body = body_json()
    raw = body.get("sleeves")

    # Rung 6: body reference existence, walked in array order.
    if isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict) and isinstance(entry.get("security_id"), str):
                lookup(db.securities, entry["security_id"], "ERR_SECURITY_NOT_FOUND")

    # Rung 7: request shape.
    if raw is None or not isinstance(raw, list):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'sleeves' must be an array.")
    seen = set()
    sleeves = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST", "Each sleeve must be an object.")
        security_id = entry.get("security_id")
        if not isinstance(security_id, str) or not security_id:
            raise ApiError("ERR_INVALID_REQUEST", "Each sleeve requires a 'security_id'.")
        target = entry.get("target_weight_bps")
        if isinstance(target, bool) or not isinstance(target, int):
            raise ApiError("ERR_INVALID_REQUEST", "'target_weight_bps' must be an integer.")
        if target < 1 or target > TOTAL_BPS:
            raise ApiError("ERR_INVALID_REQUEST", "'target_weight_bps' must be between 1 and 10000.")
        max_position = entry.get("max_position_bps")
        if max_position is None:
            max_position = TOTAL_BPS
        else:
            if isinstance(max_position, bool) or not isinstance(max_position, int):
                raise ApiError("ERR_INVALID_REQUEST", "'max_position_bps' must be an integer.")
            if max_position < 1 or max_position > TOTAL_BPS:
                raise ApiError("ERR_INVALID_REQUEST",
                               "'max_position_bps' must be between 1 and 10000.")
        if security_id in seen:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Duplicate sleeve for security '%s'." % security_id)
        seen.add(security_id)
        sleeves.append({"security_id": security_id,
                        "target_weight_bps": target,
                        "max_position_bps": max_position})

    # Rung 11: from-state.
    if version["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Sleeves may only be edited while DRAFT.")

    version["sleeves"] = sleeves
    version["sleeve_count"] = len(sleeves)
    version["total_target_weight_bps"] = sum(s["target_weight_bps"] for s in sleeves)
    touch(version)
    return ok(serialize(version))


@bp.post("/sma/model-versions/<model_version_id>/submit")
@require_roles(ROLE_PORTFOLIO_MANAGER)
def submit_model_version(model_version_id):
    version = lookup(db.model_versions, model_version_id, "ERR_MODEL_VERSION_NOT_FOUND")
    if version["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT version may be submitted.")
    if version["sleeve_count"] < 1 or version["total_target_weight_bps"] != TOTAL_BPS:
        raise ApiError("ERR_WEIGHTS_NOT_BALANCED",
                       "Sleeve weights must sum to exactly 10000 basis points.")
    version["status"] = "PENDING_APPROVAL"
    version["submitted_by_user_id"] = g.user_id
    version["rejection_note"] = None
    touch(version)
    return ok(serialize(version))


def _segregation_of_duties(version):
    submitted_by = version.get("submitted_by_user_id")
    if submitted_by is not None and submitted_by == g.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The submitter may not review their own submission.")


@bp.post("/sma/model-versions/<model_version_id>/approve")
@require_roles(ROLE_COMPLIANCE_OFFICER)
def approve_model_version(model_version_id):
    version = lookup(db.model_versions, model_version_id, "ERR_MODEL_VERSION_NOT_FOUND")
    _segregation_of_duties(version)
    if version["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_INVALID_STATE", "Only a PENDING_APPROVAL version may be approved.")
    version["status"] = "APPROVED"
    version["approved_by_user_id"] = g.user_id
    touch(version)
    return ok(serialize(version))


@bp.post("/sma/model-versions/<model_version_id>/reject")
@require_roles(ROLE_COMPLIANCE_OFFICER)
def reject_model_version(model_version_id):
    version = lookup(db.model_versions, model_version_id, "ERR_MODEL_VERSION_NOT_FOUND")
    _segregation_of_duties(version)
    body = body_json()
    rejection_note = v_str(body, "rejection_note")
    if version["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_INVALID_STATE", "Only a PENDING_APPROVAL version may be rejected.")
    version["status"] = "DRAFT"
    version["rejection_note"] = rejection_note
    version["submitted_by_user_id"] = None
    touch(version)
    return ok(serialize(version))


@bp.post("/sma/model-versions/<model_version_id>/publish")
@require_roles(ROLE_PORTFOLIO_MANAGER)
def publish_model_version(model_version_id):
    version = lookup(db.model_versions, model_version_id, "ERR_MODEL_VERSION_NOT_FOUND")
    if version["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Only an APPROVED version may be published.")
    cascade_a(version)
    return ok(serialize(version))


def cascade_a(version):
    """Publication fan-out, hops 1-5 (PRD 3.3)."""
    now = clock()
    model = db.models.get(version["model_id"])

    # --- hop 1 -------------------------------------------------------------
    prior = None
    for candidate in db.model_versions.values():
        if (candidate["model_id"] == version["model_id"]
                and candidate["id"] != version["id"]
                and candidate["status"] == "PUBLISHED"):
            prior = candidate
            break

    version["status"] = "PUBLISHED"
    version["published_at"] = now
    touch(version)
    if model is not None:
        model["published_model_version_id"] = version["id"]
        touch(model)

    if prior is None:
        return

    # --- hop 2 -------------------------------------------------------------
    prior["status"] = "SUPERSEDED"
    prior["superseded_at"] = now
    touch(prior)

    # --- hop 3 -------------------------------------------------------------
    lapsed_sponsor_ids = set()
    for dist in db.sponsor_distributions.values():
        if dist["model_version_id"] == prior["id"] and dist["status"] == "ACTIVE":
            dist["status"] = "LAPSED"
            dist["lapsed_at"] = now
            touch(dist)
            lapsed_sponsor_ids.add(dist["sponsor_id"])

    if not lapsed_sponsor_ids:
        return

    # --- hop 4 -------------------------------------------------------------
    notified = []
    for account in db.accounts.values():
        if account["sponsor_id"] not in lapsed_sponsor_ids:
            continue
        if account.get("current_model_version_id") != prior["id"]:
            continue
        if account["implementation_status"] not in ("SYNCED", "DRIFTED"):
            continue
        sponsor = db.sponsors.get(account["sponsor_id"])
        lag_days = sponsor["implementation_lag_days"] if sponsor else 0
        account["implementation_status"] = "PENDING_IMPLEMENTATION"
        account["pending_model_version_id"] = version["id"]
        account["notified_at"] = now
        account["implementation_deadline"] = now + timedelta(days=lag_days)
        account["implemented_late"] = False
        touch(account)
        notified.append(account)

    if not notified:
        return

    # --- hop 5 -------------------------------------------------------------
    notified_ids = {a["id"] for a in notified}
    affected_blocks = set()
    for order in db.trade_orders.values():
        if order["account_id"] not in notified_ids:
            continue
        if order.get("model_version_id") != prior["id"]:
            continue
        if order["status"] not in ("PROPOSED", "BLOCKED"):
            continue
        block_id = order.get("block_id")
        order["status"] = "STALE"
        order["block_id"] = None
        touch(order)
        if block_id:
            affected_blocks.add(block_id)
    for block_id in affected_blocks:
        block = db.blocks.get(block_id)
        if block is not None:
            recompute_block_membership(block)


# --------------------------------------------------------------- Dispersion --
@bp.get("/sma/model-versions/<model_version_id>/dispersion")
@require_roles(*READ_ROLES)
def get_dispersion(model_version_id):
    version = lookup(db.model_versions, model_version_id, "ERR_MODEL_VERSION_NOT_FOUND")
    basis = arg("basis") or "EQUAL_WEIGHTED"
    if basis not in DISPERSION_BASES:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'basis' is not a member of the enum.")
    return ok(dispersion_report(version["id"], basis))


# ------------------------------------------------------ SponsorDistribution --
@bp.post("/sma/sponsor-distributions")
@require_roles(ROLE_PORTFOLIO_MANAGER)
def create_distribution():
    body = body_json()

    # Rung 6: body reference existence, in declared input order.
    sponsor = None
    version = None
    if isinstance(body.get("sponsor_id"), str):
        sponsor = lookup(db.sponsors, body["sponsor_id"], "ERR_SPONSOR_NOT_FOUND")
    if isinstance(body.get("model_version_id"), str):
        version = lookup(db.model_versions, body["model_version_id"],
                         "ERR_MODEL_VERSION_NOT_FOUND")

    # Rung 7: request shape.
    v_str(body, "sponsor_id")
    v_str(body, "model_version_id")
    effective_from = v_dt(body, "effective_from")
    effective_until = v_dt(body, "effective_until", required=False, default=None)
    if effective_until is not None and effective_until <= effective_from:
        raise ApiError("ERR_INVALID_REQUEST",
                       "'effective_until' must be strictly later than 'effective_from'.")
    expected = v_int(body, "expected_model_version_version")

    # Rung 8: optimistic concurrency on the parent ModelVersion.
    if expected != version["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "The model version has advanced since it was last observed.")

    # Rung 12: referenced sibling state.
    if version["status"] != "PUBLISHED":
        raise ApiError("ERR_MODEL_VERSION_NOT_PUBLISHED",
                       "Only a PUBLISHED model version may be distributed.")

    # Rung 15: half-open effective window overlap on (sponsor_id, model_id).
    model_id = version["model_id"]
    for existing in db.sponsor_distributions.values():
        if existing["sponsor_id"] != sponsor["id"] or existing["model_id"] != model_id:
            continue
        if existing["status"] not in ("PENDING", "ACTIVE"):
            continue
        if half_open_collides(effective_from, effective_until,
                              existing["effective_from"], existing["effective_until"]):
            raise ApiError("ERR_DISTRIBUTION_WINDOW_OVERLAP",
                           "The effective window collides with an existing distribution.")

    row = new_row(sponsor_id=sponsor["id"], model_version_id=version["id"],
                  model_id=model_id, status="PENDING",
                  effective_from=effective_from, effective_until=effective_until,
                  activated_at=None, lapsed_at=None)
    db.sponsor_distributions[row["id"]] = row
    version["distribution_count"] += 1
    touch(version)
    return ok(serialize(row), 201)


@bp.get("/sma/sponsor-distributions/<sponsor_distribution_id>")
@require_roles(*READ_ROLES)
def get_distribution(sponsor_distribution_id):
    row = lookup(db.sponsor_distributions, sponsor_distribution_id, "ERR_DISTRIBUTION_NOT_FOUND")
    return ok(serialize(row))


@bp.get("/sma/sponsor-distributions")
@require_roles(*READ_ROLES)
def list_distributions():
    rows = qfilter(db.sponsor_distributions.values(),
                   sponsor_id=arg("sponsor_id"),
                   model_version_id=arg("model_version_id"),
                   model_id=arg("model_id"),
                   status=arg("status"))
    return paged(rows)


@bp.post("/sma/sponsor-distributions/<sponsor_distribution_id>/activate")
@require_roles(ROLE_SPONSOR_OPERATOR)
def activate_distribution(sponsor_distribution_id):
    dist = lookup(db.sponsor_distributions, sponsor_distribution_id, "ERR_DISTRIBUTION_NOT_FOUND")
    sponsor_scope(dist["sponsor_id"])
    if dist["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "Only a PENDING distribution may be activated.")
    version = db.model_versions.get(dist["model_version_id"])
    if version is None or version["status"] != "PUBLISHED":
        raise ApiError("ERR_MODEL_VERSION_NOT_PUBLISHED",
                       "The distributed model version is no longer PUBLISHED.")
    dist["status"] = "ACTIVE"
    dist["activated_at"] = clock()
    touch(dist)
    return ok(serialize(dist))
