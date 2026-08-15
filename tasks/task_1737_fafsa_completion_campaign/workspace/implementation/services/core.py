"""Core business logic: projections, cascades, calculations, selectors.

Everything cross-entity lives here so routes stay thin. Ordering of checks
follows PRD §2.9 validation precedence.
"""

from datetime import timezone
from decimal import Decimal, ROUND_HALF_UP

import dates
import errors
from db import store, make_common, touch

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CAPABILITIES = {"EVENT_STAFF", "AID_EXPERT", "CASE_SPECIALIST"}
CONSENT_SCOPES = {"STATUS_DETAIL", "OUTREACH", "DATA_SHARE"}
GRANTED_BY = {"PARENT", "ADULT_STUDENT"}
EFC_BANDS = {"LOW", "MID", "HIGH"}
AID_STATUSES = {"STARTED", "SUBMITTED", "VERIFICATION_SELECTED", "COMPLETE"}
ASSIGNED_ROLES = {"VOLUNTEER", "EXPERT"}
CASE_TYPES = {"VERIFICATION_FOLLOWUP", "SPECIAL_CIRCUMSTANCE"}
REPORT_VARIANTS = {"SUBMISSION_BASED", "PROCESSED_BASED"}
BACKGROUND_RESULTS = {"CLEARED", "EXPIRED"}

DOC_TEMPLATES = {
    "DEPENDENT_STANDARD": ["STUDENT_ID", "STUDENT_TAX_RETURN", "PARENT_TAX_RETURN", "BANK_STATEMENT"],
    "INDEPENDENT_STANDARD": ["STUDENT_ID", "STUDENT_TAX_RETURN", "DEPENDENCY_OVERRIDE_FORM"],
}
WAIVABLE_DOC_TYPES = {"BANK_STATEMENT", "DEPENDENCY_OVERRIDE_FORM"}

ACTIVE_CASE_STATUSES = {"OPEN", "IN_REVIEW", "AWAITING_FAMILY", "ESCALATED"}
NON_TERMINAL_CASE_STATUSES = {"OPEN", "IN_REVIEW", "AWAITING_FAMILY", "ESCALATED", "PAUSED"}
NON_TERMINAL_LINK_STATUSES = {"SUGGESTED", "AUTO_CONFIRMED", "CONFIRMED"}
NON_TERMINAL_ASSIGNMENT_STATUSES = {"INVITED", "ACCEPTED", "CONFIRMED"}

W_DOB = Decimal("0.40")
W_NAME = Decimal("0.35")
W_SCHOOL = Decimal("0.15")
W_DISTRICT = Decimal("0.10")

VENUE_BUFFER_MINUTES = 30


# ---------------------------------------------------------------------------
# Lookups with not-found errors
# ---------------------------------------------------------------------------

def get_campaign_or_404(cid):
    c = store.campaigns.get(cid)
    if c is None:
        errors.raise_error(errors.ERR_CAMPAIGN_NOT_FOUND, "Campaign not found")
    return c


def get_school_or_404(sid):
    s = store.schools.get(sid)
    if s is None:
        errors.raise_error(errors.ERR_SCHOOL_NOT_FOUND, "School not found")
    return s


def get_staff_or_404(pid):
    p = store.staff_profiles.get(pid)
    if p is None:
        errors.raise_error(errors.ERR_STAFF_PROFILE_NOT_FOUND, "Staff profile not found")
    return p


def get_senior_or_404(sid):
    s = store.senior_records.get(sid)
    if s is None:
        errors.raise_error(errors.ERR_SENIOR_RECORD_NOT_FOUND, "Senior record not found")
    return s


def get_aid_record_or_404(aid):
    a = store.aid_records.get(aid)
    if a is None:
        errors.raise_error(errors.ERR_AID_RECORD_NOT_FOUND, "Aid record not found")
    return a


def get_match_link_or_404(lid):
    l = store.match_links.get(lid)
    if l is None:
        errors.raise_error(errors.ERR_MATCH_LINK_NOT_FOUND, "Match link not found")
    return l


def get_consent_or_404(cid):
    c = store.consent_records.get(cid)
    if c is None:
        errors.raise_error(errors.ERR_CONSENT_RECORD_NOT_FOUND, "Consent record not found")
    return c


def get_event_or_404(eid):
    e = store.events.get(eid)
    if e is None:
        errors.raise_error(errors.ERR_EVENT_NOT_FOUND, "Event not found")
    return e


def get_assignment_or_404(aid):
    a = store.staff_assignments.get(aid)
    if a is None:
        errors.raise_error(errors.ERR_STAFF_ASSIGNMENT_NOT_FOUND, "Staff assignment not found")
    return a


def get_registration_or_404(rid):
    r = store.event_registrations.get(rid)
    if r is None:
        errors.raise_error(errors.ERR_EVENT_REGISTRATION_NOT_FOUND, "Event registration not found")
    return r


def get_checklist_or_404(cid):
    c = store.checklists.get(cid)
    if c is None:
        errors.raise_error(errors.ERR_CHECKLIST_NOT_FOUND, "Document checklist not found")
    return c


def get_checklist_item_or_404(iid):
    i = store.checklist_items.get(iid)
    if i is None:
        errors.raise_error(errors.ERR_CHECKLIST_ITEM_NOT_FOUND, "Checklist item not found")
    return i


def get_case_or_404(cid):
    c = store.support_cases.get(cid)
    if c is None:
        errors.raise_error(errors.ERR_SUPPORT_CASE_NOT_FOUND, "Support case not found")
    return c


def get_report_or_404(rid):
    r = store.completion_reports.get(rid)
    if r is None:
        errors.raise_error(errors.ERR_COMPLETION_REPORT_NOT_FOUND, "Completion report not found")
    return r


# ---------------------------------------------------------------------------
# Cross-aggregate helpers
# ---------------------------------------------------------------------------

def campaign_of_senior(senior):
    school = store.schools.get(senior["school_id"])
    return store.campaigns.get(school["campaign_id"]) if school else None


def campaign_of_event(event):
    school = store.schools.get(event["school_id"])
    return store.campaigns.get(school["campaign_id"]) if school else None


def school_of_senior(senior):
    return store.schools.get(senior["school_id"])


# ---------------------------------------------------------------------------
# Consent / visibility
# ---------------------------------------------------------------------------

def senior_has_granted_scope(senior_id, scope):
    for c in store.consent_records.values():
        if (
            c["senior_record_id"] == senior_id
            and c["status"] == "GRANTED"
            and scope in c["scopes"]
        ):
            return True
    return False


def any_granted_consent(senior_id):
    for c in store.consent_records.values():
        if c["senior_record_id"] == senior_id and c["status"] == "GRANTED":
            return True
    return False


def recompute_visibility(senior):
    new = "NORMAL" if senior_has_granted_scope(senior["id"], "STATUS_DETAIL") else "RESTRICTED"
    if senior["data_visibility"] != new:
        senior["data_visibility"] = new
        touch(senior)
    return senior["data_visibility"]


# ---------------------------------------------------------------------------
# Staff counters / thresholds
# ---------------------------------------------------------------------------

def recompute_staff_counters(profile):
    """Recompute confirmed_hours_total, no_show_count, active_case_count exactly."""
    total = Decimal("0")
    no_shows = 0
    for a in store.staff_assignments.values():
        if a["staff_profile_id"] != profile["id"]:
            continue
        if a["status"] in ("CONFIRMED", "CHECKED_IN"):
            total += Decimal(str(a["duration_hours"]))
        elif a["status"] == "NO_SHOW":
            no_shows += 1
    profile["confirmed_hours_total"] = float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    profile["no_show_count"] = no_shows

    active = 0
    for c in store.support_cases.values():
        if c["assigned_specialist_id"] == profile["id"] and c["status"] in ACTIVE_CASE_STATUSES:
            active += 1
    profile["active_case_count"] = active


def evaluate_overload(profile):
    """Flip ACTIVE <-> OVERLOADED based on active_case_count vs max_caseload.
    Never touches SUSPENDED."""
    if profile["status"] == "SUSPENDED":
        return
    campaign = store.campaigns.get(profile["campaign_id"])
    if campaign is None:
        return
    limit = campaign["max_caseload"]
    if profile["status"] == "ACTIVE" and profile["active_case_count"] > limit:
        profile["status"] = "OVERLOADED"
        touch(profile)
    elif profile["status"] == "OVERLOADED" and profile["active_case_count"] <= limit:
        profile["status"] = "ACTIVE"
        touch(profile)


def bump_case_count(profile_id, delta):
    profile = store.staff_profiles.get(profile_id)
    if profile is None:
        return
    profile["active_case_count"] = profile.get("active_case_count", 0) + delta
    touch(profile)
    evaluate_overload(profile)


def suspend_staff_contagion(profile):
    """ACTIVE/OVERLOADED -> SUSPENDED with contagion cascade (§3.2)."""
    if profile["status"] == "SUSPENDED":
        return
    profile["status"] = "SUSPENDED"
    touch(profile)
    now = store.clock_now
    for a in store.staff_assignments.values():
        if a["staff_profile_id"] != profile["id"]:
            continue
        if a["status"] not in ("INVITED", "ACCEPTED", "CONFIRMED"):
            continue
        event = store.events.get(a["event_id"])
        if event is None:
            continue
        start = dates.parse_datetime(event["start_time"])
        if start is not None and start > now:
            was_confirmed = a["status"] == "CONFIRMED"
            a["status"] = "CANCELLED"
            touch(a)
            if was_confirmed:
                release_hours(a)


def add_hours(assignment):
    profile = store.staff_profiles.get(assignment["staff_profile_id"])
    if profile is None:
        return
    total = Decimal(str(profile.get("confirmed_hours_total", 0))) + Decimal(
        str(assignment["duration_hours"])
    )
    profile["confirmed_hours_total"] = float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    touch(profile)


def release_hours(assignment):
    profile = store.staff_profiles.get(assignment["staff_profile_id"])
    if profile is None:
        return
    total = Decimal(str(profile.get("confirmed_hours_total", 0))) - Decimal(
        str(assignment["duration_hours"])
    )
    profile["confirmed_hours_total"] = float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    touch(profile)


def compute_duration_hours(event):
    """(end_time - start_time)/3600 in hours, 2 decimals round_half_up."""
    s = dates.parse_datetime(event["start_time"])
    e = dates.parse_datetime(event["end_time"])
    secs = Decimal(str((e - s).total_seconds()))
    hours = secs / Decimal(3600)
    return float(hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Overlap checks (half-open intervals; venue buffer)
# ---------------------------------------------------------------------------

def staff_double_booked(staff_profile_id, event, exclude_assignment_id=None):
    s1 = dates.parse_datetime(event["start_time"])
    e1 = dates.parse_datetime(event["end_time"])
    for a in store.staff_assignments.values():
        if a["staff_profile_id"] != staff_profile_id:
            continue
        if a["status"] not in ("CONFIRMED", "CHECKED_IN"):
            continue
        if exclude_assignment_id is not None and a["id"] == exclude_assignment_id:
            continue
        other = store.events.get(a["event_id"])
        if other is None:
            continue
        s2 = dates.parse_datetime(other["start_time"])
        e2 = dates.parse_datetime(other["end_time"])
        # Half-open conflict: s1 < e2 AND s2 < e1
        if s1 < e2 and s2 < e1:
            return True
    return False


def venue_buffer_conflict(school_id, event, exclude_event_id=None):
    """True if a PUBLISHED/IN_PROGRESS event at the same school is within 30 minutes."""
    from datetime import timedelta

    s1 = dates.parse_datetime(event["start_time"])
    e1 = dates.parse_datetime(event["end_time"])
    buffer = timedelta(minutes=VENUE_BUFFER_MINUTES)
    for other in store.events.values():
        if other["school_id"] != school_id:
            continue
        if other["status"] not in ("PUBLISHED", "IN_PROGRESS"):
            continue
        if exclude_event_id is not None and other["id"] == exclude_event_id:
            continue
        s2 = dates.parse_datetime(other["start_time"])
        e2 = dates.parse_datetime(other["end_time"])
        # Overlap or gap < 30 min conflicts; gap exactly 30 min allowed.
        if s1 < e2 and s2 < e1:
            return True  # overlap
        if s1 >= e2:
            if (s1 - e2) < buffer:
                return True
        elif s2 >= e1:
            if (s2 - e1) < buffer:
                return True
    return False


# ---------------------------------------------------------------------------
# Staffing coverage calculation (committed / pipeline variants)
# ---------------------------------------------------------------------------

def staffing_coverage(event):
    def block(statuses):
        qualifying = [
            a
            for a in store.staff_assignments.values()
            if a["event_id"] == event["id"] and a["status"] in statuses
        ]
        expert_count = sum(1 for a in qualifying if a["assigned_role"] == "EXPERT")
        staff_count = len(qualifying)
        langs = event.get("supported_languages") or []
        language_complete = True
        for lang in langs:
            covered = False
            for a in qualifying:
                profile = store.staff_profiles.get(a["staff_profile_id"])
                if profile and lang in (profile.get("languages") or []):
                    covered = True
                    break
            if not covered:
                language_complete = False
                break
        denom = max(event["required_expert_count"], 1)
        ratio = (Decimal(expert_count) / Decimal(denom)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        return {
            "expert_ratio": float(ratio),
            "staff_count": staff_count,
            "language_complete": language_complete,
        }

    return {
        "committed": block({"CONFIRMED"}),
        "pipeline": block({"ACCEPTED", "CONFIRMED"}),
    }


def staffing_invariant_met(event):
    """Publish gate (COMMITTED_ONLY): E >= required_expert_count AND language_complete."""
    confirmed = [
        a
        for a in store.staff_assignments.values()
        if a["event_id"] == event["id"] and a["status"] == "CONFIRMED"
    ]
    expert_count = sum(1 for a in confirmed if a["assigned_role"] == "EXPERT")
    if expert_count < event["required_expert_count"]:
        return False
    for lang in event.get("supported_languages") or []:
        covered = False
        for a in confirmed:
            profile = store.staff_profiles.get(a["staff_profile_id"])
            if profile and lang in (profile.get("languages") or []):
                covered = True
                break
        if not covered:
            return False
    return True


# ---------------------------------------------------------------------------
# Budget ledger
# ---------------------------------------------------------------------------

def recompute_budget(campaign):
    committed = 0
    spent = 0
    for ev in store.events.values():
        school = store.schools.get(ev["school_id"])
        if school is None or school["campaign_id"] != campaign["id"]:
            continue
        if ev["status"] in ("PUBLISHED", "IN_PROGRESS"):
            committed += ev["cost_estimate_cents"]
        elif ev["status"] == "COMPLETED":
            spent += ev.get("actual_cost_cents") or 0
    campaign["committed_budget_cents"] = committed
    campaign["spent_budget_cents"] = spent
    campaign["budget_balance_cents"] = (
        campaign["total_budget_cents"] - committed - spent
    )


def bump_campaign_version(campaign):
    touch(campaign)


# ---------------------------------------------------------------------------
# Event cancellation cascade (shared by cancel / school suspend / campaign close)
# ---------------------------------------------------------------------------

def cancel_event_cascade(event, release_budget_if_published=True):
    """Cancel an event in DRAFT or PUBLISHED with full assignment/registration/budget cascades."""
    was_published = event["status"] == "PUBLISHED"
    event["status"] = "CANCELLED"
    touch(event)
    for a in store.staff_assignments.values():
        if a["event_id"] != event["id"]:
            continue
        if a["status"] in NON_TERMINAL_ASSIGNMENT_STATUSES:
            was_confirmed = a["status"] == "CONFIRMED"
            a["status"] = "CANCELLED"
            touch(a)
            if was_confirmed:
                release_hours(a)
    for r in store.event_registrations.values():
        if r["event_id"] == event["id"] and r["status"] == "REGISTERED":
            r["status"] = "CANCELLED"
            touch(r)
    if was_published and release_budget_if_published:
        campaign = campaign_of_event(event)
        if campaign is not None:
            recompute_budget(campaign)
            bump_campaign_version(campaign)


def cancel_registration(registration):
    if registration["status"] == "REGISTERED":
        registration["status"] = "CANCELLED"
        touch(registration)


# ---------------------------------------------------------------------------
# Campaign close cascade
# ---------------------------------------------------------------------------

def campaign_close_cascade(campaign):
    """CLOSE CASCADE: DRAFT/PUBLISHED events cancelled; active cases cancelled."""
    for ev in list(store.events.values()):
        school = store.schools.get(ev["school_id"])
        if school is None or school["campaign_id"] != campaign["id"]:
            continue
        if ev["status"] in ("DRAFT", "PUBLISHED"):
            cancel_event_cascade(ev)
    # IN_PROGRESS events are deliberately left for manual completion.
    for case in list(store.support_cases.values()):
        senior = store.senior_records.get(case["senior_record_id"])
        if senior is None:
            continue
        sc = campaign_of_senior(senior)
        if sc is None or sc["id"] != campaign["id"]:
            continue
        if case["status"] in NON_TERMINAL_CASE_STATUSES:
            specialist_id = case.get("assigned_specialist_id")
            # Only ACTIVE_CASE_STATUSES count toward caseload; PAUSED cases were already decremented.
            was_counted = case["status"] in ACTIVE_CASE_STATUSES
            case["status"] = "CANCELLED"
            case["previous_status"] = None
            touch(case)
            if specialist_id and was_counted:
                bump_case_count(specialist_id, -1)


# ---------------------------------------------------------------------------
# Clock-driven system transitions
# ---------------------------------------------------------------------------

def advance_clock(to_dt):
    """Set logical clock and fire all time-driven transitions."""
    store.clock_now = to_dt
    now_date = to_dt.date()

    # Consent expiry (GRANTED -> EXPIRED) — same cascade as revoke.
    for c in list(store.consent_records.values()):
        if c["status"] == "GRANTED" and c.get("expires_at"):
            exp = dates.parse_datetime(c["expires_at"])
            if exp is not None and to_dt >= exp:
                c["status"] = "EXPIRED"
                touch(c)
                consent_loss_cascade(c["senior_record_id"])

    # Campaign state transitions.
    for campaign in list(store.campaigns.values()):
        if campaign["status"] == "OPEN":
            fed = dates.parse_datetime(campaign["federal_deadline"])
            state = dates.parse_datetime(campaign["state_grant_deadline"])
            fed_d = fed.date() if fed else None
            state_d = state.date() if state else None
            if fed_d is not None and now_date >= fed_d:
                campaign["status"] = "CLOSED"
                touch(campaign)
                campaign_close_cascade(campaign)
            elif state_d is not None and now_date >= state_d:
                campaign["status"] = "STATE_GRACE"
                touch(campaign)
        elif campaign["status"] == "STATE_GRACE":
            fed = dates.parse_datetime(campaign["federal_deadline"])
            fed_d = fed.date() if fed else None
            if fed_d is not None and now_date >= fed_d:
                campaign["status"] = "CLOSED"
                touch(campaign)
                campaign_close_cascade(campaign)

    # PUBLISHED events -> IN_PROGRESS at start_time.
    for ev in list(store.events.values()):
        if ev["status"] == "PUBLISHED":
            start = dates.parse_datetime(ev["start_time"])
            if start is not None and to_dt >= start:
                ev["status"] = "IN_PROGRESS"
                touch(ev)


# ---------------------------------------------------------------------------
# Consent cascades (revoke/expire: pause cases, cancel registrations;
# regrant: resume cases, do NOT restore registrations)
# ---------------------------------------------------------------------------

def consent_loss_cascade(senior_id):
    senior = store.senior_records.get(senior_id)
    if senior is None:
        return
    recompute_visibility(senior)
    for case in list(store.support_cases.values()):
        if case["senior_record_id"] != senior_id:
            continue
        if case["status"] in ACTIVE_CASE_STATUSES:
            prev = case["status"]
            case["previous_status"] = prev
            case["status"] = "PAUSED"
            touch(case)
            if case.get("assigned_specialist_id"):
                bump_case_count(case["assigned_specialist_id"], -1)
    for r in list(store.event_registrations.values()):
        if r["senior_record_id"] == senior_id and r["status"] == "REGISTERED":
            cancel_registration(r)


def consent_restore_cascade(senior_id):
    senior = store.senior_records.get(senior_id)
    if senior is None:
        return
    recompute_visibility(senior)
    for case in list(store.support_cases.values()):
        if case["senior_record_id"] != senior_id:
            continue
        if case["status"] == "PAUSED":
            prev = case.get("previous_status") or "OPEN"
            case["status"] = prev
            case["previous_status"] = None
            touch(case)
            if case.get("assigned_specialist_id"):
                bump_case_count(case["assigned_specialist_id"], 1)


# ---------------------------------------------------------------------------
# Checklists
# ---------------------------------------------------------------------------

def template_for_dependency(dependency_status):
    if dependency_status == "INDEPENDENT":
        return "INDEPENDENT_STANDARD"
    return "DEPENDENT_STANDARD"


def generate_checklist(senior):
    """Generate a DocumentChecklist with items in template order."""
    template_key = template_for_dependency(senior["dependency_status"])
    common = make_common()
    checklist = {
        **common,
        "senior_record_id": senior["id"],
        "language": senior["home_language"],
        "template_key": template_key,
        "status": "GENERATED",
        "_seq": store.next_seq(),
    }
    store.checklists[checklist["id"]] = checklist
    for doc_type in DOC_TEMPLATES[template_key]:
        icommon = make_common()
        item = {
            **icommon,
            "checklist_id": checklist["id"],
            "doc_type": doc_type,
            "status": "PENDING",
            "waivable": doc_type in WAIVABLE_DOC_TYPES,
            "_seq": store.next_seq(),
        }
        store.checklist_items[item["id"]] = item
    return checklist


def reevaluate_checklist_status(checklist):
    if checklist["status"] == "ARCHIVED":
        return
    items = [i for i in store.checklist_items.values() if i["checklist_id"] == checklist["id"]]
    if not items:
        return
    new_status = checklist["status"]
    if all(i["status"] in ("VERIFIED", "WAIVED") for i in items):
        new_status = "COMPLETE"
    elif any(i["status"] != "PENDING" for i in items):
        # First item left PENDING, or a COMPLETE checklist regained work.
        if checklist["status"] in ("GENERATED", "COMPLETE"):
            new_status = "IN_PROGRESS"
    elif checklist["status"] == "COMPLETE":
        # An item re-entered PENDING (e.g., regeneration) while all others are PENDING.
        new_status = "IN_PROGRESS"
    if new_status != checklist["status"]:
        checklist["status"] = new_status
        touch(checklist)


def archive_checklists_for_senior(senior_id):
    for cl in store.checklists.values():
        if cl["senior_record_id"] == senior_id and cl["status"] != "ARCHIVED":
            cl["status"] = "ARCHIVED"
            touch(cl)


def regenerate_checklist_for_independent(senior):
    """INDEPENDENT_CONFIRMED regeneration (§3.9 resolve side effect)."""
    cl = None
    for c in store.checklists.values():
        if c["senior_record_id"] == senior["id"] and c["status"] != "ARCHIVED":
            cl = c
            break
    if cl is None:
        return
    new_template = DOC_TEMPLATES["INDEPENDENT_STANDARD"]
    new_set = set(new_template)
    cl["template_key"] = "INDEPENDENT_STANDARD"
    items = [i for i in store.checklist_items.values() if i["checklist_id"] == cl["id"]]
    existing_types = {i["doc_type"] for i in items}
    for item in items:
        if item["doc_type"] not in new_set and item["status"] in ("PENDING", "REJECTED"):
            item["status"] = "WAIVED"
            touch(item)
    for doc_type in new_template:
        if doc_type not in existing_types:
            icommon = make_common()
            item = {
                **icommon,
                "checklist_id": cl["id"],
                "doc_type": doc_type,
                "status": "PENDING",
                "waivable": doc_type in WAIVABLE_DOC_TYPES,
                "_seq": store.next_seq(),
            }
            store.checklist_items[item["id"]] = item
    touch(cl)
    reevaluate_checklist_status(cl)


# ---------------------------------------------------------------------------
# Support cases: selector + creation
# ---------------------------------------------------------------------------

def select_specialist(campaign, senior):
    """Deterministic selector: language match DESC, active_case_count ASC, created_at ASC."""
    pool = []
    for p in store.staff_profiles.values():
        if p["campaign_id"] != campaign["id"]:
            continue
        if "CASE_SPECIALIST" not in (p.get("capabilities") or []):
            continue
        if p["status"] != "ACTIVE":
            continue
        lang_match = 1 if senior["home_language"] in (p.get("languages") or []) else 0
        pool.append((p, lang_match))
    if not pool:
        return None
    pool.sort(key=lambda t: (-t[1], t[0]["active_case_count"], t[0]["created_at"], t[0]["_seq"]))
    return pool[0][0]


def create_support_case(senior, case_type, notes=""):
    campaign = campaign_of_senior(senior)
    specialist = select_specialist(campaign, senior) if campaign else None
    common = make_common()

    has_status_detail = senior_has_granted_scope(senior["id"], "STATUS_DETAIL")
    initial_status = "OPEN" if has_status_detail else "PAUSED"
    previous_status = None if has_status_detail else "OPEN"

    case = {
        **common,
        "senior_record_id": senior["id"],
        "assigned_specialist_id": specialist["id"] if specialist else None,
        "case_type": case_type,
        "status": initial_status,
        "previous_status": previous_status,
        "resolution_outcome": None,
        "notes": notes or "",
        "_seq": store.next_seq(),
    }
    store.support_cases[case["id"]] = case
    if specialist is not None:
        # PAUSED cases do not count toward active caseload.
        delta = 1 if initial_status in ACTIVE_CASE_STATUSES else 0
        if delta:
            bump_case_count(specialist["id"], delta)
    return case


# ---------------------------------------------------------------------------
# Senior fafsa axis: projection, submitted_at, classification, cascades
# ---------------------------------------------------------------------------

def recompute_submitted_at(senior):
    """Earliest effective_date of linked aid record events in {SUBMITTED, VERIFICATION_SELECTED, COMPLETE}."""
    link_id = senior.get("current_match_link_id")
    submitted_at = None
    if link_id:
        link = store.match_links.get(link_id)
        if link is not None:
            aid_record = store.aid_records.get(link["aid_record_id"])
            if aid_record is not None:
                dates_found = []
                for ev in store.aid_status_events.values():
                    if ev["aid_record_id"] != aid_record["id"]:
                        continue
                    if ev["fafsa_status"] in ("SUBMITTED", "VERIFICATION_SELECTED", "COMPLETE"):
                        dates_found.append(ev["effective_date"])
                if dates_found:
                    submitted_at = min(dates_found)
    senior["submitted_at"] = submitted_at

    # deadline classification (day granularity, inclusive upper bounds)
    campaign = campaign_of_senior(senior)
    if submitted_at is None or campaign is None:
        senior["deadline_classification"] = "NOT_SUBMITTED"
    else:
        sub_d = dates.to_utc_date(submitted_at)
        state_d = dates.to_utc_date(campaign["state_grant_deadline"])
        fed_d = dates.to_utc_date(campaign["federal_deadline"])
        if sub_d <= state_d:
            senior["deadline_classification"] = "ON_TRACK_STATE"
        elif sub_d <= fed_d:
            senior["deadline_classification"] = "STATE_MISSED_FEDERAL_OPEN"
        else:
            senior["deadline_classification"] = "LATE"


def verification_cascade(senior):
    """Auto-create VERIFICATION_FOLLOWUP case unless one is already non-terminal."""
    for c in store.support_cases.values():
        if (
            c["senior_record_id"] == senior["id"]
            and c["case_type"] == "VERIFICATION_FOLLOWUP"
            and c["status"] in NON_TERMINAL_CASE_STATUSES
        ):
            return
    create_support_case(senior, "VERIFICATION_FOLLOWUP")


def auto_resolve_cascade(senior):
    """Open VERIFICATION_FOLLOWUP cases -> RESOLVED with VERIFICATION_COMPLETED."""
    for c in list(store.support_cases.values()):
        if (
            c["senior_record_id"] == senior["id"]
            and c["case_type"] == "VERIFICATION_FOLLOWUP"
            and c["status"] in ACTIVE_CASE_STATUSES
        ):
            specialist_id = c.get("assigned_specialist_id")
            c["status"] = "RESOLVED"
            c["resolution_outcome"] = "VERIFICATION_COMPLETED"
            touch(c)
            if specialist_id:
                bump_case_count(specialist_id, -1)


def senior_fafsa_transition(senior, new_status):
    """Apply a fafsa_status transition with its cascades (§3.4)."""
    old = senior["fafsa_status"]
    if old == new_status:
        # still recompute submitted_at/classification per bookkeeping rule? No —
        # only on transition. Keep idempotent.
        return
    senior["fafsa_status"] = new_status
    recompute_submitted_at(senior)
    touch(senior)
    if new_status == "VERIFICATION_SELECTED":
        verification_cascade(senior)
    elif new_status == "COMPLETE" and old in ("SUBMITTED", "VERIFICATION_SELECTED"):
        auto_resolve_cascade(senior)


def apply_aid_record_projection(aid_record):
    """Recompute projection from the event stream; propagate to linked senior."""
    events = [e for e in store.aid_status_events.values() if e["aid_record_id"] == aid_record["id"]]
    if not events:
        return
    # Winner: max effective_date, tie -> later created_at (then _seq).
    events.sort(key=lambda e: (dates.to_utc_date(e["effective_date"]), e["created_at"], e["_seq"]))
    winner = events[-1]
    changed = aid_record.get("current_status") != winner["fafsa_status"]
    aid_record["current_status"] = winner["fafsa_status"]
    aid_record["last_effective_date"] = winner["effective_date"]
    touch(aid_record)
    if changed:
        # Propagate via CONFIRMED/AUTO_CONFIRMED link.
        for link in store.match_links.values():
            if link["aid_record_id"] != aid_record["id"]:
                continue
            if link["status"] not in ("CONFIRMED", "AUTO_CONFIRMED"):
                continue
            senior = store.senior_records.get(link["senior_record_id"])
            if senior is None:
                continue
            if senior.get("current_match_link_id") != link["id"]:
                continue
            senior_fafsa_transition(senior, aid_record["current_status"])


# ---------------------------------------------------------------------------
# Match links: scoring + matched cascade
# ---------------------------------------------------------------------------

def compute_match_score(senior, aid_record):
    school = store.schools.get(senior["school_id"])
    dob_exact = senior["dob"] == aid_record["dob"]
    name_exact = senior["full_name"].strip().lower() == aid_record["full_name"].strip().lower()
    school_code_match = bool(school) and school["school_code"] == aid_record["school_code"]
    district_match = bool(school) and school["district_code"] == aid_record["district_code"]
    score = Decimal("0")
    if dob_exact:
        score += W_DOB
    if name_exact:
        score += W_NAME
    if school_code_match:
        score += W_SCHOOL
    if district_match:
        score += W_DISTRICT
    components = {
        "dob_exact": dob_exact,
        "name_exact": name_exact,
        "school_code_match": school_code_match,
        "district_match": district_match,
    }
    return score, components


def matched_cascade(senior, link, aid_record):
    """UNMATCHED/SUGGESTED -> MATCHED with full cascade (§3.5)."""
    senior["match_status"] = "MATCHED"
    senior["current_match_link_id"] = link["id"]
    # fafsa_status initializes from linked aid record's current_status
    target_status = aid_record["current_status"]
    old = senior["fafsa_status"]
    senior["fafsa_status"] = target_status
    recompute_submitted_at(senior)
    touch(senior)
    # cascades based on initial status
    if target_status == "VERIFICATION_SELECTED" and old != "VERIFICATION_SELECTED":
        verification_cascade(senior)
    elif target_status == "COMPLETE" and old in ("SUBMITTED", "VERIFICATION_SELECTED"):
        auto_resolve_cascade(senior)
    generate_checklist(senior)


def unmatched_cascade(senior):
    """MATCHED -> UNMATCHED (link invalidated)."""
    senior["match_status"] = "UNMATCHED"
    senior["current_match_link_id"] = None
    # fafsa_status retained as historical.
    touch(senior)
    archive_checklists_for_senior(senior["id"])


# ---------------------------------------------------------------------------
# Completion reporting (§3.10)
# ---------------------------------------------------------------------------

def eligible_seniors(campaign):
    result = []
    for s in store.senior_records.values():
        school = store.schools.get(s["school_id"])
        if school is None or school["campaign_id"] != campaign["id"]:
            continue
        if s["match_status"] != "MATCHED":
            continue
        if not senior_has_granted_scope(s["id"], "DATA_SHARE"):
            continue
        if school["status"] != "ENROLLED":
            continue
        result.append(s)
    return result


def is_completed(senior, variant):
    if variant == "SUBMISSION_BASED":
        return senior["fafsa_status"] in ("SUBMITTED", "VERIFICATION_SELECTED", "COMPLETE")
    return senior["fafsa_status"] == "COMPLETE"


def met_state_deadline(senior, campaign):
    if senior.get("submitted_at") is None:
        return False
    sub_d = dates.to_utc_date(senior["submitted_at"])
    state_d = dates.to_utc_date(campaign["state_grant_deadline"])
    return sub_d <= state_d


def rate_1dp(completed, eligible):
    """round_half_up(1000 * completed / eligible) / 10 -> percent, 1 decimal."""
    if eligible == 0:
        return None
    r = (Decimal(1000) * Decimal(completed) / Decimal(eligible)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return float(r / Decimal(10))


def generate_report_rows(campaign, variant):
    seniors = eligible_seniors(campaign)
    total_eligible = len(seniors)
    total_completed = sum(1 for s in seniors if is_completed(s, variant))

    buckets = {}  # (dimension, key) -> [eligible, completed, met]

    def add(dim, key, senior):
        k = (dim, key)
        if k not in buckets:
            buckets[k] = [0, 0, 0]
        buckets[k][0] += 1
        if is_completed(senior, variant):
            buckets[k][1] += 1
        if met_state_deadline(senior, campaign):
            buckets[k][2] += 1

    for s in seniors:
        add("LANGUAGE", s["home_language"], s)
        add("EFC_BAND", s["efc_band"], s)
        school = store.schools.get(s["school_id"])
        skey = f'{school["id"]} {school["name"]}' if school else s["school_id"]
        add("SCHOOL", skey, s)

    rows = []
    for (dim, key) in sorted(buckets.keys(), key=lambda k: (k[0], k[1])):
        elig, comp, met = buckets[(dim, key)]
        if elig < campaign["min_subgroup_size"]:
            continue  # strict less-than suppression
        rows.append(
            {
                "dimension": dim,
                "key": key,
                "eligible_count": elig,
                "completed_count": comp,
                "state_deadline_met_count": met,
                "rate": rate_1dp(comp, elig),
            }
        )
    overall_rate = rate_1dp(total_completed, total_eligible) if total_eligible else None
    return rows, total_eligible, total_completed, overall_rate


def recompute_recognition_tiers(campaign):
    """§3.10 recognition ranking with pinned evaluation order."""
    # (1) raw rate per ENROLLED school (SUBMISSION_BASED semantics)
    rates = {}  # school_id -> (rate_1dp_value, eligible_count)
    for school in store.schools.values():
        if school["campaign_id"] != campaign["id"]:
            continue
        if school["status"] != "ENROLLED":
            school["recognition_tier"] = "UNRATED"
            touch(school)
            continue
        seniors = []
        for s in store.senior_records.values():
            if s["school_id"] != school["id"]:
                continue
            if s["match_status"] != "MATCHED":
                continue
            if not senior_has_granted_scope(s["id"], "DATA_SHARE"):
                continue
            seniors.append(s)
        elig = len(seniors)
        comp = sum(1 for s in seniors if is_completed(s, "SUBMISSION_BASED"))
        rates[school["id"]] = (rate_1dp(comp, elig), elig)

    # (2) ranking pool
    import math

    pool = [
        (sid, rate)
        for sid, (rate, elig) in rates.items()
        if elig >= campaign["min_recognition_seniors"] and rate is not None
    ]
    # Schools outside R -> UNRATED
    for school in store.schools.values():
        if school["campaign_id"] != campaign["id"]:
            continue
        if school["status"] != "ENROLLED":
            continue  # already UNRATED above
        if school["id"] not in {sid for sid, _ in pool}:
            if school["recognition_tier"] != "UNRATED":
                school["recognition_tier"] = "UNRATED"
                touch(school)

    if not pool:
        return

    # (3) cutoffs via nearest-rank percentile
    sorted_rates = sorted(r for _, r in pool)
    n = len(sorted_rates)
    c70 = sorted_rates[math.ceil(0.70 * n) - 1]
    c40 = sorted_rates[math.ceil(0.40 * n) - 1]

    # (4) tiers (boundaries inclusive)
    for sid, rate in pool:
        school = store.schools[sid]
        if rate >= c70:
            tier = "GOLD"
        elif rate >= c40:
            tier = "SILVER"
        else:
            tier = "BRONZE"
        if school["recognition_tier"] != tier:
            school["recognition_tier"] = tier
            touch(school)


# ---------------------------------------------------------------------------
# Serialization (with consent masking for seniors)
# ---------------------------------------------------------------------------

MASKED_SENIOR_FIELDS = ("fafsa_status", "submitted_at", "deadline_classification", "current_match_link_id")


def serialize(obj, collection=None):
    """Return a JSON-safe copy; strip internal keys (underscore-prefixed)."""
    out = {}
    for k, v in obj.items():
        if k.startswith("_"):
            continue
        if isinstance(v, Decimal):
            out[k] = float(v)
        else:
            out[k] = v
    if collection == "senior_records":
        if obj.get("data_visibility") != "NORMAL":
            for f in MASKED_SENIOR_FIELDS:
                out[f] = None
    if collection == "events":
        out["staffing_coverage"] = staffing_coverage(obj)
    return out


def sorted_page(items, limit, offset):
    """created_at ASC default sort, stable by _seq; returns (page, total)."""
    ordered = sorted(items, key=lambda x: (x.get("created_at", ""), x.get("_seq", 0)))
    total = len(ordered)
    return ordered[offset : offset + limit], total
