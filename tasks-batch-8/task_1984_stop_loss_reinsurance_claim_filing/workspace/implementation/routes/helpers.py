"""Shared route helpers: list pagination, filtered reads, role sets (PRD §2.3)."""
from flask import request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST
from middleware import authorized
from response import success_list, success_object
from services.core import public
from validate import require_path_resource

# Read-role sets per the endpoint table (scaffold §1.5).
READ_ALL = ["PlanAdministrator", "StopLossAnalyst", "ClaimsExaminer",
            "PlanAccountant", "CarrierReviewer", "CarrierAuditor"]
READ_LASER = ["PlanAdministrator", "StopLossAnalyst", "CarrierReviewer", "CarrierAuditor"]
READ_FILING = ["PlanAdministrator", "StopLossAnalyst", "PlanAccountant",
               "CarrierReviewer", "CarrierAuditor"]
READ_REIMBURSEMENT = ["PlanAdministrator", "StopLossAnalyst", "PlanAccountant",
                      "CarrierReviewer", "CarrierAuditor"]
READ_FORECAST = ["PlanAdministrator", "StopLossAnalyst", "CarrierReviewer"]
READ_AUDIT = ["PlanAdministrator", "StopLossAnalyst", "PlanAccountant", "CarrierAuditor"]


def get_pagination():
    """limit (default 10, min 1, max 100) and offset (default 0, min 0)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None or limit_raw == "":
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            raise_error(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset_raw is None or offset_raw == "":
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def list_response(collection, roles, filters=None):
    """List with created_at-ascending sort, exact-match query filters, pagination."""
    authorized(roles)
    items = list(db[collection].values())
    if filters:
        for field, value in filters.items():
            if value is None:
                continue
            items = [r for r in items if r.get(field) == value]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


def get_one(collection, rid, roles):
    authorized(roles)
    rec = require_path_resource(collection, rid)
    return success_object(public(rec))
