"""ItemVariant endpoints (PRD §3.8)."""
from flask import Blueprint, request

from db import db, next_seq
from errors import (
    raise_error,
    ERR_VARIANT_KIND_MISMATCH,
    ERR_VARIANT_NOT_DRAFT,
    ERR_VARIANT_SOURCE_NOT_READY,
)
from middleware import authorized, ALL_ROLES
from response import success_object
from routes.helpers import public, list_response, get_one
from services.common import touch
from util import new_id, now_ts
from validate import (
    get_body, req_str, req_enum, req_obj, opt_nullable_str,
    require_path_resource, require_body_ref,
)

bp = Blueprint("variants", __name__)

VARIANT_KINDS = ["TRANSLATION", "ACCOMMODATION"]
ACCOMMODATION_CODES = ["LARGE_PRINT", "SCREEN_READER", "BRAILLE", "READ_ALOUD", "EXTENDED_TIME"]


@bp.post("/api/item-variants")
def create_variant():
    caller = authorized(["TranslationSpecialist", "ItemWriter"])
    body = get_body()
    item_id = req_str(body, "item_id")
    variant_kind = req_enum(body, "variant_kind", VARIANT_KINDS)
    language_code = opt_nullable_str(body, "language_code")
    accommodation_code = opt_nullable_str(body, "accommodation_code")
    stimulus_html = req_str(body, "stimulus_html")
    options_json = req_obj(body, "options_json")

    require_body_ref("items", item_id, "item_id")

    if variant_kind == "TRANSLATION":
        lang_ok = (
            isinstance(language_code, str)
            and len(language_code) == 2
            and language_code.isalpha()
        )
        if not lang_ok or accommodation_code is not None:
            raise_error(
                ERR_VARIANT_KIND_MISMATCH,
                "TRANSLATION variants require a two-letter language_code and no accommodation_code",
            )
    else:  # ACCOMMODATION
        if (
            accommodation_code not in ACCOMMODATION_CODES
            or language_code is not None
        ):
            raise_error(
                ERR_VARIANT_KIND_MISMATCH,
                "ACCOMMODATION variants require an accommodation_code and no language_code",
            )

    now = now_ts()
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "item_id": item_id,
        "variant_kind": variant_kind,
        "language_code": language_code if variant_kind == "TRANSLATION" else None,
        "accommodation_code": accommodation_code if variant_kind == "ACCOMMODATION" else None,
        "stimulus_html": stimulus_html,
        "options_json": options_json,
        "status": "DRAFT",
        "_seq": next_seq(),
    }
    db["item_variants"][rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.get("/api/item-variants")
def list_variants():
    authorized(ALL_ROLES)
    filters = {"item_id": request.args.get("item_id")}
    return list_response("item_variants", filters)


@bp.get("/api/item-variants/<vid>")
def get_variant(vid):
    authorized(ALL_ROLES)
    rec = require_path_resource("item_variants", vid)
    return get_one(rec)


@bp.post("/api/item-variants/<vid>/approve")
def approve_variant(vid):
    caller = authorized(["ContentReviewer"])
    rec = require_path_resource("item_variants", vid)
    get_body()
    if rec["status"] != "DRAFT":
        raise_error(ERR_VARIANT_NOT_DRAFT, "variant must be DRAFT to approve")
    item = db["items"].get(rec["item_id"])
    if item is None or item["status"] not in ("OPERATIONAL", "FIELD_TESTING", "STATS_REVIEW"):
        raise_error(ERR_VARIANT_SOURCE_NOT_READY, "source item is not OPERATIONAL/FIELD_TESTING/STATS_REVIEW")
    rec["status"] = "APPROVED"
    touch(rec)
    return success_object(public(rec))


@bp.post("/api/item-variants/<vid>/reject")
def reject_variant(vid):
    caller = authorized(["ContentReviewer"])
    rec = require_path_resource("item_variants", vid)
    get_body()
    if rec["status"] != "DRAFT":
        raise_error(ERR_VARIANT_NOT_DRAFT, "variant must be DRAFT to reject")
    rec["status"] = "REJECTED"
    touch(rec)
    return success_object(public(rec))
