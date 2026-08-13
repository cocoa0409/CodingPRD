"""Shared domain services: cascades, counter ledgers, consent helpers."""
import db

# ---------------------------------------------------------------------------
# Consent / reportable
# ---------------------------------------------------------------------------

def has_granted_consent(client_id, scope):
    return any(c for c in db.all_of("consents")
               if c["client_id"] == client_id and c["scope"] == scope
               and c["status"] == "GRANTED")


def recompute_reportable(client_id):
    """reportable == holds a GRANTED DATA_REPORTING consent. Touch on change."""
    client = db.get("clients", client_id)
    if client is None:
        return
    new_val = has_granted_consent(client_id, "DATA_REPORTING")
    if client.get("reportable") != new_val:
        client["reportable"] = new_val
        db.touch(client)


# ---------------------------------------------------------------------------
# Organization slot ledger
# ---------------------------------------------------------------------------

def org_slot_delta(org, delta):
    org["referral_slots_used"] = org.get("referral_slots_used", 0) + delta
    org["referral_slots_open"] = org["referral_capacity"] - org[
        "referral_slots_used"]
    db.touch(org)


# ---------------------------------------------------------------------------
# Referral suspension cascade (privacy seal / consent revoke+expiry)
# ---------------------------------------------------------------------------

def cancel_linked_appointments(referral):
    """m3b: cancel REQUESTED/CONFIRMED appointments tied to the referral."""
    for appt in db.all_of("appointments"):
        if appt.get("referral_id") == referral["id"] and appt["status"] in (
                "REQUESTED", "CONFIRMED"):
            appt["status"] = "CANCELLED"
            appt["cancelled_by_system"] = True
            db.touch(appt)


def suspend_referral(referral, reason):
    """Move one referral to SUSPENDED with slot release + appt cascade."""
    prior = referral["status"]
    referral["status"] = "SUSPENDED"
    referral["suspension_reason"] = reason
    db.touch(referral)
    if prior in ("SENT", "ACCEPTED"):
        org = db.get("organizations", referral["organization_id"])
        if org is not None:
            org_slot_delta(org, -1)
    cancel_linked_appointments(referral)


def seal_case_cascade(case):
    """m2/m3a/m3b: suspend DRAFT/SENT/ACCEPTED referrals (CASE_SEALED)."""
    for ref in db.all_of("referrals"):
        if ref["case_id"] == case["id"] and ref["status"] in (
                "DRAFT", "SENT", "ACCEPTED"):
            suspend_referral(ref, "CASE_SEALED")


def referral_share_cascade(client_id):
    """Consent revocation/expiry: suspend SENT/ACCEPTED referrals of the
    client's cases (CONSENT_REVOKED), release slots, cancel appointments."""
    case_ids = {c["id"] for c in db.all_of("cases")
                if c["client_id"] == client_id}
    for ref in db.all_of("referrals"):
        if ref["case_id"] in case_ids and ref["status"] in (
                "SENT", "ACCEPTED"):
            suspend_referral(ref, "CONSENT_REVOKED")


# ---------------------------------------------------------------------------
# Program seat ledger
# ---------------------------------------------------------------------------

def program_sync_signage(program):
    """Auto OPEN<->FULL signage; never touches a CLOSED program."""
    if program["status"] in ("OPEN", "FULL"):
        program["status"] = ("FULL"
                             if program["enrolled_count"] >= program["capacity"]
                             else "OPEN")


# ---------------------------------------------------------------------------
# Workshop session counters
# ---------------------------------------------------------------------------

def session_recount(session):
    """Derived counters: enrolled_count / waitlist_count / open_seats."""
    enrolled = sum(1 for w in db.all_of("wk_enrollments")
                   if w["session_id"] == session["id"]
                   and w["status"] == "ENROLLED")
    waitlisted = sum(1 for w in db.all_of("wk_enrollments")
                     if w["session_id"] == session["id"]
                     and w["status"] == "WAITLISTED")
    session["enrolled_count"] = enrolled
    session["waitlist_count"] = waitlisted
    session["open_seats"] = session["capacity"] - enrolled
