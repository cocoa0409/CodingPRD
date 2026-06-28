"""Family and Student endpoints (PRD §3.3)."""
from flask import Blueprint, request

from db import db, public
import errors
import helpers
from middleware import get_auth, require_role, get_body
from response import success

bp = Blueprint("families", __name__)


# =========================================================================
# Family
# =========================================================================
@bp.route("/families", methods=["POST"])
def create_family():
    _uid, role = get_auth()
    require_role(role, {"FranchiseAdmin", "CenterDirector"})
    body = get_body()

    center_id = helpers.require_str(body, "center_id")
    contact_email = helpers.require_str(body, "contact_email")
    contact_name = helpers.require_str(body, "contact_name")

    if center_id not in db.centers:
        raise errors.not_found()

    obj = {
        "center_id": center_id,
        "contact_email": contact_email,
        "contact_name": contact_name,
        "wallet_credit_cents": 0,
        "sibling_count": 0,
    }
    db.stamp_create(obj)
    db.families[obj["id"]] = obj
    return success(public(obj), status=201)


@bp.route("/families/<family_id>", methods=["GET"])
def get_family(family_id):
    uid, role = get_auth()
    require_role(role, {"FranchiseAdmin", "CenterDirector", "Parent"})
    family = db.families.get(family_id)
    if not family:
        raise errors.not_found()
    if role == "Parent" and not helpers.parent_owns_family(uid, family_id):
        raise errors.forbidden()
    return success(public(family))


@bp.route("/families", methods=["GET"])
def list_families():
    _uid, role = get_auth()
    require_role(role, {"FranchiseAdmin", "CenterDirector"})
    center_id = request.args.get("center_id")
    items = list(db.families.values())
    if center_id:
        items = [f for f in items if f["center_id"] == center_id]
    return helpers.paginate_and_respond(items)


@bp.route("/families/<family_id>/wallet-adjustments", methods=["POST"])
def adjust_wallet(family_id):
    _uid, role = get_auth()
    require_role(role, {"FranchiseAdmin", "CenterDirector"})
    family = db.families.get(family_id)
    if not family:
        raise errors.not_found()
    body = get_body()
    amount = helpers.require_int(body, "amount_cents")
    helpers.require_str(body, "reason")

    new_balance = family["wallet_credit_cents"] + amount
    family["wallet_credit_cents"] = max(0, new_balance)
    db.touch(family)
    return success(public(family))


# =========================================================================
# Student
# =========================================================================
@bp.route("/students", methods=["POST"])
def create_student():
    uid, role = get_auth()
    require_role(role, {"FranchiseAdmin", "CenterDirector", "Parent"})
    body = get_body()

    family_id = helpers.require_str(body, "family_id")
    full_name = helpers.require_str(body, "full_name")
    birthdate = helpers.require_str(body, "birthdate")

    if family_id not in db.families:
        raise errors.not_found()
    if role == "Parent" and not helpers.parent_owns_family(uid, family_id):
        raise errors.forbidden()

    obj = {
        "family_id": family_id,
        "full_name": full_name,
        "birthdate": birthdate,
        "enrollment_fee_charged": False,
    }
    db.stamp_create(obj)
    db.students[obj["id"]] = obj
    return success(public(obj), status=201)


@bp.route("/students/<student_id>", methods=["GET"])
def get_student(student_id):
    uid, role = get_auth()
    require_role(role, {"FranchiseAdmin", "CenterDirector", "Parent", "Instructor"})
    student = db.students.get(student_id)
    if not student:
        raise errors.not_found()
    if role == "Parent" and not helpers.parent_owns_family(uid, student["family_id"]):
        raise errors.forbidden()
    return success(public(student))


@bp.route("/students", methods=["GET"])
def list_students():
    uid, role = get_auth()
    require_role(role, {"FranchiseAdmin", "CenterDirector", "Parent", "Instructor"})
    family_id = request.args.get("family_id")
    items = list(db.students.values())
    if family_id:
        items = [s for s in items if s["family_id"] == family_id]
    if role == "Parent":
        items = [s for s in items if helpers.parent_owns_family(uid, s["family_id"])]
    return helpers.paginate_and_respond(items)
