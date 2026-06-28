"""Center and FranchiseAgreement endpoints (PRD §3.1)."""
from flask import Blueprint, request

from db import db, public
import errors
import helpers
from middleware import get_auth, require_role, get_body
from response import success

bp = Blueprint("centers", __name__)


# =========================================================================
# Center
# =========================================================================
@bp.route("/centers", methods=["POST"])
def create_center():
    _uid, role = get_auth()
    require_role(role, {"FranchiseAdmin"})
    body = get_body()

    name = helpers.require_str(body, "name")
    territory_code = helpers.require_str(body, "territory_code")
    ratio_cap = helpers.require_int(body, "instructor_ratio_cap", minimum=1, default=6, required=False)
    enrollment_fee = helpers.require_int(body, "enrollment_fee_cents", minimum=0, default=5000, required=False)
    monthly_tuition = helpers.require_int(body, "monthly_tuition_cents", minimum=0, default=15000, required=False)

    # territory_code stored uppercase, unique across all centers.
    territory_code = territory_code.upper()
    for c in db.centers.values():
        if c["territory_code"] == territory_code:
            raise errors.territory_conflict()

    obj = {
        "name": name,
        "territory_code": territory_code,
        "instructor_ratio_cap": ratio_cap,
        "enrollment_fee_cents": enrollment_fee,
        "monthly_tuition_cents": monthly_tuition,
        "status": "PROVISIONING",
        "active_enrollment_count": 0,
    }
    db.stamp_create(obj)
    db.centers[obj["id"]] = obj
    return success(public(obj), status=201)


def _recompute_active_enrollment_count(center_id):
    center = db.centers.get(center_id)
    if not center:
        return
    count = sum(
        1 for e in db.enrollments.values()
        if e["center_id"] == center_id and e["status"] in ("ACTIVE", "PAUSED")
    )
    center["active_enrollment_count"] = count


@bp.route("/centers/<center_id>", methods=["GET"])
def get_center(center_id):
    _uid, role = get_auth()
    require_role(role, {"FranchiseAdmin", "CenterDirector", "Instructor", "Parent"})
    center = db.centers.get(center_id)
    if not center:
        raise errors.not_found()
    _recompute_active_enrollment_count(center_id)
    return success(public(center))


@bp.route("/centers", methods=["GET"])
def list_centers():
    _uid, role = get_auth()
    require_role(role, {"FranchiseAdmin"})
    status = request.args.get("status")
    items = list(db.centers.values())
    if status:
        items = [c for c in items if c["status"] == status]
    for c in items:
        _recompute_active_enrollment_count(c["id"])
    return helpers.paginate_and_respond(items)


@bp.route("/centers/<center_id>/activate", methods=["POST"])
def activate_center(center_id):
    _uid, role = get_auth()
    require_role(role, {"FranchiseAdmin"})
    center = db.centers.get(center_id)
    if not center:
        raise errors.not_found()
    if center["status"] not in ("PROVISIONING", "SUSPENDED"):
        raise errors.invalid_state()
    # Requires an ACTIVE FranchiseAgreement naming this center.
    has_active = any(
        a["center_id"] == center_id and a["status"] == "ACTIVE"
        for a in db.agreements.values()
    )
    if not has_active:
        raise errors.agreement_not_active()
    center["status"] = "OPERATING"
    db.touch(center)
    return success(public(center))


@bp.route("/centers/<center_id>/suspend", methods=["POST"])
def suspend_center(center_id):
    _uid, role = get_auth()
    require_role(role, {"FranchiseAdmin"})
    center = db.centers.get(center_id)
    if not center:
        raise errors.not_found()
    if center["status"] != "OPERATING":
        raise errors.invalid_state()
    center["status"] = "SUSPENDED"
    db.touch(center)
    # Cascade L1: SCHEDULED/OPEN sessions at this center -> CANCELLED, then L2
    # their BOOKED/PRESENT attendance -> CANCELLED, recompute booked_seat_count.
    from services import session_ops
    for sess in db.sessions.values():
        if sess["center_id"] == center_id and sess["status"] in ("SCHEDULED", "OPEN"):
            session_ops.cancel_session_cascade(sess)
    return success(public(center))


# =========================================================================
# FranchiseAgreement
# =========================================================================
@bp.route("/franchise-agreements", methods=["POST"])
def create_agreement():
    _uid, role = get_auth()
    require_role(role, {"FranchiseAdmin"})
    body = get_body()

    center_id = helpers.require_str(body, "center_id")
    royalty_rate = helpers.require_int(body, "royalty_rate_bps", minimum=0, maximum=10000, default=1000, required=False)
    marketing_fee = helpers.require_int(body, "marketing_fee_bps", minimum=0, maximum=10000, default=200, required=False)
    minimum_royalty = helpers.require_int(body, "minimum_monthly_royalty_cents", minimum=0, default=50000, required=False)
    royalty_basis = body.get("royalty_basis", "ROYALTY_FLOOR")
    if royalty_basis not in ("ROYALTY_FLOOR", "COMBINED_FLOOR"):
        raise errors.invalid_request("royalty_basis must be ROYALTY_FLOOR or COMBINED_FLOOR.")

    if center_id not in db.centers:
        raise errors.not_found()

    obj = {
        "center_id": center_id,
        "royalty_rate_bps": royalty_rate,
        "marketing_fee_bps": marketing_fee,
        "minimum_monthly_royalty_cents": minimum_royalty,
        "royalty_basis": royalty_basis,
        "status": "PENDING",
    }
    db.stamp_create(obj)
    db.agreements[obj["id"]] = obj
    return success(public(obj), status=201)


@bp.route("/franchise-agreements/<agreement_id>", methods=["GET"])
def get_agreement(agreement_id):
    _uid, role = get_auth()
    require_role(role, {"FranchiseAdmin", "CenterDirector"})
    agreement = db.agreements.get(agreement_id)
    if not agreement:
        raise errors.not_found()
    return success(public(agreement))


@bp.route("/franchise-agreements", methods=["GET"])
def list_agreements():
    _uid, role = get_auth()
    require_role(role, {"FranchiseAdmin", "CenterDirector"})
    center_id = request.args.get("center_id")
    items = list(db.agreements.values())
    if center_id:
        items = [a for a in items if a["center_id"] == center_id]
    return helpers.paginate_and_respond(items)


@bp.route("/franchise-agreements/<agreement_id>/activate", methods=["POST"])
def activate_agreement(agreement_id):
    _uid, role = get_auth()
    require_role(role, {"FranchiseAdmin"})
    agreement = db.agreements.get(agreement_id)
    if not agreement:
        raise errors.not_found()
    if agreement["status"] != "PENDING":
        raise errors.invalid_state()
    if agreement["royalty_rate_bps"] + agreement["marketing_fee_bps"] > 10000:
        raise errors.royalty_rate_invalid()
    agreement["status"] = "ACTIVE"
    db.touch(agreement)
    return success(public(agreement))


@bp.route("/franchise-agreements/<agreement_id>/terminate", methods=["POST"])
def terminate_agreement(agreement_id):
    _uid, role = get_auth()
    require_role(role, {"FranchiseAdmin"})
    agreement = db.agreements.get(agreement_id)
    if not agreement:
        raise errors.not_found()
    if agreement["status"] != "ACTIVE":
        raise errors.invalid_state()
    center = db.centers.get(agreement["center_id"])
    if center and center["status"] == "OPERATING":
        raise errors.center_operating()
    agreement["status"] = "TERMINATED"
    db.touch(agreement)
    return success(public(agreement))
