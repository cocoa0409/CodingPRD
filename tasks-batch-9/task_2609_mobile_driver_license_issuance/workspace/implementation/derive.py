"""Derived counters, recomputed from the rows they count (PRD section 2.9).

Every counter the scaffold declares as ``count(...)`` or ``sum(...)`` is
computed here rather than incremented in place, which makes the conserved-
quantity invariants of section 2.9 hold by construction instead of by luck.
"""

from store import db

LIVE_CREDENTIAL_STATES = ("PENDING_PROVISION", "ACTIVE", "SUSPENDED")
DEVICE_SLOT_STATES = ("ATTESTED", "BOUND", "LOST_REPORTED")
OPEN_SESSION_STATES = ("REQUESTED", "CONSENT_PENDING", "CONSENT_GRANTED")


def credentials_of_holder(holder_id):
    return [c for c in db.credentials.values() if c["holder_id"] == holder_id]


def credentials_of_device(device_id):
    return [c for c in db.credentials.values() if c["device_id"] == device_id]


def deliveries_of_credential(credential_id):
    return [d for d in db.deliveries.values() if d["credential_id"] == credential_id]


def deliveries_of_order(order_id):
    return [d for d in db.deliveries.values() if d["update_order_id"] == order_id]


def entries_of_credential(credential_id):
    return [r for r in db.revocation_entries.values() if r["credential_id"] == credential_id]


def evidence_of_session(session_id):
    return [e for e in db.evidence.values() if e["proofing_session_id"] == session_id]


def reader_apps_of_verifier(verifier_id):
    return [a for a in db.reader_apps.values() if a["verifier_id"] == verifier_id]


def log_entries_of_verifier(verifier_id):
    return [e for e in db.log_entries.values() if e["verifier_id"] == verifier_id]


def log_entries_of_session(session_id):
    return [e for e in db.log_entries.values()
            if e["presentation_session_id"] == session_id]


def sessions_of_credential(credential_id):
    return [s for s in db.presentation_sessions.values()
            if s["credential_id"] == credential_id]


def sessions_of_reader_app(reader_app_id):
    return [s for s in db.presentation_sessions.values()
            if s["reader_app_id"] == reader_app_id]


# --------------------------------------------------------------------------
# Holder
# --------------------------------------------------------------------------
def active_credential_count(holder_id):
    return len([c for c in credentials_of_holder(holder_id)
                if c["lifecycle_state"] == "ACTIVE"])


def bound_device_count(holder_id):
    return len([d for d in db.devices.values()
                if d["holder_id"] == holder_id and d["state"] in DEVICE_SLOT_STATES])


def revoked_credential_count(holder_id):
    return len([c for c in credentials_of_holder(holder_id)
                if c["lifecycle_state"] == "REVOKED"])


# --------------------------------------------------------------------------
# Device
# --------------------------------------------------------------------------
def active_binding_count(device_id):
    device = db.devices.get(device_id)
    if device is not None and device["state"] == "WIPED":
        # PRD 3.6: a wipe sets the handset's binding count to zero outright.
        return 0
    return len([c for c in credentials_of_device(device_id)
                if c["lifecycle_state"] in LIVE_CREDENTIAL_STATES])


# --------------------------------------------------------------------------
# DigitalCredential
# --------------------------------------------------------------------------
def pending_update_count(credential_id):
    return len([d for d in deliveries_of_credential(credential_id)
                if d["status"] == "PENDING"])


def failed_delivery_count(credential_id):
    return len([d for d in deliveries_of_credential(credential_id)
                if d["status"] == "FAILED"])


def revocation_sequence(credential_id):
    entries = entries_of_credential(credential_id)
    if not entries:
        return 0
    return max(r["sequence"] for r in entries)


# --------------------------------------------------------------------------
# UpdateOrder
# --------------------------------------------------------------------------
def order_counts(order_id):
    children = deliveries_of_order(order_id)
    delivery_count = len([d for d in children if d["status"] != "SUPERSEDED"])
    delivered_count = len([d for d in children if d["status"] == "DELIVERED"])
    failed_count = len([d for d in children if d["status"] == "FAILED"])
    return delivery_count, delivered_count, failed_count


# --------------------------------------------------------------------------
# IdentityProofingSession
# --------------------------------------------------------------------------
def evidence_count(session_id):
    return len(evidence_of_session(session_id))


# --------------------------------------------------------------------------
# ReaderApp / Verifier
# --------------------------------------------------------------------------
def query_count(reader_app_id):
    return len([s for s in sessions_of_reader_app(reader_app_id)
                if s["state"] == "COMPLETED"])


def volume_discount_pct(reader_app_id):
    return 0.10 if query_count(reader_app_id) >= 250 else 0.00


def open_session_count(verifier_id):
    total = 0
    for app in reader_apps_of_verifier(verifier_id):
        total += len([s for s in sessions_of_reader_app(app["id"])
                      if s["state"] in OPEN_SESSION_STATES])
    return total


def billable_query_balance_cents(verifier_id):
    return sum(e["billed_amount_cents"] for e in log_entries_of_verifier(verifier_id)
               if e["billing_state"] == "BILLED")


def listed_reader_app_count():
    return len([a for a in db.reader_apps.values() if a["trust_state"] == "LISTED"])
