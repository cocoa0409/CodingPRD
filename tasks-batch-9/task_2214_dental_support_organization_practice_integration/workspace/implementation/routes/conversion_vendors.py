"""Conversion vendors: the shared cutover-window capacity ledger (PRD 3.5)."""

from flask import Blueprint

import config
import db
import middleware
import payload
import support

bp = Blueprint("conversion_vendors", __name__)


@bp.post("/conversion-vendors")
@support.transactional
def create_conversion_vendor():
    middleware.authorize([config.ROLE_INTEGRATION_LEAD])
    data = payload.body()
    name = payload.string(data, "name")
    max_concurrent_windows = payload.integer(data, "max_concurrent_windows", minimum=1)
    row = db.insert(
        "conversion_vendors",
        {"name": name, "max_concurrent_windows": max_concurrent_windows},
    )
    return "conversion_vendors", row, 201


@bp.get("/conversion-vendors/<conversion_vendor_id>")
def get_conversion_vendor(conversion_vendor_id):
    middleware.authorize(
        [
            config.ROLE_INTEGRATION_LEAD,
            config.ROLE_DEAL_COUNSEL,
            config.ROLE_FINANCE_CONTROLLER,
        ]
    )
    row = support.load("conversion_vendors", conversion_vendor_id)
    return support.read_one("conversion_vendors", row)
