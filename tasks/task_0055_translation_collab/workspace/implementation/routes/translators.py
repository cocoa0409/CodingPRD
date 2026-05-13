from flask import Blueprint, request

from db import store
from errors import err
from middleware import require_roles, require_auth
from response import success, list_response
from services.common import (parse_pagination, serialize_translator, sort_by_created_at,
                              stamp_create, touch)
from services.validation import (AVAIL, DOMAINS, GRADES, require_enum, require_field,
                                  require_string, validate_lang)

bp = Blueprint("translators", __name__)


def _validate_language_pairs(pairs):
    if not isinstance(pairs, list) or not pairs:
        raise err("ERR_VALIDATION_FAILED", "language_pairs must be a non-empty list.")
    out = []
    for p in pairs:
        if not isinstance(p, dict):
            raise err("ERR_VALIDATION_FAILED", "language_pair must be an object.")
        s = validate_lang(require_field(p, "source_lang"))
        t = validate_lang(require_field(p, "target_lang"))
        if s == t:
            raise err("ERR_VALIDATION_FAILED", "source_lang must differ from target_lang in language_pair.")
        out.append({"source_lang": s, "target_lang": t})
    return out


def _validate_domains(domains):
    if not isinstance(domains, list) or not domains:
        raise err("ERR_VALIDATION_FAILED", "domains must be a non-empty list.")
    for d in domains:
        if d not in DOMAINS:
            raise err("ERR_VALIDATION_FAILED", f"domain {d} not allowed.")
    return list(domains)


@bp.post("/translators")
@require_roles("ProjectManager")
def create_translator():
    body = request.get_json(silent=True) or {}
    display_name = require_string(body, "display_name", min_len=1, max_len=100)
    language_pairs = _validate_language_pairs(require_field(body, "language_pairs"))
    domains = _validate_domains(require_field(body, "domains"))
    grade = body.get("grade", "JUNIOR")
    if grade not in GRADES:
        raise err("ERR_VALIDATION_FAILED", "grade invalid.")
    t = {
        "display_name": display_name,
        "language_pairs": language_pairs,
        "domains": domains,
        "grade": grade,
        "test_translation_passed": False,
        "availability_status": "AVAILABLE",
        "workload_segments_open": 0,
        "rolling_quality_score": 100.00,
        "latest_quality_score": 100.00,
    }
    stamp_create(t)
    store.translators[t["id"]] = t
    return success(serialize_translator(t), status=201)


@bp.post("/translators/<id>/pass-test")
@require_roles("ProjectManager")
def pass_test(id):
    t = store.translators.get(id)
    if not t:
        raise err("ERR_NOT_FOUND", "translator not found")
    t["test_translation_passed"] = True
    touch(t)
    return success(serialize_translator(t))


@bp.get("/translators/<id>")
@require_roles("ProjectManager", "Translator")
def get_translator(id):
    t = store.translators.get(id)
    if not t:
        raise err("ERR_NOT_FOUND", "translator not found")
    return success(serialize_translator(t))


@bp.get("/translators")
@require_roles("ProjectManager")
def list_translators():
    limit, offset = parse_pagination(request.args)
    avail = request.args.get("availability_status")
    domain = request.args.get("domain")
    items = list(store.translators.values())
    if avail:
        items = [t for t in items if t["availability_status"] == avail]
    if domain:
        items = [t for t in items if domain in t["domains"]]
    items = sort_by_created_at(items)
    total = len(items)
    sliced = items[offset:offset + limit]
    return list_response([serialize_translator(t) for t in sliced], total, limit, offset)
