from flask import Blueprint

from constants import ALL_ROLES, DONOR_TYPES
from db import store, stamp_new, pub
from middleware import authenticate
from response import success
from services.domain import get_or_404, list_response
from util import new_id, parse_body, req_str, req_enum, opt_str_nullable

bp = Blueprint("donors", __name__)


@bp.route("/endowment/donors", methods=["POST"])
def create_donor():
    authenticate(["DevelopmentOfficer"])
    body = parse_body(required=True)
    donor_name = req_str(body, "donor_name")
    donor_type = req_enum(body, "donor_type", DONOR_TYPES)
    contact_email = opt_str_nullable(body, "contact_email")
    rec = {
        "id": new_id(),
        "donor_name": donor_name,
        "donor_type": donor_type,
        "contact_email": contact_email,
        "total_contributed_cents": 0,
        "version": 1,
    }
    stamp_new(rec)
    store.donors[rec["id"]] = rec
    return success(pub(rec), status=201)


@bp.route("/endowment/donors", methods=["GET"])
def list_donors():
    authenticate(ALL_ROLES)
    return list_response(store.donors, [("donor_type", "donor_type", "str")])


@bp.route("/endowment/donors/<donor_id>", methods=["GET"])
def get_donor(donor_id):
    authenticate(ALL_ROLES)
    return success(pub(get_or_404(store.donors, donor_id, "Donor")))
