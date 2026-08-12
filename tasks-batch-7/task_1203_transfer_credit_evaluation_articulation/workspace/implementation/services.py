"""Business logic: serializers, credit math, selector, cascades, waterfall,
degree progress. All credit arithmetic uses Decimal."""
from datetime import timedelta
from decimal import Decimal

import db
from db import touch
from util import (GRADE_SCALE, MAX_TRANSFER_CREDITS, PROVISIONAL_FACTOR,
                  RESIDENCY_MIN_INSTITUTIONAL_CREDITS, SLOT_NEED, SLOT_ORDER,
                  TRANSFER_MIN_GRADE_POINTS, parse_dt, rhu, to_decimal)

OPEN_LINE_STATUSES = {"PENDING", "AUTO_MATCHED", "PETITION_REQUIRED"}
EQ_TYPE_ORDER = {"DIRECT": 0, "GENED_ONLY": 1, "ELECTIVE": 2}


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def ser_partner(r):
    return {
        "id": r["id"], "name": r["name"], "institution_code": r["institution_code"],
        "credit_system": r["credit_system"], "state_code": r.get("state_code"),
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_course(r):
    return {
        "id": r["id"], "course_code": r["course_code"], "title": r["title"],
        "credit_hours": r["credit_hours"], "level": r["level"],
        "department": r["department"], "gened_tags": list(r.get("gened_tags") or []),
        "is_active": r["is_active"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_agreement(r):
    return {
        "id": r["id"], "partner_institution_id": r["partner_institution_id"],
        "program_scope": r["program_scope"],
        "effective_start": r["effective_start"], "effective_end": r["effective_end"],
        "amends_agreement_id": r.get("amends_agreement_id"),
        "status": r["status"], "activated_at": r.get("activated_at"),
        "expired_at": r.get("expired_at"),
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_equivalency(r):
    return {
        "id": r["id"], "agreement_id": r["agreement_id"],
        "internal_course_id": r["internal_course_id"],
        "external_course_code": r["external_course_code"],
        "external_title": r["external_title"],
        "external_credit_hours": r["external_credit_hours"],
        "effective_from": r["effective_from"], "effective_until": r["effective_until"],
        "equivalency_type": r["equivalency_type"], "status": r["status"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_student(r):
    return {
        "id": r["id"], "full_name": r["full_name"], "email": r["email"],
        "declared_major": r["declared_major"], "catalog_year": r["catalog_year"],
        "total_posted_transfer_credits": r["total_posted_transfer_credits"],
        "total_posted_pla_credits": r["total_posted_pla_credits"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_transcript(r):
    return {
        "id": r["id"], "student_id": r["student_id"],
        "partner_institution_id": r["partner_institution_id"],
        "term_completed": r["term_completed"], "courses": r["courses"],
        "status": r["status"], "rejection_reason": r.get("rejection_reason"),
        "verified_at": r.get("verified_at"),
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_evaluation(r):
    return {
        "id": r["id"], "student_id": r["student_id"],
        "transcript_id": r["transcript_id"], "status": r["status"],
        "provisional_credits_total": r["provisional_credits_total"],
        "awarded_credits_total": r["awarded_credits_total"],
        "applied_credits_total": r["applied_credits_total"],
        "open_line_count": r["open_line_count"],
        "evaluated_by_id": r.get("evaluated_by_id"),
        "posted_by_id": r.get("posted_by_id"),
        "posted_at": r.get("posted_at"),
        "reopen_reason": r.get("reopen_reason"),
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_line(r):
    return {
        "id": r["id"], "evaluation_id": r["evaluation_id"],
        "external_course_code": r["external_course_code"],
        "external_title": r["external_title"],
        "external_credit_hours": r["external_credit_hours"],
        "grade": r["grade"], "grade_points": r["grade_points"],
        "equivalency_id": r.get("equivalency_id"),
        "internal_course_id": r.get("internal_course_id"),
        "provisional_credits": r.get("provisional_credits"),
        "awarded_credits": r.get("awarded_credits"),
        "applied_credits": r.get("applied_credits"),
        "status": r["status"], "resolution": r.get("resolution"),
        "denial_reason": r.get("denial_reason"),
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_petition(r):
    return {
        "id": r["id"], "line_item_id": r["line_item_id"],
        "student_id": r["student_id"],
        "proposed_internal_course_id": r["proposed_internal_course_id"],
        "syllabus_ref": r["syllabus_ref"], "status": r["status"],
        "adjudicator_id": r.get("adjudicator_id"),
        "adjudication_note": r.get("adjudication_note"),
        "awarded_internal_course_id": r.get("awarded_internal_course_id"),
        "decided_at": r.get("decided_at"),
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_appeal(r):
    return {
        "id": r["id"], "petition_id": r["petition_id"],
        "student_id": r["student_id"], "grounds": r["grounds"],
        "status": r["status"], "adjudicator_id": r.get("adjudicator_id"),
        "adjudication_note": r.get("adjudication_note"),
        "decided_at": r.get("decided_at"),
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_pla(r):
    return {
        "id": r["id"], "student_id": r["student_id"],
        "source_type": r["source_type"], "credential_ref": r["credential_ref"],
        "claimed_credits": r["claimed_credits"],
        "verified_credits": r.get("verified_credits"),
        "proposed_internal_course_id": r.get("proposed_internal_course_id"),
        "status": r["status"], "rejection_reason": r.get("rejection_reason"),
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_application(r):
    return {
        "id": r["id"], "student_id": r["student_id"],
        "line_item_id": r.get("line_item_id"), "pla_id": r.get("pla_id"),
        "slot": r["slot"], "applied_credits": r["applied_credits"],
        "status": r["status"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def guide_is_stale(r):
    pinned = r.get("pinned_agreement_id")
    if not pinned:
        return False
    ag = db.agreements.get(pinned)
    if ag is None:
        return True
    if ag["status"] != "ACTIVE":
        return True
    return ag["version"] != r.get("pinned_agreement_version")


def ser_guide(r):
    return {
        "id": r["id"], "partner_institution_id": r["partner_institution_id"],
        "catalog_year": r["catalog_year"], "status": r["status"],
        "pinned_agreement_id": r.get("pinned_agreement_id"),
        "pinned_agreement_version": r.get("pinned_agreement_version"),
        "published_at": r.get("published_at"),
        "entries_snapshot": r.get("entries_snapshot"),
        "is_stale": guide_is_stale(r),
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def evaluation_of_line(line):
    return db.evaluations.get(line["evaluation_id"])


def student_of_evaluation(ev):
    return db.students.get(ev["student_id"])


def transcript_of_evaluation(ev):
    return db.transcripts.get(ev["transcript_id"])


def partner_of_transcript(tr):
    return db.partners.get(tr["partner_institution_id"])


def lines_of_evaluation(ev_id):
    return sorted([l for l in db.lines.values() if l["evaluation_id"] == ev_id],
                  key=db.sort_key)


def student_id_of_line(line):
    ev = evaluation_of_line(line)
    return ev["student_id"] if ev else None


# ---------------------------------------------------------------------------
# Credit math
# ---------------------------------------------------------------------------

def provisional_credit_award(external_hours, credit_system, course_hours):
    """Provisional variant: estimate factor, round half-up to 1dp BEFORE cap."""
    ext = to_decimal(external_hours) if not isinstance(external_hours, Decimal) else external_hours
    cap = to_decimal(course_hours) if not isinstance(course_hours, Decimal) else course_hours
    raw = ext * PROVISIONAL_FACTOR[credit_system]
    rounded = rhu(raw, 1)
    return min(rounded, cap)


def final_credit_award(external_hours, credit_system, course_hours):
    """Final variant: exact factor, round-half-up(raw*2)/2, then cap.

    For QUARTER the exact factor is 2/3, so raw*2 == ext*4/3 (single division,
    no truncated intermediate factor)."""
    ext = to_decimal(external_hours) if not isinstance(external_hours, Decimal) else external_hours
    cap = to_decimal(course_hours) if not isinstance(course_hours, Decimal) else course_hours
    if credit_system == "QUARTER":
        doubled = (ext * 4) / 3
    else:
        doubled = ext * 2
    half_stepped = rhu(doubled, 0) / 2
    return min(half_stepped, cap)


def natural_slot_for_course(course, declared_major):
    if course is None:
        return "FREE_ELECTIVE"
    if course["department"] == declared_major:
        return "MAJOR_CORE"
    tags = course.get("gened_tags") or []
    if tags:
        return tags[0]
    return "FREE_ELECTIVE"


def natural_slot_of_line(line, student):
    course = db.courses.get(line.get("internal_course_id") or "")
    return natural_slot_for_course(course, student["declared_major"])


# ---------------------------------------------------------------------------
# Evaluation totals
# ---------------------------------------------------------------------------

def recompute_evaluation(ev, do_touch=True):
    ev_lines = lines_of_evaluation(ev["id"])
    total = Decimal("0")
    for l in ev_lines:
        pv = l.get("provisional_credits")
        if pv is not None:
            total += pv
    ev["provisional_credits_total"] = total
    ev["open_line_count"] = sum(1 for l in ev_lines if l["status"] in OPEN_LINE_STATUSES)
    if do_touch:
        touch(ev)


# ---------------------------------------------------------------------------
# Auto-match selector
# ---------------------------------------------------------------------------

def select_equivalency(external_course_code, transcript, student):
    term = parse_dt(transcript["term_completed"])
    candidates = []
    for eq in db.equivalencies.values():
        if eq["external_course_code"] != external_course_code:
            continue
        if eq["status"] != "ACTIVE":
            continue
        ag = db.agreements.get(eq["agreement_id"])
        if ag is None or ag["status"] != "ACTIVE":
            continue
        if ag["partner_institution_id"] != transcript["partner_institution_id"]:
            continue
        if ag["program_scope"] not in ("ALL", student["declared_major"]):
            continue
        if not (parse_dt(eq["effective_from"]) <= term <= parse_dt(eq["effective_until"])):
            continue
        course = db.courses.get(eq["internal_course_id"])
        if course is None or not course["is_active"]:
            continue
        candidates.append((eq, ag))
    if not candidates:
        return None

    def rank(ea):
        eq, ag = ea
        specificity = 0 if ag["program_scope"] == student["declared_major"] else 1
        # effective_from DESC -> negate epoch seconds
        from_desc = -parse_dt(eq["effective_from"]).timestamp()
        return (specificity, from_desc, db.sort_key(eq),
                EQ_TYPE_ORDER[eq["equivalency_type"]])

    candidates.sort(key=rank)
    return candidates[0][0]


# ---------------------------------------------------------------------------
# Evaluation intake
# ---------------------------------------------------------------------------

def intake_evaluation(ev, transcript, student):
    """Create one line item per transcript course with grade conversion and
    auto-match triage. Evaluation totals are set at the end (creation, no touch)."""
    partner = partner_of_transcript(transcript)
    credit_system = partner["credit_system"] if partner else "SEMESTER"
    for entry in transcript["courses"]:
        grade = entry["grade"]
        gp = GRADE_SCALE[grade]
        line = db.create_rec(db.lines, {
            "evaluation_id": ev["id"],
            "external_course_code": entry["external_course_code"],
            "external_title": entry["title"],
            "external_credit_hours": to_decimal(entry["credit_hours"]),
            "grade": grade,
            "grade_points": gp,
            "equivalency_id": None,
            "internal_course_id": None,
            "provisional_credits": None,
            "awarded_credits": None,
            "applied_credits": None,
            "resolution": None,
            "denial_reason": None,
            "status": "PENDING",
        })
        if gp < TRANSFER_MIN_GRADE_POINTS:
            line["status"] = "DENIED"
            line["resolution"] = "AUTO_GRADE"
            line["denial_reason"] = "GRADE_BELOW_TRANSFER_THRESHOLD"
            continue
        eq = select_equivalency(entry["external_course_code"], transcript, student)
        if eq is None:
            line["status"] = "PETITION_REQUIRED"
        else:
            course = db.courses.get(eq["internal_course_id"])
            line["status"] = "AUTO_MATCHED"
            line["equivalency_id"] = eq["id"]
            line["internal_course_id"] = eq["internal_course_id"]
            line["provisional_credits"] = provisional_credit_award(
                line["external_credit_hours"], credit_system, course["credit_hours"])
    recompute_evaluation(ev, do_touch=False)


# ---------------------------------------------------------------------------
# Agreement cascades
# ---------------------------------------------------------------------------

def _cascade_agreement_left_active(agreement):
    """Links 1-3 of the suspend/expire/supersede cascade."""
    flipped_eq_ids = set()
    for eq in db.equivalencies.values():
        if eq["agreement_id"] == agreement["id"] and eq["status"] == "ACTIVE":
            eq["status"] = "INACTIVE"
            touch(eq)
            flipped_eq_ids.add(eq["id"])
    affected_evals = set()
    for line in db.lines.values():
        if line["status"] != "AUTO_MATCHED":
            continue
        if line.get("equivalency_id") not in flipped_eq_ids:
            continue
        ev = evaluation_of_line(line)
        if ev is None or ev["status"] not in ("DRAFT", "IN_REVIEW"):
            continue
        line["status"] = "PETITION_REQUIRED"
        line["equivalency_id"] = None
        line["internal_course_id"] = None
        line["provisional_credits"] = None
        touch(line)
        affected_evals.add(ev["id"])
    for ev_id in affected_evals:
        recompute_evaluation(db.evaluations[ev_id])


def activate_agreement(agreement):
    """DRAFT -> ACTIVE with supersede cascade and equivalency activation."""
    # Supersede any other ACTIVE agreement with same (partner, scope)
    for other in list(db.agreements.values()):
        if other["id"] == agreement["id"]:
            continue
        if (other["partner_institution_id"] == agreement["partner_institution_id"]
                and other["program_scope"] == agreement["program_scope"]
                and other["status"] == "ACTIVE"):
            other["status"] = "SUPERSEDED"
            touch(other)
            _cascade_agreement_left_active(other)
    agreement["status"] = "ACTIVE"
    agreement["activated_at"] = db.now_iso()
    touch(agreement)
    for eq in db.equivalencies.values():
        if eq["agreement_id"] == agreement["id"] and eq["status"] == "INACTIVE":
            eq["status"] = "ACTIVE"
            touch(eq)


def suspend_agreement(agreement):
    agreement["status"] = "SUSPENDED"
    touch(agreement)
    _cascade_agreement_left_active(agreement)


def reactivate_agreement(agreement):
    agreement["status"] = "ACTIVE"
    touch(agreement)
    for eq in db.equivalencies.values():
        if eq["agreement_id"] == agreement["id"] and eq["status"] == "INACTIVE":
            eq["status"] = "ACTIVE"
            touch(eq)


def expire_agreements():
    """Synchronous expiry evaluation driven by the logical clock."""
    now = db.now()
    for ag in list(db.agreements.values()):
        if ag["status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        if now >= parse_dt(ag["effective_end"]):
            was_active = ag["status"] == "ACTIVE"
            ag["status"] = "EXPIRED"
            ag["expired_at"] = db.now_iso()
            touch(ag)
            if was_active:
                _cascade_agreement_left_active(ag)


# ---------------------------------------------------------------------------
# Posting waterfall / reopen compensation
# ---------------------------------------------------------------------------

def _slot_priority(slot):
    if slot == "MAJOR_CORE":
        return (1, "")
    if slot == "MAJOR_ELECTIVE":
        return (2, "")
    if slot == "FREE_ELECTIVE":
        return (4, "")
    return (3, slot)  # GENED_* ordered by slot enum name


def run_post_waterfall(ev, student, poster_id):
    adopted = [l for l in lines_of_evaluation(ev["id"]) if l["status"] == "ADOPTED"]
    adopted.sort(key=lambda l: (_slot_priority(natural_slot_of_line(l, student)),
                                db.sort_key(l)))
    slot_filled = {s: Decimal("0") for s in SLOT_NEED}
    global_remaining = MAX_TRANSFER_CREDITS

    for line in adopted:
        awarded = line["awarded_credits"]
        ns = natural_slot_of_line(line, student)
        natural_remaining = SLOT_NEED[ns] - slot_filled[ns]
        place = min(awarded, natural_remaining, global_remaining)
        if place < 0:
            place = Decimal("0")
        slot_filled[ns] += place
        global_remaining -= place

        line_rows = []
        # Every processed line yields a natural-slot row, even when zero.
        row = db.create_rec(db.applications, {
            "student_id": student["id"], "line_item_id": line["id"],
            "pla_id": None, "slot": ns, "applied_credits": place,
            "status": "APPLIED",
        })
        line_rows.append(row)

        leftover = awarded - place
        spill = Decimal("0")
        if leftover > 0 and ns != "FREE_ELECTIVE":
            fe_remaining = SLOT_NEED["FREE_ELECTIVE"] - slot_filled["FREE_ELECTIVE"]
            spill = min(leftover, fe_remaining, global_remaining)
            if spill < 0:
                spill = Decimal("0")
            slot_filled["FREE_ELECTIVE"] += spill
            global_remaining -= spill
            if spill > 0:
                row2 = db.create_rec(db.applications, {
                    "student_id": student["id"], "line_item_id": line["id"],
                    "pla_id": None, "slot": "FREE_ELECTIVE",
                    "applied_credits": spill, "status": "APPLIED",
                })
                line_rows.append(row2)

        applied = place + spill
        line["applied_credits"] = applied
        if applied == awarded:
            app_status = "APPLIED"
        elif applied > 0:
            app_status = "PARTIAL"
        else:
            app_status = "UNAPPLIED"
        for r in line_rows:
            r["status"] = app_status
        line["status"] = "POSTED"
        touch(line)

    total_applied = sum(
        (l["applied_credits"] for l in adopted), Decimal("0"))
    student["total_posted_transfer_credits"] = (
        student["total_posted_transfer_credits"] + total_applied)
    touch(student)

    ev["applied_credits_total"] = total_applied
    ev["posted_by_id"] = poster_id
    ev["posted_at"] = db.now_iso()
    ev["status"] = "POSTED"
    touch(ev)


def reopen_evaluation(ev, reason):
    """POSTED -> IN_REVIEW with full compensation."""
    student = student_of_evaluation(ev)
    previously_applied = ev["applied_credits_total"]
    line_ids = set()
    for line in lines_of_evaluation(ev["id"]):
        line_ids.add(line["id"])
        if line["status"] == "POSTED":
            line["status"] = "ADOPTED"
            line["applied_credits"] = None
            touch(line)
    for app_id, app in list(db.applications.items()):
        if app.get("line_item_id") in line_ids:
            del db.applications[app_id]
    if student is not None:
        student["total_posted_transfer_credits"] = (
            student["total_posted_transfer_credits"] - previously_applied)
        touch(student)
    ev["applied_credits_total"] = Decimal("0")
    ev["posted_by_id"] = None
    ev["posted_at"] = None
    ev["reopen_reason"] = reason
    ev["status"] = "IN_REVIEW"
    touch(ev)


# ---------------------------------------------------------------------------
# Petition / appeal cascades
# ---------------------------------------------------------------------------

def _partner_credit_system_for_line(line):
    ev = evaluation_of_line(line)
    tr = transcript_of_evaluation(ev) if ev else None
    partner = partner_of_transcript(tr) if tr else None
    return partner["credit_system"] if partner else "SEMESTER"


def adopt_line_via_petition(line, course_id):
    course = db.courses[course_id]
    line["status"] = "ADOPTED"
    line["resolution"] = "PETITION"
    line["internal_course_id"] = course_id
    line["awarded_credits"] = final_credit_award(
        line["external_credit_hours"],
        _partner_credit_system_for_line(line),
        course["credit_hours"])
    touch(line)
    ev = evaluation_of_line(line)
    if ev is not None:
        recompute_evaluation(ev)


def adjudicate_petition_approved(petition, awarded_course_id):
    petition["status"] = "APPROVED"
    petition["decided_at"] = db.now_iso()
    if awarded_course_id is not None:
        petition["awarded_internal_course_id"] = awarded_course_id
    touch(petition)
    line = db.lines.get(petition["line_item_id"])
    course_id = awarded_course_id or petition["proposed_internal_course_id"]
    if line is not None:
        adopt_line_via_petition(line, course_id)


def adjudicate_appeal(appeal, decision, note):
    appeal["status"] = decision
    appeal["adjudication_note"] = note
    appeal["decided_at"] = db.now_iso()
    touch(appeal)
    if decision != "OVERTURNED":
        return
    # Cascade link 1: petition DENIED -> APPROVED
    petition = db.petitions.get(appeal["petition_id"])
    if petition is None:
        return
    petition["status"] = "APPROVED"
    touch(petition)
    # Cascade link 2: line -> ADOPTED with final award recompute
    line = db.lines.get(petition["line_item_id"])
    if line is None:
        return
    ev = evaluation_of_line(line)
    course_id = petition.get("awarded_internal_course_id") or petition["proposed_internal_course_id"]
    adopt_line_via_petition(line, course_id)
    # Cascade link 3: force reopen when the evaluation had posted
    if ev is not None and ev["status"] == "POSTED":
        reopen_evaluation(ev, "APPEAL_OVERTURN")


# ---------------------------------------------------------------------------
# Degree progress
# ---------------------------------------------------------------------------

def compute_transfer_gpa(student_id):
    qp_sum = Decimal("0")
    credit_sum = Decimal("0")
    for ev in db.evaluations.values():
        if ev["student_id"] != student_id:
            continue
        for line in lines_of_evaluation(ev["id"]):
            if line["status"] != "POSTED":
                continue
            awarded = line["awarded_credits"]
            if awarded is None:
                continue
            qp_sum += rhu(line["grade_points"] * awarded, 2)
            credit_sum += awarded
    if credit_sum == 0:
        return None
    return rhu(qp_sum / credit_sum, 3)


def compute_degree_progress(student, variant):
    applied = {s: Decimal("0") for s in SLOT_NEED}
    sid = student["id"]
    for app in db.applications.values():
        if app["student_id"] != sid:
            continue
        # CERTIFIED sources: POSTED line or CREDITED pla
        if app.get("line_item_id"):
            line = db.lines.get(app["line_item_id"])
            if line is None or line["status"] != "POSTED":
                continue
        elif app.get("pla_id"):
            pla = db.plas.get(app["pla_id"])
            if pla is None or pla["status"] != "CREDITED":
                continue
        else:
            continue
        applied[app["slot"]] = applied.get(app["slot"], Decimal("0")) + app["applied_credits"]

    if variant == "PROVISIONAL":
        for ev in db.evaluations.values():
            if ev["student_id"] != sid:
                continue
            for line in lines_of_evaluation(ev["id"]):
                if line["status"] != "ADOPTED" or line["awarded_credits"] is None:
                    continue
                slot = natural_slot_of_line(line, student)
                applied[slot] = applied.get(slot, Decimal("0")) + line["awarded_credits"]
        for pla in db.plas.values():
            if pla["student_id"] != sid or pla["status"] != "VERIFIED":
                continue
            course = db.courses.get(pla.get("proposed_internal_course_id") or "")
            slot = natural_slot_for_course(course, student["declared_major"])
            applied[slot] = applied.get(slot, Decimal("0")) + pla["verified_credits"]

    slots = []
    total_applied = Decimal("0")
    for slot in SLOT_ORDER:
        req = SLOT_NEED[slot]
        app_val = applied.get(slot, Decimal("0"))
        total_applied += app_val
        slots.append({
            "slot": slot,
            "required_credits": req,
            "applied_credits": app_val,
            "remaining_credits": req - app_val,
        })
    return {
        "variant": variant,
        "total_applied_credits": total_applied,
        "residency_min_institutional_credits": RESIDENCY_MIN_INSTITUTIONAL_CREDITS,
        "transfer_gpa": compute_transfer_gpa(sid),
        "slots": slots,
    }
