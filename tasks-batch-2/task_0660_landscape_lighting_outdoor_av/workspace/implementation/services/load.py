"""Load recomputation engine (PRD 2.5) — the quota/allocation core.

committed_load_va of a transformer is the exact integer sum of:
  - wattage_w of fixtures whose zone's transformer is this transformer and
    whose status is PLANNED or INSTALLED, plus
  - power_draw_va of ACTIVE add-ons whose zone's transformer is this transformer
    (zone_id non-null).

zone_load_va is the sum of wattage_w over the zone's PLANNED/INSTALLED fixtures.

A project's total_committed_load_va is the sum of committed_load_va across its
transformers; fixture_count is the count of its PLANNED/INSTALLED fixtures.

Recompute helpers bump updated_at/version on the affected resource per PRD 2.4
(recomputation of a derived field is a mutation). Callers decide which
resources to recompute for a given cascade; version bumps on the *transformer*
that are part of OCC are handled explicitly at the call site.
"""

from common import touch
from db import db

LIVE_FIXTURE_STATES = {"PLANNED", "INSTALLED"}


def zone_load(zone):
    return sum(
        f["wattage_w"]
        for f in db.fixtures.values()
        if f.get("zone_id") == zone["id"] and f["status"] in LIVE_FIXTURE_STATES
    )


def transformer_committed(transformer):
    tid = transformer["id"]
    # Zones fed by this transformer.
    zone_ids = {z["id"] for z in db.zones.values() if z.get("transformer_id") == tid}
    fixture_sum = sum(
        f["wattage_w"]
        for f in db.fixtures.values()
        if f.get("zone_id") in zone_ids and f["status"] in LIVE_FIXTURE_STATES
    )
    addon_sum = sum(
        a["power_draw_va"]
        for a in db.add_ons.values()
        if a.get("zone_id") in zone_ids
        and a.get("zone_id") is not None
        and a["status"] == "ACTIVE"
    )
    return fixture_sum + addon_sum


def project_total_committed(project):
    pid = project["id"]
    return sum(
        transformer_committed(t)
        for t in db.transformers.values()
        if t.get("project_id") == pid
    )


def project_fixture_count(project):
    pid = project["id"]
    return sum(
        1
        for f in db.fixtures.values()
        if f.get("project_id") == pid and f["status"] in LIVE_FIXTURE_STATES
    )


# --------------------------------------------------------------------------
# Recompute-and-stamp helpers. Each writes the derived field and, when the
# stored value changes, refreshes updated_at and bumps version (PRD 2.4).
# --------------------------------------------------------------------------
def recompute_zone(zone):
    new_val = zone_load(zone)
    if zone.get("zone_load_va") != new_val:
        zone["zone_load_va"] = new_val
        touch(zone)


def recompute_transformer(transformer, bump_version_always=False):
    new_val = transformer_committed(transformer)
    changed = transformer.get("committed_load_va") != new_val
    transformer["committed_load_va"] = new_val
    if changed or bump_version_always:
        touch(transformer)


def recompute_project_loads(project):
    new_total = project_total_committed(project)
    new_count = project_fixture_count(project)
    if (
        project.get("total_committed_load_va") != new_total
        or project.get("fixture_count") != new_count
    ):
        project["total_committed_load_va"] = new_total
        project["fixture_count"] = new_count
        touch(project)


def transformer_for_zone(zone):
    return db.transformers.get(zone.get("transformer_id"))
