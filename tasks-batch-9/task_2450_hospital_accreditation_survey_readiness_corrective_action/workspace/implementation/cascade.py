"""Derived state, conserved ledgers and cascading recomputation (PRD 2.9)."""

from decimal import Decimal

import calc
from store import db, rows, touch


# --------------------------------------------------------------------------
# lookups
# --------------------------------------------------------------------------
def standards_of_chapter(chapter_id):
    return [s for s in rows(db.standards) if s["chapter_id"] == chapter_id]


def active_assignments(standard_id):
    return [
        a
        for a in rows(db.owner_assignments)
        if a["standard_id"] == standard_id and a["status"] == "ACTIVE"
    ]


def is_active_owner(standard_id, user_id):
    return any(a["owner_user_id"] == user_id for a in active_assignments(standard_id))


def is_active_primary_owner(standard_id, user_id):
    return any(
        a["owner_user_id"] == user_id and a["designation"] == "PRIMARY"
        for a in active_assignments(standard_id)
    )


def observations_of_tracer(tracer_id):
    return [o for o in rows(db.observations) if o["mock_tracer_id"] == tracer_id]


def tickets_of_unit(unit_id):
    out = []
    for ticket in rows(db.tickets):
        session = db.rounding_sessions.get(ticket["rounding_session_id"])
        if session is not None and session["unit_id"] == unit_id:
            out.append(ticket)
    return out


def immediate_threat_active():
    """Rung 24: any ESCALATED ticket with severity IMMEDIATE_THREAT, hospital-wide."""
    return any(
        t["state"] == "ESCALATED" and t["severity"] == "IMMEDIATE_THREAT"
        for t in db.tickets.values()
    )


# --------------------------------------------------------------------------
# chapter readiness flag (PRD 3.1) and the PPR return cascade (PRD 3.9)
# --------------------------------------------------------------------------
def refresh_chapter_flag(chapter, exclude_ppr_id=None):
    at_risk = (
        chapter["deficient_standard_count"] >= calc.CHAPTER_AT_RISK_DEFICIENT_COUNT
        or chapter["ppr_escalation_count"] >= calc.CHAPTER_AT_RISK_PPR_COUNT
    )
    if at_risk and chapter["readiness_flag"] == "ON_TRACK":
        chapter["readiness_flag"] = "AT_RISK"
        touch(chapter)
        for ppr in rows(db.pprs):
            if ppr["chapter_id"] != chapter["id"]:
                continue
            if exclude_ppr_id is not None and ppr["id"] == exclude_ppr_id:
                # The assessment written by this very request keeps the state its
                # own workflow assigned it (PRD 3.9: a new assessment "begins at
                # SUBMITTED"; a revision ends "requires_reassessment = false").
                continue
            if ppr["state"] == "SUBMITTED":
                ppr["state"] = "RETURNED_FOR_REASSESSMENT"
                ppr["requires_reassessment"] = True
                touch(ppr)
    elif not at_risk and chapter["readiness_flag"] == "AT_RISK":
        chapter["readiness_flag"] = "ON_TRACK"
        touch(chapter)


# --------------------------------------------------------------------------
# Standard compliance_state machine
# --------------------------------------------------------------------------
def on_owner_added(standard):
    chapter = db.chapters[standard["chapter_id"]]
    before = standard["active_owner_count"]
    standard["active_owner_count"] = before + 1
    if before == 0:
        chapter["mapped_standard_count"] += 1
        touch(chapter)
        if standard["compliance_state"] == "UNMAPPED":
            standard["compliance_state"] = "MAPPED"
    touch(standard)


def on_owner_revoked(standard):
    chapter = db.chapters[standard["chapter_id"]]
    before = standard["active_owner_count"]
    standard["active_owner_count"] = max(0, before - 1)
    if before == 1:
        chapter["mapped_standard_count"] = max(0, chapter["mapped_standard_count"] - 1)
        state = standard["compliance_state"]
        if state == "MAPPED":
            standard["compliance_state"] = "UNMAPPED"
        elif state == "EVIDENCE_COMPLETE":
            standard["compliance_state"] = "UNMAPPED"
            chapter["evidence_complete_standard_count"] = max(
                0, chapter["evidence_complete_standard_count"] - 1
            )
        touch(chapter)
    touch(standard)


def on_evidence_counted(standard):
    """A newly VALIDATED evidence item joins validated_evidence_count."""
    chapter = db.chapters[standard["chapter_id"]]
    standard["validated_evidence_count"] += 1
    if (
        standard["compliance_state"] == "MAPPED"
        and standard["validated_evidence_count"] >= chapter["evidence_min_count"]
    ):
        standard["compliance_state"] = "EVIDENCE_COMPLETE"
        chapter["evidence_complete_standard_count"] += 1
        touch(chapter)
    touch(standard)


def on_evidence_uncounted(standard):
    """A VALIDATED evidence item leaves validated_evidence_count (REJECT or expiry)."""
    chapter = db.chapters[standard["chapter_id"]]
    standard["validated_evidence_count"] = max(0, standard["validated_evidence_count"] - 1)
    if (
        standard["compliance_state"] == "EVIDENCE_COMPLETE"
        and standard["validated_evidence_count"] < chapter["evidence_min_count"]
    ):
        standard["compliance_state"] = "MAPPED"
        chapter["evidence_complete_standard_count"] = max(
            0, chapter["evidence_complete_standard_count"] - 1
        )
        touch(chapter)
    touch(standard)


def mark_standard_deficient(standard):
    """Tracer NON_COMPLIANT observation or condition-level escalation."""
    chapter = db.chapters[standard["chapter_id"]]
    standard["last_noncompliant_observed_at"] = db.clock
    state = standard["compliance_state"]
    if state in ("MAPPED", "EVIDENCE_COMPLETE"):
        if state == "EVIDENCE_COMPLETE":
            chapter["evidence_complete_standard_count"] = max(
                0, chapter["evidence_complete_standard_count"] - 1
            )
        standard["compliance_state"] = "DEFICIENT"
        chapter["deficient_standard_count"] += 1
        touch(chapter)
        touch(standard)
        refresh_chapter_flag(chapter)
    else:
        touch(standard)


def release_standard_from_deficient(standard):
    """Ticket VERIFY: the standard leaves DEFICIENT once no non-VERIFIED ticket
    references it any more (PRD 3.5)."""
    if standard["compliance_state"] != "DEFICIENT":
        return
    for ticket in db.tickets.values():
        if ticket["standard_id"] == standard["id"] and ticket["state"] in calc.TICKET_OPEN_STATES:
            return
    chapter = db.chapters[standard["chapter_id"]]
    chapter["deficient_standard_count"] = max(0, chapter["deficient_standard_count"] - 1)
    if standard["validated_evidence_count"] >= chapter["evidence_min_count"]:
        standard["compliance_state"] = "EVIDENCE_COMPLETE"
        chapter["evidence_complete_standard_count"] += 1
    else:
        standard["compliance_state"] = "MAPPED"
    touch(chapter)
    touch(standard)
    refresh_chapter_flag(chapter)


# --------------------------------------------------------------------------
# Unit readiness score (PRD 3.3)
# --------------------------------------------------------------------------
def _penalised_tickets(unit, mode):
    selected = []
    for ticket in tickets_of_unit(unit["id"]):
        if ticket["state"] not in calc.TICKET_OPEN_STATES:
            continue
        if mode == "PROJECTED":
            if ticket["state"] in ("IN_PROGRESS", "REMEDIATED") and ticket["due_at"] >= db.clock:
                continue
        selected.append(ticket)
    return selected


def compute_readiness(unit, mode="ATTESTED"):
    """The five pinned steps of unit_readiness_score."""
    breakdown = []
    participating = []
    for chapter in rows(db.chapters):
        tracers = [
            t
            for t in rows(db.tracers)
            if t["unit_id"] == unit["id"]
            and t["chapter_id"] == chapter["id"]
            and t["state"] == "COMPLETED"
            and t["contributes_to_readiness"]
        ]
        if tracers:
            participating.append((chapter, tracers))

    if not participating:
        # Step 1 stop: an unassessed unit is not punished for open deficiencies.
        return {
            "unit_id": unit["id"],
            "mode": mode,
            "base_score": Decimal("0.00"),
            "penalty_points_applied": 0,
            "participating_weight_pct": Decimal("0.00"),
            "readiness_score": Decimal("0.00"),
            "readiness_band": "NOT_ASSESSED",
            "chapter_breakdown": [],
        }

    participating_weight = sum((c["weight_pct"] for c, _ in participating), Decimal("0"))

    rates = []
    for chapter, tracers in participating:
        tracer_ids = {t["id"] for t in tracers}
        scored = Decimal("0")
        earned = Decimal("0")
        for obs in rows(db.observations):
            if obs["mock_tracer_id"] not in tracer_ids:
                continue
            if obs["result"] == "NOT_APPLICABLE":
                continue
            scored += obs["weight"]
            earned += obs["weight"] * calc.CREDIT[obs["result"]]
        rate = calc.q4(earned / scored) if scored > 0 else Decimal("0.0000")
        rates.append((chapter, rate))

    base = Decimal("0.00")
    for chapter, rate in rates:
        contribution = calc.q2(
            (chapter["weight_pct"] / participating_weight) * rate * Decimal("100")
        )
        base += contribution
        breakdown.append(
            {
                "chapter_id": chapter["id"],
                "chapter_code": chapter["code"],
                "weight_pct": calc.q2(chapter["weight_pct"]),
                "rate": rate,
                "compliance_rate": rate,
                "contribution": contribution,
            }
        )
    base = calc.q2(base)

    penalty = sum(t["penalty_points"] for t in _penalised_tickets(unit, mode))
    penalty_applied = min(penalty, calc.PENALTY_CAP)

    score = calc.q2(max(Decimal("0.00"), base - Decimal(penalty_applied)))
    return {
        "unit_id": unit["id"],
        "mode": mode,
        "base_score": base,
        "penalty_points_applied": penalty_applied,
        "participating_weight_pct": calc.q2(participating_weight),
        "readiness_score": score,
        "readiness_band": calc.readiness_band(score),
        "chapter_breakdown": breakdown,
    }


def recompute_unit_readiness(unit):
    """Persist the ATTESTED variant onto the unit."""
    result = compute_readiness(unit, "ATTESTED")
    if (
        unit["readiness_score"] != result["readiness_score"]
        or unit["readiness_band"] != result["readiness_band"]
    ):
        unit["readiness_score"] = result["readiness_score"]
        unit["readiness_band"] = result["readiness_band"]
        touch(unit)


# --------------------------------------------------------------------------
# Unit posture (PRD 3.3)
# --------------------------------------------------------------------------
def abort_scheduled_tracers(unit, reason):
    for tracer in rows(db.tracers):
        if tracer["unit_id"] == unit["id"] and tracer["state"] == "SCHEDULED":
            tracer["state"] = "ABORTED"
            tracer["abort_reason"] = reason
            touch(tracer)
            unit["scheduled_tracer_count"] = max(0, unit["scheduled_tracer_count"] - 1)
            touch(unit)


def refresh_unit_posture(unit):
    """Reacts to a change of open_deficiency_penalty_points, then recomputes
    readiness."""
    posture = unit["posture"]
    if posture == "OPEN" and unit["open_deficiency_penalty_points"] >= calc.POSTURE_RESTRICT_POINTS:
        unit["posture"] = "RESTRICTED"
        touch(unit)
        abort_scheduled_tracers(unit, "UNIT_POSTURE_RESTRICTED")
    elif (
        posture == "RESTRICTED"
        and unit["open_deficiency_penalty_points"] < calc.POSTURE_RESTRICT_POINTS
    ):
        unit["posture"] = "OPEN"
        touch(unit)
    recompute_unit_readiness(unit)


def lock_units_for_survey():
    for unit in rows(db.units):
        if unit["posture"] in ("OPEN", "RESTRICTED"):
            unit["posture"] = "LOCKED_FOR_SURVEY"
            touch(unit)
            abort_scheduled_tracers(unit, "SURVEY_ACTIVE")
            recompute_unit_readiness(unit)


def release_units_after_survey():
    for unit in rows(db.units):
        if unit["posture"] == "LOCKED_FOR_SURVEY":
            if unit["open_deficiency_penalty_points"] >= calc.POSTURE_RESTRICT_POINTS:
                unit["posture"] = "RESTRICTED"
            else:
                unit["posture"] = "OPEN"
            touch(unit)
            recompute_unit_readiness(unit)


# --------------------------------------------------------------------------
# Periodic performance review scoring (PRD 3.9)
# --------------------------------------------------------------------------
def compute_ppr_scores(chapter, self_ratings):
    denominator = chapter["standard_count"]
    if denominator <= 0:
        zero = Decimal("0.00")
        return zero, zero, zero
    denom = Decimal(denominator)
    self_points = sum(calc.RATING_POINTS[r["rating"]] for r in self_ratings)
    self_score = calc.q2(Decimal(self_points) / denom)
    verified_points = sum(
        calc.STATE_POINTS[s["compliance_state"]] for s in standards_of_chapter(chapter["id"])
    )
    verified_score = calc.q2(Decimal(verified_points) / denom)
    gap = calc.q2(self_score - verified_score)
    return self_score, verified_score, gap
