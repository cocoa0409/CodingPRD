"""Standard endpoints."""
from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import auth
from response import ok, ok_list
from services import get_or_404
from util import as_enum, as_int, as_str, body, paginate, pagination, required, stamp_new

bp = Blueprint("standards", __name__)

DOMAINS = {"LEADERSHIP", "LEARNING", "RESOURCES"}


def standard_view(s):
    return {k: v for k, v in s.items() if not k.startswith("_")}


@bp.post("/accreditation/standards")
def create_standard():
    auth(["AccreditationOfficer"])
    data = body()
    code = as_str(required(data, "code"), "code")
    title = as_str(required(data, "title"), "title")
    domain = as_enum(required(data, "domain"), "domain", DOMAINS)
    weight_pct = as_int(required(data, "weight_pct"), "weight_pct")
    if weight_pct < 1 or weight_pct > 100:
        raise ApiError("ERR_VALIDATION", 400, "weight_pct must be in 1..100")
    evidence_min_items = as_int(required(data, "evidence_min_items"), "evidence_min_items")
    if evidence_min_items < 0:
        raise ApiError("ERR_VALIDATION", 400, "evidence_min_items must be >= 0")
    # Uniqueness on code.
    for s in DB["standards"].values():
        if s["code"] == code:
            raise ApiError("ERR_DUPLICATE_RESOURCE", 409, f"Standard code {code} already exists")
    record = {
        "id": new_id(),
        "code": code,
        "title": title,
        "domain": domain,
        "weight_pct": weight_pct,
        "evidence_min_items": evidence_min_items,
    }
    # Standard carries id and created_at only (PRD 2.4).
    stamp_new(record, with_version=False)
    DB["standards"][record["id"]] = record
    return ok(standard_view(record), status=201)


@bp.get("/accreditation/standards")
def list_standards():
    auth(["AccreditationOfficer", "AccreditationCommission", "SchoolLeader", "Reviewer"])
    limit, offset = pagination()
    rows = sorted(DB["standards"].values(), key=lambda s: s["created_at"])
    domain = request.args.get("domain")
    if domain:
        rows = [r for r in rows if r["domain"] == domain]
    page, total = paginate(rows, limit, offset)
    return ok_list([standard_view(r) for r in page], total, limit, offset)


@bp.get("/accreditation/standards/<id>")
def get_standard(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "SchoolLeader", "Reviewer"])
    row = get_or_404("standards", id, "Standard")
    return ok(standard_view(row))


@bp.get("/accreditation/standards/<id>/ratings")
def list_standard_ratings(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "SchoolLeader"])
    get_or_404("standards", id, "Standard")
    limit, offset = pagination()
    rows = [r for r in DB["ratings"].values() if r["standard_id"] == id]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    from routes.ratings import rating_view
    return ok_list([rating_view(r) for r in page], total, limit, offset)


@bp.get("/accreditation/standards/<id>/goals")
def list_standard_goals(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "SchoolLeader"])
    get_or_404("standards", id, "Standard")
    limit, offset = pagination()
    rows = [g for g in DB["goals"].values() if g["standard_id"] == id]
    rows.sort(key=lambda g: g["created_at"])
    page, total = paginate(rows, limit, offset)
    from routes.goals import goal_view
    return ok_list([goal_view(r) for r in page], total, limit, offset)


@bp.get("/accreditation/standards/<id>/findings")
def list_standard_findings(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "Reviewer"])
    get_or_404("standards", id, "Standard")
    limit, offset = pagination()
    rows = [f for f in DB["findings"].values() if f["standard_id"] == id]
    rows.sort(key=lambda f: f["created_at"])
    page, total = paginate(rows, limit, offset)
    from routes.findings import finding_view
    return ok_list([finding_view(r) for r in page], total, limit, offset)
