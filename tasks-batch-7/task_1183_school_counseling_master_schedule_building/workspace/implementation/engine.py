"""Heavy orchestration: auto-placement at publish, credit audits, rebalance."""

import db
import domain
from util import now_iso
from validate import new_record, touch


def create_entry(student_id, section, term_id, origin, epoch_placed):
    e = new_record()
    e.update({
        "student_id": student_id,
        "section_id": section["id"],
        "term_id": term_id,
        "state": "ENROLLED",
        "origin": origin,
        "moved_to_section_id": None,
        "epoch_placed": epoch_placed,
    })
    db.schedule_entries[e["id"]] = e
    return e


def write_credit_audit(student, term):
    """Final-audit variant; idempotent within an epoch (replace same-epoch)."""
    vals = domain.credit_audit_values(student, term["id"], provisional=False)
    epoch = term["rebalance_epoch"]
    existing = None
    for a in db.credit_audits.values():
        if (a["student_id"] == student["id"] and a["term_id"] == term["id"]
                and a["audit_epoch"] == epoch):
            existing = a
            break
    if existing is not None:
        existing.update(vals)
        return existing
    a = new_record(slim=True)
    a.update({"student_id": student["id"], "term_id": term["id"],
              "audit_epoch": epoch})
    a.update(vals)
    db.credit_audits[a["id"]] = a
    return a


def _place(student, request, course, term):
    sec = domain.placement_select(student, course, term["id"])
    if sec is None:
        return None
    create_entry(student["id"], sec, term["id"], "AUTO_PLACEMENT", 0)
    request["state"] = "PLACED"
    touch(request)
    return sec


def run_auto_placement(term):
    """Walk each student's LOCKED primaries by priority_rank ASC (created_at
    tie-break), place via placement_selector, fall back to alternates."""
    locked = [r for r in db.course_requests.values()
              if r["term_id"] == term["id"] and r["state"] == "LOCKED"]
    student_ids = {r["student_id"] for r in locked}
    students = sorted((db.students[sid] for sid in student_ids if sid in db.students),
                      key=lambda s: (s["created_at"], s["_seq"]))

    for student in students:
        reqs = [r for r in locked if r["student_id"] == student["id"]]
        primaries = sorted((r for r in reqs if not r["is_alternate"]),
                           key=lambda r: (r["priority_rank"], r["created_at"], r["_seq"]))
        tried = set()
        for req in primaries:
            course = db.courses.get(req["course_id"])
            if course is not None and _place(student, req, course, term) is not None:
                continue
            # Primary failed: walk untried alternates, lowest rank first.
            placed = False
            while True:
                alts = sorted(
                    (r for r in reqs
                     if r["is_alternate"] and r["state"] == "LOCKED"
                     and r["id"] not in tried),
                    key=lambda r: (r["priority_rank"], r["created_at"], r["_seq"]))
                if not alts:
                    break
                alt = alts[0]
                tried.add(alt["id"])
                alt_course = db.courses.get(alt["course_id"])
                if alt_course is not None and _place(student, alt, alt_course, term):
                    placed = True
                    break
                alt["state"] = "UNPLACED"
                touch(alt)
            req["state"] = "UNPLACED"
            touch(req)
        # Any alternate never needed resolves to UNPLACED at publish.
        for r in reqs:
            if r["state"] == "LOCKED":
                r["state"] = "UNPLACED"
                touch(r)

    # Credit audit for every student who had at least one locked request.
    for student in students:
        write_credit_audit(student, term)


def run_rebalance(term):
    """LOCKED -> REBALANCING -> LOCKED. Returns the new RebalanceRun row."""
    new_epoch = term["rebalance_epoch"] + 1
    term["rebalance_epoch"] = new_epoch
    before = domain.term_imbalance(term)
    moves = 0
    target = term["class_size_target"]

    # Consolidation: empty under-enrolled PUBLISHED sections are cancelled.
    for sec in list(db.sections.values()):
        if (sec["term_id"] == term["id"] and sec["state"] == "PUBLISHED"
                and domain.section_enrolled_count(sec["id"]) == 0
                and domain.section_under_enrolled(sec)):
            sec["state"] = "CANCELLED"
            touch(sec)

    def donors():
        ds = [s for s in db.sections.values()
              if s["term_id"] == term["id"] and s["state"] == "PUBLISHED"
              and domain.section_enrolled_count(s["id"]) > target]
        ds.sort(key=lambda s: (-(domain.section_enrolled_count(s["id"]) - target),
                               s["created_at"], s["_seq"]))
        return ds

    def receivers(course_id):
        rs = [s for s in db.sections.values()
              if s["term_id"] == term["id"] and s["course_id"] == course_id
              and s["state"] == "PUBLISHED"
              and domain.section_enrolled_count(s["id"]) < target]
        rs.sort(key=lambda s: (domain.section_enrolled_count(s["id"]),
                               s["created_at"], s["_seq"]))
        return rs

    any_move = True
    while any_move:
        any_move = False
        for donor in donors():
            # The donor drains into its single best receiver, chosen once when
            # the drain begins; per-move guards are only the three pinned in
            # §3.8 (period conflict, cohort guard, free seat).
            recv_pool = [r for r in receivers(donor["course_id"])
                         if r["id"] != donor["id"]]
            if not recv_pool:
                continue  # no receiver: nothing in this donor can move
            best = recv_pool[0]
            while domain.section_enrolled_count(donor["id"]) > target:
                entries = domain.enrolled_entries(donor["id"])
                entries.sort(key=lambda e: (
                    0 if (db.students.get(e["student_id"]) or {}).get(
                        "special_program", "NONE") == "NONE" else 1,
                    e["epoch_placed"], e["created_at"], e["_seq"]))
                moved = False
                for entry in entries:
                    if entry["epoch_placed"] == new_epoch:
                        continue  # no student moves twice in one run
                    student = db.students.get(entry["student_id"])
                    if student is None:
                        continue
                    taken = domain.student_enrolled_periods(
                        student["id"], term["id"], exclude_entry_id=entry["id"])
                    if best.get("period") in taken:
                        continue
                    prog = student["special_program"]
                    if prog != "NONE":
                        counts = domain.section_cohort_counts(best["id"])
                        if (counts.get(prog, 0) + 1
                                > domain.cohort_half_cap(best["capacity"])):
                            continue
                    if (domain.section_enrolled_count(best["id"]) + 1
                            > best["capacity"]):
                        continue
                    entry["state"] = "MOVED"
                    entry["moved_to_section_id"] = best["id"]
                    touch(entry)
                    create_entry(student["id"], best, term["id"],
                                 "REBALANCE", new_epoch)
                    moves += 1
                    any_move = True
                    moved = True
                    break
                if not moved:
                    break  # donor ran out of movable students

    after = domain.term_imbalance(term)
    run = new_record(slim=True)
    run.update({
        "term_id": term["id"],
        "epoch": new_epoch,
        "moves_proposed": moves,
        "imbalance_score_before": before,
        "imbalance_score_after": after,
        "executed_at": now_iso(),
    })
    db.rebalance_runs[run["id"]] = run
    return run
