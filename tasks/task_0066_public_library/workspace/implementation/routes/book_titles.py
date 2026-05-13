"""Book titles + copies routes."""
from flask import Blueprint, request

import db
from errors import err
from response import success, success_list
from middleware import require_auth, get_pagination
from services import validation as V
from services.common import get_book_title, get_copy
from services.aggregates import recompute_title_aggregates
from services.serialize import serialize_book_title, serialize_copy


bp = Blueprint("book_titles", __name__)

ALL_ROLES = {"Reader", "Librarian", "FineOfficer", "ILLCoordinator", "Admin"}


# ---------- BookTitle ----------

@bp.route("/library/book-titles", methods=["POST"])
@require_auth(roles={"Librarian"})
def create_book_title():
    body = V.require_dict(request.get_json(silent=True) or {})
    marc = V.require_marc(V.require_str(body, "marc_control_number"))
    isbn = V.require_isbn13(V.require_str(body, "isbn"))
    title = V.require_str(body, "title")
    author = V.require_str(body, "author")
    publisher = V.require_str(body, "publisher")
    pub_year = V.require_publication_year(V.require_field(body, "publication_year"))
    classification_scheme = V.require_enum(body, "classification_scheme", V.CLASSIFICATION_SCHEMES)
    classification_code = V.require_str(body, "classification_code")
    subject_category = V.require_enum(body, "subject_category", V.SUBJECT_CATEGORIES)
    acquisition_source = V.require_enum(body, "acquisition_source", V.ACQUISITION_SOURCES)

    # Uniqueness checks
    for bt in db.book_titles.values():
        if bt["marc_control_number"] == marc:
            raise err("ERR_INVALID_INPUT", f"marc_control_number {marc} already exists")

    entity = {
        "marc_control_number": marc,
        "isbn": isbn,
        "title": title,
        "author": author,
        "publisher": publisher,
        "publication_year": pub_year,
        "classification_scheme": classification_scheme,
        "classification_code": classification_code,
        "subject_category": subject_category,
        "acquisition_source": acquisition_source,
        "total_copies": 0,
        "available_copies": 0,
        "status": "ACTIVE",
    }
    db.stamp_create(entity)
    db.book_titles[entity["id"]] = entity
    return success(serialize_book_title(entity), status=201)


@bp.route("/library/book-titles", methods=["GET"])
@require_auth(roles=ALL_ROLES)
def list_book_titles():
    limit, offset = get_pagination()
    cls = request.args.get("classification_scheme")
    cat = request.args.get("subject_category")
    search = request.args.get("search")
    items = list(db.book_titles.values())
    if cls:
        items = [b for b in items if b["classification_scheme"] == cls]
    if cat:
        items = [b for b in items if b["subject_category"] == cat]
    if search:
        s = search.lower()
        items = [b for b in items
                 if s in b["title"].lower()
                 or s in b["author"].lower()
                 or s in b["marc_control_number"].lower()
                 or s in b["isbn"].lower()]
    items.sort(key=lambda b: (b["created_at"], b["_seq"]))
    total = len(items)
    sliced = items[offset:offset + limit]
    return success_list([serialize_book_title(b) for b in sliced], limit, offset, total)


@bp.route("/library/book-titles/<bid>", methods=["GET"])
@require_auth(roles=ALL_ROLES)
def get_book_title_endpoint(bid):
    bt = get_book_title(bid)
    return success(serialize_book_title(bt))


# ---------- Copies under a title ----------

@bp.route("/library/book-titles/<bid>/copies", methods=["POST"])
@require_auth(roles={"Librarian"})
def add_copy(bid):
    bt = get_book_title(bid)
    body = V.require_dict(request.get_json(silent=True) or {})
    barcode = V.require_str(body, "barcode")
    location_code = V.require_str(body, "location_code")
    acquisition_source = V.require_enum(body, "acquisition_source", V.ACQUISITION_SOURCES)
    acquired_at = V.require_str(body, "acquired_at")

    if not location_code.strip():
        raise err("ERR_INVALID_INPUT", "location_code must be non-empty")
    for c in db.copies.values():
        if c["barcode"] == barcode:
            raise err("ERR_INVALID_INPUT", f"barcode {barcode} already exists")

    entity = {
        "book_title_id": bt["id"],
        "barcode": barcode,
        "location_code": location_code,
        "acquisition_source": acquisition_source,
        "acquired_at": acquired_at,
        "weeding_reason": None,
        "status": "AVAILABLE",
    }
    db.stamp_create(entity)
    db.copies[entity["id"]] = entity

    recompute_title_aggregates(bt["id"])
    return success(serialize_copy(entity), status=201)


@bp.route("/library/book-titles/<bid>/copies", methods=["GET"])
@require_auth(roles=ALL_ROLES)
def list_copies(bid):
    bt = get_book_title(bid)
    limit, offset = get_pagination()
    status_filter = request.args.get("status")
    items = [c for c in db.copies.values() if c["book_title_id"] == bt["id"]]
    if status_filter:
        items = [c for c in items if c["status"] == status_filter]
    items.sort(key=lambda c: (c["created_at"], c["_seq"]))
    total = len(items)
    sliced = items[offset:offset + limit]
    return success_list([serialize_copy(c) for c in sliced], limit, offset, total)


# ---------- Weed a copy ----------

@bp.route("/library/copies/<cid>/weed", methods=["POST"])
@require_auth(roles={"Librarian"})
def weed_copy(cid):
    copy = get_copy(cid)
    body = V.require_dict(request.get_json(silent=True) or {})
    from services.common import check_version
    check_version(copy, body)

    # State machine: transition only declared from AVAILABLE.
    if copy["status"] == "WEEDED":
        raise err("ERR_INVALID_STATE", "Copy is already WEEDED")
    if copy["status"] != "AVAILABLE":
        raise err("ERR_COPY_NOT_AVAILABLE",
                  f"Copy must be AVAILABLE to be weeded; current status={copy['status']}")

    reason = V.require_enum(body, "weeding_reason", V.WEED_REASONS)

    copy["status"] = "WEEDED"
    copy["weeding_reason"] = reason
    db.stamp_update(copy)
    recompute_title_aggregates(copy["book_title_id"])
    return success(serialize_copy(copy))
