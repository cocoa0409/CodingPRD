"""Bundle CRUD (PRD §3.6). Bundle-enroll lives in routes/enrollments.py."""
from datetime import timedelta

from flask import Blueprint, request

import response
from db import db, new_id
from errors import err
from middleware import authenticate, require_roles
from services.common import (stamp_create, require_field, as_str, as_int,
                             paginate, parse_dt)
from services.serialize import view, view_list

bp = Blueprint("bundles", __name__)

ONE_DAY = timedelta(seconds=86400)


def _body():
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


@bp.route("/bundles", methods=["POST"])
def create_bundle():
    principal = authenticate()
    require_roles(principal, "Instructor")
    body = _body()

    instructor_id = as_str(require_field(body, "instructor_id"), "instructor_id")
    title = as_str(require_field(body, "title"), "title")
    course_ids = require_field(body, "course_ids")
    bundle_price = as_int(require_field(body, "bundle_price_cents"), "bundle_price_cents")
    promo_starts_raw = require_field(body, "promo_starts_at")
    promo_ends_raw = require_field(body, "promo_ends_at")

    if not isinstance(course_ids, list) or not all(isinstance(c, str) for c in course_ids):
        raise err("ERR_INVALID_REQUEST", "course_ids must be a list of course id strings.")
    if bundle_price < 0:
        raise err("ERR_INVALID_REQUEST", "bundle_price_cents must be >= 0.")

    promo_starts = parse_dt(promo_starts_raw)
    promo_ends = parse_dt(promo_ends_raw)
    if not (promo_ends > promo_starts):
        raise err("ERR_INVALID_REQUEST", "promo_ends_at must be strictly after promo_starts_at.")

    # ownership
    if principal.user_id != instructor_id:
        raise err("ERR_FORBIDDEN")
    if instructor_id not in db.instructors:
        raise err("ERR_NOT_FOUND")

    # existence of every member course (left-to-right)
    for cid in course_ids:
        if cid not in db.courses:
            raise err("ERR_NOT_FOUND")

    # ERR_INVALID_BUNDLE: >= 2 distinct PUBLISHED courses owned by issuer,
    # bundle_price strictly < sum of member list prices.
    distinct = list(dict.fromkeys(course_ids))
    if len(distinct) < 2:
        raise err("ERR_INVALID_BUNDLE", "A bundle needs at least 2 distinct courses.")
    members = [db.courses[cid] for cid in distinct]
    for c in members:
        if c["instructor_id"] != instructor_id:
            raise err("ERR_INVALID_BUNDLE", "All member courses must be owned by the issuer.")
        if c["status"] != "PUBLISHED":
            raise err("ERR_INVALID_BUNDLE", "All member courses must be PUBLISHED.")
    sum_list = sum(c["list_price_cents"] for c in members)
    if not (bundle_price < sum_list):
        raise err("ERR_INVALID_BUNDLE", "bundle_price_cents must be < sum of member list prices.")

    # ERR_BUNDLE_PROMO_OVERLAP: strict 1-day buffer from every existing ACTIVE
    # same-instructor bundle sharing >= 1 member course. Closed-with-buffer:
    # collide iff (a_starts < b_ends + 1d) and (b_starts < a_ends + 1d).
    member_set = set(distinct)
    for b in db.bundles.values():
        if (b["status"] == "ACTIVE" and b["instructor_id"] == instructor_id
                and member_set & set(b["course_ids"])):
            b_starts = parse_dt(b["promo_starts_at"])
            b_ends = parse_dt(b["promo_ends_at"])
            if (promo_starts < b_ends + ONE_DAY) and (b_starts < promo_ends + ONE_DAY):
                raise err("ERR_BUNDLE_PROMO_OVERLAP")

    savings = sum_list - bundle_price
    rec = {
        "id": new_id(),
        "instructor_id": instructor_id,
        "title": title,
        "course_ids": distinct,
        "bundle_price_cents": bundle_price,
        "promo_starts_at": promo_starts_raw,
        "promo_ends_at": promo_ends_raw,
        "sum_list_price_cents": sum_list,
        "savings_cents": savings,
        "status": "ACTIVE",
    }
    stamp_create(rec)
    db.bundles[rec["id"]] = rec
    return response.success(view(rec), status=201)


@bp.route("/bundles/<bundle_id>", methods=["GET"])
def get_bundle(bundle_id):
    principal = authenticate()
    require_roles(principal, "Instructor", "Learner", "PlatformAdmin")
    bundle = db.bundles.get(bundle_id)
    if bundle is None:
        raise err("ERR_NOT_FOUND")
    return response.success(view(bundle), status=200)


@bp.route("/bundles", methods=["GET"])
def list_bundles():
    principal = authenticate()
    require_roles(principal, "Instructor", "Learner", "PlatformAdmin")
    args = request.args
    items = list(db.bundles.values())
    instructor_id = args.get("instructor_id")
    status = args.get("status")
    if instructor_id is not None:
        items = [b for b in items if b["instructor_id"] == instructor_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    page, meta = paginate(items, args)
    return response.success(view_list(page), status=200, pagination=meta)
