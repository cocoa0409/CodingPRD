"""Derived / computed field helpers.

Every `source: computed` field in the scaffold is recomputed from its stated
source of truth here rather than cached independently.
"""
from store import db

MAILABLE_TIERS = ("AUTOMATION", "RETAIL")
SURVIVING_DEDUPE = ("UNSCREENED", "UNIQUE", "HOUSEHOLD_HEAD")
DUPLICATE_DEDUPE = ("DUP_EXACT", "DUP_HOUSEHOLD")


# ---------------------------------------------------------------- accounts
def account_ledger_rows(account_id):
    return [r for r in db.ledger_entries.values() if r["account_id"] == account_id]


def account_sum(account_id, entry_type):
    return sum(r["amount_cents"] for r in db.ledger_entries.values()
               if r["account_id"] == account_id and r["entry_type"] == entry_type)


def account_balance(account_id):
    """PRD 2.8: the balance IS the ledger."""
    total = 0
    for r in db.ledger_entries.values():
        if r["account_id"] != account_id:
            continue
        total += r["signed_amount_cents"]
    return total


# --------------------------------------------------------------- campaigns
def campaign_write_gate(campaign):
    if campaign["compliance_status"] == "HOLD" or campaign["billing_status"] == "CLOSED":
        return "FROZEN"
    return "OPEN"


def campaign_jobs(campaign_id):
    return [j for j in db.mail_jobs.values() if j["campaign_id"] == campaign_id]


def campaign_mailed_piece_count(campaign_id):
    return sum(j["billable_piece_count"] for j in db.mail_jobs.values()
               if j["campaign_id"] == campaign_id and j["status"] in ("MAILED", "CLOSED"))


def campaign_returned_piece_count(campaign_id):
    job_ids = set(j["id"] for j in db.mail_jobs.values() if j["campaign_id"] == campaign_id)
    return sum(1 for e in db.return_events.values() if e["mail_job_id"] in job_ids)


def campaign_ledger_sum(campaign_id, entry_type):
    return sum(r["amount_cents"] for r in db.ledger_entries.values()
               if r["campaign_id"] == campaign_id and r["entry_type"] == entry_type)


# ------------------------------------------------------------ mailing list
def list_records_of(mailing_list_id):
    return [r for r in db.list_records.values() if r["mailing_list_id"] == mailing_list_id]


def list_counts(mailing_list_id):
    """Partition counters for a mailing list.

    # Adjudication of friction 1: unmailable-first precedence — the campaign
    # deliverability report (PRD 3.9/2.10) is explicitly unmailable-first, and
    # taking the same precedence here is what makes the list's own declared
    # partition invariant (automation + retail + unmailable + duplicate ==
    # record_count) hold unconditionally rather than only on lists with no
    # overlap.  Under the literal-independent reading that declared invariant
    # would be unreachable on any list holding a record that is both
    # UNMAILABLE and a duplicate.
    """
    rows = list_records_of(mailing_list_id)
    automation = retail = unmailable = duplicate = 0
    for r in rows:
        if r["deliverability_tier"] == "UNMAILABLE":
            unmailable += 1
        elif r["dedupe_status"] in DUPLICATE_DEDUPE:
            duplicate += 1
        elif r["deliverability_tier"] == "AUTOMATION" and r["dedupe_status"] in SURVIVING_DEDUPE:
            automation += 1
        elif r["deliverability_tier"] == "RETAIL" and r["dedupe_status"] in SURVIVING_DEDUPE:
            retail += 1
    return {
        "record_count": len(rows),
        "automation_count": automation,
        "retail_count": retail,
        "unmailable_count": unmailable,
        "duplicate_count": duplicate,
        "mailable_count": automation + retail,
    }


def record_keys(record):
    exact = "|".join([
        (record["first_name"] or "").strip().lower(),
        (record["last_name"] or "").strip().lower(),
        (record["address_line1"] or "").strip().lower(),
        record["zip5"] or "",
    ])
    household = "|".join([
        (record["last_name"] or "").strip().lower(),
        (record["address_line1"] or "").strip().lower(),
        record["zip5"] or "",
    ])
    return exact, household


def record_reprint_count(record):
    """Scaffold: fulfilled reprints for this record within the campaign of its
    last mail job.

    # Adjudication of friction 9: reprint_count is a PER-CAMPAIGN figure,
    # evaluated against the cited campaign each time.  That reading keeps
    # strictly more declared behaviour reachable — the cap error stays
    # reachable inside one campaign, and a record mailed under two campaigns
    # can still be reprinted once in each, which the single-running-counter
    # reading makes impossible.
    """
    job_id = record.get("last_mail_job_id")
    if not job_id:
        return 0
    job = db.mail_jobs.get(job_id)
    if not job:
        return 0
    return reprint_count_in_campaign(record["id"], job["campaign_id"])


def reprint_count_in_campaign(list_record_id, campaign_id):
    return sum(1 for r in db.reprint_requests.values()
               if r["list_record_id"] == list_record_id
               and r["campaign_id"] == campaign_id
               and r["status"] == "FULFILLED")


# ------------------------------------------------------------- mail jobs
def job_routes(mail_job_id):
    return [r for r in db.eddm_routes.values() if r["mail_job_id"] == mail_job_id]


def job_runs(mail_job_id):
    return [r for r in db.production_runs.values() if r["mail_job_id"] == mail_job_id]


def job_proofs(mail_job_id):
    return [p for p in db.proofs.values() if p["mail_job_id"] == mail_job_id]


def job_returned_piece_count(mail_job_id):
    return sum(1 for e in db.return_events.values() if e["mail_job_id"] == mail_job_id)


def job_refunded_postage_cents(mail_job_id):
    return sum(r["amount_cents"] for r in db.ledger_entries.values()
               if r["mail_job_id"] == mail_job_id and r["entry_type"] == "REFUND")


def job_campaign(job):
    return db.campaigns.get(job["campaign_id"])


def job_account_id(job):
    campaign = db.campaigns.get(job["campaign_id"])
    return campaign["account_id"] if campaign else None


# --------------------------------------------------------------- drip
def schedule_steps(drip_schedule_id):
    return [s for s in db.drip_steps.values() if s["drip_schedule_id"] == drip_schedule_id]


def schedule_step_count(drip_schedule_id):
    return sum(1 for s in schedule_steps(drip_schedule_id) if s["status"] != "CANCELLED")


# --------------------------------------------------------------- ink lots
def lot_remaining_ul(lot):
    """Scaffold ink_lot_conservation: initial volume less non-voided draws."""
    drawn = sum(r["planned_ink_ul"] for r in db.production_runs.values()
                if r["ink_lot_id"] == lot["id"]
                and r["status"] in ("RESERVED", "RUNNING", "COMPLETED", "FAILED"))
    return lot["initial_volume_ul"] - drawn


def machine_day_committed_minutes(machine_id, run_date, exclude_run_id=None):
    total = 0
    for r in db.production_runs.values():
        if r["machine_id"] != machine_id or r["run_date"] != run_date:
            continue
        if exclude_run_id is not None and r["id"] == exclude_run_id:
            continue
        if r["status"] in ("RESERVED", "RUNNING", "COMPLETED", "FAILED"):
            total += r["planned_slot_minutes"]
    return total
