"""Damage charge routes: assess, get, list, bill, waive, pay."""

from flask import Blueprint, request

import db
import errors
import response
import common
from middleware import authenticate, require_role
from services import core

bp = Blueprint("damage_charges", __name__)

ALL_ROLES = ("HousingOfficer", "Student", "ResidentAdvisor")
CATEGORIES = {"CLEANING", "REPAIR", "REPLACEMENT", "LOST_KEY"}
SPLIT_BASES = {"SOLE", "SHARED"}


@bp.route("/damage-charges", methods=["POST"])
def create_charge():
    principal = authenticate()
    require_role(principal, ("HousingOfficer",))
    body = common.get_body()
    common.require_fields(body, ["assignment_id", "category", "assessed_cents", "split_basis"])
    assignment_id = body["assignment_id"]
    category = common.require_enum(body, "category", CATEGORIES)
    assessed = common.require_int(body, "assessed_cents", min_value=0)
    split_basis = common.require_enum(body, "split_basis", SPLIT_BASES)

    with db.LOCK:
        assignment = core.get_or_404(db.assignments, assignment_id)
        rec = core.init_record({
            "assignment_id": assignment_id,
            "room_id": assignment["room_id"],
            "category": category,
            "assessed_cents": assessed,
            "amount_cents": None,
            "split_basis": split_basis,
            "status": "PENDING",
        })
        db.damage_charges[rec["id"]] = rec
        return response.object_response(core.serialize(rec), status=201)


@bp.route("/damage-charges/<charge_id>", methods=["GET"])
def get_charge(charge_id):
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    with db.LOCK:
        rec = core.get_or_404(db.damage_charges, charge_id)
        return response.object_response(core.serialize(rec))


@bp.route("/damage-charges", methods=["GET"])
def list_charges():
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    with db.LOCK:
        limit, offset = common.parse_pagination()
        items = list(db.damage_charges.values())
        for key in ("assignment_id", "room_id"):
            val = request.args.get(key)
            if val is not None:
                items = [c for c in items if c.get(key) == val]
        items = common.sort_by_created(items)
        page, total = common.paginate(items, limit, offset)
        return response.array_response(
            [core.serialize(c) for c in page], limit, offset, total
        )


@bp.route("/damage-charges/<charge_id>/bill", methods=["POST"])
def bill_charge(charge_id):
    principal = authenticate()
    require_role(principal, ("HousingOfficer",))
    with db.LOCK:
        charge = core.get_or_404(db.damage_charges, charge_id)
        if charge["status"] != "PENDING":
            raise errors.invalid_state("Charge is not PENDING.")
        amount = _compute_split(charge)
        charge["status"] = "BILLED"
        charge["amount_cents"] = amount
        core.touch(charge)
        # Debit the student.
        student = _student_for_charge(charge)
        if student is not None:
            student["account_balance_cents"] += amount
            core.touch(student)
        return response.object_response(core.serialize(charge))


@bp.route("/damage-charges/<charge_id>/waive", methods=["POST"])
def waive_charge(charge_id):
    principal = authenticate()
    require_role(principal, ("HousingOfficer",))
    with db.LOCK:
        charge = core.get_or_404(db.damage_charges, charge_id)
        if charge["status"] != "PENDING":
            raise errors.invalid_state("Charge is not PENDING.")
        charge["status"] = "WAIVED"
        charge["amount_cents"] = 0
        core.touch(charge)
        return response.object_response(core.serialize(charge))


@bp.route("/damage-charges/<charge_id>/pay", methods=["POST"])
def pay_charge(charge_id):
    principal = authenticate()
    require_role(principal, ("HousingOfficer",))
    with db.LOCK:
        charge = core.get_or_404(db.damage_charges, charge_id)
        if charge["status"] != "BILLED":
            raise errors.invalid_state("Charge is not BILLED.")
        charge["status"] = "PAID"
        core.touch(charge)
        student = _student_for_charge(charge)
        if student is not None:
            new_balance = student["account_balance_cents"] - (charge["amount_cents"] or 0)
            student["account_balance_cents"] = max(0, new_balance)
            core.touch(student)
        return response.object_response(core.serialize(charge))


def _compute_split(charge):
    """damage_billing_split: floor-divide across ACTIVE occupants when SHARED;
    the billed resident absorbs the remainder."""
    assessed = charge["assessed_cents"]
    if charge["split_basis"] == "SOLE":
        return assessed
    occupants = sum(
        1 for a in db.assignments.values()
        if a["room_id"] == charge["room_id"] and a["status"] == "ACTIVE"
    )
    if occupants <= 1:
        return assessed
    base = assessed // occupants
    remainder = assessed - base * occupants
    return base + remainder


def _student_for_charge(charge):
    assignment = db.assignments.get(charge["assignment_id"])
    if assignment is None:
        return None
    return db.students.get(assignment["student_id"])
