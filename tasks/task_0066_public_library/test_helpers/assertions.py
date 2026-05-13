"""Entity assertions and domain invariant checkers for the Public Library API.

Field names are taken verbatim from PRD §3. Each assert_<entity> verifies the
shape declared in PRD §3 (workflows) and §2.4 (common fields), nothing more —
extra fields the implementer chooses to include do not trip the assertions.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ─────────────────────────────────────────────────────────────
# Common-field assertions (PRD §2.4)
# ─────────────────────────────────────────────────────────────


def _assert_common_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: id (UUID), created_at (ISO 8601), updated_at (ISO 8601),
    version (integer starting at 1)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID: {data.get('id')}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601: {data.get('created_at')}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601: {data.get('updated_at')}"
    assert isinstance(data.get("version"), int), "version must be integer"
    assert data["version"] >= 1, "version begins at 1 per PRD §2.4"


def _assert_append_only_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: AuditLog carries only id and created_at — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID: {data.get('id')}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601: {data.get('created_at')}"


# ─────────────────────────────────────────────────────────────
# Per-entity assertions
# ─────────────────────────────────────────────────────────────


def assert_book_title(data: Dict[str, Any]) -> None:
    """PRD §3.1 BookTitle shape."""
    _assert_common_fields(data)
    assert isinstance(data["marc_control_number"], str) and 8 <= len(
        data["marc_control_number"]
    ) <= 20
    assert isinstance(data["isbn"], str) and len(data["isbn"]) == 13
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert isinstance(data["author"], str) and len(data["author"]) > 0
    assert isinstance(data["publisher"], str)
    assert isinstance(data["publication_year"], int)
    assert data["classification_scheme"] in ("DEWEY", "CLC")
    assert data["subject_category"] in ("GENERAL", "REFERENCE", "CHILDREN", "RARE")
    assert data["acquisition_source"] in (
        "PURCHASE",
        "DONATION",
        "EXCHANGE",
        "ILL_PURCHASE",
    )
    assert data["status"] in ("ACTIVE", "WITHDRAWN")
    assert isinstance(data["total_copies"], int) and data["total_copies"] >= 0
    assert isinstance(data["available_copies"], int) and data["available_copies"] >= 0
    assert data["available_copies"] <= data["total_copies"], (
        "PRD §3.1: available_copies counts AVAILABLE copies; cannot exceed total_copies"
    )


def assert_copy(data: Dict[str, Any]) -> None:
    """PRD §3.1 Copy shape."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("book_title_id", ""))
    assert isinstance(data["barcode"], str) and len(data["barcode"]) > 0
    assert isinstance(data["location_code"], str)
    assert data["acquisition_source"] in (
        "PURCHASE",
        "DONATION",
        "EXCHANGE",
        "ILL_PURCHASE",
    )
    assert is_iso8601_timestamp(data.get("acquired_at", ""))
    assert data["status"] in (
        "AVAILABLE",
        "ON_LOAN",
        "RESERVED",
        "IN_TRANSIT_ILL",
        "WEEDED",
    )


def assert_reader(data: Dict[str, Any]) -> None:
    """PRD §3.2 Reader shape."""
    _assert_common_fields(data)
    assert isinstance(data["national_id_hash"], str) and len(data["national_id_hash"]) == 64
    assert isinstance(data["full_name"], str)
    assert isinstance(data["identity_verified"], bool)
    if data["identity_verified"]:
        assert data.get("identity_verified_at") is not None
        assert is_iso8601_timestamp(data["identity_verified_at"])
    assert data["status"] in ("NORMAL", "OVERDUE", "BLACKLISTED")
    assert isinstance(data["active_loan_count"], int) and data["active_loan_count"] >= 0
    assert (
        isinstance(data["unpaid_fine_cents"], int) and data["unpaid_fine_cents"] >= 0
    )


def assert_card(data: Dict[str, Any]) -> None:
    """PRD §3.2 Card shape."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("reader_id", ""))
    assert isinstance(data["card_number"], str) and data["card_number"].startswith(
        "LIB-"
    ), f"PRD §3.2: card_number must follow LIB-YYYY-NNNNNN format; got {data['card_number']}"
    assert data["card_type"] in ("REGULAR", "STUDENT", "SENIOR", "TEMPORARY")
    assert isinstance(data["max_loans"], int) and data["max_loans"] >= 0
    assert isinstance(data["loan_duration_days"], int) and data["loan_duration_days"] > 0
    assert isinstance(data["max_renewals"], int) and data["max_renewals"] >= 0
    assert is_iso8601_timestamp(data.get("valid_from", ""))
    assert is_iso8601_timestamp(data.get("valid_until", ""))
    assert data["status"] in ("ACTIVE", "FROZEN", "REISSUED", "EXPIRED")


def assert_loan(data: Dict[str, Any]) -> None:
    """PRD §3.3 Loan shape."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("copy_id", ""))
    assert is_valid_uuid(data.get("card_id", ""))
    assert is_valid_uuid(data.get("reader_id", ""))
    assert is_iso8601_timestamp(data.get("borrowed_at", ""))
    assert is_iso8601_timestamp(data.get("due_at", ""))
    assert isinstance(data["renewals_used"], int) and data["renewals_used"] >= 0
    assert isinstance(data["is_recalled"], bool)
    assert data["channel"] in ("COUNTER", "KIOSK")
    assert data["status"] in (
        "BORROWED",
        "RENEWED",
        "RECALL_PENDING",
        "RETURNED",
        "OVERDUE_CLOSED",
    )


def assert_reservation(data: Dict[str, Any]) -> None:
    """PRD §3.5 Reservation shape."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("book_title_id", ""))
    assert is_valid_uuid(data.get("card_id", ""))
    assert is_valid_uuid(data.get("reader_id", ""))
    assert data["channel"] in ("ONLINE", "ON_SITE")
    assert isinstance(data["queue_position"], int) and data["queue_position"] >= 1, (
        "PRD §3.5: queue_position is 1-indexed"
    )
    assert data["status"] in (
        "QUEUED",
        "READY_FOR_PICKUP",
        "FULFILLED",
        "EXPIRED",
        "CANCELLED",
    )


def assert_fine(data: Dict[str, Any]) -> None:
    """PRD §3.6 Fine shape."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("loan_id", ""))
    assert is_valid_uuid(data.get("reader_id", ""))
    assert data["subject_category"] in ("GENERAL", "REFERENCE", "CHILDREN", "RARE")
    assert isinstance(data["daily_rate_cents"], int) and data["daily_rate_cents"] > 0
    assert isinstance(data["fine_cap_cents"], int) and data["fine_cap_cents"] > 0
    assert isinstance(data["accrued_cents"], int) and data["accrued_cents"] >= 0
    assert isinstance(data["waived_cents"], int) and data["waived_cents"] >= 0
    assert isinstance(data["paid_cents"], int) and data["paid_cents"] >= 0
    assert (
        isinstance(data["outstanding_cents"], int) and data["outstanding_cents"] >= 0
    )
    assert data["settlement_status"] in ("PENDING", "SETTLED")
    # Conserved-quantity invariant per PRD §3.6:
    # outstanding_cents = accrued_cents - waived_cents - paid_cents
    assert (
        data["outstanding_cents"]
        == data["accrued_cents"] - data["waived_cents"] - data["paid_cents"]
    ), (
        "PRD §3.6: outstanding_cents must equal accrued_cents - waived_cents - paid_cents"
    )
    assert data["accrued_cents"] <= data["fine_cap_cents"], (
        "PRD §3.6: accrued_cents is capped at fine_cap_cents"
    )


def assert_ill_request(data: Dict[str, Any]) -> None:
    """PRD §3.7 ILLRequest shape."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("reader_id", ""))
    assert is_valid_uuid(data.get("card_id", ""))
    assert data["partner_library_code"] in ("PL_A", "PL_B", "PL_C")
    assert isinstance(data["target_marc_control_number"], str)
    assert isinstance(data["shipping_cost_cents"], int) and data["shipping_cost_cents"] >= 0
    assert isinstance(data["handling_fee_cents"], int) and data["handling_fee_cents"] >= 0
    assert (
        isinstance(data["settlement_total_cents"], int)
        and data["settlement_total_cents"] >= 0
    )
    assert data["status"] in (
        "SUBMITTED",
        "APPROVED",
        "REJECTED",
        "IN_TRANSIT",
        "AT_PARTNER",
        "RETURNED_TRANSIT",
        "SETTLED",
    )


def assert_acquisition_suggestion(data: Dict[str, Any]) -> None:
    """PRD §3.8 AcquisitionSuggestion shape."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("reader_id", ""))
    assert is_valid_uuid(data.get("card_id", ""))
    assert isinstance(data["suggested_isbn"], str) and len(data["suggested_isbn"]) == 13
    assert isinstance(data["suggested_title"], str)
    assert isinstance(data["rationale"], str)
    assert data["status"] in (
        "SUBMITTED",
        "UNDER_REVIEW",
        "ACQUIRED",
        "DECLINED",
        "DEFERRED",
    )


def assert_audit_log(data: Dict[str, Any]) -> None:
    """PRD §2.8 AuditLog shape. Append-only — only id and created_at per §2.4."""
    _assert_append_only_fields(data)
    assert data["event_type"] in (
        "LOAN_CREATED",
        "LOAN_RENEWED",
        "LOAN_RECALLED",
        "LOAN_RETURNED",
        "FINE_ACCRUED",
        "FINE_WAIVED",
        "FINE_PAID",
        "RESERVATION_CREATED",
        "RESERVATION_FULFILLED",
    ), f"PRD §2.8: event_type must be one of the catalogued strings; got {data.get('event_type')}"
    assert isinstance(data["subject_type"], str)
    assert isinstance(data["subject_id"], str)
    assert isinstance(data["actor_role"], str)
    assert is_iso8601_timestamp(data.get("occurred_at", ""))


# ─────────────────────────────────────────────────────────────
# Domain invariants
# ─────────────────────────────────────────────────────────────


def assert_fine_conserved(fine: Dict[str, Any]) -> None:
    """PRD §3.6: outstanding_cents == accrued_cents - waived_cents - paid_cents
    at every observable state; on SETTLED, outstanding_cents == 0 AND
    accrued_cents == waived_cents + paid_cents EXACTLY.
    """
    assert (
        fine["outstanding_cents"]
        == fine["accrued_cents"] - fine["waived_cents"] - fine["paid_cents"]
    )
    if fine["settlement_status"] == "SETTLED":
        assert fine["outstanding_cents"] == 0
        assert fine["accrued_cents"] == fine["waived_cents"] + fine["paid_cents"]


def assert_no_fine_above_cap(fine: Dict[str, Any]) -> None:
    """PRD §3.6: 'the reported provisional value is the smaller of that raw amount
    and fine_cap_cents' / 'Fine.accrued_cents is set to the smaller of that raw
    amount and fine_cap_cents'."""
    assert fine["accrued_cents"] <= fine["fine_cap_cents"]


def assert_version_increased(after: Dict[str, Any], before_version: int) -> None:
    """PRD §2.4: version increments by 1 on every persisted mutation. Strictly
    greater is sufficient evidence the system minted a new version row."""
    assert isinstance(after.get("version"), int)
    assert after["version"] > before_version, (
        f"PRD §2.4: version must increment after a mutation; was {before_version}, "
        f"now {after['version']}"
    )


def round_half_up(value: float) -> int:
    """Half-up rounding to whole units. PRD §2.10: 'an amount of 0.5 cents rounds
    up to 1'. Helper for tests that need to predict the ILL settlement number."""
    import math

    if value >= 0:
        return int(math.floor(value + 0.5))
    return int(-math.floor(-value + 0.5))


def expected_ill_settlement_total(shipping_cost_cents: int, handling_fee_cents: int = 300) -> int:
    """PRD §3.7: per-leg = round_half_up(shipping + handling + insurance) where
    insurance = round_half_up(shipping * 2.50%). Total = leg + leg (round-per-leg
    BEFORE summation)."""
    insurance = round_half_up(shipping_cost_cents * 250 / 10000)
    per_leg = round_half_up(shipping_cost_cents + handling_fee_cents + insurance)
    return per_leg + per_leg
