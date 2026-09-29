"""The invalidation cascades and their compensations (PRD 3.2, 3.7, 3.8, 3.9)."""
import calc_hazard
import db
import ledger


def _resnapshot_demand(calc, area):
    """Re-derive a calculation's demand snapshot from the area's new figures."""
    if calc["method"] == "ROOM_DESIGN" and area.get("room_area_sqft") is None:
        return
    snapshot = calc_hazard.demand_snapshot(area, calc["method"])
    calc.update(snapshot)


def cascade_reclassification(area, project):
    """Cascade C: reclassify -> calculation REOPENED -> evaluation and pump SUPERSEDED."""
    reopened = []
    for calc in ledger.calculations_of(project["id"]):
        if calc["hazard_area_id"] != area["id"]:
            continue
        if calc["state"] not in ("CONVERGED", "QC_PASSED", "SEALED"):
            continue
        source = calc["state"]
        calc["state"] = "REOPENED"
        calc["stale_reason"] = "HAZARD_RECLASSIFIED"
        _resnapshot_demand(calc, area)
        if source == "QC_PASSED":
            calc["qc_reviewed_by_engineer_id"] = None
        elif source == "SEALED":
            calc["sealed_by_engineer_id"] = None
            calc["sealed_at"] = None
            project["sealed_calculation_count"] = max(
                0, (project["sealed_calculation_count"] or 0) - 1
            )
        db.touch(calc)
        reopened.append(calc["id"])

    superseded_evaluations = []
    for evaluation in db.evaluations.values():
        if evaluation["project_id"] != project["id"]:
            continue
        if evaluation["state"] != "EVALUATED":
            continue
        if evaluation["governing_hydraulic_calculation_id"] not in reopened:
            continue
        evaluation["state"] = "SUPERSEDED"
        db.touch(evaluation)
        superseded_evaluations.append(evaluation["id"])

    for pump in db.pumps.values():
        if pump["water_supply_evaluation_id"] in superseded_evaluations and pump["state"] == "SIZED":
            pump["state"] = "SUPERSEDED"
            db.touch(pump)

    ledger.recompute_ledger(project)
    ledger.recompute_posture(project)
    return reopened


def drawings_over(calculation_ids):
    return [
        d
        for d in db.shop_drawings.values()
        if d["hydraulic_calculation_id"] in calculation_ids
    ]


def clearances_of(shop_drawing_id):
    return [
        c
        for c in db.trade_clearances.values()
        if c["shop_drawing_id"] == shop_drawing_id
    ]


def cascade_major_comment(submittal, project):
    """Cascade A: MAJOR comment issued -> calculation REOPENED -> sheet and item STALE."""
    reopened = []
    for calc_id in submittal["included_calculation_ids"]:
        calc = db.calculations.get(calc_id)
        if calc is None or calc["state"] != "SEALED":
            continue
        calc["_prev_sealed_by_engineer_id"] = calc.get("sealed_by_engineer_id")
        calc["_prev_sealed_at"] = calc.get("sealed_at")
        calc["state"] = "REOPENED"
        calc["stale_reason"] = "MAJOR_COMMENT"
        calc["reopened_by_submittal_id"] = submittal["id"]
        project["sealed_calculation_count"] = max(
            0, (project["sealed_calculation_count"] or 0) - 1
        )
        db.touch(calc)
        reopened.append(calc["id"])

    for drawing in drawings_over(reopened):
        if drawing["state"] != "COORDINATED":
            continue
        drawing["state"] = "STALE"
        for item in clearances_of(drawing["id"]):
            if item["state"] == "CLEARED":
                item["state"] = "STALE"
                db.touch(item)
        drawing["cleared_trade_count"] = 0
        db.touch(drawing)

    ledger.recompute_ledger(project)
    return reopened


def cascade_package_approved(submittal, project):
    """Approval: COORDINATED sheets become ISSUED and CLEARED items LOCKED."""
    for drawing in drawings_over(list(submittal["included_calculation_ids"])):
        if drawing["state"] != "COORDINATED":
            continue
        drawing["state"] = "ISSUED"
        for item in clearances_of(drawing["id"]):
            if item["state"] == "CLEARED":
                item["state"] = "LOCKED"
                db.touch(item)
        db.touch(drawing)


def compensate_major_comment(submittal, project):
    """The full compensation of cascade A when the last comment is withdrawn."""
    resealed = []
    for calc in ledger.calculations_of(project["id"]):
        if calc.get("reopened_by_submittal_id") != submittal["id"]:
            continue
        if calc["state"] != "REOPENED":
            continue
        calc["state"] = "SEALED"
        if "_prev_sealed_by_engineer_id" in calc:
            calc["sealed_by_engineer_id"] = calc.pop("_prev_sealed_by_engineer_id")
        if "_prev_sealed_at" in calc:
            calc["sealed_at"] = calc.pop("_prev_sealed_at")
        calc["stale_reason"] = None
        calc["reopened_by_submittal_id"] = None
        project["sealed_calculation_count"] = (project["sealed_calculation_count"] or 0) + 1
        db.touch(calc)
        resealed.append(calc["id"])

    for drawing in drawings_over(resealed):
        if drawing["state"] != "STALE":
            continue
        drawing["state"] = "COORDINATED"
        for item in clearances_of(drawing["id"]):
            if item["state"] == "STALE":
                item["state"] = "CLEARED"
                db.touch(item)
        drawing["cleared_trade_count"] = drawing["required_trade_count"]
        db.touch(drawing)

    ledger.recompute_ledger(project)
    return resealed


def cascade_witness_failure(project):
    """Cascade B: witness fail -> project CORRECTIVE_ACTION -> aux DECOMMISSIONED."""
    project["status"] = "CORRECTIVE_ACTION"
    for system in ledger.aux_systems_of(project["id"]):
        if system["status"] != "COMMISSIONED":
            continue
        system["status"] = "DECOMMISSIONED_PENDING_RETEST"
        system["outage_start_at"] = None
        system["outage_end_at"] = None
        db.touch(system)
    ledger.recompute_posture(project)


def cascade_close_out(project):
    """Close-out: project CLOSED_OUT and every still-SEALED calculation ARCHIVED."""
    project["status"] = "CLOSED_OUT"
    for calc in ledger.calculations_of(project["id"]):
        if calc["state"] == "SEALED":
            calc["state"] = "ARCHIVED"
            db.touch(calc)
    ledger.recompute_posture(project)


def supersede_current_evaluations(project):
    """Only one evaluation of a project is current at a time (PRD 3.4)."""
    superseded = []
    for evaluation in db.evaluations.values():
        if evaluation["project_id"] != project["id"]:
            continue
        if evaluation["state"] != "EVALUATED":
            continue
        evaluation["state"] = "SUPERSEDED"
        db.touch(evaluation)
        superseded.append(evaluation["id"])
    for pump in db.pumps.values():
        if pump["water_supply_evaluation_id"] in superseded and pump["state"] == "SIZED":
            pump["state"] = "SUPERSEDED"
            db.touch(pump)
    return superseded
