"""The twelve calculation rules of PRD section 3."""

from decimal import Decimal

import clock
import db
import util
from constants import (
    ALIGNMENT_PASS_THRESHOLD, AT_RISK_BAND, BASE_FEE_CENTS, BRACKET_A_PAGES,
    BRACKET_B_PAGES, CERT_FACTOR, CROSS_BUILDING_BUFFER_MINUTES, DEGREE_RANK,
    EXPEDITE_MULTIPLIER, FEE_CAP_CENTS, FEE_FLOOR_CENTS, FOREIGN_SURCHARGE_CENTS,
    FREE_PAGES, INACTIVE_ASSIGNMENT_STATUSES, NO_MATCH_SCORE, PARENT_CHILD_SCORE,
    PD_CYCLE_DAYS, PD_HOURS_REQUIRED, PREFIX_SCORE, RATE_A_CENTS, RATE_B_CENTS,
    RATE_C_CENTS, RESPONSE_WINDOW_DAYS, RISK_TIER_LOW_MAX, RISK_TIER_MODERATE_MAX,
    RISK_WEIGHT_ADEQUACY_GAP, RISK_WEIGHT_DOSSIER, RISK_WEIGHT_REMEDIATION,
    RISK_WEIGHT_UNQUALIFIED, SAME_BUILDING_BUFFER_MINUTES, SAME_NODE_SCORE,
    SIBLING_SCORE, TESTED_EXPERIENCE_CODES_CAP, TESTED_EXPERIENCE_WEIGHT_CERT,
    TESTED_EXPERIENCE_WEIGHT_CODES, TESTED_EXPERIENCE_WEIGHT_YEARS,
    TESTED_EXPERIENCE_YEARS_CAP, TIER_MULTIPLIER, UNQUALIFIED_ASSIGNMENT_STATUSES,
)
from db import store
from services import lookup

ZERO4 = Decimal("0.0000")


# ------------------------------------------------ 1. discipline alignment
def alignment_score(source_id, target_id):
    source = store.disciplines.get(source_id) if isinstance(source_id, str) else None
    target = store.disciplines.get(target_id) if isinstance(target_id, str) else None
    if source is None or target is None:
        return ZERO4
    if source["id"] == target["id"]:
        return SAME_NODE_SCORE
    s_parent = source.get("parent_discipline_id")
    t_parent = target.get("parent_discipline_id")
    if source["id"] == t_parent or target["id"] == s_parent:
        return PARENT_CHILD_SCORE
    if s_parent is not None and s_parent == t_parent:
        return SIBLING_SCORE
    if source.get("code", "")[0:2] == target.get("code", "")[0:2]:
        return PREFIX_SCORE
    return NO_MATCH_SCORE


def aligns(source_id, target_id):
    return alignment_score(source_id, target_id) >= ALIGNMENT_PASS_THRESHOLD


# ------------------------------------- 2. assignment qualification decision
def effective_level(record):
    return record.get("effective_degree_level") or record["degree_level"]


def effective_discipline(record):
    return record.get("effective_discipline_id") or record["discipline_id"]


def qualification_determination(assignment_row):
    section = store.course_sections[assignment_row["course_section_id"]]
    program = store.programs[section["program_id"]]
    section_discipline = store.disciplines.get(section["discipline_id"])
    faculty = store.faculty_members[assignment_row["faculty_member_id"]]

    course_requirement = ("MASTERS"
                          if section["course_level"] in ("LOWER_DIVISION", "UPPER_DIVISION")
                          else "DOCTORATE")
    discipline_requirement = (section_discipline or {}).get(
        "required_terminal_degree_level", "MASTERS")
    required_rank = max(DEGREE_RANK[course_requirement], DEGREE_RANK[discipline_requirement])

    records = lookup.credentials_of(faculty["id"])
    official_set = [r for r in records
                    if r["verification_status"] == "VERIFIED"
                    and r["transcript_status"] == "OFFICIAL_RECEIVED"]
    eligible_set = []
    for r in official_set:
        if r.get("is_foreign_institution") and not lookup.has_completed_equivalent_evaluation(r["id"]):
            continue
        eligible_set.append(r)

    scores = {}
    for r in eligible_set:
        scores[r["id"]] = alignment_score(effective_discipline(r), section["discipline_id"])

    degree_hit = False
    for r in eligible_set:
        if (DEGREE_RANK[effective_level(r)] >= required_rank
                and scores[r["id"]] >= ALIGNMENT_PASS_THRESHOLD):
            degree_hit = True
            break

    coursework_hours = Decimal(0)
    for r in eligible_set:
        if scores[r["id"]] >= ALIGNMENT_PASS_THRESHOLD:
            coursework_hours += util.dec(r.get("graduate_credit_hours_in_discipline") or 0)
    min_hours = util.dec((section_discipline or {}).get("min_graduate_credit_hours") or 0)
    coursework_hit = coursework_hours >= min_hours

    if program["qualification_policy"] == "COURSEWORK_18":
        credential_pass = degree_hit or coursework_hit
        basis = "TERMINAL_DEGREE" if degree_hit else "COURSEWORK_18_HOUR"
    else:
        credential_pass = degree_hit
        basis = "TERMINAL_DEGREE"

    score = max(scores.values()) if scores else ZERO4

    qualified = credential_pass and faculty["dossier_status"] == "VERIFIED"
    exception_code = None
    if not qualified:
        if not official_set:
            exception_code = "NO_OFFICIAL_TRANSCRIPT"
        elif not eligible_set:
            exception_code = "FOREIGN_EVALUATION_MISSING"
        elif not credential_pass and score >= ALIGNMENT_PASS_THRESHOLD:
            exception_code = "DEGREE_LEVEL_INSUFFICIENT"
        elif not credential_pass:
            exception_code = "DISCIPLINE_MISALIGNED"
        else:
            exception_code = "DOSSIER_DEFICIENT"

    return {
        "qualified": qualified,
        "credential_pass": credential_pass,
        "qualification_basis": basis if qualified else "NONE",
        "exception_code": exception_code,
        "alignment_score": util.round4(score),
        "coursework_hours": coursework_hours,
        "required_rank": required_rank,
    }


# --------------------------------------------- 3. program faculty adequacy
def program_adequacy(program, term_id, basis=None):
    included = lookup.included_assignments(program["id"], term_id)
    terminal = [a for a in included
                if a["status"] == "VERIFIED_QUALIFIED"
                and a.get("qualification_basis") == "TERMINAL_DEGREE"]
    applied = basis or program["adequacy_basis"]

    if applied == "HEADCOUNT":
        denominator = len({a["faculty_member_id"] for a in included})
        numerator = len({a["faculty_member_id"] for a in terminal})
    else:
        denominator = sum(util.dec(_credit_hours(a)) for a in included) or Decimal(0)
        numerator = sum(util.dec(_credit_hours(a)) for a in terminal) or Decimal(0)

    denom = util.dec(denominator)
    numer = util.dec(numerator)
    if denom == 0:
        ratio = ZERO4
    else:
        ratio = util.round4(numer / denom)

    minimum = util.dec(program.get("min_terminal_ratio"))
    if ratio >= minimum:
        status = "ADEQUATE"
    elif ratio >= minimum - AT_RISK_BAND:
        status = "AT_RISK"
    else:
        status = "INSUFFICIENT"

    unqualified = len([a for a in included
                       if a["status"] in UNQUALIFIED_ASSIGNMENT_STATUSES])

    return {
        "basis_applied": applied,
        "numerator": numer,
        "denominator": denom,
        "adequacy_ratio": ratio,
        "adequacy_status": status,
        "unqualified_assignment_count": unqualified,
        "included": included,
    }


def _credit_hours(assignment_row):
    section = store.course_sections.get(assignment_row["course_section_id"])
    return (section or {}).get("credit_hours") or 0


# ---------------------------------------------------- 4. evaluation fee
def evaluation_fee_cents(page_count, is_foreign, service_level):
    billable = max(0, int(page_count) - FREE_PAGES)
    page_charge = 0
    remaining = billable
    tier_a = min(remaining, BRACKET_A_PAGES)
    page_charge += tier_a * RATE_A_CENTS
    remaining -= tier_a
    tier_b = min(remaining, BRACKET_B_PAGES)
    page_charge += tier_b * RATE_B_CENTS
    remaining -= tier_b
    page_charge += remaining * RATE_C_CENTS

    subtotal = BASE_FEE_CENTS + page_charge
    if is_foreign:
        subtotal += FOREIGN_SURCHARGE_CENTS

    multiplier = EXPEDITE_MULTIPLIER if service_level == "EXPEDITED" else Decimal("1.00")
    raw = util.round0(util.dec(subtotal) * multiplier)
    return min(FEE_CAP_CENTS, max(FEE_FLOOR_CENTS, raw))


# ------------------------------------------- 5. evaluation cost allocation
def evaluation_allocation(evaluation_row):
    record = store.credential_records[evaluation_row["credential_record_id"]]
    faculty_id = record["faculty_member_id"]
    fee = int(evaluation_row["fee_cents"])

    weights = {}
    for a in lookup.assignments_of_faculty(faculty_id):
        if a["status"] in INACTIVE_ASSIGNMENT_STATUSES:
            continue
        section = store.course_sections.get(a["course_section_id"])
        if not section:
            continue
        term = store.terms.get(section["term_id"])
        if not term or term["status"] == "CLOSED":
            continue
        program_id = section["program_id"]
        weights[program_id] = util.dec(weights.get(program_id, 0)) + util.dec(
            section["credit_hours"])

    weights = {pid: w for pid, w in weights.items() if w > 0}
    if not weights:
        return [{
            "program_id": evaluation_row["billed_program_id"],
            "weight_credit_hours": 0,
            "share_cents": fee,
        }]

    total_weight = sum(weights.values())
    shares = {}
    for pid, weight in weights.items():
        shares[pid] = int((util.dec(fee) * weight / total_weight).to_integral_value(
            rounding="ROUND_FLOOR"))

    residual = fee - sum(shares.values())
    order = sorted(
        weights.keys(),
        key=lambda pid: (-weights[pid], store.programs[pid]["_seq"]
                         if pid in store.programs else 0),
    )
    index = 0
    while residual > 0 and order:
        shares[order[index % len(order)]] += 1
        residual -= 1
        index += 1

    return [{
        "program_id": pid,
        "weight_credit_hours": util.num(weights[pid]),
        "share_cents": shares[pid],
    } for pid in order]


# ------------------------------------------ 6. accreditor review risk index
def review_risk(program, anchor_roster):
    if anchor_roster is None:
        u = d = e = Decimal(0)
        gap = Decimal(0)
    else:
        included = lookup.included_assignments(program["id"], anchor_roster["term_id"])
        total = len(included)
        unqualified = len([a for a in included
                           if a["status"] in UNQUALIFIED_ASSIGNMENT_STATUSES])
        remediating = len([a for a in included
                           if a["status"] == "REMEDIATION_IN_PROGRESS"])
        u = Decimal(0) if total == 0 else util.dec(unqualified) / util.dec(total)
        e = Decimal(0) if total == 0 else util.dec(remediating) / util.dec(total)

        faculty_ids = {a["faculty_member_id"] for a in included}
        if not faculty_ids:
            d = Decimal(0)
        else:
            deficient = 0
            for fid in faculty_ids:
                member = store.faculty_members.get(fid)
                if member and member["dossier_status"] in ("INCOMPLETE", "DEFICIENT"):
                    deficient += 1
            d = util.dec(deficient) / util.dec(len(faculty_ids))

        minimum = util.dec(program.get("min_terminal_ratio"))
        snapshot = util.dec(anchor_roster.get("adequacy_ratio_snapshot") or 0)
        if minimum == 0 or snapshot >= minimum:
            gap = Decimal(0)
        else:
            gap = min(Decimal(1), (minimum - snapshot) / minimum)

    preliminary = util.round2(Decimal(100) * (
        RISK_WEIGHT_UNQUALIFIED * u
        + RISK_WEIGHT_DOSSIER * d
        + RISK_WEIGHT_REMEDIATION * e
        + RISK_WEIGHT_ADEQUACY_GAP * gap
    ))

    if preliminary < RISK_TIER_LOW_MAX:
        tier = "LOW"
    elif preliminary < RISK_TIER_MODERATE_MAX:
        tier = "MODERATE"
    else:
        tier = "HIGH"

    risk_index = min(Decimal("100.00"),
                     util.round2(preliminary * TIER_MULTIPLIER[tier]))
    due_date = util.add_days(clock.current_date(), RESPONSE_WINDOW_DAYS[tier])

    return {
        "preliminary_risk_index": preliminary,
        "risk_tier": tier,
        "risk_index": risk_index,
        "response_due_date": due_date,
    }


# ----------------------------------------------- 7. tested experience score
def tested_experience_score(years, certification_level, codes):
    years_factor = min(Decimal(1), util.dec(years) / TESTED_EXPERIENCE_YEARS_CAP)
    cert_factor = CERT_FACTOR.get(certification_level, Decimal(0))
    distinct = len({c for c in (codes or [])})
    codes_factor = min(Decimal(1), util.dec(distinct) / TESTED_EXPERIENCE_CODES_CAP)
    return util.round4(
        TESTED_EXPERIENCE_WEIGHT_YEARS * years_factor
        + TESTED_EXPERIENCE_WEIGHT_CERT * cert_factor
        + TESTED_EXPERIENCE_WEIGHT_CODES * codes_factor
    )


# ------------------------------------------ 11. professional development
def pd_compliance(faculty):
    terms = db.ordered(store.terms)
    if not terms:
        return {"pd_hours_current_cycle": Decimal("0.0"), "pd_compliant": False}

    open_terms = [t for t in terms if t["status"] == "OPEN"]
    pool = open_terms or terms
    anchor = None
    for t in pool:
        if anchor is None:
            anchor = t
            continue
        t_end = util.parse_date(t["end_date"])
        a_end = util.parse_date(anchor["end_date"])
        if t_end > a_end:
            anchor = t
    if anchor is None:
        return {"pd_hours_current_cycle": Decimal("0.0"), "pd_compliant": False}

    window_end = util.parse_date(anchor["end_date"])
    window_start = util.add_days(window_end, -PD_CYCLE_DAYS)

    home_program = store.programs.get(faculty.get("home_program_id"))
    program_discipline = (home_program or {}).get("discipline_id")

    total = Decimal(0)
    for record in lookup.pd_records_of(faculty["id"]):
        if record["status"] != "VERIFIED":
            continue
        activity_date = util.parse_date(record["activity_date"])
        if activity_date is None or activity_date < window_start or activity_date > window_end:
            continue
        if not aligns(record["discipline_id"], program_discipline):
            continue
        total += util.dec(record["contact_hours"])

    hours = util.round1(total)
    required = PD_HOURS_REQUIRED.get(faculty["employment_class"], Decimal(0))
    return {"pd_hours_current_cycle": hours, "pd_compliant": hours >= required}


# ---------------------------------------------- 12. assigned-credit ledger
def assigned_credit_hours(faculty_id):
    total = Decimal(0)
    for a in lookup.assignments_of_faculty(faculty_id):
        if a["status"] in INACTIVE_ASSIGNMENT_STATUSES:
            continue
        section = store.course_sections.get(a["course_section_id"])
        if not section:
            continue
        term = store.terms.get(section["term_id"])
        if not term or term["status"] == "CLOSED":
            continue
        total += util.dec(section["credit_hours"])
    return total


def term_load(faculty_id, term_id, exclude_assignment_ids=()):
    total = Decimal(0)
    for a in lookup.assignments_of_faculty(faculty_id):
        if a["status"] in INACTIVE_ASSIGNMENT_STATUSES:
            continue
        if a["id"] in exclude_assignment_ids:
            continue
        section = store.course_sections.get(a["course_section_id"])
        if not section or section["term_id"] != term_id:
            continue
        total += util.dec(section["credit_hours"])
    return total


# ---------------------------------------------- teaching-block conflict
def blocks_conflict(new_section, other_section):
    if new_section["delivery_mode"] == "ONLINE_ASYNC":
        return False
    if other_section["delivery_mode"] == "ONLINE_ASYNC":
        return False
    new_days = set(new_section.get("meeting_days") or [])
    other_days = set(other_section.get("meeting_days") or [])
    if not (new_days & other_days):
        return False
    new_start = new_section.get("meeting_start_minute")
    new_end = new_section.get("meeting_end_minute")
    other_start = other_section.get("meeting_start_minute")
    other_end = other_section.get("meeting_end_minute")
    if None in (new_start, new_end, other_start, other_end):
        return False
    if new_section.get("building_code") == other_section.get("building_code"):
        buffer_minutes = SAME_BUILDING_BUFFER_MINUTES
    else:
        buffer_minutes = CROSS_BUILDING_BUFFER_MINUTES
    return (new_start < other_end + buffer_minutes
            and other_start < new_end + buffer_minutes)
