from flask import Blueprint

from db import STORE
from middleware import ALL_ROLES, auth_context, require_roles
from response import success
from serializers import licensee_view
from services import get_or_404, new_record
from validators import body_json, req_enum, req_str

bp = Blueprint("licensees", __name__)

LICENSEE_TYPES = ["STREAMING", "LABEL", "SYNC_HOUSE", "OTHER"]


@bp.route("/licensees", methods=["POST"], strict_slashes=False)
def create_licensee():
    uid, role = auth_context()
    require_roles(role, ["PublisherAdmin"])
    body = body_json()
    name = req_str(body, "name")
    licensee_type = req_enum(body, "licensee_type", LICENSEE_TYPES)
    lc = new_record()
    lc.update({"name": name, "licensee_type": licensee_type})
    STORE["licensees"][lc["id"]] = lc
    return success(licensee_view(lc), status=201)


@bp.route("/licensees/<lid>", methods=["GET"], strict_slashes=False)
def get_licensee(lid):
    uid, role = auth_context()
    require_roles(role, ALL_ROLES)
    lc = get_or_404("licensees", lid, "licensee")
    return success(licensee_view(lc))
