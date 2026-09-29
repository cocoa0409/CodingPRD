"""Patron endpoints (PRD 3.2)."""

from flask import Blueprint

from db import base_record, db, public, sort_created_asc, touch
from errors import ApiError
from middleware import ANY_ROLE, auth, f_str, get_body, q, q_bool
from response import ok
from services.domain import get_or_404
from routes._common import filter_bool, paginated

bp = Blueprint("patrons", __name__)


@bp.route("/patrons", methods=["POST"])
def register_patron():
    auth(("BoxOfficeAgent",))
    body = get_body()
    email = f_str(body, "email", allow_empty=False)
    display_name = f_str(body, "display_name", allow_empty=False)

    lowered = email.strip().lower()
    for patron in db.patrons.values():
        if patron["email"].strip().lower() == lowered:
            raise ApiError("ERR_DUPLICATE_EMAIL")

    rec = base_record()
    rec["email"] = email
    rec["display_name"] = display_name
    rec["identity_verified"] = False
    rec["device_rebind_count"] = 0
    rec["strike_count"] = 0
    rec["fraud_risk_score"] = 0
    rec["fraud_risk_basis"] = "PROVISIONAL"
    rec["remediation_credit_cents"] = 0
    rec["payout_balance_cents"] = 0
    db.patrons[rec["id"]] = rec
    return ok(public(rec), 201)


@bp.route("/patrons/<patron_id>", methods=["GET"])
def get_patron(patron_id):
    auth(ANY_ROLE)
    patron = get_or_404(db.patrons, patron_id, "ERR_PATRON_NOT_FOUND")
    return ok(public(patron))


@bp.route("/patrons", methods=["GET"])
def list_patrons():
    auth(("BoxOfficeAgent", "SecurityInvestigator", "VenueAdmin"))
    rows = sort_created_asc(list(db.patrons.values()))
    email = q("email")
    if email is not None:
        lowered = email.strip().lower()
        rows = [r for r in rows if r["email"].strip().lower() == lowered]
    rows = filter_bool(rows, "identity_verified", q_bool("identity_verified"))
    return paginated(rows)


@bp.route("/patrons/<patron_id>/verify-identity", methods=["POST"])
def verify_identity(patron_id):
    auth(("BoxOfficeAgent",))
    body = get_body()
    f_str(body, "document_reference", allow_empty=False)
    patron = get_or_404(db.patrons, patron_id, "ERR_PATRON_NOT_FOUND")
    patron["identity_verified"] = True
    touch(patron)
    return ok(public(patron))
