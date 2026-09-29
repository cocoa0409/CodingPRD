"""PRD 2.6: every mutation -- including a recomputation of a derived field --
refreshes `updated_at` and increments `version` on the affected row.

Rather than hand-annotate every cascade, the request pipeline fingerprints every
existing row before the handler runs and again afterwards, and bumps whatever
actually changed. Rows created during the request are skipped: they are born at
version 1.
"""

import json

from flask import g

import serialize
from db import db

IGNORED = ("version", "updated_at")


def _fingerprint(rec):
    projection = serialize.serialize(rec)
    for key in IGNORED:
        projection.pop(key, None)
    return json.dumps(projection, sort_keys=True, default=str)


def _all_records():
    for store in db.stores():
        for rec in list(store.values()):
            yield rec


def snapshot():
    g._version_snapshot = {rec["id"]: _fingerprint(rec) for rec in _all_records()}
    g._version_forced = set()


def force(rec):
    """Mark a row as mutated even when no serialized field changed.

    Used for the two version bumps PRD 2.8 mandates explicitly:
    a contract offer bumps Prospect.version, a share request bumps
    MedicalEvaluation.version.
    """
    forced = getattr(g, "_version_forced", None)
    if forced is not None:
        forced.add(rec["id"])


def commit():
    before = getattr(g, "_version_snapshot", None)
    if before is None:
        return
    forced = getattr(g, "_version_forced", set())
    for rec in _all_records():
        rid = rec["id"]
        if rid not in before:
            continue
        if rid in forced or _fingerprint(rec) != before[rid]:
            rec["version"] += 1
            rec["updated_at"] = db.now
