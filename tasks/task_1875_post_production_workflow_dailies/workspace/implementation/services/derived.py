"""Derived-field recomputation and cascade side effects (PRD §2.10, §3).

Every recomputation that changes a parent resource is a mutation of that
parent: it refreshes updated_at and increments version.
"""

import db
from helpers import touch, now_iso, compute_storage_used_gb


# ---------------------------------------------------------------------------
# Project derived fields
# ---------------------------------------------------------------------------


def recompute_project_storage(project):
    new_value = compute_storage_used_gb(project["id"], db.assets)
    if project.get("storage_used_gb") != new_value:
        project["storage_used_gb"] = new_value
        touch(project)


def recompute_open_change_list_count(project):
    count = 0
    for cl in db.change_lists.values():
        if cl["project_id"] == project["id"] and cl["status"] == "OPEN":
            count += 1
    if project.get("open_change_list_count") != count:
        project["open_change_list_count"] = count
        touch(project)


def recompute_conform_ready(project):
    """True iff: every MediaAsset in scope has status CONFORMED/LOCKED/PURGED,
    no ReviewRound has unresolved_critical, and at least one TurnoverPackage
    is in ISSUED or later (ISSUED, ACKED, RETURNED, CLOSED)."""
    pid = project["id"]
    assets_ok = True
    for asset in db.assets.values():
        if asset["project_id"] != pid:
            continue
        if asset["status"] not in ("CONFORMED", "LOCKED", "PURGED"):
            assets_ok = False
            break
    reviews_ok = True
    for rr in db.review_rounds.values():
        if rr["project_id"] != pid:
            continue
        if rr.get("unresolved_critical"):
            reviews_ok = False
            break
    turnover_ok = False
    for to in db.turnovers.values():
        if to["project_id"] != pid:
            continue
        if to["status"] in ("ISSUED", "ACKED", "RETURNED", "CLOSED"):
            turnover_ok = True
            break
    ready = assets_ok and reviews_ok and turnover_ok
    if project.get("conform_ready") != ready:
        project["conform_ready"] = ready
        touch(project)


# ---------------------------------------------------------------------------
# MediaBatch derived fields
# ---------------------------------------------------------------------------


def recompute_batch_counters(batch):
    assets = [
        a for a in db.assets.values() if a.get("batch_id") == batch["id"]
    ]
    asset_count = len(assets)
    failed_count = sum(1 for a in assets if a["status"] == "FAILED")
    done_count = sum(1 for a in assets if a["proxy_status"] == "DONE")
    progress = (100 * done_count) // max(1, asset_count)
    changed = False
    if batch.get("asset_count") != asset_count:
        batch["asset_count"] = asset_count
        changed = True
    if batch.get("failed_asset_count") != failed_count:
        batch["failed_asset_count"] = failed_count
        changed = True
    if batch.get("proxy_progress_pct") != progress:
        batch["proxy_progress_pct"] = progress
        changed = True
    if changed:
        touch(batch)


# ---------------------------------------------------------------------------
# ReviewRound derived fields
# ---------------------------------------------------------------------------


def recompute_round_counters(review_round):
    notes = [
        n for n in db.review_notes.values() if n.get("round_id") == review_round["id"]
    ]
    unresolved_critical = any(
        n["severity"] == "CRITICAL" and n["status"] != "RESOLVED" for n in notes
    )
    open_note_count = sum(
        1 for n in notes if n["status"] not in ("RESOLVED", "VOID")
    )
    changed = False
    if review_round.get("unresolved_critical") != unresolved_critical:
        review_round["unresolved_critical"] = unresolved_critical
        changed = True
    if review_round.get("open_note_count") != open_note_count:
        review_round["open_note_count"] = open_note_count
        changed = True
    if changed:
        touch(review_round)


# ---------------------------------------------------------------------------
# Deliverable derived fields
# ---------------------------------------------------------------------------


def recompute_deliverable_counters(deliverable):
    reports = [
        r
        for r in db.qc_reports.values()
        if r.get("deliverable_id") == deliverable["id"]
    ]
    attempt_count = len(reports)
    progress = (
        100
        if deliverable["status"]
        in ("RENDERED", "QC_QUEUED", "QC_PASSED", "QC_FAILED", "DELIVERED")
        else 0
    )
    changed = False
    if deliverable.get("qc_attempt_count") != attempt_count:
        deliverable["qc_attempt_count"] = attempt_count
        changed = True
    if deliverable.get("render_progress_pct") != progress:
        deliverable["render_progress_pct"] = progress
        changed = True
    if changed:
        touch(deliverable)


# ---------------------------------------------------------------------------
# TurnoverPackage derived fields
# ---------------------------------------------------------------------------


def recompute_turnover_change_list_revision(turnover):
    highest = 0
    for cl in db.change_lists.values():
        if cl.get("turnover_id") == turnover["id"]:
            highest = max(highest, cl["revision"])
    if turnover.get("change_list_revision") != highest:
        turnover["change_list_revision"] = highest
        touch(turnover)


# ---------------------------------------------------------------------------
# Cascades (PRD §2.10, §3)
# ---------------------------------------------------------------------------


def void_review_round(review_round):
    """System cascade: OPEN round -> VOID; voids every note still OPEN."""
    if review_round["status"] != "OPEN":
        return
    review_round["status"] = "VOID"
    touch(review_round)
    for note in db.review_notes.values():
        if note.get("round_id") == review_round["id"] and note["status"] == "OPEN":
            note["status"] = "VOID"
            touch(note)


def revoke_dailies_package(package):
    """PUBLISHED -> REVOKED; sets revoked_at; voids OPEN rounds targeting it
    (which in turn void their OPEN notes)."""
    if package["status"] != "PUBLISHED":
        return
    package["status"] = "REVOKED"
    package["revoked_at"] = now_iso()
    touch(package)
    for rr in db.review_rounds.values():
        if (
            rr.get("target_ref_id") == package["id"]
            and rr["status"] == "OPEN"
        ):
            void_review_round(rr)


def purge_batch_assets(batch):
    """All child MediaAssets transition to PURGED."""
    for asset in db.assets.values():
        if asset.get("batch_id") == batch["id"] and asset["status"] != "PURGED":
            asset["status"] = "PURGED"
            touch(asset)
