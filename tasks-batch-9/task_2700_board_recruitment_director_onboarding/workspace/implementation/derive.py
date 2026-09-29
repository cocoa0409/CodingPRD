"""Derived-state recomputation and cascade propagation (PRD 2.9).

Every function here mutates rows in place through store.touch, which refreshes
updated_at and increments version at most once per row per request.  A recompute
that leaves every field identical is not a mutation and does not bump version.
"""

from datetime import date

from calc import (
    add_years,
    candidate_board_set,
    dec,
    governing_award,
    governing_policy,
    parse_iso_date,
    pct_of_cents,
    public_company_ids,
    ratio_pct,
    rhu2,
    rhu_cents,
    whole_years,
)
from store import clock_date, clock_instant, db, touch

COUNTED_NOMINEE = ("PROPOSED", "CONFIRMED", "ELECTED")


def _apply(row, changes):
    """Write changes and mark the row mutated only when something moved."""
    moved = False
    for key, value in changes.items():
        if row.get(key) != value:
            row[key] = value
            moved = True
    if moved:
        touch(row)
    return moved


# --------------------------------------------------------------- child lookups
def slate_nominees(slate_id):
    return [n for n in db.nominees.values() if n["slate_id"] == slate_id]


def counted_nominees(slate_id):
    return [n for n in db.nominees.values()
            if n["slate_id"] == slate_id and n["status"] in COUNTED_NOMINEE]


def slate_votes(slate_id):
    return [v for v in db.votes.values() if v["slate_id"] == slate_id]


def director_items(director_id):
    return [i for i in db.onboarding_items.values() if i["director_id"] == director_id]


def director_assignments(director_id):
    return [a for a in db.assignments.values() if a["director_id"] == director_id]


def committee_assignments(committee_id):
    return [a for a in db.assignments.values() if a["committee_id"] == committee_id]


def candidate_interviews(candidate_id):
    return [s for s in db.interviews.values() if s["candidate_id"] == candidate_id]


def candidate_screens(candidate_id):
    return [s for s in db.screens.values() if s["candidate_id"] == candidate_id]


def nominee_subject_candidate(nominee):
    if nominee.get("candidate_id") is None:
        return None
    return db.candidates.get(nominee["candidate_id"])


def sourcing_firm(nominee):
    candidate = nominee_subject_candidate(nominee)
    if candidate is None:
        return None
    firm_id = candidate.get("search_firm_id")
    if firm_id is None:
        return None
    return db.search_firms.get(firm_id)


# ------------------------------------------------------------ candidate figures
def recompute_candidate_interviews(candidate):
    sessions = [s for s in candidate_interviews(candidate["id"]) if s["status"] == "COMPLETED"]
    count = len(sessions)
    if count:
        total = sum(dec(s["score"]) for s in sessions)
        average = rhu2(total / dec(count))
    else:
        average = 0.00
    _apply(candidate, {"completed_interview_count": count, "interview_score_avg": average})


def recompute_candidate_boards(candidate):
    board_set = candidate_board_set(candidate["id"])
    _apply(candidate, {"external_public_board_count": len(board_set)})
    return board_set


def recompute_readiness(candidate):
    from calc import candidate_readiness_score
    _apply(candidate, {"readiness_score": candidate_readiness_score(candidate)})


# ------------------------------------------------------------- director figures
def refresh_director_clock_fields(director):
    today = clock_date()
    _apply(director, {
        "age_years": whole_years(parse_iso_date(director["birth_date"]), today),
        "tenure_years": whole_years(parse_iso_date(director["appointed_on"]), today),
    })


def recompute_director_boards(director):
    board_set = public_company_ids(
        [d for d in db.directorships.values() if d.get("director_id") == director["id"]])
    _apply(director, {"external_public_board_count": len(board_set)})
    return board_set


def recompute_education_hours(director, policy=None):
    if policy is None:
        policy = governing_policy()
    total = dec(0)
    if policy is not None:
        marker = "%04d" % int(policy["cycle_year"])
        for item in director_items(director["id"]):
            if item["category"] != "CONTINUING_EDUCATION" or item["status"] != "COMPLETED":
                continue
            stamp = item.get("completed_at")
            if not stamp or str(stamp)[0:4] != marker:
                continue
            total = total + dec(item["credit_hours"])
    _apply(director, {"education_hours_cycle": rhu2(total)})


def recompute_onboarding(director):
    items = director_items(director["id"])
    required = [i for i in items if i["is_required"]]
    satisfied = [i for i in required if i["status"] in ("COMPLETED", "WAIVED")]
    touched_any = any(i["status"] in ("COMPLETED", "WAIVED") for i in items)
    if not required:
        status = "NOT_STARTED"
        pct = 0.00
    else:
        if len(satisfied) == len(required):
            status = "COMPLETE"
        elif touched_any:
            status = "IN_PROGRESS"
        else:
            status = "NOT_STARTED"
        pct = ratio_pct(len(satisfied), len(required))
    _apply(director, {"onboarding_status": status, "onboarding_completion_pct": pct})


def recompute_compliance(director, policy=None):
    """Three legs in a fixed order; the first match wins (PRD 3.9)."""
    if policy is None:
        policy = governing_policy()
    if policy is None:
        return
    limit = (policy["max_public_boards_sitting_ceo"] if director["is_sitting_ceo_elsewhere"]
             else policy["max_public_boards_default"])
    status = None
    if director["external_public_board_count"] + 1 > limit:
        status = "OVERBOARDED"
    if status is None:
        award = governing_award(director["id"])
        if award is not None and not award["ownership_compliant"]:
            appointed = parse_iso_date(director["appointed_on"])
            threshold = add_years(appointed, policy["ownership_grace_years"])
            if threshold is not None and clock_date() >= threshold:
                status = "OWNERSHIP_SHORTFALL"
    if status is None:
        deadline = date(int(policy["cycle_year"]), 12, 31)
        if clock_date() >= deadline \
                and dec(director["education_hours_cycle"]) < dec(policy["education_hours_required"]):
            status = "EDUCATION_DELINQUENT"
    if status is None:
        status = "COMPLIANT"
    before = director["compliance_status"]
    _apply(director, {"compliance_status": status})
    if before != status:
        for committee in committees_of_director(director["id"]):
            recompute_committee(committee)


# ------------------------------------------------------------ committee ledger
def committees_of_director(director_id):
    found = {}
    for row in db.assignments.values():
        if row["director_id"] == director_id and row["status"] == "ACTIVE":
            committee = db.committees.get(row["committee_id"])
            if committee is not None:
                found[committee["id"]] = committee
    return list(found.values())


def recompute_committee(committee):
    active = [a for a in committee_assignments(committee["id"]) if a["status"] == "ACTIVE"]
    filled = len(active)
    suspended = False
    has_chair = False
    for row in active:
        director = db.directors.get(row["director_id"])
        if director is not None and director["compliance_status"] == "OVERBOARDED":
            suspended = True
        if row["seat_role"] == "CHAIR":
            has_chair = True
    if suspended:
        status = "SUSPENDED"
    elif filled >= committee["min_seats"] and has_chair:
        status = "AT_STRENGTH"
    else:
        status = "UNDER_STRENGTH"
    _apply(committee, {"filled_seats": filled, "status": status})


# ------------------------------------------------------- search-firm fee ledger
def recompute_firm_ledger(firm):
    """Re-derive every fee-bearing nominee's ordinal, tier and fee, then the ledger.

    Fees are rounded per nominee and the already-rounded integers are summed
    (PRD 3.6); summing raw products would drift by whole cents.
    """
    from store import seq_of
    rows = []
    for nominee in db.nominees.values():
        if nominee["status"] not in COUNTED_NOMINEE:
            continue
        candidate = nominee_subject_candidate(nominee)
        if candidate is None or candidate.get("search_firm_id") != firm["id"]:
            continue
        rows.append(nominee)
    rows.sort(key=lambda n: (str(n["created_at"]), n["ballot_order"], seq_of(n)))
    committed = 0
    fee_touched = set()
    for index, nominee in enumerate(rows, start=1):
        candidate = nominee_subject_candidate(nominee)
        tier = "TIER1" if index <= 2 else "TIER2"
        pct = firm["placement_fee_pct"] if tier == "TIER1" else firm["placement_fee_tier2_pct"]
        fee = pct_of_cents(pct, candidate["target_annual_comp_cents"])
        if _apply(nominee, {"nominee_ordinal": index, "fee_tier_applied": tier,
                            "placement_fee_cents": fee}):
            fee_touched.add(nominee["slate_id"])
        committed += fee
    credit = 0
    if firm["fee_model"] == "RETAINER":
        credit = firm["retainer_fee_cents"] if firm["retainer_fee_cents"] < committed else committed
    _apply(firm, {
        "placed_nominee_count": len(rows),
        "committed_fee_cents": committed,
        "retainer_credit_applied_cents": credit,
        "net_payable_cents": committed - credit,
    })
    return fee_touched


def nominee_fee_preview(firm, candidate, created_at, ballot_order):
    """The fee the candidate's nominee row would carry if appended right now."""
    from store import seq_of
    rows = []
    for nominee in db.nominees.values():
        if nominee["status"] not in COUNTED_NOMINEE:
            continue
        other = nominee_subject_candidate(nominee)
        if other is None or other.get("search_firm_id") != firm["id"]:
            continue
        rows.append((str(nominee["created_at"]), nominee["ballot_order"], seq_of(nominee)))
    rows.append((str(created_at), ballot_order, float("inf")))
    rows.sort()
    ordinal = rows.index((str(created_at), ballot_order, float("inf"))) + 1
    tier = "TIER1" if ordinal <= 2 else "TIER2"
    pct = firm["placement_fee_pct"] if tier == "TIER1" else firm["placement_fee_tier2_pct"]
    return ordinal, tier, pct_of_cents(pct, candidate["target_annual_comp_cents"])


# --------------------------------------------------------------- slate rollups
def recompute_slate(slate, policy=None):
    if policy is None:
        policy = governing_policy()
    counted = counted_nominees(slate["id"])
    total = len(counted)
    independent = sum(1 for n in counted if n["is_independent"])
    pct = ratio_pct(independent, total) if total else 0.00
    shortfall = False
    if total > 0 and policy is not None:
        shortfall = dec(pct) < dec(policy["independence_min_pct"])
    committed = sum(n["placement_fee_cents"] for n in counted)
    contested = False
    for nominee in counted:
        candidate = nominee_subject_candidate(nominee)
        if candidate is not None and candidate["source_channel"] == "UNIVERSAL_PROXY_NOMINATION":
            contested = True
            break
    _apply(slate, {
        "nominee_count": total,
        "independent_nominee_count": independent,
        "independent_nominee_pct": pct,
        "independence_shortfall": shortfall,
        "committed_search_fee_cents": committed,
        "contested": contested,
        "universal_proxy_applicable": contested,
    })


def recompute_slate_tally(slate, policy=None):
    if policy is None:
        policy = governing_policy()
    cast = [v for v in slate_votes(slate["id"]) if v["status"] == "CAST"]
    counts = {"FOR": 0, "AGAINST": 0, "ABSTAIN": 0, "RECUSED": 0}
    for vote in cast:
        counts[vote["ballot"]] = counts.get(vote["ballot"], 0) + 1
    denominator = counts["FOR"] + counts["AGAINST"] + counts["ABSTAIN"]
    approval = ratio_pct(counts["FOR"], denominator) if denominator else 0.00
    quorum = False
    if policy is not None:
        quorum = len(cast) >= policy["quorum_size"]
    _apply(slate, {
        "votes_for": counts["FOR"],
        "votes_against": counts["AGAINST"],
        "votes_abstain": counts["ABSTAIN"],
        "votes_recused": counts["RECUSED"],
        "approval_pct": approval,
        "quorum_met": quorum,
    })


def void_cast_ballots(slate):
    for vote in slate_votes(slate["id"]):
        if vote["status"] == "CAST":
            _apply(vote, {"status": "VOIDED_BY_REVISION"})


def return_slate_to_draft(slate, policy=None):
    """COMMITTEE_REVIEW -> DRAFT with the revision counter advanced and ballots voided."""
    slate["status"] = "DRAFT"
    slate["revision_count"] = slate["revision_count"] + 1
    touch(slate)
    void_cast_ballots(slate)
    recompute_slate_tally(slate, policy)


def settle_nominee_change(changed_slate_ids, firms, policy=None, revise_reviews=True):
    """Hop 4 and hop 5 of the nominee-void cascade."""
    if policy is None:
        policy = governing_policy()
    affected = set(changed_slate_ids)
    for firm in firms:
        affected |= recompute_firm_ledger(firm)
    for slate_id in sorted(affected):
        slate = db.slates.get(slate_id)
        if slate is not None:
            recompute_slate(slate, policy)
    if revise_reviews:
        for slate_id in sorted(changed_slate_ids):
            slate = db.slates.get(slate_id)
            if slate is not None and slate["status"] == "COMMITTEE_REVIEW":
                return_slate_to_draft(slate, policy)


def void_nominee_row(nominee, defer_candidate=True):
    """Mark one nominee VOIDED; optionally defer its candidate subject."""
    _apply(nominee, {"status": "VOIDED", "voided_at": clock_instant()})
    slate = db.slates.get(nominee["slate_id"])
    if defer_candidate:
        candidate = nominee_subject_candidate(nominee)
        if candidate is not None and candidate["status"] == "NOMINATED":
            _apply(candidate, {
                "status": "DEFERRED",
                "deferred_cycle_year": slate["cycle_year"] if slate else None,
            })
    return sourcing_firm(nominee)


def void_live_nominees_of_candidate(candidate, policy=None):
    """Hops 3 to 5 of the rejection cascade: the candidate keeps its own status."""
    changed = set()
    firms = {}
    for nominee in list(db.nominees.values()):
        if nominee.get("candidate_id") != candidate["id"]:
            continue
        if nominee["status"] not in ("PROPOSED", "CONFIRMED"):
            continue
        firm = void_nominee_row(nominee, defer_candidate=False)
        changed.add(nominee["slate_id"])
        if firm is not None:
            firms[firm["id"]] = firm
    if changed or firms:
        settle_nominee_change(changed, list(firms.values()), policy)
    return changed


# ------------------------------------------------------------- other cascades
def cancel_scheduled_interviews(candidate):
    for session in candidate_interviews(candidate["id"]):
        if session["status"] == "SCHEDULED":
            _apply(session, {"status": "CANCELLED"})


def void_open_screens(candidate):
    for screen in candidate_screens(candidate["id"]):
        if screen["status"] in ("DRAFT", "SUBMITTED"):
            _apply(screen, {"status": "VOIDED"})


def end_active_assignments(director, reason="RETIREMENT_NOTICE"):
    committees = {}
    for row in director_assignments(director["id"]):
        if row["status"] != "ACTIVE":
            continue
        _apply(row, {"status": "ENDED", "ended_reason_code": reason,
                     "ended_at": clock_instant()})
        committee = db.committees.get(row["committee_id"])
        if committee is not None:
            committees[committee["id"]] = committee
    for committee in committees.values():
        recompute_committee(committee)


SEEDED_ITEMS = (
    ("BOARD_ORIENTATION", "BUSINESS_ORIENTATION"),
    ("COMMITTEE_ONBOARD", "COMMITTEE_ONBOARDING"),
    ("DOC_PORTAL", "DOCUMENT_ACCESS"),
)


def seed_onboarding_items(director):
    """Hop 4 of the election cascade: three required orientation modules."""
    from store import add_days, new_row
    due_on = add_days(clock_date(), 90).isoformat()
    for module_code, category in SEEDED_ITEMS:
        row = new_row({
            "director_id": director["id"],
            "module_code": module_code,
            "category": category,
            "is_required": True,
            "credit_hours": 0.0,
            "due_on": due_on,
            "status": "PENDING",
            "completed_at": None,
            "waiver_reason": None,
        })
        db.onboarding_items[row["id"]] = row
    recompute_onboarding(director)
    recompute_education_hours(director)


# --------------------------------------------------------------- screen factory
SCREEN_INPUTS = (
    ("payments_to_company_cents", 0),
    ("recipient_gross_revenue_cents", 0),
    ("prior_employment_end_on", None),
    ("family_member_employed", False),
    ("auditor_affiliation", False),
    ("charitable_contributions_cents", 0),
    ("company_gross_revenue_cents", 0),
)


def new_screen(candidate_id, supplied=None):
    """Create one DRAFT independence screen; every factual field has a default."""
    from store import new_row
    supplied = supplied or {}
    fields = {"candidate_id": candidate_id, "standard_applied": None}
    for name, default in SCREEN_INPUTS:
        value = supplied.get(name)
        fields[name] = default if value is None else value
    fields.update({
        "bright_line_fail_count": 0,
        "qualitative_fail_count": 0,
        "determination": "PENDING",
        "disqualifying_factor_code": None,
        "status": "DRAFT",
        "submitted_at": None,
        "determined_at": None,
    })
    row = new_row(fields)
    db.screens[row["id"]] = row
    return row
