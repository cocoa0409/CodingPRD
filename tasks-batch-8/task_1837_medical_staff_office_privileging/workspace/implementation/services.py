"""Business logic: derived fields, calculations, cascades, clock advance."""
import math
import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from util import parse_dt, fmt_dt, add_years

# --- Constants (scaffold §1.3) ----------------------------------------------
TERM_YEARS = 2
REAPPOINTMENT_WINDOW_DAYS = 180
NPDB_REPORT_WINDOW_DAYS = 30
HEARING_REQUEST_WINDOW_DAYS = 30
RISK_SUSPEND_THRESHOLD = Decimal("75.00")
COMMITTEE_QUORUM = 3
MIN_HEARING_QUORUM = 3
QUORUM_RATIO = 0.5
TRAINING_BONUS_CAP_MONTHS = 24
TRAINING_BONUS_PER_MONTH = Decimal("0.5")
CASE_SCORE_CAP = 1000
SATISFACTORY_MIN = Decimal("70.00")
MARGINAL_MIN = Decimal("50.00")
CRITICAL_KINDS = {"STATE_LICENSE", "MALPRACTICE_INSURANCE"}
SUSPENDING_KINDS = {"STATE_LICENSE", "BOARD_CERT", "MALPRACTICE_INSURANCE"}

OPEN_CASE_STATES = {"PROPOSED", "MEC_ENDORSED", "HEARING_REQUESTED",
                    "HEARING_HELD", "REMANDED"}
IN_FLIGHT_APP_STATES = {"SUBMITTED", "PSV_IN_PROGRESS", "PSV_COMPLETE",
                        "COMMITTEE_REVIEW", "BOARD_REVIEW"}


# --- Generic record helpers --------------------------------------------------

def now_iso():
    return fmt_dt(db.clock_now())


def new_id():
    return str(uuid.uuid4())


def touch(rec):
    """Refresh updated_at and bump version (records that carry them)."""
    if "updated_at" in rec:
        rec["updated_at"] = now_iso()
    if "version" in rec:
        rec["version"] += 1


def base_record():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def round2(value):
    """Round half-up to exactly 2 decimal places; returned as float."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# --- Member derived fields ----------------------------------------------------

def member_grants(member_id):
    return [g for g in db.grants.values() if g["member_id"] == member_id]


def criteria_for(member, privilege_line):
    for c in db.criteria.values():
        if (c["specialty_code"] == member["primary_specialty_code"]
                and c["privilege_line"] == privilege_line):
            return c
    return None


def recompute_member_derived(member, force_posture=None):
    """Reconcile active_privilege_line_count and privilege_posture (PRD §2.8)."""
    changed = False
    grants = member_grants(member["id"])
    active = sum(1 for g in grants if g["grant_status"] == "ACTIVE")
    if member["active_privilege_line_count"] != active:
        member["active_privilege_line_count"] = active
        changed = True
    if force_posture is not None:
        posture = force_posture
    elif member["membership_status"] in ("TERMINATED", "LAPSED"):
        posture = "NONE"
    else:
        any_suspended = any(g["grant_status"] == "SUSPENDED" for g in grants)
        has_temp = any(
            t["member_id"] == member["id"] and t["temp_status"] == "ACTIVE"
            for t in db.temps.values()
        )
        if active > 0 and not any_suspended:
            posture = "FULL"
        elif active > 0:
            posture = "PARTIAL"
        elif has_temp:
            posture = "EMERGENCY_ONLY"
        else:
            posture = "NONE"
    if member["privilege_posture"] != posture:
        member["privilege_posture"] = posture
        changed = True
    if changed:
        touch(member)


# --- Credential expiry risk (calculation: credential_expiry_risk_window) -----

def compute_risk(member, as_of=None):
    ref = as_of if as_of is not None else db.clock_now()
    total = Decimal("0")
    for c in db.credentials.values():
        if c["member_id"] != member["id"]:
            continue
        if c["credential_status"] != "CURRENT":
            continue
        if as_of is not None and parse_dt(c["issued_on"]) > as_of:
            continue
        days = math.floor(
            (parse_dt(c["expires_on"]) - ref).total_seconds() / 86400
        )
        if days < 0:
            contrib = Decimal("100")
        elif days <= 30:
            contrib = Decimal("50")
        elif days <= 90:
            contrib = Decimal("25")
        else:
            contrib = Decimal("0")
        if c["credential_kind"] in CRITICAL_KINDS:
            contrib *= Decimal("1.5")
        total += contrib
    return float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def recompute_risk(member):
    score = compute_risk(member)
    if member["credential_expiry_risk_score"] != score:
        member["credential_expiry_risk_score"] = score
        touch(member)


# --- Grant cascades ------------------------------------------------------------

def grant_requires_kind(member, grant, kind):
    if kind in ("STATE_LICENSE", "MALPRACTICE_INSURANCE"):
        return True
    if kind == "BOARD_CERT":
        crit = criteria_for(member, grant["privilege_line"])
        return bool(crit and crit.get("required_board_cert"))
    return False


def suspend_grants_for_credential(member, kind):
    """Cascade link 2/3: lapse or revocation of a mandatory credential."""
    for g in db.grants.values():
        if (g["member_id"] == member["id"] and g["grant_status"] == "ACTIVE"
                and grant_requires_kind(member, g, kind)):
            g["grant_status"] = "SUSPENDED"
            g["suspension_reason"] = kind
            touch(g)
            for ai in db.agenda_items.values():
                if (ai["item_kind"] == "PRIVILEGE_GRANT"
                        and ai.get("ref_delineation_id") == g["delineation_id"]
                        and ai["committee_status"] == "AGENDA"):
                    ai["committee_status"] = "DEFERRED"
                    touch(ai)
    recompute_member_derived(member)


def reinstate_grants_for_credential(member, kind):
    for g in db.grants.values():
        if (g["member_id"] == member["id"] and g["grant_status"] == "SUSPENDED"
                and g.get("suspension_reason") == kind):
            g["grant_status"] = "ACTIVE"
            g["suspension_reason"] = None
            touch(g)
    recompute_member_derived(member)


def maybe_activate_grant(grant):
    """PROVISIONAL -> ACTIVE once FPPE cases reach the criteria count."""
    if grant["grant_status"] != "PROVISIONAL":
        return
    member = db.members.get(grant["member_id"])
    crit = criteria_for(member, grant["privilege_line"]) if member else None
    required = crit["fppe_case_count"] if crit else 0
    if grant["fppe_cases_completed"] >= required:
        grant["grant_status"] = "ACTIVE"
        touch(grant)
        if member:
            recompute_member_derived(member)


def create_grant(member, delineation):
    grant = base_record()
    grant.update({
        "member_id": member["id"],
        "delineation_id": delineation["id"],
        "privilege_line": delineation["privilege_line"],
        "grant_status": "PROVISIONAL",
        "effective_from": now_iso(),
        "effective_until": member.get("current_term_end"),
        "fppe_cases_completed": 0,
        "suspension_reason": None,
    })
    db.grants[grant["id"]] = grant
    recompute_member_derived(member)
    maybe_activate_grant(grant)
    return grant


# --- Verification counts / PSV automation --------------------------------------

def app_items(app_id):
    return [i for i in db.verification_items.values()
            if i["application_id"] == app_id]


def recompute_verification_counts(app):
    items = app_items(app["id"])
    required = sum(1 for i in items if i["item_status"] != "WAIVED")
    complete = sum(1 for i in items if i["item_status"] == "VERIFIED")
    changed = False
    if app["verification_required_count"] != required:
        app["verification_required_count"] = required
        changed = True
    if app["verification_complete_count"] != complete:
        app["verification_complete_count"] = complete
        changed = True
    if changed:
        touch(app)


def maybe_complete_psv(app):
    """PSV_IN_PROGRESS -> PSV_COMPLETE when the file is fully resolved."""
    if app["application_status"] != "PSV_IN_PROGRESS":
        return
    items = app_items(app["id"])
    open_states = {"PENDING", "REQUESTED", "RECEIVED", "DISCREPANCY"}
    if (app["verification_complete_count"] == app["verification_required_count"]
            and not any(i["item_status"] in open_states for i in items)):
        app["application_status"] = "PSV_COMPLETE"
        touch(app)


# --- Delineation satisfaction (calculation: privilege_delineation_satisfaction)

def evaluate_delineation(delineation):
    app = db.applications[delineation["application_id"]]
    member = db.members[app["member_id"]]
    crit = criteria_for(member, delineation["privilege_line"])
    now = db.clock_now()

    mandatory_ok = delineation["documented_training_months"] >= crit["min_training_months"]
    if crit.get("required_board_cert"):
        has_cert = any(
            c["member_id"] == member["id"]
            and c["credential_kind"] == "BOARD_CERT"
            and c["credential_status"] == "CURRENT"
            and parse_dt(c["expires_on"]) > now
            for c in db.credentials.values()
        )
        mandatory_ok = mandatory_ok and has_cert

    volume_ok = delineation["documented_cases_24mo"] >= crit["min_case_volume_24mo"]

    tiers = sorted(crit.get("volume_tier_table") or [],
                   key=lambda t: t.get("min_cases", 0))
    selected = None
    for tier in tiers:
        if tier.get("min_cases", 0) <= delineation["documented_cases_24mo"]:
            selected = tier
    if selected is not None:
        base = Decimal(str(selected.get("score_multiplier", 0))) * Decimal(
            min(delineation["documented_cases_24mo"], CASE_SCORE_CAP))
    else:
        base = Decimal("0")
    excess = max(delineation["documented_training_months"]
                 - crit["min_training_months"], 0)
    bonus = Decimal(min(excess, TRAINING_BONUS_CAP_MONTHS)) * TRAINING_BONUS_PER_MONTH
    score = float((base + bonus).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    if selected is None or not mandatory_ok:
        tier_name = "UNMET"
    else:
        tier_name = selected.get("tier_name")

    delineation["satisfaction_score"] = score
    delineation["satisfaction_tier"] = tier_name
    if mandatory_ok and volume_ok and selected is not None:
        delineation["delineation_status"] = "CRITERIA_MET"
    else:
        delineation["delineation_status"] = "CRITERIA_UNMET"
    touch(delineation)


# --- Metric normalization / review composites -----------------------------------

def normalize_metric(raw_value, domain):
    raw = Decimal(str(raw_value))
    if domain == "CLINICAL_QUALITY":
        val = Decimal("100") - raw * Decimal("5")
    elif domain == "PATIENT_SAFETY":
        val = Decimal("100") - raw * Decimal("8")
    elif domain in ("DOCUMENTATION", "CITIZENSHIP"):
        val = raw
    elif domain == "UTILIZATION":
        val = Decimal("100") - abs(raw - Decimal("85")) * Decimal("2")
    else:
        val = raw
    # Round half-up to 2dp FIRST, then clamp into [0.00, 100.00] (PRD §2.6).
    rounded = val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if rounded < Decimal("0"):
        rounded = Decimal("0.00")
    if rounded > Decimal("100"):
        rounded = Decimal("100.00")
    return float(rounded)


def review_metrics(review_id):
    return [m for m in db.metrics.values() if m["review_id"] == review_id]


def recompute_review_counts(review):
    ms = review_metrics(review["id"])
    active = sum(1 for m in ms if m["metric_status"] == "ACTIVE")
    retracted = sum(1 for m in ms if m["metric_status"] == "RETRACTED")
    changed = False
    if review["metric_count"] != active:
        review["metric_count"] = active
        changed = True
    if review["retracted_metric_count"] != retracted:
        review["retracted_metric_count"] = retracted
        changed = True
    if changed:
        touch(review)


def composite_score(review, variant):
    """fppe_composite_score. provisional: boundary-inclusive; final: half-open."""
    period_end = parse_dt(review["period_end"])
    included = []
    for m in review_metrics(review["id"]):
        if m["metric_status"] != "ACTIVE":
            continue
        if variant == "final" and parse_dt(m["collected_at"]) >= period_end:
            continue
        included.append(m)
    by_domain = {}
    for m in included:
        by_domain.setdefault(m["metric_domain"], []).append(m)
    total = Decimal("0")
    for domain, ms in by_domain.items():
        vals = [Decimal(str(m["normalized_value"])) for m in ms]
        avg = (sum(vals) / Decimal(len(vals))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)
        weight = Decimal(str(ms[0]["domain_weight"]))
        total += avg * weight
    return float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def outcome_for(final_score):
    s = Decimal(str(final_score))
    if s >= SATISFACTORY_MIN:
        return "SATISFACTORY"
    if s >= MARGINAL_MIN:
        return "MARGINAL"
    return "UNSATISFACTORY"


# --- Hearing quorum (calculation: hearing_quorum_determination) -----------------

def quorum_required_for_case(case_id):
    total_ever_seated = sum(1 for p in db.panels.values()
                            if p["case_id"] == case_id)
    return max(MIN_HEARING_QUORUM, math.ceil(total_ever_seated * QUORUM_RATIO))


def eligible_panel_count(case_id):
    count = 0
    for p in db.panels.values():
        if p["case_id"] != case_id or p["panel_status"] != "SEATED":
            continue
        member = db.members.get(p["panel_member_id"])
        if member and case_id in (member.get("sod_exclusion_tags") or []):
            continue
        count += 1
    return count


# --- NPDB filings -----------------------------------------------------------------

def spawn_npdb_report(member_id, case_id, report_kind, submission_deadline_dt):
    rec = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": db.next_seq(),
        "member_id": member_id,
        "case_id": case_id,
        "report_kind": report_kind,
        "submitted_at": now_iso(),
        "submission_deadline": (fmt_dt(submission_deadline_dt)
                                if submission_deadline_dt else None),
        "report_status": "SUBMITTED",
        "is_late": False,
    }
    if submission_deadline_dt is not None and db.clock_now() > submission_deadline_dt:
        rec["is_late"] = True
        rec["report_status"] = "LATE"
    db.npdb_reports[rec["id"]] = rec
    return rec


# --- Adverse action finalization ---------------------------------------------------

def apply_final_adverse(case):
    """Shared side effects for UPHELD decisions and waiver-by-silence."""
    now = db.clock_now()
    case["case_status"] = "FINAL_ADVERSE"
    kind = case["case_kind"]
    reportable = (kind in ("SUSPENSION", "REVOCATION", "DENIAL_OF_REAPPOINTMENT")
                  or (kind == "RESTRICTION"
                      and (case.get("restriction_days") or 0) > 30))
    case["npdb_reportable"] = reportable
    touch(case)
    if reportable:
        spawn_npdb_report(case["subject_member_id"], case["id"],
                          "REPORT_ADVERSE_ACTION",
                          now + timedelta(days=NPDB_REPORT_WINDOW_DAYS))
    member = db.members.get(case["subject_member_id"])
    if member is not None:
        member_changed = False
        if kind == "SUSPENSION":
            if member["membership_status"] == "ACTIVE":
                member["membership_status"] = "SUSPENDED"
                member_changed = True
            for g in member_grants(member["id"]):
                if g["grant_status"] == "ACTIVE":
                    g["grant_status"] = "SUSPENDED"
                    touch(g)
            recompute_member_derived(member)
        elif kind in ("REVOCATION", "DENIAL_OF_REAPPOINTMENT"):
            if member["membership_status"] != "TERMINATED":
                member["membership_status"] = "TERMINATED"
                member_changed = True
            for g in member_grants(member["id"]):
                if g["grant_status"] in ("ACTIVE", "PROVISIONAL"):
                    g["grant_status"] = "REVOKED"
                    touch(g)
                    if kind == "REVOCATION":
                        spawn_npdb_report(
                            member["id"], case["id"], "REPORT_ADVERSE_ACTION",
                            now + timedelta(days=NPDB_REPORT_WINDOW_DAYS))
            recompute_member_derived(member, force_posture="NONE")
        # recompute_member_derived touches when derived fields change; ensure a
        # status change alone also refreshes the audit trail.
        if member_changed:
            touch(member)
    for ai in db.agenda_items.values():
        if (ai["item_kind"] == "ADVERSE_ACTION"
                and ai.get("ref_case_id") == case["id"]
                and ai["committee_status"] == "AGENDA"):
            ai["committee_status"] = "COMMITTEE_APPROVED"
            touch(ai)


# --- Application approval / denial cascades -----------------------------------------

def create_agenda_item_for_application(app):
    for ai in db.agenda_items.values():
        if (ai["item_kind"] == "APPLICATION_APPROVAL"
                and ai.get("ref_application_id") == app["id"]):
            return ai
    item = base_record()
    item.update({
        "item_kind": "APPLICATION_APPROVAL",
        "ref_application_id": app["id"],
        "ref_delineation_id": None,
        "ref_case_id": None,
        "committee_status": "AGENDA",
        "committee_votes_for": 0,
        "committee_votes_against": 0,
        "quorum_required": COMMITTEE_QUORUM,
        "mec_voter_ids": [],
        "board_voter_id": None,
    })
    db.agenda_items[item["id"]] = item
    return item


def approve_application(app):
    now = db.clock_now()
    app["application_status"] = "APPROVED"
    touch(app)
    member = db.members[app["member_id"]]
    member["current_term_start"] = fmt_dt(now)
    member["current_term_end"] = fmt_dt(add_years(now, TERM_YEARS))
    if app["application_kind"] == "INITIAL":
        if member["membership_status"] == "APPLICANT":
            member["membership_status"] = "ACTIVE"
    touch(member)
    for d in db.delineations.values():
        if d["application_id"] != app["id"]:
            continue
        if d["delineation_status"] == "CRITERIA_MET":
            d["delineation_status"] = "GRANTED"
            touch(d)
            create_grant(member, d)
        elif d["delineation_status"] == "CRITERIA_UNMET":
            d["delineation_status"] = "DENIED"
            touch(d)
    recompute_member_derived(member)


def deny_application(app, agenda_item=None):
    app["application_status"] = "DENIED"
    # The deciding agenda item carries no rationale field; nothing to copy.
    app["decision_reason"] = None
    touch(app)
    if app["application_kind"] == "REAPPOINTMENT":
        member = db.members[app["member_id"]]
        create_case(
            subject_member_id=member["id"],
            proposed_by_member_id=None,
            case_kind="DENIAL_OF_REAPPOINTMENT",
            restriction_days=0,
            linked_review_id=None,
        )


def create_case(subject_member_id, proposed_by_member_id, case_kind,
                restriction_days=0, linked_review_id=None):
    now = db.clock_now()
    rec = base_record()
    rec.update({
        "subject_member_id": subject_member_id,
        "proposed_by_member_id": proposed_by_member_id,
        "case_kind": case_kind,
        "case_status": "PROPOSED",
        "proposed_at": fmt_dt(now),
        "hearing_request_deadline": fmt_dt(
            now + timedelta(days=HEARING_REQUEST_WINDOW_DAYS)),
        "hearing_requested_at": None,
        "npdb_reportable": False,
        "restriction_days": restriction_days or 0,
        "linked_review_id": linked_review_id,
    })
    db.cases[rec["id"]] = rec
    return rec


# --- Clock advance --------------------------------------------------------------------

def advance_clock():
    """Fire every lapse/expiration cascade armed by the new clock reading."""
    now = db.clock_now()

    # 1. Credentials lapse (clock reaches expires_on).
    for c in list(db.credentials.values()):
        if (c["credential_status"] == "CURRENT"
                and parse_dt(c["expires_on"]) <= now):
            c["credential_status"] = "LAPSED"
            touch(c)
            member = db.members.get(c["member_id"])
            if member is not None and c["credential_kind"] in SUSPENDING_KINDS:
                suspend_grants_for_credential(member, c["credential_kind"])

    # 2. ACTIVE grants expire at effective_until (half-open upper bound).
    for g in list(db.grants.values()):
        if (g["grant_status"] == "ACTIVE" and g.get("effective_until")
                and parse_dt(g["effective_until"]) <= now):
            g["grant_status"] = "EXPIRED"
            touch(g)
            member = db.members.get(g["member_id"])
            if member is not None:
                recompute_member_derived(member)

    # 3. Active temporary privileges expire once strictly past window_end.
    for t in list(db.temps.values()):
        if (t["temp_status"] == "ACTIVE"
                and parse_dt(t["window_end"]) < now):
            t["temp_status"] = "EXPIRED"
            touch(t)
            member = db.members.get(t["member_id"])
            if member is not None:
                recompute_member_derived(member)

    # 4. Appointment terms close out.
    for m in list(db.members.values()):
        term_end = m.get("current_term_end")
        if not term_end or parse_dt(term_end) > now:
            continue
        if m["membership_status"] != "ACTIVE":
            continue
        m["membership_status"] = "LAPSED"
        for g in member_grants(m["id"]):
            if g["grant_status"] == "ACTIVE":
                g["grant_status"] = "EXPIRED"
                touch(g)
        for app in db.applications.values():
            if (app["member_id"] == m["id"]
                    and app["application_kind"] == "REAPPOINTMENT"
                    and app["application_status"] == "BOARD_REVIEW"):
                app["application_status"] = "EXPIRED"
                touch(app)
        recompute_member_derived(m, force_posture="NONE")
        touch(m)

    # 5. Hearing-request deadlines elapse (waiver by silence).
    for case in list(db.cases.values()):
        if (case["case_status"] == "MEC_ENDORSED"
                and case.get("hearing_requested_at") is None
                and parse_dt(case["hearing_request_deadline"]) < now):
            apply_final_adverse(case)

    # 6. Expiry risk recomputed for every member.
    for m in list(db.members.values()):
        recompute_risk(m)
