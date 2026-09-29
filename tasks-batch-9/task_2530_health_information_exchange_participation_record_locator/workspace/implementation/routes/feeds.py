"""Data feed provisioning, quality samples and feed status (PRD 3.9)."""
from decimal import Decimal

from flask import Blueprint, request

from db import commit, create, db, parse_iso, snapshot, touch
from errors import ApiError
from middleware import HIE_ADMIN, PARTICIPANT_ADMIN, authenticate, require_scope
from response import entity, entity_created, paginate, pagination
from services import cascades, repo, scorecard
from services.precision import dec, out, rhu4
from services.scorecard import FEED_DEGRADED_REJECT_RATE
from validate import body, before, req_dt, req_enum, req_int, req_str

bp = Blueprint("feeds", __name__)

FEED_TYPES = ("ADT", "CCDA", "LAB_RESULT")
FEED_STATUSES = ("PROVISIONING", "MONITORED", "DEGRADED", "SUSPENDED", "RETIRED")
SUPERSEDABLE = ("PROVISIONING", "MONITORED", "DEGRADED", "SUSPENDED")
FEED_ACTIONS = ("SUSPEND", "RESTORE")
REJECT_RATE_BREACH = "REJECT_RATE_BREACH"


def _refresh_latest_reject_rate(feed):
    samples = repo.feed_samples(feed["id"])
    if not samples:
        feed["latest_reject_rate"] = None
        return
    ordered = sorted(samples, key=lambda s: (s["created_at"], s["_seq"]))
    ordered.sort(key=lambda s: parse_iso(s["period_end"]), reverse=True)
    feed["latest_reject_rate"] = ordered[0]["reject_rate"]


@bp.route("/hie/participants/<pid>/data-feeds", methods=["POST"])
def provision_feed(pid):
    actor = authenticate((HIE_ADMIN, PARTICIPANT_ADMIN))
    require_scope(actor, pid)
    payload = body()
    feed_type = req_enum(payload, "feed_type", FEED_TYPES)
    expected = req_int(payload, "expected_participant_version")

    participant = repo.must("participants", pid)
    if expected != int(participant["version"]):
        raise ApiError("ERR_STALE_PARTICIPANT_VERSION")
    if repo.has_delinquent_invoice(participant["id"]):
        raise ApiError("ERR_PARTICIPATION_FEE_DELINQUENT")

    siblings = [
        f
        for f in repo.participant_feeds(pid)
        if f["feed_type"] == feed_type
    ]
    generation = 1 + max([int(f["generation"] or 0) for f in siblings] or [0])

    row = create(
        db.data_feeds,
        "DataFeed",
        {
            "participant_id": pid,
            "feed_type": feed_type,
            "generation": generation,
            "status": "PROVISIONING",
            "latest_reject_rate": None,
            "sample_count": 0,
            "status_reason": None,
        },
    )
    for incumbent in siblings:
        if incumbent["status"] not in SUPERSEDABLE:
            continue
        snap = snapshot(incumbent)
        incumbent["status"] = "RETIRED"
        incumbent["status_reason"] = cascades.SUPERSEDED_BY_GENERATION
        commit(incumbent, snap)

    scorecard.apply_to_participant(participant)
    touch(participant)
    return entity_created(row)


@bp.route("/hie/data-feeds/<fid>/quality-samples", methods=["POST"])
def record_sample(fid):
    authenticate((HIE_ADMIN,))
    payload = body()
    start_raw, start_dt = req_dt(payload, "period_start")
    end_raw, end_dt = req_dt(payload, "period_end")
    before(start_dt, end_dt, "period_end must be strictly after period_start.")
    received = req_int(payload, "messages_received", minimum=0)
    rejected = req_int(payload, "messages_rejected", minimum=0, maximum=received)
    missing = req_int(payload, "required_fields_missing_count", minimum=0)
    duplicates = req_int(payload, "duplicate_count", minimum=0)
    p95 = req_int(payload, "timeliness_p95_seconds", minimum=0)

    feed = repo.must("data_feeds", fid)
    if feed["status"] == "RETIRED":
        raise ApiError("ERR_TERMINAL_STATE")

    if rejected + missing > received:
        raise ApiError("ERR_QUALITY_SAMPLE_INVALID")
    if duplicates > received:
        raise ApiError("ERR_QUALITY_SAMPLE_INVALID")
    for existing in repo.feed_samples(fid):
        other_start = parse_iso(existing["period_start"])
        other_end = parse_iso(existing["period_end"])
        if other_start is None or other_end is None:
            continue
        if start_dt < other_end and other_start < end_dt:
            raise ApiError("ERR_QUALITY_SAMPLE_INVALID")

    reject_rate = rhu4(Decimal(rejected) / Decimal(max(1, received)))
    sample = create(
        db.samples,
        "FeedQualitySample",
        {
            "data_feed_id": fid,
            "period_start": start_raw,
            "period_end": end_raw,
            "messages_received": received,
            "messages_rejected": rejected,
            "required_fields_missing_count": missing,
            "duplicate_count": duplicates,
            "timeliness_p95_seconds": p95,
            "reject_rate": out(reject_rate),
        },
        versioned=False,
    )

    first_sample = int(feed["sample_count"] or 0) == 0
    feed["sample_count"] = int(feed["sample_count"] or 0) + 1
    _refresh_latest_reject_rate(feed)

    breached = reject_rate > FEED_DEGRADED_REJECT_RATE
    if feed["status"] == "PROVISIONING" and first_sample:
        feed["status"] = "MONITORED"
        if breached:
            feed["status"] = "DEGRADED"
            feed["status_reason"] = REJECT_RATE_BREACH
    elif feed["status"] == "MONITORED" and breached:
        feed["status"] = "DEGRADED"
        feed["status_reason"] = REJECT_RATE_BREACH
    elif feed["status"] == "DEGRADED" and not breached:
        feed["status"] = "MONITORED"
        feed["status_reason"] = None
    touch(feed)

    participant = repo.participant(feed["participant_id"])
    if participant is not None:
        scorecard.refresh(participant)
    return entity_created(sample)


@bp.route("/hie/data-feeds/<fid>/status-transitions", methods=["POST"])
def feed_status_transition(fid):
    authenticate((HIE_ADMIN,))
    payload = body()
    action = req_enum(payload, "action", FEED_ACTIONS)
    reason = None
    if action == "SUSPEND":
        reason = req_str(payload, "reason")

    feed = repo.must("data_feeds", fid)
    if feed["status"] == "RETIRED":
        raise ApiError("ERR_TERMINAL_STATE")

    participant = repo.participant(feed["participant_id"])
    if action == "SUSPEND":
        if feed["status"] not in ("PROVISIONING", "MONITORED", "DEGRADED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        feed["status"] = "SUSPENDED"
        feed["status_reason"] = reason
    else:
        if feed["status"] != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if participant is not None and participant["onboarding_status"] == "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        feed["status"] = "MONITORED"
        feed["status_reason"] = None
    touch(feed)
    if participant is not None:
        scorecard.refresh(participant)
    return entity(feed)


@bp.route("/hie/data-feeds/<fid>", methods=["GET"])
def read_feed(fid):
    authenticate((HIE_ADMIN, PARTICIPANT_ADMIN))
    return entity(repo.must("data_feeds", fid))


@bp.route("/hie/participants/<pid>/data-feeds", methods=["GET"])
def list_participant_feeds(pid):
    authenticate((HIE_ADMIN, PARTICIPANT_ADMIN))
    limit, offset = pagination()
    repo.must("participants", pid)
    rows = repo.participant_feeds(pid)
    feed_type = request.args.get("feed_type")
    status = request.args.get("status")
    if feed_type:
        rows = [r for r in rows if r["feed_type"] == feed_type]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, limit, offset)


@bp.route("/hie/data-feeds/<fid>/quality-samples", methods=["GET"])
def list_samples(fid):
    authenticate((HIE_ADMIN, PARTICIPANT_ADMIN))
    limit, offset = pagination()
    repo.must("data_feeds", fid)
    return paginate(repo.feed_samples(fid), limit, offset)
