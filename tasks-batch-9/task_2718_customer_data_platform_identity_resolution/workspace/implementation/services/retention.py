"""The four-step retention run and the daily hash-quota ledger reset."""

import db
from services import cascade, derive


def _expire_consent_records(now):
    expired = 0
    groups = set()
    for record in db.by_seq(db.all_of("consent_records")):
        if record["status"] != "ACTIVE":
            continue
        if record["expires_at"] is None or record["expires_at"] > now:
            continue
        record["status"] = "EXPIRED"
        record["precedence_rank"] = 0
        db.touch(record)
        expired += 1
        groups.add((record["profile_id"], record["channel"], record["purpose"]))
    for profile_id, channel, purpose in sorted(groups, key=lambda k: (k[1], k[2])):
        derive.rerank_consent_group(profile_id, channel, purpose)
    return expired


def _expire_suppression_entries(now):
    expired = 0
    subjects = []
    for entry in db.by_seq(db.all_of("suppression_entries")):
        if entry["status"] != "ACTIVE":
            continue
        if entry["expires_at"] is None or entry["expires_at"] > now:
            continue
        entry["status"] = "EXPIRED"
        db.touch(entry)
        expired += 1
        if entry["profile_id"] not in subjects:
            subjects.append(entry["profile_id"])
    for profile_id in subjects:
        profile = db.store["profiles"].get(profile_id)
        if profile is None:
            continue
        if derive.apply_privacy_status(profile):
            db.touch(profile)
    return expired


def _time_out_tasks(now):
    timed_out = 0
    parents = []
    for task in db.by_seq(db.all_of("vendor_deletion_tasks")):
        if task["status"] != "DISPATCHED":
            continue
        if task["ack_deadline_at"] is None or task["ack_deadline_at"] > now:
            continue
        task["status"] = "TIMED_OUT"
        db.touch(task)
        timed_out += 1
        if task["deletion_request_id"] not in parents:
            parents.append(task["deletion_request_id"])
    partially = 0
    for request_id in parents:
        request = db.store["deletion_requests"].get(request_id)
        if request is None or request["status"] != "PROPAGATING":
            continue
        counts = {"PENDING": 0, "DISPATCHED": 0, "ACKNOWLEDGED": 0, "FAILED": 0, "TIMED_OUT": 0}
        for task in db.all_of("vendor_deletion_tasks"):
            if task["deletion_request_id"] != request_id:
                continue
            counts[task["status"]] = counts.get(task["status"], 0) + 1
        if counts["PENDING"] + counts["DISPATCHED"] != 0:
            continue
        if counts["TIMED_OUT"] + counts["FAILED"] < 1:
            continue
        request["status"] = "PARTIALLY_VERIFIED"
        db.touch(request)
        partially += 1
    return timed_out, partially


def _expire_governance(now):
    expired = 0
    paused = 0
    for segment in db.by_seq(db.all_of("segments")):
        if segment["status"] != "APPROVED":
            continue
        if segment["governance_expires_at"] is None or segment["governance_expires_at"] > now:
            continue
        paused += cascade.expire_governance(segment)
        expired += 1
    return expired, paused


def _reset_quotas(now):
    today = db.date_str(now)
    reset = 0
    for destination in db.by_seq(db.all_of("destinations")):
        if destination["quota_reset_on"] == today:
            continue
        destination["remaining_daily_hash_quota"] = destination["daily_hash_quota"]
        destination["quota_reset_on"] = today
        db.touch(destination)
        reset += 1
    return reset


def run():
    now = db.now()
    expired_consent = _expire_consent_records(now)
    expired_suppression = _expire_suppression_entries(now)
    paused = cascade.audience_cascade()
    timed_out, partially = _time_out_tasks(now)
    governance_expired, governance_paused = _expire_governance(now)
    paused += governance_paused
    reset = _reset_quotas(now)
    return {
        "run_at": db.iso(now),
        "expired_consent_record_count": expired_consent,
        "expired_suppression_entry_count": expired_suppression,
        "timed_out_vendor_task_count": timed_out,
        "partially_verified_deletion_request_count": partially,
        "governance_expired_segment_count": governance_expired,
        "paused_activation_count": paused,
        "quota_reset_destination_count": reset,
    }
