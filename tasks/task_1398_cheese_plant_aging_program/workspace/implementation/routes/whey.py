"""Whey stream resources (PRD 3.5)."""

from flask import request

from calc import D, whey_fields
from db import STORES, touch
from errors import ApiError
from helpers import auth, body, f_num, filter_and_page, get_or_404
from response import serialize, success
from routes import make_bp

bp = make_bp("whey_streams")

GET_ROLES = ("PlantAdmin", "Cheesemaker", "QAGrader")


@bp.get("/plant/whey-streams/<wheyStreamId>")
def get_whey(wheyStreamId):
    auth(*GET_ROLES)
    rec = get_or_404("whey_streams", wheyStreamId, "whey stream")
    return success(serialize(rec))


@bp.get("/plant/whey-streams")
def list_whey():
    auth(*GET_ROLES)
    data, pagination = filter_and_page(
        "whey_streams",
        [
            ("plant_id", request.args.get("plant_id")),
            ("make_sheet_id", request.args.get("make_sheet_id")),
        ],
        serialize,
    )
    return success(data, 200, pagination)


@bp.put("/plant/whey-streams/<wheyStreamId>")
def update_whey(wheyStreamId):
    auth("Cheesemaker")
    b = body()
    valorized_kg = f_num(b, "valorized_kg", non_negative=True)
    rec = get_or_404("whey_streams", wheyStreamId, "whey stream")
    # Rung 13: valorization may not exceed total whey (disposed >= 0);
    # valorizing exactly the total, leaving zero disposal, is permitted.
    if D(valorized_kg) > D(rec["total_whey_kg"]):
        raise ApiError(
            "ERR_WHEY_OVER_VALORIZED",
            422,
            "valorized_kg exceeds total_whey_kg (disposed_kg would be negative)",
        )
    disposed, rate = whey_fields(rec["total_whey_kg"], valorized_kg)
    rec["valorized_kg"] = valorized_kg
    rec["disposed_kg"] = disposed
    rec["valorization_rate_pct"] = rate
    touch(rec)
    return success(serialize(rec))
