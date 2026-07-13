"""In-memory data store, logical clock, serializers.

The store starts EMPTY on every boot. Nothing is seeded, preloaded or
hardcoded; every entity is built by the API surface.
"""
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.4: the logical clock starts at exactly 2026-05-01T00:00:00Z.
CLOCK_START = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.accounts = {}
        self.account_users = {}
        self.audiences = {}
        self.subscribers = {}
        self.import_jobs = {}
        self.segments = {}
        self.templates = {}
        self.campaigns = {}
        self.sends = {}
        self.suppressions = {}
        self.journeys = {}
        self.enrollments = {}
        self.billing_cycles = {}
        self.clock = CLOCK_START


db = Store()


def now():
    return db.clock


def set_clock(dt):
    db.clock = dt


def new_id():
    return str(uuid.uuid4())


def new_token():
    return uuid.uuid4().hex


def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO-8601 instant; returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def days_between(later, earlier):
    """Whole days between two instants, fractional remainder discarded."""
    delta = later - earlier
    return int(delta.total_seconds() // 86400)


def base_fields():
    t = now()
    return {"id": new_id(), "created_at": t, "updated_at": t, "version": 1}


def mutate(res):
    """PRD 2.4: every mutation refreshes updated_at and increments version by 1."""
    res["updated_at"] = now()
    res["version"] = res["version"] + 1


# --------------------------------------------------------------------------
# Serializers -- explicit field whitelists, datetimes rendered ISO-8601 UTC.
# --------------------------------------------------------------------------
COMMON = ["id", "created_at", "updated_at", "version"]

FIELDS = {
    "account": ["name", "plan_tier", "status", "suspension_reason",
                "hourly_send_capacity", "granted_send_credits",
                "send_credit_balance", "reserved_send_credits",
                "consumed_send_credits", "billable_contact_count",
                "sender_reputation_score"] + COMMON,
    "account_user": ["account_id", "email", "user_role"] + COMMON,
    "audience": ["account_id", "name", "double_optin_required",
                 "default_from_email", "subscriber_count"] + COMMON,
    "subscriber": ["audience_id", "email", "first_name", "consent_source",
                   "consent_state", "engagement_state", "confirmation_token",
                   "unsubscribe_token", "consent_confirmed_at", "unsubscribed_at",
                   "delivered_send_count", "opened_send_count", "clicked_send_count",
                   "last_opened_at", "engagement_score",
                   "engagement_score_90d"] + COMMON,
    "import_job": ["audience_id", "rows", "status", "row_count", "accepted_count",
                   "rejected_count", "duplicate_count", "suppressed_count",
                   "created_subscriber_ids"] + COMMON,
    "segment": ["audience_id", "name", "consent_states", "min_engagement_score",
                "max_days_since_open", "member_count"] + COMMON,
    "template": ["account_id", "name", "subject", "html_body",
                 "has_unsubscribe_link", "status"] + COMMON,
    "campaign": ["account_id", "audience_id", "segment_id", "template_id",
                 "created_by_user_id", "approved_by_user_id", "name", "status",
                 "ab_test_enabled", "variant_split_pct", "variant_b_subject",
                 "pinned_subject", "pinned_html_body", "pinned_template_version",
                 "review_note", "scheduled_at", "send_window_minutes",
                 "recipient_snapshot_ids", "recipient_count",
                 "reserved_credit_count", "send_charge_cents", "winning_variant",
                 "winner_selected_at"] + COMMON,
    "send": ["campaign_id", "journey_id", "subscriber_id", "variant_label",
             "delivery_status", "engagement_status", "soft_bounce_count",
             "open_count", "click_count", "delivered_at", "first_opened_at",
             "last_clicked_at"] + COMMON,
    # SuppressionEntry is immutable: only id and created_at, no updated_at/version.
    "suppression": ["account_id", "email", "reason", "id", "created_at"],
    "journey": ["account_id", "audience_id", "name", "trigger_event", "steps",
                "status", "active_enrollment_count", "entered_count"] + COMMON,
    "enrollment": ["journey_id", "subscriber_id", "status", "current_step_index",
                   "next_action_at", "enrolled_at"] + COMMON,
    "billing_cycle": ["account_id", "period_start", "period_end", "status",
                      "peak_contact_count", "tier_applied", "base_fee_cents",
                      "overage_cents", "total_cents", "closed_at"] + COMMON,
}


def dump(kind, res):
    out = {}
    for f in FIELDS[kind]:
        v = res.get(f)
        out[f] = iso(v) if isinstance(v, datetime) else v
    return out


def dump_all(kind, rows):
    return [dump(kind, r) for r in rows]
