"""Submission, CorrelationEntry and PublicComment endpoints (PRD 3.4, 3.5, 3.7)."""

from datetime import timedelta
from decimal import Decimal

import calc
import domain
import serializers as S
import validation as V
from db import apply_changes, base_record, db, now
from errors import fail
from middleware import authorize
from response import respond, respond_list

from flask import Blueprint

bp = Blueprint("submissions", __name__)

READ_ROLES = (
    "PlatformAdmin",
    "PublisherEditor",
    "EditorialDirector",
    "StateAdoptionOfficer",
    "ReviewCommitteeMember",
    "PricingManager",
)

CORRELATION_LIST_ROLES = (
    "PlatformAdmin",
    "PublisherEditor",
    "ReviewCommitteeMember",
    "StateAdoptionOfficer",
)

COMMENT_LIST_ROLES = (
    "PlatformAdmin",
    "PublisherEditor",
    "StateAdoptionOfficer",
    "ReviewCommitteeMember",
    "PublicCommenter",
)

ENTRY_VERDICTS = ("ACCEPT", "INSUFFICIENT")
WITHDRAW_REASONS = ("REVISE", "ABANDON")


# --- Submission ------------------------------------------------------------
@bp.post("/submissions")
def create_submission():
    authorize(("PublisherEditor",))
    payload = V.body()

    cycle_id = V.get_str(payload, "cycle_id")
    title_id = V.get_str(payload, "title_id")

    cycle = domain.find_cycle(cycle_id, "ERR_REFERENCED_RESOURCE_NOT_FOUND")
    domain.find_title(title_id, "ERR_REFERENCED_RESOURCE_NOT_FOUND")
    state = db.state_profiles[cycle["state_id"]]

    for existing in db.submissions.values():
        if existing["cycle_id"] != cycle_id or existing["title_id"] != title_id:
            continue
        if existing["review_status"] not in ("WITHDRAWN", "NOT_ADOPTED"):
            fail(
                "ERR_DUPLICATE_SUBMISSION",
                "A live submission already exists for this cycle and title.",
            )

    record = base_record()
    record.update(
        {
            "cycle_id": cycle_id,
            "title_id": title_id,
            "review_status": "DRAFT",
            "pricing_status": "UNPRICED",
            "sampling_status": calc.sampling_status(
                state["sampling_copies_required"], 0
            ),
            "sample_copies_shipped": 0,
            "pinned_content_revision": None,
            "content_pin_stale": False,
            "self_reported_coverage_pct": Decimal("0.00"),
            "verified_coverage_pct": Decimal("0.00"),
            "prohibited_hit_count": 0,
            "missing_required_topic_count": 0,
            "unresolved_critical_count": 0,
            "overdue_response_count": 0,
            "compliance_score": 100,
            "adoption_blocked": False,
            "filed_at": None,
        }
    )
    domain.recompute_submission(record, bump=False)
    db.submissions[record["id"]] = record
    return respond(S.serialize(record, S.SUBMISSION_FIELDS), 201)


@bp.get("/submissions/<submission_id>")
def get_submission(submission_id):
    authorize(READ_ROLES)
    record = domain.find_submission(submission_id)
    return respond(S.serialize(record, S.SUBMISSION_FIELDS))


@bp.get("/submissions")
def list_submissions():
    authorize(READ_ROLES)
    limit, offset = V.pagination()
    cycle_id = V.query_str("cycle_id")
    title_id = V.query_str("title_id")
    review_status = V.query_enum("review_status", V.REVIEW_STATUSES)
    pricing_status = V.query_enum("pricing_status", V.PRICING_STATUSES)
    adoption_blocked = V.query_bool("adoption_blocked")

    items = domain.ordered(list(db.submissions.values()))
    if cycle_id is not None:
        items = [i for i in items if i["cycle_id"] == cycle_id]
    if title_id is not None:
        items = [i for i in items if i["title_id"] == title_id]
    if review_status is not None:
        items = [i for i in items if i["review_status"] == review_status]
    if pricing_status is not None:
        items = [i for i in items if i["pricing_status"] == pricing_status]
    if adoption_blocked is not None:
        items = [i for i in items if i["adoption_blocked"] == adoption_blocked]

    total = len(items)
    page = items[offset:offset + limit]
    return respond_list(
        S.serialize_many(page, S.SUBMISSION_FIELDS), total, limit, offset
    )


# --- CorrelationEntry ------------------------------------------------------
@bp.post("/submissions/<submission_id>/correlations")
def create_correlation(submission_id):
    authorize(("PublisherEditor",))
    payload = V.body()

    standard_code = V.get_str(payload, "standard_code", min_len=1, max_len=40)
    depth_level = V.get_enum(payload, "depth_level", V.DEPTH_LEVELS)
    page_reference = V.get_str(payload, "page_reference", min_len=1, max_len=40)
    evidence_citation = V.get_str(
        payload, "evidence_citation", min_len=20, max_len=500
    )

    submission = domain.find_submission(submission_id)
    if submission["review_status"] != "DRAFT":
        fail(
            "ERR_SUBMISSION_STATE_INVALID",
            "Correlation entries may only be added while the submission is DRAFT.",
        )

    cycle = db.adoption_cycles[submission["cycle_id"]]
    standard = None
    for candidate in domain.standards_of_state(cycle["state_id"]):
        if (
            candidate["subject"] == cycle["subject"]
            and candidate["standard_code"] == standard_code
        ):
            standard = candidate
            break
    if standard is None:
        fail(
            "ERR_STANDARD_NOT_IN_FRAMEWORK",
            "Standard %s is not declared for this state and subject."
            % standard_code,
        )

    record = base_record()
    record.update(
        {
            "submission_id": submission_id,
            "standard_code": standard_code,
            "depth_level": depth_level,
            "page_reference": page_reference,
            "evidence_citation": evidence_citation,
            "reviewer_verdict": "PENDING",
            "verdict_by_user_id": None,
            "effective_weight": calc.round_half_up(
                Decimal(standard["weight"]) * calc.DEPTH_MULTIPLIERS[depth_level], 2
            ),
        }
    )
    db.correlation_entries[record["id"]] = record

    domain.recompute_submission(
        submission, coverage=True, comments=False, content=False
    )
    return respond(S.serialize(record, S.CORRELATION_ENTRY_FIELDS), 201)


@bp.get("/submissions/<submission_id>/correlations")
def list_correlations(submission_id):
    authorize(CORRELATION_LIST_ROLES)
    limit, offset = V.pagination()
    reviewer_verdict = V.query_enum("reviewer_verdict", V.REVIEWER_VERDICTS)
    depth_level = V.query_enum("depth_level", V.DEPTH_LEVELS)

    domain.find_submission(submission_id)

    items = domain.entries_of_submission(submission_id)
    if reviewer_verdict is not None:
        items = [i for i in items if i["reviewer_verdict"] == reviewer_verdict]
    if depth_level is not None:
        items = [i for i in items if i["depth_level"] == depth_level]

    total = len(items)
    page = items[offset:offset + limit]
    return respond_list(
        S.serialize_many(page, S.CORRELATION_ENTRY_FIELDS), total, limit, offset
    )


@bp.post("/submissions/<submission_id>/correlations/<entry_id>/verdict")
def correlation_verdict(submission_id, entry_id):
    user_id, _role = authorize(("ReviewCommitteeMember",))
    payload = V.body()
    verdict = V.get_enum(payload, "verdict", ENTRY_VERDICTS)

    submission = domain.find_submission(submission_id)
    entry = db.correlation_entries.get(entry_id)
    if entry is None or entry["submission_id"] != submission_id:
        fail(
            "ERR_CORRELATION_ENTRY_NOT_FOUND",
            "Correlation entry %s does not belong to this submission." % entry_id,
        )
    if submission["review_status"] != "DRAFT":
        fail(
            "ERR_SUBMISSION_STATE_INVALID",
            "Entry verdicts may only be recorded while the submission is DRAFT.",
        )

    apply_changes(
        entry,
        {
            "reviewer_verdict": "ACCEPTED" if verdict == "ACCEPT" else "INSUFFICIENT",
            "verdict_by_user_id": user_id,
        },
    )
    domain.recompute_submission(
        submission, coverage=True, comments=False, content=False
    )
    return respond(S.serialize(entry, S.CORRELATION_ENTRY_FIELDS))


# --- filing and withdrawal -------------------------------------------------
@bp.post("/submissions/<submission_id>/file")
def file_submission(submission_id):
    authorize(("PublisherEditor",))
    V.body()

    submission = domain.find_submission(submission_id)
    if submission["review_status"] != "DRAFT":
        fail(
            "ERR_SUBMISSION_STATE_INVALID",
            "Only a DRAFT submission may be filed.",
        )

    cycle, title, state = domain.submission_context(submission)

    if title["status"] not in ("ACTIVE", "REVISION_PLANNED"):
        fail(
            "ERR_TITLE_NOT_RELEASED",
            "The edition has not been released for submission.",
        )
    if cycle["status"] != "OPEN":
        fail(
            "ERR_CYCLE_NOT_OPEN_FOR_SUBMISSION",
            "The adoption cycle is not OPEN for submission.",
        )

    prohibited_hits, missing_topics = domain.content_counters(submission)
    if prohibited_hits > 0:
        fail(
            "ERR_PROHIBITED_CONTENT_PRESENT",
            "The edition still carries content this state prohibits.",
        )
    if missing_topics > 0:
        fail(
            "ERR_REQUIRED_TOPIC_MISSING",
            "The edition is missing a topic this state requires.",
        )

    clock = now()
    if clock < cycle["submission_open_at"] or clock >= cycle["submission_deadline_at"]:
        fail(
            "ERR_SUBMISSION_WINDOW_CLOSED",
            "The logical clock sits outside the cycle's submission window.",
        )

    entries = domain.entries_of_submission(submission_id)
    if not entries:
        fail(
            "ERR_CORRELATION_SET_EMPTY",
            "At least one correlation entry is required before filing.",
        )

    deep = ("PRACTICE", "MASTERY")
    claimed = ("PENDING", "ACCEPTED")
    for standard in domain.denominator_set(cycle, title):
        if not standard["is_focus"]:
            continue
        covered = any(
            e["standard_code"] == standard["standard_code"]
            and e["depth_level"] in deep
            and e["reviewer_verdict"] in claimed
            for e in entries
        )
        if not covered:
            fail(
                "ERR_FOCUS_STANDARD_UNCOVERED",
                "Focus standard %s is not cited at PRACTICE depth or deeper."
                % standard["standard_code"],
            )

    self_reported, _verified = domain.coverage_values(submission)
    if self_reported < state["min_verified_coverage_pct"]:
        fail(
            "ERR_COVERAGE_BELOW_MINIMUM",
            "Self-reported coverage is below the state's minimum.",
        )

    if submission["sampling_status"] not in ("NOT_REQUIRED", "SHIPPED"):
        fail(
            "ERR_SAMPLING_INCOMPLETE",
            "The state's sampling requirement is not satisfied.",
        )

    domain.recompute_submission(
        submission,
        extra={
            "review_status": "FILED",
            "filed_at": clock,
            "pinned_content_revision": title["content_revision"],
            "content_pin_stale": False,
        },
    )
    domain.recount_cycle(cycle)
    return respond(S.serialize(submission, S.SUBMISSION_FIELDS))


@bp.post("/submissions/<submission_id>/withdraw")
def withdraw_submission(submission_id):
    authorize(("PublisherEditor",))
    payload = V.body()
    reason = V.get_enum(payload, "reason", WITHDRAW_REASONS)

    submission = domain.find_submission(submission_id)
    cycle = db.adoption_cycles[submission["cycle_id"]]

    if reason == "REVISE":
        if cycle["status"] not in ("OPEN", "CLOSED_FOR_SUBMISSION", "IN_REVIEW"):
            fail(
                "ERR_ADOPTION_CYCLE_STATE_INVALID",
                "A revision withdrawal requires an open review calendar.",
            )
    elif cycle["status"] in ("DECIDED", "ARCHIVED"):
        fail(
            "ERR_ADOPTION_CYCLE_STATE_INVALID",
            "The adoption cycle no longer admits withdrawals.",
        )

    if reason == "REVISE":
        if submission["review_status"] not in ("FILED", "SCHEDULED"):
            fail(
                "ERR_SUBMISSION_STATE_INVALID",
                "Only a FILED or SCHEDULED submission may be revised.",
            )
        for slot in domain.slots_of_submission(submission_id):
            if slot["status"] == "RESERVED":
                domain.cancel_slot(slot)
        domain.recompute_submission(
            submission,
            extra={
                "review_status": "DRAFT",
                "pinned_content_revision": None,
                "content_pin_stale": False,
            },
        )
    else:
        if submission["review_status"] != "DRAFT":
            fail(
                "ERR_SUBMISSION_STATE_INVALID",
                "Only a DRAFT submission may be abandoned.",
            )
        apply_changes(submission, {"review_status": "WITHDRAWN"})

    domain.recount_cycle(cycle)
    return respond(S.serialize(submission, S.SUBMISSION_FIELDS))


@bp.post("/submissions/<submission_id>/sampling-shipments")
def ship_samples(submission_id):
    authorize(("PublisherEditor",))
    payload = V.body()
    units = V.get_int(payload, "units", minimum=1)
    V.get_str(
        payload, "carrier_ref", min_len=1, max_len=60, required=False, default=None
    )

    submission = domain.find_submission(submission_id)
    if submission["review_status"] != "DRAFT":
        fail(
            "ERR_SUBMISSION_STATE_INVALID",
            "Sample copies may only be shipped while the submission is DRAFT.",
        )

    _cycle, title, state = domain.submission_context(submission)
    if title["on_hand_units"] < units:
        fail(
            "ERR_INSUFFICIENT_PRINT_INVENTORY",
            "on_hand_units does not cover the requested shipment.",
        )

    apply_changes(
        title,
        {
            "on_hand_units": title["on_hand_units"] - units,
            "sample_reserved_units": title["sample_reserved_units"] + units,
        },
    )
    shipped = submission["sample_copies_shipped"] + units
    apply_changes(
        submission,
        {
            "sample_copies_shipped": shipped,
            "sampling_status": calc.sampling_status(
                state["sampling_copies_required"], shipped
            ),
        },
    )
    return respond(S.serialize(submission, S.SUBMISSION_FIELDS))


# --- PublicComment ---------------------------------------------------------
@bp.post("/submissions/<submission_id>/public-comments")
def create_public_comment(submission_id):
    authorize(("PublicCommenter", "StateAdoptionOfficer"))
    payload = V.body()

    commenter_ref = V.get_str(payload, "commenter_ref", min_len=1, max_len=60)
    category = V.get_enum(payload, "category", V.COMMENT_CATEGORIES)
    severity = V.get_enum(payload, "severity", V.COMMENT_SEVERITIES)
    comment_body = V.get_str(payload, "body", min_len=10, max_len=2000)

    submission = domain.find_submission(submission_id)
    _cycle, _title, state = domain.submission_context(submission)

    record = base_record()
    record.update(
        {
            "submission_id": submission_id,
            "commenter_ref": commenter_ref,
            "category": category,
            "severity": severity,
            "body": comment_body,
            "status": "OPEN",
            "response_due_at": record["created_at"]
            + timedelta(
                seconds=state["comment_response_days"] * calc.SECONDS_PER_DAY
            ),
            "responded_at": None,
            "response_body": None,
            "was_overdue_at_response": False,
        }
    )
    db.public_comments[record["id"]] = record

    domain.recompute_submission(
        submission, coverage=False, comments=True, content=False
    )
    return respond(S.serialize(record, S.PUBLIC_COMMENT_FIELDS), 201)


@bp.get("/submissions/<submission_id>/public-comments")
def list_public_comments(submission_id):
    authorize(COMMENT_LIST_ROLES)
    limit, offset = V.pagination()
    status = V.query_enum("status", V.COMMENT_STATUSES)
    severity = V.query_enum("severity", V.COMMENT_SEVERITIES)
    category = V.query_enum("category", V.COMMENT_CATEGORIES)

    domain.find_submission(submission_id)

    items = domain.comments_of_submission(submission_id)
    if status is not None:
        items = [i for i in items if i["status"] == status]
    if severity is not None:
        items = [i for i in items if i["severity"] == severity]
    if category is not None:
        items = [i for i in items if i["category"] == category]

    total = len(items)
    page = items[offset:offset + limit]
    return respond_list(
        S.serialize_many(page, S.PUBLIC_COMMENT_FIELDS), total, limit, offset
    )


@bp.post("/public-comments/<comment_id>/response")
def respond_to_comment(comment_id):
    authorize(("PublisherEditor",))
    payload = V.body()
    response_body = V.get_str(payload, "response_body", min_len=1, max_len=2000)

    comment = domain.find_comment(comment_id)
    submission = db.submissions[comment["submission_id"]]

    if submission["review_status"] not in domain.LIVE_REVIEW_STATUSES:
        fail(
            "ERR_SUBMISSION_STATE_INVALID",
            "The submission is not in a state that admits comment responses.",
        )
    if comment["status"] not in ("OPEN", "ESCALATED"):
        fail(
            "ERR_PUBLIC_COMMENT_STATE_INVALID",
            "This comment has already been answered.",
        )

    clock = now()
    overdue = (
        comment["status"] == "ESCALATED"
        or comment["was_overdue_at_response"]
        or clock >= comment["response_due_at"]
    )
    apply_changes(
        comment,
        {
            "status": "RESPONDED",
            "responded_at": clock,
            "response_body": response_body,
            "was_overdue_at_response": overdue,
        },
    )
    domain.recompute_submission(
        submission, coverage=False, comments=True, content=False
    )
    return respond(S.serialize(comment, S.PUBLIC_COMMENT_FIELDS))
