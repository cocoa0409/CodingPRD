from flask import Blueprint, request
from datetime import timedelta
import errors
from db import db
from middleware import require_auth
from response import success_object, success_array
from pagination import parse_pagination, paginate
from serializers import revision_out
from util import new_uuid, now_iso, parse_iso
from services.handicap import compute_official_base, apply_caps
import validate as V

bp = Blueprint("revisions", __name__)


@bp.route("/golf/handicap-revisions", methods=["POST"])
def create_revision():
    require_auth({"ProShop"})
    data = V.require_body(request.get_json(silent=True))

    effective_utc = V.as_str(V.require_present(data, "effective_utc"), "effective_utc")
    try:
        eff_dt = parse_iso(effective_utc)
    except Exception:
        raise errors.validation("effective_utc must be ISO 8601.")

    # monotonic: strictly after previous revision's effective_utc
    if db.revisions:
        prev = max(db.revisions.values(), key=lambda r: r["revision_number"])
        prev_dt = parse_iso(prev["effective_utc"])
        if not (eff_dt > prev_dt):
            raise errors.ApiError(
                errors.ERR_REVISION_NOT_MONOTONIC, 409,
                "effective_utc must be strictly after the previous revision.")

    eff_date = eff_dt.date().isoformat()
    window_start = eff_dt - timedelta(days=365)

    db.revision_counter += 1
    revision_number = db.revision_counter
    ts = now_iso()

    golfer_count = 0
    for golfer in db.golfers.values():
        base, contributing = compute_official_base(golfer["id"], eff_date, db)
        if base is None:
            continue
        # caps use the pre-run anchor (trailing-365 low as of this run, prior indices only)
        official = apply_caps(base, golfer["low_handicap_index"])
        official_f = float(official)

        golfer["handicap_index"] = official_f
        golfer["handicap_revision"] = revision_number

        # record this run's official index in history
        golfer["_index_history"].append((eff_dt, official_f))
        # refresh anchor: min official index over trailing 365 days, this run included
        in_window = [
            idx for (d, idx) in golfer["_index_history"]
            if d > window_start
        ]
        golfer["low_handicap_index"] = min(in_window) if in_window else official_f

        for sid in contributing:
            sc = db.scores.get(sid)
            if sc:
                sc["counted_in_revision"] = revision_number

        golfer["version"] += 1
        golfer["updated_at"] = ts
        golfer_count += 1

    r = {
        "id": new_uuid(),
        "_seq": db.next_seq(),
        "created_at": ts,
        "revision_number": revision_number,
        "effective_utc": effective_utc,
        "golfer_count": golfer_count,
    }
    db.revisions[r["id"]] = r
    return success_object(revision_out(r), 201)


@bp.route("/golf/handicap-revisions", methods=["GET"])
def list_revisions():
    require_auth({"ProShop", "Golfer", "Anonymous"})
    limit, offset = parse_pagination()
    items = sorted(db.revisions.values(), key=lambda x: (x["created_at"], x["_seq"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return success_array([revision_out(r) for r in page], limit, offset, total, 200)
