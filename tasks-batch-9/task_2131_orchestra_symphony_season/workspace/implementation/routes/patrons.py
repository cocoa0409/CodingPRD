"""Patrons, philanthropy and donor standing."""

from flask import Blueprint

from db import db
from domain import (apply_donation, base_fields, recompute_patron_score,
                    serialize, touch)
from errors import raise_err
from middleware import endpoint
from response import ok
from validate import body, check_body_fks, opt_int, req_int, req_str

bp = Blueprint("patrons", __name__)


def get_patron_or_404(patron_id):
    patron = db.patrons.get(patron_id)
    if patron is None:
        raise_err("ERR_PATRON_NOT_FOUND")
    return patron


@bp.route("/orchestra/patrons", methods=["POST"])
@endpoint(["BoxOfficeAgent"])
def create_patron():
    data = body()
    check_body_fks(data, [])
    full_name = req_str(data, "full_name")
    email = req_str(data, "email")
    subscriber_since_year = opt_int(data, "subscriber_since_year", None)
    for existing in db.patrons.values():
        if existing["email"] == email:
            raise_err("ERR_INVALID_REQUEST", "Field 'email' must be unique across patrons.")

    patron = base_fields()
    patron.update({
        "full_name": full_name,
        "email": email,
        "subscriber_since_year": subscriber_since_year,
        "lifetime_donation_cents": 0,
        "donor_level": "NONE",
        "consecutive_renewal_years": 0,
        "renewal_priority_score": 0,
        "credit_balance_cents": 0,
        "lifetime_cash_in_cents": 0,
    })
    recompute_patron_score(patron)
    db.patrons[patron["id"]] = patron
    return ok(serialize(patron), 201)


@bp.route("/orchestra/patrons/<patron_id>", methods=["GET"])
@endpoint(["ArtisticAdmin", "BoxOfficeAgent", "Patron"])
def read_patron(patron_id):
    return ok(serialize(get_patron_or_404(patron_id)))


@bp.route("/orchestra/patrons/<patron_id>/donations", methods=["POST"])
@endpoint(["BoxOfficeAgent"])
def record_donation(patron_id):
    patron = get_patron_or_404(patron_id)                    # rung 3
    data = body()
    amount_cents = req_int(data, "amount_cents")             # rung 6
    with touch(patron):
        apply_donation(patron, amount_cents)
    return ok(serialize(patron))
