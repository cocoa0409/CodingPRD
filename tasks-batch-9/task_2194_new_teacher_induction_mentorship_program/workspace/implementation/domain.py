"""Shared queries, derived counters and readiness/licence derivation."""

from decimal import Decimal

import calc
from store import db, now, sorted_rows, touch

LIVE_MATCH_STATES = ("PROPOSED", "ACTIVE", "SUSPENDED")
NON_TERMINAL_PHASES = ("PRE_CONFERENCE", "OBSERVED", "POST_CONFERENCE")
ACTIVE_PACKET_STATES = ("ASSEMBLING", "SUBMITTED_TO_STATE", "ACCEPTED")


# --------------------------------------------------------------------- queries

def matches_of_mentor(mentor_id):
    return sorted_rows([m for m in db.matches.values() if m.get("mentor_id") == mentor_id])


def matches_of_novice(novice_id):
    return sorted_rows([m for m in db.matches.values() if m.get("novice_id") == novice_id])


def logs_of_match(match_id):
    return sorted_rows([l for l in db.contact_logs.values() if l.get("match_id") == match_id])


def logs_of_mentor(mentor_id):
    ids = {m["id"] for m in matches_of_mentor(mentor_id)}
    return sorted_rows([l for l in db.contact_logs.values() if l.get("match_id") in ids])


def logs_of_novice(novice_id):
    ids = {m["id"] for m in matches_of_novice(novice_id)}
    return sorted_rows([l for l in db.contact_logs.values() if l.get("match_id") in ids])


def cycles_of_match(match_id):
    rows = [c for c in db.cycles.values() if c.get("match_id") == match_id]
    return sorted(rows, key=lambda c: (c.get("cycle_index") or 0,))


def cycles_of_novice(novice_id):
    ids = {m["id"] for m in matches_of_novice(novice_id)}
    return sorted_rows([c for c in db.cycles.values() if c.get("match_id") in ids])


def attainments_of_novice(novice_id):
    rows = [a for a in db.attainments.values() if a.get("novice_id") == novice_id]
    return sorted(rows, key=lambda a: (_milestone_seq(a.get("milestone_id")),))


def _milestone_seq(milestone_id):
    milestone = db.milestones.get(milestone_id)
    return milestone.get("sequence_index") if milestone else 0


def milestones_sorted():
    return sorted(db.milestones.values(), key=lambda m: m.get("sequence_index") or 0)


def sessions_of_cohort(cohort_id):
    return sorted_rows([s for s in db.sessions.values() if s.get("cohort_id") == cohort_id])


def attendances_of_session(session_id):
    return sorted_rows([a for a in db.attendances.values()
                        if a.get("session_id") == session_id])


def attendances_of_novice(novice_id):
    return sorted_rows([a for a in db.attendances.values()
                        if a.get("novice_id") == novice_id])


def packets_of_novice(novice_id):
    return sorted_rows([p for p in db.packets.values() if p.get("novice_id") == novice_id])


def disbursements_of_mentor(mentor_id):
    return sorted_rows([x for x in db.disbursements.values()
                        if x.get("mentor_id") == mentor_id])


def novice_of_match(match):
    return db.novices.get(match.get("novice_id")) if match else None


def mentor_of_match(match):
    return db.mentors.get(match.get("mentor_id")) if match else None


def site_of_match(match):
    novice = novice_of_match(match)
    return db.sites.get(novice.get("site_id")) if novice else None


def has_live_match(novice_id, exclude_id=None):
    for m in matches_of_novice(novice_id):
        if exclude_id is not None and m["id"] == exclude_id:
            continue
        if m.get("match_status") in LIVE_MATCH_STATES:
            return True
    return False


# ------------------------------------------------------------ derived counters

def recompute_site_counter(site):
    if site is None:
        return
    total = 0
    for match in db.matches.values():
        if match.get("match_status") != "ACTIVE":
            continue
        novice = novice_of_match(match)
        if novice is not None and novice.get("site_id") == site["id"]:
            total += 1
    site["active_match_count"] = total


def recompute_mentor_caseload(mentor):
    if mentor is None:
        return
    mentor["active_caseload_count"] = len(
        [m for m in matches_of_mentor(mentor["id"]) if m.get("match_status") == "ACTIVE"])


def recompute_cohort_enrolment(cohort):
    if cohort is None:
        return
    cohort["enrolled_novice_count"] = len(
        [n for n in db.novices.values()
         if n.get("cohort_id") == cohort["id"] and n.get("program_status") != "WITHDRAWN"])


def recompute_match_totals(match):
    if match is None:
        return
    minutes = 0
    cents = 0
    for log in logs_of_match(match["id"]):
        if log.get("verification_status") == "VERIFIED":
            minutes += int(log.get("credited_minutes") or 0)
            cents += int(log.get("stipend_cents") or 0)
    match["verified_minutes_total"] = minutes
    match["accrued_stipend_cents"] = cents


def day_already_credited(match_id, contact_date, exclude_log_id=None):
    total = 0
    for log in logs_of_match(match_id):
        if log["id"] == exclude_log_id:
            continue
        if log.get("verification_status") != "VERIFIED":
            continue
        if (log.get("contact_date") or "")[:10] == (contact_date or "")[:10]:
            total += int(log.get("credited_minutes") or 0)
    return total


def provisional_accrual(mentor):
    """PRD 3.8: provisional accrual over SUBMITTED and VERIFIED logs."""
    total = 0
    for match in matches_of_mentor(mentor["id"]):
        if match.get("match_status") not in ("ACTIVE", "SUSPENDED"):
            continue
        for log in logs_of_match(match["id"]):
            status = log.get("verification_status")
            if status == "VERIFIED":
                total += calc.stipend_cents(
                    log.get("credited_minutes") or 0,
                    log.get("rate_tier_at_verification") or match.get("subject_match_tier"),
                    Decimal(str(log.get("cert_multiplier_at_verification") or 1.0)),
                )
            elif status == "SUBMITTED":
                tier = match.get("subject_match_tier")
                multiplier = (Decimal("1.00")
                              if mentor.get("certification_status") == "CERTIFIED"
                              else Decimal("0.50"))
                already = day_already_credited(match["id"], log.get("contact_date"),
                                               log["id"])
                projected = calc.credited_minutes(
                    log.get("minutes") or 0, log.get("contact_type"), already)
                total += calc.stipend_cents(projected, tier, multiplier)
    return total


def recompute_mentor_totals(mentor):
    if mentor is None:
        return
    minutes = 0
    for log in logs_of_mentor(mentor["id"]):
        if log.get("verification_status") == "VERIFIED":
            minutes += int(log.get("credited_minutes") or 0)
    mentor["verified_minutes_lifetime"] = minutes
    mentor["stipend_accrued_cents"] = provisional_accrual(mentor)
    recompute_mentor_caseload(mentor)


def recompute_novice_evidence(novice):
    if novice is None:
        return
    minutes = 0
    for log in logs_of_novice(novice["id"]):
        if log.get("verification_status") == "VERIFIED":
            minutes += int(log.get("credited_minutes") or 0)
    novice["verified_contact_minutes"] = minutes
    novice["documented_observation_cycles"] = len(
        [c for c in cycles_of_novice(novice["id"]) if c.get("phase") == "DOCUMENTED"])
    credited = 0
    for row in attendances_of_novice(novice["id"]):
        session = db.sessions.get(row.get("session_id"))
        if row.get("credited") and session is not None and session.get("status") == "HELD":
            credited += 1
    novice["credited_seminar_sessions"] = credited
    novice["attained_milestone_count"] = len(
        [a for a in attainments_of_novice(novice["id"]) if a.get("status") == "ATTAINED"])


# ------------------------------------------------------------------- readiness

def readiness_inputs(novice):
    cohort_id = novice.get("cohort_id")
    held = [s for s in sessions_of_cohort(cohort_id) if s.get("status") == "HELD"]
    held_ids = {s["id"] for s in held}
    excused = 0
    for row in attendances_of_novice(novice["id"]):
        if row.get("session_id") in held_ids and row.get("attendance_status") == "EXCUSED":
            excused += 1
    return len(held), excused


def readiness_live(novice):
    held, excused = readiness_inputs(novice)
    return calc.readiness_components(
        novice.get("verified_contact_minutes") or 0,
        novice.get("documented_observation_cycles") or 0,
        novice.get("credited_seminar_sessions") or 0,
        held, excused,
    )


def snapshot_source(novice):
    rows = [a for a in db.attainments.values()
            if a.get("novice_id") == novice["id"] and a.get("status") == "ATTAINED"]
    if not rows:
        return None
    rows.sort(key=lambda a: (_milestone_seq(a.get("milestone_id")),
                            a.get("_created"), a.get("_seq")), reverse=True)
    return rows[0]


def readiness_snapshot(novice):
    row = snapshot_source(novice)
    if row is None:
        return Decimal("0.00"), None
    result = calc.readiness_components(
        row.get("snapshot_contact_minutes") or 0,
        row.get("snapshot_observation_cycles") or 0,
        row.get("snapshot_credited_seminars") or 0,
        row.get("snapshot_held_sessions") or 0,
        row.get("snapshot_excused_sessions") or 0,
    )
    return result["index"], row["id"]


def apply_license_gate(novice, live_index):
    status = novice.get("license_advancement_status")
    if status == "NOT_ELIGIBLE" and live_index >= calc.READINESS_GATE:
        novice["license_advancement_status"] = "ELIGIBLE"
    elif status == "ELIGIBLE" and live_index < calc.READINESS_GATE:
        novice["license_advancement_status"] = "NOT_ELIGIBLE"


def refresh_novice(novice, bump=True):
    """Recompute evidence counters, readiness figures and the licence gate."""
    if novice is None:
        return
    recompute_novice_evidence(novice)
    live = readiness_live(novice)["index"]
    novice["readiness_index_live"] = float(live)
    snapshot, _ = readiness_snapshot(novice)
    novice["readiness_index_snapshot"] = float(snapshot)
    apply_license_gate(novice, live)
    if bump:
        touch(novice)


def refresh_snapshot_only(novice, bump=True):
    snapshot, _ = readiness_snapshot(novice)
    novice["readiness_index_snapshot"] = float(snapshot)
    if bump:
        touch(novice)


def mentor_certified(mentor):
    if mentor is None or mentor.get("certification_status") != "CERTIFIED":
        return False
    return True


def mentor_certified_now(mentor):
    """CERTIFIED with an expiry strictly in the future."""
    from store import parse_iso
    if not mentor_certified(mentor):
        return False
    expires = parse_iso(mentor.get("certification_expires_on"))
    return expires is not None and expires > now()
