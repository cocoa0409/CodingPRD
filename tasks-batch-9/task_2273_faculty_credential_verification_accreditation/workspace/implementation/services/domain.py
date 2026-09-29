"""Derived-field reconciliation, state machines and the three named cascades."""

from decimal import Decimal

import clock
import db
import util
from constants import (
    DEGREE_RANK, INACTIVE_ASSIGNMENT_STATUSES, UNQUALIFIED_ASSIGNMENT_STATUSES,
)
from db import store, touch
from services import calc, lookup

ACTIVE_ASSIGNMENT_STATUSES = (
    "PENDING_VERIFICATION",
    "VERIFIED_QUALIFIED",
    "EXCEPTION_FLAGGED",
    "REMEDIATION_IN_PROGRESS",
)


# --------------------------------------------------------- dossier recompute
def recompute_dossier(faculty, bump=True):
    records = lookup.credentials_of(faculty["id"])
    live = [r for r in records if r["verification_status"] != "REJECTED"]

    codes = []
    if not live:
        codes.append("NO_CREDENTIAL_ON_FILE")

    for r in live:
        if r["verification_status"] == "REPUDIATED":
            continue
        if r["transcript_status"] != "OFFICIAL_RECEIVED":
            codes.append("TRANSCRIPT_NOT_OFFICIAL")
            break

    for r in live:
        if r["verification_status"] == "REPUDIATED":
            continue
        if not r.get("is_foreign_institution"):
            continue
        if not lookup.has_completed_equivalent_evaluation(r["id"]):
            codes.append("FOREIGN_EVALUATION_INCOMPLETE")
            break

    for r in live:
        if r["verification_status"] != "REPUDIATED":
            continue
        cured = False
        for other in live:
            if other["_seq"] <= r["_seq"]:
                continue
            if (other["degree_level"] == r["degree_level"]
                    and other["discipline_id"] == r["discipline_id"]):
                cured = True
                break
        if not cured:
            codes.append("CREDENTIAL_REPUDIATED")
            break

    deduped = []
    for code in codes:
        if code not in deduped:
            deduped.append(code)

    if not live:
        status = "INCOMPLETE"
    elif any(r["verification_status"] == "PENDING" for r in live):
        status = "UNDER_REVIEW"
    elif not deduped:
        status = "VERIFIED"
    else:
        status = "DEFICIENT"

    highest = None
    for r in records:
        if r["verification_status"] != "VERIFIED":
            continue
        level = calc.effective_level(r)
        if highest is None or DEGREE_RANK[level] > DEGREE_RANK[highest]:
            highest = level

    faculty["deficiency_codes"] = deduped
    faculty["dossier_status"] = status
    faculty["highest_verified_degree_level"] = highest

    if status == "VERIFIED" and faculty["appointment_status"] == "PROSPECT":
        faculty["appointment_status"] = "CREDENTIALED_ELIGIBLE"

    refresh_pd(faculty)
    if bump:
        touch(faculty)
    return faculty


def refresh_pd(faculty):
    result = calc.pd_compliance(faculty)
    faculty["pd_hours_current_cycle"] = result["pd_hours_current_cycle"]
    faculty["pd_compliant"] = result["pd_compliant"]
    return faculty


# ---------------------------------------------------------- roster snapshot
def recompute_roster(roster, advance_epoch=False, bump=True):
    program = store.programs[roster["program_id"]]
    included = lookup.included_assignments(roster["program_id"], roster["term_id"])

    terminal = [a for a in included
                if a["status"] == "VERIFIED_QUALIFIED"
                and a.get("qualification_basis") == "TERMINAL_DEGREE"]

    credit_total = Decimal(0)
    for a in included:
        credit_total += util.dec(calc._credit_hours(a))
    credit_terminal = Decimal(0)
    for a in terminal:
        credit_terminal += util.dec(calc._credit_hours(a))

    adequacy = calc.program_adequacy(program, roster["term_id"])

    roster["total_assignment_count"] = len(included)
    roster["distinct_faculty_count"] = len({a["faculty_member_id"] for a in included})
    roster["flagged_exception_count"] = len(
        [a for a in included
         if a["status"] in ("EXCEPTION_FLAGGED", "REMEDIATION_IN_PROGRESS")])
    roster["terminal_qualified_headcount"] = len(
        {a["faculty_member_id"] for a in terminal})
    roster["credit_hours_total"] = credit_total
    roster["credit_hours_terminal_qualified"] = credit_terminal
    roster["adequacy_ratio_snapshot"] = adequacy["adequacy_ratio"]

    blocking = []
    if any(a["status"] in UNQUALIFIED_ASSIGNMENT_STATUSES for a in included):
        blocking.append("EXCEPTIONS_OUTSTANDING")
    if adequacy["adequacy_ratio"] < util.dec(program["min_terminal_ratio"]):
        blocking.append("ADEQUACY_BELOW_MINIMUM")
    for faculty_id in {a["faculty_member_id"] for a in included}:
        member = store.faculty_members.get(faculty_id)
        if member and member["dossier_status"] in ("INCOMPLETE", "DEFICIENT"):
            blocking.append("DOSSIER_DEFICIENT")
            break

    roster["blocking_reason_codes"] = blocking
    roster["certification_readiness"] = "READY" if not blocking else "BLOCKED"

    if advance_epoch:
        roster["generation_epoch"] = roster.get("generation_epoch", 0) + 1
    if bump:
        touch(roster)
    return roster


# --------------------------------------------------------- program adequacy
def write_program_adequacy(program, term_id, bump=True):
    adequacy = calc.program_adequacy(program, term_id)
    program["adequacy_ratio"] = adequacy["adequacy_ratio"]
    program["adequacy_status"] = adequacy["adequacy_status"]
    program["adequacy_term_id"] = term_id
    program["unqualified_assignment_count"] = adequacy["unqualified_assignment_count"]
    if bump:
        touch(program)
    return program


def bump_unqualified(program, delta):
    if delta == 0 or program is None:
        return program
    current = program.get("unqualified_assignment_count", 0) + delta
    program["unqualified_assignment_count"] = max(0, current)
    touch(program)
    return program


def recompute_covering(program_id, term_id):
    """Recompute the covering GENERATED roster and rewrite its program."""
    roster = lookup.generated_roster(program_id, term_id)
    if roster is None:
        return None
    recompute_roster(roster)
    program = store.programs.get(program_id)
    if program is not None:
        write_program_adequacy(program, term_id)
    return roster


# ------------------------------------------------------- assignment verdict
def apply_decision(assignment, consider_justification=True):
    """Run the qualification determination and write the verdict in place."""
    determination = calc.qualification_determination(assignment)
    qualified = determination["qualified"]
    basis = determination["qualification_basis"]

    if not qualified and consider_justification:
        if lookup.approved_justification(assignment["id"]) is not None:
            qualified = True
            basis = "TESTED_EXPERIENCE"

    before = {
        "status": assignment["status"],
        "qualification_basis": assignment.get("qualification_basis"),
        "exception_code": assignment.get("exception_code"),
        "alignment_score": assignment.get("alignment_score"),
    }

    if qualified:
        assignment["status"] = "VERIFIED_QUALIFIED"
        assignment["qualification_basis"] = basis
        assignment["exception_code"] = None
    else:
        assignment["status"] = "EXCEPTION_FLAGGED"
        assignment["qualification_basis"] = "NONE"
        assignment["exception_code"] = determination["exception_code"]
    assignment["alignment_score"] = determination["alignment_score"]

    changed = any(assignment.get(k) != v for k, v in before.items())
    return before["status"], assignment["status"], changed


def unqualified_delta(old_status, new_status):
    was = 1 if old_status in UNQUALIFIED_ASSIGNMENT_STATUSES else 0
    now = 1 if new_status in UNQUALIFIED_ASSIGNMENT_STATUSES else 0
    return now - was


def withdraw_backing_justifications(assignment):
    for j in lookup.justifications_of_assignment(assignment["id"]):
        if j["status"] in ("SUBMITTED", "UNDER_REVIEW"):
            j["status"] = "WITHDRAWN"
            touch(j)


# ------------------------------------------------------------ ledger sync
def sync_faculty_load(faculty, bump=True):
    faculty["assigned_credit_hours"] = calc.assigned_credit_hours(faculty["id"])
    if bump:
        touch(faculty)
    return faculty


# ------------------------------------------------- cascade A: repudiation
def cascade_a(record):
    faculty = store.faculty_members[record["faculty_member_id"]]
    recompute_dossier(faculty)

    if faculty["dossier_status"] != "DEFICIENT":
        return

    affected_pairs = set()
    for assignment in lookup.assignments_of_faculty(faculty["id"]):
        if assignment["status"] not in ("PENDING_VERIFICATION", "VERIFIED_QUALIFIED"):
            continue
        section = store.course_sections.get(assignment["course_section_id"])
        if not section:
            continue
        term = store.terms.get(section["term_id"])
        if not term or term["status"] == "CLOSED":
            continue
        if lookup.certified_roster(section["program_id"], section["term_id"]):
            continue
        old_status = assignment["status"]
        assignment["status"] = "EXCEPTION_FLAGGED"
        assignment["qualification_basis"] = "NONE"
        assignment["exception_code"] = "DOSSIER_DEFICIENT"
        touch(assignment)
        program = store.programs.get(section["program_id"])
        bump_unqualified(program, unqualified_delta(old_status, "EXCEPTION_FLAGGED"))
        affected_pairs.add((section["program_id"], section["term_id"]))

    affected_programs = []
    for program_id, term_id in sorted(affected_pairs):
        if recompute_covering(program_id, term_id) is not None:
            program = store.programs.get(program_id)
            if program is not None and program not in affected_programs:
                affected_programs.append(program)

    for program in affected_programs:
        clean = (program["adequacy_status"] == "ADEQUATE"
                 and program.get("unqualified_assignment_count", 0) == 0)
        if clean:
            continue
        for review in lookup.reviews_of_program(program["id"]):
            if review["status"] != "RESPONSE_SUBMITTED":
                continue
            review["status"] = "REMEDIATION_REQUIRED"
            anchor = lookup.anchor_roster_for_program(program["id"])
            risk = calc.review_risk(program, anchor)
            review["preliminary_risk_index"] = risk["preliminary_risk_index"]
            review["risk_tier"] = risk["risk_tier"]
            review["risk_index"] = risk["risk_index"]
            review["response_due_date"] = util.date_to_str(risk["response_due_date"])
            touch(review)


# --------------------------------------------------- cascade C: separation
def cascade_c(faculty):
    affected_pairs = set()
    for assignment in lookup.assignments_of_faculty(faculty["id"]):
        if assignment["status"] not in ACTIVE_ASSIGNMENT_STATUSES:
            continue
        section = store.course_sections.get(assignment["course_section_id"])
        old_status = assignment["status"]
        assignment["status"] = "WITHDRAWN"
        assignment["remediation_action"] = None
        touch(assignment)
        if old_status == "REMEDIATION_IN_PROGRESS":
            withdraw_backing_justifications(assignment)
        if section:
            program = store.programs.get(section["program_id"])
            bump_unqualified(program, unqualified_delta(old_status, "WITHDRAWN"))
            if section.get("instructor_of_record_id") == faculty["id"]:
                section["instructor_of_record_id"] = None
                touch(section)
            affected_pairs.add((section["program_id"], section["term_id"]))

    for section in db.ordered(store.course_sections):
        if section.get("instructor_of_record_id") == faculty["id"]:
            section["instructor_of_record_id"] = None
            touch(section)

    sync_faculty_load(faculty, bump=False)

    for program_id, term_id in sorted(affected_pairs):
        recompute_covering(program_id, term_id)

    for contract in lookup.contracts_of_faculty(faculty["id"]):
        if contract["status"] in ("ISSUED", "COUNTERSIGNED"):
            contract["status"] = "VOIDED"
            touch(contract)
