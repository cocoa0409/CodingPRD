"""Ordered cascades, compensating actions and the append-only ledgers."""

import hashlib

import calc
import derive
from store import (
    active_profile_row,
    base_row,
    db,
    newest_snapshot,
    now,
    sort_rows,
    touch,
)

OPEN_SESSION_STATES = ("REQUESTED", "CONSENT_PENDING", "CONSENT_GRANTED")


# --------------------------------------------------------------------------
# trust-list pointer hops
# --------------------------------------------------------------------------
def _bump_pointer(mark_stale):
    profile = active_profile_row()
    if profile is None:
        return
    snapshot = newest_snapshot(profile)
    if snapshot is not None:
        if mark_stale:
            snapshot["revocation_pointer_stale"] = True
        snapshot["pending_delta_count"] += 1
        touch(snapshot)
    profile["pending_republish_count"] += 1
    touch(profile)


def pointer_stale_hop():
    """Hop fired by every appended RevocationEntry."""
    _bump_pointer(True)


def reader_set_changed_hop():
    """Hop fired when the trusted reader set changes (list / delist)."""
    _bump_pointer(False)


# --------------------------------------------------------------------------
# revocation ledger
# --------------------------------------------------------------------------
def append_revocation_entry(credential, status, reason):
    row = base_row("RevocationEntry", common_fields=False)
    row["credential_id"] = credential["id"]
    row["sequence"] = derive.revocation_sequence(credential["id"]) + 1
    row["status"] = status
    row["reason"] = reason
    row["effective_at"] = now()
    row["published"] = False
    db.revocation_entries[row["id"]] = row
    pointer_stale_hop()
    return row


# --------------------------------------------------------------------------
# presentation log
# --------------------------------------------------------------------------
def pseudonym(verifier, credential_id):
    seed = verifier["_salt"] + "|" + credential_id
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def verifier_of_session(session):
    app = db.reader_apps.get(session["reader_app_id"])
    if app is None:
        return None, None
    return db.verifiers.get(app["verifier_id"]), app


def append_log_entry(session, outcome, billed_amount_cents=0,
                     billing_state="UNBILLED", disclosed_element_count=0):
    verifier, _app = verifier_of_session(session)
    if verifier is None:
        return None
    subject = pseudonym(verifier, session["credential_id"])
    row = base_row("PresentationLogEntry", common_fields=False)
    row["presentation_session_id"] = session["id"]
    row["verifier_id"] = verifier["id"]
    row["credential_pseudonym"] = subject
    row["outcome"] = outcome
    row["disclosed_element_count"] = disclosed_element_count
    row["excess_element_count"] = session.get("excess_element_count", 0)
    row["retention_days_declared"] = session.get("retention_days", 0)
    row["billed_amount_cents"] = billed_amount_cents
    row["billing_state"] = billing_state
    row["recorded_at"] = now()
    earlier = [
        e for e in derive.log_entries_of_verifier(verifier["id"])
        if e["credential_pseudonym"] == subject and e["recorded_at"] < row["recorded_at"]
    ]
    row["pseudonym_reuse_index"] = len(earlier) + 1
    db.log_entries[row["id"]] = row
    return row


def abort_session(session, abort_reason):
    session["state"] = "ABORTED"
    session["abort_reason"] = abort_reason
    touch(session)
    append_log_entry(session, "ABORTED")


def abort_sessions_of_credential(credential, abort_reason):
    rows = [s for s in derive.sessions_of_credential(credential["id"])
            if s["state"] in OPEN_SESSION_STATES]
    for session in sort_rows(rows):
        abort_session(session, abort_reason)


def abort_sessions_of_reader_app(reader_app, abort_reason):
    rows = [s for s in derive.sessions_of_reader_app(reader_app["id"])
            if s["state"] in OPEN_SESSION_STATES]
    for session in sort_rows(rows):
        abort_session(session, abort_reason)


# --------------------------------------------------------------------------
# credential lifecycle helpers
# --------------------------------------------------------------------------
def suspend_credential(credential, suspend_reason, entry_status, entry_reason):
    credential["lifecycle_state"] = "SUSPENDED"
    credential["suspend_reason"] = suspend_reason
    touch(credential)
    append_revocation_entry(credential, entry_status, entry_reason)


def reinstate_credential(credential):
    credential["lifecycle_state"] = "ACTIVE"
    credential["suspend_reason"] = None
    touch(credential)
    append_revocation_entry(credential, "REINSTATED", "RECOVERY")


def revoke_credential(credential, entry_reason, abort_reason=None):
    credential["lifecycle_state"] = "REVOKED"
    credential["suspend_reason"] = None
    touch(credential)
    append_revocation_entry(credential, "REVOKED", entry_reason)
    if abort_reason is not None:
        abort_sessions_of_credential(credential, abort_reason)


# --------------------------------------------------------------------------
# lazy transitions
# --------------------------------------------------------------------------
def lazy_expire_credential(credential):
    """ACTIVE -> EXPIRED once the clock reaches valid_until."""
    if credential["lifecycle_state"] != "ACTIVE":
        return credential
    if now() < credential["valid_until"]:
        return credential
    credential["lifecycle_state"] = "EXPIRED"
    credential["suspend_reason"] = None
    touch(credential)
    append_revocation_entry(credential, "EXPIRED", "VALIDITY_LAPSED")
    return credential


def lazy_expire_proofing(session):
    """VERIFIED -> EXPIRED once the clock reaches assurance_expires_at."""
    if session["state"] != "VERIFIED":
        return session
    expires = session.get("assurance_expires_at")
    if expires is None or now() < expires:
        return session
    session["state"] = "EXPIRED"
    touch(session)
    return session


# --------------------------------------------------------------------------
# the five-hop propagation cascade (PRD 3.5)
# --------------------------------------------------------------------------
def open_update_order(holder, reason, payload_summary, target_address_version):
    # HOP 1 -- the order itself
    order = base_row("UpdateOrder")
    order["holder_id"] = holder["id"]
    order["reason"] = reason
    order["status"] = "OPEN"
    order["payload_summary"] = payload_summary
    order["target_address_version"] = target_address_version
    order["opened_at"] = now()
    order["closed_at"] = None
    db.update_orders[order["id"]] = order

    # HOP 2 -- one PENDING delivery per live credential, credential created_at ASC
    targets = [c for c in derive.credentials_of_holder(holder["id"])
               if c["lifecycle_state"] in ("ACTIVE", "SUSPENDED")]
    stale_orders = []
    for credential in sort_rows(targets):
        delivery = base_row("UpdateDelivery")
        delivery["update_order_id"] = order["id"]
        delivery["credential_id"] = credential["id"]
        delivery["status"] = "PENDING"
        delivery["attempt_count"] = 0
        delivery["failure_code"] = None
        delivery["delivered_at"] = None
        delivery["device_receipt_token"] = None
        delivery["resulting_doc_version"] = None
        db.deliveries[delivery["id"]] = delivery

        # an older PENDING delivery against the same credential is superseded
        for other in sort_rows(derive.deliveries_of_credential(credential["id"])):
            if other["id"] == delivery["id"] or other["status"] != "PENDING":
                continue
            if other["update_order_id"] == order["id"]:
                continue
            other["status"] = "SUPERSEDED"
            touch(other)
            older = db.update_orders.get(other["update_order_id"])
            if older is not None and older not in stale_orders:
                stale_orders.append(older)

        # HOP 3 -- the target credential's sync axis moves to UPDATE_PENDING
        credential["sync_state"] = "UPDATE_PENDING"
        touch(credential)

        # HOP 4 + HOP 5 -- in-flight presentations are aborted and logged
        abort_sessions_of_credential(credential, "CREDENTIAL_UPDATE_PENDING")

    for older in stale_orders:
        calc.rollup(older)

    calc.rollup(order)
    return order
