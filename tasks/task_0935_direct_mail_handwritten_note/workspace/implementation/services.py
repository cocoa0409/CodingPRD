"""Shared side-effect machinery: the ledger, the three cascades, resource
release, proof expiry and job piece-count refresh."""
import calc
import derive
import store
from errors import ApiError
from model import new_row, touch
from store import db


# ------------------------------------------------------------------ ledger
def append_ledger(account_id, entry_type, amount_cents, reason,
                  campaign_id=None, mail_job_id=None):
    signed = amount_cents if entry_type in ("TOPUP", "REFUND") else -amount_cents
    balance_after = derive.account_balance(account_id) + signed
    row = new_row({
        "account_id": account_id,
        "mail_job_id": mail_job_id,
        "campaign_id": campaign_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "signed_amount_cents": signed,
        "balance_after_cents": balance_after,
        "reason": reason,
    }, common=False)
    db.ledger_entries[row["id"]] = row
    return row


# ------------------------------------------------------------- proof expiry
def materialize_proof_expiry(proof):
    """PRD 3.5: once the logical clock reaches or passes `expires_at` an
    APPROVED proof becomes EXPIRED.  The boundary is inclusive."""
    if proof["status"] != "APPROVED" or proof["expires_at"] is None:
        return proof
    if store.now() >= proof["expires_at"]:
        proof["status"] = "EXPIRED"
        touch(proof)
    return proof


def approval_gate(job):
    """Rungs 24 and 25, in that order, over the job's proofs."""
    proofs = derive.job_proofs(job["id"])
    for p in proofs:
        materialize_proof_expiry(p)
    ever_approved = [p for p in proofs if p["approved_at"] is not None]
    if not ever_approved:
        raise ApiError("ERR_PROOF_NOT_APPROVED")
    latest = max(ever_approved, key=lambda p: (p["approved_at"], p["id"]))
    if latest["status"] != "APPROVED":
        raise ApiError("ERR_PROOF_APPROVAL_STALE")
    template = db.templates.get(latest["template_id"])
    if template is None or latest["pinned_template_version"] != template["version_no"]:
        raise ApiError("ERR_PROOF_APPROVAL_STALE")
    if latest["expires_at"] is None or not store.now() < latest["expires_at"]:
        raise ApiError("ERR_PROOF_APPROVAL_STALE")
    return latest


# ------------------------------------------------------------ job resources
def void_run(run):
    """Return the run's ink and release its machine-day slot-minutes."""
    run["status"] = "VOIDED"
    touch(run)
    lot = db.ink_lots.get(run["ink_lot_id"])
    if lot is not None:
        lot["remaining_ul"] = lot["remaining_ul"] + run["planned_ink_ul"]
        if lot["status"] == "DEPLETED" and lot["remaining_ul"] > store.INK_SAFETY_RESERVE_UL:
            lot["status"] = "OPEN"
        touch(lot)
    # Machine slot-minutes are derived from the non-VOIDED runs on the bucket,
    # so the release is complete once the run leaves that set.


def unschedule_step(step):
    step["status"] = "PENDING"
    step["computed_mail_date"] = None
    step["computed_in_home_date"] = None
    step["shifted_days"] = 0
    touch(step)


def refresh_job_counts(job, variant):
    automation, retail, unmailable, eddm, billable = calc.job_piece_counts(job, variant)
    tier = calc.presort_tier_selection(job, automation)
    return {
        "automation_piece_count": automation,
        "retail_piece_count": retail,
        "unmailable_piece_count": unmailable,
        "eddm_piece_count": eddm,
        "billable_piece_count": billable,
        "presort_tier": tier,
    }


def write_job_counts(job, counts):
    for key, value in counts.items():
        job[key] = value


# --------------------------------------------------------------- CASCADE A
def cascade_a(template):
    """PRD 3.2's seven hops, run atomically with the template edit."""
    template["version_no"] = template["version_no"] + 1                     # hop 1
    superseded = []
    for proof in list(db.proofs.values()):                                   # hop 2
        if proof["template_id"] == template["id"] and proof["status"] == "APPROVED":
            proof["status"] = "SUPERSEDED"
            touch(proof)
            superseded.append(proof)
    job_ids = []
    for proof in superseded:
        if proof["mail_job_id"] not in job_ids:
            job_ids.append(proof["mail_job_id"])
    for job_id in job_ids:                                                   # hop 3
        job = db.mail_jobs.get(job_id)
        if job is None or job["status"] not in ("PROOFED", "SCHEDULED", "COMMITTED"):
            continue
        previous = job["status"]
        job["status"] = "DRAFT"
        job["pinned_template_version"] = None
        if previous in ("SCHEDULED", "COMMITTED"):
            job["mail_date"] = None
            job["blackout_shifted_days"] = 0
            job["scheduled_at"] = None
        for run in derive.job_runs(job_id):                                  # hops 4-5
            if run["status"] == "RESERVED":
                void_run(run)
        if previous == "COMMITTED":                                          # hop 6
            amount = job["drawn_postage_cents"]
            campaign = db.campaigns.get(job["campaign_id"])
            account_id = campaign["account_id"] if campaign else None
            if amount and account_id:
                append_ledger(account_id, "REFUND", amount, "template edit refund",
                              campaign_id=job["campaign_id"], mail_job_id=job_id)
            job["drawn_postage_cents"] = 0
        for step in list(db.drip_steps.values()):                            # hop 7
            if step["mail_job_id"] == job_id and step["status"] == "SCHEDULED":
                unschedule_step(step)
        touch(job)


# --------------------------------------------------------------- CASCADE C
def cascade_c(campaign):
    """PRD 3.9's four hops on a billing close."""
    campaign["billing_status"] = "CLOSED"                                    # hop 1
    campaign["lifecycle_status"] = "COMPLETED"
    touch(campaign)
    closed_job_ids = []
    for job in derive.campaign_jobs(campaign["id"]):                         # hop 2
        if job["status"] != "MAILED":
            continue
        job["status"] = "CLOSED"
        returned_record_ids = set(e["list_record_id"] for e in db.return_events.values()
                                  if e["mail_job_id"] == job["id"])
        for record in db.list_records.values():
            if record.get("last_mail_job_id") != job["id"]:
                continue
            if record["mail_status"] != "MAILED":
                continue
            if record["id"] in returned_record_ids:
                continue
            record["mail_status"] = "DELIVERED_ASSUMED"
            touch(record)
        touch(job)
        closed_job_ids.append(job["id"])
    for step in list(db.drip_steps.values()):                                # hop 3
        if step["mail_job_id"] in closed_job_ids and step["status"] in (
                "PENDING", "SCHEDULED", "RELEASED"):
            step["status"] = "CANCELLED"
            touch(step)
    for schedule in list(db.drip_schedules.values()):                        # hop 4
        if schedule["campaign_id"] != campaign["id"]:
            continue
        if schedule["status"] == "ACTIVE" and derive.schedule_step_count(schedule["id"]) == 0:
            schedule["status"] = "CANCELLED"
            touch(schedule)
