"""Publishers and publisher agreements (PRD §3.2)."""

from flask import Blueprint

from db import store, new_entity, pub
from errors import ApiError, ERR_VALIDATION, ERR_AGREEMENT_OVERLAP
from middleware import (
    require_roles, body, get_str, get_num, get_date, get_or_404,
)
from response import success, list_response

bp = Blueprint("publishers", __name__)

READ_ROLES = ("PlatformAdmin", "BookstoreManager", "FinanceAdmin")


@bp.post("/bookstore/publishers")
def create_publisher():
    require_roles("PlatformAdmin")
    data = body()
    name = get_str(data, "name")
    if any(p["name"] == name for p in store.publishers.values()):
        raise ApiError(ERR_VALIDATION, 400, "name must be unique")
    pub_rec = new_entity()
    pub_rec.update({"name": name})
    store.publishers[pub_rec["id"]] = pub_rec
    return success(pub(pub_rec), status=201)


@bp.get("/bookstore/publishers")
def list_publishers():
    require_roles(*READ_ROLES)
    return list_response(list(store.publishers.values()))


@bp.get("/bookstore/publishers/<pid>")
def get_publisher(pid):
    require_roles(*READ_ROLES)
    return success(pub(get_or_404(store.publishers, pid, "publisher")))


@bp.post("/bookstore/publishers/<pid>/agreements")
def create_agreement(pid):
    require_roles("PlatformAdmin")
    publisher = get_or_404(store.publishers, pid, "publisher")
    data = body()
    start_date = get_date(data, "start_date")
    end_date = get_date(data, "end_date")
    discount_pct = get_num(data, "discount_pct", lo=0, hi=1)
    digital_discount_pct = get_num(data, "digital_discount_pct", lo=0, hi=1)
    commission_pct = get_num(data, "commission_pct", lo=0, hi=1)
    if start_date > end_date:
        raise ApiError(ERR_VALIDATION, 400, "start_date must be <= end_date")
    # closed-interval overlap; adjacency (start == end) IS an overlap
    for ex in store.agreements.values():
        if ex["publisher_id"] != publisher["id"]:
            continue
        if start_date <= ex["end_date"] and end_date >= ex["start_date"]:
            raise ApiError(ERR_AGREEMENT_OVERLAP, 409,
                           "overlapping agreement for publisher")
    ag = new_entity()
    ag.update({
        "publisher_id": publisher["id"],
        "start_date": start_date,
        "end_date": end_date,
        "discount_pct": discount_pct,
        "digital_discount_pct": digital_discount_pct,
        "commission_pct": commission_pct,
    })
    store.agreements[ag["id"]] = ag
    return success(pub(ag), status=201)


@bp.get("/bookstore/publishers/<pid>/agreements")
def list_agreements(pid):
    require_roles(*READ_ROLES)
    publisher = get_or_404(store.publishers, pid, "publisher")
    items = [a for a in store.agreements.values()
             if a["publisher_id"] == publisher["id"]]
    return list_response(items)
