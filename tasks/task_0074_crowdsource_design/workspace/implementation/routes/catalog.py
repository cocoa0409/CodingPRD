"""Design category catalog routes."""
import re

from flask import Blueprint

from common import get_json_body, paginate, stamp_new
from db import db
from errors import api_error
from middleware import require_roles
from response import success


bp = Blueprint("catalog", __name__)


_CODE_RE = re.compile(r"^[A-Z_]+$")


@bp.route("/design-categories", methods=["POST"])
def create_design_category():
    require_roles({"PlatformOps"})
    body = get_json_body()
    code = body.get("code")
    name = body.get("name")
    similarity_corpus_id = body.get("similarity_corpus_id")
    if not isinstance(code, str) or not _CODE_RE.match(code):
        raise api_error("ERR_VALIDATION", "code must be uppercase A-Z and underscore")
    if not isinstance(name, str) or not name:
        raise api_error("ERR_VALIDATION", "name is required")
    if not isinstance(similarity_corpus_id, str) or not similarity_corpus_id:
        raise api_error("ERR_VALIDATION", "similarity_corpus_id is required")
    if code in db.design_categories_by_code:
        raise api_error("ERR_VALIDATION", f"design category code {code} already exists")
    cat = stamp_new({
        "code": code,
        "name": name,
        "similarity_corpus_id": similarity_corpus_id,
    }, with_common=False)
    db.design_categories[cat["id"]] = cat
    db.design_categories_by_code[code] = cat["id"]
    return success(cat, status=201)


@bp.route("/design-categories", methods=["GET"])
def list_design_categories():
    require_roles({"PlatformOps", "Client", "Designer", "Reviewer"})
    items = list(db.design_categories.values())
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)
