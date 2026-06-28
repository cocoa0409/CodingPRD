"""Principal endpoints (PRD §3.2). credit_tier derived; indemnity_on_file flag."""

from flask import Blueprint

import errors
from db import db, new_id, now_ts, next_seq
from middleware import require_roles
from response import success
from serializers import serialize_principal
from services.calculations import derive_credit_tier
from helpers import get_body, require_str, require_int

bp = Blueprint("principals", __name__)


@bp.route("/surety/principals", methods=["POST"])
@require_roles("Underwriter", "SeniorUnderwriter")
def create_principal():
    body = get_body()
    legal_name = require_str(body, "legal_name")
    credit_score = require_int(body, "credit_score")
    working_capital_cents = require_int(body, "working_capital_cents")

    # PRD §3.2 / §2.12: credit score must be 300..850 inclusive.
    if credit_score < 300 or credit_score > 850:
        raise errors.invalid_request("credit_score must be an integer in [300, 850]")

    ts = now_ts()
    pid = new_id()
    record = {
        "id": pid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
        "legal_name": legal_name,
        "credit_score": credit_score,
        "working_capital_cents": working_capital_cents,
        "credit_tier": derive_credit_tier(credit_score, working_capital_cents),
        "indemnity_on_file": False,
    }
    db.principals[pid] = record
    return success(serialize_principal(record), status=201)


@bp.route("/surety/principals/<pid>", methods=["GET"])
@require_roles("Underwriter", "SeniorUnderwriter", "ClaimsExaminer")
def get_principal(pid):
    record = db.principals.get(pid)
    if record is None:
        raise errors.not_found("Principal not found")
    return success(serialize_principal(record), status=200)
