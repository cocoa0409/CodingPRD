"""Business logic: derived fields, readiness scoring, cascades, clock sweep.

Implements SCAFFOLD.yaml state machines / calculations and the PRD §3
workflows. All readiness figures, counts, staffing posture, and field-day
scores are computed live from the store (consistency_model: immediate) — a
recomputation is not itself a version-bumping mutation; version increments
happen exactly on the mutations declared in the state-machine side effects
(PRD §2.4). Money/fee math uses Decimal with ROUND_HALF_UP (PRD §2.8).
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import ERR_NOT_FOUND, ApiError
from util import LICENSE_ORDER, iso_ts, new_id

EPOCH = datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

# --- calculations.member_readiness constants ---
W_CHECKIN = 50
CHECKIN_TARGET = 6
W_DRILL = 30
DRILL_TARGET = 2
BONUS_NO_SHOW_FREE = 20
PRIVILEGE_PENALTY = 50
TIER_ELIGIBLE_MIN = 70
TIER_PROVISIONAL_MIN = 40
TRAILING_DAYS = 365

# --- calculations.equipment_late_fee constants ---
DAILY_RATE_CENTS = 150
DAMAGE_RATE = Decimal("0.10")

# --- calculations.contact_points / field_day_scores constants ---
PER_CONTACT_CAP = 10
BONUS_THRESHOLD = 100
BONUS_POINTS = 100
MODE_BASE = {"CW": 2, "DIGITAL": 2, "PHONE": 1}
POWER_MULT = {"QRP": 5, "LOW": 2, "HIGH": 1}
BONUS_BANDS = {"B6M", "B2M"}

ANNUAL_DUES_CENTS = 3600
EXAM_PASS_PERCENT = 74
EXAM_PASS_LICENSE_DAYS = 3650
LOAN_MAX_DAYS = 90

CANDIDATE_TERMINAL = {"PASSED", "FAILED", "NO_SHOW", "CANCELLED"}


# ---------------------------------------------------------------------------
# Lookup helpers (existence validation -> ERR_NOT_FOUND, priority 3)
# ---------------------------------------------------------------------------

def _get(store, rid, label):
    rec = db.STORE[store].get(rid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 404, "%s not found: %s" % (label, rid))
    return rec


def get_member(rid):
    return _get("members", rid, "Member")


def get_site(rid):
    return _get("site_agreements", rid, "AntennaSiteAgreement")


def get_repeater(rid):
    return _get("repeaters", rid, "Repeater")


def get_coord(rid):
    return _get("coordination_requests", rid, "CoordinationRequest")


def get_net(rid):
    return _get("net_sessions", rid, "NetSession")


def get_checkin(rid):
    return _get("check_ins", rid, "CheckIn")


def get_agency(rid):
    return _get("agency_agreements", rid, "ServedAgencyAgreement")


def get_activation(rid):
    return _get("activations", rid, "EmergencyActivation")


def get_roster(rid):
    return _get("roster_entries", rid, "RosterEntry")


def get_drill(rid):
    return _get("drills", rid, "Drill")


def get_message(rid):
    return _get("drill_messages", rid, "DrillMessage")


def get_event(rid):
    return _get("field_day_events", rid, "FieldDayEvent")


def get_contact(rid):
    return _get("field_day_contacts", rid, "FieldDayContact")


def get_session(rid):
    return _get("exam_sessions", rid, "ExamSession")


def get_candidate(rid):
    return _get("exam_candidates", rid, "ExamCandidate")


def get_loan(rid):
    return _get("equipment_loans", rid, "EquipmentLoan")


# ---------------------------------------------------------------------------
# Record plumbing
# ---------------------------------------------------------------------------

def stamp_new(rec):
    rec["id"] = new_id()
    rec["created_at"] = db.now()
    rec["updated_at"] = db.now()
    rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec):
    """Every declared mutation refreshes updated_at and increments version."""
    rec["updated_at"] = db.now()
    rec["version"] += 1


def sorted_records(store_name):
    return sorted(
        db.STORE[store_name].values(),
        key=lambda r: (r["created_at"], r["_seq"]),
    )


def license_at_least(member, min_class):
    return LICENSE_ORDER[member["license_class"]] >= LICENSE_ORDER[min_class]


# ---------------------------------------------------------------------------
# calculations.member_readiness (verified + optimistic variants)
# ---------------------------------------------------------------------------

def _trailing_start():
    return db.now() - timedelta(days=TRAILING_DAYS)


def _readiness_inputs(member):
    """Returns (ci_verified, ci_optimistic, dr_verified, dr_optimistic, no_shows)."""
    window_start = _trailing_start()
    ci_v = ci_o = 0
    for c in db.STORE["check_ins"].values():
        if c["member_id"] != member["id"] or c["checked_in_at"] < window_start:
            continue
        net = db.STORE["net_sessions"].get(c["net_session_id"])
        if net is None:
            continue
        if net["status"] == "CLOSED":
            ci_v += 1
            ci_o += 1
        elif net["status"] == "OPEN":
            ci_o += 1
    dr_v = dr_o = 0
    for d in db.STORE["drills"].values():
        if d["scheduled_start"] < window_start:
            continue
        if d["status"] not in ("IN_PROGRESS", "COMPLETED"):
            continue
        handled = any(
            msg["drill_id"] == d["id"]
            and msg["originator_member_id"] == member["id"]
            and msg["status"] in ("RELAYED", "DELIVERED")
            for msg in db.STORE["drill_messages"].values()
        )
        if not handled:
            continue
        if d["status"] == "COMPLETED":
            dr_v += 1
            dr_o += 1
        else:
            dr_o += 1
    ns = 0
    for r in db.STORE["roster_entries"].values():
        if (r["member_id"] == member["id"] and r["status"] == "NO_SHOW"
                and r["updated_at"] >= window_start):
            ns += 1
    return ci_v, ci_o, dr_v, dr_o, ns


def _score(ci_count, dr_count, no_shows, privilege):
    """Single final round-half-up after summing all components (PRD §2.8)."""
    ci = min(Decimal(ci_count) / Decimal(CHECKIN_TARGET), Decimal(1))
    dr = min(Decimal(dr_count) / Decimal(DRILL_TARGET), Decimal(1))
    total = (Decimal(W_CHECKIN) * ci + Decimal(W_DRILL) * dr
             + (BONUS_NO_SHOW_FREE if no_shows == 0 else 0)
             - (PRIVILEGE_PENALTY if privilege == "SUSPENDED" else 0))
    score = int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return max(0, score)


def member_readiness(member):
    """Live computation of the member's readiness fields (both variants)."""
    ci_v, ci_o, dr_v, dr_o, ns = _readiness_inputs(member)
    verified = _score(ci_v, dr_v, ns, member["equipment_privilege"])
    optimistic = _score(ci_o, dr_o, ns, member["equipment_privilege"])
    if verified >= TIER_ELIGIBLE_MIN:
        tier = "ELIGIBLE"
    elif verified >= TIER_PROVISIONAL_MIN:
        tier = "PROVISIONAL"
    else:
        tier = "INELIGIBLE"
    return {
        "readiness_score": verified,
        "readiness_score_optimistic": optimistic,
        "readiness_tier": tier,
        "check_ins_12m_count": ci_v,
        "drills_12m_count": dr_v,
        "no_shows_12m_count": ns,
    }


# ---------------------------------------------------------------------------
# Live counts / scores on other aggregates
# ---------------------------------------------------------------------------

def net_checkin_count(net):
    return sum(1 for c in db.STORE["check_ins"].values()
               if c["net_session_id"] == net["id"])


def activation_confirmed_count(act):
    return sum(1 for r in db.STORE["roster_entries"].values()
               if r["activation_id"] == act["id"] and r["status"] == "CONFIRMED")


def activation_staffing(act):
    confirmed = activation_confirmed_count(act)
    posture = "ADEQUATE" if confirmed >= act["required_operators"] else "UNDERSTAFFED"
    return confirmed, posture


def contact_points(mode, band, power_category):
    """calculations.contact_points — computed once at creation, immutable."""
    raw = MODE_BASE[mode] * POWER_MULT[power_category]
    if band in BONUS_BANDS:
        raw += 2
    return min(PER_CONTACT_CAP, raw)


def event_scores(event):
    """calculations.field_day_scores — live until FINALIZED locks final_score."""
    contacts = [c for c in db.STORE["field_day_contacts"].values()
                if c["event_id"] == event["id"]]
    provisional = sum(c["points"] for c in contacts)
    if len(contacts) >= BONUS_THRESHOLD:
        provisional += BONUS_POINTS
    non_dup = [c for c in contacts if not c["is_duplicate"]]
    final = sum(c["points"] for c in non_dup)
    if len(non_dup) >= BONUS_THRESHOLD:
        final += BONUS_POINTS
    if event["status"] == "FINALIZED" and event.get("_final_score_locked") is not None:
        final = event["_final_score_locked"]
    return len(contacts), provisional, final


def session_registered_count(session):
    return sum(1 for c in db.STORE["exam_candidates"].values()
               if c["session_id"] == session["id"]
               and c["status"] in ("REGISTERED", "CHECKED_IN"))


# ---------------------------------------------------------------------------
# calculations.equipment_late_fee (pinned two-component nested rounding)
# ---------------------------------------------------------------------------

def compute_late_fee(loan, returned_at, return_condition):
    """Pinned two-component nested rounding (calculations.equipment_late_fee):
    each component is rounded half-up to whole cents first, the rounded
    components are summed, and the cap min(estimated_value_cents, ...) is
    applied last. No lateness component accrues when returned_at <= due_at;
    the damage component applies to any DAMAGED return."""
    seconds = int((returned_at - loan["due_at"]).total_seconds())
    days_overdue = 0 if seconds <= 0 else (seconds + 86399) // 86400
    base_fee = int(Decimal(days_overdue * DAILY_RATE_CENTS).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))
    damage_fee = 0
    if return_condition == "DAMAGED":
        damage_fee = int((Decimal(loan["estimated_value_cents"]) * DAMAGE_RATE)
                         .quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return min(loan["estimated_value_cents"], base_fee + damage_fee)


# ---------------------------------------------------------------------------
# Cascades (PRD §2.6). Each hop is a real mutation: touch() on the resource.
# ---------------------------------------------------------------------------

def cancel_net_cascade(net):
    """Net -> CANCELLED; member readiness inputs change (live-recomputed)."""
    net["status"] = "CANCELLED"
    touch(net)


def repeater_offline_cascade(repeater):
    """Repeater -> OFFLINE; nets in {SCHEDULED, OPEN} on it -> CANCELLED."""
    repeater["status"] = "OFFLINE"
    touch(repeater)
    for net in sorted_records("net_sessions"):
        if (net["repeater_id"] == repeater["id"]
                and net["status"] in ("SCHEDULED", "OPEN")):
            cancel_net_cascade(net)


def site_leaving_active_cascade(site):
    """Site agreement leaves ACTIVE: repeaters -> OFFLINE -> nets CANCELLED."""
    for rep in sorted_records("repeaters"):
        if rep["site_agreement_id"] == site["id"] and rep["status"] != "OFFLINE":
            repeater_offline_cascade(rep)


def resolve_roster_on_activation_close(act):
    """Demobilize/cancel roster resolution: CONFIRMED -> RELEASED,
    VOLUNTEERED -> WITHDRAWN; staffing figures recompute live."""
    for entry in sorted_records("roster_entries"):
        if entry["activation_id"] != act["id"]:
            continue
        if entry["status"] == "CONFIRMED":
            entry["status"] = "RELEASED"
            touch(entry)
        elif entry["status"] == "VOLUNTEERED":
            entry["status"] = "WITHDRAWN"
            touch(entry)


def cancel_activation_cascade(act):
    act["status"] = "CANCELLED"
    touch(act)
    resolve_roster_on_activation_close(act)


def privilege_suspension_cascade(member):
    """DAMAGED return / mark-lost: privilege -> SUSPENDED (member bumped);
    if readiness_tier flips to INELIGIBLE, live roster entries withdraw."""
    tier_before = member_readiness(member)["readiness_tier"]
    member["equipment_privilege"] = "SUSPENDED"
    touch(member)
    tier_after = member_readiness(member)["readiness_tier"]
    if tier_before != "INELIGIBLE" and tier_after == "INELIGIBLE":
        for entry in sorted_records("roster_entries"):
            if (entry["member_id"] != member["id"]
                    or entry["status"] not in ("VOLUNTEERED", "CONFIRMED")):
                continue
            act = db.STORE["activations"].get(entry["activation_id"])
            if act is None or act["status"] not in ("STANDBY", "ACTIVATED"):
                continue
            entry["status"] = "WITHDRAWN"
            touch(entry)


# ---------------------------------------------------------------------------
# Logical clock sweep (PRD §2.5): fixed order, evaluated on set_current_utc.
# ---------------------------------------------------------------------------

def clock_sweep():
    now = db.now()
    # 1. Members ACTIVE -> LAPSED when dues window has passed.
    for m in sorted_records("members"):
        if (m["membership_status"] == "ACTIVE"
                and m["dues_paid_through"] is not None
                and now > m["dues_paid_through"]):
            m["membership_status"] = "LAPSED"
            touch(m)
    # 2. Antenna site agreements ACTIVE -> EXPIRED (repeater/net cascade).
    for site in sorted_records("site_agreements"):
        if site["status"] == "ACTIVE" and now > site["lease_end"]:
            site["status"] = "EXPIRED"
            touch(site)
            site_leaving_active_cascade(site)
    # 3. Served-agency agreements ACTIVE -> EXPIRED (STANDBY activations cancel).
    for ag in sorted_records("agency_agreements"):
        if ag["status"] == "ACTIVE" and now > ag["effective_end"]:
            ag["status"] = "EXPIRED"
            touch(ag)
            for act in sorted_records("activations"):
                if (act["agreement_id"] == ag["id"]
                        and act["status"] == "STANDBY"):
                    cancel_activation_cascade(act)
    # 4. Equipment loans ACTIVE -> OVERDUE when due_at has passed.
    for loan in sorted_records("equipment_loans"):
        if loan["status"] == "ACTIVE" and now > loan["due_at"]:
            loan["status"] = "OVERDUE"
            touch(loan)


# ---------------------------------------------------------------------------
# Serializers (public projections; internal _-prefixed keys excluded).
# Datetimes are stored as datetime objects and rendered ISO 8601 / 3 digits.
# ---------------------------------------------------------------------------

def ser_member(m):
    out = {
        "id": m["id"],
        "callsign": m["callsign"],
        "full_name": m["full_name"],
        "license_class": m["license_class"],
        "license_expires_at": iso_ts(m["license_expires_at"]),
        "membership_status": m["membership_status"],
        "dues_paid_through": iso_ts(m["dues_paid_through"]),
        "equipment_privilege": m["equipment_privilege"],
    }
    out.update(member_readiness(m))
    out["created_at"] = iso_ts(m["created_at"])
    out["updated_at"] = iso_ts(m["updated_at"])
    out["version"] = m["version"]
    return out


def ser_site(s):
    return {
        "id": s["id"],
        "site_name": s["site_name"],
        "owner_name": s["owner_name"],
        "lease_start": iso_ts(s["lease_start"]),
        "lease_end": iso_ts(s["lease_end"]),
        "status": s["status"],
        "renewal_count": s["renewal_count"],
        "created_at": iso_ts(s["created_at"]),
        "updated_at": iso_ts(s["updated_at"]),
        "version": s["version"],
    }


def ser_repeater(r):
    return {
        "id": r["id"],
        "callsign": r["callsign"],
        "output_frequency_mhz": r["output_frequency_mhz"],
        "site_agreement_id": r["site_agreement_id"],
        "status": r["status"],
        "created_at": iso_ts(r["created_at"]),
        "updated_at": iso_ts(r["updated_at"]),
        "version": r["version"],
    }


def ser_coord(c):
    return {
        "id": c["id"],
        "repeater_id": c["repeater_id"],
        "requested_frequency_mhz": c["requested_frequency_mhz"],
        "status": c["status"],
        "council_reference": c["council_reference"],
        "revision_number": c["revision_number"],
        "submitted_at": iso_ts(c["submitted_at"]),
        "decision_at": iso_ts(c["decision_at"]),
        "created_at": iso_ts(c["created_at"]),
        "updated_at": iso_ts(c["updated_at"]),
        "version": c["version"],
    }


def ser_net(n):
    return {
        "id": n["id"],
        "name": n["name"],
        "repeater_id": n["repeater_id"],
        "net_control_member_id": n["net_control_member_id"],
        "scheduled_start": iso_ts(n["scheduled_start"]),
        "scheduled_end": iso_ts(n["scheduled_end"]),
        "min_license_class": n["min_license_class"],
        "status": n["status"],
        "checkin_count": net_checkin_count(n),
        "created_at": iso_ts(n["created_at"]),
        "updated_at": iso_ts(n["updated_at"]),
        "version": n["version"],
    }


def ser_checkin(c):
    """CheckIn carries only id + created_at of the common fields (PRD §2.4)."""
    return {
        "id": c["id"],
        "net_session_id": c["net_session_id"],
        "member_id": c["member_id"],
        "has_traffic": c["has_traffic"],
        "traffic_count": c["traffic_count"],
        "checked_in_at": iso_ts(c["checked_in_at"]),
        "created_at": iso_ts(c["created_at"]),
    }


def ser_agency(a):
    return {
        "id": a["id"],
        "agency_name": a["agency_name"],
        "max_operators": a["max_operators"],
        "effective_start": iso_ts(a["effective_start"]),
        "effective_end": iso_ts(a["effective_end"]),
        "status": a["status"],
        "created_at": iso_ts(a["created_at"]),
        "updated_at": iso_ts(a["updated_at"]),
        "version": a["version"],
    }


def ser_activation(a):
    confirmed, posture = activation_staffing(a)
    return {
        "id": a["id"],
        "agreement_id": a["agreement_id"],
        "title": a["title"],
        "required_operators": a["required_operators"],
        "status": a["status"],
        "activated_by_member_id": a["activated_by_member_id"],
        "activated_at": iso_ts(a["activated_at"]),
        "demobilized_at": iso_ts(a["demobilized_at"]),
        "confirmed_count": confirmed,
        "staffing_posture": posture,
        "created_at": iso_ts(a["created_at"]),
        "updated_at": iso_ts(a["updated_at"]),
        "version": a["version"],
    }


def ser_roster(r):
    return {
        "id": r["id"],
        "activation_id": r["activation_id"],
        "member_id": r["member_id"],
        "status": r["status"],
        "confirmed_at": iso_ts(r["confirmed_at"]),
        "created_at": iso_ts(r["created_at"]),
        "updated_at": iso_ts(r["updated_at"]),
        "version": r["version"],
    }


def ser_drill(d):
    return {
        "id": d["id"],
        "title": d["title"],
        "scheduled_start": iso_ts(d["scheduled_start"]),
        "scheduled_end": iso_ts(d["scheduled_end"]),
        "passing_score": d["passing_score"],
        "status": d["status"],
        "created_at": iso_ts(d["created_at"]),
        "updated_at": iso_ts(d["updated_at"]),
        "version": d["version"],
    }


def ser_message(m):
    return {
        "id": m["id"],
        "drill_id": m["drill_id"],
        "originator_member_id": m["originator_member_id"],
        "precedence": m["precedence"],
        "relay_count": m["relay_count"],
        "status": m["status"],
        "delivered_at": iso_ts(m["delivered_at"]),
        "handling_seconds": m["handling_seconds"],
        "created_at": iso_ts(m["created_at"]),
        "updated_at": iso_ts(m["updated_at"]),
        "version": m["version"],
    }


def ser_event(e):
    count, provisional, final = event_scores(e)
    return {
        "id": e["id"],
        "name": e["name"],
        "start_at": iso_ts(e["start_at"]),
        "end_at": iso_ts(e["end_at"]),
        "status": e["status"],
        "contact_count": count,
        "provisional_score": provisional,
        "final_score": final,
        "created_at": iso_ts(e["created_at"]),
        "updated_at": iso_ts(e["updated_at"]),
        "version": e["version"],
    }


def ser_contact(c):
    return {
        "id": c["id"],
        "event_id": c["event_id"],
        "operator_member_id": c["operator_member_id"],
        "worked_callsign": c["worked_callsign"],
        "band": c["band"],
        "mode": c["mode"],
        "power_category": c["power_category"],
        "is_duplicate": c["is_duplicate"],
        "points": c["points"],
        "created_at": iso_ts(c["created_at"]),
        "updated_at": iso_ts(c["updated_at"]),
        "version": c["version"],
    }


def ser_session(s):
    return {
        "id": s["id"],
        "location": s["location"],
        "scheduled_at": iso_ts(s["scheduled_at"]),
        "max_candidates": s["max_candidates"],
        "status": s["status"],
        "registered_count": session_registered_count(s),
        "created_at": iso_ts(s["created_at"]),
        "updated_at": iso_ts(s["updated_at"]),
        "version": s["version"],
    }


def ser_candidate(c):
    return {
        "id": c["id"],
        "session_id": c["session_id"],
        "candidate_name": c["candidate_name"],
        "frn": c["frn"],
        "element": c["element"],
        "member_id": c["member_id"],
        "status": c["status"],
        "checked_in_by_member_id": c["checked_in_by_member_id"],
        "score_percent": c["score_percent"],
        "created_at": iso_ts(c["created_at"]),
        "updated_at": iso_ts(c["updated_at"]),
        "version": c["version"],
    }


def ser_loan(l):
    return {
        "id": l["id"],
        "item_tag": l["item_tag"],
        "member_id": l["member_id"],
        "estimated_value_cents": l["estimated_value_cents"],
        "checked_out_at": iso_ts(l["checked_out_at"]),
        "due_at": iso_ts(l["due_at"]),
        "returned_at": iso_ts(l["returned_at"]),
        "return_condition": l["return_condition"],
        "status": l["status"],
        "late_fee_cents": l["late_fee_cents"],
        "created_at": iso_ts(l["created_at"]),
        "updated_at": iso_ts(l["updated_at"]),
        "version": l["version"],
    }
