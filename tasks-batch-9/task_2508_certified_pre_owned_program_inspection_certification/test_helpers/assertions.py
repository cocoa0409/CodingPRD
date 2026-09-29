"""Entity shape assertions, invariant checkers and rounding helpers.

Every rule asserted here is one the PRD states in §2 or §3. Nothing infers a
field the PRD does not name.
"""

import math
import re
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    AUDIT_SAMPLE_STATUSES,
    CERTIFICATION_STATUSES,
    CLAIM_RATIO_VARIANTS,
    CLAIM_STATUSES,
    COMPLAINT_CATEGORIES,
    COMPLAINT_STATUSES,
    COMPONENT_CATEGORIES,
    CPO_STATES,
    DECERTIFICATION_REASONS,
    INSPECTION_PURPOSES,
    INSPECTION_STATUSES,
    INVENTORY_STATES,
    ITEM_CATEGORIES,
    ITEM_SEVERITIES,
    LISTING_CHANNELS,
    LISTING_STATUSES,
    PRIOR_USES,
    PRIVILEGE_REASONS,
    PRIVILEGE_STATUSES,
    RECONDITIONING_STATUSES,
    RESULT_OUTCOMES,
    TEMPLATE_STATUSES,
    TITLE_BRANDS,
    WARRANTY_ANCHOR_VARIANTS,
    WITHDRAWAL_REASONS,
)

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ───────────────────────── instants and dates ────────────────────────

def normalize_instant(value: str) -> datetime:
    """Parse an emitted ISO 8601 UTC instant, with or without fractional digits."""
    assert isinstance(value, str), f"expected an instant string, got {value!r}"
    cleaned = value.replace("Z", "+00:00")
    return datetime.fromisoformat(cleaned).astimezone(timezone.utc)


def assert_instant_equals(actual: Optional[str], expected: str, label: str = "instant") -> None:
    """Compare two instants by value, tolerating the emitted fractional digits."""
    assert actual is not None, f"{label} must be set, got null"
    assert normalize_instant(actual) == normalize_instant(expected), (
        f"{label} must be {expected}, got {actual}"
    )


def assert_millisecond_timestamp(value: str) -> None:
    """§2.4: every emitted instant is ISO 8601 UTC with exactly three fractional digits."""
    assert isinstance(value, str), f"expected a timestamp string, got {value!r}"
    assert is_iso8601_timestamp(value), f"not a valid ISO 8601 UTC instant: {value!r}"
    assert value.endswith("Z"), f"timestamp must end in Z: {value!r}"
    assert len(value) == 24 and value[19] == ".", (
        f"timestamp must carry exactly three fractional digits: {value!r}"
    )


def assert_calendar_date(value: str, label: str = "date") -> None:
    """§3.7: `warranty_start_date` and `warranty_end_date` are dates in YYYY-MM-DD form."""
    assert isinstance(value, str) and DATE_RE.match(value), (
        f"{label} must be a YYYY-MM-DD date, got {value!r}"
    )


def iso_shift(base_iso: str, days: int = 0, hours: int = 0, minutes: int = 0, seconds: int = 0) -> str:
    """Return `base_iso` moved by the given offset, formatted as ISO 8601 UTC."""
    moment = normalize_instant(base_iso) + timedelta(
        days=days, hours=hours, minutes=minutes, seconds=seconds
    )
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def date_shift(base_date: str, days: int) -> str:
    """Return `base_date` (YYYY-MM-DD) moved by whole days."""
    parsed = date.fromisoformat(base_date)
    return (parsed + timedelta(days=days)).isoformat()


def days_between(earlier_date: str, later_date: str) -> int:
    """The whole number of days between two YYYY-MM-DD calendar dates."""
    return (date.fromisoformat(later_date) - date.fromisoformat(earlier_date)).days


# ─────────────────────── rounding disciplines (§2.9) ─────────────────

def round_half_up(value) -> int:
    """§2.9: round half up to a whole number."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value) -> float:
    """§2.9: a ratio field is rounded to exactly 2 decimals using round half up."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def floor_cents(value) -> int:
    """§2.9: the certification fee floors on every division and percentage.

    §2.9 demands exact decimal arithmetic ("no intermediate rounding to
    dollars"), so the value is quantized to nine decimal places before it is
    floored. Without that step a binary-float artefact defeats the rule the PRD
    states: `89900 * 0.35` evaluates to `31464.999999999996` in float, which
    would floor to 31464 rather than the exact 31465 §3.7's surcharge cap is.
    """
    quantized = Decimal(str(value)).quantize(
        Decimal("1E-9"), rounding=ROUND_HALF_UP
    )
    return int(quantized.to_integral_value(rounding=ROUND_FLOOR))


def ceil_count(value) -> int:
    """§2.9: the audit sample count uses ceiling."""
    return math.ceil(value)


def reimbursable_for(actual_cost_cents: int, item_cap_cents: int, share: float = 0.6) -> int:
    """§3.5: round the share half up to whole cents, then take the smaller of that and the point's ceiling."""
    return min(round_half_up(actual_cost_cents * share), item_cap_cents)


# ─────────────────────── shared structural helpers ───────────────────

def assert_common_fields(data: dict) -> None:
    """§2.4: a mutable resource exposes id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a bare UUID, got {data.get('id')!r}"
    )
    assert_millisecond_timestamp(data.get("created_at", ""))
    assert_millisecond_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"


def assert_append_only_row(data: dict) -> None:
    """§2.4: checklist items, inspection results and certification documents carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a bare UUID, got {data.get('id')!r}"
    )
    assert_millisecond_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, (
        f"an append-only row exposes no updated_at, got {data.get('updated_at')!r}"
    )
    assert "version" not in data, (
        f"an append-only row exposes no version, got {data.get('version')!r}"
    )


def assert_error_envelope(body: dict) -> None:
    """§2.2: an error body carries meta with exactly the two request fields, response_type error, and data of error_id plus message."""
    assert body.get("response_type") == "error", (
        f"response_type must be 'error', got {body.get('response_type')!r}"
    )
    meta = body.get("meta") or {}
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"], (
        "meta.api_request_id must be a non-empty string"
    )
    assert isinstance(meta.get("api_request_timestamp"), str), (
        "meta.api_request_timestamp must be a string"
    )
    for pagination_field in ("limit", "offset", "total_count", "has_more"):
        assert pagination_field not in meta, (
            f"an error envelope's meta carries no {pagination_field}"
        )
    error_data = body.get("data") or {}
    assert set(error_data.keys()) == {"error_id", "message"}, (
        f"error data holds exactly error_id and message, got {sorted(error_data.keys())}"
    )
    assert isinstance(error_data["error_id"], str) and error_data["error_id"]
    assert isinstance(error_data["message"], str) and error_data["message"].strip()


def assert_ratio_two_decimals(value, label: str = "ratio") -> None:
    """§2.9: the claim ratio and the audit failure rate are decimals at exactly 2 places."""
    assert isinstance(value, (int, float)), f"{label} must be numeric, got {value!r}"
    assert round(float(value), 2) == float(value), (
        f"{label} must be rounded to 2 decimal places, got {value!r}"
    )


# ─────────────────────────── entity shapes ───────────────────────────

def assert_program_config(data: dict) -> None:
    assert_common_fields(data)
    assert int(data["max_age_days"]) >= 1
    assert int(data["max_odometer_miles"]) >= 1
    assert isinstance(data["ineligible_title_brands"], list)
    assert "CLEAN" not in data["ineligible_title_brands"], (
        "CLEAN is never an ineligible title brand"
    )
    assert isinstance(data["ineligible_prior_uses"], list)
    assert isinstance(data["volume_discount_tiers"], list)
    for tier in data["volume_discount_tiers"]:
        assert "min_count" in tier and "pct" in tier, (
            f"a discount tier is a min_count/pct pair, got {tier!r}"
        )
    assert isinstance(data["required_doc_types"], list)
    assert isinstance(data["listing_required_disclosure_fields"], list)


def assert_dealer(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["franchise_code"], str) and data["franchise_code"]
    assert isinstance(data["region_code"], str)
    assert data["privilege_status"] in PRIVILEGE_STATUSES, (
        f"privilege_status must be declared, got {data['privilege_status']!r}"
    )
    assert data["privilege_reason"] in PRIVILEGE_REASONS, (
        f"privilege_reason must be declared, got {data['privilege_reason']!r}"
    )
    assert data["claim_ratio_variant"] in CLAIM_RATIO_VARIANTS
    for counter in (
        "lifetime_submitted_count",
        "lifetime_activated_count",
        "window_activated_count",
        "active_certification_count",
        "approved_claim_count_lifetime",
        "approved_claim_count_window",
        "audit_sample_count",
        "audit_fail_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"{counter} must be a non-negative integer, got {data[counter]!r}"
        )
    assert_ratio_two_decimals(data["claim_ratio_effective"], "claim_ratio_effective")
    assert_ratio_two_decimals(data["audit_fail_rate"], "audit_fail_rate")
    assert isinstance(data["risk_score"], int) and 0 <= data["risk_score"] <= 100, (
        f"risk_score is an integer from 0 through 100, got {data['risk_score']!r}"
    )
    assert_dealer_ledger_conservation(data)


def assert_dealer_ledger_conservation(dealer: dict) -> None:
    """§3.2: `fee_balance_cents` is the billed total minus the credited total, and the two totals must always reconcile to it."""
    billed = dealer["fee_billed_cents_total"]
    credited = dealer["fee_credited_cents_total"]
    balance = dealer["fee_balance_cents"]
    assert billed >= 0 and credited >= 0, "fee ledger totals are never negative"
    assert balance == billed - credited, (
        f"fee_balance_cents must equal {billed} - {credited} = {billed - credited}, got {balance}"
    )


def assert_technician(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["dealer_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["credential_id"], str) and data["credential_id"]
    assert_millisecond_timestamp(data["credential_expires_at"])
    assert data["credential_status"] in ("ACTIVE", "REVOKED")
    assert isinstance(data["completed_inspection_count"], int)
    assert data["completed_inspection_count"] >= 0


def assert_vehicle(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["vin"], str) and len(data["vin"]) == 17, (
        f"vin is exactly 17 characters, got {data['vin']!r}"
    )
    assert isinstance(data["model_year"], int)
    assert_calendar_date(data["in_service_date"], "in_service_date")
    assert isinstance(data["odometer_miles"], int) and data["odometer_miles"] >= 0
    assert data["title_brand"] in TITLE_BRANDS
    assert data["prior_use"] in PRIOR_USES
    assert isinstance(data["owner_count"], int)
    assert data["cpo_state"] in CPO_STATES
    assert data["inventory_state"] in INVENTORY_STATES
    assert_vehicle_slot_invariant(data)


def assert_vehicle_slot_invariant(vehicle: dict) -> None:
    """§3.2: `active_certification_count` is the conserved slot quantity and never exceeds 1."""
    count = vehicle["active_certification_count"]
    assert isinstance(count, int) and 0 <= count <= 1, (
        f"a vehicle's active_certification_count never exceeds 1, got {count}"
    )
    if count == 0:
        assert vehicle["certified_certification_id"] is None or vehicle["cpo_state"] != "CERTIFIED", (
            "with no live certification the derived pointer cannot name a CERTIFIED row"
        )


def assert_checklist_template(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert_calendar_date(data["effective_from"], "effective_from")
    assert data["status"] in TEMPLATE_STATUSES
    assert isinstance(data["point_count"], int) and data["point_count"] >= 0
    assert isinstance(data["critical_item_count"], int)
    assert data["critical_item_count"] <= data["point_count"], (
        "critical_item_count counts a subset of the template's points"
    )
    if data["status"] == "DRAFT":
        assert data["published_at"] is None, "a DRAFT template has published_at null"


def assert_checklist_item(data: dict) -> None:
    assert_append_only_row(data)
    assert is_valid_uuid(data["template_id"])
    assert isinstance(data["item_code"], str) and data["item_code"]
    assert data["category"] in ITEM_CATEGORIES
    assert data["severity"] in ITEM_SEVERITIES
    assert isinstance(data["pass_criteria"], str) and data["pass_criteria"]
    assert isinstance(data["reconditioning_allowed"], bool)
    assert isinstance(data["max_reconditioning_cost_cents"], int)


def assert_inspection(data: dict) -> None:
    assert_common_fields(data)
    for edge in ("dealer_id", "vehicle_id", "technician_id", "template_id"):
        assert is_valid_uuid(data[edge]), f"{edge} must be a UUID, got {data[edge]!r}"
    assert data["purpose"] in INSPECTION_PURPOSES
    assert data["status"] in INSPECTION_STATUSES
    assert_millisecond_timestamp(data["started_at"])
    assert_millisecond_timestamp(data["slot_end_at"])
    assert isinstance(data["odometer_at_inspection"], int)
    assert isinstance(data["vehicle_age_days_at_inspection"], int)
    for counter in (
        "attempt_count",
        "recorded_item_count",
        "failed_critical_count",
        "failed_recon_count",
        "total_recon_cost_cents",
        "total_reimbursable_cents",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"{counter} must be a non-negative integer, got {data[counter]!r}"
        )


def assert_inspection_result(data: dict) -> None:
    assert_append_only_row(data)
    assert is_valid_uuid(data["inspection_id"])
    assert isinstance(data["attempt_index"], int) and data["attempt_index"] >= 1
    assert isinstance(data["item_code"], str)
    assert data["outcome"] in RESULT_OUTCOMES
    assert is_valid_uuid(data["recorded_by_technician_id"])
    assert_millisecond_timestamp(data["recorded_at"])


def assert_reconditioning_item(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["inspection_id"])
    assert isinstance(data["item_code"], str)
    assert data["severity"] in ITEM_SEVERITIES
    assert data["status"] in RECONDITIONING_STATUSES
    assert isinstance(data["reimbursable_cents"], int)
    assert data["reimbursable_cents"] >= 0
    if data["status"] == "REQUIRED":
        assert data["actual_cost_cents"] is None, (
            "an open repair keeps actual_cost_cents null"
        )
        assert data["reimbursable_cents"] == 0
        assert data["completed_at"] is None
        assert data["closed_by_user_id"] is None
    if data["status"] == "WAIVED":
        assert data["actual_cost_cents"] is None, (
            "§3.5: a waived item keeps actual_cost_cents null"
        )
        assert data["reimbursable_cents"] == 0, (
            "§3.5: a waived item keeps reimbursable_cents 0"
        )


def assert_certification(data: dict) -> None:
    assert_common_fields(data)
    for edge in ("dealer_id", "vehicle_id", "inspection_id"):
        assert is_valid_uuid(data[edge]), f"{edge} must be a UUID, got {data[edge]!r}"
    assert data["status"] in CERTIFICATION_STATUSES
    assert isinstance(data["certification_number"], str) and data["certification_number"]
    assert data["certification_number"].startswith("CPO-"), (
        f"§3.6: the label is built as the literal prefix CPO-, got {data['certification_number']!r}"
    )
    assert_millisecond_timestamp(data["submitted_at"])
    assert data["decertification_reason"] in DECERTIFICATION_REASONS
    assert isinstance(data["audit_sampled"], bool)
    for money in (
        "fee_surcharge_cents",
        "fee_discount_cents",
        "fee_charged_cents",
        "fee_credited_cents",
        "approved_claim_amount_cents",
    ):
        assert isinstance(data[money], int) and data[money] >= 0, (
            f"{money} must be a non-negative whole number of cents, got {data[money]!r}"
        )
    if data["warranty_anchor_variant"] is not None:
        assert data["warranty_anchor_variant"] in WARRANTY_ANCHOR_VARIANTS
    if data["status"] == "SUBMITTED":
        assert data["activated_at"] is None, (
            "§3.6: a newly submitted certification has activated_at null"
        )
        assert data["program_config_version"] is None, (
            "§3.6: a newly submitted certification pins no configuration generation"
        )


def assert_certification_number(number: str, franchise_code: str, sequence: int) -> None:
    """§3.6: `CPO-` then the franchise code, a hyphen, then the sequence zero-padded to four digits."""
    expected = f"CPO-{franchise_code}-{sequence:04d}"
    assert number == expected, f"certification_number must be {expected}, got {number}"


def assert_certification_document(data: dict) -> None:
    assert_append_only_row(data)
    assert is_valid_uuid(data["certification_id"])
    assert isinstance(data["doc_type"], str)
    assert isinstance(data["reference"], str)
    assert_millisecond_timestamp(data["uploaded_at"])


def assert_audit_sample(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["certification_id"])
    assert isinstance(data["audit_run_id"], str) and data["audit_run_id"].startswith("AR-"), (
        f"§3.10: the run label is AR- followed by the run count, got {data['audit_run_id']!r}"
    )
    assert isinstance(data["selection_rank"], int) and data["selection_rank"] >= 1
    assert data["status"] in AUDIT_SAMPLE_STATUSES


def assert_audit_run_summary(data: dict) -> None:
    """§3.10: the run returns audit_run_id, pool_size, selected_count and selected_certification_ids."""
    assert isinstance(data["audit_run_id"], str) and data["audit_run_id"].startswith("AR-")
    assert isinstance(data["pool_size"], int) and data["pool_size"] >= 0
    assert isinstance(data["selected_count"], int) and data["selected_count"] >= 0
    assert isinstance(data["selected_certification_ids"], list)
    assert data["selected_count"] == len(data["selected_certification_ids"]), (
        "selected_count must match the length of selected_certification_ids"
    )
    assert data["selected_count"] <= data["pool_size"], (
        "§3.10: the number drawn is the smaller of the pool size and the sampling figure"
    )


def assert_warranty_claim(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["certification_id"])
    assert data["component_category"] in COMPONENT_CATEGORIES
    assert_calendar_date(data["repair_date"], "repair_date")
    assert isinstance(data["repair_odometer_miles"], int)
    assert isinstance(data["claimed_amount_cents"], int) and data["claimed_amount_cents"] >= 1
    assert isinstance(data["approved_amount_cents"], int)
    assert data["status"] in CLAIM_STATUSES
    if data["status"] == "SUBMITTED":
        assert data["approved_amount_cents"] == 0, (
            "§3.9: a new claim is created with approved_amount_cents 0"
        )
        assert data["dealer_ratio_snapshot_before"] is None
        assert data["adjudicated_at"] is None


def assert_listing(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["certification_id"])
    assert data["channel"] in LISTING_CHANNELS
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 1
    assert isinstance(data["disclosure_fields"], list)
    assert data["status"] in LISTING_STATUSES
    if data["withdrawal_reason"] is not None:
        assert data["withdrawal_reason"] in WITHDRAWAL_REASONS
    if data["status"] == "DRAFT":
        assert data["syndicated_at"] is None, "§3.8: a new listing begins with syndicated_at null"
        assert data["syndicated_snapshot_version"] is None
        assert data["withdrawn_at"] is None
        assert data["withdrawal_reason"] is None
        assert data["removal_due_at"] is None


def assert_complaint(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["certification_id"])
    assert isinstance(data["customer_reference"], str)
    assert data["category"] in COMPLAINT_CATEGORIES
    assert isinstance(data["description"], str)
    assert data["status"] in COMPLAINT_STATUSES
    assert_millisecond_timestamp(data["filed_at"])
    assert_millisecond_timestamp(data["reinspection_deadline_at"])


# ─────────────────── pagination and collection helpers ───────────────

def assert_pagination_meta(meta: dict, limit: int, offset: int, total_count: int, has_more: bool) -> None:
    """§2.3: the four pagination fields report the applied page and the pre-pagination total."""
    assert meta["limit"] == limit, f"meta.limit must be {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"meta.offset must be {offset}, got {meta['offset']}"
    assert meta["total_count"] == total_count, (
        f"meta.total_count must be {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"meta.has_more must be {has_more}, got {meta['has_more']}"
    )


def assert_created_at_ascending(rows: list) -> None:
    """§2.3: unless a listing states otherwise, results are ordered by created_at ascending."""
    stamps = [normalize_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), "a listing must be ordered by created_at ascending"


def ids_of(rows: list) -> list:
    return [row["id"] for row in rows]
