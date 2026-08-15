from flask import Blueprint

import db
from errors import ApiError
from middleware import require_roles
from response import ok
from validation import body, opt_bool, req_int, req_str

bp = Blueprint("drugs", __name__)

ALL_ROLES = ("PbmAdmin", "Pharmacist", "Member", "ClinicalReviewer", "Auditor")


@bp.route("/drugs", methods=["POST"])
def create_drug():
    require_roles("PbmAdmin")
    b = body()
    ndc = req_str(b, "ndc")
    name = req_str(b, "name")
    therapeutic_class = req_str(b, "therapeutic_class")
    unit_cost_cents = req_int(b, "unit_cost_cents", minimum=1)
    max_daily_dose_units = req_int(b, "max_daily_dose_units", minimum=1)
    is_specialty = opt_bool(b, "is_specialty", default=False)
    if any(d["ndc"] == ndc for d in db.drugs.values()):
        raise ApiError("ERR_INVALID_REQUEST", "A drug with this ndc already exists", 400)
    rec = db.base_record()
    rec.update(
        {
            "ndc": ndc,
            "name": name,
            "therapeutic_class": therapeutic_class,
            "unit_cost_cents": unit_cost_cents,
            "max_daily_dose_units": max_daily_dose_units,
            "is_specialty": is_specialty,
        }
    )
    db.drugs[rec["id"]] = rec
    return ok(db.public(rec), 201)


def get_drug_or_404(drug_id):
    drug = db.drugs.get(drug_id)
    if drug is None:
        raise ApiError("ERR_DRUG_NOT_FOUND", "Drug not found", 404)
    return drug


@bp.route("/drugs/<drug_id>", methods=["GET"])
def get_drug(drug_id):
    require_roles(*ALL_ROLES)
    return ok(db.public(get_drug_or_404(drug_id)), 200)
