"""Quote endpoints: fetch, approve, reject, request-revision."""
from flask import Blueprint

import db
import errors
import response
from middleware import authenticate, require_role
from services import models, validate, calc

bp = Blueprint("quotes", __name__)


def _get_quote(qid):
    q = db.store.quotes.get(qid)
    if q is None:
        raise errors.not_found("Quote not found.")
    return q


@bp.route("/quotes/<qid>", methods=["GET"])
def get_quote(qid):
    uid, role = authenticate()
    require_role(role, {"PlatformAdmin", "Customer", "Mechanic", "Dispatcher"})
    q = _get_quote(qid)
    if role == "Customer":
        sr = db.store.service_requests.get(q["service_request_id"])
        if sr is None or uid != sr["customer_id"]:
            raise errors.not_owner("Customer may only read its own quotes.")
    return response.success(models.serialize(q), 200)


@bp.route("/quotes/<qid>/approve", methods=["POST"])
def approve_quote(qid):
    uid, role = authenticate()
    require_role(role, {"Customer"})
    q = _get_quote(qid)
    sr = db.store.service_requests.get(q["service_request_id"])
    if sr is None:
        raise errors.not_found("Service request not found.")
    # ownership (priority 4)
    if uid != sr["customer_id"]:
        raise errors.not_owner("Customer may only approve its own quotes.")
    # state precondition (priority 5): request QUOTED and quote SENT
    if sr["status"] != "QUOTED" or q["status"] != "SENT":
        raise errors.invalid_state("Quote is not in an approvable state.")
    # structural validation (priority 6): expected_service_request_version required
    body = validate.get_body()
    if "expected_service_request_version" not in body or body["expected_service_request_version"] is None:
        raise errors.invalid_request("expected_service_request_version is required.")
    expected = body["expected_service_request_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.invalid_request("expected_service_request_version must be an integer.")

    fleet_id = sr.get("fleet_account_id")
    fleet = db.store.fleet_accounts.get(fleet_id) if fleet_id else None

    # fleet headroom (priority 12) uses the estimate (quoted_total_cents)
    if fleet is not None:
        if not calc.fleet_headroom_ok(fleet["outstanding_balance_cents"],
                                      q["quoted_total_cents"], fleet["credit_limit_cents"]):
            raise errors.fleet_credit_exceeded()
    # fleet active (priority 13)
    if fleet is not None and fleet["status"] != "ACTIVE":
        raise errors.fleet_account_suspended()
    # OCC (priority 14)
    if expected != sr["version"]:
        raise errors.stale_version()

    q["status"] = "APPROVED"
    models.touch(q, db.store)
    sr["estimate_total_cents"] = q["quoted_total_cents"]
    sr["status"] = "APPROVED"
    models.touch(sr, db.store)
    return response.success(models.serialize(q), 200)


@bp.route("/quotes/<qid>/reject", methods=["POST"])
def reject_quote(qid):
    uid, role = authenticate()
    require_role(role, {"Customer"})
    q = _get_quote(qid)
    sr = db.store.service_requests.get(q["service_request_id"])
    if sr is None:
        raise errors.not_found("Service request not found.")
    if uid != sr["customer_id"]:
        raise errors.not_owner("Customer may only reject its own quotes.")
    if q["status"] != "SENT":
        raise errors.invalid_state("Only a SENT quote may be rejected.")
    q["status"] = "REJECTED"
    models.touch(q, db.store)
    return response.success(models.serialize(q), 200)


@bp.route("/quotes/<qid>/request-revision", methods=["POST"])
def request_revision(qid):
    uid, role = authenticate()
    require_role(role, {"Customer"})
    q = _get_quote(qid)
    sr = db.store.service_requests.get(q["service_request_id"])
    if sr is None:
        raise errors.not_found("Service request not found.")
    if uid != sr["customer_id"]:
        raise errors.not_owner("Customer may only revise its own quotes.")
    if q["status"] != "SENT" or sr["status"] != "QUOTED":
        raise errors.invalid_state("Revision allowed only while quote is SENT and request is QUOTED.")
    q["status"] = "REVISION_REQUESTED"
    models.touch(q, db.store)
    return response.success(models.serialize(q), 200)
