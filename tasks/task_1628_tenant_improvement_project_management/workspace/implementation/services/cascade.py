"""Project cancellation compensation cascade per PRD §3.8."""

from db import store
from services.util import bump_version
from services import calc


def cancel_project(project):
    """Run the full compensation cascade for project cancellation.

    The project's status is set to CANCELLED by the caller AFTER this function
    so that we can branch on the pre-cancel status here.
    """
    from_status = project["status"]
    pid = project["id"]

    # From INITIATED: no children to compensate
    if from_status == "INITIATED":
        return

    # --- WorkLetters: all non-terminal -> WITHDRAWN ---
    for wl in store.work_letters.values():
        if wl["project_id"] == pid and wl["status"] in (
            "DRAFT", "PROPOSED", "COUNTERED", "ACCEPTED"
        ):
            wl["status"] = "WITHDRAWN"
            bump_version(wl)

    # --- PlanSubmissions: non-terminal -> REJECTED_FINAL (from PLAN_REVIEW onward) ---
    if from_status in (
        "PLAN_REVIEW", "PRE_CONSTRUCTION", "CONSTRUCTION", "PUNCH", "CLOSEOUT"
    ):
        for ps in store.plan_submissions.values():
            if ps["project_id"] == pid and ps["status"] in (
                "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUIRED"
            ):
                ps["status"] = "REJECTED_FINAL"
                bump_version(ps)

    # --- Engagements / Milestones / COs / Draws / Invoices (from PRE_CONSTRUCTION onward) ---
    if from_status in ("PRE_CONSTRUCTION", "CONSTRUCTION", "PUNCH", "CLOSEOUT"):
        # Engagements
        engagement_statuses = ("PROPOSED", "APPROVED")
        if from_status in ("CONSTRUCTION", "PUNCH", "CLOSEOUT"):
            engagement_statuses = ("PROPOSED", "APPROVED", "ACTIVE", "SUSPENDED")
        for eng in store.contractor_engagements.values():
            if eng["project_id"] == pid and eng["status"] in engagement_statuses:
                eng["status"] = "TERMINATED"
                bump_version(eng)

        # Milestones (only from CONSTRUCTION onward per scaffold)
        if from_status in ("CONSTRUCTION", "PUNCH", "CLOSEOUT"):
            eng_ids = {
                e["id"] for e in store.contractor_engagements.values()
                if e["project_id"] == pid
            }
            for m in store.schedule_milestones.values():
                if m["engagement_id"] in eng_ids and m["status"] in ("PLANNED", "CONFIRMED"):
                    m["status"] = "CANCELLED"
                    bump_version(m)

        # ChangeOrders
        for co in store.change_orders.values():
            if co["project_id"] != pid:
                continue
            if co["status"] in ("DRAFT", "SUBMITTED"):
                co["status"] = "REJECTED"
                bump_version(co)
            elif co["status"] == "APPROVED":
                co["status"] = "VOIDED"
                bump_version(co)
                # Compensation: recompute project cost
                calc.recompute_total_cost(project)

        # DisbursementRequests
        if from_status in ("CONSTRUCTION", "PUNCH", "CLOSEOUT"):
            for d in store.disbursement_requests.values():
                if d["project_id"] != pid:
                    continue
                if d["status"] in ("DRAFT", "SUBMITTED", "ON_HOLD"):
                    d["status"] = "VOIDED"
                    bump_version(d)
                elif d["status"] == "APPROVED":
                    d["status"] = "VOIDED"
                    bump_version(d)
            # Recompute allowance/retainage after voiding
            calc.recompute_allowance(project)
            calc.recompute_retainage(project)
            calc.recompute_posture(project)

        # OverageInvoices
        if from_status in ("CONSTRUCTION", "PUNCH", "CLOSEOUT"):
            for inv in store.overage_invoices.values():
                if inv["project_id"] == pid and inv["status"] in ("DRAFT", "ISSUED", "DISPUTED"):
                    inv["status"] = "VOID"
                    bump_version(inv)

    # --- LeaseSpace: UNDER_CONSTRUCTION -> LEASED ---
    if from_status in ("CONSTRUCTION", "PUNCH", "CLOSEOUT"):
        lease = store.leases.get(project["lease_id"])
        if lease:
            space = store.lease_spaces.get(lease["space_id"])
            if space and space["status"] == "UNDER_CONSTRUCTION":
                space["status"] = "LEASED"
                bump_version(space)


def maybe_terminate_lease(lease_id):
    """After project cancel, if all TIProjects of the lease are terminal, terminate lease."""
    lease = store.leases.get(lease_id)
    if not lease or lease["status"] != "ACTIVE":
        return
    projects = [
        p for p in store.ti_projects.values() if p["lease_id"] == lease_id
    ]
    if projects and all(p["status"] in ("COMPLETED", "CANCELLED") for p in projects):
        lease["status"] = "TERMINATED"
        bump_version(lease)
