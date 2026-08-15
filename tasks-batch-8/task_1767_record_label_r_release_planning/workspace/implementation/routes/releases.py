"""Releases, asset deliveries, and distributors."""

from flask import Blueprint

from db import db, today
from errors import raise_err
from helpers import (
    get_body, make_entity, touch, serialize, get_or_404, list_page,
    apply_filters, bool_filter, parse_date, days_later, v_str, v_bool,
    v_enum, v_date, v_str_list,
)
from middleware import auth, check_ownership
from response import ok, ok_list
from services.domain import artist_of_contract

bp = Blueprint("releases", __name__)

RELEASE_TYPES = ["SINGLE", "ALBUM"]
CHANNEL_TYPES = ["DSP", "PHYSICAL", "RADIO"]
DELIVERY_NON_TERMINAL = ("QUEUED", "TRANSMITTED", "REJECTED")


def _artist_of_release(release):
    contract = db.contracts.get(release["contract_id"])
    return artist_of_contract(contract) if contract else None


def _label_id_of_release(release):
    artist = _artist_of_release(release)
    return artist["label_id"] if artist else None


# ---------------------------------------------------------------------------
# Releases
# ---------------------------------------------------------------------------

@bp.post("/api/contracts/<cid>/releases")
def create_release(cid):
    auth(["AnRManager"])
    contract = get_or_404(db.contracts, cid)
    body = get_body()
    project_id = v_str(body, "project_id")
    title = v_str(body, "title")
    release_type = v_enum(body, "release_type", RELEASE_TYPES)
    release_date = v_date(body, "release_date")
    track_ids = v_str_list(body, "track_ids", non_empty=True)

    project = db.recording_projects.get(project_id)
    if project is None or project["contract_id"] != cid:
        raise_err("ERR_NOT_FOUND", "project_id does not reference a project of this contract")

    tracks = []
    for tid in track_ids:
        track = db.tracks.get(tid)
        if track is None:
            raise_err("ERR_NOT_FOUND", "track id not found: %s" % tid)
        track_project = db.recording_projects.get(track["project_id"])
        track_contract = track_project["contract_id"] if track_project else None
        track_artist = artist_of_contract(db.contracts.get(track_contract)) if track_contract else None
        if track_artist is None or track_artist["label_id"] != artist_of_contract(contract)["label_id"]:
            raise_err("ERR_NOT_FOUND", "track id references another label: %s" % tid)
        tracks.append((track, track_contract))

    count = len(track_ids)
    valid_count = (count == 1) if release_type == "SINGLE" else (2 <= count <= 30)
    if not valid_count:
        raise_err("ERR_SINGLE_TRACK_COUNT", "Invalid track count for release type %s" % release_type)
    for track, track_contract in tracks:
        if track_contract != cid:
            raise_err("ERR_SINGLE_TRACK_COUNT", "Track does not belong to a project of this contract")
        if track["status"] not in ("MIXED", "MASTERED", "CLEARED"):
            raise_err("ERR_SINGLE_TRACK_COUNT", "Track %s is not MIXED, MASTERED, or CLEARED" % track["id"])

    artist = artist_of_contract(contract)
    if artist["status"] not in ("SIGNED", "ACTIVE"):
        raise_err("ERR_ARTIST_NOT_SIGNABLE", "Artist status %s does not permit a release" % artist["status"])

    release = make_entity({
        "contract_id": cid,
        "project_id": project_id,
        "title": title,
        "release_type": release_type,
        "release_date": release_date,
        "track_ids": list(track_ids),
        "went_live_date": None,
        "asset_status": "DRAFT",
        "distribution_status": "PLANNED",
        "_release_date": parse_date(release_date),
    })
    db.releases[release["id"]] = release
    return ok(serialize(release), code=201)


@bp.get("/api/releases/<rid>")
def get_release(rid):
    uid, role = auth(["LabelAdmin", "AnRManager", "FinanceController", "MarketingManager", "ArtistPortal"])
    release = get_or_404(db.releases, rid)
    artist = _artist_of_release(release)
    check_ownership(role, uid, artist["id"] if artist else None)
    return ok(serialize(release))


@bp.get("/api/contracts/<cid>/releases")
def list_contract_releases(cid):
    uid, role = auth(["LabelAdmin", "AnRManager", "FinanceController", "MarketingManager", "ArtistPortal"])
    contract = get_or_404(db.contracts, cid)
    check_ownership(role, uid, contract["artist_id"])
    items = [r for r in db.releases.values() if r["contract_id"] == cid]
    items = apply_filters(items, [("distribution_status", lambda r: r["distribution_status"])])
    data, pagination = list_page(items)
    return ok_list(data, pagination)


@bp.get("/api/recording-projects/<pid>/releases")
def list_project_releases(pid):
    uid, role = auth(["LabelAdmin", "AnRManager", "FinanceController", "MarketingManager", "ArtistPortal"])
    project = get_or_404(db.recording_projects, pid)
    contract = db.contracts.get(project["contract_id"])
    artist = artist_of_contract(contract) if contract else None
    check_ownership(role, uid, artist["id"] if artist else None)
    items = [r for r in db.releases.values() if r["project_id"] == pid]
    data, pagination = list_page(items)
    return ok_list(data, pagination)


@bp.post("/api/releases/<rid>/assemble")
def assemble_release(rid):
    auth(["AnRManager"])
    release = get_or_404(db.releases, rid)
    get_body()
    if release["asset_status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "Assets may only be assembled from DRAFT")
    if release["distribution_status"] != "PLANNED":
        raise_err("ERR_INVALID_STATE", "Distribution must be PLANNED to assemble")
    for tid in release["track_ids"]:
        track = db.tracks.get(tid)
        if track is None or track["status"] != "CLEARED":
            raise_err("ERR_TRACKS_NOT_CLEARED", "Every member track must be CLEARED")
    release["asset_status"] = "ASSEMBLED"
    touch(release)
    return ok(serialize(release))


@bp.post("/api/releases/<rid>/lock-assets")
def lock_assets(rid):
    auth(["AnRManager"])
    release = get_or_404(db.releases, rid)
    body = get_body()
    if release["asset_status"] != "ASSEMBLED":
        raise_err("ERR_INVALID_STATE", "Only ASSEMBLED assets may be locked")
    if body.get("cover_art_confirmed") is not True:
        raise_err("ERR_COVER_ART_MISSING", "cover_art_confirmed must be true")
    release["asset_status"] = "LOCKED"
    touch(release)
    return ok(serialize(release))


@bp.post("/api/releases/<rid>/schedule")
def schedule_release(rid):
    auth(["MarketingManager"])
    release = get_or_404(db.releases, rid)
    get_body()
    if release["distribution_status"] != "PLANNED":
        raise_err("ERR_INVALID_STATE", "Only a PLANNED release may be scheduled")
    if release["asset_status"] != "LOCKED":
        raise_err("ERR_ASSETS_NOT_LOCKED", "Assets must be LOCKED before scheduling")
    contract = db.contracts.get(release["contract_id"])
    artist = artist_of_contract(contract)
    label = db.labels.get(artist["label_id"])
    earliest = days_later(today(), label["release_lead_days"])
    if release["_release_date"] < earliest:
        raise_err("ERR_RELEASE_LEAD_TIME", "release_date is earlier than the required lead time")
    release["distribution_status"] = "SCHEDULED"
    touch(release)
    return ok(serialize(release))


@bp.post("/api/releases/<rid>/go-live")
def go_live(rid):
    auth(["MarketingManager"])
    release = get_or_404(db.releases, rid)
    get_body()
    if release["distribution_status"] != "DELIVERED":
        raise_err("ERR_INVALID_STATE", "Only a DELIVERED release may go live")
    if today() < release["_release_date"]:
        raise_err("ERR_RELEASE_DATE_NOT_REACHED", "release_date has not been reached")
    release["distribution_status"] = "LIVE"
    release["went_live_date"] = today().isoformat()
    touch(release)
    artist = _artist_of_release(release)
    if artist is not None and artist["status"] == "SIGNED":
        artist["status"] = "ACTIVE"
        touch(artist)
    return ok(serialize(release))


@bp.post("/api/releases/<rid>/takedown")
def takedown(rid):
    auth(["MarketingManager"])
    release = get_or_404(db.releases, rid)
    get_body()
    if release["distribution_status"] != "LIVE":
        raise_err("ERR_INVALID_STATE", "Only a LIVE release may be taken down")
    release["distribution_status"] = "TAKEN_DOWN"
    touch(release)
    return ok(serialize(release))


@bp.post("/api/releases/<rid>/relaunch")
def relaunch(rid):
    auth(["MarketingManager"])
    release = get_or_404(db.releases, rid)
    get_body()
    if release["distribution_status"] != "TAKEN_DOWN":
        raise_err("ERR_INVALID_STATE", "Only a TAKEN_DOWN release may be relaunched")
    release["distribution_status"] = "LIVE"
    touch(release)
    return ok(serialize(release))


@bp.post("/api/releases/<rid>/cancel")
def cancel_release(rid):
    auth(["AnRManager", "LabelAdmin"])
    release = get_or_404(db.releases, rid)
    get_body()
    if release["distribution_status"] not in ("PLANNED", "SCHEDULED", "DELIVERED", "TAKEN_DOWN"):
        raise_err("ERR_INVALID_STATE", "Release in %s cannot be cancelled" % release["distribution_status"])
    for beat in db.beats.values():
        if beat["release_id"] == rid and beat["status"] in ("PLANNED", "READY"):
            beat["status"] = "CANCELLED"
            touch(beat)
    for campaign in db.campaigns.values():
        if campaign["release_id"] == rid and campaign["status"] in ("DRAFT", "ACTIVE", "PAUSED"):
            campaign["status"] = "KILLED"
            touch(campaign)
    for delivery in db.deliveries.values():
        if delivery["release_id"] == rid and delivery["status"] in ("QUEUED", "TRANSMITTED"):
            delivery["status"] = "CANCELLED"
            touch(delivery)
    release["distribution_status"] = "CANCELLED"
    touch(release)
    return ok(serialize(release))


# ---------------------------------------------------------------------------
# Asset deliveries
# ---------------------------------------------------------------------------

@bp.post("/api/releases/<rid>/deliveries")
def create_deliveries(rid):
    auth(["MarketingManager"])
    release = get_or_404(db.releases, rid)
    body = get_body()
    distributor_ids = v_str_list(body, "distributor_ids", non_empty=True)
    label_id = _label_id_of_release(release)
    distributors = []
    for did in distributor_ids:
        distributor = db.distributors.get(did)
        if distributor is None or distributor["label_id"] != label_id:
            raise_err("ERR_NOT_FOUND", "distributor id not found: %s" % did)
        distributors.append(distributor)
    # Duplicate check precedes the activity check; the create is atomic.
    seen = set()
    for distributor in distributors:
        if distributor["id"] in seen:
            raise_err("ERR_DUPLICATE_DELIVERY", "Duplicate distributor in request")
        seen.add(distributor["id"])
        for existing in db.deliveries.values():
            if (existing["release_id"] == rid
                    and existing["distributor_id"] == distributor["id"]
                    and existing["status"] in DELIVERY_NON_TERMINAL):
                raise_err("ERR_DUPLICATE_DELIVERY",
                          "A non-terminal delivery already exists for this distributor")
    for distributor in distributors:
        if not distributor["is_active"]:
            raise_err("ERR_DISTRIBUTOR_INACTIVE", "Distributor is inactive")
    created = []
    for distributor in distributors:
        delivery = make_entity({
            "release_id": rid,
            "distributor_id": distributor["id"],
            "attempt_count": 0,
            "status": "QUEUED",
        })
        db.deliveries[delivery["id"]] = delivery
        created.append(serialize(delivery))
    return ok(created, code=201, response_type="array")


@bp.get("/api/asset-deliveries/<did>")
def get_delivery(did):
    auth(["LabelAdmin", "AnRManager", "MarketingManager"])
    delivery = get_or_404(db.deliveries, did)
    return ok(serialize(delivery))


@bp.get("/api/releases/<rid>/deliveries")
def list_release_deliveries(rid):
    auth(["LabelAdmin", "AnRManager", "MarketingManager"])
    get_or_404(db.releases, rid)
    items = [d for d in db.deliveries.values() if d["release_id"] == rid]
    items = apply_filters(items, [("status", lambda d: d["status"])])
    data, pagination = list_page(items)
    return ok_list(data, pagination)


@bp.get("/api/asset-deliveries")
def list_deliveries():
    auth(["LabelAdmin", "AnRManager", "MarketingManager"])
    items = apply_filters(db.deliveries.values(), [
        ("release_id", lambda d: d["release_id"]),
        ("distributor_id", lambda d: d["distributor_id"]),
        ("status", lambda d: d["status"]),
    ])
    data, pagination = list_page(items)
    return ok_list(data, pagination)


@bp.post("/api/asset-deliveries/<did>/transmit")
def transmit_delivery(did):
    auth(["MarketingManager"])
    delivery = get_or_404(db.deliveries, did)
    get_body()
    if delivery["status"] != "QUEUED":
        raise_err("ERR_INVALID_STATE", "Only a QUEUED delivery may be transmitted")
    release = db.releases.get(delivery["release_id"])
    if release["distribution_status"] != "SCHEDULED":
        raise_err("ERR_INVALID_STATE", "Release must be SCHEDULED to transmit")
    delivery["status"] = "TRANSMITTED"
    delivery["attempt_count"] += 1
    touch(delivery)
    return ok(serialize(delivery))


@bp.post("/api/asset-deliveries/<did>/acknowledge")
def acknowledge_delivery(did):
    auth(["MarketingManager"])
    delivery = get_or_404(db.deliveries, did)
    get_body()
    if delivery["status"] != "TRANSMITTED":
        raise_err("ERR_INVALID_STATE", "Only a TRANSMITTED delivery may be acknowledged")
    delivery["status"] = "ACKNOWLEDGED"
    touch(delivery)
    release = db.releases.get(delivery["release_id"])
    siblings = [d for d in db.deliveries.values()
                if d["release_id"] == release["id"] and d["status"] != "CANCELLED"]
    if (release["distribution_status"] == "SCHEDULED" and len(siblings) > 0
            and all(d["status"] == "ACKNOWLEDGED" for d in siblings)):
        release["distribution_status"] = "DELIVERED"
        touch(release)
    return ok(serialize(delivery))


@bp.post("/api/asset-deliveries/<did>/reject")
def reject_delivery(did):
    auth(["MarketingManager"])
    delivery = get_or_404(db.deliveries, did)
    get_body()
    if delivery["status"] != "TRANSMITTED":
        raise_err("ERR_INVALID_STATE", "Only a TRANSMITTED delivery may be rejected")
    delivery["status"] = "REJECTED"
    touch(delivery)
    return ok(serialize(delivery))


@bp.post("/api/asset-deliveries/<did>/retry")
def retry_delivery(did):
    auth(["MarketingManager"])
    delivery = get_or_404(db.deliveries, did)
    get_body()
    if delivery["status"] != "REJECTED":
        raise_err("ERR_INVALID_STATE", "Only a REJECTED delivery may be retried")
    release = db.releases.get(delivery["release_id"])
    if release["distribution_status"] != "SCHEDULED":
        raise_err("ERR_INVALID_STATE", "Release must be SCHEDULED to retry")
    delivery["status"] = "QUEUED"
    touch(delivery)
    return ok(serialize(delivery))


# ---------------------------------------------------------------------------
# Distributors
# ---------------------------------------------------------------------------

@bp.post("/api/distributors")
def create_distributor():
    auth(["LabelAdmin"])
    body = get_body()
    label_id = v_str(body, "label_id")
    if label_id not in db.labels:
        raise_err("ERR_NOT_FOUND", "label_id does not reference an existing label")
    name = v_str(body, "name")
    channel_type = v_enum(body, "channel_type", CHANNEL_TYPES)
    is_active = v_bool(body, "is_active", required=False)
    distributor = make_entity({
        "label_id": label_id,
        "name": name,
        "channel_type": channel_type,
        "is_active": is_active if is_active is not None else True,
    })
    db.distributors[distributor["id"]] = distributor
    return ok(serialize(distributor), code=201)


@bp.get("/api/distributors/<did>")
def get_distributor(did):
    auth(["LabelAdmin", "AnRManager", "FinanceController", "MarketingManager"])
    distributor = get_or_404(db.distributors, did)
    return ok(serialize(distributor))


@bp.get("/api/distributors")
def list_distributors():
    auth(["LabelAdmin", "AnRManager", "FinanceController", "MarketingManager"])
    items = apply_filters(db.distributors.values(), [
        ("label_id", lambda d: d["label_id"]),
    ])
    items = bool_filter(items, "is_active", lambda d: d["is_active"])
    data, pagination = list_page(items)
    return ok_list(data, pagination)


@bp.patch("/api/distributors/<did>")
def update_distributor(did):
    auth(["LabelAdmin"])
    distributor = get_or_404(db.distributors, did)
    body = get_body()
    is_active = v_bool(body, "is_active")
    distributor["is_active"] = is_active
    touch(distributor)
    return ok(serialize(distributor))
