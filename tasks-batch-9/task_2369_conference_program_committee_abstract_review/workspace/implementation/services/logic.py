"""State-machine side effects, cascades, selector and conserved ledgers."""

from decimal import Decimal

from db import db, new_row, parse_dt, touch
from services import calc, derive


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------

def conference_of(abstract):
    return db.conferences.get(abstract["conference_id"])


def category_of(abstract):
    return db.categories.get(abstract["category_id"])


# ---------------------------------------------------------------------------
# blinding / conflict of interest (PRD 2.10)
# ---------------------------------------------------------------------------

def declaration_matches(declaration, abstract):
    subject_type = declaration["conflict_subject_type"]
    if subject_type == "NONE":
        return False
    value = declaration["conflict_subject_value"]
    if value is None:
        return False
    if subject_type == "AUTHOR_EMAIL":
        return value in derive.author_emails(abstract)
    if subject_type == "AFFILIATION":
        return value in derive.author_affiliations(abstract)
    return False


def member_has_conflict(member_id, abstract):
    for declaration in derive.member_declarations(member_id):
        if declaration_matches(declaration, abstract):
            return True
    return False


def member_is_author(member, abstract):
    return member["email"] in derive.author_emails(abstract)


def member_holds_live_review(member_id, abstract_id):
    for review in derive.abstract_reviews(abstract_id):
        if review["reviewer_member_id"] == member_id and review["status"] in ("ASSIGNED", "SUBMITTED"):
            return True
    return False


# ---------------------------------------------------------------------------
# reviewer_selection_by_expertise
# ---------------------------------------------------------------------------

def select_reviewer(abstract, exclude=()):
    exclude = set(exclude)
    emails = derive.author_emails(abstract)
    candidates = []
    for member in db.members.values():
        if member["conference_id"] != abstract["conference_id"]:
            continue
        if member["member_role"] != "REVIEWER":
            continue
        if member["status"] != "ACTIVE":
            continue
        if member["coi_declaration_status"] != "SUBMITTED":
            continue
        load = derive.current_review_load(member["id"])
        if load >= member["max_review_load"]:
            continue
        if member_has_conflict(member["id"], abstract):
            continue
        if member["email"] in emails:
            continue
        if member_holds_live_review(member["id"], abstract["id"]):
            continue
        if member["id"] in exclude:
            continue
        score = calc.dice_coefficient(member["expertise_keywords"], abstract["keywords"])
        if score < calc.MIN_MATCH_SCORE:
            continue
        candidates.append((score, member["max_review_load"] - load, member))
    if not candidates:
        return None
    candidates.sort(key=lambda t: (-t[0], -t[1], t[2]["created_at"], t[2]["_seq"]))
    return candidates[0][2]


# ---------------------------------------------------------------------------
# reviewer load ledger
# ---------------------------------------------------------------------------

def bump_member(member):
    """A member's derived load / chairing counter changed: register a mutation."""
    if member is not None:
        touch(member)


def create_review(abstract, member, due_utc=None, is_third_review=False):
    conference = conference_of(abstract)
    review = new_row({
        "abstract_id": abstract["id"],
        "reviewer_member_id": member["id"],
        "status": "ASSIGNED",
        "assigned_round": abstract["revision_round"],
        "expertise_match_score": calc.dice_coefficient(
            member["expertise_keywords"], abstract["keywords"]),
        "due_utc": due_utc or conference["review_deadline_utc"],
        "is_third_review": bool(is_third_review),
        "score_originality": None,
        "score_methodology": None,
        "score_relevance": None,
        "score_clarity": None,
        "confidence": None,
        "recommended_format": None,
        "comments_to_authors": None,
        "weighted_score": None,
        "submitted_at": None,
        "decline_reason": None,
    })
    db.reviews[review["id"]] = review
    bump_member(member)
    if abstract["status"] == "SUBMITTED":
        abstract["status"] = "UNDER_REVIEW"
        touch(abstract)
    return review


def void_review(review):
    review["status"] = "VOIDED"
    touch(review)
    bump_member(db.members.get(review["reviewer_member_id"]))


def void_assigned_reviews(reviews):
    for review in reviews:
        if review["status"] == "ASSIGNED":
            void_review(review)


# ---------------------------------------------------------------------------
# consensus / spread / discrepancy
# ---------------------------------------------------------------------------

def recompute_provisional(abstract):
    reviews = derive.round_reviews(abstract)
    abstract["provisional_score"] = calc.provisional_score(reviews)
    abstract["score_spread"] = calc.score_spread(reviews)


def compute_final(abstract):
    return calc.final_score(derive.round_reviews(abstract))


def maybe_promote_to_scored(abstract):
    category = category_of(abstract)
    if abstract["status"] != "UNDER_REVIEW":
        return False
    if category is None:
        return False
    if derive.submitted_review_count(abstract) >= category["min_reviews_required"]:
        abstract["status"] = "SCORED"
        return True
    return False


def maybe_open_case(abstract):
    spread = abstract["score_spread"]
    if spread is None:
        return None
    category = category_of(abstract)
    if category is None:
        return None
    if spread < category["discrepancy_threshold"]:
        return None
    if derive.open_case_for_abstract(abstract["id"]) is not None:
        return None
    case = new_row({
        "abstract_id": abstract["id"],
        "arbiter_member_id": None,
        "third_review_id": None,
        "status": "OPEN",
        "spread_at_open": spread,
        "resolution_method": None,
        "resolved_score": None,
    })
    db.cases[case["id"]] = case
    return case


def resolve_third_review_case(abstract, review):
    """Third review submitted: resolve or escalate the pending case."""
    case = None
    for candidate in derive.abstract_cases(abstract["id"]):
        if candidate["third_review_id"] == review["id"] and candidate["status"] == "THIRD_REVIEW_PENDING":
            case = candidate
            break
    if case is None:
        return
    category = category_of(abstract)
    spread = abstract["score_spread"]
    threshold = category["discrepancy_threshold"] if category else Decimal("0")
    if spread is not None and spread < threshold:
        case["status"] = "RESOLVED"
        case["resolution_method"] = "THIRD_REVIEW"
        resolved = compute_final(abstract)
        case["resolved_score"] = resolved
        touch(case)
        abstract["final_score"] = resolved
        touch(abstract)
    else:
        case["status"] = "ESCALATED"
        touch(case)


def apply_review_submission(review, abstract, scores, confidence, recommended_format,
                            comments):
    member = db.members.get(review["reviewer_member_id"])
    review["score_originality"] = scores["originality"]
    review["score_methodology"] = scores["methodology"]
    review["score_relevance"] = scores["relevance"]
    review["score_clarity"] = scores["clarity"]
    review["confidence"] = confidence
    review["recommended_format"] = recommended_format
    if comments is not None:
        review["comments_to_authors"] = comments
    review["weighted_score"] = calc.weighted_score(
        scores["originality"], scores["methodology"], scores["relevance"],
        scores["clarity"], member["calibration_bias"] if member else Decimal("0.00"))
    review["status"] = "SUBMITTED"
    review["submitted_at"] = db.now_raw()
    touch(review)
    bump_member(member)

    recompute_provisional(abstract)
    maybe_promote_to_scored(abstract)
    touch(abstract)

    maybe_open_case(abstract)
    if review["is_third_review"]:
        resolve_third_review_case(abstract, review)


# ---------------------------------------------------------------------------
# format capacity waterfall + waitlist promotion
# ---------------------------------------------------------------------------

def waitlist_candidates(conference_id, fmt):
    rows = []
    for abstract in db.abstracts.values():
        if abstract["conference_id"] != conference_id:
            continue
        if abstract["status"] != "WAITLISTED":
            continue
        category = category_of(abstract)
        if category is None or fmt not in category["allowed_formats"]:
            continue
        rows.append(abstract)

    def rank(abstract):
        score = abstract["final_score"]
        if score is None:
            score = abstract["provisional_score"]
        missing = score is None
        return (missing, -(score or Decimal("0")), abstract["created_at"], abstract["_seq"])

    rows.sort(key=rank)
    return rows


def promote_from_waitlist(conference, fmt, decided_by_member_id=None):
    candidates = waitlist_candidates(conference["id"], fmt)
    if not candidates:
        return None
    promoted = candidates[0]
    promoted["status"] = "ACCEPTED"
    promoted["decision"] = fmt
    promoted["decision_downgraded"] = fmt != promoted["requested_format"]
    if decided_by_member_id is not None:
        promoted["decided_by_member_id"] = decided_by_member_id
    touch(promoted)
    touch(conference)
    return promoted


# ---------------------------------------------------------------------------
# session helpers
# ---------------------------------------------------------------------------

def bump_session(session):
    touch(session)


def unpublish_if_empty(session):
    if session["status"] == "PUBLISHED" and derive.session_slot_count(session["id"]) == 0:
        session["status"] = "PLANNED"
        touch(session)


def unpublish_if_non_compliant(session):
    if session["status"] == "PUBLISHED" and derive.session_posture(session) == "NON_COMPLIANT":
        session["status"] = "PLANNED"
        touch(session)


def sessions_holding_abstract(abstract_id):
    seen = {}
    for slot in derive.abstract_slots(abstract_id):
        if slot["status"] not in derive.COUNTED_SLOT_STATUSES:
            continue
        session = db.sessions.get(slot["session_id"])
        if session is not None:
            seen[session["id"]] = session
    return list(seen.values())


# ---------------------------------------------------------------------------
# CASCADE-B — abstract withdrawal
# ---------------------------------------------------------------------------

def withdraw_abstract(abstract):
    released_format = abstract["decision"]
    affected_sessions = {}
    for slot in derive.abstract_slots(abstract["id"]):
        if slot["status"] != "SCHEDULED":
            continue
        slot["status"] = "WITHDRAWN"
        touch(slot)
        session = db.sessions.get(slot["session_id"])
        if session is not None:
            affected_sessions[session["id"]] = session

    abstract["status"] = "WITHDRAWN"
    touch(abstract)

    for session in affected_sessions.values():
        bump_session(session)
        unpublish_if_empty(session)

    if released_format is not None and released_format != "REJECTED":
        conference = conference_of(abstract)
        if conference is not None:
            touch(conference)
            promote_from_waitlist(conference, released_format,
                                  abstract["decided_by_member_id"])


# ---------------------------------------------------------------------------
# CASCADE-C — reviewer suspension
# ---------------------------------------------------------------------------

def suspend_member(member):
    member["status"] = "SUSPENDED"
    touch(member)
    for review in list(db.reviews.values()):
        if review["reviewer_member_id"] != member["id"]:
            continue
        if review["status"] != "ASSIGNED":
            continue
        abstract = db.abstracts.get(review["abstract_id"])
        void_review(review)
        if abstract is None:
            continue
        if abstract["status"] != "UNDER_REVIEW":
            continue
        replacement = select_reviewer(abstract, exclude={member["id"]})
        if replacement is not None:
            create_review(abstract, replacement, due_utc=review["due_utc"])


# ---------------------------------------------------------------------------
# CASCADE-D — no-show
# ---------------------------------------------------------------------------

def record_no_show(slot, abstract):
    slot["status"] = "NO_SHOW_RECORDED"
    touch(slot)
    if abstract is not None:
        abstract["status"] = "NO_SHOW"
        touch(abstract)
    author = db.authors.get(slot["presenter_author_id"])
    if author is not None:
        touch(author)


# ---------------------------------------------------------------------------
# CASCADE-E — embargo breach
# ---------------------------------------------------------------------------

def record_embargo_breach(abstract, outlet_name):
    abstract["embargo_status"] = "BREACHED"
    if outlet_name is not None:
        abstract["press_outlet_name"] = outlet_name
    touch(abstract)
    author = db.authors.get(abstract["submitting_author_id"])
    if author is not None:
        touch(author)


# ---------------------------------------------------------------------------
# CASCADE-A — disclosure rejection after validation
# ---------------------------------------------------------------------------

def cascade_disclosure_rejection(disclosure):
    accreditation = db.accreditations.get(disclosure["accreditation_id"])
    if accreditation is None:
        return
    if accreditation["validation_status"] != "VALIDATED":
        touch(accreditation)
        return
    accreditation["validation_status"] = "REVOKED"
    touch(accreditation)
    abstract = db.abstracts.get(accreditation["abstract_id"])
    conference = conference_of(abstract) if abstract else None
    if conference is not None:
        touch(conference)
    for session in sessions_holding_abstract(accreditation["abstract_id"]):
        bump_session(session)
        unpublish_if_non_compliant(session)


# ---------------------------------------------------------------------------
# Conference transition side effects
# ---------------------------------------------------------------------------

def close_review_round(conference):
    for abstract in derive.conference_abstracts(conference["id"]):
        mutated = False
        if abstract["status"] == "UNDER_REVIEW":
            if maybe_promote_to_scored(abstract):
                mutated = True
        if abstract["status"] in ("UNDER_REVIEW", "SCORED"):
            if derive.submitted_review_count(abstract) >= 1:
                abstract["final_score"] = compute_final(abstract)
                mutated = True
        if mutated:
            touch(abstract)
    void_assigned_reviews(derive.conference_reviews(conference["id"]))


def reopen_review_round(conference):
    for abstract in derive.conference_abstracts(conference["id"]):
        if abstract["status"] == "SCORED" and abstract["decision"] is None:
            if abstract["final_score"] is not None:
                abstract["final_score"] = None
                touch(abstract)


def lock_published_sessions(conference):
    for session in derive.conference_sessions(conference["id"]):
        if session["status"] == "PUBLISHED":
            session["status"] = "LOCKED"
            touch(session)


# ---------------------------------------------------------------------------
# session overlap rules
# ---------------------------------------------------------------------------

def room_conflict(conference_id, room_code, start, end, exclude_session_id=None):
    for session in db.sessions.values():
        if session["conference_id"] != conference_id:
            continue
        if session["id"] == exclude_session_id:
            continue
        if session["status"] == "CANCELLED":
            continue
        if session["room_code"] != room_code:
            continue
        peer_start = parse_dt(session["start_utc"])
        peer_end = parse_dt(session["end_utc"])
        if start < peer_end and peer_start < end:
            return session
    return None


def chair_conflict(chair_member_id, start, end, exclude_session_id=None):
    from datetime import timedelta

    gap = timedelta(minutes=calc.CHAIR_TURNAROUND_MINUTES)
    for session in db.sessions.values():
        if session["chair_member_id"] != chair_member_id:
            continue
        if session["id"] == exclude_session_id:
            continue
        if session["status"] == "CANCELLED":
            continue
        peer_start = parse_dt(session["start_utc"])
        peer_end = parse_dt(session["end_utc"])
        if start < peer_end + gap and peer_start < end + gap:
            return session
    return None


def presenter_conflict(presenter_author_id, session):
    start = parse_dt(session["start_utc"])
    end = parse_dt(session["end_utc"])
    for slot in db.slots.values():
        if slot["presenter_author_id"] != presenter_author_id:
            continue
        if slot["status"] != "SCHEDULED":
            continue
        if slot["session_id"] == session["id"]:
            continue
        peer = db.sessions.get(slot["session_id"])
        if peer is None or peer["status"] == "CANCELLED":
            continue
        peer_start = parse_dt(peer["start_utc"])
        peer_end = parse_dt(peer["end_utc"])
        if start <= peer_end and peer_start <= end:
            return slot
    return None
