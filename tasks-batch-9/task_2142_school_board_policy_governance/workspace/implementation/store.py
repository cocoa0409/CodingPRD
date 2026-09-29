"""In-memory store, logical clock, record helpers and serialization.

The store starts completely empty on every boot. No entity is ever seeded.
"""

import itertools
import re
import uuid
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


class _Clock(object):
    def __init__(self):
        self.now = CLOCK_START

    def get(self):
        return self.now

    def set(self, dt):
        self.now = dt.astimezone(UTC)


clock = _Clock()

_seq_counter = itertools.count(1)

TABLES = [
    "board_members", "committees", "assignments", "disclosures", "policies",
    "policy_versions", "mandates", "meetings", "agenda_items", "public_comments",
    "waivers", "evaluations", "ratings", "publications",
]

db = {t: {} for t in TABLES}

# per-request dirty set (records already version-bumped in this request)
_dirty = set()


def reset_request_state():
    _dirty.clear()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq_counter)


def now():
    return clock.get()


def fmt_dt(dt):
    if dt is None:
        return None
    if not isinstance(dt, datetime):
        return dt
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}(:\d{2}(\.\d{1,9})?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_dt(value):
    """Parse an ISO 8601 instant. Returns None when the value is not parseable."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s or not _ISO_RE.match(s):
        return None
    s2 = s.replace(" ", "T").replace("t", "T")
    if s2.endswith("Z") or s2.endswith("z"):
        s2 = s2[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s2)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def days_between(start, end):
    """Whole days between two instants: floor(seconds / 86400)."""
    delta = (end - start).total_seconds()
    return int(delta // 86400)


def add_days(dt, days):
    return dt + timedelta(days=days)


# ---------------------------------------------------------------------------
# record lifecycle
# ---------------------------------------------------------------------------

def create(table, kind, fields):
    rec = dict(fields)
    ts = now()
    rec["id"] = new_id()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_kind"] = kind
    rec["_seq"] = next_seq()
    db[table][rec["id"]] = rec
    # a freshly created record must never receive a cascade bump in the same request
    _dirty.add((kind, rec["id"]))
    return rec


def touch(rec):
    """Refresh updated_at and bump version at most once per request."""
    key = (rec["_kind"], rec["id"])
    if key in _dirty:
        rec["updated_at"] = now()
        return rec
    _dirty.add(key)
    rec["updated_at"] = now()
    rec["version"] = rec.get("version", 1) + 1
    return rec


def set_fields(rec, **kwargs):
    """Assign fields; touch the record only when something actually changed."""
    changed = False
    for k, v in kwargs.items():
        if rec.get(k, "__missing__") != v:
            rec[k] = v
            changed = True
    if changed:
        touch(rec)
    return changed


def rows(table):
    return list(db[table].values())


def sorted_rows(table):
    return sorted(db[table].values(), key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# serialization
# ---------------------------------------------------------------------------

COMMON = ["id", "created_at", "updated_at", "version"]

FIELDS = {
    "BoardMember": COMMON + [
        "full_name", "seat_number", "office", "term_start_date", "term_end_date",
        "employer_name", "status", "open_recusal_count", "active_committee_count",
    ],
    "Committee": COMMON + [
        "name", "charter_type", "seat_capacity", "quorum_size", "status",
        "filled_seat_count", "voting_seat_count", "vacant_seat_count",
    ],
    "CommitteeAssignment": COMMON + [
        "committee_id", "board_member_id", "role_on_committee", "status",
        "assigned_on", "removed_on",
    ],
    "ConflictDisclosure": COMMON + [
        "board_member_id", "policy_id", "nature", "narrative", "status",
        "disclosed_on", "cleared_on",
    ],
    "Policy": COMMON + [
        "code", "title", "category", "legal_requirement_level", "manual_section",
        "status", "adopted_version_no", "last_review_date", "version_count",
        "open_mandate_count", "overdue_mandate_count", "active_waiver_count",
        "compliance_state",
    ],
    "PolicyVersion": COMMON + [
        "policy_id", "version_no", "body_text", "summary_of_change", "status",
        "reading_count", "first_reading_meeting_id", "adopting_meeting_id",
        "adopted_at", "effective_date", "superseded_at", "withdrawn_reason",
        "policy_version_after",
    ],
    "LegalMandate": COMMON + [
        "notice_code", "policy_id", "citation", "issued_on", "compliance_deadline",
        "required_action", "status", "satisfied_by_version_no", "days_past_deadline",
    ],
    "Meeting": COMMON + [
        "title", "scope", "committee_id", "meeting_type", "scheduled_start_utc",
        "public_comment_rule", "status", "minutes_status",
        "minutes_approved_at_meeting_id", "notice_posted_at", "agenda_locked_at",
        "opened_at", "adjourned_at", "seated_member_count_snapshot",
        "attending_member_ids", "quorum_required", "public_comment_minutes_budget",
        "public_comment_minutes_remaining", "public_comment_allocation_variant",
    ],
    "AgendaItem": COMMON + [
        "meeting_id", "sequence_no", "item_type", "title", "policy_version_id",
        "waiver_request_id", "requires_public_comment", "status", "vote_yes",
        "vote_no", "vote_abstain", "recused_member_count", "absent_member_count",
        "required_yes_votes", "vote_outcome", "acted_at", "meeting_version_after",
    ],
    "PublicComment": COMMON + [
        "agenda_item_id", "speaker_name", "speaker_affiliation", "requested_minutes",
        "submitted_at", "allotted_minutes", "status", "denial_reason",
    ],
    "WaiverRequest": COMMON + [
        "policy_id", "reviewing_committee_id", "requesting_school_code",
        "justification", "requested_start_date", "requested_end_date", "status",
        "committee_recommendation", "denial_stage", "max_allowed_days",
        "granted_start_date", "granted_end_date", "granted_days", "revoked_on",
    ],
    "SuperintendentEvaluation": COMMON + [
        "cycle_year", "window_start_date", "window_end_date",
        "midyear_checkpoint_date", "goal_count", "weight_instructional",
        "weight_fiscal", "weight_community", "weight_governance", "status",
        "reopen_count", "rating_count", "eligible_rater_count",
        "midyear_formative_score", "summative_composite_score", "adopted_at",
    ],
    "EvaluationRating": COMMON + [
        "evaluation_id", "board_member_id", "domain", "score", "comments",
        "submitted_at", "phase", "counted_in_summative",
    ],
    "ManualPublication": COMMON + [
        "publication_label", "as_of_date", "status", "certification_state",
        "pinned_entries", "entry_count", "compliance_gap_count", "published_at",
        "superseded_by_label",
    ],
}


def serialize(rec):
    kind = rec["_kind"]
    out = {}
    for name in FIELDS[kind]:
        v = rec.get(name)
        if isinstance(v, datetime):
            v = fmt_dt(v)
        elif isinstance(v, list):
            v = list(v)
        out[name] = v
    if kind == "Meeting":
        out["quorum_required"] = meeting_quorum_required(rec)
    return out


def meeting_quorum_required(meeting):
    if meeting.get("opened_at") is not None:
        base = meeting.get("seated_member_count_snapshot") or 0
    else:
        base = len([m for m in db["board_members"].values()
                    if m["status"] == "SEATED"])
    return base // 2 + 1
