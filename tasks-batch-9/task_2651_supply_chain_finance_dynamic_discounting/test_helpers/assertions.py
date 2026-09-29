"""Domain assertion helpers.

These wrap the generic structural helpers from the framework and add the
shape rules this contract states: which entities carry the mutable common-field
quartet, which carry only ``id`` and ``created_at``, how percentages are
formatted, and the two conserved quantities.
"""

from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    APPEND_ONLY_ENTITIES,  # noqa: F401  (documented surface)
)


# ─── Common-field shape ───────────────────────────────
def assert_mutable_common_fields(row: Dict[str, Any]) -> None:
    """A version-tracked row carries id, created_at, updated_at and version."""
    assert is_valid_uuid(row["id"]), "id must be a UUID, got {!r}".format(row.get("id"))
    assert not str(row["id"]).startswith(
        ("buyer_", "prog_", "inv_", "off_", "ep_", "fnd_")
    ), "identifiers carry no type prefix: {!r}".format(row["id"])
    assert is_iso8601_timestamp(row["created_at"]), (
        "created_at must be ISO 8601 UTC, got {!r}".format(row.get("created_at"))
    )
    assert "updated_at" in row, "a version-tracked row must expose updated_at"
    assert is_iso8601_timestamp(row["updated_at"]), (
        "updated_at must be ISO 8601 UTC, got {!r}".format(row.get("updated_at"))
    )
    assert isinstance(row.get("version"), int), "version must be an integer"
    assert row["version"] >= 1, "version starts at 1, got {}".format(row.get("version"))


def assert_append_only_common_fields(row: Dict[str, Any]) -> None:
    """An append-only audit row carries ONLY id and created_at: no updated_at
    and no version."""
    assert is_valid_uuid(row["id"]), "id must be a UUID, got {!r}".format(row.get("id"))
    assert is_iso8601_timestamp(row["created_at"]), (
        "created_at must be ISO 8601 UTC, got {!r}".format(row.get("created_at"))
    )
    assert "updated_at" not in row, (
        "an append-only row must not expose updated_at, got {!r}".format(
            row.get("updated_at")
        )
    )
    assert "version" not in row, (
        "an append-only row must not expose version, got {!r}".format(row.get("version"))
    )


# ─── Envelope ─────────────────────────────────────────
def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """meta.api_request_id starts with req_ and the timestamp is ISO 8601 UTC
    with exactly three fractional-second digits."""
    meta = body["meta"]
    request_id = meta["api_request_id"]
    assert request_id.startswith("req_"), (
        "api_request_id must start with 'req_', got {!r}".format(request_id)
    )
    assert len(request_id) > len("req_"), "api_request_id carries no unique part"
    timestamp = meta["api_request_timestamp"]
    assert is_iso8601_timestamp(timestamp), (
        "api_request_timestamp must be ISO 8601 UTC, got {!r}".format(timestamp)
    )
    assert timestamp.endswith("Z"), "timestamps are UTC and end in Z"
    assert "." in timestamp and len(timestamp.split(".")[1]) == 4, (
        "timestamp must carry exactly three fractional digits, got {!r}".format(
            timestamp
        )
    )


def assert_pagination_meta(
    meta: Dict[str, Any],
    expected_limit: int,
    expected_offset: int,
    expected_total: Optional[int] = None,
    expected_has_more: Optional[bool] = None,
) -> None:
    assert meta["limit"] == expected_limit, (
        "meta.limit should echo {}, got {}".format(expected_limit, meta["limit"])
    )
    assert meta["offset"] == expected_offset, (
        "meta.offset should echo {}, got {}".format(expected_offset, meta["offset"])
    )
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            "meta.total_count should be {}, got {}".format(
                expected_total, meta["total_count"]
            )
        )
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more, (
            "meta.has_more should be {}, got {}".format(
                expected_has_more, meta["has_more"]
            )
        )


def assert_created_at_ascending(rows: List[Dict[str, Any]]) -> None:
    """Collections are ordered by created_at ascending, never by id."""
    stamps = [r["created_at"] for r in rows]
    assert stamps == sorted(stamps), (
        "rows must be ordered by created_at ascending, got {}".format(stamps)
    )


# ─── Percentages and money ────────────────────────────
def assert_two_decimal_percentage(value: Any, expected: Optional[float] = None) -> None:
    """Percentages are numbers carrying exactly two decimal places."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        "a percentage must be numeric, got {!r}".format(value)
    )
    quantised = round(float(value) * 100)
    assert abs(float(value) * 100 - quantised) < 1e-6, (
        "percentage {!r} carries more than two decimal places".format(value)
    )
    if expected is not None:
        assert abs(float(value) - expected) < 1e-9, (
            "percentage should be {}, got {}".format(expected, value)
        )


def assert_integer_cents(value: Any, field: str = "amount") -> None:
    assert isinstance(value, int) and not isinstance(value, bool), (
        "{} must be integer cents, got {!r}".format(field, value)
    )


# ─── Conserved quantities ─────────────────────────────
def assert_invoice_face_conserved(invoice: Dict[str, Any]) -> None:
    """face_amount_cents == face_covered_cents + remaining_face_cents."""
    face = invoice["face_amount_cents"]
    covered = invoice["face_covered_cents"]
    remaining = invoice["remaining_face_cents"]
    assert covered + remaining == face, (
        "invoice face is not conserved: covered {} + remaining {} != face {}".format(
            covered, remaining, face
        )
    )


def assert_funder_capital_conserved(funder: Dict[str, Any], committed_cents: int) -> None:
    """available_capital_cents + encumbered_capital_cents == committed_at(clock)."""
    available = funder["available_capital_cents"]
    encumbered = funder["encumbered_capital_cents"]
    assert available + encumbered == committed_cents, (
        "funder capital is not conserved: available {} + encumbered {} != committed {}".format(
            available, encumbered, committed_cents
        )
    )


# ─── Entity-shaped assertions ─────────────────────────
def assert_buyer(row: Dict[str, Any], **expected: Any) -> None:
    assert_mutable_common_fields(row)
    for key, value in expected.items():
        assert row[key] == value, "Buyer.{} should be {!r}, got {!r}".format(
            key, value, row.get(key)
        )


def assert_program(row: Dict[str, Any], **expected: Any) -> None:
    assert_mutable_common_fields(row)
    assert_two_decimal_percentage(row["concentration_cap_pct"])
    assert_two_decimal_percentage(row["adoption_rate_pct"])
    for key, value in expected.items():
        assert row[key] == value, "BuyerProgram.{} should be {!r}, got {!r}".format(
            key, value, row.get(key)
        )


def assert_invoice(row: Dict[str, Any], **expected: Any) -> None:
    assert_mutable_common_fields(row)
    assert_invoice_face_conserved(row)
    for key, value in expected.items():
        assert row[key] == value, "Invoice.{} should be {!r}, got {!r}".format(
            key, value, row.get(key)
        )


def assert_offer(row: Dict[str, Any], **expected: Any) -> None:
    assert_mutable_common_fields(row)
    for key, value in expected.items():
        assert row[key] == value, "DiscountOffer.{} should be {!r}, got {!r}".format(
            key, value, row.get(key)
        )


def assert_payment(row: Dict[str, Any], **expected: Any) -> None:
    assert_mutable_common_fields(row)
    for key, value in expected.items():
        assert row[key] == value, "EarlyPayment.{} should be {!r}, got {!r}".format(
            key, value, row.get(key)
        )


def assert_payment_axes(
    row: Dict[str, Any],
    funding_status: Optional[str] = None,
    settlement_status: Optional[str] = None,
    accounting_status: Optional[str] = None,
) -> None:
    """Assert only the three parallel state axes, leaving the rest untouched."""
    if funding_status is not None:
        assert row["funding_status"] == funding_status, (
            "funding_status should be {}, got {}".format(
                funding_status, row["funding_status"]
            )
        )
    if settlement_status is not None:
        assert row["settlement_status"] == settlement_status, (
            "settlement_status should be {}, got {}".format(
                settlement_status, row["settlement_status"]
            )
        )
    if accounting_status is not None:
        assert row["accounting_status"] == accounting_status, (
            "accounting_status should be {}, got {}".format(
                accounting_status, row["accounting_status"]
            )
        )


def assert_cash_breakdown(
    row: Dict[str, Any],
    days_early: Optional[int] = None,
    discount_amount_cents: Optional[int] = None,
    funder_fee_cents: Optional[int] = None,
    net_payment_cents: Optional[int] = None,
    check_identity: bool = True,
) -> None:
    """Assert the four cash figures and, when ``check_identity`` is left on,
    that net == face_covered - discount - fee."""
    for field in ("discount_amount_cents", "funder_fee_cents", "net_payment_cents"):
        assert_integer_cents(row[field], field)
    if days_early is not None:
        assert row["days_early"] == days_early, "days_early should be {}, got {}".format(
            days_early, row["days_early"]
        )
    if discount_amount_cents is not None:
        assert row["discount_amount_cents"] == discount_amount_cents, (
            "discount_amount_cents should be {}, got {}".format(
                discount_amount_cents, row["discount_amount_cents"]
            )
        )
    if funder_fee_cents is not None:
        assert row["funder_fee_cents"] == funder_fee_cents, (
            "funder_fee_cents should be {}, got {}".format(
                funder_fee_cents, row["funder_fee_cents"]
            )
        )
    if net_payment_cents is not None:
        assert row["net_payment_cents"] == net_payment_cents, (
            "net_payment_cents should be {}, got {}".format(
                net_payment_cents, row["net_payment_cents"]
            )
        )
    if not check_identity:
        return
    assert (
        row["face_covered_cents"]
        - row["discount_amount_cents"]
        - row["funder_fee_cents"]
        == row["net_payment_cents"]
    ), "net must equal face - discount - fee, got {} - {} - {} != {}".format(
        row["face_covered_cents"],
        row["discount_amount_cents"],
        row["funder_fee_cents"],
        row["net_payment_cents"],
    )


def assert_supplier_axes(
    row: Dict[str, Any],
    onboarding_status: Optional[str] = None,
    idv_status: Optional[str] = None,
    bank_status: Optional[str] = None,
) -> None:
    if onboarding_status is not None:
        assert row["onboarding_status"] == onboarding_status, (
            "onboarding_status should be {}, got {}".format(
                onboarding_status, row["onboarding_status"]
            )
        )
    if idv_status is not None:
        assert row["idv_status"] == idv_status, "idv_status should be {}, got {}".format(
            idv_status, row["idv_status"]
        )
    if bank_status is not None:
        assert row["bank_status"] == bank_status, (
            "bank_status should be {}, got {}".format(bank_status, row["bank_status"])
        )


def assert_analytics(view: Dict[str, Any], **expected: Any) -> None:
    """Assert the programme analytics read model, checking that both
    concentration bases and the adoption rate are 2-decimal percentages."""
    for field in (
        "adoption_rate_pct",
        "concentration_top_supplier_face_pct",
        "concentration_top_supplier_funded_pct",
        "concentration_cap_pct",
    ):
        assert field in view, "analytics must expose {}".format(field)
        assert_two_decimal_percentage(view[field])
    for key, value in expected.items():
        actual = view.get(key)
        if isinstance(value, float):
            assert abs(float(actual) - value) < 1e-9, (
                "analytics.{} should be {}, got {}".format(key, value, actual)
            )
        else:
            assert actual == value, "analytics.{} should be {!r}, got {!r}".format(
                key, value, actual
            )


def ids_of(rows: Iterable[Dict[str, Any]]) -> List[str]:
    return [r["id"] for r in rows]
