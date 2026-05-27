"""BenefitAward + ChildAuxiliaryBenefit + SSISupplement endpoints."""
from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_CHILD_OVER_AGE,
    ERR_FAMILY_MAX_EXCEEDED,
    ERR_INVALID_APPLICATION_STATE,
    ERR_STALE_AWARD_VERSION,
    invalid_request,
    not_found,
)
from middleware import require_roles
from response import created, ok, paginated
from services import calculations as calc
from services import state as svc_state
from services.utils import (
    paginate,
    parse_iso8601,
    parse_pagination,
    require_body,
    require_int,
    require_str,
    years_between,
)

bp = Blueprint("awards", __name__)

VALID_RELATIONSHIPS = {"BIOLOGICAL", "ADOPTED", "STEPCHILD"}


# ---------- BenefitAward ----------
@bp.route("/ssdi/awards/<aid>", methods=["GET"])
@require_roles("Claimant", "BenefitsAdmin", "SSAAdmin")
def get_award(aid, user_id, role):
    rec = db.awards.get(aid)
    if rec is None:
        raise not_found(f"award {aid} not found")
    return ok(rec)


@bp.route("/ssdi/awards", methods=["GET"])
@require_roles("BenefitsAdmin", "SSAAdmin", "Claimant")
def list_awards(user_id, role):
    limit, offset = parse_pagination(request.args)
    items = list(db.awards.values())
    app_filter = request.args.get("application_id")
    status_filter = request.args.get("status")
    if app_filter:
        items = [r for r in items if r.get("application_id") == app_filter]
    if status_filter:
        items = [r for r in items if r.get("status") == status_filter]
    items, total = paginate(items, limit, offset)
    return paginated(items, total, limit, offset)


@bp.route("/ssdi/awards/<aid>/suspend", methods=["POST"])
@require_roles("BenefitsAdmin")
def suspend(aid, user_id, role):
    award = db.awards.get(aid)
    if award is None:
        raise not_found(f"award {aid} not found")
    if award.get("status") != "ACTIVE":
        raise APIError(
            ERR_INVALID_APPLICATION_STATE,
            409,
            f"award not in ACTIVE (current: {award.get('status')})",
        )
    svc_state.suspend_award(award)
    return ok(award)


@bp.route("/ssdi/awards/<aid>/reinstate", methods=["POST"])
@require_roles("BenefitsAdmin")
def reinstate(aid, user_id, role):
    award = db.awards.get(aid)
    if award is None:
        raise not_found(f"award {aid} not found")
    if award.get("status") != "SUSPENDED":
        raise APIError(
            ERR_INVALID_APPLICATION_STATE,
            409,
            f"award not in SUSPENDED (current: {award.get('status')})",
        )
    svc_state.reinstate_award(award)
    return ok(award)


# ---------- Child auxiliaries ----------
@bp.route("/ssdi/awards/<aid>/child-auxiliaries", methods=["POST"])
@require_roles("Claimant", "BenefitsAdmin")
def create_child_aux(aid, user_id, role):
    award = db.awards.get(aid)
    if award is None:
        raise not_found(f"award {aid} not found")
    body = require_body()
    # Priority 9: OCC stale parent version
    expected_version = require_int(body, "expected_benefit_award_version")
    if expected_version != award.get("version"):
        raise APIError(
            ERR_STALE_AWARD_VERSION,
            412,
            f"expected_benefit_award_version {expected_version} != current {award.get('version')}",
        )
    child_name = require_str(body, "child_full_name")
    cdob = require_str(body, "child_date_of_birth")
    cdob_dt = parse_iso8601(cdob, "child_date_of_birth")
    relationship = require_str(body, "relationship")
    if relationship not in VALID_RELATIONSHIPS:
        raise invalid_request(f"invalid relationship: {relationship}")
    # Priority 14: child must be under 18
    if years_between(cdob_dt, db.now_utc()) >= 18:
        raise APIError(
            ERR_CHILD_OVER_AGE,
            422,
            "child must be under 18 at creation time",
        )
    # Priority 15: family-max headroom
    base, family_max, headroom = calc.compute_child_aux_base_and_headroom(award)
    if headroom <= 0:
        raise APIError(
            ERR_FAMILY_MAX_EXCEEDED,
            422,
            "creating this child auxiliary would exceed the family-max headroom",
        )
    amount = min(base, max(0, headroom))
    rec = {
        "benefit_award_id": aid,
        "child_full_name": child_name,
        "child_date_of_birth": cdob,
        "relationship": relationship,
        "monthly_amount_cents": amount,
        "status": "ACTIVE",
    }
    db.stamp_create(rec)
    db.child_aux[rec["id"]] = rec
    # Side effect: bump parent award version
    db.stamp_update(award)
    return created(rec)


@bp.route("/ssdi/awards/<aid>/child-auxiliaries", methods=["GET"])
@require_roles("Claimant", "BenefitsAdmin", "SSAAdmin")
def list_child_aux(aid, user_id, role):
    award = db.awards.get(aid)
    if award is None:
        raise not_found(f"award {aid} not found")
    limit, offset = parse_pagination(request.args)
    items = [c for c in db.child_aux.values() if c.get("benefit_award_id") == aid]
    items, total = paginate(items, limit, offset)
    return paginated(items, total, limit, offset)


# ---------- SSI supplements ----------
@bp.route("/ssdi/ssi-supplements/<sid>", methods=["GET"])
@require_roles("Claimant", "BenefitsAdmin", "SSAAdmin")
def get_ssi(sid, user_id, role):
    rec = db.ssi_supplements.get(sid)
    if rec is None:
        raise not_found(f"ssi supplement {sid} not found")
    return ok(rec)


@bp.route("/ssdi/ssi-supplements", methods=["GET"])
@require_roles("BenefitsAdmin", "SSAAdmin")
def list_ssi(user_id, role):
    limit, offset = parse_pagination(request.args)
    items = list(db.ssi_supplements.values())
    app_filter = request.args.get("application_id")
    status_filter = request.args.get("status")
    if app_filter:
        items = [r for r in items if r.get("application_id") == app_filter]
    if status_filter:
        items = [r for r in items if r.get("status") == status_filter]
    items, total = paginate(items, limit, offset)
    return paginated(items, total, limit, offset)
