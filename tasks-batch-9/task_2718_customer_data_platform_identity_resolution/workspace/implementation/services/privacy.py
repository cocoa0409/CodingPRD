"""Suppression windows, erasure requests, vendor fan-out and the tombstone bubble."""

from datetime import timedelta

import db
from services import cascade, derive

SYSTEM_ACTOR = "system"


# ------------------------------------------------------ suppression entries

def create_suppression(profile, entry_type, reason_code, effective_at, expires_at,
                       actor_id, deletion_request_id=None):
    entry = db.new_entity(
        "suppression_entries",
        profile_id=profile["id"],
        deletion_request_id=deletion_request_id,
        entry_type=entry_type,
        reason_code=reason_code,
        effective_at=effective_at,
        expires_at=expires_at,
        status="ACTIVE",
        created_by_user_id=actor_id,
        released_by_user_id=None,
        released_at=None,
    )
    derive.apply_privacy_status(profile)
    db.touch(profile)
    cascade.audience_cascade()
    return entry


def release_suppression(entry, profile, actor_id):
    entry["status"] = "RELEASED"
    entry["released_by_user_id"] = actor_id
    entry["released_at"] = db.now()
    db.touch(entry)
    derive.apply_privacy_status(profile)
    db.touch(profile)
    if entry["entry_type"] == "LEGAL_HOLD" and not derive.has_active_legal_hold(profile["id"]):
        cascade.unblock_deletion_requests(profile["id"])
    cascade.audience_cascade()
    return entry


def windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) intersection; a null end runs forever."""
    if a_end is not None and a_end <= b_start:
        return False
    if b_end is not None and b_end <= a_start:
        return False
    return True


def has_window_conflict(profile_id, entry_type, effective_at, expires_at):
    for entry in derive.profile_suppressions(profile_id):
        if entry["entry_type"] != entry_type or entry["status"] != "ACTIVE":
            continue
        if windows_overlap(effective_at, expires_at, entry["effective_at"], entry["expires_at"]):
            return True
    return False


# --------------------------------------------------------- erasure requests

def open_request_for(profile_id):
    for request in db.all_of("deletion_requests"):
        if request["profile_id"] == profile_id \
                and request["status"] in derive.OPEN_DELETION_STATUSES:
            return request
    return None


def create_deletion_request(profile, request_origin, requester_reference, actor_id):
    request = db.new_entity(
        "deletion_requests",
        profile_id=profile["id"],
        request_origin=request_origin,
        requester_reference=requester_reference,
        status="RECEIVED",
        propagated_at=None,
        verified_at=None,
        blocked_reason=None,
    )
    profile["privacy_status"] = "DELETION_PENDING"
    db.touch(profile)
    db.new_entity(
        "suppression_entries",
        profile_id=profile["id"],
        deletion_request_id=request["id"],
        entry_type="PRIVACY_DELETE",
        reason_code="PRIVACY_DELETE",
        effective_at=db.now(),
        expires_at=None,
        status="ACTIVE",
        created_by_user_id=SYSTEM_ACTOR,
        released_by_user_id=None,
        released_at=None,
    )
    cascade.audience_cascade(re_derive_rates=True)
    return request


def request_tasks(request_id):
    return db.by_seq([
        t for t in db.all_of("vendor_deletion_tasks")
        if t["deletion_request_id"] == request_id
    ])


def qualifying_destinations():
    result = []
    for destination in db.by_seq(db.all_of("destinations")):
        if destination["status"] != "ACTIVE":
            continue
        delivered = any(
            a["destination_id"] == destination["id"] and a["status"] != "DRAFT"
            for a in db.all_of("activations")
        )
        if delivered:
            result.append(destination)
    result.sort(key=lambda d: (d["created_at"], d["_seq"]))
    return result


def active_legal_hold_entry(profile_id):
    entries = [
        e for e in derive.profile_suppressions(profile_id)
        if e["entry_type"] == "LEGAL_HOLD" and e["status"] == "ACTIVE"
    ]
    entries.sort(key=lambda e: (e["created_at"], e["_seq"]))
    return entries[0] if entries else None


def _dispatch_task(task, destination):
    task["status"] = "DISPATCHED"
    task["dispatched_at"] = db.now()
    task["ack_deadline_at"] = db.now() + timedelta(hours=destination["deletion_ack_sla_hours"])
    db.touch(task)


def propagate(request, profile):
    if request["status"] == "PARTIALLY_VERIFIED":
        for task in request_tasks(request["id"]):
            if task["status"] not in ("TIMED_OUT", "FAILED"):
                continue
            destination = db.store["destinations"].get(task["destination_id"])
            task["attempt_count"] += 1
            if destination is not None:
                _dispatch_task(task, destination)
            else:
                task["status"] = "DISPATCHED"
                task["dispatched_at"] = db.now()
                db.touch(task)
        request["status"] = "PROPAGATING"
        request["propagated_at"] = db.now()
        db.touch(request)
        return request

    destinations = qualifying_destinations()
    if not destinations:
        request["status"] = "VERIFIED"
        request["verified_at"] = db.now()
        db.touch(request)
        cascade.tombstone_profile(profile)
        return request

    for destination in destinations:
        task = db.new_entity(
            "vendor_deletion_tasks",
            deletion_request_id=request["id"],
            destination_id=destination["id"],
            status="PENDING",
            dispatched_at=None,
            ack_deadline_at=None,
            acknowledged_at=None,
            deletion_evidence_reference=None,
            acknowledged_record_count=None,
            attempt_count=1,
        )
        _dispatch_task(task, destination)
    request["status"] = "PROPAGATING"
    request["propagated_at"] = db.now()
    db.touch(request)
    return request


def task_counts(request_id):
    counts = {"PENDING": 0, "DISPATCHED": 0, "ACKNOWLEDGED": 0, "FAILED": 0, "TIMED_OUT": 0}
    total = 0
    for task in db.all_of("vendor_deletion_tasks"):
        if task["deletion_request_id"] != request_id:
            continue
        total += 1
        counts[task["status"]] = counts.get(task["status"], 0) + 1
    return total, counts


def acknowledge(task, outcome, evidence_reference, acknowledged_record_count):
    if outcome == "ACKNOWLEDGED":
        task["status"] = "ACKNOWLEDGED"
        task["acknowledged_at"] = db.now()
    else:
        task["status"] = "FAILED"
    if evidence_reference is not None:
        task["deletion_evidence_reference"] = evidence_reference
    if acknowledged_record_count is not None:
        task["acknowledged_record_count"] = acknowledged_record_count
    db.touch(task)
    request = db.store["deletion_requests"].get(task["deletion_request_id"])
    if request is not None:
        bubble_up(request)
    return task


def bubble_up(request):
    """Compound status: all children acknowledged verifies the request and tombstones."""
    if request["status"] not in ("PROPAGATING", "PARTIALLY_VERIFIED"):
        return False
    total, counts = task_counts(request["id"])
    if total == 0 or counts["ACKNOWLEDGED"] != total:
        return False
    request["status"] = "VERIFIED"
    request["verified_at"] = db.now()
    db.touch(request)
    profile = db.store["profiles"].get(request["profile_id"])
    if profile is not None:
        cascade.tombstone_profile(profile)
    return True
