"""Titles and Formats (PRD §3.2)."""
from flask import Blueprint

import db
import errors
from middleware import get_principal, require_publisher, serialize
from response import object_response, array_response
from services import validate
from services.access import can_read_contract
from services.listing import paginate

bp = Blueprint("catalogue", __name__)

FORMAT_TYPES = {"HARDCOVER", "PAPERBACK", "EBOOK", "AUDIO"}


def _read_contract_or_403(cid):
    role, user_id = get_principal()
    contract = db.contracts.get(cid)
    if contract is None:
        raise errors.not_found("Contract not found.")
    if not can_read_contract(role, user_id, contract):
        raise errors.unauthorized()
    return contract


def _read_title_or_403(tid):
    role, user_id = get_principal()
    title = db.titles.get(tid)
    if title is None:
        raise errors.not_found("Title not found.")
    contract = db.contracts.get(title["contract_id"])
    if contract is None or not can_read_contract(role, user_id, contract):
        raise errors.unauthorized()
    return title


# ---- Titles ----

@bp.route("/contracts/<cid>/titles", methods=["POST"])
def create_title(cid):
    role, _ = get_principal()
    require_publisher(role)
    contract = db.contracts.get(cid)
    if contract is None:
        raise errors.not_found("Contract not found.")
    body = validate.get_body()
    name = validate.req_string(body, "name")
    edition = validate.opt_int(body, "edition", 1)
    validate.range_ge(edition, "edition", 1)
    rec = db.make_common({
        "contract_id": cid,
        "name": name,
        "edition": edition,
        "status": "DRAFT",
    })
    db.titles[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/contracts/<cid>/titles", methods=["GET"])
def list_titles(cid):
    contract = _read_contract_or_403(cid)
    records = [t for t in db.titles.values() if t["contract_id"] == contract["id"]]
    limit, offset = validate.pagination()
    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)


@bp.route("/titles/<tid>", methods=["GET"])
def get_title(tid):
    title = _read_title_or_403(tid)
    return object_response(serialize(title))


@bp.route("/titles/<tid>/publish", methods=["POST"])
def publish_title(tid):
    role, _ = get_principal()
    require_publisher(role)
    title = db.titles.get(tid)
    if title is None:
        raise errors.not_found("Title not found.")
    contract = db.contracts.get(title["contract_id"])
    # State: must be DRAFT to publish.
    if title["status"] != "DRAFT":
        raise errors.invalid_state("Only a DRAFT title may be published.")
    if contract is None or contract["status"] != "ACTIVE":
        raise errors.invalid_state("Owning contract must be ACTIVE to publish a title.")
    formats = [f for f in db.formats.values() if f["title_id"] == tid]
    if not formats:
        raise errors.title_has_no_format()
    title["status"] = "PUBLISHED"
    db.touch(title)
    return object_response(serialize(title))


@bp.route("/titles/<tid>/retire", methods=["POST"])
def retire_title(tid):
    role, _ = get_principal()
    require_publisher(role)
    title = db.titles.get(tid)
    if title is None:
        raise errors.not_found("Title not found.")
    contract = db.contracts.get(title["contract_id"])
    if title["status"] != "PUBLISHED":
        raise errors.invalid_state("Only a PUBLISHED title may be retired.")
    if contract is None or contract["status"] != "ACTIVE":
        raise errors.invalid_state("Owning contract must be ACTIVE to retire a title.")
    title["status"] = "OUT_OF_PRINT"
    db.touch(title)
    # Cascade: every Format of this title goes inactive.
    for f in db.formats.values():
        if f["title_id"] == tid and f["active"]:
            f["active"] = False
            db.touch(f)
    return object_response(serialize(title))


# ---- Formats ----

@bp.route("/titles/<tid>/formats", methods=["POST"])
def create_format(tid):
    role, _ = get_principal()
    require_publisher(role)
    title = db.titles.get(tid)
    if title is None:
        raise errors.not_found("Title not found.")
    body = validate.get_body()
    format_type = validate.req_enum(body, "format_type", FORMAT_TYPES)
    list_price_cents = validate.req_int(body, "list_price_cents")
    validate.range_gt(list_price_cents, "list_price_cents", 0)
    rec = db.make_common({
        "title_id": tid,
        "format_type": format_type,
        "list_price_cents": list_price_cents,
        "active": True,
    })
    db.formats[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/titles/<tid>/formats", methods=["GET"])
def list_formats(tid):
    title = _read_title_or_403(tid)
    records = [f for f in db.formats.values() if f["title_id"] == title["id"]]
    limit, offset = validate.pagination()
    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)
