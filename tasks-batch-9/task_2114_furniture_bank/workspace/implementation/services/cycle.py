"""The operational cycle (PRD 2.6): six passes in a pinned order."""

from core import BED_BUG_REMEDIATION_DAYS, clock, days
from db import db, touch, sorted_by_creation, client_of_voucher, referral_of_voucher
from services.allocation import expire_voucher, run_allocation_round
from services.calc import recompute_agency_standing, waitlist_score

LIVE_VOUCHER_STATUSES = ("ISSUED", "PARTIALLY_ALLOCATED", "ALLOCATED")


def run_cycle(advance_quota_epoch):
    now = clock.now()
    summary = {
        "expired_referral_count": 0,
        "expired_voucher_count": 0,
        "released_inventory_count": 0,
        "promoted_waitlist_count": 0,
        "restanding_count": 0,
        "reinstated_client_count": 0,
        "quota_epoch_advanced": False,
    }

    # ---- Pass 1: referral expiry --------------------------------------
    for referral in sorted_by_creation(list(db.referrals.values())):
        if referral["status"] != "APPROVED":
            continue
        if referral["expires_at"] is None or not (referral["expires_at"] < now):
            continue
        referral["status"] = "EXPIRED"
        touch(referral)
        agency = db.agencies.get(referral["agency_id"])
        if agency is not None:
            agency["quota_used"] = max(agency["quota_used"] - 1, 0)
            touch(agency)
        summary["expired_referral_count"] += 1

    # ---- Pass 2: voucher expiry and stock release ----------------------
    for voucher in sorted_by_creation(list(db.vouchers.values())):
        if voucher["status"] not in LIVE_VOUCHER_STATUSES:
            continue
        referral = referral_of_voucher(voucher)
        if referral is None or referral["expires_at"] is None:
            continue
        if not (referral["expires_at"] < now):
            continue
        summary["released_inventory_count"] += expire_voucher(voucher)
        summary["expired_voucher_count"] += 1

    # ---- Pass 3: standing recompute over every agency ------------------
    agencies = sorted_by_creation(list(db.agencies.values()))
    for agency in agencies:
        recompute_agency_standing(agency)
    summary["restanding_count"] = len(agencies)

    # ---- Pass 3a: bed-bug remediation ---------------------------------
    for client in sorted_by_creation(list(db.clients.values())):
        if client["bed_bug_status"] != "CONFIRMED":
            continue
        confirmed_at = client["bed_bug_confirmed_at"]
        if confirmed_at is None:
            continue
        if now - confirmed_at >= days(BED_BUG_REMEDIATION_DAYS):
            client["bed_bug_status"] = "REMEDIATED"
            touch(client)

    # ---- Pass 3b: household reinstatement ------------------------------
    for client in sorted_by_creation(list(db.clients.values())):
        if client["status"] != "ON_HOLD":
            continue
        ban = client["delivery_ban_until"]
        if ban is not None and ban > now:
            continue
        if client["bed_bug_status"] == "CONFIRMED":
            continue
        client["status"] = "ACTIVE"
        client["no_show_strikes"] = 0
        touch(client)
        summary["reinstated_client_count"] += 1

    # ---- Pass 4: waitlist rescoring ------------------------------------
    for entry in sorted_by_creation(list(db.waitlist_entries.values())):
        if entry["status"] != "WAITING":
            continue
        line = db.voucher_lines.get(entry["voucher_line_id"])
        if line is None:
            continue
        voucher = db.vouchers.get(line["voucher_id"])
        if voucher is None:
            continue
        referral = referral_of_voucher(voucher)
        client = client_of_voucher(voucher)
        if referral is None or client is None:
            continue
        score = waitlist_score(referral, client, entry["waiting_since"])
        if entry["priority_score"] != score:
            entry["priority_score"] = score
            touch(entry)

    # ---- Pass 5: promotion --------------------------------------------
    waiting_voucher_ids = []
    for entry in sorted_by_creation(list(db.waitlist_entries.values())):
        if entry["status"] != "WAITING":
            continue
        line = db.voucher_lines.get(entry["voucher_line_id"])
        if line is None:
            continue
        if line["voucher_id"] not in waiting_voucher_ids:
            waiting_voucher_ids.append(line["voucher_id"])

    candidates = [db.vouchers[vid] for vid in waiting_voucher_ids if vid in db.vouchers]
    for voucher in sorted_by_creation(candidates):
        if voucher["status"] not in ("ISSUED", "PARTIALLY_ALLOCATED"):
            continue
        summary["promoted_waitlist_count"] += run_allocation_round(voucher)

    # ---- Pass 6: quota epoch advance ----------------------------------
    if advance_quota_epoch:
        for agency in agencies:
            agency["quota_epoch"] += 1
            agency["quota_used"] = 0
            touch(agency)
        summary["quota_epoch_advanced"] = True

    return summary
