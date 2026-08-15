"""Banners and BannerRevisions (PRD 3.3)."""
from flask import Blueprint, request

from db import DB
from errors import ApiError
from middleware import auth, client_owner_guard
from response import ok, ok_list
from services import (
    campaign_of_banner,
    get_banner,
    get_campaign,
    get_revision,
    new_record,
    pub,
    sorted_created,
    touch,
)
from util import as_int, as_str, as_version, body, pagination_args, required

bp = Blueprint("banners", __name__, url_prefix="/btaa")

BANNER_READ = ["PlatformAdmin", "Dispatcher", "GroundCrewLead", "ComplianceOfficer", "Client", "Pilot"]
REVISION_READ = ["PlatformAdmin", "Dispatcher", "GroundCrewLead", "ComplianceOfficer", "Client"]


def _list(recs, filters):
    items = sorted_created(recs)
    for key, val in filters.items():
        if val is not None:
            items = [r for r in items if r.get(key) == val]
    limit, offset = pagination_args()
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([pub(r) for r in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Banners
# ---------------------------------------------------------------------------
@bp.post("/campaigns/<cid>/banners")
def create_banner(cid):
    user_id, role = auth(["Client", "PlatformAdmin"])
    camp = get_campaign(cid)
    client_owner_guard(role, user_id, camp["client_id"])
    data = body()
    artwork_hash = as_str(required(data, "artwork_hash"), "artwork_hash")
    text_message = as_str(required(data, "text_message"), "text_message")
    length_ft = as_int(required(data, "banner_length_ft"), "banner_length_ft")
    weight_lbs = as_int(required(data, "banner_weight_lbs"), "banner_weight_lbs")
    rec = new_record()
    rec.update(
        {
            "campaign_id": camp["id"],
            "artwork_hash": artwork_hash,
            "text_message": text_message,
            "banner_length_ft": length_ft,
            "banner_weight_lbs": weight_lbs,
            "current_revision_id": None,
            "status": "DRAFT",
        }
    )
    DB["banners"][rec["id"]] = rec
    return ok(pub(rec), status=201)


@bp.get("/campaigns/<cid>/banners")
def list_banners(cid):
    user_id, role = auth(BANNER_READ)
    camp = get_campaign(cid)
    client_owner_guard(role, user_id, camp["client_id"])
    recs = [b for b in DB["banners"].values() if b["campaign_id"] == camp["id"]]
    return _list(recs, {"status": request.args.get("status")})


@bp.get("/banners/<bid>")
def get_one_banner(bid):
    user_id, role = auth(BANNER_READ)
    b = get_banner(bid)
    camp = campaign_of_banner(b)
    if camp:
        client_owner_guard(role, user_id, camp["client_id"])
    return ok(pub(b))


@bp.post("/banners/<bid>/fabricate")
def fabricate_banner(bid):
    auth(["GroundCrewLead"])
    b = get_banner(bid)
    data = body()
    expected = as_version(
        required(data, "expected_banner_version"), "expected_banner_version"
    )
    if b["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Banner is not in a state permitting fabricate",
        )
    # An active revision must exist (PRD 3.3).
    if not b.get("current_revision_id"):
        raise ApiError(
            "ERR_NO_ACTIVE_REVISION", 409, "Banner has no ACTIVE revision"
        )
    # Banner length must satisfy every route the parent campaign has booked.
    camp = campaign_of_banner(b)
    if camp:
        for s in DB["flight_slots"].values():
            if s["campaign_id"] != camp["id"]:
                continue
            if s["status"] not in ("BOOKED", "SCHEDULED", "WEATHER_HOLD", "FLOWN"):
                continue
            route = DB["routes"].get(s["route_id"])
            if route and b["banner_length_ft"] < route["min_banner_length_ft"]:
                raise ApiError(
                    "ERR_BANNER_TOO_SHORT",
                    409,
                    "banner_length_ft below route minimum",
                )
    # OCC last (PRD 2.10).
    if expected != b["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_banner_version is stale")
    b["status"] = "IN_FABRICATION"
    touch(b)
    return ok(pub(b))


@bp.post("/banners/<bid>/mark_ready")
def mark_ready_banner(bid):
    auth(["GroundCrewLead"])
    b = get_banner(bid)
    if b["status"] != "IN_FABRICATION":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Banner is not in a state permitting mark_ready",
        )
    b["status"] = "READY"
    touch(b)
    return ok(pub(b))


@bp.post("/banners/<bid>/retire")
def retire_banner(bid):
    auth(["GroundCrewLead"])
    b = get_banner(bid)
    if b["status"] != "READY":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Banner is not in a state permitting retire",
        )
    for s in DB["flight_slots"].values():
        if s.get("banner_id") == b["id"] and s["status"] in (
            "BOOKED",
            "SCHEDULED",
            "WEATHER_HOLD",
        ):
            raise ApiError(
                "ERR_BANNER_IN_USE", 409, "Banner is referenced by open FlightSlots"
            )
    b["status"] = "RETIRED"
    touch(b)
    return ok(pub(b))


@bp.get("/banners")
def list_banners_system():
    user_id, role = auth(REVISION_READ)
    recs = list(DB["banners"].values())
    if role == "Client":
        recs = [
            b
            for b in recs
            if (campaign_of_banner(b) or {}).get("client_id") == user_id
        ]
    return _list(
        recs,
        {
            "current_revision_id": request.args.get("current_revision_id"),
            "status": request.args.get("status"),
        },
    )


# ---------------------------------------------------------------------------
# Banner revisions
# ---------------------------------------------------------------------------
@bp.post("/banners/<bid>/revisions")
def propose_revision(bid):
    user_id, role = auth(["Client", "GroundCrewLead"])
    b = get_banner(bid)
    camp = campaign_of_banner(b)
    if camp:
        client_owner_guard(role, user_id, camp["client_id"])
    data = body()
    proposed_text = as_str(required(data, "proposed_text"), "proposed_text")
    proposed_hash = as_str(
        required(data, "proposed_artwork_hash"), "proposed_artwork_hash"
    )
    priors = [r for r in DB["banner_revisions"].values() if r["banner_id"] == b["id"]]
    seq = 1 + max((r["revision_seq"] for r in priors), default=0)
    # supersedes_revision_id points at the previous ACTIVE revision (null first).
    active = next((r for r in priors if r["status"] == "ACTIVE"), None)
    rec = new_record()
    rec.update(
        {
            "banner_id": b["id"],
            "revision_seq": seq,
            "proposed_text": proposed_text,
            "proposed_artwork_hash": proposed_hash,
            "supersedes_revision_id": active["id"] if active else None,
            "status": "PROPOSED",
        }
    )
    DB["banner_revisions"][rec["id"]] = rec
    return ok(pub(rec), status=201)


@bp.get("/banners/<bid>/revisions")
def list_revisions(bid):
    user_id, role = auth(REVISION_READ)
    b = get_banner(bid)
    camp = campaign_of_banner(b)
    if camp:
        client_owner_guard(role, user_id, camp["client_id"])
    recs = [r for r in DB["banner_revisions"].values() if r["banner_id"] == b["id"]]
    return _list(recs, {"status": request.args.get("status")})


@bp.get("/banner_revisions/<rid>")
def get_one_revision(rid):
    user_id, role = auth(REVISION_READ)
    r = get_revision(rid)
    b = DB["banners"].get(r["banner_id"])
    camp = campaign_of_banner(b) if b else None
    if camp:
        client_owner_guard(role, user_id, camp["client_id"])
    return ok(pub(r))


def _revision_owner_check(role, user_id, rev):
    b = DB["banners"].get(rev["banner_id"])
    camp = campaign_of_banner(b) if b else None
    if camp:
        client_owner_guard(role, user_id, camp["client_id"])


@bp.post("/banner_revisions/<rid>/approve")
def approve_revision(rid):
    user_id, role = auth(["Client"])
    rev = get_revision(rid)
    if rev["status"] != "PROPOSED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "BannerRevision is not in a state permitting approve",
        )
    _revision_owner_check(role, user_id, rev)
    # PROPOSED -> APPROVED -> ACTIVE (automatic). Pinned propagation order
    # (PRD 3.3 / banner_revision_refab_trigger):
    #   1) supersede prior ACTIVE revision on the same banner
    #   2) demote banner status IN_FABRICATION/READY -> DRAFT
    #   3) update banner.current_revision_id
    banner = DB["banners"].get(rev["banner_id"])
    prior = None
    if banner:
        prior = next(
            (
                r
                for r in DB["banner_revisions"].values()
                if r["banner_id"] == banner["id"]
                and r["status"] == "ACTIVE"
                and r["id"] != rev["id"]
            ),
            None,
        )
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(prior)
    rev["status"] = "ACTIVE"
    touch(rev)
    if banner:
        if banner["status"] in ("IN_FABRICATION", "READY"):
            banner["status"] = "DRAFT"
        banner["current_revision_id"] = rev["id"]
        # The banner now reflects the message the client most recently approved.
        banner["text_message"] = rev["proposed_text"]
        banner["artwork_hash"] = rev["proposed_artwork_hash"]
        touch(banner)
    return ok(pub(rev))


@bp.post("/banner_revisions/<rid>/reject")
def reject_revision(rid):
    user_id, role = auth(["Client"])
    rev = get_revision(rid)
    if rev["status"] != "PROPOSED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "BannerRevision is not in a state permitting reject",
        )
    _revision_owner_check(role, user_id, rev)
    rev["status"] = "REJECTED"
    touch(rev)
    return ok(pub(rev))


@bp.get("/banner_revisions")
def list_revisions_system():
    user_id, role = auth(REVISION_READ)
    recs = list(DB["banner_revisions"].values())
    if role == "Client":
        kept = []
        for r in recs:
            b = DB["banners"].get(r["banner_id"])
            camp = campaign_of_banner(b) if b else None
            if camp and camp["client_id"] == user_id:
                kept.append(r)
        recs = kept
    return _list(
        recs,
        {
            "supersedes_revision_id": request.args.get("supersedes_revision_id"),
            "banner_id": request.args.get("banner_id"),
            "status": request.args.get("status"),
        },
    )
