"""Shared cascade mechanics (PRD 2.10, 2.11 and the cascades of PRD 3)."""

from db import db, make_record, sort_records, touch
from services import calc


# --- subscriber ledgers --------------------------------------------------
def refresh_risk_operational(subscriber_id):
    """Recompute risk_score_operational; only a genuine change is a mutation."""
    if subscriber_id is None:
        return
    subscriber = db.subscribers.get(subscriber_id)
    if subscriber is None:
        return
    value = calc.recompute_risk_operational(subscriber_id)
    if subscriber["risk_score_operational"] != value:
        subscriber["risk_score_operational"] = value
        touch(subscriber)


def adjust_pending_revocations(subscriber, delta):
    """Move revocation_pending_count and apply the suspension threshold."""
    if subscriber is None:
        return
    subscriber["revocation_pending_count"] = max(0, subscriber["revocation_pending_count"] + delta)
    touch(subscriber)
    count = subscriber["revocation_pending_count"]
    if delta > 0:
        if count >= 2 and subscriber["account_status"] == "ACTIVE":
            subscriber["account_status"] = "SUSPENDED"
            subscriber["suspended_at"] = db.now()
            touch(subscriber)
    elif delta < 0:
        if count < 2 and subscriber["account_status"] == "SUSPENDED":
            subscriber["account_status"] = "ACTIVE"
            subscriber["suspended_at"] = None
            touch(subscriber)


# --- profile posture ----------------------------------------------------
def block_ready_requests(profile):
    pending = [
        r for r in db.requests.values()
        if r["profile_id"] == profile["id"] and r["state"] == "READY_TO_ISSUE"
    ]
    for req in sort_records(pending):
        req["state"] = "ISSUANCE_BLOCKED"
        req["blocked_reason"] = "PROFILE_STATUS_SERVICE_OVERDUE"
        touch(req)


def release_blocked_requests(profile):
    blocked = [
        r for r in db.requests.values()
        if r["profile_id"] == profile["id"] and r["state"] == "ISSUANCE_BLOCKED"
    ]
    for req in sort_records(blocked):
        req["state"] = "READY_TO_ISSUE"
        req["blocked_reason"] = None
        touch(req)


def record_revocation_on_profile(profile):
    """Profile-side ledger of one executed revocation, plus the posture flip."""
    if profile is None:
        return
    profile["revoked_certificate_count"] += 1
    profile["pending_crl_entry_count"] += 1
    touch(profile)
    if (
        profile["status_service_posture"] == "NOMINAL"
        and profile["pending_crl_entry_count"] >= profile["crl_trigger_threshold"]
    ):
        profile["status_service_posture"] = "CRL_OVERDUE"
        touch(profile)
        block_ready_requests(profile)


# --- revocation requests ------------------------------------------------
def new_revocation_request(cert, profile, reason_code, origin, user_id, state,
                           incident_id=None, evidence_ref=None, executed_at=None):
    now = db.now()
    record = make_record({
        "certificate_id": cert["id"],
        "incident_id": incident_id,
        "reason_code": reason_code,
        "evidence_ref": evidence_ref,
        "state": state,
        "origin": origin,
        "requested_by_user_id": user_id,
        "requested_at": now,
        "deadline_at": calc.revocation_deadline(now, reason_code, incident_id is not None, profile),
        "deadline_breached": False,
        "executed_at": executed_at,
        "denied_at": None,
        "denial_reason": None,
        "superseded_at": None,
    })
    db.revocation_requests[record["id"]] = record
    return record


def supersede_other_open_requests(cert, keep_id):
    others = [
        r for r in db.revocation_requests.values()
        if r["certificate_id"] == cert["id"] and r["id"] != keep_id and r["state"] == "REQUESTED"
    ]
    for req in sort_records(others):
        req["state"] = "SUPERSEDED"
        req["superseded_at"] = db.now()
        touch(req)


# --- domain authorization invalidation ----------------------------------
def cascade_invalidated_authorization(auth):
    affected = [
        r for r in db.requests.values()
        if auth["id"] in (r.get("consumed_authorization_ids") or [])
        and r["state"] in ("READY_TO_ISSUE", "ISSUANCE_BLOCKED")
    ]
    for req in sort_records(affected):
        held = list(req.get("consumed_authorization_ids") or [])
        req["state"] = "SUBMITTED"
        req["validation_cleared_by_user_id"] = None
        req["validation_cleared_at"] = None
        req["projected_not_before"] = None
        req["projected_not_after"] = None
        req["projected_charge_cents"] = None
        req["blocked_reason"] = None
        req["consumed_authorization_ids"] = []
        touch(req)
        for auth_id in held:
            other = db.authorizations.get(auth_id)
            if other is None:
                continue
            other["reuse_count"] = max(0, other["reuse_count"] - 1)
            if other["id"] != auth["id"]:
                touch(other)


# --- attestation repudiation (four hops) --------------------------------
def cascade_revoke_attestation(ceremony):
    now = db.now()
    partition = db.partitions.get(ceremony["partition_id"])

    # Hop one: the ceremony loses its attestation.
    ceremony["state"] = "ATTESTATION_REVOKED"
    ceremony["attestation_revoked_at"] = now
    touch(ceremony)
    if partition is not None:
        partition["attested_ceremony_count"] = max(
            0, partition["attested_ceremony_count"] - 1
        )

    # Hop two: the partition is quarantined for good.
    if partition is not None:
        if partition["state"] == "OPERATIONAL":
            partition["state"] = "QUARANTINED"
            partition["quarantined_at"] = now
        partition["attested_ceremony_count"] = sum(
            1 for c in db.ceremonies.values()
            if c["partition_id"] == partition["id"] and c["state"] == "ATTESTED"
        )
        touch(partition)

    # Hop three: every certificate signed on any ceremony of that partition.
    if partition is None:
        return
    ceremony_ids = set(
        c["id"] for c in db.ceremonies.values() if c["partition_id"] == partition["id"]
    )
    targets = [
        c for c in db.certificates.values()
        if c["ceremony_id"] in ceremony_ids and c["revocation_status"] == "NONE"
    ]
    for cert in sort_records(targets):
        cert["revocation_status"] = "REVOCATION_PENDING"
        touch(cert)
        profile = db.profiles.get(cert["profile_id"])
        new_revocation_request(
            cert,
            profile,
            "KEY_COMPROMISE",
            "SYSTEM_CASCADE",
            "system",
            "REQUESTED",
            incident_id=None,
            evidence_ref="ceremony:%s" % ceremony["id"],
        )
        # Hop four: the owning subscriber's pending ledger and suspension.
        adjust_pending_revocations(db.subscribers.get(cert["subscriber_id"]), 1)
