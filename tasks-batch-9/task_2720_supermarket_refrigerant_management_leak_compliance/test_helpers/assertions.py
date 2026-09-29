"""
Domain assertions for the Supermarket Refrigerant Leak Compliance API.

Timestamps are compared through `assert_instant`, which parses both sides and
compares the instants they denote, so an implementation that renders
`2026-08-01T00:00:00Z` and one that renders `2026-08-01T00:00:00.000Z` both pass
while a genuinely different instant still fails.

Masses, percentages and scores are compared at one decimal place and money at
two, matching the rounding rules of §2.6.
"""

import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import is_valid_uuid

from .constants import (
    API_REQUEST_ID_PREFIX,
    MULTIPLIER_AT_RISK,
    MULTIPLIER_COMPLIANT,
    MULTIPLIER_NON_COMPLIANT,
    RESPONSE_TYPE_ARRAY,
    RESPONSE_TYPE_ERROR,
    RESPONSE_TYPE_OBJECT,
)

_META_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


# ─── Instants ─────────────────────────────────────────────────────────


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating any fractional-second width."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant(actual: Any, expected: str, label: str = "timestamp") -> None:
    """Assert that `actual` denotes the same instant as `expected`."""
    assert actual is not None, f"{label} is missing"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_instant_is_none(actual: Any, label: str = "timestamp") -> None:
    assert actual is None, f"{label}: expected null, got {actual!r}"


# ─── Envelope (§2.2) ──────────────────────────────────────────────────


def assert_meta(body: Dict[str, Any]) -> None:
    """`meta.api_request_id` starts `req_`; the timestamp has three fractionals."""
    meta = body["meta"]
    assert meta["api_request_id"].startswith(API_REQUEST_ID_PREFIX), (
        f"api_request_id must start with '{API_REQUEST_ID_PREFIX}', "
        f"got {meta['api_request_id']!r}"
    )
    assert _META_TIMESTAMP_RE.match(meta["api_request_timestamp"]), (
        "api_request_timestamp must be ISO 8601 UTC with three fractional digits, "
        f"got {meta['api_request_timestamp']!r}"
    )


def assert_object_envelope(response) -> Dict[str, Any]:
    """A single-resource response: `response_type` object, `data` an object."""
    body = response.json()
    assert_meta(body)
    assert body["response_type"] == RESPONSE_TYPE_OBJECT, (
        f"expected response_type 'object', got {body['response_type']!r}"
    )
    assert isinstance(body["data"], dict), "object responses carry an object in data"
    return body


def assert_array_envelope(response) -> Dict[str, Any]:
    """A collection response: `response_type` array, `data` a list, `meta` paged."""
    body = response.json()
    assert_meta(body)
    assert body["response_type"] == RESPONSE_TYPE_ARRAY, (
        f"expected response_type 'array', got {body['response_type']!r}"
    )
    assert isinstance(body["data"], list), "array responses carry a list in data"
    for key in ("total_count", "limit", "offset"):
        assert key in body["meta"], f"paginated meta must carry {key}"
    return body


def assert_error_envelope(response) -> Dict[str, Any]:
    """An error response: `response_type` error, `data` carrying id and message."""
    body = response.json()
    assert_meta(body)
    assert body["response_type"] == RESPONSE_TYPE_ERROR, (
        f"expected response_type 'error', got {body['response_type']!r}"
    )
    assert "error_id" in body["data"], "error data must carry error_id"
    assert isinstance(body["data"].get("message"), str), (
        "error data must carry a human-readable message"
    )
    assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta carries only the two request fields, got {sorted(body['meta'])}"
    )
    return body


# ─── Common fields (§2.5) ─────────────────────────────────────────────


def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """`id`, `created_at`, `updated_at` and a `version` that starts at 1."""
    assert is_valid_uuid(entity["id"]), f"id must be a UUID, got {entity['id']!r}"
    parse_instant(entity["created_at"])
    parse_instant(entity["updated_at"])
    assert isinstance(entity["version"], int), "version must be an integer"
    assert entity["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_append_only_fields(entity: Dict[str, Any]) -> None:
    """
    An append-only evidence row carries `id` and `created_at` and neither
    `updated_at` nor `version` (§2.5).
    """
    assert is_valid_uuid(entity["id"]), f"id must be a UUID, got {entity['id']!r}"
    parse_instant(entity["created_at"])
    assert "updated_at" not in entity, "an append-only row carries no updated_at"
    assert "version" not in entity, "an append-only row carries no version"


# ─── Precision (§2.6) ─────────────────────────────────────────────────


def assert_mass(actual: Any, expected: float, label: str = "mass") -> None:
    """A mass or percentage carried to one decimal place."""
    assert actual is not None, f"{label} is missing"
    assert round(float(actual), 1) == round(float(expected), 1), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_money(actual: Any, expected: float, label: str = "amount") -> None:
    """A monetary amount carried to two decimal places."""
    assert actual is not None, f"{label} is missing"
    assert round(float(actual), 2) == round(float(expected), 2), (
        f"{label}: expected {expected:.2f}, got {actual}"
    )


def assert_score(actual: Any, expected: float, label: str = "score") -> None:
    """A compatibility score or percentage carried to one decimal place."""
    assert_mass(actual, expected, label)


# ─── Store posture (§3.1) ─────────────────────────────────────────────


def assert_store_posture(
    store: Dict[str, Any],
    compliance_status: Optional[str] = None,
    open_leak_event_count: Optional[int] = None,
    overdue_leak_event_count: Optional[int] = None,
    mandated_retrofit_count: Optional[int] = None,
    chronic_leaker_flag: Optional[bool] = None,
    regulated_system_count: Optional[int] = None,
    total_regulated_charge_lbs: Optional[float] = None,
    vented_loss_lbs: Optional[float] = None,
    penalty_exposure_total_usd: Optional[float] = None,
) -> None:
    """Assert whichever posture fields the caller names, and only those."""
    if compliance_status is not None:
        assert store["compliance_status"] == compliance_status, (
            f"compliance_status: expected {compliance_status}, got {store['compliance_status']}"
        )
    if open_leak_event_count is not None:
        assert store["open_leak_event_count"] == open_leak_event_count, (
            f"open_leak_event_count: expected {open_leak_event_count}, "
            f"got {store['open_leak_event_count']}"
        )
    if overdue_leak_event_count is not None:
        assert store["overdue_leak_event_count"] == overdue_leak_event_count, (
            f"overdue_leak_event_count: expected {overdue_leak_event_count}, "
            f"got {store['overdue_leak_event_count']}"
        )
    if mandated_retrofit_count is not None:
        assert store["mandated_retrofit_count"] == mandated_retrofit_count, (
            f"mandated_retrofit_count: expected {mandated_retrofit_count}, "
            f"got {store['mandated_retrofit_count']}"
        )
    if chronic_leaker_flag is not None:
        assert store["chronic_leaker_flag"] is chronic_leaker_flag, (
            f"chronic_leaker_flag: expected {chronic_leaker_flag}, "
            f"got {store['chronic_leaker_flag']}"
        )
    if regulated_system_count is not None:
        assert store["regulated_system_count"] == regulated_system_count, (
            f"regulated_system_count: expected {regulated_system_count}, "
            f"got {store['regulated_system_count']}"
        )
    if total_regulated_charge_lbs is not None:
        assert_mass(
            store["total_regulated_charge_lbs"],
            total_regulated_charge_lbs,
            "total_regulated_charge_lbs",
        )
    if vented_loss_lbs is not None:
        assert_mass(store["vented_loss_lbs"], vented_loss_lbs, "vented_loss_lbs")
    if penalty_exposure_total_usd is not None:
        assert_money(
            store["penalty_exposure_total_usd"],
            penalty_exposure_total_usd,
            "penalty_exposure_total_usd",
        )


# ─── Systems (§3.1, §3.9) ─────────────────────────────────────────────


def assert_system_axes(
    system: Dict[str, Any],
    operational_status: Optional[str] = None,
    compliance_state: Optional[str] = None,
) -> None:
    """The two independent state axes of a refrigeration system."""
    if operational_status is not None:
        assert system["operational_status"] == operational_status, (
            f"operational_status: expected {operational_status}, "
            f"got {system['operational_status']}"
        )
    if compliance_state is not None:
        assert system["compliance_state"] == compliance_state, (
            f"compliance_state: expected {compliance_state}, got {system['compliance_state']}"
        )


def assert_system_charge(
    system: Dict[str, Any],
    current_charge_lbs: Optional[float] = None,
    leak_rate_pct: Optional[float] = None,
    exceedance_count_12mo: Optional[int] = None,
) -> None:
    if current_charge_lbs is not None:
        assert_mass(system["current_charge_lbs"], current_charge_lbs, "current_charge_lbs")
    if leak_rate_pct is not None:
        assert_mass(system["leak_rate_pct"], leak_rate_pct, "leak_rate_pct")
    if exceedance_count_12mo is not None:
        assert system["exceedance_count_12mo"] == exceedance_count_12mo, (
            f"exceedance_count_12mo: expected {exceedance_count_12mo}, "
            f"got {system['exceedance_count_12mo']}"
        )


def assert_untouched(before: Dict[str, Any], after: Dict[str, Any], *fields: str) -> None:
    """
    Assert that a rejected write left the named fields exactly as they were,
    version included, which is what "nothing was written" means observably.
    """
    checked = fields or ("version",)
    for field in checked:
        assert after[field] == before[field], (
            f"{field} changed from {before[field]!r} to {after[field]!r} on a rejected write"
        )


# ─── Mass conservation (§2.7) ─────────────────────────────────────────


def total_refrigerant_mass(
    systems: Iterable[Dict[str, Any]],
    cylinders: Iterable[Dict[str, Any]],
    store: Dict[str, Any],
) -> float:
    """
    The store's four buckets: system charge, cylinder contents, refrigerant
    shipped for reclaim, and vented loss.
    """
    total = 0.0
    for system in systems:
        total += float(system["current_charge_lbs"])
    for cylinder in cylinders:
        total += float(cylinder["current_contents_lbs"])
        total += float(cylinder["shipped_for_reclaim_lbs"])
    total += float(store["vented_loss_lbs"])
    return round(total, 1)


def assert_mass_conserved(
    systems: Iterable[Dict[str, Any]],
    cylinders: Iterable[Dict[str, Any]],
    store: Dict[str, Any],
    expected_total_lbs: float,
) -> None:
    total = total_refrigerant_mass(systems, cylinders, store)
    assert_mass(total, expected_total_lbs, "total refrigerant mass across the four buckets")


# ─── Leak events (§3.5, §3.6) ─────────────────────────────────────────


def assert_leak_event_schedule(
    event: Dict[str, Any],
    initial_repair_deadline: Optional[str] = None,
    repair_deadline: Optional[str] = None,
    verification_deadline: Optional[str] = None,
) -> None:
    if initial_repair_deadline is not None:
        assert_instant(
            event["initial_repair_deadline"], initial_repair_deadline, "initial_repair_deadline"
        )
    if repair_deadline is not None:
        assert_instant(event["repair_deadline"], repair_deadline, "repair_deadline")
    if verification_deadline is not None:
        assert_instant(
            event["verification_deadline"], verification_deadline, "verification_deadline"
        )


def assert_extension_budget(
    event: Dict[str, Any], granted_total: int, remaining: int
) -> None:
    """The two counters must both match and must still sum to the statutory 30."""
    assert event["extension_days_granted_total"] == granted_total, (
        f"extension_days_granted_total: expected {granted_total}, "
        f"got {event['extension_days_granted_total']}"
    )
    assert event["extension_days_remaining"] == remaining, (
        f"extension_days_remaining: expected {remaining}, "
        f"got {event['extension_days_remaining']}"
    )
    assert granted_total + remaining == 30, (
        "the two extension counters must always sum to the statutory 30 days"
    )
    assert (
        event["extension_days_granted_total"] + event["extension_days_remaining"] == 30
    ), "the two extension counters must always sum to the statutory 30 days"


# ─── Inspections (§3.9) ───────────────────────────────────────────────


def assert_penalty_exposure(
    inspection: Dict[str, Any],
    penalty_exposure_usd: Optional[float] = None,
    chronic_multiplier_applied: Optional[float] = None,
    capped: Optional[bool] = None,
) -> None:
    if penalty_exposure_usd is not None:
        assert_money(
            inspection["penalty_exposure_usd"], penalty_exposure_usd, "penalty_exposure_usd"
        )
    if chronic_multiplier_applied is not None:
        assert_money(
            inspection["chronic_multiplier_applied"],
            chronic_multiplier_applied,
            "chronic_multiplier_applied",
        )
    if capped is not None:
        assert inspection["capped"] is capped, (
            f"capped: expected {capped}, got {inspection['capped']}"
        )


def multiplier_for_posture(compliance_status: str) -> float:
    """The exposure multiplier a store's posture carries."""
    return {
        "COMPLIANT": MULTIPLIER_COMPLIANT,
        "AT_RISK": MULTIPLIER_AT_RISK,
        "NON_COMPLIANT": MULTIPLIER_NON_COMPLIANT,
    }[compliance_status]


# ─── Leak-rate projection (§3.4) ──────────────────────────────────────


def assert_projection(
    projection: Dict[str, Any],
    method: Optional[str] = None,
    leak_rate_pct: Optional[float] = None,
    refrigerant_added_lbs_in_window: Optional[float] = None,
    window_start: Optional[str] = None,
    window_end: Optional[str] = None,
    threshold_pct: Optional[float] = None,
    would_trigger_leak_event: Optional[bool] = None,
) -> None:
    if method is not None:
        assert projection["method"] == method, (
            f"method: expected {method}, got {projection['method']}"
        )
    if leak_rate_pct is not None:
        assert_mass(projection["leak_rate_pct"], leak_rate_pct, "leak_rate_pct")
    if refrigerant_added_lbs_in_window is not None:
        assert_mass(
            projection["refrigerant_added_lbs_in_window"],
            refrigerant_added_lbs_in_window,
            "refrigerant_added_lbs_in_window",
        )
    if window_start is not None:
        assert_instant(projection["window_start"], window_start, "window_start")
    if window_end is not None:
        assert_instant(projection["window_end"], window_end, "window_end")
    if threshold_pct is not None:
        assert_mass(projection["threshold_pct"], threshold_pct, "threshold_pct")
    if would_trigger_leak_event is not None:
        assert projection["would_trigger_leak_event"] is would_trigger_leak_event, (
            f"would_trigger_leak_event: expected {would_trigger_leak_event}, "
            f"got {projection['would_trigger_leak_event']}"
        )


# ─── Sweep report (§3.6) ──────────────────────────────────────────────


def assert_sweep_report(
    report: Dict[str, Any],
    repair_overdue: Optional[List[str]] = None,
    verification_overdue: Optional[List[str]] = None,
    expired_extensions: Optional[List[str]] = None,
    overdue_equipment: Optional[List[str]] = None,
    escalated_inspections: Optional[List[str]] = None,
    stores_recomputed_count: Optional[int] = None,
    as_of: Optional[str] = None,
) -> None:
    """Assert the five pinned collections the sweep returns, in their own keys."""
    pairs = (
        ("swept_repair_overdue_leak_event_ids", repair_overdue),
        ("swept_verification_overdue_leak_event_ids", verification_overdue),
        ("expired_extension_request_ids", expired_extensions),
        ("overdue_equipment_ids", overdue_equipment),
        ("escalated_inspection_ids", escalated_inspections),
    )
    for key, expected in pairs:
        assert key in report, f"the sweep report must carry {key}"
        if expected is not None:
            assert sorted(report[key]) == sorted(expected), (
                f"{key}: expected {sorted(expected)}, got {sorted(report[key])}"
            )
    if stores_recomputed_count is not None:
        assert report["stores_recomputed_count"] == stores_recomputed_count, (
            f"stores_recomputed_count: expected {stores_recomputed_count}, "
            f"got {report['stores_recomputed_count']}"
        )
    if as_of is not None:
        assert_instant(report["as_of"], as_of, "as_of")


# ─── Collections ──────────────────────────────────────────────────────


def ids_of(rows: Iterable[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]
