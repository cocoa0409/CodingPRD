"""Deterministic, synchronous cascades with the orderings declared in PRD 2.8."""

import calc
import domain
from store import db, iso, new_row, now, parse_iso, sorted_rows, touch


def create_attainment(novice, milestone, evidence_note=None):
    """Open an attainment row; LOCKED unless its prerequisite is already met."""
    prerequisite_id = milestone.get("prerequisite_milestone_id")
    status = "IN_PROGRESS"
    if prerequisite_id:
        parent = None
        for row in db.attainments.values():
            if (row.get("novice_id") == novice["id"]
                    and row.get("milestone_id") == prerequisite_id):
                parent = row
                break
        if parent is None or parent.get("status") != "ATTAINED":
            status = "LOCKED"
    row = new_row({
        "novice_id": novice["id"],
        "milestone_id": milestone["id"],
        "status": status,
        "evidence_note": evidence_note,
        "attained_on": None,
        "attested_by_user_id": None,
        "revoked_on": None,
        "revoke_reason": None,
        "revocation_count": 0,
        "snapshot_contact_minutes": None,
        "snapshot_observation_cycles": None,
        "snapshot_credited_seminars": None,
        "snapshot_held_sessions": None,
        "snapshot_excused_sessions": None,
    })
    db.attainments[row["id"]] = row
    return row


# --------------------------------------------------------- observation cycles

def abandon_cycles(match):
    """Abandon every non-terminal cycle of a match, cycle_index ascending."""
    for cycle in domain.cycles_of_match(match["id"]):
        if cycle.get("phase") not in domain.NON_TERMINAL_PHASES:
            continue
        cycle["phase"] = "ABANDONED"
        cycle["abandoned_at"] = iso(now())
        if cycle.get("feedback_review_status") in ("DRAFT", "SUBMITTED"):
            cycle["feedback_review_status"] = "RETURNED"
            cycle["return_reason"] = "CYCLE_ABANDONED"
            cycle["return_count"] = int(cycle.get("return_count") or 0) + 1
        touch(cycle)


# ----------------------------------------------------------------- match moves

def suspend_match(match):
    match["match_status"] = "SUSPENDED"
    match["suspended_at"] = iso(now())
    abandon_cycles(match)
    mentor = domain.mentor_of_match(match)
    site = domain.site_of_match(match)
    domain.recompute_mentor_caseload(mentor)
    domain.recompute_site_counter(site)
    touch(match)
    touch(mentor)
    touch(site)


def end_match(match, end_reason, status="ENDED"):
    was_active = match.get("match_status") == "ACTIVE"
    match["match_status"] = status
    match["ended_at"] = iso(now())
    match["end_reason"] = end_reason
    abandon_cycles(match)
    mentor = domain.mentor_of_match(match)
    site = domain.site_of_match(match)
    if was_active:
        domain.recompute_mentor_caseload(mentor)
        domain.recompute_site_counter(site)
        touch(mentor)
        touch(site)
    touch(match)
    return was_active


def can_reactivate(match):
    site = domain.site_of_match(match)
    novice = domain.novice_of_match(match)
    mentor = domain.mentor_of_match(match)
    if site is None or novice is None or mentor is None:
        return False
    if site.get("status") != "OPEN":
        return False
    if novice.get("program_status") not in ("MATCHED", "ACTIVE"):
        return False
    if int(mentor.get("active_caseload_count") or 0) >= int(mentor.get("caseload_cap") or 0):
        return False
    if int(site.get("active_match_count") or 0) >= int(site.get("mentor_slot_cap") or 0):
        return False
    return True


def reactivate_matches(mentor):
    """Conditional reactivation offers, created_at ascending; failures stay put."""
    for match in domain.matches_of_mentor(mentor["id"]):
        if match.get("match_status") != "SUSPENDED":
            continue
        if not can_reactivate(match):
            continue
        match["match_status"] = "ACTIVE"
        match["suspended_at"] = None
        site = domain.site_of_match(match)
        domain.recompute_mentor_caseload(mentor)
        domain.recompute_site_counter(site)
        touch(match)
        touch(mentor)
        touch(site)


def suspend_mentor_matches(mentor):
    for match in domain.matches_of_mentor(mentor["id"]):
        if match.get("match_status") == "ACTIVE":
            suspend_match(match)


# ----------------------------------------------------------------- lapse sweep

def lapse_sweep():
    moment = now()
    for mentor in sorted_rows(list(db.mentors.values())):
        if mentor.get("certification_status") not in ("CERTIFIED", "SUSPENDED"):
            continue
        expires = parse_iso(mentor.get("certification_expires_on"))
        if expires is None or expires >= moment:
            continue
        was_certified = mentor.get("certification_status") == "CERTIFIED"
        mentor["certification_status"] = "LAPSED"
        touch(mentor)
        if was_certified:
            suspend_mentor_matches(mentor)


# ------------------------------------------------------------------ milestones

def requirements_met(novice, milestone):
    return (
        int(novice.get("verified_contact_minutes") or 0)
        >= int(milestone.get("required_contact_minutes") or 0)
        and int(novice.get("documented_observation_cycles") or 0)
        >= int(milestone.get("required_observation_cycles") or 0)
        and int(novice.get("credited_seminar_sessions") or 0)
        >= int(milestone.get("required_credited_seminars") or 0)
    )


def dependents(novice_id, milestone_id):
    rows = []
    for row in domain.attainments_of_novice(novice_id):
        milestone = db.milestones.get(row.get("milestone_id"))
        if milestone and milestone.get("prerequisite_milestone_id") == milestone_id:
            rows.append(row)
    return rows


def unlock_dependents(novice, milestone_id):
    for row in dependents(novice["id"], milestone_id):
        if row.get("status") == "LOCKED":
            row["status"] = "IN_PROGRESS"
            touch(row)


def relock_dependents(novice, milestone_id):
    for row in dependents(novice["id"], milestone_id):
        if row.get("status") == "IN_PROGRESS":
            row["status"] = "LOCKED"
            touch(row)


def return_submitted_packets(novice, reason):
    """Void/revocation hop four: state-side packets come back."""
    for packet in domain.packets_of_novice(novice["id"]):
        if packet.get("packet_status") != "SUBMITTED_TO_STATE":
            continue
        packet["packet_status"] = "RETURNED"
        packet["return_reason"] = reason
        packet["decided_at"] = None
        packet["decided_by_user_id"] = None
        touch(packet)
        if novice.get("program_status") == "COMPLETION_PENDING":
            novice["program_status"] = "ACTIVE"
            touch(novice)


def drop_recommendation(novice):
    if novice.get("license_advancement_status") == "RECOMMENDED":
        novice["license_advancement_status"] = "NOT_ELIGIBLE"
        novice["license_stage"] = "PRELIMINARY"
        touch(novice)
        return True
    return False


def revoke_unsupported_attainments(novice):
    """Void hop two and three: revoke rows whose evidence no longer holds."""
    gating_revoked = False
    for row in domain.attainments_of_novice(novice["id"]):
        if row.get("status") != "ATTAINED":
            continue
        milestone = db.milestones.get(row.get("milestone_id"))
        if milestone is None or requirements_met(novice, milestone):
            continue
        row["status"] = "REVOKED"
        row["revoked_on"] = iso(now())
        row["revoke_reason"] = "EVIDENCE_WITHDRAWN"
        row["revocation_count"] = int(row.get("revocation_count") or 0) + 1
        touch(row)
        # A revocation "decrements attained_milestone_count", on the cascaded
        # hop-two path exactly as on the explicit one.
        novice["attained_milestone_count"] = max(
            0, int(novice.get("attained_milestone_count") or 0) - 1)
        relock_dependents(novice, milestone["id"])
        if milestone.get("gates_license_recommendation"):
            gating_revoked = True
    if gating_revoked:
        dropped = drop_recommendation(novice)
        if dropped:
            return_submitted_packets(novice, "EVIDENCE_REVOKED")
    return gating_revoked


# --------------------------------------------------------------------- packets

def rescore_packet(packet, novice, persist=True):
    live = domain.readiness_live(novice)["index"]
    attained = len([a for a in domain.attainments_of_novice(novice["id"])
                    if a.get("status") == "ATTAINED"])
    base, bonus, completion = calc.completion_scores(
        live, attained, novice.get("retention_outcome"))
    if persist:
        packet["evidence_milestone_count"] = attained
        packet["base_score"] = float(base)
        packet["retention_bonus"] = float(bonus)
        packet["completion_score"] = float(completion)
        touch(packet)
    return attained, base, bonus, completion
