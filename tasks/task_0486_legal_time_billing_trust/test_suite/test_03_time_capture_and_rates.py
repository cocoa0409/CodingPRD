"""Billable-rate resolution ladder, six-minute rounding, the round-per-line order,
and the half-open time-entry overlap rule.

Queue A: combinatorial_formula, boundary_precision_check (increment),
resource_temporal_overlap (time entries). Queue B: calculations (rate variants),
validations (timekeeper inactive).
"""
import pytest
from test_helpers import (
    TEST_USERS,
    validate_success, validate_error,
    ApiErrorId,
    create_rate_override_payload, create_time_entry_payload, create_timekeeper_payload,
    create_open_matter, create_client, create_timekeeper, ensure_billing_codes,
    capture_time_entry, create_matter_conflict_cleared,
    api_client,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]
ATT = TEST_USERS["attorney_headers"]


# ---------------------------------------------------------------------------
# Queue A — combinatorial_formula / rate_ladder_three_input_precedence
# ---------------------------------------------------------------------------
def test_client_override_beats_standard_when_no_matter_rate(api):
    """PRD §3.3: "Otherwise, the system looks for a client rate override matching
    the client and the timekeeper's `role_kind`; if such an override exists, the
    resolved rate is the override's `rate_cents`."

    Design: Difficulty/combinatorial_formula/rate_ladder_three_input_precedence
    """
    ensure_billing_codes()
    client_id = create_client()["id"]
    tk_id = create_timekeeper(role_kind="PARTNER", standard_rate_cents=50000)["id"]
    validate_success(
        api.create_rate_override(client_id, create_rate_override_payload("PARTNER", 45000), CLERK),
        expected_status=201)
    # Matter with NO matter_rate -> middle tier (override) must win.
    matter, _, _ = create_open_matter(client_id=client_id, timekeeper_id=tk_id,
                                      matter_rate_cents=None)
    te = capture_time_entry(matter["id"], tk_id, minutes=90)
    assert te["resolved_rate_cents"] == 45000
    # 45000 * ceil(90/6)/10 = 45000 * 15 / 10 = 67500
    assert te["billable_amount_cents"] == 67500


def test_rate_ladder_override_amount_with_ninety_minutes(api):
    """PRD §3.4: "The entry's `billable_amount_cents` is then the resolved hourly
    rate (`resolved_rate_cents`) multiplied by that number of billable tenths,
    divided by ten, with the result rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/rate_ladder_three_input_precedence
    """
    ensure_billing_codes()
    client_id = create_client()["id"]
    tk_id = create_timekeeper(role_kind="PARTNER", standard_rate_cents=50000)["id"]
    validate_success(
        api.create_rate_override(client_id, create_rate_override_payload("PARTNER", 45000), CLERK),
        expected_status=201)
    matter, _, _ = create_open_matter(client_id=client_id, timekeeper_id=tk_id,
                                      matter_rate_cents=None)
    te = capture_time_entry(matter["id"], tk_id, minutes=90)
    assert te["resolved_rate_cents"] == 45000
    assert te["billable_amount_cents"] == 67500


# ---------------------------------------------------------------------------
# Queue A — combinatorial_formula / invoice_rounding_order_round_per_line_then_sum
# ---------------------------------------------------------------------------
def test_rounding_per_line_each_entry_at_odd_rate(api):
    """PRD §3.4: "This per-entry cent amount is computed and pinned on each entry
    individually at capture; invoice subtotals are later formed by summing these
    already-rounded per-entry amounts, and the system never sums raw
    rate-times-minutes products and rounds once at the end."

    Design: Difficulty/combinatorial_formula/invoice_rounding_order_round_per_line_then_sum
    """
    ensure_billing_codes()
    # matter_rate 33333, two min5 entries -> each ceil(5/6)=1 tenth -> 33333*1/10 = 3333.3 -> 3333.
    matter, client_id, tk_id = create_open_matter(matter_rate_cents=33333)
    te1 = capture_time_entry(matter["id"], tk_id, minutes=5, worked_at="2026-05-01T09:00:00Z")
    te2 = capture_time_entry(matter["id"], tk_id, minutes=5, worked_at="2026-05-01T10:00:00Z")
    assert te1["billable_amount_cents"] == 3333
    assert te2["billable_amount_cents"] == 3333


def test_invoice_subtotal_sums_already_rounded_lines(api):
    """PRD §2.5: "The exact rounding order for time-entry amounts and invoice
    subtotals is pinned in §3 and must be followed precisely, because rounding per
    line and then summing yields a different cent total than summing first and
    rounding once."
    PRD §3.5: "The `fees_subtotal_cents` is the sum of `billable_amount_cents`
    over the attached time entries (each already rounded per the per-entry rule)".

    Design: Difficulty/combinatorial_formula/invoice_rounding_order_round_per_line_then_sum
    """
    from test_helpers import create_invoice_payload
    ensure_billing_codes()
    matter, client_id, tk_id = create_open_matter(matter_rate_cents=33333)
    capture_time_entry(matter["id"], tk_id, minutes=5, worked_at="2026-05-01T09:00:00Z")
    capture_time_entry(matter["id"], tk_id, minutes=5, worked_at="2026-05-01T10:00:00Z")
    inv = validate_success(api.create_invoice(create_invoice_payload(matter["id"]), CLERK),
                           expected_status=201)
    final = validate_success(api.finalize_invoice(inv["id"], {}, CLERK))
    # 3333 + 3333 = 6666 (round-per-line then sum), NOT 6667 (round after sum).
    assert final["fees_subtotal_cents"] == 6666


# ---------------------------------------------------------------------------
# Queue A — boundary_precision_check / time_increment_six_vs_seven_minutes
# ---------------------------------------------------------------------------
def test_six_minutes_bills_one_tenth(api):
    """PRD §3.4: "The number of billable tenths of an hour is the worked `minutes`
    divided by 6, rounded up to the next whole tenth (so 1 through 6 minutes bill
    as one tenth, 7 through 12 as two tenths, and so on)."

    Design: Difficulty/boundary_precision_check/time_increment_six_vs_seven_minutes
    """
    ensure_billing_codes()
    matter, client_id, tk_id = create_open_matter(matter_rate_cents=50000)
    te = capture_time_entry(matter["id"], tk_id, minutes=6, worked_at="2026-05-01T09:00:00Z")
    # 6 min -> 1 tenth -> 50000 * 1 / 10 = 5000.
    assert te["billable_amount_cents"] == 5000


def test_seven_minutes_rounds_up_to_two_tenths(api):
    """PRD §3.4: "The number of billable tenths of an hour is the worked `minutes`
    divided by 6, rounded up to the next whole tenth (so 1 through 6 minutes bill
    as one tenth, 7 through 12 as two tenths, and so on)."

    Design: Difficulty/boundary_precision_check/time_increment_six_vs_seven_minutes
    """
    ensure_billing_codes()
    matter, client_id, tk_id = create_open_matter(matter_rate_cents=50000)
    te = capture_time_entry(matter["id"], tk_id, minutes=7, worked_at="2026-05-01T10:00:00Z")
    # 7 min -> 2 tenths -> 50000 * 2 / 10 = 10000.
    assert te["billable_amount_cents"] == 10000


# ---------------------------------------------------------------------------
# Queue A — resource_temporal_overlap / timekeeper_halfopen_time_overlap
# ---------------------------------------------------------------------------
def test_overlapping_time_entry_rejected(api):
    """PRD §3.4: "Two entries for the same timekeeper may not overlap. Because the
    interval is half-open, two entries that merely touch — one ending at exactly
    the instant the next begins — do not overlap and are permitted; any genuine
    overlap with an existing entry for that same timekeeper that is not in
    `status` `WRITTEN_DOWN` is rejected with `ERR_TIME_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/timekeeper_halfopen_time_overlap
    """
    ensure_billing_codes()
    matter, client_id, tk_id = create_open_matter(matter_rate_cents=50000)
    capture_time_entry(matter["id"], tk_id, minutes=60, worked_at="2026-05-01T09:00:00Z")
    # [09:30,10:30) overlaps [09:00,10:00).
    payload = create_time_entry_payload(matter["id"], tk_id, minutes=60,
                                        worked_at="2026-05-01T09:30:00Z")
    validate_error(api.create_time_entry(payload, ATT), ApiErrorId.ERR_TIME_OVERLAP)


def test_back_to_back_time_entry_allowed(api):
    """PRD §3.4: "Because the interval is half-open, two entries that merely touch
    — one ending at exactly the instant the next begins — do not overlap and are
    permitted".

    Design: Difficulty/resource_temporal_overlap/timekeeper_halfopen_time_overlap
    """
    ensure_billing_codes()
    matter, client_id, tk_id = create_open_matter(matter_rate_cents=50000)
    capture_time_entry(matter["id"], tk_id, minutes=60, worked_at="2026-05-01T09:00:00Z")
    # [10:00,10:30) starts exactly where the first ends -> allowed.
    payload = create_time_entry_payload(matter["id"], tk_id, minutes=30,
                                        worked_at="2026-05-01T10:00:00Z")
    validate_success(api.create_time_entry(payload, ATT), expected_status=201)


# ---------------------------------------------------------------------------
# Section 3 — Calculations (rate variants) (queue B)
# ---------------------------------------------------------------------------
def test_matter_rate_beats_standard_rate(api):
    """PRD §3.3: "The highest-precedence tier is the matter's own negotiated rate:
    if the matter's `matter_rate_cents` is present (non-null), the resolved rate is
    exactly that value."

    Design: Corner/calculations/matter_rate_beats_standard_rate
    """
    ensure_billing_codes()
    matter, client_id, tk_id = create_open_matter(matter_rate_cents=40000)
    te = capture_time_entry(matter["id"], tk_id, minutes=90)
    assert te["resolved_rate_cents"] == 40000
    # 40000 * 15 / 10 = 60000
    assert te["billable_amount_cents"] == 60000


def test_standard_rate_when_no_overrides(api):
    """PRD §3.3: "If neither of those applies, the resolved rate falls to the
    timekeeper's `standard_rate_cents`, which is always present and is the
    lowest-precedence tier."

    Design: Corner/calculations/standard_rate_when_no_overrides
    """
    ensure_billing_codes()
    # No matter_rate, no override.
    matter, client_id, tk_id = create_open_matter(matter_rate_cents=None)
    te = capture_time_entry(matter["id"], tk_id, minutes=90)
    assert te["resolved_rate_cents"] == 50000
    # 50000 * 15 / 10 = 75000
    assert te["billable_amount_cents"] == 75000


# ---------------------------------------------------------------------------
# Section 4 — Validations (timekeeper inactive) (queue B)
# ---------------------------------------------------------------------------
def test_timekeeper_inactive_rejected_on_time_entry(api):
    """PRD §3.4: "The timekeeper must be active: capturing against a `Timekeeper`
    whose `is_active` is false is rejected with `ERR_TIMEKEEPER_INACTIVE`
    (HTTP 422)."

    Design: Corner/validations/timekeeper_inactive_rejected_on_time_entry
    """
    ensure_billing_codes()
    active_tk = create_timekeeper(full_name="Active TK", role_kind="PARTNER",
                                  standard_rate_cents=50000)["id"]
    inactive_tk = validate_success(
        api.create_timekeeper(create_timekeeper_payload(
            full_name="Inactive TK", role_kind="ASSOCIATE",
            standard_rate_cents=30000, is_active=False), ADMIN), expected_status=201)["id"]
    matter, client_id, _ = create_open_matter(timekeeper_id=active_tk, matter_rate_cents=50000)
    payload = create_time_entry_payload(matter["id"], inactive_tk, minutes=60)
    validate_error(api.create_time_entry(payload, ATT), ApiErrorId.ERR_TIMEKEEPER_INACTIVE)
