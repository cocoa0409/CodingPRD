"""The multi-hop cascades of PRD 3.2, 3.4, 3.7 and 3.8.

Each chain lives here exactly once so that every trigger of it applies the
identical hops in the identical order.  Every record a hop rewrites gets its
own `updated_at` refresh and its own single `version` increment (section 2.5).
"""

import clock
import store
from services import interests, projects as project_service, sales


# --- shared consequences ---------------------------------------------------

def recompute_report_counters(report):
    """`verified_component_count` and `total_replacement_cost_cents` are both
    taken over the report's VERIFIED children, which is why unverifying every
    component drives both to 0."""
    components = store.report_components(report["id"])
    verified = [c for c in components
                if c["verification_status"] == "VERIFIED"]
    count = len(verified)
    total = sum(c["replacement_cost_cents"] for c in verified)
    if (report["verified_component_count"] != count
            or report["total_replacement_cost_cents"] != total):
        report["verified_component_count"] = count
        report["total_replacement_cost_cents"] = total
        store.touch(report)
    return report


def demote_batches(project):
    """A batch at THRESHOLD_MET or RELEASED that no longer clears both clauses
    falls back to THRESHOLD_SHORT; one that leaves RELEASED also clears
    `released_at` and drags the project CLOSINGS -> PRESALE."""
    for batch in store.project_batches(project["id"]):
        sales.write_batch_counters(batch, project)
        if batch["status"] not in ("THRESHOLD_MET", "RELEASED"):
            continue
        if sales.thresholds_met(batch):
            continue
        left_released = batch["status"] == "RELEASED"
        batch["status"] = "THRESHOLD_SHORT"
        if left_released:
            batch["released_at"] = None
        store.touch(batch)
        if left_released and project["status"] == "CLOSINGS":
            project["status"] = "PRESALE"
            store.touch(project)
    return project


def promote_batch(batch, project):
    """A batch at THRESHOLD_SHORT that now satisfies both clauses is carried to
    THRESHOLD_MET as a system consequence of an agreement hardening."""
    sales.write_batch_counters(batch, project)
    if batch["status"] == "THRESHOLD_SHORT" and sales.thresholds_met(batch):
        batch["status"] = "THRESHOLD_MET"
        store.touch(batch)
    return batch


def require_amendment(project):
    """EFFECTIVE -> AMENDMENT_REQUIRED, driven by the system only."""
    statement = store.project_statement(project["id"])
    if statement is not None and statement["status"] == "EFFECTIVE":
        statement["status"] = "AMENDMENT_REQUIRED"
        store.touch(statement)
    return statement


# --- peer-review rejection: the four-hop punitive cascade (3.2) ------------

def reject_report(report, project, actor_user_id):
    # Hop one: the report itself and every child component.
    report["status"] = "REVISION_REQUESTED"
    report["reviewed_by_user_id"] = actor_user_id
    for component in store.report_components(report["id"]):
        if component["verification_status"] != "UNVERIFIED":
            component["verification_status"] = "UNVERIFIED"
            store.touch(component)
    store.touch(report)
    recompute_report_counters(report)

    # Hop two: no component is VERIFIED any longer, so the effective
    # assessments of this report are invalidated.
    for assessment in store.report_assessments(report["id"]):
        if assessment["status"] == "EFFECTIVE":
            assessment["status"] = "INVALIDATED"
            store.touch(assessment)

    # Hop three: the project has no EFFECTIVE assessment left.
    project["suitability_gate"] = "FAILED"
    project["suitability_score"] = project_service.ZERO_PCT
    if project["status"] == "DOCUMENTS_PREPARATION":
        project["status"] = "SUITABILITY_REVIEW"
    store.touch(project)

    # Hop four: the freezing branch now matches, and the disclosure goes stale.
    require_amendment(project)
    project_service.sync(project)
    project_service.recompute_posture(project)
    return report


# --- the plat fallback and the unit withdrawal cascade (3.4) ---------------

def revert_plat(package):
    """PLAT_CERTIFIED -> DRAFT, a system-driven fallback that counts the
    reopening in `plat_revision`."""
    if package is not None and package["status"] == "PLAT_CERTIFIED":
        package["status"] = "DRAFT"
        package["plat_revision"] = package["plat_revision"] + 1
        store.touch(package)
    return package


def _resettle_allocation(project, package):
    from services import budgets
    interests.reallocate(package)
    budgets.reallocate_for_project(project)
    project_service.sync(project)
    project_service.recompute_posture(project)


def withdraw_unit(unit, package, project, withdrawal_reason):
    # Hop one.
    unit["declaration_status"] = "WITHDRAWN"
    if withdrawal_reason is not None:
        unit["withdrawal_reason"] = withdrawal_reason
    store.touch(unit)

    # Hop two: void the live sales on the unit.
    voided = []
    for agreement in store.unit_agreements(unit["id"]):
        if agreement["contract_status"] in ("SIGNED", "HARD"):
            agreement["contract_status"] = "VOID"
            voided.append(agreement)
            store.touch(agreement)

    # Hop three: refund the money taken on each voided agreement.
    for agreement in voided:
        if agreement["escrow_status"] == "FUNDED":
            agreement["escrow_status"] = "REFUNDED"
            store.touch(agreement)
    sales.derive_unit_sale_status(unit)
    project_service.sync(project)

    # Hop four: the batches that held those agreements.
    demote_batches(project)

    # Hop five and six: the plat reopens and the sweep re-runs.
    revert_plat(package)

    # Hop seven: the disclosure now describes a unit no longer on offer.
    require_amendment(project)
    _resettle_allocation(project, package)
    return unit


def reinstate_unit(unit, package, project):
    unit["declaration_status"] = "INCLUDED"
    store.touch(unit)
    revert_plat(package)
    _resettle_allocation(project, package)
    return unit


# --- material amendment: the four-hop cascade (3.7) ------------------------

AMENDMENT_RESTART_SECONDS = 5 * 86400


def file_amendment(statement, project, material_change):
    # Hop one.
    statement["status"] = "AMENDMENT_FILED"
    statement["amendment_count"] = statement["amendment_count"] + 1
    amendment_instant = clock.now()
    if material_change:
        statement["last_material_amendment_at"] = amendment_instant
    store.touch(statement)

    if material_change:
        # Hop two: the delivered, unclosed population.
        for agreement in store.project_agreements(project["id"]):
            if agreement["contract_status"] not in ("SIGNED", "HARD"):
                continue
            if agreement["pos_delivered_at"] is None:
                continue
            if agreement["contract_status"] == "HARD":
                agreement["contract_status"] = "SIGNED"
            restarted = clock.plus_seconds(amendment_instant,
                                           AMENDMENT_RESTART_SECONDS)
            current = agreement["rescission_deadline_at"]
            if current is None or restarted > current:
                agreement["rescission_deadline_at"] = restarted
            agreement["rescission_restart_count"] = (
                agreement["rescission_restart_count"] + 1)
            store.touch(agreement)
            unit = store.units.get(agreement["unit_id"])
            if unit is not None:
                sales.derive_unit_sale_status(unit)

        # Hop three.
        project_service.sync(project)
        demote_batches(project)

        # Hop four.
        if project["status"] == "PRESALE":
            project["status"] = "REGISTRATION"
            store.touch(project)

    project_service.sync(project)
    project_service.recompute_posture(project)
    return statement


# --- rescission: the four-hop cascade (3.8) -------------------------------

def rescind_agreement(agreement, project, rescission_reason):
    # Hop one.
    agreement["contract_status"] = "RESCINDED"
    if agreement["escrow_status"] == "FUNDED":
        agreement["escrow_status"] = "REFUNDED"
    if rescission_reason is not None:
        agreement["rescission_reason"] = rescission_reason
    store.touch(agreement)

    # Hop two: the escrow buckets move and the unit loses its contract.
    unit = store.units.get(agreement["unit_id"])
    if unit is not None:
        sales.derive_unit_sale_status(unit)
    project_service.sync(project)

    # Hop three and four.
    demote_batches(project)
    sales.recompute_warrantability(project, "contract")
    project_service.sync(project)
    project_service.recompute_posture(project)
    return agreement


# --- project completion after a closing (3.9) -----------------------------

def complete_project_if_all_sold(project):
    included = store.included_units(project["id"])
    if not included:
        return project
    if any(unit["sale_status"] != "SOLD" for unit in included):
        return project
    if project["status"] != "CLOSINGS":
        return project
    project["status"] = "COMPLETED"
    store.touch(project)
    for batch in store.project_batches(project["id"]):
        if batch["status"] == "RELEASED":
            batch["status"] = "SETTLED"
            store.touch(batch)
    return project
