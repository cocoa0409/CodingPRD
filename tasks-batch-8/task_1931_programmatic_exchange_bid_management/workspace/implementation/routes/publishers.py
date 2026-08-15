"""Publisher endpoints (PRD §3.1) and the publisher payout-line statement."""

from flask import Blueprint, request

from db import store
from errors import not_found, invalid_state
from middleware import (
    require_roles, ALL_ROLES, ROLE_EXCHANGE_ADMIN,
)
from response import success_object, success_list, paginate
from util import get_body, req_str, opt_enum
from services.core import (
    PAYMENT_TERMS, base_record, touch, serialize_publisher, serialize_line,
    expire_deals_for_publisher, recompute_package_floor, _sorted,
)

bp = Blueprint("publishers", __name__)


@bp.route("/publishers", methods=["POST"])
def create_publisher():
    require_roles([ROLE_EXCHANGE_ADMIN])
    body = get_body()
    name = req_str(body, "name")
    domain = req_str(body, "domain")
    payment_terms = opt_enum(body, "payment_terms", PAYMENT_TERMS)
    if payment_terms is None:
        payment_terms = "SEQUENTIAL_LIABILITY"
    pub = base_record()
    pub.update({
        "name": name,
        "domain": domain,
        "payment_terms": payment_terms,
        "status": "ACTIVE",
        "lifetime_net_micros": 0,
        "accrued_open_micros": 0,
        "paid_out_micros": 0,
        "written_off_micros": 0,
    })
    store.publishers[pub["id"]] = pub
    return success_object(serialize_publisher(pub), 201)


@bp.route("/publishers", methods=["GET"])
def list_publishers():
    require_roles(ALL_ROLES)
    status = request.args.get("status")
    items = list(store.publishers.values())
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, limit, offset, total = paginate(_sorted(items), request.args)
    return success_list([serialize_publisher(p) for p in page], limit, offset, total)


@bp.route("/publishers/<publisherId>", methods=["GET"])
def get_publisher(publisherId):
    require_roles(ALL_ROLES)
    pub = store.publishers.get(publisherId)
    if pub is None:
        raise not_found("Publisher not found")
    # lazy deal-expiry sweep applies to this publisher's deals on read
    expire_deals_for_publisher(publisherId)
    return success_object(serialize_publisher(pub))


@bp.route("/publishers/<publisherId>/suspend", methods=["POST"])
def suspend_publisher(publisherId):
    require_roles([ROLE_EXCHANGE_ADMIN])
    pub = store.publishers.get(publisherId)
    if pub is None:
        raise not_found("Publisher not found")
    if pub["status"] != "ACTIVE":
        raise invalid_state("Publisher is not ACTIVE")
    # Cascade hop 1: publisher -> SUSPENDED.
    pub["status"] = "SUSPENDED"
    touch(pub)
    # Hop 2: every ACTIVE package of this publisher -> PAUSED.
    # Hop 3: every ACTIVE deal on a paused package -> PAUSED. Each cascaded
    # resource gets its own version bump and updated_at refresh (§2.10).
    for pkg in _sorted(store.packages.values()):
        if pkg["publisher_id"] == publisherId and pkg["status"] == "ACTIVE":
            pkg["status"] = "PAUSED"
            touch(pkg)
            for deal in _sorted(store.deals.values()):
                if deal["package_id"] == pkg["id"] and deal["status"] == "ACTIVE":
                    deal["status"] = "PAUSED"
                    touch(deal)
    return success_object(serialize_publisher(pub))


@bp.route("/publishers/<publisherId>/resume", methods=["POST"])
def resume_publisher(publisherId):
    require_roles([ROLE_EXCHANGE_ADMIN])
    pub = store.publishers.get(publisherId)
    if pub is None:
        raise not_found("Publisher not found")
    if pub["status"] != "SUSPENDED":
        raise invalid_state("Publisher is not SUSPENDED")
    pub["status"] = "ACTIVE"
    touch(pub)
    # The cascade resumes PAUSED packages and recomputes their floors; deals
    # deliberately stay PAUSED until individually resumed (§3.1).
    for pkg in _sorted(store.packages.values()):
        if pkg["publisher_id"] == publisherId and pkg["status"] == "PAUSED":
            pkg["status"] = "ACTIVE"
            recompute_package_floor(pkg)
            touch(pkg)
    return success_object(serialize_publisher(pub))


@bp.route("/publishers/<publisherId>/payout-lines", methods=["GET"])
def publisher_payout_lines(publisherId):
    require_roles(ALL_ROLES)
    pub = store.publishers.get(publisherId)
    if pub is None:
        raise not_found("Publisher not found")
    status = request.args.get("status")
    items = [l for l in store.payout_lines.values() if l["publisher_id"] == publisherId]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    page, limit, offset, total = paginate(_sorted(items), request.args)
    return success_list([serialize_line(l) for l in page], limit, offset, total)
