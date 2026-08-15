"""In-memory data store. The store starts EMPTY on every boot — no seeding.

Every record is a plain dict. System-managed common fields per PRD §2.4:
  id          — server-minted UUID, no type prefix
  created_at  — ISO 8601 UTC, 3 fractional digits
  updated_at  — refreshed on every mutation (including cascade side effects)
  version     — integer, starts at 1 on creation, +1 on every mutation
Internal bookkeeping keys are prefixed with "_" and never serialized.
"""

import secrets
import uuid
from datetime import datetime, timezone

# --- The store: dicts keyed by id -------------------------------------------
tours = {}
venues = {}
stops = {}
performances = {}
tech_checks = {}
settlements = {}
cast_members = {}
tracks = {}
coverages = {}
injuries = {}
per_diems = {}
crew_calls = {}

# --- Logical clock (PRD §2.9): default exactly 2026-08-01T00:00:00Z ----------
DEFAULT_CLOCK_RAW = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
logical_clock = {"dt": DEFAULT_CLOCK_DT, "raw": DEFAULT_CLOCK_RAW}

# Monotonic insertion counter — authoritative ordering for created_at ASC.
_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def now_iso():
    """Wall-clock timestamp for system fields: ISO 8601 UTC, 3 fractional digits."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_request_id():
    return "req_" + secrets.token_hex(12)


def new_record():
    ts = now_iso()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(rec):
    """A genuine mutation: refresh updated_at, bump version (PRD §2.4)."""
    rec["version"] += 1
    rec["updated_at"] = now_iso()


# --- Serialization -----------------------------------------------------------
# Declared fields per entity (SCAFFOLD §1.1), common fields appended.
ENTITY_FIELDS = {
    "tour": ["name", "budget_total_cents", "capitalization_cents", "per_diem_policy",
             "per_diem_daily_cents", "royalty_tier_threshold_cents", "status",
             "budget_committed_cents", "budget_spent_cents", "budget_available_cents",
             "cumulative_producer_net_cents", "recouped", "royalty_accrued_cents"],
    "venue": ["name", "city", "stage_width_ft", "fly_capacity_lines", "power_amps",
              "crew_available"],
    "stop": ["tour_id", "venue_id", "play_week_start", "play_week_end", "load_in_date",
             "travel_in_days", "guarantee_cents", "split_pct", "advance_sales_cents",
             "booking_status", "compliance_status", "estimated_venue_payment_cents",
             "cancellation_penalty_cents", "wrapped_total_cents"],
    "performance": ["stop_id", "perf_date", "curtain_time", "duration_minutes",
                    "gross_cents", "status"],
    "tech_check": ["stop_id", "item", "required_value", "actual_value", "status",
                   "waiver_note"],
    "settlement": ["stop_id", "status", "system_gross_cents", "audited_gross_cents",
                   "taxes_cents", "levies_cents", "adjusted_gross_cents",
                   "venue_payment_cents", "producer_share_cents", "royalty_cents",
                   "submitted_by", "approved_by", "dispute_reason"],
    "cast_member": ["tour_id", "name", "contract_type", "weekly_salary_cents",
                    "status", "bump_shows_accrued", "bump_pay_cents"],
    "track": ["tour_id", "track_name", "required_covers", "principal_member_id",
              "available_covers", "exposed"],
    "coverage": ["track_id", "cast_member_id", "kind", "priority_rank", "status"],
    "injury": ["cast_member_id", "notes", "status", "covered_by_coverage_id"],
    "per_diem": ["stop_id", "cast_member_id", "days_present", "travel_days",
                 "policy_snapshot", "daily_rate_cents", "total_cents", "status"],
    "crew_call": ["stop_id", "call_type", "scheduled_start", "lines", "actual_lines",
                  "total_pay_cents", "cancellation_penalty_cents", "status"],
}

COMMON = ["id", "created_at", "updated_at", "version"]


def tour_view(t):
    out = serialize("tour", t)
    # Identity (PRD §3.1): available = total - committed - spent, always.
    out["budget_available_cents"] = (
        t["budget_total_cents"] - t["budget_committed_cents"] - t["budget_spent_cents"]
    )
    return out


def serialize(kind, rec):
    fields = ENTITY_FIELDS[kind]
    out = {}
    for k in COMMON:
        out[k] = rec[k]
    for k in fields:
        out[k] = rec.get(k)
    return out
