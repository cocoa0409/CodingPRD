"""Cross-entity cascades (PRD section 2.6).  Everything runs inside the
triggering request; there is no deferred work and no read-time repair."""

from store import iso, now, runs_of, store, touch, windows_of


def _has_current_complete_run(project):
    for run in runs_of(project["id"]):
        if run["status"] == "COMPLETE" and run["design_version_at_run"] == project["design_version"]:
            return True
    return False


def invalidate_design_evidence(project):
    """Links 2, 3 and 4 of the design-reopening cascade.

    Called after any change of Project.design_version: a segment created or
    revised, a flow link created, or a scope-bearing change order approved.
    """
    # Link 2 - every COMPLETE run whose snapshot no longer matches goes STALE.
    for run in runs_of(project["id"]):
        if (
            run["status"] == "COMPLETE"
            and run["design_version_at_run"] != project["design_version"]
        ):
            run["status"] = "STALE"
            touch(run)

    # Link 3 - with no current simulation left, SCHEDULED windows are blocked.
    if _has_current_complete_run(project):
        return
    blocked_lot_ids = []
    for window in windows_of(project["id"]):
        if window["status"] == "SCHEDULED":
            window["status"] = "BLOCKED_STALE_DESIGN"
            touch(window)
            blocked_lot_ids.append(window["fabrication_lot_id"])

    # Link 4 - lots referenced by a window blocked in link 3 lose FAT credit.
    for lot_id in blocked_lot_ids:
        lot = store.fabrication_lots.get(lot_id)
        if lot is not None and lot["status"] in ("STAGED", "FAT_PASSED"):
            lot["status"] = "HOLD"
            touch(lot)


def release_design_block(project):
    """The design-block mechanism in reverse (PRD sections 2.6 and 3.3).

    Windows unblock first; the lots follow from the windows that unblocked.
    """
    released_lot_ids = []
    for window in windows_of(project["id"]):
        if window["status"] == "BLOCKED_STALE_DESIGN":
            window["status"] = "SCHEDULED"
            touch(window)
            released_lot_ids.append(window["fabrication_lot_id"])
    for lot_id in released_lot_ids:
        lot = store.fabrication_lots.get(lot_id)
        if lot is not None and lot["status"] == "HOLD":
            lot["status"] = "STAGED"
            touch(lot)


def scrap_unwind(project, lot):
    """The scrap-unwind cascade (PRD section 2.6): links 2 and 3.

    Link 1 (the lot itself reaching SCRAPPED) is applied by the caller.
    """
    cancelled_any = False
    for window in windows_of(project["id"]):
        if window["fabrication_lot_id"] == lot["id"] and window["status"] == "SCHEDULED":
            window["status"] = "CANCELLED_LOT_SCRAPPED"
            window["closed_at"] = iso(now())
            touch(window)
            cancelled_any = True
    if cancelled_any and project["delivery_status"] == "IN_FABRICATION":
        project["delivery_status"] = "REBASELINE_REQUIRED"
        touch(project)


def reopen_design(project):
    """Link 1 of the design-reopening cascade, then links 2-4."""
    project["design_version"] += 1
    project["design_frozen_at"] = None
    if project["delivery_status"] in (
        "DESIGN_FROZEN",
        "IN_FABRICATION",
        "CUTOVER",
        "REBASELINE_REQUIRED",
    ):
        project["delivery_status"] = "DESIGN"
    touch(project)
    invalidate_design_evidence(project)


def advance_design_baseline(project):
    """A design mutation: design_version and version advance, evidence dies."""
    project["design_version"] += 1
    touch(project)
    invalidate_design_evidence(project)
