"""Contestant and consent routes."""

from flask import Blueprint, request

from db import DB, new_id, now_ts
from errors import err_not_found, err_not_owner, err_validation
from middleware import require_roles
from response import success
from services.helpers import body_json, req_str, req_date, opt_list, req_bool, req_enum
from services.serializers import contestant_view, judge_view, paginate

bp = Blueprint("contestants", __name__)

CONSENT_SCOPES = {"PHOTOGRAPHY", "VIDEO", "LIVESTREAM"}


@bp.route("/contestants", methods=["POST"])
def create_contestant():
    # The one endpoint open to Anonymous. Any authenticated role may also call it.
    require_roles("Anonymous", "Contestant", "ContestLead", "Judge",
                  "SafetyOfficer", "StageManager", "Treasurer")
    body = body_json()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    birth_date = req_date(body, "birth_date")
    accessibility = opt_list(body, "accessibility_needs", default=[])

    if any(c["email"] == email for c in DB.contestants.values()):
        raise err_validation("email must be unique across contestants")

    ts = now_ts()
    contestant = {
        "id": new_id(),
        "full_name": full_name,
        "email": email,
        "birth_date": birth_date,
        "accessibility_needs": accessibility,
        "consents": [],
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB.contestants[contestant["id"]] = contestant
    return success(contestant_view(contestant), status=201)


@bp.route("/contestants/<cid>", methods=["GET"])
def get_contestant(cid):
    user_id, role = require_roles("Contestant", "ContestLead")
    contestant = DB.contestants.get(cid)
    if contestant is None:
        raise err_not_found("Contestant not found")
    if role == "Contestant" and user_id != cid:
        raise err_not_owner("Contestant may only read own profile")
    return success(contestant_view(contestant))


@bp.route("/contestants/<cid>/consents", methods=["POST"])
def upsert_consent(cid):
    user_id, _ = require_roles("Contestant")
    body = body_json()
    scope = req_enum(body, "scope", CONSENT_SCOPES)
    granted = req_bool(body, "granted")

    contestant = DB.contestants.get(cid)
    if contestant is None:
        raise err_not_found("Contestant not found")
    if user_id != cid:
        raise err_not_owner("Contestant may only manage own consents")

    status = "GRANTED" if granted else "REVOKED"
    ts = now_ts()
    for item in contestant["consents"]:
        if item["scope"] == scope:
            item["status"] = status
            item["updated_at"] = ts
            break
    else:
        contestant["consents"].append({
            "scope": scope,
            "status": status,
            "updated_at": ts,
        })
    contestant["updated_at"] = ts
    contestant["version"] += 1
    return success(contestant_view(contestant))


@bp.route("/contestants/<cid>/judges", methods=["GET"])
def list_linked_judges(cid):
    require_roles("ContestLead")
    contestant = DB.contestants.get(cid)
    if contestant is None:
        raise err_not_found("Contestant not found")
    items = [j for j in DB.judges.values() if j.get("linked_contestant_id") == cid]
    items.sort(key=lambda j: j["created_at"])
    page, pag = paginate([judge_view(j) for j in items], request.args)
    return success(page, response_type="array", pagination=pag)
