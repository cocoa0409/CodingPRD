"""Supplier scorecards: the PROVISIONAL and FINAL composite variants (PRD 3.9)."""
from flask import Blueprint

import auth
import calc
import clock
import response
import store
import validate
from errors import ApiError
from store import created_key, db, touch

from routes import common

bp = Blueprint("scorecards", __name__)

VARIANTS = ("PROVISIONAL", "FINAL")


@bp.post("/suppliers/<supplier_id>/scorecards")
def create_scorecard(supplier_id):
    auth.authenticate(("CommercialManager", "ComplianceOfficer"))
    supplier = common.find("suppliers", supplier_id)
    data = validate.body()
    period_start = validate.date_req(data, "period_start")
    period_end = validate.date_req(data, "period_end")
    fields = {
        "supplier_id": supplier["id"],
        "period_start": period_start,
        "period_end": period_end,
        "variant": "PROVISIONAL",
        "finalized_by_user_id": None,
    }
    fields.update(calc.composite_score(supplier, period_start, period_end, "PROVISIONAL"))
    scorecard = store.new_row("scorecards", fields)
    return response.obj(scorecard, 201)


@bp.get("/scorecards/<scorecard_id>")
def read_scorecard(scorecard_id):
    auth.authenticate(auth.ALL_ROLES)
    return response.obj(common.find("scorecards", scorecard_id), 200)


@bp.get("/scorecards")
def list_scorecards():
    auth.authenticate(auth.ALL_ROLES)
    supplier_id = validate.filter_str("supplier_id")
    variant = validate.filter_enum("variant", VARIANTS)
    rows = []
    for row in db["scorecards"].values():
        if supplier_id is not None and row["supplier_id"] != supplier_id:
            continue
        if variant is not None and row["variant"] != variant:
            continue
        rows.append(row)
    return common.paged(rows, key=lambda r: (r["period_start"], created_key(r)))


@bp.post("/scorecards/<scorecard_id>/finalize")
def finalize(scorecard_id):
    actor = auth.authenticate(("ComplianceOfficer",))
    scorecard = common.find("scorecards", scorecard_id)
    data = validate.body()
    validate.str_opt(data, "note")
    if scorecard["variant"] != "PROVISIONAL":
        raise ApiError("ERR_SCORECARD_ALREADY_FINAL")
    if clock.today().isoformat() <= scorecard["period_end"]:
        raise ApiError("ERR_PERIOD_NOT_CLOSED")
    supplier = db["suppliers"].get(scorecard["supplier_id"])
    scorecard.update(calc.composite_score(supplier, scorecard["period_start"],
                                          scorecard["period_end"], "FINAL"))
    scorecard["variant"] = "FINAL"
    scorecard["finalized_by_user_id"] = actor.user_id
    touch(scorecard)
    return response.obj(scorecard, 200)
