"""Episode endpoints — the production pipeline (PRD §3.2, §3.4-§3.7)."""
from flask import Blueprint, request

import errors
import middleware as mw
from clock import clock
from constants import LOUDNESS_TOLERANCE_LUFS
from db import db
from response import array_response, object_response
from routes.common import assert_show_owner, get_or_404
from serialize import serialize, serialize_list
from services import calc, show_state

bp = Blueprint("episodes", __name__)


def _accepted_master_version(episode_id):
    """Return the currently accepted MASTER_AUDIO version for an episode, or None.

    Resolves the MASTER_AUDIO deliverable and its highest accepted version.
    """
    master = None
    for d in db.deliverables.all():
        if d["episode_id"] == episode_id and d["kind"] == "MASTER_AUDIO":
            master = d
            break
    if master is None:
        return None, None
    accepted = [
        v for v in db.asset_versions.all()
        if v["deliverable_id"] == master["id"] and v["status"] == "ACCEPTED"
    ]
    if not accepted:
        return master, None
    accepted.sort(key=lambda v: v["version_no"])
    return master, accepted[-1]


def _deliverable_by_kind(episode_id, kind):
    for d in db.deliverables.all():
        if d["episode_id"] == episode_id and d["kind"] == kind:
            return d
    return None


@bp.post("/episodes")
def create_episode():
    auth = mw.authenticate()
    mw.require_role(auth, {"ShowOwner", "PlatformAdmin"})
    body = mw.get_json_body()
    # existence left-to-right: show then contract
    show_id = mw.require_string(body, "show_id")
    show = get_or_404(db.shows, show_id)
    contract_id = mw.require_string(body, "contract_id")
    contract = get_or_404(db.contracts, contract_id)
    # ownership for ShowOwner
    assert_show_owner(auth, show_id)
    title = mw.require_string(body, "title")
    planned = mw.require_int(body, "planned_track_count")
    if planned < 1:
        raise errors.err(errors.ERR_INVALID_REQUEST, "planned_track_count must be >= 1")
    transcript_requested = mw.optional_bool(body, "transcript_requested", False)
    # posture gate (priority 12) before contract referential rule (priority 20)
    if show["production_posture"] != "ACTIVE":
        raise errors.err(errors.ERR_SHOW_NOT_ACTIVE, "Show is not ACTIVE")
    if contract["status"] != "ACTIVE" or contract["show_id"] != show_id:
        raise errors.err(errors.ERR_CONTRACT_NOT_ACTIVE,
                         "Contract is not ACTIVE or belongs to a different show")
    rec = db.episodes.create({
        "show_id": show_id,
        "contract_id": contract_id,
        "title": title,
        "planned_track_count": planned,
        "raw_track_count": 0,
        "transcript_requested": transcript_requested,
        "recording_ended_at": None,
        "assets_complete_at": None,
        "turnaround_due_utc": None,
        "delivered_late": False,
        "status": "INTAKE",
        "revision_count": 0,
        "published_at": None,
    })
    show_state.recompute_open_episode_count(show)
    show_state.recompute_posture(show)
    return object_response(serialize(rec), status=201)


@bp.get("/episodes")
def list_episodes():
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin", "ShowOwner", "ProducerEng", "AdOps"})
    limit, offset = mw.parse_pagination()
    records = db.episodes.all()
    show_id = request.args.get("show_id")
    contract_id = request.args.get("contract_id")
    status = request.args.get("status")
    if show_id is not None:
        records = [r for r in records if r["show_id"] == show_id]
    if contract_id is not None:
        records = [r for r in records if r["contract_id"] == contract_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if auth.role == "ShowOwner":
        records = [r for r in records if r["show_id"] == auth.user_id]
    page, meta = mw.paginate(records, limit, offset)
    return array_response(serialize_list(page), meta)


@bp.get("/episodes/<rid>")
def get_episode(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin", "ShowOwner", "ProducerEng", "AdOps"})
    rec = get_or_404(db.episodes, rid)
    assert_show_owner(auth, rec["show_id"])
    return object_response(serialize(rec))


@bp.post("/episodes/<rid>/lock-assets")
def lock_assets(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"ProducerEng"})
    rec = get_or_404(db.episodes, rid)
    body = mw.get_json_body()
    raw_track_count = mw.require_int(body, "raw_track_count")
    if raw_track_count < 1:
        raise errors.err(errors.ERR_INVALID_REQUEST, "raw_track_count must be >= 1")
    rec["assets_complete_at"] = clock.now()
    rec["raw_track_count"] = raw_track_count
    db.episodes.touch(rec)
    return object_response(serialize(rec))


@bp.post("/episodes/<rid>/submit-edit")
def submit_edit(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"ProducerEng"})
    rec = get_or_404(db.episodes, rid)
    if rec["status"] != "EDITING":
        raise errors.err(errors.ERR_INVALID_STATE, "Episode is not EDITING")
    if rec["assets_complete_at"] is None:
        raise errors.err(errors.ERR_ASSETS_NOT_LOCKED, "Assets are not locked")
    rec["status"] = "REVIEW"
    db.episodes.touch(rec)
    return object_response(serialize(rec))


@bp.post("/episodes/<rid>/request-revision")
def request_revision(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"ShowOwner"})
    rec = get_or_404(db.episodes, rid)
    assert_show_owner(auth, rec["show_id"])
    if rec["status"] != "REVIEW":
        raise errors.err(errors.ERR_INVALID_STATE, "Episode is not in REVIEW")
    rec["status"] = "EDITING"
    rec["revision_count"] = rec["revision_count"] + 1
    db.episodes.touch(rec)
    return object_response(serialize(rec))


@bp.post("/episodes/<rid>/approve-edit")
def approve_edit(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"ShowOwner"})
    rec = get_or_404(db.episodes, rid)
    assert_show_owner(auth, rec["show_id"])
    # ordering (PRD §3.4): state -> master readiness -> loudness
    if rec["status"] != "REVIEW":
        raise errors.err(errors.ERR_INVALID_STATE, "Episode is not in REVIEW")
    master, accepted = _accepted_master_version(rec["id"])
    if master is None or master["status"] != "READY":
        raise errors.err(errors.ERR_MASTER_NOT_READY, "MASTER_AUDIO deliverable is not READY")
    show = db.shows.get(rec["show_id"])
    if accepted is not None and accepted.get("integrated_loudness_lufs") is not None:
        diff = abs(accepted["integrated_loudness_lufs"] - show["target_loudness_lufs"])
        if diff > LOUDNESS_TOLERANCE_LUFS:
            raise errors.err(errors.ERR_LOUDNESS_OUT_OF_SPEC,
                             "Master loudness out of spec")
    # finalize turnaround (final variant) and delivered_late (PRD §3.6)
    contract = db.contracts.get(rec["contract_id"])
    if rec["assets_complete_at"] is not None and contract is not None:
        final_due = calc.turnaround_due(
            rec["assets_complete_at"], contract["tier"], rec["raw_track_count"])
        rec["turnaround_due_utc"] = final_due
        rec["delivered_late"] = clock.now() > final_due
    rec["status"] = "MASTERED"
    db.episodes.touch(rec)
    # MASTER_AUDIO deliverable -> DELIVERED
    master["status"] = "DELIVERED"
    db.deliverables.touch(master)
    return object_response(serialize(rec))


@bp.post("/episodes/<rid>/schedule")
def schedule_episode(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"ProducerEng"})
    rec = get_or_404(db.episodes, rid)
    if rec["status"] != "MASTERED":
        raise errors.err(errors.ERR_INVALID_STATE, "Episode is not MASTERED")
    if rec["transcript_requested"]:
        transcript = _deliverable_by_kind(rec["id"], "TRANSCRIPT")
        if transcript is None or transcript["status"] != "READY":
            raise errors.err(errors.ERR_TRANSCRIPT_NOT_READY, "TRANSCRIPT deliverable not READY")
    rec["status"] = "SCHEDULED"
    db.episodes.touch(rec)
    return object_response(serialize(rec))


@bp.post("/episodes/<rid>/publish")
def publish_episode(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"ProducerEng"})
    rec = get_or_404(db.episodes, rid)
    # state legality first, then posture gate (PRD §2.8, priority 14)
    if rec["status"] != "SCHEDULED":
        raise errors.err(errors.ERR_INVALID_STATE, "Episode is not SCHEDULED")
    show = db.shows.get(rec["show_id"])
    if show["production_posture"] not in {"ACTIVE", "ON_HOLD"}:
        raise errors.err(errors.ERR_SHOW_SUSPENDED, "Show is SUSPENDED")
    rec["status"] = "PUBLISHED"
    rec["published_at"] = clock.now()
    db.episodes.touch(rec)
    # PER_EPISODE billing (PRD §3.5). Snapshot ordering (§2.9).
    contract = db.contracts.get(rec["contract_id"])
    if contract is not None and contract["engagement_type"] == "PER_EPISODE":
        snapshot = show["lifetime_billed_cents"]
        subtotal, discount, late_fee, total = calc.per_episode_invoice_amounts(
            contract["tier"],
            rec["transcript_requested"],
            rec["raw_track_count"],
            contract["loyalty_discount_pct"],
            rec["delivered_late"],
            snapshot,
        )
        db.invoices.create({
            "show_id": rec["show_id"],
            "episode_id": rec["id"],
            "retainer_cycle_id": None,
            "kind": "PER_EPISODE",
            "subtotal_cents": subtotal,
            "discount_cents": discount,
            "late_fee_cents": late_fee,
            "total_cents": total,
            "status": "ISSUED",
        })
        show["lifetime_billed_cents"] = snapshot + total
        db.shows.touch(show)
    show_state.recompute_open_episode_count(show)
    show_state.recompute_posture(show)
    return object_response(serialize(rec))


@bp.post("/episodes/<rid>/cancel")
def cancel_episode(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"ShowOwner"})
    rec = get_or_404(db.episodes, rid)
    assert_show_owner(auth, rec["show_id"])
    if rec["status"] not in {"INTAKE", "RECORDING", "EDITING", "REVIEW"}:
        raise errors.err(errors.ERR_INVALID_STATE, "Episode cannot be cancelled in this state")
    rec["status"] = "CANCELLED"
    db.episodes.touch(rec)
    # cascade non-terminal sessions -> CANCELLED
    for s in db.sessions.all():
        if s["episode_id"] == rec["id"] and s["status"] in {"BOOKED", "LIVE"}:
            s["status"] = "CANCELLED"
            db.sessions.touch(s)
    show = db.shows.get(rec["show_id"])
    if show is not None:
        show_state.recompute_open_episode_count(show)
    return object_response(serialize(rec))


@bp.post("/episodes/<rid>/archive")
def archive_episode(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin"})
    rec = get_or_404(db.episodes, rid)
    if rec["status"] != "PUBLISHED":
        raise errors.err(errors.ERR_INVALID_STATE, "Episode is not PUBLISHED")
    rec["status"] = "ARCHIVED"
    db.episodes.touch(rec)
    show = db.shows.get(rec["show_id"])
    if show is not None:
        show_state.recompute_open_episode_count(show)
    return object_response(serialize(rec))
