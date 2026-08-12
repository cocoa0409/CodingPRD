"""Cross-entity business logic: recomputes and cascade side effects."""

from core import db, now, touch
import calc


def contractor_events(contractor_id):
    return [e for e in db.safety_events.values()
            if e["contractor_id"] == contractor_id]


def contractor_score(contractor_id, variant):
    return calc.safety_score(contractor_events(contractor_id), variant, now())


def refresh_contractor_score(contractor):
    """Stored score uses the default ROLLING_12MO variant; per-terminal
    variants are computed on demand at qualification/scheduling time."""
    contractor["safety_score"] = float(contractor_score(
        contractor["id"], "ROLLING_12MO"))
    touch(contractor)


def recompute_shipped_solids(job):
    """shipped_solids_kg = manifested kg over DELIVERED/RECONCILED shipments
    + residual_sludge_kg. While RTS_PENDING, a broken balance reverts the job
    to FLUSH_VERIFIED (the RTS gate is not sticky)."""
    total = job["residual_sludge_kg"] or 0
    for sh in db.waste_shipments.values():
        if sh["job_id"] == job["id"] and sh["status"] in ("DELIVERED", "RECONCILED"):
            total += sh["manifested_kg"]
    changed = total != job["shipped_solids_kg"]
    job["shipped_solids_kg"] = total
    if job["status"] == "RTS_PENDING":
        terminal = db.terminals.get(job["terminal_id"])
        if terminal is not None and not calc.mass_balance_passes(job, terminal):
            job["status"] = "FLUSH_VERIFIED"
            changed = True
    if changed:
        touch(job)


def recompute_waste_cost(job):
    """waste_cost_cents = sum of disposal costs over RECONCILED shipments."""
    total = 0
    for sh in db.waste_shipments.values():
        if sh["job_id"] == job["id"] and sh["status"] == "RECONCILED":
            total += sh["disposal_cost_cents"]
    if total != job["waste_cost_cents"]:
        job["waste_cost_cents"] = total
        touch(job)


def pause_job(job, reason):
    """PAUSED records the held status and cause; SCHEDULED inspections cancel."""
    job["paused_from"] = job["status"]
    job["pause_reason"] = reason
    job["status"] = "PAUSED"
    touch(job)
    for insp in db.inspections.values():
        if insp["job_id"] == job["id"] and insp["status"] == "SCHEDULED":
            insp["status"] = "CANCELLED"
            touch(insp)


def cert_death_cascade(cert, reason):
    """Shared revoke/expiry cascade (PRD §3.6):
    permits anchored to the dead cert ISSUED/ACTIVE -> SUSPENDED;
    job PAUSED when a suspended permit remains and nothing is open;
    job -> GAS_FREE_PENDING when nothing was ever open;
    SCHEDULED inspections of a PAUSED job -> CANCELLED."""
    for p in db.entry_permits.values():
        if p["cert_id"] == cert["id"] and p["status"] in ("ISSUED", "ACTIVE"):
            p["status"] = "SUSPENDED"
            touch(p)
    job = db.cleaning_jobs.get(cert["job_id"])
    if job is None:
        return
    if job["status"] in ("GAS_FREE_CERTIFIED", "ENTRY_IN_PROGRESS", "ENTRY_COMPLETE"):
        job_permits = [p for p in db.entry_permits.values()
                       if p["job_id"] == job["id"]]
        has_open = any(p["status"] in ("ISSUED", "ACTIVE") for p in job_permits)
        has_suspended = any(p["status"] == "SUSPENDED" for p in job_permits)
        if has_suspended and not has_open:
            pause_job(job, reason)
        elif not has_open and not has_suspended \
                and job["status"] == "GAS_FREE_CERTIFIED":
            job["status"] = "GAS_FREE_PENDING"
            touch(job)


def permit_suspend_cascade(permit):
    """Suspending the job's last open (ISSUED/ACTIVE) permit pauses the job."""
    job = db.cleaning_jobs.get(permit["job_id"])
    if job is None:
        return
    job_permits = [p for p in db.entry_permits.values()
                   if p["job_id"] == job["id"]]
    if any(p["status"] in ("ISSUED", "ACTIVE") for p in job_permits):
        return
    if job["status"] in ("GAS_FREE_CERTIFIED", "ENTRY_IN_PROGRESS"):
        pause_job(job, "MANUAL")


def accepted_inspection(job_id):
    """The most recent ACCEPTED inspection for the job (drives rework/flush/RTS)."""
    cands = [i for i in db.inspections.values()
             if i["job_id"] == job_id and i["status"] == "ACCEPTED"]
    if not cands:
        return None
    return max(cands, key=lambda i: i["_seq"])


def findings_of(inspection_id):
    return [f for f in db.findings.values()
            if f["inspection_id"] == inspection_id]


def sweep_clock():
    """Runs on every clock advance (PRD §2.5): cert expiry sweep first,
    then window OVERRUN sweep."""
    now_dt = db.clock
    for cert in list(db.gas_free_certs.values()):
        if cert["status"] == "VALID" and cert["expires_at"] <= now_dt:
            cert["status"] = "EXPIRED"
            touch(cert)
            cert_death_cascade(cert, "CERT_EXPIRED")
    for w in list(db.service_windows.values()):
        if w["status"] == "PLANNED" and w["planned_end"] <= now_dt:
            w["status"] = "OVERRUN"
            touch(w)
        elif w["status"] == "ACTIVE" and w["planned_end"] <= now_dt:
            job = db.cleaning_jobs.get(w["job_id"]) if w["job_id"] else None
            if job is None or job["status"] != "RETURNED_TO_SERVICE":
                w["status"] = "OVERRUN"
                touch(w)
