"""RateCard routes (PRD §3.1). Immutable config — only id + created_at."""
from flask import Blueprint

from db import db, lean_fields
from errors import err
from middleware import get_user_context, require_role
from response import success_object
from serializers import rate_card_out
from services.helpers import get_json_body, require_fields
from services.lookups import get_rate_card

bp = Blueprint("rate_cards", __name__)


def _check_int(body, field):
    v = body[field]
    if not isinstance(v, int) or isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "%s must be an integer" % field)


@bp.route("/rate-cards", methods=["POST"])
def create_rate_card():
    _uid, role = get_user_context()
    require_role(role, {"ProjectManager"})
    body = get_json_body()
    require_fields(body, ["source_locale", "target_locale",
                          "base_rate_cents_per_word", "linguist_rate_cents_per_word"])
    _check_int(body, "base_rate_cents_per_word")
    _check_int(body, "linguist_rate_cents_per_word")
    active = body.get("active", True)
    if not isinstance(active, bool):
        raise err("ERR_INVALID_REQUEST", "active must be a boolean")

    r = lean_fields()
    r.update({
        "source_locale": body["source_locale"],
        "target_locale": body["target_locale"],
        "base_rate_cents_per_word": body["base_rate_cents_per_word"],
        "linguist_rate_cents_per_word": body["linguist_rate_cents_per_word"],
        "active": active,
    })
    db.rate_cards[r["id"]] = r
    return success_object(rate_card_out(r), 201)


@bp.route("/rate-cards/<rid>", methods=["GET"])
def get_rate_card_route(rid):
    _uid, role = get_user_context()
    require_role(role, {"ProjectManager", "AccountsReceivable"})
    r = get_rate_card(rid)
    return success_object(rate_card_out(r), 200)
