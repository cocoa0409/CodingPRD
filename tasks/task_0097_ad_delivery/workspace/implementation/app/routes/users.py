"""AccountUser CRUD."""
from flask import Blueprint

from .. import store
from ..auth import require_auth
from ..errors import ApiError
from ..pagination import get_pagination, paginate, sort_by_created_asc
from ..response import success
from ..validators import get_json_body, require_fields, require_enum, check_version_if_provided
from ..services.paths import resolve_advertiser, resolve_account_user


bp = Blueprint("account_users", __name__)


ACCOUNT_ROLES = ["OWNER", "CAMPAIGN_MANAGER", "FINANCE", "VIEWER"]


@bp.post("/advertisers/<advertiser_id>/users")
@require_auth(["PlatformAdmin", "AccountOwner"])
def create_user(advertiser_id):
    resolve_advertiser(advertiser_id)
    body = get_json_body()
    require_fields(body, ["external_user_id", "account_role"])
    role = require_enum(body, "account_role", ACCOUNT_ROLES)

    rec = {
        "id": store.gen_uuid(),
        "advertiser_id": advertiser_id,
        "external_user_id": body["external_user_id"],
        "account_role": role,
        "status": "ACTIVE",
    }
    store.stamp_common(rec, with_version=True)
    store.insert("AccountUser", rec)
    return success(rec, status=201)


@bp.get("/advertisers/<advertiser_id>/users")
@require_auth(["PlatformAdmin", "AccountOwner", "CampaignManager", "FinanceOfficer"])
def list_users(advertiser_id):
    resolve_advertiser(advertiser_id)
    limit, offset = get_pagination()
    rows = [u for u in store.list_all("AccountUser") if u.get("advertiser_id") == advertiser_id]
    rows = sort_by_created_asc(rows)
    page, meta = paginate(rows, limit, offset)
    return success(page, pagination=meta)


@bp.patch("/advertisers/<advertiser_id>/users/<user_id>")
@require_auth(["PlatformAdmin", "AccountOwner"])
def patch_user(advertiser_id, user_id):
    _, u = resolve_account_user(advertiser_id, user_id)
    body = get_json_body()
    check_version_if_provided(body, u)

    if "account_role" in body and body["account_role"] is not None:
        require_enum(body, "account_role", ACCOUNT_ROLES)
        u["account_role"] = body["account_role"]
    if "status" in body and body["status"] is not None:
        if body["status"] not in ("ACTIVE", "DISABLED"):
            raise ApiError("ERR_INVALID_REQUEST", "status must be ACTIVE or DISABLED.")
        u["status"] = body["status"]
    store.touch(u)
    return success(u)
