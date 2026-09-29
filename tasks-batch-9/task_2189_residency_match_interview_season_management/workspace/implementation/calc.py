"""Derived counters and the ten named calculations."""

from decimal import Decimal, ROUND_HALF_UP

from store import (
    RANK_LIST_MAX_MULTIPLE,
    dt_of,
    rows,
)

# ------------------------------------------------------------------ rounding
_QUANT = {0: Decimal("1"), 1: Decimal("0.1"), 2: Decimal("0.01")}


def round_half_up(value, places):
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(_QUANT[places], rounding=ROUND_HALF_UP)


def as_number(value, places):
    """Emit a Decimal as a JSON number carried to `places` decimals."""
    if value is None:
        return None
    return float(round_half_up(value, places))


# ------------------------------------------------------------------ selectors
def program_applications(program_id):
    return [a for a in rows("applications") if a["program_id"] == program_id]


def application_reviews(application_id):
    return [r for r in rows("application_reviews") if r["application_id"] == application_id]


def application_cards(application_id):
    return [c for c in rows("score_cards") if c["application_id"] == application_id]


def wave_invitations(wave_id):
    return [i for i in rows("interview_invitations") if i["wave_id"] == wave_id]


def slot_invitations(slot_id):
    return [i for i in rows("interview_invitations") if i.get("slot_id") == slot_id]


def application_invitations(application_id):
    return [i for i in rows("interview_invitations") if i["application_id"] == application_id]


def wave_slots(wave_id):
    return [s for s in rows("interview_slots") if s["wave_id"] == wave_id]


def slot_assignments(slot_id):
    return [a for a in rows("interview_assignments") if a["slot_id"] == slot_id]


def faculty_assignments(faculty_member_id):
    return [
        a for a in rows("interview_assignments") if a["faculty_member_id"] == faculty_member_id
    ]


def list_entries(rank_list_id):
    return [e for e in rows("rank_list_entries") if e["rank_list_id"] == rank_list_id]


def list_votes(rank_list_id):
    return [v for v in rows("committee_votes") if v["rank_list_id"] == rank_list_id]


def program_match_results(program_id):
    return [m for m in rows("match_results") if m["program_id"] == program_id]


def program_soap_offers(program_id):
    return [o for o in rows("soap_offers") if o["program_id"] == program_id]


def contract_items(contract_id):
    return [c for c in rows("credential_items") if c["contract_id"] == contract_id]


def application_logs(application_id):
    return [c for c in rows("communication_logs") if c["application_id"] == application_id]


def program_faculty(program_id):
    return [f for f in rows("faculty_members") if f["program_id"] == program_id]


def program_waves(program_id):
    return [w for w in rows("interview_waves") if w["program_id"] == program_id]


def program_rank_lists(program_id):
    return [r for r in rows("rank_lists") if r["program_id"] == program_id]


# ------------------------------------------------------------------ counters
def matched_count(program):
    return len([m for m in program_match_results(program["id"]) if m["outcome"] == "MATCHED"])


def unfilled_positions(program):
    return program["quota_positions"] - matched_count(program)


def invited_count(program):
    return len(
        [a for a in program_applications(program["id"]) if a["interview_status"] != "NOT_INVITED"]
    )


def review_count(application):
    return len(application_reviews(application["id"]))


def issued_count(wave):
    return len(
        [i for i in wave_invitations(wave["id"]) if i["status"] in ("ISSUED", "ACCEPTED")]
    )


def waitlisted_count(wave):
    return len([i for i in wave_invitations(wave["id"]) if i["status"] == "WAITLISTED"])


def booked_count(slot):
    return len([i for i in slot_invitations(slot["id"]) if i["status"] == "ACCEPTED"])


def entry_count(rank_list):
    return len(list_entries(rank_list["id"]))


def mandatory_credential_count(contract):
    return len([c for c in contract_items(contract["id"]) if c["is_mandatory"]])


def verified_credential_count(contract):
    return len(
        [
            c
            for c in contract_items(contract["id"])
            if c["is_mandatory"] and c["status"] == "VERIFIED"
        ]
    )


def rank_list_capacity(program):
    return program["quota_positions"] * RANK_LIST_MAX_MULTIPLE


# ------------------------------------------------ 1. screen_composite_score
W_ACADEMIC = Decimal("0.45")
W_EXPERIENCE = Decimal("0.30")
W_HOLISTIC = Decimal("0.25")
PIPELINE_BONUS = Decimal("3.0")
SCORE_CEILING = Decimal("40.0")


def _review_raw(review):
    return (
        Decimal(review["academic_points"]) * W_ACADEMIC
        + Decimal(review["experience_points"]) * W_EXPERIENCE
        + Decimal(review["holistic_points"]) * W_HOLISTIC
    )


def screen_base(application):
    included = application_reviews(application["id"])
    if not included:
        return Decimal("0.0")
    total = sum((_review_raw(r) for r in included), Decimal("0"))
    return total / Decimal(len(included))


def step2_band_bonus(applicant):
    score = applicant["step2_score"]
    if score >= 250:
        return Decimal("6.0")
    if score >= 235:
        return Decimal("4.0")
    if score >= 220:
        return Decimal("2.0")
    return Decimal("0.0")


def provisional_screen_score(application):
    """Variant A: the review mean alone, rounded once at the end."""
    return round_half_up(screen_base(application), 2)


def final_screen_score(application, applicant):
    """Variant B: base + band bonus + pipeline bonus, capped, rounded once."""
    base = screen_base(application)
    bonus = step2_band_bonus(applicant)
    if applicant.get("pipeline_program_alum"):
        bonus += PIPELINE_BONUS
    total = base + bonus
    if total > SCORE_CEILING:
        total = SCORE_CEILING
    return round_half_up(total, 2)


# ------------------------------------------------ 2. interviewer_load_index
LEAD_WEIGHT = Decimal("1.5")
MEMBER_WEIGHT = Decimal("1.0")


def slot_duration_hours(slot):
    start = dt_of(slot, "start_at")
    end = dt_of(slot, "end_at")
    seconds = Decimal((end - start).total_seconds())
    return seconds / Decimal(3600)


def _role_weight(assignment):
    return LEAD_WEIGHT if assignment["panel_role"] == "LEAD" else MEMBER_WEIGHT


def scheduled_load(faculty, slot_lookup):
    total = Decimal("0")
    for assignment in faculty_assignments(faculty["id"]):
        if assignment["status"] != "ASSIGNED":
            continue
        slot = slot_lookup(assignment["slot_id"])
        if slot is None or slot["status"] not in ("OPEN", "BOOKED"):
            continue
        total += slot_duration_hours(slot) * _role_weight(assignment)
    return round_half_up(total, 2)


def realized_load(faculty, slot_lookup):
    total = Decimal("0")
    for assignment in faculty_assignments(faculty["id"]):
        if assignment["status"] != "ASSIGNED":
            continue
        slot = slot_lookup(assignment["slot_id"])
        if slot is None or slot["status"] != "COMPLETED":
            continue
        attendance = Decimal(booked_count(slot)) / Decimal(slot["applicant_capacity"])
        total += slot_duration_hours(slot) * _role_weight(assignment) * attendance
    return round_half_up(total, 2)


# ------------------------------------------------ 3. committee_rubric_score
def card_domain_average(card):
    total = (
        card["communication_score"]
        + card["clinical_reasoning_score"]
        + card["professionalism_score"]
        + card["teamwork_score"]
    )
    return round_half_up(Decimal(total) / Decimal(4), 1)


def committee_rubric_score(application):
    """Pinned order: round each card's mean to 1dp FIRST, then average to 2dp."""
    included = [
        c for c in application_cards(application["id"]) if c["status"] in ("SUBMITTED", "LOCKED")
    ]
    if not included:
        return None
    total = sum((card_domain_average(c) for c in included), Decimal("0"))
    return round_half_up(total / Decimal(len(included)), 2)


# ------------------------------------------------ 4. soap_offer_budget
def soap_offer_budget(program):
    base_unfilled = program["quota_positions"] - matched_count(program)
    if base_unfilled >= 6:
        reserve_credit = 3
    elif base_unfilled >= 3:
        reserve_credit = 2
    elif base_unfilled >= 1:
        reserve_credit = 1
    else:
        reserve_credit = 0
    return base_unfilled + reserve_credit


def live_soap_offers(program_id):
    return [
        o for o in program_soap_offers(program_id) if o["status"] in ("OFFERED", "ACCEPTED")
    ]


# ------------------------------------------------ 5. waitlist_promotion_selector
def waitlist_winner(wave, application_lookup):
    candidates = []
    for invitation in wave_invitations(wave["id"]):
        if invitation["status"] != "WAITLISTED":
            continue
        application = application_lookup(invitation["application_id"])
        if application is None:
            continue
        if application["screening_status"] != "ADVANCED":
            continue
        if application["interview_status"] != "NOT_INVITED":
            continue
        score = application.get("final_screen_score")
        score = Decimal(str(score)) if score is not None else Decimal("-1")
        candidates.append((score, invitation))
    if not candidates:
        return None
    candidates.sort(
        key=lambda pair: (-pair[0], pair[1]["created_at"], pair[1]["_seq"])
    )
    return candidates[0][1]


# ------------------------------------------------ 7. committee_quorum_resolution
COMMITTEE_QUORUM_PCT = Decimal("0.60")


def quorum_threshold(program_id):
    eligible = len([f for f in program_faculty(program_id) if f.get("is_committee_member")])
    exact = Decimal(eligible) * COMMITTEE_QUORUM_PCT
    return int(exact.to_integral_value(rounding="ROUND_CEILING"))


# ------------------------------------------------ 9. pipeline_diversity_report
def pipeline_report(program, applicant_lookup):
    cohort = [
        a
        for a in program_applications(program["id"])
        if a["screening_status"] in ("RECEIVED", "UNDER_REVIEW", "ADVANCED", "REJECTED")
    ]
    cohort_size = len(cohort)

    def pct(count):
        if cohort_size == 0:
            return 0.0
        value = Decimal(count) / Decimal(cohort_size) * Decimal(100)
        return float(round_half_up(value, 1))

    advanced = len([a for a in cohort if a["screening_status"] == "ADVANCED"])
    img = 0
    alum = 0
    labels = {}
    for application in cohort:
        applicant = applicant_lookup(application["applicant_id"])
        if applicant is None:
            continue
        if applicant.get("medical_school_type") == "IMG":
            img += 1
        if applicant.get("pipeline_program_alum"):
            alum += 1
        label = applicant.get("self_identified_group") or "UNREPORTED"
        labels[label] = labels.get(label, 0) + 1

    buckets = [
        {"group": label, "count": labels[label], "share": pct(labels[label])}
        for label in sorted(labels.keys())
    ]
    return {
        "cohort_size": cohort_size,
        "advanced_rate": pct(advanced),
        "img_share": pct(img),
        "pipeline_alum_share": pct(alum),
        "group_buckets": buckets,
    }


# ------------------------------------------------ 11. communication_compliance_scan
PROHIBITED_PHRASES = (
    "how will you rank",
    "rank us",
    "commit to us",
    "where will we be on your list",
    "ranking intent",
)

PRE_MATCH_PHASES = (
    "PRE_SEASON",
    "REVIEW_OPEN",
    "INTERVIEWS_OPEN",
    "RANKING",
    "LIST_CERTIFIED",
)


def compliance_scan(body_text, program):
    normalized = body_text.lower()
    contains = any(phrase in normalized for phrase in PROHIBITED_PHRASES)
    pre_match = program["season_phase"] in PRE_MATCH_PHASES
    status = "FLAGGED" if (contains and pre_match) else "CLEAN"
    return contains, status


def has_unresolved_flag(application_id):
    return any(
        log["compliance_status"] == "FLAGGED" for log in application_logs(application_id)
    )
