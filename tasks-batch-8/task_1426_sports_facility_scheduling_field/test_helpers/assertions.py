"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

CLASSIFICATIONS = ["RESIDENT", "NONRESIDENT", "COMMERCIAL"]
ORG_TYPES = ["YOUTH_LEAGUE", "ADULT_LEAGUE", "SCHOOL", "TOURNAMENT_OPERATOR", "CORPORATE"]
ORG_STANDINGS = ["GOOD", "PROBATION", "SUSPENDED"]
FACILITY_CLASSES = ["DIAMOND", "RECTANGLE", "MULTIPURPOSE"]
CONDITION_STATUSES = ["OPEN", "LIMITED", "CLOSED"]
FEE_SCHEDULE_STATUSES = ["DRAFT", "PUBLISHED", "SUPERSEDED"]
WINDOW_STATUSES = ["SCHEDULED", "OPEN", "CLOSED", "ALLOCATED"]
EVENT_TYPES = ["LEAGUE_GAME", "LEAGUE_PRACTICE", "TOURNAMENT", "SPECIAL_EVENT"]
APPLICATION_STATUSES = ["SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO", "AWARDED",
                        "WAITLISTED", "DENIED", "WITHDRAWN"]
PERMIT_STATUSES = ["RESERVED", "CONFIRMED", "RAINED_OUT", "COMPLETED",
                   "CANCELLED", "NO_SHOW", "REVOKED"]
CLOSURE_REASONS = ["RAIN", "TURF_REST", "MAINTENANCE", "SAFETY"]
CLOSURE_STATUSES = ["ACTIVE", "LIFTED"]
INVOICE_STATUSES = ["DRAFT", "ISSUED", "PARTIALLY_PAID", "PAID", "VOID", "REFUNDED"]
PAYMENT_KINDS = ["PAYMENT", "REFUND"]
PAYMENT_METHODS = ["CHECK", "CARD", "CASH", "CREDIT"]
PAYMENT_STATUSES = ["CLEARED", "PENDING_APPROVAL"]
STRIKE_STATUSES = ["ACTIVE", "RESCINDED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive integer, got {data.get('version')!r}"


def assert_organization(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["classification"] in CLASSIFICATIONS
    assert data["org_type"] in ORG_TYPES
    assert data["standing"] in ORG_STANDINGS
    assert isinstance(data["prior_seasons_active"], int) and data["prior_seasons_active"] >= 0
    assert isinstance(data["no_show_strikes_active"], int) and data["no_show_strikes_active"] >= 0


def assert_facility(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["facility_class"] in FACILITY_CLASSES
    assert isinstance(data["has_lights"], bool)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["weekly_prime_hour_cap"], int) and data["weekly_prime_hour_cap"] >= 1
    assert isinstance(data["nightly_light_block_cap"], int) and data["nightly_light_block_cap"] >= 1
    assert data["condition_status"] in CONDITION_STATUSES
    assert isinstance(data["condition_reason"], str)
    assert isinstance(data["weekly_prime_hours_used"], int) and data["weekly_prime_hours_used"] >= 0


def assert_fee_schedule(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in FEE_SCHEDULE_STATUSES
    for field in ("hourly_resident_cents", "hourly_nonresident_cents",
                  "hourly_commercial_cents", "lights_block_cents",
                  "tournament_day_cents", "min_deposit_cents"):
        assert isinstance(data[field], int) and data[field] >= 0, field
    for field in ("nonresident_surcharge_pct", "commercial_surcharge_pct"):
        assert isinstance(data[field], int) and 0 <= data[field] <= 100, field
    assert isinstance(data["tournament_day_min_minutes"], int) and data["tournament_day_min_minutes"] >= 60
    assert isinstance(data["deposit_pct"], int) and 1 <= data["deposit_pct"] <= 100


def assert_allocation_window(data: dict):
    _assert_common(data)
    assert isinstance(data["season_code"], str) and data["season_code"]
    assert data["status"] in WINDOW_STATUSES
    assert isinstance(data["prime_cap_hours_per_org"], int) and data["prime_cap_hours_per_org"] >= 1
    assert isinstance(data["max_tournament_days_per_org"], int) and data["max_tournament_days_per_org"] >= 0


def assert_permit_application(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("window_id", ""))
    assert is_valid_uuid(data.get("organization_id", ""))
    assert is_valid_uuid(data.get("facility_id", ""))
    assert data["event_type"] in EVENT_TYPES
    assert data["status"] in APPLICATION_STATUSES
    assert isinstance(data["start_minute"], int) and 0 <= data["start_minute"] <= 1439
    assert isinstance(data["end_minute"], int) and data["start_minute"] < data["end_minute"] <= 1440
    assert isinstance(data["headcount"], int) and data["headcount"] >= 1
    assert isinstance(data["wants_lights"], bool)
    assert isinstance(data["provisional_score"], int)
    assert data["final_score"] is None or isinstance(data["final_score"], int)
    assert isinstance(data["decision_note"], str)


def assert_permit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("application_id", ""))
    assert is_valid_uuid(data.get("organization_id", ""))
    assert is_valid_uuid(data.get("facility_id", ""))
    assert is_valid_uuid(data.get("fee_schedule_id", ""))
    assert data["original_permit_id"] is None or is_valid_uuid(data["original_permit_id"])
    assert data["event_type"] in EVENT_TYPES
    assert data["status"] in PERMIT_STATUSES
    assert isinstance(data["lights_approved"], bool)
    assert isinstance(data["lights_minutes_quoted"], int) and data["lights_minutes_quoted"] >= 0
    for field in ("quoted_field_fee_cents", "quoted_lights_fee_cents",
                  "quoted_surcharge_cents", "quoted_total_cents", "deposit_required_cents"):
        assert isinstance(data[field], int) and data[field] >= 0, field
    assert data["final_total_cents"] is None or isinstance(data["final_total_cents"], int)
    assert data["attendance_minutes"] is None or isinstance(data["attendance_minutes"], int)
    assert isinstance(data["rain_reschedule_count"], int) and data["rain_reschedule_count"] >= 0


def assert_field_closure(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("facility_id", ""))
    assert data["reason"] in CLOSURE_REASONS
    assert data["status"] in CLOSURE_STATUSES


def assert_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("permit_id", ""))
    assert is_valid_uuid(data.get("organization_id", ""))
    assert data["status"] in INVOICE_STATUSES
    for field in ("field_fee_cents", "lights_fee_cents", "surcharge_cents",
                  "credit_cents", "penalty_cents", "total_cents", "deposit_cents",
                  "paid_cents", "refunded_cents",
                  "deposit_penalty_applied_cents", "deposit_balance_applied_cents",
                  "deposit_refunded_cents"):
        assert isinstance(data[field], int) and data[field] >= 0, field
    assert isinstance(data["adjustment_cents"], int)
    assert isinstance(data["balance_due_cents"], int)


def assert_payment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("invoice_id", ""))
    assert is_valid_uuid(data.get("organization_id", ""))
    assert data["kind"] in PAYMENT_KINDS
    assert data["method"] in PAYMENT_METHODS
    assert data["status"] in PAYMENT_STATUSES
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert isinstance(data["initiated_by"], str) and data["initiated_by"]
    assert data["approved_by"] is None or isinstance(data["approved_by"], str)


def assert_strike_record(data: dict):
    """StrikeRecord is the immutable ledger entry of PRD section 2.5: it
    carries id and created_at only (no updated_at, no version)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "StrikeRecord must not carry updated_at"
    assert "version" not in data, "StrikeRecord must not carry version"
    assert is_valid_uuid(data.get("organization_id", ""))
    assert is_valid_uuid(data.get("permit_id", ""))
    assert isinstance(data["strike_points"], int) and data["strike_points"] >= 10
    assert data["status"] in STRIKE_STATUSES


def assert_usage_ledger(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("organization_id", ""))
    assert isinstance(data["season_code"], str) and data["season_code"]
    for field in ("awarded_prime_hours", "awarded_nonprime_hours",
                  "attended_hours", "no_show_count"):
        assert isinstance(data[field], int) and data[field] >= 0, field


def assert_invoice_money_identity(invoice: dict):
    """PRD section 3.8: balance_due_cents is the total minus net payments,
    where net means paid minus refunded."""
    assert invoice["balance_due_cents"] == (
        invoice["total_cents"] - (invoice["paid_cents"] - invoice["refunded_cents"])
    ), (
        f"money identity broken: total {invoice['total_cents']} != "
        f"(paid {invoice['paid_cents']} - refunded {invoice['refunded_cents']}) "
        f"+ balance {invoice['balance_due_cents']}"
    )


def assert_deposit_waterfall_conservation(invoice: dict):
    """PRD section 3.8: at every closeout the three waterfall buckets sum
    exactly to the deposit held, min(net payments, deposit_cents).

    The held amount is what the waterfall saw at the closeout instant, i.e.
    BEFORE its own REFUND row disbursed. A refund bucket of 10000 cents or
    less is created directly CLEARED (PRD 3.8), so it has already raised
    refunded_cents on the post-closeout invoice; add it back to reconstruct
    the net-paid the waterfall observed. A larger bucket pends approval and
    never touched refunded_cents, so nothing is added back for it."""
    refunded_bucket = invoice["deposit_refunded_cents"]
    waterfall_refund_cleared = refunded_bucket if 0 < refunded_bucket <= 10000 else 0
    net_paid_at_closeout = (
        invoice["paid_cents"] - (invoice["refunded_cents"] - waterfall_refund_cleared))
    deposit_held = min(net_paid_at_closeout, invoice["deposit_cents"])
    buckets = (invoice["deposit_penalty_applied_cents"]
               + invoice["deposit_balance_applied_cents"]
               + refunded_bucket)
    assert deposit_held == buckets, (
        f"waterfall conservation broken: held {deposit_held} != buckets sum {buckets}"
    )
