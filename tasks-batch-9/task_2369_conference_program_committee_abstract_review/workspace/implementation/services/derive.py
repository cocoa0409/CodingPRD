"""Computed fields and output serialisation."""

from decimal import Decimal

from db import db
from services import calc

FORMATS = ("ORAL", "POSTER", "WORKSHOP")

# Abstract statuses that still hold a committed format slot.
HOLDING_STATUSES = {"ACCEPTED", "CONFIRMED", "SCHEDULED", "PRESENTED", "NO_SHOW"}

# SessionSlot statuses that count toward session packing / capacity.
COUNTED_SLOT_STATUSES = {"SCHEDULED", "PRESENTED", "NO_SHOW_RECORDED"}

# DiscrepancyCase statuses that are not terminal.
NON_TERMINAL_CASE_STATUSES = {"OPEN", "ARBITER_ASSIGNED", "THIRD_REVIEW_PENDING", "ESCALATED"}

CHAIRING_SESSION_STATUSES = {"PLANNED", "PUBLISHED", "LOCKED"}


# ---------------------------------------------------------------------------
# collection scans
# ---------------------------------------------------------------------------

def conference_abstracts(conference_id):
    return [a for a in db.abstracts.values() if a["conference_id"] == conference_id]


def abstract_reviews(abstract_id):
    return [r for r in db.reviews.values() if r["abstract_id"] == abstract_id]


def conference_reviews(conference_id):
    ids = {a["id"] for a in db.abstracts.values() if a["conference_id"] == conference_id}
    return [r for r in db.reviews.values() if r["abstract_id"] in ids]


def conference_cases(conference_id):
    ids = {a["id"] for a in db.abstracts.values() if a["conference_id"] == conference_id}
    return [c for c in db.cases.values() if c["abstract_id"] in ids]


def abstract_cases(abstract_id):
    return [c for c in db.cases.values() if c["abstract_id"] == abstract_id]


def open_case_for_abstract(abstract_id):
    for case in abstract_cases(abstract_id):
        if case["status"] in NON_TERMINAL_CASE_STATUSES:
            return case
    return None


def conference_sessions(conference_id):
    return [s for s in db.sessions.values() if s["conference_id"] == conference_id]


def session_slots(session_id):
    return [s for s in db.slots.values() if s["session_id"] == session_id]


def counted_slots(session_id):
    return [s for s in session_slots(session_id) if s["status"] in COUNTED_SLOT_STATUSES]


def abstract_slots(abstract_id):
    return [s for s in db.slots.values() if s["abstract_id"] == abstract_id]


def abstract_accreditations(abstract_id):
    return [a for a in db.accreditations.values() if a["abstract_id"] == abstract_id]


def accreditation_disclosures(accreditation_id):
    return [d for d in db.disclosures.values() if d["accreditation_id"] == accreditation_id]


def conference_accreditations(conference_id):
    ids = {a["id"] for a in db.abstracts.values() if a["conference_id"] == conference_id}
    return [a for a in db.accreditations.values() if a["abstract_id"] in ids]


def member_declarations(member_id):
    return [d for d in db.declarations.values() if d["member_id"] == member_id]


# ---------------------------------------------------------------------------
# Conference derived counters
# ---------------------------------------------------------------------------

def accepted_count(conference_id, fmt):
    return sum(
        1
        for a in db.abstracts.values()
        if a["conference_id"] == conference_id
        and a["decision"] == fmt
        and a["status"] in HOLDING_STATUSES
    )


def waitlisted_count(conference_id):
    return sum(
        1
        for a in db.abstracts.values()
        if a["conference_id"] == conference_id and a["status"] == "WAITLISTED"
    )


def capacity_for(conference, fmt):
    return conference[{"ORAL": "oral_slot_capacity",
                       "POSTER": "poster_slot_capacity",
                       "WORKSHOP": "workshop_slot_capacity"}[fmt]]


def remaining_capacity(conference, fmt):
    return capacity_for(conference, fmt) - accepted_count(conference["id"], fmt)


def cme_minutes_allocated(conference_id):
    return sum(
        acc["content_minutes"]
        for acc in conference_accreditations(conference_id)
        if acc["validation_status"] == "VALIDATED"
    )


def cme_minutes_available(conference):
    return conference["cme_minutes_pool_total"] - cme_minutes_allocated(conference["id"])


# ---------------------------------------------------------------------------
# CommitteeMember derived counters
# ---------------------------------------------------------------------------

def current_review_load(member_id):
    return sum(
        1 for r in db.reviews.values()
        if r["reviewer_member_id"] == member_id and r["status"] == "ASSIGNED"
    )


def chaired_session_count(member_id):
    return sum(
        1 for s in db.sessions.values()
        if s["chair_member_id"] == member_id and s["status"] in CHAIRING_SESSION_STATUSES
    )


# ---------------------------------------------------------------------------
# Abstract derived counters
# ---------------------------------------------------------------------------

def round_reviews(abstract):
    """Reviews in the consensus input set S for this abstract."""
    return [
        r for r in abstract_reviews(abstract["id"])
        if r["status"] == "SUBMITTED" and r["assigned_round"] == abstract["revision_round"]
    ]


def submitted_review_count(abstract):
    return len(round_reviews(abstract))


def author_emails(abstract):
    emails = set()
    author = db.authors.get(abstract["submitting_author_id"])
    if author:
        emails.add(author["email"])
    for email in abstract["coauthor_emails"]:
        emails.add(email)
    return emails


def author_rows(abstract):
    rows = []
    author = db.authors.get(abstract["submitting_author_id"])
    if author:
        rows.append(author)
    for email in abstract["coauthor_emails"]:
        for candidate in db.authors.values():
            if candidate["email"] == email:
                rows.append(candidate)
    return rows


def author_affiliations(abstract):
    return {row["affiliation"] for row in author_rows(abstract) if row["affiliation"]}


# ---------------------------------------------------------------------------
# Author sanctions
# ---------------------------------------------------------------------------

def no_show_strikes(author_id):
    return sum(
        1 for s in db.slots.values()
        if s["presenter_author_id"] == author_id and s["status"] == "NO_SHOW_RECORDED"
    )


def embargo_breach_count(author_id):
    return sum(
        1 for a in db.abstracts.values()
        if a["submitting_author_id"] == author_id and a["embargo_status"] == "BREACHED"
    )


def sanction_status(author_id):
    total = no_show_strikes(author_id) + embargo_breach_count(author_id)
    if total >= 2:
        return "BARRED"
    if total == 1:
        return "WARNED"
    return "NONE"


def is_barred(author):
    return author is not None and sanction_status(author["id"]) == "BARRED"


# ---------------------------------------------------------------------------
# Accreditation derived fields
# ---------------------------------------------------------------------------

def commercial_bias_flag(accreditation):
    if not accreditation["commercial_support_disclosed"]:
        return False
    for disclosure in accreditation_disclosures(accreditation["id"]):
        if disclosure["mitigation_required"] and not disclosure["mitigation_completed"]:
            return True
    return False


def awarded_credits(accreditation):
    if accreditation["validation_status"] != "VALIDATED":
        return Decimal("0.00")
    return calc.credits_for_minutes(accreditation["content_minutes"])


def validated_accreditation(abstract_id):
    for acc in abstract_accreditations(abstract_id):
        if acc["validation_status"] == "VALIDATED":
            return acc
    return None


# ---------------------------------------------------------------------------
# Session derived fields
# ---------------------------------------------------------------------------

def session_slot_count(session_id):
    return len(counted_slots(session_id))


def session_committed_minutes(session_id):
    durations = [s["duration_minutes"] for s in counted_slots(session_id)]
    return calc.committed_minutes(durations)


def session_credit_total(session_id):
    total = Decimal("0.00")
    for slot in counted_slots(session_id):
        acc = validated_accreditation(slot["abstract_id"])
        if acc is not None:
            total += calc.credits_for_minutes(acc["content_minutes"])
    return total.quantize(Decimal("0.01"))


def session_posture(session):
    if not session["cme_designated"]:
        return "NOT_APPLICABLE"
    if session_credit_total(session["id"]) >= Decimal("0.50"):
        return "COMPLIANT"
    return "NON_COMPLIANT"


def session_window_minutes(session):
    from db import parse_dt

    start = parse_dt(session["start_utc"])
    end = parse_dt(session["end_utc"])
    return int((end - start).total_seconds() // 60)


# ---------------------------------------------------------------------------
# Serialisers
# ---------------------------------------------------------------------------

def common(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def conference_out(row):
    out = common(row)
    for field in ("name", "code", "status", "event_start_utc", "event_end_utc",
                  "abstract_deadline_utc", "review_deadline_utc", "program_freeze_utc",
                  "oral_slot_capacity", "poster_slot_capacity", "workshop_slot_capacity",
                  "cme_minutes_pool_total", "cfa_extension_count", "review_reopen_count",
                  "abstract_sequence"):
        out[field] = row[field]
    out["accepted_oral_count"] = accepted_count(row["id"], "ORAL")
    out["accepted_poster_count"] = accepted_count(row["id"], "POSTER")
    out["accepted_workshop_count"] = accepted_count(row["id"], "WORKSHOP")
    out["waitlisted_count"] = waitlisted_count(row["id"])
    out["cme_minutes_allocated"] = cme_minutes_allocated(row["id"])
    out["cme_minutes_available"] = cme_minutes_available(row)
    return out


def category_out(row):
    out = common(row)
    for field in ("conference_id", "code", "name", "max_word_count",
                  "requires_structured_body", "allowed_formats", "min_reviews_required",
                  "discrepancy_threshold", "cme_eligible"):
        out[field] = row[field]
    return out


def author_out(row):
    out = common(row)
    for field in ("full_name", "email", "affiliation", "is_registered", "registered_at"):
        out[field] = row[field]
    out["no_show_strikes"] = no_show_strikes(row["id"])
    out["embargo_breach_count"] = embargo_breach_count(row["id"])
    out["sanction_status"] = sanction_status(row["id"])
    return out


def abstract_out(row):
    out = common(row)
    for field in ("conference_id", "category_id", "submitting_author_id", "title",
                  "body_word_count", "body_structured", "requested_format", "keywords",
                  "coauthor_emails", "is_newsworthy", "blind_code", "status",
                  "revision_round", "provisional_score", "final_score", "score_spread",
                  "decision", "decision_downgraded", "decided_by_member_id",
                  "embargo_status", "embargo_until_utc", "press_outlet_name"):
        out[field] = row[field]
    out["submitted_review_count"] = submitted_review_count(row)
    return out


def member_out(row):
    out = common(row)
    for field in ("conference_id", "full_name", "email", "expertise_keywords",
                  "member_role", "max_review_load", "calibration_bias", "status",
                  "coi_declaration_status"):
        out[field] = row[field]
    out["current_review_load"] = current_review_load(row["id"])
    out["chaired_session_count"] = chaired_session_count(row["id"])
    return out


def declaration_out(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "member_id": row["member_id"],
        "conflict_subject_type": row["conflict_subject_type"],
        "conflict_subject_value": row["conflict_subject_value"],
        "conflict_type": row["conflict_type"],
        "declared_at": row["declared_at"],
    }


def review_out(row):
    out = common(row)
    for field in ("abstract_id", "reviewer_member_id", "status", "assigned_round",
                  "expertise_match_score", "due_utc", "is_third_review",
                  "score_originality", "score_methodology", "score_relevance",
                  "score_clarity", "confidence", "recommended_format",
                  "comments_to_authors", "weighted_score", "submitted_at",
                  "decline_reason"):
        out[field] = row[field]
    return out


def case_out(row):
    out = common(row)
    for field in ("abstract_id", "arbiter_member_id", "third_review_id", "status",
                  "spread_at_open", "resolution_method", "resolved_score"):
        out[field] = row[field]
    return out


def session_out(row):
    out = common(row)
    for field in ("conference_id", "chair_member_id", "theme_code", "format",
                  "room_code", "start_utc", "end_utc", "capacity_slots",
                  "cme_designated", "status"):
        out[field] = row[field]
    out["slot_count"] = session_slot_count(row["id"])
    out["committed_minutes"] = session_committed_minutes(row["id"])
    out["accredited_credit_total"] = session_credit_total(row["id"])
    out["accreditation_posture"] = session_posture(row)
    return out


def slot_out(row):
    out = common(row)
    for field in ("session_id", "abstract_id", "presenter_author_id",
                  "swapped_with_slot_id", "position", "duration_minutes", "status"):
        out[field] = row[field]
    return out


def accreditation_out(row):
    out = common(row)
    for field in ("abstract_id", "content_minutes", "commercial_support_disclosed",
                  "validation_status", "validated_by_member_id", "validated_at"):
        out[field] = row[field]
    out["commercial_bias_flag"] = commercial_bias_flag(row)
    out["awarded_credits"] = awarded_credits(row)
    return out


def disclosure_out(row):
    out = common(row)
    for field in ("abstract_id", "accreditation_id", "author_id",
                  "has_financial_relationship", "relationship_entity",
                  "mitigation_required", "mitigation_completed", "status",
                  "rejection_reason"):
        out[field] = row[field]
    return out


def change_request_out(row):
    out = common(row)
    for field in ("conference_id", "session_slot_id", "requested_by_author_id",
                  "change_type", "target_session_id", "substitute_presenter_author_id",
                  "approver_member_id", "status", "submitted_at", "days_to_event",
                  "estimated_fee_cents", "final_fee_cents", "rush_pct_applied"):
        out[field] = row[field]
    return out
