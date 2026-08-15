"""Program lifecycle and ops-run checkpoint."""

from datetime import timedelta

import db
import errors
from services import credits, posture


def serialize_program(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "fiscal_year": p["fiscal_year"],
        "status": p["status"],
        "posture_contam_threshold": p["posture_contam_threshold"],
        "posture_complaint_threshold": p["posture_complaint_threshold"],
        "diversion_credit_rate": p["diversion_credit_rate"],
        "ops_run_index": p["ops_run_index"],
        "total_diverted_kg": p["total_diverted_kg"],
        "total_contamination_kg": p["total_contamination_kg"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def touch(entity):
    entity["updated_at"] = db.iso_now()
    entity["version"] = entity.get("version", 1) + 1


def recompute_program_totals(program):
    """total_diverted_kg = sum of final_net_kg over CONFIRMED (FINALLY_CREDITED)
    DropEvents in the program; total_contamination_kg = sum of contamination_kg
    over those same confirmed drops."""
    site_ids = {s["id"] for s in db.sites.values() if s["program_id"] == program["id"]}
    total_div = 0.0
    total_contam = 0.0
    for d in db.drops.values():
        if d["site_id"] in site_ids and d["credit_state"] == "FINALLY_CREDITED":
            total_div += float(d.get("final_net_kg") or 0)
            total_contam += float(d.get("contamination_kg") or 0)
    program["total_diverted_kg"] = db.round_kg(total_div)
    program["total_contamination_kg"] = db.round_kg(total_contam)


def run_ops(program):
    """Ops-run checkpoint (PRD §3.8):
    1. ops_run_index += 1
    2. Expire ACTIVE AccessGrants past expires_at (auto MINOR report if buckets out)
    3. Expire ACTIVE agreements past term_end (clear site link; posture recompute)
    4. Mark unresolved complaints past sla_due_at as sla_breached = true
    5. Expire bucket credits older than 365 days (FIFO)
    6. Recompute all site postures
    """
    now = db.clock_now()
    program["ops_run_index"] += 1

    # --- 1. Expire access grants ---
    for grant in list(db.grants.values()):
        if grant["status"] != "ACTIVE":
            continue
        participant = db.participants.get(grant["participant_id"])
        if not participant or participant["program_id"] != program["id"]:
            continue
        if now >= grant["expires_at"]:
            grant["status"] = "EXPIRED"
            touch(grant)
            if grant.get("buckets_checked_out", 0) > 0:
                site = db.sites.get(grant["site_id"])
                if site:
                    report = {
                        "id": db.new_id(),
                        "site_id": site["id"],
                        "drop_event_id": None,
                        "auditor_id": "system",
                        "severity": "MINOR",
                        "finding_note": "Auto-opened by ops run: access grant expired with buckets still checked out",
                        "feedback_sent_at": None,
                        "status": "OPEN",
                        "created_at": db.iso_now(),
                        "updated_at": db.iso_now(),
                        "version": 1,
                    }
                    db.contamination_reports[report["id"]] = report
                    site_posture_touch(site)

    # --- 2. Expire host agreements ---
    for agreement in list(db.host_agreements.values()):
        if agreement["program_id"] != program["id"]:
            continue
        if agreement["status"] != "ACTIVE":
            continue
        if now >= agreement["term_end"]:
            agreement["status"] = "EXPIRED"
            touch(agreement)
            site = db.sites.get(agreement["site_id"])
            if site and site.get("host_agreement_id") == agreement["id"]:
                site["host_agreement_id"] = None
                site_posture_touch(site)

    # --- 3. SLA breach marking ---
    for complaint in db.complaints.values():
        site = db.sites.get(complaint["site_id"])
        if not site or site["program_id"] != program["id"]:
            continue
        if complaint["status"] in ("OPEN", "ACKNOWLEDGED", "REOPENED"):
            if now >= complaint["sla_due_at"] and not complaint["sla_breached"]:
                complaint["sla_breached"] = True
                touch(complaint)

    # --- 4. Credit expiry ---
    for participant in db.participants.values():
        if participant["program_id"] != program["id"]:
            continue
        credits.expire_for_participant(participant["id"])

    # --- 5. Recompute all site postures ---
    for site in db.sites.values():
        if site["program_id"] == program["id"]:
            posture.recompute_site_posture(site)

    touch(program)
    recompute_program_totals(program)
    return program


def site_posture_touch(site):
    """Recompute posture and bump site version/timestamp (posture-affecting
    event)."""
    posture.recompute_site_posture(site)
    touch(site)
