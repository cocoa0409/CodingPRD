"""Faculty adoptions: create-with-supersede, OCC-guarded edits, the review
loop, and buy-plan creation at approval (PRD §3.4)."""

from flask import Blueprint, request

from db import store, now, new_entity, touch, pub
from errors import (
    ApiError, ERR_VALIDATION, ERR_INVALID_STATE, ERR_NOT_OWNER,
    ERR_STALE_VERSION, ERR_PRICE_POSTING_REQUIRED, ERR_FORMAT_NOT_OFFERED,
    ERR_DUPLICATE_ADOPTION, ERR_NO_ACTIVE_AGREEMENT,
)
from middleware import (
    require_roles, body, get_str, get_int, get_or_404,
)
from response import success, list_response
from services import active_agreement

bp = Blueprint("adoptions", __name__)

ADOPTION_READ_ROLES = ("PlatformAdmin", "BookstoreManager", "Faculty")
QTY_FIELDS = ("qty_new_requested", "qty_used_requested",
              "qty_rental_requested", "qty_digital_requested")
NON_TERMINAL = ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "RETURNED")


@bp.post("/bookstore/adoptions")
def create_adoption():
    uid, _ = require_roles("Faculty")
    data = body()
    section_id = get_str(data, "section_id")
    title_id = get_str(data, "title_id")
    # existence, left to right
    section = get_or_404(store.sections, section_id, "section")
    title = get_or_404(store.titles, title_id, "title")
    # ownership: the acting faculty must own the section (adoption faculty_id
    # is copied from the section)
    if section["faculty_id"] != uid:
        raise ApiError(ERR_NOT_OWNER, 403, "not the section's faculty")
    # OCC (§2.7): expected_section_version pins the section version
    expected = get_int(data, "expected_section_version")
    if expected != section["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "stale section version")
    # field validation
    qtys = {f: get_int(data, f, min_val=0) for f in QTY_FIELDS}
    posted = None
    if "posted_price_cents" in data and data["posted_price_cents"] is not None:
        posted = get_int(data, "posted_price_cents", min_val=0)
    # adopted formats must be offered by the title
    offered = {
        "qty_new_requested": title["has_new"],
        "qty_used_requested": title["has_used"],
        "qty_rental_requested": title["has_rental"],
        "qty_digital_requested": title["has_digital"],
    }
    for f, ok in offered.items():
        if qtys[f] > 0 and not ok:
            raise ApiError(ERR_FORMAT_NOT_OFFERED, 422,
                           "format not offered by title")
    # at most one non-terminal adoption per (section, title)
    for ad in store.adoptions.values():
        if (ad["section_id"] == section["id"]
                and ad["title_id"] == title["id"]
                and ad["status"] in NON_TERMINAL):
            raise ApiError(ERR_DUPLICATE_ADOPTION, 409,
                           "non-terminal adoption exists for (section, title)")
    # supersede cascade: an APPROVED adoption for the same pair is replaced;
    # its still-DRAFT buy plan is cancelled
    for ad in store.adoptions.values():
        if (ad["section_id"] == section["id"]
                and ad["title_id"] == title["id"]
                and ad["status"] == "APPROVED"):
            ad["status"] = "SUPERSEDED"
            touch(ad)
            for plan in store.buy_plans.values():
                if plan["adoption_id"] == ad["id"] and plan["status"] == "DRAFT":
                    plan["status"] = "CANCELLED"
                    touch(plan)
    ad = new_entity()
    ad.update({
        "section_id": section["id"],
        "title_id": title["id"],
        "faculty_id": section["faculty_id"],
        "qty_new_requested": qtys["qty_new_requested"],
        "qty_used_requested": qtys["qty_used_requested"],
        "qty_rental_requested": qtys["qty_rental_requested"],
        "qty_digital_requested": qtys["qty_digital_requested"],
        "posted_price_cents": posted,
        "status": "DRAFT",
        "submitted_at": None,
        "late_flag": False,
        "transparency_late_flag": False,
        "review_note": None,
    })
    store.adoptions[ad["id"]] = ad
    # creation bumps the section's version (why OCC pins it)
    touch(section)
    return success(pub(ad), status=201)


@bp.get("/bookstore/adoptions")
def list_adoptions():
    require_roles(*ADOPTION_READ_ROLES)
    section_id = request.args.get("section_id")
    title_id = request.args.get("title_id")
    faculty_id = request.args.get("faculty_id")
    status = request.args.get("status")
    items = [
        a for a in store.adoptions.values()
        if (section_id is None or a["section_id"] == section_id)
        and (title_id is None or a["title_id"] == title_id)
        and (faculty_id is None or a["faculty_id"] == faculty_id)
        and (status is None or a["status"] == status)
    ]
    return list_response(items)


@bp.get("/bookstore/adoptions/<aid>")
def get_adoption(aid):
    require_roles(*ADOPTION_READ_ROLES)
    return success(pub(get_or_404(store.adoptions, aid, "adoption")))


@bp.patch("/bookstore/adoptions/<aid>")
def patch_adoption(aid):
    uid, _ = require_roles("Faculty")
    ad = get_or_404(store.adoptions, aid, "adoption")
    if ad["faculty_id"] != uid:
        raise ApiError(ERR_NOT_OWNER, 403, "not the adoption owner")
    # from-state: DRAFT edit, or RETURNED revision loop (needs the term back
    # in ADOPTION_OPEN)
    revising = False
    if ad["status"] == "DRAFT":
        pass
    elif ad["status"] == "RETURNED":
        term = store.terms[store.sections[ad["section_id"]]["term_id"]]
        if term["status"] != "ADOPTION_OPEN":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "term not in ADOPTION_OPEN for revision")
        revising = True
    else:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "adoption not editable in its current state")
    data = body()
    # OCC (§2.7): after existence and from-state, before business rules
    expected = get_int(data, "expected_adoption_version")
    if expected != ad["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "stale adoption version")
    for f in QTY_FIELDS:
        if f in data and data[f] is not None:
            ad[f] = get_int(data, f, min_val=0)
    if "posted_price_cents" in data:
        if data["posted_price_cents"] is None:
            ad["posted_price_cents"] = None
        else:
            ad["posted_price_cents"] = get_int(data, "posted_price_cents",
                                               min_val=0)
    if revising:
        ad["status"] = "DRAFT"
        ad["review_note"] = None
        ad["submitted_at"] = None
        ad["late_flag"] = False
        ad["transparency_late_flag"] = False
    touch(ad)
    return success(pub(ad))


@bp.post("/bookstore/adoptions/<aid>/submit")
def submit_adoption(aid):
    uid, _ = require_roles("Faculty")
    ad = get_or_404(store.adoptions, aid, "adoption")
    if ad["faculty_id"] != uid:
        raise ApiError(ERR_NOT_OWNER, 403, "not the adoption owner")
    if ad["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "adoption not in DRAFT")
    term = store.terms[store.sections[ad["section_id"]]["term_id"]]
    if term["status"] != "ADOPTION_OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "term not in ADOPTION_OPEN")
    if ad["posted_price_cents"] is None:
        raise ApiError(ERR_PRICE_POSTING_REQUIRED, 422,
                       "posted_price_cents required before submit")
    n = now()
    ad["submitted_at"] = n
    ad["late_flag"] = n > term["adoption_deadline_at"]
    ad["transparency_late_flag"] = n > term["price_posting_deadline_at"]
    ad["status"] = "SUBMITTED"
    touch(ad)
    return success(pub(ad))


@bp.post("/bookstore/adoptions/<aid>/start-review")
def start_review(aid):
    require_roles("BookstoreManager")
    ad = get_or_404(store.adoptions, aid, "adoption")
    if ad["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "adoption not in SUBMITTED")
    ad["status"] = "UNDER_REVIEW"
    touch(ad)
    return success(pub(ad))


@bp.post("/bookstore/adoptions/<aid>/approve")
def approve_adoption(aid):
    require_roles("BookstoreManager")
    ad = get_or_404(store.adoptions, aid, "adoption")
    if ad["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409, "adoption not in UNDER_REVIEW")
    title = store.titles[ad["title_id"]]
    if active_agreement(title["publisher_id"]) is None:
        raise ApiError(ERR_NO_ACTIVE_AGREEMENT, 422,
                       "no active agreement covers the publisher")
    ad["status"] = "APPROVED"
    touch(ad)
    # approve cascade: exactly one buy plan per adoption, quantities
    # initialized from the adoption's request
    plan = new_entity()
    plan.update({
        "adoption_id": ad["id"],
        "qty_new": ad["qty_new_requested"],
        "qty_used": ad["qty_used_requested"],
        "qty_rental": ad["qty_rental_requested"],
        "qty_digital": ad["qty_digital_requested"],
        "discount_pct_applied": 0,
        "tier_bonus_applied": False,
        "landed_cost_cents": 0,
        "status": "DRAFT",
        "committed_by_user_id": None,
    })
    store.buy_plans[plan["id"]] = plan
    return success(pub(ad))


@bp.post("/bookstore/adoptions/<aid>/return")
def return_adoption(aid):
    require_roles("BookstoreManager")
    ad = get_or_404(store.adoptions, aid, "adoption")
    if ad["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409, "adoption not in UNDER_REVIEW")
    data = body()
    ad["review_note"] = get_str(data, "review_note")
    ad["status"] = "RETURNED"
    touch(ad)
    return success(pub(ad))


@bp.get("/bookstore/adoptions/<aid>/buy-plan")
def get_adoption_buy_plan(aid):
    require_roles("BookstoreManager", "Faculty")
    ad = get_or_404(store.adoptions, aid, "adoption")
    plans = [p for p in store.buy_plans.values() if p["adoption_id"] == ad["id"]]
    return list_response(plans)
