"""Author endpoints."""

from flask import Blueprint

from db import db, new_row, touch
from errors import fail
from middleware import ROLE_ADMIN, ROLE_AUTHOR, ROLE_CHAIR, ROLE_PRESS, endpoint
from response import created, ok, ok_list
from routes.helpers import filtered, lookup
from services import derive
from validators import (body_json, paginate, q_bool, q_str, v_bool, v_string)

bp = Blueprint("authors", __name__)


@bp.post("/authors")
@endpoint(ROLE_ADMIN, ROLE_AUTHOR)
def create_author(actor):
    body = body_json()
    full_name = v_string(body, "full_name", required=True, min_len=1, max_len=200)
    email = v_string(body, "email", required=True, min_len=3, max_len=254, lower=True)
    affiliation = v_string(body, "affiliation", default="", min_len=0, max_len=200)
    if affiliation is None:
        affiliation = ""
    for existing in db.authors.values():
        if existing["email"] == email:
            fail("ERR_VALIDATION", "email must be unique across authors.")
    row = new_row({
        "full_name": full_name,
        "email": email,
        "affiliation": affiliation,
        "is_registered": False,
        "registered_at": None,
    })
    db.authors[row["id"]] = row
    return created(derive.author_out(row))


@bp.get("/authors")
@endpoint(ROLE_ADMIN, ROLE_CHAIR, ROLE_PRESS)
def list_authors(actor):
    rows = [r for r in db.authors.values()]
    email = q_str("email")
    is_registered = q_bool("is_registered")
    sanction = q_str("sanction_status")
    out = []
    for row in rows:
        if email is not None and row["email"] != email:
            continue
        if is_registered is not None and row["is_registered"] != is_registered:
            continue
        if sanction is not None and derive.sanction_status(row["id"]) != sanction:
            continue
        out.append(row)
    out = filtered(out, {})
    page, meta = paginate(out)
    return ok_list([derive.author_out(r) for r in page], meta)


@bp.get("/authors/<author_id>")
@endpoint(ROLE_ADMIN, ROLE_CHAIR, ROLE_AUTHOR, ROLE_PRESS)
def get_author(actor, author_id):
    row = lookup("authors", author_id, "ERR_AUTHOR_NOT_FOUND")
    return ok(derive.author_out(row))


@bp.post("/authors/<author_id>/registration")
@endpoint(ROLE_ADMIN, ROLE_AUTHOR)
def set_registration(actor, author_id):
    author = lookup("authors", author_id, "ERR_AUTHOR_NOT_FOUND")
    body = body_json()
    is_registered = v_bool(body, "is_registered", required=True)
    author["is_registered"] = is_registered
    author["registered_at"] = db.now_raw() if is_registered else None
    touch(author)
    return ok(derive.author_out(author))
