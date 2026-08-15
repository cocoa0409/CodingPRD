"""Eligibility override routes (PRD 3.7). Half-open windows [start, end);
OCC on Carrier.version; APPROVE pins approved_against_snapshot_id."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import (
    body_json,
    ctx,
    list_response,
    need_str,
    ownership_guard,
    require_role,
)
from response import ok
from services.posture import recompute_posture
from util import fmt_ts, parse_date

bp = Blueprint("overrides", __name__)

OPEN_STATUSES = ("REQUESTED", "APPROVED", "ACTIVE")
OUTCOMES = ("APPROVE", "REJECT", "REVOKE")


def _overlaps_existing(cid, start, end, exclude_id=None):
    """Half-open [start, end) overlap against the carrier's REQUESTED/
    APPROVED/ACTIVE overrides; adjacency (start == existing end) is allowed."""
    for o in store.overrides.values():
        if o["carrier_id"] != cid or o["status"] not in OPEN_STATUSES:
            continue
        if exclude_id is not None and o["id"] == exclude_id:
            continue
        if start < o["_end"] and o["_start"] < end:
            return True
    return False


@bp.post("/api/eligibility-overrides")
def create_override():
    uid, role = ctx()
    require_role(role, ("CarrierManager",))
    body = body_json()
    cid = body.get("carrier_id")
    # Rung 3: direct comparison on the body's carrier_id
    if isinstance(cid, str):
        ownership_guard(cid, uid)
    # Rung 4
    carrier = store.carriers.get(cid) if isinstance(cid, str) else None
    if isinstance(cid, str) and carrier is None:
        raise ApiError("ERR_CARRIER_NOT_FOUND", 404, "carrier id does not exist")
    # Rung 6: OCC token (non-optional per PRD 2.9)
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
    # Rung 7: override requests are rejected only for a TERMINATED carrier
    if carrier is not None and carrier["status"] == "TERMINATED":
        raise ApiError(
            "ERR_CARRIER_NOT_ACTIVE",
            409,
            "override requests are not accepted for a TERMINATED carrier",
        )
    # Rung 8: a waiver needs a score history to waive
    if carrier is not None and carrier["latest_snapshot_id"] is None:
        raise ApiError(
            "ERR_NO_SAFETY_SNAPSHOT", 422, "carrier has no safety score snapshot on file"
        )
    # Rung 9: temporal sanity — end_date must fall after start_date
    sd = parse_date(body.get("start_date"))
    ed = parse_date(body.get("end_date"))
    if sd is not None and ed is not None and ed <= sd:
        raise ApiError(
            "ERR_INVALID_DATE_RANGE", 400, "end_date must be after start_date"
        )
    # Rung 10: half-open window overlap
    if carrier is not None and sd is not None and ed is not None:
        if _overlaps_existing(cid, sd, ed):
            raise ApiError(
                "ERR_OVERRIDE_WINDOW_OVERLAP",
                409,
                "window overlaps an existing REQUESTED/APPROVED/ACTIVE override",
            )
    # Rung 12
    cid = need_str(body, "carrier_id")
    reason = need_str(body, "reason")
    if sd is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "start_date must be a YYYY-MM-DD date")
    if ed is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "end_date must be a YYYY-MM-DD date")
    rec = {
        "id": db.new_id(),
        "_seq": store.next_seq(),
        "carrier_id": cid,
        "reason": reason,
        "start_date": sd.isoformat(),
        "end_date": ed.isoformat(),
        "_start": sd,
        "_end": ed,
        "status": "REQUESTED",
        "decided_by": None,
        "approved_against_snapshot_id": None,
        "version": 1,
    }
    db.stamp(rec)
    store.overrides[rec["id"]] = rec
    # Filing the request increments the carrier's version (PRD 3.7)
    carrier["version"] += 1
    carrier["updated_at"] = fmt_ts(db.now())
    return ok(db.public(rec), 201)


@bp.get("/api/eligibility-overrides")
def list_overrides():
    return list_response(
        store.overrides.values(),
        [
            ("carrier_id", "carrier_id"),
            ("status", "status"),
            ("approved_against_snapshot_id", "approved_against_snapshot_id"),
        ],
    )


@bp.get("/api/eligibility-overrides/<overrideId>")
def get_override(overrideId):
    ctx()
    o = store.overrides.get(overrideId)
    if o is None:
        raise ApiError("ERR_OVERRIDE_NOT_FOUND", 404, "override id does not exist")
    return ok(db.public(o), 200)


@bp.post("/api/eligibility-overrides/<overrideId>/decide")
def decide_override(overrideId):
    uid, role = ctx()
    require_role(role, ("ComplianceOfficer",))
    o = store.overrides.get(overrideId)
    if o is None:
        raise ApiError("ERR_OVERRIDE_NOT_FOUND", 404, "override id does not exist")
    body = body_json()
    outcome = body.get("outcome")
    # Rung 5: state-machine legality for valid outcomes; rung 12 otherwise
    if isinstance(outcome, str) and outcome in OUTCOMES:
        legal = (o["status"] == "REQUESTED" and outcome in ("APPROVE", "REJECT")) or (
            o["status"] in ("APPROVED", "ACTIVE") and outcome == "REVOKE"
        )
        if not legal:
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                409,
                f"override in status {o['status']} cannot be decided with {outcome}",
            )
    else:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "outcome must be one of APPROVE, REJECT, REVOKE"
        )
    carrier = store.carriers.get(o["carrier_id"])
    if outcome == "APPROVE":
        # Rung 8: snapshot presence re-verified at approval time
        if carrier is not None and carrier["latest_snapshot_id"] is None:
            raise ApiError(
                "ERR_NO_SAFETY_SNAPSHOT", 422, "carrier has no safety score snapshot on file"
            )
        # Rung 10: window still clears every sibling override
        if _overlaps_existing(o["carrier_id"], o["_start"], o["_end"], exclude_id=o["id"]):
            raise ApiError(
                "ERR_OVERRIDE_WINDOW_OVERLAP",
                409,
                "window overlaps an existing REQUESTED/APPROVED/ACTIVE override",
            )
        o["approved_against_snapshot_id"] = (
            carrier["latest_snapshot_id"] if carrier is not None else None
        )
        o["decided_by"] = uid
        if o["_start"] <= db.today():
            # Start date has already arrived: straight to ACTIVE with an
            # immediate posture recompute (override in force => ELIGIBLE).
            o["status"] = "ACTIVE"
            db.bump(o)
            if carrier is not None:
                recompute_posture(carrier)
        else:
            o["status"] = "APPROVED"
            db.bump(o)
    elif outcome == "REJECT":
        o["status"] = "REJECTED"
        o["decided_by"] = uid
        db.bump(o)
    else:  # REVOKE from APPROVED or ACTIVE
        o["status"] = "REVOKED"
        o["decided_by"] = uid
        db.bump(o)
        # Revoking an in-force waiver recomputes posture without it (possible
        # INELIGIBLE -> safety cascade); a not-yet-active approval is a no-op.
        if carrier is not None:
            recompute_posture(carrier)
    return ok(db.public(o), 200)
