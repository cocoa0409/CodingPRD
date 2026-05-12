"""Exchange rate endpoint."""

from flask import Blueprint

from db import DB, LOCK
from errors import APIError, ERR_INVALID_REQUEST
from middleware import require_roles
from response import success_object
from services.common import get_body, stamp_create_minimal
from services.serializers import serialize_exchange_rate


bp = Blueprint("exchange_rates", __name__)


@bp.route("/exchange_rates", methods=["POST"])
@require_roles("CustomsOfficer")
def create_exchange_rate():
    body = get_body()
    from_currency = body.get("from_currency")
    to_currency = body.get("to_currency")
    rate_micros = body.get("rate_micros")
    effective_date = body.get("effective_date")

    if not isinstance(from_currency, str):
        raise APIError(ERR_INVALID_REQUEST, "from_currency required", 400)
    if not isinstance(to_currency, str):
        raise APIError(ERR_INVALID_REQUEST, "to_currency required", 400)
    if not isinstance(rate_micros, int) or isinstance(rate_micros, bool):
        raise APIError(ERR_INVALID_REQUEST, "rate_micros must be integer", 400)
    if not isinstance(effective_date, str):
        raise APIError(ERR_INVALID_REQUEST, "effective_date required", 400)

    with LOCK:
        for er in DB.exchange_rates.values():
            if (er["from_currency"] == from_currency
                    and er["to_currency"] == to_currency
                    and er["effective_date"] == effective_date):
                raise APIError(ERR_INVALID_REQUEST,
                               "Duplicate (from_currency, to_currency, effective_date)", 400)
        er = {
            "from_currency": from_currency,
            "to_currency": to_currency,
            "rate_micros": int(rate_micros),
            "effective_date": effective_date,
        }
        stamp_create_minimal(er)
        DB.exchange_rates[er["id"]] = er
        return success_object(serialize_exchange_rate(er), status=201)
