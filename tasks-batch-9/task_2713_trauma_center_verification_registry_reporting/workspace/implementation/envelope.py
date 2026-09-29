"""Response envelope (PRD 2.2), pagination meta (PRD 2.3) and the per-request
mutation bookkeeping that implements PRD 2.8 ("every touched record is a
mutation")."""
import random
import string

from flask import g, jsonify

from common import iso, wall_now
from store import db, VERSIONED_COLLECTIONS

_ALPHABET = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(20))


def meta(extra=None):
    payload = {
        "api_request_id": request_id(),
        "api_request_timestamp": iso(wall_now()),
    }
    if extra:
        payload.update(extra)
    return payload


def begin_request():
    g._snapshot = {
        name: {rid: dict(rec) for rid, rec in db.collection(name).items()}
        for name in VERSIONED_COLLECTIONS
    }
    g._touched = set()
    g._finalized = False


def touch(record):
    """Force a version bump for `record` even when no visible field changed."""
    if record is None:
        return
    if not hasattr(g, "_touched"):
        g._touched = set()
    g._touched.add(record["id"])


_SKIP = ("updated_at", "version")


def finalize():
    """Bump updated_at/version once for every record mutated by this request."""
    if getattr(g, "_finalized", True):
        return
    g._finalized = True
    snapshot = getattr(g, "_snapshot", {})
    touched = getattr(g, "_touched", set())
    now = wall_now()
    for name in VERSIONED_COLLECTIONS:
        previous = snapshot.get(name, {})
        for rid, record in db.collection(name).items():
            old = previous.get(rid)
            if old is None:
                continue  # created during this request: already at version 1
            changed = rid in touched
            if not changed:
                for key, value in record.items():
                    if key in _SKIP:
                        continue
                    if old.get(key) != value:
                        changed = True
                        break
            if changed:
                record["updated_at"] = now
                record["version"] = record.get("version", 1) + 1


def respond_object(builder, status=200):
    finalize()
    data = builder() if callable(builder) else builder
    body = {"meta": meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def respond_list(builder, page, status=200):
    finalize()
    data = builder() if callable(builder) else builder
    body = {"meta": meta(page), "response_type": "array", "data": data}
    return jsonify(body), status


def error_body(error_id, message):
    return {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
