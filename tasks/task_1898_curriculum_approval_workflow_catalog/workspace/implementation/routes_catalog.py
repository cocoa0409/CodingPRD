"""Cross-listings, catalog editions, and catalog entries."""

from datetime import timedelta

from flask import Blueprint, request

from db import STORE, new_record, pub, touch
from errors import ApiError
from helpers import (
    check_fields, get_json_body, list_response, parse_date, path_param,
)
from middleware import require_auth
from response import ok

bp = Blueprint("catalog", __name__)

CHAIR = {"DepartmentChair"}
REGISTRAR = {"Registrar"}
NON_TERMINAL_LISTING = ("PENDING", "HOME_APPROVED", "PARTNER_APPROVED", "ACTIVE")


# --- Cross-listings --------------------------------------------------------------

def _derive_side(cl, uid):
    if uid == cl["home_department_id"]:
        return "home"
    if uid == cl["partner_department_id"]:
        return "partner"
    raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "caller chairs neither side of this cross-listing")


@bp.post("/curriculum/cross-listings")
def create_cross_listing():
    uid, _ = require_auth(CHAIR)
    body = get_json_body()
    check_fields(body, {
        "home_course_id": ("str", True),
        "partner_course_id": ("str", True),
    })
    home = STORE["courses"].get(body["home_course_id"])
    if home is None:
        raise ApiError("ERR_VALIDATION", 400, "home_course_id does not reference an existing course")
    partner = STORE["courses"].get(body["partner_course_id"])
    if partner is None:
        raise ApiError("ERR_VALIDATION", 400, "partner_course_id does not reference an existing course")
    if home["id"] == partner["id"]:
        raise ApiError("ERR_VALIDATION", 400, "home and partner courses must differ")
    if home["owning_department_id"] == partner["owning_department_id"]:
        raise ApiError("ERR_VALIDATION", 400, "home and partner courses must belong to different departments")
    if uid != home["owning_department_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "caller does not chair the home course's department")
    if home["status"] != "ACTIVE" or partner["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "both courses must be ACTIVE")
    pair = frozenset((home["id"], partner["id"]))
    for cl in STORE["cross_listings"].values():
        if cl["status"] in NON_TERMINAL_LISTING and frozenset((cl["home_course_id"], cl["partner_course_id"])) == pair:
            raise ApiError("ERR_CROSS_LISTING_EXISTS", 409, "a non-terminal cross-listing already exists for this pair")
    rec = new_record()
    rec.update({
        "home_course_id": home["id"],
        "partner_course_id": partner["id"],
        "home_department_id": home["owning_department_id"],
        "partner_department_id": partner["owning_department_id"],
        "home_approved_by": None,
        "partner_approved_by": None,
        "status": "PENDING",
    })
    STORE["cross_listings"][rec["id"]] = rec
    return ok(pub(rec), 201)


@bp.post("/curriculum/cross-listings/<cid>/approve")
def approve_cross_listing(cid):
    uid, _ = require_auth(CHAIR)
    cl = path_param("cross_listings", cid)
    check_fields(get_json_body(), {})
    side = _derive_side(cl, uid)  # priority 5
    status = cl["status"]
    if status == "PENDING":
        cl["status"] = "HOME_APPROVED" if side == "home" else "PARTNER_APPROVED"
        cl[f"{side}_approved_by"] = uid
    elif status == "HOME_APPROVED" and side == "partner":
        _require_both_active(cl)
        cl["status"] = "ACTIVE"
        cl["partner_approved_by"] = uid
    elif status == "PARTNER_APPROVED" and side == "home":
        _require_both_active(cl)
        cl["status"] = "ACTIVE"
        cl["home_approved_by"] = uid
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "this side cannot approve from the listing's current state")
    touch(cl)
    return ok(pub(cl), 200)


def _require_both_active(cl):
    home = STORE["courses"].get(cl["home_course_id"])
    partner = STORE["courses"].get(cl["partner_course_id"])
    if (
        home is None or partner is None
        or home["status"] != "ACTIVE" or partner["status"] != "ACTIVE"
    ):
        raise ApiError("ERR_INVALID_STATE", 409, "both courses must still be ACTIVE")


@bp.post("/curriculum/cross-listings/<cid>/reject")
def reject_cross_listing(cid):
    uid, _ = require_auth(CHAIR)
    cl = path_param("cross_listings", cid)
    body = get_json_body()
    check_fields(body, {"rationale": ("str", False)})
    _derive_side(cl, uid)
    if cl["status"] not in ("PENDING", "HOME_APPROVED", "PARTNER_APPROVED"):
        raise ApiError("ERR_INVALID_STATE", 409, "listing cannot be rejected from its current state")
    cl["status"] = "REJECTED"
    touch(cl)
    return ok(pub(cl), 200)


@bp.post("/curriculum/cross-listings/<cid>/rescind")
def rescind_cross_listing(cid):
    uid, _ = require_auth(CHAIR)
    cl = path_param("cross_listings", cid)
    check_fields(get_json_body(), {})
    side = _derive_side(cl, uid)
    if cl["status"] == "HOME_APPROVED" and side == "home":
        cl["status"] = "PENDING"
        cl["home_approved_by"] = None
    elif cl["status"] == "PARTNER_APPROVED" and side == "partner":
        cl["status"] = "PENDING"
        cl["partner_approved_by"] = None
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "this side has no approval to rescind")
    touch(cl)
    return ok(pub(cl), 200)


# --- Catalog editions ------------------------------------------------------------

def _edition_window_check(academic_year, start_d, end_d):
    """Closed-interval overlap, day-after contiguity, academic_year uniqueness —
    all among non-ARCHIVED editions, all ERR_EDITION_WINDOW_CONFLICT."""
    live = [e for e in STORE["catalog_editions"].values() if e["status"] != "ARCHIVED"]
    for e in live:
        if e["academic_year"] == academic_year:
            raise ApiError("ERR_EDITION_WINDOW_CONFLICT", 409, "academic_year already used by a non-archived edition")
    for e in live:
        o_start = parse_date(e["year_start_date"])
        o_end = parse_date(e["year_end_date"])
        if start_d <= o_end and end_d >= o_start:  # closed intervals: a shared day conflicts
            raise ApiError("ERR_EDITION_WINDOW_CONFLICT", 409, "edition window overlaps an existing edition")
    if live:
        latest_end = max(parse_date(e["year_end_date"]) for e in live)
        if start_d != latest_end + timedelta(days=1):
            raise ApiError("ERR_EDITION_WINDOW_CONFLICT", 409, "edition must start the day after the latest edition ends")


@bp.post("/curriculum/editions")
def create_edition():
    require_auth(REGISTRAR)
    body = get_json_body()
    check_fields(body, {
        "edition_label": ("str", True),
        "academic_year": ("str", True),
        "year_start_date": ("date", True),
        "year_end_date": ("date", True),
    })
    start_d = parse_date(body["year_start_date"])
    end_d = parse_date(body["year_end_date"])
    if end_d < start_d:
        raise ApiError("ERR_VALIDATION", 400, "year_end_date must be at or after year_start_date")
    _edition_window_check(body["academic_year"], start_d, end_d)
    rec = new_record()
    rec.update({
        "edition_label": body["edition_label"],
        "academic_year": body["academic_year"],
        "year_start_date": body["year_start_date"],
        "year_end_date": body["year_end_date"],
        "included_entry_count": 0,
        "status": "DRAFT",
    })
    STORE["catalog_editions"][rec["id"]] = rec
    return ok(pub(rec), 201)


@bp.post("/curriculum/editions/<eid>/freeze")
def freeze_edition(eid):
    require_auth(REGISTRAR)
    ed = path_param("catalog_editions", eid)
    check_fields(get_json_body(), {})
    if ed["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "edition is not DRAFT")
    for t in STORE["terms"].values():
        if t["academic_year"] == ed["academic_year"] and t["status"] != "CATALOG_FROZEN":
            raise ApiError("ERR_TERM_NOT_LOCKED", 409, "a same-year term is not CATALOG_FROZEN")
    # freeze sweep in entry-creation order
    staged = sorted(
        (e for e in STORE["catalog_entries"].values() if e["edition_id"] == ed["id"] and e["status"] == "STAGED"),
        key=lambda e: e["_seq"],
    )
    for entry in staged:
        course = STORE["courses"].get(entry["course_id"])
        cstatus = course["status"] if course is not None else None
        if cstatus in ("ACTIVE", "DEACTIVATING"):
            entry["status"] = "INCLUDED"
        elif cstatus == "INACTIVE":
            entry["status"] = "EXCLUDED"
        else:
            continue
        touch(entry)
    ed["included_entry_count"] = sum(
        1 for e in STORE["catalog_entries"].values()
        if e["edition_id"] == ed["id"] and e["status"] == "INCLUDED"
    )
    ed["status"] = "FROZEN"
    touch(ed)
    return ok(pub(ed), 200)


@bp.post("/curriculum/editions/<eid>/publish")
def publish_edition(eid):
    require_auth(REGISTRAR)
    ed = path_param("catalog_editions", eid)
    check_fields(get_json_body(), {})
    if ed["status"] != "FROZEN":
        raise ApiError("ERR_INVALID_STATE", 409, "edition is not FROZEN")
    # archive arm: retire the previously PUBLISHED edition and its PUBLISHED entries
    for other in list(STORE["catalog_editions"].values()):
        if other["id"] != ed["id"] and other["status"] == "PUBLISHED":
            other["status"] = "ARCHIVED"
            touch(other)
            for entry in STORE["catalog_entries"].values():
                if entry["edition_id"] == other["id"] and entry["status"] == "PUBLISHED":
                    entry["status"] = "ARCHIVED"
                    touch(entry)
    # publish arm: INCLUDED entries -> PUBLISHED, stamping their courses
    included = sorted(
        (e for e in STORE["catalog_entries"].values() if e["edition_id"] == ed["id"] and e["status"] == "INCLUDED"),
        key=lambda e: e["_seq"],
    )
    for entry in included:
        entry["status"] = "PUBLISHED"
        touch(entry)
        course = STORE["courses"].get(entry["course_id"])
        if course is not None:
            course["last_published_edition_id"] = ed["id"]
            touch(course)
    ed["status"] = "PUBLISHED"
    touch(ed)
    return ok(pub(ed), 200)


# --- Catalog entries -------------------------------------------------------------

_ENTRY_FILTERS = ("edition_id", "course_id", "proposal_id", "status")


@bp.get("/curriculum/catalog-entries")
def list_catalog_entries():
    require_auth()
    records = list(STORE["catalog_entries"].values())
    for f in _ENTRY_FILTERS:
        v = request.args.get(f)
        if v is not None:
            records = [e for e in records if str(e[f]) == v]
    return list_response(records, pub)


@bp.get("/curriculum/catalog-entries/<eid>")
def get_catalog_entry(eid):
    require_auth()
    return ok(pub(path_param("catalog_entries", eid)), 200)
