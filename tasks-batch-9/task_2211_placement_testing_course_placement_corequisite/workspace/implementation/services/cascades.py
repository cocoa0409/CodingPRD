"""Multi-hop cascades (PRD 3.1, 3.3, 3.6, 3.7, 3.8, 3.9)."""

from db import base_row, db, sort_rows, touch
from services import calc

LIVE_REGISTRATION_STATES = ("PENDING", "ENROLLED", "WAITLISTED")


def new_ctx():
    return {"sections": []}


def mark_section(ctx, section_id):
    if section_id is not None and section_id not in ctx["sections"]:
        ctx["sections"].append(section_id)


def settle(ctx, promote=True):
    """Run waitlist promotions on every section that released a seat, then bump
    each touched section's version exactly once."""
    if promote:
        index = 0
        while index < len(ctx["sections"]):
            section_id = ctx["sections"][index]
            index += 1
            promote_waitlist(db.sections.get(section_id), ctx)
    for section_id in ctx["sections"]:
        section = db.sections.get(section_id)
        if section is not None:
            touch(section)


# ------------------------------------------------------------- registrations

def enroll_registration(reg, section, ctx):
    """Shared PENDING/WAITLISTED -> ENROLLED side effects (PRD 3.9)."""
    units = calc.term_unit_load(reg, section)
    reg["state"] = "ENROLLED"
    reg["term_units_at_confirm"] = units
    touch(reg)
    mark_section(ctx, section["id"])

    override = db.overrides.get(reg["override_id"]) if reg["override_id"] else None
    if override is not None and override["state"] == "ISSUED":
        override["state"] = "CONSUMED"
        override["consumed_by_registration_id"] = reg["id"]
        touch(override)

    if (
        section["pairing_state"] == "PAIRED"
        and section["role_in_pair"] == "PRIMARY"
        and reg["coreq_registration_id"] is None
        and section["linked_section_id"]
    ):
        linked = db.sections.get(section["linked_section_id"])
        if linked is not None:
            companion = base_row()
            companion.update({
                "student_id": reg["student_id"],
                "section_id": linked["id"],
                "coreq_registration_id": reg["id"],
                "override_id": None,
                "prerequisite_status": "SATISFIED",
                "term_units_at_confirm": units,
                "final_grade": None,
                "graded_at": None,
                "denial_reason": None,
                "state": "ENROLLED",
            })
            companion["prerequisite_status"] = calc.prerequisite_status(
                companion["student_id"], linked["course_id"], None
            )
            db.registrations[companion["id"]] = companion
            reg["coreq_registration_id"] = companion["id"]
            mark_section(ctx, linked["id"])


def promote_waitlist(section, ctx):
    if section is None:
        return
    while section["status"] == "OPEN":
        if calc.available_seats(section) < 1:
            break
        waiting = sort_rows([
            r for r in db.registrations.values()
            if r["section_id"] == section["id"] and r["state"] == "WAITLISTED"
        ])
        if not waiting:
            break
        enroll_registration(waiting[0], section, ctx)


def deny_registration(reg, reason, ctx, denied_ids):
    reg["state"] = "DENIED"
    reg["denial_reason"] = reason
    touch(reg)
    denied_ids.append(reg["id"])
    mark_section(ctx, reg["section_id"])


def deny_counterparts_and_release_overrides(denied_ids, reason, ctx):
    """HOP 4 of the dispute / supersession / cancellation chains."""
    for reg_id in list(denied_ids):
        reg = db.registrations.get(reg_id)
        if reg is None:
            continue
        counterpart_id = reg["coreq_registration_id"]
        if not counterpart_id:
            continue
        counterpart = db.registrations.get(counterpart_id)
        if counterpart is None:
            continue
        if counterpart["state"] in LIVE_REGISTRATION_STATES:
            deny_registration(counterpart, reason, ctx, denied_ids)
    for override in sort_rows(list(db.overrides.values())):
        if override["state"] == "CONSUMED" and override["consumed_by_registration_id"] in denied_ids:
            override["state"] = "ISSUED"
            override["consumed_by_registration_id"] = None
            touch(override)


# ------------------------------------------------- determination -> DISPUTED

def dispute_registration_cascade(determination, ctx):
    """PRD 3.6: landing on DISPUTED denies live registrations of the placed and
    corequisite courses, releases their overrides, and promotes waitlists."""
    courses = set(
        c for c in (determination["placed_course_id"], determination["coreq_course_id"]) if c
    )
    if not courses:
        return
    denied = []
    for reg in sort_rows(list(db.registrations.values())):
        if reg["state"] not in LIVE_REGISTRATION_STATES:
            continue
        if reg["student_id"] != determination["student_id"]:
            continue
        if calc.section_course_id(reg["section_id"]) in courses:
            deny_registration(reg, "EVIDENCE_DISPUTED", ctx, denied)
    deny_counterparts_and_release_overrides(denied, "EVIDENCE_DISPUTED", ctx)


# ---------------------------------------------------------------- attempts

def void_attempt(attempt, reason):
    """The five-hop void chain (PRD 3.3 / 3.6)."""
    ctx = new_ctx()
    attempt["state"] = "VOIDED"
    attempt["void_reason"] = reason
    attempt["next_eligible_at"] = None
    touch(attempt)

    calc.renumber_attempts(attempt["student_id"], attempt["subject_area"])

    student = db.students.get(attempt["student_id"])
    if student is not None:
        touch(student)

    disputed = [
        d for d in sort_rows(list(db.determinations.values()))
        if d["source_attempt_id"] == attempt["id"]
        and d["placement_state"] in ("PROVISIONAL", "FINAL")
    ]
    for det in disputed:
        det["evidence_state"] = "DISPUTED"
        touch(det)
    for det in disputed:
        dispute_registration_cascade(det, ctx)
    settle(ctx)


def close_administration(admin):
    affected = set()
    for attempt in sort_rows(list(db.attempts.values())):
        if attempt["administration_id"] != admin["id"]:
            continue
        if attempt["state"] == "BOOKED":
            attempt["state"] = "NO_SHOW"
            attempt["next_eligible_at"] = None
            touch(attempt)
            affected.add((attempt["student_id"], attempt["subject_area"]))
        elif attempt["state"] == "CHECKED_IN":
            attempt["state"] = "VOIDED"
            attempt["void_reason"] = "PROCTOR_ERROR"
            attempt["next_eligible_at"] = None
            touch(attempt)
            affected.add((attempt["student_id"], attempt["subject_area"]))
    for student_id, subject in sorted(affected):
        calc.renumber_attempts(student_id, subject)
        student = db.students.get(student_id)
        if student is not None:
            touch(student)


def cancel_administration(admin):
    affected = set()
    for attempt in sort_rows(list(db.attempts.values())):
        if attempt["administration_id"] != admin["id"]:
            continue
        if attempt["state"] in ("BOOKED", "CHECKED_IN"):
            attempt["state"] = "VOIDED"
            attempt["void_reason"] = "ADMIN_CORRECTION"
            attempt["next_eligible_at"] = None
            touch(attempt)
            affected.add((attempt["student_id"], attempt["subject_area"]))
    for student_id, subject in sorted(affected):
        calc.renumber_attempts(student_id, subject)
        student = db.students.get(student_id)
        if student is not None:
            touch(student)


# ------------------------------------------------------------------- courses

def retire_requisite_edge(edge, ctx=None):
    """PRD 3.1: retiring an edge revokes its overrides and re-evaluates the
    live registrations that leaned on them."""
    edge["status"] = "RETIRED"
    touch(edge)
    revoke_overrides_for_requisites([edge["id"]], [edge["course_id"]])


def revoke_overrides_for_requisites(requisite_ids, course_ids):
    revoked = []
    for override in sort_rows(list(db.overrides.values())):
        if override["state"] == "ISSUED" and override["requisite_id"] in requisite_ids:
            override["state"] = "REVOKED"
            touch(override)
            revoked.append(override["id"])
    for reg in sort_rows(list(db.registrations.values())):
        if reg["state"] not in ("PENDING", "WAITLISTED"):
            continue
        if calc.section_course_id(reg["section_id"]) in course_ids:
            calc.recompute_registration_prerequisite(reg)
    return revoked


def retire_course(course):
    """PRD 3.1: ACTIVE -> RETIRED plus three further hops."""
    course["status"] = "RETIRED"
    touch(course)

    retired_requisites = []
    for edge in sort_rows(list(db.requisites.values())):
        if edge["status"] != "ACTIVE":
            continue
        if edge["course_id"] == course["id"] or edge["requisite_course_id"] == course["id"]:
            edge["status"] = "RETIRED"
            touch(edge)
            retired_requisites.append(edge)

    retired_rules = []
    for rule in sort_rows(list(db.rules.values())):
        if rule["status"] not in ("DRAFT", "ACTIVE", "SUPERSEDED"):
            continue
        if rule["target_course_id"] == course["id"] or rule["coreq_course_id"] == course["id"]:
            rule["status"] = "RETIRED"
            touch(rule)
            retired_rules.append(rule)

    retired_rule_ids = [r["id"] for r in retired_rules]
    for study in sort_rows(list(db.studies.values())):
        if study["state"] in ("DRAFT", "RUNNING", "COMPLETED") and study["candidate_rule_id"] in retired_rule_ids:
            study["state"] = "WITHDRAWN"
            study["decision_note"] = "candidate rule retired"
            touch(study)

    if retired_requisites:
        revoke_overrides_for_requisites(
            [e["id"] for e in retired_requisites],
            [e["course_id"] for e in retired_requisites],
        )


# --------------------------------------------------------------------- rules

def activate_rule(rule):
    rule["status"] = "ACTIVE"
    rule["activated_at"] = db.clock
    touch(rule)
    for other in sort_rows(list(db.rules.values())):
        if other["id"] == rule["id"]:
            continue
        if other["status"] != "ACTIVE":
            continue
        if (
            other["subject_area"] == rule["subject_area"]
            and other["measure_type"] == rule["measure_type"]
            and other["target_course_id"] == rule["target_course_id"]
        ):
            other["status"] = "SUPERSEDED"
            touch(other)


def retire_rule(rule, withdraw_studies):
    previous = rule["status"]
    rule["status"] = "RETIRED"
    touch(rule)
    if withdraw_studies and previous in ("DRAFT", "ACTIVE"):
        for study in sort_rows(list(db.studies.values())):
            if study["candidate_rule_id"] == rule["id"] and study["state"] in (
                "DRAFT", "RUNNING", "COMPLETED"
            ):
                study["state"] = "WITHDRAWN"
                study["decision_note"] = "candidate rule retired"
                touch(study)


# ------------------------------------------------------------------ sections

def cancel_section(section):
    """PRD 3.8: three hops, no waitlist promotion on the cancelled section."""
    ctx = new_ctx()
    section["status"] = "CANCELLED"

    denied = []
    for reg in sort_rows(list(db.registrations.values())):
        if reg["section_id"] != section["id"]:
            continue
        if reg["state"] in LIVE_REGISTRATION_STATES:
            deny_registration(reg, "SECTION_CANCELLED", ctx, denied)

    linked = None
    if section["pairing_state"] == "PAIRED" and section["linked_section_id"]:
        linked = db.sections.get(section["linked_section_id"])
        section["pairing_state"] = "PAIR_BROKEN"
        if linked is not None:
            linked["pairing_state"] = "PAIR_BROKEN"
            mark_section(ctx, linked["id"])

    if linked is not None and linked["role_in_pair"] == "PRIMARY" and linked["status"] == "OPEN":
        linked["status"] = "CLOSED"

    deny_counterparts_and_release_overrides(denied, "SECTION_CANCELLED", ctx)

    if section["id"] in ctx["sections"]:
        ctx["sections"].remove(section["id"])
    settle(ctx, promote=False)
    touch(section)


def drop_registration(reg):
    """PRD 3.9: three hops."""
    ctx = new_ctx()
    reg["state"] = "DROPPED"
    touch(reg)
    mark_section(ctx, reg["section_id"])

    override = db.overrides.get(reg["override_id"]) if reg["override_id"] else None
    if override is not None and override["state"] == "CONSUMED":
        override["state"] = "ISSUED"
        override["consumed_by_registration_id"] = None
        touch(override)

    counterpart_id = reg["coreq_registration_id"]
    if counterpart_id:
        counterpart = db.registrations.get(counterpart_id)
        if counterpart is not None and counterpart["state"] in LIVE_REGISTRATION_STATES:
            counterpart["state"] = "DROPPED"
            touch(counterpart)
            mark_section(ctx, counterpart["section_id"])
            counterpart_override = (
                db.overrides.get(counterpart["override_id"]) if counterpart["override_id"] else None
            )
            if counterpart_override is not None and counterpart_override["state"] == "CONSUMED":
                counterpart_override["state"] = "ISSUED"
                counterpart_override["consumed_by_registration_id"] = None
                touch(counterpart_override)

    settle(ctx)


# ------------------------------------------------------------------- appeals

def release_determination_from_appealed(det):
    if det is None or det["placement_state"] != "APPEALED":
        return
    det["placement_state"] = "FINAL" if det["evidence_state"] == "VERIFIED" else "PROVISIONAL"
    touch(det)


def grant_appeal(appeal, det, decider_user_id):
    """PRD 3.7: the second five-hop chain.  Returns the minted determination."""
    ctx = new_ctx()

    det["placement_state"] = "SUPERSEDED"

    coreq_course_id = None
    for edge in sort_rows(list(db.requisites.values())):
        if (
            edge["course_id"] == appeal["requested_course_id"]
            and edge["status"] == "ACTIVE"
            and edge["requisite_type"] == "COREQUISITE"
        ):
            coreq_course_id = edge["requisite_course_id"]
            break

    bundle = calc.appeal_override_bundle()
    minted = base_row()
    minted.update({
        "student_id": det["student_id"],
        "subject_area": det["subject_area"],
        "measure_type_used": "APPEAL_OVERRIDE",
        "applied_rule_id": None,
        "placed_course_id": appeal["requested_course_id"],
        "coreq_course_id": coreq_course_id,
        "source_attempt_id": None,
        "superseded_by_id": None,
        "base_confidence_score": bundle["base_confidence_score"],
        "staleness_penalty": bundle["staleness_penalty"],
        "confidence_score": bundle["confidence_score"],
        "validity_days": bundle["validity_days"],
        "expires_at": bundle["expires_at"],
        "determined_by_user_id": decider_user_id,
        "determined_at": bundle["determined_at"],
        "placement_state": "PROVISIONAL",
        "evidence_state": bundle["evidence_state"],
    })
    db.determinations[minted["id"]] = minted

    appeal["minted_determination_id"] = minted["id"]
    det["superseded_by_id"] = minted["id"]
    touch(det)

    old_courses = set(c for c in (det["placed_course_id"], det["coreq_course_id"]) if c)
    new_courses = set(c for c in (minted["placed_course_id"], minted["coreq_course_id"]) if c)
    dropped_courses = old_courses - new_courses

    denied = []
    if dropped_courses:
        for reg in sort_rows(list(db.registrations.values())):
            if reg["state"] not in LIVE_REGISTRATION_STATES:
                continue
            if reg["student_id"] != det["student_id"]:
                continue
            if calc.section_course_id(reg["section_id"]) in dropped_courses:
                deny_registration(reg, "PLACEMENT_SUPERSEDED", ctx, denied)
    deny_counterparts_and_release_overrides(denied, "PLACEMENT_SUPERSEDED", ctx)
    settle(ctx)

    student = db.students.get(det["student_id"])
    if student is not None:
        touch(student)

    return minted
