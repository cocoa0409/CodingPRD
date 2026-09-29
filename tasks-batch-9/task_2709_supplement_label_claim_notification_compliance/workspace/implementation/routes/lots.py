"""Ingredient lots: intake, release and the compensating recall (PRD 3.7)."""

from flask import Blueprint

import auth
import calc
import cascade
import db
import errors
import response
import serialize
import validate
from errors import fail
from routes.helpers import PREFIX, fk_row, listing, path_row

bp = Blueprint("ingredient_lots", __name__)

READ_ROLES = (
    auth.ROLE_QA,
    auth.ROLE_SPECIALIST,
    auth.ROLE_SUPPLIER_REP,
    auth.ROLE_AUDITOR,
)


def _lot_code_taken(supplier_id, lot_code):
    for lot in db.all_rows("lots"):
        if lot["supplier_id"] == supplier_id and lot["lot_code"] == lot_code:
            return True
    return False


def release_mass(lot, supplier):
    """Move the whole lot from quarantine into the released bucket."""
    mass = calc.d2(lot["quantity_kg"])
    lot["released_quantity_kg"] = mass
    lot["quarantined_quantity_kg"] = calc.d2(0)
    lot["lot_status"] = "RELEASED"
    lot["released_at"] = db.now()
    db.touch(lot)
    if supplier is not None:
        supplier["total_released_kg"] = calc.d2(
            calc.dec(supplier["total_released_kg"]) + calc.dec(mass)
        )
        db.touch(supplier)


def recall_mass(lot, supplier, reason):
    """Compensate a release: the mass becomes rejected and the ledger returns exactly."""
    mass = calc.d2(lot["quantity_kg"])
    lot["rejected_quantity_kg"] = mass
    lot["released_quantity_kg"] = calc.d2(0)
    lot["lot_status"] = "RECALLED"
    lot["recalled_at"] = db.now()
    lot["recall_reason"] = reason
    db.touch(lot)
    if supplier is not None:
        supplier["total_released_kg"] = calc.d2(
            calc.dec(supplier["total_released_kg"]) - calc.dec(mass)
        )
        db.touch(supplier)


def reject_quarantined_mass(lot):
    """A certificate rejection on a still-quarantined lot disposes of it outright."""
    mass = calc.d2(lot["quantity_kg"])
    lot["rejected_quantity_kg"] = mass
    lot["quarantined_quantity_kg"] = calc.d2(0)
    lot["lot_status"] = "REJECTED"
    db.touch(lot)


@bp.route(PREFIX + "/ingredient-lots", methods=["POST"])
@auth.endpoint([auth.ROLE_SUPPLIER_REP, auth.ROLE_QA])
def create_lot():
    body = validate.body()
    supplier_id = validate.req_str(body, "supplier_id")
    ingredient_id = validate.req_str(body, "ingredient_id")
    lot_code = validate.req_str(body, "lot_code")
    quantity_kg = validate.req_number(body, "quantity_kg", gt=0)

    # Screening order is pinned: ingredient_id (priority 6) resolves before supplier_id (9).
    fk_row("ingredients", ingredient_id, errors.ERR_INGREDIENT_NOT_FOUND)
    fk_row("suppliers", supplier_id, errors.ERR_SUPPLIER_NOT_FOUND)

    if auth.role() == auth.ROLE_SUPPLIER_REP and auth.user_id() != supplier_id:
        fail(
            errors.ERR_SUPPLIER_SCOPE_VIOLATION,
            "A supplier representative may only receive lots for its own supplier id.",
        )

    if _lot_code_taken(supplier_id, lot_code):
        fail(
            errors.ERR_LOT_CODE_DUPLICATE,
            "lot_code %s is already recorded for this supplier." % lot_code,
        )

    mass = calc.d2(quantity_kg)
    row = db.base_fields()
    row.update(
        {
            "supplier_id": supplier_id,
            "ingredient_id": ingredient_id,
            "lot_code": lot_code,
            "quantity_kg": mass,
            "quarantined_quantity_kg": mass,
            "released_quantity_kg": calc.d2(0),
            "rejected_quantity_kg": calc.d2(0),
            "lot_status": "QUARANTINED",
            "identity_verified": False,
            "released_at": None,
            "recalled_at": None,
            "recall_reason": None,
        }
    )
    db.insert("lots", row)
    return response.object_response(serialize.lot(row), 201)


@bp.route(PREFIX + "/ingredient-lots/<row_id>", methods=["GET"])
@auth.endpoint(READ_ROLES)
def get_lot(row_id):
    row = path_row("lots", row_id, errors.ERR_LOT_NOT_FOUND)
    return response.object_response(serialize.lot(row))


@bp.route(PREFIX + "/ingredient-lots", methods=["GET"])
@auth.endpoint(READ_ROLES)
def list_lots():
    return listing(
        "lots", serialize.lot, filters=("supplier_id", "ingredient_id", "lot_status")
    )


@bp.route(PREFIX + "/ingredient-lots/<row_id>/release", methods=["POST"])
@auth.endpoint([auth.ROLE_QA])
def release_lot(row_id):
    row = path_row("lots", row_id, errors.ERR_LOT_NOT_FOUND)

    if row["lot_status"] != "QUARANTINED":
        fail(errors.ERR_LOT_STATE_INVALID, "Only a QUARANTINED lot may be released.")

    supplier = db.get("suppliers", row["supplier_id"])
    if supplier is None or supplier["qualification_status"] != "QUALIFIED":
        fail(
            errors.ERR_SUPPLIER_NOT_QUALIFIED,
            "The lot's own supplier must be QUALIFIED before release.",
        )
    if not row["identity_verified"]:
        fail(
            errors.ERR_LOT_IDENTITY_UNVERIFIED,
            "The lot has no ACCEPTED certificate confirming its identity.",
        )

    release_mass(row, supplier)
    # A released lot joins the derived supplier set of every product on its ingredient.
    for product in cascade.products_with_active_line_on(row["ingredient_id"]):
        cascade.recompute_posture(product)
    return response.object_response(serialize.lot(row))


@bp.route(PREFIX + "/ingredient-lots/<row_id>/recall", methods=["POST"])
@auth.endpoint([auth.ROLE_QA])
def recall_lot(row_id):
    row = path_row("lots", row_id, errors.ERR_LOT_NOT_FOUND)
    body = validate.body()
    reason = validate.req_str(body, "recall_reason")

    if row["lot_status"] != "RELEASED":
        fail(errors.ERR_LOT_STATE_INVALID, "Only a RELEASED lot may be recalled.")

    supplier = db.get("suppliers", row["supplier_id"])
    recall_mass(row, supplier, reason)

    # RECALLED still populates the derived supplier set, so the posture is re-derived.
    for product in cascade.products_with_active_line_on(row["ingredient_id"]):
        cascade.recompute_posture(product)
    return response.object_response(serialize.lot(row))
