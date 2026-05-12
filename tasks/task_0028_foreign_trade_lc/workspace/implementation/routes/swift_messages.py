"""SWIFT message read endpoints."""

from flask import Blueprint, request
import middleware
import response
from services import swift_query

bp = Blueprint("swift_messages", __name__)


@bp.route("/swift-messages/<message_id>", methods=["GET"])
def get_message(message_id):
    middleware.require_auth()
    middleware.require_role("IssuingBank", "AdvisingBank", "ConfirmingBank", "Operator", "Auditor")
    return response.success(swift_query.get_message(message_id))


@bp.route("/letters-of-credit/<lc_id>/swift-messages", methods=["GET"])
def list_lc_messages(lc_id):
    middleware.require_auth()
    middleware.require_role("IssuingBank", "AdvisingBank", "ConfirmingBank", "Operator", "Auditor")
    limit, offset = response.parse_pagination(request.args)
    filters = {}
    if request.args.get("message_type"):
        filters["message_type"] = request.args.get("message_type")
    items, total = swift_query.list_lc_messages(lc_id, filters, limit, offset)
    return response.success_list(items, total, limit, offset)
