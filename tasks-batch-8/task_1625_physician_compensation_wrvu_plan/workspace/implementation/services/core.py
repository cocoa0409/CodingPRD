"""Core record lifecycle: creation, per-request version bumps, serialization."""
from flask import g

from db import db
from util import new_id, now_ts, CLOCK, parse_iso_datetime, add_months_dt


def new_record(collection, fields):
    rec = dict(fields)
    rec["id"] = new_id()
    ts = now_ts()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    db[collection][rec["id"]] = rec
    return rec


def _touched():
    if "touched" not in g:
        g.touched = set()
    return g.touched


def touch(collection, rec):
    """Increment version and refresh updated_at — at most once per entity per
    request, so multi-hop cascades bump each touched entity exactly once
    (PRD 2.5 / 2.10)."""
    key = (collection, rec["id"])
    if key in _touched():
        return
    _touched().add(key)
    rec["updated_at"] = now_ts()
    rec["version"] = rec.get("version", 1) + 1


def public(rec):
    return dict(rec) if rec is not None else None


def compute_compliance_hold(agreement) -> bool:
    """Derived live (PRD 3.3): true exactly when the agreement is EFFECTIVE and
    the logical clock is strictly later than fmv_reviewed_at + 12 months."""
    if agreement["status"] != "EFFECTIVE":
        return False
    reviewed = agreement.get("fmv_reviewed_at")
    if not reviewed:
        return False
    threshold = add_months_dt(parse_iso_datetime(reviewed), 12)
    return CLOCK.now() > threshold


def agreement_out(agreement):
    out = dict(agreement)
    out["compliance_hold"] = compute_compliance_hold(agreement)
    return out
