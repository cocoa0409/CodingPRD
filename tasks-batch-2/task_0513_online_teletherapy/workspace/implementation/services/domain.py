"""Core domain operations: cascades, system-driven transitions, license recompute, clock advance."""
from datetime import timedelta

from db import db, touch, light_create_fields
from clock import clock, parse_iso, iso_millis, iso_instant


# ---------------------------------------------------------------------------
# License status recompute
# ---------------------------------------------------------------------------
def recompute_license_status(lic):
    """A license is VALID only while clock < expires_on; REVOKED is sticky."""
    if lic["status"] == "REVOKED":
        return
    expires = parse_iso(lic["expires_on"])
    new_status = "VALID" if clock.now() < expires else "EXPIRED"
    if new_status != lic["status"]:
        lic["status"] = new_status
        touch(lic)


def recompute_all_licenses():
    for lic in db.licenses.values():
        recompute_license_status(lic)


def therapist_has_valid_license(therapist_id, state_code):
    for lic in db.licenses.values():
        if lic["therapist_id"] == therapist_id and lic["state_code"] == state_code:
            recompute_license_status(lic)
            if lic["status"] == "VALID":
                return True
    return False


# ---------------------------------------------------------------------------
# Therapist caseload bubbling
# ---------------------------------------------------------------------------
def therapist_increment_caseload(therapist):
    therapist["active_caseload"] += 1
    if therapist["status"] == "ACCEPTING" and therapist["active_caseload"] == therapist["max_active_caseload"]:
        therapist["status"] = "FULL"
    touch(therapist)


def therapist_decrement_caseload(therapist):
    if therapist["active_caseload"] > 0:
        therapist["active_caseload"] -= 1
    if therapist["status"] == "FULL" and therapist["active_caseload"] < therapist["max_active_caseload"]:
        therapist["status"] = "ACCEPTING"
    touch(therapist)


# ---------------------------------------------------------------------------
# Thread helpers
# ---------------------------------------------------------------------------
def thread_for_match(match_id):
    for t in db.threads.values():
        if t["match_id"] == match_id:
            return t
    return None


def create_thread_for_match(match_id):
    fields = {
        **_versioned_create(),
        "match_id": match_id,
        "status": "OPEN",
        "unread_for_therapist": 0,
    }
    db.threads[fields["id"]] = fields
    return fields


def _versioned_create():
    from db import common_create_fields
    return common_create_fields(versioned=True)


# ---------------------------------------------------------------------------
# Match ending (system-driven ACTIVE -> ENDED)
# ---------------------------------------------------------------------------
def end_match(match):
    """ACTIVE -> ENDED with caseload decrement and thread archive."""
    if match["status"] != "ACTIVE":
        return
    match["status"] = "ENDED"
    touch(match)
    therapist = db.therapists.get(match["therapist_id"])
    if therapist:
        therapist_decrement_caseload(therapist)
    thread = thread_for_match(match["id"])
    if thread and thread["status"] in ("OPEN", "FROZEN"):
        thread["status"] = "ARCHIVED"
        touch(thread)


# ---------------------------------------------------------------------------
# Client close cascade
# ---------------------------------------------------------------------------
def close_client(client):
    """ACTIVE/SUSPENDED -> CLOSED with full cascade."""
    if client["status"] not in ("ACTIVE", "SUSPENDED"):
        return
    client["status"] = "CLOSED"
    touch(client)
    # end all ACTIVE matches
    for m in db.matches.values():
        if m["client_id"] == client["id"] and m["status"] == "ACTIVE":
            end_match(m)
    # expire all AVAILABLE/RESERVED credits
    for sc in db.session_credits.values():
        if sc["client_id"] == client["id"] and sc["status"] in ("AVAILABLE", "RESERVED"):
            sc["status"] = "EXPIRED"
    # archive all OPEN/FROZEN threads owned by this client's matches
    client_match_ids = {m["id"] for m in db.matches.values() if m["client_id"] == client["id"]}
    for t in db.threads.values():
        if t["match_id"] in client_match_ids and t["status"] in ("OPEN", "FROZEN"):
            t["status"] = "ARCHIVED"
            touch(t)


def client_has_other_nonterminal_subscription(client_id, exclude_sub_id):
    for s in db.subscriptions.values():
        if s["client_id"] == client_id and s["id"] != exclude_sub_id:
            if s["status"] != "CANCELLED":
                return True
    return False


# ---------------------------------------------------------------------------
# Subscription finalize-cancel cascade
# ---------------------------------------------------------------------------
def finalize_subscription_cancel(sub):
    """CANCEL_SCHEDULED -> CANCELLED, cascade Client CLOSED."""
    sub["status"] = "CANCELLED"
    touch(sub)
    client = db.clients.get(sub["client_id"])
    if client and not client_has_other_nonterminal_subscription(client["id"], sub["id"]):
        close_client(client)


# ---------------------------------------------------------------------------
# Subscription resume (manual / system)
# ---------------------------------------------------------------------------
def resume_subscription(sub):
    sub["status"] = "ACTIVE"
    sub["pause_resumes_on"] = None
    sub["current_period_start"] = iso_instant(clock.now())
    touch(sub)


# ---------------------------------------------------------------------------
# Clock advance follow-on transitions
# ---------------------------------------------------------------------------
def advance_clock(new_dt):
    clock.set(new_dt)
    now = clock.now()
    # recompute license statuses
    recompute_all_licenses()
    # auto-resume PAUSED subscriptions whose pause_resumes_on <= clock
    for sub in list(db.subscriptions.values()):
        if sub["status"] == "PAUSED" and sub.get("pause_resumes_on"):
            if parse_iso(sub["pause_resumes_on"]) <= now:
                resume_subscription(sub)
    # auto-finalize CANCEL_SCHEDULED subscriptions whose cancel_effective_on <= clock
    for sub in list(db.subscriptions.values()):
        if sub["status"] == "CANCEL_SCHEDULED" and sub.get("cancel_effective_on"):
            if parse_iso(sub["cancel_effective_on"]) <= now:
                finalize_subscription_cancel(sub)
    # expire SessionCredits whose expires_on <= clock
    for sc in db.session_credits.values():
        if sc["status"] in ("AVAILABLE", "RESERVED") and sc.get("expires_on"):
            if parse_iso(sc["expires_on"]) <= now:
                sc["status"] = "EXPIRED"


def days_add(dt, days):
    return dt + timedelta(days=days)
