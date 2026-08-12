from flask import Blueprint

import constants as C
import serializers
import validation as V
from envelope import object_response
from lookups import path_row, unique_or_400
from store import db

bp = Blueprint("agencies", __name__)


@bp.post("/livescan/agencies")
def create_agency():
    data = V.body()
    name = V.req_string(data, "name")
    account_code = V.req_string(data, "account_code")
    regime = V.opt_string(data, "payer_regime_default", default="APPLICANT_PAID")
    terms = V.opt_int(data, "invoice_terms_days", default=C.INVOICE_TERMS_DAYS,
                      minimum=1, maximum=90)
    unique_or_400("agencies", "account_code", account_code)
    V.enum_value("payer_regime_default", regime, C.PAYER_REGIMES)

    row = db.create(
        "agencies",
        {
            "name": name,
            "account_code": account_code,
            "billing_status": "CURRENT",
            "payer_regime_default": regime,
            "invoice_terms_days": terms,
            "outstanding_balance_cents": 0,
            "max_aging_days": 0,
            "mtd_billed_cents": 0,
            "suspended_at": None,
        },
    )
    return object_response(serializers.agency(row), 201)


@bp.get("/livescan/agencies/<id>")
def read_agency(id):
    row = path_row("agencies", id)
    return object_response(serializers.agency(row))
