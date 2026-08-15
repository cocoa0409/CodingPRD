from flask import Blueprint

import db
import errors
import middleware as mw
import response as resp
import services

bp = Blueprint("store_visits", __name__)
COLL = "store_visits"

PHOTO_TYPES = {"BEFORE", "AFTER", "POG_LABEL", "FIXTURE", "VOID_AREA"}
EXCEPTION_TYPES = {"OUT_OF_STOCK", "VOID", "FIXTURE_MISSING", "POG_MISSING", "PRICE_MISMATCH"}
SEVERITIES = {"LOW", "MEDIUM", "HIGH"}


def _get_visit_or_404(vid):
    v = db.collections[COLL].get(vid)
    if v is None:
        raise errors.not_found("store visit not found")
    return v


def _visit_chains(v):
    """Resolve (assignment, project_store, project) for a visit."""
    a = db.collections["assignments"].get(v["assignment_id"])
    ps = db.collections["project_stores"].get(a["project_store_id"]) if a else None
    project = services.get_project(a["project_id"]) if a else None
    return a, ps, project


def _check_visit_read_ownership(uid, role, v):
    a, ps, project = _visit_chains(v)
    if role == "FieldRep" and a is not None and a["rep_id"] != uid:
        raise errors.unauthorized("rep acting on another rep's visit")
    if role == "Client" and project is not None and project["client_id"] != uid:
        raise errors.unauthorized("client acting on another client's project")


@bp.get("/store-visits")
def list_store_visits():
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager", "Client", "BillingClerk"})
    items = list(db.collections[COLL].values())
    if role == "Client":
        items = [v for v in items
                 if (services.project_of_assignment(
                     db.collections["assignments"].get(v["assignment_id"])) or {}
                     ).get("client_id") == uid]
    aid = mw.request.args.get("assignment_id")
    if aid is not None:
        items = [v for v in items if v["assignment_id"] == aid]
    vs = mw.request.args.get("verification_status")
    if vs is not None:
        items = [v for v in items if v["verification_status"] == vs]
    rw = mw.request.args.get("is_rework")
    if rw is not None:
        want = rw.strip().lower()
        items = [v for v in items if str(v["is_rework"]).lower() == want]
    items = db.sorted_by_creation(items)
    page, pg = resp.paginate(items)
    return resp.success_list(db.serialize_list(page), pg)


@bp.get("/store-visits/<vid>")
def get_store_visit(vid):
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager", "Client", "BillingClerk", "FieldRep"})
    v = _get_visit_or_404(vid)
    _check_visit_read_ownership(uid, role, v)
    return resp.success_object(db.serialize(v))


@bp.post("/store-visits/<vid>/photos")
def upload_photo(vid):
    uid, role = mw.auth()
    mw.require_role(role, {"FieldRep"})
    v = _get_visit_or_404(vid)
    a, ps, project = _visit_chains(v)
    if a is not None and a["rep_id"] != uid:
        raise errors.unauthorized("rep uploading to another rep's visit")
    # Priority 4: uploads accepted only while the owning assignment is ON_SITE.
    if a is None or a["status"] != "ON_SITE":
        raise errors.invalid_state("visit is frozen; assignment is not ON_SITE")
    # Priority 6: check_in_at <= captured_at <= current logical clock (inclusive, seconds).
    body = mw.get_body()
    captured = mw.parse_dt(body.get("captured_at"))
    if captured is not None:
        check_in = mw.parse_dt(v["check_in_at"])
        cap_s = captured.replace(microsecond=0)
        now_s = db.now().replace(microsecond=0)
        if check_in is not None and cap_s < check_in.replace(microsecond=0):
            raise errors.temporal_invalid("captured_at precedes check_in_at")
        if cap_s > now_s:
            raise errors.temporal_invalid("captured_at is in the future")
    # Priority 13: input sanitization.
    photo_type = mw.req_enum(body, "photo_type", PHOTO_TYPES)
    image_url = mw.req_str(body, "image_url")
    if captured is None:
        raise errors.invalid_request("captured_at is required and must be an ISO 8601 datetime")
    photo = db.light_fields()
    photo.update({
        "store_visit_id": vid,
        "photo_type": photo_type,
        "image_url": image_url,
        "captured_at": body["captured_at"],
    })
    db.collections["photos"][photo["id"]] = photo
    return resp.success_object(db.serialize(photo), 201)


@bp.get("/store-visits/<vid>/photos")
def list_photos(vid):
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager", "Client", "FieldRep"})
    v = _get_visit_or_404(vid)
    _check_visit_read_ownership(uid, role, v)
    items = [p for p in db.collections["photos"].values() if p["store_visit_id"] == vid]
    pt = mw.request.args.get("photo_type")
    if pt is not None:
        items = [p for p in items if p["photo_type"] == pt]
    items = db.sorted_by_creation(items)
    page, pg = resp.paginate(items)
    return resp.success_list(db.serialize_list(page), pg)


@bp.post("/store-visits/<vid>/exceptions")
def file_exception(vid):
    uid, role = mw.auth()
    mw.require_role(role, {"FieldRep", "ProjectManager"})
    v = _get_visit_or_404(vid)
    a, ps, project = _visit_chains(v)
    if role == "FieldRep" and a is not None and a["rep_id"] != uid:
        raise errors.unauthorized("rep filing against another rep's visit")
    body = mw.get_body()
    exception_type = mw.req_enum(body, "exception_type", EXCEPTION_TYPES)
    sku_count = mw.req_int(body, "sku_count", min_val=1)
    severity = mw.req_enum(body, "severity", SEVERITIES)
    exc = db.light_fields()
    exc.update({
        "store_visit_id": vid,
        "exception_type": exception_type,
        "sku_count": sku_count,
        "severity": severity,
        "resolution": "OPEN",
    })
    db.collections["exceptions"][exc["id"]] = exc
    return resp.success_object(db.serialize(exc), 201)


@bp.get("/store-visits/<vid>/exceptions")
def list_visit_exceptions(vid):
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager", "Client", "FieldRep", "BillingClerk"})
    v = _get_visit_or_404(vid)
    _check_visit_read_ownership(uid, role, v)
    items = [e for e in db.collections["exceptions"].values() if e["store_visit_id"] == vid]
    res = mw.request.args.get("resolution")
    if res is not None:
        items = [e for e in items if e["resolution"] == res]
    items = db.sorted_by_creation(items)
    page, pg = resp.paginate(items)
    return resp.success_list(db.serialize_list(page), pg)


def _has_required_photos(visit_id):
    photos = [p for p in db.collections["photos"].values() if p["store_visit_id"] == visit_id]
    return (any(p["photo_type"] == "BEFORE" for p in photos)
            and any(p["photo_type"] == "AFTER" for p in photos))


@bp.post("/store-visits/<vid>/verify")
def verify_visit(vid):
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager"})
    v = _get_visit_or_404(vid)
    a, ps, project = _visit_chains(v)
    # Priority 4: state legality.
    if v["verification_status"] != "PENDING_REVIEW":
        raise errors.invalid_state("visit is not PENDING_REVIEW")
    if a is None or a["status"] != "SUBMITTED":
        raise errors.invalid_state("assignment is not SUBMITTED")
    if not _has_required_photos(vid):
        raise errors.invalid_state("verification requires BEFORE and AFTER photos")
    # Verify: compute billable amount, advance assignment and store row.
    client = services.get_client(project["client_id"]) if project else None
    v["verification_status"] = "VERIFIED"
    v["billable_amount_cents"] = services.compute_visit_billable_cents(v, project, client)
    db.touch(v)
    a["status"] = "VERIFIED"
    db.touch(a)
    if ps is not None and ps["status"] == "IN_PROGRESS":
        ps["status"] = "COMPLETED"
        db.touch(ps)
    if project is not None:
        new_count = services.recompute_completed_store_count(project)
        count_changed = new_count != project["completed_store_count"]
        project["completed_store_count"] = new_count
        if not services.maybe_cascade_reconciling(project) and count_changed:
            db.touch(project)
        services.refresh_open_invoice_total(project["id"])
    return resp.success_object(db.serialize(v))


@bp.post("/store-visits/<vid>/reject")
def reject_visit(vid):
    uid, role = mw.auth()
    mw.require_role(role, {"ProjectManager"})
    v = _get_visit_or_404(vid)
    a, ps, project = _visit_chains(v)
    if v["verification_status"] != "PENDING_REVIEW":
        raise errors.invalid_state("visit is not PENDING_REVIEW")
    if a is None or a["status"] != "SUBMITTED":
        raise errors.invalid_state("assignment is not SUBMITTED")
    v["verification_status"] = "REJECTED"
    db.touch(v)
    a["status"] = "REJECTED"
    db.touch(a)
    if ps is not None and ps["status"] == "IN_PROGRESS":
        ps["status"] = "REWORK_REQUIRED"
        db.touch(ps)
    if project is not None:
        services.add_penalty(project, services.REJECT_PENALTY)
    # Auto-create the rework authorization in REQUESTED.
    ra = db.base_fields()
    ra.update({
        "project_id": a["project_id"],
        "project_store_id": a["project_store_id"],
        "rejected_store_visit_id": v["id"],
        "status": "REQUESTED",
        "reason": None,
    })
    db.collections["rework_auths"][ra["id"]] = ra
    return resp.success_object(db.serialize(v))
