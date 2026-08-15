"""Titles and wholesale quotes (PRD §3.2)."""

from flask import Blueprint, request

from db import store, new_entity, pub
from errors import ApiError, ERR_VALIDATION, ERR_QUOTE_WINDOW_OVERLAP
from middleware import (
    require_roles, body, get_str, get_int, get_bool, get_enum, get_dt,
    get_or_404, ALL_ROLES,
)
from response import success, list_response

bp = Blueprint("titles", __name__)

CONDITIONS = ("LIKE_NEW", "GOOD", "ACCEPTABLE")


@bp.post("/bookstore/titles")
def create_title():
    require_roles("PlatformAdmin")
    data = body()
    isbn = get_str(data, "isbn")
    publisher_id = get_str(data, "publisher_id")
    list_price_cents = get_int(data, "list_price_cents", min_val=1)
    has_new = get_bool(data, "has_new")
    has_used = get_bool(data, "has_used")
    has_rental = get_bool(data, "has_rental")
    has_digital = get_bool(data, "has_digital")
    init_new = get_int(data, "initial_new_stock_qty", required=False,
                       default=0, min_val=0)
    init_used = get_int(data, "initial_used_stock_qty", required=False,
                        default=0, min_val=0)
    init_rental = get_int(data, "initial_rental_stock_qty", required=False,
                          default=0, min_val=0)
    get_or_404(store.publishers, publisher_id, "publisher")
    if any(t["isbn"] == isbn for t in store.titles.values()):
        raise ApiError(ERR_VALIDATION, 400, "isbn must be unique")
    title = new_entity()
    title.update({
        "isbn": isbn,
        "publisher_id": publisher_id,
        "list_price_cents": list_price_cents,
        "has_new": has_new,
        "has_used": has_used,
        "has_rental": has_rental,
        "has_digital": has_digital,
        "initial_new_stock_qty": init_new,
        "initial_used_stock_qty": init_used,
        "initial_rental_stock_qty": init_rental,
        "new_stock_qty": init_new,
        "used_stock_qty": init_used,
        "rental_stock_qty": init_rental,
    })
    store.titles[title["id"]] = title
    return success(pub(title), status=201)


@bp.get("/bookstore/titles")
def list_titles():
    require_roles(*ALL_ROLES)
    publisher_id = request.args.get("publisher_id")
    items = [t for t in store.titles.values()
             if publisher_id is None or t["publisher_id"] == publisher_id]
    return list_response(items)


@bp.get("/bookstore/titles/<tid>")
def get_title(tid):
    require_roles(*ALL_ROLES)
    return success(pub(get_or_404(store.titles, tid, "title")))


@bp.post("/bookstore/titles/<tid>/wholesale-quotes")
def create_wholesale_quote(tid):
    require_roles("PlatformAdmin")
    title = get_or_404(store.titles, tid, "title")
    data = body()
    condition = get_enum(data, "condition", CONDITIONS)
    price_cents = get_int(data, "price_cents", min_val=1)
    effective_from = get_dt(data, "effective_from")
    effective_to = get_dt(data, "effective_to")
    if not effective_from < effective_to:
        raise ApiError(ERR_VALIDATION, 400,
                       "effective_from must be before effective_to")
    # half-open overlap; adjacency (from == to) is NOT an overlap
    for ex in store.wholesale_quotes.values():
        if ex["title_id"] != title["id"] or ex["condition"] != condition:
            continue
        if effective_from < ex["effective_to"] and effective_to > ex["effective_from"]:
            raise ApiError(ERR_QUOTE_WINDOW_OVERLAP, 409,
                           "overlapping quote window for (title, condition)")
    q = new_entity()
    q.update({
        "title_id": title["id"],
        "condition": condition,
        "price_cents": price_cents,
        "effective_from": effective_from,
        "effective_to": effective_to,
    })
    store.wholesale_quotes[q["id"]] = q
    return success(pub(q), status=201)


@bp.get("/bookstore/titles/<tid>/wholesale-quotes")
def list_wholesale_quotes(tid):
    require_roles("PlatformAdmin", "BookstoreManager", "Student")
    title = get_or_404(store.titles, tid, "title")
    condition = request.args.get("condition")
    items = [q for q in store.wholesale_quotes.values()
             if q["title_id"] == title["id"]
             and (condition is None or q["condition"] == condition)]
    return list_response(items)
