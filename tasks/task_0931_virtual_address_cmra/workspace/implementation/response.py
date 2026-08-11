"""Response envelope (PRD 2.2) and the once-per-row-per-request version ledger (PRD 2.4)."""

from flask import g, jsonify

from util import CLOCK, new_request_id, render_instant


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": render_instant(CLOCK.now),
    }


def ok(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def created(data):
    return ok(data, 201)


def empty():
    return ok({}, 200)


def listing(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ------------------------------------------------------------------ version ledger
def touch(row):
    """
    PRD 2.4: `version` is bumped exactly ONCE per row per request that mutates
    it, never once per side effect.  Every mutation in this codebase routes
    through here, so a request that touches one row three times still advances
    that row's version by one.  Rows without common fields (plan tiers, carrier
    rules, ledger entries) are never touched.
    """
    if "version" not in row:
        return row
    bumped = getattr(g, "bumped", None)
    if bumped is None:
        bumped = set()
        g.bumped = bumped
    if row["id"] not in bumped:
        bumped.add(row["id"])
        row["version"] += 1
        row["updated_at"] = CLOCK.now
    return row
