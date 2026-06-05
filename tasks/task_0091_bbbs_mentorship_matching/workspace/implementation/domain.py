"""Domain logic: derived-field recomputation, state-machine bubble-ups, and the
closure cascade. (PRD §3, SCAFFOLD §1.2.)

These helpers operate on raw records in db.* and use store.touch to keep
updated_at/version coherent whenever a mutation (direct or cascaded) touches an
entity.
"""
import db
import calc
import clock
import store
from util import floor_days


# ---------------------------------------------------------------------------
# Derived-field recomputation
# ---------------------------------------------------------------------------

def recompute_volunteer_active_match_count(volunteer):
    """active_match_count = number of Matches referencing this volunteer whose
    relationship_status is in {INTRODUCED, ACTIVE} (SCAFFOLD entity note).

    Note: the PRD describes active_match_count as 1 while a match is held
    (CONFIRMED through ACTIVE) and 0 once closed. We follow the PRD's prose:
    the count is incremented to 1 when a Match is created in CONFIRMED and
    dropped to 0 when the match closes. We therefore count matches that are not
    CLOSED.
    """
    count = 0
    for m in db.matches.values():
        if m["volunteer_id"] == volunteer["id"] and m["relationship_status"] != "CLOSED":
            count += 1
    volunteer["active_match_count"] = count
    return count


def matches_for_volunteer(volunteer_id):
    return [m for m in db.matches.values() if m["volunteer_id"] == volunteer_id]


def matches_for_child(child_id):
    return [m for m in db.matches.values() if m["child_id"] == child_id]


def checks_for_volunteer(volunteer_id):
    return [c for c in db.background_checks.values() if c["volunteer_id"] == volunteer_id]


def contacts_for_match(match_id):
    return [c for c in db.supervision_contacts.values() if c["match_id"] == match_id]


def activities_for_match(match_id):
    return [a for a in db.activity_logs.values() if a["match_id"] == match_id]


def meetings_for_match(match_id):
    return [m for m in db.match_meetings.values() if m["match_id"] == match_id]


def recompute_volunteer_cleared(volunteer):
    """cleared_check_id points at the CRIMINAL check id while all three checks
    are jointly valid (CLEARED and now < valid_until); null otherwise
    (PRD §3.2 / calc background_check_validity)."""
    checks = checks_for_volunteer(volunteer["id"])
    by_type = {}
    for c in checks:
        # latest check per type wins (re-screening replaces older cycles).
        # The test clock can be pinned, so multiple cycles' checks may share an
        # identical created_at; tie-break on _seq (true insertion order) so the
        # freshest re-screen cycle's check is the one selected, never a stale
        # prior cycle's check.
        prev = by_type.get(c["check_type"])
        if prev is None or (c["created_at"], c["_seq"]) > (prev["created_at"], prev["_seq"]):
            by_type[c["check_type"]] = c
    required = {"CRIMINAL", "DMV", "CHILD_ABUSE_REGISTRY"}
    now = clock.now()
    if not required.issubset(by_type.keys()):
        volunteer["cleared_check_id"] = None
        return None
    all_valid = True
    for t in required:
        c = by_type[t]
        if c["status"] != "CLEARED" or c["valid_until"] is None or not (now < c["valid_until"]):
            all_valid = False
            break
    if all_valid:
        volunteer["cleared_check_id"] = by_type["CRIMINAL"]["id"]
    else:
        volunteer["cleared_check_id"] = None
    return volunteer["cleared_check_id"]


def recompute_match_activity_rollups(match):
    """total_mentoring_minutes and last_activity_at from LOGGED activities."""
    acts = [a for a in activities_for_match(match["id"]) if a["status"] == "LOGGED"]
    match["total_mentoring_minutes"] = sum(a["duration_minutes"] for a in acts)
    if acts:
        match["last_activity_at"] = max(a["occurred_at"] for a in acts)
    else:
        match["last_activity_at"] = None


def recompute_match_contact_rollup(match):
    """last_contact_at = latest COMPLETED SupervisionContact.contacted_at."""
    completed = [
        c for c in contacts_for_match(match["id"])
        if c["status"] == "COMPLETED" and c["contacted_at"] is not None
    ]
    if completed:
        match["last_contact_at"] = max(c["contacted_at"] for c in completed)
    else:
        match["last_contact_at"] = None


def compliance_status(match):
    """Derive GREEN | AMBER | RED at read time against the current clock
    (PRD §3.6 / calc match_compliance_status)."""
    if match["relationship_status"] != "ACTIVE":
        return "GREEN"
    now = clock.now()
    activated_at = match["activated_at"]
    contact_ref = match["last_contact_at"] or activated_at
    activity_ref = match["last_activity_at"] or activated_at
    days_since_contact = floor_days(now, contact_ref)
    days_since_activity = floor_days(now, activity_ref)

    has_missed = any(c["status"] == "MISSED" for c in contacts_for_match(match["id"]))

    if days_since_contact > calc.RED_CONTACT_DAYS or has_missed:
        return "RED"
    if days_since_contact > calc.AMBER_CONTACT_DAYS or days_since_activity > calc.AMBER_ACTIVITY_DAYS:
        return "AMBER"
    return "GREEN"


# ---------------------------------------------------------------------------
# Volunteer screening bubble-ups (SCAFFOLD Volunteer / BackgroundCheck SMs)
# ---------------------------------------------------------------------------

def on_check_cleared(volunteer):
    """If all three of the volunteer's latest checks are CLEARED & valid, bubble
    SCREENING -> ELIGIBLE and set cleared_check_id to the CRIMINAL check id."""
    if volunteer["status"] != "SCREENING":
        return
    cleared_id = recompute_volunteer_cleared(volunteer)
    if cleared_id is not None:
        volunteer["status"] = "ELIGIBLE"
        store.touch(volunteer)


def on_check_flagged(volunteer):
    """A FLAGGED check drives the volunteer SCREENING -> SCREENING_FAILED and runs
    the compensation cascade: decline any OFFERED proposal naming this volunteer,
    reverting that child to WAITLISTED (PRD §3.1)."""
    if volunteer["status"] != "SCREENING":
        return
    volunteer["status"] = "SCREENING_FAILED"
    volunteer["cleared_check_id"] = None
    store.touch(volunteer)
    # Compensation: decline any still-OFFERED proposal naming this volunteer.
    for prop in list(db.match_proposals.values()):
        if prop["volunteer_id"] == volunteer["id"] and prop["status"] == "OFFERED":
            prop["status"] = "DECLINED"
            store.touch(prop)
            child = db.children.get(prop["child_id"])
            if child is not None:
                revert_child_after_offer_gone(child)


# ---------------------------------------------------------------------------
# Child proposal-state bubble-ups (SCAFFOLD Child SM)
# ---------------------------------------------------------------------------

def child_open_proposal(child):
    for prop in db.match_proposals.values():
        if prop["child_id"] == child["id"] and prop["status"] == "OFFERED":
            return prop
    return None


def revert_child_after_offer_gone(child):
    """A child reverts PROPOSED -> WAITLISTED once it has no remaining OFFERED
    proposal (PRD §3.4), clearing open_proposal_id."""
    if child_open_proposal(child) is None:
        if child["status"] == "PROPOSED":
            child["status"] = "WAITLISTED"
            child["open_proposal_id"] = None
            store.touch(child)
        else:
            # keep open_proposal_id coherent regardless
            if child.get("open_proposal_id") is not None:
                child["open_proposal_id"] = None
                store.touch(child)


# ---------------------------------------------------------------------------
# Match closure cascade (PRD §3.7, SCAFFOLD Match exit transitions)
# ---------------------------------------------------------------------------

def close_match(match, exit_type, closed_from_status):
    """Close a match: set relationship_status CLOSED and closure_reason; cascade
    OPEN contacts -> MISSED; if closed out of INTRODUCED, SCHEDULED meetings ->
    NO_SHOW; bubble volunteer MATCHED -> ELIGIBLE and child per closure reason."""
    match["relationship_status"] = "CLOSED"
    match["closure_reason"] = exit_type
    store.touch(match)

    # Cascade: every still-OPEN supervision contact -> MISSED
    for c in contacts_for_match(match["id"]):
        if c["status"] == "OPEN":
            c["status"] = "MISSED"
            store.touch(c)

    # Cascade: SCHEDULED meetings -> NO_SHOW only when closed out of INTRODUCED
    if closed_from_status == "INTRODUCED":
        for m in meetings_for_match(match["id"]):
            if m["status"] == "SCHEDULED":
                m["status"] = "NO_SHOW"
                store.touch(m)

    # Bubble volunteer MATCHED -> ELIGIBLE (active_match_count drops to 0)
    volunteer = db.volunteers.get(match["volunteer_id"])
    if volunteer is not None:
        recompute_volunteer_active_match_count(volunteer)
        if volunteer["status"] == "MATCHED" and volunteer["active_match_count"] == 0:
            volunteer["status"] = "ELIGIBLE"
        store.touch(volunteer)

    # Bubble child per closure reason
    child = db.children.get(match["child_id"])
    if child is not None and child["status"] == "MATCHED":
        if exit_type == "EARLY_TERMINATION":
            child["status"] = "WAITLISTED"
        else:  # SUCCESSFUL_CLOSURE
            child["status"] = "INACTIVE"
        store.touch(child)


# ---------------------------------------------------------------------------
# Supervision-contact sweeps on clock advance (PRD §3.2 / §3.6)
# ---------------------------------------------------------------------------

def sweep_expiry_and_overdue():
    """Fired by /_clock/set_current_utc: expire CLEARED checks past valid_until
    and sweep stale OPEN supervision contacts to MISSED."""
    now = clock.now()

    # BackgroundCheck CLEARED -> EXPIRED when now >= valid_until
    expired_volunteers = set()
    for c in db.background_checks.values():
        if c["status"] == "CLEARED" and c["valid_until"] is not None and now >= c["valid_until"]:
            c["status"] = "EXPIRED"
            store.touch(c)
            expired_volunteers.add(c["volunteer_id"])
    for vid in expired_volunteers:
        v = db.volunteers.get(vid)
        if v is not None:
            recompute_volunteer_cleared(v)

    # SupervisionContact OPEN -> MISSED when now > due_at AND a newer OPEN
    # contact already exists for the same match (SCAFFOLD SupervisionContact SM).
    by_match = {}
    for c in db.supervision_contacts.values():
        by_match.setdefault(c["match_id"], []).append(c)
    for match_id, contacts in by_match.items():
        open_contacts = [c for c in contacts if c["status"] == "OPEN"]
        if len(open_contacts) < 2:
            continue
        # newest by created_at, tie-broken by true insertion order (_seq) so a
        # pinned clock never makes the choice depend on the random id.
        newest = max(open_contacts, key=lambda c: (c["created_at"], c["_seq"]))
        for c in open_contacts:
            if c is newest:
                continue
            if now > c["due_at"]:
                c["status"] = "MISSED"
                store.touch(c)
