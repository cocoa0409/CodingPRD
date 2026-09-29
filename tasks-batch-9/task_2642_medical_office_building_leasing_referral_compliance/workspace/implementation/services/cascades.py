"""The two deep cascades: lease termination (depth 4) and invoice delinquency
(depth 3). See PRD Sections 3.5 and 3.7."""

from db import by_creation, clock_date, db, touch
from services import calc
from services.compliance import open_case


def _subleases_of(master_id):
    return by_creation([l for l in db.leases.values() if l["master_lease_id"] == master_id])


def terminate_lease(lease, reason, note=None, settle_dependents=True):
    building = db.buildings[lease["building_id"]]
    suite = db.suites[lease["suite_id"]]
    today = clock_date()

    # --- Hop 1: the lease releases its suite -----------------------------
    lease["status"] = "TERMINATED"
    lease["termination_reason"] = reason
    lease["terminated_on"] = today
    if note is not None:
        lease["termination_note"] = note
    suite["occupancy_status"] = "VACANT"
    suite["last_vacated_on"] = today
    touch(suite)

    # --- Hop 2: the building's tenant mix is re-derived -------------------
    previous_posture = building["tenant_mix_posture"]
    new_posture = calc.recompute_building_mix(building)
    touch(building)

    if settle_dependents:
        # --- Hop 3: only when hop 2 moved the posture to RESTRICTED ------
        suspended = []
        if previous_posture != "RESTRICTED" and new_posture == "RESTRICTED":
            for peer in calc.leases_of_building(building["id"]):
                if peer["id"] == lease["id"]:
                    continue
                if peer["status"] not in ("DRAFT", "PENDING_FMV_REVIEW"):
                    continue
                tenant = db.tenants.get(peer["tenant_id"])
                if tenant is None or tenant["affiliation"] not in calc.ANCHOR_AFFILIATIONS:
                    continue
                was = peer["status"]
                peer["status"] = "SUSPENDED_MIX_REVIEW"
                peer["fmv_certification_status"] = "NOT_STARTED"
                if was == "PENDING_FMV_REVIEW":
                    peer["fmv_submitted_by_user_id"] = None
                touch(peer)
                suspended.append(peer)

        # --- Hop 4: only when hop 3 suspended at least one lease ---------
        for peer in suspended:
            for project in calc.projects_of_lease(peer["id"]):
                if project["status"] in ("DESIGN", "IN_REVIEW", "PERMITTED"):
                    project["on_hold_from_status"] = project["status"]
                    project["status"] = "ON_HOLD"
                    touch(project)

        # --- The terminating lease's own dependents ----------------------
        for alloc in calc.allocations_of_lease(lease["id"]):
            if alloc["status"] == "ACTIVE":
                alloc["status"] = "REVOKED"
                alloc["revoked_on"] = today
                touch(alloc)
        calc.recompute_parking_pool(building)

        for booking in calc.bookings_of_lease(lease["id"]):
            if booking["status"] == "BOOKED":
                booking["status"] = "CANCELLED"
                booking["cancellation_source"] = "LEASE_TERMINATION"
                touch(booking)

        lease["after_hours_authorized"] = False

        if lease["lease_type"] == "MASTER":
            for sublease in _subleases_of(lease["id"]):
                if sublease["status"] in ("EXECUTED", "ACTIVE", "HOLDOVER"):
                    # A cascaded sublease runs its own hop 1 and hop 2 only.
                    terminate_lease(sublease, reason, None, settle_dependents=False)

    touch(lease)
    return lease


def flag_invoice_delinquent(invoice):
    lease = db.leases[invoice["lease_id"]]
    tenant = db.tenants[lease["tenant_id"]]

    # --- Hop 1: freeze the aging figures --------------------------------
    days = calc.live_days_past_due(invoice)
    invoice["status"] = "DELINQUENT"
    invoice["days_past_due"] = max(0, days)
    invoice["days_past_due_at_flag"] = days
    invoice["delinquency_tier_weight"] = calc.delinquency_tier_weight(days)

    # --- Hop 2: the tenant's scores move -------------------------------
    tenant["delinquency_event_count"] += 1
    rolling, strict = calc.risk_scores(tenant["id"])
    tenant["referral_compliance_risk_score"] = rolling
    tenant["strict_cumulative_risk_score"] = strict
    touch(tenant)

    # --- Hop 3: watch flag plus an automatic case ----------------------
    if rolling >= calc.RISK_SCORE_WATCH_THRESHOLD:
        tenant["compliance_watch_status"] = "WATCH"
        open_case(
            tenant,
            "RENT_DELINQUENCY",
            "ROLLING_12M",
            rolling,
            "system",
            "Automatic rent-delinquency case raised by the arrears cascade on invoice %s."
            % invoice["id"],
        )
        # --- Hop 3b: the tenant's whole lease book and future bookings ---
        for peer in calc.leases_of_tenant(tenant["id"]):
            if peer["status"] in calc.CLOSED_LEASE_STATUSES:
                continue
            peer["rent_concession_locked"] = True
            peer["after_hours_authorized"] = False
            touch(peer)
            for booking in calc.bookings_of_lease(peer["id"]):
                if booking["status"] == "BOOKED" and booking["window_start"] > db.clock:
                    booking["status"] = "CANCELLED"
                    booking["cancellation_source"] = "COMPLIANCE_CASCADE"
                    touch(booking)

    touch(invoice)
    return invoice
