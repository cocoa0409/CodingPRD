"""Linguist routes (PRD §3.1, §3.12)."""
from flask import Blueprint, request

from db import db, common_fields, touch
from errors import err
from middleware import get_user_context, require_role
from response import success_object
from serializers import linguist_out, assignment_out, payout_ledger_out
from services.helpers import get_json_body, require_fields, paginate_and_respond
from services.lookups import get_linguist

bp = Blueprint("linguists", __name__)


def _validate_pairs(pairs):
    if not isinstance(pairs, list):
        raise err("ERR_INVALID_REQUEST", "qualified_pairs must be an array")
    for p in pairs:
        if not isinstance(p, dict) or "source_locale" not in p or "target_locale" not in p:
            raise err("ERR_INVALID_REQUEST",
                      "each qualified_pair must have source_locale and target_locale")


@bp.route("/linguists", methods=["POST"])
def create_linguist():
    _uid, role = get_user_context()
    require_role(role, {"ProjectManager"})
    body = get_json_body()
    require_fields(body, ["full_name", "native_locale", "qualified_pairs"])
    _validate_pairs(body["qualified_pairs"])

    can_review = body.get("can_review", False)
    if not isinstance(can_review, bool):
        raise err("ERR_INVALID_REQUEST", "can_review must be a boolean")
    throughput = body.get("daily_throughput_words", 2500)
    if not isinstance(throughput, int) or isinstance(throughput, bool) or throughput < 0:
        raise err("ERR_INVALID_REQUEST", "daily_throughput_words must be a non-negative integer")

    l = common_fields()
    l.update({
        "full_name": body["full_name"],
        "native_locale": body["native_locale"],
        "qualified_pairs": body["qualified_pairs"],
        "can_review": can_review,
        "daily_throughput_words": throughput,
        "committed_payout_cents": 0,
        "status": "ACTIVE",
    })
    db.linguists[l["id"]] = l
    return success_object(linguist_out(l), 201)


@bp.route("/linguists/<lid>", methods=["GET"])
def get_linguist_route(lid):
    uid, role = get_user_context()
    require_role(role, {"ProjectManager", "AccountsReceivable", "Translator", "Reviewer"})
    l = get_linguist(lid)
    if role in ("Translator", "Reviewer") and uid != l["id"]:
        raise err("ERR_FORBIDDEN_FOR_ROLE", "Linguist may only read its own record")
    return success_object(linguist_out(l), 200)


@bp.route("/linguists/<lid>/deactivate", methods=["POST"])
def deactivate_linguist(lid):
    _uid, role = get_user_context()
    require_role(role, {"ProjectManager"})
    l = get_linguist(lid)
    l["status"] = "INACTIVE"
    touch(l)
    return success_object(linguist_out(l), 200)


@bp.route("/linguists/<lid>/assignments", methods=["GET"])
def list_linguist_assignments(lid):
    uid, role = get_user_context()
    require_role(role, {"ProjectManager", "Translator", "Reviewer"})
    l = get_linguist(lid)
    if role in ("Translator", "Reviewer") and uid != l["id"]:
        raise err("ERR_FORBIDDEN_FOR_ROLE", "Linguist may only read its own assignments")
    items = [a for a in db.assignments.values() if a["linguist_id"] == lid]
    status_f = request.args.get("status")
    if status_f is not None:
        items = [a for a in items if a["status"] == status_f]
    return paginate_and_respond(items, assignment_out)


@bp.route("/linguists/<lid>/payout-ledger", methods=["GET"])
def list_linguist_ledger(lid):
    uid, role = get_user_context()
    require_role(role, {"ProjectManager", "Translator", "Reviewer"})
    l = get_linguist(lid)
    if role in ("Translator", "Reviewer") and uid != l["id"]:
        raise err("ERR_FORBIDDEN_FOR_ROLE", "Linguist may only read its own ledger")
    items = [e for e in db.payout_ledger.values() if e["linguist_id"] == lid]
    entry_type_f = request.args.get("entry_type")
    if entry_type_f is not None:
        items = [e for e in items if e["entry_type"] == entry_type_f]
    return paginate_and_respond(items, payout_ledger_out)
