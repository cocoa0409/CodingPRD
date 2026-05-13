"""Acquisition suggestion routes."""
from flask import Blueprint, request, g

import db
from errors import err
from response import success
from middleware import require_auth
from services import validation as V
from services.common import get_suggestion, get_card, check_version
from services.serialize import serialize_suggestion, serialize_book_title


bp = Blueprint("suggestions", __name__)


@bp.route("/library/acquisition-suggestions", methods=["POST"])
@require_auth(roles={"Reader"})
def submit_suggestion():
    body = V.require_dict(request.get_json(silent=True) or {})
    card_id = V.require_str(body, "card_id")
    card = get_card(card_id)
    if g.user_id != card["reader_id"]:
        raise err("ERR_FORBIDDEN",
                  "Reader can submit a suggestion only with their own card")
    isbn = V.require_isbn13(V.require_str(body, "suggested_isbn"), "suggested_isbn")
    title = V.require_str(body, "suggested_title")
    rationale = V.require_str(body, "rationale")

    entity = {
        "reader_id": card["reader_id"],
        "card_id": card["id"],
        "suggested_isbn": isbn,
        "suggested_title": title,
        "rationale": rationale,
        "review_notes": None,
        "decision_book_title_id": None,
        "status": "SUBMITTED",
    }
    db.stamp_create(entity)
    db.acquisition_suggestions[entity["id"]] = entity
    return success(serialize_suggestion(entity), status=201)


@bp.route("/library/acquisition-suggestions/<sid>/start-review", methods=["POST"])
@require_auth(roles={"Librarian"})
def start_review(sid):
    s = get_suggestion(sid)
    body = V.require_dict(request.get_json(silent=True) or {})
    check_version(s, body)
    if s["status"] not in {"SUBMITTED", "DEFERRED"}:
        raise err("ERR_INVALID_STATE",
                  f"Cannot start review from status={s['status']}")
    s["status"] = "UNDER_REVIEW"
    db.stamp_update(s)
    return success(serialize_suggestion(s))


@bp.route("/library/acquisition-suggestions/<sid>/decide", methods=["POST"])
@require_auth(roles={"Librarian"})
def decide_suggestion(sid):
    s = get_suggestion(sid)
    body = V.require_dict(request.get_json(silent=True) or {})
    check_version(s, body)
    if s["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE",
                  f"Cannot decide from status={s['status']}; must be UNDER_REVIEW")

    decision = V.require_enum(body, "decision", V.DECISION_VALUES)
    review_notes = body.get("review_notes")
    if review_notes is not None and not isinstance(review_notes, str):
        raise err("ERR_INVALID_INPUT", "review_notes must be a string")
    s["review_notes"] = review_notes

    if decision == "DECLINE":
        s["status"] = "DECLINED"
        db.stamp_update(s)
        return success(serialize_suggestion(s))

    if decision == "DEFER":
        s["status"] = "DEFERRED"
        db.stamp_update(s)
        return success(serialize_suggestion(s))

    # ACQUIRE: requires a new_book_title payload that matches the suggestion's ISBN
    new_book = body.get("new_book_title")
    if not isinstance(new_book, dict):
        raise err("ERR_INVALID_INPUT",
                  "decision=ACQUIRE requires a new_book_title object")
    marc = V.require_marc(V.require_str(new_book, "marc_control_number"))
    isbn = V.require_isbn13(V.require_str(new_book, "isbn"), "isbn")
    if isbn != s["suggested_isbn"]:
        raise err("ERR_INVALID_INPUT",
                  "new_book_title.isbn must equal suggestion.suggested_isbn")
    classification_scheme = V.require_enum(new_book, "classification_scheme", V.CLASSIFICATION_SCHEMES)
    classification_code = V.require_str(new_book, "classification_code")
    subject_category = V.require_enum(new_book, "subject_category", V.SUBJECT_CATEGORIES)
    acquisition_source = V.require_enum(new_book, "acquisition_source", V.ACQUISITION_SOURCES)
    title_text = new_book.get("title") or s["suggested_title"]
    author = new_book.get("author") or ""
    publisher = new_book.get("publisher") or ""
    publication_year = new_book.get("publication_year")
    if publication_year is None:
        from clock import now
        publication_year = now().year
    publication_year = V.require_publication_year(publication_year)

    # Uniqueness
    for bt in db.book_titles.values():
        if bt["marc_control_number"] == marc:
            raise err("ERR_INVALID_INPUT", f"marc_control_number {marc} already exists")

    bt = {
        "marc_control_number": marc,
        "isbn": isbn,
        "title": title_text,
        "author": author,
        "publisher": publisher,
        "publication_year": publication_year,
        "classification_scheme": classification_scheme,
        "classification_code": classification_code,
        "subject_category": subject_category,
        "acquisition_source": acquisition_source,
        "total_copies": 0,
        "available_copies": 0,
        "status": "ACTIVE",
    }
    db.stamp_create(bt)
    db.book_titles[bt["id"]] = bt

    s["status"] = "ACQUIRED"
    s["decision_book_title_id"] = bt["id"]
    db.stamp_update(s)

    return success(serialize_suggestion(s))


@bp.route("/library/acquisition-suggestions/stats", methods=["GET"])
@require_auth(roles={"Librarian", "Admin"})
def suggestion_stats():
    counts = {"SUBMITTED": 0, "UNDER_REVIEW": 0, "ACQUIRED": 0,
              "DECLINED": 0, "DEFERRED": 0}
    for s in db.acquisition_suggestions.values():
        counts[s["status"]] = counts.get(s["status"], 0) + 1
    total = sum(counts.values())
    ratio = (counts["ACQUIRED"] / total) if total > 0 else 0.0
    return success({
        "counts": counts,
        "total": total,
        "conversion_ratio": ratio,
    })
