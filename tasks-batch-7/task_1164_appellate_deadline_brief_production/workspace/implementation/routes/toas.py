"""TableOfAuthorities and Citation endpoints (PRD §3.5)."""
from flask import Blueprint, request

from db import STORE, now_iso
from errors import ApiError
from middleware import get_auth, require_roles
from response import success_object, success_list
from services.core import (
    get_body, req_str, req_enum, new_entity, paginate, touch,
    path_brief, path_toa, path_citation, toa_for_brief, recompute_toa_counts,
)

bp = Blueprint("toas", __name__)

ALL = ("CourtAdmin", "Attorney", "CourtClerk", "ParalegalStaff")
AUTHORITY_TYPES = ("CASE", "STATUTE", "RULE", "SECONDARY")


def _normalize(raw):
    """Derive a normalized citation form: collapse whitespace, strip."""
    return " ".join(raw.split())


@bp.get("/appellate/briefs/<bid>/toa")
def get_brief_toa(bid):
    auth = get_auth()
    require_roles(auth, ALL)
    brief = path_brief(bid)
    items = [t for t in STORE.toas.values() if t["brief_id"] == brief["id"]]
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/appellate/toas/<tid>")
def get_toa(tid):
    auth = get_auth()
    require_roles(auth, ALL)
    t = path_toa(tid)
    out = dict(t)
    out.pop("_seq", None)
    return success_object(out)


@bp.post("/appellate/toas/<tid>/citations")
def add_citation(tid):
    auth = get_auth()
    require_roles(auth, ("Attorney", "ParalegalStaff"))
    toa = path_toa(tid)
    body = get_body()
    raw = req_str(body, "raw_text")
    atype = req_enum(body, "authority_type", AUTHORITY_TYPES)
    cit = new_entity({
        "toa_id": toa["id"],
        "raw_text": raw,
        "normalized": _normalize(raw),
        "authority_type": atype,
        "verified": False,
        "verified_at": None,
    })
    STORE.citations[cit["id"]] = cit
    recompute_toa_counts(toa)
    touch(toa)
    out = dict(cit)
    out.pop("_seq", None)
    return success_object(out, 201)


@bp.get("/appellate/toas/<tid>/citations")
def list_citations(tid):
    auth = get_auth()
    require_roles(auth, ALL)
    toa = path_toa(tid)
    items = [c for c in STORE.citations.values() if c["toa_id"] == toa["id"]]
    ver = request.args.get("verified")
    if ver is not None:
        if ver.lower() in ("true", "1"):
            items = [c for c in items if c["verified"]]
        elif ver.lower() in ("false", "0"):
            items = [c for c in items if not c["verified"]]
    atype = request.args.get("authority_type")
    if atype is not None:
        items = [c for c in items if c["authority_type"] == atype]
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.post("/appellate/citations/<cid>/verify")
def verify_citation(cid):
    auth = get_auth()
    require_roles(auth, ("ParalegalStaff", "Attorney"))
    cit = path_citation(cid)
    if cit["verified"]:
        raise ApiError("ERR_INVALID_STATE", "Citation is already verified", 409)
    cit["verified"] = True
    cit["verified_at"] = now_iso()
    touch(cit)
    toa = STORE.toas.get(cit["toa_id"])
    if toa:
        recompute_toa_counts(toa)
        touch(toa)
    out = dict(cit)
    out.pop("_seq", None)
    return success_object(out)
