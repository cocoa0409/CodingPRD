"""Safety score snapshot feed (PRD 3.2). OCC on Carrier.version; posting
recomputes posture and may fire the safety deactivation cascade; an in-force
override pinned to a superseded snapshot flips to STALE."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import body_json, ctx, list_response, need_enum, require_role
from response import ok
from services.posture import latest_snapshot, recompute_posture
from util import fmt_ts, parse_date

bp = Blueprint("snapshots", __name__)

RATINGS = ("SATISFACTORY", "CONDITIONAL", "UNSATISFACTORY")
SOURCES = ("FMCSA_FEED", "MANUAL_AUDIT")


@bp.post("/api/safety-score-snapshots")
def create_snapshot():
    _uid, role = ctx()
    require_role(role, ("SafetyDataFeed",))
    body = body_json()
    cid = body.get("carrier_id")
    carrier = store.carriers.get(cid) if isinstance(cid, str) else None
    # Rung 4: existence precedes OCC
    if isinstance(cid, str) and carrier is None:
        raise ApiError("ERR_CARRIER_NOT_FOUND", 404, "carrier id does not exist")
    # Rung 6: OCC token is non-optional (PRD 2.9)
    if carrier is not None:
        expected = body.get("expected_carrier_version")
        if (
            expected is None
            or isinstance(expected, bool)
            or not isinstance(expected, int)
            or expected != carrier["version"]
        ):
            raise ApiError(
                "ERR_STALE_VERSION",
                412,
                "expected_carrier_version does not match the carrier's current version",
            )
    # Rung 9: effective_date must not be in the future
    eff = parse_date(body.get("effective_date"))
    if eff is not None and eff > db.today():
        raise ApiError(
            "ERR_INVALID_DATE_RANGE", 400, "effective_date must not be in the future"
        )
    # Rung 12: field ranges/enums
    if not isinstance(cid, str) or not cid:
        raise ApiError("ERR_INVALID_REQUEST", 400, "carrier_id must be a non-empty string")
    iss = body.get("iss_score")
    if isinstance(iss, bool) or not isinstance(iss, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, "iss_score must be an integer")
    if not (0 <= iss <= 100):
        raise ApiError("ERR_INVALID_ISS_SCORE", 400, "iss_score must be in 0..100")
    rating = need_enum(body, "safety_rating", RATINGS)
    source = need_enum(body, "source", SOURCES)
    if eff is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "effective_date must be a YYYY-MM-DD date"
        )
    rec = {
        "id": db.new_id(),
        "_seq": store.next_seq(),
        "carrier_id": cid,
        "iss_score": iss,
        "safety_rating": rating,
        "source": source,
        "effective_date": eff.isoformat(),
        "_effective": eff,
    }
    db.stamp_feed(rec)
    store.snapshots[rec["id"]] = rec

    # Parent-side derived pointer: snapshot with max effective_date (tie: latest
    # created_at).
    lat = latest_snapshot(cid)
    if lat["id"] != carrier["latest_snapshot_id"]:
        carrier["latest_snapshot_id"] = lat["id"]
        carrier["latest_iss_score"] = lat["iss_score"]
        carrier["latest_safety_rating"] = lat["safety_rating"]
    # Version pinning enforces itself: an ACTIVE override whose pinned snapshot
    # is no longer latest flips to STALE (terminal).
    for o in store.overrides.values():
        if (
            o["carrier_id"] == cid
            and o["status"] == "ACTIVE"
            and o["approved_against_snapshot_id"] != carrier["latest_snapshot_id"]
        ):
            o["status"] = "STALE"
            db.bump(o)
    # Posture recompute (safety cascade may fire, +1 carrier version), then the
    # snapshot write itself increments Carrier.version by 1 (PRD 3.2 "also").
    recompute_posture(carrier)
    carrier["version"] += 1
    carrier["updated_at"] = fmt_ts(db.now())
    return ok(db.public(rec), 201)


@bp.get("/api/safety-score-snapshots")
def list_snapshots():
    return list_response(store.snapshots.values(), [("carrier_id", "carrier_id")])


@bp.get("/api/safety-score-snapshots/<snapshotId>")
def get_snapshot(snapshotId):
    ctx()
    snap = store.snapshots.get(snapshotId)
    if snap is None:
        raise ApiError("ERR_NOT_FOUND", 404, "snapshot id does not exist")
    return ok(db.public(snap), 200)
