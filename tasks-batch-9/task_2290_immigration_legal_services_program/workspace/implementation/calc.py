"""Derived values and calculations (PRD sections 2.5, 3.1-3.10)."""

import datetime
from decimal import Decimal

import store
from errors import ApiError

# --------------------------------------------------------------------------
# enumerations / constants
# --------------------------------------------------------------------------

CASE_TYPES = (
    "ASYLUM_AFFIRMATIVE",
    "ASYLUM_DEFENSIVE",
    "REMOVAL_DEFENSE_OTHER",
    "U_VISA",
    "VAWA_SELF_PETITION",
    "SIJS",
    "DACA_RENEWAL",
    "NATURALIZATION",
    "ADJUSTMENT_OF_STATUS",
    "BOND_HEARING",
)

FEE_EXEMPT_CASE_TYPES = frozenset({
    "ASYLUM_DEFENSIVE",
    "ASYLUM_AFFIRMATIVE",
    "U_VISA",
    "VAWA_SELF_PETITION",
    "SIJS",
    "BOND_HEARING",
})

FORUMS = ("USCIS", "EOIR_IMMIGRATION_COURT", "BIA", "ASYLUM_OFFICE")

FORUM_BY_CASE_TYPE = {
    "ASYLUM_DEFENSIVE": "EOIR_IMMIGRATION_COURT",
    "REMOVAL_DEFENSE_OTHER": "EOIR_IMMIGRATION_COURT",
    "BOND_HEARING": "EOIR_IMMIGRATION_COURT",
    "ASYLUM_AFFIRMATIVE": "ASYLUM_OFFICE",
    "U_VISA": "USCIS",
    "VAWA_SELF_PETITION": "USCIS",
    "SIJS": "USCIS",
    "DACA_RENEWAL": "USCIS",
    "NATURALIZATION": "USCIS",
    "ADJUSTMENT_OF_STATUS": "USCIS",
}

CONSENT_SCOPES = ("NONE", "PROGRAM_ONLY", "FUNDER_AGGREGATE", "FUNDER_IDENTIFIED")
CONSENT_RANK = {name: index for index, name in enumerate(CONSENT_SCOPES)}

FPL_BASE_CENTS = 1508000
FPL_INCREMENT_CENTS = 532000
INDIGENCY_CEILING_PERCENT = Decimal("200.00")

DETAINED_JURISDICTIONS = frozenset({"TX-ELP", "AZ-ELO", "CA-ADL", "LA-JEN", "GA-ATL"})

URGENCY_BASE_POINTS = {
    "BOND_HEARING": 42,
    "ASYLUM_DEFENSIVE": 40,
    "REMOVAL_DEFENSE_OTHER": 38,
    "SIJS": 30,
    "ASYLUM_AFFIRMATIVE": 26,
    "VAWA_SELF_PETITION": 24,
    "U_VISA": 22,
    "DACA_RENEWAL": 14,
    "ADJUSTMENT_OF_STATUS": 12,
    "NATURALIZATION": 8,
}

URGENCY_DETAINED_BONUS = 25
URGENCY_UNACCOMPANIED_MINOR_BONUS = 15
URGENCY_PRIOR_REMOVAL_BONUS = 10
URGENCY_ONE_YEAR_BAR_BONUS = 8

HORIZON_MAX_POINTS = Decimal("30")
HORIZON_SPAN_DAYS = Decimal("84")
URGENCY_MAX = Decimal("100.00")

URGENCY_TIERS = (
    ("EMERGENCY", Decimal("85.00")),
    ("URGENT", Decimal("65.00")),
    ("ELEVATED", Decimal("45.00")),
)

CALENDAR_URGENCY_EVENT_TYPES = frozenset({
    "MASTER_CALENDAR_HEARING",
    "INDIVIDUAL_HEARING",
    "ASYLUM_INTERVIEW",
    "BIOMETRICS",
})

POSTURE_FROZEN_AT = Decimal("0.9500")
POSTURE_RESTRICTED_AT = Decimal("0.8000")

WAITLIST_TTL_DAYS = 30

ACCREDITATION_TERM_DAYS = 1095
ACCREDITATION_EXPIRING_WINDOW_DAYS = 90

PARTIAL_FORUM_CEILING = frozenset({"USCIS", "ASYLUM_OFFICE"})
FULL_FORUM_CEILING = frozenset({"USCIS", "ASYLUM_OFFICE", "EOIR_IMMIGRATION_COURT", "BIA"})

REP_TYPES = ("STAFF_ATTORNEY", "ACCREDITED_REP", "PRO_BONO_VOLUNTEER", "LAW_GRADUATE")

ASSIGNMENT_ROLES = ("LEAD", "CO_COUNSEL", "SUPERVISOR", "INTERPRETER_COORDINATOR")
DIRECT_HOURS_ROLES = frozenset({"LEAD", "CO_COUNSEL", "INTERPRETER_COORDINATOR"})
MAX_HOURS_PER_ENTRY = Decimal("12.00")
CASELOAD_ROLES = frozenset({"LEAD", "CO_COUNSEL"})

ATTORNEY_FORUMS = frozenset({"EOIR_IMMIGRATION_COURT", "BIA"})

EVIDENCE_ITEM_TYPES = (
    "IDENTITY_DOCUMENT",
    "COUNTRY_CONDITIONS",
    "MEDICAL_RECORD",
    "POLICE_REPORT",
    "WITNESS_STATEMENT",
    "TAX_RECORD",
    "CERTIFICATION_LETTER",
)
EVIDENCE_TIERS = ("REQUIRED", "SUPPORTING", "OPTIONAL")
EVIDENCE_OPEN_STATUSES = frozenset({"REQUESTED", "RECEIVED", "TRANSLATED", "REJECTED"})

READINESS_WEIGHTED_THRESHOLD = Decimal("0.7500")

EVENT_TYPES = (
    "BIOMETRICS",
    "MASTER_CALENDAR_HEARING",
    "INDIVIDUAL_HEARING",
    "ASYLUM_INTERVIEW",
    "FILING_DEADLINE",
    "FACILITY_VISIT",
)

TRAVEL_BUFFER_MINUTES = {
    "FACILITY_VISIT": 90,
    "INDIVIDUAL_HEARING": 60,
    "MASTER_CALENDAR_HEARING": 45,
    "ASYLUM_INTERVIEW": 45,
    "BIOMETRICS": 30,
    "FILING_DEADLINE": 0,
}

EVENT_ACTIVE_STATUSES = frozenset({"SCHEDULED", "CONFIRMED"})
MAX_RESCHEDULES = 3

INTERPRETER_SOURCES = ("STAFF", "VOLUNTEER", "CONTRACT", "TELEPHONIC")
INTERPRETER_NAMED_SOURCES = frozenset({"STAFF", "VOLUNTEER"})
INTERPRETATION_PURPOSES = (
    "INTAKE",
    "DECLARATION_READBACK",
    "RIGHTS_COUNSELING",
    "HEARING_PREP",
    "FACILITY_VISIT",
)
INTERPRETER_RATE_CENTS_PER_HOUR = {
    "STAFF": 0,
    "VOLUNTEER": 0,
    "CONTRACT": 9500,
    "TELEPHONIC": 6200,
}
INTERPRETATION_MIN_BILLED_MINUTES = 30
INTERPRETATION_BILLING_INCREMENT_MINUTES = 15
RARE_LANGUAGE_SURCHARGE_RATE = Decimal("0.15")
COMMON_LANGUAGES = frozenset({"es", "fr", "pt", "zh", "ar"})

MATTER_OUTCOMES = (
    "GRANTED",
    "DENIED",
    "ADMINISTRATIVELY_CLOSED",
    "WITHDRAWN",
    "TERMINATED",
    "REFERRED_TO_COURT",
)

STAFFED_STATUSES = frozenset({"STAFFED", "SUPERVISED_STAFFED"})

REIMBURSEMENT_RATE_CENTS_PER_HOUR = 12500
GRANT_TIER_MID_FLOOR = 500000
GRANT_TIER_HIGH_FLOOR = 2000000
GRANT_SURCHARGE_RATES = (
    (2000000, Decimal("0.09")),
    (500000, Decimal("0.06")),
    (0, Decimal("0.00")),
)

DISCLOSURE_CONSENT_REQUIREMENTS = {
    "AGGREGATE_ONLY": frozenset({"PROGRAM_ONLY", "FUNDER_AGGREGATE", "FUNDER_IDENTIFIED"}),
    "DEIDENTIFIED_CASE_LEVEL": frozenset({"FUNDER_AGGREGATE", "FUNDER_IDENTIFIED"}),
    "IDENTIFIED_WITH_CONSENT": frozenset({"FUNDER_IDENTIFIED"}),
}


# --------------------------------------------------------------------------
# client indigency (PRD 3.1)
# --------------------------------------------------------------------------

def fpl_guideline_cents(household_size):
    return FPL_BASE_CENTS + FPL_INCREMENT_CENTS * (int(household_size) - 1)


def fpl_percent(household_size, income_cents):
    guideline = fpl_guideline_cents(household_size)
    if guideline <= 0:
        return Decimal("0.00")
    ratio = store.dec(income_cents) / store.dec(guideline) * Decimal("100")
    return store.rhu(ratio, 2)


def indigency_eligible(client):
    return store.dec(client["fpl_percent"]) <= INDIGENCY_CEILING_PERCENT


def interpreter_required(language_code):
    return language_code != "en"


# --------------------------------------------------------------------------
# capacity cycle (PRD 3.2)
# --------------------------------------------------------------------------

def cycle_matters(cycle_id):
    return [m for m in store.db["matters"].values() if m.get("cycle_id") == cycle_id]


def recompute_cycle(cycle, bump=True):
    total = int(cycle["total_case_slots"])
    general = 0
    detained = 0
    for matter in cycle_matters(cycle["id"]):
        if matter.get("representation_status") == "WITHDRAWN_FROM":
            continue
        if matter.get("slot_pool_consumed") == "DETAINED_RESERVED":
            detained += 1
        else:
            general += 1
    waitlisted = sum(
        1 for s in store.db["screenings"].values()
        if s.get("cycle_id") == cycle["id"] and s.get("status") == "WAITLISTED"
    )
    ratio = store.rhu(store.dec(general + detained) / store.dec(total), 4) if total > 0 \
        else Decimal("0.0000")
    changed = (
        cycle.get("general_slots_consumed") != general
        or cycle.get("detained_slots_consumed") != detained
        or cycle.get("waitlisted_count") != waitlisted
        or cycle.get("utilization_ratio") != ratio
        or cycle.get("available_slot_count") != total - general - detained
    )
    cycle["general_slots_consumed"] = general
    cycle["detained_slots_consumed"] = detained
    cycle["available_slot_count"] = total - general - detained
    cycle["waitlisted_count"] = waitlisted
    cycle["utilization_ratio"] = ratio
    cycle["capacity_posture"] = computed_posture(cycle)
    if bump and changed:
        store.touch(cycle)
    return cycle


def computed_posture(cycle):
    ratio = store.dec(cycle.get("utilization_ratio") or 0)
    if ratio >= POSTURE_FROZEN_AT:
        return "FROZEN"
    if ratio >= POSTURE_RESTRICTED_AT:
        return "RESTRICTED"
    return "OPEN"


def override_active(cycle):
    until = cycle.get("posture_override_until_utc")
    if not until:
        return False
    parsed = store.parse_dt(until)
    if parsed is None:
        return False
    return store.clock_dt() < parsed


def effective_posture(cycle):
    """The posture as reported and enforced, honouring an active override."""
    posture = computed_posture(cycle)
    if posture == "FROZEN" and override_active(cycle):
        return "RESTRICTED"
    return posture


def detained_pool_free(cycle):
    return max(0, int(cycle["reserved_detained_slots"]) - int(cycle["detained_slots_consumed"]))


def general_pool_free(cycle):
    return max(
        0,
        int(cycle["total_case_slots"]) - int(cycle["reserved_detained_slots"])
        - int(cycle["general_slots_consumed"]),
    )


def pool_free(cycle, pool):
    if pool == "DETAINED_RESERVED":
        return detained_pool_free(cycle)
    return general_pool_free(cycle)


def waterfall_pools(detained):
    return ("DETAINED_RESERVED", "GENERAL") if detained else ("GENERAL",)


def resolve_pool(cycle, detained):
    for pool in waterfall_pools(detained):
        if pool_free(cycle, pool) > 0:
            return pool
    return None


# --------------------------------------------------------------------------
# urgency (PRD 3.3)
# --------------------------------------------------------------------------

def urgency_tier(score):
    value = store.dec(score)
    for name, floor in URGENCY_TIERS:
        if value >= floor:
            return name
    return "ROUTINE"


def _earliest_calendar_anchor(client_id):
    best = None
    for event in store.db["events"].values():
        if event.get("status") not in EVENT_ACTIVE_STATUSES:
            continue
        if event.get("event_type") not in CALENDAR_URGENCY_EVENT_TYPES:
            continue
        matter = store.get("matters", event.get("matter_id"))
        if matter is None or matter.get("client_id") != client_id:
            continue
        if matter.get("filing_status") in ("DECIDED", "CLOSED_NO_FILING"):
            continue
        started = store.parse_dt(event.get("starts_at_utc"))
        if started is None:
            continue
        day = started.date()
        if best is None or day < best:
            best = day
    return best


def horizon_points(anchor_date):
    if anchor_date is None:
        return Decimal("0.00"), None
    days = (anchor_date - store.clock_date()).days
    if days <= 0:
        return store.rhu(HORIZON_MAX_POINTS, 2), anchor_date
    raw = HORIZON_MAX_POINTS * (Decimal("1") - store.dec(days) / HORIZON_SPAN_DAYS)
    points = store.rhu(raw, 2)
    if points < 0:
        points = Decimal("0.00")
    return points, anchor_date


def compute_urgency(screening, client):
    case_type = screening["case_type"]
    detained = bool(screening.get("detained"))
    base = store.dec(URGENCY_BASE_POINTS[case_type])
    bonus = Decimal("0")
    if detained:
        bonus += URGENCY_DETAINED_BONUS
    if screening.get("unaccompanied_minor"):
        bonus += URGENCY_UNACCOMPANIED_MINOR_BONUS
    if screening.get("prior_removal_order"):
        bonus += URGENCY_PRIOR_REMOVAL_BONUS
    if screening.get("one_year_bar_applies"):
        bonus += URGENCY_ONE_YEAR_BAR_BONUS

    statutory = store.parse_date(screening.get("statutory_deadline_date"))
    if detained:
        variant = "CALENDAR_INCLUSIVE"
        calendar_anchor = _earliest_calendar_anchor(screening["client_id"])
        candidates = [d for d in (statutory, calendar_anchor) if d is not None]
        anchor = min(candidates) if candidates else None
    else:
        variant = "STRICT_STATUTORY"
        anchor = statutory

    points, anchor_used = horizon_points(anchor)
    total = base + bonus + points
    if total > URGENCY_MAX:
        total = URGENCY_MAX
    score = store.rhu(total, 2)
    return {
        "urgency_score": score,
        "urgency_tier": urgency_tier(score),
        "urgency_variant_applied": variant,
        "urgency_anchor_date": anchor_used.isoformat() if anchor_used else None,
    }


def eligibility_verdict(screening, client):
    """Verdict clauses evaluated in the pinned order of PRD 3.3."""
    case_type = screening["case_type"]
    if case_type == "NATURALIZATION" and screening.get("prior_removal_order"):
        return "INELIGIBLE_NO_RELIEF"
    if screening.get("detained"):
        facility = store.get("facilities", screening.get("facility_id"))
        jurisdiction = facility.get("jurisdiction_code") if facility else None
        if jurisdiction not in DETAINED_JURISDICTIONS:
            return "INELIGIBLE_JURISDICTION"
    if not indigency_eligible(client) and case_type not in FEE_EXEMPT_CASE_TYPES:
        return "INELIGIBLE_INCOME"
    if (case_type == "ASYLUM_AFFIRMATIVE"
            and screening.get("one_year_bar_applies")
            and not screening.get("unaccompanied_minor")):
        return "INELIGIBLE_NO_RELIEF"
    return "ELIGIBLE"


RISKS = frozenset({
    "REMOVAL_RISK",
    "DETENTION_RISK",
    "BAR_TO_FUTURE_RELIEF",
    "FEE_LOSS",
    "CRIMINAL_EXPOSURE",
    "FAMILY_SEPARATION",
    "DATA_DISCLOSURE",
})

ALTERNATIVES = frozenset({
    "DO_NOTHING",
    "SEEK_OTHER_COUNSEL",
    "ALTERNATIVE_RELIEF_PATH",
    "VOLUNTARY_DEPARTURE",
    "ADMINISTRATIVE_CLOSURE",
    "APPEAL",
})


# --------------------------------------------------------------------------
# authority derivation (PRD 3.5)
# --------------------------------------------------------------------------

QUALIFYING_ACCREDITATION_STATUSES = frozenset({"APPROVED", "EXPIRING", "RENEWAL_PENDING"})
ACTIVE_RECOGNITION_STATUSES = frozenset({"ACTIVE", "CONDITIONAL"})


def rep_accreditations(rep_id):
    return [a for a in store.db["accreditations"].values()
            if a.get("representative_id") == rep_id]


def accreditation_qualifies(accreditation):
    if accreditation.get("status") not in QUALIFYING_ACCREDITATION_STATUSES:
        return False
    recognition = store.get("recognitions", accreditation.get("recognition_id"))
    if recognition is None or recognition.get("status") not in ACTIVE_RECOGNITION_STATUSES:
        return False
    expiry = store.parse_date(accreditation.get("expiry_date"))
    if expiry is None or expiry < store.clock_date():
        return False
    return True


def supervision_required(rep):
    return rep.get("rep_type") != "STAFF_ATTORNEY"


def authorization_status(rep):
    """First matching clause of PRD 3.5 wins."""
    status = rep.get("status")
    if status == "SUSPENDED":
        return "AUTHORIZATION_SUSPENDED"
    rep_type = rep.get("rep_type")
    if rep_type == "STAFF_ATTORNEY":
        if status == "ACTIVE" and rep.get("bar_number"):
            return "AUTHORIZED_ATTORNEY"
        return "UNAUTHORIZED"
    if rep_type == "ACCREDITED_REP":
        accreditations = rep_accreditations(rep["id"])
        if status == "ACTIVE" and any(accreditation_qualifies(a) for a in accreditations):
            return "AUTHORIZED_ACCREDITED"
        if any(a.get("status") == "SUSPENDED_BY_RECOGNITION" for a in accreditations):
            return "AUTHORIZATION_SUSPENDED"
        return "UNAUTHORIZED"
    if status == "ACTIVE":
        return "AUTHORIZED_SUPERVISED"
    return "UNAUTHORIZED"


def forum_ceiling(accreditation_type):
    return FULL_FORUM_CEILING if accreditation_type == "FULL" else PARTIAL_FORUM_CEILING


def forum_grant(requested_forums, recognition, accreditation_type):
    ceiling = forum_ceiling(accreditation_type)
    recognised = set(recognition.get("authorized_forums") or [])
    granted = set(requested_forums or []) & recognised & set(ceiling)
    return sorted(granted)


def rep_authorized_for_forum(rep, forum):
    """PRD 3.6: LEAD authority on EOIR / BIA forums."""
    if authorization_status(rep) == "AUTHORIZED_ATTORNEY":
        return True
    for accreditation in rep_accreditations(rep["id"]):
        if accreditation.get("accreditation_type") != "FULL":
            continue
        if not accreditation_qualifies(accreditation):
            continue
        if forum in (accreditation.get("authorized_forums") or []):
            return True
    return False


# --------------------------------------------------------------------------
# assignments, counters, supervision (PRD 3.6)
# --------------------------------------------------------------------------

def matter_assignments(matter_id):
    return sorted(
        [a for a in store.db["assignments"].values() if a.get("matter_id") == matter_id],
        key=store.order_key,
    )


def rep_assignments(rep_id):
    return sorted(
        [a for a in store.db["assignments"].values()
         if a.get("representative_id") == rep_id],
        key=store.order_key,
    )


def recompute_rep_counters(rep, bump=True):
    case_load = 0
    for assignment in store.db["assignments"].values():
        if (assignment.get("representative_id") == rep["id"]
                and assignment.get("status") == "ACTIVE"
                and assignment.get("role_on_case") in CASELOAD_ROLES):
            case_load += 1
    supervisees = 0
    for assignment in store.db["assignments"].values():
        if assignment.get("status") != "ACTIVE":
            continue
        link_id = assignment.get("supervision_link_id")
        if not link_id:
            continue
        link = store.get("assignments", link_id)
        if link is not None and link.get("representative_id") == rep["id"]:
            supervisees += 1
    changed = (rep.get("active_case_load") != case_load
               or rep.get("supervisee_count") != supervisees)
    rep["active_case_load"] = case_load
    rep["supervisee_count"] = supervisees
    if bump and changed:
        store.touch(rep)
    return rep


def recompute_all_rep_counters(bump=True):
    for rep in list(store.db["representatives"].values()):
        recompute_rep_counters(rep, bump=bump)


def supervisor_link_eligible(link_assignment, matter, client):
    if link_assignment is None:
        return False
    if link_assignment.get("matter_id") != matter["id"]:
        return False
    if link_assignment.get("status") != "ACTIVE":
        return False
    if link_assignment.get("role_on_case") != "SUPERVISOR":
        return False
    rep = store.get("representatives", link_assignment.get("representative_id"))
    if rep is None:
        return False
    if rep.get("rep_type") != "STAFF_ATTORNEY":
        return False
    if rep.get("status") != "ACTIVE":
        return False
    if authorization_status(rep) != "AUTHORIZED_ATTORNEY":
        return False
    if int(rep.get("supervisee_count") or 0) >= int(rep.get("max_supervisees") or 0):
        return False
    languages = rep.get("languages") or []
    if client.get("preferred_language_code") not in languages:
        return False
    return True


def supervisor_candidates(matter, client):
    candidates = []
    for assignment in matter_assignments(matter["id"]):
        if supervisor_link_eligible(assignment, matter, client):
            rep = store.get("representatives", assignment["representative_id"])
            candidates.append((assignment, rep))
    candidates.sort(key=lambda pair: (
        int(pair[1].get("supervisee_count") or 0),
        -(int(pair[1].get("max_supervisees") or 0) - int(pair[1].get("supervisee_count") or 0)),
        int(pair[1].get("active_case_load") or 0),
        store.order_key(pair[0]),
    ))
    return candidates


def active_lead(matter_id):
    for assignment in matter_assignments(matter_id):
        if assignment.get("status") == "ACTIVE" and assignment.get("role_on_case") == "LEAD":
            return assignment
    return None


def recompute_representation_status(matter, bump=True):
    """Derive STAFFED / SUPERVISED_STAFFED / COVERAGE_GAP from the lead."""
    if matter.get("representation_status") == "WITHDRAWN_FROM":
        return matter
    lead = active_lead(matter["id"])
    if lead is None:
        if matter.get("representation_status") in ("UNSTAFFED",):
            return matter
        new_status = "COVERAGE_GAP"
        gap = True
    else:
        rep = store.get("representatives", lead.get("representative_id"))
        needs_supervision = rep is not None and supervision_required(rep)
        new_status = "SUPERVISED_STAFFED" if needs_supervision else "STAFFED"
        gap = False
    changed = (matter.get("representation_status") != new_status
               or bool(matter.get("coverage_gap_flag")) != gap)
    matter["representation_status"] = new_status
    matter["coverage_gap_flag"] = gap
    if bump and changed:
        store.touch(matter)
    return matter


# --------------------------------------------------------------------------
# readiness and hours (PRD 3.6, 3.7)
# --------------------------------------------------------------------------

def matter_evidence(matter_id):
    return sorted(
        [e for e in store.db["evidence"].values() if e.get("matter_id") == matter_id],
        key=store.order_key,
    )


def recompute_matter_readiness(matter, bump=True):
    items = matter_evidence(matter["id"])
    counted = [i for i in items if i.get("status") != "WAIVED"]
    counted_weight = sum(int(i.get("weight_points") or 0) for i in counted)
    verified_weight = sum(int(i.get("weight_points") or 0)
                          for i in counted if i.get("status") == "VERIFIED")
    if counted_weight > 0:
        index = store.rhu(store.dec(verified_weight) / store.dec(counted_weight), 4)
    else:
        index = Decimal("0.0000")
    required_total = sum(1 for i in items if i.get("tier") == "REQUIRED")
    required_open = sum(1 for i in items
                        if i.get("tier") == "REQUIRED"
                        and i.get("status") in EVIDENCE_OPEN_STATUSES)
    rejected = sum(1 for i in items if i.get("status") == "REJECTED")
    ready_strict = required_total >= 1 and required_open == 0
    blocking = required_open + rejected
    changed = (matter.get("readiness_index_weighted") != index
               or bool(matter.get("readiness_ready_strict")) != ready_strict
               or matter.get("evidence_blocking_count") != blocking)
    matter["readiness_index_weighted"] = index
    matter["readiness_ready_strict"] = ready_strict
    matter["evidence_blocking_count"] = blocking
    if bump and changed:
        store.touch(matter)
    return matter


def required_evidence_total(matter_id):
    return sum(1 for i in matter_evidence(matter_id) if i.get("tier") == "REQUIRED")


def recompute_matter_hours(matter, bump=True):
    direct = Decimal("0.00")
    supervision = Decimal("0.00")
    for assignment in matter_assignments(matter["id"]):
        direct += store.dec(assignment.get("direct_hours_logged") or 0)
        supervision += store.dec(assignment.get("supervision_hours_logged") or 0)
    direct = store.rhu(direct, 2)
    supervision = store.rhu(supervision, 2)
    changed = (matter.get("direct_hours_logged") != direct
               or matter.get("supervision_hours_logged") != supervision)
    matter["direct_hours_logged"] = direct
    matter["supervision_hours_logged"] = supervision
    if bump and changed:
        store.touch(matter)
    return matter


# --------------------------------------------------------------------------
# interpretation billing (PRD 3.7)
# --------------------------------------------------------------------------

def session_billing(interpreter_source, language_code, actual_minutes):
    minutes = int(actual_minutes)
    increments = -(-minutes // INTERPRETATION_BILLING_INCREMENT_MINUTES)
    billed = increments * INTERPRETATION_BILLING_INCREMENT_MINUTES
    if billed < INTERPRETATION_MIN_BILLED_MINUTES:
        billed = INTERPRETATION_MIN_BILLED_MINUTES
    rate = INTERPRETER_RATE_CENTS_PER_HOUR[interpreter_source]
    surcharge = Decimal("0") if language_code in COMMON_LANGUAGES \
        else RARE_LANGUAGE_SURCHARGE_RATE
    raw = store.dec(rate) * (store.dec(billed) / Decimal("60")) * (Decimal("1") + surcharge)
    return billed, store.rhu_int(raw)


def recompute_matter_interpretation_cost(matter, bump=True):
    total = 0
    for session in store.db["sessions"].values():
        if session.get("matter_id") != matter["id"]:
            continue
        if session.get("status") != "COMPLETED":
            continue
        total += int(session.get("billable_cents") or 0)
    changed = matter.get("interpretation_cost_cents") != total
    matter["interpretation_cost_cents"] = total
    if bump and changed:
        store.touch(matter)
    return matter


# --------------------------------------------------------------------------
# matter deadlines (PRD 3.9)
# --------------------------------------------------------------------------

def matter_decision_date(matter):
    screening = store.get("screenings", matter.get("intake_id"))
    if screening is not None and screening.get("decided_at_utc"):
        parsed = store.parse_dt(screening["decided_at_utc"])
        if parsed is not None:
            return parsed.date()
    parsed = store.parse_dt(matter.get("created_at"))
    return parsed.date() if parsed else store.clock_date()


def recompute_matter_deadlines(matter):
    statutory = store.parse_date(matter.get("statutory_deadline_date"))
    expedited = None
    if matter.get("detained") and matter.get("facility_id"):
        facility = store.get("facilities", matter["facility_id"])
        if facility is not None:
            days = int(facility.get("expedited_filing_days") or 0)
            expedited = matter_decision_date(matter) + datetime.timedelta(days=days)
    candidates = [d for d in (statutory, expedited) if d is not None]
    effective = min(candidates) if candidates else None
    matter["expedited_deadline_date"] = expedited.isoformat() if expedited else None
    matter["effective_filing_deadline_date"] = effective.isoformat() if effective else None
    return matter


def readiness_gate_name(detained):
    return "EVIDENCE_WEIGHTED_GATE" if detained else "CHECKLIST_STRICT_GATE"


# --------------------------------------------------------------------------
# calendar geometry (PRD 3.8)
# --------------------------------------------------------------------------

def travel_buffer(event_type):
    return TRAVEL_BUFFER_MINUTES.get(event_type, 0)


def matter_client_id(matter_id):
    matter = store.get("matters", matter_id)
    return matter.get("client_id") if matter else None


def scan_calendar_conflicts(candidate, exclude_event_id=None):
    """Representative -> client -> facility, first trip reported (PRD 3.8)."""
    start = candidate["starts_at_utc"]
    end = candidate["ends_at_utc"]
    rep_id = candidate.get("assigned_representative_id")
    active = [e for e in store.db["events"].values()
              if e.get("status") in EVENT_ACTIVE_STATUSES and e["id"] != exclude_event_id]
    active.sort(key=store.order_key)

    if rep_id:
        for existing in active:
            if existing.get("assigned_representative_id") != rep_id:
                continue
            existing_start = store.parse_dt(existing["starts_at_utc"])
            existing_end = store.parse_dt(existing["ends_at_utc"])
            buffer_minutes = 0
            if existing.get("location_code") != candidate.get("location_code"):
                buffer_minutes = travel_buffer(existing.get("event_type"))
            padded_end = existing_end + datetime.timedelta(minutes=buffer_minutes)
            if start < padded_end and existing_start < end:
                raise ApiError(
                    "ERR_REPRESENTATIVE_CALENDAR_CONFLICT",
                    "The assigned representative already has an overlapping event.",
                )

    if not candidate.get("client_conflict_waived") \
            and candidate.get("event_type") != "FILING_DEADLINE":
        client_id = matter_client_id(candidate.get("matter_id"))
        if client_id:
            for existing in active:
                if existing.get("event_type") == "FILING_DEADLINE":
                    continue
                if matter_client_id(existing.get("matter_id")) != client_id:
                    continue
                existing_start = store.parse_dt(existing["starts_at_utc"])
                existing_end = store.parse_dt(existing["ends_at_utc"])
                if start <= existing_end and existing_start <= end:
                    raise ApiError(
                        "ERR_CLIENT_CALENDAR_CONFLICT",
                        "The client already has an overlapping event.",
                    )

    if candidate.get("event_type") == "FACILITY_VISIT" and candidate.get("facility_id"):
        facility = store.get("facilities", candidate["facility_id"])
        if facility is not None:
            day = start.date()
            count = 0
            for existing in active:
                if existing.get("event_type") != "FACILITY_VISIT":
                    continue
                if existing.get("facility_id") != candidate["facility_id"]:
                    continue
                existing_start = store.parse_dt(existing["starts_at_utc"])
                if existing_start is not None and existing_start.date() == day:
                    count += 1
            if count >= int(facility.get("max_daily_visit_slots") or 0):
                raise ApiError(
                    "ERR_FACILITY_VISIT_SLOTS_EXHAUSTED",
                    "The facility has no remaining visit slots on that date.",
                )


# --------------------------------------------------------------------------
# grant reimbursement (PRD 3.10)
# --------------------------------------------------------------------------

def grant_surcharge_rate(base_cents):
    for floor, rate in GRANT_SURCHARGE_RATES:
        if base_cents >= floor:
            return rate
    return Decimal("0.00")


def grant_financials(lines):
    """lines is the ordered list of matters in the report's line set."""
    from fractions import Fraction

    per_matter = []
    for matter in lines:
        hours = store.dec(matter.get("direct_hours_logged") or 0)
        per_matter.append(store.rhu_int(store.dec(REIMBURSEMENT_RATE_CENTS_PER_HOUR) * hours))
    base = sum(per_matter)
    rate = grant_surcharge_rate(base)
    surcharge = store.rhu_int(store.dec(base) * rate)
    total = base + surcharge

    hours_list = [store.dec(m.get("direct_hours_logged") or 0) for m in lines]
    sum_hours = sum(hours_list) if hours_list else Decimal("0")
    allocations = [0] * len(lines)
    leftover = 0
    if lines and sum_hours > 0 and total > 0:
        ideals = []
        for hours in hours_list:
            ideals.append(Fraction(total) * Fraction(hours) / Fraction(sum_hours))
        floors = [int(value) for value in ideals]
        remainders = [ideals[i] - floors[i] for i in range(len(ideals))]
        leftover = total - sum(floors)
        allocations = list(floors)
        order = sorted(
            range(len(lines)),
            key=lambda i: (-remainders[i], store.order_key(lines[i])),
        )
        for i in order[:max(0, leftover)]:
            allocations[i] += 1
    elif sum_hours == 0:
        base = 0
        surcharge = 0
        total = 0

    return {
        "base_reimbursable_cents": base,
        "supervision_surcharge_cents": surcharge,
        "total_reimbursable_cents": total,
        "allocated_line_total_cents": sum(allocations),
        "rounding_remainder_cents": leftover,
        "allocations": allocations,
    }


def empty_outcomes_summary():
    """The histogram of a report that has no line set at all.

    PRD 3.11 opens a report with "an empty `outcomes_summary`", so a key is only
    present once some matter has been counted under it.
    """
    return {}


def outcomes_summary(lines):
    """Histogram the line set by `outcome`, folding unrecorded outcomes together.

    Keys are minted on first use, matching the empty histogram a report starts
    from, so the values still sum to `cases_served_count`.
    """
    summary = {}
    for matter in lines:
        outcome = matter.get("outcome")
        if outcome not in MATTER_OUTCOMES:
            outcome = "NOT_YET_DECIDED"
        summary[outcome] = summary.get(outcome, 0) + 1
    return summary
