"""Certificates of analysis and the four-hop rejection cascade (PRD 3.7)."""

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
from routes import lots as lots_routes
from routes.helpers import PREFIX, fk_row, listing, path_row

bp = Blueprint("coas", __name__)

READ_ROLES = (
    auth.ROLE_QA,
    auth.ROLE_SPECIALIST,
    auth.ROLE_SUPPLIER_REP,
    auth.ROLE_AUDITOR,
)


@bp.route(PREFIX + "/coas", methods=["POST"])
@auth.endpoint([auth.ROLE_SUPPLIER_REP, auth.ROLE_QA])
def create_coa():
    body = validate.body()
    lot_id = validate.req_str(body, "lot_id")
    lab_name = validate.req_str(body, "lab_name")
    method = validate.req_enum(body, "identity_test_method", calc.IDENTITY_METHODS)
    identity_match = validate.req_bool(body, "identity_match")
    assay = validate.req_number(body, "assay_percent_of_label", ge=0)
    heavy_metals_pass = validate.req_bool(body, "heavy_metals_pass")
    microbial_pass = validate.req_bool(body, "microbial_pass")

    lot = fk_row("lots", lot_id, errors.ERR_LOT_NOT_FOUND)

    if auth.role() == auth.ROLE_SUPPLIER_REP and auth.user_id() != lot["supplier_id"]:
        fail(
            errors.ERR_SUPPLIER_SCOPE_VIOLATION,
            "A supplier representative may only certify its own lots.",
        )

    ingredient = db.get("ingredients", lot["ingredient_id"])
    ingredient_class = None if ingredient is None else ingredient["ingredient_class"]
    approved = calc.APPROVED_METHODS.get(ingredient_class, ())
    if method not in approved:
        fail(
            errors.ERR_IDENTITY_METHOD_NOT_APPROVED,
            "%s is not an approved identity method for ingredient class %s."
            % (method, ingredient_class),
        )

    row = db.base_fields()
    row.update(
        {
            "lot_id": lot_id,
            "lab_name": lab_name,
            "identity_test_method": method,
            "identity_match": identity_match,
            "assay_percent_of_label": calc.d2(assay),
            "heavy_metals_pass": heavy_metals_pass,
            "microbial_pass": microbial_pass,
            "coa_acceptable": calc.coa_acceptable(
                identity_match, assay, heavy_metals_pass, microbial_pass
            ),
            "coa_status": "RECEIVED",
            "review_decision": None,
            "reviewed_by_user_id": None,
            "reviewed_at": None,
            "rejection_reason": None,
        }
    )
    db.insert("coas", row)
    return response.object_response(serialize.coa(row), 201)


@bp.route(PREFIX + "/coas/<row_id>", methods=["GET"])
@auth.endpoint(READ_ROLES)
def get_coa(row_id):
    row = path_row("coas", row_id, errors.ERR_COA_NOT_FOUND)
    return response.object_response(serialize.coa(row))


@bp.route(PREFIX + "/coas", methods=["GET"])
@auth.endpoint(READ_ROLES)
def list_coas():
    return listing("coas", serialize.coa, filters=("lot_id", "coa_status"))


@bp.route(PREFIX + "/coas/<row_id>/review", methods=["POST"])
@auth.endpoint([auth.ROLE_QA])
def review_coa(row_id):
    row = path_row("coas", row_id, errors.ERR_COA_NOT_FOUND)
    body = validate.body()
    decision = validate.req_enum(body, "decision", calc.REVIEW_DECISIONS)
    rejection_reason = validate.opt_str(body, "rejection_reason")

    if row["coa_status"] != "RECEIVED":
        fail(errors.ERR_COA_STATE_INVALID, "Only a RECEIVED certificate may be reviewed.")
    if decision == "ACCEPT" and not row["coa_acceptable"]:
        fail(
            errors.ERR_COA_NOT_ACCEPTABLE,
            "An unacceptable certificate cannot be accepted.",
        )

    now = db.now()
    row["reviewed_by_user_id"] = auth.user_id()
    row["reviewed_at"] = now
    row["review_decision"] = decision

    lot = db.get("lots", row["lot_id"])

    if decision == "ACCEPT":
        row["coa_status"] = "ACCEPTED"
        db.touch(row)
        if lot is not None and row["identity_match"] is True:
            lot["identity_verified"] = True
            db.touch(lot)
        return response.object_response(serialize.coa(row))

    row["coa_status"] = "REJECTED"
    row["rejection_reason"] = rejection_reason
    db.touch(row)
    _rejection_cascade(lot)
    return response.object_response(serialize.coa(row))


def _rejection_cascade(lot):
    """The four hops of PRD 3.7: products, then the lot, then the supplier, then postures."""
    if lot is None:
        return

    # Hop 1 - every product printing this ingredient absorbs a rejected certificate.
    affected = cascade.products_with_active_line_on(lot["ingredient_id"])
    for product in affected:
        product["rejected_coa_count"] += 1
        db.touch(product)
        cascade.recompute_risk_index(product)

    # Hop 2 - dispose of the lot according to where it stood.
    supplier = db.get("suppliers", lot["supplier_id"])
    if lot["lot_status"] == "QUARANTINED":
        lots_routes.reject_quarantined_mass(lot)
    elif lot["lot_status"] == "RELEASED":
        lots_routes.recall_mass(lot, supplier, "COA_REJECTED")

    # Hop 3 - the rejection count drives the supplier's qualification standing.
    if supplier is not None:
        supplier["coa_rejection_count"] += 1
        count = supplier["coa_rejection_count"]
        status = supplier["qualification_status"]
        if count >= 2 and status == "PROBATION":
            supplier["qualification_status"] = "DISQUALIFIED"
            supplier["last_decision_at"] = db.now()
        elif count >= 1 and status == "QUALIFIED":
            supplier["qualification_status"] = "PROBATION"
            supplier["last_decision_at"] = db.now()
        db.touch(supplier)

        # Hop 4 - the supplier transition re-derives every affected product's posture.
        cascade.supplier_qualification_cascade(supplier)

    for product in affected:
        cascade.recompute_posture(product)
