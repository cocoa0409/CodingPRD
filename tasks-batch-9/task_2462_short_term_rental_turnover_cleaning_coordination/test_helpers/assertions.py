"""Entity assertions and domain invariant checkers."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ─── Instant comparison ────────────────────────────────────────────────────

def parse_instant(value: Any) -> Optional[datetime]:
    """Parse an ISO 8601 UTC instant regardless of its fractional-digit width.

    PRD §2.4 declares the server's timestamp *format* only for `created_at` and
    `updated_at` — "an ISO 8601 UTC timestamp with three fractional digits" —
    and says of every event timestamp merely that it is a "reading of that
    logical clock". A rule of the form "`accepted_at` reads the logical clock"
    is therefore a claim about the *instant*, not about how many fractional
    digits the serializer prints, so tests compare instants.
    """
    if value is None:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def same_instant(actual: Any, expected: Any) -> bool:
    """True when two ISO 8601 UTC strings denote the same instant (PRD §2.4)."""
    if actual is None or expected is None:
        return actual is None and expected is None
    return parse_instant(actual) == parse_instant(expected)


# ─── Shared shape helpers ──────────────────────────────────────────────────

def assert_common_fields(data: Dict[str, Any]) -> None:
    """id (bare UUID), created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC with three fractional digits, "
        f"got {data.get('created_at')!r}")
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer beginning at 1, got {data.get('version')!r}")


def assert_append_only_fields(data: Dict[str, Any]) -> None:
    """An append-only evidence row carries only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}")
    assert "updated_at" not in data or data["updated_at"] is None, (
        "an append-only evidence row must not carry updated_at")
    assert "version" not in data or data["version"] is None, (
        "an append-only evidence row must not carry version")


def assert_no_type_prefix(identifier: str) -> None:
    """An id is the bare UUID string and nothing else."""
    assert is_valid_uuid(identifier), f"identifier must be a bare UUID, got {identifier!r}"


# ─── Per-entity assertions ─────────────────────────────────────────────────

def assert_property(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["zone_code"], str) and 1 <= len(data["zone_code"]) <= 16
    assert data["size_tier"] in ("STUDIO", "ONE_BR", "TWO_BR", "THREE_BR_PLUS")
    assert isinstance(data["owner_contact_email"], str) and data["owner_contact_email"]
    assert 0 <= data["bedroom_count"] <= 12
    assert 0 <= data["bathroom_count"] <= 12
    assert 0 <= data["bed_count"] <= 24
    assert -720 <= data["local_utc_offset_minutes"] <= 840
    assert 0 <= data["min_clean_minutes"] <= 600
    assert 1 <= data["min_skill_level"] <= 5
    assert data["owner_notify_min_cost_cents"] >= 0
    assert data["status"] in ("ACTIVE", "PAUSED", "OFFBOARDED")
    assert isinstance(data["open_issue_count"], int) and data["open_issue_count"] >= 0


def assert_cleaner(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["home_zone_code"], str) and data["home_zone_code"]
    assert isinstance(data["secondary_zone_codes"], list)
    assert len(data["secondary_zone_codes"]) <= 5
    assert data["home_zone_code"] not in data["secondary_zone_codes"]
    assert isinstance(data["accepts_cross_zone"], bool)
    assert 1 <= data["skill_level"] <= 5
    assert 1 <= data["max_daily_turnovers"] <= 6
    assert 0 <= float(data["quality_score"]) <= 100
    assert_two_decimal_places(data["quality_score"], "quality_score")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "OFFBOARDED")
    assert isinstance(data["pending_payout_cents"], int)
    assert data["completed_turnover_count"] >= 0
    assert data["decline_count"] >= 0
    assert data["strike_count"] >= 0


def assert_booking(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert_no_type_prefix(data["property_id"])
    assert isinstance(data["external_ref"], str) and data["external_ref"]
    assert isinstance(data["guest_name"], str) and data["guest_name"]
    assert is_iso8601_timestamp(data["checkin_at"])
    assert is_iso8601_timestamp(data["checkout_at"])
    assert data["checkout_at"] > data["checkin_at"], (
        "checkout_at must be strictly later than checkin_at")
    assert 1 <= data["party_size"] <= 24
    assert isinstance(data["pet_stay"], bool)
    assert data["status"] in ("SCHEDULED", "CHECKED_OUT", "CANCELLED")
    assert data["checkin_gate"] in ("OPEN", "BLOCKED", "RELEASED")
    assert data["guest_notice_code"] in (
        "NONE", "LATE_CHECKOUT_GRANTED", "EARLY_CHECKIN_LIMITED", "CHECKIN_DELAYED")
    if data.get("cleanliness_rating") is not None:
        assert 1 <= data["cleanliness_rating"] <= 5


def assert_turnover(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert_no_type_prefix(data["property_id"])
    assert_no_type_prefix(data["outgoing_booking_id"])
    assert is_iso8601_timestamp(data["window_start_at"])
    assert is_iso8601_timestamp(data["window_end_at"])
    assert isinstance(data["window_minutes"], int) and data["window_minutes"] >= 0
    assert isinstance(data["required_minutes"], int) and data["required_minutes"] >= 0
    assert data["slack_minutes"] == data["window_minutes"] - data["required_minutes"], (
        "slack_minutes must equal window_minutes less required_minutes")
    assert data["turn_type"] in ("SAME_DAY", "OVERNIGHT", "VACANT_GAP")
    assert isinstance(data["is_tight"], bool)
    assert data["is_tight"] == (data["slack_minutes"] < 45), (
        "is_tight must be true exactly when slack_minutes is strictly below 45")
    assert isinstance(data["escalation_required"], bool)
    assert data["status"] in (
        "PENDING_ASSIGNMENT", "SCHEDULED", "IN_PROGRESS", "AWAITING_VERIFICATION",
        "REWORK_REQUIRED", "ON_HOLD", "COMPLETED", "VOID")
    assert data["checklist_task_count"] >= 0
    assert data["rejected_review_count"] >= 0
    assert data["rework_round"] >= 0
    assert data["late_minutes"] >= 0
    assert data["restock_chargeback_cents"] >= 0


def assert_assignment(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert_no_type_prefix(data["turnover_id"])
    assert_no_type_prefix(data["cleaner_id"])
    assert data["sequence_no"] >= 1
    assert data["selection_mode"] in ("EXPLICIT", "SELECTOR")
    assert 0.0 <= float(data["match_score"]) <= 1.0, (
        "match_score always lies between 0 and 1 inclusive")
    assert_four_decimal_places(data["match_score"], "match_score")
    assert float(data["zone_match_factor"]) in (1.0, 0.4, 0.0)
    assert isinstance(data["assigned_by_user_id"], str) and data["assigned_by_user_id"]
    assert data["status"] in (
        "OFFERED", "ACCEPTED", "ACTIVE", "DECLINED", "REVOKED", "COMPLETED")


def assert_checklist_task(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert_no_type_prefix(data["turnover_id"])
    assert data["task_code"] in (
        "STRIP_LINENS", "BATHROOM_DEEP_CLEAN", "BED_STAGING", "SUPPLY_RESTOCK",
        "PATIO_STAGING")
    assert data["category"] in ("CLEANING", "STAGING", "RESTOCK")
    assert data["sequence_no"] in (10, 20, 30, 40, 50)
    assert isinstance(data["requires_photo"], bool)
    assert data["status"] in ("PENDING", "SUBMITTED", "VERIFIED", "REJECTED", "WAIVED")
    assert data["reject_count"] >= 0
    assert data["restock_line_count"] >= 0
    assert data["restock_charge_cents"] >= 0


def assert_supply_line(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert_no_type_prefix(data["property_id"])
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["category"] in ("LINEN", "CONSUMABLE", "WELCOME")
    assert isinstance(data["unit"], str) and data["unit"]
    assert data["unit_cost_cents"] >= 0
    assert data["par_qty"] >= 0
    assert data["reorder_point"] >= 0
    assert data["on_hand_qty"] >= 0, "on_hand_qty can never be driven below zero"
    assert isinstance(data["below_par"], bool)
    assert data["below_par"] == (data["on_hand_qty"] <= data["reorder_point"]), (
        "below_par must be true exactly when on_hand_qty is at or below reorder_point")
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_stock_movement(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert_no_type_prefix(data["supply_line_id"])
    assert data["sequence_no"] >= 1
    assert data["reason"] in ("SEED", "REPLENISH", "RESTOCK_USE", "REVERSAL")
    assert isinstance(data["delta_qty"], int)
    assert isinstance(data["unit_cost_cents_at_time"], int)
    assert isinstance(data["charge_cents"], int)


def assert_issue_report(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert_no_type_prefix(data["turnover_id"])
    assert_no_type_prefix(data["property_id"])
    assert data["issue_type"] in (
        "DAMAGE", "MAINTENANCE", "SAFETY", "CONSUMABLE_SHORTAGE")
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert isinstance(data["description"], str) and data["description"]
    assert data["estimated_cost_cents"] >= 0
    assert isinstance(data["guest_chargeable"], bool)
    assert data["status"] in ("REPORTED", "OWNER_NOTIFIED", "DISPATCHED", "RESOLVED")


def assert_repair_order(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert_no_type_prefix(data["issue_report_id"])
    assert_no_type_prefix(data["property_id"])
    assert isinstance(data["vendor_name"], str) and data["vendor_name"]
    assert is_iso8601_timestamp(data["scheduled_at"])
    assert isinstance(data["blocks_checkin"], bool)
    assert data["status"] in ("DISPATCHED", "COMPLETED")


def assert_quality_audit(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert_no_type_prefix(data["turnover_id"])
    assert_no_type_prefix(data["cleaner_id"])
    assert isinstance(data["auditor_user_id"], str) and data["auditor_user_id"]
    assert 0 <= data["score"] <= 100
    assert data["status"] in ("SAMPLED", "FINALIZED", "VOIDED")
    if data.get("variant_applied") is not None:
        assert data["variant_applied"] in ("BLENDED", "AUDIT_ONLY")
    if data.get("observed_score") is not None:
        assert_two_decimal_places(data["observed_score"], "observed_score")
    if data.get("resulting_quality_score") is not None:
        assert_two_decimal_places(
            data["resulting_quality_score"], "resulting_quality_score")


def assert_pay_line(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert_no_type_prefix(data["assignment_id"])
    assert_no_type_prefix(data["cleaner_id"])
    assert_no_type_prefix(data["turnover_id"])
    assert data["variant"] in ("PROVISIONAL", "FINAL")
    assert data["status"] in ("PROVISIONAL", "FINAL", "ADJUSTED", "VOIDED")
    assert_pay_line_arithmetic(data)


# ─── Domain invariant checkers ─────────────────────────────────────────────

def assert_integer_cents(value: Any, field_name: str = "amount") -> None:
    """All monetary amounts in this system are integer cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field_name} must be integer cents, got {value!r}")


def assert_two_decimal_places(value: Any, field_name: str = "value") -> None:
    """quality_score, observed_score and resulting_quality_score carry two decimals."""
    assert round(float(value), 2) == float(value), (
        f"{field_name} must carry two decimal places, got {value!r}")


def assert_four_decimal_places(value: Any, field_name: str = "value") -> None:
    """match_score carries four decimal places."""
    assert round(float(value), 4) == float(value), (
        f"{field_name} must carry four decimal places, got {value!r}")


def assert_pay_line_arithmetic(pay: Dict[str, Any]) -> None:
    """The seven-step pay calculation must reconcile inside the row itself."""
    for field in ("size_base_cents", "rush_premium_cents", "tight_window_premium_cents",
                  "cross_zone_premium_cents", "linen_adder_cents", "gross_cents",
                  "late_penalty_cents", "photo_penalty_cents", "penalty_cents",
                  "on_time_bonus_cents", "photo_pass_bonus_cents", "bonus_cents",
                  "audit_adjustment_cents", "net_cents"):
        assert_integer_cents(pay[field], field)
    expected_gross = (pay["size_base_cents"] + pay["rush_premium_cents"]
                      + pay["tight_window_premium_cents"]
                      + pay["cross_zone_premium_cents"] + pay["linen_adder_cents"])
    assert pay["gross_cents"] == expected_gross, (
        f"gross_cents must be the base plus the three premiums plus the linen adder: "
        f"expected {expected_gross}, got {pay['gross_cents']}")
    assert pay["penalty_cents"] == pay["late_penalty_cents"] + pay["photo_penalty_cents"], (
        "penalty_cents must be late_penalty_cents plus photo_penalty_cents")
    assert pay["bonus_cents"] == pay["on_time_bonus_cents"] + pay["photo_pass_bonus_cents"], (
        "bonus_cents must be on_time_bonus_cents plus photo_pass_bonus_cents")
    expected_net = (pay["gross_cents"] + pay["bonus_cents"] - pay["penalty_cents"]
                    + pay["audit_adjustment_cents"])
    assert pay["net_cents"] == expected_net, (
        f"net_cents must be gross plus bonuses less penalties plus the audit "
        f"adjustment: expected {expected_net}, got {pay['net_cents']}")
    assert pay["photo_penalty_cents"] <= 900, (
        "the photo penalty saturates at an absolute ceiling of 900 cents")


def assert_payout_ledger_conserved(cleaner: Dict[str, Any],
                                   pay_lines: List[Dict[str, Any]]) -> None:
    """pending_payout_cents is the sum of net_cents over PROVISIONAL, FINAL and
    ADJUSTED pay lines; VOIDED lines are excluded but retained."""
    expected = sum(p["net_cents"] for p in pay_lines
                   if p["status"] in ("PROVISIONAL", "FINAL", "ADJUSTED"))
    assert cleaner["pending_payout_cents"] == expected, (
        f"pending_payout_cents must equal the sum of net_cents over PROVISIONAL, "
        f"FINAL and ADJUSTED pay lines: expected {expected}, "
        f"got {cleaner['pending_payout_cents']}")


def assert_on_hand_is_ledger_sum(supply_line: Dict[str, Any],
                                 movements: List[Dict[str, Any]]) -> None:
    """on_hand_qty is a pure projection over the append-only ledger."""
    expected = sum(m["delta_qty"] for m in movements)
    assert supply_line["on_hand_qty"] == expected, (
        f"on_hand_qty must equal the summed delta_qty of its movements: "
        f"expected {expected}, got {supply_line['on_hand_qty']}")
    assert supply_line["below_par"] == (
        supply_line["on_hand_qty"] <= supply_line["reorder_point"]), (
        "below_par must be recomputed from the refreshed projection")


def assert_sequence_numbers_monotonic(movements: List[Dict[str, Any]]) -> None:
    """Within one supply line, sequence_no is a 1-based monotonic counter."""
    seqs = [m["sequence_no"] for m in movements]
    assert seqs == list(range(1, len(seqs) + 1)), (
        f"sequence_no must be a 1-based monotonic counter, got {seqs}")


def assert_envelope_is_error(response) -> None:
    """The error envelope carries only error_id and message under data."""
    body = response.json()
    assert body["response_type"] == "error", "an error response_type must be 'error'"
    assert set(body["data"].keys()) <= {"error_id", "message"}, (
        f"an error body must carry only error_id and message, "
        f"got {sorted(body['data'].keys())}")
    assert body["meta"]["api_request_id"].startswith("req_"), (
        "api_request_id must start with req_")
