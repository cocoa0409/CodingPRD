"""Mutation tracking: each resource mutated by an operation gets exactly one
version increment and an updated_at refresh, per PRD section 2.5 / 2.7.

Computed-on-read fields (carrier credit/ytd, escort active count) never touch
stored state and therefore never bump a version. Silent field mirrors that the
scaffold does not annotate with a version bump (leg.survey_min_clearance_inches
at survey submit, escort reliability score changes short of suspension) are
applied directly without mark().
"""

from flask import g

import db


def mark(obj):
    dirty = g.get("_dirty")
    if dirty is None:
        dirty = set()
        g._dirty = dirty
    key = id(obj)
    if key in dirty:
        return
    dirty.add(key)
    obj["version"] += 1
    obj["updated_at"] = db.now()
