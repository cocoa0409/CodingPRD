"""SpecialAssessment routes: create, get, list, levy."""
from flask import request

from db import db, stamp_create, touch
import errors
from errors import err
from middleware import get_user_context, require_role
from response import success
from routes.common import get_or_404, get_json, list_response
from services.util import serialize, require_str, require_int, parse_iso
from services.calc import special_assessment_shares


def serialize_assessment(a):
    return serialize(a)


def _points_basis(contract):
    if contract["inventory_model"] == "FIXED_WEEK" and contract.get("fixed_unit_id"):
        unit = db.inventory_units.get(contract["fixed_unit_id"])
        if unit is not None:
            return unit["points_value"]
        return 0
    return contract["annual_points_allotment"]


def register(app):
    @app.route("/special-assessments", methods=["POST"])
    def create_assessment():
        _, role = get_user_context()
        require_role(role, ["ResortManager"])
        data = get_json()
        resort_id = require_str(data, "resort_id")
        reason = require_str(data, "reason")
        total_amount_cents = require_int(data, "total_amount_cents", positive=True)
        use_year = require_int(data, "use_year")
        get_or_404(db.resorts, resort_id)
        sa = {
            "resort_id": resort_id,
            "reason": reason,
            "total_amount_cents": total_amount_cents,
            "use_year": use_year,
            "status": "DRAFT",
        }
        stamp_create(sa)
        db.special_assessments[sa["id"]] = sa
        return success(serialize_assessment(sa), status=201)

    @app.route("/special-assessments/<assessment_id>", methods=["GET"])
    def get_assessment(assessment_id):
        _, role = get_user_context()
        require_role(role, ["ResortManager", "Owner", "ResaleAgent", "ComplianceOfficer"])
        sa = get_or_404(db.special_assessments, assessment_id)
        return success(serialize_assessment(sa))

    @app.route("/special-assessments", methods=["GET"])
    def list_assessments():
        _, role = get_user_context()
        require_role(role, ["ResortManager", "ResaleAgent", "ComplianceOfficer"])
        items = list(db.special_assessments.values())
        for key in ("resort_id", "status"):
            val = request.args.get(key)
            if val is not None:
                items = [a for a in items if a.get(key) == val]
        return list_response(items, serialize_assessment)

    @app.route("/special-assessments/<assessment_id>/levy", methods=["POST"])
    def levy_assessment(assessment_id):
        _, role = get_user_context()
        require_role(role, ["ResortManager"])
        sa = get_or_404(db.special_assessments, assessment_id)
        if sa["status"] != "DRAFT":
            raise err(errors.ERR_INVALID_STATE, "Assessment is not DRAFT.")
        data = get_json()
        due_date = require_str(data, "due_date")
        try:
            parse_iso(due_date)
        except Exception:
            raise err(errors.ERR_INVALID_REQUEST, "due_date is not a valid ISO 8601 timestamp.")

        # ACTIVE contracts at the resort, ordered by created_at ASC (stable via _seq).
        active = [
            c
            for c in db.contracts.values()
            if c["resort_id"] == sa["resort_id"] and c["status"] == "ACTIVE"
        ]
        if not active:
            raise err(errors.ERR_NO_ELIGIBLE_CONTRACTS, "No ACTIVE contracts at the resort.")
        active.sort(key=lambda c: c["_seq"])

        contracts_with_basis = [(c, _points_basis(c)) for c in active]
        shares = special_assessment_shares(sa["total_amount_cents"], contracts_with_basis)

        sa["status"] = "LEVIED"
        touch(sa)
        for c in active:
            invoice = {
                "contract_id": c["id"],
                "owner_id": c["owner_id"],
                "source_type": "SPECIAL_ASSESSMENT",
                "special_assessment_id": sa["id"],
                "use_year": sa["use_year"],
                "amount_cents": shares[c["id"]],
                "late_charge_cents": 0,
                "amount_paid_cents": 0,
                "due_date": due_date,
                "status": "DRAFT",
            }
            stamp_create(invoice)
            db.invoices[invoice["id"]] = invoice
        return success(serialize_assessment(sa))
